"""Training class scheduling: window validity, instructor turnover buffer,
facility half-open overlap, cancellation cascades (PRD §3.4)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_training_class,
    create_fund,
    create_indentured_apprentice,
    create_training_class,
    create_class_payload,
    enroll,
    get_apprentice,
    get_class,
    get_enrollment,
    setup_fund_employer_apprentice,
    validate_error,
    validate_success,
)


def test_zero_length_class_window_rejected(api):
    """PRD §3.4: "The window must be strictly positive: an `end_minute` that
    does not exceed `start_minute` is rejected with
    `ERR_INVALID_CLASS_WINDOW`."

    Design: Corner/validations/invalid_class_window_rejected
    """
    fund = create_fund()
    resp = api.create_class(
        create_class_payload(fund["id"], course_code="BAD-1",
                             start_minute=600, end_minute=600),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_CLASS_WINDOW)


def test_instructor_gap_29_minutes_conflicts(api):
    """PRD §3.4: "Two classes taught by the same `instructor_user_id` conflict
    unless a turnover buffer separates them: a conflict exists when the new
    class's `start_minute` is strictly earlier than the existing class's
    `end_minute` plus 30 minutes and the existing class's `start_minute` is
    strictly earlier than the new class's `end_minute` plus 30 minutes."

    Design: Difficulty/resource_temporal_overlap/instructor_buffer_overlap
    """
    fund = create_fund()
    create_training_class(
        fund["id"], course_code="CN-101", instructor_user_id="inst-1",
        facility="SHOP-A", start_minute=600, end_minute=720,
    )
    resp = api.create_class(
        create_class_payload(
            fund["id"], course_code="CN-102", instructor_user_id="inst-1",
            instructor_name="I. Mason", facility="SHOP-B",
            start_minute=749, end_minute=800,
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_SCHEDULE_CONFLICT)


def test_instructor_gap_exactly_30_minutes_allowed(api):
    """PRD §3.4: "A gap of exactly 30 minutes between the classes is
    permitted."

    Design: Difficulty/resource_temporal_overlap/instructor_buffer_overlap
    """
    fund = create_fund()
    create_training_class(
        fund["id"], course_code="CN-101", instructor_user_id="inst-1",
        facility="SHOP-A", start_minute=600, end_minute=720,
    )
    resp = api.create_class(
        create_class_payload(
            fund["id"], course_code="CN-103", instructor_user_id="inst-1",
            instructor_name="I. Mason", facility="SHOP-C",
            start_minute=750, end_minute=870,
        ),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert_training_class(data)
    assert data["status"] == "SCHEDULED", (
        "start 750 == existing end 720 + 30-minute turnover buffer"
    )


def test_facility_adjacent_classes_allowed(api):
    """PRD §3.4: "The intervals are half-open, so back-to-back classes — one
    ending at exactly the minute the other begins — do not conflict."

    Design: Difficulty/resource_temporal_overlap/facility_half_open_overlap
    """
    fund = create_fund()
    create_training_class(
        fund["id"], course_code="CN-101", instructor_user_id="inst-a",
        instructor_name="A. One", facility="SHOP-A",
        start_minute=600, end_minute=720,
    )
    resp = api.create_class(
        create_class_payload(
            fund["id"], course_code="CN-102", instructor_user_id="inst-b",
            instructor_name="B. Two", facility="SHOP-A",
            start_minute=720, end_minute=740,
        ),
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED", (
        "start 720 == existing end 720: half-open adjacency is allowed"
    )


def test_facility_one_minute_overlap_conflicts(api):
    """PRD §3.4: "Two classes booked into the same `facility` conflict when
    the new class's `start_minute` is strictly earlier than the existing
    class's `end_minute` and the existing class's `start_minute` is strictly
    earlier than the new class's `end_minute`. The intervals are half-open, so
    back-to-back classes — one ending at exactly the minute the other begins —
    do not conflict. A violation is rejected with
    `ERR_FACILITY_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/facility_half_open_overlap
    """
    fund = create_fund()
    create_training_class(
        fund["id"], course_code="CN-101", instructor_user_id="inst-a",
        instructor_name="A. One", facility="SHOP-A",
        start_minute=600, end_minute=720,
    )
    resp = api.create_class(
        create_class_payload(
            fund["id"], course_code="CN-103", instructor_user_id="inst-c",
            instructor_name="C. Three", facility="SHOP-A",
            start_minute=719, end_minute=740,
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_SCHEDULE_CONFLICT)


def test_complete_cancelled_class_rejected(api):
    """PRD §3.4: "Completing a class moves it `SCHEDULED` → `COMPLETED` — any
    other source status is rejected with `ERR_CLASS_NOT_SCHEDULED` — and takes
    the `attended_enrollment_ids` list."

    Design: Corner/errors/error_class_not_schedulable_on_complete
    """
    fund = create_fund()
    klass = create_training_class(fund["id"], course_code="CN-101")
    cancelled = validate_success(api.cancel_class(klass["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"

    resp = api.complete_class(klass["id"], {"attended_enrollment_ids": []}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_CLASS_NOT_SCHEDULED)
    assert get_class(klass["id"])["status"] == "CANCELLED"


def test_class_cancel_drops_only_open_enrollments(api):
    """PRD §3.4: "A cancelled class drops all of its `ENROLLED` enrollments to
    `DROPPED` and recomputes the count."
    PRD §3.4: "Dropping an enrollment moves `ENROLLED` → `DROPPED`; any other
    source status is rejected with `ERR_ENROLLMENT_NOT_OPEN`."

    Design: Corner/state_machines/class_cancel_drops_only_open_enrollments
    """
    fund, employer, app1 = setup_fund_employer_apprentice(rate=500)
    app2 = create_indentured_apprentice(fund["id"], employer["id"],
                                        full_name="App Two")
    klass = create_training_class(fund["id"], course_code="CN-101",
                                  capacity=5)
    enr1 = enroll(klass["id"], app1["id"])
    enr2 = enroll(klass["id"], app2["id"])
    dropped_early = validate_success(api.drop_enrollment(enr2["id"], ADMIN), 200)
    assert dropped_early["status"] == "DROPPED"

    cancelled = validate_success(api.cancel_class(klass["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"
    assert get_enrollment(enr1["id"])["status"] == "DROPPED", (
        "still-ENROLLED enrollment is cascaded to DROPPED"
    )
    assert get_enrollment(enr2["id"])["status"] == "DROPPED", (
        "previously dropped enrollment is untouched"
    )
    assert get_class(klass["id"])["enrolled_count"] == 0
    assert get_apprentice(app1["id"])["rti_credits_accumulated"] == 0, (
        "cancellation awards no credits"
    )
