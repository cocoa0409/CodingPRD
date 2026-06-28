"""Entity creation/retrieval/listing, defaults, validations (PRD §2.3, §3.1, §3.2, §3.5, §3.9).

Corner queue (entities): create/get student, list cohorts paginated, not-found,
   missing-required, invalid-enum, default track, computed placement_level null,
   unknown sponsor contract, attendance immutability.
Corner queue (validations): duplicate email, duplicate session, invalid termination
   reason, not-found-before-state, add-on enrollment mismatch.
Corner queue (errors): pagination out of bounds.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    create_cohort, create_student, create_placed_student, create_enrollment, confirm,
    create_corporate_contract_payload, mark_attendance,
)

REG = TEST_USERS["registrar_headers"]
DSO = TEST_USERS["dso_headers"]
INSTR = TEST_USERS["instructor_headers"]


# =====================================================================
# Corner / entities / create_student_returns_201_with_system_fields
# =====================================================================
def test_create_student_returns_201_with_system_defaults(api):
    """PRD §3.1: "Registration captures the student's legal full_name and a contact
    email, and may declare whether the student is_international (defaulting to false),
    which program track they study in (one of GENERAL, ACADEMIC, BUSINESS, or
    EXAM_PREP, defaulting to GENERAL)"
    PRD §3.1: "The visa_status (one of NONE, INITIAL, ACTIVE, PROBATION, or
    TERMINATED, defaulting to NONE ...)"

    Design: Corner/entities/create_student_returns_201_with_system_fields
    """
    data = validate_success(api.create_student({"full_name": "New Stu", "email": "new1@x.com"}, REG), 201)
    assert data["full_name"] == "New Stu"
    assert data["visa_status"] == "NONE"
    assert data["certification_status"] == "NONE"
    assert data["track"] == "GENERAL"
    assert data["version"] == 1


# =====================================================================
# Corner / entities / get_student_returns_stored_entity
# =====================================================================
def test_get_student_returns_stored_entity(api):
    """PRD §3.1: "Registration captures the student's legal full_name and a contact email"

    Design: Corner/entities/get_student_returns_stored_entity
    """
    created = get_success_data(api.create_student({"full_name": "Read Me", "email": "read1@x.com"}, REG))
    data = validate_success(api.get_student(created["id"], REG))
    assert data["full_name"] == "Read Me"


# =====================================================================
# Corner / entities / list_cohorts_returns_paginated_envelope
# =====================================================================
def test_list_cohorts_returns_paginated_envelope(api):
    """PRD §2.3: "List responses carry the pagination bookkeeping in the meta object
    of the envelope, exposing limit, offset, total_count, and has_more."

    Design: Corner/entities/list_cohorts_returns_paginated_envelope
    """
    create_cohort(level="A1", track="GENERAL", schedule_block="MORNING", name="L1")
    create_cohort(level="A2", track="GENERAL", schedule_block="AFTERNOON", name="L2")
    data, meta = validate_paginated(api.list_cohorts(REG, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# =====================================================================
# Corner / entities / get_student_nonexistent_returns_not_found
# =====================================================================
def test_get_student_nonexistent_returns_not_found(api):
    """PRD §2.8: "The request is rejected with ERR_NOT_FOUND (HTTP 404) for the first
    identifier in that order that does not correspond to an existing resource."

    Design: Corner/entities/get_student_nonexistent_returns_not_found
    """
    validate_error(api.get_student(NON_EXISTENT_UUID, REG), ApiErrorId.ERR_NOT_FOUND.value)


# =====================================================================
# Corner / entities / create_student_missing_required_field_returns_invalid_request
# =====================================================================
def test_create_student_missing_email_returns_invalid_request(api):
    """PRD §3.1: "Registration captures the student's legal full_name and a contact email"
    PRD §3.2: "Any cohort field that violates its range or enum ... is rejected with
    ERR_INVALID_REQUEST (HTTP 422)." (the same field-level validation applies to
    missing required inputs across create endpoints, §2.8 final gate)

    Design: Corner/entities/create_student_missing_required_field_returns_invalid_request
    """
    validate_error(api.create_student({"full_name": "No Email"}, REG), ApiErrorId.ERR_INVALID_REQUEST.value)


# =====================================================================
# Corner / entities / create_cohort_invalid_enum_level_returns_invalid_request
# =====================================================================
def test_create_cohort_invalid_enum_level_returns_invalid_request(api):
    """PRD §3.2: "Any cohort field that violates its range or enum, or a term_end not
    strictly after term_start, is rejected with ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_cohort_invalid_enum_level_returns_invalid_request
    """
    payload = {
        "name": "Bad", "level": "Z9", "track": "GENERAL", "capacity": 5, "weekly_hours": 9,
        "term_start": "2026-05-04T00:00:00Z", "term_end": "2026-08-01T00:00:00Z",
        "total_sessions": 40, "base_tuition_cents": 100000, "schedule_block": "MORNING",
    }
    validate_error(api.create_cohort(payload, REG), ApiErrorId.ERR_INVALID_REQUEST.value)


# =====================================================================
# Corner / entities / student_track_default_applied_when_omitted
# =====================================================================
def test_student_track_default_applied_when_omitted(api):
    """PRD §3.1: "which program track they study in (one of GENERAL, ACADEMIC,
    BUSINESS, or EXAM_PREP, defaulting to GENERAL)"

    Design: Corner/entities/student_track_default_applied_when_omitted
    """
    data = validate_success(api.create_student({"full_name": "Def", "email": "def1@x.com"}, REG), 201)
    assert data["track"] == "GENERAL"


# =====================================================================
# Corner / entities / student_placement_level_computed_input_ignored
# =====================================================================
def test_student_placement_level_null_until_scored(api):
    """PRD §3.1: "The placement_level holds the CEFR level assigned by the student's
    most recent scored placement test and is one of A1, A2, B1, B2, C1, or C2,
    remaining null until a test is scored."

    Design: Corner/entities/student_placement_level_computed_input_ignored
    """
    created = get_success_data(api.create_student({"full_name": "NoLvl", "email": "nolvl1@x.com"}, REG))
    data = validate_success(api.get_student(created["id"], REG))
    assert data["placement_level"] is None, "placement_level null until a test is scored"


# =====================================================================
# Corner / entities / student_sponsor_unknown_contract_returns_not_found
# =====================================================================
def test_student_sponsor_unknown_contract_returns_not_found(api):
    """PRD §3.1: "When a corporate_contract_id is supplied, it must reference an
    existing contract; if it does not, the registration is rejected with
    ERR_CONTRACT_REQUIRED_FOR_SPONSOR (HTTP 404)."

    Design: Corner/entities/student_sponsor_unknown_contract_returns_not_found
    """
    payload = {"full_name": "Orphan", "email": "orphan1@x.com", "corporate_contract_id": NON_EXISTENT_UUID}
    validate_error(api.create_student(payload, REG), ApiErrorId.ERR_CONTRACT_REQUIRED_FOR_SPONSOR.value)


# =====================================================================
# Corner / entities / attendance_record_is_immutable_no_version
# =====================================================================
def test_attendance_record_has_no_version_field(api):
    """PRD §2.4: "Two entities are deliberate exceptions to this convention: the
    AttendanceRecord and the ComplianceEvent. These are append-only records that are
    never modified after creation. Each therefore carries only an id (UUID) and a
    created_at timestamp; both updated_at and version are absent on these two entities."

    Design: Corner/entities/attendance_record_is_immutable_no_version
    """
    cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=18, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    data = validate_success(api.create_attendance(
        {"enrollment_id": enr["id"], "session_index": 1, "status": "PRESENT"}, INSTR), 201)
    assert data["id"] is not None
    assert "version" not in data, "AttendanceRecord must NOT carry a version field"


# =====================================================================
# Corner / validations / duplicate_email_returns_conflict
# =====================================================================
def test_duplicate_email_case_insensitive_returns_conflict(api):
    """PRD §3.1: "Email addresses must be unique across all students when compared
    case-insensitively; a registration whose email collides with an existing student
    is rejected with ERR_DUPLICATE_EMAIL (HTTP 409)."

    Design: Corner/validations/duplicate_email_returns_conflict
    """
    get_success_data(api.create_student({"full_name": "First", "email": "dup1@x.com"}, REG))
    validate_error(api.create_student({"full_name": "Second", "email": "DUP1@X.COM"}, REG),
                   ApiErrorId.ERR_DUPLICATE_EMAIL.value)


# =====================================================================
# Corner / validations / duplicate_attendance_session_index_returns_conflict
# =====================================================================
def test_duplicate_attendance_session_index_returns_conflict(api):
    """PRD §3.5: "The session_index must be unique within a given enrollment and must
    fall within 1 through the cohort's total_sessions; a record whose index repeats an
    already-recorded session for that enrollment, or whose index falls outside that
    range, is rejected with ERR_DUPLICATE_SESSION (HTTP 409)."

    Design: Corner/validations/duplicate_attendance_session_index_returns_conflict
    """
    cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=18, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    mark_attendance(enr["id"], 1, "PRESENT")
    validate_error(api.create_attendance(
        {"enrollment_id": enr["id"], "session_index": 1, "status": "ABSENT"}, INSTR),
        ApiErrorId.ERR_DUPLICATE_SESSION.value)


# =====================================================================
# Corner / validations / invalid_termination_reason_returns_invalid_request
# =====================================================================
def test_invalid_termination_reason_returns_error(api):
    """PRD §3.7: "Termination requires the enrollment to be in ENROLLED state and a
    supplied termination_reason that is one of VISA_NONCOMPLIANCE, ATTENDANCE_FAILURE,
    or CONTRACT_REVOKED; a termination with a missing or out-of-set reason is rejected
    with ERR_INVALID_TERMINATION_REASON (HTTP 422)."

    Design: Corner/validations/invalid_termination_reason_returns_invalid_request
    """
    cohort = create_cohort(level="B1", track="GENERAL", weekly_hours=18, schedule_block="MORNING")
    stu = create_placed_student(level="B1", track="GENERAL")
    enr = create_enrollment(stu["id"], cohort["id"])
    confirm(enr["id"], cohort["version"], require_seat=True)
    validate_error(api.terminate_enrollment(enr["id"], {"termination_reason": "JUST_BECAUSE"}, DSO),
                   ApiErrorId.ERR_INVALID_TERMINATION_REASON.value)


# =====================================================================
# Corner / validations / not_found_checked_before_state_on_confirm
# =====================================================================
def test_confirm_nonexistent_enrollment_returns_not_found(api):
    """PRD §2.8: "fourth, existence of every referenced resource, validated left to
    right through the path and then the body (ERR_NOT_FOUND, 404); fifth, that the
    target resource is in a state from which the requested transition is legal
    (ERR_INVALID_STATE, 409)."

    Design: Corner/validations/not_found_checked_before_state_on_confirm
    """
    validate_error(api.confirm_enrollment(NON_EXISTENT_UUID, {"expected_cohort_version": 1, "require_seat": True}, REG),
                   ApiErrorId.ERR_NOT_FOUND.value)


# =====================================================================
# Corner / validations / addon_enrollment_mismatch_returns_conflict
# =====================================================================
def test_addon_enrollment_mismatch_returns_conflict(api):
    """PRD §3.6: "the named enrollment must belong to the named student, and if it
    does not the request is rejected with ERR_ADDON_ENROLLMENT_MISMATCH (HTTP 409)."

    Design: Corner/validations/addon_enrollment_mismatch_returns_conflict
    """
    cohort = create_cohort(level="B1", track="GENERAL", schedule_block="MORNING")
    stu_a = create_student(track="GENERAL")
    stu_b = create_student(track="GENERAL")
    enr_a = create_enrollment(stu_a["id"], cohort["id"])
    # Registrar creates an add-on with student B but A's enrollment.
    validate_error(api.create_add_on(
        {"student_id": stu_b["id"], "enrollment_id": enr_a["id"], "add_on_type": "CONVERSATION_CLUB", "units": 4}, REG),
        ApiErrorId.ERR_ADDON_ENROLLMENT_MISMATCH.value)


# =====================================================================
# Corner / errors / pagination_limit_out_of_bounds_returns_invalid
# =====================================================================
def test_pagination_limit_zero_returns_invalid(api):
    """PRD §2.3: "A request whose limit falls outside 1 through 100, or whose offset is
    below 0, is rejected with ERR_VALIDATION_PAGINATION (HTTP 422)."

    Design: Corner/errors/pagination_limit_out_of_bounds_returns_invalid
    """
    validate_error(api.list_students(REG, params={"limit": 0}), ApiErrorId.ERR_VALIDATION_PAGINATION.value)
