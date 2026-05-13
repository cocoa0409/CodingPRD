"""Cost endpoints + reports."""
from flask import Blueprint, request, g

import db
from middleware import require_roles
from response import success, success_list
from services import cost_logic, serializers
from services.common import get_or_404
from services.serializers import compute_business_unit_spend
from utils import get_pagination, paginate, get_str

bp = Blueprint("costs", __name__)


@bp.route("/costs", methods=["POST"])
@require_roles("FinanceManager")
def book_cost():
    body = request.get_json(silent=True) or {}
    with db.lock():
        cost = cost_logic.book_cost(body, g.user_role, g.user_id)
    return success(serializers.serialize_cost(cost), 201)


@bp.route("/costs/<cid>/allocation", methods=["PATCH"])
@require_roles("FinanceManager")
def reallocate(cid):
    body = request.get_json(silent=True) or {}
    with db.lock():
        cost = get_or_404(db.costs, cid)
        cost_logic.reallocate(cost, body, g.user_role, g.user_id)
    return success(serializers.serialize_cost(cost))


@bp.route("/costs", methods=["GET"])
@require_roles("FinanceManager", "Admin")
def list_costs():
    limit, offset = get_pagination(request.args)
    category = request.args.get("category")
    ip_right_id = request.args.get("ip_right_id")
    business_unit_id = request.args.get("business_unit_id")
    booked_from = request.args.get("booked_from")
    booked_to = request.args.get("booked_to")
    items = list(db.costs.values())
    if category:
        items = [c for c in items if c["category"] == category]
    if ip_right_id:
        items = [c for c in items if c.get("ip_right_id") == ip_right_id]
    if business_unit_id:
        items = [c for c in items if any(a["business_unit_id"] == business_unit_id
                                         for a in c.get("allocations", []))]
    if booked_from:
        bf = db.parse_iso(booked_from)
        if bf:
            items = [c for c in items if db.parse_iso(c["booked_at"]) and
                     db.parse_iso(c["booked_at"]) >= bf]
    if booked_to:
        bt = db.parse_iso(booked_to)
        if bt:
            items = [c for c in items if db.parse_iso(c["booked_at"]) and
                     db.parse_iso(c["booked_at"]) <= bt]
    items.sort(key=lambda c: c["created_at"])
    window, total = paginate(items, limit, offset)
    data = [serializers.serialize_cost(c) for c in window]
    return success_list(data, limit, offset, total)


@bp.route("/reports/cost-summary", methods=["GET", "POST"])
@require_roles("FinanceManager", "Admin")
def cost_summary():
    # Per PRD, callers supply from/to body fields. Accept both query and body.
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
    else:
        body = dict(request.args)
    from_str = body.get("from")
    to_str = body.get("to")
    business_unit_id = body.get("business_unit_id")

    from_dt = db.parse_iso(from_str) if from_str else None
    to_dt = db.parse_iso(to_str) if to_str else None

    # Aggregate per (business_unit_id, category) within the [from, to) window.
    rows = {}
    for cost in db.costs.values():
        booked = db.parse_iso(cost.get("booked_at"))
        if from_dt and (booked is None or booked < from_dt):
            continue
        if to_dt and (booked is None or booked >= to_dt):
            continue
        for a in cost.get("allocations", []):
            bu_id = a["business_unit_id"]
            if business_unit_id and bu_id != business_unit_id:
                continue
            key = (bu_id, cost["category"])
            rows[key] = rows.get(key, 0) + a["allocated_cents"]

    out_rows = []
    for (bu_id, category), spent in rows.items():
        bu = db.business_units.get(bu_id)
        out_rows.append({
            "business_unit_id": bu_id,
            "business_unit_code": bu["code"] if bu else None,
            "category": category,
            "allocated_cents": spent,
            "annual_budget_cents": bu["annual_budget_cents"] if bu else 0,
            "actual_spend_cents": compute_business_unit_spend(bu_id),
        })

    payload = {
        "from": from_str,
        "to": to_str,
        "rows": out_rows,
    }
    return success(payload)
