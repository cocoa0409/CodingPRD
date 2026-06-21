"""ApprovalWorkflow + ApprovalStep endpoints (PRD §3.3)."""

from flask import Blueprint, g, request

from common import (bump, get_json_body, new_id, parse_pagination, paginate,
                    require_field, serialize)
from db import db
from errors import (invalid_state, mandatory_clause_missing, resource_not_found,
                    self_approval)
from middleware import require_roles
from response import success_list, success_object
from services.contract_logic import (current_version, workflow_reached_approved,
                                      workflow_reached_rejected)
from util import format_iso_millis

bp = Blueprint("approval_workflows", __name__)

DECISION_ENUM = {"APPROVE", "REJECT"}


@bp.route("/approval-workflows/<wid>", methods=["GET"])
@require_roles("ContractManager", "ContractApprover", "RiskOfficer")
def get_workflow(wid):
    wf = db.approval_workflows.get(wid)
    if not wf:
        raise resource_not_found("Approval workflow not found.")
    return success_object(serialize(wf), status=200)


@bp.route("/approval-workflows", methods=["GET"])
@require_roles("ContractManager", "ContractApprover", "RiskOfficer")
def list_workflows():
    limit, offset = parse_pagination()
    rows = list(db.approval_workflows.values())
    contract_id = request.args.get("contract_id")
    pinned_version_id = request.args.get("pinned_version_id")
    status = request.args.get("status")
    if contract_id is not None:
        rows = [r for r in rows if r.get("contract_id") == contract_id]
    if pinned_version_id is not None:
        rows = [r for r in rows if r.get("pinned_version_id") == pinned_version_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    page, total = paginate(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/approval-workflows/<wid>/steps", methods=["POST"])
@require_roles("ContractApprover")
def record_step(wid):
    wf = db.approval_workflows.get(wid)
    if not wf:
        raise resource_not_found("Approval workflow not found.")

    body = get_json_body()
    decision = require_field(body, "decision", types=str, enum=DECISION_ENUM)
    comment = body.get("comment")
    if comment is not None and not isinstance(comment, str):
        from errors import invalid_request
        raise invalid_request("comment must be a string.")

    contract = db.contracts.get(wf.get("contract_id"))

    # State (priority 6): decisions only on a PENDING workflow.
    if wf.get("status") != "PENDING":
        raise invalid_state("Workflow is not PENDING.")

    # Segregation of duties (priority 8) — evaluated before the mandatory-clause
    # check (PRD §3.3). Caller must differ from drafter and version author.
    version = current_version(contract) if contract else None
    drafter = contract.get("drafter_user_id") if contract else None
    author = version.get("authored_by_user_id") if version else None
    if g.user_id == drafter or (author is not None and g.user_id == author):
        raise self_approval("Caller is the drafter or version author.")

    # Record the ApprovalStep (write-once: id + created_at only).
    step = {
        "id": new_id(),
        "approval_workflow_id": wid,
        "approver_user_id": g.user_id,
        "decision": decision,
        "comment": comment,
        "created_at": format_iso_millis(db.clock),
    }

    if decision == "APPROVE":
        new_count = int(wf.get("approvals_received", 0)) + 1
        reaches_quorum = new_count >= int(wf.get("required_approver_count", 1))

        # Mandatory-clause check (priority 9) only on the quorum-reaching APPROVE
        # (PRD §3.3). Checked AFTER segregation of duties.
        if reaches_quorum and _missing_mandatory_clause(contract, version):
            raise mandatory_clause_missing(
                "Current version omits a mandatory clause required by the template.")

        # Commit the step and the count.
        wf["approvals_received"] = new_count
        bump(wf)
        db.approval_steps[step["id"]] = step

        if reaches_quorum:
            # pinned_version_id must still be current (else it would be VOIDED).
            if (
                contract is not None
                and wf.get("pinned_version_id") == contract.get("current_version_id")
            ):
                workflow_reached_approved(wf, contract)
    else:  # REJECT
        db.approval_steps[step["id"]] = step
        if contract is not None:
            workflow_reached_rejected(wf, contract)
        else:
            wf["status"] = "REJECTED"
            bump(wf)

    return success_object(serialize(step), status=201)


@bp.route("/approval-workflows/<wid>/steps", methods=["GET"])
@require_roles("ContractManager", "ContractApprover", "RiskOfficer")
def list_steps(wid):
    wf = db.approval_workflows.get(wid)
    if not wf:
        raise resource_not_found("Approval workflow not found.")
    limit, offset = parse_pagination()
    rows = [s for s in db.approval_steps.values()
            if s.get("approval_workflow_id") == wid]
    page, total = paginate(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


def _missing_mandatory_clause(contract, version):
    """True if the version omits any mandatory clause template required by the
    contract's template (PRD §3.3, §1.4 priority 9)."""
    if contract is None or version is None:
        return False
    template = db.contract_templates.get(contract.get("contract_template_id"))
    if not template:
        return False
    present = {c.get("clause_template_id") for c in (version.get("clauses") or [])}
    for ct_id in template.get("clause_template_ids", []):
        ct = db.clause_templates.get(ct_id)
        if ct and ct.get("is_mandatory") and ct_id not in present:
            return True
    return False
