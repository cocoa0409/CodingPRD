"""Vendor endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_TAX_ID_REQUIRED
from middleware import auth_required, ALL_ROLES
from response import ok_object
from routes._helpers import (
    get_body, require_fields, serialize, is_str, is_bool, is_number, is_int,
)
from services.common import new_common_fields, touch

bp = Blueprint("vendors", __name__)

PAYMENT_METHODS = {"ACH", "CHECK", "CARD"}


@bp.post("/ap/vendors")
def create_vendor():
    auth_required({"APManager"})()
    body = get_body()
    require_fields(body, ["legal_name", "payment_method"])

    if not is_str(body["legal_name"]) or not body["legal_name"]:
        raise APIError(ERR_INVALID_REQUEST, 400, "legal_name must be a non-empty string")
    if body["payment_method"] not in PAYMENT_METHODS:
        raise APIError(ERR_INVALID_REQUEST, 400, "payment_method must be one of ACH, CHECK, CARD")

    is_1099 = body.get("is_1099", False)
    if not is_bool(is_1099):
        raise APIError(ERR_INVALID_REQUEST, 400, "is_1099 must be a boolean")

    tax_id = body.get("tax_id")
    if tax_id is not None and not is_str(tax_id):
        raise APIError(ERR_INVALID_REQUEST, 400, "tax_id must be a string")

    early_pay_terms_pct = body.get("early_pay_terms_pct", 0)
    if not is_number(early_pay_terms_pct) or early_pay_terms_pct < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "early_pay_terms_pct must be a non-negative number")

    early_pay_window_days = body.get("early_pay_window_days", 0)
    if not is_int(early_pay_window_days) or early_pay_window_days < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "early_pay_window_days must be a non-negative integer")

    net_terms_days = body.get("net_terms_days", 30)
    if not is_int(net_terms_days) or net_terms_days < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "net_terms_days must be a non-negative integer")

    # business_referential: is_1099 vendor must supply a non-empty tax_id (422).
    if is_1099 and (tax_id is None or tax_id == ""):
        raise APIError(ERR_TAX_ID_REQUIRED, 422, "is_1099 vendor requires a non-empty tax_id")

    vendor = {
        **new_common_fields(),
        "legal_name": body["legal_name"],
        "payment_method": body["payment_method"],
        "is_1099": is_1099,
        "tax_id": tax_id,
        "early_pay_terms_pct": early_pay_terms_pct,
        "early_pay_window_days": early_pay_window_days,
        "net_terms_days": net_terms_days,
        "status": "ACTIVE",
        "ytd_1099_paid_cents": 0,
    }
    db.vendors[vendor["id"]] = vendor
    return ok_object(serialize(vendor), http_status=201)


@bp.get("/ap/vendors/<vid>")
def get_vendor(vid):
    auth_required(ALL_ROLES)()
    v = db.vendors.get(vid)
    if v is None:
        raise APIError(ERR_NOT_FOUND, 404, "Vendor not found")
    return ok_object(serialize(v))


@bp.post("/ap/vendors/<vid>/hold")
def hold_vendor(vid):
    auth_required({"APManager"})()
    v = db.vendors.get(vid)
    if v is None:
        raise APIError(ERR_NOT_FOUND, 404, "Vendor not found")
    body = get_body()
    require_fields(body, ["on_hold"])
    on_hold = body["on_hold"]
    if not is_bool(on_hold):
        raise APIError(ERR_INVALID_REQUEST, 400, "on_hold must be a boolean")
    v["status"] = "ON_HOLD" if on_hold else "ACTIVE"
    touch(v)
    return ok_object(serialize(v))
