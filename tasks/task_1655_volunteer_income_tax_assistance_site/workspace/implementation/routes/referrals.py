"""Financial-capability add-on referrals (PRD §3.8)."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok, paginate
from services.serialize import referral_json
from validation import parse_body, require_entity

bp = Blueprint("referrals", __name__)

SERVICE_TYPES = ["SAVINGS_ACCOUNT", "CREDIT_COUNSELING", "BANK_ACCOUNT",
                 "FINANCIAL_COACHING"]

REFERRAL_STATUSES = ["OFFERED", "ACCEPTED", "ENROLLED", "DECLINED", "VOID"]

RETURN_TERMINAL = ("COMPLETED", "REFERRED", "WITHDRAWN")

CREATE_SCHEMA = {
    "service_type": {"kind": "enum", "required": True, "values": SERVICE_TYPES},
}

STATE_SCHEMA = {
    "to_status": {"kind": "enum", "required": True, "values": REFERRAL_STATUSES},
}

# Actor-drivable transitions: (from, to). VOID is system-only (PRD §3.8).
TRANSITIONS = {("OFFERED", "ACCEPTED"), ("ACCEPTED", "ENROLLED"),
               ("OFFERED", "DECLINED")}


@bp.post("/tax-returns/<return_id>/financial-referrals")
def offer_referral(return_id):
    uid, role, _ = get_context()
    require_roles(["Preparer", "SiteCoordinator"])
    ret = require_entity(store.tax_returns, return_id)
    body = parse_body(CREATE_SCHEMA)
    if ret["status"] in RETURN_TERMINAL:
        raise ApiError("ERR_INVALID_TRANSITION", 409,
                       "Terminal returns accept no further activity")
    ref = db.new_common({
        "tax_return_id": return_id,
        "service_type": body["service_type"],
        "status": "OFFERED",
        "offered_by": uid,
        "source": "MANUAL",
    })
    store.financial_referrals[ref["id"]] = ref
    return created(referral_json(ref))


@bp.get("/tax-returns/<return_id>/financial-referrals")
def list_referrals(return_id):
    get_context()
    require_entity(store.tax_returns, return_id)
    rows = [f for f in store.financial_referrals.values()
            if f["tax_return_id"] == return_id]
    page = paginate(rows)
    return ok([referral_json(f) for f in page], rtype="array", pagination=paginate)


@bp.post("/financial-referrals/<referral_id>/state")
def transition_referral(referral_id):
    get_context()
    require_roles(["Preparer", "SiteCoordinator"])
    ref = require_entity(store.financial_referrals, referral_id)
    body = parse_body(STATE_SCHEMA)
    current = ref["status"]
    target = body["to_status"]
    if (current, target) not in TRANSITIONS:
        raise ApiError("ERR_INVALID_TRANSITION", 409,
                       "Cannot move referral from %s to %s" % (current, target))
    ref["status"] = target
    db.touch(ref)
    return ok(referral_json(ref))
