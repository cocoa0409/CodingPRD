"""Employer account surface, its reverse lookups, invoicing sweep and analytics."""

from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import auth, json_body
from response import ok, paginate
from util import (
    D,
    check_range,
    decimals_of,
    opt_bool,
    opt_enum,
    opt_int_field,
    opt_num_field,
    opt_str,
    parse_date_value,
    present,
    req_str,
)

from services.calc import utilization_report
from services.core import (
    created_key,
    new_row,
    s_employee,
    s_employer,
    s_invoice,
    s_plan,
    sort_created,
    touch,
)
from services.invoice import build_invoice, period_overlaps
from routes._common import (
    CONTRACT_STATUSES,
    ELIGIBILITY_STATUSES,
    EMPLOYMENT_STATUSES,
    INVOICE_STATUSES,
    INVOICING_CYCLES,
    PLAN_STATUSES,
    keep,
    need,
    qs_enum,
)

bp = Blueprint("employers", __name__)


def _validate_fee(body):
    fee = opt_num_field(body, "admin_fee_pct")
    if fee is not None:
        check_range(fee, 0, "0.5")
        if decimals_of(fee) > 4:
            raise ApiError("ERR_INVALID_REQUEST")
    return fee


def _employer_eligibility_filter(rows, eligibility):
    if eligibility is None:
        return rows
    from services.core import employee_eligibility

    return [r for r in rows if employee_eligibility(r) == eligibility]


@bp.post("/employers")
def create_employer():
    body = json_body()
    name = req_str(body, "name", 200)
    industry_code = req_str(body, "industry_code", 16)
    contract_status = opt_enum(body, "contract_status", CONTRACT_STATUSES)
    fiscal_month = opt_int_field(body, "fiscal_year_start_month")
    check_range(fiscal_month, 1, 12)
    invoicing_cycle = opt_enum(body, "invoicing_cycle", INVOICING_CYCLES)
    fee = _validate_fee(body)
    overage_enabled = opt_bool(body, "overage_billing_enabled")
    adult_elder = opt_bool(body, "adult_elder_extension_enabled")

    auth("network_admin", "benefits_admin")

    for row in db.employers.values():
        if row["name"] == name:
            raise ApiError("ERR_DUPLICATE_KEY")

    employer = new_row(
        {
            "name": name,
            "industry_code": industry_code,
            "contract_status": contract_status or "ACTIVE",
            "fiscal_year_start_month": 1 if fiscal_month is None else fiscal_month,
            "invoicing_cycle": invoicing_cycle or "MONTHLY",
            "admin_fee_pct": D("0.085") if fee is None else D(fee),
            "overage_billing_enabled": True if overage_enabled is None else overage_enabled,
            "adult_elder_extension_enabled": False
            if adult_elder is None
            else adult_elder,
        }
    )
    db.employers[employer["id"]] = employer
    return ok(s_employer(employer), 201)


@bp.get("/employers/<row_id>")
def get_employer(row_id):
    auth("network_admin", "benefits_admin", "care_coordinator")
    employer = need(db.employers, row_id, "ERR_EMPLOYER_NOT_FOUND")
    return ok(s_employer(employer))


@bp.get("/employers")
def list_employers():
    auth("network_admin", "benefits_admin")
    contract_status = qs_enum("contract_status", CONTRACT_STATUSES)
    rows = keep(sort_created(list(db.employers.values())), "contract_status", contract_status)
    return paginate(rows, s_employer)


@bp.patch("/employers/<row_id>")
def patch_employer(row_id):
    body = json_body()
    contract_status = opt_enum(body, "contract_status", CONTRACT_STATUSES)
    fee = _validate_fee(body)
    invoicing_cycle = opt_enum(body, "invoicing_cycle", INVOICING_CYCLES)
    overage_enabled = opt_bool(body, "overage_billing_enabled")
    adult_elder = opt_bool(body, "adult_elder_extension_enabled")
    fiscal_month = opt_int_field(body, "fiscal_year_start_month")
    check_range(fiscal_month, 1, 12)

    auth("benefits_admin")
    employer = need(db.employers, row_id, "ERR_EMPLOYER_NOT_FOUND")

    if contract_status is not None:
        employer["contract_status"] = contract_status
    if fee is not None:
        employer["admin_fee_pct"] = D(fee)
    if invoicing_cycle is not None:
        employer["invoicing_cycle"] = invoicing_cycle
    if overage_enabled is not None:
        employer["overage_billing_enabled"] = overage_enabled
    if adult_elder is not None:
        employer["adult_elder_extension_enabled"] = adult_elder
    if fiscal_month is not None:
        employer["fiscal_year_start_month"] = fiscal_month
    touch(employer)
    return ok(s_employer(employer))


@bp.get("/employers/<row_id>/benefit-plans")
def employer_plans(row_id):
    auth("network_admin", "benefits_admin", "care_coordinator")
    employer = need(db.employers, row_id, "ERR_EMPLOYER_NOT_FOUND")
    status = qs_enum("status", PLAN_STATUSES)
    rows = [p for p in db.benefit_plans.values() if p["employer_id"] == employer["id"]]
    rows = keep(rows, "status", status)
    rows = sorted(sort_created(rows), key=lambda p: p["effective_from"], reverse=True)
    return paginate(rows, s_plan)


@bp.get("/employers/<row_id>/employees")
def employer_employees(row_id):
    auth("network_admin", "benefits_admin")
    employer = need(db.employers, row_id, "ERR_EMPLOYER_NOT_FOUND")
    employment_status = qs_enum("employment_status", EMPLOYMENT_STATUSES)
    eligibility = qs_enum("eligibility_status", ELIGIBILITY_STATUSES)
    rows = [e for e in db.employees.values() if e["employer_id"] == employer["id"]]
    rows = keep(rows, "employment_status", employment_status)
    rows = _employer_eligibility_filter(rows, eligibility)
    return paginate(sort_created(rows), s_employee)


@bp.get("/employers/<row_id>/invoices")
def employer_invoices(row_id):
    auth("network_admin", "benefits_admin")
    employer = need(db.employers, row_id, "ERR_EMPLOYER_NOT_FOUND")
    invoice_status = qs_enum("invoice_status", INVOICE_STATUSES)
    rows = [
        i for i in db.employer_invoices.values() if i["employer_id"] == employer["id"]
    ]
    rows = keep(rows, "invoice_status", invoice_status)
    rows = sorted(sort_created(rows), key=lambda i: i["period_start"], reverse=True)
    return paginate(rows, s_invoice)


def _period(body_or_args, source):
    if source == "body":
        raw_start = body_or_args.get("period_start")
        raw_end = body_or_args.get("period_end")
    else:
        raw_start = body_or_args.get("period_start")
        raw_end = body_or_args.get("period_end")
    if raw_start is None or raw_end is None:
        raise ApiError("ERR_INVALID_REQUEST")
    start = parse_date_value(raw_start)
    end = parse_date_value(raw_end)
    if end < start:
        raise ApiError("ERR_INVALID_PERIOD")
    return start, end


@bp.post("/employers/<row_id>/invoices")
def create_invoice(row_id):
    body = json_body()
    period_start, period_end = _period(body, "body")
    auth("network_admin", "benefits_admin")
    employer = need(db.employers, row_id, "ERR_EMPLOYER_NOT_FOUND")
    if period_overlaps(employer["id"], period_start, period_end):
        raise ApiError("ERR_INVOICE_PERIOD_OVERLAP")
    invoice = build_invoice(employer, period_start, period_end)
    return ok(s_invoice(invoice), 201)


@bp.get("/employers/<row_id>/utilization-report")
def employer_utilization(row_id):
    period_start, period_end = _period(request.args, "args")
    auth("network_admin", "benefits_admin")
    employer = need(db.employers, row_id, "ERR_EMPLOYER_NOT_FOUND")
    return ok(utilization_report(employer, period_start, period_end))
