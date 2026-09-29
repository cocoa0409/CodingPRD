"""Statutory inventory buybacks: settlement pricing, volume reversal, clawback."""

from flask import Blueprint, g

from common import (
    apply_bp,
    bad,
    clock_dt,
    clock_str,
    is_int,
    new_row,
    opt_str,
    pagination,
    paginate,
    parse_dt,
    plus_days,
    q_enum,
    q_str,
    raw_body,
    req_enum,
    req_list,
    req_str,
    rhu,
    touch,
)
from db import db
from errors import ApiError
from middleware import actor_id, auth, own_consultant
from response import created, ok, ok_list
from services.genealogy import by_created
from services.lookup import fetch, peek
from services.qual import (
    ensure_row,
    recompute_group_fields_for_period,
    refresh_period_totals,
)

bp = Blueprint("buybacks", __name__)

BUYBACK_STATUSES = ("REQUESTED", "APPROVED", "DENIED", "REFUNDED")
CONDITIONS = ("RESALABLE", "OPENED", "DAMAGED")

READ_ROLES = ["Consultant", "ComplianceOfficer", "FinanceController", "PlatformAdmin"]


def _order_line(order, product_id):
    for line in order["lines"]:
        if line["product_id"] == product_id:
            return line
    return None


def _period_for_code(consultant, period_code):
    if period_code is None:
        return None
    for period in db.periods.values():
        if (
            period["compensation_plan_id"] == consultant["compensation_plan_id"]
            and period["period_code"] == period_code
        ):
            return period
    return None


def _reference_statement(consultant_id, period_code):
    candidates = [
        s
        for s in db.statements.values()
        if s["consultant_id"] == consultant_id
        and s["period_code"] == period_code
        and s["status"] in ("ACTIVE", "VOIDED")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return candidates[-1]


@bp.post("/buyback-requests")
def create_buyback():
    auth(["Consultant", "PlatformAdmin"])
    body = raw_body()

    # Row ownership runs before body validation.
    if g.get("role") == "Consultant" and isinstance(body.get("consultant_id"), str):
        own_consultant(body["consultant_id"])

    consultant_id = req_str(body, "consultant_id", min_len=1)
    lines = req_list(body, "lines", min_len=1, max_len=20)
    for line in lines:
        if not isinstance(line.get("product_order_id"), str) or not line["product_order_id"]:
            bad()
        if not isinstance(line.get("product_id"), str) or not line["product_id"]:
            bad()
        if not is_int(line.get("quantity")) or line["quantity"] < 1:
            bad()
        if line.get("condition") not in CONDITIONS:
            bad()

    consultant = fetch("consultant", consultant_id)

    resolved = []
    for line in lines:
        order = fetch("order", line["product_order_id"])
        product = fetch("product", line["product_id"])
        resolved.append((line, order, product))

    plan = db.plans.get(consultant["compensation_plan_id"])

    if consultant["status"] == "SUSPENDED":
        raise ApiError("ERR_CONSULTANT_NOT_ORDER_ELIGIBLE")

    # Line rules, rule by rule across every line.
    for line, order, product in resolved:
        if order["consultant_id"] != consultant["id"]:
            raise ApiError("ERR_BUYBACK_LINE_INVALID")
        if order["order_type"] != "PERSONAL_INVENTORY":
            raise ApiError("ERR_BUYBACK_LINE_INVALID")
        if order["payment_status"] not in ("PAID", "REFUNDED_PARTIAL"):
            raise ApiError("ERR_BUYBACK_LINE_INVALID")
        if _order_line(order, product["id"]) is None:
            raise ApiError("ERR_BUYBACK_LINE_INVALID")

    for line, order, product in resolved:
        if not product["buyback_eligible"]:
            raise ApiError("ERR_PRODUCT_NOT_BUYBACK_ELIGIBLE")

    window_days = int(plan["buyback_window_days"]) if plan else 0
    now = clock_dt()
    for line, order, product in resolved:
        placed = parse_dt(order.get("placed_at") or "")
        if placed is None or now is None:
            continue
        if plus_days(placed, window_days) < now:
            raise ApiError("ERR_BUYBACK_WINDOW_EXPIRED")

    for line, order, product in resolved:
        order_line = _order_line(order, product["id"])
        available = int(order_line["quantity"]) - int(order_line["returned_quantity"])
        if int(line["quantity"]) > available:
            raise ApiError("ERR_BUYBACK_QUANTITY_EXCEEDED")
        if line["condition"] != "RESALABLE":
            raise ApiError("ERR_BUYBACK_CONDITION_INVALID")

    priced_lines = []
    for line, order, product in resolved:
        quantity = int(line["quantity"])
        priced_lines.append(
            {
                "product_order_id": order["id"],
                "product_id": product["id"],
                "quantity": quantity,
                "condition": line["condition"],
                "unit_wholesale_price_cents": int(product["wholesale_price_cents"]),
                "volume_points_per_unit": int(product["volume_points_per_unit"]),
                "line_wholesale_cents": int(product["wholesale_price_cents"]) * quantity,
                "line_volume_points": int(product["volume_points_per_unit"]) * quantity,
            }
        )

    period_code = resolved[0][1]["posted_period_code"]

    eligible_wholesale = sum(l["line_wholesale_cents"] for l in priced_lines)
    requested_points = sum(l["line_volume_points"] for l in priced_lines)
    gross_refund = apply_bp(eligible_wholesale, int(plan["buyback_rate_bp"]))

    fee_bp = (
        int(plan["restock_fee_bp"])
        if gross_refund > int(plan["restock_free_limit_cents"])
        else 0
    )
    fee_cents = apply_bp(gross_refund, fee_bp)

    statement = _reference_statement(consultant["id"], period_code)
    reference_period = _period_for_code(consultant, period_code)
    reference_row = None
    if reference_period is not None:
        for row in db.qualifications.values():
            if (
                row["consultant_id"] == consultant["id"]
                and row["qualification_period_id"] == reference_period["id"]
            ):
                reference_row = row
                break

    clawback = 0
    if statement is not None and reference_row is not None:
        net_points = int(reference_row["net_personal_volume_points"])
        if net_points > 0:
            pv_bonus = int(statement["pv_bonus_cents"])
            clawback = min(rhu(pv_bonus * requested_points, net_points), pv_bonus)

    net_refund = max(0, gross_refund - fee_cents - clawback)
    unrecovered = max(0, fee_cents + clawback - gross_refund)

    row = new_row()
    row.update(
        {
            "consultant_id": consultant["id"],
            "lines": priced_lines,
            "status": "REQUESTED",
            "requested_volume_points": requested_points,
            "eligible_wholesale_cents": eligible_wholesale,
            "gross_refund_cents": gross_refund,
            "restocking_fee_bp": fee_bp,
            "restocking_fee_cents": fee_cents,
            "commission_clawback_cents": clawback,
            "net_refund_cents": net_refund,
            "unrecovered_clawback_cents": unrecovered,
            "volume_reversal_period_code": period_code,
            "decided_by_user_id": None,
            "decision_reason": None,
            "refunded_at": None,
        }
    )
    db.buybacks[row["id"]] = row
    return created(row)


@bp.get("/buyback-requests")
def list_buybacks():
    auth(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "consultant_id": q_str("consultant_id"),
        "status": q_enum("status", BUYBACK_STATUSES),
        "volume_reversal_period_code": q_str("volume_reversal_period_code"),
    }
    rows = by_created(list(db.buybacks.values()))
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/buyback-requests/<buyback_id>")
def read_buyback(buyback_id):
    auth(READ_ROLES)
    existing = peek("buyback", buyback_id)
    if existing is not None:
        own_consultant(existing["consultant_id"])
    return ok(fetch("buyback", buyback_id))


@bp.post("/buyback-requests/<buyback_id>/decision")
def buyback_decision(buyback_id):
    auth(["FinanceController"])
    body = raw_body()
    decision = req_enum(body, "decision", ("APPROVE", "DENY"))
    decision_reason = opt_str(body, "decision_reason")

    buyback = fetch("buyback", buyback_id)
    if buyback["status"] != "REQUESTED":
        raise ApiError("ERR_BUYBACK_NOT_REQUESTED")
    if decision == "DENY" and decision_reason is None:
        raise ApiError("ERR_DECISION_REASON_REQUIRED")

    buyback["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    buyback["decided_by_user_id"] = actor_id()
    buyback["decision_reason"] = decision_reason
    touch(buyback)
    return ok(buyback)


@bp.post("/buyback-requests/<buyback_id>/refund")
def buyback_refund(buyback_id):
    auth(["FinanceController"])
    buyback = fetch("buyback", buyback_id)
    if buyback["status"] != "APPROVED":
        raise ApiError("ERR_BUYBACK_NOT_APPROVED")

    consultant = db.consultants.get(buyback["consultant_id"])
    buyback["status"] = "REFUNDED"
    buyback["refunded_at"] = clock_str()
    touch(buyback)

    # ---- order side -----------------------------------------------------
    touched_orders = []
    for line in buyback["lines"]:
        order = db.orders.get(line["product_order_id"])
        if order is None:
            continue
        order_line = _order_line(order, line["product_id"])
        if order_line is not None:
            order_line["returned_quantity"] = int(order_line["returned_quantity"]) + int(
                line["quantity"]
            )
        if order["id"] not in [o["id"] for o in touched_orders]:
            touched_orders.append(order)

    for order in touched_orders:
        order["returned_volume_points"] = sum(
            int(l["volume_points_per_unit"]) * int(l["returned_quantity"])
            for l in order["lines"]
        )
        order["refunded_cents"] = sum(
            int(b["net_refund_cents"])
            for b in db.buybacks.values()
            if b["status"] == "REFUNDED"
            and any(l["product_order_id"] == order["id"] for l in b["lines"])
        )
        fully_returned = all(
            int(l["returned_quantity"]) >= int(l["quantity"]) for l in order["lines"]
        )
        order["payment_status"] = "REFUNDED_FULL" if fully_returned else "REFUNDED_PARTIAL"
        order["fulfillment_status"] = "RETURNED_FULL" if fully_returned else "RETURNED_PARTIAL"
        touch(order)

    # ---- volume side ----------------------------------------------------
    period = _period_for_code(consultant, buyback["volume_reversal_period_code"]) if consultant else None
    if period is not None:
        row = ensure_row(period, consultant["id"])
        row["returned_volume_points"] = int(row["returned_volume_points"]) + int(
            buyback["requested_volume_points"]
        )
        row["net_personal_volume_points"] = int(row["personal_volume_points"]) - int(
            row["returned_volume_points"]
        )
        touch(row)

        # PRD §3.4 defines total_net_personal_volume_points as the sum of
        # net_personal_volume_points across the period's rows, and only
        # group_volume_points and active_leg_count are frozen while the period is
        # LOCKED or CLOSED (PRD §2.10), so the period total follows the row here too.
        refresh_period_totals(period)

        if period["status"] in ("OPEN", "REOPENED"):
            recompute_group_fields_for_period(period)
        else:
            period["correction_pending"] = True
            touch(period)
            for run in db.runs.values():
                if run["qualification_period_id"] != period["id"] or run["status"] != "PAID":
                    continue
                run["correction_flagged"] = True
                touch(run)
                for disclosure in db.disclosures.values():
                    if (
                        disclosure["commission_run_id"] == run["id"]
                        and disclosure["status"] == "PUBLISHED"
                    ):
                        disclosure["status"] = "SUPERSEDED"
                        disclosure["supersede_reason"] = "PERIOD_CORRECTION"
                        touch(disclosure)

    # ---- ledger side ----------------------------------------------------
    if consultant is not None:
        consultant["clawback_balance_cents"] = int(consultant["clawback_balance_cents"]) + int(
            buyback["unrecovered_clawback_cents"]
        )
        consultant["payout_hold"] = int(consultant["clawback_balance_cents"]) > 0
        touch(consultant)

    return ok(buyback)
