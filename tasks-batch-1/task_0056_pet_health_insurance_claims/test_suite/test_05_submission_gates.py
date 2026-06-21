"""Claim submission preconditions: active policy, accepted invoice, non-empty lines.

Difficulty queue: cross_entity_state_dependency (claim->policy, claim->invoice),
boundary_precision_check (empty-lines submit).
"""
from test_helpers import (
    validate_success, validate_error,
    create_account, create_policy, activate_policy, create_condition,
    open_claim, add_line, upload_invoice, run_ocr, accept_invoice,
    make_policy_holder_headers, make_underwriter_headers,
    ApiErrorId,
)


def _uw():
    return make_underwriter_headers()


def _draft_with_line_and_accepted_invoice(acct_id, pol_id, billed=40000):
    cond = create_condition(acct_id, pol_id, first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = open_claim(acct_id, pol_id, claim_type="ILLNESS", condition_id=cond["id"])
    add_line(acct_id, claim["id"], billed_amount_cents=billed)
    invoice = upload_invoice(acct_id, claim["id"])
    run_ocr(claim["id"], invoice["id"], billed)
    accept_invoice(claim["id"], invoice["id"])
    return claim, invoice


def test_submit_succeeds_once_policy_active(api):
    """PRD 3.6: "Submission has four preconditions, all of which must hold: the claim must
    be in DRAFT; its owning policy must be in ACTIVE status ... On a successful submission
    the platform freezes submitted_amount_cents to the sum of the claim's ClaimLine
    billed_amount_cents values."

    With an ACTIVE policy and a ready claim, submit advances to SUBMITTED and freezes the
    submitted amount.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_policy_active
    """
    acct = create_account(email="ce1b@x.com")
    pol = create_policy(acct["id"])
    activate_policy(acct["id"], pol["id"])
    claim, _ = _draft_with_line_and_accepted_invoice(acct["id"], pol["id"], billed=40000)

    submitted = validate_success(api.submit_claim(claim["id"], make_policy_holder_headers(acct["id"])))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_amount_cents"] == 40000, f"frozen amount: {submitted['submitted_amount_cents']}"


def test_submit_succeeds_once_invoice_accepted(api):
    """PRD 3.6: "the claim must have at least one InvoiceDocument whose ocr_status is
    ACCEPTED ... On a successful submission the platform freezes submitted_amount_cents."

    The same claim that was blocked at OCR_DONE submits successfully once its invoice is
    ACCEPTED.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_invoice_accepted
    """
    acct = create_account(email="ce2b@x.com")
    pol = create_policy(acct["id"])
    activate_policy(acct["id"], pol["id"])
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = open_claim(acct["id"], pol["id"], claim_type="ILLNESS", condition_id=cond["id"])
    add_line(acct["id"], claim["id"], billed_amount_cents=40000)
    invoice = upload_invoice(acct["id"], claim["id"])
    run_ocr(claim["id"], invoice["id"], 40000)  # OCR_DONE only
    blocked = api.submit_claim(claim["id"], make_policy_holder_headers(acct["id"]))
    validate_error(blocked, ApiErrorId.ERR_CLAIM_NOT_READY.value)

    accept_invoice(claim["id"], invoice["id"])
    submitted = validate_success(api.submit_claim(claim["id"], make_policy_holder_headers(acct["id"])))
    assert submitted["status"] == "SUBMITTED"


def test_submit_blocked_while_invoice_not_accepted(api):
    """PRD 3.6: "the claim must have at least one InvoiceDocument whose ocr_status is
    ACCEPTED ... if the readiness conditions on lines and an accepted invoice are not
    met, the submission is rejected with ERR_CLAIM_NOT_READY."

    An ACTIVE-policy claim with a line and an invoice only at OCR_DONE (not accepted)
    -> ERR_CLAIM_NOT_READY.

    Design: Difficulty/cross_entity_state_dependency/claim_submit_requires_invoice_accepted
    """
    acct = create_account(email="ce2@x.com")
    pol = create_policy(acct["id"])
    activate_policy(acct["id"], pol["id"])
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = open_claim(acct["id"], pol["id"], claim_type="ILLNESS", condition_id=cond["id"])
    add_line(acct["id"], claim["id"], billed_amount_cents=40000)
    invoice = upload_invoice(acct["id"], claim["id"])
    run_ocr(claim["id"], invoice["id"], 40000)  # OCR_DONE, not accepted

    resp = api.submit_claim(claim["id"], make_policy_holder_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_READY.value)

    unchanged = validate_success(api.get_claim(claim["id"], make_policy_holder_headers(acct["id"])))
    assert unchanged["status"] == "DRAFT", f"claim should stay DRAFT, got {unchanged['status']}"


def test_submit_empty_claim_no_lines_rejected_not_ready(api):
    """PRD 3.6: "the claim must have at least one ClaimLine; and the claim must have at
    least one InvoiceDocument whose ocr_status is ACCEPTED ... if the readiness
    conditions on lines and an accepted invoice are not met, the submission is rejected
    with ERR_CLAIM_NOT_READY."

    A DRAFT claim with zero lines and no invoice -> ERR_CLAIM_NOT_READY.

    Design: Difficulty/boundary_precision_check/empty_claim_lines_blocks_submit_on_submit_endpoint
    """
    acct = create_account(email="ce3@x.com")
    pol = create_policy(acct["id"])
    activate_policy(acct["id"], pol["id"])
    cond = create_condition(acct["id"], pol["id"], first_diagnosed_date="2026-02-01T00:00:00Z")
    claim = open_claim(acct["id"], pol["id"], claim_type="ILLNESS", condition_id=cond["id"])

    resp = api.submit_claim(claim["id"], make_policy_holder_headers(acct["id"]))
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_READY.value)

    unchanged = validate_success(api.get_claim(claim["id"], make_policy_holder_headers(acct["id"])))
    assert unchanged["status"] == "DRAFT", f"claim should stay DRAFT, got {unchanged['status']}"


def test_submit_with_one_line_and_accepted_invoice_succeeds(api):
    """PRD 3.6: "the claim must have at least one ClaimLine; and the claim must have at
    least one InvoiceDocument whose ocr_status is ACCEPTED ... On a successful submission
    the platform freezes submitted_amount_cents to the sum of the claim's ClaimLine
    billed_amount_cents values and increments the claim version by one."

    The just-above-empty boundary — exactly one line plus one accepted invoice — submits
    successfully, contrasting the zero-line rejection.

    Design: Difficulty/boundary_precision_check/empty_claim_lines_blocks_submit_on_submit_endpoint
    """
    acct = create_account(email="ce3b@x.com")
    pol = create_policy(acct["id"])
    activate_policy(acct["id"], pol["id"])
    claim, _ = _draft_with_line_and_accepted_invoice(acct["id"], pol["id"], billed=40000)

    submitted = validate_success(api.submit_claim(claim["id"], make_policy_holder_headers(acct["id"])))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_amount_cents"] == 40000
