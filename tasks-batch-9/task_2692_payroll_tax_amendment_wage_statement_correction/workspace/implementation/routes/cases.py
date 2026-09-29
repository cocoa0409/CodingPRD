"""Correction cases, the three-way reconciliation and discrepancy triage (PRD 3.2, 3.3)."""

from flask import Blueprint

import calc
from common import (
    F, R_ADMIN, R_ANALYST, R_OFFICER, READ6,
    authenticate, db, fail, get_agency, get_case, get_discrepancy, get_employer,
    get_body, matches, new_row, now, ok, pagination, paginate, qs, qs_int,
    quarter_field, require_state, sorted_rows, tax_year_field, touch, validate,
)
from serializers import case_json, discrepancy_json

bp = Blueprint("cases", __name__)

CASE_CREATE = {
    "employer_id": F("string", True),
    "agency_id": F("string", True),
    "tax_year": tax_year_field(True),
    "quarter": quarter_field(True),
}


@bp.post("/correction-cases")
def create_case():
    actor = authenticate((R_ADMIN, R_ANALYST))
    body = get_body()
    employer = None
    if isinstance(body.get("employer_id"), str) and body["employer_id"]:
        employer = get_employer(body["employer_id"])
    if isinstance(body.get("agency_id"), str) and body["agency_id"]:
        get_agency(body["agency_id"])
    data = validate(body, CASE_CREATE)
    if employer is not None:
        actor.require_employer(employer["id"])

    row = new_row({
        "employer_id": data["employer_id"],
        "agency_id": data["agency_id"],
        "tax_year": data["tax_year"],
        "quarter": data["quarter"],
        "status": "OPEN",
        "detection_status": "NOT_RUN",
        "filing_status": "FILING_NOT_REQUIRED",
        "statement_status": "STMT_NOT_REQUIRED",
        "dominant_root_cause_code": None,
        "open_discrepancy_count": 0,
        "total_exposure_cents": 0,
        "corrected_wage_base_cents": 0,
        "repayment_recovered_cents": 0,
        "closed_at": None,
    })
    db.correction_cases[row["id"]] = row
    # corrected_wage_base_cents is seeded from the posted register lines on scope.
    row["corrected_wage_base_cents"] = calc.compute_corrected_wage_base(row)
    calc.sync_employer(db.employers.get(row["employer_id"]))
    return ok(case_json(row), 201)


@bp.get("/correction-cases/<correction_case_id>")
def read_case(correction_case_id):
    actor = authenticate(READ6)
    row = get_case(correction_case_id)
    actor.require_employer(row["employer_id"])
    return ok(case_json(row))


@bp.get("/correction-cases")
def list_cases():
    actor = authenticate(READ6)
    limit, offset = pagination()
    filters = {
        "employer_id": actor.scoped_employer(qs("employer_id")),
        "agency_id": qs("agency_id"),
        "tax_year": qs_int("tax_year"),
        "quarter": qs_int("quarter"),
        "status": qs("status"),
        "detection_status": qs("detection_status"),
        "filing_status": qs("filing_status"),
        "statement_status": qs("statement_status"),
    }
    rows = [r for r in sorted_rows(db.correction_cases.values()) if matches(r, filters)]
    return paginate(rows, limit, offset, case_json)


@bp.post("/correction-cases/<correction_case_id>/reconcile")
def reconcile_case(correction_case_id):
    authenticate((R_ADMIN, R_ANALYST))
    case = get_case(correction_case_id)
    get_body()

    if case["status"] == "CLOSED":
        fail("ERR_ALREADY_TERMINAL", "case is closed")
    if case["detection_status"] == "NO_VARIANCE":
        fail("ERR_ALREADY_TERMINAL", "reconciliation already completed with no variance")
    if case["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "reconciliation requires the case to be OPEN")
    rerun = case["detection_status"] == "VARIANCE_FOUND"
    if rerun:
        for amendment in calc.case_amendments(case["id"]):
            if amendment["status"] in ("SIGNED", "SUBMITTED", "ACCEPTED"):
                fail("ERR_INVALID_STATE",
                     "the discrepancy set is frozen once an amendment has been signed")

    agency = db.tax_agencies.get(case["agency_id"])
    emissions = calc.detect_variances(case, agency)

    if rerun:
        for row in calc.case_discrepancies(case["id"]):
            if row["status"] in ("OPEN", "CATEGORIZED"):
                row["status"] = "SUPERSEDED"
                touch(row)
        calc.emit_discrepancies(case, emissions)
    else:
        calc.emit_discrepancies(case, emissions)
        if emissions:
            case["detection_status"] = "VARIANCE_FOUND"
            categories = set(e[0] for e in emissions)
            if categories & {"TAXABLE_WAGE", "WITHHOLDING", "DEPOSIT_SHORTFALL"}:
                case["filing_status"] = "FILING_PENDING"
            if "JURISDICTION_ASSIGNMENT" in categories:
                case["statement_status"] = "STMT_PENDING"
        else:
            case["detection_status"] = "NO_VARIANCE"

    calc.sync_case(case, forced=True)
    calc.sync_employer(db.employers.get(case["employer_id"]))
    return ok(case_json(case))


@bp.post("/correction-cases/<correction_case_id>/close")
def close_case(correction_case_id):
    authenticate((R_ADMIN, R_OFFICER))
    case = get_case(correction_case_id)
    body = get_body()
    validate(body, {"closure_note": F("string", False, max_len=2000)})

    require_state(case["status"], ("REMEDIATION_PENDING",), ("CLOSED",))
    if calc.compute_open_discrepancy_count(case) != 0:
        fail("ERR_INVALID_STATE", "the case still has outstanding discrepancies")
    for rem in calc.case_remediations(case["id"]):
        if rem["status"] != "VERIFIED":
            fail("ERR_REMEDIATION_NOT_VERIFIED",
                 "every remediation on the case must be VERIFIED")
    for rep in calc.case_repayments(case["id"]):
        if rep["status"] not in calc.SETTLED_REPAYMENT_STATES:
            fail("ERR_REPAYMENT_NOT_SETTLED",
                 "every wage repayment on the case must be settled")

    case["status"] = "CLOSED"
    case["closed_at"] = now()
    calc.sync_case(case, forced=True)
    calc.sync_employer(db.employers.get(case["employer_id"]))
    return ok(case_json(case))


@bp.get("/correction-cases/<correction_case_id>/exposure-summary")
def case_exposure_summary(correction_case_id):
    actor = authenticate(READ6)
    case = get_case(correction_case_id)
    actor.require_employer(case["employer_id"])
    gross = calc.compute_gross_exposure(case)
    waived = calc.compute_waived(case)
    return ok({
        "gross_exposure_cents": gross,
        "waived_cents": waived,
        "total_exposure_cents": max(0, gross - waived),
        "corrected_wage_base_cents": calc.compute_corrected_wage_base(case),
        "repayment_recovered_cents": calc.compute_repayment_recovered(case),
        "dominant_root_cause_code": calc.compute_dominant_root_cause(case),
    })


# ---------------------------------------------------------------------------
# Discrepancies
# ---------------------------------------------------------------------------

CATEGORIES = ("TAXABLE_WAGE", "WITHHOLDING", "JURISDICTION_ASSIGNMENT", "DEPOSIT_SHORTFALL")
ROOT_CAUSES = ("RATE_TABLE_STALE", "JURISDICTION_MAPPING_ERROR", "THIRD_PARTY_FEED_ERROR",
               "MANUAL_ENTRY_ERROR", "DEPOSIT_SCHEDULING_ERROR")


def _discrepancy_employer(row):
    case = db.correction_cases.get(row["correction_case_id"])
    return case["employer_id"] if case else None


@bp.get("/discrepancies/<discrepancy_id>")
def read_discrepancy(discrepancy_id):
    actor = authenticate(READ6)
    row = get_discrepancy(discrepancy_id)
    actor.require_employer(_discrepancy_employer(row))
    return ok(discrepancy_json(row))


@bp.get("/discrepancies")
def list_discrepancies():
    actor = authenticate(READ6)
    limit, offset = pagination()
    filters = {
        "correction_case_id": qs("correction_case_id"),
        "employee_id": qs("employee_id"),
        "register_line_id": qs("register_line_id"),
        "resolved_amended_return_id": qs("resolved_amended_return_id"),
        "category": qs("category"),
        "status": qs("status"),
    }
    rows = [r for r in sorted_rows(db.discrepancies.values()) if matches(r, filters)]
    if actor.role == "EmployerRep":
        rows = [r for r in rows if _discrepancy_employer(r) == actor.user_id]
    return paginate(rows, limit, offset, discrepancy_json)


@bp.post("/discrepancies/<discrepancy_id>/categorize")
def categorize_discrepancy(discrepancy_id):
    authenticate((R_ADMIN, R_ANALYST))
    row = get_discrepancy(discrepancy_id)
    body = get_body()
    data = validate(body, {
        "category": F("string", True, enum=CATEGORIES),
        "root_cause_code": F("string", True, enum=ROOT_CAUSES),
    })
    case = db.correction_cases.get(row["correction_case_id"])
    require_state(row["status"], ("OPEN",), ("DISMISSED", "SUPERSEDED"))
    if case is None or case["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "the owning case must be OPEN")

    row["category"] = data["category"]
    row["root_cause_code"] = data["root_cause_code"]
    row["status"] = "CATEGORIZED"
    touch(row)
    calc.sync_case(case)
    calc.sync_employer(db.employers.get(case["employer_id"]))
    return ok(discrepancy_json(row))


@bp.post("/discrepancies/<discrepancy_id>/dismiss")
def dismiss_discrepancy(discrepancy_id):
    authenticate((R_ADMIN, R_ANALYST))
    row = get_discrepancy(discrepancy_id)
    body = get_body()
    data = validate(body, {"dismissal_reason": F("string", True, min_len=1, max_len=2000)})
    case = db.correction_cases.get(row["correction_case_id"])
    require_state(row["status"], ("CATEGORIZED",), ("DISMISSED", "SUPERSEDED"))
    if case is None or case["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "the owning case must be OPEN")

    row["dismissal_reason"] = data["dismissal_reason"]
    row["status"] = "DISMISSED"
    touch(row)
    filing_moved = calc.advance_filing_after_discrepancy_change(case)
    calc.sync_case(case, forced=filing_moved)
    calc.sync_employer(db.employers.get(case["employer_id"]))
    return ok(discrepancy_json(row))
