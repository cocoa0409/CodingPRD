"""Shared route helpers: serialization with computed fields, pagination, lists."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import ALL_ROLES, authorized
from response import success_list, success_object
from services import core
from util import dec, num

READ_ROLES = list(ALL_ROLES)


def get_pagination():
    """limit: default 10, min 1, max 100; offset: default 0 (PRD 2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit_raw, str) and limit_raw.strip() != str(limit):
            # reject things like "1.5"
            try:
                f = float(limit_raw)
                if f != limit:
                    raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
            except (TypeError, ValueError):
                raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def serialize(collection, rec):
    """Inject computed fields and normalize numbers for JSON output."""
    if rec is None:
        return None
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    if collection == "crews":
        out["status"] = core.crew_status(rec)
    elif collection == "equipment":
        out["status"] = core.equipment_status(rec)
    elif collection == "bid_items":
        out["accepted_quantity"] = num(core.accepted_quantity(rec["id"]))
        out["billed_quantity"] = num(core.billed_quantity(rec["id"]))
    elif collection == "work_packages":
        out["rework_open_count"] = core.rework_open_count(rec["id"])
        out["open_material_issue_count"] = core.open_material_issue_count(rec["id"])
    elif collection == "stock_items":
        out["on_hand"] = num(core.stock_on_hand(rec))
    elif collection == "invoices":
        _serialize_invoice(rec, out)
    return out


def _serialize_invoice(rec, out):
    from services.billing import compute_lines, totals_as_numbers
    if rec["status"] == "DRAFT" or rec.get("frozen_lines") is None:
        wp = db["work_packages"].get(rec["work_package_id"])
        lines, subtotal, retainage, amount_due = compute_lines(
            wp, rec["period_start"], rec["period_end"], "final")
        out["lines"] = lines
        s, r, a = totals_as_numbers(subtotal, retainage, amount_due)
        out["subtotal"] = s
        out["retainage_amount"] = r
        out["amount_due"] = a
    else:
        out["lines"] = rec.get("frozen_lines")
        out["subtotal"] = rec.get("frozen_subtotal")
        out["retainage_amount"] = rec.get("frozen_retainage_amount")
        out["amount_due"] = rec.get("frozen_amount_due")
    out["hold_reason"] = core.invoice_hold_reason(rec)


def list_response(collection, filters=None, pre_hook=None):
    """GET list: auth (any declared role), optional pre-hook (e.g. outage lazy
    sweep), exact-match filters, created_at ascending, limit/offset pagination."""
    authorized(READ_ROLES)
    if pre_hook is not None:
        pre_hook()
    items = list(db[collection].values())
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items
                     if serialize(collection, r).get(field) == value]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize(collection, r) for r in page], total, limit, offset)


def get_one(collection, rid):
    authorized(READ_ROLES)
    rec = db[collection].get(rid)
    if rec is None:
        from errors import ERR_NOT_FOUND
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return success_object(serialize(collection, rec))
