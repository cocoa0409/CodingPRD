"""FleetAccount endpoints and credit governance."""
from flask import Blueprint, request

from db import store, new_record, touch, new_id
from errors import (ApiError, err_not_found, err_invalid_state)
from middleware import auth, require_fleet_ownership
from response import success
from serializers import serialize_fleet, fleet_mtd
from services.cascades import maybe_reinstate_credit_hold, wall_now
from util import (Field, validate_body, parse_pagination, paginate)

bp = Blueprint("fleets", __name__)

READ_ROLES = ["OpsAdmin", "Dispatcher", "BillingClerk", "FleetManager",
              "WarrantyAdministrator"]
LIST_ROLES = ["OpsAdmin", "Dispatcher", "BillingClerk"]

NON_TERMINAL_CALL_STATES = {
    "RECEIVED", "TRIAGED", "DISPATCHED", "EN_ROUTE", "ON_SITE", "DIAGNOSED",
    "REPAIR_IN_PROGRESS", "REPAIR_COMPLETED", "TOW_IN_PROGRESS", "TOWED",
    "INVOICED", "REOPENED",
}


def _get_fleet(fleet_id):
    fleet = store.fleets.get(fleet_id)
    if fleet is None:
        raise err_not_found("FleetAccount not found")
    return fleet


@bp.route("/roadside/fleet-accounts", methods=["POST"])
def create_fleet():
    auth(["OpsAdmin"])
    vals = validate_body(request.get_json(silent=True), [
        Field("company_name", "string", required=True),
        Field("account_number", "string", required=True),
        Field("billing_email", "string", required=True),
        Field("per_call_authorization_limit_cents", "int", required=True, min_val=0),
        Field("monthly_spend_cap_cents", "int", required=True, min_val=0),
        Field("payment_terms_days", "int", min_val=0),
        Field("rate_card_id", "string", nullable=True),
    ])
    rc_id = vals.get("rate_card_id")
    if rc_id is not None and rc_id not in store.rate_cards:
        raise err_not_found("RateCard not found")
    for f in store.fleets.values():
        if f["account_number"] == vals["account_number"]:
            raise ApiError("ERR_DUPLICATE_VIN",
                           "account_number already exists", 409)
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "company_name": vals["company_name"],
        "account_number": vals["account_number"],
        "billing_email": vals["billing_email"],
        "per_call_authorization_limit_cents": vals["per_call_authorization_limit_cents"],
        "monthly_spend_cap_cents": vals["monthly_spend_cap_cents"],
        "payment_terms_days": vals.get("payment_terms_days", 30),
        "rate_card_id": rc_id,
        "status": "ACTIVE",
        "suspension_reason": "NONE",
    })
    store.fleets[rec["id"]] = rec
    return success(serialize_fleet(rec), status=201)


@bp.route("/roadside/fleet-accounts/<fleetAccountId>", methods=["GET"])
def get_fleet(fleetAccountId):
    uid, role = auth(READ_ROLES)
    fleet = _get_fleet(fleetAccountId)
    if role == "FleetManager":
        require_fleet_ownership(uid, fleet["id"])
    return success(serialize_fleet(fleet))


@bp.route("/roadside/fleet-accounts", methods=["GET"])
def list_fleets():
    auth(LIST_ROLES)
    limit, offset = parse_pagination(request.args)
    status_f = request.args.get("status")
    rc_f = request.args.get("rate_card_id")
    items = sorted(store.fleets.values(), key=lambda r: r["_seq"])
    if status_f is not None:
        items = [f for f in items if f["status"] == status_f]
    if rc_f is not None:
        items = [f for f in items if f.get("rate_card_id") == rc_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize_fleet(f) for f in page], response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/fleet-accounts/<fleetAccountId>", methods=["PATCH"])
def patch_fleet(fleetAccountId):
    auth(["OpsAdmin"])
    fleet = _get_fleet(fleetAccountId)
    vals = validate_body(request.get_json(silent=True), [
        Field("per_call_authorization_limit_cents", "int", min_val=0),
        Field("monthly_spend_cap_cents", "int", min_val=0),
        Field("payment_terms_days", "int", min_val=0),
        Field("rate_card_id", "string", nullable=True),
    ])
    if "rate_card_id" in vals and vals["rate_card_id"] is not None:
        if vals["rate_card_id"] not in store.rate_cards:
            raise err_not_found("RateCard not found")
    for k, v in vals.items():
        fleet[k] = v
    touch(fleet, wall_now())
    return success(serialize_fleet(fleet))


@bp.route("/roadside/fleet-accounts/<fleetAccountId>/suspend", methods=["POST"])
def suspend_fleet(fleetAccountId):
    auth(["OpsAdmin"])
    fleet = _get_fleet(fleetAccountId)
    if fleet["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE fleet can be suspended")
    fleet["status"] = "SUSPENDED"
    fleet["suspension_reason"] = "ADMIN"
    touch(fleet, wall_now())
    return success(serialize_fleet(fleet))


@bp.route("/roadside/fleet-accounts/<fleetAccountId>/reinstate", methods=["POST"])
def reinstate_fleet(fleetAccountId):
    auth(["OpsAdmin"])
    fleet = _get_fleet(fleetAccountId)
    if fleet["status"] != "SUSPENDED":
        raise err_invalid_state("Only a SUSPENDED fleet can be reinstated")
    fleet["status"] = "ACTIVE"
    fleet["suspension_reason"] = "NONE"
    touch(fleet, wall_now())
    return success(serialize_fleet(fleet))


@bp.route("/roadside/fleet-accounts/<fleetAccountId>/close", methods=["POST"])
def close_fleet(fleetAccountId):
    auth(["OpsAdmin"])
    fleet = _get_fleet(fleetAccountId)
    if fleet["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err_invalid_state("Fleet is already CLOSED")
    for call in store.service_calls.values():
        if (call.get("fleet_account_id") == fleet["id"]
                and call["status"] in NON_TERMINAL_CALL_STATES):
            raise ApiError("ERR_FLEET_HAS_OPEN_CALLS",
                           "Fleet has service calls in a non-terminal status", 409)
    fleet["status"] = "CLOSED"
    touch(fleet, wall_now())
    return success(serialize_fleet(fleet))


@bp.route("/roadside/fleet-accounts/<fleetAccountId>/spend-adjustments",
          methods=["POST"])
def spend_adjustment(fleetAccountId):
    auth(["OpsAdmin", "BillingClerk"])
    fleet = _get_fleet(fleetAccountId)
    vals = validate_body(request.get_json(silent=True), [
        Field("amount_cents", "int", required=True),
        Field("reason", "string", required=True),
    ])
    rec = {
        "id": new_id(),
        "_seq": next(store.seq),
        "fleet_account_id": fleet["id"],
        "amount_cents": vals["amount_cents"],
        "reason": vals["reason"],
        "posted_at": store.clock,
    }
    store.spend_adjustments[rec["id"]] = rec
    touch(fleet, wall_now())
    maybe_reinstate_credit_hold(fleet)
    return success(serialize_fleet(fleet), status=201)
