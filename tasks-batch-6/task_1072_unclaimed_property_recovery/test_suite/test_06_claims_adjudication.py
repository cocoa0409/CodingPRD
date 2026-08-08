"""Claim adjudication: provisional-vs-final recovery fee, the payout waterfall's
pinned evaluation order, the evidence review loop, terminal denial, evidence
rejection, and the pending-evidence approval gate.

Translates queue A (dual_variant_calc/recovery_fee, combinatorial_formula/
claim_payout_waterfall, non_linear_state_machine/claim_evidence_review_cycle) and
queue B (deny terminal, evidence reject, evidence required).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, factories as f, fixtures,
    assert_waterfall_identity,
)
from test_helpers.test_users import (
    make_holder_headers, make_owner_headers, make_examiner_headers, make_approver_headers,
)


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/recovery_fee_provisional_vs_final
# ---------------------------------------------------------------------------
def test_provisional_fee_on_face_at_filing(api):
    """PRD §3.6: "The provisional fee uses the property's pre-interest face value: it is the
    effective fee fraction — the smaller of the claim's contract_fee_pct and the 10-percent
    statutory ceiling — multiplied by the property's face amount_cents, rounded half-up to
    whole cents."

    Interest-bearing face 100000, contract_fee_pct 0.10 -> provisional_fee_cents 10000 at filing.

    Design: Difficulty/dual_variant_calc/recovery_fee_provisional_vs_final
    """
    ctx = fixtures.setup_filed_firm_claim(api, amount_cents=100000, interest_bearing=True,
                                          contract_fee_pct=0.10)
    assert ctx["claim"]["provisional_fee_cents"] == 10000, \
        f"provisional 0.10*100000 must be 10000, got {ctx['claim']['provisional_fee_cents']}"


def test_final_fee_on_escheated_gross_at_approval(api):
    """PRD §3.7: "The final recovery fee, unlike the provisional estimate, is computed on the
    escheated gross rather than the pre-interest face value. Step one sets fee_cents to the
    effective fee fraction — the smaller of the claim's contract_fee_pct and the 10-percent
    statutory ceiling (STATE_MAX_FEE_PCT, 0.10) — multiplied by the claim's claim_amount_cents,
    rounded half-up."

    claim_amount_cents 106000 (principal 100000 + interest 6000): final fee 0.10*106000 = 10600,
    exceeding the 10000 provisional.

    Design: Difficulty/dual_variant_calc/recovery_fee_provisional_vs_final
    """
    ctx = fixtures.setup_examined_firm_claim(api, amount_cents=100000, interest_bearing=True,
                                             contract_fee_pct=0.10)
    approved = validate_success(api.approve_claim(ctx["claim"]["id"], make_approver_headers("appr-1")), 200)
    assert approved["fee_cents"] == 10600, f"final fee 0.10*106000 must be 10600, got {approved['fee_cents']}"
    assert approved["fee_cents"] != approved["provisional_fee_cents"], \
        "final fee must differ from the provisional estimate for an interest-bearing property"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/claim_payout_waterfall_eval_order
# ---------------------------------------------------------------------------
def test_waterfall_fee_and_gross(api):
    """PRD §3.7: "Step one sets fee_cents to the effective fee fraction ... multiplied by the
    claim's claim_amount_cents, rounded half-up."

    claim_amount_cents 1000000 (no interest), contract 0.10 -> fee_cents 100000.

    Design: Difficulty/combinatorial_formula/claim_payout_waterfall_eval_order
    """
    ctx = fixtures.setup_examined_firm_claim(api, amount_cents=1000000, interest_bearing=False,
                                             contract_fee_pct=0.10)
    approved = validate_success(api.approve_claim(ctx["claim"]["id"], make_approver_headers("appr-1")), 200)
    assert approved["claim_amount_cents"] == 1000000
    assert approved["fee_cents"] == 100000, f"fee 0.10*1000000 must be 100000, got {approved['fee_cents']}"


def test_waterfall_admin_pct_branch_and_net(api):
    """PRD §3.7: "Step two forms the post-fee residual by subtracting fee_cents from
    claim_amount_cents. Step three sets the state administrative deduction, admin_deduction_cents,
    from a tier keyed on that post-fee residual: if the residual is at or below the administrative
    tier threshold of 100000 cents (ADMIN_TIER_THRESHOLD_CENTS), the deduction is a flat 500 cents
    (ADMIN_FLAT_FEE_CENTS); otherwise the deduction is 0.5 percent of the post-fee residual
    (ADMIN_PCT, 0.005), rounded half-up. Step four sets net_payout_cents to claim_amount_cents
    minus fee_cents minus admin_deduction_cents."

    post_fee 900000 > 100000 selects the ADMIN_PCT branch: admin round(0.005*900000) = 4500;
    net 1000000 - 100000 - 4500 = 895500.

    Design: Difficulty/combinatorial_formula/claim_payout_waterfall_eval_order
    """
    ctx = fixtures.setup_examined_firm_claim(api, amount_cents=1000000, interest_bearing=False,
                                             contract_fee_pct=0.10)
    approved = validate_success(api.approve_claim(ctx["claim"]["id"], make_approver_headers("appr-1")), 200)
    assert approved["admin_deduction_cents"] == 4500, \
        f"admin 0.005*900000 must be 4500, got {approved['admin_deduction_cents']}"
    assert approved["net_payout_cents"] == 895500, \
        f"net must be 895500, got {approved['net_payout_cents']}"
    assert_waterfall_identity(approved)


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/claim_evidence_review_cycle
# ---------------------------------------------------------------------------
def _owner_claim_needs_evidence_with_accepted_doc(api):
    ctx = fixtures.escheat_property(api, amount_cents=50000, interest_bearing=False,
                                    dormancy_basis="ISSUANCE", pt_code="MO02",
                                    clock="2026-07-15T00:00:00Z")
    owner = fixtures.create_owner(api)
    oh = make_owner_headers(owner["id"])
    claim = validate_success(api.create_claim(
        f.create_claim_payload(ctx["property"]["id"], owner["id"], "OWNER"), oh), 201)
    ex = make_examiner_headers()
    validate_success(api.examine_claim(claim["id"], ex), 200)
    validate_success(api.request_evidence(claim["id"], ex), 200)
    doc = validate_success(api.upload_evidence(claim["id"], f.evidence_payload("GOV_ID"), oh), 201)
    validate_success(api.review_evidence(claim["id"], doc["id"], f.review_payload("ACCEPTED"), ex), 200)
    return ctx, claim, doc, oh, ex


def test_resubmit_after_accepted_evidence_returns_under_review(api):
    """PRD §3.6: "The claimant closes the loop by resubmitting a claim that is in NEEDS_EVIDENCE,
    which returns it from NEEDS_EVIDENCE to UNDER_REVIEW. Resubmission is permitted only when at
    least one EvidenceDocument for that claim has reached status ACCEPTED."

    Design: Difficulty/non_linear_state_machine/claim_evidence_review_cycle
    """
    ctx, claim, doc, oh, ex = _owner_claim_needs_evidence_with_accepted_doc(api)
    data = validate_success(api.resubmit_claim(claim["id"], oh), 200)
    assert data["status"] == "UNDER_REVIEW", \
        f"resubmit must revisit UNDER_REVIEW, got {data['status']}"


def test_evidence_accepted_before_resubmit(api):
    """PRD §3.6: "A StateExaminer reviews a document by supplying a decision of either ACCEPTED
    or REJECTED, which sets the document's status accordingly and records the reviewing
    operator's X-User-ID as its reviewed_by_user_id."
    PRD §3.6: "Resubmission is permitted only when at least one EvidenceDocument for that claim
    has reached status ACCEPTED."

    The accepted document that unlocks the loop is in status ACCEPTED.

    Design: Difficulty/non_linear_state_machine/claim_evidence_review_cycle
    """
    ctx, claim, doc, oh, ex = _owner_claim_needs_evidence_with_accepted_doc(api)
    validate_success(api.resubmit_claim(claim["id"], oh), 200)
    docs = validate_success(api.list_evidence(claim["id"], ex), 200)
    assert docs[0]["status"] == "ACCEPTED", f"the reviewed document must be ACCEPTED, got {docs[0]['status']}"


# ---------------------------------------------------------------------------
# Corner/state_machines/deny_then_examine_terminal_lockdown
# ---------------------------------------------------------------------------
def test_examine_after_deny_rejected(api):
    """PRD §3.7: "Denial is an examiner action from UNDER_REVIEW that moves the claim to DENIED,
    a terminal state."
    PRD §2.12: "if the target resource is not in a state from which the requested transition is
    defined, the request is rejected with ERR_INVALID_STATE (HTTP 409)."

    A DENIED claim is terminal, so a subsequent examine is rejected.

    Design: Corner/state_machines/deny_then_examine_terminal_lockdown
    """
    ctx = fixtures.escheat_property(api, amount_cents=50000, interest_bearing=False,
                                    dormancy_basis="ISSUANCE", pt_code="MO02",
                                    clock="2026-07-15T00:00:00Z")
    owner = fixtures.create_owner(api)
    oh = make_owner_headers(owner["id"])
    claim = validate_success(api.create_claim(
        f.create_claim_payload(ctx["property"]["id"], owner["id"], "OWNER"), oh), 201)
    ex = make_examiner_headers()
    validate_success(api.examine_claim(claim["id"], ex), 200)
    validate_success(api.deny_claim(claim["id"], ex), 200)
    validate_error(api.examine_claim(claim["id"], ex), ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_claim(claim["id"], ex), 200)
    assert after["status"] == "DENIED"


# ---------------------------------------------------------------------------
# Corner/state_machines/evidence_review_reject_sets_status
# ---------------------------------------------------------------------------
def test_evidence_review_reject_sets_status(api):
    """PRD §3.6: "A StateExaminer reviews a document by supplying a decision of either ACCEPTED
    or REJECTED, which sets the document's status accordingly and records the reviewing
    operator's X-User-ID as its reviewed_by_user_id."

    Reviewing with decision REJECTED sets the document status to REJECTED.

    Design: Corner/state_machines/evidence_review_reject_sets_status
    """
    ctx = fixtures.escheat_property(api, amount_cents=50000, interest_bearing=False,
                                    dormancy_basis="ISSUANCE", pt_code="MO02",
                                    clock="2026-07-15T00:00:00Z")
    owner = fixtures.create_owner(api)
    oh = make_owner_headers(owner["id"])
    claim = validate_success(api.create_claim(
        f.create_claim_payload(ctx["property"]["id"], owner["id"], "OWNER"), oh), 201)
    ex = make_examiner_headers()
    validate_success(api.examine_claim(claim["id"], ex), 200)
    validate_success(api.request_evidence(claim["id"], ex), 200)
    doc = validate_success(api.upload_evidence(claim["id"], f.evidence_payload("GOV_ID"), oh), 201)
    data = validate_success(api.review_evidence(claim["id"], doc["id"], f.review_payload("REJECTED"), ex), 200)
    assert data["status"] == "REJECTED", f"decision REJECTED must set status REJECTED, got {data['status']}"


# ---------------------------------------------------------------------------
# Corner/validations/approve_with_pending_evidence_returns_error
# ---------------------------------------------------------------------------
def test_approve_with_pending_evidence_rejected(api):
    """PRD §3.7: "And no EvidenceDocument for the claim may still be in PENDING — every uploaded
    document must have been reviewed to either ACCEPTED or REJECTED — otherwise approval is
    rejected with ERR_EVIDENCE_REQUIRED (HTTP 422)."

    A claim worked back to UNDER_REVIEW that still carries a PENDING document cannot be approved.

    Design: Corner/validations/approve_with_pending_evidence_returns_error
    """
    ctx, claim, doc, oh, ex = _owner_claim_needs_evidence_with_accepted_doc(api)
    # Back to UNDER_REVIEW (has one ACCEPTED doc), then upload a fresh PENDING document.
    validate_success(api.resubmit_claim(claim["id"], oh), 200)
    pending = validate_success(api.upload_evidence(claim["id"], f.evidence_payload("PROOF_OF_ADDRESS"), oh), 201)
    validate_error(api.approve_claim(claim["id"], make_approver_headers("appr-1")),
                   ApiErrorId.ERR_EVIDENCE_REQUIRED.value)
    after = validate_success(api.get_claim(claim["id"], ex), 200)
    assert after["status"] == "UNDER_REVIEW"
    docs = validate_success(api.list_evidence(claim["id"], ex), 200)
    assert any(d["id"] == pending["id"] and d["status"] == "PENDING" for d in docs), \
        "the freshly uploaded document must remain PENDING"
