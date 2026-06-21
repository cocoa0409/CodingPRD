"""RFQ + Quote endpoints (PRD §3.2)."""
from flask import Blueprint, request, g

import errors
from errors import ApiError
from db import db
from middleware import require_roles
from response import object_response, list_response
from services.common import (
    init_common, touch, public, get_body, require_fields, require_positive_int,
    invalid, parse_pagination, paginate, resolve, parse_instant,
)
from services.calculations import quote_total
from services.cascades import void_submitted_quotes

bp = Blueprint("rfqs", __name__)

RFQ_READ_ROLES = ("ProcurementAdmin", "Buyer", "Approver")


@bp.route("/procurement/rfqs", methods=["POST"])
@require_roles("Buyer")
def create_rfq():
    body = get_body()
    require_fields(body, ["requisition_id", "open_at", "close_at"])
    requisition_id = body["requisition_id"]
    resolve(db.requisitions, requisition_id)

    open_at = parse_instant(body["open_at"], "open_at")
    close_at = parse_instant(body["close_at"], "close_at")
    if not (close_at > open_at):
        invalid("close_at must be strictly after open_at")

    round_index = sum(1 for r in db.rfqs.values()
                      if r["requisition_id"] == requisition_id)

    rec = {
        "requisition_id": requisition_id,
        "round_index": round_index,
        "open_at": body["open_at"],
        "close_at": body["close_at"],
        "awarded_quote_id": None,
        "status": "OPEN",
        "_open_at_dt": open_at,
        "_close_at_dt": close_at,
    }
    init_common(rec)
    db.rfqs[rec["id"]] = rec
    return object_response(public(rec), status=201)


@bp.route("/procurement/rfqs/<rid>", methods=["GET"])
@require_roles(*RFQ_READ_ROLES)
def get_rfq(rid):
    rec = resolve(db.rfqs, rid)
    return object_response(public(rec))


@bp.route("/procurement/rfqs", methods=["GET"])
@require_roles(*RFQ_READ_ROLES)
def list_rfqs():
    limit, offset = parse_pagination(request.args)
    requisition_id = request.args.get("requisition_id")
    awarded_quote_id = request.args.get("awarded_quote_id")
    status = request.args.get("status")
    items = []
    for rec in db.rfqs.values():
        if requisition_id is not None and rec["requisition_id"] != requisition_id:
            continue
        if awarded_quote_id is not None and rec["awarded_quote_id"] != awarded_quote_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        items.append(rec)
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/procurement/rfqs/<rid>/award", methods=["POST"])
@require_roles("Buyer")
def award_rfq(rid):
    rec = resolve(db.rfqs, rid)
    body = get_body()
    require_fields(body, ["awarded_quote_id"])
    quote = resolve(db.quotes, body["awarded_quote_id"])

    if rec["status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "RFQ is not OPEN")

    requisition = db.requisitions.get(rec["requisition_id"])
    if requisition is None or requisition["status"] != "APPROVED":
        raise ApiError(errors.ERR_REQUISITION_NOT_APPROVED, 409,
                       "Requisition is not APPROVED")

    if quote["rfq_id"] != rec["id"] or quote["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Awarded quote must belong to this RFQ and be SUBMITTED")

    rec["awarded_quote_id"] = quote["id"]
    rec["status"] = "AWARDED"
    touch(rec)
    quote["status"] = "AWARDED"
    touch(quote)
    for q in db.quotes.values():
        if q["rfq_id"] == rec["id"] and q["id"] != quote["id"] and q["status"] == "SUBMITTED":
            q["status"] = "VOIDED"
            touch(q)
    return object_response(public(rec))


@bp.route("/procurement/rfqs/<rid>/cancel", methods=["POST"])
@require_roles("Buyer")
def cancel_rfq(rid):
    rec = resolve(db.rfqs, rid)
    if rec["status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "RFQ is not OPEN")
    rec["status"] = "CANCELLED"
    touch(rec)
    void_submitted_quotes(rec["id"])
    return object_response(public(rec))


@bp.route("/procurement/rfqs/<rid>/close_no_award", methods=["POST"])
@require_roles("Buyer")
def close_no_award_rfq(rid):
    rec = resolve(db.rfqs, rid)
    if rec["status"] != "OPEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "RFQ is not OPEN")
    if rec["awarded_quote_id"] is not None:
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "RFQ already has an awarded quote")
    rec["status"] = "CLOSED_NO_AWARD"
    touch(rec)
    void_submitted_quotes(rec["id"])
    return object_response(public(rec))


# -----------------------------------------------------------------------------
# Quotes
# -----------------------------------------------------------------------------
def _validate_unit_prices(unit_prices):
    if not isinstance(unit_prices, list) or len(unit_prices) == 0:
        invalid("unit_prices must be a non-empty array")
    for up in unit_prices:
        if not isinstance(up, dict):
            invalid("each unit price entry must be an object")
        if "sku" not in up or not isinstance(up["sku"], str) or up["sku"] == "":
            invalid("each unit price requires a sku")
        if "unit_price_cents" not in up:
            invalid("each unit price requires unit_price_cents")
        require_positive_int(up["unit_price_cents"], "unit_price_cents")
        if "promised_lead_days" in up and up["promised_lead_days"] is not None:
            v = up["promised_lead_days"]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                invalid("promised_lead_days must be a non-negative integer")


@bp.route("/procurement/quotes", methods=["POST"])
@require_roles("Buyer")
def create_quote():
    body = get_body()
    require_fields(body, ["rfq_id", "vendor_id", "submitted_at", "unit_prices"])
    rfq = resolve(db.rfqs, body["rfq_id"])
    vendor = resolve(db.vendors, body["vendor_id"])

    _validate_unit_prices(body["unit_prices"])
    submitted_at = parse_instant(body["submitted_at"], "submitted_at")

    # Half-open window: open_at <= submitted_at < close_at.
    if not (rfq["_open_at_dt"] <= submitted_at < rfq["_close_at_dt"]):
        raise ApiError(errors.ERR_QUOTE_OUTSIDE_WINDOW, 409,
                       "submitted_at is outside the RFQ window")

    requisition = db.requisitions.get(rfq["requisition_id"])
    qty_by_sku = {}
    if requisition is not None:
        for l in requisition["lines"]:
            qty_by_sku[l["sku"]] = qty_by_sku.get(l["sku"], 0) + l["quantity"]

    unit_prices = [
        {
            "sku": up["sku"],
            "unit_price_cents": up["unit_price_cents"],
            "promised_lead_days": up.get("promised_lead_days"),
        }
        for up in body["unit_prices"]
    ]
    total = quote_total(unit_prices, qty_by_sku)

    rec = {
        "rfq_id": rfq["id"],
        "vendor_id": vendor["id"],
        "submitted_at": body["submitted_at"],
        "unit_prices": unit_prices,
        "quoted_total_cents": total,
        "status": "SUBMITTED",
    }
    init_common(rec)
    db.quotes[rec["id"]] = rec
    return object_response(public(rec), status=201)


@bp.route("/procurement/quotes/<qid>", methods=["GET"])
@require_roles(*RFQ_READ_ROLES)
def get_quote(qid):
    rec = resolve(db.quotes, qid)
    return object_response(public(rec))


@bp.route("/procurement/quotes", methods=["GET"])
@require_roles(*RFQ_READ_ROLES)
def list_quotes():
    limit, offset = parse_pagination(request.args)
    rfq_id = request.args.get("rfq_id")
    vendor_id = request.args.get("vendor_id")
    status = request.args.get("status")
    items = []
    for rec in db.quotes.values():
        if rfq_id is not None and rec["rfq_id"] != rfq_id:
            continue
        if vendor_id is not None and rec["vendor_id"] != vendor_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        items.append(rec)
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)
