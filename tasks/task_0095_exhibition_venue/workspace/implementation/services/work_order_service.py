"""WorkOrder workflow (§3.6)."""

from flask import g

import db
from errors import (
    AppError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_INPUT,
    ERR_UTILITY_CAPACITY_EXCEEDED,
    ERR_DISPUTE_RESOLUTION_INVALID,
    ERR_FORBIDDEN,
)
from services.common import stamp_create, bump, check_occ, must_dict
from services import calculations


VALID_SERVICE_CODES = {"EXTRA_POWER", "FURNITURE", "NETWORK", "CLEANING", "SECURITY"}


def _get_wo(wo_id):
    wo = db.work_orders.get(wo_id)
    if wo is None:
        raise AppError(ERR_NOT_FOUND, "Work order not found.", 404)
    return wo


def _check_owner(wo):
    if g.role == "Exhibitor" and wo["exhibitor_id"] != g.user_id:
        raise AppError(ERR_FORBIDDEN, "Work order not owned by exhibitor.", 403)


def create_work_order(body: dict) -> dict:
    body = must_dict(body)
    for f in ("exhibition_id", "allocation_id", "lines"):
        if f not in body or body[f] in (None, ""):
            raise AppError(ERR_INVALID_INPUT, f"Missing required field '{f}'.", 422)
    ex = db.exhibitions.get(body["exhibition_id"])
    if ex is None:
        raise AppError(ERR_NOT_FOUND, "Exhibition not found.", 404)
    allocation = db.allocations.get(body["allocation_id"])
    if allocation is None:
        raise AppError(ERR_NOT_FOUND, "Allocation not found.", 404)
    if g.role == "Exhibitor" and allocation["exhibitor_id"] != g.user_id:
        raise AppError(ERR_FORBIDDEN, "Allocation not owned by exhibitor.", 403)
    lines = body["lines"]
    if not isinstance(lines, list) or not lines:
        raise AppError(ERR_INVALID_INPUT, "lines must be a non-empty array.", 422)
    parsed_lines = []
    for line in lines:
        if not isinstance(line, dict):
            raise AppError(ERR_INVALID_INPUT, "Each line must be an object.", 422)
        sc = line.get("service_code")
        qty = line.get("quantity")
        price = line.get("unit_price_cents")
        if sc not in VALID_SERVICE_CODES:
            raise AppError(ERR_INVALID_INPUT, "Invalid service_code.", 422)
        # PRD §3.6: create-time only requires integer types; strict positivity
        # is enforced at submit.
        if not isinstance(qty, int):
            raise AppError(ERR_INVALID_INPUT, "Each line.quantity must be an integer.", 422)
        if not isinstance(price, int):
            raise AppError(ERR_INVALID_INPUT, "Each line.unit_price_cents must be an integer.", 422)
        parsed_lines.append({
            "service_code": sc,
            "quantity": qty,
            "unit_price_cents": price,
        })
    row = {
        "exhibition_id": body["exhibition_id"],
        "allocation_id": body["allocation_id"],
        "exhibitor_id": allocation["exhibitor_id"],
        "lines": parsed_lines,
        "subtotal_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "status": "DRAFT",
        "dispute_reason": None,
        "resolved_total_cents": 0,
    }
    stamp_create(row)
    db.work_orders[row["id"]] = row
    return row


def submit_work_order(wo_id, body):
    wo = _get_wo(wo_id)
    _check_owner(wo)
    if wo["status"] != "DRAFT":
        raise AppError(ERR_INVALID_STATE, "Work order not in DRAFT.", 409)
    allocation = db.allocations.get(wo["allocation_id"])
    if allocation is None or allocation["status"] != "CONFIRMED":
        raise AppError(ERR_INVALID_STATE, "Allocation not CONFIRMED.", 409)
    # Validate lines.
    if not wo["lines"]:
        raise AppError(ERR_INVALID_INPUT, "Empty lines.", 422)
    for line in wo["lines"]:
        if int(line["quantity"]) <= 0 or int(line["unit_price_cents"]) <= 0:
            raise AppError(ERR_INVALID_INPUT, "Invalid line.", 422)
    # Utility capacity check (EXTRA_POWER in kW).
    booth = db.booths.get(allocation["booth_id"])
    if booth is not None:
        power_sum = sum(
            int(l["quantity"]) for l in wo["lines"] if l["service_code"] == "EXTRA_POWER"
        )
        if power_sum > float(booth.get("power_kw_capacity") or 0):
            raise AppError(ERR_UTILITY_CAPACITY_EXCEEDED, "Utility capacity exceeded.", 422)
    check_occ(wo, body)
    subtotal, tax, total = calculations.work_order_billing(wo["lines"])
    wo["subtotal_cents"] = subtotal
    wo["tax_cents"] = tax
    wo["total_cents"] = total
    wo["resolved_total_cents"] = total
    wo["status"] = "SUBMITTED"
    bump(wo)
    return wo


def dispatch_work_order(wo_id, body):
    wo = _get_wo(wo_id)
    if wo["status"] != "SUBMITTED":
        raise AppError(ERR_INVALID_STATE, "Work order not in SUBMITTED.", 409)
    check_occ(wo, body)
    wo["status"] = "DISPATCHED"
    bump(wo)
    return wo


def confirm_execution(wo_id, body):
    wo = _get_wo(wo_id)
    if wo["status"] != "DISPATCHED":
        raise AppError(ERR_INVALID_STATE, "Work order not in DISPATCHED.", 409)
    check_occ(wo, body)
    wo["status"] = "EXECUTED"
    bump(wo)
    return wo


def bill_work_order(wo_id, body):
    wo = _get_wo(wo_id)
    if wo["status"] != "EXECUTED":
        raise AppError(ERR_INVALID_STATE, "Work order not in EXECUTED.", 409)
    check_occ(wo, body)
    wo["status"] = "BILLED"
    wo["resolved_total_cents"] = wo["total_cents"]
    bump(wo)
    return wo


def dispute_work_order(wo_id, body):
    wo = _get_wo(wo_id)
    _check_owner(wo)
    if wo["status"] != "EXECUTED":
        raise AppError(ERR_INVALID_STATE, "Work order not in EXECUTED.", 409)
    body = must_dict(body)
    reason = body.get("dispute_reason")
    if not reason or not isinstance(reason, str) or not reason.strip():
        raise AppError(ERR_INVALID_INPUT, "dispute_reason is required.", 422)
    check_occ(wo, body)
    wo["dispute_reason"] = reason
    wo["status"] = "DISPUTED"
    bump(wo)
    return wo


def resolve_work_order(wo_id, body):
    wo = _get_wo(wo_id)
    if wo["status"] != "DISPUTED":
        raise AppError(ERR_INVALID_STATE, "Work order not in DISPUTED.", 409)
    body = must_dict(body)
    resolved = body.get("resolved_total_cents")
    if resolved is None or not isinstance(resolved, int):
        raise AppError(ERR_INVALID_INPUT, "resolved_total_cents must be an integer.", 422)
    if resolved < 0 or resolved > int(wo["total_cents"]):
        raise AppError(ERR_DISPUTE_RESOLUTION_INVALID, "Out-of-range resolution amount.", 422)
    check_occ(wo, body)
    wo["resolved_total_cents"] = resolved
    wo["status"] = "RESOLVED"
    bump(wo)
    return wo


def cancel_work_order(wo_id, body):
    wo = _get_wo(wo_id)
    _check_owner(wo)
    if wo["status"] != "DRAFT":
        raise AppError(ERR_INVALID_STATE, "Work order not in DRAFT.", 409)
    check_occ(wo, body)
    wo["status"] = "CANCELLED"
    bump(wo)
    return wo
