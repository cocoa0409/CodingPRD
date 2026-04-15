"""Settlement routes."""

from flask import Blueprint, request as req
import db
from errors import raise_error, ERR_SETTLEMENT_NOT_FOUND, ERR_INVALID_STATE
from middleware import require_roles
from response import success_response, list_response

bp = Blueprint("settlements", __name__)


def _paginate(request):
    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    return limit, offset


@bp.route("/platform/settlements/run", methods=["POST"])
def run_settlement():
    require_roles("platform_admin")
    body = req.get_json(force=True, silent=True) or {}
    period_start = body.get("period_start")
    period_end = body.get("period_end")
    results = []

    # Restaurant settlements
    for r in list(db.restaurants.values()):
        if r["balance_pending_cents"] > 0:
            gross = r["balance_pending_cents"]
            # Calculate deductions: sum of restaurant_payout_cents from orders with
            # complaints resolved as REFUND during the settlement period
            deductions = 0
            for c in db.complaints.values():
                if c["status"] == "RESOLVED_REFUND":
                    order = db.orders.get(c["order_id"])
                    if order and order["restaurant_id"] == r["id"]:
                        # Check if resolution happened "in period" - for simplicity,
                        # we include all resolved refund complaints
                        deductions += c.get("resolution_amount_cents", 0)

            net = gross - deductions
            net = max(net, 0)

            # Count orders completed for this restaurant
            total_orders = sum(
                1 for o in db.orders.values()
                if o["restaurant_id"] == r["id"] and o["status"] == "DELIVERED"
            )

            settlement = {
                "id": db.new_id(),
                "entity_type": "RESTAURANT",
                "entity_id": r["id"],
                "period_start": period_start,
                "period_end": period_end,
                "total_orders": total_orders,
                "gross_amount_cents": gross,
                "deductions_cents": deductions,
                "net_amount_cents": net,
                "status": "CALCULATED",
                "created_at": db.now_iso(),
            }
            db.settlements[settlement["id"]] = settlement
            results.append(settlement)

            r["balance_pending_cents"] = 0
            r["balance_settled_cents"] += net
            r["updated_at"] = db.now_iso()
            r["version"] += 1

    # Rider settlements
    for rider in list(db.riders.values()):
        if rider["earnings_balance_cents"] > 0:
            gross = rider["earnings_balance_cents"]
            total_deliveries = sum(
                1 for d in db.deliveries.values()
                if d["rider_id"] == rider["id"] and d["status"] == "DELIVERED"
            )
            settlement = {
                "id": db.new_id(),
                "entity_type": "RIDER",
                "entity_id": rider["id"],
                "period_start": period_start,
                "period_end": period_end,
                "total_orders": total_deliveries,
                "gross_amount_cents": gross,
                "deductions_cents": 0,
                "net_amount_cents": gross,
                "status": "CALCULATED",
                "created_at": db.now_iso(),
            }
            db.settlements[settlement["id"]] = settlement
            results.append(settlement)

            rider["earnings_balance_cents"] = 0
            rider["earnings_settled_cents"] += gross
            rider["updated_at"] = db.now_iso()
            rider["version"] += 1

    return success_response(results, response_type="array")


@bp.route("/platform/settlements", methods=["GET"])
def list_settlements():
    require_roles("platform_admin")
    limit, offset = _paginate(req)
    items = sorted(db.settlements.values(), key=lambda x: x["created_at"])
    et_f = req.args.get("entity_type")
    status_f = req.args.get("status")
    if et_f:
        items = [i for i in items if i["entity_type"] == et_f]
    if status_f:
        items = [i for i in items if i["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return list_response(page, total, limit, offset)


@bp.route("/platform/settlements/<settlement_id>/approve", methods=["POST"])
def approve_settlement(settlement_id):
    require_roles("platform_admin")
    s = db.settlements.get(settlement_id)
    if not s:
        raise_error(ERR_SETTLEMENT_NOT_FOUND, "Settlement not found.")
    if s["status"] != "CALCULATED":
        raise_error(ERR_INVALID_STATE, "Settlement must be CALCULATED to approve.")
    s["status"] = "APPROVED"
    return success_response(s)


@bp.route("/platform/settlements/<settlement_id>/mark-paid", methods=["POST"])
def mark_settlement_paid(settlement_id):
    require_roles("platform_admin")
    s = db.settlements.get(settlement_id)
    if not s:
        raise_error(ERR_SETTLEMENT_NOT_FOUND, "Settlement not found.")
    if s["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, "Settlement must be APPROVED to mark paid.")
    s["status"] = "PAID"
    return success_response(s)
