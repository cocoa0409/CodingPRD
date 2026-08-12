"""Recording a landing: the regulatory gates, the quota debit and the counter-signature."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_landed_pounds_partition,
    assert_quota_ledger_invariant,
    close_landings,
    make_vendor_headers,
    new_trip,
    read_ledger,
    read_lot,
    read_trip,
    read_vessel,
    record_landing_payload,
    set_clock,
    set_compliance,
    setup_fleet,
    setup_landed_lot,
    setup_open_season,
    validate_error,
    validate_success,
    verify_landing,
)

ADMIN = TEST_USERS["admin_headers"]


def test_partial_fill_trims_the_landing_to_the_remaining_entitlement(api):
    """PRD 3.3: "When the gross exceeds it, behaviour forks on `allow_partial_fill`: if the
    flag is true, `landed_pounds_net` is trimmed to exactly the available pounds and the excess
    — the gross less the available figure — is written to `discarded_over_quota_pounds` as a
    regulatory discard; if the flag is false or absent, the landing is refused with
    `ERR_QUOTA_EXCEEDED`."
    PRD 3.3: "and moves to `EXHAUSTED` from either `OPEN` or `WARNING` the moment
    `remaining_pounds` reaches exactly zero."

    Design: Corner/calculations/quota_partial_fill_trims_the_over_quota_pounds
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(ctx["season_id"], species="SALMON", entitlement_pounds=20.00)
    trip = new_trip(fleet["vessel_id"], ctx["season_id"], fleet["ledger_id"])

    lot = validate_success(
        api.record_landing(
            trip["id"],
            record_landing_payload("SALMON", 25.00, allow_partial_fill=True),
            make_vendor_headers(fleet["vessel_id"]),
        ),
        201,
    )
    assert float(lot["landed_pounds_gross"]) == pytest.approx(25.00)
    assert float(lot["landed_pounds_net"]) == pytest.approx(20.00)
    assert float(lot["discarded_over_quota_pounds"]) == pytest.approx(5.00)
    assert_landed_pounds_partition(lot)

    ledger = read_ledger(fleet["ledger_id"])
    assert float(ledger["committed_pounds"]) == pytest.approx(20.00)
    assert float(ledger["remaining_pounds"]) == pytest.approx(0.00)
    assert ledger["status"] == "EXHAUSTED"

    landed_trip = read_trip(trip["id"])
    assert landed_trip["status"] == "LANDED"
    assert landed_trip["sustainability_band"] == "GREEN"


def test_a_red_sustainability_band_blocks_the_landing(api):
    """PRD 3.3: "From that base the ledger's `area_sensitivity_penalty` is subtracted and its
    `species_stock_adjustment` is added; the result is then clamped into the range 0 through
    100, meaning any value below 0 becomes 0 and any value above 100 becomes 100, and that
    clamped integer is `sustainability_score`."
    PRD 3.3: "A `RED` band blocks the landing outright with `ERR_SUSTAINABILITY_BLOCKED`."
    PRD 3.3: "a trawl trip against a penalty of 10 scores 35 and is refused."

    Design: Corner/calculations/red_sustainability_band_rejects_the_landing
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(
        ctx["season_id"],
        species="SALMON",
        management_area="GOM-3",
        vessel={
            "vessel_name": "Dragnet",
            "permit_number": "P-200",
            "home_port": "Gloucester",
            "gear_types": ["TRAWL"],
        },
        permitted_gears=["TRAWL"],
        area_sensitivity_penalty=10,
        species_stock_adjustment=0,
    )
    trip = new_trip(
        fleet["vessel_id"],
        ctx["season_id"],
        fleet["ledger_id"],
        gear_type="TRAWL",
        management_area="GOM-3",
    )

    response = api.record_landing(
        trip["id"],
        record_landing_payload("SALMON", 40.00),
        make_vendor_headers(fleet["vessel_id"]),
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_SUSTAINABILITY_BLOCKED.value)

    assert read_trip(trip["id"])["status"] == "PLANNED"
    assert float(read_ledger(fleet["ledger_id"])["committed_pounds"]) == pytest.approx(0.00)


def test_a_closed_area_blocks_the_landing(api):
    """PRD 3.3: "The entitlement's area must not be administratively closed, or the landing is
    refused with `ERR_AREA_CLOSED`."
    PRD 2.5: "The entitlement's `area_closed` flag is false — otherwise `ERR_AREA_CLOSED`
    (HTTP 422), on landing recording."

    Design: Corner/validations/closed_area_rejects_the_landing_before_any_other_business_rung
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(
        ctx["season_id"], species="SALMON", management_area="GOM-9", area_closed=True
    )
    trip = new_trip(
        fleet["vessel_id"], ctx["season_id"], fleet["ledger_id"], management_area="GOM-9"
    )

    response = api.record_landing(
        trip["id"],
        record_landing_payload("SALMON", 5.00),
        make_vendor_headers(fleet["vessel_id"]),
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_AREA_CLOSED.value)

    assert read_trip(trip["id"])["status"] == "PLANNED"
    assert float(read_ledger(fleet["ledger_id"])["committed_pounds"]) == pytest.approx(0.00)


def test_gear_outside_the_entitlements_permitted_list_blocks_the_landing(api):
    """PRD 3.3: "The trip's `gear_type` must appear both in the ledger's `permitted_gears` and
    in the vessel's own `gear_types`, or it is refused with `ERR_GEAR_NOT_PERMITTED`."
    PRD 2.5: "The trip's `gear_type` is a member of the entitlement's `permitted_gears` and
    also a member of the vessel's `gear_types` — otherwise `ERR_GEAR_NOT_PERMITTED` (HTTP 422),
    on landing recording."

    Design: Corner/validations/gear_absent_from_permitted_gears_is_rejected
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(
        ctx["season_id"],
        species="SALMON",
        management_area="GOM-4",
        vessel={
            "vessel_name": "Northeaster",
            "permit_number": "P-100",
            "home_port": "Portland",
            "gear_types": ["HOOK_AND_LINE", "TRAP"],
        },
        permitted_gears=["TRAP"],
    )
    trip = new_trip(
        fleet["vessel_id"],
        ctx["season_id"],
        fleet["ledger_id"],
        gear_type="HOOK_AND_LINE",
        management_area="GOM-4",
    )

    response = api.record_landing(
        trip["id"],
        record_landing_payload("SALMON", 5.00),
        make_vendor_headers(fleet["vessel_id"]),
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_GEAR_NOT_PERMITTED.value)
    assert read_trip(trip["id"])["status"] == "PLANNED"


def test_over_quota_landing_without_the_partial_fill_flag_is_refused(api):
    """PRD 2.5: "`landed_pounds_gross` is at most the entitlement's `remaining_pounds`, or
    `allow_partial_fill` is true; and a ledger already in status `EXHAUSTED` or `SUSPENDED`
    accepts no landing at all. Failure is `ERR_QUOTA_EXCEEDED` (HTTP 422), on landing
    recording."
    PRD 3.3: "if the flag is false or absent, the landing is refused with
    `ERR_QUOTA_EXCEEDED`."

    Design: Corner/validations/over_quota_landing_without_partial_fill_is_rejected
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(ctx["season_id"], species="SALMON", entitlement_pounds=5.00)
    trip = new_trip(fleet["vessel_id"], ctx["season_id"], fleet["ledger_id"])

    response = api.record_landing(
        trip["id"],
        record_landing_payload("SALMON", 10.00),
        make_vendor_headers(fleet["vessel_id"]),
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_QUOTA_EXCEEDED.value)

    ledger = read_ledger(fleet["ledger_id"])
    assert float(ledger["committed_pounds"]) == pytest.approx(0.00)
    assert float(ledger["remaining_pounds"]) == pytest.approx(5.00)
    assert ledger["status"] == "OPEN"


def test_returning_a_vessel_to_compliant_re_opens_its_suspended_ledger(api):
    """PRD 3.3: "Moving `SUSPENDED → COMPLIANT` re-opens each of the vessel's `SUSPENDED`
    ledgers, and each one lands where its own consumption puts it: back to `OPEN` when its
    `committed_pounds` divided by its `entitlement_pounds` is strictly less than
    `QUOTA_WARNING_PCT`, which is 0.85, and to `WARNING` otherwise."
    PRD 3.3: "`COMPLIANT → PROBATION → SUSPENDED → COMPLIANT` is a full cycle and may be
    walked repeatedly, `violation_count` accumulating each time."

    Design: Corner/state_machines/vessel_compliance_cycle_restores_the_ledger_to_open
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    set_compliance(fleet["vessel_id"], "PROBATION")
    set_compliance(fleet["vessel_id"], "SUSPENDED")

    vessel = set_compliance(fleet["vessel_id"], "COMPLIANT")
    assert vessel["compliance_status"] == "COMPLIANT"
    assert vessel["violation_count"] == 2

    ledger = read_ledger(fleet["ledger_id"])
    assert ledger["status"] == "OPEN"
    assert float(ledger["remaining_pounds"]) == pytest.approx(500.00)


def test_landing_at_the_species_close_instant_is_admitted(api):
    """PRD 2.5: "The logical clock is at or after the entitlement's `species_open_date` and at
    or before its `species_close_date` — otherwise `ERR_SPECIES_OUT_OF_SEASON` (HTTP 422), on
    landing recording."
    PRD 2.6: "Comparisons against instants are exact to the second, and a boundary instant
    belongs to whichever side the prose names. Throughout this document, "at or before" and
    "at or after" include the boundary instant; "strictly after" and "strictly before" exclude
    it."

    Design: Difficulty/resource_temporal_overlap/species_season_is_a_closed_interval_at_its_end_instant
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(
        ctx["season_id"], species="SALMON", species_close_date="2026-06-01T00:00:00Z"
    )
    trip = new_trip(fleet["vessel_id"], ctx["season_id"], fleet["ledger_id"])
    set_clock("2026-06-01T00:00:00Z")

    lot = validate_success(
        api.record_landing(
            trip["id"],
            record_landing_payload("SALMON", 7.00),
            make_vendor_headers(fleet["vessel_id"]),
        ),
        201,
    )
    assert read_trip(trip["id"])["status"] == "LANDED"
    assert float(lot["landed_pounds_net"]) == pytest.approx(7.00)


def test_landing_one_second_past_the_species_close_instant_is_refused(api):
    """PRD 3.3: "The logical clock must sit at or after `species_open_date` and at or before
    `species_close_date`, or it is refused with `ERR_SPECIES_OUT_OF_SEASON`."
    PRD 3.3: "a `species_open_date` and a `species_close_date` bounding the period during
    which the species may be landed in that area (both boundaries inclusive)"

    Design: Difficulty/resource_temporal_overlap/species_season_is_a_closed_interval_at_its_end_instant
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(
        ctx["season_id"], species="SALMON", species_close_date="2026-06-01T00:00:00Z"
    )
    first_trip = new_trip(fleet["vessel_id"], ctx["season_id"], fleet["ledger_id"])
    second_trip = new_trip(fleet["vessel_id"], ctx["season_id"], fleet["ledger_id"])

    set_clock("2026-06-01T00:00:00Z")
    validate_success(
        api.record_landing(
            first_trip["id"],
            record_landing_payload("SALMON", 7.00),
            make_vendor_headers(fleet["vessel_id"]),
        ),
        201,
    )

    set_clock("2026-06-01T00:00:01Z")
    response = api.record_landing(
        second_trip["id"],
        record_landing_payload("SALMON", 7.00),
        make_vendor_headers(fleet["vessel_id"]),
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.ERR_SPECIES_OUT_OF_SEASON.value)

    assert read_trip(second_trip["id"])["status"] == "PLANNED"
    ledger = read_ledger(fleet["ledger_id"])
    assert float(ledger["committed_pounds"]) == pytest.approx(7.00)
    assert float(ledger["remaining_pounds"]) == pytest.approx(493.00)


def test_a_suspended_vessel_can_no_longer_land_its_planned_trip(api):
    """PRD 2.5: "The vessel behind the trip has compliance standing `COMPLIANT` or `PROBATION`
    — otherwise `ERR_VESSEL_SUSPENDED` (HTTP 403), on trip creation and landing recording."
    PRD 3.3: "The call requires the trip to be `PLANNED`, the season to be `OPEN` and the
    vessel to be `COMPLIANT` or on `PROBATION`; a season that has moved past open refuses the
    landing with `ERR_SEASON_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/landing_depends_on_vessel_compliance_status
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    trip = new_trip(fleet["vessel_id"], ctx["season_id"], fleet["ledger_id"])
    set_compliance(fleet["vessel_id"], "PROBATION")
    set_compliance(fleet["vessel_id"], "SUSPENDED")

    response = api.record_landing(
        trip["id"],
        record_landing_payload("SALMON", 5.00),
        make_vendor_headers(fleet["vessel_id"]),
    )
    assert response.status_code == 403
    validate_error(response, ApiErrorId.ERR_VESSEL_SUSPENDED.value)
    assert read_trip(trip["id"])["status"] == "PLANNED"


def test_suspending_a_vessel_suspends_the_entitlement_behind_its_trip(api):
    """PRD 3.3: "Moving `PROBATION → SUSPENDED` increments `violation_count` by 1 again, and
    additionally suspends the vessel's entitlements: every quota ledger of that vessel standing
    in `OPEN` or `WARNING` moves to `SUSPENDED`, and both trip creation and landing recording
    for that vessel are refused with `ERR_VESSEL_SUSPENDED`."
    PRD 3.3: "Moving `COMPLIANT → PROBATION` increments `violation_count` by 1 and nothing
    else."

    Design: Difficulty/cross_entity_state_dependency/landing_depends_on_vessel_compliance_status
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    new_trip(fleet["vessel_id"], ctx["season_id"], fleet["ledger_id"])

    on_probation = set_compliance(fleet["vessel_id"], "PROBATION")
    assert on_probation["violation_count"] == 1
    assert read_ledger(fleet["ledger_id"])["status"] == "OPEN"

    suspended = set_compliance(fleet["vessel_id"], "SUSPENDED")
    assert suspended["compliance_status"] == "SUSPENDED"
    assert suspended["violation_count"] == 2

    ledger = read_ledger(fleet["ledger_id"])
    assert ledger["status"] == "SUSPENDED"
    assert float(ledger["committed_pounds"]) == pytest.approx(0.00)
    assert_quota_ledger_invariant(ledger)


def test_rejecting_a_landing_report_credits_the_quota_pounds_back_exactly(api):
    """PRD 3.3: "Rejecting moves the trip `LANDED → REJECTED`, requires the trip's lot to still
    be in `RECORDED`, returns `landed_pounds_net` to the ledger by reducing `committed_pounds`
    by exactly that figure — restoring `committed_pounds` and `remaining_pounds` to their
    pre-landing values — recomputes the ledger's status per the thresholds above, and moves the
    lot `RECORDED → CLOSED`, leaving its `quality_status` untouched."
    PRD 2.9: "`INV_QUOTA_LEDGER` — for every quota ledger, `entitlement_pounds` equals
    `committed_pounds` plus `remaining_pounds`."

    Design: Difficulty/compensating_invariant/landing_rejection_restores_the_quota_pounds_exactly
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    landing = setup_landed_lot(ctx["season_id"], fleet, "SALMON", 120.00)

    before = read_ledger(fleet["ledger_id"])
    assert float(before["committed_pounds"]) == pytest.approx(120.00)
    assert float(before["remaining_pounds"]) == pytest.approx(380.00)
    assert_quota_ledger_invariant(before)

    verify_landing(landing["trip_id"], accepted=False)

    after = read_ledger(fleet["ledger_id"])
    assert float(after["entitlement_pounds"]) == pytest.approx(500.00)
    assert float(after["committed_pounds"]) == pytest.approx(0.00)
    assert float(after["remaining_pounds"]) == pytest.approx(500.00)
    assert after["status"] == "OPEN"
    assert_quota_ledger_invariant(after)


def test_rejecting_a_landing_report_closes_the_lot_without_touching_its_pounds(api):
    """PRD 3.3: "Verification is the administrator's counter-signature and takes a single
    boolean, `accepted`."
    PRD 3.3: "Rejecting moves the trip `LANDED → REJECTED`, requires the trip's lot to still
    be in `RECORDED`, returns `landed_pounds_net` to the ledger by reducing `committed_pounds`
    by exactly that figure — restoring `committed_pounds` and `remaining_pounds` to their
    pre-landing values — recomputes the ledger's status per the thresholds above, and moves the
    lot `RECORDED → CLOSED`, leaving its `quality_status` untouched."

    Design: Difficulty/compensating_invariant/landing_rejection_restores_the_quota_pounds_exactly
    """
    ctx = setup_open_season(offered_species=("SALMON",))
    fleet = setup_fleet(ctx["season_id"], species="SALMON")
    landing = setup_landed_lot(ctx["season_id"], fleet, "SALMON", 120.00)

    trip = verify_landing(landing["trip_id"], accepted=False)
    assert trip["status"] == "REJECTED"

    lot = read_lot(landing["lot_id"])
    assert lot["status"] == "CLOSED"
    assert lot["quality_status"] == "CLEAR"
    assert float(lot["landed_pounds_net"]) == pytest.approx(120.00)


def _exhausted_ledger_after_close_landings():
    """A season closed to landings whose 5.00 lb entitlement is already fully consumed,
    with a second trip planned while the season was still OPEN."""
    ctx = setup_open_season(offered_species=("COD",))
    fleet = setup_fleet(
        ctx["season_id"], species="COD", management_area="GOM-2", entitlement_pounds=5.00
    )
    first = setup_landed_lot(ctx["season_id"], fleet, "COD", 5.00)
    second_trip = new_trip(
        fleet["vessel_id"], ctx["season_id"], fleet["ledger_id"], management_area="GOM-2"
    )
    close_landings(ctx["season_id"])
    ctx.update(fleet)
    ctx["first_landing"] = first
    ctx["second_trip"] = second_trip
    return ctx


def test_season_state_outranks_the_quota_gate_on_a_late_landing(api):
    """PRD 2.5: "Every request is screened by an ordered ladder of checks. The order matters
    and is normative: when a request would fail more than one rung, the response carries the
    error of the **lowest-numbered** rung it fails, and no later rung is evaluated."
    PRD 2.5: "The season is in the status the operation requires — otherwise
    `ERR_SEASON_NOT_OPEN` (HTTP 409). Subscription creation, subscription activation,
    subscription resumption, trip creation, landing recording, catch allocation and transfer
    creation all require the season to be `OPEN`"
    PRD 3.9: "The first moves it `OPEN → LANDINGS_CLOSED`: from that point landings for the
    season are refused with `ERR_SEASON_NOT_OPEN`, and every share transfer of the season still
    standing in `REQUESTED` expires."

    Design: Difficulty/priority_pair_validation_conflict/season_state_outranks_quota_fiscal_on_landing
    """
    ctx = _exhausted_ledger_after_close_landings()

    response = api.record_landing(
        ctx["second_trip"]["id"],
        record_landing_payload("COD", 1.00),
        make_vendor_headers(ctx["vessel_id"]),
    )
    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_SEASON_NOT_OPEN.value)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_QUOTA_EXCEEDED.value


def test_the_late_landing_leaves_the_exhausted_ledger_and_the_trip_untouched(api):
    """PRD 2.5: "and a ledger already in status `EXHAUSTED` or `SUSPENDED` accepts no landing
    at all. Failure is `ERR_QUOTA_EXCEEDED` (HTTP 422), on landing recording."
    PRD 3.3: "and moves to `EXHAUSTED` from either `OPEN` or `WARNING` the moment
    `remaining_pounds` reaches exactly zero."

    The landing violates this fiscal rung too, yet the season rung sits above it, so nothing
    on either entity moves.

    Design: Difficulty/priority_pair_validation_conflict/season_state_outranks_quota_fiscal_on_landing
    """
    ctx = _exhausted_ledger_after_close_landings()

    api.record_landing(
        ctx["second_trip"]["id"],
        record_landing_payload("COD", 1.00),
        make_vendor_headers(ctx["vessel_id"]),
    )

    ledger = read_ledger(ctx["ledger_id"])
    assert ledger["status"] == "EXHAUSTED"
    assert float(ledger["committed_pounds"]) == pytest.approx(5.00)
    assert read_trip(ctx["second_trip"]["id"])["status"] == "PLANNED"
    assert read_vessel(ctx["vessel_id"])["compliance_status"] == "COMPLIANT"
