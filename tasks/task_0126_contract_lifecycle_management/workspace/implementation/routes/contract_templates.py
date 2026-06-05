"""ContractTemplate endpoints (PRD §3.1)."""

from flask import Blueprint, request

from common import (bump, get_json_body, optional_bool, optional_int,
                    parse_pagination, paginate, require_field, serialize,
                    stamp_new)
from db import db
from errors import (invalid_request, invalid_state, reference_not_found,
                    resource_not_found, template_in_use, validation_range)
from middleware import require_roles
from response import success_list, success_object

bp = Blueprint("contract_templates", __name__)


@bp.route("/contract-templates", methods=["POST"])
@require_roles("ClauseLibrarian")
def create_contract_template():
    body = get_json_body()
    org_id = require_field(body, "organization_id", types=str)
    name = require_field(body, "name", types=str)
    clause_ids = require_field(body, "clause_template_ids", types=list)
    default_term_months = optional_int(body, "default_term_months", default=12)
    auto_renew_default = optional_bool(body, "auto_renew_default", default=False)

    if not all(isinstance(x, str) for x in clause_ids):
        raise invalid_request("clause_template_ids must be a list of strings.")

    # FK existence (priority 4).
    if org_id not in db.organizations:
        raise reference_not_found("organization_id does not reference an organization.")

    if default_term_months <= 0:
        raise validation_range("default_term_months must be > 0.")

    # Each clause must belong to the same org and be ACTIVE at create time
    # (PRD §3.1; else ERR_REFERENCE_NOT_FOUND).
    for ct_id in clause_ids:
        ct = db.clause_templates.get(ct_id)
        if (
            not ct
            or ct.get("organization_id") != org_id
            or ct.get("status") != "ACTIVE"
        ):
            raise reference_not_found(
                "clause_template_ids must reference ACTIVE clauses of this organization.")

    template = {
        "organization_id": org_id,
        "name": name,
        "clause_template_ids": list(clause_ids),
        "default_term_months": default_term_months,
        "auto_renew_default": auto_renew_default,
        "status": "ACTIVE",
    }
    stamp_new(template)
    db.contract_templates[template["id"]] = template
    return success_object(serialize(template), status=201)


@bp.route("/contract-templates/<tid>", methods=["GET"])
@require_roles("ClauseLibrarian", "ContractManager", "ContractApprover", "RiskOfficer")
def get_contract_template(tid):
    template = db.contract_templates.get(tid)
    if not template:
        raise resource_not_found("Contract template not found.")
    return success_object(serialize(template), status=200)


@bp.route("/contract-templates", methods=["GET"])
@require_roles("ClauseLibrarian", "ContractManager", "ContractApprover", "RiskOfficer")
def list_contract_templates():
    limit, offset = parse_pagination()
    org_id = request.args.get("organization_id")
    status = request.args.get("status")

    rows = list(db.contract_templates.values())
    if org_id is not None:
        rows = [r for r in rows if r.get("organization_id") == org_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]

    page, total = paginate(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/contract-templates/<tid>/retire", methods=["POST"])
@require_roles("ClauseLibrarian")
def retire_contract_template(tid):
    template = db.contract_templates.get(tid)
    if not template:
        raise resource_not_found("Contract template not found.")
    if template.get("status") != "ACTIVE":
        raise invalid_state("Only an ACTIVE contract template can be retired.")

    # No working-state contract may reference it (PRD §3.1; else ERR_TEMPLATE_IN_USE).
    working = {"DRAFT", "UNDER_REVIEW", "REDLINING"}
    for contract in db.contracts.values():
        if (
            contract.get("contract_template_id") == tid
            and contract.get("status") in working
        ):
            raise template_in_use(
                "Contract template is referenced by a working contract.")

    template["status"] = "RETIRED"
    bump(template)
    return success_object(serialize(template), status=200)
