"""Temperature surveillance, excursion severity, assessment outcomes, and the
stability budget (PRD §2.4, §2.5, §2.11, §3.4)."""
from datetime import datetime, timezone

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId,
    create_study, create_site, create_staff_member,
    setup_pharmacy, setup_two_reading_both_sides_excursion, setup_open_excursion,
    setup_randomized_subject, assess_excursion, post_temperature_log, set_clock,
    get_kit, get_lot, create_temperature_log_payload,
    ship_kits, receive_kit_in_range,
)
from test_helpers import TEST_USERS, make_pharmacist_headers

SPONSOR = TEST_USERS["sponsor_admin_headers"]


def test_temperature_log_system_timestamp_uses_default_logical_clock():
    """PRD §2.5: "At server startup the logical clock reads exactly
    `2026-08-01T00:00:00Z`." PRD §3.4: "the server stamps `recorded_at` from the
    logical clock." PRD §3.4: "A reading inside every stored lot's range at that
    site is a quiet event: the log's `excursion_id` remains null."

    Design: Corner/entities/temperature_log_system_timestamp_uses_default_logical_clock
    """
    study = create_study(protocol_number="P-COR-2", phase="PHASE_I",
                       blinding_model="OPEN_LABEL", max_dose_per_visit_mg=100)
    site = create_site(study["id"])
    pharmacist = create_staff_member(site["id"], license_number="L-COR-2", full_name="P")
    resp = api_client.create_temperature_log(
        create_temperature_log_payload(site["id"], 5.0, source="MANUAL"),
        make_pharmacist_headers(pharmacist["id"]))
    data = validate_success(resp, expected_status=201)
    recorded = datetime.fromisoformat(data["recorded_at"].replace("Z", "+00:00"))
    assert recorded == datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc), (
        f"recorded_at must equal the startup logical clock, got {data['recorded_at']}"
    )
    assert data["excursion_id"] is None, "no lot stored at the site means no range to breach"


def test_temperature_log_is_append_only_without_version():
    """PRD §2.4: "One deliberate exception exists: a temperature log entry is an
    immutable observation and carries only `id` and `created_at`. Both
    `updated_at` and `version` are absent from temperature log resources; the
    moment of observation is instead recorded in the server-stamped
    `recorded_at` field, which is never client-supplied."

    Design: Corner/entities/temperature_log_is_append_only_without_version
    """
    study = create_study(protocol_number="P-COR-5", phase="PHASE_I",
                       blinding_model="OPEN_LABEL", max_dose_per_visit_mg=100)
    site = create_site(study["id"])
    pharmacist = create_staff_member(site["id"], license_number="L-COR-5", full_name="P")
    log = get_success_data(api_client.create_temperature_log(
        create_temperature_log_payload(site["id"], 5.0, source="MANUAL"),
        make_pharmacist_headers(pharmacist["id"])))
    data = validate_success(api_client.get_temperature_log(log["id"], SPONSOR))
    assert "id" in data and "created_at" in data
    assert "version" not in data, "temperature log must not carry a version key"
    assert "updated_at" not in data, "temperature log must not carry an updated_at key"


def test_excursion_assess_after_resolution_returns_already_resolved():
    """PRD §3.4: "Assessing an excursion that is no longer `OPEN` — other than
    the void-from-acceptable path — is rejected with
    `ERR_EXCURSION_ALREADY_RESOLVED`."

    Design: Corner/state_machines/excursion_assess_after_resolution_returns_already_resolved
    """
    world = setup_pharmacy(protocol_number="P-SM-5", kit_numbers=("K-EX",),
                           pharmacist_license="L-SM-5")
    exc = setup_open_excursion(world, readings=((9.0, None),), source="MANUAL")
    assess_excursion(exc["excursion_id"], "ACCEPTABLE", rationale="QA")
    resp = api_client.assess_temperature_excursion(
        exc["excursion_id"], {"outcome": "UNACCEPTABLE", "resolution_rationale": "late QA override"},
        SPONSOR)
    validate_error(resp, ApiErrorId.ERR_EXCURSION_ALREADY_RESOLVED.value, expected_status=409)
    excursion = get_success_data(api_client.get_temperature_excursion(exc["excursion_id"], SPONSOR))
    assert excursion["status"] == "RESOLVED_ACCEPTABLE"


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / excursion_severity_minutes_nested_multiplier
# ---------------------------------------------------------------------------

def test_excursion_severity_charged_once_per_distinct_lot():
    """PRD §3.4: "Sixth, `severity_minutes_charged` is the capped duration
    multiplied by the side multiplier, multiplied again by the degree band." and
    "`ACCEPTABLE` moves the excursion `OPEN` → `RESOLVED_ACCEPTABLE`. The server
    computes the excursion's severity (below), records it as
    `severity_minutes_charged`, and charges it to the stability budget of every
    distinct lot owning a kit linked to the excursion or quarantined by it —
    each such lot's `stability_minutes_consumed` increases by
    `severity_minutes_charged`."

    Window 100 min, both sides breached, peak deviation 1.5 -> band 1:
    severity = min(100, 1440) x 4 x 1 = 400.

    Design: Difficulty/combinatorial_formula/excursion_severity_minutes_nested_multiplier
    """
    world = setup_two_reading_both_sides_excursion(protocol_number="P-SEV-1",
                                                   kit_numbers=("K-E1", "K-E2"))
    assessed = assess_excursion(world["excursion_id"], "ACCEPTABLE",
                                rationale="Sponsor QA: product stable")
    assert assessed["status"] == "RESOLVED_ACCEPTABLE"
    assert assessed["severity_minutes_charged"] == 400, (
        f"expected severity 400 = 100 min x 4 (both sides) x 1 (band), "
        f"got {assessed['severity_minutes_charged']}"
    )
    lot = get_lot(world["lot"]["id"])
    assert lot["stability_minutes_consumed"] == 400, (
        "severity charged once per distinct lot (not per kit)"
    )
    # 400 < 600 budget: both kits restore to AVAILABLE.
    for kit in world["kits"]:
        after = get_kit(kit["id"])
        assert after["status"] == "AVAILABLE"
        assert after["excursion_id"] is None


def test_second_out_of_range_reading_extends_same_open_excursion():
    """PRD §3.4: "It opens a new `OPEN` temperature excursion for the site — or
    extends the site's existing `OPEN` excursion — and cascades: every kit at
    that site in `AVAILABLE` or `ALLOCATED` whose lot's range is violated by the
    reading moves to `QUARANTINED_EXCURSION`".

    Design: Difficulty/combinatorial_formula/excursion_severity_minutes_nested_multiplier
    """
    world = setup_two_reading_both_sides_excursion(protocol_number="P-SEV-1B",
                                                   kit_numbers=("K-E1", "K-E2"))
    log1, log2 = world["logs"]
    assert log1["excursion_id"] is not None
    assert log2["excursion_id"] == log1["excursion_id"], (
        "the second out-of-range reading must extend the site's existing OPEN excursion"
    )
    # Both kits were quarantined by the cascade before assessment.
    for kit in world["kits"]:
        assert get_kit(kit["id"])["status"] == "QUARANTINED_EXCURSION"
    excursion = get_success_data(
        api_client.get_temperature_excursion(world["excursion_id"], SPONSOR))
    start = datetime.fromisoformat(excursion["window_start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(excursion["window_end"].replace("Z", "+00:00"))
    assert (end - start).total_seconds() == 100 * 60, "window spans the two readings"
    assert excursion["min_observed_celsius"] == 1.0
    assert excursion["max_observed_celsius"] == 9.5


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / kit_quarantine_release_cycle_restores_prior_state
# ---------------------------------------------------------------------------

def _world_with_quarantined_available_and_allocated_kits():
    """K-C1 AVAILABLE and K-C2 ALLOCATED to a randomized subject; one 9.0
    reading quarantines both."""
    world = setup_pharmacy(protocol_number="P-CYC-1", kit_numbers=("K-C1", "K-C2"),
                           pharmacist_license="L-CYC-1")
    setup_randomized_subject(world, subject_number="SUB-C", slot_kit_numbers=["K-C2"])
    exc = setup_open_excursion(world, readings=((9.0, None),), source="MANUAL")
    return {**world, **exc}


def test_quarantine_cycle_records_pre_quarantine_status():
    """PRD §3.4: "every kit at that site in `AVAILABLE` or `ALLOCATED` whose
    lot's range is violated by the reading moves to `QUARANTINED_EXCURSION`,
    recording its `pre_quarantine_status` (`AVAILABLE` or `ALLOCATED`; an
    allocated kit's subject allocation is preserved through the excursion) and
    linking `excursion_id` to the excursion."

    Design: Difficulty/non_linear_state_machine/kit_quarantine_release_cycle_restores_prior_state
    """
    world = _world_with_quarantined_available_and_allocated_kits()
    kits = {k["kit_number"]: get_kit(k["id"]) for k in world["kits"]}
    assert kits["K-C1"]["status"] == "QUARANTINED_EXCURSION"
    assert kits["K-C1"]["pre_quarantine_status"] == "AVAILABLE"
    assert kits["K-C1"]["excursion_id"] == world["excursion_id"]
    assert kits["K-C2"]["status"] == "QUARANTINED_EXCURSION"
    assert kits["K-C2"]["pre_quarantine_status"] == "ALLOCATED"


def test_acceptable_assessment_restores_each_kit_to_its_prior_state():
    """PRD §3.4: "Linked kits then restore according to their
    `pre_quarantine_status`: `AVAILABLE` kits return to `AVAILABLE`, `ALLOCATED`
    kits return to `ALLOCATED` with their `allocated_subject_id` retained, and
    receipt-excursion kits return to `QUARANTINED_RECEIPT`; restored kits clear
    `excursion_id` and `pre_quarantine_status`."

    Design: Difficulty/non_linear_state_machine/kit_quarantine_release_cycle_restores_prior_state
    """
    world = _world_with_quarantined_available_and_allocated_kits()
    subject_id = get_kit([k for k in world["kits"] if k["kit_number"] == "K-C2"][0]["id"])["allocated_subject_id"]
    assessed = assess_excursion(world["excursion_id"], "ACCEPTABLE", rationale="QA release")
    # Single reading -> zero-length window -> severity 0 -> no budget pressure.
    assert assessed["severity_minutes_charged"] == 0
    kits = {k["kit_number"]: get_kit(k["id"]) for k in world["kits"]}
    assert kits["K-C1"]["status"] == "AVAILABLE"
    assert kits["K-C1"]["excursion_id"] is None
    assert kits["K-C1"]["pre_quarantine_status"] is None
    assert kits["K-C2"]["status"] == "ALLOCATED"
    assert kits["K-C2"]["allocated_subject_id"] == subject_id
    assert kits["K-C2"]["excursion_id"] is None
    assert kits["K-C2"]["pre_quarantine_status"] is None


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / excursion_unacceptable_cascades_to_lot_depletion_and_resupply
# ---------------------------------------------------------------------------

def _world_with_unacceptable_assessment():
    """Two released kits of one lot quarantined by a 9.0 reading, then the
    excursion assessed UNACCEPTABLE."""
    world = setup_pharmacy(protocol_number="P-CAS-1", kit_numbers=("K-D1", "K-D2"),
                           pharmacist_license="L-CAS-1",
                           lot_overrides={"lot_number": "LOT-CAS-1"})
    exc = setup_open_excursion(world, readings=((9.0, None),))
    assess_excursion(exc["excursion_id"], "UNACCEPTABLE",
                     rationale="QA: product compromised")
    return world


def test_unacceptable_assessment_quarantines_kits_to_destruction_and_depletes_lot():
    """PRD §3.4: "every linked kit moves from `QUARANTINED_EXCURSION` to
    `DESTRUCTION_PENDING`, clearing `pre_quarantine_status` while `excursion_id`
    is retained for audit. Each affected lot then recomputes its usable count;
    a lot falling to zero flips from `ACTIVE` to `DEPLETED` and triggers the
    automatic resupply described in §3.2."

    Design: Difficulty/transitive_cascade/excursion_unacceptable_cascades_to_lot_depletion_and_resupply
    """
    world = _world_with_unacceptable_assessment()
    for kit in world["kits"]:
        after = get_kit(kit["id"])
        assert after["status"] == "DESTRUCTION_PENDING", (
            f"{after['kit_number']} should be DESTRUCTION_PENDING, got {after['status']}"
        )
    assert get_lot(world["lot"]["id"])["status"] == "DEPLETED"


def test_unacceptable_assessment_autocreates_numbered_resupply_kits():
    """PRD §3.2: "if the lot's study is `ACTIVE` and the affected site is
    `ACTIVE`, the server automatically creates a resupply: replacement kits in
    `IN_TRANSIT` for that lot at that site, equal in count to the number of kits
    that just left usable states in the triggering mutation, numbered `RS-`
    followed by the `lot_number`, a dash, and a 1-based running sequence number
    counting every resupply kit ever created for the lot."

    Design: Difficulty/transitive_cascade/excursion_unacceptable_cascades_to_lot_depletion_and_resupply
    """
    world = _world_with_unacceptable_assessment()
    resp = api_client.list_kits(SPONSOR, params={"lot_id": world["lot"]["id"],
                                                 "status": "IN_TRANSIT"})
    data, meta = validate_paginated(resp)
    numbers = sorted(k["kit_number"] for k in data)
    assert numbers == ["RS-LOT-CAS-1-1", "RS-LOT-CAS-1-2"], (
        f"expected exactly two resupply kits RS-LOT-CAS-1-1/-2, got {numbers}"
    )
    for kit in data:
        assert kit["site_id"] == world["site"]["id"]


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / temperature_reading_exactly_at_minimum_stays_in_range
# ---------------------------------------------------------------------------

def test_temperature_reading_exactly_at_minimum_stays_in_range():
    """PRD §2.11: "Every drug lot declares an inclusive storage-temperature
    range bounded by `storage_temp_min_celsius` and `storage_temp_max_celsius`;
    a reading exactly equal to either bound is in range."

    Design: Difficulty/boundary_precision_check/temperature_reading_exactly_at_minimum_stays_in_range
    """
    world = setup_pharmacy(protocol_number="P-BND-1", kit_numbers=("K-T",),
                           pharmacist_license="L-BND-1")
    kit = world["kits"][0]
    log = post_temperature_log(world["site"]["id"], 2.0, world["pharmacist"]["id"])
    assert log["excursion_id"] is None, (
        "a reading exactly equal to storage_temp_min_celsius (2.0) is in range"
    )
    assert get_kit(kit["id"])["status"] == "AVAILABLE"


def test_temperature_reading_one_tick_below_minimum_opens_excursion():
    """PRD §3.4: "A reading that falls outside the inclusive storage range of
    any lot with kits stored at the site is an excursion event. It opens a new
    `OPEN` temperature excursion for the site — or extends the site's existing
    `OPEN` excursion — and cascades".

    Design: Difficulty/boundary_precision_check/temperature_reading_exactly_at_minimum_stays_in_range
    """
    world = setup_pharmacy(protocol_number="P-BND-1B", kit_numbers=("K-T",),
                           pharmacist_license="L-BND-1")
    kit = world["kits"][0]
    log = post_temperature_log(world["site"]["id"], 1.9, world["pharmacist"]["id"])
    assert log["excursion_id"] is not None, "1.9 is below the inclusive minimum"
    assert get_kit(kit["id"])["status"] == "QUARANTINED_EXCURSION"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / stability_budget_exactly_consumed_blocks_release
# ---------------------------------------------------------------------------

def _world_with_budget_exactly_consumed():
    """Lot budget 400; a 100-minute both-sides excursion assessed ACCEPTABLE
    charges exactly 400 (== budget). K-S2 is shipped but kept IN_TRANSIT through
    the excursion and assessment, then received in range — landing in
    QUARANTINED_RECEIPT with the lot already stability-exhausted, so a release
    attempt reaches the stability gate of PRD §3.3."""
    world = setup_pharmacy(protocol_number="P-BND-2", kit_numbers=("K-S1",),
                           pharmacist_license="L-BND-2",
                           lot_overrides={"stability_budget_minutes": 400})
    k2 = ship_kits(world["lot"]["id"], world["site"]["id"], ["K-S2"])[0]
    exc = setup_open_excursion(world, readings=((9.5, None), (1.0, "2026-08-01T01:40:00Z")))
    assess_excursion(exc["excursion_id"], "ACCEPTABLE", rationale="QA")
    k2 = receive_kit_in_range(k2["id"], world["pharmacist"]["id"])
    return {**world, **exc, "kits": [world["kits"][0], k2]}


def test_stability_budget_exactly_consumed_blocks_release():
    """PRD §2.11: "A lot is stability-exhausted once its
    `stability_minutes_consumed` reaches or exceeds its
    `stability_budget_minutes`, and exhaustion permanently bars release of its
    receipt-quarantined kits and restoration of its excursion-quarantined
    kits." PRD §3.3: "the lot's `stability_minutes_consumed` must still be
    strictly below its `stability_budget_minutes`, else
    `ERR_LOT_STABILITY_EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/stability_budget_exactly_consumed_blocks_release
    """
    world = _world_with_budget_exactly_consumed()
    lot = get_lot(world["lot"]["id"])
    assert lot["stability_minutes_consumed"] == 400
    assert lot["stability_minutes_consumed"] == lot["stability_budget_minutes"], (
        "boundary: consumed must equal the budget exactly"
    )
    k2 = world["kits"][1]
    resp = api_client.release_kit(k2["id"], world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_LOT_STABILITY_EXHAUSTED.value, expected_status=422)


def test_stability_exhausted_kit_not_restored_by_acceptable_assessment():
    """PRD §3.4: "One exception overrides the restore: any kit whose lot is
    stability-exhausted after the charge — consumed has reached or exceeded the
    budget — remains in `QUARANTINED_EXCURSION`."

    Design: Difficulty/boundary_precision_check/stability_budget_exactly_consumed_blocks_release
    """
    world = _world_with_budget_exactly_consumed()
    k1 = world["kits"][0]
    assert get_kit(k1["id"])["status"] == "QUARANTINED_EXCURSION", (
        "consumed (400) reached the budget (400), so the ACCEPTABLE assessment "
        "must not restore the excursion-quarantined kit"
    )


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / excursion_assess_then_void_restores_stability_budget
# ---------------------------------------------------------------------------

def _world_with_assessable_excursion():
    world = setup_pharmacy(protocol_number="P-INV-3", kit_numbers=("K-I2",),
                           pharmacist_license="L-INV3-1",
                           lot_overrides={"lot_number": "LOT-INV-3"})
    exc = setup_open_excursion(world, readings=((9.5, None), (1.0, "2026-08-01T01:40:00Z")))
    return {**world, **exc}


def test_acceptable_assessment_charges_stability_budget_forward():
    """PRD §3.4: "The server computes the excursion's severity (below), records
    it as `severity_minutes_charged`, and charges it to the stability budget of
    every distinct lot owning a kit linked to the excursion or quarantined by it
    — each such lot's `stability_minutes_consumed` increases by
    `severity_minutes_charged`."

    Design: Difficulty/compensating_invariant/excursion_assess_then_void_restores_stability_budget
    """
    world = _world_with_assessable_excursion()
    assessed = assess_excursion(world["excursion_id"], "ACCEPTABLE", rationale="QA release")
    assert assessed["severity_minutes_charged"] == 400
    assert get_lot(world["lot"]["id"])["stability_minutes_consumed"] == 400
    assert get_kit(world["kits"][0]["id"])["status"] == "AVAILABLE", (
        "400 < 600 budget: the kit restores to AVAILABLE"
    )


def test_void_of_acceptable_assessment_reverses_the_charge():
    """PRD §3.4: "`VOID` — permitted only from `RESOLVED_ACCEPTABLE`, as a
    sponsor reversal of an acceptable assessment — moves the excursion to
    `VOIDED`. The budget charge is reversed: every charged lot's
    `stability_minutes_consumed` is decreased by `severity_minutes_charged`,
    restoring the compensating invariant on stability minutes. Kits already
    restored stay restored; the void performs no retroactive kit mutation."

    Design: Difficulty/compensating_invariant/excursion_assess_then_void_restores_stability_budget
    """
    world = _world_with_assessable_excursion()
    assess_excursion(world["excursion_id"], "ACCEPTABLE", rationale="QA release")
    voided = assess_excursion(world["excursion_id"], "VOID",
                              rationale="QA reversal — logger miscalibrated")
    assert voided["status"] == "VOIDED"
    assert get_lot(world["lot"]["id"])["stability_minutes_consumed"] == 0, (
        "the compensating VOID subtracts exactly the charged severity"
    )
    assert get_kit(world["kits"][0]["id"])["status"] == "AVAILABLE", (
        "kits already restored stay restored"
    )
