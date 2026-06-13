"""Quote endpoints: create (priced), list, read, send, accept, decline."""
from flask import Blueprint, request

import calc
import db
from auth import require_roles
from clock import logical_now, parse_iso
from errors import err
from helpers import (
    ADDON_CODES, apply_quote_expiry, body, get_or_404, paginate,
    pagination_params, req_enum, req_str,
)
from response import success, list_success
from serialize import public, public_list

bp = Blueprint("quotes", __name__)


def _price_quote(quote, prop):
    base, addon_total, quoted_total = calc.quote_amount(
        quote["pricing_basis"], prop, quote["addon_codes"]
    )
    quote["base_price_cents"] = base
    quote["addon_total_cents"] = addon_total
    quote["quoted_total_cents"] = quoted_total
    quote["required_deposit_cents"] = calc.deposit_requirement(quoted_total)


@bp.post("/quotes")
def create_quote():
    require_roles({"Customer", "Billing"})
    data = body()
    account_id = req_str(data, "account_id")
    property_id = req_str(data, "property_id")
    pricing_basis = req_enum(data, "pricing_basis", {"PANE_COUNT", "SQ_FT"})
    valid_until = req_str(data, "valid_until")
    try:
        parse_iso(valid_until)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "valid_until must be a valid ISO 8601 instant")
    addon_codes = []
    if data.get("addon_codes") is not None:
        raw = data["addon_codes"]
        if not isinstance(raw, list):
            raise err("ERR_INVALID_REQUEST", "addon_codes must be a list")
        for c in raw:
            if not isinstance(c, str) or c not in ADDON_CODES:
                raise err("ERR_INVALID_REQUEST", "addon_codes contains an invalid value")
            addon_codes.append(c)

    # Existence (left-to-right): account then property.
    get_or_404(db.accounts, account_id)
    prop = get_or_404(db.properties, property_id)
    # Referential consistency: property must belong to the quote's account.
    if prop["account_id"] != account_id:
        raise err("ERR_REFERENTIAL_MISMATCH", "property does not belong to account")

    rec = db.new_record(db.quotes, {
        "account_id": account_id,
        "property_id": property_id,
        "pricing_basis": pricing_basis,
        "addon_codes": addon_codes,
        "valid_until": valid_until,
        "status": "DRAFT",
        "base_price_cents": 0,
        "addon_total_cents": 0,
        "quoted_total_cents": 0,
        "required_deposit_cents": 0,
    })
    _price_quote(rec, prop)
    return success(public(rec), status=201)


@bp.get("/quotes")
def list_quotes():
    require_roles({"Customer", "Billing"})
    limit, offset = pagination_params()
    property_id = request.args.get("property_id")
    account_id = request.args.get("account_id")
    rows = list(db.quotes.values())
    if property_id is not None:
        rows = [q for q in rows if q["property_id"] == property_id]
    if account_id is not None:
        rows = [q for q in rows if q["account_id"] == account_id]
    for q in rows:
        apply_quote_expiry(q)
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


@bp.get("/quotes/<rid>")
def read_quote(rid):
    require_roles({"Customer", "Billing"})
    rec = get_or_404(db.quotes, rid)
    apply_quote_expiry(rec)
    return success(public(rec))


@bp.post("/quotes/<rid>/send")
def send_quote(rid):
    require_roles({"Customer", "Billing"})
    rec = get_or_404(db.quotes, rid)
    apply_quote_expiry(rec)
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Quote is not in DRAFT")
    # Recompute then freeze the four priced fields.
    prop = db.properties.get(rec["property_id"])
    _price_quote(rec, prop)
    rec["status"] = "SENT"
    db.touch(rec)
    return success(public(rec))


@bp.post("/quotes/<rid>/accept")
def accept_quote(rid):
    require_roles({"Customer"})
    rec = get_or_404(db.quotes, rid)
    apply_quote_expiry(rec)
    if rec["status"] == "EXPIRED":
        raise err("ERR_QUOTE_EXPIRED", "Quote has expired")
    if rec["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Quote is not in SENT")
    # Defensive: accept only before valid_until.
    if logical_now() >= parse_iso(rec["valid_until"]):
        rec["status"] = "EXPIRED"
        db.touch(rec)
        raise err("ERR_QUOTE_EXPIRED", "Quote has expired")
    rec["status"] = "ACCEPTED"
    db.touch(rec)
    return success(public(rec))


@bp.post("/quotes/<rid>/decline")
def decline_quote(rid):
    require_roles({"Customer"})
    rec = get_or_404(db.quotes, rid)
    apply_quote_expiry(rec)
    if rec["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Quote is not in SENT")
    rec["status"] = "DECLINED"
    db.touch(rec)
    return success(public(rec))
