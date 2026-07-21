"""Classes, retreats, and enrollment: the OPEN<->FULL seat cycle, the capacity boundary and
ERR_CLASS_FULL, the class-must-be-open cross-entity dependency, member time-window conflicts,
the class time-window guard, duplicate-enrollment rejection, and filtered enrollment listing."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_member, create_class, enroll,
    ApiErrorId, TEST_USERS,
)
from test_helpers import factories as f

CLERK = TEST_USERS["clerk_headers"]


# =========================================================================
# Difficulty/non_linear_state_machine/class_event_open_full_cycle
# =========================================================================
def test_class_flips_to_full_on_last_seat(api):
    """PRD §3.5: "it flips from OPEN to FULL the moment confirmed seats equal capacity, and
    back from FULL to OPEN when a cancellation drops confirmed seats below capacity". A
    capacity-1 class flips to FULL as soon as its single seat is enrolled.

    Design: Difficulty/non_linear_state_machine/class_event_open_full_cycle
    """
    member = create_member(api)
    cls = create_class(api, capacity=1, fee=20.00, title="Mini",
                       start_time="2026-09-01T10:00:00Z", end_time="2026-09-01T12:00:00Z")
    enroll(api, cls["id"], member["id"])
    data = validate_success(api.get_class(cls["id"], CLERK), 200)
    assert data["seats_taken"] == 1
    assert data["status"] == "FULL", f"expected FULL, got {data['status']}"


def test_class_returns_to_open_when_seat_frees(api):
    """PRD §3.5: "back from FULL to OPEN when a cancellation drops confirmed seats below
    capacity — the latter only while the event has not itself been cancelled." A capacity-1
    class that is FULL returns to OPEN with seats_taken 0 once its single enrollment is
    cancelled.

    Design: Difficulty/non_linear_state_machine/class_event_open_full_cycle
    """
    member = create_member(api)
    cls = create_class(api, capacity=1, fee=20.00, title="Mini",
                       start_time="2026-09-01T10:00:00Z", end_time="2026-09-01T12:00:00Z")
    enrollment = enroll(api, cls["id"], member["id"])
    validate_success(api.cancel_enrollment(enrollment["id"], CLERK), 200)
    data = validate_success(api.get_class(cls["id"], CLERK), 200)
    assert data["status"] == "OPEN", f"expected OPEN, got {data['status']}"
    assert data["seats_taken"] == 0


# =========================================================================
# Difficulty/boundary_precision_check/class_capacity_last_seat_full
# =========================================================================
def test_capacity_reached_exactly_marks_full(api):
    """PRD §3.5: "A class's seats_taken is always the count of its enrollments in CONFIRMED
    status". PRD §3.5: "it flips from OPEN to FULL the moment confirmed seats equal capacity".
    A capacity-2 class reaches seats_taken 2 after two enrollments and becomes FULL.

    Design: Difficulty/boundary_precision_check/class_capacity_last_seat_full
    """
    m1 = create_member(api)
    m2 = create_member(api)
    cls = create_class(api, capacity=2, fee=30.00, title="FMQ",
                       start_time="2026-09-05T10:00:00Z", end_time="2026-09-05T14:00:00Z")
    enroll(api, cls["id"], m1["id"])
    enroll(api, cls["id"], m2["id"])
    data = validate_success(api.get_class(cls["id"], CLERK), 200)
    assert data["seats_taken"] == 2
    assert data["status"] == "FULL"


def test_enroll_into_full_class_rejected(api):
    """PRD §3.5: "a class already at capacity is FULL, and enrolling into a full class is
    rejected with ERR_CLASS_FULL." A third enrollment into a capacity-2 class that already has
    two confirmed seats is rejected.

    Design: Difficulty/boundary_precision_check/class_capacity_last_seat_full
    """
    m1 = create_member(api)
    m2 = create_member(api)
    m3 = create_member(api)
    cls = create_class(api, capacity=2, fee=30.00, title="FMQ",
                       start_time="2026-09-05T10:00:00Z", end_time="2026-09-05T14:00:00Z")
    enroll(api, cls["id"], m1["id"])
    enroll(api, cls["id"], m2["id"])
    resp = api.create_enrollment(f.create_enrollment_payload(cls["id"], m3["id"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_CLASS_FULL.value)


# =========================================================================
# Difficulty/cross_entity_state_dependency/enroll_requires_class_open
# =========================================================================
def test_enroll_into_cancelled_class_rejected(api):
    """PRD §3.5: "Enrollment is refused if the class is not accepting enrollments — it must be
    OPEN". PRD §2.5: "The target resource must be in a state that permits the operation (the
    state machines in §3 spell these out); otherwise a 409 conflict specific to the
    transition, such as ... ERR_CLASS_NOT_OPEN". A class that has been cancelled is not OPEN,
    so enrolling into it is rejected with ERR_CLASS_NOT_OPEN.

    Design: Difficulty/cross_entity_state_dependency/enroll_requires_class_open
    """
    member = create_member(api)
    cls = create_class(api, capacity=5, fee=25.00, title="Dead",
                       start_time="2026-09-10T10:00:00Z", end_time="2026-09-10T12:00:00Z")
    validate_success(api.cancel_class(cls["id"], CLERK), 200)
    resp = api.create_enrollment(f.create_enrollment_payload(cls["id"], member["id"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_CLASS_NOT_OPEN.value)


def test_enroll_into_open_class_confirms(api):
    """PRD §3.5: "A successful enrollment is recorded as CONFIRMED". Enrolling a member into an
    OPEN class with available capacity yields a CONFIRMED enrollment.

    Design: Difficulty/cross_entity_state_dependency/enroll_requires_class_open
    """
    member = create_member(api)
    cls = create_class(api, capacity=5, fee=25.00, title="Live",
                       start_time="2026-09-10T10:00:00Z", end_time="2026-09-10T12:00:00Z")
    resp = api.create_enrollment(f.create_enrollment_payload(cls["id"], member["id"]), CLERK)
    data = validate_success(resp, 201)
    assert data["status"] == "CONFIRMED"


# =========================================================================
# Difficulty/resource_temporal_overlap/member_class_schedule_overlap
# =========================================================================
def test_member_overlapping_class_times_rejected(api):
    """PRD §3.5: "Nor may a member be enrolled into a class whose time window overlaps that of
    another class in which they already hold a CONFIRMED enrollment; such an overlap is
    rejected with ERR_MEMBER_SCHEDULE_CONFLICT." A member confirmed in class A [10:00,12:00]
    who enrolls in class B [11:00,13:00] is rejected.

    Design: Difficulty/resource_temporal_overlap/member_class_schedule_overlap
    """
    member = create_member(api)
    class_a = create_class(api, capacity=5, fee=20.00, title="A",
                           start_time="2026-09-20T10:00:00Z", end_time="2026-09-20T12:00:00Z")
    class_b = create_class(api, capacity=5, fee=20.00, title="B",
                           start_time="2026-09-20T11:00:00Z", end_time="2026-09-20T13:00:00Z")
    enroll(api, class_a["id"], member["id"])
    resp = api.create_enrollment(f.create_enrollment_payload(class_b["id"], member["id"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_MEMBER_SCHEDULE_CONFLICT.value)


def test_member_non_overlapping_class_times_allowed(api):
    """PRD §3.5: "A successful enrollment is recorded as CONFIRMED". The overlap bar applies
    only to a class "whose time window overlaps that of another class in which they already
    hold a CONFIRMED enrollment"; a member confirmed in class A [10:00,12:00] may still enroll
    in a clearly separated class C [14:00,16:00].

    Design: Difficulty/resource_temporal_overlap/member_class_schedule_overlap
    """
    member = create_member(api)
    class_a = create_class(api, capacity=5, fee=20.00, title="A",
                           start_time="2026-09-20T10:00:00Z", end_time="2026-09-20T12:00:00Z")
    class_c = create_class(api, capacity=5, fee=20.00, title="C",
                           start_time="2026-09-20T14:00:00Z", end_time="2026-09-20T16:00:00Z")
    enroll(api, class_a["id"], member["id"])
    resp = api.create_enrollment(f.create_enrollment_payload(class_c["id"], member["id"]), CLERK)
    data = validate_success(resp, 201)
    assert data["status"] == "CONFIRMED"


# =========================================================================
# Corner/validations/class_invalid_time_window_rejected
# =========================================================================
def test_class_end_before_start_rejected(api):
    """PRD §3.5: "The end_time must be strictly later than the start_time (otherwise
    ERR_INVALID_TIME_WINDOW)". A class whose end_time precedes its start_time is rejected.

    Design: Corner/validations/class_invalid_time_window_rejected
    """
    resp = api.create_class(
        f.create_class_payload(title="Bad", instructor="Bad",
                               start_time="2026-09-30T14:00:00Z", end_time="2026-09-30T12:00:00Z",
                               capacity=5, fee=20.00),
        CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW.value)


# =========================================================================
# Corner/validations/duplicate_enrollment_returns_conflict
# =========================================================================
def test_duplicate_enrollment_rejected(api):
    """PRD §3.5: "A member may not hold two active enrollments in the same class; a duplicate
    confirmed enrollment is rejected with ERR_DUPLICATE_ENROLLMENT." A member already
    CONFIRMED in a class who enrolls again in that same class is rejected.

    Design: Corner/validations/duplicate_enrollment_returns_conflict
    """
    member = create_member(api)
    cls = create_class(api, capacity=5, fee=20.00, title="Dup C",
                       start_time="2026-10-05T10:00:00Z", end_time="2026-10-05T12:00:00Z")
    enroll(api, cls["id"], member["id"])
    resp = api.create_enrollment(f.create_enrollment_payload(cls["id"], member["id"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value)


# =========================================================================
# Corner/endpoints/list_enrollments_filtered_by_member
# =========================================================================
def test_list_enrollments_filtered_by_member(api):
    """PRD §3.5: "Enrollments may be listed and filtered by member_id, by class_event_id, or
    by status." Filtering by a member with one confirmed enrollment returns exactly that row.

    Design: Corner/endpoints/list_enrollments_filtered_by_member
    """
    member = create_member(api)
    cls = create_class(api, capacity=5, fee=15.00, title="Le C",
                       start_time="2026-10-06T10:00:00Z", end_time="2026-10-06T12:00:00Z")
    enroll(api, cls["id"], member["id"])
    resp = api.list_enrollments(CLERK, params={"member_id": member["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"expected 1 enrollment, got {len(data)}"
    assert data[0]["member_id"] == member["id"]
