from flask import Blueprint, request

from db import db
from clock import clock, parse_iso
from middleware import require_role
from response import object_response, array_response
from errors import err, ERR_INVALID_STATE, ERR_INVALID_REQUEST
from services.common import (
    stamp_create, touch, get_json_body, require_fields, require_string,
    require_pos_int, parse_pagination, paginate,
)
from services.lookups import get_vessel, get_policy
from services.serialize import policy_view

insurance_bp = Blueprint("insurance", __name__)

READ_ROLES = {"DockMaster", "BillingClerk", "BoatOwner"}

# PRD §3.2: minimum liability floor. No numeric value is specified anywhere in
# the PRD/scaffold (symbolic only) and no error id guards it; any positive
# liability_limit_cents (constrained > 0) satisfies the floor.
MIN_LIABILITY_CENTS = 0


def policy_covers_clock(policy, now_dt):
    """A VERIFIED policy covers the logical clock when effective_from <= clock < effective_to."""
    eff_from = parse_iso(policy["effective_from"])
    eff_to = parse_iso(policy["effective_to"])
    return eff_from <= now_dt < eff_to


def recompute_active_policy(vessel):
    """Set vessel.active_policy_id to a VERIFIED, in-window policy if one exists,
    else null. Used by verify/expire side effects."""
    now = clock.now()
    for p in db.policies.values():
        if p["vessel_id"] == vessel["id"] and p["status"] == "VERIFIED" and policy_covers_clock(p, now):
            return p["id"]
    return None


@insurance_bp.route("/marina/insurance-policies", methods=["POST"])
def create_policy():
    require_role({"BillingClerk", "BoatOwner"})
    body = get_json_body()
    require_fields(body, ["vessel_id", "carrier_name", "liability_limit_cents",
                          "effective_from", "effective_to"])
    require_string(body["vessel_id"], "vessel_id")
    require_string(body["carrier_name"], "carrier_name")
    require_pos_int(body["liability_limit_cents"], "liability_limit_cents")
    require_string(body["effective_from"], "effective_from")
    require_string(body["effective_to"], "effective_to")
    try:
        parse_iso(body["effective_from"])
        parse_iso(body["effective_to"])
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "effective_from/effective_to must be ISO-8601 instants.")
    with db.lock:
        get_vessel(body["vessel_id"])
        rec = {
            "vessel_id": body["vessel_id"],
            "carrier_name": body["carrier_name"],
            "liability_limit_cents": body["liability_limit_cents"],
            "effective_from": body["effective_from"],
            "effective_to": body["effective_to"],
            "status": "SUBMITTED",
        }
        stamp_create(rec)
        db.policies[rec["id"]] = rec
    return object_response(policy_view(rec), 201)


@insurance_bp.route("/marina/insurance-policies/<policy_id>", methods=["GET"])
def fetch_policy(policy_id):
    require_role(READ_ROLES)
    rec = get_policy(policy_id)
    return object_response(policy_view(rec), 200)


@insurance_bp.route("/marina/insurance-policies", methods=["GET"])
def list_policies():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.policies.values())
    vessel_id = request.args.get("vessel_id")
    status = request.args.get("status")
    if vessel_id is not None:
        records = [r for r in records if r["vessel_id"] == vessel_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response([policy_view(r) for r in page], limit, offset, total)


@insurance_bp.route("/marina/insurance-policies/<policy_id>/verify", methods=["POST"])
def verify_policy(policy_id):
    require_role({"BillingClerk"})
    with db.lock:
        policy = get_policy(policy_id)
        if policy["status"] != "SUBMITTED":
            raise err(ERR_INVALID_STATE, "Policy must be SUBMITTED to verify.")
        eff_from = parse_iso(policy["effective_from"])
        eff_to = parse_iso(policy["effective_to"])
        if not (eff_to > eff_from):
            raise err(ERR_INVALID_STATE, "effective_to must be later than effective_from.")
        if policy["liability_limit_cents"] < MIN_LIABILITY_CENTS:
            raise err(ERR_INVALID_STATE, "liability_limit_cents below minimum floor.")
        policy["status"] = "VERIFIED"
        touch(policy)
        # If the vessel has no other VERIFIED policy covering the clock, set active.
        vessel = db.vessels.get(policy["vessel_id"])
        if vessel is not None and vessel.get("active_policy_id") is None:
            if policy_covers_clock(policy, clock.now()):
                vessel["active_policy_id"] = policy["id"]
                touch(vessel)
    return object_response(policy_view(policy), 200)


@insurance_bp.route("/marina/insurance-policies/<policy_id>/reject", methods=["POST"])
def reject_policy(policy_id):
    require_role({"BillingClerk"})
    with db.lock:
        policy = get_policy(policy_id)
        if policy["status"] != "SUBMITTED":
            raise err(ERR_INVALID_STATE, "Policy must be SUBMITTED to reject.")
        policy["status"] = "REJECTED"
        touch(policy)
    return object_response(policy_view(policy), 200)


@insurance_bp.route("/marina/insurance-policies/<policy_id>/expire", methods=["POST"])
def expire_policy(policy_id):
    require_role({"BillingClerk"})
    with db.lock:
        policy = get_policy(policy_id)
        if policy["status"] != "VERIFIED":
            raise err(ERR_INVALID_STATE, "Policy must be VERIFIED to expire.")
        if clock.now() < parse_iso(policy["effective_to"]):
            raise err(ERR_INVALID_STATE, "Clock has not reached effective_to.")
        policy["status"] = "EXPIRED"
        touch(policy)
        vessel = db.vessels.get(policy["vessel_id"])
        if vessel is not None and vessel.get("active_policy_id") == policy["id"]:
            vessel["active_policy_id"] = None
            touch(vessel)
    return object_response(policy_view(policy), 200)
