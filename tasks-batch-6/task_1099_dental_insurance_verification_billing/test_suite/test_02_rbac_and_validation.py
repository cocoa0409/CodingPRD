"""RBAC gates and single-rule validation errors (corner instances)."""
from test_helpers import (
    validate_error, ApiErrorId,
    make_frontoffice_headers, make_biller_headers, make_manager_headers,
    make_patient_headers,
)
from test_helpers import fixtures as fx


def test_create_patient_missing_email_invalid_request(api):
    """PRD §2.6: "Well-formedness of the body itself — required fields present,
    enum values legal, and integer amounts not negative — is checked with
    `ERR_INVALID_REQUEST` on any write endpoint."

    Design: Corner/validations/create_patient_missing_email_invalid_request
    """
    resp = api.create_patient(
        {"full_name": "No Email", "date_of_birth": "1990-02-02"},
        make_frontoffice_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying an unrecognized
    role, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/missing_user_context_header_rejected
    """
    resp = api.create_patient(
        {"full_name": "Anon", "date_of_birth": "1990-02-02", "email": "anon@x.com"},
        {})  # both auth headers omitted
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_attachment_without_target_rejected(api):
    """PRD §3.4: "If neither target is supplied, or both are, the upload is
    rejected with `ERR_ATTACHMENT_TARGET_REQUIRED`."

    Design: Corner/validations/attachment_without_target_rejected
    """
    resp = api.create_attachment(
        {"kind": "XRAY", "filename": "orphan.png"}, make_biller_headers())
    validate_error(resp, ApiErrorId.ERR_ATTACHMENT_TARGET_REQUIRED.value)


def test_missing_narrative_rejected_on_submit(api):
    """PRD §3.5: "If any line's procedure requires a narrative, a non-empty
    `narrative` must be present, or the submission is rejected with
    `ERR_MISSING_NARRATIVE`."

    Design: Corner/validations/missing_narrative_rejected_on_submit
    """
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000, basic_coinsurance_pct=80,
                       deductible_cents=0)
    fx.new_procedure(api, cdt_code="D4341", description="SRP", category="BASIC",
                     ucr_fee_cents=20000, requires_narrative=True)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    fx.new_verification(api, cov, verified_deductible_cents=0)
    claim = fx.new_claim(api, patient["id"], cov["id"],
                         [{"cdt_code": "D4341", "billed_fee_cents": 20000}])
    resp = api.submit_claim(claim["id"], make_biller_headers("biller_alice"))
    validate_error(resp, ApiErrorId.ERR_MISSING_NARRATIVE.value)


def test_missing_attachment_rejected_on_submit(api):
    """PRD §3.5: "If any line's procedure requires an attachment, at least one
    attachment naming this claim must be present, or it is rejected with
    `ERR_MISSING_ATTACHMENT`."

    Design: Corner/validations/missing_attachment_rejected_on_submit
    """
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000, major_coinsurance_pct=50,
                       deductible_cents=5000)
    fx.new_procedure(api, requires_attachment=True)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    fx.new_verification(api, cov)
    claim = fx.new_claim(api, patient["id"], cov["id"],
                         [{"cdt_code": "D2740", "billed_fee_cents": 130000}])
    resp = api.submit_claim(claim["id"], make_biller_headers("biller_alice"))
    validate_error(resp, ApiErrorId.ERR_MISSING_ATTACHMENT.value)


def test_segregation_of_duties_same_user_posts_insurance(api):
    """PRD §3.7: "the posting user's `X-User-ID` must differ from the claim's
    `submitted_by_user_id`, or the posting is rejected with
    `ERR_SEGREGATION_OF_DUTIES` — the person who submitted a claim may never post
    its insurance payment."

    Design: Corner/validations/segregation_of_duties_same_user_posts_insurance
    """
    sc, submitted = fx.submitted_crown_claim(api, submit_user="biller_alice")
    resp = api.create_payment(
        {"patient_id": sc["patient"]["id"], "payer_type": "INSURANCE",
         "amount_cents": 57500, "claim_id": submitted["id"], "is_denial": False,
         "eob_lines": [{"cdt_code": "D2740", "allowed_cents": 120000,
                        "paid_cents": 57500, "deductible_applied_cents": 5000}]},
        make_biller_headers("biller_alice"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_insurance_payment_on_draft_claim_mismatch(api):
    """PRD §3.7: "A payment's `claim_id`, when present, must name a claim that is
    in a postable state and whose patient and coverage match the payment;
    otherwise the posting is rejected with `ERR_PAYMENT_CLAIM_MISMATCH`."

    Design: Corner/validations/insurance_payment_on_draft_claim_mismatch
    """
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000, major_coinsurance_pct=50,
                       deductible_cents=5000)
    fx.new_procedure(api)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    claim = fx.new_claim(api, patient["id"], cov["id"],
                         [{"cdt_code": "D2740", "billed_fee_cents": 130000}])
    resp = api.create_payment(
        {"patient_id": patient["id"], "payer_type": "INSURANCE",
         "amount_cents": 57500, "claim_id": claim["id"], "is_denial": False,
         "eob_lines": [{"cdt_code": "D2740", "allowed_cents": 120000,
                        "paid_cents": 57500, "deductible_applied_cents": 5000}]},
        make_manager_headers("mgr_bob"))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_CLAIM_MISMATCH.value)


def test_patient_overpayment_rejected(api):
    """PRD §3.7: "`amount_cents` added to the claim's existing `patient_paid_cents`
    may not exceed the claim's `final_patient_portion_cents`, or the payment is
    rejected with `ERR_OVERPAYMENT`."

    Design: Corner/validations/patient_overpayment_rejected
    """
    sc, claim, _pay = fx.adjudicated_crown_claim(api)
    # final_patient_portion is 72500; paying 80000 overshoots.
    resp = api.create_payment(
        {"patient_id": sc["patient"]["id"], "payer_type": "PATIENT",
         "amount_cents": 80000, "claim_id": claim["id"]},
        make_patient_headers(sc["patient"]["id"]))
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value)


def test_membership_pay_zero_balance_rejected(api):
    """PRD §3.8: "a payment against a membership with no balance (or a cancelled
    one) is rejected with `ERR_MEMBERSHIP_NOT_PAYABLE`."

    Design: Corner/validations/membership_pay_zero_balance_rejected
    """
    patient, _mp, membership = fx.enrolled_membership(api)
    resp = api.pay_membership(membership["id"], 2500,
                              make_patient_headers(patient["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_PAYABLE.value)


def test_frontoffice_cannot_create_insurance_plan(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."
    PRD §4: POST `/insurance-plans` — BillingManager.

    Design: Corner/rbac/frontoffice_cannot_create_insurance_plan
    """
    resp = api.create_insurance_plan({"payer_name": "Nope", "plan_name": "X"},
                                     make_frontoffice_headers())
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


def test_patient_cannot_read_other_patients_claim(api):
    """PRD §2.1: "A Patient may read and act only on resources they own; an
    attempt to read or pay against another patient's coverage, claim, payment, or
    membership is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/patient_cannot_read_other_patients_claim
    """
    pa = fx.new_patient(api, full_name="Owner A", email="a@x.com")
    pb = fx.new_patient(api, full_name="Other B", date_of_birth="1991-03-03",
                        email="b@x.com")
    plan = fx.new_plan(api, annual_maximum_cents=150000)
    fx.new_procedure(api)
    cov = fx.new_coverage(api, pa["id"], plan["id"])
    claim = fx.new_claim(api, pa["id"], cov["id"],
                         [{"cdt_code": "D2740", "billed_fee_cents": 130000}])
    resp = api.get_claim(claim["id"], make_patient_headers(pb["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
