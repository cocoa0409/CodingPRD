"""Reference-data registration, referral intake, and simple state guards.

Queue B (Corner) instances from sections `entities` and `state_machines`.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_patient, assert_program,
)
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import make_coordinator_headers, make_physician_headers


def test_patient_create_returns_201_with_server_fields(api, coordinator_headers):
    """PRD §3.1: "A `Patient` is registered with a medical record number `mrn`
    (unique per patient), a `full_name`, and a `date_of_birth` given as an ISO 8601
    calendar date."
    PRD §2.4: "`version`: an integer that begins at 1 on creation and increments by
    one on every mutation of the resource."

    Design: Corner/entities/patient_create_returns_201_with_fields
    """
    payload = F.create_patient_payload(mrn="C-001-MRN", full_name="Corner One")
    data = validate_success(api.create_patient(payload, coordinator_headers), expected_status=201)
    assert_patient(data)
    assert data["mrn"] == "C-001-MRN"
    assert data["full_name"] == "Corner One"
    assert data["version"] == 1

    got = validate_success(api.get_patient(data["id"], coordinator_headers))
    assert got["id"] == data["id"]
    assert got["mrn"] == "C-001-MRN"


def test_get_program_nonexistent_returns_404(api, coordinator_headers):
    """PRD §2.5: "The first identifier that does not resolve to an existing resource
    produces that resource's specific not-found error (for example,
    `ERR_PROGRAM_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, ...),
    each returned with HTTP 404."

    Design: Corner/entities/get_program_nonexistent_returns_404
    """
    resp = api.get_program(NON_EXISTENT_UUID, coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND, expected_status=404)


def test_referral_missing_required_risk_returns_validation(api):
    """PRD §2.5: "A malformed body — a missing required field, a value of the wrong
    type, or an unparseable payload — is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/referral_missing_required_risk_returns_validation
    """
    patient = X.create_patient(api)
    physician = X.create_physician(api)
    phys = make_physician_headers(physician["id"])
    payload = {
        "patient_id": patient["id"],
        "physician_id": physician["id"],
        "program_type": "CARDIAC",
        "indication": "post-MI",
        # risk_stratification omitted
    }
    validate_error(api.create_referral(payload, phys), ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_referral_invalid_enum_risk_returns_error(api):
    """PRD §2.5: "When an enum-typed field carries a value outside its declared set,
    the rejection is `ERR_INVALID_ENUM` (HTTP 400)."

    Design: Corner/entities/referral_invalid_enum_risk_returns_error
    """
    patient = X.create_patient(api)
    physician = X.create_physician(api)
    phys = make_physician_headers(physician["id"])
    payload = F.create_referral_payload(patient["id"], physician["id"], risk_stratification="SEVERE")
    validate_error(api.create_referral(payload, phys), ApiErrorId.ERR_INVALID_ENUM, expected_status=400)


def test_program_authorized_session_cap_defaults_36(api, coordinator_headers):
    """PRD §3.3: "`authorized_session_cap` defaults to 36 when omitted; and the
    program starts in `DRAFT` status."

    Design: Corner/entities/program_authorized_session_cap_defaults_36
    """
    referral = X.create_accepted_referral(api, risk_stratification="LOW")
    data = validate_success(
        api.create_program(F.create_program_payload(referral["id"]), coordinator_headers),
        expected_status=201,
    )
    assert_program(data)
    assert data["authorized_session_cap"] == 36
    assert data["status"] == "DRAFT"


def test_program_computed_counters_start_zero(api, coordinator_headers):
    """PRD §2.8: "`sessions_used` is the count of this program's sessions in
    `COMPLETED` status."
    PRD §2.9: "`total_billed_cents` sums each claim's `billed_amount_cents`; ... and
    `outstanding_balance_cents` sums the patient-responsibility amounts of claims
    currently in `DENIED` status (the portion not recovered from the payer)."

    Design: Corner/entities/program_computed_counters_start_zero
    """
    referral = X.create_accepted_referral(api, risk_stratification="LOW")
    data = validate_success(
        api.create_program(F.create_program_payload(referral["id"]), coordinator_headers),
        expected_status=201,
    )
    assert data["sessions_used"] == 0
    assert data["total_billed_cents"] == 0
    assert data["outstanding_balance_cents"] == 0


def test_decision_on_declined_referral_returns_not_pending(api, coordinator_headers):
    """PRD §3.2: "A decision may only be rendered on a referral that is still
    `PENDING`; otherwise the request is rejected with `ERR_REFERRAL_NOT_PENDING`."

    Design: Corner/state_machines/decision_on_declined_referral_returns_not_pending
    """
    referral = X.create_accepted_referral(api, risk_stratification="LOW", decision="DECLINE")
    resp = api.decide_referral(referral["id"], {"decision": "ACCEPT"}, coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_PENDING, expected_status=409)


def test_approve_already_approved_authorization_returns_not_pending(api, coordinator_headers):
    """PRD §3.3: "Approving it — permitted only while it is `PENDING`, else
    `ERR_AUTHORIZATION_NOT_PENDING` — moves it to `APPROVED`."

    Design: Corner/state_machines/approve_already_approved_authorization_returns_invalid
    """
    ctx = X.setup_draft_program(api, risk_stratification="LOW", with_baseline=False)
    resp = api.approve_authorization(ctx["authorization_id"], coordinator_headers)
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_PENDING, expected_status=409)
