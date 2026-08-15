"""Party onboarding: sellers, agents, buyers, buyer qualification."""

from flask import Blueprint

import db
import serializers
from errors import raise_err, ERR_DUPLICATE_RECORD, ERR_VALIDATION
from middleware import auth, require_roles, forbid
from response import (
    success_object, get_body, as_str, as_decimal, as_datetime,
    new_common, touch, fmt_dt,
)
from .clock import get_or_404, new_id

bp = Blueprint("parties", __name__)


@bp.post("/api/sellers")
def create_seller():
    _, role = auth()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    full_name = as_str(body, "full_name")
    email = as_str(body, "email")
    s = new_common({"id": new_id(), "full_name": full_name, "email": email})
    db.sellers[s["id"]] = s
    return success_object(serializers.seller(s), status=201)


@bp.post("/api/agents")
def create_agent():
    _, role = auth()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    full_name = as_str(body, "full_name")
    license_number = as_str(body, "license_number")
    for a in db.agents.values():
        if a["license_number"] == license_number:
            raise_err(ERR_DUPLICATE_RECORD, "license_number already registered")
    a = new_common({"id": new_id(), "full_name": full_name, "license_number": license_number})
    db.agents[a["id"]] = a
    return success_object(serializers.agent(a), status=201)


@bp.post("/api/buyers")
def create_buyer():
    _, role = auth()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    full_name = as_str(body, "full_name")
    email = as_str(body, "email")
    pof = as_decimal(body, "proof_of_funds_amount")
    b = new_common({
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "proof_of_funds_amount": pof,
        "qualification_status": "UNVERIFIED",
        "qualification_expires_at": None,
        "_qualification_expires_dt": None,
    })
    db.buyers[b["id"]] = b
    return success_object(serializers.buyer(b), status=201)


@bp.get("/api/buyers/<bid>")
def get_buyer(bid):
    user_id, role = auth()
    require_roles(role, {"PlatformAdmin", "BrokerAgent", "Buyer"})
    if role == "Buyer" and user_id != bid:
        forbid("a Buyer may read only its own record")
    b = get_or_404(db.buyers, bid, "buyer")
    return success_object(serializers.buyer(b))


@bp.post("/api/buyers/<bid>/qualify")
def qualify_buyer(bid):
    _, role = auth()
    require_roles(role, {"PlatformAdmin"})
    b = get_or_404(db.buyers, bid, "buyer")
    body = get_body()
    exp = as_datetime(body, "qualification_expires_at")
    # UNVERIFIED records the expiry verbatim; EXPIRED requires a future instant;
    # QUALIFIED / DISQUALIFIED cannot be (re)qualified.
    if b["qualification_status"] in ("QUALIFIED", "DISQUALIFIED"):
        raise_err(ERR_VALIDATION,
                  f"buyer in {b['qualification_status']} cannot be qualified")
    if b["qualification_status"] == "EXPIRED" and not (exp > db.clock_now()):
        raise_err(ERR_VALIDATION, "qualification_expires_at must be strictly in the future")
    b["qualification_status"] = "QUALIFIED"
    b["qualification_expires_at"] = fmt_dt(exp)
    b["_qualification_expires_dt"] = exp
    touch(b)
    return success_object(serializers.buyer(b))
