"""Valid and invalid state transitions across parcel, route, stop, appointment.

Queue B (Corner): section state_machines (non-stub instances).
"""
import pytest
from test_helpers import validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx

DM = TEST_USERS["dispatch_manager_headers"]
SA = TEST_USERS["sort_associate_headers"]
CSA = TEST_USERS["customer_service_agent_headers"]


def test_sort_parcel_not_received_rejected(api):
    """PRD §3.1: "The parcel must currently be in `RECEIVED` (otherwise
    `ERR_PARCEL_NOT_RECEIVED`), and the target center must be `OPEN`".

    Design: Corner/state_machines/sort_parcel_not_received_rejected
    """
    center = fx.create_center(name="HubC3", sort_capacity=10)
    parcel = fx.create_sorted_parcel(center["id"], weight_kg=1.0)
    resp = api.sort_parcel(parcel["id"], {"center_id": center["id"]}, SA)
    validate_error(resp, ApiErrorId.ERR_PARCEL_NOT_RECEIVED)


def test_stop_create_parcel_not_sorted_rejected(api):
    """PRD §3.3: "The referenced parcel must currently be in `SORTED` status,
    otherwise the add is rejected with `ERR_PARCEL_NOT_SORTED`."

    Design: Corner/state_machines/stop_create_parcel_not_sorted_rejected
    """
    center = fx.create_center(name="HubC4", sort_capacity=10)
    driver = fx.create_driver(name="Dy", vehicle_capacity_kg=50)
    parcel = fx.create_parcel(weight_kg=1.0)  # RECEIVED, never sorted
    route = fx.create_route(driver["id"], center["id"], service_date="2026-07-03")
    resp = api.create_stop(
        {"route_id": route["id"], "parcel_id": parcel["id"], "sequence": 1,
         "window_start_min": 540, "window_end_min": 600}, DM,
    )
    validate_error(resp, ApiErrorId.ERR_PARCEL_NOT_SORTED)


def test_dispatch_empty_route_rejected(api):
    """PRD §3.3: "The route must be in `PLANNING` (otherwise
    `ERR_ROUTE_NOT_PLANNING`) and must hold at least one non-`CANCELLED` stop
    (otherwise `ERR_ROUTE_EMPTY`)."

    Design: Corner/state_machines/dispatch_empty_route_rejected
    """
    center = fx.create_center(name="HubC5", sort_capacity=10)
    driver = fx.create_driver(name="De", vehicle_capacity_kg=50)
    route = fx.create_route(driver["id"], center["id"], service_date="2026-07-04")
    rv = fx.current_route_version(route["id"])
    resp = api.dispatch_route(route["id"], {"expected_route_version": rv}, DM)
    validate_error(resp, ApiErrorId.ERR_ROUTE_EMPTY)


def test_complete_with_open_stops_rejected(api):
    """PRD §3.3: "no stop may still be open — that is, no stop may be in
    `OUT_FOR_DELIVERY`, `ATTEMPTED`, or `REDELIVERY_SCHEDULED`; if any open stop
    remains, completion is rejected with `ERR_OPEN_STOPS_REMAIN`."

    Design: Corner/state_machines/complete_with_open_stops_rejected
    """
    s = fx.setup_dispatched_route_with_stop(name_suffix="op", service_date="2026-07-05")
    resp = api.complete_route(s["route"]["id"], DM)
    validate_error(resp, ApiErrorId.ERR_OPEN_STOPS_REMAIN)


def test_complete_route_after_delivery_succeeds(api):
    """PRD §3.3: "Completing a route advances it from `DISPATCHED` to
    `COMPLETED`. The route must be in `DISPATCHED` (otherwise
    `ERR_ROUTE_NOT_DISPATCHED`), and no stop may still be open".

    Design: Corner/state_machines/complete_route_after_delivery_succeeds
    """
    s = fx.setup_dispatched_route_with_stop(name_suffix="cmp", service_date="2026-07-06")
    fx.log_attempt(s["stop"]["id"], s["driver"]["id"], "DELIVERED")
    data = validate_success(api.complete_route(s["route"]["id"], DM))
    assert data["status"] == "COMPLETED"


def test_cancel_completed_route_terminal_lockdown(api):
    """PRD §3.3: "Cancelling a route is permitted only while it is in `PLANNING`;
    otherwise the request is rejected with `ERR_ROUTE_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_completed_route_terminal_lockdown
    """
    s = fx.setup_dispatched_route_with_stop(name_suffix="tl", service_date="2026-07-07")
    fx.log_attempt(s["stop"]["id"], s["driver"]["id"], "DELIVERED")
    get_success_data(api.complete_route(s["route"]["id"], DM))
    resp = api.cancel_route(s["route"]["id"], DM)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_CANCELLABLE)


def test_reschedule_non_attempted_stop_rejected(api):
    """PRD §3.5: "The stop must be in `ATTEMPTED`, otherwise the request is
    rejected with `ERR_STOP_NOT_ATTEMPTED`."

    Design: Corner/state_machines/reschedule_non_attempted_stop_rejected
    """
    s = fx.setup_dispatched_route_with_stop(name_suffix="na", service_date="2026-07-08")
    resp = api.reschedule_stop(s["stop"]["id"], DM)
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_ATTEMPTED)


def test_attempt_on_pending_stop_rejected(api):
    """PRD §3.4: "The stop must be in either `OUT_FOR_DELIVERY` or
    `REDELIVERY_SCHEDULED`; an attempt logged against a stop in any other state
    is rejected with `ERR_STOP_NOT_OUT_FOR_DELIVERY`."

    Design: Corner/state_machines/attempt_on_pending_stop_rejected
    """
    s = fx.setup_planning_route_with_stop(name_suffix="pe", service_date="2026-07-09")
    resp = api.create_attempt(
        s["stop"]["id"], {"outcome": "NO_ONE_HOME"},
        fx.make_driver_headers(s["driver"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STOP_NOT_OUT_FOR_DELIVERY)


def test_appointment_reject_transition(api):
    """PRD §3.7: "A `CustomerServiceAgent` may reject a requested appointment,
    moving it from `REQUESTED` to `REJECTED`".

    Design: Corner/state_machines/appointment_reject_transition
    """
    s = fx.setup_planning_route_with_stop(name_suffix="ar", service_date="2026-07-10")
    appt = fx.create_appointment(s["stop"]["id"], requested_start_min=700, requested_end_min=760)
    data = validate_success(api.reject_appointment(appt["id"], CSA))
    assert data["status"] == "REJECTED"
    stop_d = validate_success(api.get_stop(s["stop"]["id"], DM))
    assert stop_d["window_start_min"] == 540, "rejected appointment must not move the window"


def test_appointment_apply_no_conflict_moves_window(api):
    """PRD §3.7: "On a successful apply, the appointment moves from `REQUESTED`
    to `APPLIED`, the target stop's `window_start_min` and `window_end_min` are
    overwritten with the appointment's `requested_start_min` and
    `requested_end_min`".

    Design: Corner/state_machines/appointment_apply_no_conflict_moves_window
    """
    s = fx.setup_planning_route_with_stop(name_suffix="aa", service_date="2026-07-11")
    appt = fx.create_appointment(s["stop"]["id"], requested_start_min=700, requested_end_min=760)
    data = validate_success(api.apply_appointment(appt["id"], CSA))
    assert data["status"] == "APPLIED"
    stop_d = validate_success(api.get_stop(s["stop"]["id"], DM))
    assert stop_d["window_start_min"] == 700
    assert stop_d["window_end_min"] == 760


def test_appointment_apply_on_delivered_stop_window_locked(api):
    """PRD §3.7: "The target stop must be in `PENDING`, `OUT_FOR_DELIVERY`, or
    `REDELIVERY_SCHEDULED`; if the stop is in any other (terminal or otherwise
    locked) state, the apply is rejected with `ERR_STOP_WINDOW_LOCKED`."

    Design: Corner/state_machines/appointment_apply_on_delivered_stop_window_locked
    """
    s = fx.setup_dispatched_route_with_stop(name_suffix="wl", service_date="2026-07-12")
    appt = fx.create_appointment(s["stop"]["id"], requested_start_min=700, requested_end_min=760)
    fx.log_attempt(s["stop"]["id"], s["driver"]["id"], "DELIVERED")
    resp = api.apply_appointment(appt["id"], CSA)
    validate_error(resp, ApiErrorId.ERR_STOP_WINDOW_LOCKED)
