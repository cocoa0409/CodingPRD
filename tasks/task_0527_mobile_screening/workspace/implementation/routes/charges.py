from flask import Blueprint, request
from db import db
from middleware import require_user_context, require_role
from response import object_response, array_response
from services.common import (bump, public, get_json_body, paginate, sorted_by_creation)
from services.lookup import get_or_404
from services.calc import finalized_responsibility, recompute_grant
from errors import err

bp = Blueprint("charges", __name__)

READ_ROLES = {"ProgramManager", "BillingClerk"}


@bp.route("/charges", methods=["GET"])
def list_charges():
    _, role = require_user_context()
    require_role(role, READ_ROLES)
    items = list(db.charges.values())
    for f in ("appointment_id", "participant_id", "grant_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [c for c in items if c.get(f) == val]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return array_response([public(c) for c in page], limit, offset, total)


@bp.route("/charges/<rid>", methods=["GET"])
def get_charge(rid):
    _, role = require_user_context()
    require_role(role, READ_ROLES)
    return object_response(public(get_or_404("charges", rid)), 200)


def _require_version(body):
    v = body.get("expected_charge_version")
    if v is None:
        raise err("ERR_INVALID_REQUEST", "expected_charge_version required")
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "expected_charge_version must be an integer")
    return v


@bp.route("/charges/<rid>/adjudicate", methods=["POST"])
def adjudicate(rid):
    _, role = require_user_context()
    require_role(role, {"BillingClerk"})
    charge = get_or_404("charges", rid)
    body = get_json_body()
    expected = _require_version(body)
    # state (priority 6) before OCC-mismatch business gate ordering per PRD §3.7
    if charge["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Charge not DRAFT")
    if expected != charge["version"]:
        raise err("ERR_STALE_VERSION", "expected_charge_version mismatch")
    pay_type = charge["pay_type"]
    insurance_allowed = body.get("insurance_allowed_cents")
    if pay_type == "INSURANCE":
        if insurance_allowed is None or isinstance(insurance_allowed, bool) \
                or not isinstance(insurance_allowed, int):
            raise err("ERR_INVALID_ADJUDICATION", "insurance_allowed_cents required")
        if not (0 <= insurance_allowed <= charge["list_price_cents"]):
            raise err("ERR_INVALID_ADJUDICATION", "insurance_allowed_cents out of range")
        charge["insurance_allowed_cents"] = insurance_allowed
    final = finalized_responsibility(pay_type, charge["list_price_cents"],
                                     insurance_allowed if pay_type == "INSURANCE" else None,
                                     charge.get("grant_covered_cents") or 0)
    charge["final_patient_responsibility_cents"] = final
    charge["status"] = "ADJUDICATED"
    bump(charge)
    return object_response(public(charge), 200)


@bp.route("/charges/<rid>/settle", methods=["POST"])
def settle(rid):
    _, role = require_user_context()
    require_role(role, {"BillingClerk"})
    charge = get_or_404("charges", rid)
    body = get_json_body()
    expected = _require_version(body)
    if charge["status"] != "ADJUDICATED":
        raise err("ERR_INVALID_STATE", "Charge not ADJUDICATED")
    if expected != charge["version"]:
        raise err("ERR_STALE_VERSION", "expected_charge_version mismatch")
    charge["status"] = "SETTLED"
    bump(charge)
    if charge.get("grant_id"):
        grant = db.grants.get(charge["grant_id"])
        if grant:
            recompute_grant(grant)
            bump(grant)
    return object_response(public(charge), 200)


@bp.route("/charges/<rid>/void", methods=["POST"])
def void(rid):
    _, role = require_user_context()
    require_role(role, {"BillingClerk"})
    charge = get_or_404("charges", rid)
    if charge["status"] not in ("DRAFT", "ADJUDICATED"):
        raise err("ERR_INVALID_STATE", "Charge not DRAFT or ADJUDICATED")
    charge["status"] = "VOID"
    bump(charge)
    if charge.get("grant_id"):
        grant = db.grants.get(charge["grant_id"])
        if grant:
            recompute_grant(grant)
            bump(grant)
    return object_response(public(charge), 200)
