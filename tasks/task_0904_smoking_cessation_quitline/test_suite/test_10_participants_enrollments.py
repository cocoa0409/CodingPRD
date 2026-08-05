"""Participant registration, enrollment creation defaults, and not-found handling."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_participant, create_enrollment,
)

CM = TEST_USERS["case_manager_headers"]


def test_participant_missing_required_field_returns_validation(api):
    """PRD §2.5: "a syntactically malformed body — a missing required field, a value
    out of range, or an invalid enum member — is rejected with `ERR_VALIDATION` (400)."

    Design: Corner/entities/participant_missing_required_field_returns_validation
    """
    payload = {"full_name": "P", "email": "p@x.com", "primary_language": "EN"}
    resp = api.create_participant(payload, CM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_self_pay_enrollment_defaults_nrt_allotment(api):
    """PRD §3.2: "Its `nrt_courses_allotted` is copied from the sponsor program's
    `nrt_courses_allotted` when the participant is sponsored, and otherwise takes the
    self-pay default of `DEFAULT_SELF_PAY_NRT_COURSES`, which is 2. At creation
    `nrt_courses_used` is 0 and `nrt_eligibility` is `ELIGIBLE`."

    Design: Corner/entities/self_pay_enrollment_defaults_nrt_allotment
    """
    part = create_participant(api, cpd=10)  # no employer_program_id -> self-pay
    enr = create_enrollment(api, part["id"])
    assert enr["nrt_courses_allotted"] == 2
    assert enr["nrt_eligibility"] == "ELIGIBLE"


def test_participant_get_nonexistent_returns_not_found(api):
    """PRD §2.5: "The first identifier that does not correspond to an existing
    resource halts processing with that resource's specific not-found error —
    `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_EMPLOYER_PROGRAM_NOT_FOUND`, `ERR_COACH_NOT_FOUND`,
    `ERR_QUIT_ATTEMPT_NOT_FOUND`, `ERR_COACHING_CALL_NOT_FOUND`, or
    `ERR_NRT_SHIPMENT_NOT_FOUND` — before any deeper resource or business rule is
    consulted."

    Design: Corner/entities/participant_get_nonexistent_returns_not_found
    """
    resp = api.get_participant(NON_EXISTENT_UUID, CM)
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_FOUND.value)


def test_enrollment_system_fields_generated(api):
    """PRD §3.2: "A new enrollment begins in `PENDING_ASSESSMENT`, with
    `participant_id` set to its owner."
    PRD §2.4: "`version` — an integer that begins at 1 on creation and increments by
    one on every mutation."

    Design: Corner/entities/enrollment_system_fields_generated
    """
    part = create_participant(api, cpd=10)
    enr = validate_success(api.create_enrollment(part["id"], {}, CM), 201)
    assert enr["status"] == "PENDING_ASSESSMENT"
    assert enr["version"] == 1
    assert enr["participant_id"] == part["id"]


def test_transition_unknown_quit_attempt_returns_not_found(api):
    """PRD §2.5: "The first identifier that does not correspond to an existing
    resource halts processing with that resource's specific not-found error —
    `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_EMPLOYER_PROGRAM_NOT_FOUND`, `ERR_COACH_NOT_FOUND`,
    `ERR_QUIT_ATTEMPT_NOT_FOUND`, `ERR_COACHING_CALL_NOT_FOUND`, or
    `ERR_NRT_SHIPMENT_NOT_FOUND` — before any deeper resource or business rule is
    consulted."

    Design: Corner/endpoints/transition_unknown_quit_attempt_returns_not_found
    """
    resp = api.transition_quit_attempt(NON_EXISTENT_UUID, {"to_status": "RELAPSED"}, CM)
    validate_error(resp, ApiErrorId.ERR_QUIT_ATTEMPT_NOT_FOUND.value)
