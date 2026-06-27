"""Merchant routes (PRD §3.1).

POST /merchants is OPEN (pre-auth onboarding) — no headers required.
"""
import re

from flask import Blueprint

import db
import serialize
from common import parse_body, require_fields, require_int, stamp_create, touch
from errors import err, ERR_INVALID_REQUEST
from lookups import get_merchant
from middleware import auth_and_role
from response import object_response

bp = Blueprint("merchants", __name__)

EIN_RE = re.compile(r"^\d{9}$")
STATE_RE = re.compile(r"^[A-Z]{2}$")


@bp.post("/merchants")
def create_merchant():
    # Open endpoint: no auth.
    body = parse_body()
    require_fields(body, ["legal_name", "ein", "state_code", "monthly_revenue_cents"])

    legal_name = body["legal_name"]
    ein = body["ein"]
    state_code = body["state_code"]
    if not isinstance(legal_name, str) or not legal_name:
        raise err(ERR_INVALID_REQUEST, "legal_name must be a non-empty string")
    if not isinstance(ein, str) or not EIN_RE.match(ein):
        raise err(ERR_INVALID_REQUEST, "ein must be exactly 9 digits")
    if not isinstance(state_code, str) or not STATE_RE.match(state_code):
        raise err(ERR_INVALID_REQUEST, "state_code must be 2 uppercase letters")
    monthly_revenue_cents = require_int(body, "monthly_revenue_cents", minimum=0)

    # EIN unique across all merchants.
    for m in db.merchants.values():
        if m["ein"] == ein:
            raise err(ERR_INVALID_REQUEST, "ein must be unique")

    record = {
        "legal_name": legal_name,
        "ein": ein,
        "state_code": state_code,
        "status": "ACTIVE",
        "monthly_revenue_cents": monthly_revenue_cents,
    }
    stamp_create(record)
    db.merchants[record["id"]] = record
    return object_response(serialize.merchant(record), 201)


@bp.get("/merchants/<rid>")
def fetch_merchant(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    m = get_merchant(rid)
    return object_response(serialize.merchant(m), 200)


@bp.post("/merchants/<rid>/blocklist")
def blocklist_merchant(rid):
    auth_and_role(["CreditOfficer"])
    m = get_merchant(rid)
    m["status"] = "BLOCKLISTED"
    touch(m)
    return object_response(serialize.merchant(m), 200)
