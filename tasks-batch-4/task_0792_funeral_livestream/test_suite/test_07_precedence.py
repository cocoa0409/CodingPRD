"""Validation precedence conflicts — the fixed order of checks in PRD §2.6
decides which error a doubly-invalid request returns.

Queue-A priority_pair_validation_conflict instances.
"""
from test_helpers import (
    TEST_USERS,
    validate_error, ApiErrorId,
    setup_scheduled_order, setup_home_and_venue,
    create_operator, set_operator_duty, create_assignment, create_order, get_home,
    create_camera_assignment_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# --- state (P6) beats fiscal credit check (P11) ------------------------------
def test_reschedule_reports_state_error_over_credit_error(api):
    """PRD §2.6: "the first check that fails determines the error returned."
    PRD §2.6: "6. The target resource or axis is in the correct state for the
    requested transition (HTTP 409, state-specific error)."
    PRD §2.6: "11. The funeral home holds sufficient stream credits to schedule
    (otherwise `ERR_INSUFFICIENT_STREAM_CREDITS`, HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/schedule_state_precondition_beats_credit_fiscal
    """
    base = setup_scheduled_order(
        initial_credits=1,
        scheduled_start="2026-06-09T10:00:00Z", scheduled_end="2026-06-09T11:00:00Z",
    )
    # Order is now SCHEDULED (fails DRAFT check) and the home has 0 credits
    # (would also fail the credit check); the earlier state check must win.
    resp = api.transition_service_order(base["order"]["id"], {"action": "SCHEDULE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DRAFT)


def test_rejected_reschedule_leaves_credit_balance_unchanged(api):
    """PRD §3.6: "On success the transition consumes one stream credit from the
    home and computes the forward estimate `estimated_cost_cents` from the
    scheduled duration".

    Design: Difficulty/priority_pair_validation_conflict/schedule_state_precondition_beats_credit_fiscal
    """
    base = setup_scheduled_order(
        initial_credits=1,
        scheduled_start="2026-06-09T10:00:00Z", scheduled_end="2026-06-09T11:00:00Z",
    )
    api.transition_service_order(base["order"]["id"], {"action": "SCHEDULE"}, ADMIN)
    # The rejected second SCHEDULE consumes no further credit.
    assert get_home(base["home"]["id"])["stream_credit_balance"] == 0


# --- safety operator-on-duty (P8) beats temporal overlap (P9) ----------------
def _off_duty_operator_with_overlap():
    """Operator assigned to order A (10:00-12:00) while ON_DUTY, then set OFF_DUTY;
    order B (11:00-13:00) overlaps A. Returns (operator, order_b)."""
    base = setup_home_and_venue(initial_credits=0)
    op = create_operator(base["home"]["id"], skill="CAMERA")
    set_operator_duty(op["id"], "ON_DUTY")
    order_a = create_order(base["home"]["id"], base["venue"]["id"], decedent_name="A Aaa",
                           scheduled_start="2026-06-10T10:00:00Z",
                           scheduled_end="2026-06-10T12:00:00Z")
    create_assignment(order_a["id"], op["id"], "CAMERA")
    set_operator_duty(op["id"], "OFF_DUTY")
    order_b = create_order(base["home"]["id"], base["venue"]["id"], decedent_name="B Bbb",
                           scheduled_start="2026-06-10T11:00:00Z",
                           scheduled_end="2026-06-10T13:00:00Z")
    return op, order_b


def test_camera_assign_reports_off_duty_over_time_conflict(api):
    """PRD §2.6: "the first check that fails determines the error returned."
    PRD §2.6: "8. The target operator is on duty when a camera assignment is
    created (otherwise `ERR_OPERATOR_OFF_DUTY`, HTTP 409)."
    PRD §2.6: "9. No resource time conflict exists (HTTP 409, see §3)."

    Design: Difficulty/priority_pair_validation_conflict/camera_assign_operator_safety_beats_temporal_overlap
    """
    op, order_b = _off_duty_operator_with_overlap()
    payload = create_camera_assignment_payload(order_b["id"], op["id"], "CAMERA")
    validate_error(api.create_camera_assignment(payload, ADMIN), ApiErrorId.ERR_OPERATOR_OFF_DUTY)


def test_time_conflict_surfaces_once_operator_is_on_duty(api):
    """PRD §3.5: "the operator must be free during the service: an assignment
    covers its order's planned window from `scheduled_start` to `scheduled_end`,
    and if that window overlaps the window of any other `ASSIGNED` assignment for
    the same operator, the request is refused with `ERR_OPERATOR_TIME_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/camera_assign_operator_safety_beats_temporal_overlap
    """
    op, order_b = _off_duty_operator_with_overlap()
    set_operator_duty(op["id"], "ON_DUTY")  # clear the safety failure; overlap remains
    payload = create_camera_assignment_payload(order_b["id"], op["id"], "CAMERA")
    validate_error(api.create_camera_assignment(payload, ADMIN),
                   ApiErrorId.ERR_OPERATOR_TIME_CONFLICT)
