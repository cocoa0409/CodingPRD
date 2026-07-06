"""Consent capture, pre-op clearance, and the consent/deposit acceptance gates."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, PROC_A,
    create_procedure, create_patient, create_completed_consultation,
    create_draft_quote, create_presented_quote,
    create_consent_payload, create_clearance_payload,
)

FRONT = TEST_USERS["front_desk_headers"]
SURGEON = TEST_USERS["surgeon_headers"]


def test_consent_created_signed_when_surgical_consent_true(api):
    """PRD §3.4: "If surgical_consent_signed is true the record is created directly in
    SIGNED; otherwise it is created in PENDING."

    Design: Corner/endpoints/consent_created_signed_when_surgical_consent_true
    """
    quote, _cons, _pat, _lis = create_draft_quote([])
    resp = api.create_consent(quote["id"], create_consent_payload(
        before_photo_ref="s3://b/1", photo_consent_signed=True,
        surgical_consent_signed=True), FRONT)
    data = validate_success(resp, 201)
    assert data["status"] == "SIGNED"


def test_clearance_cleared_false_when_tier_insufficient(api):
    """PRD §3.5: "At issue time the system snapshots the patient's current
    clearance_tier into the record's tier_required ... and computes cleared: the
    clearance is considered satisfied when the provided tier meets or exceeds the
    required tier ... a required tier of MEDICAL is satisfied only by a provided
    MEDICAL."

    Design: Corner/endpoints/clearance_cleared_false_when_tier_insufficient
    """
    # asa 3 + smoker (age 40 bmi 25): (3-1)*25=50 + 20 = 70 -> MEDICAL
    patient = create_patient(full_name="Med M", date_of_birth="1986-01-01",
                             age_years=40, bmi=25, asa_class=3, smoker=True)
    resp = api.issue_clearance(patient["id"], create_clearance_payload(tier_provided="STANDARD"),
                               SURGEON)
    data = validate_success(resp, 201)
    assert data["tier_required"] == "MEDICAL"
    assert data["cleared"] is False


def test_accept_without_consent_rejected(api):
    """PRD §3.3: "First, a ConsentRecord for this quote must be SIGNED with
    surgical_consent_signed equal to true; absent that, the request is rejected with
    ERR_CONSENT_MISSING."

    Design: Difficulty/priority_pair_validation_conflict/priority_consent_missing_before_deposit_unpaid
    """
    procA = create_procedure(**PROC_A)
    # neither consent signed nor deposit paid -> higher-priority consent error surfaces
    quote, _cons, _pat, _lis = create_presented_quote([procA["id"]], sign_consent=False)
    resp = api.accept_quote(quote["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_CONSENT_MISSING, 409)


def test_consent_missing_precedes_deposit_unpaid_on_accept(api):
    """PRD §3.6: "The business gates then follow in this order: procedure-retired and
    empty-quote checks for their respective operations, then for booking the
    clearance-present safety check, then the operating-room overlap check, then the
    surgeon turnaround-buffer check, then the future-start check, then the deposit and
    financing fiscal checks where applicable, then the optimistic-concurrency version
    check, and finally the time-range check that the end follows the start."
    PRD §3.3: "absent that, the request is rejected with ERR_CONSENT_MISSING."

    Design: Difficulty/priority_pair_validation_conflict/priority_consent_missing_before_deposit_unpaid
    """
    procA = create_procedure(**PROC_A)
    quote, _cons, _pat, _lis = create_presented_quote([procA["id"]], sign_consent=False)
    # consent missing AND deposit unpaid both true; consent is the safety check that
    # precedes the fiscal deposit check, so ERR_CONSENT_MISSING wins.
    resp = api.accept_quote(quote["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_CONSENT_MISSING, 409)


def test_accept_with_consent_but_no_deposit_rejected(api):
    """PRD §3.3: "Second, the recorded deposit must cover the required deposit:
    deposit_paid_cents must be at least required_deposit_cents, otherwise
    ERR_DEPOSIT_UNPAID."

    Design: Corner/validations/error_deposit_unpaid_on_accept
    """
    procA = create_procedure(**PROC_A)
    # consent signed so the fiscal check surfaces; no deposit paid
    quote, _cons, _pat, _lis = create_presented_quote([procA["id"]], sign_consent=True)
    resp = api.accept_quote(quote["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_UNPAID, 402)


def test_add_retired_procedure_rejected(api):
    """PRD §3.3: "the referenced procedure must be ACTIVE, and adding a retired
    procedure is rejected with ERR_PROCEDURE_RETIRED."

    Design: Corner/validations/error_procedure_retired_on_add_line
    """
    proc = create_procedure(code="OLD01", name="Old Proc", surgical_fee_cents=400000,
                            facility_fee_cents=100000, anesthesia_fee_cents=90000)
    from test_helpers import api_client
    api_client.retire_procedure(proc["id"], TEST_USERS["practice_admin_headers"])
    quote, _cons, _pat, _lis = create_draft_quote([])
    resp = api.add_line_item(quote["id"], {"procedure_id": proc["id"]}, FRONT)
    validate_error(resp, ApiErrorId.ERR_PROCEDURE_RETIRED, 409)
