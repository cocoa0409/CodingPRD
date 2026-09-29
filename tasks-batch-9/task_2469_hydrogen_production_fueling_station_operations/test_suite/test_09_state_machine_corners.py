"""State-machine corners: refused transitions, bounded loops and side-effect order."""

import pytest
from test_helpers import (
    COMPLIANCE,
    DISPATCHER,
    OFFICER_2,
    add_emergency_responders,
    acknowledge_safety_event,
    api_client,
    arrive_delivery,
    book_tube_trailer_delivery,
    clear_safety_event,
    commission_vessel,
    delivery_reschedule_payload,
    find_ledger_entry,
    make_station_operator_headers,
    open_safety_event,
    pass_inspection,
    read_delivery,
    read_ledger,
    read_lot,
    read_safety_event,
    read_station,
    read_vessel,
    record_purity_test,
    reject_delivery,
    set_clock,
    setup_small_produced_lot,
    setup_small_released_lot,
    setup_station,
    validate_error,
    validate_success,
)

HIGH_VESSEL = {
    "bank_tier": "HIGH",
    "water_volume_l": 600.0,
    "mawp_bar": 1000.00,
    "min_residual_bar": 200.00,
    "initial_pressure_bar": 950.00,
    "next_inspection_due_date": "2027-06-30",
}
LOW_VESSEL = {
    "bank_tier": "LOW",
    "water_volume_l": 5000.0,
    "mawp_bar": 1000.00,
    "min_residual_bar": 100.00,
    "initial_pressure_bar": 300.00,
    "next_inspection_due_date": "2027-06-30",
}
EVENT_STATION = {
    "nozzle_count": 4,
    "offload_bay_count": 2,
    "storage_capacity_kg": 900.000,
    "reserve_floor_kg": 20.000,
    "max_pressure_class": "H70",
    "setback_compliant": True,
}
YARD_STATION = {
    "nozzle_count": 2,
    "offload_bay_count": 1,
    "storage_capacity_kg": 900.000,
    "reserve_floor_kg": 20.000,
    "max_pressure_class": "H35",
    "setback_compliant": True,
}


# ─── Recipe builders ──────────────────────────────────────────────────────


def _station_with_an_open_minor_event(code, **event_overrides):
    """A healthy station carrying one OPEN MINOR OVERPRESSURE event."""
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        station_overrides={**EVENT_STATION, "code": code, "name": "Event Station"},
    )
    station_id = scenario["station"]["id"]
    scenario["vessel"] = commission_vessel(station_id, **HIGH_VESSEL)
    scenario["event"] = open_safety_event(
        station_id,
        kind="OVERPRESSURE",
        severity="MINOR",
        affected_nozzle_count=0,
        **event_overrides,
    )
    return scenario


def _yard_with_a_booked_delivery(code, **delivery_overrides):
    """A LOW-bank yard, a produced lot and one 100.000 kg tube-trailer booking."""
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        station_overrides={**YARD_STATION, "code": code, "name": "Delivery Yard"},
    )
    station_id = scenario["station"]["id"]
    scenario["vessel"] = commission_vessel(station_id, **LOW_VESSEL)
    add_emergency_responders(station_id, count=2)
    scenario.update(setup_small_produced_lot())
    scenario["delivery"] = book_tube_trailer_delivery(
        station_id,
        scenario["lot"]["id"],
        scenario["vessel"]["id"],
        planned_kg=100.000,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
        departed_at="2026-08-01T12:00:00Z",
        trailer_water_volume_l=2500.0,
        trailer_final_pressure_bar=210.00,
        **delivery_overrides,
    )
    return scenario


def _reschedule(delivery_id, window_start, window_end):
    return api_client.reschedule_delivery(
        delivery_id,
        delivery_reschedule_payload(window_start=window_start, window_end=window_end),
        DISPATCHER,
    )


# ─── SafetyEvent: the declared edges are the only edges ───────────────────


def test_clearing_an_unacknowledged_event_is_refused():
    """There is no OPEN to CLEARED edge, so acknowledgement cannot be skipped.

    "It is accepted only while the event's `status` is `ACKNOWLEDGED` — an `OPEN`
    event must be acknowledged first — and the acting `X-User-ID` must differ from the
    event's `opened_by_user_id`, with `ERR_SEGREGATION_OF_DUTIES` otherwise."  A
    request of that shape is "rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP
    409)".

    Design: Corner/state_machines/safety_event_clear_without_acknowledge_returns_invalid_state_transition
    """
    scenario = _station_with_an_open_minor_event("STN-S1", detected_by="OPERATOR_ROUND")
    event_id = scenario["event"]["id"]
    assert scenario["event"]["status"] == "OPEN"

    response = api_client.clear_safety_event(
        event_id, {"corrective_action": "Reseated relief valve"}, OFFICER_2
    )

    validate_error(response, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
    event = read_safety_event(event_id)
    assert event["status"] == "OPEN"
    assert event["cleared_at"] is None
    assert event["cleared_by_user_id"] is None
    assert event["corrective_action"] is None
    assert read_station(scenario["station"]["id"])["safety_posture"] == "OPEN", (
        "a MINOR OVERPRESSURE event neither freezes nor restricts"
    )


def test_acknowledging_an_event_twice_does_not_re_stamp_the_timestamp():
    """Repeating an applied action is an error, and the first stamp survives it.

    "Acknowledgement belongs exclusively to `SafetyOfficer`, takes no payload, and is
    accepted only while the event's `status` is `OPEN`. It stamps `acknowledged_at`
    from the logical clock and moves the event `OPEN → ACKNOWLEDGED`."  A repeat is
    "including repeating an already-applied action and acting on a terminal state".

    Design: Corner/state_machines/safety_event_acknowledged_twice_returns_invalid_state_transition
    """
    scenario = _station_with_an_open_minor_event("STN-S2", detected_by="SENSOR")
    event_id = scenario["event"]["id"]
    first = acknowledge_safety_event(event_id)
    assert first["status"] == "ACKNOWLEDGED"
    assert first["acknowledged_at"].startswith("2026-08-01T00:00:00")
    set_clock("2026-08-01T04:00:00Z")

    response = api_client.acknowledge_safety_event(event_id, OFFICER_2)

    validate_error(response, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
    event = read_safety_event(event_id)
    assert event["status"] == "ACKNOWLEDGED"
    assert event["acknowledged_at"] == first["acknowledged_at"], (
        "the refused repeat must not re-stamp acknowledged_at to 04:00:00Z"
    )


def test_clearing_the_last_event_restores_the_subsystem_then_reopens_the_station():
    """The subsystem field is healed before the posture is recomputed, not after.

    "When no other event of the same `kind` on the station remains `OPEN` or
    `ACKNOWLEDGED`, the matching subsystem field returns to its healthy value —
    `ventilation_status` to `NORMAL`, `leak_detection_status` to `NORMAL`,
    `compressor_status` to `ONLINE`, `setback_compliant` to true."  Then "Clearing the
    last outstanding event of any kind, with no restricting condition left — no
    offline compressor, high-bank deliverable mass at or above 10.000 kg, no `OVERDUE`
    or `CONDEMNED` vessel and no outstanding `MAJOR` event — takes the station
    `FROZEN → OPEN`."

    Design: Corner/state_machines/safety_event_clear_restores_subsystem_field_and_reopens_posture
    """
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        station_overrides={**EVENT_STATION, "code": "STN-S6", "name": "Ventilation Station"},
    )
    station_id = scenario["station"]["id"]
    commission_vessel(station_id, **HIGH_VESSEL)
    set_clock("2026-08-01T02:00:00Z")
    event = open_safety_event(
        station_id,
        kind="VENTILATION_FAULT",
        severity="MAJOR",
        affected_nozzle_count=2,
        detected_by="SENSOR",
    )
    acknowledge_safety_event(event["id"])
    frozen = read_station(station_id)
    assert frozen["ventilation_status"] == "FAULT"
    assert frozen["safety_posture"] == "FROZEN", (
        "a VENTILATION_FAULT event freezes regardless of severity"
    )
    set_clock("2026-08-01T06:00:00Z")

    cleared = clear_safety_event(
        event["id"],
        corrective_action="Replaced exhaust fan motor and re-tested airflow",
    )

    assert cleared["status"] == "CLEARED"
    assert cleared["cleared_at"].startswith("2026-08-01T06:00:00"), (
        "the exclusive end of a 240-minute outage that opened at 02:00:00Z"
    )
    assert cleared["cleared_by_user_id"] == "SO-2"
    assert cleared["corrective_action"] == (
        "Replaced exhaust fan motor and re-tested airflow"
    )
    station = read_station(station_id)
    assert station["ventilation_status"] == "NORMAL"
    assert station["safety_posture"] == "OPEN"
    assert station["high_bank_deliverable_kg"] == pytest.approx(36.000, abs=0.001)
    assert station["version"] == frozen["version"] + 1


# ─── PressureVessel: a pass is metadata only ─────────────────────────────


def test_a_passing_inspection_moves_the_metadata_and_never_vents():
    """The vessel keeps every kilogram it held; only the inspection fields move.

    "A passing inspection is accepted while the vessel's `inspection_status` is `DUE`
    or `OVERDUE` and the station is not `FROZEN`; it sets `last_inspection_date` to
    the logical-clock date, replaces `next_inspection_due_date` with the supplied
    `next_due_date`, increments `inspection_count` by one, sets `inspection_status`
    back to `CURRENT`, and triggers a posture recomputation."

    Design: Corner/state_machines/vessel_inspection_pass_resets_due_date_and_increments_count
    """
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        station_overrides={**EVENT_STATION, "code": "STN-S7", "name": "Inspection Station"},
    )
    station_id = scenario["station"]["id"]
    vessel = commission_vessel(
        station_id, **{**HIGH_VESSEL, "next_inspection_due_date": "2026-08-05"}
    )
    clock = set_clock("2026-08-10T00:00:00Z")
    assert clock["vessels_recomputed"] == 1, "the station's single vessel was re-derived"
    due = read_vessel(vessel["id"])
    assert due["inspection_status"] == "DUE", "2026-08-10 lies inside the 30-day grace"
    assert read_station(station_id)["safety_posture"] == "OPEN", (
        "a DUE vessel stays inside total_deliverable_kg"
    )

    passed = pass_inspection(vessel["id"], "2027-08-05")

    assert passed["inspection_status"] == "CURRENT"
    assert passed["inspection_count"] == 1
    assert passed["last_inspection_date"] == "2026-08-10"
    assert passed["next_inspection_due_date"] == "2027-08-05"
    assert passed["current_pressure_bar"] == pytest.approx(950.00, abs=0.01)
    assert passed["stored_mass_kg"] == pytest.approx(45.600, abs=0.001)
    entries = read_ledger(station_id, params={"limit": 100, "offset": 0})
    assert [entry["reason"] for entry in entries] == ["OPENING_BALANCE"], (
        "a PASS never vents, so no INSPECTION_VENT row is appended"
    )
    station = read_station(station_id)
    assert station["onsite_inventory_kg"] == pytest.approx(45.600, abs=0.001)
    assert station["high_bank_deliverable_kg"] == pytest.approx(36.000, abs=0.001)
    assert station["safety_posture"] == "OPEN"


# ─── ProductionLot: release is a join over two branches ──────────────────


def test_release_is_refused_while_the_carbon_branch_is_still_pending():
    """One error code covers both branches, and the same call succeeds once CI lands.

    "Then both branches must be complete — `qa_status` must be `PASSED` and
    `ci_status` must be `CERTIFIED` — and a lot missing either is refused with
    `ERR_QA_NOT_PASSED` (HTTP 422); the single code covers both an
    untested-or-indeterminate quality branch and an uncertified carbon branch."  On
    success it "moves the lot `PRODUCED → RELEASED`, records `released_by_user_id`
    from the acting `X-User-ID`, and increments the lot's `version` by one".

    Design: Corner/state_machines/production_lot_release_before_ci_certification_returns_qa_not_passed
    """
    set_clock("2026-08-01T00:00:00Z")
    scenario = setup_small_produced_lot()
    lot_id = scenario["lot"]["id"]
    record_purity_test(lot_id, sampled_at="2026-07-21T06:00:00Z")
    assert read_lot(lot_id)["qa_status"] == "PASSED"

    refused = api_client.release_production_lot(lot_id, COMPLIANCE)

    validate_error(refused, "ERR_QA_NOT_PASSED", expected_status=422)
    blocked = read_lot(lot_id)
    assert blocked["status"] == "PRODUCED"
    assert blocked["ci_status"] == "PENDING"
    assert blocked["released_by_user_id"] is None

    certified = validate_success(api_client.certify_lot_ci(lot_id, COMPLIANCE))
    released = validate_success(api_client.release_production_lot(lot_id, COMPLIANCE))

    assert certified["ci_status"] == "CERTIFIED"
    assert certified["ci_variant_applied"] == "ANNUAL_AVERAGE"
    assert certified["ci_certified_gco2e_per_mj"] == pytest.approx(85.92, abs=0.005)
    assert released["status"] == "RELEASED"
    assert released["released_by_user_id"] == "CA-1"
    assert released["version"] > blocked["version"]


# ─── Delivery: one terminal branch and one bounded loop ──────────────────


def test_a_quarantined_delivery_can_neither_be_rebooked_nor_offloaded():
    """PURITY_FAIL is the reason that makes the refusal terminal.

    "A `PURITY_FAIL` refusal takes the delivery `ARRIVED → QUARANTINED`, which is
    terminal and not reschedulable, and recomputes the station's
    `inbound_planned_kg`, `projected_available_kg` and `supply_alert`."  "Under either
    outcome no ledger entry is appended, because nothing was received, and the
    station's `version` is incremented by one."

    Design: Corner/state_machines/quarantined_delivery_cannot_be_rescheduled_or_offloaded
    """
    scenario = _yard_with_a_booked_delivery("STN-S3")
    station_id = scenario["station"]["id"]
    delivery_id = scenario["delivery"]["id"]
    arrive_delivery(delivery_id, at_clock="2026-08-02T01:00:00Z")
    quarantined = reject_delivery(delivery_id, station_id, reject_reason="PURITY_FAIL")
    assert quarantined["status"] == "QUARANTINED"

    refused_reschedule = _reschedule(
        delivery_id, "2026-08-03T00:00:00Z", "2026-08-03T06:00:00Z"
    )
    refused_offload = api_client.offload_delivery(
        delivery_id, make_station_operator_headers(station_id)
    )

    validate_error(refused_reschedule, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
    validate_error(refused_offload, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
    delivery = read_delivery(delivery_id)
    assert delivery["status"] == "QUARANTINED"
    assert delivery["reschedule_count"] == 0
    assert delivery["window_start"].startswith("2026-08-02T00:00:00")
    station = read_station(station_id)
    assert station["inbound_planned_kg"] == pytest.approx(0.000, abs=0.001), (
        "a QUARANTINED delivery has left the inbound set"
    )
    assert station["onsite_inventory_kg"] == pytest.approx(120.000, abs=0.001), (
        "the opening balance only — nothing was received"
    )


def test_the_third_reschedule_is_refused_and_parks_the_delivery_in_rejected():
    """The rebooking loop is bounded by a counter, and the ceiling ends it by error.

    "Two guards apply: the delivery's `reschedule_count` must be strictly less than
    the reschedule ceiling of two, so a delivery that has already been rebooked twice
    is refused with `ERR_RESCHEDULE_LIMIT_REACHED` (HTTP 409); and the new window must
    not exhaust the station's `offload_bay_count` under exactly the aggregate-capacity
    rule described for booking, failing with `ERR_OFFLOAD_BAY_CONFLICT`."

    Design: Corner/state_machines/delivery_third_reschedule_rejected_at_max_reschedules
    """
    scenario = _yard_with_a_booked_delivery("STN-S4")
    station_id = scenario["station"]["id"]
    delivery_id = scenario["delivery"]["id"]
    rounds = [
        ("2026-08-02T01:00:00Z", "DOCUMENTATION", "2026-08-03T00:00:00Z", "2026-08-03T06:00:00Z"),
        ("2026-08-03T01:00:00Z", "SEAL_BROKEN", "2026-08-04T00:00:00Z", "2026-08-04T06:00:00Z"),
    ]
    counts = []
    for arrive_at, reason, next_start, next_end in rounds:
        arrive_delivery(delivery_id, at_clock=arrive_at)
        reject_delivery(delivery_id, station_id, reject_reason=reason)
        rebooked = validate_success(_reschedule(delivery_id, next_start, next_end))
        counts.append(rebooked["reschedule_count"])
    arrive_delivery(delivery_id, at_clock="2026-08-04T01:00:00Z")
    reject_delivery(delivery_id, station_id, reject_reason="DOCUMENTATION")
    assert counts == [1, 2], "the two permitted iterations of the loop"

    response = _reschedule(delivery_id, "2026-08-05T00:00:00Z", "2026-08-05T06:00:00Z")

    validate_error(response, "ERR_RESCHEDULE_LIMIT_REACHED", expected_status=409)
    delivery = read_delivery(delivery_id)
    assert delivery["status"] == "REJECTED", "the row is parked, not auto-terminated"
    assert delivery["reschedule_count"] == 2, "the failed attempt does not increment"
    assert delivery["window_start"].startswith("2026-08-04T00:00:00")
    assert read_station(station_id)["inbound_planned_kg"] == pytest.approx(
        0.000, abs=0.001
    ), "a REJECTED delivery sits outside the inbound set"


def test_an_accepted_offload_writes_two_ledger_rows_and_consumes_the_lot():
    """The receipt is credited, the heel is only recorded, and the lot tips over 90 %.

    "at the same time two ledger entries are appended — a `DELIVERY_RECEIPT` entry
    whose `delta_kg` is the positive `net_receipt_kg` with `source_ref_type` of
    `DELIVERY`, and immediately after it a second entry whose `delta_kg` is 0.000 and
    whose `reason` is `HEEL_RETURNED` for a tube trailer or `BOILOFF_LOSS` for a
    liquid tanker, recording the loss term for audit without moving inventory."  Then
    "When an offload lifts that figure to at least ninety percent of the lot's
    `mass_kg` — the consumption fraction is 0.900, applied at three decimal places —
    the lot moves `RELEASED → CONSUMED`, which is terminal, and no further delivery
    may reference it."

    Design: Corner/state_machines/accepted_offload_syncs_the_ledger_and_consumes_the_lot
    """
    scenario = setup_station(
        clock="2026-08-01T00:00:00Z",
        station_overrides={**YARD_STATION, "code": "STN-S8", "name": "Offload Yard"},
    )
    station_id = scenario["station"]["id"]
    vessel = commission_vessel(
        station_id, **{**LOW_VESSEL, "initial_pressure_bar": 100.00}
    )
    add_emergency_responders(station_id, count=2)
    lot_scenario = setup_small_released_lot(
        lot_overrides={"mass_kg": 280.000, "energy_consumed_kwh": 14560.0}
    )
    lot_id = lot_scenario["lot"]["id"]
    delivery = book_tube_trailer_delivery(
        station_id,
        lot_id,
        vessel["id"],
        planned_kg=280.000,
        window_start="2026-08-02T00:00:00Z",
        window_end="2026-08-02T06:00:00Z",
        departed_at="2026-08-01T12:00:00Z",
        trailer_water_volume_l=2500.0,
        trailer_final_pressure_bar=100.00,
    )

    arrived = arrive_delivery(delivery["id"], at_clock="2026-08-02T02:00:00Z")
    accepted = validate_success(
        api_client.offload_delivery(
            delivery["id"], make_station_operator_headers(station_id)
        )
    )

    assert arrived["transit_hours"] == pytest.approx(14.000, abs=0.001)
    assert arrived["heel_kg"] == pytest.approx(20.000, abs=0.001)
    assert arrived["boiloff_kg"] == pytest.approx(0.000, abs=0.001)
    assert arrived["net_receipt_kg"] == pytest.approx(260.000, abs=0.001)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_at"].startswith("2026-08-02T02:00:00")
    reread_vessel = read_vessel(vessel["id"])
    assert reread_vessel["current_pressure_bar"] == pytest.approx(750.00, abs=0.01)
    assert reread_vessel["stored_mass_kg"] == pytest.approx(300.000, abs=0.001)
    entries = read_ledger(station_id, params={"limit": 100, "offset": 0})
    assert [entry["reason"] for entry in entries] == [
        "OPENING_BALANCE",
        "DELIVERY_RECEIPT",
        "HEEL_RETURNED",
    ]
    receipt = find_ledger_entry(entries, "DELIVERY_RECEIPT")
    assert receipt["delta_kg"] == pytest.approx(260.000, abs=0.001)
    assert receipt["resulting_onsite_kg"] == pytest.approx(300.000, abs=0.001)
    assert receipt["source_ref_type"] == "DELIVERY"
    heel = find_ledger_entry(entries, "HEEL_RETURNED")
    assert heel["delta_kg"] == pytest.approx(0.000, abs=0.001), (
        "the heel is recorded, never credited"
    )
    assert heel["resulting_onsite_kg"] == pytest.approx(300.000, abs=0.001)
    station = read_station(station_id)
    assert station["onsite_inventory_kg"] == pytest.approx(300.000, abs=0.001)
    assert station["total_deliverable_kg"] == pytest.approx(260.000, abs=0.001)
    assert station["inbound_planned_kg"] == pytest.approx(0.000, abs=0.001)
    lot = read_lot(lot_id)
    assert lot["accepted_delivered_kg"] == pytest.approx(260.000, abs=0.001)
    assert lot["status"] == "CONSUMED", "260.000 clears 280.000 times 0.900"
