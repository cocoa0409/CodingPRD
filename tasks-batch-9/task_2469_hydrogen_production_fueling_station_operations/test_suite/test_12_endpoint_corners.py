"""Endpoint corners: the clock's report, the ledger read, the void guard and the join reads."""

import pytest
from test_helpers import (
    AUDITOR,
    COMPLIANCE,
    DISPATCHER,
    NON_EXISTENT_UUID,
    SMALL_LOT,
    add_emergency_responders,
    api_client,
    certify_lot_ci,
    commission_vessel,
    complete_session,
    create_funding_agreement,
    create_production_lot,
    create_session,
    create_station,
    create_uptime_report,
    fuel_session,
    liquid_tanker_delivery_payload,
    list_meta,
    list_rows,
    read_agreement,
    read_ledger,
    read_lot,
    read_station,
    read_station_version,
    read_vessel,
    set_clock,
    settle_session,
    setup_operational_station,
    setup_small_produced_lot,
    submit_claim,
    validate_error,
    validate_success,
    void_meter_payload,
)

HIGH_VESSEL = {
    "bank_tier": "HIGH",
    "water_volume_l": 600.0,
    "mawp_bar": 1000.00,
    "min_residual_bar": 200.00,
    "initial_pressure_bar": 950.00,
}
LOW_VESSEL = {
    "bank_tier": "LOW",
    "water_volume_l": 5000.0,
    "mawp_bar": 1000.00,
    "min_residual_bar": 100.00,
    "initial_pressure_bar": 300.00,
}
COLD_H35_BUS = {
    "vehicle_class": "TRANSIT_BUS",
    "target_pressure_class": "H35",
    "fill_protocol": "SAE_J2601_TABLE",
    "planned_kg": 24.000,
    "ambient_temp_c": -18.0,
}
STATION_SHAPE = {
    "nozzle_count": 2,
    "offload_bay_count": 1,
    "storage_capacity_kg": 900.000,
    "reserve_floor_kg": 20.000,
    "max_pressure_class": "H35",
    "setback_compliant": True,
}
AGREEMENT_SHAPE = {
    "funder_name": "State Clean Transport Fund",
    "min_uptime_pct": 99.000,
    "penalty_per_point_cents": 250000,
    "initial_holdback_cents": 500000,
}


# ─── Recipe builders ──────────────────────────────────────────────────────


def _dispensing_station(code, name, bank, **station_overrides):
    return setup_operational_station(
        clock="2026-08-01T00:00:00Z",
        agreement_overrides={"agreement_code": f"FA-{code}", **AGREEMENT_SHAPE,
                             "uptime_method": "NOZZLE_WEIGHTED"},
        station_overrides={**STATION_SHAPE, "code": code, "name": name, **station_overrides},
        bank=bank,
        responders=2,
        vessel_due_date="2027-06-30",
    )


def _completed_cold_fill(station_id):
    """One 24.000 kg fill at ambient -18.0, completed but not yet settled."""
    session = create_session(station_id, **COLD_H35_BUS)
    fuel_session(session["id"], station_id, -20.0)
    return complete_session(session["id"], station_id, 24.000, 700.00, 438.00)


def _two_station_estate():
    """Two stations under one agreement: three vessels, one of them nearly due."""
    set_clock("2026-08-01T00:00:00Z")
    agreement = create_funding_agreement(
        agreement_code="FA-E1", **AGREEMENT_SHAPE, uptime_method="NOZZLE_WEIGHTED"
    )
    first = create_station(
        agreement["id"], **{**STATION_SHAPE, "code": "STN-E1", "name": "Clock Station A"}
    )
    near_due = commission_vessel(
        first["id"], **HIGH_VESSEL, next_inspection_due_date="2026-08-15"
    )
    far_due = commission_vessel(
        first["id"], **LOW_VESSEL, next_inspection_due_date="2026-10-01"
    )
    add_emergency_responders(first["id"], count=2)
    second = create_station(
        agreement["id"], **{**STATION_SHAPE, "code": "STN-E2", "name": "Clock Station B"}
    )
    other = commission_vessel(
        second["id"], **HIGH_VESSEL, next_inspection_due_date="2027-06-30"
    )
    return {
        "first": first, "second": second,
        "near_due": near_due, "far_due": far_due, "other": other,
    }


def _book_tanker(station_id, lot_id, vessel_id):
    return api_client.create_delivery(
        liquid_tanker_delivery_payload(
            station_id, lot_id, vessel_id,
            planned_kg=100.000,
            window_start="2026-08-02T08:00:00Z",
            window_end="2026-08-02T12:00:00Z",
            departed_at="2026-08-02T04:00:00Z",
        ),
        DISPATCHER,
    )


# ─── The clock endpoint's own report ──────────────────────────────────────


def test_the_clock_flips_one_vessel_across_the_grace_edge_and_reports_itself():
    """Thirty days past due is still DUE; thirty-one days strips the station's posture.

    "That capability's response is not a resource envelope but a small object reporting
    `current_utc` (the newly set instant), `vessels_recomputed` (how many pressure vessels
    had their inspection status re-derived) and `stations_recomputed` (how many stations
    had their posture re-derived)."  "The two boundaries are worth stating explicitly: a
    vessel whose due date is exactly today is `DUE`, not `CURRENT`, and a vessel exactly
    thirty days past due is still `DUE`, not `OVERDUE`."  "Moving the clock across the
    second boundary takes the vessel `DUE → OVERDUE`, drops it out of
    `total_deliverable_kg` and `high_bank_deliverable_kg`, and forces the station's posture
    to be recomputed, because an overdue vessel is a restricting condition; a station that
    was `OPEN` and holds at least one vessel newly gone overdue therefore moves `OPEN →
    RESTRICTED`, and its `version` is incremented by one."

    Design: Corner/endpoints/clock_advance_reports_recompute_counts_and_flips_inspection_bands
    """
    estate = _two_station_estate()
    assert estate["near_due"]["inspection_status"] == "CURRENT", (
        "2026-08-01 is strictly earlier than the 2026-08-15 due date"
    )

    on_the_grace_edge = set_clock("2026-09-14T00:00:00Z")

    assert on_the_grace_edge["current_utc"].startswith("2026-09-14T00:00:00")
    assert isinstance(on_the_grace_edge["vessels_recomputed"], int)
    assert isinstance(on_the_grace_edge["stations_recomputed"], int), (
        "the clock answers with its own small object, not a resource envelope"
    )
    assert read_vessel(estate["near_due"]["id"])["inspection_status"] == "DUE"
    assert read_vessel(estate["far_due"]["id"])["inspection_status"] == "CURRENT"
    assert read_vessel(estate["other"]["id"])["inspection_status"] == "CURRENT"
    mid = read_station(estate["first"]["id"])
    assert mid["safety_posture"] == "OPEN", "a DUE vessel restricts nothing"
    assert mid["total_deliverable_kg"] == pytest.approx(116.000, abs=0.001), (
        "36.000 kg from the high bank plus 80.000 kg from the low bank"
    )

    set_clock("2026-09-15T00:00:00Z")

    assert read_vessel(estate["near_due"]["id"])["inspection_status"] == "OVERDUE"
    late = read_station(estate["first"]["id"])
    assert late["safety_posture"] == "RESTRICTED"
    assert late["total_deliverable_kg"] == pytest.approx(80.000, abs=0.001)
    assert late["high_bank_deliverable_kg"] == pytest.approx(0.000, abs=0.001)
    assert late["onsite_inventory_kg"] == pytest.approx(165.600, abs=0.001), (
        "an inspection band never moves mass"
    )
    assert read_station(estate["second"]["id"])["safety_posture"] == "OPEN", (
        "the recompute did not leak across stations"
    )


# ─── The ledger read ──────────────────────────────────────────────────────


def test_the_ledger_read_replays_the_balance_and_the_filter_keeps_the_numbering():
    """Three rows in replay order, and the filtered row keeps its own sequence and balance.

    "Each station owns an append-only ledger whose entries are the sole record of mass
    movement, and `onsite_inventory_kg` on the station is the `resulting_onsite_kg` of the
    latest entry in replay order — 0.000 when the ledger is empty."  "Replay order is
    pinned: entries are ordered by `occurred_at` ascending, then by `sequence_no`
    ascending, where `sequence_no` is assigned per station in append order, beginning at 1
    and incrementing by one for each subsequent entry, so that the secondary key fully
    disambiguates entries sharing a single logical-clock instant."  "The ledger is readable
    per station and may be filtered by `reason`."  "A `METER_CORRECTION` entry is appended
    whose `delta_kg` is the session's `metered_kg` minus its `corrected_kg`, reconciling the
    raw meter reading — which the completion already removed from inventory — to the
    corrected mass."

    Design: Corner/endpoints/inventory_ledger_read_replays_the_running_onsite_balance
    """
    scenario = _dispensing_station("STN-E3", "Ledger Station", (HIGH_VESSEL,))
    station_id = scenario["station"]["id"]
    filled = _completed_cold_fill(station_id)
    assert filled["corrected_kg"] == pytest.approx(24.365, abs=0.001)
    settled = settle_session(filled["id"])
    assert settled["billing_status"] == "METERED"

    rows = read_ledger(station_id, params={"limit": 100, "offset": 0})

    assert [row["sequence_no"] for row in rows] == [1, 2, 3]
    assert [row["reason"] for row in rows] == [
        "OPENING_BALANCE", "DISPENSE_DRAW", "METER_CORRECTION"
    ]
    assert [row["delta_kg"] for row in rows] == [
        pytest.approx(45.600, abs=0.001),
        pytest.approx(-24.000, abs=0.001),
        pytest.approx(-0.365, abs=0.001),
    ]
    assert [row["resulting_onsite_kg"] for row in rows] == [
        pytest.approx(45.600, abs=0.001),
        pytest.approx(21.600, abs=0.001),
        pytest.approx(21.235, abs=0.001),
    ]

    filtered = api_client.list_station_inventory_ledger(
        station_id, AUDITOR, params={"reason": "METER_CORRECTION", "limit": 100, "offset": 0}
    )

    assert list_meta(filtered)["total_count"] == 1
    only_row = list_rows(filtered)[0]
    assert only_row["sequence_no"] == 3, "filtering narrows the rows without renumbering them"
    assert only_row["resulting_onsite_kg"] == pytest.approx(21.235, abs=0.001)
    station = read_station(station_id)
    assert station["onsite_inventory_kg"] == pytest.approx(21.235, abs=0.001)
    assert station["metering_error_pct_mtd"] == pytest.approx(-1.498, abs=0.0005)


# ─── The conditional void ─────────────────────────────────────────────────


def test_the_void_is_legal_from_metered_and_from_nowhere_else():
    """Too early and twice over both fail, so the reversal row can never be written twice.

    "The transition is accepted only while `billing_status` is `METERED`, and only while no
    incentive claim whose `status` is `CERTIFIED` or `CREDITS_ISSUED` covers the date of the
    session's `started_at`; a session already baked into an adjudicated credit claim cannot
    be unwound, and the attempt is refused with `ERR_INVALID_STATE_TRANSITION`."  "A void
    moves `billing_status` `METERED → VOIDED` and appends a `METER_VOID_REVERSAL` entry
    whose `delta_kg` is the session's `corrected_kg` minus its `metered_kg` — the exact
    additive inverse of the `METER_CORRECTION` entry the settlement appended."  "Because the
    ledger is append-only, this is how a movement is undone, and the invariant it guarantees
    is checkable: after the void, the station's `onsite_inventory_kg` returns precisely to
    its pre-settlement value."

    Design: Corner/endpoints/void_meter_is_conditional_on_the_metered_billing_state
    """
    scenario = _dispensing_station("STN-E4", "Void Station", (HIGH_VESSEL,))
    station_id = scenario["station"]["id"]
    filled = _completed_cold_fill(station_id)
    assert filled["billing_status"] == "PENDING"

    too_early = api_client.void_dispense_session_meter(
        filled["id"], void_meter_payload(void_reason="AUDIT_ADJUSTMENT"), COMPLIANCE
    )

    validate_error(too_early, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
    assert len(read_ledger(station_id, params={"limit": 100, "offset": 0})) == 2, (
        "nothing was booked, so the draw is still the last row"
    )

    settle_session(filled["id"])
    voided = validate_success(
        api_client.void_dispense_session_meter(
            filled["id"], void_meter_payload(void_reason="AUDIT_ADJUSTMENT"), COMPLIANCE
        ),
        expected_status=200,
    )
    second_attempt = api_client.void_dispense_session_meter(
        filled["id"], void_meter_payload(void_reason="AUDIT_ADJUSTMENT"), COMPLIANCE
    )

    assert voided["billing_status"] == "VOIDED"
    assert voided["void_reason"] == "AUDIT_ADJUSTMENT"
    validate_error(second_attempt, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
    rows = read_ledger(station_id, params={"limit": 100, "offset": 0})
    assert [row["reason"] for row in rows] == [
        "OPENING_BALANCE", "DISPENSE_DRAW", "METER_CORRECTION", "METER_VOID_REVERSAL"
    ], "exactly one correction and exactly one reversal"
    assert rows[3]["delta_kg"] == pytest.approx(0.365, abs=0.001)
    station = read_station(station_id)
    assert station["onsite_inventory_kg"] == pytest.approx(21.600, abs=0.001), (
        "back to the balance the draw left behind"
    )
    assert station["metered_kg_mtd"] == pytest.approx(0.000, abs=0.001)
    assert station["corrected_kg_mtd"] == pytest.approx(0.000, abs=0.001)
    assert station["metering_error_pct_mtd"] == pytest.approx(0.000, abs=0.001)
    assert station["metering_accuracy_flag"] == "WITHIN_TOLERANCE"


# ─── The three-legged join ────────────────────────────────────────────────


def test_each_missing_leg_of_a_booking_has_its_own_not_found_code():
    """Station, lot and vessel each answer for themselves, and the link reads back both ways.

    "Each entity type has its own 404: `ERR_STATION_NOT_FOUND`,
    `ERR_FUNDING_AGREEMENT_NOT_FOUND`, `ERR_PRESSURE_VESSEL_NOT_FOUND`,
    `ERR_PRODUCTION_ASSET_NOT_FOUND`, `ERR_PRODUCTION_LOT_NOT_FOUND`,
    `ERR_DELIVERY_NOT_FOUND`, `ERR_DISPENSE_SESSION_NOT_FOUND`,
    `ERR_SAFETY_EVENT_NOT_FOUND`, `ERR_INCENTIVE_CLAIM_NOT_FOUND` and
    `ERR_UPTIME_REPORT_NOT_FOUND`."  "A new delivery is created with `status` of
    `SCHEDULED` and `reschedule_count` of 0, and the write recomputes the station's
    `inbound_planned_kg`, `projected_available_kg` and `supply_alert` and increments the
    station's `version` by one."  "Deliveries can be listed with optional `station_id`,
    `production_lot_id`, `receiving_vessel_id`, `status` and `mode` filters."

    Design: Corner/endpoints/delivery_booking_links_station_lot_and_receiving_vessel
    """
    scenario = _dispensing_station(
        "STN-E5", "Link Station", (LOW_VESSEL,), offload_bay_count=2
    )
    station_id = scenario["station"]["id"]
    vessel_id = scenario["vessels"]["LOW"]["id"]
    lot_id = setup_small_produced_lot()["lot"]["id"]
    version_before = read_station_version(station_id)

    no_station = _book_tanker(NON_EXISTENT_UUID, lot_id, vessel_id)
    no_lot = _book_tanker(station_id, NON_EXISTENT_UUID, vessel_id)
    no_vessel = _book_tanker(station_id, lot_id, NON_EXISTENT_UUID)

    validate_error(no_station, "ERR_STATION_NOT_FOUND", expected_status=404)
    validate_error(no_lot, "ERR_PRODUCTION_LOT_NOT_FOUND", expected_status=404)
    validate_error(no_vessel, "ERR_PRESSURE_VESSEL_NOT_FOUND", expected_status=404)
    assert read_station_version(station_id) == version_before, (
        "three refusals created no row and moved no version"
    )

    booked = validate_success(
        _book_tanker(station_id, lot_id, vessel_id), expected_status=201
    )

    assert booked["station_id"] == station_id
    assert booked["production_lot_id"] == lot_id
    assert booked["receiving_vessel_id"] == vessel_id
    assert booked["status"] == "SCHEDULED"
    assert booked["reschedule_count"] == 0
    by_lot = api_client.list_deliveries(
        COMPLIANCE, params={"production_lot_id": lot_id, "limit": 100, "offset": 0}
    )
    by_vessel = api_client.list_deliveries(
        COMPLIANCE,
        params={"receiving_vessel_id": vessel_id, "status": "SCHEDULED",
                "limit": 100, "offset": 0},
    )
    assert list_meta(by_lot)["total_count"] == 1
    assert list_meta(by_vessel)["total_count"] == 1
    assert [row["id"] for row in list_rows(by_lot)] == [booked["id"]]
    station = read_station(station_id)
    assert station["inbound_planned_kg"] == pytest.approx(100.000, abs=0.001)
    assert station["projected_available_kg"] == pytest.approx(220.000, abs=0.001), (
        "120.000 kg available plus 100.000 kg inbound"
    )
    assert station["supply_alert"] is False


# ─── Read-only reads and action-only version moves ────────────────────────


def test_an_agreement_reads_back_unchanged_until_an_action_endpoint_moves_it():
    """Two reads leave the version at one; drafting a report takes it to two.

    "At creation the agreement's live `holdback_balance_cents` equals
    `initial_holdback_cents`, because no penalty has yet been charged."  "Agreements can be
    listed with optional `funder_name` and `uptime_method` filters."  "A successful draft is
    created with `status` of `DRAFT`, snapshots `nozzle_count_snapshot` from the station's
    current `nozzle_count` — the denominator of the nozzle-weighted variant, frozen at
    report creation so that later nozzle expansion does not rewrite history — computes both
    uptime variants along with `uptime_pct` and `shortfall_points`, leaves `penalty_cents`
    at 0 because nothing is charged against the holdback until finalisation, and increments
    the agreement's `version` by one."

    Design: Corner/endpoints/agreement_read_after_create_and_version_only_moves_via_actions
    """
    set_clock("2026-08-01T00:00:00Z")
    created = create_funding_agreement(
        agreement_code="FA-E6", **AGREEMENT_SHAPE, uptime_method="STATION_LEVEL"
    )
    station = create_station(
        created["id"], **{**STATION_SHAPE, "code": "STN-E6", "name": "Crud Station"}
    )
    assert created["version"] == 1

    first_read = validate_success(
        api_client.get_funding_agreement(created["id"], AUDITOR), expected_status=200
    )

    assert first_read["version"] == 1, "a read never bumps the version"
    assert first_read["agreement_code"] == "FA-E6"
    assert first_read["funder_name"] == "State Clean Transport Fund"
    assert first_read["uptime_method"] == "STATION_LEVEL"
    assert first_read["min_uptime_pct"] == pytest.approx(99.000, abs=0.0005)
    assert first_read["penalty_per_point_cents"] == 250000
    assert first_read["initial_holdback_cents"] == 500000
    assert first_read["holdback_balance_cents"] == 500000
    listing = api_client.list_funding_agreements(AUDITOR, params={"limit": 10, "offset": 0})
    assert list_meta(listing)["total_count"] == 1
    assert list_meta(listing)["has_more"] is False

    report = create_uptime_report(station["id"], created["id"])

    assert report["status"] == "DRAFT"
    assert report["uptime_pct"] == pytest.approx(100.000, abs=0.0005), (
        "no cleared safety event exists, so no downtime accrued"
    )
    assert report["shortfall_points"] == pytest.approx(0.000, abs=0.0005)
    assert report["penalty_cents"] == 0
    assert read_agreement(created["id"])["version"] == 2, (
        "only the action endpoint moved the version, and by exactly one"
    )


# ─── An all-or-nothing set input ──────────────────────────────────────────


def test_one_bad_lot_rejects_the_whole_claim_set_at_each_guard_in_turn():
    """The set is judged whole, and the second guard only surfaces once the first is met.

    "Every lot named in `production_lot_ids` must have `ci_status` of `CERTIFIED`, or the
    claim is refused with `ERR_LOT_CI_NOT_CERTIFIED` — an uncertified lot has no carbon
    intensity to weight."  "Every named lot must also have at least one delivery to *this*
    station whose `status` is `ACCEPTED` and whose `accepted_at` falls inside the inclusive
    claim period, or the claim is refused with `ERR_LOT_NOT_DELIVERED_IN_PERIOD` (HTTP
    422); a lot the station never received cannot back its dispensing."  "The lot's own
    `status` is untouched: this is progress along one branch of a two-branch lifecycle, not
    a lifecycle transition, so the lot remains `PRODUCED` throughout."

    Design: Corner/endpoints/claim_lot_set_is_validated_all_or_nothing
    """
    scenario = _dispensing_station("STN-E7", "Claim Station", (LOW_VESSEL,))
    station_id = scenario["station"]["id"]
    lot_scenario = setup_small_produced_lot(asset_overrides={"asset_code": "PA-E7"})
    first_lot = certify_lot_ci(lot_scenario["lot"]["id"])
    second_lot = create_production_lot(
        lot_scenario["asset"]["id"],
        **{**SMALL_LOT, "lot_code": "LOT-E7-B",
           "production_start_at": "2026-07-22T00:00:00Z",
           "production_end_at": "2026-07-23T00:00:00Z"},
    )
    lot_ids = [first_lot["id"], second_lot["id"]]
    assert first_lot["ci_status"] == "CERTIFIED"
    assert second_lot["ci_status"] == "PENDING"

    uncertified = submit_claim(station_id, lot_ids, period_start="2026-08-01",
                               period_end="2026-08-31")

    validate_error(uncertified, "ERR_LOT_CI_NOT_CERTIFIED", expected_status=422)

    certify_lot_ci(second_lot["id"])
    undelivered = submit_claim(station_id, lot_ids, period_start="2026-08-01",
                               period_end="2026-08-31")

    validate_error(undelivered, "ERR_LOT_NOT_DELIVERED_IN_PERIOD", expected_status=422)
    claims = api_client.list_station_incentive_claims(
        station_id, AUDITOR, params={"limit": 100, "offset": 0}
    )
    assert list_meta(claims)["total_count"] == 0, "not even a partial claim row survived"
    for lot_id in lot_ids:
        lot = read_lot(lot_id)
        assert lot["status"] == "PRODUCED"
        assert lot["ci_status"] == "CERTIFIED"
        assert lot["qa_status"] == "PENDING"
