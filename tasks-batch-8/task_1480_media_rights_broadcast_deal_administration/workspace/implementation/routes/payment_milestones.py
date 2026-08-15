from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import raise_error
from flask import Blueprint, request
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from serializers import serialize
from services import calculations as calc
from services.clock import now, parse_iso
from util import (apply_filters, get_json_body, get_pagination, paginate,
                  req_datetime, req_int, req_number, sorted_by_created,
                  stamp_new, touch)

bp = Blueprint("payment_milestones", __name__)


def _get_deal_or_404(deal_id):
    d = db.deals.get(deal_id)
    if d is None:
        raise_error("ERR_DEAL_NOT_FOUND")
    return d


def _get_milestone_scoped(deal_id, milestone_id):
    _get_deal_or_404(deal_id)
    m = db.payment_milestones.get(milestone_id)
    if m is None or m["deal_id"] != deal_id:
        raise_error("ERR_MILESTONE_NOT_FOUND")
    return m


def _get_milestone_or_404(milestone_id):
    m = db.payment_milestones.get(milestone_id)
    if m is None:
        raise_error("ERR_MILESTONE_NOT_FOUND")
    return m


@bp.route("/deals/<dealId>/payment-milestones", methods=["POST"])
def create_milestone(dealId):
    require_roles({"FinanceController"})
    deal = _get_deal_or_404(dealId)
    body = get_json_body()
    season_index = req_int(body, "season_index", minimum=1)
    sequence_in_season = req_int(body, "sequence_in_season", minimum=1)
    due_date = req_datetime(body, "due_date", parse_iso)
    milestone_weight = req_number(body, "milestone_weight")
    if milestone_weight <= 0:
        raise_error("ERR_INVALID_REQUEST", "milestone_weight must be > 0")
    milestone = {
        "deal_id": dealId,
        "season_index": season_index,
        "sequence_in_season": sequence_in_season,
        "due_date": due_date,
        "base_amount_cents": 0,
        "milestone_weight": milestone_weight,
        "escalated_amount_cents": 0,
        "late_fee_cents": 0,
        "paid_at": None,
        "status": "SCHEDULED",
    }
    stamp_new(milestone)
    db.payment_milestones[milestone["id"]] = milestone
    calc.recompute_season_allocation(deal, season_index)
    # PRD §2.7: adding a payment milestone amends the deal — its version
    # must advance so a stale expected_deal_version is rejected at execute.
    touch(deal)
    return success_object(serialize(milestone), status_code=201)


@bp.route("/deals/<dealId>/payment-milestones", methods=["GET"])
def list_milestones(dealId):
    require_roles(ALL_ROLES)
    _get_deal_or_404(dealId)
    limit, offset = get_pagination()
    items = [m for m in db.payment_milestones.values() if m["deal_id"] == dealId]
    items = sorted_by_created(items)
    items = apply_filters(items, [
        ("status", request.args.get("status")),
        ("season_index", request.args.get("season_index")),
        ("deal_id", request.args.get("deal_id")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(m) for m in page], limit, offset, total)


@bp.route("/deals/<dealId>/payment-milestones/<milestoneId>", methods=["GET"])
def get_milestone(dealId, milestoneId):
    require_roles(ALL_ROLES)
    return success_object(serialize(_get_milestone_scoped(dealId, milestoneId)))


@bp.route("/payment-milestones", methods=["GET"])
def list_milestones_flat():
    require_roles(ALL_ROLES)
    limit, offset = get_pagination()
    items = sorted_by_created(list(db.payment_milestones.values()))
    items = apply_filters(items, [
        ("deal_id", request.args.get("deal_id")),
        ("status", request.args.get("status")),
        ("season_index", request.args.get("season_index")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(m) for m in page], limit, offset, total)


@bp.route("/payment-milestones/<milestoneId>", methods=["GET"])
def get_milestone_flat(milestoneId):
    require_roles(ALL_ROLES)
    return success_object(serialize(_get_milestone_or_404(milestoneId)))


@bp.route("/deals/<dealId>/payment-milestones/<milestoneId>/invoice", methods=["POST"])
def invoice_milestone(dealId, milestoneId):
    require_roles({"FinanceController"})
    m = _get_milestone_scoped(dealId, milestoneId)
    deal = db.deals[dealId]
    if m["status"] != "SCHEDULED":
        raise_error("ERR_MILESTONE_NOT_SCHEDULED")
    if deal["status"] not in ("EXECUTED", "ACTIVE"):
        raise_error("ERR_DEAL_NOT_LIVE")
    m["status"] = "INVOICED"
    touch(m)
    # Clock may already be past due: run system transitions.
    from services.system import run_clock_transitions
    run_clock_transitions()
    return success_object(serialize(m))


@bp.route("/deals/<dealId>/payment-milestones/<milestoneId>/record-payment", methods=["POST"])
def record_payment(dealId, milestoneId):
    require_roles({"FinanceController"})
    m = _get_milestone_scoped(dealId, milestoneId)
    deal = db.deals[dealId]
    now_dt = now()
    if m["status"] == "INVOICED":
        if now_dt <= m["due_date"]:
            m["status"] = "PAID"
            m["paid_at"] = now_dt
            touch(m)
            if deal["status"] == "EXECUTED":
                any_paid = any(
                    x["deal_id"] == dealId and x["status"] == "PAID"
                    for x in db.payment_milestones.values()
                )
                if any_paid:
                    deal["status"] = "ACTIVE"
                    touch(deal)
            calc.refresh_posture(deal)
        else:
            # Past due: system transition to OVERDUE path.
            m["status"] = "OVERDUE"
            touch(m)
            deal["payment_delinquency_count"] = deal.get("payment_delinquency_count", 0) + 1
            touch(deal)
            calc.refresh_posture(deal)
    elif m["status"] == "OVERDUE":
        days_late = (now_dt.date() - m["due_date"].date()).days
        if days_late < 0:
            days_late = 0
        late_fee = int((Decimal(m["escalated_amount_cents"]) * calc.LATE_FEE_DAILY_RATE * Decimal(days_late)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        m["late_fee_cents"] = late_fee
        m["escalated_amount_cents"] = m["base_amount_cents"] + late_fee
        m["status"] = "CURED"
        m["paid_at"] = now_dt
        touch(m)
        deal["payment_delinquency_count"] = max(0, deal.get("payment_delinquency_count", 0) - 1)
        touch(deal)
        calc.refresh_posture(deal)
    else:
        raise_error("ERR_INVALID_REQUEST", f"Milestone in status {m['status']} cannot accept a payment")
    return success_object(serialize(m))


@bp.route("/deals/<dealId>/payment-milestones/<milestoneId>/declare-default", methods=["POST"])
def declare_default(dealId, milestoneId):
    require_roles({"FinanceController"})
    m = _get_milestone_scoped(dealId, milestoneId)
    deal = db.deals[dealId]
    if m["status"] != "OVERDUE":
        raise_error("ERR_INVALID_REQUEST", "Declare-default requires milestone OVERDUE")
    now_dt = now()
    if now_dt < m["due_date"] + timedelta(days=calc.DEFAULT_GRACE_DAYS):
        raise_error("ERR_DEFAULT_GRACE_NOT_ELAPSED")
    # Finalize late fee before defaulting.
    days_late = max(0, (now_dt.date() - m["due_date"].date()).days)
    late_fee = int((Decimal(m["base_amount_cents"]) * calc.LATE_FEE_DAILY_RATE * Decimal(days_late)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    m["late_fee_cents"] = late_fee
    m["escalated_amount_cents"] = m["base_amount_cents"] + late_fee
    m["status"] = "DEFAULTED"
    touch(m)
    deal["payment_delinquency_count"] = max(0, deal.get("payment_delinquency_count", 0) - 1)
    deal["accrued_shortfall_liability_cents"] = deal.get("accrued_shortfall_liability_cents", 0) + m["escalated_amount_cents"] + m["late_fee_cents"]
    touch(deal)
    calc.refresh_posture(deal)
    return success_object(serialize(m))
