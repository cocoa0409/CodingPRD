"""Class sessions and enrollments: cancel-refund cascade, waitlist promotion,
capacity boundary, schedule-buffer conflicts, and session lifecycle side effects.
"""
from test_helpers import (
    TEST_USERS,
    enroll,
    new_class_session,
    new_customer,
    validate_error,
    validate_success,
)

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


# ─────────────── depth-3 session-cancel refund cascade ─────────────────────
def test_session_cancel_cancels_all_enrollments(api):
    """PRD §3.6: "every enrollment in `ENROLLED` or `WAITLISTED` becomes
    `CANCELLED`, and each such cancellation refunds that enrollment's
    `fee_charged_cents` to its customer's `store_credit_cents` — a three-level
    cascade from session to enrollments to customers."

    Design: Difficulty/transitive_cascade/class_session_cancel_refund_cascade_depth3
    """
    c1 = new_customer("Cust One", "c1@example.com", credit=20000)
    c2 = new_customer("Cust Two", "c2@example.com", credit=20000)
    session = new_class_session(title="Intro to Quilting", machine_type="SEWING",
                                start_at="2026-08-01T10:00:00Z", end_at="2026-08-01T12:00:00Z",
                                capacity=5, fee_cents=5000)
    e1 = enroll(session["id"], c1["id"])
    e2 = enroll(session["id"], c2["id"])
    cancelled = validate_success(api.cancel_class_session(session["id"], SM), 200)
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api.get_enrollment(e1["id"], SA), 200)["status"] == "CANCELLED"
    assert validate_success(api.get_enrollment(e2["id"], SA), 200)["status"] == "CANCELLED"


def test_session_cancel_refunds_each_enrollee(api):
    """PRD §3.6: "every enrollment in `ENROLLED` or `WAITLISTED` becomes
    `CANCELLED`, and each such cancellation refunds that enrollment's
    `fee_charged_cents` to its customer's `store_credit_cents` — a three-level
    cascade from session to enrollments to customers."

    Design: Difficulty/transitive_cascade/class_session_cancel_refund_cascade_depth3
    """
    c1 = new_customer("Cust One", "c1@example.com", credit=20000)
    c2 = new_customer("Cust Two", "c2@example.com", credit=20000)
    session = new_class_session(title="Intro to Quilting", machine_type="SEWING",
                                start_at="2026-08-01T10:00:00Z", end_at="2026-08-01T12:00:00Z",
                                capacity=5, fee_cents=5000)
    enroll(session["id"], c1["id"])
    enroll(session["id"], c2["id"])
    api.cancel_class_session(session["id"], SM)
    assert validate_success(api.get_customer(c1["id"], SA), 200)["store_credit_cents"] == 20000
    assert validate_success(api.get_customer(c2["id"], SA), 200)["store_credit_cents"] == 20000


# ─────────────── depth-2 enrollment-cancel waitlist promotion ──────────────
def test_cancel_enrolled_promotes_earliest_waitlisted(api):
    """PRD §3.6: "then promotes the earliest-created `WAITLISTED` enrollment on that
    session — ordered by `created_at` ascending — into the freed seat, decrementing
    `waitlist_count` by one and incrementing `enrolled_count` by one."

    Design: Difficulty/transitive_cascade/enrollment_cancel_waitlist_promotion_depth2
    """
    c1 = new_customer("WL One", "w1@example.com")
    c2 = new_customer("WL Two", "w2@example.com")
    c3 = new_customer("WL Three", "w3@example.com")
    session = new_class_session(title="Serger Basics", machine_type="SEWING",
                                start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T12:00:00Z",
                                capacity=1, fee_cents=0)
    e1 = enroll(session["id"], c1["id"])
    e2 = enroll(session["id"], c2["id"])
    e3 = enroll(session["id"], c3["id"])
    cancelled = validate_success(api.cancel_enrollment(e1["id"], SA), 200)
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api.get_enrollment(e2["id"], SA), 200)["status"] == "ENROLLED"
    assert validate_success(api.get_enrollment(e3["id"], SA), 200)["status"] == "WAITLISTED"


def test_cancel_enrolled_keeps_seat_counts_consistent(api):
    """PRD §3.6: "Cancelling an `ENROLLED` seat (else `ERR_INVALID_STATE`, and
    subject to the ownership rule, else `ERR_FORBIDDEN`) moves it to `CANCELLED`,
    refunds the `fee_charged_cents` back to that customer's `store_credit_cents`,
    decrements the session's `enrolled_count` by one, and then promotes the
    earliest-created `WAITLISTED` enrollment on that session — ordered by
    `created_at` ascending — into the freed seat, decrementing `waitlist_count` by
    one and incrementing `enrolled_count` by one."

    Design: Difficulty/transitive_cascade/enrollment_cancel_waitlist_promotion_depth2
    """
    c1 = new_customer("WL One", "w1@example.com")
    c2 = new_customer("WL Two", "w2@example.com")
    c3 = new_customer("WL Three", "w3@example.com")
    session = new_class_session(title="Serger Basics", machine_type="SEWING",
                                start_at="2026-08-02T10:00:00Z", end_at="2026-08-02T12:00:00Z",
                                capacity=1, fee_cents=0)
    e1 = enroll(session["id"], c1["id"])
    enroll(session["id"], c2["id"])
    enroll(session["id"], c3["id"])
    api.cancel_enrollment(e1["id"], SA)
    after = validate_success(api.get_class_session(session["id"], SM), 200)
    assert after["enrolled_count"] == 1
    assert after["waitlist_count"] == 1


# ─────────────── capacity >= boundary waitlists ────────────────────────────
def test_enrollment_at_capacity_boundary_is_waitlisted(api):
    """PRD §3.6: "when the session is already full, it enters `WAITLISTED` and the
    session's `waitlist_count` increases by one instead."

    Design: Difficulty/boundary_precision_check/class_capacity_ge_boundary_waitlists
    """
    c1 = new_customer("Cap One", "cap1@example.com")
    c2 = new_customer("Cap Two", "cap2@example.com")
    session = new_class_session(title="Full Class", machine_type="VACUUM",
                                start_at="2026-08-03T10:00:00Z", end_at="2026-08-03T11:00:00Z",
                                capacity=1, fee_cents=0)
    enroll(session["id"], c1["id"])  # enrolled_count now == capacity == 1
    e2 = enroll(session["id"], c2["id"])
    assert e2["status"] == "WAITLISTED"


def test_first_enrollment_below_capacity_is_enrolled(api):
    """PRD §3.6: "When the session still has room — `enrolled_count` below
    `capacity` — the new `ClassEnrollment` enters `ENROLLED` and the session's
    `enrolled_count` increases by one"

    Design: Difficulty/boundary_precision_check/class_capacity_ge_boundary_waitlists
    """
    c1 = new_customer("Cap One", "cap1@example.com")
    session = new_class_session(title="Full Class", machine_type="VACUUM",
                                start_at="2026-08-03T10:00:00Z", end_at="2026-08-03T11:00:00Z",
                                capacity=1, fee_cents=0)
    e1 = enroll(session["id"], c1["id"])
    assert e1["status"] == "ENROLLED"
    after = validate_success(api.get_class_session(session["id"], SM), 200)
    assert after["enrolled_count"] == 1
    assert after["waitlist_count"] == 0


# ─────────────── closed-interval buffer on customer schedule ───────────────
def test_enrollment_within_buffer_conflicts(api):
    """PRD §3.6: "Two sessions are clear of each other only when the existing
    session's end plus 30 minutes is at or before the new session's start, or the
    new session's end plus 30 minutes is at or before the existing session's start;
    anything closer than that buffer is a conflict, rejected with
    `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/class_closed_buffer_customer_schedule
    """
    cust = new_customer("Sched Cust", "sched@example.com")
    s1 = new_class_session(title="S1", machine_type="SEWING",
                           start_at="2026-08-05T10:00:00Z", end_at="2026-08-05T12:00:00Z",
                           capacity=5, fee_cents=0)
    s2 = new_class_session(title="S2", machine_type="SEWING",
                           start_at="2026-08-05T12:20:00Z", end_at="2026-08-05T14:00:00Z",
                           capacity=5, fee_cents=0)
    enroll(s1["id"], cust["id"])
    res = api.create_enrollment(s2["id"], {"customer_id": cust["id"]}, SA)
    validate_error(res, "ERR_SCHEDULE_CONFLICT", expected_status=409)


def test_enrollment_exactly_at_buffer_allowed(api):
    """PRD §3.6: "Two sessions are clear of each other only when the existing
    session's end plus 30 minutes is at or before the new session's start, or the
    new session's end plus 30 minutes is at or before the existing session's start;
    anything closer than that buffer is a conflict, rejected with
    `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/class_closed_buffer_customer_schedule
    """
    cust = new_customer("Sched Cust", "sched@example.com")
    s1 = new_class_session(title="S1", machine_type="SEWING",
                           start_at="2026-08-05T10:00:00Z", end_at="2026-08-05T12:00:00Z",
                           capacity=5, fee_cents=0)
    s3 = new_class_session(title="S3", machine_type="SEWING",
                           start_at="2026-08-05T12:30:00Z", end_at="2026-08-05T14:00:00Z",
                           capacity=5, fee_cents=0)
    enroll(s1["id"], cust["id"])
    enrollment = validate_success(api.create_enrollment(s3["id"], {"customer_id": cust["id"]}, SA), 201)
    assert enrollment["status"] == "ENROLLED"


# ─────────────── enroll blocked when session not scheduled ─────────────────
def test_enroll_into_cancelled_session_rejected(api):
    """PRD §3.6: "Enrollment requires the session to be `SCHEDULED`, else
    `ERR_SESSION_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/enroll_blocked_by_session_not_scheduled
    """
    cust = new_customer("Enr Cust", "enr@example.com")
    session = new_class_session(title="Cancelled Class", machine_type="SEWING",
                                start_at="2026-08-04T10:00:00Z", end_at="2026-08-04T11:00:00Z",
                                capacity=3, fee_cents=0)
    validate_success(api.cancel_class_session(session["id"], SM), 200)
    res = api.create_enrollment(session["id"], {"customer_id": cust["id"]}, SA)
    validate_error(res, "ERR_SESSION_NOT_OPEN", expected_status=409)


def test_enroll_into_completed_session_rejected(api):
    """PRD §3.6: "Enrollment requires the session to be `SCHEDULED`, else
    `ERR_SESSION_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/enroll_blocked_by_session_not_scheduled
    """
    cust = new_customer("Enr Cust", "enr@example.com")
    session = new_class_session(title="Done Class", machine_type="SEWING",
                                start_at="2026-08-04T10:00:00Z", end_at="2026-08-04T11:00:00Z",
                                capacity=3, fee_cents=0)
    validate_success(api.complete_class_session(session["id"], SM), 200)
    res = api.create_enrollment(session["id"], {"customer_id": cust["id"]}, SA)
    validate_error(res, "ERR_SESSION_NOT_OPEN", expected_status=409)


# ──────────────────────────── corner instance ─────────────────────────────
def test_session_complete_marks_enrollments_attended(api):
    """PRD §3.6: "Completing a `SCHEDULED` session (else `ERR_INVALID_STATE`) moves
    it `SCHEDULED → COMPLETED` and promotes every enrollment still in `ENROLLED` to
    `ATTENDED`."

    Design: Corner/state_machines/class_session_complete_marks_attended
    """
    cust = new_customer("At Cust", "at@example.com")
    session = new_class_session(title="Att Class", machine_type="SEWING",
                                start_at="2026-08-06T10:00:00Z", end_at="2026-08-06T11:00:00Z",
                                capacity=3, fee_cents=0)
    e = enroll(session["id"], cust["id"])
    completed = validate_success(api.complete_class_session(session["id"], SM), 200)
    assert completed["status"] == "COMPLETED"
    assert validate_success(api.get_enrollment(e["id"], SA), 200)["status"] == "ATTENDED"
