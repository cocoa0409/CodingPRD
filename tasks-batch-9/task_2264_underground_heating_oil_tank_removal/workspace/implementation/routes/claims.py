"""Trust-fund claims: filing, the eligibility breakdown, submission and review."""

from flask import Blueprint

import calculations as calc
from db import assign, create, db
from errors import ApiError
from middleware import (authenticate, body, filter_arg, opt_id, opt_str, pagination,
                        req_enum, req_int, resolve)
from response import entity_response, list_response
from services import project as svc

bp = Blueprint("claims", __name__)

READ_ROLES = ("ProjectCoordinator", "LicensedSiteProfessional", "ComplianceOfficer")
OPEN_INTERIM_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED")
SUBMITTABLE_PROJECT_STATUSES = ("ASSESSED", "REMEDIATION_ACTIVE", "CLEARED", "CLOSED_NFA")


def _apply_eligibility(claim):
    figures = calc.eligibility(claim["state_code"], claim["claimed_costs_cents"],
                               claim["variant"], claim["reimbursed_amount_cents"])
    for field, value in figures.items():
        assign(claim, field, value)


def _add_finding(claim, code):
    findings = sorted(set(list(claim["eligibility_findings"]) + [code]))
    assign(claim, "eligibility_findings", findings)


@bp.post("/trust-fund-claims")
def create_claim():
    authenticate(("ComplianceOfficer",))
    payload = body()
    project_id = opt_id(payload, "tank_project_id")
    project = resolve("tank_projects", project_id) if project_id else None
    if project is None:
        raise ApiError("ERR_INVALID_REQUEST", "tank_project_id is required.")

    variant = req_enum(payload, "variant", calc.CLAIM_VARIANTS)
    claimed_costs_cents = req_int(payload, "claimed_costs_cents", exclusive_min=0)
    expected_version = req_int(payload, "expected_project_version")

    if expected_version != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")

    if variant == "FINAL_SETTLEMENT":
        conflicting = [c for c in svc.children("trust_fund_claims", project["id"])
                       if c["variant"] == "FINAL_SETTLEMENT"
                       and c["status"] not in ("DENIED", "WITHDRAWN")]
        if conflicting:
            raise ApiError("ERR_DUPLICATE_FINAL_CLAIM")

    prop = svc.property_of(project)
    claim = create("trust_fund_claims", {
        "tank_project_id": project["id"],
        "variant": variant,
        "state_code": prop["state_code"] if prop else None,
        "claimed_costs_cents": claimed_costs_cents,
        "deductible_cents": 0,
        "cap_cents": 0,
        "admin_fee_cents": 0,
        "eligible_amount_cents": 0,
        "reimbursed_amount_cents": 0,
        "unreimbursed_balance_cents": 0,
        "eligibility_findings": [],
        "info_request_count": 0,
        "decision_note": None,
        "submitted_at": None,
        "decided_at": None,
        "paid_at": None,
        "status": "DRAFT",
    })
    _apply_eligibility(claim)

    if variant == "FINAL_SETTLEMENT":
        for other in svc.children("trust_fund_claims", project["id"]):
            if other["id"] == claim["id"]:
                continue
            if other["variant"] == "PRELIMINARY_ESTIMATE" \
                    and other["status"] in OPEN_INTERIM_STATUSES:
                assign(other, "status", "WITHDRAWN")
                _add_finding(other, "SUPERSEDED_BY_FINAL_SETTLEMENT")

    svc.bump_project_version(project)
    return entity_response(claim, 201)


@bp.get("/trust-fund-claims")
def list_claims():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    project_id = filter_arg("tank_project_id")
    variant = filter_arg("variant")
    status = filter_arg("status")
    rows = list(db.trust_fund_claims.values())
    if project_id is not None:
        rows = [r for r in rows if r["tank_project_id"] == project_id]
    if variant is not None:
        rows = [r for r in rows if r["variant"] == variant]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, limit, offset)


@bp.get("/trust-fund-claims/<claim_id>")
def read_claim(claim_id):
    authenticate(READ_ROLES)
    return entity_response(resolve("trust_fund_claims", claim_id))


@bp.post("/trust-fund-claims/<claim_id>/submit")
def submit_claim(claim_id):
    authenticate(("ComplianceOfficer",))
    claim = resolve("trust_fund_claims", claim_id)
    project = db.tank_projects.get(claim["tank_project_id"])

    if claim["status"] not in ("DRAFT", "INFO_REQUESTED"):
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    if project is None or project["status"] not in SUBMITTABLE_PROJECT_STATUSES:
        raise ApiError("ERR_PROJECT_STATE_INVALID")

    if claim["status"] == "DRAFT":
        if project["contamination_disclosure_required"]:
            acknowledged = [d for d in svc.children("disclosures", project["id"])
                            if d["disclosure_kind"] == "CONTAMINATION_FINDINGS"
                            and d["status"] == "ACKNOWLEDGED"]
            if not acknowledged:
                raise ApiError("ERR_DISCLOSURE_NOT_ACKNOWLEDGED")
        if int(claim["eligible_amount_cents"]) <= 0:
            raise ApiError("ERR_CLAIM_NOT_ELIGIBLE")

    assign(claim, "status", "SUBMITTED")
    assign(claim, "submitted_at", db.now())
    return entity_response(claim)


@bp.post("/trust-fund-claims/<claim_id>/decision")
def decide_claim(claim_id):
    authenticate(("ComplianceOfficer",))
    claim = resolve("trust_fund_claims", claim_id)
    payload = body()
    decision = req_enum(payload, "decision",
                        ("UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DENIED", "PAID"))
    decision_note = opt_str(payload, "decision_note")
    project = db.tank_projects.get(claim["tank_project_id"])

    required_state = {
        "UNDER_REVIEW": "SUBMITTED",
        "INFO_REQUESTED": "UNDER_REVIEW",
        "APPROVED": "UNDER_REVIEW",
        "DENIED": "UNDER_REVIEW",
        "PAID": "APPROVED",
    }[decision]
    if claim["status"] != required_state:
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    if decision == "PAID" and (project is None or project["status"] != "CLOSED_NFA"):
        raise ApiError("ERR_PROJECT_STATE_INVALID")

    if decision == "APPROVED" and int(claim["eligible_amount_cents"]) <= 0:
        raise ApiError("ERR_CLAIM_NOT_ELIGIBLE")
    if decision == "INFO_REQUESTED" \
            and int(claim["info_request_count"]) >= calc.MAX_INFO_REQUESTS:
        raise ApiError("ERR_INFO_REQUEST_LIMIT_REACHED")

    now = db.now()
    if decision == "UNDER_REVIEW":
        assign(claim, "status", "UNDER_REVIEW")
    elif decision == "INFO_REQUESTED":
        assign(claim, "status", "INFO_REQUESTED")
        assign(claim, "info_request_count", int(claim["info_request_count"]) + 1)
    elif decision == "APPROVED":
        assign(claim, "status", "APPROVED")
        assign(claim, "decided_at", now)
    elif decision == "DENIED":
        assign(claim, "status", "DENIED")
        assign(claim, "decided_at", now)
        assign(claim, "reimbursed_amount_cents", 0)
        assign(claim, "unreimbursed_balance_cents",
               int(claim["eligible_amount_cents"]))
    else:  # PAID
        assign(claim, "status", "PAID")
        assign(claim, "paid_at", now)
        assign(claim, "reimbursed_amount_cents", int(claim["eligible_amount_cents"]))
        assign(claim, "unreimbursed_balance_cents", 0)
        svc.settle_project(project)

    if decision_note is not None:
        assign(claim, "decision_note", decision_note)
    return entity_response(claim)
