"""Seller onboarding, approval, manual standing actions and scorecards."""

from flask import Blueprint

import calc
import validate as v
from auth import endpoint, require_scope, user_id
from envelope import created, ok, ok_list
from errors import ApiError
from helpers import (cancel_open_commitments, datetime_field, dt_of,
                     governing_review, governing_statement, need_scorecard,
                     need_seller, need_statement, need_qc_review,
                     seller_reviews, seller_scorecards, seller_statements)
from store import (base_record, date_end, date_start, db, now, parse_date,
                   plus_days, public, public_list, touch)

sellers_bp = Blueprint("sellers", __name__)

SELLER_TYPES = ("BANK", "CREDIT_UNION", "NON_BANK_IMB")
APPROVAL_STATUSES = ("APPLIED", "UNDER_REVIEW", "APPROVED", "DECLINED")
DELIVERY_STANDINGS = ("NOT_ELIGIBLE", "GOOD_STANDING", "WATCH", "SUSPENDED",
                      "TERMINATED")
REVIEW_TYPES = ("PRE_APPROVAL", "ANNUAL_RECERT")
STATEMENT_DECISIONS = ("ACCEPT", "REJECT")
APPROVAL_DECISIONS = ("APPROVE", "DECLINE")
STANDING_ACTIONS = ("SUSPEND", "REINSTATE", "TERMINATE", "PLACE_ON_WATCH")


# --------------------------------------------------------------------------
# sellers
# --------------------------------------------------------------------------

@sellers_bp.route("/sellers", methods=["POST"])
@endpoint("CounterpartyAnalyst")
def create_seller():
    body = v.body()
    legal_name = v.req_str(body, "legal_name", min_len=1, max_len=200)
    if not legal_name.strip():
        v.bad("Field 'legal_name' must be non-empty.")
    tin = v.req_str(body, "tin", min_len=9, max_len=9)
    if not tin.isdigit():
        v.bad("Field 'tin' must be exactly nine digits.")
    seller_type = v.req_enum(body, "seller_type", SELLER_TYPES)

    for existing in db.sellers.values():
        if existing["tin"] == tin:
            raise ApiError("ERR_DUPLICATE_TIN")

    record = base_record()
    record.update({
        "legal_name": legal_name,
        "tin": tin,
        "seller_type": seller_type,
        "approval_status": "APPLIED",
        "delivery_standing": "NOT_ELIGIBLE",
        "approval_tier": None,
        "servicing_retained_eligible": False,
        "approved_tangible_net_worth_cents": 0,
        "mandatory_exposure_limit_cents": 0,
        "open_mandatory_exposure_cents": 0,
        "net_funded_cents": 0,
        "fee_receivable_cents": 0,
        "current_defect_rate_bps": 0,
        "current_scorecard_grade": "UNRATED",
        "suspension_reason": None,
        "approval_decided_by_user_id": None,
    })
    db.sellers[record["id"]] = record
    return created(public(record))


@sellers_bp.route("/sellers/<sid>", methods=["GET"])
@endpoint("CounterpartyAnalyst", "PlatformAdmin", "LockDeskTrader",
          "PurchaseReviewer", "SellerUser")
def read_seller(sid):
    seller = need_seller(sid)
    require_scope(seller["id"])
    return ok(public(seller))


@sellers_bp.route("/sellers", methods=["GET"])
@endpoint("CounterpartyAnalyst", "PlatformAdmin")
def list_sellers():
    limit, offset = v.pagination()
    approval_status = v.arg("approval_status")
    delivery_standing = v.arg("delivery_standing")
    rows = list(db.sellers.values())
    if approval_status is not None:
        rows = [r for r in rows if r["approval_status"] == approval_status]
    if delivery_standing is not None:
        rows = [r for r in rows if r["delivery_standing"] == delivery_standing]
    rows.sort(key=lambda r: r["_seq"])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


# --------------------------------------------------------------------------
# financial statements
# --------------------------------------------------------------------------

@sellers_bp.route("/sellers/<sid>/financial-statements", methods=["POST"])
@endpoint("SellerUser", "CounterpartyAnalyst")
def create_statement(sid):
    seller = need_seller(sid)
    body = v.body()
    fiscal_year_end, _ = v.req_date(body, "fiscal_year_end")
    audited = v.req_bool(body, "audited")
    tangible_net_worth_cents = v.req_int(body, "tangible_net_worth_cents",
                                        minimum=0)
    liquid_assets_cents = v.req_int(body, "liquid_assets_cents", minimum=0)
    review_note = v.req_str(body, "review_note", max_len=1000, required=False)

    require_scope(seller["id"])

    if seller["approval_status"] not in ("APPLIED", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_SELLER_STATE")

    record = base_record()
    record.update({
        "seller_id": seller["id"],
        "fiscal_year_end": fiscal_year_end,
        "audited": audited,
        "tangible_net_worth_cents": tangible_net_worth_cents,
        "liquid_assets_cents": liquid_assets_cents,
        "status": "SUBMITTED",
        "reviewed_by_user_id": None,
        "review_note": review_note,
    })
    db.statements[record["id"]] = record
    return created(public(record))


@sellers_bp.route("/sellers/<sid>/financial-statements", methods=["GET"])
@endpoint("CounterpartyAnalyst", "PlatformAdmin", "SellerUser")
def list_statements(sid):
    seller = need_seller(sid)
    require_scope(seller["id"])
    limit, offset = v.pagination()
    status = v.arg("status")
    rows = seller_statements(seller["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@sellers_bp.route("/financial-statements/<stid>/review", methods=["POST"])
@endpoint("CounterpartyAnalyst")
def review_statement(stid):
    statement = need_statement(stid)
    body = v.body()
    decision = v.req_enum(body, "decision", STATEMENT_DECISIONS)
    review_note = v.req_str(body, "review_note", max_len=1000, required=False)

    if statement["status"] != "SUBMITTED":
        raise ApiError("ERR_STATEMENT_NOT_REVIEWABLE")

    statement["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    statement["reviewed_by_user_id"] = user_id()
    if review_note is not None:
        statement["review_note"] = review_note
    touch(statement)
    return ok(public(statement))


# --------------------------------------------------------------------------
# quality control reviews
# --------------------------------------------------------------------------

@sellers_bp.route("/sellers/<sid>/qc-reviews", methods=["POST"])
@endpoint("QCReviewer")
def create_qc_review(sid):
    seller = need_seller(sid)
    body = v.body()
    review_type = v.req_enum(body, "review_type", REVIEW_TYPES)

    if seller["approval_status"] not in ("APPLIED", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_SELLER_STATE")

    first_review = not seller_reviews(seller["id"])

    record = base_record()
    record.update({
        "seller_id": seller["id"],
        "review_type": review_type,
        "status": "OPEN",
        "outcome": None,
        "findings_count": 0,
        "critical_findings_count": 0,
        "completed_by_user_id": None,
        "completed_at": None,
    })
    db.qc_reviews[record["id"]] = record

    if first_review and seller["approval_status"] == "APPLIED":
        seller["approval_status"] = "UNDER_REVIEW"
        touch(seller)

    return created(public(record))


@sellers_bp.route("/sellers/<sid>/qc-reviews", methods=["GET"])
@endpoint("QCReviewer", "CounterpartyAnalyst", "PlatformAdmin")
def list_qc_reviews(sid):
    seller = need_seller(sid)
    limit, offset = v.pagination()
    status = v.arg("status")
    rows = seller_reviews(seller["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@sellers_bp.route("/qc-reviews/<rid>/complete", methods=["POST"])
@endpoint("QCReviewer")
def complete_qc_review(rid):
    review = need_qc_review(rid)
    body = v.body()
    findings_count = v.req_int(body, "findings_count", minimum=0)
    critical_findings_count = v.req_int(body, "critical_findings_count", minimum=0)
    if critical_findings_count > findings_count:
        v.bad("Field 'critical_findings_count' must not exceed 'findings_count'.")

    if review["status"] != "OPEN":
        raise ApiError("ERR_QC_REVIEW_NOT_OPEN")

    review["findings_count"] = findings_count
    review["critical_findings_count"] = critical_findings_count
    review["status"] = "COMPLETED"
    review["outcome"] = calc.qc_review_outcome(findings_count,
                                               critical_findings_count)
    review["completed_by_user_id"] = user_id()
    datetime_field(review, "completed_at", now())
    touch(review)
    return ok(public(review))


# --------------------------------------------------------------------------
# approval decision
# --------------------------------------------------------------------------

@sellers_bp.route("/sellers/<sid>/approval-decision", methods=["POST"])
@endpoint("CounterpartyAnalyst")
def approval_decision(sid):
    seller = need_seller(sid)
    body = v.body()
    decision = v.req_enum(body, "decision", APPROVAL_DECISIONS)
    review_note = v.req_str(body, "review_note", max_len=1000, required=False)

    review = governing_review(seller["id"])

    # group 6: segregation of duties, evaluated for APPROVE and DECLINE alike
    if review is not None and review["completed_by_user_id"] == user_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # group 8: state precondition
    if seller["approval_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_SELLER_STATE")

    if decision == "DECLINE":
        seller["approval_status"] = "DECLINED"
        seller["approval_decided_by_user_id"] = user_id()
        touch(seller)
        return ok(public(seller))

    # group 9: counterparty eligibility gates, in declared order
    statement = governing_statement(seller["id"])
    if statement is None:
        raise ApiError("ERR_NO_ACCEPTED_STATEMENT")
    fiscal_end = parse_date(statement["fiscal_year_end"])
    if plus_days(fiscal_end, calc.FS_STALENESS_DAYS) < now().date():
        raise ApiError("ERR_FINANCIAL_STATEMENT_STALE")
    if statement["tangible_net_worth_cents"] < calc.MIN_TANGIBLE_NET_WORTH_CENTS:
        raise ApiError("ERR_NET_WORTH_BELOW_MINIMUM")
    if statement["liquid_assets_cents"] < calc.MIN_LIQUIDITY_CENTS:
        raise ApiError("ERR_LIQUIDITY_BELOW_MINIMUM")
    if review is None:
        raise ApiError("ERR_QC_REVIEW_NOT_COMPLETED")
    if review["outcome"] not in ("PASS", "CONDITIONAL_PASS"):
        raise ApiError("ERR_QC_REVIEW_FAILED")

    outcome = review["outcome"]
    seller["approval_status"] = "APPROVED"
    seller["approved_tangible_net_worth_cents"] = statement["tangible_net_worth_cents"]
    seller["approval_tier"] = "STANDARD" if outcome == "PASS" else "CONDITIONAL"
    seller["servicing_retained_eligible"] = (outcome == "PASS")
    seller["mandatory_exposure_limit_cents"] = calc.mandatory_exposure_limit(
        outcome, statement["tangible_net_worth_cents"])
    if seller["delivery_standing"] == "NOT_ELIGIBLE":
        seller["delivery_standing"] = "GOOD_STANDING"
        seller["suspension_reason"] = None
    seller["approval_decided_by_user_id"] = user_id()
    touch(seller)
    return ok(public(seller))


# --------------------------------------------------------------------------
# manual standing actions
# --------------------------------------------------------------------------

@sellers_bp.route("/sellers/<sid>/standing-actions", methods=["POST"])
@endpoint("CounterpartyAnalyst", "PlatformAdmin")
def standing_action(sid):
    seller = need_seller(sid)
    body = v.body()
    action = v.req_enum(body, "action", STANDING_ACTIONS)
    v.req_str(body, "note", max_len=1000, required=False)

    if seller["approval_status"] != "APPROVED":
        raise ApiError("ERR_INVALID_SELLER_STATE")

    standing = seller["delivery_standing"]
    if action == "PLACE_ON_WATCH":
        if standing != "GOOD_STANDING":
            raise ApiError("ERR_INVALID_SELLER_STATE")
        seller["delivery_standing"] = "WATCH"
    elif action == "REINSTATE":
        if standing not in ("WATCH", "SUSPENDED"):
            raise ApiError("ERR_INVALID_SELLER_STATE")
        seller["delivery_standing"] = "GOOD_STANDING"
        seller["suspension_reason"] = None
    elif action == "SUSPEND":
        if standing not in ("GOOD_STANDING", "WATCH"):
            raise ApiError("ERR_INVALID_SELLER_STATE")
        seller["delivery_standing"] = "SUSPENDED"
        seller["suspension_reason"] = "MANUAL_COUNTERPARTY_ACTION"
        # a manual suspension deliberately cancels nothing
    else:  # TERMINATE
        if standing not in ("GOOD_STANDING", "WATCH", "SUSPENDED"):
            raise ApiError("ERR_INVALID_SELLER_STATE")
        seller["delivery_standing"] = "TERMINATED"
        touch(seller)
        cancel_open_commitments(seller)
        return ok(public(seller))

    touch(seller)
    return ok(public(seller))


# --------------------------------------------------------------------------
# scorecards
# --------------------------------------------------------------------------

@sellers_bp.route("/sellers/<sid>/scorecards", methods=["POST"])
@endpoint("CounterpartyAnalyst", "PlatformAdmin")
def create_scorecard(sid):
    seller = need_seller(sid)
    body = v.body()
    period_start, start_date = v.req_date(body, "period_start")
    period_end, end_date = v.req_date(body, "period_end")
    if end_date < start_date:
        v.bad("Field 'period_end' must not precede 'period_start'.")

    # group 11: the closed intervals of one seller may never overlap
    for existing in seller_scorecards(seller["id"]):
        other_start = parse_date(existing["period_start"])
        other_end = parse_date(existing["period_end"])
        if start_date <= other_end and other_start <= end_date:
            raise ApiError("ERR_SCORECARD_PERIOD_OVERLAP")

    record = base_record()
    record.update({
        "seller_id": seller["id"],
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "purchased_loan_count": 0,
        "purchased_upb_cents": 0,
        "defective_loan_count": 0,
        "defective_upb_cents": 0,
        "defect_rate_bps": 0,
        "upb_weighted_defect_rate_bps": 0,
        "grade": "UNRATED",
        "breach": False,
        "standing_action_applied": "NONE",
        "closed_at": None,
    })
    db.scorecards[record["id"]] = record
    return created(public(record))


@sellers_bp.route("/sellers/<sid>/scorecards", methods=["GET"])
@endpoint("CounterpartyAnalyst", "SellerUser", "PlatformAdmin")
def list_scorecards(sid):
    seller = need_seller(sid)
    require_scope(seller["id"])
    limit, offset = v.pagination()
    status = v.arg("status")
    rows = seller_scorecards(seller["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@sellers_bp.route("/scorecards/<scid>/close", methods=["POST"])
@endpoint("CounterpartyAnalyst")
def close_scorecard(scid):
    scorecard = need_scorecard(scid)

    if scorecard["status"] != "OPEN":
        raise ApiError("ERR_SCORECARD_NOT_OPEN")
    if now() <= date_end(scorecard["period_end"]):
        raise ApiError("ERR_SCORECARD_PERIOD_NOT_ENDED")

    seller = db.sellers.get(scorecard["seller_id"])
    metrics = calc.defect_rate_metrics(scorecard["seller_id"],
                                       scorecard["period_start"],
                                       scorecard["period_end"])
    scorecard.update(metrics)
    action = calc.scorecard_standing_action(metrics, seller)
    scorecard["standing_action_applied"] = action
    scorecard["status"] = "CLOSED"
    datetime_field(scorecard, "closed_at", now())
    touch(scorecard)

    seller["current_defect_rate_bps"] = metrics["defect_rate_bps"]
    seller["current_scorecard_grade"] = metrics["grade"]

    if action == "SUSPENDED" and seller["delivery_standing"] in (
            "GOOD_STANDING", "WATCH"):
        seller["delivery_standing"] = "SUSPENDED"
        seller["suspension_reason"] = "SCORECARD_DEFECT_RATE"
        touch(seller)
        cancel_open_commitments(seller)
    elif action == "WATCH" and seller["delivery_standing"] == "GOOD_STANDING":
        seller["delivery_standing"] = "WATCH"
        touch(seller)
    elif action == "RECOVERED" and seller["delivery_standing"] == "WATCH":
        seller["delivery_standing"] = "GOOD_STANDING"
        touch(seller)
    else:
        touch(seller)

    return ok(public(scorecard))
