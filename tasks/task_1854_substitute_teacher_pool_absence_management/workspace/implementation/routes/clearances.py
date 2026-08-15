"""Clearance endpoints: register (PENDING), verify, list (lazy expiry)."""

from flask import Blueprint

import domain
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_SUBSTITUTE_NOT_FOUND, ERR_CLEARANCE_NOT_FOUND,
    ERR_CLEARANCE_INVALID_STATE, ERR_CLEARANCE_INVALID,
)
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, paginated
from util import parse_date
from validate import body, req_str, req_enum, req_date

bp = Blueprint("clearances", __name__)

CLEARANCE_TYPES = ("BACKGROUND_CHECK", "TEACHING_CREDENTIAL", "TB_TEST")


@bp.route("/clearances", methods=["POST"])
def create_clearance():
    _, role = auth_context()
    data = body()
    substitute_id = req_str(data, "substitute_id")
    clearance_type = req_enum(data, "clearance_type", CLEARANCE_TYPES)
    expires_on = req_date(data, "expires_on")
    require_role(role, ["DistrictAdmin"])
    if substitute_id not in STORE.substitutes:
        raise_err(ERR_SUBSTITUTE_NOT_FOUND, "substitute id does not exist")
    c = new_entity(STORE.clearances, {
        "substitute_id": substitute_id,
        "clearance_type": clearance_type,
        "expires_on": expires_on,
        "status": "PENDING",
    })
    return ok(public(c), status=201)


@bp.route("/clearances/<cid>/verify", methods=["POST"])
def verify_clearance(cid):
    _, role = auth_context()
    require_role(role, ["DistrictAdmin"])
    c = STORE.clearances.get(cid)
    if c is None:
        raise_err(ERR_CLEARANCE_NOT_FOUND, "clearance id does not exist")
    # State first, then the expiry-date screen: a PENDING clearance whose
    # expires_on has passed fails as ERR_CLEARANCE_INVALID (PRD 3.2).
    if c["status"] != "PENDING":
        raise_err(ERR_CLEARANCE_INVALID_STATE, "verify requires status PENDING")
    if parse_date(c["expires_on"]) < domain.now().date():
        c["status"] = "EXPIRED"  # eager flip at a validation that reads it
        touch(c)
        raise_err(ERR_CLEARANCE_INVALID, "clearance expires_on has already passed")
    c["status"] = "VERIFIED"
    touch(c)
    return ok(public(c))


@bp.route("/substitutes/<sid>/clearances", methods=["GET"])
def list_substitute_clearances(sid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if sid not in STORE.substitutes:
        raise_err(ERR_SUBSTITUTE_NOT_FOUND, "substitute id does not exist")
    items = sorted((c for c in STORE.clearances.values() if c["substitute_id"] == sid),
                   key=lambda c: (c["created_at"], c["_seq"]))
    for c in items:
        domain.refresh_clearance(c)  # expiry applied lazily on read
    page, meta = paginated(items)
    return ok([public(c) for c in page], pagination=meta)
