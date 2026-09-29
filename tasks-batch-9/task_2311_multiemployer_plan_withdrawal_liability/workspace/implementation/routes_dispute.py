"""Review, arbitration and asset-sale due diligence (§3.8 - §3.9)."""

from flask import Blueprint

import calc
import serialize
import services as svc
from clockutil import add_days, now
from db import db
from errors import fail, invalid
from listing import paged, str_filters
from response import created, obj
from validate import (ANY_ROLE, authorize, body, field_bool, field_datetime,
                      field_enum, field_fraction, field_int, field_str, present)

bp = Blueprint("dispute", __name__)

CHALLENGED_ASSUMPTIONS = ("NONE", "INTEREST_RATE", "MORTALITY", "UVB_POOL_ALLOCATION")
REVIEW_DECISIONS = ("AFFIRMED", "REDUCED", "REVERSED")
ASSUMPTION_RULINGS = ("SUSTAINED", "REJECTED", "NOT_RAISED")
ADVANCE_TARGETS = ("BRIEFING", "HEARING", "AWARD_ISSUED", "REMANDED", "CLOSED")
AWARD_OUTCOMES = ("AFFIRM", "REDUCE", "VACATE", "REMAND")
DISPOSITIONS = ("CERTIFY_4204_EXEMPTION", "DETERMINE_SUCCESSOR", "REJECT")

YEAR_MIN = 1900
YEAR_MAX = 2200


# --------------------------------------------------------------------------
# ReviewRequest
# --------------------------------------------------------------------------

@bp.post("/review-requests")
def file_review():
    ctx = authorize(("EmployerRepresentative",))
    data = body()
    assessment_id = field_str(data, "liability_assessment_id", required=True)
    grounds = field_str(data, "grounds_summary", required=True, min_len=1, max_len=2000)
    challenged = field_enum(data, "challenged_assumption", CHALLENGED_ASSUMPTIONS,
                            default="NONE")
    proposed = field_int(data, "proposed_interest_rate_bps", minimum=1, maximum=3000)

    # tier 3: the proposed rate belongs to an interest-rate challenge and to
    # nothing else
    if challenged == "INTEREST_RATE" and proposed is None:
        invalid("'proposed_interest_rate_bps' is required when "
                "'challenged_assumption' is INTEREST_RATE.")
    if challenged != "INTEREST_RATE" and present(data, "proposed_interest_rate_bps"):
        invalid("'proposed_interest_rate_bps' is only permitted when "
                "'challenged_assumption' is INTEREST_RATE.")

    assessment = svc.get_assessment(assessment_id)
    svc.require_owner(ctx, svc.employer_of_assessment(assessment))

    # tier 8
    svc.require_issued(assessment)
    if assessment["review_status"] != "NONE":
        fail("ERR_DUPLICATE_REVIEW_REQUEST")

    # tier 11
    filed_at = now()
    deadline = assessment["review_deadline_at"]
    if deadline is not None and filed_at > deadline:
        fail("ERR_REVIEW_WINDOW_CLOSED")

    review = svc.new_row(db.review_requests, {
        "liability_assessment_id": assessment["id"],
        "grounds_summary": grounds,
        "challenged_assumption": challenged,
        "proposed_interest_rate_bps": proposed,
        "filed_at": filed_at,
        "filed_by_user_id": ctx.user_id,
        "plan_response_deadline_at": None,
        "arbitration_deadline_at": None,
        "status": "PENDING",
        "decision": "NONE",
        "assumption_ruling": "PENDING",
        "recomputed_net_assessed_cents": None,
        "decided_at": None,
        "decided_by_user_id": None,
    })
    svc.review_deadlines(review)

    svc.apply_changes(assessment, {"review_status": "REQUESTED"})
    return created(serialize.review_request(review))


@bp.post("/review-requests/<review_request_id>/decide")
def decide_review(review_request_id):
    ctx = authorize(("PlanTrustee",))
    review = svc.get_review(review_request_id)
    data = body()
    decision = field_enum(data, "decision", REVIEW_DECISIONS, required=True)
    ruling = field_enum(data, "assumption_ruling", ASSUMPTION_RULINGS, required=True)
    recomputed = field_int(data, "recomputed_net_assessed_cents", minimum=0)

    if decision == "REDUCED" and recomputed is None:
        invalid("'recomputed_net_assessed_cents' is required when 'decision' "
                "is REDUCED.")
    if decision != "REDUCED" and present(data, "recomputed_net_assessed_cents"):
        invalid("'recomputed_net_assessed_cents' is only permitted when "
                "'decision' is REDUCED.")

    # tier 8
    if review["status"] != "PENDING":
        fail("ERR_REVIEW_ALREADY_DECIDED")
    assessment = svc.get_assessment(review["liability_assessment_id"])
    svc.require_issued(assessment)

    # tier 9: the trustee who issued the demand may not adjudicate the challenge
    if ctx.user_id == assessment["issued_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    review["status"] = "DECIDED"
    review["decision"] = decision
    review["assumption_ruling"] = ruling
    review["recomputed_net_assessed_cents"] = recomputed
    review["decided_at"] = now()
    review["decided_by_user_id"] = ctx.user_id
    review["arbitration_deadline_at"] = calc.arbitration_deadline(review)
    svc.touch(review)

    # the recomputed figure is a proposal only: no monetary field moves here
    svc.apply_changes(assessment, {"review_status": "DECIDED"})
    return obj(serialize.review_request(review))


@bp.get("/review-requests")
def list_reviews():
    authorize(ANY_ROLE)
    rows = str_filters(list(db.review_requests.values()), {
        "liability_assessment_id": "liability_assessment_id",
        "status": "status",
    })
    return paged(rows, serialize.review_request)


@bp.get("/review-requests/<review_request_id>")
def read_review(review_request_id):
    authorize(ANY_ROLE)
    return obj(serialize.review_request(svc.get_review(review_request_id)))


# --------------------------------------------------------------------------
# Arbitration
# --------------------------------------------------------------------------

@bp.post("/arbitrations")
def initiate_arbitration():
    ctx = authorize(("EmployerRepresentative",))
    data = body()
    assessment_id = field_str(data, "liability_assessment_id", required=True)
    review_id = field_str(data, "review_request_id", required=True)

    # tier 5: foreign keys resolve in declaration order
    assessment = svc.get_assessment(assessment_id)
    review = svc.get_review(review_id)

    svc.require_owner(ctx, svc.employer_of_assessment(assessment))

    # tier 8
    svc.require_issued(assessment)

    # tier 10: the referenced request's own status is the gateway
    if review["status"] not in ("DECIDED", "DEEMED_DENIED"):
        fail("ERR_REVIEW_REQUEST_NOT_DECIDED")

    # tier 11
    initiated_at = now()
    deadline = review["arbitration_deadline_at"]
    if deadline is not None and initiated_at > deadline:
        fail("ERR_ARBITRATION_WINDOW_CLOSED")

    # tier 12: an employer may not borrow somebody else's decided request
    if review["liability_assessment_id"] != assessment["id"]:
        fail("ERR_EMPLOYER_PLAN_MISMATCH")

    arbitration = svc.new_row(db.arbitrations, {
        "liability_assessment_id": assessment["id"],
        "review_request_id": review["id"],
        "initiated_at": initiated_at,
        "round_number": 1,
        "status": "BRIEFING",
        "award_outcome": "NONE",
        "assumption_ruling": "PENDING",
        "awarded_net_assessed_cents": None,
        "closed_at": None,
    })
    return created(serialize.arbitration(arbitration))


@bp.post("/arbitrations/<arbitration_id>/advance")
def advance_arbitration(arbitration_id):
    authorize(("Arbitrator",))
    arbitration = svc.get_arbitration(arbitration_id)
    data = body()
    to_status = field_enum(data, "to_status", ADVANCE_TARGETS, required=True)

    # tier 8
    if arbitration["status"] == "CLOSED":
        fail("ERR_ARBITRATION_ALREADY_CLOSED")
    current = arbitration["status"]
    if not ((current == "BRIEFING" and to_status == "HEARING")
            or (current == "REMANDED" and to_status == "BRIEFING")):
        fail("ERR_INVALID_ARBITRATION_ADVANCE")

    # tier 12: at most three rounds
    if arbitration["round_number"] > calc.MAX_ARBITRATION_ROUNDS:
        fail("ERR_ARBITRATION_ROUND_LIMIT")

    svc.apply_changes(arbitration, {"status": to_status})
    return obj(serialize.arbitration(arbitration))


@bp.post("/arbitrations/<arbitration_id>/award")
def award_arbitration(arbitration_id):
    authorize(("Arbitrator",))
    arbitration = svc.get_arbitration(arbitration_id)
    data = body()
    outcome = field_enum(data, "award_outcome", AWARD_OUTCOMES, required=True)
    ruling = field_enum(data, "assumption_ruling", ASSUMPTION_RULINGS, required=True)
    awarded = field_int(data, "awarded_net_assessed_cents", minimum=0)

    if outcome == "REDUCE" and awarded is None:
        invalid("'awarded_net_assessed_cents' is required when 'award_outcome' "
                "is REDUCE.")
    if outcome != "REDUCE" and present(data, "awarded_net_assessed_cents"):
        invalid("'awarded_net_assessed_cents' is only permitted when "
                "'award_outcome' is REDUCE.")

    # tier 8
    if arbitration["status"] == "CLOSED":
        fail("ERR_ARBITRATION_ALREADY_CLOSED")
    if arbitration["status"] != "HEARING":
        fail("ERR_ARBITRATION_NOT_IN_AWARDABLE_STATE")

    # tier 12: remands are bounded at three rounds
    if outcome == "REMAND" and arbitration["round_number"] >= calc.MAX_ARBITRATION_ROUNDS:
        fail("ERR_ARBITRATION_ROUND_LIMIT")

    assessment = svc.get_assessment(arbitration["liability_assessment_id"])
    review = db.review_requests.get(arbitration["review_request_id"])

    if outcome == "REDUCE":
        # tier 13: reject before a single row moves.  The rate the successor
        # generation would amortise at is the one this very award sustains.
        rate_bps = assessment["interest_rate_bps_applied"]
        if (ruling == "SUSTAINED" and review is not None
                and review["challenged_assumption"] == "INTEREST_RATE"
                and review["proposed_interest_rate_bps"] is not None):
            rate_bps = review["proposed_interest_rate_bps"]
        svc.check_amortizable(svc.plan_of_assessment(assessment), awarded,
                              assessment["annual_payment_cents"], rate_bps,
                              svc.applied_credit_for(assessment))

    arbitration["award_outcome"] = outcome
    arbitration["assumption_ruling"] = ruling
    arbitration["awarded_net_assessed_cents"] = awarded

    if outcome == "REMAND":
        # AWARD_ISSUED is passed through immediately by the server itself
        arbitration["status"] = "REMANDED"
        arbitration["round_number"] += 1
        svc.touch(arbitration)
        return obj(serialize.arbitration(arbitration))

    arbitration["status"] = "CLOSED"
    arbitration["closed_at"] = now()
    svc.touch(arbitration)

    if outcome == "AFFIRM":
        svc.apply_changes(assessment, {"review_status": "ARBITRATED"})
    elif outcome == "REDUCE":
        svc.apply_changes(assessment, {"review_status": "ARBITRATED"})
        svc.regenerate(assessment, "ARBITRATION_AWARD", awarded)
    else:
        svc.rescind(assessment, arbitration, review)

    return obj(serialize.arbitration(arbitration))


@bp.get("/arbitrations")
def list_arbitrations():
    authorize(ANY_ROLE)
    rows = str_filters(list(db.arbitrations.values()), {
        "liability_assessment_id": "liability_assessment_id",
        "review_request_id": "review_request_id",
        "status": "status",
    })
    return paged(rows, serialize.arbitration)


@bp.get("/arbitrations/<arbitration_id>")
def read_arbitration(arbitration_id):
    authorize(ANY_ROLE)
    return obj(serialize.arbitration(svc.get_arbitration(arbitration_id)))


# --------------------------------------------------------------------------
# AssetSaleTransaction
# --------------------------------------------------------------------------

@bp.post("/asset-sale-transactions")
def submit_transaction():
    ctx = authorize(("EmployerRepresentative", "FundAdministrator"))
    data = body()
    seller_id = field_str(data, "seller_employer_id", required=True)
    buyer_id = field_str(data, "buyer_controlled_group_id", required=True)
    closing_date = field_datetime(data, "closing_date", required=True)
    closing_plan_year = field_int(data, "closing_plan_year", required=True,
                                  minimum=YEAR_MIN, maximum=YEAR_MAX)
    if closing_plan_year != closing_date.year:
        invalid("'closing_plan_year' must equal the calendar year of "
                "'closing_date'.")
    purchase_price = field_int(data, "purchase_price_cents", required=True, minimum=0)
    bond_amount = field_int(data, "bond_amount_cents", default=0, minimum=0)
    assumes = field_bool(data, "buyer_assumes_contribution_obligation", required=True)
    workforce = field_fraction(data, "workforce_continuity_pct", required=True)
    assets = field_fraction(data, "asset_continuity_pct", required=True)
    customers = field_fraction(data, "customer_continuity_pct", required=True)

    seller = svc.get_employer(seller_id)
    svc.get_group(buyer_id)
    svc.require_owner(ctx, seller)

    required_bond = calc.required_sale_of_assets_bond(seller, closing_plan_year,
                                                      purchase_price)

    txn = svc.new_row(db.transactions, {
        "seller_employer_id": seller["id"],
        "buyer_controlled_group_id": buyer_id,
        "closing_date": closing_date,
        "closing_plan_year": closing_plan_year,
        "purchase_price_cents": purchase_price,
        "bond_amount_cents": bond_amount,
        "buyer_assumes_contribution_obligation": assumes,
        "workforce_continuity_pct": workforce,
        "asset_continuity_pct": assets,
        "customer_continuity_pct": customers,
        "required_bond_cents": required_bond,
        "substantial_continuity_score": 0.0,
        "bond_period_end_plan_year": None,
        "exemption_status": "PENDING",
        "successor_determination": "PENDING",
        "status": "SUBMITTED",
        "adjudicated_at": None,
    })
    return created(serialize.transaction(txn))


@bp.post("/asset-sale-transactions/<asset_sale_transaction_id>/adjudicate")
def adjudicate_transaction(asset_sale_transaction_id):
    authorize(("PlanTrustee",))
    txn = svc.get_transaction(asset_sale_transaction_id)
    data = body()
    disposition = field_enum(data, "disposition", DISPOSITIONS, required=True)

    # tier 8
    if txn["status"] != "SUBMITTED":
        fail("ERR_TRANSACTION_ALREADY_ADJUDICATED")

    if disposition == "CERTIFY_4204_EXEMPTION":
        # tier 9 precedes tier 12: an under-bonded sale that also assumed
        # nothing surfaces as the bond failure
        if txn["bond_amount_cents"] < txn["required_bond_cents"]:
            fail("ERR_4204_BOND_INSUFFICIENT")
        if not txn["buyer_assumes_contribution_obligation"]:
            fail("ERR_4204_OBLIGATION_NOT_ASSUMED")

    group = db.controlled_groups.get(txn["buyer_controlled_group_id"])
    seller = db.employers.get(txn["seller_employer_id"])
    changes = {"adjudicated_at": now()}

    if disposition == "CERTIFY_4204_EXEMPTION":
        changes.update({
            "status": "EXEMPTION_CERTIFIED",
            "exemption_status": "EXEMPT_4204",
            "bond_period_end_plan_year":
                txn["closing_plan_year"] + calc.BOND_PERIOD_PLAN_YEARS,
        })
        # the seller's own status is deliberately left alone
    elif disposition == "DETERMINE_SUCCESSOR":
        score, liable = calc.substantial_continuity_score(txn)
        changes.update({
            "status": "SUCCESSOR_DETERMINED",
            "exemption_status": "NOT_EXEMPT",
            "substantial_continuity_score": score,
            "successor_determination":
                "SUCCESSOR_LIABLE" if liable else "NO_SUCCESSOR_LIABILITY",
        })
        if liable and group is not None and seller is not None:
            group["_successor_extra_cents"] = (
                group.get("_successor_extra_cents", 0)
                + seller["outstanding_liability_cents"])
    else:
        changes.update({
            "status": "REJECTED",
            "exemption_status": "NOT_EXEMPT",
            "successor_determination": "NO_SUCCESSOR_LIABILITY",
        })

    txn.update(changes)
    svc.touch(txn)

    if disposition != "REJECT":
        svc.recompute_group(group)
    return obj(serialize.transaction(txn))


@bp.get("/asset-sale-transactions")
def list_transactions():
    authorize(ANY_ROLE)
    rows = str_filters(list(db.transactions.values()), {
        "seller_employer_id": "seller_employer_id",
        "buyer_controlled_group_id": "buyer_controlled_group_id",
        "exemption_status": "exemption_status",
    })
    return paged(rows, serialize.transaction)


@bp.get("/asset-sale-transactions/<asset_sale_transaction_id>")
def read_transaction(asset_sale_transaction_id):
    authorize(ANY_ROLE)
    return obj(serialize.transaction(svc.get_transaction(asset_sale_transaction_id)))
