"""Deed-in-Lieu & Cash-for-Keys Administration API — Flask application.

All state is in-memory (db module dicts); a fresh process boots with empty
collections and the logical clock at 2026-08-01T00:00:00Z.
"""
import os
from datetime import timedelta

from flask import Flask

import db
from db import (
    loans, borrowers, properties, cases, listings, suspensions,
    title_commitments, liens, agreements, appointments, reports,
    disbursements, waivers, recordings, evictions,
    new_id, stamp_new, touch, now_dt, today, iso_ts,
)
from errors import ApiError, err
from middleware import require_roles, get_auth
from response import success, error, paginate
from services import (
    MARKETING_MIN_DAYS, MIN_VACATE_NOTICE_DAYS, INSPECTION_MIN_NOTICE_HOURS,
    INSPECTION_TRAVEL_BUFFER_MINUTES, HOLDOVER_GRACE_DAYS,
    RECORDING_DEADLINE_DAYS, MAX_NEGOTIATION_ROUNDS,
    ENUM_FORECLOSURE_REFERRAL, ENUM_HARDSHIP, ENUM_CONDITION_GRADE,
    ENUM_OCCUPANCY, ENUM_CONDITION_STANDARD, ENUM_PROGRAM_TYPE, ENUM_DECISION,
    ENUM_APPOINTMENT_TYPE, ENUM_ITEM_CODE, ENUM_SEVERITY, ENUM_PURPOSE,
    ENUM_DISMISSAL_REASON,
    get_loan_or_404, get_borrower_or_404, get_property_or_404,
    get_case_or_404, get_listing_or_404, get_commitment_or_404,
    get_agreement_or_404, get_appointment_or_404, get_report_or_404,
    get_disbursement_or_404, get_waiver_or_404, get_recording_or_404,
    get_eviction_or_404,
    body_json, req_str, opt_str, req_int, opt_int, req_number, req_bool,
    req_enum, opt_enum, req_iso_date, req_iso_datetime,
    check_borrower_case_read, lazy_expire_agreement,
    compute_per_diem, provisional_assistance_quote,
    condition_deduction_schedule, final_assistance_settlement,
    deficiency_waiver_amount, refresh_creditable_days,
    case_accepted_agreement, recompute_remaining, case_listings,
    case_commitments, case_evictions, case_waiver,
    withdraw_cascade, _close_listing, terminate_accepted_agreement,
    eviction_file_cascade, execute_waiver_and_complete_loan, complete_case,
)

app = Flask(__name__)

# Roles
ADMIN = "ServicingAdmin"
SPECIALIST = "PropertySolutionsSpecialist"
MANAGER = "WorkoutManager"
TITLE = "TitleOfficer"
BORROWER = "Borrower"
INSPECTOR = "Inspector"
OFFICER = "DisbursementOfficer"
LEGAL = "LegalCounsel"

STAFF_READ = (ADMIN, SPECIALIST, MANAGER, TITLE, LEGAL, OFFICER)
STAFF_READ_INSP = STAFF_READ + (INSPECTOR,)
ALL_READ = STAFF_READ_INSP + (BORROWER,)

CASE_TERMINAL = {"COMPLETED", "DECLINED", "WITHDRAWN", "CLOSED_EVICTED"}


@app.errorhandler(ApiError)
def handle_api_error(e: ApiError):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_INVALID_REQUEST", "Route not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_INVALID_REQUEST", "Method not allowed", 405)


# ===========================================================================
# Logical clock
# ===========================================================================

@app.post("/_clock/set_current_utc")
def set_clock():
    require_roles(ADMIN)
    data = body_json()
    _, dt = req_iso_datetime(data, "to_iso8601")
    db.clock.set(dt)
    return success({"current_utc": iso_ts(db.clock.now())}, 200)


# ===========================================================================
# Loans
# ===========================================================================

@app.post("/property-solutions/loans")
def create_loan():
    require_roles(ADMIN)
    data = body_json()
    loan_number = req_str(data, "loan_number")
    upb = req_int(data, "unpaid_principal_balance_cents")
    if upb <= 0:
        raise err("ERR_INVALID_REQUEST", "unpaid_principal_balance_cents must be > 0")
    accrued = req_int(data, "accrued_interest_cents")
    if accrued < 0:
        raise err("ERR_INVALID_REQUEST", "accrued_interest_cents must be >= 0")
    escrow = req_int(data, "escrow_advances_cents")
    if escrow < 0:
        raise err("ERR_INVALID_REQUEST", "escrow_advances_cents must be >= 0")
    fc_fees = req_int(data, "foreclosure_fees_cents")
    if fc_fees < 0:
        raise err("ERR_INVALID_REQUEST", "foreclosure_fees_cents must be >= 0")
    rate = req_number(data, "note_annual_rate")
    if rate <= 0 or rate > 0.25:
        raise err("ERR_INVALID_REQUEST", "note_annual_rate must be > 0 and <= 0.25")
    fmv = req_int(data, "fair_market_value_cents")
    if fmv < 0:
        raise err("ERR_INVALID_REQUEST", "fair_market_value_cents must be >= 0")
    delinq = req_int(data, "delinquency_days")
    if delinq < 0:
        raise err("ERR_INVALID_REQUEST", "delinquency_days must be >= 0")
    fc_status = opt_enum(data, "foreclosure_referral_status",
                         ENUM_FORECLOSURE_REFERRAL, "NONE")

    # loan_number uniqueness
    for l in loans.values():
        if l["loan_number"] == loan_number:
            raise err("ERR_INVALID_REQUEST",
                      f"loan_number '{loan_number}' already exists")

    rec = {
        "id": new_id(),
        "loan_number": loan_number,
        "unpaid_principal_balance_cents": upb,
        "accrued_interest_cents": accrued,
        "escrow_advances_cents": escrow,
        "foreclosure_fees_cents": fc_fees,
        "note_annual_rate": rate,
        "per_diem_interest_cents": compute_per_diem(upb, rate),
        "fair_market_value_cents": fmv,
        "delinquency_days": delinq,
        "foreclosure_referral_status": fc_status,
        "status": "ACTIVE_DELINQUENT",
        "deficiency_balance_cents": 0,
        "servicing_system_synced": False,
    }
    stamp_new(rec)
    loans[rec["id"]] = rec
    return success(rec, 201)


@app.get("/property-solutions/loans/<lid>")
def get_loan(lid):
    require_roles(*STAFF_READ)
    return success(get_loan_or_404(lid), 200)


@app.get("/property-solutions/loans")
def list_loans():
    require_roles(*STAFF_READ)
    from flask import request
    items = sorted(loans.values(), key=lambda r: r["created_at"])
    status_f = request.args.get("status")
    if status_f is not None:
        items = [l for l in items if l["status"] == status_f]
    page, pg = paginate(items, request.args)
    return success(page, 200, pg)


# ===========================================================================
# Borrowers
# ===========================================================================

@app.post("/property-solutions/borrowers")
def create_borrower():
    require_roles(ADMIN)
    data = body_json()
    rec = {
        "id": new_id(),
        "full_name": req_str(data, "full_name"),
        "email": req_str(data, "email"),
        "hardship_type": req_enum(data, "hardship_type", ENUM_HARDSHIP),
        "self_reported_condition_grade": req_enum(
            data, "self_reported_condition_grade", ENUM_CONDITION_GRADE),
    }
    stamp_new(rec)
    borrowers[rec["id"]] = rec
    return success(rec, 201)


@app.get("/property-solutions/borrowers/<bid>")
def get_borrower(bid):
    user_id, role = require_roles(ADMIN, SPECIALIST, MANAGER, BORROWER)
    rec = get_borrower_or_404(bid)
    if role == BORROWER and rec["id"] != user_id:
        raise err("ERR_FORBIDDEN", "Borrower may read only their own record")
    return success(rec, 200)


# ===========================================================================
# Properties
# ===========================================================================

@app.post("/property-solutions/properties")
def create_property():
    require_roles(ADMIN)
    data = body_json()
    loan_id = data.get("loan_id")
    if loan_id is None:
        raise err("ERR_INVALID_REQUEST", "Field 'loan_id' is required")
    get_loan_or_404(loan_id)
    rec = {
        "id": new_id(),
        "loan_id": loan_id,
        "address_line": req_str(data, "address_line"),
        "county": req_str(data, "county"),
        "state_code": req_str(data, "state_code"),
        "occupancy_type": req_enum(data, "occupancy_type", ENUM_OCCUPANCY),
        "required_condition_standard": opt_enum(
            data, "required_condition_standard", ENUM_CONDITION_STANDARD,
            "BROOM_CLEAN"),
    }
    stamp_new(rec)
    properties[rec["id"]] = rec
    return success(rec, 201)


@app.get("/property-solutions/properties/<pid>")
def get_property(pid):
    require_roles(*STAFF_READ_INSP)
    return success(get_property_or_404(pid), 200)


@app.get("/property-solutions/properties")
def list_properties():
    require_roles(*STAFF_READ_INSP)
    from flask import request
    items = sorted(properties.values(), key=lambda r: r["created_at"])
    loan_f = request.args.get("loan_id")
    if loan_f is not None:
        items = [p for p in items if p["loan_id"] == loan_f]
    page, pg = paginate(items, request.args)
    return success(page, 200, pg)


# ===========================================================================
# Workout cases
# ===========================================================================

@app.post("/property-solutions/cases")
def create_case():
    user_id, _ = require_roles(SPECIALIST)
    data = body_json()
    loan_id = data.get("loan_id")
    borrower_id = data.get("borrower_id")
    if loan_id is None:
        raise err("ERR_INVALID_REQUEST", "Field 'loan_id' is required")
    get_loan_or_404(loan_id)
    if borrower_id is None:
        raise err("ERR_INVALID_REQUEST", "Field 'borrower_id' is required")
    get_borrower_or_404(borrower_id)
    program_type = req_enum(data, "program_type", ENUM_PROGRAM_TYPE)
    rec = {
        "id": new_id(),
        "loan_id": loan_id,
        "borrower_id": borrower_id,
        "program_type": program_type,
        "status": "INTAKE",
        "assigned_specialist_id": user_id,
        "marketing_exception_granted": False,
        "marketing_exception_reason": None,
        "total_disbursed_cents": 0,
        "remaining_assistance_cents": None,
        "handover_date": None,
        "keys_returned": False,
    }
    stamp_new(rec)
    cases[rec["id"]] = rec
    return success(rec, 201)


@app.get("/property-solutions/cases/<cid>")
def get_case(cid):
    user_id, role = require_roles(*ALL_READ)
    rec = get_case_or_404(cid)
    check_borrower_case_read(user_id, role, rec)
    return success(rec, 200)


@app.get("/property-solutions/cases")
def list_cases():
    require_roles(*STAFF_READ_INSP)
    from flask import request
    items = sorted(cases.values(), key=lambda r: r["created_at"])
    loan_f = request.args.get("loan_id")
    if loan_f is not None:
        items = [c for c in items if c["loan_id"] == loan_f]
    bor_f = request.args.get("borrower_id")
    if bor_f is not None:
        items = [c for c in items if c["borrower_id"] == bor_f]
    status_f = request.args.get("status")
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    page, pg = paginate(items, request.args)
    return success(page, 200, pg)


@app.post("/property-solutions/cases/<cid>/submit")
def submit_case(cid):
    require_roles(SPECIALIST)
    case = get_case_or_404(cid)
    if case["status"] != "INTAKE":
        raise err("ERR_CASE_INVALID_STATE",
                  f"Case in {case['status']}; submit requires INTAKE")
    loan = loans[case["loan_id"]]
    if loan["status"] != "ACTIVE_DELINQUENT":
        raise err("ERR_LOAN_INVALID_STATE",
                  f"Loan in {loan['status']}; submit requires ACTIVE_DELINQUENT")
    case["status"] = "ELIGIBILITY_REVIEW"
    touch(case)
    loan["status"] = "WORKOUT_IN_PROGRESS"
    touch(loan)
    return success(case, 200)


@app.post("/property-solutions/cases/<cid>/evaluate-eligibility")
def evaluate_eligibility(cid):
    require_roles(SPECIALIST)
    case = get_case_or_404(cid)
    data = body_json()
    decision = req_enum(data, "decision", ENUM_DECISION)
    opt_str(data, "notes", None)
    if case["status"] != "ELIGIBILITY_REVIEW":
        raise err("ERR_CASE_INVALID_STATE",
                  f"Case in {case['status']}; evaluate-eligibility requires ELIGIBILITY_REVIEW")
    if decision == "PASS":
        loan = loans[case["loan_id"]]
        if loan["delinquency_days"] < 31 or loan["foreclosure_referral_status"] == "ACTIVE":
            raise err("ERR_ELIGIBILITY_CRITERIA_NOT_MET",
                      "Loan must be >= 31 days delinquent and foreclosure referral not ACTIVE")
        case["status"] = "MARKETING_PERIOD"
        touch(case)
    else:
        case["status"] = "DECLINED"
        touch(case)
        loan = loans[case["loan_id"]]
        if loan["status"] == "WORKOUT_IN_PROGRESS":
            loan["status"] = "ACTIVE_DELINQUENT"
            touch(loan)
    return success(case, 200)


@app.post("/property-solutions/cases/<cid>/marketing-exception")
def marketing_exception(cid):
    require_roles(MANAGER)
    case = get_case_or_404(cid)
    data = body_json()
    reason = req_str(data, "reason")
    if case["status"] != "MARKETING_PERIOD":
        raise err("ERR_CASE_INVALID_STATE",
                  f"Case in {case['status']}; marketing-exception requires MARKETING_PERIOD")
    case["marketing_exception_granted"] = True
    case["marketing_exception_reason"] = reason
    touch(case)
    return success(case, 200)


@app.post("/property-solutions/cases/<cid>/certify-marketing")
def certify_marketing(cid):
    require_roles(SPECIALIST)
    case = get_case_or_404(cid)
    if case["status"] != "MARKETING_PERIOD":
        raise err("ERR_CASE_INVALID_STATE",
                  f"Case in {case['status']}; certify-marketing requires MARKETING_PERIOD")
    ls = sorted(case_listings(cid), key=lambda r: r["created_at"])
    if not ls:
        raise err("ERR_LISTING_MISSING",
                  "At least one MarketingListing must exist for the case")
    latest = ls[-1]
    refresh_creditable_days(latest)
    if latest["creditable_days"] < MARKETING_MIN_DAYS and not case["marketing_exception_granted"]:
        raise err("ERR_MARKETING_PERIOD_NOT_MET",
                  f"Latest listing has {latest['creditable_days']} creditable days; need >= {MARKETING_MIN_DAYS} or a marketing exception")
    case["status"] = "TITLE_REVIEW"
    touch(case)
    return success(case, 200)


@app.post("/property-solutions/cases/<cid>/certify-title")
def certify_title(cid):
    require_roles(SPECIALIST)
    case = get_case_or_404(cid)
    if case["status"] != "TITLE_REVIEW":
        raise err("ERR_CASE_INVALID_STATE",
                  f"Case in {case['status']}; certify-title requires TITLE_REVIEW")
    tcs = sorted(case_commitments(cid), key=lambda r: r["created_at"])
    if not tcs:
        raise err("ERR_TITLE_COMMITMENT_MISSING",
                  "A TitleCommitment must exist for the case")
    tc = tcs[-1]
    if tc["status"] == "CLEARED":
        pass
    elif tc["status"] == "ORDERED":
        raise err("ERR_TITLE_INVALID_STATE",
                  "Title commitment is ORDERED (not yet received)")
    else:  # RECEIVED with unreleased liens
        raise err("ERR_JUNIOR_LIENS_OUTSTANDING",
                  "Title commitment carries UNRELEASED junior liens")
    case["status"] = "TERMS_NEGOTIATION"
    touch(case)
    return success(case, 200)


@app.post("/property-solutions/cases/<cid>/escalate-holdover")
def escalate_holdover(cid):
    require_roles(MANAGER)
    case = get_case_or_404(cid)
    if case["status"] not in ("AGREEMENT_ACTIVE", "VACATE_PENDING",
                              "HANDOVER_INSPECTION", "DISBURSEMENT_PENDING"):
        raise err("ERR_CASE_INVALID_STATE",
                  f"Case in {case['status']}; escalation requires AGREEMENT_ACTIVE, VACATE_PENDING, HANDOVER_INSPECTION, or DISBURSEMENT_PENDING")
    agreement = case_accepted_agreement(case)
    if agreement is None:
        raise err("ERR_AGREEMENT_NOT_FOUND",
                  "No ACCEPTED agreement exists for the case")
    vacate_d = db.parse_date(agreement["vacate_date"])
    if not (today() > vacate_d + timedelta(days=HOLDOVER_GRACE_DAYS)):
        raise err("ERR_HOLDOVER_GRACE_NOT_ELAPSED",
                  "Holdover grace period (vacate_date + 3 days) has not elapsed")
    rec = {
        "id": new_id(),
        "case_id": case["id"],
        "reason": "HOLDOVER",
        "status": "ESCALATED",
        "court_reference": None,
        "filed_at": None,
        "dismissal_reason": None,
    }
    stamp_new(rec)
    evictions[rec["id"]] = rec
    case["status"] = "HOLDOVER_ESCALATED"
    touch(case)
    return success(rec, 201)


@app.post("/property-solutions/cases/<cid>/withdraw")
def withdraw_case(cid):
    user_id, role = require_roles(SPECIALIST, BORROWER)
    case = get_case_or_404(cid)
    if role == BORROWER and case["borrower_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Borrower may withdraw only their own case")
    if case["status"] not in ("INTAKE", "ELIGIBILITY_REVIEW", "MARKETING_PERIOD",
                              "TITLE_REVIEW", "TERMS_NEGOTIATION",
                              "AGREEMENT_ACTIVE", "VACATE_PENDING",
                              "HOLDOVER_ESCALATED"):
        raise err("ERR_CASE_INVALID_STATE",
                  f"Case in {case['status']}; withdrawal not permitted")
    case["status"] = "WITHDRAWN"
    touch(case)
    withdraw_cascade(case)
    return success(case, 200)


# --- Case sub-resource reads ------------------------------------------------

def _case_sub_list(cid, collection, key):
    user_id, role = require_roles(*ALL_READ)
    case = get_case_or_404(cid)
    check_borrower_case_read(user_id, role, case)
    from flask import request
    items = sorted((r for r in collection.values() if r[key] == cid),
                   key=lambda r: r["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, 200, pg)


@app.get("/property-solutions/cases/<cid>/listings")
def case_listings_ep(cid):
    return _case_sub_list(cid, listings, "case_id")


@app.get("/property-solutions/cases/<cid>/title-commitments")
def case_title_commitments_ep(cid):
    return _case_sub_list(cid, title_commitments, "case_id")


@app.get("/property-solutions/cases/<cid>/agreements")
def case_agreements_ep(cid):
    user_id, role = require_roles(*ALL_READ)
    case = get_case_or_404(cid)
    check_borrower_case_read(user_id, role, case)
    from flask import request
    col = sorted((r for r in agreements.values() if r["case_id"] == cid),
                 key=lambda r: r["created_at"])
    for a in col:
        lazy_expire_agreement(a)
    page, pg = paginate(col, request.args)
    return success(page, 200, pg)


@app.get("/property-solutions/cases/<cid>/inspection-appointments")
def case_appointments_ep(cid):
    return _case_sub_list(cid, appointments, "case_id")


@app.get("/property-solutions/cases/<cid>/inspection-reports")
def case_reports_ep(cid):
    return _case_sub_list(cid, reports, "case_id")


@app.get("/property-solutions/cases/<cid>/disbursements")
def case_disbursements_ep(cid):
    user_id, role = require_roles(*(STAFF_READ + (BORROWER,)))
    case = get_case_or_404(cid)
    check_borrower_case_read(user_id, role, case)
    from flask import request
    items = sorted((r for r in disbursements.values() if r["case_id"] == cid),
                   key=lambda r: r["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, 200, pg)


@app.get("/property-solutions/cases/<cid>/deficiency-waivers")
def case_waivers_ep(cid):
    user_id, role = require_roles(*(STAFF_READ + (BORROWER,)))
    case = get_case_or_404(cid)
    check_borrower_case_read(user_id, role, case)
    from flask import request
    items = sorted((r for r in waivers.values() if r["case_id"] == cid),
                   key=lambda r: r["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, 200, pg)


@app.get("/property-solutions/cases/<cid>/deed-recordings")
def case_recordings_ep(cid):
    user_id, role = require_roles(*(STAFF_READ + (BORROWER,)))
    case = get_case_or_404(cid)
    check_borrower_case_read(user_id, role, case)
    from flask import request
    items = sorted((r for r in recordings.values() if r["case_id"] == cid),
                   key=lambda r: r["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, 200, pg)


@app.get("/property-solutions/cases/<cid>/eviction-cases")
def case_evictions_ep(cid):
    user_id, role = require_roles(*(STAFF_READ + (BORROWER,)))
    case = get_case_or_404(cid)
    check_borrower_case_read(user_id, role, case)
    from flask import request
    items = sorted((r for r in evictions.values() if r["case_id"] == cid),
                   key=lambda r: r["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, 200, pg)


# ===========================================================================
# Marketing listings
# ===========================================================================

@app.post("/property-solutions/listings")
def create_listing():
    require_roles(SPECIALIST)
    data = body_json()
    case_id = data.get("case_id")
    if case_id is None:
        raise err("ERR_INVALID_REQUEST", "Field 'case_id' is required")
    case = get_case_or_404(case_id)
    list_date_raw, list_d = req_iso_date(data, "list_date")
    price = req_int(data, "list_price_cents")
    if price <= 0:
        raise err("ERR_INVALID_REQUEST", "list_price_cents must be > 0")
    if list_d > today():
        raise err("ERR_INVALID_REQUEST", "list_date must not be in the future")
    if case["status"] != "MARKETING_PERIOD":
        raise err("ERR_CASE_INVALID_STATE",
                  f"Case in {case['status']}; listing creation requires MARKETING_PERIOD")
    for l in listings.values():
        if l["case_id"] == case_id and l["status"] in ("ACTIVE", "SUSPENDED"):
            raise err("ERR_ACTIVE_LISTING_EXISTS",
                      "Case already has a non-CLOSED listing")
    rec = {
        "id": new_id(),
        "case_id": case_id,
        "list_date": list_date_raw,
        "list_price_cents": price,
        "status": "ACTIVE",
        "creditable_days": 0,
        "closed_at": None,
    }
    stamp_new(rec)
    listings[rec["id"]] = rec
    refresh_creditable_days(rec)
    return success(rec, 201)


@app.get("/property-solutions/listings/<lid>")
def get_listing(lid):
    require_roles(*ALL_READ)
    rec = get_listing_or_404(lid)
    if rec["status"] != "CLOSED":
        refresh_creditable_days(rec)
    return success(rec, 200)


@app.post("/property-solutions/listings/<lid>/suspend")
def suspend_listing(lid):
    require_roles(SPECIALIST)
    rec = get_listing_or_404(lid)
    data = body_json()
    reason = req_str(data, "reason")
    if rec["status"] != "ACTIVE":
        raise err("ERR_LISTING_INVALID_STATE",
                  f"Listing in {rec['status']}; suspend requires ACTIVE")
    rec["status"] = "SUSPENDED"
    susp = {
        "id": new_id(),
        "listing_id": rec["id"],
        "started_at": iso_ts(now_dt()),
        "ended_at": None,
        "reason": reason,
    }
    stamp_new(susp)
    suspensions[susp["id"]] = susp
    refresh_creditable_days(rec)
    touch(rec)
    return success(rec, 200)


@app.post("/property-solutions/listings/<lid>/resume")
def resume_listing(lid):
    require_roles(SPECIALIST)
    rec = get_listing_or_404(lid)
    if rec["status"] != "SUSPENDED":
        raise err("ERR_LISTING_INVALID_STATE",
                  f"Listing in {rec['status']}; resume requires SUSPENDED")
    for s in suspensions.values():
        if s["listing_id"] == rec["id"] and s.get("ended_at") is None:
            s["ended_at"] = iso_ts(now_dt())
            touch(s)
    rec["status"] = "ACTIVE"
    refresh_creditable_days(rec)
    touch(rec)
    return success(rec, 200)


@app.post("/property-solutions/listings/<lid>/close")
def close_listing(lid):
    require_roles(SPECIALIST)
    rec = get_listing_or_404(lid)
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_LISTING_INVALID_STATE",
                  f"Listing in {rec['status']}; close requires ACTIVE or SUSPENDED")
    _close_listing(rec)
    return success(rec, 200)


@app.get("/property-solutions/listings/<lid>/suspensions")
def list_suspensions(lid):
    require_roles(*ALL_READ)
    rec = get_listing_or_404(lid)
    from flask import request
    items = sorted((s for s in suspensions.values() if s["listing_id"] == rec["id"]),
                   key=lambda r: r["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, 200, pg)


# ===========================================================================
# Title commitments & junior liens
# ===========================================================================

@app.post("/property-solutions/title-commitments")
def create_commitment():
    require_roles(TITLE)
    data = body_json()
    case_id = data.get("case_id")
    if case_id is None:
        raise err("ERR_INVALID_REQUEST", "Field 'case_id' is required")
    case = get_case_or_404(case_id)
    if case["status"] != "TITLE_REVIEW":
        raise err("ERR_CASE_INVALID_STATE",
                  f"Case in {case['status']}; ordering a commitment requires TITLE_REVIEW")
    rec = {
        "id": new_id(),
        "case_id": case_id,
        "status": "ORDERED",
        "vested_owner_name": None,
        "unreleased_lien_count": 0,
    }
    stamp_new(rec)
    title_commitments[rec["id"]] = rec
    return success(rec, 201)


@app.get("/property-solutions/title-commitments/<tid>")
def get_commitment(tid):
    require_roles(*STAFF_READ)
    return success(get_commitment_or_404(tid), 200)


@app.post("/property-solutions/title-commitments/<tid>/receive")
def receive_commitment(tid):
    require_roles(TITLE)
    rec = get_commitment_or_404(tid)
    data = body_json()
    owner = req_str(data, "vested_owner_name")
    if rec["status"] != "ORDERED":
        raise err("ERR_TITLE_INVALID_STATE",
                  f"Commitment in {rec['status']}; receive requires ORDERED")
    rec["status"] = "RECEIVED"
    rec["vested_owner_name"] = owner
    touch(rec)
    if rec["unreleased_lien_count"] == 0:
        rec["status"] = "CLEARED"
        touch(rec)
    return success(rec, 200)


@app.post("/property-solutions/title-commitments/<tid>/liens")
def add_lien(tid):
    require_roles(TITLE)
    rec = get_commitment_or_404(tid)
    data = body_json()
    lienholder = req_str(data, "lienholder_name")
    amount = req_int(data, "amount_cents")
    if amount <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be > 0")
    position = req_int(data, "position")
    if position < 2:
        raise err("ERR_INVALID_REQUEST", "position must be >= 2")
    if rec["status"] not in ("RECEIVED", "CLEARED"):
        raise err("ERR_TITLE_INVALID_STATE",
                  f"Commitment in {rec['status']}; adding a lien requires RECEIVED or CLEARED")
    for l in liens.values():
        if l["title_commitment_id"] == tid and l["position"] == position:
            raise err("ERR_LIEN_POSITION_DUPLICATE",
                      f"A lien with position {position} already exists on this commitment")
    lien = {
        "id": new_id(),
        "title_commitment_id": tid,
        "lienholder_name": lienholder,
        "amount_cents": amount,
        "position": position,
        "status": "UNRELEASED",
        "settlement_amount_cents": None,
        "released_at": None,
    }
    stamp_new(lien)
    liens[lien["id"]] = lien
    rec["unreleased_lien_count"] += 1
    if rec["status"] == "CLEARED":
        rec["status"] = "RECEIVED"
    touch(rec)
    return success(lien, 201)


@app.get("/property-solutions/title-commitments/<tid>/liens")
def list_liens(tid):
    require_roles(*STAFF_READ)
    rec = get_commitment_or_404(tid)
    from flask import request
    items = sorted((l for l in liens.values() if l["title_commitment_id"] == tid),
                   key=lambda r: r["created_at"])
    status_f = request.args.get("status")
    if status_f is not None:
        items = [l for l in items if l["status"] == status_f]
    page, pg = paginate(items, request.args)
    return success(page, 200, pg)


@app.post("/property-solutions/title-commitments/<tid>/lien-releases")
def release_lien(tid):
    require_roles(TITLE)
    rec = get_commitment_or_404(tid)
    data = body_json()
    lien_id = data.get("lien_id")
    if lien_id is None:
        raise err("ERR_INVALID_REQUEST", "Field 'lien_id' is required")
    lien = liens.get(lien_id)
    if lien is None or lien["title_commitment_id"] != tid:
        raise err("ERR_LIEN_NOT_FOUND",
                  f"Lien {lien_id} does not resolve on commitment {tid}")
    settlement = req_int(data, "settlement_amount_cents")
    expected = data.get("expected_title_commitment_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST",
                  "Field 'expected_title_commitment_version' is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST",
                  "expected_title_commitment_version must be an integer")
    if lien["status"] != "UNRELEASED":
        raise err("ERR_LIEN_INVALID_STATE",
                  f"Lien in {lien['status']}; release requires UNRELEASED")
    if expected != rec["version"]:
        raise err("ERR_STALE_TITLE_VERSION",
                  f"expected_title_commitment_version {expected} does not match current version {rec['version']}")
    if settlement > lien["amount_cents"]:
        raise err("ERR_SETTLEMENT_EXCEEDS_LIEN",
                  "settlement_amount_cents must not exceed lien amount_cents")
    lien["status"] = "RELEASED"
    lien["settlement_amount_cents"] = settlement
    lien["released_at"] = iso_ts(now_dt())
    touch(lien)
    rec["unreleased_lien_count"] -= 1
    touch(rec)
    if rec["unreleased_lien_count"] == 0 and rec["status"] == "RECEIVED":
        rec["status"] = "CLEARED"
        touch(rec)
    return success(lien, 200)


# ===========================================================================
# Settlement agreements
# ===========================================================================

@app.post("/property-solutions/cases/<cid>/agreements")
def create_agreement(cid):
    user_id, _ = require_roles(SPECIALIST)
    case = get_case_or_404(cid)
    data = body_json()
    vacate_raw, vacate_d = req_iso_date(data, "vacate_date")
    expected = data.get("expected_case_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST", "Field 'expected_case_version' is required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_case_version must be an integer")
    if case["status"] != "TERMS_NEGOTIATION":
        raise err("ERR_CASE_INVALID_STATE",
                  f"Case in {case['status']}; agreement creation requires TERMS_NEGOTIATION")
    # one-active-agreement rule
    for a in agreements.values():
        if a["case_id"] == cid and a["status"] in ("OFFERED", "COUNTERED", "ACCEPTED"):
            raise err("ERR_ACTIVE_AGREEMENT_EXISTS",
                      "Case has an OFFERED, COUNTERED, or ACCEPTED agreement")
    if expected != case["version"]:
        raise err("ERR_STALE_VERSION",
                  f"expected_case_version {expected} does not match current version {case['version']}")
    if vacate_d < today() + timedelta(days=MIN_VACATE_NOTICE_DAYS):
        raise err("ERR_VACATE_DATE_TOO_SOON",
                  f"vacate_date must be at least {MIN_VACATE_NOTICE_DAYS} days after the current logical date")
    # supersede existing DRAFT
    for a in agreements.values():
        if a["case_id"] == cid and a["status"] == "DRAFT":
            a["status"] = "SUPERSEDED"
            touch(a)
    loan = loans[case["loan_id"]]
    prop = next((p for p in properties.values() if p["loan_id"] == case["loan_id"]), None)
    if prop is None:
        raise err("ERR_PROPERTY_NOT_FOUND",
                  f"No property registered for loan {case['loan_id']}")
    borrower = borrowers[case["borrower_id"]]
    provisional = provisional_assistance_quote(loan, prop, borrower)
    rec = {
        "id": new_id(),
        "case_id": cid,
        "vacate_date": vacate_raw,
        "provisional_assistance_cents": provisional,
        "final_assistance_cents": None,
        "condition_basis": "SELF_REPORTED",
        "status": "DRAFT",
        "offer_expires_at": None,
        "round_number": 0,
        "created_by_specialist_id": user_id,
        "accepted_at": None,
    }
    stamp_new(rec)
    agreements[rec["id"]] = rec
    recompute_remaining(case)
    touch(case)
    return success(rec, 201)


@app.get("/property-solutions/agreements/<aid>")
def get_agreement(aid):
    user_id, role = require_roles(*(STAFF_READ + (BORROWER,)))
    rec = get_agreement_or_404(aid)
    if role == BORROWER:
        case = cases.get(rec["case_id"])
        if case is None or case["borrower_id"] != user_id:
            raise err("ERR_FORBIDDEN", "Borrower may read only their own case's agreements")
    lazy_expire_agreement(rec)
    return success(rec, 200)


@app.post("/property-solutions/agreements/<aid>/offer")
def offer_agreement(aid):
    require_roles(SPECIALIST)
    rec = get_agreement_or_404(aid)
    data = body_json()
    valid_days = req_int(data, "offer_valid_days")
    lazy_expire_agreement(rec)
    if rec["status"] != "DRAFT":
        raise err("ERR_AGREEMENT_INVALID_STATE",
                  f"Agreement in {rec['status']}; offer requires DRAFT")
    rec["status"] = "OFFERED"
    rec["offer_expires_at"] = iso_ts(now_dt() + timedelta(days=valid_days))
    touch(rec)
    return success(rec, 200)


@app.post("/property-solutions/agreements/<aid>/counter")
def counter_agreement(aid):
    user_id, _ = require_roles(BORROWER)
    rec = get_agreement_or_404(aid)
    data = body_json()
    proposed_raw, proposed_d = req_iso_date(data, "proposed_vacate_date")
    # No pre-emptive lazy expiry here: on counter the pinned guard order is
    # state -> ownership -> expiry, and the expiry guard itself flips the
    # agreement to EXPIRED while reporting ERR_OFFER_EXPIRED (PRD §3.5).
    if rec["status"] != "OFFERED":
        raise err("ERR_AGREEMENT_INVALID_STATE",
                  f"Agreement in {rec['status']}; counter requires OFFERED")
    case = cases[rec["case_id"]]
    if case["borrower_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Borrower may counter only their own case's agreement")
    exp = db.parse_dt(rec["offer_expires_at"])
    if exp is not None and now_dt() > exp:
        rec["status"] = "EXPIRED"
        touch(rec)
        raise err("ERR_OFFER_EXPIRED", "The offer has expired")
    if proposed_d < today() + timedelta(days=MIN_VACATE_NOTICE_DAYS):
        raise err("ERR_VACATE_DATE_TOO_SOON",
                  f"proposed_vacate_date must be at least {MIN_VACATE_NOTICE_DAYS} days after the current logical date")
    rec["vacate_date"] = proposed_raw
    rec["status"] = "COUNTERED"
    touch(rec)
    recompute_remaining(case)
    return success(rec, 200)


@app.post("/property-solutions/agreements/<aid>/reoffer")
def reoffer_agreement(aid):
    require_roles(SPECIALIST)
    rec = get_agreement_or_404(aid)
    data = body_json()
    vacate_raw, vacate_d = req_iso_date(data, "vacate_date")
    valid_days = req_int(data, "offer_valid_days")
    lazy_expire_agreement(rec)
    if rec["status"] != "COUNTERED":
        raise err("ERR_AGREEMENT_INVALID_STATE",
                  f"Agreement in {rec['status']}; reoffer requires COUNTERED")
    if rec["round_number"] >= MAX_NEGOTIATION_ROUNDS:
        raise err("ERR_NEGOTIATION_ROUND_LIMIT",
                  f"Negotiation round cap of {MAX_NEGOTIATION_ROUNDS} reached")
    if vacate_d < today() + timedelta(days=MIN_VACATE_NOTICE_DAYS):
        raise err("ERR_VACATE_DATE_TOO_SOON",
                  f"vacate_date must be at least {MIN_VACATE_NOTICE_DAYS} days after the current logical date")
    case = cases[rec["case_id"]]
    loan = loans[case["loan_id"]]
    prop = next((p for p in properties.values() if p["loan_id"] == case["loan_id"]), None)
    borrower = borrowers[case["borrower_id"]]
    rec["vacate_date"] = vacate_raw
    rec["round_number"] += 1
    rec["provisional_assistance_cents"] = provisional_assistance_quote(loan, prop, borrower)
    rec["offer_expires_at"] = iso_ts(now_dt() + timedelta(days=valid_days))
    rec["status"] = "OFFERED"
    touch(rec)
    recompute_remaining(case)
    return success(rec, 200)


@app.post("/property-solutions/agreements/<aid>/accept")
def accept_agreement(aid):
    user_id, _ = require_roles(BORROWER)
    rec = get_agreement_or_404(aid)
    # No pre-emptive lazy expiry here: on accept the pinned guard order is
    # state -> ownership -> expiry, and the expiry guard itself flips the
    # agreement to EXPIRED while reporting ERR_OFFER_EXPIRED (PRD §3.5).
    if rec["status"] != "OFFERED":
        raise err("ERR_AGREEMENT_INVALID_STATE",
                  f"Agreement in {rec['status']}; accept requires OFFERED")
    case = cases[rec["case_id"]]
    if case["borrower_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Borrower may accept only their own case's agreement")
    # temporal guard before referential (lien) check
    exp = db.parse_dt(rec["offer_expires_at"])
    if exp is not None and now_dt() > exp:
        rec["status"] = "EXPIRED"
        touch(rec)
        raise err("ERR_OFFER_EXPIRED", "The offer has expired")
    if case["program_type"] == "DEED_IN_LIEU":
        tcs = case_commitments(case["id"])
        if tcs:
            tc = sorted(tcs, key=lambda r: r["created_at"])[-1]
            if tc["unreleased_lien_count"] > 0:
                raise err("ERR_JUNIOR_LIENS_OUTSTANDING",
                          "A junior lien is still UNRELEASED on the case's title commitment")
    rec["status"] = "ACCEPTED"
    rec["accepted_at"] = iso_ts(now_dt())
    touch(rec)
    # bubble up: case TERMS_NEGOTIATION -> AGREEMENT_ACTIVE
    if case["status"] == "TERMS_NEGOTIATION":
        case["status"] = "AGREEMENT_ACTIVE"
    recompute_remaining(case)
    touch(case)
    if case["program_type"] == "DEED_IN_LIEU":
        loan = loans[case["loan_id"]]
        accepted_d = db.parse_dt(rec["accepted_at"]).date()
        vacate_d2 = db.parse_date(rec["vacate_date"])
        projected = deficiency_waiver_amount(loan, accepted_d, vacate_d2)
        w = {
            "id": new_id(),
            "case_id": case["id"],
            "loan_id": case["loan_id"],
            "status": "DRAFT",
            "projected_waiver_cents": projected,
            "final_waiver_cents": None,
            "pre_waiver_deficiency_cents": 0,
            "waived_amount_cents": 0,
            "document_reference": None,
        }
        stamp_new(w)
        waivers[w["id"]] = w
    return success(rec, 200)


@app.post("/property-solutions/agreements/<aid>/terminate")
def terminate_agreement(aid):
    require_roles(MANAGER)
    rec = get_agreement_or_404(aid)
    lazy_expire_agreement(rec)
    if rec["status"] != "ACCEPTED":
        raise err("ERR_AGREEMENT_INVALID_STATE",
                  f"Agreement in {rec['status']}; terminate requires ACCEPTED")
    terminate_accepted_agreement(rec)
    return success(rec, 200)


@app.get("/property-solutions/agreements/<aid>/disbursements")
def agreement_disbursements(aid):
    user_id, role = require_roles(*(STAFF_READ + (BORROWER,)))
    rec = get_agreement_or_404(aid)
    if role == BORROWER:
        case = cases.get(rec["case_id"])
        if case is None or case["borrower_id"] != user_id:
            raise err("ERR_FORBIDDEN", "Borrower may read only their own case's disbursements")
    from flask import request
    items = sorted((d for d in disbursements.values() if d["agreement_id"] == aid),
                   key=lambda r: r["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, 200, pg)


# ===========================================================================
# Inspection appointments & reports
# ===========================================================================

@app.post("/property-solutions/inspection-appointments")
def create_appointment():
    require_roles(SPECIALIST)
    data = body_json()
    case_id = data.get("case_id")
    if case_id is None:
        raise err("ERR_INVALID_REQUEST", "Field 'case_id' is required")
    case = get_case_or_404(case_id)
    inspector_id = req_str(data, "inspector_id")
    appt_type = req_enum(data, "appointment_type", ENUM_APPOINTMENT_TYPE)
    start_raw, start_dt = req_iso_datetime(data, "scheduled_start")
    end_raw, end_dt = req_iso_datetime(data, "scheduled_end")
    if end_dt <= start_dt:
        raise err("ERR_INVALID_REQUEST", "scheduled_end must be > scheduled_start")
    # case posture gate (state check, priority 5)
    if appt_type == "HANDOVER":
        if case["status"] not in ("AGREEMENT_ACTIVE", "VACATE_PENDING"):
            raise err("ERR_CASE_INVALID_STATE",
                      f"Case in {case['status']}; HANDOVER scheduling requires AGREEMENT_ACTIVE or VACATE_PENDING")
    else:  # RE_INSPECTION
        if case["status"] != "VACATE_PENDING":
            raise err("ERR_CASE_INVALID_STATE",
                      f"Case in {case['status']}; RE_INSPECTION scheduling requires VACATE_PENDING")
    # calendar conflict first (priority 10), then notice (priority 14)
    buf = timedelta(minutes=INSPECTION_TRAVEL_BUFFER_MINUTES)
    new_start, new_end = start_dt, end_dt + buf
    for a in appointments.values():
        if a["inspector_id"] != inspector_id or a["status"] != "SCHEDULED":
            continue
        a_start = db.parse_dt(a["scheduled_start"])
        a_end = db.parse_dt(a["scheduled_end"]) + buf
        # half-open interval intersection; touching endpoints allowed
        if new_start < a_end and a_start < new_end:
            raise err("ERR_INSPECTOR_SCHEDULE_CONFLICT",
                      "New appointment's buffered interval intersects another SCHEDULED appointment for the same inspector")
    if start_dt < now_dt() + timedelta(hours=INSPECTION_MIN_NOTICE_HOURS):
        raise err("ERR_INSPECTION_TOO_SOON",
                  f"scheduled_start must be at least {INSPECTION_MIN_NOTICE_HOURS} hours in the future")
    rec = {
        "id": new_id(),
        "case_id": case_id,
        "inspector_id": inspector_id,
        "appointment_type": appt_type,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "status": "SCHEDULED",
    }
    stamp_new(rec)
    appointments[rec["id"]] = rec
    if appt_type == "HANDOVER" and case["status"] == "AGREEMENT_ACTIVE":
        case["status"] = "VACATE_PENDING"
        touch(case)
    return success(rec, 201)


@app.get("/property-solutions/inspection-appointments/<aid>")
def get_appointment(aid):
    require_roles(*STAFF_READ_INSP)
    return success(get_appointment_or_404(aid), 200)


@app.post("/property-solutions/inspection-appointments/<aid>/cancel")
def cancel_appointment(aid):
    require_roles(SPECIALIST)
    rec = get_appointment_or_404(aid)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_APPOINTMENT_INVALID_STATE",
                  f"Appointment in {rec['status']}; cancel requires SCHEDULED")
    rec["status"] = "CANCELLED"
    touch(rec)
    return success(rec, 200)


@app.post("/property-solutions/inspection-appointments/<aid>/no-access")
def no_access_appointment(aid):
    user_id, _ = require_roles(INSPECTOR)
    rec = get_appointment_or_404(aid)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_APPOINTMENT_INVALID_STATE",
                  f"Appointment in {rec['status']}; no-access requires SCHEDULED")
    if rec["inspector_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Inspector identity does not match appointment.inspector_id")
    rec["status"] = "NO_ACCESS"
    touch(rec)
    return success(rec, 200)


@app.post("/property-solutions/inspection-appointments/<aid>/reports")
def create_report(aid):
    user_id, _ = require_roles(INSPECTOR)
    appt = get_appointment_or_404(aid)
    data = body_json()
    broom = req_bool(data, "broom_clean_verified")
    keys = req_int(data, "keys_returned_count")
    if keys < 0:
        raise err("ERR_INVALID_REQUEST", "keys_returned_count must be >= 0")
    line_items = data.get("line_items")
    if line_items is None:
        line_items = []
    if not isinstance(line_items, list):
        raise err("ERR_INVALID_REQUEST", "line_items must be an array")
    for line in line_items:
        if not isinstance(line, dict):
            raise err("ERR_INVALID_REQUEST", "each line_items entry must be an object")
        if "item_code" not in line or line["item_code"] not in ENUM_ITEM_CODE:
            raise err("ERR_INVALID_ENUM", "line item_code outside its declared domain")
        if "severity" not in line or line["severity"] not in ENUM_SEVERITY:
            raise err("ERR_INVALID_ENUM", "line severity outside its declared domain")
    if appt["status"] != "SCHEDULED":
        raise err("ERR_APPOINTMENT_INVALID_STATE",
                  f"Appointment in {appt['status']}; report creation requires SCHEDULED")
    if appt["inspector_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Inspector identity does not match appointment.inspector_id")
    rec = {
        "id": new_id(),
        "appointment_id": appt["id"],
        "case_id": appt["case_id"],
        "status": "DRAFT",
        "broom_clean_verified": broom,
        "keys_returned_count": keys,
        "line_items": line_items,
        "total_deduction_cents": 0,
        "result": None,
    }
    stamp_new(rec)
    reports[rec["id"]] = rec
    return success(rec, 201)


@app.get("/property-solutions/inspection-appointments/<aid>/reports")
def appointment_reports(aid):
    require_roles(*STAFF_READ_INSP)
    appt = get_appointment_or_404(aid)
    from flask import request
    items = sorted((r for r in reports.values() if r["appointment_id"] == appt["id"]),
                   key=lambda r: r["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, 200, pg)


@app.get("/property-solutions/inspection-reports/<rid>")
def get_report(rid):
    user_id, role = require_roles(*ALL_READ)
    rec = get_report_or_404(rid)
    if role == BORROWER:
        case = cases.get(rec["case_id"])
        if case is None or case["borrower_id"] != user_id:
            raise err("ERR_FORBIDDEN", "Borrower may read only their own case's reports")
    return success(rec, 200)


@app.post("/property-solutions/inspection-reports/<rid>/submit")
def submit_report(rid):
    user_id, _ = require_roles(INSPECTOR)
    rec = get_report_or_404(rid)
    if rec["status"] != "DRAFT":
        raise err("ERR_REPORT_INVALID_STATE",
                  f"Report in {rec['status']}; submit requires DRAFT")
    appt = appointments.get(rec["appointment_id"])
    if appt is not None and appt["inspector_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Inspector identity does not match appointment.inspector_id")
    # compute deductions (per-item rounding, then sum) and derive result
    rec["total_deduction_cents"] = condition_deduction_schedule(rec["line_items"])
    has_structural = any(l["item_code"] == "STRUCTURAL_DAMAGE" for l in rec["line_items"])
    if (not rec["broom_clean_verified"]) or has_structural:
        rec["result"] = "FAILED"
    elif rec["total_deduction_cents"] > 0:
        rec["result"] = "PASSED_WITH_DEDUCTIONS"
    else:
        rec["result"] = "PASSED"
    rec["status"] = "SUBMITTED"
    touch(rec)
    # Hop 1: appointment -> COMPLETED; case VACATE_PENDING -> HANDOVER_INSPECTION
    if appt is not None and appt["status"] == "SCHEDULED":
        appt["status"] = "COMPLETED"
        touch(appt)
    case = cases.get(rec["case_id"])
    if case is not None and case["status"] == "VACATE_PENDING":
        case["status"] = "HANDOVER_INSPECTION"
        case["handover_date"] = today().isoformat()
        case["keys_returned"] = rec["keys_returned_count"] > 0
        # Hop 2: fork on result
        if rec["result"] in ("PASSED", "PASSED_WITH_DEDUCTIONS"):
            case["status"] = "DISBURSEMENT_PENDING"
            agreement = case_accepted_agreement(case)
            if agreement is not None:
                agreement["condition_basis"] = "INSPECTED"
                vacate_d = db.parse_date(agreement["vacate_date"])
                handover_d = today()
                agreement["final_assistance_cents"] = final_assistance_settlement(
                    agreement["provisional_assistance_cents"],
                    rec["total_deduction_cents"], vacate_d, handover_d)
                touch(agreement)
        else:
            case["status"] = "VACATE_PENDING"
        recompute_remaining(case)
        touch(case)
    return success(rec, 200)


# ===========================================================================
# Disbursements
# ===========================================================================

@app.post("/property-solutions/cases/<cid>/disbursements")
def create_disbursement(cid):
    user_id, _ = require_roles(SPECIALIST)
    case = get_case_or_404(cid)
    data = body_json()
    agreement_id = data.get("agreement_id")
    if agreement_id is None:
        raise err("ERR_INVALID_REQUEST", "Field 'agreement_id' is required")
    get_agreement_or_404(agreement_id)
    amount = req_int(data, "amount_cents")
    opt_enum(data, "purpose", ENUM_PURPOSE, "RELOCATION_ASSISTANCE")
    if case["status"] != "DISBURSEMENT_PENDING":
        raise err("ERR_CASE_INVALID_STATE",
                  f"Case in {case['status']}; disbursement request requires DISBURSEMENT_PENDING")
    if amount <= 0:
        raise err("ERR_DISBURSEMENT_NOT_POSITIVE", "amount_cents must be > 0")
    remaining = case["remaining_assistance_cents"]
    if remaining is None or amount > remaining:
        raise err("ERR_DISBURSEMENT_EXCEEDS_REMAINING",
                  "amount_cents exceeds the case's remaining_assistance_cents")
    rec = {
        "id": new_id(),
        "case_id": cid,
        "agreement_id": agreement_id,
        "amount_cents": amount,
        "purpose": "RELOCATION_ASSISTANCE",
        "status": "PENDING",
        "requested_by_user_id": user_id,
        "approved_by_user_id": None,
        "released_by_user_id": None,
        "released_at": None,
    }
    stamp_new(rec)
    disbursements[rec["id"]] = rec
    return success(rec, 201)


@app.get("/property-solutions/disbursements/<did>")
def get_disbursement(did):
    require_roles(*STAFF_READ)
    return success(get_disbursement_or_404(did), 200)


@app.post("/property-solutions/disbursements/<did>/approve")
def approve_disbursement(did):
    user_id, _ = require_roles(OFFICER)
    rec = get_disbursement_or_404(did)
    if rec["status"] != "PENDING":
        raise err("ERR_DISBURSEMENT_INVALID_STATE",
                  f"Disbursement in {rec['status']}; approve requires PENDING")
    if user_id == rec["requested_by_user_id"]:
        raise err("ERR_SOD_APPROVER_EQUALS_REQUESTER",
                  "Approver must differ from the requester")
    rec["status"] = "APPROVED"
    rec["approved_by_user_id"] = user_id
    touch(rec)
    return success(rec, 200)


@app.post("/property-solutions/disbursements/<did>/release")
def release_disbursement(did):
    user_id, _ = require_roles(OFFICER)
    rec = get_disbursement_or_404(did)
    if rec["status"] != "APPROVED":
        raise err("ERR_DISBURSEMENT_INVALID_STATE",
                  f"Disbursement in {rec['status']}; release requires APPROVED")
    if user_id == rec["approved_by_user_id"]:
        raise err("ERR_SOD_RELEASER_EQUALS_APPROVER",
                  "Releaser must differ from the approver")
    case = cases[rec["case_id"]]
    if not case["keys_returned"]:
        raise err("ERR_KEYS_NOT_RETURNED",
                  "Case keys_returned must be true before release")
    rec["status"] = "RELEASED"
    rec["released_by_user_id"] = user_id
    rec["released_at"] = iso_ts(now_dt())
    touch(rec)
    case["total_disbursed_cents"] += rec["amount_cents"]
    recompute_remaining(case)
    touch(case)
    if case["remaining_assistance_cents"] == 0 and case["keys_returned"]:
        if case["program_type"] == "DEED_IN_LIEU":
            case["status"] = "RECORDING_PENDING"
            touch(case)
        else:
            # CASH_FOR_KEYS completion fork
            complete_case(case)
            loan = loans[case["loan_id"]]
            loan["status"] = "DEED_IN_LIEU_COMPLETED"
            loan["servicing_system_synced"] = True
            touch(loan)
    return success(rec, 200)


@app.post("/property-solutions/disbursements/<did>/void")
def void_disbursement(did):
    require_roles(SPECIALIST)
    rec = get_disbursement_or_404(did)
    if rec["status"] not in ("PENDING", "APPROVED"):
        raise err("ERR_DISBURSEMENT_INVALID_STATE",
                  f"Disbursement in {rec['status']}; void requires PENDING or APPROVED")
    rec["status"] = "VOIDED"
    touch(rec)
    return success(rec, 200)


@app.post("/property-solutions/disbursements/<did>/clawback")
def clawback_disbursement(did):
    require_roles(MANAGER)
    rec = get_disbursement_or_404(did)
    if rec["status"] != "RELEASED":
        raise err("ERR_DISBURSEMENT_INVALID_STATE",
                  f"Disbursement in {rec['status']}; clawback requires RELEASED")
    rec["status"] = "CLAWED_BACK"
    touch(rec)
    case = cases[rec["case_id"]]
    case["total_disbursed_cents"] -= rec["amount_cents"]
    recompute_remaining(case)
    touch(case)
    return success(rec, 200)


# ===========================================================================
# Deficiency waivers
# ===========================================================================

@app.get("/property-solutions/deficiency-waivers/<wid>")
def get_waiver(wid):
    user_id, role = require_roles(*(STAFF_READ + (BORROWER,)))
    rec = get_waiver_or_404(wid)
    if role == BORROWER:
        case = cases.get(rec["case_id"])
        if case is None or case["borrower_id"] != user_id:
            raise err("ERR_FORBIDDEN", "Borrower may read only their own case's waivers")
    return success(rec, 200)


@app.post("/property-solutions/deficiency-waivers/<wid>/document")
def document_waiver(wid):
    require_roles(LEGAL)
    rec = get_waiver_or_404(wid)
    data = body_json()
    doc_ref = req_str(data, "document_reference")
    if rec["status"] != "DRAFT":
        raise err("ERR_WAIVER_INVALID_STATE",
                  f"Waiver in {rec['status']}; document requires DRAFT")
    rec["status"] = "DOCUMENTED"
    rec["document_reference"] = doc_ref
    touch(rec)
    return success(rec, 200)


@app.post("/property-solutions/deficiency-waivers/<wid>/rescind")
def rescind_waiver(wid):
    require_roles(MANAGER)
    rec = get_waiver_or_404(wid)
    if rec["status"] != "EXECUTED":
        raise err("ERR_WAIVER_INVALID_STATE",
                  f"Waiver in {rec['status']}; rescind requires EXECUTED")
    rec["status"] = "RESCINDED"
    rec["waived_amount_cents"] = 0
    touch(rec)
    loan = loans[rec["loan_id"]]
    loan["deficiency_balance_cents"] = rec["pre_waiver_deficiency_cents"]
    touch(loan)
    return success(rec, 200)


@app.get("/property-solutions/loans/<lid>/deficiency-waivers")
def loan_waivers(lid):
    require_roles(*STAFF_READ)
    get_loan_or_404(lid)
    from flask import request
    items = sorted((w for w in waivers.values() if w["loan_id"] == lid),
                   key=lambda r: r["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, 200, pg)


# ===========================================================================
# Deed recordings
# ===========================================================================

@app.post("/property-solutions/cases/<cid>/deed-recordings")
def create_recording(cid):
    require_roles(LEGAL)
    case = get_case_or_404(cid)
    data = body_json()
    county = req_str(data, "county")
    if case["program_type"] != "DEED_IN_LIEU":
        raise err("ERR_INVALID_REQUEST", "Deed recordings apply to DEED_IN_LIEU cases only")
    if case["status"] != "RECORDING_PENDING":
        raise err("ERR_CASE_INVALID_STATE",
                  f"Case in {case['status']}; recording creation requires RECORDING_PENDING")
    rec = {
        "id": new_id(),
        "case_id": cid,
        "county": county,
        "instrument_number": None,
        "status": "PENDING",
        "recorded_at": None,
        "rejection_reason": None,
    }
    stamp_new(rec)
    recordings[rec["id"]] = rec
    return success(rec, 201)


@app.get("/property-solutions/deed-recordings/<rid>")
def get_recording(rid):
    require_roles(*STAFF_READ)
    return success(get_recording_or_404(rid), 200)


@app.post("/property-solutions/deed-recordings/<rid>/submit")
def submit_recording(rid):
    require_roles(LEGAL)
    rec = get_recording_or_404(rid)
    if rec["status"] != "PENDING":
        raise err("ERR_RECORDING_INVALID_STATE",
                  f"Recording in {rec['status']}; submit requires PENDING")
    rec["status"] = "SUBMITTED"
    touch(rec)
    return success(rec, 200)


@app.post("/property-solutions/deed-recordings/<rid>/confirm")
def confirm_recording(rid):
    require_roles(LEGAL)
    rec = get_recording_or_404(rid)
    data = body_json()
    instrument = req_str(data, "instrument_number")
    if rec["status"] != "SUBMITTED":
        raise err("ERR_RECORDING_INVALID_STATE",
                  f"Recording in {rec['status']}; confirm requires SUBMITTED")
    case = cases[rec["case_id"]]
    waiver = case_waiver(case["id"])
    if waiver is None or waiver["status"] != "DOCUMENTED":
        raise err("ERR_WAIVER_NOT_DOCUMENTED",
                  "The case's DeficiencyWaiver must be DOCUMENTED before confirm")
    handover_d = db.parse_date(case["handover_date"])
    if today() > handover_d + timedelta(days=RECORDING_DEADLINE_DAYS):
        raise err("ERR_RECORDING_DEADLINE_PASSED",
                  f"Recording confirm is later than handover_date + {RECORDING_DEADLINE_DAYS} days")
    rec["status"] = "RECORDED"
    rec["instrument_number"] = instrument
    rec["recorded_at"] = iso_ts(now_dt())
    touch(rec)
    # Hop 1: case RECORDING_PENDING -> COMPLETED (completion cascade)
    complete_case(case)
    # Hop 2/3: waiver execution + loan completion
    execute_waiver_and_complete_loan(case, now_dt())
    return success(rec, 200)


@app.post("/property-solutions/deed-recordings/<rid>/reject")
def reject_recording(rid):
    require_roles(LEGAL)
    rec = get_recording_or_404(rid)
    data = body_json()
    reason = req_str(data, "rejection_reason")
    if rec["status"] != "SUBMITTED":
        raise err("ERR_RECORDING_INVALID_STATE",
                  f"Recording in {rec['status']}; reject requires SUBMITTED")
    rec["status"] = "REJECTED"
    rec["rejection_reason"] = reason
    touch(rec)
    return success(rec, 200)


# ===========================================================================
# Eviction cases
# ===========================================================================

@app.get("/property-solutions/eviction-cases/<eid>")
def get_eviction(eid):
    require_roles(*STAFF_READ)
    return success(get_eviction_or_404(eid), 200)


@app.post("/property-solutions/eviction-cases/<eid>/file")
def file_eviction(eid):
    require_roles(LEGAL)
    rec = get_eviction_or_404(eid)
    data = body_json()
    court_ref = req_str(data, "court_reference")
    if rec["status"] != "ESCALATED":
        raise err("ERR_EVICTION_INVALID_STATE",
                  f"Eviction case in {rec['status']}; file requires ESCALATED")
    rec["status"] = "FILED"
    rec["court_reference"] = court_ref
    rec["filed_at"] = iso_ts(now_dt())
    touch(rec)
    case = cases[rec["case_id"]]
    if case["status"] == "HOLDOVER_ESCALATED":
        eviction_file_cascade(case)
    return success(rec, 200)


@app.post("/property-solutions/eviction-cases/<eid>/writ")
def writ_eviction(eid):
    require_roles(LEGAL)
    rec = get_eviction_or_404(eid)
    if rec["status"] != "FILED":
        raise err("ERR_EVICTION_INVALID_STATE",
                  f"Eviction case in {rec['status']}; writ requires FILED")
    rec["status"] = "WRIT_ISSUED"
    touch(rec)
    return success(rec, 200)


@app.post("/property-solutions/eviction-cases/<eid>/evicted")
def evicted_eviction(eid):
    require_roles(LEGAL)
    rec = get_eviction_or_404(eid)
    if rec["status"] != "WRIT_ISSUED":
        raise err("ERR_EVICTION_INVALID_STATE",
                  f"Eviction case in {rec['status']}; evicted requires WRIT_ISSUED")
    rec["status"] = "EVICTED"
    touch(rec)
    case = cases[rec["case_id"]]
    if case["status"] == "EVICTION_IN_PROGRESS":
        case["status"] = "CLOSED_EVICTED"
        touch(case)
    return success(rec, 200)


@app.post("/property-solutions/eviction-cases/<eid>/dismiss")
def dismiss_eviction(eid):
    require_roles(LEGAL)
    rec = get_eviction_or_404(eid)
    data = body_json()
    reason = req_enum(data, "dismissal_reason", ENUM_DISMISSAL_REASON)
    if rec["status"] not in ("ESCALATED", "FILED"):
        raise err("ERR_EVICTION_INVALID_STATE",
                  f"Eviction case in {rec['status']}; dismiss requires ESCALATED or FILED")
    prev_status = rec["status"]
    rec["status"] = "DISMISSED"
    rec["dismissal_reason"] = reason
    touch(rec)
    case = cases[rec["case_id"]]
    if reason == "OCCUPANT_VACATED":
        if prev_status == "ESCALATED" and case["status"] == "HOLDOVER_ESCALATED":
            case["status"] = "VACATE_PENDING"
            touch(case)
        elif prev_status == "FILED" and case["status"] == "EVICTION_IN_PROGRESS":
            case["status"] = "TERMS_NEGOTIATION"
            recompute_remaining(case)
            touch(case)
            if case["program_type"] == "DEED_IN_LIEU":
                loan = loans[case["loan_id"]]
                if loan["status"] == "FORECLOSURE_PROCEEDING":
                    loan["status"] = "WORKOUT_IN_PROGRESS"
                    touch(loan)
    return success(rec, 200)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
