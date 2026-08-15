"""Co-op bootstrap, singleton read, logical clock, quarter close."""

from flask import Blueprint

import db
from db import store, new_entity, public
from errors import err_state, err_invalid_request
from middleware import require_roles, body_json, req_str
from response import success_object
from services import lifecycle

bp = Blueprint("coop", __name__)

ALL_ROLES = ("CoopAdmin", "FinanceOfficer", "SupplierRep", "MemberRep", "ProgramAuditor")


@bp.route("/coop/bootstrap", methods=["POST"])
@require_roles("CoopAdmin")
def bootstrap(uid, role):
    body = body_json(required=True)
    name = req_str(body, "name")
    if store.coop is not None:
        raise err_state("Co-op has already been bootstrapped")
    coop = new_entity()
    coop.update({
        "name": name,
        "current_quarter_index": 0,
        "pool_reserve_cents": 0,
        "retained_revenue_cents": 0,
    })
    store.coop = coop
    return success_object(public(coop), code=201)


@bp.route("/coop", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_coop(uid, role):
    return success_object(public(db.get_coop()), code=200)


@bp.route("/coop/_clock/set_current_utc", methods=["POST"])
@require_roles("CoopAdmin")
def set_clock(uid, role):
    body = body_json(required=True)
    raw = body.get("to_iso8601")
    parsed = db.parse_iso(raw)
    if parsed is None:
        raise err_invalid_request("to_iso8601 must be a valid ISO 8601 timestamp")
    store.clock = parsed
    return success_object({"current_utc": db.iso_now()}, code=200)


@bp.route("/coop/close_quarter", methods=["POST"])
@require_roles("CoopAdmin")
def close_quarter(uid, role):
    coop = lifecycle.close_quarter()
    return success_object(public(coop), code=200)
