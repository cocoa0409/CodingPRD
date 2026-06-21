"""Calculations, scheduling validations, error paths, and RBAC.

Corner-design queue B: sections `calculations`, `validations`, `errors`, `rbac`.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    make_student_headers, make_anonymous_headers,
    set_clock, create_student,
    create_package, create_active_enrollment,
    setup_road_scheduling_context, setup_classroom_scheduling_context,
    schedule_lesson, schedule_and_complete, student_version,
    create_lesson_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Calculations
# ===========================================================================
def test_enrollment_final_price_adult_no_promo_bundle_only(api):
    """PRD §3.4: "for an adult with no promo on the same package, only the
    bundle flat applies and both percentage steps are skipped."
    PRD §3.4: "If — and only if — the package includes both tracks ... the
    package's `bundle_discount_cents` is subtracted from the running subtotal."

    Design: Corner/calculations/enrollment_final_price_adult_no_promo_bundle_only
    """
    set_clock("2026-06-01T00:00:00.000Z")
    pkg = create_package(price_cents=90000, enrollment_fee_cents=5000,
                         included_classroom_hours=30, included_online_hours=8,
                         included_road_hours=6, bundle_discount_cents=5000)
    stu = create_student(full_name="Ad Ult", email="adult2@x.com",
                        date_of_birth="1990-01-01")
    enr = create_active_enrollment(stu["id"], pkg["id"])
    assert enr["final_price_cents"] == 85000


def test_no_show_first_strike_forgiven_zero_fee(api):
    """PRD §3.8: "the first strike is forgiven and charges nothing".
    PRD §3.8: "Whenever the charged fee is above zero, the system posts a wallet
    debit ... which lowers the student's `wallet_balance_cents`."

    Design: Corner/calculations/no_show_first_strike_forgiven_zero_fee
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context()
    lesson = schedule_lesson(
        ctx["student"]["id"], ctx["enrollment"]["id"], "ROAD",
        "2026-06-05T09:00:00.000Z", "2026-06-05T11:00:00.000Z",
        instructor_id=ctx["instructor"]["id"], vehicle_id=ctx["vehicle"]["id"],
    )
    set_clock("2026-06-05T09:30:00.000Z")
    validate_success(api.no_show_lesson(lesson["id"], ADMIN))

    strikes, _ = validate_paginated(
        api.list_no_show_strikes(ADMIN, params={"student_id": ctx["student"]["id"]})
    )
    assert len(strikes) == 1
    assert strikes[0]["strike_index"] == 1
    assert strikes[0]["fee_charged_cents"] == 0

    student = validate_success(api.get_student(ctx["student"]["id"], ADMIN))
    assert student["wallet_balance_cents"] == 0
    assert student["no_show_count"] == 1


def test_readiness_score_partial_online_is_point_nine(api):
    """PRD §3.7: "The score is the road ratio weighted at 0.5, plus the
    classroom ratio weighted at 0.3, plus the online ratio weighted at 0.2, with
    the sum rounded to four decimal places half up."
    PRD §3.7: "take the ratio of completed hours to that track's required floor
    but cap it at 1.0 — road against a floor of 6 hours, classroom against a
    floor of 30 hours, online against a floor of 8 hours."

    Design: Corner/calculations/readiness_score_partial_online_is_point_nine
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context(package_overrides={
        "price_cents": 90000, "enrollment_fee_cents": 5000,
        "included_classroom_hours": 30, "included_online_hours": 8,
        "included_road_hours": 6, "bundle_discount_cents": 5000,
    })
    stu, enr = ctx["student"], ctx["enrollment"]
    inst, veh = ctx["instructor"], ctx["vehicle"]
    # 30h classroom
    schedule_and_complete(stu["id"], enr["id"], "CLASSROOM",
                          "2026-06-02T08:00:00.000Z", "2026-06-03T14:00:00.000Z",
                          inst["id"], "2026-06-03T14:00:00.000Z")
    # 4h online (4/8 = 0.5 -> contributes 0.1)
    schedule_and_complete(stu["id"], enr["id"], "ONLINE",
                          "2026-06-04T08:00:00.000Z", "2026-06-04T12:00:00.000Z",
                          inst["id"], "2026-06-04T12:00:00.000Z")
    # 6h road
    schedule_and_complete(stu["id"], enr["id"], "ROAD",
                          "2026-06-05T08:00:00.000Z", "2026-06-05T14:00:00.000Z",
                          inst["id"], "2026-06-05T14:00:00.000Z", vehicle_id=veh["id"])

    student = validate_success(api.get_student(stu["id"], ADMIN))
    assert student["readiness_score"] == 0.9
    assert student["completed_online_hours"] == 4
    assert student["status"] == "ROAD_READY"


# ===========================================================================
# Validations (scheduling chain)
# ===========================================================================
def test_schedule_road_with_non_dual_control_vehicle_rejected(api):
    """PRD §3.6: "a `ROAD` lesson requires the student to be at `PERMITTED` or
    `ROAD_READY` (a recorded permit), the assigned instructor to be
    `certified_road`, and the assigned vehicle to be `dual_control`; any of
    these missing yields `ERR_ROAD_PREREQUISITE_NOT_MET`."

    Design: Corner/validations/schedule_road_with_non_dual_control_vehicle_rejected
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context(
        vehicle_overrides={"dual_control": False},
    )
    payload = create_lesson_payload(
        ctx["student"]["id"], ctx["enrollment"]["id"], "ROAD",
        "2026-06-20T09:00:00.000Z", "2026-06-20T11:00:00.000Z",
        student_version(ctx["student"]["id"]),
        instructor_id=ctx["instructor"]["id"], vehicle_id=ctx["vehicle"]["id"],
    )
    resp = api.create_lesson(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ROAD_PREREQUISITE_NOT_MET, expected_status=422)


def test_schedule_lesson_with_end_before_start_rejected(api):
    """PRD §3.6: "The interval must be well-formed — `end_at` strictly after
    `start_at`, and `start_at` strictly in the future relative to the current
    clock — or the request is rejected with `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/schedule_lesson_with_end_before_start_rejected
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_classroom_scheduling_context(package_overrides={
        "included_classroom_hours": 30, "included_online_hours": 0,
        "included_road_hours": 0, "enrollment_fee_cents": 0,
        "bundle_discount_cents": 0, "price_cents": 60000,
    })
    payload = create_lesson_payload(
        ctx["student"]["id"], ctx["enrollment"]["id"], "CLASSROOM",
        "2026-06-20T11:00:00.000Z", "2026-06-20T10:00:00.000Z",
        student_version(ctx["student"]["id"]),
        instructor_id=ctx["instructor"]["id"],
    )
    resp = api.create_lesson(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL, expected_status=422)


def test_schedule_on_out_of_service_vehicle_rejected(api):
    """PRD §3.6: "Referential availability is checked next: the assigned
    instructor must be `active`, the vehicle must not be `out_of_service`, and
    the funding enrollment must be `ACTIVE`; a violation yields
    `ERR_RESOURCE_UNAVAILABLE`."

    Design: Corner/validations/schedule_on_out_of_service_vehicle_rejected
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context(
        vehicle_overrides={"dual_control": True, "out_of_service": True},
    )
    payload = create_lesson_payload(
        ctx["student"]["id"], ctx["enrollment"]["id"], "ROAD",
        "2026-06-20T09:00:00.000Z", "2026-06-20T11:00:00.000Z",
        student_version(ctx["student"]["id"]),
        instructor_id=ctx["instructor"]["id"], vehicle_id=ctx["vehicle"]["id"],
    )
    resp = api.create_lesson(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_UNAVAILABLE, expected_status=422)


# ===========================================================================
# Errors
# ===========================================================================
def test_complete_enrollment_without_certificate_rejected(api):
    """PRD §3.5: "Completion ... moves the enrollment from `ACTIVE` to
    `COMPLETED`; it is legal only from `ACTIVE` and only when the student is
    linked to a certificate for this enrollment that is in `ISSUED`,
    `SUBMITTED`, or `ACCEPTED` status — there must be a real certificate before
    an enrollment can be closed out."

    Design: Corner/errors/complete_enrollment_without_certificate_rejected
    """
    set_clock("2026-06-01T00:00:00.000Z")
    pkg = create_package(price_cents=90000, enrollment_fee_cents=5000,
                         included_classroom_hours=30, included_online_hours=8,
                         included_road_hours=6, bundle_discount_cents=5000)
    stu = create_student(full_name="No Cert", email="nocert@x.com",
                        date_of_birth="1990-01-01")
    enr = create_active_enrollment(stu["id"], pkg["id"])
    resp = api.complete_enrollment(enr["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_enrollment(enr["id"], ADMIN))
    assert after["status"] == "ACTIVE"


# NOTE: Corner/errors/refund_inactive_enrollment_returns_invalid_state is an
# excluded_because stub; its assertion (refund of a non-ACTIVE/DRAFT enrollment
# -> ERR_INVALID_STATE) is owned by
# Difficulty/priority_pair_validation_conflict/state_beats_guardian_consent_on_refund_of_draft
# in test_06_scheduling_constraints.py. No test is emitted for the stub.


# ===========================================================================
# RBAC
# ===========================================================================
def test_student_cannot_create_course_package(api):
    """PRD §2.1: "When a request is well-authenticated but the acting role is
    not permitted to invoke the targeted endpoint, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/student_cannot_create_course_package
    """
    set_clock("2026-06-01T00:00:00.000Z")
    stu = create_student(full_name="Rb Stu", email="rbstu@x.com",
                        date_of_birth="1990-01-01")
    resp = api.create_course_package(
        {"code": "HACK", "name": "Hack", "price_cents": 1,
         "enrollment_fee_cents": 0, "included_classroom_hours": 0,
         "included_online_hours": 0, "included_road_hours": 0},
        make_student_headers(stu["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_student_cannot_cancel_another_students_lesson(api):
    """PRD §2.1: "ownership checks on any resource that references a student —
    that student's own enrollments, lessons, certificates, wallet entries, and
    no-show strikes — compare the resource's student foreign-key field to
    `X-User-ID`. ... When an entity-backed role acts on a resource it does not
    own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/student_cannot_cancel_another_students_lesson
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_classroom_scheduling_context(package_overrides={
        "included_classroom_hours": 30, "included_online_hours": 0,
        "included_road_hours": 0, "enrollment_fee_cents": 0,
        "bundle_discount_cents": 0, "price_cents": 60000,
    })
    lesson = schedule_lesson(
        ctx["student"]["id"], ctx["enrollment"]["id"], "CLASSROOM",
        "2026-07-10T09:00:00.000Z", "2026-07-10T11:00:00.000Z",
        instructor_id=ctx["instructor"]["id"],
    )
    other = create_student(full_name="Own B", email="ownb@x.com",
                          date_of_birth="1990-01-01")
    resp = api.cancel_lesson(lesson["id"], make_student_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    after = validate_success(api.get_lesson(lesson["id"], ADMIN))
    assert after["status"] == "SCHEDULED"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two mandatory HTTP headers:
    `X-User-ID` ... and `X-User-Role` .... If either header is missing, or
    `X-User-Role` is not one of the recognized roles, the request is rejected
    with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.list_course_packages(make_anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
