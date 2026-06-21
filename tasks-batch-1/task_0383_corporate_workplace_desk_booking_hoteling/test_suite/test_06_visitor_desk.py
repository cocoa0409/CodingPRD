"""Visitor desk: the cyclic host-review loop, the complete-frees-seat side
effect, and an invalid-state resubmit rejection.

Translates queue-A difficulty rule `non_linear_state_machine`
(visitor_pass_cyclic_changes_requested_loop) and queue-B Corner `state_machines`
visitor-pass instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_employee_headers,
    create_visitor_pass_payload, create_reservation_payload,
)
from test_helpers import fixtures as fx

FM = TEST_USERS["facility_manager_headers"]
RECEPTION = TEST_USERS["receptionist_headers"]


# ---------------------------------------------------------------------------
# Difficulty A: non_linear_state_machine — visitor pass cyclic loop
# ---------------------------------------------------------------------------
def test_visitor_pass_changes_requested_resubmit_cycle(api):
    """PRD §3.10: "From REQUESTED, the host employee — whose id must equal the
    acting X-User-ID — may request changes, moving the pass to CHANGES_REQUESTED
    and freeing the held seat window so it can be amended. From CHANGES_REQUESTED,
    the receptionist resubmits an amended pass, optionally supplying a new
    start_minute, end_minute, or booking_date; this returns the pass to REQUESTED
    and re-holds a seat window for the amended visit, re-running the overlap check
    on the new window. This REQUESTED to CHANGES_REQUESTED to REQUESTED cycle may
    repeat any number of rounds."

    Design: Difficulty/non_linear_state_machine/visitor_pass_cyclic_changes_requested_loop
    """
    env, vp = fx.setup_visitor_pass(booking_date="2026-06-24", start_minute=600, end_minute=720, level=5)
    host_id = env["host"]["id"]
    s1 = get_success_data(api.visitor_pass_request_changes(vp["id"], make_employee_headers(host_id)))
    assert s1["status"] == "CHANGES_REQUESTED"
    s2 = get_success_data(api.visitor_pass_resubmit(vp["id"], {"start_minute": 660, "end_minute": 780}, RECEPTION))
    assert s2["status"] == "REQUESTED"
    s3 = get_success_data(api.visitor_pass_request_changes(vp["id"], make_employee_headers(host_id)))
    assert s3["status"] == "CHANGES_REQUESTED"


def test_visitor_pass_request_changes_frees_seat_window(api):
    """PRD §3.10: "the host employee ... may request changes, moving the pass to
    CHANGES_REQUESTED and freeing the held seat window so it can be amended."

    Design: Difficulty/non_linear_state_machine/visitor_pass_cyclic_changes_requested_loop
    """
    env, vp = fx.setup_visitor_pass(booking_date="2026-06-24", start_minute=600, end_minute=720, level=52)
    host_id = env["host"]["id"]
    seat_id = env["seat"]["id"]
    get_success_data(api.visitor_pass_request_changes(vp["id"], make_employee_headers(host_id)))
    # the seat window is now free: an employee reservation in the same window succeeds
    booker = fx.create_employee(team_code="ENG")
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=booker["id"], resource_type="SEAT", seat_id=seat_id,
            booking_date="2026-06-24", start_minute=600, end_minute=720,
            expected_seat_version=fx.seat_version(seat_id)),
        make_employee_headers(booker["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["occupancy_status"] == "BOOKED"


# ---------------------------------------------------------------------------
# Corner: state_machines — visitor pass side effect / invalid state
# ---------------------------------------------------------------------------
def test_visitor_pass_complete_frees_seat_window(api):
    """PRD §3.10: "From APPROVED, the receptionist checks the visitor in, moving
    the pass to CHECKED_IN. From CHECKED_IN, the receptionist completes the visit,
    moving it to COMPLETED and freeing the seat window."

    Design: Corner/state_machines/visitor_pass_complete_frees_seat_window
    """
    env, vp = fx.setup_visitor_pass(booking_date="2026-08-06", start_minute=600, end_minute=720, level=9)
    host_id = env["host"]["id"]
    seat_id = env["seat"]["id"]
    get_success_data(api.visitor_pass_approve(vp["id"], make_employee_headers(host_id)))
    get_success_data(api.visitor_pass_check_in(vp["id"], RECEPTION))
    get_success_data(api.visitor_pass_complete(vp["id"], RECEPTION))
    # the seat window is freed, so a reservation on the same seat/date/window succeeds
    resp = api.create_reservation(
        create_reservation_payload(
            employee_id=host_id, resource_type="SEAT", seat_id=seat_id,
            booking_date="2026-08-06", start_minute=600, end_minute=720,
            expected_seat_version=fx.seat_version(seat_id)),
        make_employee_headers(host_id))
    data = validate_success(resp, expected_status=201)
    assert data["occupancy_status"] == "BOOKED"


def test_visitor_pass_resubmit_from_requested_invalid_state(api):
    """PRD §3.10: "Any visitor-pass transition attempted from a status that does
    not permit it is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/visitor_pass_resubmit_from_requested_invalid_state
    """
    env, vp = fx.setup_visitor_pass(booking_date="2026-08-09", start_minute=600, end_minute=720, level=12)
    # the pass is still REQUESTED (resubmit is only valid from CHANGES_REQUESTED)
    resp = api.visitor_pass_resubmit(vp["id"], {"start_minute": 630, "end_minute": 750}, RECEPTION)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
