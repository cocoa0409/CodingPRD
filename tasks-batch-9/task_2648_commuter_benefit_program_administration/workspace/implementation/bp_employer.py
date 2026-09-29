"""Employer program setup, the monthly close and ordinance assessments."""

from flask import Blueprint

import serialize
from auth import authenticate, resolve_assessment, resolve_employer
from calc import (
    accounts_of_employer,
    assess_ordinance,
    close_account,
    recompute_commitment,
    recompute_enrolled,
)
from guards import TERMINAL_EMPLOYER, require_not_terminal, require_transition
from responses import array_response, created_response, object_response, paginate
from store import bump, sorted_rows, stamp_new, store
from validate import (
    MANDATE_STATUSES,
    ORDINANCE_STATUSES,
    PROGRAM_STATUSES,
    REGION_CODES,
    ROLLOVER_POLICIES,
    SPILL_POLICIES,
    enum_filter,
    field,
    pagination,
    parse_body,
    str_filter,
)

bp = Blueprint("employers", __name__)

ALL_ROLES = ["ProgramAdmin", "OrderDesk", "ComplianceReviewer", "PayrollProcessor",
             "Employee"]

SETUP_FIELDS = [
    field("transit_group_limit_cents", "integer", minimum=0),
    field("parking_group_limit_cents", "integer", minimum=0),
    field("program_cap_cents", "integer", minimum=0),
    field("pretax_ratio_cap_pct", "integer", minimum=0, maximum=100),
    field("spill_policy", "enum", choices=SPILL_POLICIES),
    field("rollover_policy", "enum", choices=ROLLOVER_POLICIES),
    field("rollover_cap_cents", "integer", minimum=0),
    field("forfeiture_grace_days", "integer", minimum=0),
]


@bp.post("/benefits/employers")
def create_employer():
    authenticate(["ProgramAdmin"])
    specs = [
        field("legal_name", "string", required=True, min_len=1, max_len=200),
        field("region_code", "enum", required=True, choices=REGION_CODES),
        field("transit_group_limit_cents", "integer", required=True, minimum=0),
        field("parking_group_limit_cents", "integer", required=True, minimum=0),
        field("program_cap_cents", "integer", required=True, minimum=0),
        field("pretax_ratio_cap_pct", "integer", default=100, minimum=0, maximum=100),
        field("spill_policy", "enum", default="SPILL_TO_POSTTAX", choices=SPILL_POLICIES),
        field("rollover_policy", "enum", default="CAP_ROLLOVER", choices=ROLLOVER_POLICIES),
        field("rollover_cap_cents", "integer", default=5000, minimum=0),
        field("forfeiture_grace_days", "integer", default=30, minimum=0),
    ]
    _body, values = parse_body(specs)
    row = {
        "legal_name": values["legal_name"],
        "region_code": values["region_code"],
        "transit_group_limit_cents": values["transit_group_limit_cents"],
        "parking_group_limit_cents": values["parking_group_limit_cents"],
        "pretax_ratio_cap_pct": values["pretax_ratio_cap_pct"],
        "spill_policy": values["spill_policy"],
        "rollover_policy": values["rollover_policy"],
        "rollover_cap_cents": values["rollover_cap_cents"],
        "forfeiture_grace_days": values["forfeiture_grace_days"],
        "program_cap_cents": values["program_cap_cents"],
        "program_status": "DRAFT",
        "ordinance_mandate_status": "UNASSESSED",
        "total_pretax_committed_cents": 0,
        "enrolled_employee_count": 0,
    }
    stamp_new(row)
    store.employers[row["id"]] = row
    return created_response(serialize.employer(row))


@bp.get("/benefits/employers/<employer_id>")
def read_employer(employer_id):
    authenticate(ALL_ROLES)
    row = resolve_employer(employer_id)
    return object_response(serialize.employer(row))


@bp.get("/benefits/employers")
def list_employers():
    authenticate(["ProgramAdmin", "PayrollProcessor"])
    region = enum_filter("region_code", REGION_CODES)
    status = enum_filter("program_status", PROGRAM_STATUSES)
    mandate = enum_filter("ordinance_mandate_status", ORDINANCE_STATUSES)
    limit, offset = pagination()
    rows = []
    for row in store.employers.values():
        if region is not None and row["region_code"] != region:
            continue
        if status is not None and row["program_status"] != status:
            continue
        if mandate is not None and row["ordinance_mandate_status"] != mandate:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.employer(r) for r in page], limit, offset, total)


@bp.patch("/benefits/employers/<employer_id>")
def patch_employer(employer_id):
    authenticate(["ProgramAdmin"])
    row = resolve_employer(employer_id)
    body, values = parse_body(SETUP_FIELDS)
    require_not_terminal(row, "program_status", TERMINAL_EMPLOYER, "Employer")
    for spec in SETUP_FIELDS:
        name = spec["name"]
        if name in body:
            row[name] = values[name]
    bump(row)
    return object_response(serialize.employer(row))


@bp.post("/benefits/employers/<employer_id>/activate")
def activate_employer(employer_id):
    authenticate(["ProgramAdmin"])
    row = resolve_employer(employer_id)
    require_not_terminal(row, "program_status", TERMINAL_EMPLOYER, "Employer")
    require_transition(row["program_status"] == "DRAFT",
                       "Employer %s cannot be activated from %s."
                       % (row["id"], row["program_status"]))
    has_active_category = any(
        c["employer_id"] == row["id"] and c["status"] == "ACTIVE"
        for c in store.benefit_categories.values())
    require_transition(has_active_category,
                       "Employer %s has no ACTIVE benefit category and cannot go live."
                       % row["id"])
    row["program_status"] = "ACTIVE"
    recompute_enrolled(row)
    bump(row)
    return object_response(serialize.employer(row))


@bp.post("/benefits/employers/<employer_id>/month-close")
def month_close(employer_id):
    authenticate(["ProgramAdmin"])
    employer = resolve_employer(employer_id)
    _body, values = parse_body([field("benefit_month", "month", required=True)])
    require_not_terminal(employer, "program_status", TERMINAL_EMPLOYER, "Employer")
    benefit_month = values["benefit_month"]

    windows = [w for w in store.election_windows.values()
               if w["employer_id"] == employer["id"]
               and w["status"] == "LOCKED"
               and w["benefit_month"] == benefit_month]
    for window in sorted_rows(windows):
        window["status"] = "CLOSED"
        bump(window)
        funded = [e for e in store.elections.values()
                  if e["election_window_id"] == window["id"]
                  and e["funding_status"] == "FUNDED"]
        for election in sorted_rows(funded):
            election["funding_status"] = "SETTLED"
            bump(election)

    for account in accounts_of_employer(employer["id"]):
        employee = store.employees.get(account["employee_id"])
        if close_account(account, employer, employee):
            bump(account)

    if recompute_commitment(employer):
        bump(employer)
    return object_response(serialize.employer(employer))


# ------------------------------------------------------- compliance assessments
@bp.post("/benefits/employers/<employer_id>/compliance-assessments")
def create_assessment(employer_id):
    authenticate(["ProgramAdmin", "ComplianceReviewer"])
    employer = resolve_employer(employer_id)
    _body, values = parse_body([field("assessment_month", "month", required=True)])
    verdict = assess_ordinance(employer, values["assessment_month"])
    row = {
        "employer_id": employer["id"],
        "assessment_month": values["assessment_month"],
        "covered_employee_count": verdict["covered_employee_count"],
        "qualifying_transit_offering_count":
            verdict["qualifying_transit_offering_count"],
        "assessed_transit_group_limit_cents":
            verdict["assessed_transit_group_limit_cents"],
        "mandate_status": verdict["mandate_status"],
        "finding": verdict["finding"],
    }
    stamp_new(row, versioned=False)
    store.compliance_assessments[row["id"]] = row
    employer["ordinance_mandate_status"] = verdict["mandate_status"]
    bump(employer)
    return created_response(serialize.compliance_assessment(row))


@bp.get("/benefits/employers/<employer_id>/compliance-assessments")
def list_employer_assessments(employer_id):
    authenticate(["ProgramAdmin", "ComplianceReviewer"])
    employer = resolve_employer(employer_id)
    month = str_filter("assessment_month")
    limit, offset = pagination()
    rows = [a for a in store.compliance_assessments.values()
            if a["employer_id"] == employer["id"]
            and (month is None or a["assessment_month"] == month)]
    rows = sorted_rows(rows, newest_first=True)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.compliance_assessment(r) for r in page],
                          limit, offset, total)


@bp.get("/benefits/compliance-assessments/<assessment_id>")
def read_assessment(assessment_id):
    authenticate(["ProgramAdmin", "ComplianceReviewer"])
    row = resolve_assessment(assessment_id)
    return object_response(serialize.compliance_assessment(row))


@bp.get("/benefits/compliance-assessments")
def list_assessments():
    authenticate(["ProgramAdmin", "ComplianceReviewer"])
    employer_id = str_filter("employer_id")
    month = str_filter("assessment_month")
    mandate = enum_filter("mandate_status", MANDATE_STATUSES)
    finding = enum_filter("finding", ["COMPLIANT", "EXEMPT_REGION_NOT_COVERED",
                                     "EXEMPT_BELOW_THRESHOLD",
                                     "DEFICIENT_NO_QUALIFYING_TRANSIT_OFFERING",
                                     "DEFICIENT_LIMIT_BELOW_MINIMUM"])
    limit, offset = pagination()
    rows = []
    for row in store.compliance_assessments.values():
        if employer_id is not None and row["employer_id"] != employer_id:
            continue
        if month is not None and row["assessment_month"] != month:
            continue
        if mandate is not None and row["mandate_status"] != mandate:
            continue
        if finding is not None and row["finding"] != finding:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.compliance_assessment(r) for r in page],
                          limit, offset, total)
