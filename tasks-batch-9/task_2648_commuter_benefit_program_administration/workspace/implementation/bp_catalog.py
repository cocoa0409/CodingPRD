"""Benefit category catalogue, the employee roster and the transit media catalogue."""

from flask import Blueprint

import serialize
from auth import authenticate, resolve_category, resolve_employee, resolve_media
from calc import limit_group_for, recompute_enrolled
from cascades import terminate_cascade
from errors import invalid_request
from guards import (
    TERMINAL_CATEGORY,
    TERMINAL_EMPLOYEE,
    TERMINAL_MEDIA,
    require_not_terminal,
    require_transition,
)
from responses import array_response, created_response, object_response, paginate
from store import bump, sorted_rows, stamp_new, store
from validate import (
    CATEGORY_STATUSES,
    CATEGORY_TYPES,
    EMPLOYEE_STATUSES,
    MEDIA_CATALOG_STATUSES,
    MEDIA_TYPES,
    PAYROLL_CYCLES,
    REGION_CODES,
    bool_filter,
    enum_filter,
    field,
    pagination,
    parse_body,
    str_filter,
)

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------- benefit categories
@bp.post("/benefits/benefit-categories")
def create_category():
    authenticate(["ProgramAdmin"])
    specs = [
        field("employer_id", "id", required=True),
        field("category_type", "enum", required=True, choices=CATEGORY_TYPES),
        field("monthly_exclusion_limit_cents", "integer", required=True, minimum=0),
        field("pretax_allowed", "boolean", default=True),
        field("posttax_allowed", "boolean", default=True),
    ]
    _body, values = parse_body(specs)
    from auth import resolve_employer
    employer = resolve_employer(values["employer_id"])
    row = {
        "employer_id": employer["id"],
        "category_type": values["category_type"],
        "limit_group": limit_group_for(values["category_type"]),
        "monthly_exclusion_limit_cents": values["monthly_exclusion_limit_cents"],
        "pretax_allowed": values["pretax_allowed"],
        "posttax_allowed": values["posttax_allowed"],
        "status": "ACTIVE",
    }
    stamp_new(row)
    store.benefit_categories[row["id"]] = row
    return created_response(serialize.benefit_category(row))


@bp.get("/benefits/benefit-categories/<category_id>")
def read_category(category_id):
    authenticate(["ProgramAdmin", "Employee", "OrderDesk", "ComplianceReviewer"])
    row = resolve_category(category_id)
    return object_response(serialize.benefit_category(row))


@bp.get("/benefits/benefit-categories")
def list_categories():
    authenticate(["ProgramAdmin", "Employee", "OrderDesk", "ComplianceReviewer"])
    employer_id = str_filter("employer_id")
    category_type = enum_filter("category_type", CATEGORY_TYPES)
    status = enum_filter("status", CATEGORY_STATUSES)
    limit, offset = pagination()
    rows = []
    for row in store.benefit_categories.values():
        if employer_id is not None and row["employer_id"] != employer_id:
            continue
        if category_type is not None and row["category_type"] != category_type:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.benefit_category(r) for r in page],
                          limit, offset, total)


@bp.post("/benefits/benefit-categories/<category_id>/retire")
def retire_category(category_id):
    authenticate(["ProgramAdmin"])
    row = resolve_category(category_id)
    require_not_terminal(row, "status", TERMINAL_CATEGORY, "BenefitCategory")
    require_transition(row["status"] == "ACTIVE",
                       "BenefitCategory %s cannot be retired from %s."
                       % (row["id"], row["status"]))
    row["status"] = "RETIRED"
    bump(row)
    return object_response(serialize.benefit_category(row))


# ------------------------------------------------------------------- employees
@bp.post("/benefits/employees")
def create_employee():
    authenticate(["ProgramAdmin"])
    specs = [
        field("employer_id", "id", required=True),
        field("external_ref", "string", required=True, min_len=1, max_len=64),
        field("work_region_code", "enum", required=True, choices=REGION_CODES),
        field("payroll_cycle", "enum", required=True, choices=PAYROLL_CYCLES),
        field("hire_date", "datetime", required=True),
    ]
    body, values = parse_body(specs)
    from auth import resolve_employer
    employer = resolve_employer(values["employer_id"])
    for existing in store.employees.values():
        if existing["employer_id"] == employer["id"] and \
                existing["external_ref"] == values["external_ref"]:
            invalid_request("external_ref must be unique within an employer.")
    row = {
        "employer_id": employer["id"],
        "external_ref": values["external_ref"],
        "work_region_code": values["work_region_code"],
        "payroll_cycle": values["payroll_cycle"],
        "hire_date": body["hire_date"],
        "_hire_date": values["hire_date"],
        "termination_date": None,
        "_termination_date": None,
        "status": "ACTIVE",
        "substantiation_hold": False,
        "repayment_due_cents": 0,
    }
    stamp_new(row)
    store.employees[row["id"]] = row
    recompute_enrolled(employer)
    bump(employer)
    return created_response(serialize.employee(row))


@bp.get("/benefits/employees/<employee_id>")
def read_employee(employee_id):
    authenticate(["ProgramAdmin", "Employee", "ComplianceReviewer", "PayrollProcessor"])
    row = resolve_employee(employee_id)
    return object_response(serialize.employee(row))


@bp.get("/benefits/employees")
def list_employees():
    authenticate(["ProgramAdmin", "ComplianceReviewer", "PayrollProcessor"])
    employer_id = str_filter("employer_id")
    status = enum_filter("status", EMPLOYEE_STATUSES)
    region = enum_filter("work_region_code", REGION_CODES)
    hold = bool_filter("substantiation_hold")
    limit, offset = pagination()
    rows = []
    for row in store.employees.values():
        if employer_id is not None and row["employer_id"] != employer_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if region is not None and row["work_region_code"] != region:
            continue
        if hold is not None and row["substantiation_hold"] != hold:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.employee(r) for r in page], limit, offset, total)


@bp.post("/benefits/employees/<employee_id>/terminate")
def terminate_employee(employee_id):
    authenticate(["ProgramAdmin"])
    row = resolve_employee(employee_id)
    body, values = parse_body([field("termination_date", "datetime", required=True)])
    require_not_terminal(row, "status", TERMINAL_EMPLOYEE, "Employee")
    require_transition(row["status"] == "ACTIVE",
                       "Employee %s cannot be terminated from %s."
                       % (row["id"], row["status"]))
    require_transition(
        row["_hire_date"] is None or values["termination_date"] >= row["_hire_date"],
        "termination_date must not be earlier than the employee's hire_date.")
    row["status"] = "TERMINATED"
    row["termination_date"] = body["termination_date"]
    row["_termination_date"] = values["termination_date"]
    employer = store.employers.get(row["employer_id"])
    terminate_cascade(row, employer)
    if employer is not None and recompute_enrolled(employer):
        bump(employer)
    return object_response(serialize.employee(row))


# ------------------------------------------------------------- transit media
@bp.post("/benefits/transit-media")
def create_media():
    authenticate(["OrderDesk"])
    specs = [
        field("sku", "string", required=True, min_len=1, max_len=40),
        field("media_type", "enum", required=True, choices=MEDIA_TYPES),
        field("region_code", "enum", required=True, choices=REGION_CODES),
        field("eligible_category_type", "enum", required=True, choices=CATEGORY_TYPES),
        field("unit_price_cents", "integer", required=True, minimum=0),
        field("lead_days", "integer", default=3, minimum=0),
        field("replacement_fee_cents", "integer", default=500, minimum=0),
        field("requires_physical_fulfillment", "boolean", default=True),
    ]
    _body, values = parse_body(specs)
    for existing in store.transit_media.values():
        if existing["sku"] == values["sku"]:
            invalid_request("sku must be unique across the media catalogue.")
    row = {
        "sku": values["sku"],
        "media_type": values["media_type"],
        "region_code": values["region_code"],
        "eligible_category_type": values["eligible_category_type"],
        "unit_price_cents": values["unit_price_cents"],
        "lead_days": values["lead_days"],
        "replacement_fee_cents": values["replacement_fee_cents"],
        "requires_physical_fulfillment": values["requires_physical_fulfillment"],
        "status": "ACTIVE",
    }
    stamp_new(row)
    store.transit_media[row["id"]] = row
    return created_response(serialize.transit_media(row))


@bp.get("/benefits/transit-media/<media_id>")
def read_media(media_id):
    authenticate(["ProgramAdmin", "Employee", "OrderDesk"])
    row = resolve_media(media_id)
    return object_response(serialize.transit_media(row))


@bp.get("/benefits/transit-media")
def list_media():
    authenticate(["ProgramAdmin", "Employee", "OrderDesk"])
    region = enum_filter("region_code", REGION_CODES)
    media_type = enum_filter("media_type", MEDIA_TYPES)
    eligible = enum_filter("eligible_category_type", CATEGORY_TYPES)
    status = enum_filter("status", MEDIA_CATALOG_STATUSES)
    limit, offset = pagination()
    rows = []
    for row in store.transit_media.values():
        if region is not None and row["region_code"] != region:
            continue
        if media_type is not None and row["media_type"] != media_type:
            continue
        if eligible is not None and row["eligible_category_type"] != eligible:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.transit_media(r) for r in page],
                          limit, offset, total)


@bp.post("/benefits/transit-media/<media_id>/discontinue")
def discontinue_media(media_id):
    authenticate(["OrderDesk"])
    row = resolve_media(media_id)
    require_not_terminal(row, "status", TERMINAL_MEDIA, "TransitMedia")
    require_transition(row["status"] == "ACTIVE",
                       "TransitMedia %s cannot be discontinued from %s."
                       % (row["id"], row["status"]))
    row["status"] = "DISCONTINUED"
    bump(row)
    return object_response(serialize.transit_media(row))
