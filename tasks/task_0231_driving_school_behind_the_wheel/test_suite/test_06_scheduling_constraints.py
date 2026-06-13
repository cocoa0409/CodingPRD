"""Boundary precision, cross-entity prerequisites, double-booking semantics,
and validation-priority conflicts.

Difficulty queue A: rules `boundary_precision_check`,
`cross_entity_state_dependency`, `resource_temporal_overlap`,
`priority_pair_validation_conflict`.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    make_guardian_headers,
    set_clock, create_student, create_package, create_instructor, create_vehicle,
    create_active_enrollment, create_enrollment, create_granted_consent,
    setup_road_scheduling_context,
    schedule_lesson, schedule_and_complete, student_version,
    create_lesson_payload, api_client,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# boundary_precision_check / road_hours_exactly_equals_included_is_allowed
# ===========================================================================
def test_road_hours_exactly_equals_included_is_allowed(api):
    """PRD §3.6: "a road-hour ceiling: scheduling a road lesson must not push
    the student's `scheduled_road_hours` plus `completed_road_hours` above the
    funding package's `included_road_hours`, or the request is rejected with
    `ERR_ROAD_HOURS_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/road_hours_exactly_equals_included_is_allowed
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context(package_overrides={
        "price_cents": 60000, "enrollment_fee_cents": 0,
        "included_classroom_hours": 0, "included_online_hours": 0,
        "included_road_hours": 6, "bundle_discount_cents": 0,
    })
    stu, enr = ctx["student"], ctx["enrollment"]
    inst, veh = ctx["instructor"], ctx["vehicle"]
    schedule_lesson(stu["id"], enr["id"], "ROAD",
                   "2026-06-10T09:00:00.000Z", "2026-06-10T11:00:00.000Z",
                   instructor_id=inst["id"], vehicle_id=veh["id"])
    schedule_lesson(stu["id"], enr["id"], "ROAD",
                   "2026-06-11T09:00:00.000Z", "2026-06-11T11:00:00.000Z",
                   instructor_id=inst["id"], vehicle_id=veh["id"])
    # base 4 scheduled; this third 2h lands exactly at 6 == included (inclusive).
    lesson = schedule_lesson(stu["id"], enr["id"], "ROAD",
                            "2026-06-12T09:00:00.000Z", "2026-06-12T11:00:00.000Z",
                            instructor_id=inst["id"], vehicle_id=veh["id"])
    assert lesson["status"] == "SCHEDULED"
    student = validate_success(api.get_student(stu["id"], ADMIN))
    assert student["scheduled_road_hours"] == 6


def test_road_hours_one_over_included_is_rejected(api):
    """PRD §3.6: "scheduling a road lesson must not push the student's
    `scheduled_road_hours` plus `completed_road_hours` above the funding
    package's `included_road_hours`, or the request is rejected with
    `ERR_ROAD_HOURS_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/road_hours_exactly_equals_included_is_allowed
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context(package_overrides={
        "price_cents": 60000, "enrollment_fee_cents": 0,
        "included_classroom_hours": 0, "included_online_hours": 0,
        "included_road_hours": 6, "bundle_discount_cents": 0,
    })
    stu, enr = ctx["student"], ctx["enrollment"]
    inst, veh = ctx["instructor"], ctx["vehicle"]
    # 5 scheduled hours: 3h + 2h.
    schedule_lesson(stu["id"], enr["id"], "ROAD",
                   "2026-06-10T09:00:00.000Z", "2026-06-10T12:00:00.000Z",
                   instructor_id=inst["id"], vehicle_id=veh["id"])
    schedule_lesson(stu["id"], enr["id"], "ROAD",
                   "2026-06-11T09:00:00.000Z", "2026-06-11T11:00:00.000Z",
                   instructor_id=inst["id"], vehicle_id=veh["id"])
    # this 2h would push to 7 > 6 -> rejected.
    payload = create_lesson_payload(
        stu["id"], enr["id"], "ROAD",
        "2026-06-12T09:00:00.000Z", "2026-06-12T11:00:00.000Z",
        student_version(stu["id"]),
        instructor_id=inst["id"], vehicle_id=veh["id"],
    )
    resp = api.create_lesson(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ROAD_HOURS_EXCEEDED, expected_status=422)


# ===========================================================================
# boundary_precision_check / readiness_score_below_one_blocks_certificate_empty_online
# ===========================================================================
def _student_road6_class30_online0():
    """ROAD_READY student with road 6 + classroom 30 + online 0 -> readiness 0.8."""
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context(package_overrides={
        "price_cents": 90000, "enrollment_fee_cents": 5000,
        "included_classroom_hours": 30, "included_online_hours": 8,
        "included_road_hours": 6, "bundle_discount_cents": 5000,
    })
    stu, enr = ctx["student"], ctx["enrollment"]
    inst, veh = ctx["instructor"], ctx["vehicle"]
    schedule_and_complete(stu["id"], enr["id"], "CLASSROOM",
                         "2026-06-02T08:00:00.000Z", "2026-06-03T14:00:00.000Z",
                         inst["id"], "2026-06-03T14:00:00.000Z")
    schedule_and_complete(stu["id"], enr["id"], "ROAD",
                         "2026-06-04T08:00:00.000Z", "2026-06-04T14:00:00.000Z",
                         inst["id"], "2026-06-04T14:00:00.000Z", vehicle_id=veh["id"])
    return stu, enr


def test_certificate_blocked_when_readiness_below_one(api):
    """PRD §3.7: "It is legal only when the student is at `ROAD_READY` and their
    `readiness_score` equals exactly 1.0; a readiness below 1.0 is rejected with
    `ERR_READINESS_NOT_MET`."

    Design: Difficulty/boundary_precision_check/readiness_score_below_one_blocks_certificate_empty_online
    """
    stu, enr = _student_road6_class30_online0()
    resp = api.issue_certificate(stu["id"], {"enrollment_id": enr["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_READINESS_NOT_MET, expected_status=422)
    after = validate_success(api.get_student(stu["id"], ADMIN))
    assert after["status"] == "ROAD_READY"


def test_readiness_score_is_point_eight_with_zero_online(api):
    """PRD §3.7: "Because the weights total exactly 1.0 and each ratio is capped
    at 1.0, the score reaches exactly 1.0 if and only if all three floors are
    fully met, which is the precise gate for certification."
    PRD §3.7: "road against a floor of 6 hours, classroom against a floor of 30
    hours, online against a floor of 8 hours."

    Design: Difficulty/boundary_precision_check/readiness_score_below_one_blocks_certificate_empty_online
    """
    stu, _enr = _student_road6_class30_online0()
    after = validate_success(api.get_student(stu["id"], ADMIN))
    assert after["readiness_score"] == 0.8  # 0.5 + 0.3 + 0.0
    assert after["completed_online_hours"] == 0


# ===========================================================================
# cross_entity_state_dependency / road_lesson_requires_student_permitted_status
# ===========================================================================
def test_road_lesson_requires_permitted_student(api):
    """PRD §3.6: "a `ROAD` lesson requires the student to be at `PERMITTED` or
    `ROAD_READY` (a recorded permit), the assigned instructor to be
    `certified_road`, and the assigned vehicle to be `dual_control`; any of
    these missing yields `ERR_ROAD_PREREQUISITE_NOT_MET`."

    Design: Difficulty/cross_entity_state_dependency/road_lesson_requires_student_permitted_status
    """
    set_clock("2026-06-01T00:00:00.000Z")
    pkg = create_package(price_cents=60000, enrollment_fee_cents=0,
                         included_classroom_hours=0, included_online_hours=0,
                         included_road_hours=6, bundle_discount_cents=0)
    inst = create_instructor(certified_road=True)
    veh = create_vehicle(dual_control=True)
    stu = create_student(date_of_birth="1990-01-01")
    enr = create_active_enrollment(stu["id"], pkg["id"])  # student now ENROLLED
    payload = create_lesson_payload(
        stu["id"], enr["id"], "ROAD",
        "2026-06-20T09:00:00.000Z", "2026-06-20T11:00:00.000Z",
        student_version(stu["id"]),
        instructor_id=inst["id"], vehicle_id=veh["id"],
    )
    resp = api.create_lesson(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ROAD_PREREQUISITE_NOT_MET, expected_status=422)
    after = validate_success(api.get_student(stu["id"], ADMIN))
    assert after["status"] == "ENROLLED"


def test_road_lesson_succeeds_once_student_permitted(api):
    """PRD §3.3: "Recording a learner permit is a `SchoolAdmin` action that
    supplies a non-empty `permit_number` and advances the student from
    `ENROLLED` to `PERMITTED`."
    PRD §3.6: "a `ROAD` lesson requires the student to be at `PERMITTED` or
    `ROAD_READY` (a recorded permit)."

    Design: Difficulty/cross_entity_state_dependency/road_lesson_requires_student_permitted_status
    """
    set_clock("2026-06-01T00:00:00.000Z")
    ctx = setup_road_scheduling_context()  # student is PERMITTED
    lesson = schedule_lesson(
        ctx["student"]["id"], ctx["enrollment"]["id"], "ROAD",
        "2026-06-20T09:00:00.000Z", "2026-06-20T11:00:00.000Z",
        instructor_id=ctx["instructor"]["id"], vehicle_id=ctx["vehicle"]["id"],
    )
    assert lesson["status"] == "SCHEDULED"


# ===========================================================================
# cross_entity_state_dependency / enrollment_activate_requires_guardian_consent_granted
# ===========================================================================
def test_activate_minor_enrollment_blocked_when_consent_pending(api):
    """PRD §3.4: "if the enrolling student is a minor it requires a `GRANTED`
    guardian consent for that student, the absence of which is rejected with
    `ERR_GUARDIAN_CONSENT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_requires_guardian_consent_granted
    """
    set_clock("2026-06-01T00:00:00.000Z")
    pkg = create_package(price_cents=90000, enrollment_fee_cents=5000,
                         included_classroom_hours=30, included_online_hours=8,
                         included_road_hours=6, bundle_discount_cents=5000)
    stu = create_student(date_of_birth="2011-01-01")  # minor
    consent = validate_success(
        api.create_guardian_consent(
            {"student_id": stu["id"], "guardian_name": "Gwen G",
             "guardian_email": "gwen@x.com", "relationship": "LEGAL_GUARDIAN"},
            ADMIN),
        expected_status=201,
    )  # PENDING, not granted
    enr = create_enrollment(stu["id"], pkg["id"])
    resp = api.activate_enrollment(enr["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_GUARDIAN_CONSENT_REQUIRED, expected_status=422)
    consent_after = validate_success(api.get_guardian_consent(consent["id"], ADMIN))
    assert consent_after["status"] == "PENDING"
    enr_after = validate_success(api.get_enrollment(enr["id"], ADMIN))
    assert enr_after["status"] == "DRAFT"


def test_activate_minor_enrollment_succeeds_once_consent_granted(api):
    """PRD §3.2: "A minor cannot be put behind the wheel, nor have an enrollment
    activated, until a guardian has consented."
    PRD §3.4: "if the enrolling student is a minor it requires a `GRANTED`
    guardian consent for that student."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_requires_guardian_consent_granted
    """
    set_clock("2026-06-01T00:00:00.000Z")
    pkg = create_package(price_cents=90000, enrollment_fee_cents=5000,
                         included_classroom_hours=30, included_online_hours=8,
                         included_road_hours=6, bundle_discount_cents=5000)
    stu = create_student(date_of_birth="2011-01-01")
    create_granted_consent(stu["id"], guardian_email="gwen2@x.com",
                          relationship="LEGAL_GUARDIAN")
    enr = create_active_enrollment(stu["id"], pkg["id"])
    assert enr["status"] == "ACTIVE"


# ===========================================================================
# resource_temporal_overlap / instructor_overlap_adjacency_allowed_overlap_rejected
# ===========================================================================
def test_instructor_overlap_rejected(api):
    """PRD §3.6: "The assigned instructor must have no other `SCHEDULED` lesson
    whose half-open interval overlaps this one; back-to-back adjacency where one
    lesson's end exactly meets the next lesson's start is allowed, but any true
    overlap is rejected with `ERR_INSTRUCTOR_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/instructor_overlap_adjacency_allowed_overlap_rejected
    """
    set_clock("2026-06-01T00:00:00.000Z")
    pkg = create_package(price_cents=60000, enrollment_fee_cents=0,
                         included_classroom_hours=30, included_online_hours=0,
                         included_road_hours=0, bundle_discount_cents=0)
    inst = create_instructor(certified_road=False)
    sa = create_student(date_of_birth="1990-01-01")
    ea = create_active_enrollment(sa["id"], pkg["id"])
    schedule_lesson(sa["id"], ea["id"], "CLASSROOM",
                   "2026-06-10T09:00:00.000Z", "2026-06-10T10:00:00.000Z",
                   instructor_id=inst["id"])
    sb = create_student(date_of_birth="1990-01-01")
    eb = create_active_enrollment(sb["id"], pkg["id"])
    # 09:30 overlaps [09:00,10:00) -> rejected.
    payload = create_lesson_payload(
        sb["id"], eb["id"], "CLASSROOM",
        "2026-06-10T09:30:00.000Z", "2026-06-10T10:30:00.000Z",
        student_version(sb["id"]), instructor_id=inst["id"],
    )
    resp = api.create_lesson(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_DOUBLE_BOOKED, expected_status=409)


def test_instructor_adjacency_allowed(api):
    """PRD §3.6: "back-to-back adjacency where one lesson's end exactly meets
    the next lesson's start is allowed."

    Design: Difficulty/resource_temporal_overlap/instructor_overlap_adjacency_allowed_overlap_rejected
    """
    set_clock("2026-06-01T00:00:00.000Z")
    pkg = create_package(price_cents=60000, enrollment_fee_cents=0,
                         included_classroom_hours=30, included_online_hours=0,
                         included_road_hours=0, bundle_discount_cents=0)
    inst = create_instructor(certified_road=False)
    sa = create_student(date_of_birth="1990-01-01")
    ea = create_active_enrollment(sa["id"], pkg["id"])
    schedule_lesson(sa["id"], ea["id"], "CLASSROOM",
                   "2026-06-10T09:00:00.000Z", "2026-06-10T10:00:00.000Z",
                   instructor_id=inst["id"])
    sb = create_student(date_of_birth="1990-01-01")
    eb = create_active_enrollment(sb["id"], pkg["id"])
    # 10:00 start exactly meets the prior end -> adjacency allowed.
    lesson = schedule_lesson(sb["id"], eb["id"], "CLASSROOM",
                            "2026-06-10T10:00:00.000Z", "2026-06-10T11:00:00.000Z",
                            instructor_id=inst["id"])
    assert lesson["status"] == "SCHEDULED"


# ===========================================================================
# resource_temporal_overlap / vehicle_overlap_includes_prep_buffer_after
# ===========================================================================
def _vehicle_buffer_setup():
    """Vehicle with prep_buffer 15 already booked ROAD 09:00-10:00. Returns
    (veh, inst_b, student_b, enrollment_b) ready to book a second road lesson."""
    set_clock("2026-06-01T00:00:00.000Z")
    pkg = create_package(price_cents=60000, enrollment_fee_cents=0,
                         included_classroom_hours=0, included_online_hours=0,
                         included_road_hours=6, bundle_discount_cents=0)
    ia = create_instructor(certified_road=True)
    ib = create_instructor(certified_road=True)
    veh = create_vehicle(dual_control=True, prep_buffer_minutes=15)
    sa = create_student(date_of_birth="1990-01-01")
    ea = create_active_enrollment(sa["id"], pkg["id"])
    validate_success(api_client.record_permit(sa["id"], {"permit_number": "P-VA"}, ADMIN))
    schedule_lesson(sa["id"], ea["id"], "ROAD",
                   "2026-06-10T09:00:00.000Z", "2026-06-10T10:00:00.000Z",
                   instructor_id=ia["id"], vehicle_id=veh["id"])
    sb = create_student(date_of_birth="1990-01-01")
    eb = create_active_enrollment(sb["id"], pkg["id"])
    validate_success(api_client.record_permit(sb["id"], {"permit_number": "P-VB"}, ADMIN))
    return veh, ib, sb, eb


def test_vehicle_overlap_within_prep_buffer_rejected(api):
    """PRD §3.6: "For a road lesson the assigned vehicle must likewise be free,
    but the vehicle's window is padded: an existing booking's interval is
    expanded by that vehicle's `prep_buffer_minutes` of mandatory
    cleaning-and-fueling time **after** its end, and if that padded window
    overlaps the new lesson's interval the request is rejected with
    `ERR_VEHICLE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/vehicle_overlap_includes_prep_buffer_after
    """
    veh, ib, sb, eb = _vehicle_buffer_setup()
    # 10:00 start falls inside [09:00,10:15) buffer-padded occupancy.
    payload = create_lesson_payload(
        sb["id"], eb["id"], "ROAD",
        "2026-06-10T10:00:00.000Z", "2026-06-10T11:00:00.000Z",
        student_version(sb["id"]), instructor_id=ib["id"], vehicle_id=veh["id"],
    )
    resp = api.create_lesson(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED, expected_status=409)


def test_vehicle_booking_after_prep_buffer_allowed(api):
    """PRD §3.6: "an existing booking's interval is expanded by that vehicle's
    `prep_buffer_minutes` of mandatory cleaning-and-fueling time **after** its
    end, and if that padded window overlaps the new lesson's interval the
    request is rejected with `ERR_VEHICLE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/vehicle_overlap_includes_prep_buffer_after
    """
    veh, ib, sb, eb = _vehicle_buffer_setup()
    # 10:15 start exactly meets the end of the buffer-padded window -> allowed.
    lesson = schedule_lesson(sb["id"], eb["id"], "ROAD",
                            "2026-06-10T10:15:00.000Z", "2026-06-10T11:15:00.000Z",
                            instructor_id=ib["id"], vehicle_id=veh["id"])
    assert lesson["status"] == "SCHEDULED"


# ===========================================================================
# priority_pair_validation_conflict / state_beats_guardian_consent_on_refund_of_draft
# ===========================================================================
def test_refund_of_draft_enrollment_returns_invalid_state(api):
    """PRD §3.5: "Refund, a `SchoolAdmin` action, moves the enrollment from
    `ACTIVE` to `REFUNDED`. ... Refund is legal only from `ACTIVE`."
    PRD §2.11: "Only then are state-machine legality (`ERR_INVALID_STATE`, 409)
    and, where applicable, the lesson-scheduling stale-version check ...
    evaluated. Business-rule checks — guardian consent ... — follow after
    those."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_guardian_consent_on_refund_of_draft
    """
    set_clock("2026-06-01T00:00:00.000Z")
    pkg = create_package(price_cents=90000, enrollment_fee_cents=5000,
                         included_classroom_hours=30, included_online_hours=8,
                         included_road_hours=6, bundle_discount_cents=5000)
    stu = create_student(date_of_birth="2010-01-01")  # minor, no consent granted
    enr = create_enrollment(stu["id"], pkg["id"])  # stays DRAFT
    resp = api.refund_enrollment(
        enr["id"], {"refund_method": "PRO_RATA", "refund_destination": "WALLET"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_refund_of_draft_leaves_enrollment_draft(api):
    """PRD §3.5: "Refund is legal only from `ACTIVE`."
    PRD §2.7: "These reversions are not error conditions" — the rejected refund
    leaves the draft untouched (no state change on an illegal transition).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_guardian_consent_on_refund_of_draft
    """
    set_clock("2026-06-01T00:00:00.000Z")
    pkg = create_package(price_cents=90000, enrollment_fee_cents=5000,
                         included_classroom_hours=30, included_online_hours=8,
                         included_road_hours=6, bundle_discount_cents=5000)
    stu = create_student(date_of_birth="2010-01-01")
    enr = create_enrollment(stu["id"], pkg["id"])
    api.refund_enrollment(
        enr["id"], {"refund_method": "PRO_RATA", "refund_destination": "WALLET"},
        ADMIN,
    )
    after = validate_success(api.get_enrollment(enr["id"], ADMIN))
    assert after["status"] == "DRAFT"


# ===========================================================================
# priority_pair_validation_conflict / guardian_consent_beats_road_prereq_on_road_schedule
# ===========================================================================
def _minor_active_revoked_consent_not_permitted():
    """Minor whose enrollment is ACTIVE (consent was GRANTED to activate, then
    REVOKED), student NOT permitted, certified instructor + dual vehicle present.
    Returns (student, enrollment, instructor, vehicle)."""
    set_clock("2026-06-01T00:00:00.000Z")
    pkg = create_package(price_cents=90000, enrollment_fee_cents=5000,
                         included_classroom_hours=30, included_online_hours=8,
                         included_road_hours=6, bundle_discount_cents=5000)
    inst = create_instructor(certified_road=True)
    veh = create_vehicle(dual_control=True)
    stu = create_student(date_of_birth="2010-01-01")
    consent = create_granted_consent(stu["id"], guardian_email="gus@x.com")
    enr = create_active_enrollment(stu["id"], pkg["id"])  # consent GRANTED, ok
    validate_success(
        api_client.revoke_consent(consent["id"], make_guardian_headers(consent["id"]))
    )
    return stu, enr, inst, veh


def test_road_schedule_consent_required_beats_road_prereq(api):
    """PRD §3.6: "A minor with no `GRANTED` guardian consent cannot have a road
    lesson booked and is rejected with `ERR_GUARDIAN_CONSENT_REQUIRED`. The road
    prerequisite bundle is then enforced."
    PRD §2.8: "Guardian consent that is later revoked does not retroactively
    undo road lessons that were already completed; it only blocks the scheduling
    of new ones."

    Design: Difficulty/priority_pair_validation_conflict/guardian_consent_beats_road_prereq_on_road_schedule
    """
    stu, enr, inst, veh = _minor_active_revoked_consent_not_permitted()
    payload = create_lesson_payload(
        stu["id"], enr["id"], "ROAD",
        "2026-06-20T09:00:00.000Z", "2026-06-20T11:00:00.000Z",
        student_version(stu["id"]),
        instructor_id=inst["id"], vehicle_id=veh["id"],
    )
    resp = api.create_lesson(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_GUARDIAN_CONSENT_REQUIRED, expected_status=422)


def test_road_schedule_blocked_consent_no_lesson_created(api):
    """PRD §3.6: "A minor with no `GRANTED` guardian consent cannot have a road
    lesson booked and is rejected with `ERR_GUARDIAN_CONSENT_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/guardian_consent_beats_road_prereq_on_road_schedule
    """
    stu, enr, inst, veh = _minor_active_revoked_consent_not_permitted()
    payload = create_lesson_payload(
        stu["id"], enr["id"], "ROAD",
        "2026-06-20T09:00:00.000Z", "2026-06-20T11:00:00.000Z",
        student_version(stu["id"]),
        instructor_id=inst["id"], vehicle_id=veh["id"],
    )
    api.create_lesson(payload, ADMIN)
    lessons, _ = validate_paginated(
        api.list_lessons(ADMIN, params={"student_id": stu["id"]})
    )
    assert lessons == []
