"""ClauseTemplate library endpoints (PRD §3.1)."""

from flask import Blueprint, request

from common import (bump, get_json_body, optional_bool, parse_pagination,
                    paginate, require_field, require_int, serialize, stamp_new)
from db import db
from errors import (clause_in_use, duplicate_clause_key, invalid_state,
                    reference_not_found, resource_not_found, validation_range)
from middleware import require_roles
from response import success_list, success_object

bp = Blueprint("clause_templates", __name__)

CATEGORIES = {"LIABILITY", "INDEMNITY", "TERMINATION", "PAYMENT",
              "CONFIDENTIALITY", "OTHER"}


@bp.route("/clause-templates", methods=["POST"])
@require_roles("ClauseLibrarian")
def create_clause_template():
    body = get_json_body()
    org_id = require_field(body, "organization_id", types=str)
    clause_key = require_field(body, "clause_key", types=str)
    category = require_field(body, "category", types=str, enum=CATEGORIES)
    standard_text = require_field(body, "standard_text", types=str)
    risk_weight = require_int(body, "risk_weight")
    is_mandatory = optional_bool(body, "is_mandatory", default=False)

    # FK existence (priority 4).
    if org_id not in db.organizations:
        raise reference_not_found("organization_id does not reference an organization.")

    # Range check (priority 5): risk_weight in [0,40].
    if risk_weight < 0 or risk_weight > 40:
        raise validation_range("risk_weight must be in [0,40].")

    # clause_key uniqueness among ACTIVE clauses of the same org, case-sensitive
    # (priority 15).
    for ct in db.clause_templates.values():
        if (
            ct.get("organization_id") == org_id
            and ct.get("status") == "ACTIVE"
            and ct.get("clause_key") == clause_key
        ):
            raise duplicate_clause_key(
                "clause_key already used by an active clause in this organization.")

    ct = {
        "organization_id": org_id,
        "clause_key": clause_key,
        "category": category,
        "standard_text": standard_text,
        "risk_weight": risk_weight,
        "is_mandatory": is_mandatory,
        "status": "ACTIVE",
    }
    stamp_new(ct)
    db.clause_templates[ct["id"]] = ct
    return success_object(serialize(ct), status=201)


@bp.route("/clause-templates/<cid>", methods=["GET"])
@require_roles("ClauseLibrarian", "ContractManager", "ContractApprover", "RiskOfficer")
def get_clause_template(cid):
    ct = db.clause_templates.get(cid)
    if not ct:
        raise resource_not_found("Clause template not found.")
    return success_object(serialize(ct), status=200)


@bp.route("/clause-templates", methods=["GET"])
@require_roles("ClauseLibrarian", "ContractManager", "ContractApprover", "RiskOfficer")
def list_clause_templates():
    limit, offset = parse_pagination()
    org_id = request.args.get("organization_id")
    status = request.args.get("status")

    rows = list(db.clause_templates.values())
    if org_id is not None:
        rows = [r for r in rows if r.get("organization_id") == org_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]

    page, total = paginate(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/clause-templates/<cid>/retire", methods=["POST"])
@require_roles("ClauseLibrarian")
def retire_clause_template(cid):
    ct = db.clause_templates.get(cid)
    if not ct:
        raise resource_not_found("Clause template not found.")
    if ct.get("status") != "ACTIVE":
        raise invalid_state("Only an ACTIVE clause template can be retired.")

    # No working-state contract's current version may still reference this clause
    # (PRD §3.1; else ERR_CLAUSE_IN_USE).
    working = {"DRAFT", "UNDER_REVIEW", "REDLINING"}
    for contract in db.contracts.values():
        if contract.get("status") not in working:
            continue
        version = db.contract_versions.get(contract.get("current_version_id"))
        if not version:
            continue
        for clause in version.get("clauses", []) or []:
            if clause.get("clause_template_id") == cid:
                raise clause_in_use(
                    "Clause template is referenced by a working contract's current version.")

    ct["status"] = "RETIRED"
    bump(ct)
    return success_object(serialize(ct), status=200)
