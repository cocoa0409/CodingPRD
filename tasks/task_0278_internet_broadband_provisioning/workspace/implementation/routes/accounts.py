"""Account endpoints (PRD §3.2, §3.3, §3.8, §3.11)."""
from flask import Blueprint, request

import db
from db import touch
from errors import err
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.helpers import (get_json_body, lookup, require_fields,
                              require_positive_int, require_int, paginate,
                              sorted_by_created, check_owner)
from services.serialize import public, public_list
from services import domain

bp = Blueprint("accounts", __name__)


def _check_occ(account, body):
    """OCC guard (PRD §2.11): expected_account_version must match version."""
    require_fields(body, ["expected_account_version"])
    expected = require_int(body, "expected_account_version")
    if expected != account["version"]:
        err("ERR_STALE_ACCOUNT_VERSION",
            "expected_account_version does not match the account version.")


@bp.route("/accounts", methods=["POST"])
def create_account():
    uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent"})
    body = get_json_body()
    require_fields(body, ["service_address_id", "plan_id", "customer_user_id"])
    # Existence: body FKs.
    lookup(db.service_addresses, body["service_address_id"])
    lookup(db.service_plans, body["plan_id"])
    if not isinstance(body["customer_user_id"], str) or body["customer_user_id"] == "":
        err("ERR_INVALID_REQUEST", "customer_user_id must be a non-empty string.")
    # A Customer may create only their own account (owns it via customer_user_id).
    if role == "Customer" and body["customer_user_id"] != uid:
        err("ERR_NOT_ACCOUNT_OWNER",
            "A Customer may only create an account they own.")
    rec = db.make_record({
        "service_address_id": body["service_address_id"],
        "plan_id": body["plan_id"],
        "customer_user_id": body["customer_user_id"],
        "status": "PENDING",
        "service_state": "PROVISIONING",
        "contract_start_iso": None,
        "credit_balance_cents": 0,
        "equipment_unit_id": None,
    }, versioned=db.VERSIONED)
    db.accounts[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.route("/accounts/<rid>", methods=["GET"])
def get_account(rid):
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps", "Dispatcher"})
    rec = lookup(db.accounts, rid)
    check_owner(role, _uid, rec)
    return object_response(public(rec), 200)


@bp.route("/accounts", methods=["GET"])
def list_accounts():
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent", "NetworkOps", "Dispatcher"})
    recs = list(db.accounts.values())
    for f in ("service_address_id", "plan_id", "equipment_unit_id", "status"):
        val = request.args.get(f)
        if val is not None:
            recs = [r for r in recs if r.get(f) == val]
    recs = sorted_by_created(recs)
    window, limit, offset, total, has_more = paginate(recs)
    return array_response(public_list(window), limit, offset, total, has_more, 200)


@bp.route("/accounts/<rid>/change-plan", methods=["POST"])
def change_plan(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    rec = lookup(db.accounts, rid)
    body = get_json_body()
    require_fields(body, ["new_plan_id", "expected_account_version"])
    new_plan = lookup(db.service_plans, body["new_plan_id"])
    # State: change-plan applies to an ACTIVE account (§3.3).
    if rec["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Account must be ACTIVE to change its plan.")
    # Speed gate on the account's existing address (§2.5).
    address = db.service_addresses.get(rec["service_address_id"])
    if address is not None and new_plan["download_mbps"] > address["max_serviceable_mbps"]:
        err("ERR_PLAN_EXCEEDS_SERVICEABLE_SPEED",
            "New plan download speed exceeds the address serviceable ceiling.")
    # OCC last in the domain band.
    _check_occ(rec, body)
    rec["plan_id"] = body["new_plan_id"]
    touch(rec)
    return object_response(public(rec), 200)


@bp.route("/accounts/<rid>/suspend", methods=["POST"])
def suspend(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    get_json_body()
    rec = lookup(db.accounts, rid)
    if rec["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Account must be ACTIVE to suspend.")
    rec["status"] = "SUSPENDED"
    rec["service_state"] = "OFFLINE"
    touch(rec)
    return object_response(public(rec), 200)


@bp.route("/accounts/<rid>/resume", methods=["POST"])
def resume(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    get_json_body()
    rec = lookup(db.accounts, rid)
    if rec["status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", "Account must be SUSPENDED to resume.")
    rec["status"] = "ACTIVE"
    # ONLINE unless the open cycle is THROTTLED (§3.3).
    cycle = domain.open_cycle_for_account(rec["id"])
    if cycle is not None and cycle["throttle_state"] == "THROTTLED":
        rec["service_state"] = "THROTTLED"
    else:
        rec["service_state"] = "ONLINE"
    touch(rec)
    return object_response(public(rec), 200)


@bp.route("/accounts/<rid>/restore-speed", methods=["POST"])
def restore_speed(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    get_json_body()
    rec = lookup(db.accounts, rid)
    cycle = domain.open_cycle_for_account(rec["id"])
    if cycle is None or cycle["throttle_state"] != "THROTTLED":
        err("ERR_INVALID_STATE", "Open cycle is not THROTTLED.")
    cycle["throttle_state"] = "UNCAPPED"
    touch(cycle)
    if rec["status"] == "ACTIVE":
        rec["service_state"] = "ONLINE"
        touch(rec)
    return object_response(public(cycle), 200)


@bp.route("/accounts/<rid>/disconnect", methods=["POST"])
def disconnect(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    rec = lookup(db.accounts, rid)
    body = get_json_body()
    require_fields(body, ["expected_account_version"])
    # State: ACTIVE or SUSPENDED.
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        err("ERR_INVALID_STATE", "Account must be ACTIVE or SUSPENDED to disconnect.")
    _check_occ(rec, body)
    domain.disconnect_account(rec)
    touch(rec)  # increments Account.version by 1.
    return object_response(public(rec), 200)


@bp.route("/accounts/<rid>/credits", methods=["POST"])
def issue_goodwill_credit(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent", "NetworkOps"})
    rec = lookup(db.accounts, rid)
    body = get_json_body()
    require_fields(body, ["amount_cents"])
    amount = require_positive_int(body, "amount_cents")
    credit = domain.emit_credit(rec["id"], "GOODWILL", None, amount)
    return object_response(public(credit), 201)
