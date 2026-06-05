"""Invoice OCR pipeline branching, eligibility computation, and line exclusion.

Difficulty queue: non_linear_state_machine (invoice branching).
Corner queue: state_machines (OCR low/high mismatch, reject invalid state, claim
initial state, begin-review invalid state, pay invalid state), calculations
(line exclusion reduces eligible).
"""
from test_helpers import (
    validate_success, validate_error,
    set_clock, create_account, create_policy, activate_policy, create_condition,
    open_claim, add_line, upload_invoice, run_ocr, accept_invoice, submit_claim,
    begin_review, build_claim_in_review,
    make_claims_adjuster_headers, make_underwriter_headers, make_policy_holder_headers,
    ApiErrorId,
)


def _adj():
    return make_claims_adjuster_headers()


def _active_policy(email, **policy_overrides):
    acct = create_account(email=email)
    pol = create_policy(acct["id"], **policy_overrides)
    activate_policy(acct["id"], pol["id"])
    return acct, pol


def _draft_claim_with_line(acct, pol, billed=40000, claim_type="ILLNESS", condition_id=None):
    overrides = {"claim_type": claim_type}
    if condition_id is not None:
        overrides["condition_id"] = condition_id
    claim = open_claim(acct["id"], pol["id"], **overrides)
    add_line(acct["id"], claim["id"], billed_amount_cents=billed)
    invoice = upload_invoice(acct["id"], claim["id"])
    return claim, invoice


def test_ocr_low_mismatch_branches_to_ocr_done(api):
    """PRD 3.5: "when the mismatch is at or below 500 basis points, it lands in OCR_DONE
    and is auto-acceptable."

    OCR is run on a DRAFT claim (the only point at which it can run, since submission
    requires an ACCEPTED invoice). Per PRD 3.6 submitted_amount_cents is only frozen at
    submission, so at OCR time the mismatch is at or below tolerance and the invoice
    lands in OCR_DONE.

    Design: Corner/state_machines/ocr_low_mismatch_branches_to_ocr_done
    """
    acct, pol = _active_policy("inv2@x.com")
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
    claim, invoice = _draft_claim_with_line(acct, pol, billed=40000, condition_id=cond["id"])

    after_ocr = validate_success(api.run_ocr(claim["id"], invoice["id"], {"ocr_total_cents": 41000}, _adj()))
    assert after_ocr["ocr_status"] == "OCR_DONE", f"status: {after_ocr['ocr_status']}"


def test_reject_from_ocr_done_is_invalid_state(api):
    """PRD 3.5: "An invoice may be rejected only from REVIEW_NEEDED, moving it to
    REJECTED. Either action from a disallowed source status is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/reject_from_ocr_done_invalid_state
    """
    acct, pol = _active_policy("inv3@x.com")
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
    claim, invoice = _draft_claim_with_line(acct, pol, billed=40000, condition_id=cond["id"])
    run_ocr(claim["id"], invoice["id"], 40000)  # zero mismatch -> OCR_DONE

    resp = api.reject_invoice(claim["id"], invoice["id"], _adj())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_claim_starts_in_draft_with_zero_payable(api):
    """PRD 3.4: "A new claim begins in DRAFT status ... A claim also surfaces, once
    computed, its submitted_amount_cents, eligible_amount_cents, deductible_applied_cents,
    reimbursed_cents, and wellness_paid_cents."

    Design: Corner/state_machines/claim_initial_state_is_draft
    """
    acct, pol = _active_policy("cl1@x.com")
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")

    claim = validate_success(api.create_claim(
        acct["id"], pol["id"],
        {"claim_type": "ILLNESS", "incident_date": "2026-03-01T00:00:00Z", "condition_id": cond["id"]},
        make_policy_holder_headers(acct["id"])), 201)
    assert claim["status"] == "DRAFT"
    assert claim["reimbursed_cents"] == 0


def test_begin_review_from_draft_is_invalid_state(api):
    """PRD 3.6: "A ClaimsAdjuster begins review of a SUBMITTED claim, moving it to
    IN_REVIEW; this is allowed only from SUBMITTED and otherwise rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/begin_review_from_draft_invalid_state
    """
    acct, pol = _active_policy("cl2@x.com")
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = open_claim(acct["id"], pol["id"], claim_type="ILLNESS", condition_id=cond["id"])

    resp = api.begin_review(claim["id"], _adj())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_pay_from_in_review_is_invalid_state(api):
    """PRD 3.7: "Once a claim is APPROVED, a ClaimsAdjuster marks it PAID, permitted only
    from APPROVED and otherwise ERR_INVALID_STATE."

    Design: Corner/state_machines/pay_from_in_review_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    acct, pol = _active_policy("cl3@x.com", waiting_period_days=14)
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = build_claim_in_review(acct["id"], pol["id"], condition_id=cond["id"], billed_amount_cents=40000)

    resp = api.pay_claim(claim["id"], _adj())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_line_exclusion_reduces_eligible_amount(api):
    """PRD 3.6: "a line marked excluded contributes an allowed_amount_cents of 0, while a
    line that is not excluded takes an allowed_amount_cents equal to its current
    billed_amount_cents ... The claim's eligible_amount_cents is the sum of the
    allowed_amount_cents of the lines that are not excluded."
    PRD 3.6: "Each such adjustment recomputes the claim's eligible_amount_cents by the
    same per-line rule and increments the claim version by one."

    Two 5000 lines -> eligible 10000; excluding the second drops it to 5000.

    Design: Corner/calculations/line_exclusion_reduces_eligible_amount
    """
    set_clock("2026-06-01T00:00:00Z")
    acct, pol = _active_policy("elig@x.com", annual_deductible_cents=0, waiting_period_days=14)
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")

    claim = open_claim(acct["id"], pol["id"], claim_type="ILLNESS", condition_id=cond["id"])
    add_line(acct["id"], claim["id"], description="covered", billed_amount_cents=5000)
    line2 = add_line(acct["id"], claim["id"], description="non-covered", billed_amount_cents=5000)
    invoice = upload_invoice(acct["id"], claim["id"])
    run_ocr(claim["id"], invoice["id"], 10000)
    accept_invoice(claim["id"], invoice["id"])
    submit_claim(acct["id"], claim["id"])
    begin_review(claim["id"])

    validate_success(api.patch_line(claim["id"], line2["id"], {"excluded": True}, _adj()))
    data = validate_success(api.get_claim(claim["id"], _adj()))
    assert data["eligible_amount_cents"] == 5000, f"expected 5000, got {data['eligible_amount_cents']}"
