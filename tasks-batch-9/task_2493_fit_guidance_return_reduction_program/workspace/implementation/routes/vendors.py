"""Vendor registration and standing (PRD 3.1, 2.11)."""

import re

from flask import Blueprint

import constants as C
import validate as V
from db import db, new_row
from errors import ApiError
from lookup import get_vendor
from middleware import authenticate, require_owner
from response import object_response

bp = Blueprint("vendors", __name__)

BRAND_CODE_RE = re.compile(r"^[A-Z0-9]{2,8}$")


@bp.post("/fit-program/vendors")
def create_vendor():
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    body = V.get_body()

    name = V.req_str(body, "name", min_len=1, max_len=120)
    brand_code = V.req_str(body, "brand_code", min_len=2, max_len=8)
    if not BRAND_CODE_RE.match(brand_code):
        raise V.invalid("'brand_code' must be 2-8 uppercase characters A-Z or 0-9.")
    correction_budget_cents = V.req_int(body, "correction_budget_cents", minimum=0)

    for existing in db.vendors.values():
        if existing["brand_code"] == brand_code:
            raise ApiError("ERR_DUPLICATE_RESOURCE_KEY",
                           "brand_code '%s' is already registered." % brand_code)

    vendor = new_row({
        "name": name,
        "brand_code": brand_code,
        "correction_budget_cents": correction_budget_cents,
        "correction_spend_cents": 0,
        "correction_round_count": 0,
        "quality_chargeback_count": 0,
        "reliability_score_bp": 10000,
        "status": "ACTIVE",
    })
    db.vendors[vendor["id"]] = vendor
    return object_response(vendor, 201)


@bp.get("/fit-program/vendors/<vendor_id>")
def read_vendor(vendor_id):
    actor = authenticate(C.ROLE_MERCH_OPS_ADMIN, C.ROLE_FIT_ANALYST, C.ROLE_VENDOR_USER)
    vendor = get_vendor(vendor_id)
    if actor.role == C.ROLE_VENDOR_USER:
        require_owner(actor.user_id == vendor["id"],
                      "A VendorUser may only read its own vendor record.")
    return object_response(vendor)
