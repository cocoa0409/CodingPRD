"""Substitute endpoints: register, get, list, activate, suspend."""

from flask import Blueprint, request

import domain
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_SUBSTITUTE_NOT_FOUND, ERR_SUBSTITUTE_INVALID_STATE,
    ERR_CLEARANCE_INVALID, ERR_INVALID_REQUEST,
)
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, paginated
from util import parse_date
from validate import body, req_str, req_int

bp = Blueprint("substitutes", __name__)

SUB_STATUSES = ("PENDING_CLEARANCE", "ACTIVE", "SUSPENDED")


def serialize_substitute(sub):
    domain.refresh_substitute_scores(sub)  # events age out of the window
    return public(sub)


@bp.route("/substitutes", methods=["POST"])
def create_substitute():
    _, role = auth_context()
    data = body()
    full_name = req_str(data, "full_name")
    rate = req_int(data, "base_daily_rate_cents")
    require_role(role, ["DistrictAdmin"])
    s = new_entity(STORE.substitutes, {
        "full_name": full_name,
        "base_daily_rate_cents": rate,
        "status": "PENDING_CLEARANCE",
        "reliability_events": [],
        "reliability_lifetime_score": 100,
        "reliability_trailing_score": 100,
        "completions_lifetime": 0,
        "completions_trailing": 0,
    })
    return ok(public(s), status=201)


@bp.route("/substitutes/<sid>", methods=["GET"])
def get_substitute(sid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    s = STORE.substitutes.get(sid)
    if s is None:
        raise_err(ERR_SUBSTITUTE_NOT_FOUND, "substitute id does not exist")
    return ok(serialize_substitute(s))


@bp.route("/substitutes", methods=["GET"])
def list_substitutes():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    status = request.args.get("status")
    items = sorted(STORE.substitutes.values(), key=lambda s: (s["created_at"], s["_seq"]))
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginated(items)
    return ok([serialize_substitute(s) for s in page], pagination=meta)


@bp.route("/substitutes/<sid>/activate", methods=["POST"])
def activate_substitute(sid):
    _, role = auth_context()
    require_role(role, ["DistrictAdmin"])
    s = STORE.substitutes.get(sid)
    if s is None:
        raise_err(ERR_SUBSTITUTE_NOT_FOUND, "substitute id does not exist")
    if s["status"] not in ("PENDING_CLEARANCE", "SUSPENDED"):
        raise_err(ERR_SUBSTITUTE_INVALID_STATE,
                  "activate requires status PENDING_CLEARANCE or SUSPENDED")
    # Expiry detection at activation applies the flip to this substitute's
    # clearances before the validity screen reads them.
    for c in STORE.clearances.values():
        if c["substitute_id"] == sid:
            domain.refresh_clearance(c)
    if not domain.required_clearances_valid(sid, domain.now().date()):
        raise_err(ERR_CLEARANCE_INVALID,
                  "required clearances must be VERIFIED and valid through the current date")
    s["status"] = "ACTIVE"
    touch(s)
    return ok(serialize_substitute(s))


@bp.route("/substitutes/<sid>/suspend", methods=["POST"])
def suspend_substitute(sid):
    _, role = auth_context()
    data = body()
    if "reason" in data and data["reason"] is not None and not isinstance(data["reason"], str):
        raise_err(ERR_INVALID_REQUEST, "reason must be a string")
    require_role(role, ["DistrictAdmin"])
    s = STORE.substitutes.get(sid)
    if s is None:
        raise_err(ERR_SUBSTITUTE_NOT_FOUND, "substitute id does not exist")
    if s["status"] != "ACTIVE":
        raise_err(ERR_SUBSTITUTE_INVALID_STATE, "manual suspend requires status ACTIVE")
    domain.suspend_substitute(s)
    return ok(serialize_substitute(s))
