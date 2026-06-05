"""Obligation endpoints (PRD §3.6)."""

from flask import Blueprint, request

from common import (bump, get_json_body, parse_pagination, paginate,
                    require_field, serialize, stamp_new)
from db import db
from errors import contract_not_found, invalid_state, resource_not_found
from middleware import require_roles
from response import success_list, success_object
from util import format_iso_millis, parse_iso8601

bp = Blueprint("obligations", __name__)

PARTY_ENUM = {"INTERNAL", "COUNTERPARTY"}


@bp.route("/contracts/<cid>/obligations", methods=["POST"])
@require_roles("ContractManager")
def create_obligation(cid):
    contract = db.contracts.get(cid)
    if not contract:
        raise contract_not_found("Contract not found.")

    body = get_json_body()
    description = require_field(body, "description", types=str)
    owner_party = require_field(body, "owner_party", types=str, enum=PARTY_ENUM)
    due_date_raw = require_field(body, "due_date", types=str)
    due_date = parse_iso8601(due_date_raw, field="due_date")

    obligation = {
        "contract_id": cid,
        "description": description,
        "owner_party": owner_party,
        "due_date": format_iso_millis(due_date),
        "completed_at": None,
        "status": "OPEN",
    }
    stamp_new(obligation)
    db.obligations[obligation["id"]] = obligation
    return success_object(serialize(obligation), status=201)


@bp.route("/contracts/<cid>/obligations", methods=["GET"])
@require_roles("ContractManager", "ContractApprover", "RiskOfficer")
def list_obligations(cid):
    contract = db.contracts.get(cid)
    if not contract:
        raise contract_not_found("Contract not found.")
    limit, offset = parse_pagination()
    rows = [o for o in db.obligations.values() if o.get("contract_id") == cid]
    status = request.args.get("status")
    owner_party = request.args.get("owner_party")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if owner_party is not None:
        rows = [r for r in rows if r.get("owner_party") == owner_party]
    page, total = paginate(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/obligations/<oid>/fulfill", methods=["POST"])
@require_roles("ContractManager")
def fulfill(oid):
    ob = db.obligations.get(oid)
    if not ob:
        raise resource_not_found("Obligation not found.")
    contract = db.contracts.get(ob.get("contract_id"))

    # Fulfill only while OPEN and parent contract ACTIVE (PRD §3.6).
    if ob.get("status") != "OPEN" or (contract and contract.get("status") != "ACTIVE"):
        raise invalid_state("Obligation cannot be fulfilled in this state.")

    ob["completed_at"] = format_iso_millis(db.clock)
    ob["status"] = "FULFILLED"
    bump(ob)
    return success_object(serialize(ob), status=200)


@bp.route("/obligations/<oid>/waive", methods=["POST"])
@require_roles("ContractManager")
def waive(oid):
    ob = db.obligations.get(oid)
    if not ob:
        raise resource_not_found("Obligation not found.")

    # Waive is defined from OPEN (PRD §3.6 / §1.2).
    if ob.get("status") != "OPEN":
        raise invalid_state("Only an OPEN obligation can be waived.")

    ob["status"] = "WAIVED"
    bump(ob)
    return success_object(serialize(ob), status=200)
