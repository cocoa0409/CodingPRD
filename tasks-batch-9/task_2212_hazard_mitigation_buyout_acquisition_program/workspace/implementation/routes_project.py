"""Mitigation project and benefit-cost analysis endpoints."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import lookups
import store
import web
from core import clock_date, fail, parse_date, rhu
from web import endpoint

bp = Blueprint("projects", __name__)


def _new_project(fields):
    record = store.new_record("MitigationProject", fields)
    record["status"] = "DRAFT"
    record["validated_bcr"] = None
    record["validated_bca_method"] = None
    record["validated_by_user_id"] = None
    record["federal_obligated_cents"] = 0
    record["program_income_balance_cents"] = 0
    record["protected_open_space_acres"] = rhu(Decimal(0), 2)
    record["participating_parcel_count"] = 0
    record["holdout_parcel_count"] = 0
    record["contiguous_open_space_parcel_count"] = 0
    record["largest_component_parcel_ids"] = []
    record["neighborhood_viability_ratio"] = rhu(Decimal(0), 4)
    record["viability_status"] = "NONVIABLE"
    return record


@bp.post("/mitigation-projects")
@endpoint("ProgramAdministrator")
def create_project():
    body = web.get_body()
    code = web.req_string(body, "project_code")
    if len(code) < 4 or len(code) > 32:
        fail("ERR_INVALID_REQUEST", "Field 'project_code' must be 4 to 32 characters.")
    grant_program = web.req_enum(body, "grant_program", store.GRANT_PROGRAMS)
    declaration = web.opt_string(body, "disaster_declaration_number")
    if grant_program == "HMGP" and (declaration is None or declaration.strip() == ""):
        fail("ERR_INVALID_REQUEST",
             "Field 'disaster_declaration_number' is required when grant_program is HMGP.")
    subrecipient = web.req_string(body, "subrecipient_name")
    pct = web.decimal_field(body, "cost_share_federal_pct", required=False,
                            default=Decimal("0.75"), places=2,
                            minimum=Decimal("0.50"), maximum=Decimal("1.00"))
    cap = web.int_field(body, "total_federal_share_cap_cents", minimum=1)
    pop_end = web.req_date(body, "period_of_performance_end_date")

    for existing in store.projects.values():
        if existing["project_code"] == code:
            fail("ERR_DUPLICATE_PROJECT_CODE")

    record = _new_project({
        "project_code": code,
        "grant_program": grant_program,
        "disaster_declaration_number": declaration,
        "subrecipient_name": subrecipient,
        "cost_share_federal_pct": pct,
        "total_federal_share_cap_cents": cap,
        "period_of_performance_end_date": body["period_of_performance_end_date"],
    })
    store.projects[record["id"]] = record
    return web.respond_object(record, 201)


@bp.get("/mitigation-projects")
@endpoint()
def list_projects():
    status = web.query_enum("status", store.PROJECT_STATUSES)
    grant_program = web.query_enum("grant_program", store.GRANT_PROGRAMS)
    viability = web.query_enum("viability_status", ["NONVIABLE", "AT_RISK", "VIABLE"])
    rows = list(store.projects.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if grant_program is not None:
        rows = [r for r in rows if r["grant_program"] == grant_program]
    if viability is not None:
        rows = [r for r in rows if r["viability_status"] == viability]
    return web.list_response(rows)


@bp.get("/mitigation-projects/<project_id>")
@endpoint()
def read_project(project_id):
    return web.respond_object(lookups.get_project(project_id))


@bp.post("/mitigation-projects/<project_id>/submit")
@endpoint("SubrecipientCoordinator")
def submit_project(project_id):
    project = lookups.get_project(project_id)
    web.scope_project(project_id)
    if project["status"] != "DRAFT":
        fail("ERR_INVALID_PROJECT_STATE")
    has_bca = any(b["project_id"] == project_id and b["status"] == "SUBMITTED"
                  for b in store.bcas.values())
    has_parcel = any(p["project_id"] == project_id for p in store.parcels.values())
    if not has_bca or not has_parcel:
        fail("ERR_INVALID_PROJECT_STATE")
    project["status"] = "SUBMITTED"
    store.touch(project)
    return web.respond_object(project)


@bp.post("/mitigation-projects/<project_id>/return")
@endpoint("ProgramAdministrator")
def return_project(project_id):
    project = lookups.get_project(project_id)
    body = web.get_body()
    web.req_string(body, "return_reason")
    if project["status"] != "SUBMITTED":
        fail("ERR_INVALID_PROJECT_STATE")
    project["status"] = "DRAFT"
    store.touch(project)
    return web.respond_object(project)


@bp.post("/mitigation-projects/<project_id>/approve")
@endpoint("ProgramAdministrator")
def approve_project(project_id):
    project = lookups.get_project(project_id)
    # SoD-2 sits ahead of structural validation (PRD 2.9 step 3).
    if project.get("validated_by_user_id") is not None and g.uid == project["validated_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    body = web.get_body()
    decision = web.req_enum(body, "decision", ["APPROVE", "DENY"])
    web.opt_string(body, "decision_note")
    if project["status"] != "SUBMITTED":
        fail("ERR_INVALID_PROJECT_STATE")

    if decision == "APPROVE":
        validated = [b for b in store.bcas.values()
                     if b["project_id"] == project_id and b["status"] == "VALIDATED"]
        bcr = project.get("validated_bcr")
        if len(validated) != 1 or bcr is None or bcr < store.BCR_APPROVAL_THRESHOLD:
            fail("ERR_BCR_BELOW_THRESHOLD")
        project["status"] = "APPROVED"
        calc.recompute_viability_full(project)
        store.touch(project)
        return web.respond_object(project)

    project["status"] = "DENIED"
    for parcel in store.by_created(calc.project_parcels(project_id)):
        if parcel["acquisition_status"] not in store.PRE_CLOSING_ACQUISITION:
            continue
        parcel["acquisition_status"] = "ACQUISITION_CANCELLED"
        store.touch(parcel)
        for offer in store.by_created(calc.parcel_offers(parcel["id"])):
            if offer["status"] not in ("DRAFT", "PRESENTED"):
                continue
            offer["status"] = "WITHDRAWN"
            store.touch(offer)
    calc.recompute_federal_obligated(project)
    store.touch(project)
    return web.respond_object(project)


@bp.post("/mitigation-projects/<project_id>/closeout")
@endpoint("ProgramAdministrator")
def closeout_project(project_id):
    project = lookups.get_project(project_id)
    body = web.get_body()
    decision = web.req_enum(body, "decision", ["INITIATE", "FINALIZE"])

    if decision == "INITIATE":
        if project["status"] != "APPROVED":
            fail("ERR_INVALID_PROJECT_STATE")
        parcels = calc.project_parcels(project_id)
        if int(project["participating_parcel_count"]) < 1:
            fail("ERR_INVALID_PROJECT_STATE")
        for parcel in parcels:
            if parcel["acquisition_status"] not in ("OPEN_SPACE_RECORDED", "ACQUISITION_CANCELLED"):
                fail("ERR_INVALID_PROJECT_STATE")
        restrictions = calc.project_restrictions(project_id)
        for restriction in restrictions:
            if restriction["status"] == "VIOLATION_OPEN":
                fail("ERR_INVALID_PROJECT_STATE")
        today = clock_date()
        for restriction in restrictions:
            if calc.restriction_overdue(restriction, today):
                fail("ERR_MONITORING_OVERDUE")
        if project["viability_status"] == "NONVIABLE":
            fail("ERR_NEIGHBORHOOD_NONVIABLE")
        project["status"] = "CLOSEOUT_PENDING"
        calc.recompute_program_income_balance(project)
        calc.recompute_protected_acres(project)
        store.touch(project)
        return web.respond_object(project)

    if project["status"] != "CLOSEOUT_PENDING":
        fail("ERR_INVALID_PROJECT_STATE")
    if int(project["program_income_balance_cents"]) != 0:
        fail("ERR_PROGRAM_INCOME_OUTSTANDING")
    project["status"] = "CLOSED_OUT"
    store.touch(project)
    return web.respond_object(project)


# --------------------------------------------------------------------------
# Benefit-cost analyses
# --------------------------------------------------------------------------

@bp.post("/mitigation-projects/<project_id>/benefit-cost-analyses")
@endpoint("SubrecipientCoordinator")
def create_bca(project_id):
    project = lookups.get_project(project_id)
    web.scope_project(project_id)
    body = web.get_body()
    method = web.req_enum(body, "analysis_method", store.ANALYSIS_METHODS)
    hazard = web.req_enum(body, "hazard_type", store.HAZARD_TYPES)
    zone = web.req_enum(body, "sfha_zone", store.SFHA_ZONES)
    repetitive = web.opt_bool(body, "repetitive_loss_flag", False)
    annualized = web.int_field(body, "annualized_loss_avoided_cents", minimum=1)
    years = web.int_field(body, "project_useful_life_years", minimum=1, maximum=100)
    rate = web.decimal_field(body, "discount_rate_pct", required=False,
                             default=Decimal("0.07"), places=2)
    if method == "FEMA_BCA_TOOLKIT" and rate <= 0:
        fail("ERR_INVALID_REQUEST",
             "Field 'discount_rate_pct' must be greater than zero for FEMA_BCA_TOOLKIT.")
    if rate >= 1:
        fail("ERR_INVALID_REQUEST", "Field 'discount_rate_pct' must be less than one.")
    cost = web.int_field(body, "mitigation_cost_cents", minimum=1)
    if project["status"] not in ("DRAFT", "SUBMITTED"):
        fail("ERR_INVALID_PROJECT_STATE")

    factor, npv, bcr = calc.benefit_cost_ratio(method, annualized, years, rate, cost)
    record = store.new_record("BenefitCostAnalysis", {
        "project_id": project_id,
        "analysis_method": method,
        "hazard_type": hazard,
        "sfha_zone": zone,
        "repetitive_loss_flag": repetitive,
        "annualized_loss_avoided_cents": annualized,
        "project_useful_life_years": years,
        "discount_rate_pct": rate,
        "mitigation_cost_cents": cost,
        "pv_annuity_factor": factor,
        "npv_benefits_cents": npv,
        "bcr": bcr,
        "validated_by_user_id": None,
        "status": "SUBMITTED",
    })
    store.bcas[record["id"]] = record
    return web.respond_object(record, 201)


@bp.get("/benefit-cost-analyses")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def list_bcas():
    project_id = web.query_str("project_id")
    method = web.query_enum("analysis_method", store.ANALYSIS_METHODS)
    status = web.query_enum("status", store.BCA_STATUSES)
    rows = list(store.bcas.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if method is not None:
        rows = [r for r in rows if r["analysis_method"] == method]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return web.list_response(rows)


@bp.get("/benefit-cost-analyses/<bca_id>")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def read_bca(bca_id):
    return web.respond_object(lookups.get_bca(bca_id))


@bp.post("/benefit-cost-analyses/<bca_id>/validate")
@endpoint("ProgramAdministrator")
def validate_bca(bca_id):
    bca = lookups.get_bca(bca_id)
    body = web.get_body()
    decision = web.req_enum(body, "decision", ["VALIDATE", "REJECT"])
    web.opt_string(body, "review_note")
    project = store.projects.get(bca["project_id"])
    if project is None:
        fail("ERR_PROJECT_NOT_FOUND")
    if project["status"] != "SUBMITTED":
        fail("ERR_INVALID_PROJECT_STATE")
    if bca["status"] != "SUBMITTED":
        fail("ERR_INVALID_BCA_STATE")

    if decision == "VALIDATE":
        for other in store.bcas.values():
            if other["id"] == bca_id:
                continue
            if other["project_id"] == bca["project_id"] and other["status"] == "VALIDATED":
                fail("ERR_INVALID_BCA_STATE")
        bca["status"] = "VALIDATED"
        bca["validated_by_user_id"] = g.uid
        store.touch(bca)
        project["validated_bcr"] = bca["bcr"]
        project["validated_bca_method"] = bca["analysis_method"]
        project["validated_by_user_id"] = g.uid
        store.touch(project)
        return web.respond_object(bca)

    bca["status"] = "REJECTED"
    store.touch(bca)
    return web.respond_object(bca)
