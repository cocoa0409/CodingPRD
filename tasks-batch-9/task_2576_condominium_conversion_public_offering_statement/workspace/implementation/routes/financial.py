"""Reserve funding studies and the first-year operating budget (PRD 3.5)."""

from flask import Blueprint

import clock
import envelope
import serializers
import store
import validation as v
from errors import ApiError
from services import budgets as budget_service, reserves as reserve_service

bp = Blueprint("financial", __name__)

STUDY_CREATE_ROLES = ["ConverterSponsor", "LicensedEngineer"]
STUDY_READ_ROLES = ["ConverterSponsor", "StateRegulator", "LenderUnderwriter",
                    "LicensedEngineer", "PlatformAdmin"]
SPONSOR = ["ConverterSponsor"]
BUDGET_READ_ROLES = ["ConverterSponsor", "StateRegulator", "LenderUnderwriter",
                     "Purchaser", "PlatformAdmin"]
ADOPT_ROLES = ["ConverterSponsor", "StateRegulator"]

METHODS = ["COMPONENT_METHOD", "CASH_FLOW_METHOD"]


@bp.post("/conversion-projects/<project_id>/reserve-studies")
def create_study(project_id):
    v.authorize(STUDY_CREATE_ROLES)
    project = v.get_project(project_id)
    body = v.raw_body()
    report = v.body_ref(body, "engineering_report_id", v.get_report)
    v.require_scope(project["id"], report)
    fields = v.parse([
        v.field("engineering_report_id", "id"),
        v.field("method", "enum", values=METHODS),
        v.field("opening_reserve_balance_cents", "integer", required=False,
                default=0, minimum=0),
    ])
    v.gate_not_frozen(project)
    if project["suitability_gate"] != "PASSED":
        raise ApiError("ERR_SUITABILITY_GATE_FAILED")
    if not reserve_service.verified_components(report["id"]):
        raise ApiError("ERR_NO_VERIFIED_COMPONENTS")
    study = store.new_record(store.reserve_studies, {
        "_type": "ReserveStudy",
        "conversion_project_id": project["id"],
        "engineering_report_id": report["id"],
        "method": fields["method"],
        "opening_reserve_balance_cents":
            fields["opening_reserve_balance_cents"],
        "fully_funded_balance_cents": 0,
        "recommended_annual_contribution_cents": 0,
        "percent_funded_bp": 0,
        "funding_status": "UNDERFUNDED",
        "adoption_status": "PROPOSED",
    })
    reserve_service.compute(study, project)
    return envelope.object_response(serializers.dump(study), 201)


@bp.get("/conversion-projects/<project_id>/reserve-studies")
def list_project_studies(project_id):
    v.authorize(STUDY_READ_ROLES)
    project = v.get_project(project_id)
    limit, offset = v.pagination()
    records = [
        s for s in store.project_studies(project["id"])
        if v.matches(s,
                     method=v.filter_value("method"),
                     funding_status=v.filter_value("funding_status"),
                     adoption_status=v.filter_value("adoption_status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/reserve-studies")
def list_studies():
    v.authorize(STUDY_READ_ROLES)
    limit, offset = v.pagination()
    records = [
        s for s in store.ordered(store.reserve_studies.values())
        if v.matches(
            s,
            conversion_project_id=v.filter_value("conversion_project_id"),
            engineering_report_id=v.filter_value("engineering_report_id"),
            method=v.filter_value("method"),
            funding_status=v.filter_value("funding_status"),
            adoption_status=v.filter_value("adoption_status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/reserve-studies/<study_id>")
def get_study(study_id):
    v.authorize(STUDY_READ_ROLES)
    study = v.get_study(study_id)
    return envelope.object_response(serializers.dump(study), 200)


@bp.patch("/reserve-studies/<study_id>")
def patch_study(study_id):
    v.authorize(SPONSOR)
    study = v.get_study(study_id)
    project = v.get_project(study["conversion_project_id"])
    body = v.parse([
        v.field("opening_reserve_balance_cents", "integer", minimum=0)])
    v.gate_not_frozen(project)
    v.require_state(study, "adoption_status", ("PROPOSED",))
    study["opening_reserve_balance_cents"] = (
        body["opening_reserve_balance_cents"])
    # PRD 3.5 pins the re-derivation to the funding tail: the recommended
    # contribution stays as commissioned.
    study["percent_funded_bp"] = reserve_service.percent_funded(
        study["fully_funded_balance_cents"],
        study["opening_reserve_balance_cents"])
    study["funding_status"] = reserve_service.funding_status(
        study["percent_funded_bp"])
    store.touch(study)
    return envelope.object_response(serializers.dump(study), 200)


# --- the first-year budget -------------------------------------------------

@bp.post("/conversion-projects/<project_id>/initial-budgets")
def create_budget(project_id):
    v.authorize(SPONSOR)
    project = v.get_project(project_id)
    body = v.raw_body()
    study = v.body_ref(body, "reserve_study_id", v.get_study)
    v.require_scope(project["id"], study)
    fields = v.parse([
        v.field("reserve_study_id", "id"),
        v.field("fiscal_year_label", "string", max_len=100),
        v.field("annual_operating_expense_cents", "integer", minimum=0),
        v.field("expected_conversion_project_version", "integer"),
    ])
    v.require_unique(store.project_budgets(project["id"]),
                     fiscal_year_label=fields["fiscal_year_label"])
    v.require_version(fields["expected_conversion_project_version"], project,
                      "ERR_STALE_PROJECT_VERSION")
    v.gate_not_frozen(project)
    budget = store.new_record(store.initial_budgets, {
        "_type": "InitialBudget",
        "conversion_project_id": project["id"],
        "reserve_study_id": study["id"],
        "fiscal_year_label": fields["fiscal_year_label"],
        "annual_operating_expense_cents":
            fields["annual_operating_expense_cents"],
        "reserve_contribution_cents": 0,
        "base_expense_cents": 0,
        "management_fee_bp": 0,
        "management_fee_cents": 0,
        "total_annual_expense_cents": 0,
        "assessment_income_cents": 0,
        "developer_deficit_funding_cents": 0,
        "developer_subsidy_flag": False,
        "status": "DRAFT",
        "adopted_at": None,
    })
    budget_service.derive(budget, project, study)
    # The budget writes assessments onto units, so the parent project bumps.
    store.touch(project)
    return envelope.object_response(serializers.dump(budget), 201)


@bp.get("/conversion-projects/<project_id>/initial-budgets")
def list_project_budgets(project_id):
    v.authorize(BUDGET_READ_ROLES)
    project = v.get_project(project_id)
    limit, offset = v.pagination()
    records = [
        b for b in store.project_budgets(project["id"])
        if v.matches(b, status=v.filter_value("status"),
                     developer_subsidy_flag=v.filter_bool(
                         "developer_subsidy_flag"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/initial-budgets")
def list_budgets():
    v.authorize(BUDGET_READ_ROLES)
    limit, offset = v.pagination()
    records = [
        b for b in store.ordered(store.initial_budgets.values())
        if v.matches(
            b,
            conversion_project_id=v.filter_value("conversion_project_id"),
            reserve_study_id=v.filter_value("reserve_study_id"),
            status=v.filter_value("status"),
            developer_subsidy_flag=v.filter_bool("developer_subsidy_flag"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/initial-budgets/<budget_id>")
def get_budget(budget_id):
    v.authorize(BUDGET_READ_ROLES)
    budget = v.get_budget(budget_id)
    return envelope.object_response(serializers.dump(budget), 200)


@bp.patch("/initial-budgets/<budget_id>")
def patch_budget(budget_id):
    v.authorize(SPONSOR)
    budget = v.get_budget(budget_id)
    project = v.get_project(budget["conversion_project_id"])
    body = v.parse([
        v.field("annual_operating_expense_cents", "integer", minimum=0)])
    v.gate_not_frozen(project)
    v.require_state(budget, "status", ("DRAFT",))
    study = v.get_study(budget["reserve_study_id"])
    budget["annual_operating_expense_cents"] = (
        body["annual_operating_expense_cents"])
    # The whole chain re-derives from scratch, tier selection included.
    budget_service.derive(budget, project, study)
    store.touch(budget)
    return envelope.object_response(serializers.dump(budget), 200)


@bp.post("/initial-budgets/<budget_id>/adoption")
def adopt_budget(budget_id):
    v.authorize(ADOPT_ROLES)
    budget = v.get_budget(budget_id)
    project = v.get_project(budget["conversion_project_id"])
    v.gate_not_frozen(project)
    v.require_state(budget, "status", ("DRAFT",))
    # Adoption is exclusive across the project.
    for sibling in store.project_budgets(project["id"]):
        if sibling["id"] == budget["id"] or sibling["status"] != "ADOPTED":
            continue
        sibling["status"] = "SUPERSEDED"
        store.touch(sibling)
        old_study = store.reserve_studies.get(sibling["reserve_study_id"])
        if (old_study is not None
                and old_study["id"] != budget["reserve_study_id"]
                and old_study["adoption_status"] != "SUPERSEDED"):
            old_study["adoption_status"] = "SUPERSEDED"
            store.touch(old_study)
    budget["status"] = "ADOPTED"
    budget["adopted_at"] = clock.now()
    store.touch(budget)
    study = v.get_study(budget["reserve_study_id"])
    if study["adoption_status"] != "ADOPTED":
        study["adoption_status"] = "ADOPTED"
        store.touch(study)
    return envelope.object_response(serializers.dump(budget), 200)
