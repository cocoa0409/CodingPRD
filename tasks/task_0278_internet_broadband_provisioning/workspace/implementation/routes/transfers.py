"""TransferRequest endpoints (PRD §3.9)."""
from flask import Blueprint, request

import db
from db import touch
from errors import err
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.helpers import (get_json_body, lookup, require_fields,
                              require_int, paginate, sorted_by_created,
                              check_owner)
from services.serialize import public, public_list
from services import domain

bp = Blueprint("transfers", __name__)


@bp.route("/transfer-requests", methods=["POST"])
def create_transfer_request():
    uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent"})
    body = get_json_body()
    require_fields(body, ["account_id", "to_service_address_id", "to_plan_id"])
    account = lookup(db.accounts, body["account_id"])
    lookup(db.service_addresses, body["to_service_address_id"])
    lookup(db.service_plans, body["to_plan_id"])
    check_owner(role, uid, account)
    waive_etf = True
    if "waive_etf" in body and body["waive_etf"] is not None:
        if not isinstance(body["waive_etf"], bool):
            err("ERR_INVALID_REQUEST", "waive_etf must be a boolean.")
        waive_etf = body["waive_etf"]
    rec = db.make_record({
        "account_id": account["id"],
        "to_service_address_id": body["to_service_address_id"],
        "to_plan_id": body["to_plan_id"],
        "waive_etf": waive_etf,
        "status": "REQUESTED",
    }, versioned=db.VERSIONED)
    db.transfer_requests[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.route("/transfer-requests/<rid>", methods=["GET"])
def get_transfer_request(rid):
    uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps"})
    rec = lookup(db.transfer_requests, rid)
    account = db.accounts.get(rec["account_id"])
    if account is not None:
        check_owner(role, uid, account)
    return object_response(public(rec), 200)


@bp.route("/transfer-requests", methods=["GET"])
def list_transfer_requests():
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps"})
    recs = list(db.transfer_requests.values())
    for f in ("account_id", "to_service_address_id", "to_plan_id", "status"):
        val = request.args.get(f)
        if val is not None:
            recs = [r for r in recs if r.get(f) == val]
    recs = sorted_by_created(recs)
    window, limit, offset, total, has_more = paginate(recs)
    return array_response(public_list(window), limit, offset, total, has_more, 200)


@bp.route("/transfer-requests/<rid>/approve", methods=["POST"])
def approve_transfer(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    get_json_body()
    rec = lookup(db.transfer_requests, rid)
    if rec["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", "Transfer must be REQUESTED to approve.")
    # Serviceability then speed gates against the destination (§2.5).
    address = db.service_addresses.get(rec["to_service_address_id"])
    plan = db.service_plans.get(rec["to_plan_id"])
    if address is None or address["coverage_status"] != "SERVICEABLE":
        err("ERR_ADDRESS_NOT_SERVICEABLE", "Destination address is not SERVICEABLE.")
    if plan is not None and plan["download_mbps"] > address["max_serviceable_mbps"]:
        err("ERR_PLAN_EXCEEDS_SERVICEABLE_SPEED",
            "Destination plan exceeds the address serviceable speed.")
    rec["status"] = "APPROVED"
    touch(rec)
    return object_response(public(rec), 200)


@bp.route("/transfer-requests/<rid>/complete", methods=["POST"])
def complete_transfer(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    rec = lookup(db.transfer_requests, rid)
    body = get_json_body()
    require_fields(body, ["expected_account_version"])
    expected = require_int(body, "expected_account_version")
    account = lookup(db.accounts, rec["account_id"])
    # State: request must be APPROVED.
    if rec["status"] != "APPROVED":
        err("ERR_INVALID_STATE", "Transfer must be APPROVED to complete.")
    # Account must be ACTIVE.
    if account["status"] != "ACTIVE":
        err("ERR_ACCOUNT_NOT_ACTIVE", "Account must be ACTIVE to complete a transfer.")
    # OCC.
    if expected != account["version"]:
        err("ERR_STALE_ACCOUNT_VERSION",
            "expected_account_version does not match the account version.")
    rec["status"] = "COMPLETED"
    touch(rec)
    domain.complete_transfer_cascade(account, rec)
    touch(account)  # increments Account.version by 1.
    return object_response(public(rec), 200)


@bp.route("/transfer-requests/<rid>/reject", methods=["POST"])
def reject_transfer(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    get_json_body()
    rec = lookup(db.transfer_requests, rid)
    if rec["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", "Transfer must be REQUESTED to reject.")
    rec["status"] = "REJECTED"
    touch(rec)
    return object_response(public(rec), 200)
