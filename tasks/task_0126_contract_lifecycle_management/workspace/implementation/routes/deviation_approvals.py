"""DeviationApproval endpoints (PRD §3.4)."""

from flask import Blueprint, g, request

from common import (bump, get_json_body, parse_pagination, paginate,
                    require_field, serialize, stamp_new)
from db import db
from errors import (contract_not_found, deviation_stale, invalid_state,
                    reference_not_found, resource_not_found, self_approval)
from middleware import require_roles
from response import success_list, success_object
from services.audit import append_audit

bp = Blueprint("deviation_approvals", __name__)

DECISION_ENUM = {"GRANT", "DENY"}


@bp.route("/contracts/<cid>/deviation-approvals", methods=["POST"])
@require_roles("ContractManager")
def request_deviation(cid):
    contract = db.contracts.get(cid)
    if not contract:
        raise contract_not_found("Contract not found.")

    body = get_json_body()
    contract_version_id = require_field(body, "contract_version_id", types=str)
    clause_template_id = require_field(body, "clause_template_id", types=str)
    justification = require_field(body, "justification", types=str)

    # FK validation (priority 4): version must belong to this contract; clause
    # must belong to the contract's organization.
    version = db.contract_versions.get(contract_version_id)
    if not version or version.get("contract_id") != cid:
        raise reference_not_found(
            "contract_version_id does not reference a version of this contract.")
    ct = db.clause_templates.get(clause_template_id)
    if not ct or ct.get("organization_id") != contract.get("organization_id"):
        raise reference_not_found(
            "clause_template_id does not reference a clause of this organization.")

    dev = {
        "contract_id": cid,
        "contract_version_id": contract_version_id,
        "clause_template_id": clause_template_id,
        "justification": justification,
        "decided_by_user_id": None,
        "status": "PENDING",
    }
    stamp_new(dev)
    db.deviation_approvals[dev["id"]] = dev
    return success_object(serialize(dev), status=201)


@bp.route("/contracts/<cid>/deviation-approvals", methods=["GET"])
@require_roles("ContractManager", "RiskOfficer")
def list_contract_deviations(cid):
    contract = db.contracts.get(cid)
    if not contract:
        raise contract_not_found("Contract not found.")
    limit, offset = parse_pagination()
    rows = [d for d in db.deviation_approvals.values() if d.get("contract_id") == cid]
    status = request.args.get("status")
    contract_version_id = request.args.get("contract_version_id")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    if contract_version_id is not None:
        rows = [r for r in rows if r.get("contract_version_id") == contract_version_id]
    page, total = paginate(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/deviation-approvals/<did>/decide", methods=["POST"])
@require_roles("RiskOfficer")
def decide(did):
    dev = db.deviation_approvals.get(did)
    if not dev:
        raise resource_not_found("Deviation approval not found.")

    body = get_json_body()
    decision = require_field(body, "decision", types=str, enum=DECISION_ENUM)

    # State (priority 6): only a PENDING deviation can be decided.
    if dev.get("status") != "PENDING":
        raise invalid_state("Deviation approval is not PENDING.")

    contract = db.contracts.get(dev.get("contract_id"))

    if decision == "GRANT":
        # Staleness (priority 10): contract_version_id must still be current.
        if contract is None or dev.get("contract_version_id") != contract.get("current_version_id"):
            raise deviation_stale("Covered version is no longer current.")
        # Segregation of duties (priority 8): caller != drafter.
        if contract is not None and g.user_id == contract.get("drafter_user_id"):
            raise self_approval("Caller is the contract drafter.")

        dev["status"] = "GRANTED"
        dev["decided_by_user_id"] = g.user_id
        append_audit(dev.get("contract_id"), "DEVIATION_GRANTED",
                     actor_user_id=g.user_id, detail="Deviation granted.")
        bump(dev)
    else:  # DENY
        dev["status"] = "DENIED"
        dev["decided_by_user_id"] = g.user_id
        append_audit(dev.get("contract_id"), "DEVIATION_DENIED",
                     actor_user_id=g.user_id, detail="Deviation denied.")
        bump(dev)

    return success_object(serialize(dev), status=200)


@bp.route("/deviation-approvals/<did>", methods=["GET"])
@require_roles("ContractManager", "RiskOfficer")
def get_deviation(did):
    dev = db.deviation_approvals.get(did)
    if not dev:
        raise resource_not_found("Deviation approval not found.")
    return success_object(serialize(dev), status=200)


@bp.route("/deviation-approvals", methods=["GET"])
@require_roles("ContractManager", "RiskOfficer")
def list_deviations():
    limit, offset = parse_pagination()
    rows = list(db.deviation_approvals.values())
    contract_id = request.args.get("contract_id")
    contract_version_id = request.args.get("contract_version_id")
    clause_template_id = request.args.get("clause_template_id")
    status = request.args.get("status")
    if contract_id is not None:
        rows = [r for r in rows if r.get("contract_id") == contract_id]
    if contract_version_id is not None:
        rows = [r for r in rows if r.get("contract_version_id") == contract_version_id]
    if clause_template_id is not None:
        rows = [r for r in rows if r.get("clause_template_id") == clause_template_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    page, total = paginate(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)
