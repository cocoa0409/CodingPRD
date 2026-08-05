"""Participant intake, priority-of-service computation, and the two parallel
eligibility/enrollment dimensions."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_area, intake_participant, make_eligible, enroll,
    create_participant_payload,
    ADMIN, CM, ANY,
)


def test_intake_computes_priority_for_adult_veteran(api):
    """PRD §3.2: "if the funding stream is `ADULT` and the participant is a veteran,
    is low-income, or is basic-skills-deficient, the priority is `PRIORITY`".

    Design: Corner/entities/intake_computes_priority_of_service_veteran
    """
    area = create_area(api)
    resp = api.create_participant(
        area["id"],
        create_participant_payload(full_name="Vet P", funding_stream="ADULT", veteran=True),
        CM)
    data = validate_success(resp, 201)
    assert data["priority_of_service"] == "PRIORITY", data
    assert data["supportive_available_cents"] == 200000


def test_intake_plain_adult_is_non_priority(api):
    """PRD §3.2: "otherwise the priority is `NON_PRIORITY`."

    Design: Corner/calculations/priority_of_service_plain_adult_non_priority
    """
    area = create_area(api)
    resp = api.create_participant(
        area["id"], create_participant_payload(full_name="Plain P", funding_stream="ADULT"), CM)
    data = validate_success(resp, 201)
    assert data["priority_of_service"] == "NON_PRIORITY", data


def test_intake_seeds_supportive_ledger_from_area_cap(api):
    """PRD §3.2: "Intake initializes the supportive pool by setting
    `supportive_available_cents` to the area's annual supportive cap."

    Design: Corner/entities/participant_supportive_ledger_seeded_from_area_cap
    """
    area = create_area(api, supportive_annual_cap_cents=200000)
    resp = api.create_participant(area["id"], create_participant_payload(), CM)
    data = validate_success(resp, 201)
    assert data["supportive_available_cents"] == 200000
    assert data["supportive_obligated_cents"] == 0
    assert data["supportive_expended_cents"] == 0


def test_intake_missing_funding_stream_rejected(api):
    """PRD §2.10: "Then request-body well-formedness is checked (`ERR_INVALID_REQUEST`,
    400): required fields present, enum values recognized, amounts and mileage strictly
    positive, dates parseable, and the period end strictly after its start."

    Design: Corner/entities/participant_intake_missing_funding_stream_returns_invalid_request
    """
    area = create_area(api)
    resp = api.create_participant(area["id"], {"full_name": "P One"}, CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_nonexistent_participant_not_found(api):
    """PRD §2.10: "the first identifier in the path that does not resolve produces
    `ERR_NOT_FOUND` (404) before any deeper lookup is attempted."

    Design: Corner/entities/get_participant_nonexistent_returns_not_found
    """
    resp = api.get_participant("00000000-0000-0000-0000-000000000000", ANY)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_parallel_dimensions_advance_independently(api):
    """PRD §3.2: "a determination of eligible advances `eligibility_status` from
    `PENDING` to `ELIGIBLE`". PRD §3.2: "Enrolling a participant advances it from
    `NOT_ENROLLED` to `ENROLLED`".

    Design: Difficulty/non_linear_state_machine/participant_parallel_eligibility_enrollment
    """
    area = create_area(api)
    p = intake_participant(api, area["id"])
    make_eligible(api, p["id"])
    validate_success(api.enroll_participant(p["id"], CM))
    got = validate_success(api.get_participant(p["id"], CM))
    assert got["eligibility_status"] == "ELIGIBLE", got
    assert got["enrollment_status"] == "ENROLLED", got


def test_eligibility_advances_without_touching_enrollment(api):
    """PRD §3.2: "A participant carries two independent status dimensions that advance
    on their own triggers." PRD §3.2: "The enrollment dimension, `enrollment_status`,
    starts at `NOT_ENROLLED`."

    Design: Difficulty/non_linear_state_machine/participant_parallel_eligibility_enrollment
    """
    area = create_area(api)
    p = intake_participant(api, area["id"])
    after_elig = validate_success(api.determine_eligibility(p["id"], {"decision": "ELIGIBLE"}, CM))
    # Only the eligibility trigger fired: enrollment dimension is untouched.
    assert after_elig["eligibility_status"] == "ELIGIBLE", after_elig
    assert after_elig["enrollment_status"] == "NOT_ENROLLED", after_elig


def test_enroll_before_eligible_rejected(api):
    """PRD §3.2: "it is rejected with `ERR_PARTICIPANT_NOT_ELIGIBLE` unless the
    eligibility dimension is already `ELIGIBLE`".

    Design: Corner/state_machines/enroll_before_eligible_returns_not_eligible
    """
    area = create_area(api)
    p = intake_participant(api, area["id"])
    resp = api.enroll_participant(p["id"], CM)
    validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_ELIGIBLE.value)
