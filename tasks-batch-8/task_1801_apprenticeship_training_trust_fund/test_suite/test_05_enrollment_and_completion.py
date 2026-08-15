"""Enrollment gating, class capacity, and completion credit cascades
(PRD §3.4, §3.6)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    award_rti_credits,
    create_employer,
    create_enrollment_payload,
    create_fund,
    create_indentured_apprentice,
    create_registered_apprentice,
    create_report,
    create_training_class,
    enroll,
    get_apprentice,
    get_class,
    get_enrollment,
    report_line,
    setup_fund_employer_apprentice,
    submit_report,
    validate_error,
    validate_success,
)


def test_enroll_applicant_rejected_not_indentured(api):
    """PRD §3.4: "The apprentice must be `INDENTURED` — applicants and
    suspended apprentices cannot enroll, and the attempt is rejected with
    `ERR_APPRENTICE_NOT_INDENTURED` — and the registration dimension must read
    `REGISTERED`, else `ERR_REGISTRATION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_enrollment_requires_indentured
    """
    fund = create_fund()
    employer = create_employer(fund["id"], rate=500)
    apprentice = create_registered_apprentice(fund["id"], employer["id"])
    assert apprentice["program_status"] == "APPLICANT"
    assert apprentice["registration_status"] == "REGISTERED"

    klass = create_training_class(fund["id"], course_code="CN-101")
    resp = api.create_enrollment(
        create_enrollment_payload(klass["id"], apprentice["id"]), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_APPRENTICE_NOT_INDENTURED)
    assert get_class(klass["id"])["enrolled_count"] == 0


def test_enroll_after_indenture_succeeds(api):
    """PRD §3.4: "A created enrollment begins `ENROLLED`, and the class's
    `enrolled_count` rises by one."
    PRD §3.2: "Indenture moves an `APPLICANT` to `INDENTURED` and is the gate
    to hour reporting and class enrollment."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_enrollment_requires_indentured
    """
    fund = create_fund()
    employer = create_employer(fund["id"], rate=500)
    apprentice = create_registered_apprentice(fund["id"], employer["id"])
    klass = create_training_class(fund["id"], course_code="CN-101")

    resp = api.create_enrollment(
        create_enrollment_payload(klass["id"], apprentice["id"]), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_APPRENTICE_NOT_INDENTURED)

    validate_success(api.indenture_apprentice(apprentice["id"], ADMIN), 200)
    enrolled = validate_success(
        api.create_enrollment(
            create_enrollment_payload(klass["id"], apprentice["id"]), ADMIN,
        ),
        201,
    )
    assert enrolled["status"] == "ENROLLED"
    assert get_class(klass["id"])["enrolled_count"] == 1


def test_first_enrollment_up_to_capacity_succeeds(api):
    """PRD §3.4: "A class is full when its `enrolled_count` has reached its
    `capacity`, and enrolling into a full class fails with `ERR_CLASS_FULL`."
    PRD §3.4: "A created enrollment begins `ENROLLED`, and the class's
    `enrolled_count` rises by one."

    Design: Difficulty/boundary_precision_check/boundary_class_capacity_full_at_capacity
    """
    fund, employer, app1 = setup_fund_employer_apprentice(rate=500)
    klass = create_training_class(fund["id"], course_code="CN-101", capacity=1)

    resp = api.create_enrollment(
        create_enrollment_payload(klass["id"], app1["id"]), ADMIN,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ENROLLED", "count 0 < capacity 1 admits the first"
    assert get_class(klass["id"])["enrolled_count"] == 1


def test_enrollment_at_full_capacity_rejected(api):
    """PRD §3.4: "A class is full when its `enrolled_count` has reached its
    `capacity`, and enrolling into a full class fails with `ERR_CLASS_FULL`."

    Design: Difficulty/boundary_precision_check/boundary_class_capacity_full_at_capacity
    """
    fund, employer, app1 = setup_fund_employer_apprentice(rate=500)
    app2 = create_indentured_apprentice(fund["id"], employer["id"],
                                        full_name="App Two")
    klass = create_training_class(fund["id"], course_code="CN-101", capacity=1)
    enroll(klass["id"], app1["id"])

    resp = api.create_enrollment(
        create_enrollment_payload(klass["id"], app2["id"]), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CLASS_FULL)
    assert get_class(klass["id"])["enrolled_count"] == 1


def test_duplicate_enrollment_rejected(api):
    """PRD §3.4: "At most one `ENROLLED` enrollment may exist per apprentice
    per class; a duplicate is rejected with `ERR_DUPLICATE_ENROLLMENT`."

    Design: Corner/errors/error_duplicate_enrollment
    """
    fund, employer, app1 = setup_fund_employer_apprentice(rate=500)
    klass = create_training_class(fund["id"], course_code="CN-101", capacity=5)
    enroll(klass["id"], app1["id"])

    resp = api.create_enrollment(
        create_enrollment_payload(klass["id"], app1["id"]), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT)
    assert get_class(klass["id"])["enrolled_count"] == 1


def test_drop_credited_enrollment_rejected(api):
    """PRD §3.4: "Dropping an enrollment moves `ENROLLED` → `DROPPED`; any
    other source status is rejected with `ERR_ENROLLMENT_NOT_OPEN`."

    Design: Corner/state_machines/enrollment_drop_rejected_when_creditable_window_closed
    """
    fund, employer, app1 = setup_fund_employer_apprentice(rate=500)
    klass = create_training_class(fund["id"], course_code="CN-101", capacity=5)
    enrollment = enroll(klass["id"], app1["id"])
    validate_success(
        api.complete_class(klass["id"],
                           {"attended_enrollment_ids": [enrollment["id"]]},
                           ADMIN),
        200,
    )
    assert get_enrollment(enrollment["id"])["status"] == "CREDITED"

    resp = api.drop_enrollment(enrollment["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_OPEN)
    assert get_enrollment(enrollment["id"])["status"] == "CREDITED"


def test_complete_with_empty_attendance_marks_no_show(api):
    """PRD §3.4: "Every `ENROLLED` enrollment not present in the list becomes
    `NO_SHOW` and earns nothing."
    PRD §3.4: "The class's `enrolled_count` recomputes to zero."

    Design: Corner/calculations/complete_class_with_empty_attendance_marks_no_credit
    """
    fund, employer, app1 = setup_fund_employer_apprentice(rate=500)
    klass = create_training_class(fund["id"], course_code="CN-101", capacity=5)
    enrollment = enroll(klass["id"], app1["id"])

    completed = validate_success(
        api.complete_class(klass["id"], {"attended_enrollment_ids": []}, ADMIN),
        200,
    )
    assert completed["status"] == "COMPLETED"
    assert get_enrollment(enrollment["id"])["status"] == "NO_SHOW"
    assert get_apprentice(app1["id"])["rti_credits_accumulated"] == 0
    assert get_class(klass["id"])["enrolled_count"] == 0


def test_completion_credits_attended_enrollment(api):
    """PRD §3.4: "Each attended enrollment becomes `CREDITED`: the class's
    `rti_credit_value` is added to that apprentice's `rti_credits_accumulated`,
    and the apprentice's wage step and rate are recomputed."

    Design: Difficulty/transitive_cascade/class_complete_credit_chain
    """
    fund, employer, apprentice = setup_fund_employer_apprentice(rate=500)
    report = create_report(
        employer, 2026, 6, [report_line(apprentice["id"], 2000)],
    )
    submit_report(employer, report["id"])
    award_rti_credits(apprentice, fund["id"], 128, course_code="RTI-128",
                      instructor_user_id="inst-1", facility="SHOP-A",
                      start_minute=600, end_minute=720)

    klass2 = create_training_class(
        fund["id"], course_code="RTI-016", instructor_user_id="inst-2",
        instructor_name="J. Torres", facility="SHOP-B", rti_credit_value=16,
        start_minute=800, end_minute=920,
    )
    enrollment2 = enroll(klass2["id"], apprentice["id"])

    completed = validate_success(
        api.complete_class(klass2["id"],
                           {"attended_enrollment_ids": [enrollment2["id"]]},
                           ADMIN),
        200,
    )
    assert completed["status"] == "COMPLETED"
    assert get_enrollment(enrollment2["id"])["status"] == "CREDITED", "hop 1"
    after = get_apprentice(apprentice["id"])
    assert after["rti_credits_accumulated"] == 144, (
        "hop 2: the credit mutation (128 + 16) landed on the apprentice"
    )


def test_completion_credit_recomputes_wage_step(api):
    """PRD §3.4: "Each attended enrollment becomes `CREDITED`: the class's
    `rti_credit_value` is added to that apprentice's `rti_credits_accumulated`,
    and the apprentice's wage step and rate are recomputed."
    PRD §3.6: "The `current_wage_step` is the highest step for which both
    gates — hours and credits — hold."

    Design: Difficulty/transitive_cascade/class_complete_credit_chain
    """
    fund, employer, apprentice = setup_fund_employer_apprentice(rate=500)
    report = create_report(
        employer, 2026, 6, [report_line(apprentice["id"], 2000)],
    )
    submit_report(employer, report["id"])
    award_rti_credits(apprentice, fund["id"], 128, course_code="RTI-128",
                      instructor_user_id="inst-1", facility="SHOP-A",
                      start_minute=600, end_minute=720)
    mid = get_apprentice(apprentice["id"])
    assert mid["current_wage_step"] == 1, "128 credits is below the 144 gate"

    klass2 = create_training_class(
        fund["id"], course_code="RTI-016", instructor_user_id="inst-2",
        instructor_name="J. Torres", facility="SHOP-B", rti_credit_value=16,
        start_minute=800, end_minute=920,
    )
    enrollment2 = enroll(klass2["id"], apprentice["id"])
    validate_success(
        api.complete_class(klass2["id"],
                           {"attended_enrollment_ids": [enrollment2["id"]]},
                           ADMIN),
        200,
    )

    after = get_apprentice(apprentice["id"])
    assert after["rti_credits_accumulated"] == 144
    assert after["current_wage_step"] == 2, (
        "hop 2 continuation: crossing 144 credits with 2000 hours recomputes"
    )
    assert after["current_wage_rate_cents"] == 2400


def test_complete_with_foreign_enrollment_rejected(api):
    """PRD §3.4: "Every id in that list must reference an `ENROLLED`
    enrollment belonging to this class; an unknown id, an id from another
    class, or an id whose enrollment is not `ENROLLED` is rejected with
    `ERR_INVALID_ATTENDEE_LIST` (HTTP 400)."

    Design: Corner/errors/error_invalid_attendee_list
    """
    fund, employer, app1 = setup_fund_employer_apprentice(rate=500)
    app2 = create_indentured_apprentice(fund["id"], employer["id"],
                                        full_name="App Two")
    klass1 = create_training_class(
        fund["id"], course_code="CN-101", instructor_user_id="inst-1",
        facility="SHOP-A", capacity=5, start_minute=600, end_minute=720,
    )
    klass2 = create_training_class(
        fund["id"], course_code="CN-102", instructor_user_id="inst-2",
        instructor_name="J. Torres", facility="SHOP-B", capacity=5,
        start_minute=600, end_minute=720,
    )
    enroll(klass1["id"], app1["id"])
    enr2 = enroll(klass2["id"], app2["id"])

    resp = api.complete_class(
        klass1["id"], {"attended_enrollment_ids": [enr2["id"]]}, ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ATTENDEE_LIST)
    assert get_class(klass1["id"])["status"] == "SCHEDULED"
    assert get_enrollment(enr2["id"])["status"] == "ENROLLED"
