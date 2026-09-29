"""The read surface: 30 GET endpoints (PRD sections 2.10 and 4)."""
from flask import Blueprint

import calc
import db as store
import enums
import serializers as ser
from middleware import (authenticate, check_owner_scope, must_get, owner_id_of_conflict,
                        owner_id_of_determination, owner_id_of_document, owner_id_of_plan)
from response import ok, ok_list
from validation import pagination, query_bool, query_enum, query_str

bp = Blueprint("reads", __name__)

ALL_ROLES = ("ProgramAdmin", "UtilityCoordinator", "RightOfWayAdjudicator", "AgreementOfficer",
             "ExternalAuditor", "ConstructionEngineer", "UtilityOwnerRep")


def page(rows, serializer, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


# ------------------------------------------------------------------ projects --

@bp.get("/uro/projects")
def list_projects():
    authenticate(("ProgramAdmin", "UtilityCoordinator", "RightOfWayAdjudicator",
                  "AgreementOfficer", "ConstructionEngineer", "ExternalAuditor"))
    limit, offset = pagination()
    status = query_enum("status", enums.PROJECT_STATUS)
    posture = query_enum("clearance_posture", enums.CLEARANCE_POSTURE)
    rows = store.ordered(store.db.projects)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if posture is not None:
        rows = [r for r in rows if calc.clearance_posture(r) == posture]
    return page(rows, ser.project_out, limit, offset)


@bp.get("/uro/projects/<project_id>")
def get_project(project_id):
    authenticate(ALL_ROLES)
    project = must_get("project", project_id)
    return ok(ser.project_out(project))


@bp.get("/uro/projects/<project_id>/clearance-summary")
def project_clearance_summary(project_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "ConstructionEngineer"))
    project = must_get("project", project_id)
    liability = calc.project_state_liability(project)
    ledger = calc.project_committed_ledger(project)
    return ok({
        "clearance_posture": calc.clearance_posture(project),
        "open_conflict_count": calc.project_open_conflict_count(project),
        "untriaged_conflict_count": calc.untriaged_conflict_count(project),
        "overdue_commitment_count": calc.overdue_commitment_count(project),
        "at_risk_commitment_count": calc.at_risk_commitment_count(project),
        "estimated_state_liability_cents": liability,
        "total_committed_reimbursement_cents": ledger,
        "reimbursement_authority_cents": project["reimbursement_authority_cents"],
        "remaining_authority_cents": project["reimbursement_authority_cents"] - ledger,
    })


@bp.get("/uro/projects/<project_id>/joint-trench-slots")
def list_project_slots(project_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "ConstructionEngineer", "UtilityOwnerRep"))
    limit, offset = pagination()
    must_get("project", project_id)
    rows = store.slots_of_project(project_id)
    return page(rows, ser.slot_out, limit, offset)


# ------------------------------------------------------------ utility owners --

@bp.get("/uro/utility-owners")
def list_owners():
    authenticate(("ProgramAdmin", "UtilityCoordinator", "RightOfWayAdjudicator",
                  "AgreementOfficer", "ExternalAuditor"))
    limit, offset = pagination()
    utility_type = query_enum("utility_type", enums.UTILITY_TYPE)
    hold = query_bool("reimbursement_hold")
    rows = store.ordered(store.db.owners)
    if utility_type is not None:
        rows = [r for r in rows if r["utility_type"] == utility_type]
    if hold is not None:
        rows = [r for r in rows if r["reimbursement_hold"] is hold]
    return page(rows, ser.owner_out, limit, offset)


@bp.get("/uro/utility-owners/<owner_id>")
def get_owner(owner_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "RightOfWayAdjudicator",
                  "AgreementOfficer", "ExternalAuditor", "UtilityOwnerRep"))
    owner = must_get("owner", owner_id)
    return ok(ser.owner_out(owner))


@bp.get("/uro/utility-owners/<owner_id>/facilities")
def list_owner_facilities(owner_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "RightOfWayAdjudicator", "UtilityOwnerRep"))
    limit, offset = pagination()
    must_get("owner", owner_id)
    rows = store.facilities_of_owner(owner_id)
    return page(rows, ser.facility_out, limit, offset)


@bp.get("/uro/facilities/<facility_id>")
def get_facility(facility_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "RightOfWayAdjudicator",
                  "ConstructionEngineer", "UtilityOwnerRep"))
    facility = must_get("facility", facility_id)
    return ok(ser.facility_out(facility))


# ------------------------------------------------------------ investigations --

@bp.get("/uro/investigations")
def list_investigations():
    authenticate(("ProgramAdmin", "UtilityCoordinator", "RightOfWayAdjudicator",
                  "ConstructionEngineer"))
    limit, offset = pagination()
    project_id = query_str("project_id")
    facility_id = query_str("facility_id")
    quality_level = query_enum("quality_level", enums.QUALITY_LEVEL)
    rows = store.ordered(store.db.investigations)
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if facility_id is not None:
        rows = [r for r in rows if r["facility_id"] == facility_id]
    if quality_level is not None:
        rows = [r for r in rows if r["quality_level"] == quality_level]
    return page(rows, ser.investigation_out, limit, offset)


@bp.get("/uro/investigations/<investigation_id>")
def get_investigation(investigation_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "RightOfWayAdjudicator",
                  "ConstructionEngineer"))
    investigation = must_get("investigation", investigation_id)
    return ok(ser.investigation_out(investigation))


# ----------------------------------------------------------------- conflicts --

@bp.get("/uro/conflicts")
def list_conflicts():
    authenticate(("ProgramAdmin", "UtilityCoordinator", "RightOfWayAdjudicator",
                  "AgreementOfficer", "ConstructionEngineer", "UtilityOwnerRep"))
    limit, offset = pagination()
    project_id = query_str("project_id")
    facility_id = query_str("facility_id")
    depends_on = query_str("depends_on_conflict_id")
    status = query_enum("status", enums.CONFLICT_STATUS)
    rows = store.ordered(store.db.conflicts)
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if facility_id is not None:
        rows = [r for r in rows if r["facility_id"] == facility_id]
    if depends_on is not None:
        rows = [r for r in rows if r["depends_on_conflict_id"] == depends_on]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(rows, ser.conflict_out, limit, offset)


@bp.get("/uro/conflicts/<conflict_id>")
def get_conflict(conflict_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "RightOfWayAdjudicator",
                  "AgreementOfficer", "ConstructionEngineer", "UtilityOwnerRep"))
    conflict = must_get("conflict", conflict_id)
    return ok(ser.conflict_out(conflict))


@bp.get("/uro/conflicts/<conflict_id>/prior-rights")
def list_conflict_determinations(conflict_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "RightOfWayAdjudicator",
                  "AgreementOfficer", "UtilityOwnerRep"))
    limit, offset = pagination()
    conflict = must_get("conflict", conflict_id)
    check_owner_scope(owner_id_of_conflict(conflict))
    rows = store.determinations_of_conflict(conflict_id)
    return page(rows, ser.determination_out, limit, offset)


@bp.get("/uro/conflicts/<conflict_id>/relocation-plans")
def list_conflict_plans(conflict_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "AgreementOfficer",
                  "ConstructionEngineer", "UtilityOwnerRep"))
    limit, offset = pagination()
    status = query_enum("status", enums.PLAN_STATUS)
    conflict = must_get("conflict", conflict_id)
    check_owner_scope(owner_id_of_conflict(conflict))
    rows = store.plans_of_conflict(conflict_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(rows, ser.plan_out, limit, offset)


@bp.get("/uro/conflicts/<conflict_id>/permits")
def list_conflict_permits(conflict_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "ConstructionEngineer", "UtilityOwnerRep"))
    limit, offset = pagination()
    must_get("conflict", conflict_id)
    rows = store.permits_of_conflict(conflict_id)
    return page(rows, ser.permit_out, limit, offset)


# ------------------------------------------------------------- prior rights ---

@bp.get("/uro/prior-rights/<determination_id>")
def get_determination(determination_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "RightOfWayAdjudicator",
                  "AgreementOfficer", "UtilityOwnerRep"))
    determination = must_get("determination", determination_id)
    check_owner_scope(owner_id_of_determination(determination))
    return ok(ser.determination_out(determination))


# ---------------------------------------------------------- relocation plans --

@bp.get("/uro/relocation-plans/<plan_id>")
def get_plan(plan_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "AgreementOfficer",
                  "ConstructionEngineer", "UtilityOwnerRep"))
    plan = must_get("plan", plan_id)
    check_owner_scope(owner_id_of_plan(plan))
    return ok(ser.plan_out(plan))


# ------------------------------------------------------------------- permits --

@bp.get("/uro/permits/<permit_id>")
def get_permit(permit_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "ConstructionEngineer", "UtilityOwnerRep"))
    permit = must_get("permit", permit_id)
    return ok(ser.permit_out(permit))


# -------------------------------------------------------- joint trench slots --

@bp.get("/uro/joint-trench-slots/<slot_id>")
def get_slot(slot_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "ConstructionEngineer", "UtilityOwnerRep"))
    slot = must_get("slot", slot_id)
    return ok(ser.slot_out(slot))


# --------------------------------------------------------------- commitments --

@bp.get("/uro/commitments")
def list_commitments():
    authenticate(("ProgramAdmin", "UtilityCoordinator", "ConstructionEngineer",
                  "AgreementOfficer", "UtilityOwnerRep"))
    limit, offset = pagination()
    plan_id = query_str("plan_id")
    project_id = query_str("project_id")
    facility_id = query_str("facility_id")
    owner_id = query_str("owner_id")
    slot_id = query_str("joint_trench_slot_id")
    status = query_enum("status", enums.COMMITMENT_STATUS)
    rows = store.ordered(store.db.commitments)
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if facility_id is not None:
        rows = [r for r in rows if r["facility_id"] == facility_id]
    if owner_id is not None:
        rows = [r for r in rows if r["owner_id"] == owner_id]
    if slot_id is not None:
        rows = [r for r in rows if r["joint_trench_slot_id"] == slot_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(rows, ser.commitment_out, limit, offset)


@bp.get("/uro/commitments/<commitment_id>")
def get_commitment(commitment_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "ConstructionEngineer",
                  "AgreementOfficer", "UtilityOwnerRep"))
    commitment = must_get("commitment", commitment_id)
    check_owner_scope(commitment["owner_id"])
    return ok(ser.commitment_out(commitment))


# ---------------------------------------------------------------- agreements --

@bp.get("/uro/agreements")
def list_agreements():
    authenticate(("ProgramAdmin", "UtilityCoordinator", "AgreementOfficer",
                  "ExternalAuditor", "UtilityOwnerRep"))
    limit, offset = pagination()
    plan_id = query_str("plan_id")
    project_id = query_str("project_id")
    owner_id = query_str("owner_id")
    execution_status = query_enum("execution_status", enums.EXECUTION_STATUS)
    settlement_status = query_enum("settlement_status", enums.SETTLEMENT_STATUS)
    rows = store.ordered(store.db.agreements)
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if owner_id is not None:
        rows = [r for r in rows if r["owner_id"] == owner_id]
    if execution_status is not None:
        rows = [r for r in rows if r["execution_status"] == execution_status]
    if settlement_status is not None:
        rows = [r for r in rows if r["settlement_status"] == settlement_status]
    return page(rows, ser.agreement_out, limit, offset)


@bp.get("/uro/agreements/<agreement_id>")
def get_agreement(agreement_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "AgreementOfficer",
                  "ExternalAuditor", "UtilityOwnerRep"))
    agreement = must_get("agreement", agreement_id)
    check_owner_scope(agreement["owner_id"])
    return ok(ser.agreement_out(agreement))


@bp.get("/uro/agreements/<agreement_id>/settlement-preview")
def agreement_settlement_preview(agreement_id):
    authenticate(("ProgramAdmin", "AgreementOfficer", "ExternalAuditor"))
    agreement = must_get("agreement", agreement_id)
    figures, included, excluded = calc.settlement_figures(agreement, "ACTUAL_BASIS")
    payload = {"cost_basis": "ACTUAL_BASIS"}
    payload.update(figures)
    payload["included_document_count"] = len(included)
    payload["excluded_document_count"] = len(excluded)
    return ok(payload)


@bp.get("/uro/agreements/<agreement_id>/cost-documents")
def list_agreement_documents(agreement_id):
    authenticate(("ProgramAdmin", "AgreementOfficer", "ExternalAuditor", "UtilityOwnerRep"))
    limit, offset = pagination()
    review_status = query_enum("review_status", enums.REVIEW_STATUS)
    agreement = must_get("agreement", agreement_id)
    check_owner_scope(agreement["owner_id"])
    rows = store.documents_of_agreement(agreement_id)
    if review_status is not None:
        rows = [r for r in rows if r["review_status"] == review_status]
    return page(rows, ser.document_out, limit, offset)


@bp.get("/uro/agreements/<agreement_id>/audit-findings")
def list_agreement_findings(agreement_id):
    authenticate(("ProgramAdmin", "AgreementOfficer", "ExternalAuditor", "UtilityOwnerRep"))
    limit, offset = pagination()
    status = query_enum("status", enums.FINDING_STATUS)
    agreement = must_get("agreement", agreement_id)
    check_owner_scope(agreement["owner_id"])
    rows = store.findings_of_agreement(agreement_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(rows, ser.finding_out, limit, offset)


@bp.get("/uro/cost-documents/<document_id>")
def get_document(document_id):
    authenticate(("ProgramAdmin", "AgreementOfficer", "ExternalAuditor", "UtilityOwnerRep"))
    document = must_get("document", document_id)
    check_owner_scope(owner_id_of_document(document))
    return ok(ser.document_out(document))


@bp.get("/uro/audit-findings/<finding_id>")
def get_finding(finding_id):
    authenticate(("ProgramAdmin", "AgreementOfficer", "ExternalAuditor", "UtilityOwnerRep"))
    finding = must_get("finding", finding_id)
    agreement = store.db.agreements.get(finding["agreement_id"])
    check_owner_scope(None if agreement is None else agreement["owner_id"])
    return ok(ser.finding_out(finding))


# --------------------------------------------------------------- delay claims --

@bp.get("/uro/delay-claims")
def list_claims():
    authenticate(("ProgramAdmin", "UtilityCoordinator", "ConstructionEngineer",
                  "AgreementOfficer", "UtilityOwnerRep"))
    limit, offset = pagination()
    project_id = query_str("project_id")
    commitment_id = query_str("commitment_id")
    status = query_enum("status", enums.CLAIM_STATUS)
    rows = store.ordered(store.db.claims)
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if commitment_id is not None:
        rows = [r for r in rows if r["commitment_id"] == commitment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page(rows, ser.claim_out, limit, offset)


@bp.get("/uro/delay-claims/<claim_id>")
def get_claim(claim_id):
    authenticate(("ProgramAdmin", "UtilityCoordinator", "ConstructionEngineer",
                  "AgreementOfficer", "UtilityOwnerRep"))
    claim = must_get("claim", claim_id)
    return ok(ser.claim_out(claim))
