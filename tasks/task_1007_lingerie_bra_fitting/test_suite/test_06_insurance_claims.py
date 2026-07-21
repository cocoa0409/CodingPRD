"""Insurance claim submission, estimate-vs-final coverage, cyclic resubmit,
paid/mastectomy preconditions, and reimbursement guard.

Covers queue-A dual_variant_calc (insurance), non_linear_state_machine (cyclic
resubmit), cross_entity_state_dependency (paid order), plus queue-B insurance
instances.
"""
from test_helpers import (
    validate_success, validate_error,
    create_insurance_claim_payload, adjudicate_payload,
    ApiErrorId, TEST_USERS,
    setup_paid_mastectomy_order, setup_placed_order, setup_order_with_line, setup_paid_order,
)

BC = TEST_USERS["billing_clerk_headers"]


# ─── Estimate vs final coverage (queue A) ─────────────────────────────────
def test_claim_submit_estimate_coverage(api):
    """PRD §3.6: "Its claim_amount_cents is snapshotted as the sum of line_net_cents
    over the order's mastectomy lines. The covered amount is then estimated: it is the
    claim's base amount multiplied by the coverage rate of 80 percent, rounded half-up
    to whole cents, and then capped so that it never exceeds the coverage cap of 50000
    cents. At submission the base amount is claim_amount_cents, and the result
    populates covered_amount_cents."

    Design: Difficulty/dual_variant_calc/insurance_estimate_vs_final_coverage
    """
    ctx = setup_paid_mastectomy_order(base_price_cents=20000, quantity=1)
    claim = validate_success(
        api.create_insurance_claim(create_insurance_claim_payload(ctx["order"]["id"]), BC), 201
    )
    assert claim["claim_amount_cents"] == 20000, claim
    assert claim["covered_amount_cents"] == 16000, claim
    assert claim["status"] == "SUBMITTED", claim


def test_claim_approve_final_coverage_over_adjudicated(api):
    """PRD §3.6: "the claim moves to APPROVED, and covered_amount_cents is recomputed
    with the same coverage rate and cap but now over adjudicated_amount_cents — the
    insurer-approved eligible amount, which may be lower than the original claim and
    therefore may yield a different covered amount."

    Design: Difficulty/dual_variant_calc/insurance_estimate_vs_final_coverage
    """
    ctx = setup_paid_mastectomy_order(base_price_cents=20000, quantity=1)
    claim = validate_success(
        api.create_insurance_claim(create_insurance_claim_payload(ctx["order"]["id"]), BC), 201
    )
    adjudicated = validate_success(
        api.adjudicate_claim(claim["id"], adjudicate_payload("APPROVE", 12000), BC), 200
    )
    assert adjudicated["covered_amount_cents"] == 9600, adjudicated
    assert adjudicated["status"] == "APPROVED", adjudicated


# ─── Cyclic denial / resubmit (queue A) ───────────────────────────────────
def test_claim_deny_moves_to_denied(api):
    """PRD §3.6: "On DENY, the claim moves to DENIED and covered_amount_cents is set
    to 0."

    Design: Difficulty/non_linear_state_machine/insurance_claim_cyclic_resubmit
    """
    ctx = setup_paid_mastectomy_order(base_price_cents=15000, quantity=1)
    claim = validate_success(
        api.create_insurance_claim(create_insurance_claim_payload(ctx["order"]["id"]), BC), 201
    )
    denied = validate_success(api.adjudicate_claim(claim["id"], adjudicate_payload("DENY"), BC), 200)
    assert denied["status"] == "DENIED", denied
    assert denied["covered_amount_cents"] == 0, denied


def test_denied_claim_resubmit_returns_to_submitted(api):
    """PRD §3.6: "A denied claim may be resubmitted, which returns it to SUBMITTED,
    resets decision to PENDING, and recomputes covered_amount_cents using the estimate
    over claim_amount_cents again — a deliberate cyclic loop between denial and
    resubmission."

    Design: Difficulty/non_linear_state_machine/insurance_claim_cyclic_resubmit
    """
    ctx = setup_paid_mastectomy_order(base_price_cents=15000, quantity=1)
    claim = validate_success(
        api.create_insurance_claim(create_insurance_claim_payload(ctx["order"]["id"]), BC), 201
    )
    validate_success(api.adjudicate_claim(claim["id"], adjudicate_payload("DENY"), BC), 200)
    resubmitted = validate_success(api.resubmit_claim(claim["id"], BC), 200)
    assert resubmitted["status"] == "SUBMITTED", resubmitted
    assert resubmitted["decision"] == "PENDING", resubmitted
    # Estimate recomputed over claim_amount_cents 15000 -> min(12000, 50000) = 12000.
    assert resubmitted["covered_amount_cents"] == 12000, resubmitted


# ─── Submission preconditions (queue A + B) ───────────────────────────────
def test_claim_on_placed_unpaid_order_rejected(api):
    """PRD §3.6: "The order must be PAID (otherwise ERR_ORDER_NOT_PAID) and must
    contain at least one mastectomy line".

    Design: Difficulty/cross_entity_state_dependency/insurance_submit_requires_paid_order
    """
    ctx = setup_placed_order(
        category="MASTECTOMY_BRA", base_price_cents=18000,
        hygiene_class="INTIMATE_NON_RETURNABLE", band_size=36, cup_size="D", initial_stock=5,
    )
    res = api.create_insurance_claim(create_insurance_claim_payload(ctx["order"]["id"]), BC)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_PAID)


def test_claim_on_draft_order_rejected(api):
    """PRD §3.6: "The order must be PAID (otherwise ERR_ORDER_NOT_PAID) and must
    contain at least one mastectomy line".

    Design: Difficulty/cross_entity_state_dependency/insurance_submit_requires_paid_order
    """
    ctx = setup_order_with_line(
        category="MASTECTOMY_BRA", base_price_cents=18000,
        hygiene_class="INTIMATE_NON_RETURNABLE", band_size=36, cup_size="D", initial_stock=5,
    )
    res = api.create_insurance_claim(create_insurance_claim_payload(ctx["order"]["id"]), BC)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_PAID)


def test_claim_on_non_mastectomy_order_rejected(api):
    """PRD §3.6: "must contain at least one mastectomy line — a line whose product has
    is_mastectomy true — otherwise the submission is rejected with
    ERR_NOT_MASTECTOMY_ORDER."

    Design: Corner/state_machines/insurance_submit_non_mastectomy_returns_not_mastectomy
    """
    ctx = setup_paid_order(category="EVERYDAY_BRA", base_price_cents=3000, initial_stock=5, quantity=1)
    res = api.create_insurance_claim(create_insurance_claim_payload(ctx["order"]["id"]), BC)
    validate_error(res, ApiErrorId.ERR_NOT_MASTECTOMY_ORDER)


def test_reimburse_zero_coverage_rejected(api):
    """PRD §3.6: "Reimbursement requires covered_amount_cents to be greater than 0, or
    it is rejected with ERR_NOTHING_TO_REIMBURSE."

    Design: Corner/state_machines/reimburse_zero_coverage_returns_nothing_to_reimburse
    """
    ctx = setup_paid_mastectomy_order(base_price_cents=15000, quantity=1)
    claim = validate_success(
        api.create_insurance_claim(create_insurance_claim_payload(ctx["order"]["id"]), BC), 201
    )
    approved = validate_success(
        api.adjudicate_claim(claim["id"], adjudicate_payload("APPROVE", 0), BC), 200
    )
    assert approved["covered_amount_cents"] == 0, approved
    res = api.reimburse_claim(claim["id"], BC)
    validate_error(res, ApiErrorId.ERR_NOTHING_TO_REIMBURSE)
