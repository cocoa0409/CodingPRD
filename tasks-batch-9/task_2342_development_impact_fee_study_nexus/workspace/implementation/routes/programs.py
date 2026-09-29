"""Fee programs, facility standards, expenditures, the sweep and the annual report."""

from decimal import Decimal
from flask import Blueprint, g

import db
import helpers
import response
import serializers
from errors import raise_error
from middleware import ANY, guard
from services import derive, ledger, report

bp = Blueprint("programs", __name__)


# --------------------------------------------------------------------------- #
# Fee programs
# --------------------------------------------------------------------------- #


@bp.post("/fee-programs")
@guard("ProgramAdministrator")
def create_fee_program():
    body = helpers.json_body()
    body.forbid_versions()
    record = {
        "name": body.string("name", required=True, min_len=1, max_len=200),
        "jurisdiction_code": body.string("jurisdiction_code", required=True,
                                         pattern=helpers.JURISDICTION_PATTERN),
        "fiscal_year_start_month": body.integer("fiscal_year_start_month", default=7,
                                                minimum=1, maximum=12),
        "statutory_expenditure_deadline_years": body.integer(
            "statutory_expenditure_deadline_years", default=5, minimum=1, maximum=20),
        "notice_min_days": body.integer("notice_min_days", default=14, minimum=1, maximum=365),
        "protest_threshold_bp": body.integer("protest_threshold_bp", default=5000,
                                             minimum=1, maximum=10000),
        "effective_delay_days": body.integer("effective_delay_days", default=60,
                                             minimum=0, maximum=365),
        "admin_charge_bp": body.integer("admin_charge_bp", default=300, minimum=0, maximum=2000),
        "credit_cap_bp": body.integer("credit_cap_bp", default=5000, minimum=0, maximum=10000),
        "los_policy": body.enum("los_policy", helpers.LOS_POLICIES,
                                default="EXISTING_DEFICIENCY_EXCLUDED"),
        "discount_rate_bp": body.integer("discount_rate_bp", default=400,
                                         minimum=1, maximum=5000),
        "max_deferral_days": body.integer("max_deferral_days", default=730,
                                          minimum=1, maximum=3650),
        "default_penalty_bp": body.integer("default_penalty_bp", default=1000,
                                           minimum=0, maximum=10000),
        "at_risk_window_days": body.integer("at_risk_window_days", default=365,
                                            minimum=1, maximum=3650),
        "report_grace_days": body.integer("report_grace_days", default=180,
                                          minimum=1, maximum=730),
        "last_report_fiscal_year": None,
        "last_report_filed_at": None,
        "last_report_status": "NOT_FILED",
        "last_report_filed_by_user_id": None,
    }
    for existing in db.fee_programs.values():
        if existing["jurisdiction_code"] == record["jurisdiction_code"]:
            raise_error("ERR_DUPLICATE_JURISDICTION_CODE")

    program = db.new_record(**record)
    db.fee_programs[program["id"]] = program
    return response.object_response(serializers.fee_program(program), 201)


@bp.get("/fee-programs/<program_id>")
@guard(*ANY)
def read_fee_program(program_id):
    program = helpers.get_program(program_id)
    return response.object_response(serializers.fee_program(program))


@bp.get("/fee-programs/<program_id>/facility-categories")
@guard(*ANY)
def list_program_categories(program_id):
    program = helpers.get_program(program_id)
    posture = helpers.arg_enum("fund_posture", helpers.FUND_POSTURES)
    rows = [c for c in derive.categories_of_program(program["id"])
            if posture is None or c["fund_posture"] == posture]
    return response.paginated(rows, serializers.facility_category)


@bp.get("/fee-programs/<program_id>/annual-report")
@guard(*ANY)
def read_annual_report(program_id):
    program = helpers.get_program(program_id)
    fiscal_year = helpers.arg_int("fiscal_year", required=True)
    return response.object_response(report.compute(program, fiscal_year))


@bp.post("/fee-programs/<program_id>/deadline-sweep")
@guard("ProgramAdministrator")
def run_deadline_sweep(program_id):
    program = helpers.get_program(program_id)
    helpers.json_body().forbid_versions()
    return response.object_response(ledger.deadline_sweep(program))


@bp.post("/fee-programs/<program_id>/annual-report/file")
@guard("FinanceOfficer")
def file_annual_report(program_id):
    program = helpers.get_program(program_id)
    body = helpers.json_body()
    body.forbid_versions()
    fiscal_year = body.integer("fiscal_year", required=True)

    if g.user_id in report.expenditure_authorizers(program, fiscal_year):
        raise_error("ERR_REPORT_PREPARER_CONFLICT")
    if report.filing(program["id"], fiscal_year) is not None:
        raise_error("ERR_REPORT_ALREADY_FILED")
    import clock
    _start, window_end = report.window(program, fiscal_year)
    if clock.now() < window_end:
        raise_error("ERR_FISCAL_YEAR_NOT_COMPLETE")

    payload = report.file_report(program, fiscal_year, g.user_id)
    return response.object_response(payload, 201)


# --------------------------------------------------------------------------- #
# Facility standards
# --------------------------------------------------------------------------- #


@bp.post("/facility-categories")
@guard("ProgramAdministrator")
def create_facility_category():
    body = helpers.json_body()
    body.forbid_versions()
    program_id = body.string("fee_program_id", required=True)
    code = body.string("code", required=True, pattern=helpers.CODE_PATTERN)
    name = body.string("name", required=True, min_len=1, max_len=120)
    demand_unit_label = body.string("demand_unit_label", required=True, min_len=1, max_len=40)
    existing_los = body.number("existing_los_per_demand_unit", required=True, gt=0)
    planned_los = body.number("planned_los_per_demand_unit", required=True, gt=0)
    unit_cost_cents = body.integer("unit_cost_cents", required=True, minimum=1)
    deficiency = body.number("existing_deficiency_demand_units", default=0, ge=0)

    program = db.fee_programs.get(program_id)
    if program is None:
        raise_error("ERR_INVALID_REFERENCE")

    for existing in db.facility_categories.values():
        if existing["fee_program_id"] == program_id and existing["code"] == code:
            raise_error("ERR_DUPLICATE_CATEGORY_CODE")

    category = db.new_record(
        fee_program_id=program_id,
        code=code,
        name=name,
        demand_unit_label=demand_unit_label,
        existing_los_per_demand_unit=existing_los,
        planned_los_per_demand_unit=planned_los,
        existing_deficiency_demand_units=deficiency if deficiency is not None else Decimal(0),
        unit_cost_cents=unit_cost_cents,
        fund_posture="COMPLIANT",
        fund_balance_cents=0,
        refund_due_cents=0,
        oldest_unexpended_vintage_at=None,
        committed_demand_units=Decimal(0),
        deferred_receivable_cents=0,
    )
    db.facility_categories[category["id"]] = category
    return response.object_response(serializers.facility_category(category), 201)


@bp.get("/facility-categories/<category_id>")
@guard(*ANY)
def read_facility_category(category_id):
    category = helpers.get_category(category_id)
    return response.object_response(serializers.facility_category(category))


@bp.post("/facility-categories/<category_id>/expenditures")
@guard("FinanceOfficer")
def create_expenditure(category_id):
    category = helpers.get_category(category_id)
    body = helpers.json_body()
    body.forbid_versions("expected_facility_category_version")
    amount_cents = body.integer("amount_cents", required=True, minimum=1)
    project_name = body.string("project_name", required=True, min_len=1, max_len=120)
    expected = body.integer("expected_facility_category_version", required=True)

    if expected != category["version"]:
        raise_error("ERR_STALE_CATEGORY_VERSION")
    if category["fund_posture"] == "REFUND_DUE":
        raise_error("ERR_FUND_REFUND_OBLIGATION_PENDING")
    if amount_cents > ledger.eligible_total(category["id"]):
        raise_error("ERR_INSUFFICIENT_FUND_BALANCE")

    row = ledger.record_expenditure(category, amount_cents, project_name, g.user_id)
    return response.object_response(serializers.fund_ledger_entry(row), 201)
