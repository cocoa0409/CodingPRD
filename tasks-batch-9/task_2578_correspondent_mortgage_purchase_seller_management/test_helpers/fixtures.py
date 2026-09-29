"""Composite setup helpers.

Every helper here builds state exclusively through the documented endpoints —
there is no back door into storage. The helpers are layered:

  tier 1  single-resource creators and small state advances
  tier 2  entity-hierarchy builders (product grid, onboarded seller, lock)
  tier 3  full-lifecycle shortcuts (delivered / in review / cleared / purchased)
  tier 4  accumulation and threshold targeting (multi-loan volume, defect mix)
  tier 5  finalization and terminal states (settled, demanded, closed scorecard)

Fixtures use the lenient success reader so that a broken precondition surfaces
as a setup failure rather than as a misleading assertion inside a test body.
"""

from typing import Any, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import CLOCK_START
from .test_users import (
    ADMIN,
    ANALYST,
    QC,
    REVIEWER,
    REVIEWER_ALT,
    REVIEWER_THIRD,
    TRADER,
    make_seller_user_headers,
)

# ═══ Tier 1 — single-resource creators and small state advances ═════════════


def setup_clock(instant: str = CLOCK_START, actor: Optional[dict] = None) -> dict:
    """Move the logical clock to `instant`."""
    return get_success_data(api_client.set_clock(instant, actor or ADMIN))


def setup_product(actor: Optional[dict] = None, **overrides: Any) -> dict:
    """Create one product eligibility definition."""
    return get_success_data(
        api_client.create_product(factories.product_payload(**overrides), actor or ADMIN),
        201,
    )


def setup_pricing_adjustment(
    product_id: str, actor: Optional[dict] = None, **overrides: Any
) -> dict:
    """Add one loan-level price adjustment row to a product's grid."""
    return get_success_data(
        api_client.create_pricing_adjustment(
            product_id, factories.pricing_adjustment_payload(**overrides), actor or ADMIN
        ),
        201,
    )


def setup_seller(actor: Optional[dict] = None, **overrides: Any) -> dict:
    """Register a seller applicant; it starts out unapproved and not eligible."""
    return get_success_data(
        api_client.create_seller(factories.seller_payload(**overrides), actor or ANALYST),
        201,
    )


def setup_financial_statement(
    seller_id: str, actor: Optional[dict] = None, **overrides: Any
) -> dict:
    """File one period financial statement for the seller."""
    return get_success_data(
        api_client.create_financial_statement(
            seller_id,
            factories.financial_statement_payload(**overrides),
            actor or ANALYST,
        ),
        201,
    )


def review_financial_statement(
    statement_id: str, decision: str = "ACCEPT", actor: Optional[dict] = None
) -> dict:
    """Accept or reject a submitted financial statement."""
    return get_success_data(
        api_client.review_financial_statement(
            statement_id,
            factories.statement_review_payload(decision),
            actor or ANALYST,
        ),
        200,
    )


def setup_qc_review(
    seller_id: str, review_type: str = "PRE_APPROVAL", actor: Optional[dict] = None
) -> dict:
    """Open a quality control review on the seller."""
    return get_success_data(
        api_client.create_qc_review(
            seller_id, factories.qc_review_payload(review_type), actor or QC
        ),
        201,
    )


def complete_qc_review(
    qc_review_id: str,
    findings_count: int = 2,
    critical_findings_count: int = 0,
    actor: Optional[dict] = None,
) -> dict:
    """Complete a quality control review with the given finding counts."""
    return get_success_data(
        api_client.complete_qc_review(
            qc_review_id,
            factories.qc_completion_payload(findings_count, critical_findings_count),
            actor or QC,
        ),
        200,
    )


def decide_approval(
    seller_id: str, decision: str = "APPROVE", actor: Optional[dict] = None
) -> dict:
    """Approve or decline the seller."""
    return get_success_data(
        api_client.decide_seller_approval(
            seller_id,
            factories.approval_decision_payload(decision),
            actor or ANALYST,
        ),
        200,
    )


def apply_standing_action(
    seller_id: str, action: str, actor: Optional[dict] = None
) -> dict:
    """Apply a manual delivery standing action to an approved seller."""
    return get_success_data(
        api_client.apply_standing_action(
            seller_id, factories.standing_action_payload(action), actor or ANALYST
        ),
        200,
    )


# ─── Reads used by later tiers ──────────────────────────────────────────────


def read_seller(seller_id: str, actor: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_seller(seller_id, actor or ANALYST), 200)


def read_commitment(commitment_id: str, actor: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_commitment(commitment_id, actor or TRADER), 200
    )


def read_loan(loan_id: str, actor: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_loan(loan_id, actor or REVIEWER), 200)


def commitment_version(commitment_id: str, actor: Optional[dict] = None) -> int:
    return read_commitment(commitment_id, actor)["version"]


def loan_version(loan_id: str, actor: Optional[dict] = None) -> int:
    return read_loan(loan_id, actor)["version"]


def read_loan_defects(loan_id: str, actor: Optional[dict] = None) -> list:
    body = api_client.list_defects(loan_id, actor or REVIEWER).json()
    return body["data"]


def read_loan_conditions(loan_id: str, actor: Optional[dict] = None) -> list:
    body = api_client.list_suspense_conditions(loan_id, actor or REVIEWER).json()
    return body["data"]


def read_loan_advices(loan_id: str, actor: Optional[dict] = None) -> list:
    body = api_client.list_purchase_advices(loan_id, actor or REVIEWER).json()
    return body["data"]


def read_escrow_transfers(
    loan_id: str, actor: Optional[dict] = None, status: Optional[str] = None
) -> list:
    params = {"status": status} if status else None
    body = api_client.list_escrow_transfers(loan_id, actor or REVIEWER, params).json()
    return body["data"]


def read_pending_escrow_transfer(loan_id: str, actor: Optional[dict] = None) -> dict:
    """Return the loan's single pending escrow transfer."""
    transfers = read_escrow_transfers(loan_id, actor, status="PENDING")
    assert transfers, f"loan {loan_id} has no pending escrow transfer to work with"
    return transfers[0]


# ═══ Tier 2 — entity-hierarchy builders ═════════════════════════════════════


def setup_seller_under_review(
    review_type: str = "PRE_APPROVAL",
    statement_decision: str = "ACCEPT",
    statement_overrides: Optional[dict] = None,
    seller_overrides: Optional[dict] = None,
    seller_files_own_statement: bool = False,
    qc_actor: Optional[dict] = None,
) -> dict:
    """Register a seller, get a statement decided and open a review on it.

    Opening the seller's first quality control review is what moves the seller
    off its initial applied state, so this helper returns the seller as it
    stands once the review exists.
    """
    seller = setup_seller(**(seller_overrides or {}))
    statement_actor = (
        make_seller_user_headers(seller["id"]) if seller_files_own_statement else ANALYST
    )
    statement = setup_financial_statement(
        seller["id"], actor=statement_actor, **(statement_overrides or {})
    )
    statement = review_financial_statement(statement["id"], statement_decision)
    qc_review = setup_qc_review(seller["id"], review_type, actor=qc_actor)
    return {
        "seller": read_seller(seller["id"]),
        "seller_id": seller["id"],
        "seller_headers": make_seller_user_headers(seller["id"]),
        "statement": statement,
        "qc_review": qc_review,
    }


def setup_approved_seller(
    findings_count: int = 2,
    critical_findings_count: int = 0,
    review_type: str = "PRE_APPROVAL",
    statement_overrides: Optional[dict] = None,
    seller_overrides: Optional[dict] = None,
    seller_files_own_statement: bool = False,
    qc_actor: Optional[dict] = None,
    approval_actor: Optional[dict] = None,
) -> dict:
    """Carry a brand new seller all the way to approved and in good standing."""
    staged = setup_seller_under_review(
        review_type=review_type,
        statement_overrides=statement_overrides,
        seller_overrides=seller_overrides,
        seller_files_own_statement=seller_files_own_statement,
        qc_actor=qc_actor,
    )
    qc_review = complete_qc_review(
        staged["qc_review"]["id"],
        findings_count,
        critical_findings_count,
        actor=qc_actor,
    )
    seller = decide_approval(staged["seller_id"], "APPROVE", actor=approval_actor)
    staged["qc_review"] = qc_review
    staged["seller"] = seller
    return staged


def setup_product_with_grid(
    adjustment_overrides: Optional[dict] = None, **product_overrides: Any
) -> dict:
    """Create a product and hang one active price adjustment row on it."""
    product = setup_product(**product_overrides)
    adjustment = setup_pricing_adjustment(
        product["id"], **(adjustment_overrides or {})
    )
    return {"product": product, "product_id": product["id"], "adjustment": adjustment}


def setup_commitment(
    seller_id: str,
    product_id: str,
    actor: Optional[dict] = None,
    **overrides: Any,
) -> dict:
    """Lock one commitment for the seller against the product."""
    return get_success_data(
        api_client.create_commitment(
            factories.commitment_payload(seller_id, product_id, **overrides),
            actor or TRADER,
        ),
        201,
    )


def setup_lock_ready_seller(
    clock: str = CLOCK_START,
    product_overrides: Optional[dict] = None,
    adjustment_overrides: Optional[dict] = None,
    with_adjustment: bool = True,
    **approval_kwargs: Any,
) -> dict:
    """Clock, priced product and an approved seller — everything a lock needs."""
    setup_clock(clock)
    if with_adjustment:
        grid = setup_product_with_grid(
            adjustment_overrides=adjustment_overrides, **(product_overrides or {})
        )
    else:
        product = setup_product(**(product_overrides or {}))
        grid = {"product": product, "product_id": product["id"], "adjustment": None}
    staged = setup_approved_seller(**approval_kwargs)
    staged.update(grid)
    return staged


def setup_locked_commitment(
    clock: str = CLOCK_START,
    product_overrides: Optional[dict] = None,
    adjustment_overrides: Optional[dict] = None,
    with_adjustment: bool = True,
    commitment_overrides: Optional[dict] = None,
    commitment_actor: Optional[dict] = None,
    **approval_kwargs: Any,
) -> dict:
    """An approved seller holding one freshly locked commitment."""
    staged = setup_lock_ready_seller(
        clock=clock,
        product_overrides=product_overrides,
        adjustment_overrides=adjustment_overrides,
        with_adjustment=with_adjustment,
        **approval_kwargs,
    )
    commitment = setup_commitment(
        staged["seller_id"],
        staged["product_id"],
        actor=commitment_actor,
        **(commitment_overrides or {}),
    )
    staged["commitment"] = commitment
    staged["commitment_id"] = commitment["id"]
    return staged


# ═══ Tier 3 — full-lifecycle shortcuts ══════════════════════════════════════


def deliver_loan(
    commitment_id: str,
    seller_id: str,
    actor: Optional[dict] = None,
    seller_loan_number: str = "HP-0001",
    expected_version: Optional[int] = None,
    **overrides: Any,
) -> dict:
    """Deliver one closed loan file against the commitment."""
    version = (
        expected_version
        if expected_version is not None
        else commitment_version(commitment_id)
    )
    payload = factories.loan_payload(
        version, seller_loan_number=seller_loan_number, **overrides
    )
    return get_success_data(
        api_client.deliver_loan(
            commitment_id, payload, actor or make_seller_user_headers(seller_id)
        ),
        201,
    )


def open_loan_review(loan_id: str, actor: Optional[dict] = None) -> dict:
    """Open purchase review on a delivered loan file."""
    return get_success_data(
        api_client.open_loan_review(loan_id, actor or REVIEWER), 200
    )


def setup_delivered_loan(
    commitment_overrides: Optional[dict] = None,
    loan_overrides: Optional[dict] = None,
    delivery_actor: Optional[dict] = None,
    **staging_kwargs: Any,
) -> dict:
    """A delivered but not yet reviewed loan on a locked commitment."""
    staged = setup_locked_commitment(
        commitment_overrides=commitment_overrides, **staging_kwargs
    )
    loan = deliver_loan(
        staged["commitment_id"],
        staged["seller_id"],
        actor=delivery_actor,
        **(loan_overrides or {}),
    )
    staged["loan"] = loan
    staged["loan_id"] = loan["id"]
    return staged


def setup_loan_in_review(
    review_actor: Optional[dict] = None, **staging_kwargs: Any
) -> dict:
    """A loan whose purchase review has been opened."""
    staged = setup_delivered_loan(**staging_kwargs)
    staged["loan"] = open_loan_review(staged["loan_id"], actor=review_actor)
    return staged


def record_defect(
    loan_id: str,
    defect_code: str = "DEF-001",
    category: str = "CREDIT",
    severity: str = "MEDIUM",
    actor: Optional[dict] = None,
    **overrides: Any,
) -> dict:
    """Record one defect against the loan file."""
    return get_success_data(
        api_client.create_defect(
            loan_id,
            factories.defect_payload(defect_code, category, severity, **overrides),
            actor or REVIEWER,
        ),
        201,
    )


def cure_defect(
    defect_id: str,
    seller_id: str,
    cure_document_reference: str = "CURE-DOC-001",
    actor: Optional[dict] = None,
) -> dict:
    """Seller cures a curable defect with supporting documentation."""
    return get_success_data(
        api_client.cure_defect(
            defect_id,
            factories.cure_payload(cure_document_reference),
            actor or make_seller_user_headers(seller_id),
        ),
        200,
    )


def waive_defect(
    defect_id: str, price_adjustment_bps: int = -25, actor: Optional[dict] = None
) -> dict:
    """Waive a curable defect against a price concession."""
    return get_success_data(
        api_client.waive_defect(
            defect_id, factories.waive_payload(price_adjustment_bps), actor or REVIEWER
        ),
        200,
    )


def add_suspense_condition(
    loan_id: str,
    condition_code: str = "COND-001",
    actor: Optional[dict] = None,
    **overrides: Any,
) -> dict:
    """Add one suspense condition to the loan file."""
    return get_success_data(
        api_client.create_suspense_condition(
            loan_id,
            factories.suspense_condition_payload(condition_code, **overrides),
            actor or REVIEWER,
        ),
        201,
    )


def clear_suspense_condition(
    condition_id: str,
    document_reference: str = "COND-DOC-001",
    actor: Optional[dict] = None,
) -> dict:
    """Clear a suspense condition on receipt of its document."""
    return get_success_data(
        api_client.clear_suspense_condition(
            condition_id,
            factories.condition_clear_payload(document_reference),
            actor or REVIEWER,
        ),
        200,
    )


def sweep_loan_conditions(loan_id: str, actor: Optional[dict] = None) -> dict:
    """Run the per-loan sweep over overdue curable defects and conditions."""
    return get_success_data(
        api_client.expire_loan_conditions(loan_id, actor or REVIEWER), 200
    )


def clear_loan_for_purchase(loan_id: str, actor: Optional[dict] = None) -> dict:
    """Clear the loan file for purchase."""
    return get_success_data(api_client.clear_loan(loan_id, actor or REVIEWER), 200)


def reject_loan(loan_id: str, actor: Optional[dict] = None) -> dict:
    """Reject the loan file on a non-curable defect."""
    return get_success_data(api_client.reject_loan(loan_id, actor or REVIEWER), 200)


def issue_purchase_advice(
    loan_id: str, actor: Optional[dict] = None, expected_version: Optional[int] = None
) -> dict:
    """Issue a purchase advice for the cleared loan."""
    version = expected_version if expected_version is not None else loan_version(loan_id)
    return get_success_data(
        api_client.create_purchase_advice(
            loan_id, factories.advice_payload(version), actor or REVIEWER
        ),
        201,
    )


def settle_purchase_advice(
    advice_id: str,
    funding_reference: str = "WIRE-0001",
    actor: Optional[dict] = None,
) -> dict:
    """Settle an issued purchase advice, purchasing the loan."""
    return get_success_data(
        api_client.settle_purchase_advice(
            advice_id,
            factories.settlement_payload(funding_reference),
            actor or REVIEWER_ALT,
        ),
        200,
    )


def record_payment_event(
    loan_id: str, event_type: str, actor: Optional[dict] = None
) -> dict:
    """Record the borrower's first payment outcome."""
    return get_success_data(
        api_client.create_payment_event(
            loan_id, factories.payment_event_payload(event_type), actor or ADMIN
        ),
        200,
    )


def setup_cleared_loan(clear_actor: Optional[dict] = None, **staging_kwargs: Any) -> dict:
    """A loan cleared for purchase with no open item against it."""
    staged = setup_loan_in_review(**staging_kwargs)
    staged["loan"] = clear_loan_for_purchase(staged["loan_id"], actor=clear_actor)
    return staged


def setup_advised_loan(
    advice_actor: Optional[dict] = None, **staging_kwargs: Any
) -> dict:
    """A cleared loan carrying one issued purchase advice."""
    staged = setup_cleared_loan(**staging_kwargs)
    advice = issue_purchase_advice(staged["loan_id"], actor=advice_actor)
    staged["advice"] = advice
    staged["advice_id"] = advice["id"]
    return staged


def setup_purchased_loan(
    settle_actor: Optional[dict] = None,
    funding_reference: str = "WIRE-0001",
    **staging_kwargs: Any,
) -> dict:
    """A fully purchased loan: cleared, advised and settled."""
    staged = setup_advised_loan(**staging_kwargs)
    staged["advice"] = settle_purchase_advice(
        staged["advice_id"], funding_reference, actor=settle_actor
    )
    staged["loan"] = read_loan(staged["loan_id"])
    staged["commitment"] = read_commitment(staged["commitment_id"])
    staged["seller"] = read_seller(staged["seller_id"])
    return staged


# ═══ Tier 4 — accumulation and threshold targeting ══════════════════════════


def purchase_additional_loan(
    commitment_id: str,
    seller_id: str,
    seller_loan_number: str,
    funding_reference: str = "WIRE-0002",
    delivery_actor: Optional[dict] = None,
    advice_actor: Optional[dict] = None,
    settle_actor: Optional[dict] = None,
    **loan_overrides: Any,
) -> dict:
    """Take one more loan from delivery all the way to purchased.

    Useful for building the prior month-to-date volume that drives the volume
    incentive, and for populating a scorecard period with scored loans.
    """
    loan = deliver_loan(
        commitment_id,
        seller_id,
        actor=delivery_actor,
        seller_loan_number=seller_loan_number,
        **loan_overrides,
    )
    open_loan_review(loan["id"])
    clear_loan_for_purchase(loan["id"])
    advice = issue_purchase_advice(loan["id"], actor=advice_actor)
    advice = settle_purchase_advice(
        advice["id"], funding_reference, actor=settle_actor
    )
    return {
        "loan": read_loan(loan["id"]),
        "loan_id": loan["id"],
        "advice": advice,
        "advice_id": advice["id"],
    }


def setup_loan_with_waived_defect(
    defect_code: str = "DEF-001",
    category: str = "CREDIT",
    severity: str = "HIGH",
    price_adjustment_bps: int = -25,
    **staging_kwargs: Any,
) -> dict:
    """A loan in review carrying one waived defect and no open item."""
    staged = setup_loan_in_review(**staging_kwargs)
    defect = record_defect(
        staged["loan_id"], defect_code, category, severity
    )
    staged["defect"] = waive_defect(defect["id"], price_adjustment_bps)
    staged["defect_id"] = defect["id"]
    staged["loan"] = read_loan(staged["loan_id"])
    return staged


def setup_loan_with_expired_defect(
    expiry_instant: str,
    defect_code: str = "DEF-001",
    category: str = "CREDIT",
    severity: str = "MEDIUM",
    **staging_kwargs: Any,
) -> dict:
    """A loan in review whose single curable defect has been swept expired."""
    staged = setup_loan_in_review(**staging_kwargs)
    defect = record_defect(staged["loan_id"], defect_code, category, severity)
    setup_clock(expiry_instant)
    staged["sweep"] = sweep_loan_conditions(staged["loan_id"])
    staged["defect_id"] = defect["id"]
    staged["loan"] = read_loan(staged["loan_id"])
    return staged


# ═══ Tier 5 — finalization and terminal states ══════════════════════════════


def pair_off_commitment(
    commitment_id: str, market_price_pct: float, actor: Optional[dict] = None
) -> dict:
    """Pair off the unfilled residual of a commitment."""
    return get_success_data(
        api_client.pair_off_commitment(
            commitment_id, factories.pair_off_payload(market_price_pct), actor or TRADER
        ),
        200,
    )


def sweep_due_commitments(
    seller_id: Optional[str] = None, actor: Optional[dict] = None
) -> dict:
    """Run the commitment expiry sweep, optionally scoped to one seller."""
    return get_success_data(
        api_client.expire_due_commitments(
            factories.expire_due_payload(seller_id), actor or TRADER
        ),
        200,
    )


def issue_repurchase_demand(
    loan_id: str,
    reason: str,
    demand_letter_reference: str = "DEMAND-0001",
    source_defect_id: Optional[str] = None,
    actor: Optional[dict] = None,
) -> dict:
    """Issue a repurchase demand against a purchased loan."""
    return get_success_data(
        api_client.create_repurchase_demand(
            loan_id,
            factories.repurchase_demand_payload(
                reason, demand_letter_reference, source_defect_id
            ),
            actor or REVIEWER,
        ),
        201,
    )


def appeal_repurchase_demand(
    demand_id: str,
    seller_id: str,
    appeal_reason: str = "Documentation supports the original underwrite.",
    actor: Optional[dict] = None,
) -> dict:
    """Seller appeals an issued demand inside the appeal window."""
    return get_success_data(
        api_client.appeal_repurchase_demand(
            demand_id,
            factories.appeal_payload(appeal_reason),
            actor or make_seller_user_headers(seller_id),
        ),
        200,
    )


def decide_repurchase_demand(
    demand_id: str,
    decision: str,
    note: Optional[str] = None,
    actor: Optional[dict] = None,
) -> dict:
    """Uphold or rescind a repurchase demand."""
    return get_success_data(
        api_client.decide_repurchase_demand(
            demand_id,
            factories.demand_decision_payload(decision, note),
            actor or REVIEWER_THIRD,
        ),
        200,
    )


def satisfy_repurchase_demand(
    demand_id: str,
    seller_id: str,
    remittance_reference: str = "REMIT-0001",
    actor: Optional[dict] = None,
) -> dict:
    """Seller remits the repurchase price, satisfying the demand."""
    return get_success_data(
        api_client.settle_repurchase_demand(
            demand_id,
            factories.demand_settlement_payload(remittance_reference),
            actor or make_seller_user_headers(seller_id),
        ),
        200,
    )


def complete_escrow_transfer(
    transfer_id: str,
    goodbye_letter_reference: str = "GOODBYE-0001",
    actor: Optional[dict] = None,
) -> dict:
    """Complete the escrow balance transfer with the borrower goodbye letter."""
    return get_success_data(
        api_client.complete_escrow_transfer(
            transfer_id,
            factories.escrow_completion_payload(goodbye_letter_reference),
            actor or REVIEWER,
        ),
        200,
    )


def open_scorecard(
    seller_id: str, period_start: str, period_end: str, actor: Optional[dict] = None
) -> dict:
    """Open a scorecard period for the seller."""
    return get_success_data(
        api_client.create_scorecard(
            seller_id,
            factories.scorecard_payload(period_start, period_end),
            actor or ANALYST,
        ),
        201,
    )


def close_scorecard(scorecard_id: str, actor: Optional[dict] = None) -> dict:
    """Close a scorecard period, grading the seller."""
    return get_success_data(
        api_client.close_scorecard(scorecard_id, actor or ANALYST), 200
    )


def setup_demanded_loan(
    reason: str = "MISREPRESENTATION",
    demand_letter_reference: str = "DEMAND-0001",
    source_defect_id: Optional[str] = None,
    demand_actor: Optional[dict] = None,
    **staging_kwargs: Any,
) -> dict:
    """A purchased loan already carrying an issued repurchase demand."""
    staged = setup_purchased_loan(**staging_kwargs)
    demand = issue_repurchase_demand(
        staged["loan_id"],
        reason,
        demand_letter_reference,
        source_defect_id,
        actor=demand_actor,
    )
    staged["demand"] = demand
    staged["demand_id"] = demand["id"]
    staged["loan"] = read_loan(staged["loan_id"])
    return staged
