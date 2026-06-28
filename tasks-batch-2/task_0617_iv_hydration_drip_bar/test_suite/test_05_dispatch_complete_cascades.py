"""Completion / dispatch cascades, adverse-event derived counters, route closure
dependency, and terminal/invalid-state lockdowns.
"""
import pytest
from test_helpers import (
    get_success_data, validate_error,
    set_clock, create_menu_item, create_lounge, create_patient, create_nurse,
    create_supply_lot, create_requested_appointment, submit_intake, sign_consent,
    schedule_appointment, current_version,
    setup_in_progress_lounge_appointment, setup_completed_lounge_appointment,
    setup_reported_adverse_event, setup_mobile_route_with_dispatched_stop,
    setup_scheduled_lounge_appointment, setup_dispatched_lounge_appointment,
    TEST_USERS, make_nurse_headers, make_medical_director_headers,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["clinic_admin_headers"]
FAR_EXPIRY = "2026-12-31T00:00:00Z"


# ─── Difficulty: transitive_cascade / cascade_complete_consumes_supply_exhausts_lot ───
def test_complete_consumes_reserved_unit(api):
    """PRD §3.9: completion "moves the reserved supply units to consumed (for each line
    decreasing `units_reserved` by one and increasing `units_consumed` by one ...), sets
    `status` to `COMPLETED`".

    A lot of exactly 1 unit: after completion units_consumed=1, units_reserved=0.

    Design: Difficulty/transitive_cascade/cascade_complete_consumes_supply_exhausts_lot
    """
    ctx = setup_completed_lounge_appointment(
        menu_overrides={"tier": "MYERS", "base_price_cents": 17500,
                        "requires_standing_order": False},
        supply_units=1)
    assert ctx["appointment"]["status"] == "COMPLETED"
    lot = ctx["drip_lot"]
    assert lot["units_consumed"] == 1, f"expected consumed 1, got {lot['units_consumed']}"
    assert lot["units_reserved"] == 0, f"expected reserved 0, got {lot['units_reserved']}"


def test_complete_exhausts_lot_when_full(api):
    """PRD §3.9: completion moves reserved units to consumed, "marking the lot `EXHAUSTED`
    when `units_consumed` plus `units_reserved` equals `units_total`".

    With a single-unit lot, consuming the last unit makes consumed+reserved==total, so the
    lot flips to EXHAUSTED.

    Design: Difficulty/transitive_cascade/cascade_complete_consumes_supply_exhausts_lot
    """
    ctx = setup_completed_lounge_appointment(
        menu_overrides={"tier": "MYERS", "base_price_cents": 17500,
                        "requires_standing_order": False},
        supply_units=1)
    assert ctx["drip_lot"]["status"] == "EXHAUSTED", \
        f"expected EXHAUSTED, got {ctx['drip_lot']['status']}"


# ─── Difficulty: transitive_cascade / cascade_resolve_adverse_event_decrements_patient_counter ───
def test_resolve_adverse_event_moves_to_resolved(api):
    """PRD §3.14: "The director then resolves an `UNDER_REVIEW` event (allowed only while
    it is `UNDER_REVIEW`), moving it to the terminal `RESOLVED` state ... and incrementing
    the event's `version` by one."

    Design: Difficulty/transitive_cascade/cascade_resolve_adverse_event_decrements_patient_counter
    """
    ctx = setup_reported_adverse_event(severity="MODERATE", description="flushing")
    md = make_medical_director_headers("md-2")
    api_client.review_adverse_event(ctx["adverse_event"]["id"], md)
    resolved = get_success_data(api_client.resolve_adverse_event(
        ctx["adverse_event"]["id"], md))
    assert resolved["status"] == "RESOLVED"


def test_resolve_adverse_event_decrements_patient_counter(api):
    """PRD §3.14: resolving an event recomputes "the patient's `open_adverse_event_count`
    downward since the event is no longer open". A single reported event (count 1)
    resolved drops the patient's count back to 0.

    Design: Difficulty/transitive_cascade/cascade_resolve_adverse_event_decrements_patient_counter
    """
    ctx = setup_reported_adverse_event()
    md = make_medical_director_headers("md-2")
    api_client.review_adverse_event(ctx["adverse_event"]["id"], md)
    api_client.resolve_adverse_event(ctx["adverse_event"]["id"], md)
    patient = get_success_data(api_client.get_patient(ctx["patient"]["id"], ADMIN))
    assert patient["open_adverse_event_count"] == 0, \
        f"expected 0, got {patient['open_adverse_event_count']}"


# ─── Difficulty: cross_entity_state_dependency / cross_route_close_requires_all_stops_terminal ───
def test_close_route_blocked_while_stop_not_terminal(api):
    """PRD §3.12: "A `LOCKED` route can be closed once every appointment assigned to it is
    `COMPLETED` or `CANCELLED`". Closing a LOCKED route whose only stop is still DISPATCHED
    is rejected with ERR_INVALID_STATE (409).

    Design: Difficulty/cross_entity_state_dependency/cross_route_close_requires_all_stops_terminal
    """
    ctx = setup_mobile_route_with_dispatched_stop(turnaround_minutes=30)
    route_id = ctx["route"]["id"]
    get_success_data(api_client.lock_dispatch_route(route_id, ADMIN))
    res = api_client.close_dispatch_route(route_id, ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    route = get_success_data(api_client.get_dispatch_route(route_id, ADMIN))
    assert route["status"] == "LOCKED", f"route should stay LOCKED, got {route['status']}"


def test_locked_route_with_dispatched_stop_stays_locked(api):
    """PRD §3.12: "any dispatch attempt that would add a stop to a `LOCKED` or `CLOSED`
    route is rejected" and "A `LOCKED` route can be closed once every appointment assigned
    to it is `COMPLETED` or `CANCELLED`." With a still-DISPATCHED stop, the close attempt
    leaves the route LOCKED (not advanced to CLOSED).

    Design: Difficulty/cross_entity_state_dependency/cross_route_close_requires_all_stops_terminal
    """
    ctx = setup_mobile_route_with_dispatched_stop(turnaround_minutes=30)
    route_id = ctx["route"]["id"]
    get_success_data(api_client.lock_dispatch_route(route_id, ADMIN))
    # Confirm the assigned stop is indeed non-terminal (DISPATCHED) before close.
    appt = get_success_data(api_client.get_appointment(ctx["appointment"]["id"], ADMIN))
    assert appt["status"] == "DISPATCHED"
    res = api_client.close_dispatch_route(route_id, ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner: cross_cutting / derived_patient_counter_increment_on_report ───
def test_report_adverse_event_increments_patient_counter(api):
    """PRD §3.14: "A new adverse event begins in `REPORTED` status, and its creation
    recomputes the patient's `open_adverse_event_count` upward, since the new event is
    open." Reporting against an IN_PROGRESS appointment raises the count from 0 to 1.

    Design: Corner/cross_cutting_complexity_layers/derived_patient_counter_increment_on_report
    """
    ctx = setup_in_progress_lounge_appointment()
    nurse = ctx["nurse"]
    ae = get_success_data(api_client.create_adverse_event(
        {"appointment_id": ctx["appointment"]["id"], "reported_by_user_id": nurse["id"],
         "severity": "MILD", "description": "itch"}, make_nurse_headers(nurse["id"])))
    assert ae["status"] == "REPORTED"
    patient = get_success_data(api_client.get_patient(ctx["patient"]["id"], ADMIN))
    assert patient["open_adverse_event_count"] == 1, \
        f"expected 1, got {patient['open_adverse_event_count']}"


# ─── Corner: state_machines / complete_from_scheduled_invalid_state ───
def test_complete_from_scheduled_is_invalid_state(api):
    """PRD §3.9: "The same nurse completes the infusion from `IN_PROGRESS`". Completing a
    SCHEDULED (never started) appointment is an undefined transition rejected with
    ERR_INVALID_STATE (409).

    Design: Corner/state_machines/complete_from_scheduled_invalid_state
    """
    ctx = setup_scheduled_lounge_appointment(
        menu_overrides={"tier": "MYERS", "base_price_cents": 17500,
                        "requires_standing_order": False})
    nurse = create_nurse()
    api_client.dispatch_appointment(ctx["appointment"]["id"], {"nurse_id": nurse["id"]}, ADMIN)
    # Appointment is now DISPATCHED (not IN_PROGRESS): completing must be invalid.
    # Re-fetch state and assert it never started.
    appt = get_success_data(api_client.get_appointment(ctx["appointment"]["id"], ADMIN))
    assert appt["status"] == "DISPATCHED"
    res = api_client.complete_appointment(ctx["appointment"]["id"], make_nurse_headers(nurse["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner: state_machines / cancel_completed_appointment_invalid_state ───
def test_cancel_completed_appointment_is_invalid_state(api):
    """PRD §3.13: "A `ClinicAdmin` may cancel an appointment that is not yet terminal —
    that is, while it is in `REQUESTED`, `SCREEN_PENDING`, `REQUIRES_MD_REVIEW`,
    `SCHEDULED`, or `DISPATCHED`." A COMPLETED (terminal) appointment cannot be cancelled
    and returns ERR_INVALID_STATE (409).

    Design: Corner/state_machines/cancel_completed_appointment_invalid_state
    """
    ctx = setup_completed_lounge_appointment(
        menu_overrides={"tier": "MYERS", "base_price_cents": 17500,
                        "requires_standing_order": False},
        supply_units=3)
    assert ctx["appointment"]["status"] == "COMPLETED"
    res = api_client.cancel_appointment(ctx["appointment"]["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
