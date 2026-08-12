"""Manufacturer Patient Assistance Program API (Flask)."""

import json
import os
from datetime import date, timedelta
from decimal import Decimal

from flask import Flask, request

from errors import ApiError, err
from store import db
from util import (
    get_json_body,
    get_pagination,
    iso_to_date,
    line_value_cents,
    list_and_paginate,
    new_entity,
    now_iso,
    parse_coverage_pct,
    parse_decimal4,
    parse_iso_datetime,
    public,
    require_auth,
    require_bool,
    require_enum,
    require_fields,
    require_int,
    require_iso_date,
    require_role,
    require_string,
    optional_int,
    optional_string,
    round_half_up_int,
    round_half_up_2dp_str,
    success_list,
    success_object,
    today_date,
    touch,
)

app = Flask(__name__)

FPL_BASE_CENTS = 1565000
FPL_ADDITIONAL_CENTS = 550000
FPL_THRESHOLD_UNINSURED_PCT = Decimal("400.00")
FPL_THRESHOLD_UNDERINSURED_PCT = Decimal("500.00")

INSURANCE_STATUSES = {
    "UNINSURED", "UNDERINSURED", "INSURED_COMMERCIAL", "MEDICARE", "MEDICAID"
}
INCOME_BASES = {"YTD_ANNUALIZED", "PRIOR_YEAR"}
DOC_TYPES = {"PROOF_OF_INCOME", "IDENTITY", "INSURANCE_VERIFICATION", "OTHER"}
CIRCUMSTANCE_TYPES = {"INCOME_CHANGE", "INSURANCE_CHANGE", "HOUSEHOLD_CHANGE"}
DESTINATIONS = {"PROVIDER", "PATIENT"}


# ---------------------------------------------------------------------------
# error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def _api_error(e):
    from util import error_response
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _not_found(e):
    from util import error_response
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def _method_not_allowed(e):
    from util import error_response
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def _unhandled(e):
    from util import error_response
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    # In production you'd log this; here map to 400 for safety
    return error_response("ERR_INVALID_REQUEST", 400, "Bad request")


# ---------------------------------------------------------------------------
# computed program fields
# ---------------------------------------------------------------------------

def recompute_program_totals(program):
    """Recompute total_allocated_cents, total_disbursed_cents, total_committed_cents, posture."""
    prog_id = program["id"]
    allocated = sum(
        bp["allocated_cents"] for bp in db.budget_periods.values()
        if bp["program_id"] == prog_id
    )
    disbursed = sum(
        e["disbursed_cents"] for e in db.enrollments.values()
        if e["program_id"] == prog_id
    )
    committed = sum(
        e["benefit_cap_cents"] - e["disbursed_cents"]
        for e in db.enrollments.values()
        if e["program_id"] == prog_id and e["status"] in ("ACTIVE", "SUSPENDED")
    )
    program["total_allocated_cents"] = allocated
    program["total_disbursed_cents"] = disbursed
    program["total_committed_cents"] = committed
    program["posture"] = posture_for(committed, disbursed, allocated)


def utilization_pcts(committed, disbursed, allocated):
    if allocated == 0:
        return Decimal("0.00"), Decimal("0.00")
    committed_basis = (Decimal(committed + disbursed) * 100) / Decimal(allocated)
    disbursed_basis = (Decimal(disbursed) * 100) / Decimal(allocated)
    return (
        Decimal(round_half_up_2dp_str(committed_basis)),
        Decimal(round_half_up_2dp_str(disbursed_basis)),
    )


def posture_for(committed, disbursed, allocated):
    cb, _ = utilization_pcts(committed, disbursed, allocated)
    if cb >= Decimal("100.00"):
        return "EXHAUSTED"
    if cb >= Decimal("90.00"):
        return "RESTRICTED"
    return "OPEN"


def touch_program(program):
    recompute_program_totals(program)
    touch(program)


# ---------------------------------------------------------------------------
# programs
# ---------------------------------------------------------------------------

PROGRAM_FIELDS = [
    "name", "product_name", "unit_cost_per_unit",
    "max_units_per_enrollment", "max_units_per_shipment",
    "max_annual_benefit_cents", "enrollment_duration_days",
    "screening_validity_days", "appeal_window_days",
    "renewal_window_days", "lot_expiry_buffer_days",
    "allow_patient_direct_shipment",
]


def validate_program_payload(body, partial=False):
    out = {}
    if not partial or "name" in body:
        out["name"] = require_string(body, "name")
    if not partial or "product_name" in body:
        out["product_name"] = require_string(body, "product_name")
    if not partial or "unit_cost_per_unit" in body:
        v = body.get("unit_cost_per_unit")
        d = parse_decimal4(v)
        if d is None:
            raise err("ERR_INVALID_REQUEST", 400, "unit_cost_per_unit must be a decimal string with exactly 4 fraction digits")
        out["unit_cost_per_unit"] = v
    for f in ("max_units_per_enrollment", "max_units_per_shipment", "enrollment_duration_days",
              "screening_validity_days", "appeal_window_days", "renewal_window_days",
              "lot_expiry_buffer_days"):
        if not partial or f in body:
            out[f] = require_int(body, f, minimum=0)
    if not partial or "max_annual_benefit_cents" in body:
        out["max_annual_benefit_cents"] = require_int(body, "max_annual_benefit_cents", minimum=0)
    if not partial or "allow_patient_direct_shipment" in body:
        out["allow_patient_direct_shipment"] = require_bool(body, "allow_patient_direct_shipment")
    return out


@app.route("/pap/programs", methods=["POST"])
def create_program():
    require_role("ProgramAdministrator")
    body = get_json_body()
    fields = validate_program_payload(body, partial=False)
    prog = new_entity(extra=dict(
        **fields,
        posture="OPEN",
        total_allocated_cents=0,
        total_committed_cents=0,
        total_disbursed_cents=0,
    ))
    db.programs[prog["id"]] = prog
    return success_object(public(prog), status=201)


@app.route("/pap/programs", methods=["GET"])
def list_programs():
    require_auth()
    return list_and_paginate(list(db.programs.values()))


@app.route("/pap/programs/<pid>", methods=["GET"])
def get_program(pid):
    require_auth()
    prog = db.programs.get(pid)
    if not prog:
        raise err("ERR_NOT_FOUND", 404, "Program not found")
    recompute_program_totals(prog)
    return success_object(public(prog))


@app.route("/pap/programs/<pid>", methods=["PUT"])
def update_program(pid):
    require_role("ProgramAdministrator")
    body = get_json_body()
    prog = db.programs.get(pid)
    if not prog:
        raise err("ERR_NOT_FOUND", 404, "Program not found")
    if "expected_program_version" not in body:
        raise err("ERR_INVALID_REQUEST", 400, "expected_program_version is required")
    expected = body["expected_program_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", 400, "expected_program_version must be an integer")
    if expected != prog["version"]:
        raise err("ERR_STALE_VERSION", 412, "Stale program version")
    fields = validate_program_payload(body, partial=True)
    for k, v in fields.items():
        prog[k] = v
    touch(prog)
    recompute_program_totals(prog)
    return success_object(public(prog))


@app.route("/pap/programs/<pid>/utilization", methods=["GET"])
def program_utilization(pid):
    require_auth()
    prog = db.programs.get(pid)
    if not prog:
        raise err("ERR_NOT_FOUND", 404, "Program not found")
    recompute_program_totals(prog)
    committed = prog["total_committed_cents"]
    disbursed = prog["total_disbursed_cents"]
    allocated = prog["total_allocated_cents"]
    cb, dbd = utilization_pcts(committed, disbursed, allocated)
    active_count = sum(
        1 for e in db.enrollments.values()
        if e["program_id"] == pid and e["status"] == "ACTIVE"
    )
    open_app_count = sum(
        1 for a in db.applications.values()
        if a["program_id"] == pid and a["status"] in ("SUBMITTED", "UNDER_REVIEW", "MORE_INFO_REQUESTED")
    )
    payload = {
        "allocated_cents": allocated,
        "committed_cents": committed,
        "disbursed_cents": disbursed,
        "utilization_committed_basis_pct": str(cb),
        "utilization_disbursed_basis_pct": str(dbd),
        "posture": prog["posture"],
        "active_enrollment_count": active_count,
        "open_application_count": open_app_count,
    }
    return success_object(payload)


# ---------------------------------------------------------------------------
# budget periods
# ---------------------------------------------------------------------------

@app.route("/pap/budget-periods", methods=["POST"])
def create_budget_period():
    require_role("ProgramAdministrator")
    body = get_json_body()
    require_fields(body, ["program_id", "period_start", "period_end", "allocated_cents"])
    program_id = body["program_id"]
    period_start = require_iso_date(body, "period_start")
    period_end = require_iso_date(body, "period_end")
    allocated_cents = require_int(body, "allocated_cents", minimum=0)
    # date range sanity: period_end >= period_start (schema, priority 3)
    if iso_to_date(period_end) < iso_to_date(period_start):
        raise err("ERR_INVALID_REQUEST", 400, "period_end must be on or after period_start")
    prog = db.programs.get(program_id)
    if not prog:
        raise err("ERR_NOT_FOUND", 404, "Program not found")
    s = iso_to_date(period_start)
    e = iso_to_date(period_end)
    for bp in db.budget_periods.values():
        if bp["program_id"] != program_id:
            continue
        s2 = iso_to_date(bp["period_start"])
        e2 = iso_to_date(bp["period_end"])
        # overlap iff NOT (e < s2 OR s > e2)
        if not (e < s2 or s > e2):
            raise err("ERR_BUDGET_PERIOD_OVERLAP", 409, "Budget period overlaps existing period")
    bp = new_entity(extra=dict(
        program_id=program_id,
        period_start=period_start,
        period_end=period_end,
        allocated_cents=allocated_cents,
        committed_cents=0,
        disbursed_cents=0,
        status="OPEN",
    ))
    db.budget_periods[bp["id"]] = bp
    touch_program(prog)
    return success_object(public(bp), status=201)


@app.route("/pap/budget-periods", methods=["GET"])
def list_budget_periods():
    require_auth()
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(db.budget_periods.values())
    if program_id:
        items = [b for b in items if b["program_id"] == program_id]
    if status:
        items = [b for b in items if b["status"] == status]
    return list_and_paginate(items)


@app.route("/pap/budget-periods/<bid>", methods=["GET"])
def get_budget_period(bid):
    require_auth()
    bp = db.budget_periods.get(bid)
    if not bp:
        raise err("ERR_NOT_FOUND", 404, "Budget period not found")
    return success_object(public(bp))


@app.route("/pap/budget-periods/<bid>/close", methods=["POST"])
def close_budget_period(bid):
    require_role("ProgramAdministrator")
    bp = db.budget_periods.get(bid)
    if not bp:
        raise err("ERR_NOT_FOUND", 404, "Budget period not found")
    if bp["status"] != "OPEN":
        raise err("ERR_BUDGET_PERIOD_NOT_OPEN", 409, "Budget period is not OPEN")
    bp["status"] = "CLOSED"
    touch(bp)
    return success_object(public(bp))


# ---------------------------------------------------------------------------
# patients / prescribers
# ---------------------------------------------------------------------------

@app.route("/pap/patients", methods=["POST"])
def create_patient():
    require_role("CaseWorker", "ProgramAdministrator")
    body = get_json_body()
    require_fields(body, ["full_name", "date_of_birth", "state_code"])
    full_name = require_string(body, "full_name")
    dob = require_iso_date(body, "date_of_birth")
    state_code = require_string(body, "state_code")
    p = new_entity(extra=dict(full_name=full_name, date_of_birth=dob, state_code=state_code))
    db.patients[p["id"]] = p
    return success_object(public(p), status=201)


@app.route("/pap/patients/<pid>", methods=["GET"])
def get_patient(pid):
    require_auth()
    p = db.patients.get(pid)
    if not p:
        raise err("ERR_NOT_FOUND", 404, "Patient not found")
    return success_object(public(p))


@app.route("/pap/prescribers", methods=["POST"])
def create_prescriber():
    require_role("CaseWorker", "ProgramAdministrator")
    body = get_json_body()
    require_fields(body, ["full_name", "npi_number", "state_code"])
    full_name = require_string(body, "full_name")
    npi_number = require_string(body, "npi_number")
    state_code = require_string(body, "state_code")
    p = new_entity(extra=dict(full_name=full_name, npi_number=npi_number, state_code=state_code))
    db.prescribers[p["id"]] = p
    return success_object(public(p), status=201)


@app.route("/pap/prescribers/<pid>", methods=["GET"])
def get_prescriber(pid):
    require_auth()
    p = db.prescribers.get(pid)
    if not p:
        raise err("ERR_NOT_FOUND", 404, "Prescriber not found")
    return success_object(public(p))


# ---------------------------------------------------------------------------
# screenings
# ---------------------------------------------------------------------------

def compute_screening_fields(household_size, income_basis, ytd_income_cents,
                             ytd_months_elapsed, prior_year_income_cents):
    if income_basis == "YTD_ANNUALIZED":
        annualized = round_half_up_int(
            (Decimal(ytd_income_cents) / Decimal(ytd_months_elapsed)) * Decimal(12)
        )
    else:
        annualized = prior_year_income_cents
    fpl_limit = FPL_BASE_CENTS + FPL_ADDITIONAL_CENTS * (household_size - 1)
    pct = (Decimal(annualized) * 100) / Decimal(fpl_limit)
    fpl_percent = round_half_up_2dp_str(pct)
    return annualized, fpl_limit, fpl_percent


def eligibility_determination(insurance_status, insurance_coverage_pct, fpl_percent_str):
    fpl_pct = Decimal(fpl_percent_str)
    if insurance_status == "UNINSURED":
        return "ELIGIBLE" if fpl_pct <= FPL_THRESHOLD_UNINSURED_PCT else "INELIGIBLE"
    if insurance_status == "UNDERINSURED":
        cov = Decimal(insurance_coverage_pct)
        if fpl_pct <= FPL_THRESHOLD_UNDERINSURED_PCT and cov < Decimal("1.00"):
            return "ELIGIBLE"
        return "INELIGIBLE"
    return "INELIGIBLE"


@app.route("/pap/screenings", methods=["POST"])
def create_screening():
    uid, _ = require_role("Patient")
    body = get_json_body()
    require_fields(body, ["patient_id", "program_id", "household_size", "income_basis", "insurance_status"])
    patient_id = body["patient_id"]
    program_id = body["program_id"]
    household_size = require_int(body, "household_size", minimum=1)
    income_basis = require_enum(body, "income_basis", INCOME_BASES)
    insurance_status = require_enum(body, "insurance_status", INSURANCE_STATUSES)

    ytd_income_cents = body.get("ytd_income_cents")
    ytd_months_elapsed = body.get("ytd_months_elapsed")
    prior_year_income_cents = body.get("prior_year_income_cents")
    insurance_coverage_pct = body.get("insurance_coverage_pct")

    # conditional inputs
    if income_basis == "YTD_ANNUALIZED":
        if ytd_income_cents is None or ytd_months_elapsed is None:
            raise err("ERR_INVALID_REQUEST", 400, "ytd_income_cents and ytd_months_elapsed required for YTD_ANNUALIZED")
        if isinstance(ytd_income_cents, bool) or not isinstance(ytd_income_cents, int):
            raise err("ERR_INVALID_REQUEST", 400, "ytd_income_cents must be an integer")
        if isinstance(ytd_months_elapsed, bool) or not isinstance(ytd_months_elapsed, int):
            raise err("ERR_INVALID_REQUEST", 400, "ytd_months_elapsed must be an integer")
        if ytd_months_elapsed < 1 or ytd_months_elapsed > 12:
            raise err("ERR_INVALID_REQUEST", 400, "ytd_months_elapsed must be 1..12")
        if prior_year_income_cents is not None:
            raise err("ERR_INVALID_REQUEST", 400, "prior_year_income_cents must not be supplied for YTD_ANNUALIZED")
    else:  # PRIOR_YEAR
        if prior_year_income_cents is None:
            raise err("ERR_INVALID_REQUEST", 400, "prior_year_income_cents required for PRIOR_YEAR")
        if isinstance(prior_year_income_cents, bool) or not isinstance(prior_year_income_cents, int):
            raise err("ERR_INVALID_REQUEST", 400, "prior_year_income_cents must be an integer")
        if ytd_income_cents is not None or ytd_months_elapsed is not None:
            raise err("ERR_INVALID_REQUEST", 400, "ytd fields must not be supplied for PRIOR_YEAR")

    if insurance_status == "UNDERINSURED":
        if insurance_coverage_pct is None:
            raise err("ERR_INVALID_REQUEST", 400, "insurance_coverage_pct required for UNDERINSURED")
        if parse_coverage_pct(insurance_coverage_pct) is None:
            raise err("ERR_INVALID_REQUEST", 400, "insurance_coverage_pct must be a decimal 0.00..0.99")
    else:
        if insurance_coverage_pct is not None:
            raise err("ERR_INVALID_REQUEST", 400, "insurance_coverage_pct must not be supplied unless UNDERINSURED")

    # ownership: Patient may act only on own resources (patient_id == X-User-ID)
    if patient_id != uid:
        raise err("ERR_OWNERSHIP_VIOLATION", 403, "Patient may only create screenings for self")
    # existence
    if patient_id not in db.patients:
        raise err("ERR_NOT_FOUND", 404, "Patient not found")
    if program_id not in db.programs:
        raise err("ERR_NOT_FOUND", 404, "Program not found")

    annualized, fpl_limit, fpl_percent = compute_screening_fields(
        household_size, income_basis, ytd_income_cents, ytd_months_elapsed, prior_year_income_cents
    )

    s = new_entity(extra=dict(
        patient_id=patient_id,
        program_id=program_id,
        household_size=household_size,
        income_basis=income_basis,
        ytd_income_cents=ytd_income_cents if income_basis == "YTD_ANNUALIZED" else None,
        ytd_months_elapsed=ytd_months_elapsed if income_basis == "YTD_ANNUALIZED" else None,
        prior_year_income_cents=prior_year_income_cents if income_basis == "PRIOR_YEAR" else None,
        insurance_status=insurance_status,
        insurance_coverage_pct=insurance_coverage_pct if insurance_status == "UNDERINSURED" else None,
        annualized_income_cents=annualized,
        fpl_limit_cents=fpl_limit,
        fpl_percent=fpl_percent,
        eligibility_determination=None,
        status="DRAFT",
        verified_at=None,
        rejection_reason=None,
    ))
    db.screenings[s["id"]] = s
    return success_object(public(s), status=201)


@app.route("/pap/screenings", methods=["GET"])
def list_screenings():
    require_auth()
    patient_id = request.args.get("patient_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(db.screenings.values())
    if patient_id:
        items = [s for s in items if s["patient_id"] == patient_id]
    if program_id:
        items = [s for s in items if s["program_id"] == program_id]
    if status:
        items = [s for s in items if s["status"] == status]
    return list_and_paginate(items)


@app.route("/pap/screenings/<sid>", methods=["GET"])
def get_screening(sid):
    require_auth()
    s = db.screenings.get(sid)
    if not s:
        raise err("ERR_NOT_FOUND", 404, "Screening not found")
    return success_object(public(s))


def required_doc_types(insurance_status):
    base = {"PROOF_OF_INCOME", "IDENTITY"}
    if insurance_status != "UNINSURED":
        base.add("INSURANCE_VERIFICATION")
    return base


@app.route("/pap/screenings/<sid>/submit", methods=["POST"])
def submit_screening(sid):
    uid, _ = require_role("Patient")
    s = db.screenings.get(sid)
    if not s:
        raise err("ERR_NOT_FOUND", 404, "Screening not found")
    if s["patient_id"] != uid:
        raise err("ERR_OWNERSHIP_VIOLATION", 403, "Caller does not own screening")
    if s["status"] != "DRAFT":
        raise err("ERR_SCREENING_NOT_DRAFT", 409, "Screening is not DRAFT")
    # doc completeness
    docs = [d for d in db.documents.values() if d["screening_id"] == sid]
    have = {d["doc_type"] for d in docs}
    need = required_doc_types(s["insurance_status"])
    if not need.issubset(have):
        raise err("ERR_DOCUMENTS_INCOMPLETE", 409, "Required document types missing")
    s["status"] = "SUBMITTED"
    touch(s)
    return success_object(public(s))


@app.route("/pap/screenings/<sid>/decision", methods=["POST"])
def screening_decision(sid):
    uid, _ = require_role("CaseWorker")
    body = get_json_body()
    decision = require_enum(body, "decision", {"VERIFIED", "REJECTED"})
    s = db.screenings.get(sid)
    if not s:
        raise err("ERR_NOT_FOUND", 404, "Screening not found")
    if s["status"] != "SUBMITTED":
        raise err("ERR_SCREENING_NOT_SUBMITTED", 409, "Screening is not SUBMITTED")
    if decision == "VERIFIED":
        docs = [d for d in db.documents.values() if d["screening_id"] == sid]
        if any(d["status"] != "ACCEPTED" for d in docs):
            raise err("ERR_DOCUMENTS_NOT_ACCEPTED", 409, "All documents must be ACCEPTED")
        determination = eligibility_determination(
            s["insurance_status"], s["insurance_coverage_pct"], s["fpl_percent"]
        )
        if determination != "ELIGIBLE":
            raise err("ERR_PATIENT_INELIGIBLE", 422, "Computed eligibility is INELIGIBLE")
        s["eligibility_determination"] = "ELIGIBLE"
        s["verified_at"] = now_iso()
        s["status"] = "VERIFIED"
        s["rejection_reason"] = None
    else:  # REJECTED
        reason = body.get("rejection_reason")
        if not isinstance(reason, str) or not reason:
            raise err("ERR_INVALID_REQUEST", 400, "rejection_reason is required for REJECTED")
        s["status"] = "REJECTED"
        s["rejection_reason"] = reason
    touch(s)
    return success_object(public(s))


@app.route("/pap/screenings/<sid>/revise", methods=["POST"])
def revise_screening(sid):
    uid, _ = require_role("Patient")
    s = db.screenings.get(sid)
    if not s:
        raise err("ERR_NOT_FOUND", 404, "Screening not found")
    if s["patient_id"] != uid:
        raise err("ERR_OWNERSHIP_VIOLATION", 403, "Caller does not own screening")
    if s["status"] != "REJECTED":
        raise err("ERR_SCREENING_NOT_REJECTED", 409, "Screening is not REJECTED")
    s["status"] = "DRAFT"
    s["verified_at"] = None
    s["rejection_reason"] = None
    s["eligibility_determination"] = None
    touch(s)
    return success_object(public(s))


# ---------------------------------------------------------------------------
# screening documents
# ---------------------------------------------------------------------------

@app.route("/pap/screenings/<sid>/documents", methods=["POST"])
def upload_document(sid):
    uid, _ = require_role("Patient")
    s = db.screenings.get(sid)
    if not s:
        raise err("ERR_NOT_FOUND", 404, "Screening not found")
    body = get_json_body()
    require_fields(body, ["doc_type", "file_reference"])
    doc_type = require_enum(body, "doc_type", DOC_TYPES)
    file_reference = require_string(body, "file_reference")
    # ownership
    if s["patient_id"] != uid:
        raise err("ERR_OWNERSHIP_VIOLATION", 403, "Caller does not own screening")
    # state: only DRAFT or SUBMITTED
    if s["status"] not in ("DRAFT", "SUBMITTED"):
        raise err("ERR_SCREENING_NOT_DRAFT", 409, "Documents may be uploaded only while DRAFT or SUBMITTED")
    d = new_entity(extra=dict(
        screening_id=sid,
        doc_type=doc_type,
        file_reference=file_reference,
        status="PENDING",
        review_note=None,
    ))
    db.documents[d["id"]] = d
    return success_object(public(d), status=201)


@app.route("/pap/screenings/<sid>/documents", methods=["GET"])
def list_documents(sid):
    require_auth()
    if sid not in db.screenings:
        raise err("ERR_NOT_FOUND", 404, "Screening not found")
    items = [d for d in db.documents.values() if d["screening_id"] == sid]
    return list_and_paginate(items)


@app.route("/pap/documents/<did>/review", methods=["POST"])
def review_document(did):
    require_role("CaseWorker")
    d = db.documents.get(did)
    if not d:
        raise err("ERR_NOT_FOUND", 404, "Document not found")
    body = get_json_body()
    decision = require_enum(body, "decision", {"ACCEPTED", "REJECTED"})
    if d["status"] != "PENDING":
        raise err("ERR_DOCUMENT_NOT_PENDING", 409, "Document is not PENDING")
    note = optional_string(body, "review_note")
    d["status"] = decision
    if note is not None:
        d["review_note"] = note
    touch(d)
    return success_object(public(d))


# ---------------------------------------------------------------------------
# applications
# ---------------------------------------------------------------------------

def _check_duplicate_benefit(patient_id, program_id, start_date, end_date, exclude_enrollment_id=None):
    """ERR_DUPLICATE_BENEFIT_ACTIVE if any ACTIVE/SUSPENDED enrollment (other than exclude id)
    exists for (patient, program), or any ACTIVE copay card overlaps [start, end]."""
    for e in db.enrollments.values():
        if e["patient_id"] != patient_id or e["program_id"] != program_id:
            continue
        if e["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if exclude_enrollment_id and e["id"] == exclude_enrollment_id:
            continue
        raise err("ERR_DUPLICATE_BENEFIT_ACTIVE", 409, "Existing ACTIVE/SUSPENDED enrollment for patient+program")
    for c in db.copay_cards.values():
        if c["patient_id"] != patient_id or c["program_id"] != program_id:
            continue
        if c["status"] != "ACTIVE":
            continue
        cs = iso_to_date(c["coverage_start"])
        ce = iso_to_date(c["coverage_end"])
        if not (ce < start_date or cs > end_date):
            raise err("ERR_DUPLICATE_BENEFIT_ACTIVE", 409, "Overlapping ACTIVE copay card for patient+program")


def _find_open_period_containing(program_id, today):
    """Return the OPEN BudgetPeriod of the program whose interval contains today, else None."""
    for bp in db.budget_periods.values():
        if bp["program_id"] != program_id or bp["status"] != "OPEN":
            continue
        s = iso_to_date(bp["period_start"])
        e = iso_to_date(bp["period_end"])
        if s <= today <= e:
            return bp
    return None


def _compute_benefit_cap(program, screening):
    unit_cost = parse_decimal4(program["unit_cost_per_unit"])
    unit_cents = round_half_up_int(unit_cost * Decimal(100))
    product_axis = program["max_units_per_enrollment"] * unit_cents
    base_cap = min(program["max_annual_benefit_cents"], product_axis)
    if screening["insurance_status"] == "UNDERINSURED":
        cov = parse_coverage_pct(screening["insurance_coverage_pct"])
        cap = round_half_up_int(Decimal(base_cap) * (Decimal(1) - cov))
    else:
        cap = base_cap
    return cap


def _release_enrollment_commitment(enrollment):
    """Release remaining commitment (benefit_cap - disbursed) from period and program totals."""
    released = enrollment["benefit_cap_cents"] - enrollment["disbursed_cents"]
    period = db.budget_periods.get(enrollment["commitment_budget_period_id"])
    if period:
        period["committed_cents"] -= released
        touch(period)
    prog = db.programs.get(enrollment["program_id"])
    if prog:
        touch_program(prog)


def _cancel_reserved_shipments_for(enrollment, reason=None):
    cancelled_ids = []
    for sh in db.shipments.values():
        if sh["enrollment_id"] != enrollment["id"] or sh["status"] != "RESERVED":
            continue
        _cancel_shipment(sh, enrollment, reason=reason)
        cancelled_ids.append(sh["id"])
    return cancelled_ids


def _cancel_shipment(shipment, enrollment, reason=None):
    for line in db.shipment_lines.values():
        if line["shipment_id"] != shipment["id"]:
            continue
        lot = db.inventory_lots.get(line["lot_id"])
        if lot:
            lot["quantity_reserved"] -= line["quantity"]
            lot["quantity_on_hand"] += line["quantity"]
            touch(lot)
        line["dispensed_quantity"] = line.get("dispensed_quantity", 0)
        touch(line)
    shipment["status"] = "CANCELLED"
    if reason is not None:
        shipment["status_reason"] = reason
    enrollment["remaining_units"] += shipment["quantity_units"]
    touch(enrollment)
    touch(shipment)


def _create_enrollment_for(application, is_renewal, prior_enrollment):
    """All fiscal gates already passed. Creates enrollment and commits budget."""
    program = db.programs[application["program_id"]]
    screening = db.screenings[application["screening_id"]]
    today = today_date()
    if is_renewal and prior_enrollment is not None:
        start_date = iso_to_date(prior_enrollment["end_date"]) + timedelta(days=1)
    else:
        start_date = today
    end_date = start_date + timedelta(days=program["enrollment_duration_days"] - 1)
    cap = _compute_benefit_cap(program, screening)
    period = _find_open_period_containing(application["program_id"], today)
    enr = new_entity(extra=dict(
        patient_id=application["patient_id"],
        program_id=application["program_id"],
        application_id=application["id"],
        commitment_budget_period_id=period["id"],
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        benefit_cap_cents=cap,
        cap_units=program["max_units_per_enrollment"],
        disbursed_cents=0,
        remaining_units=program["max_units_per_enrollment"],
        status="ACTIVE",
        status_reason=None,
    ))
    db.enrollments[enr["id"]] = enr
    period["committed_cents"] += cap
    touch(period)
    return enr


def _run_approval_gates(application, program, screening, is_renewal, prior_enrollment, new_start, new_end):
    """Runs all approval gates in priority order. Raises on failure.

    Caller has already verified application state and reviewer match.
    """
    # screening VERIFIED
    if screening["status"] != "VERIFIED":
        raise err("ERR_SCREENING_NOT_VERIFIED", 409, "Screening must be VERIFIED")
    # screening freshness
    verified_date = iso_to_date(screening["verified_at"])
    if today_date() > verified_date + timedelta(days=program["screening_validity_days"]):
        raise err("ERR_SCREENING_STALE", 409, "Screening is stale")
    # duplication of benefits
    exclude_id = prior_enrollment["id"] if (is_renewal and prior_enrollment) else None
    _check_duplicate_benefit(application["patient_id"], application["program_id"],
                             new_start, new_end, exclude_enrollment_id=exclude_id)
    # renewal-source check
    if is_renewal:
        if not prior_enrollment:
            raise err("ERR_NOT_FOUND", 404, "Prior enrollment not found")
        if prior_enrollment["status"] != "ACTIVE":
            raise err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Renewal source enrollment is not ACTIVE")
    # fiscal gates in fixed order
    recompute_program_totals(program)
    # 1) posture EXHAUSTED blocks all
    if program["posture"] == "EXHAUSTED":
        raise err("ERR_PROGRAM_BUDGET_EXHAUSTED", 402, "Program budget exhausted")
    # 2) posture RESTRICTED blocks fresh approvals
    if program["posture"] == "RESTRICTED" and not is_renewal:
        raise err("ERR_PROGRAM_RESTRICTED", 403, "Program restricted; only renewals allowed")
    # 3) OPEN period containing today
    period = _find_open_period_containing(program["id"], today_date())
    if period is None:
        raise err("ERR_NO_OPEN_BUDGET_PERIOD", 409, "No OPEN budget period contains today")
    # 4) sufficiency: committed + disbursed + new cap <= allocated
    #    For renewals, release prior remaining commitment first.
    new_cap = _compute_benefit_cap(program, screening)
    committed = program["total_committed_cents"]
    disbursed = program["total_disbursed_cents"]
    if is_renewal and prior_enrollment is not None:
        committed -= (prior_enrollment["benefit_cap_cents"] - prior_enrollment["disbursed_cents"])
    if committed + disbursed + new_cap > program["total_allocated_cents"]:
        raise err("ERR_INSUFFICIENT_PROGRAM_BUDGET", 402, "Insufficient program budget")


@app.route("/pap/applications", methods=["POST"])
def create_application():
    uid, _ = require_role("Patient")
    body = get_json_body()
    require_fields(body, ["patient_id", "program_id", "screening_id"])
    patient_id = body["patient_id"]
    program_id = body["program_id"]
    screening_id = body["screening_id"]
    # ownership
    if patient_id != uid:
        raise err("ERR_OWNERSHIP_VIOLATION", 403, "Patient may only apply for self")
    # existence
    if patient_id not in db.patients:
        raise err("ERR_NOT_FOUND", 404, "Patient not found")
    if program_id not in db.programs:
        raise err("ERR_NOT_FOUND", 404, "Program not found")
    screening = db.screenings.get(screening_id)
    if not screening:
        raise err("ERR_NOT_FOUND", 404, "Screening not found")
    # screening VERIFIED (§2.7 tier 7: source-state legality)
    if screening["status"] != "VERIFIED":
        raise err("ERR_SCREENING_NOT_VERIFIED", 409, "Screening must be VERIFIED")
    # staleness (§2.7 tier 9: temporal windows)
    program = db.programs[program_id]
    verified_date = iso_to_date(screening["verified_at"])
    if today_date() > verified_date + timedelta(days=program["screening_validity_days"]):
        raise err("ERR_SCREENING_STALE", 409, "Screening is stale")
    # one non-terminal fresh application per (patient, program) (tier 10: uniqueness)
    for a in db.applications.values():
        if (a["patient_id"] == patient_id and a["program_id"] == program_id
                and a.get("renewal_of_enrollment_id") is None
                and a["status"] in ("SUBMITTED", "UNDER_REVIEW", "MORE_INFO_REQUESTED")):
            raise err("ERR_APPLICATION_ALREADY_EXISTS", 409, "Non-terminal application exists for patient+program")
    # cross-reference: screening.patient/program match application's (tier 11)
    if screening["patient_id"] != patient_id or screening["program_id"] != program_id:
        raise err("ERR_SCREENING_MISMATCH", 422, "Screening does not match patient/program")
    app_obj = new_entity(extra=dict(
        patient_id=patient_id,
        program_id=program_id,
        screening_id=screening_id,
        renewal_of_enrollment_id=None,
        status="SUBMITTED",
        reviewer_id=None,
        info_request_note=None,
        decision_reason=None,
        decided_at=None,
        approved_via_appeal=False,
        enrollment_id=None,
    ))
    db.applications[app_obj["id"]] = app_obj
    return success_object(public(app_obj), status=201)


@app.route("/pap/applications", methods=["GET"])
def list_applications():
    require_auth()
    items = list(db.applications.values())
    for f in ("patient_id", "program_id", "screening_id", "enrollment_id",
              "renewal_of_enrollment_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if str(a.get(f)) == v]
    return list_and_paginate(items)


@app.route("/pap/applications/<aid>", methods=["GET"])
def get_application(aid):
    require_auth()
    a = db.applications.get(aid)
    if not a:
        raise err("ERR_NOT_FOUND", 404, "Application not found")
    return success_object(public(a))


@app.route("/pap/applications/<aid>/claim", methods=["POST"])
def claim_application(aid):
    uid, _ = require_role("CaseWorker")
    a = db.applications.get(aid)
    if not a:
        raise err("ERR_NOT_FOUND", 404, "Application not found")
    if a["status"] != "SUBMITTED":
        raise err("ERR_APPLICATION_NOT_SUBMITTED", 409, "Application not SUBMITTED")
    a["status"] = "UNDER_REVIEW"
    a["reviewer_id"] = uid
    touch(a)
    return success_object(public(a))


@app.route("/pap/applications/<aid>/request-info", methods=["POST"])
def request_info(aid):
    uid, _ = require_role("CaseWorker")
    a = db.applications.get(aid)
    if not a:
        raise err("ERR_NOT_FOUND", 404, "Application not found")
    body = get_json_body()
    note = require_string(body, "info_request_note")
    if a["status"] != "UNDER_REVIEW":
        raise err("ERR_APPLICATION_NOT_UNDER_REVIEW", 409, "Application not UNDER_REVIEW")
    if a["reviewer_id"] != uid:
        raise err("ERR_REVIEWER_MISMATCH", 403, "Only the claiming reviewer may request info")
    a["status"] = "MORE_INFO_REQUESTED"
    a["info_request_note"] = note
    touch(a)
    return success_object(public(a))


@app.route("/pap/applications/<aid>/resubmit", methods=["POST"])
def resubmit_application(aid):
    uid, _ = require_role("Patient")
    a = db.applications.get(aid)
    if not a:
        raise err("ERR_NOT_FOUND", 404, "Application not found")
    if a["patient_id"] != uid:
        raise err("ERR_OWNERSHIP_VIOLATION", 403, "Caller does not own application")
    if a["status"] != "MORE_INFO_REQUESTED":
        raise err("ERR_APPLICATION_NOT_AWAITING_INFO", 409, "Application not MORE_INFO_REQUESTED")
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return success_object(public(a))


@app.route("/pap/applications/<aid>/decision", methods=["POST"])
def decide_application(aid):
    uid, _ = require_role("CaseWorker")
    a = db.applications.get(aid)
    if not a:
        raise err("ERR_NOT_FOUND", 404, "Application not found")
    body = get_json_body()
    decision = require_enum(body, "decision", {"APPROVED", "DENIED"})
    # state + reviewer first
    if a["status"] != "UNDER_REVIEW":
        raise err("ERR_APPLICATION_NOT_UNDER_REVIEW", 409, "Application not UNDER_REVIEW")
    if a["reviewer_id"] != uid:
        raise err("ERR_REVIEWER_MISMATCH", 403, "Only the claiming reviewer may decide")
    if decision == "DENIED":
        reason = body.get("decision_reason")
        if not isinstance(reason, str) or not reason:
            raise err("ERR_INVALID_REQUEST", 400, "decision_reason is required for DENIED")
        a["status"] = "DENIED"
        a["decision_reason"] = reason
        a["decided_at"] = now_iso()
        touch(a)
        return success_object(public(a))
    # APPROVED path
    program = db.programs[a["program_id"]]
    screening = db.screenings[a["screening_id"]]
    is_renewal = a.get("renewal_of_enrollment_id") is not None
    prior_enrollment = db.enrollments.get(a["renewal_of_enrollment_id"]) if is_renewal else None
    if is_renewal and prior_enrollment is not None:
        new_start = iso_to_date(prior_enrollment["end_date"]) + timedelta(days=1)
    else:
        new_start = today_date()
    new_end = new_start + timedelta(days=program["enrollment_duration_days"] - 1)
    _run_approval_gates(a, program, screening, is_renewal, prior_enrollment, new_start, new_end)
    # create enrollment
    enrollment = _create_enrollment_for(a, is_renewal, prior_enrollment)
    # for renewals: close prior enrollment
    if is_renewal and prior_enrollment is not None:
        _release_enrollment_commitment(prior_enrollment)
        prior_enrollment["status"] = "CLOSED_RENEWED"
        touch(prior_enrollment)
    a["status"] = "APPROVED"
    a["decided_at"] = now_iso()
    a["enrollment_id"] = enrollment["id"]
    touch(a)
    touch_program(program)
    return success_object(public(a))


@app.route("/pap/applications/<aid>/appeals", methods=["POST"])
def file_appeal(aid):
    uid, _ = require_role("Patient")
    a = db.applications.get(aid)
    if not a:
        raise err("ERR_NOT_FOUND", 404, "Application not found")
    body = get_json_body()
    grounds = require_string(body, "grounds")
    if a["patient_id"] != uid:
        raise err("ERR_OWNERSHIP_VIOLATION", 403, "Caller does not own application")
    if a["status"] != "DENIED":
        raise err("ERR_APPLICATION_NOT_DENIED", 409, "Appeal requires DENIED application")
    # one FILED appeal per application
    for ap in db.appeals.values():
        if ap["application_id"] == aid and ap["status"] == "FILED":
            raise err("ERR_APPEAL_ALREADY_EXISTS", 409, "A FILED appeal already exists")
    program = db.programs[a["program_id"]]
    decided_date = iso_to_date(a["decided_at"])
    if today_date() > decided_date + timedelta(days=program["appeal_window_days"]):
        raise err("ERR_APPEAL_WINDOW_EXPIRED", 409, "Appeal window has expired")
    ap = new_entity(extra=dict(
        application_id=aid,
        grounds=grounds,
        status="FILED",
        decided_by=None,
        decision_reason=None,
        decided_at=None,
    ))
    db.appeals[ap["id"]] = ap
    return success_object(public(ap), status=201)


# ---------------------------------------------------------------------------
# appeals
# ---------------------------------------------------------------------------

@app.route("/pap/appeals", methods=["GET"])
def list_appeals():
    require_auth()
    items = list(db.appeals.values())
    app_id = request.args.get("application_id")
    status = request.args.get("status")
    if app_id:
        items = [a for a in items if a["application_id"] == app_id]
    if status:
        items = [a for a in items if a["status"] == status]
    return list_and_paginate(items)


@app.route("/pap/appeals/<aid>", methods=["GET"])
def get_appeal(aid):
    require_auth()
    ap = db.appeals.get(aid)
    if not ap:
        raise err("ERR_NOT_FOUND", 404, "Appeal not found")
    return success_object(public(ap))


@app.route("/pap/appeals/<aid>/decision", methods=["POST"])
def decide_appeal(aid):
    uid, _ = require_role("AppealsOfficer")
    ap = db.appeals.get(aid)
    if not ap:
        raise err("ERR_NOT_FOUND", 404, "Appeal not found")
    body = get_json_body()
    decision = require_enum(body, "decision", {"UPHELD", "OVERTURNED"})
    if ap["status"] != "FILED":
        raise err("ERR_APPEAL_NOT_FILED", 409, "Appeal not FILED")
    application = db.applications[ap["application_id"]]
    # segregation of duties
    if application.get("reviewer_id") is not None and uid == application["reviewer_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", 403, "Appeal decider must differ from reviewer")
    reason = optional_string(body, "decision_reason")
    ap["decided_by"] = uid
    ap["decided_at"] = now_iso()
    if reason is not None:
        ap["decision_reason"] = reason
    if decision == "UPHELD":
        ap["status"] = "UPHELD"
        touch(ap)
        return success_object(public(ap))
    # OVERTURNED: re-run approval gates now
    program = db.programs[application["program_id"]]
    screening = db.screenings[application["screening_id"]]
    is_renewal = application.get("renewal_of_enrollment_id") is not None
    prior_enrollment = db.enrollments.get(application["renewal_of_enrollment_id"]) if is_renewal else None
    if is_renewal and prior_enrollment is not None:
        new_start = iso_to_date(prior_enrollment["end_date"]) + timedelta(days=1)
    else:
        new_start = today_date()
    new_end = new_start + timedelta(days=program["enrollment_duration_days"] - 1)
    _run_approval_gates(application, program, screening, is_renewal, prior_enrollment, new_start, new_end)
    enrollment = _create_enrollment_for(application, is_renewal, prior_enrollment)
    if is_renewal and prior_enrollment is not None:
        _release_enrollment_commitment(prior_enrollment)
        prior_enrollment["status"] = "CLOSED_RENEWED"
        touch(prior_enrollment)
    application["status"] = "APPROVED"
    application["approved_via_appeal"] = True
    application["decided_at"] = now_iso()
    application["enrollment_id"] = enrollment["id"]
    touch(application)
    ap["status"] = "OVERTURNED"
    touch(ap)
    touch_program(program)
    return success_object(public(ap))


# ---------------------------------------------------------------------------
# enrollments
# ---------------------------------------------------------------------------

@app.route("/pap/enrollments", methods=["GET"])
def list_enrollments():
    require_auth()
    items = list(db.enrollments.values())
    for f in ("patient_id", "program_id", "application_id", "commitment_budget_period_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if str(e.get(f)) == v]
    return list_and_paginate(items)


@app.route("/pap/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    require_auth()
    e = db.enrollments.get(eid)
    if not e:
        raise err("ERR_NOT_FOUND", 404, "Enrollment not found")
    return success_object(public(e))


@app.route("/pap/enrollments/<eid>/renewal-applications", methods=["POST"])
def create_renewal_application(eid):
    uid, _ = require_role("Patient")
    body = get_json_body()
    require_fields(body, ["screening_id", "expected_enrollment_version"])
    screening_id = body["screening_id"]
    expected = body["expected_enrollment_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", 400, "expected_enrollment_version must be an integer")
    enr = db.enrollments.get(eid)
    if not enr:
        raise err("ERR_NOT_FOUND", 404, "Enrollment not found")
    # OCC
    if expected != enr["version"]:
        raise err("ERR_STALE_VERSION", 412, "Stale enrollment version")
    # ownership
    if enr["patient_id"] != uid:
        raise err("ERR_OWNERSHIP_VIOLATION", 403, "Caller does not own enrollment")
    # enrollment must be ACTIVE
    if enr["status"] != "ACTIVE":
        raise err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment must be ACTIVE to renew")
    # screening existence
    screening = db.screenings.get(screening_id)
    if not screening:
        raise err("ERR_NOT_FOUND", 404, "Screening not found")
    # cross-reference: screening of enrollment.patient_id and enrollment.program_id
    if screening["patient_id"] != enr["patient_id"] or screening["program_id"] != enr["program_id"]:
        raise err("ERR_SCREENING_MISMATCH", 422, "Screening does not match enrollment patient/program")
    # screening VERIFIED
    if screening["status"] != "VERIFIED":
        raise err("ERR_SCREENING_NOT_VERIFIED", 409, "Screening must be VERIFIED")
    # screening freshness
    program = db.programs[enr["program_id"]]
    verified_date = iso_to_date(screening["verified_at"])
    if today_date() > verified_date + timedelta(days=program["screening_validity_days"]):
        raise err("ERR_SCREENING_STALE", 409, "Screening is stale")
    # renewal window: end_date - renewal_window_days <= today <= end_date
    end_d = iso_to_date(enr["end_date"])
    window_start = end_d - timedelta(days=program["renewal_window_days"])
    today = today_date()
    if not (window_start <= today <= end_d):
        raise err("ERR_OUTSIDE_RENEWAL_WINDOW", 409, "Outside renewal window")
    # supersede prior non-terminal renewal applications for this enrollment
    for a in db.applications.values():
        if (a.get("renewal_of_enrollment_id") == eid
                and a["status"] in ("SUBMITTED", "UNDER_REVIEW", "MORE_INFO_REQUESTED")):
            a["status"] = "SUPERSEDED"
            touch(a)
    app_obj = new_entity(extra=dict(
        patient_id=enr["patient_id"],
        program_id=enr["program_id"],
        screening_id=screening_id,
        renewal_of_enrollment_id=eid,
        status="SUBMITTED",
        reviewer_id=None,
        info_request_note=None,
        decision_reason=None,
        decided_at=None,
        approved_via_appeal=False,
        enrollment_id=None,
    ))
    db.applications[app_obj["id"]] = app_obj
    # renewal creation advances the enrollment version
    touch(enr)
    return success_object(public(app_obj), status=201)


@app.route("/pap/enrollments/<eid>/terminate", methods=["POST"])
def terminate_enrollment(eid):
    require_role("CaseWorker")
    enr = db.enrollments.get(eid)
    if not enr:
        raise err("ERR_NOT_FOUND", 404, "Enrollment not found")
    body = get_json_body()
    reason = body.get("termination_reason")
    if enr["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment not ACTIVE or SUSPENDED")
    _cancel_reserved_shipments_for(enr, reason=reason if isinstance(reason, str) else None)
    _release_enrollment_commitment(enr)
    enr["status"] = "TERMINATED"
    if isinstance(reason, str):
        enr["status_reason"] = reason
    touch(enr)
    return success_object(public(enr))


@app.route("/pap/enrollments/<eid>/reinstate", methods=["POST"])
def reinstate_enrollment(eid):
    require_role("CaseWorker")
    body = get_json_body()
    require_fields(body, ["screening_id"])
    screening_id = body["screening_id"]
    enr = db.enrollments.get(eid)
    if not enr:
        raise err("ERR_NOT_FOUND", 404, "Enrollment not found")
    if enr["status"] != "SUSPENDED":
        raise err("ERR_ENROLLMENT_NOT_SUSPENDED", 409, "Enrollment not SUSPENDED")
    screening = db.screenings.get(screening_id)
    if not screening:
        raise err("ERR_NOT_FOUND", 404, "Screening not found")
    if screening["patient_id"] != enr["patient_id"] or screening["program_id"] != enr["program_id"]:
        raise err("ERR_SCREENING_MISMATCH", 422, "Screening does not match enrollment patient/program")
    if screening["status"] != "VERIFIED":
        raise err("ERR_SCREENING_NOT_VERIFIED", 409, "Screening must be VERIFIED")
    program = db.programs[enr["program_id"]]
    verified_date = iso_to_date(screening["verified_at"])
    if today_date() > verified_date + timedelta(days=program["screening_validity_days"]):
        raise err("ERR_SCREENING_STALE", 409, "Screening is stale")
    enr["status"] = "ACTIVE"
    enr["status_reason"] = None
    touch(enr)
    return success_object(public(enr))


# ---------------------------------------------------------------------------
# circumstances
# ---------------------------------------------------------------------------

@app.route("/pap/enrollments/<eid>/circumstances", methods=["POST"])
def report_circumstance(eid):
    uid, role = require_role("Patient", "CaseWorker")
    enr = db.enrollments.get(eid)
    if not enr:
        raise err("ERR_NOT_FOUND", 404, "Enrollment not found")
    body = get_json_body()
    require_fields(body, ["circumstance_type"])
    ctype = require_enum(body, "circumstance_type", CIRCUMSTANCE_TYPES)
    new_income = body.get("new_annual_income_cents")
    new_household = body.get("new_household_size")
    new_insurance = body.get("new_insurance_status")
    # conditional field matching
    if ctype == "INCOME_CHANGE":
        if new_income is None:
            raise err("ERR_INVALID_REQUEST", 400, "new_annual_income_cents required for INCOME_CHANGE")
        if isinstance(new_income, bool) or not isinstance(new_income, int):
            raise err("ERR_INVALID_REQUEST", 400, "new_annual_income_cents must be an integer")
    elif ctype == "HOUSEHOLD_CHANGE":
        if new_household is None:
            raise err("ERR_INVALID_REQUEST", 400, "new_household_size required for HOUSEHOLD_CHANGE")
        if isinstance(new_household, bool) or not isinstance(new_household, int):
            raise err("ERR_INVALID_REQUEST", 400, "new_household_size must be an integer")
    elif ctype == "INSURANCE_CHANGE":
        if new_insurance is None:
            raise err("ERR_INVALID_REQUEST", 400, "new_insurance_status required for INSURANCE_CHANGE")
        if new_insurance not in INSURANCE_STATUSES:
            raise err("ERR_INVALID_REQUEST", 400, "new_insurance_status invalid")
    # ownership for Patient callers
    if role == "Patient" and enr["patient_id"] != uid:
        raise err("ERR_OWNERSHIP_VIOLATION", 403, "Caller does not own enrollment")
    # enrollment must be ACTIVE or SUSPENDED (state check)
    if enr["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment not ACTIVE or SUSPENDED")
    note = optional_string(body, "note")
    c = new_entity(extra=dict(
        enrollment_id=eid,
        circumstance_type=ctype,
        new_annual_income_cents=new_income if ctype == "INCOME_CHANGE" else None,
        new_household_size=new_household if ctype == "HOUSEHOLD_CHANGE" else None,
        new_insurance_status=new_insurance if ctype == "INSURANCE_CHANGE" else None,
        note=note,
        reported_by=uid,
        status="REPORTED",
        outcome=None,
        review_note=None,
    ))
    db.circumstances[c["id"]] = c
    return success_object(public(c), status=201)


@app.route("/pap/circumstances", methods=["GET"])
def list_circumstances():
    require_auth()
    items = list(db.circumstances.values())
    enr_id = request.args.get("enrollment_id")
    status = request.args.get("status")
    if enr_id:
        items = [c for c in items if c["enrollment_id"] == enr_id]
    if status:
        items = [c for c in items if c["status"] == status]
    return list_and_paginate(items)


@app.route("/pap/circumstances/<cid>", methods=["GET"])
def get_circumstance(cid):
    require_auth()
    c = db.circumstances.get(cid)
    if not c:
        raise err("ERR_NOT_FOUND", 404, "Circumstance not found")
    return success_object(public(c))


@app.route("/pap/circumstances/<cid>/review", methods=["POST"])
def review_circumstance(cid):
    require_role("CaseWorker")
    c = db.circumstances.get(cid)
    if not c:
        raise err("ERR_NOT_FOUND", 404, "Circumstance not found")
    body = get_json_body()
    decision = require_enum(body, "decision", {"APPLIED_SUSPEND", "APPLIED_TERMINATE", "DISMISSED"})
    if c["status"] != "REPORTED":
        raise err("ERR_CIRCUMSTANCE_NOT_REPORTED", 409, "Circumstance not REPORTED")
    enr = db.enrollments[c["enrollment_id"]]
    if decision in ("APPLIED_SUSPEND", "APPLIED_TERMINATE"):
        if enr["status"] not in ("ACTIVE", "SUSPENDED"):
            raise err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment not ACTIVE or SUSPENDED")
    review_note = optional_string(body, "review_note")
    if decision == "DISMISSED":
        c["status"] = "DISMISSED"
        if review_note is not None:
            c["review_note"] = review_note
        touch(c)
        return success_object(public(c))
    # APPLIED_*
    c["status"] = "APPLIED"
    c["outcome"] = "SUSPENDED" if decision == "APPLIED_SUSPEND" else "TERMINATED"
    if review_note is not None:
        c["review_note"] = review_note
    if decision == "APPLIED_SUSPEND":
        # cascade: ACTIVE -> SUSPENDED with shipment cancellation
        _cancel_reserved_shipments_for(enr, reason=review_note)
        enr["status"] = "SUSPENDED"
        enr["status_reason"] = review_note
        touch(enr)
    else:  # APPLIED_TERMINATE
        _cancel_reserved_shipments_for(enr, reason=review_note)
        _release_enrollment_commitment(enr)
        enr["status"] = "TERMINATED"
        enr["status_reason"] = review_note
        touch(enr)
    touch(c)
    return success_object(public(c))


# ---------------------------------------------------------------------------
# copay cards
# ---------------------------------------------------------------------------

@app.route("/pap/copay-cards", methods=["POST"])
def create_copay_card():
    require_role("CaseWorker")
    body = get_json_body()
    require_fields(body, ["patient_id", "program_id", "coverage_start", "coverage_end"])
    patient_id = body["patient_id"]
    program_id = body["program_id"]
    coverage_start = require_iso_date(body, "coverage_start")
    coverage_end = require_iso_date(body, "coverage_end")
    if iso_to_date(coverage_end) < iso_to_date(coverage_start):
        raise err("ERR_INVALID_REQUEST", 400, "coverage_end must be on or after coverage_start")
    if patient_id not in db.patients:
        raise err("ERR_NOT_FOUND", 404, "Patient not found")
    if program_id not in db.programs:
        raise err("ERR_NOT_FOUND", 404, "Program not found")
    cs = iso_to_date(coverage_start)
    ce = iso_to_date(coverage_end)
    # duplicate-benefit: no ACTIVE/SUSPENDED enrollment overlapping coverage
    for e in db.enrollments.values():
        if e["patient_id"] != patient_id or e["program_id"] != program_id:
            continue
        if e["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        es = iso_to_date(e["start_date"])
        ee = iso_to_date(e["end_date"])
        if not (ee < cs or es > ce):
            raise err("ERR_DUPLICATE_BENEFIT_ACTIVE", 409, "Overlapping ACTIVE/SUSPENDED enrollment")
    # card-overlap: no other non-TERMINATED card for (patient, program) overlaps
    for c in db.copay_cards.values():
        if c["patient_id"] != patient_id or c["program_id"] != program_id:
            continue
        if c["status"] == "TERMINATED":
            continue
        os_ = iso_to_date(c["coverage_start"])
        oe = iso_to_date(c["coverage_end"])
        if not (oe < cs or os_ > ce):
            raise err("ERR_COPAY_CARD_OVERLAP", 409, "Overlapping copay card exists")
    card = new_entity(extra=dict(
        patient_id=patient_id,
        program_id=program_id,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        status="ACTIVE",
        termination_reason=None,
    ))
    db.copay_cards[card["id"]] = card
    return success_object(public(card), status=201)


@app.route("/pap/copay-cards", methods=["GET"])
def list_copay_cards():
    require_auth()
    items = list(db.copay_cards.values())
    for f in ("patient_id", "program_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if str(c.get(f)) == v]
    return list_and_paginate(items)


@app.route("/pap/copay-cards/<cid>", methods=["GET"])
def get_copay_card(cid):
    require_auth()
    c = db.copay_cards.get(cid)
    if not c:
        raise err("ERR_NOT_FOUND", 404, "Copay card not found")
    return success_object(public(c))


@app.route("/pap/copay-cards/<cid>/suspend", methods=["POST"])
def suspend_copay_card(cid):
    require_role("CaseWorker")
    c = db.copay_cards.get(cid)
    if not c:
        raise err("ERR_NOT_FOUND", 404, "Copay card not found")
    if c["status"] == "TERMINATED":
        raise err("ERR_COPAY_CARD_TERMINATED", 409, "Copay card terminated")
    if c["status"] != "ACTIVE":
        raise err("ERR_COPAY_CARD_NOT_ACTIVE", 409, "Copay card not ACTIVE")
    c["status"] = "SUSPENDED"
    touch(c)
    return success_object(public(c))


@app.route("/pap/copay-cards/<cid>/terminate", methods=["POST"])
def terminate_copay_card(cid):
    require_role("CaseWorker")
    c = db.copay_cards.get(cid)
    if not c:
        raise err("ERR_NOT_FOUND", 404, "Copay card not found")
    if c["status"] == "TERMINATED":
        raise err("ERR_COPAY_CARD_TERMINATED", 409, "Copay card terminated")
    body = get_json_body()
    reason = optional_string(body, "reason")
    c["status"] = "TERMINATED"
    if reason is not None:
        c["termination_reason"] = reason
    touch(c)
    return success_object(public(c))


# ---------------------------------------------------------------------------
# inventory lots
# ---------------------------------------------------------------------------

@app.route("/pap/inventory-lots", methods=["POST"])
def create_lot():
    require_role("ProgramAdministrator")
    body = get_json_body()
    require_fields(body, ["program_id", "lot_number", "quantity_received", "unit_cost_per_unit", "expiry_date"])
    program_id = body["program_id"]
    lot_number = require_string(body, "lot_number")
    quantity_received = require_int(body, "quantity_received", minimum=1)
    unit_cost_str = body["unit_cost_per_unit"]
    if parse_decimal4(unit_cost_str) is None:
        raise err("ERR_INVALID_REQUEST", 400, "unit_cost_per_unit must be decimal with exactly 4 fraction digits")
    expiry_date = require_iso_date(body, "expiry_date")
    if program_id not in db.programs:
        raise err("ERR_NOT_FOUND", 404, "Program not found")
    for l in db.inventory_lots.values():
        if l["program_id"] == program_id and l["lot_number"] == lot_number:
            raise err("ERR_LOT_NUMBER_DUPLICATE", 409, "Lot number already exists for program")
    lot = new_entity(extra=dict(
        program_id=program_id,
        lot_number=lot_number,
        quantity_received=quantity_received,
        unit_cost_per_unit=unit_cost_str,
        expiry_date=expiry_date,
        status="ACTIVE",
        quantity_on_hand=quantity_received,
        quantity_reserved=0,
        quantity_shipped=0,
        quantity_dispensed=0,
        quantity_quarantined=0,
        status_reason=None,
    ))
    db.inventory_lots[lot["id"]] = lot
    return success_object(public(lot), status=201)


@app.route("/pap/inventory-lots", methods=["GET"])
def list_lots():
    require_auth()
    items = list(db.inventory_lots.values())
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if program_id:
        items = [l for l in items if l["program_id"] == program_id]
    if status:
        items = [l for l in items if l["status"] == status]
    return list_and_paginate(items)


@app.route("/pap/inventory-lots/<lid>", methods=["GET"])
def get_lot(lid):
    require_auth()
    l = db.inventory_lots.get(lid)
    if not l:
        raise err("ERR_NOT_FOUND", 404, "Lot not found")
    return success_object(public(l))


@app.route("/pap/inventory-lots/<lid>/quarantine", methods=["POST"])
def quarantine_lot(lid):
    require_role("ProgramAdministrator")
    l = db.inventory_lots.get(lid)
    if not l:
        raise err("ERR_NOT_FOUND", 404, "Lot not found")
    body = get_json_body()
    reason = require_string(body, "reason")
    if l["status"] != "ACTIVE":
        raise err("ERR_LOT_NOT_ACTIVE", 409, "Lot not ACTIVE")
    l["status"] = "QUARANTINED"
    l["status_reason"] = reason
    touch(l)
    return success_object(public(l))


@app.route("/pap/inventory-lots/<lid>/lines", methods=["GET"])
def list_lot_lines(lid):
    require_auth()
    if lid not in db.inventory_lots:
        raise err("ERR_NOT_FOUND", 404, "Lot not found")
    items = [ln for ln in db.shipment_lines.values() if ln["lot_id"] == lid]
    return list_and_paginate(items)


@app.route("/pap/inventory-lots/<lid>/dispense-events", methods=["GET"])
def list_lot_dispense_events(lid):
    require_auth()
    if lid not in db.inventory_lots:
        raise err("ERR_NOT_FOUND", 404, "Lot not found")
    items = [e for e in db.dispense_events.values() if e["lot_id"] == lid]
    return list_and_paginate(items)


# ---------------------------------------------------------------------------
# shipments
# ---------------------------------------------------------------------------

def _fefo_allocate(program_id, quantity_units, today, buffer_days):
    """Return list of (lot, qty) allocations per FEFO, or raise."""
    eligible = []
    cutoff = today + timedelta(days=buffer_days)
    for lot in db.inventory_lots.values():
        if lot["program_id"] != program_id:
            continue
        if lot["status"] != "ACTIVE":
            continue
        if lot["quantity_on_hand"] <= 0:
            continue
        exp = iso_to_date(lot["expiry_date"])
        if not (exp > cutoff):
            continue
        eligible.append(lot)
    if not eligible:
        raise err("ERR_NO_ELIGIBLE_INVENTORY", 409, "No eligible inventory")
    # rank: expiry_date ASC, tie-break created_at ASC (use _seq as creation order proxy)
    eligible.sort(key=lambda l: (l["expiry_date"], l.get("_seq", 0)))
    total_avail = sum(l["quantity_on_hand"] for l in eligible)
    if total_avail < quantity_units:
        raise err("ERR_INSUFFICIENT_INVENTORY", 409, "Insufficient inventory across eligible lots")
    allocations = []
    remaining = quantity_units
    for lot in eligible:
        if remaining <= 0:
            break
        take = min(lot["quantity_on_hand"], remaining)
        allocations.append((lot, take))
        remaining -= take
    return allocations


@app.route("/pap/shipments", methods=["POST"])
def create_shipment():
    uid, role = require_role("CaseWorker", "Patient", "Prescriber")
    body = get_json_body()
    # Idempotency-Key (header or body) is part of request schema (priority 2.5)
    idem_key = request.headers.get("Idempotency-Key") or body.get("idempotency_key")
    if not idem_key:
        raise err("ERR_INVALID_REQUEST", 400, "Idempotency-Key header is required")
    require_fields(body, ["enrollment_id", "quantity_units", "destination"])
    enrollment_id = body["enrollment_id"]
    destination = require_enum(body, "destination", DESTINATIONS)
    quantity_units = body["quantity_units"]
    if isinstance(quantity_units, bool) or not isinstance(quantity_units, int):
        raise err("ERR_INVALID_REQUEST", 400, "quantity_units must be an integer")
    if quantity_units < 1:
        raise err("ERR_INVALID_QUANTITY", 400, "quantity_units must be >= 1")
    prescriber_id = body.get("prescriber_id")

    # destination rules (schema-level)
    # fetch enrollment for program rules first (existence comes next in priority order)
    enrollment = db.enrollments.get(enrollment_id)
    if not enrollment:
        raise err("ERR_NOT_FOUND", 404, "Enrollment not found")
    program = db.programs[enrollment["program_id"]]

    # destination schema: PATIENT requires allow_patient_direct_shipment
    if destination == "PATIENT" and not program["allow_patient_direct_shipment"]:
        raise err("ERR_INVALID_DESTINATION", 400, "Program does not allow patient-direct shipment")
    if destination == "PROVIDER" and not prescriber_id:
        raise err("ERR_PRESCRIBER_REQUIRED", 400, "prescriber_id required for PROVIDER destination")
    if destination == "PATIENT" and prescriber_id:
        raise err("ERR_PRESCRIBER_REQUIRED", 400, "prescriber_id must not be supplied for PATIENT destination")

    # idempotency replay: same key + same body -> replay; same key + different -> conflict
    # canonical body excludes idempotency_key field itself (since header could carry it)
    body_for_hash = {k: v for k, v in body.items() if k != "idempotency_key"}
    canonical = json.dumps(body_for_hash, sort_keys=True, separators=(",", ":"))
    if idem_key in db.idempotency_keys:
        prior = db.idempotency_keys[idem_key]
        if prior["body"] != canonical:
            raise err("ERR_IDEMPOTENCY_CONFLICT", 409, "Idempotency-Key reused with different body")
        # replay stored response verbatim
        from util import error_response  # local import to avoid circularity confusion
        resp_body = prior["response"]
        return success_object(resp_body, status=201)

    # ownership/role checks (priority 3 entity-backed ownership)
    if role == "Patient":
        if enrollment["patient_id"] != uid:
            raise err("ERR_OWNERSHIP_VIOLATION", 403, "Patient may only ship against own enrollment")
        if destination != "PATIENT":
            # Patient may create shipments only with destination PATIENT
            raise err("ERR_OWNERSHIP_VIOLATION", 403, "Patient may only create PATIENT-destination shipments")
    elif role == "Prescriber":
        if destination != "PROVIDER" or prescriber_id != uid:
            raise err("ERR_PRESCRIBER_MISMATCH", 403, "Prescriber may only create PROVIDER shipments to self")

    # prescriber existence (for PROVIDER)
    if destination == "PROVIDER" and prescriber_id not in db.prescribers:
        raise err("ERR_NOT_FOUND", 404, "Prescriber not found")

    # state: enrollment must be ACTIVE
    if enrollment["status"] != "ACTIVE":
        raise err("ERR_ENROLLMENT_NOT_ACTIVE", 409, "Enrollment not ACTIVE")

    # quantity caps
    if quantity_units > program["max_units_per_shipment"]:
        raise err("ERR_SHIPMENT_QUANTITY_LIMIT_EXCEEDED", 422, "Exceeds max_units_per_shipment")
    if quantity_units > enrollment["remaining_units"]:
        raise err("ERR_SHIPMENT_QUANTITY_LIMIT_EXCEEDED", 422, "Exceeds enrollment.remaining_units")

    # FEFO allocation
    today = today_date()
    allocations = _fefo_allocate(program["id"], quantity_units, today, program["lot_expiry_buffer_days"])

    shipment = new_entity(extra=dict(
        enrollment_id=enrollment_id,
        destination=destination,
        prescriber_id=prescriber_id if destination == "PROVIDER" else None,
        quantity_units=quantity_units,
        status="RESERVED",
        value_cents=0,
        dispensed_value_cents=0,
        idempotency_key=idem_key,
        requested_by=uid,
        status_reason=None,
    ))
    db.shipments[shipment["id"]] = shipment

    total_value = 0
    for lot, qty in allocations:
        unit_cost = parse_decimal4(lot["unit_cost_per_unit"])
        line_val = line_value_cents(qty, unit_cost)
        line = new_entity(extra=dict(
            shipment_id=shipment["id"],
            lot_id=lot["id"],
            quantity=qty,
            value_cents=line_val,
            dispensed_quantity=0,
        ))
        db.shipment_lines[line["id"]] = line
        lot["quantity_on_hand"] -= qty
        lot["quantity_reserved"] += qty
        touch(lot)
        total_value += line_val
    shipment["value_cents"] = total_value
    enrollment["remaining_units"] -= quantity_units
    touch(enrollment)

    db.idempotency_keys[idem_key] = {"body": canonical, "response": public(shipment)}
    return success_object(public(shipment), status=201)


@app.route("/pap/shipments", methods=["GET"])
def list_shipments():
    require_auth()
    items = list(db.shipments.values())
    for f in ("enrollment_id", "prescriber_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if str(s.get(f)) == v]
    return list_and_paginate(items)


@app.route("/pap/shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    require_auth()
    s = db.shipments.get(sid)
    if not s:
        raise err("ERR_NOT_FOUND", 404, "Shipment not found")
    return success_object(public(s))


@app.route("/pap/shipments/<sid>/lines", methods=["GET"])
def list_shipment_lines(sid):
    require_auth()
    if sid not in db.shipments:
        raise err("ERR_NOT_FOUND", 404, "Shipment not found")
    items = [ln for ln in db.shipment_lines.values() if ln["shipment_id"] == sid]
    return list_and_paginate(items)


@app.route("/pap/shipments/<sid>/dispatch", methods=["POST"])
def dispatch_shipment(sid):
    require_role("CaseWorker")
    sh = db.shipments.get(sid)
    if not sh:
        raise err("ERR_NOT_FOUND", 404, "Shipment not found")
    if sh["status"] != "RESERVED":
        raise err("ERR_SHIPMENT_NOT_RESERVED", 409, "Shipment not RESERVED")
    lines = [ln for ln in db.shipment_lines.values() if ln["shipment_id"] == sid]
    for ln in lines:
        lot = db.inventory_lots.get(ln["lot_id"])
        if not lot or lot["status"] != "ACTIVE":
            raise err("ERR_LOT_NOT_ACTIVE", 409, "Line lot not ACTIVE")
    for ln in lines:
        lot = db.inventory_lots[ln["lot_id"]]
        lot["quantity_reserved"] -= ln["quantity"]
        lot["quantity_shipped"] += ln["quantity"]
        touch(lot)
    sh["status"] = "DISPATCHED"
    touch(sh)
    return success_object(public(sh))


@app.route("/pap/shipments/<sid>/deliver", methods=["POST"])
def deliver_shipment(sid):
    uid, role = require_role("CaseWorker", "Prescriber", "Patient")
    sh = db.shipments.get(sid)
    if not sh:
        raise err("ERR_NOT_FOUND", 404, "Shipment not found")
    if sh["status"] != "DISPATCHED":
        raise err("ERR_SHIPMENT_NOT_DISPATCHED", 409, "Shipment not DISPATCHED")
    enrollment = db.enrollments[sh["enrollment_id"]]
    if role == "Prescriber":
        if sh["destination"] != "PROVIDER" or sh["prescriber_id"] != uid:
            raise err("ERR_PRESCRIBER_MISMATCH", 403, "Prescriber may deliver only own PROVIDER shipments")
    elif role == "Patient":
        if sh["destination"] != "PATIENT" or enrollment["patient_id"] != uid:
            raise err("ERR_OWNERSHIP_VIOLATION", 403, "Patient may deliver only own PATIENT shipments")
    sh["status"] = "DELIVERED"
    touch(sh)
    # money movement
    enrollment["disbursed_cents"] += sh["value_cents"]
    touch(enrollment)
    period = db.budget_periods.get(enrollment["commitment_budget_period_id"])
    if period:
        period["disbursed_cents"] += sh["value_cents"]
        touch(period)
    program = db.programs.get(enrollment["program_id"])
    if program:
        touch_program(program)
    return success_object(public(sh))


@app.route("/pap/shipments/<sid>/cancel", methods=["POST"])
def cancel_shipment(sid):
    require_role("CaseWorker")
    sh = db.shipments.get(sid)
    if not sh:
        raise err("ERR_NOT_FOUND", 404, "Shipment not found")
    if sh["status"] != "RESERVED":
        raise err("ERR_SHIPMENT_NOT_CANCELLABLE", 409, "Shipment not RESERVED")
    body = get_json_body()
    reason = optional_string(body, "reason")
    enrollment = db.enrollments[sh["enrollment_id"]]
    _cancel_shipment(sh, enrollment, reason=reason)
    return success_object(public(sh))


@app.route("/pap/shipments/<sid>/return", methods=["POST"])
def return_shipment(sid):
    require_role("CaseWorker")
    sh = db.shipments.get(sid)
    if not sh:
        raise err("ERR_NOT_FOUND", 404, "Shipment not found")
    if sh["status"] != "DISPATCHED":
        raise err("ERR_SHIPMENT_NOT_DISPATCHED", 409, "Shipment not DISPATCHED")
    body = get_json_body()
    reason = optional_string(body, "reason")
    lines = [ln for ln in db.shipment_lines.values() if ln["shipment_id"] == sid]
    for ln in lines:
        lot = db.inventory_lots.get(ln["lot_id"])
        if lot:
            lot["quantity_shipped"] -= ln["quantity"]
            lot["quantity_quarantined"] += ln["quantity"]
            touch(lot)
    sh["status"] = "RETURNED"
    if reason is not None:
        sh["status_reason"] = reason
    touch(sh)
    return success_object(public(sh))


# ---------------------------------------------------------------------------
# dispense events
# ---------------------------------------------------------------------------

@app.route("/pap/shipments/<sid>/dispense-events", methods=["POST"])
def create_dispense_event(sid):
    uid, _ = require_role("PharmacyDispenser")
    sh = db.shipments.get(sid)
    if not sh:
        raise err("ERR_NOT_FOUND", 404, "Shipment not found")
    body = get_json_body()
    require_fields(body, ["lot_id", "quantity"])
    lot_id = body["lot_id"]
    quantity = body["quantity"]
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise err("ERR_INVALID_REQUEST", 400, "quantity must be an integer")
    if quantity < 1:
        raise err("ERR_INVALID_QUANTITY", 400, "quantity must be >= 1")
    dispensed_at = body.get("dispensed_at")
    if dispensed_at is not None:
        if parse_iso_datetime(dispensed_at) is None:
            raise err("ERR_INVALID_REQUEST", 400, "dispensed_at must be ISO8601 datetime")
    # shipment state
    if sh["status"] != "DELIVERED":
        raise err("ERR_SHIPMENT_NOT_DELIVERED", 409, "Dispense events require DELIVERED shipment")
    # lot membership
    line = None
    for ln in db.shipment_lines.values():
        if ln["shipment_id"] == sid and ln["lot_id"] == lot_id:
            line = ln
            break
    if line is None:
        # distinguish: lot may exist but not in shipment
        if lot_id not in db.inventory_lots:
            raise err("ERR_NOT_FOUND", 404, "Lot not found")
        raise err("ERR_LOT_NOT_IN_SHIPMENT", 409, "Lot not in shipment")
    # cumulative quantity check
    if line["dispensed_quantity"] + quantity > line["quantity"]:
        raise err("ERR_DISPENSE_EXCEEDS_RESERVED", 409, "Cumulative dispense exceeds line quantity")
    lot = db.inventory_lots[lot_id]
    unit_cost = parse_decimal4(lot["unit_cost_per_unit"])
    event_value = line_value_cents(quantity, unit_cost)
    ev = new_entity(extra=dict(
        shipment_id=sid,
        lot_id=lot_id,
        quantity=quantity,
        dispensed_at=dispensed_at if dispensed_at else now_iso(),
        value_cents=event_value,
        dispenser_id=uid,
    ), common=False)
    db.dispense_events[ev["id"]] = ev
    # mutate lot, line, shipment
    lot["quantity_shipped"] -= quantity
    lot["quantity_dispensed"] += quantity
    touch(lot)
    line["dispensed_quantity"] += quantity
    touch(line)
    sh["dispensed_value_cents"] += event_value
    touch(sh)
    return success_object(public(ev), status=201)


@app.route("/pap/shipments/<sid>/dispense-events", methods=["GET"])
def list_shipment_dispense_events(sid):
    require_auth()
    if sid not in db.shipments:
        raise err("ERR_NOT_FOUND", 404, "Shipment not found")
    items = [e for e in db.dispense_events.values() if e["shipment_id"] == sid]
    return list_and_paginate(items)


# ---------------------------------------------------------------------------
# reconciliation
# ---------------------------------------------------------------------------

@app.route("/pap/reconciliation-runs", methods=["POST"])
def create_reconciliation_run():
    require_role("ProgramAdministrator")
    body = get_json_body()
    require_fields(body, ["program_id", "budget_period_id", "counts"])
    program_id = body["program_id"]
    budget_period_id = body["budget_period_id"]
    counts = body["counts"]
    if not isinstance(counts, list):
        raise err("ERR_INVALID_REQUEST", 400, "counts must be a list")
    for c in counts:
        if not isinstance(c, dict):
            raise err("ERR_INVALID_REQUEST", 400, "each count entry must be an object")
        if "lot_id" not in c or "actual_on_hand" not in c:
            raise err("ERR_INVALID_REQUEST", 400, "each count entry requires lot_id and actual_on_hand")
        aoh = c["actual_on_hand"]
        if isinstance(aoh, bool) or not isinstance(aoh, int):
            raise err("ERR_INVALID_REQUEST", 400, "actual_on_hand must be an integer")
        if aoh < 0:
            raise err("ERR_INVALID_QUANTITY", 400, "actual_on_hand must be >= 0")
    if program_id not in db.programs:
        raise err("ERR_NOT_FOUND", 404, "Program not found")
    bp = db.budget_periods.get(budget_period_id)
    if not bp:
        raise err("ERR_NOT_FOUND", 404, "Budget period not found")
    if bp["status"] != "CLOSED":
        raise err("ERR_BUDGET_PERIOD_NOT_CLOSED", 409, "Reconciliation requires CLOSED budget period")
    # coverage: every ACTIVE lot of the program with (on_hand + reserved + shipped) > 0 must be counted
    counted_lot_ids = set()
    for c in counts:
        counted_lot_ids.add(c["lot_id"])
    # lot-program match
    for c in counts:
        lot = db.inventory_lots.get(c["lot_id"])
        if lot is None:
            raise err("ERR_NOT_FOUND", 404, "Lot not found")
        if lot["program_id"] != program_id:
            raise err("ERR_RECONCILIATION_LOT_MISMATCH", 422, "Counted lot not in program")
    for lot in db.inventory_lots.values():
        if lot["program_id"] != program_id or lot["status"] != "ACTIVE":
            continue
        book_units = lot["quantity_on_hand"] + lot["quantity_reserved"] + lot["quantity_shipped"]
        if book_units > 0 and lot["id"] not in counted_lot_ids:
            raise err("ERR_RECONCILIATION_COUNTS_MISSING", 422, "Missing count for ACTIVE lot with book units")
    lines = []
    any_variance = False
    flagged_lots = []
    for c in counts:
        lot = db.inventory_lots[c["lot_id"]]
        book = lot["quantity_on_hand"]
        actual = c["actual_on_hand"]
        variance = actual - book
        unit_cost = parse_decimal4(lot["unit_cost_per_unit"])
        variance_value = round_half_up_int(Decimal(variance) * unit_cost * Decimal(100))
        lines.append({
            "lot_id": lot["id"],
            "book_on_hand": book,
            "actual_on_hand": actual,
            "variance_units": variance,
            "variance_value_cents": variance_value,
        })
        if variance != 0:
            any_variance = True
            flagged_lots.append(lot)
    status = "VARIANCE_FLAGGED" if any_variance else "CLEAN"
    run = new_entity(extra=dict(
        program_id=program_id,
        budget_period_id=budget_period_id,
        status=status,
        lines=lines,
    ))
    db.reconciliation_runs[run["id"]] = run
    for lot in flagged_lots:
        if lot["status"] == "ACTIVE":
            lot["status"] = "UNDER_INVESTIGATION"
            touch(lot)
    return success_object(public(run), status=201)


@app.route("/pap/reconciliation-runs", methods=["GET"])
def list_reconciliation_runs():
    require_auth()
    items = list(db.reconciliation_runs.values())
    for f in ("program_id", "budget_period_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if str(r.get(f)) == v]
    return list_and_paginate(items)


@app.route("/pap/reconciliation-runs/<rid>", methods=["GET"])
def get_reconciliation_run(rid):
    require_auth()
    r = db.reconciliation_runs.get(rid)
    if not r:
        raise err("ERR_NOT_FOUND", 404, "Reconciliation run not found")
    return success_object(public(r))


# ---------------------------------------------------------------------------
# system: logical clock + daily sweep
# ---------------------------------------------------------------------------

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role("ProgramAdministrator")
    body = get_json_body()
    to_iso8601 = body.get("to_iso8601")
    dt = parse_iso_datetime(to_iso8601)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", 400, "to_iso8601 must be a valid ISO8601 datetime")
    db.clock = dt
    return success_object({"current_utc": now_iso()})


@app.route("/_system/run-daily-sweep", methods=["POST"])
def run_daily_sweep():
    require_role("ProgramAdministrator")
    body = get_json_body()
    scope_program = body.get("program_id") if body else None
    today = today_date()
    staled_screening_ids = []
    expired_enrollment_ids = []
    expired_lot_ids = []
    cancelled_shipment_ids = []

    # (1) VERIFIED screenings past validity -> STALE
    for s in list(db.screenings.values()):
        if s["status"] != "VERIFIED":
            continue
        if scope_program and s["program_id"] != scope_program:
            continue
        program = db.programs.get(s["program_id"])
        if not program:
            continue
        verified_date = iso_to_date(s["verified_at"])
        if verified_date is None:
            continue
        if today > verified_date + timedelta(days=program["screening_validity_days"]):
            s["status"] = "STALE"
            touch(s)
            staled_screening_ids.append(s["id"])

    # (2) ACTIVE/SUSPENDED enrollments past end_date -> EXPIRED
    for e in list(db.enrollments.values()):
        if e["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if scope_program and e["program_id"] != scope_program:
            continue
        end_d = iso_to_date(e["end_date"])
        if end_d is None:
            continue
        if today > end_d:
            cancelled = _cancel_reserved_shipments_for(e)
            cancelled_shipment_ids.extend(cancelled)
            _release_enrollment_commitment(e)
            e["status"] = "EXPIRED"
            touch(e)
            expired_enrollment_ids.append(e["id"])

    # (3) ACTIVE lots past expiry_date -> EXPIRED
    for l in list(db.inventory_lots.values()):
        if l["status"] != "ACTIVE":
            continue
        if scope_program and l["program_id"] != scope_program:
            continue
        exp = iso_to_date(l["expiry_date"])
        if exp is None:
            continue
        if today > exp:
            l["quantity_quarantined"] += l["quantity_on_hand"]
            l["quantity_on_hand"] = 0
            l["status"] = "EXPIRED"
            touch(l)
            expired_lot_ids.append(l["id"])

    return success_object({
        "staled_screening_ids": staled_screening_ids,
        "expired_enrollment_ids": expired_enrollment_ids,
        "expired_lot_ids": expired_lot_ids,
        "cancelled_shipment_ids": cancelled_shipment_ids,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
