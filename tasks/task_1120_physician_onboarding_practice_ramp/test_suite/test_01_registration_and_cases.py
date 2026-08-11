"""Physician registration and case opening: creation defaults, uniqueness,
not-found resolution, computed-field handling, and schema validation."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    is_valid_uuid, ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    create_physician_payload, create_case_payload, create_physician, create_case,
)

RECRUITER = TEST_USERS["recruiter_headers"]


def test_physician_create_defaults_and_initial_state(api):
    """PRD §3.1: "A newly registered physician has `status` `PROSPECT`."
    PRD §2.4: "The server maintains a logical clock whose startup default is exactly 2026-05-01T00:00:00Z and which never falls back to wall-clock time"
    PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created."
    PRD §2.5: "`id` (string): a unique, server-minted UUID with no type prefix."
    PRD §2.5: "`version` (integer): a system-managed integer that increments on every mutation of the resource."

    Design: Corner/entities/physician_create_defaults_and_initial_state
    """
    resp = api.create_physician(
        create_physician_payload(
            full_name="Dr. Ann", specialty="PEDIATRICS",
            email="ann@x.com", hire_type="NEW_GRAD",
        ),
        RECRUITER,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "PROSPECT"
    assert data["version"] == 1
    assert data["created_at"] == "2026-05-01T00:00:00.000Z", (
        f"created_at must come from the logical clock startup default, got {data['created_at']!r}"
    )
    assert is_valid_uuid(data["id"])


def test_case_duplicate_for_same_physician_rejected(api):
    """PRD §3.1: "Exactly one case may exist per physician — a second attempt is rejected with `ERR_DUPLICATE_CASE` (HTTP 409)."

    Design: Corner/entities/case_duplicate_for_same_physician_rejected
    """
    physician = create_physician(full_name="Dr. Bo", specialty="CARDIOLOGY")
    create_case(physician["id"])
    resp = api.create_onboarding_case(
        create_case_payload(physician["id"], target_start_date="2027-07-01"), RECRUITER
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CASE)


def test_case_create_unknown_physician_returns_not_found(api):
    """PRD §2.10: "Identifiers supplied in a path or a body are validated left-to-right — physician first, then case, then the child resource — and the request is rejected immediately with the 404 corresponding to the first identifier that does not resolve."

    Design: Corner/entities/case_create_unknown_physician_returns_not_found
    """
    resp = api.create_onboarding_case(
        create_case_payload(NON_EXISTENT_UUID, target_start_date="2027-06-01"), RECRUITER
    )
    validate_error(resp, ApiErrorId.ERR_PHYSICIAN_NOT_FOUND)


def test_case_create_posture_input_ignored(api):
    """PRD §3.1: "A new case starts with `case_status` `IN_PROGRESS` and `posture` `PRE_CONTRACT`; its three parallel dimensions sit at `credential_status` `NOT_STARTED`, `training_status` `NOT_STARTED`, and `practice_status` `PLANNING`; `weekly_active_minutes`, `attained_milestone_count`, and `missed_milestone_count` are zero; `actual_start_date`, `latest_risk_score`, and `latest_risk_band` are null; and `at_risk` is false."

    Design: Corner/entities/case_create_posture_input_ignored
    """
    physician = create_physician(full_name="Dr. Cy", specialty="PEDIATRICS", hire_type="NEW_GRAD")
    payload = create_case_payload(physician["id"], target_start_date="2027-06-01")
    payload["posture"] = "LIVE"
    resp = api.create_onboarding_case(payload, RECRUITER)
    data = validate_success(resp, 201)
    assert data["posture"] == "PRE_CONTRACT", (
        "client-supplied value for the derived posture field must be ignored"
    )
    case = get_success_data(api.get_onboarding_case(data["id"], RECRUITER))
    assert case["case_status"] == "IN_PROGRESS"
    assert case["credential_status"] == "NOT_STARTED"
    assert case["training_status"] == "NOT_STARTED"
    assert case["practice_status"] == "PLANNING"
    assert case["weekly_active_minutes"] == 0
    assert case["attained_milestone_count"] == 0
    assert case["missed_milestone_count"] == 0
    assert case["actual_start_date"] is None
    assert case["latest_risk_score"] is None
    assert case["latest_risk_band"] is None
    assert case["at_risk"] is False


def test_create_physician_invalid_enum_returns_validation(api):
    """PRD §2.9: "Request body schema: required fields are present, enum members are valid, dates parse, `start_minute` precedes `end_minute`, `start_date` is not after `end_date`, and amounts are not negative, else `ERR_VALIDATION` (HTTP 400)."
    PRD §3.1: "The specialty is one of `FAMILY_MEDICINE`, `INTERNAL_MEDICINE`, `CARDIOLOGY`, `ORTHOPEDICS`, or `PEDIATRICS`"

    Design: Corner/entities/create_physician_invalid_enum_returns_validation
    """
    resp = api.create_physician(
        create_physician_payload(
            full_name="Dr. Zed", specialty="DERMATOLOGY",
            email="zed@x.com", hire_type="EXPERIENCED",
        ),
        RECRUITER,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
