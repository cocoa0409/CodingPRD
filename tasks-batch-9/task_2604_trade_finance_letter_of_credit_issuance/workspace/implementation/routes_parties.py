"""Applicants, facilities, collateral, banks and beneficiaries (PRD 3.1)."""

from flask import Blueprint

import calc
import ledger
import validate as v
from db import db, new_row, public, by_created, touch
from errors import bail
from middleware import (
    APPLICANT_USER,
    BENEFICIARY_USER,
    COMPLIANCE_OFFICER,
    CORRESPONDENT_BANK,
    CREDIT_OFFICER,
    DOCUMENT_EXAMINER,
    TRADE_FINANCE_OFFICER,
    must_find,
    pending,
    raise_pending,
    require,
    require_same_id,
)
from response import created, ok, paginated

bp = Blueprint("parties", __name__)

INTERNAL_RISK_GRADES = ("AAA", "AA", "A", "BBB", "BB", "B", "CCC")
KYC_STATUSES = ("PENDING", "CLEARED", "REJECTED")
CREDIT_RATINGS = ("AA", "A", "BBB", "BB")
BANK_STATUSES = ("ACTIVE", "SUSPENDED")
FACILITY_ACTIONS = ("SUSPEND", "REINSTATE", "CLOSE")


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------

@bp.get("/applicants/<applicant_id>")
def get_applicant(applicant_id):
    principal = require(CREDIT_OFFICER, TRADE_FINANCE_OFFICER, COMPLIANCE_OFFICER,
                        DOCUMENT_EXAMINER, APPLICANT_USER)
    applicant, deferred = pending("applicants", applicant_id)
    if applicant is not None and principal.is_applicant:
        require_same_id(principal, applicant["id"])
    raise_pending(deferred)
    return ok(public(applicant))


@bp.get("/applicants/<applicant_id>/facilities")
def list_applicant_facilities(applicant_id):
    principal = require(CREDIT_OFFICER, TRADE_FINANCE_OFFICER, COMPLIANCE_OFFICER, APPLICANT_USER)
    applicant, deferred = pending("applicants", applicant_id)
    if applicant is not None and principal.is_applicant:
        require_same_id(principal, applicant["id"])
    raise_pending(deferred)
    rows = by_created([f for f in db.facilities.values() if f["applicant_id"] == applicant_id])
    rows = v.filtered(rows, status=v.arg("status"))
    return paginated(rows, public)


@bp.get("/facilities/<facility_id>")
def get_facility(facility_id):
    principal = require(CREDIT_OFFICER, TRADE_FINANCE_OFFICER, COMPLIANCE_OFFICER, APPLICANT_USER)
    facility, deferred = pending("facilities", facility_id)
    if facility is not None and principal.is_applicant:
        require_same_id(principal, facility["applicant_id"])
    raise_pending(deferred)
    return ok(public(facility))


@bp.get("/facilities/<facility_id>/allocations")
def list_facility_allocations(facility_id):
    require(CREDIT_OFFICER, TRADE_FINANCE_OFFICER, COMPLIANCE_OFFICER)
    must_find("facilities", facility_id)
    rows = ledger.facility_allocations(facility_id)
    rows = v.filtered(rows, status=v.arg("status"), credit_id=v.arg("credit_id"))
    return paginated(rows, public)


@bp.get("/banks/<bank_id>")
def get_bank(bank_id):
    require(CREDIT_OFFICER, TRADE_FINANCE_OFFICER, COMPLIANCE_OFFICER,
            DOCUMENT_EXAMINER, CORRESPONDENT_BANK)
    return ok(public(must_find("banks", bank_id)))


@bp.get("/banks")
def list_banks():
    require(CREDIT_OFFICER, TRADE_FINANCE_OFFICER, COMPLIANCE_OFFICER)
    max_risk = v.arg_int("max_country_risk_score")
    rows = list(db.banks.values())
    rows = v.filtered(rows, country_code=v.arg("country_code"), status=v.arg("status"),
                      credit_rating=v.arg("credit_rating"))
    if max_risk is not None:
        rows = [b for b in rows if int(b.get("country_risk_score") or 0) <= max_risk]
    # eligibility_score DESC, country_risk_score ASC, created_at ASC
    rows.sort(key=lambda b: (-int(b.get("eligibility_score") or 0),
                             int(b.get("country_risk_score") or 0),
                             b["_seq"]))
    return paginated(rows, public)


@bp.get("/beneficiaries/<beneficiary_id>")
def get_beneficiary(beneficiary_id):
    principal = require(TRADE_FINANCE_OFFICER, CREDIT_OFFICER, COMPLIANCE_OFFICER,
                        DOCUMENT_EXAMINER, BENEFICIARY_USER)
    beneficiary, deferred = pending("beneficiaries", beneficiary_id)
    if beneficiary is not None and principal.is_beneficiary:
        require_same_id(principal, beneficiary["id"])
    raise_pending(deferred)
    return ok(public(beneficiary))


@bp.get("/beneficiaries")
def list_beneficiaries():
    require(TRADE_FINANCE_OFFICER, CREDIT_OFFICER, COMPLIANCE_OFFICER)
    rows = by_created(list(db.beneficiaries.values()))
    rows = v.filtered(rows, nominated_bank_id=v.arg("nominated_bank_id"),
                      country_code=v.arg("country_code"), status=v.arg("status"))
    return paginated(rows, public)


# --------------------------------------------------------------------------
# writes: applicants and facilities
# --------------------------------------------------------------------------

@bp.post("/applicants")
def create_applicant():
    principal = require(CREDIT_OFFICER)
    data = v.body()
    legal_name = v.req_str(data, "legal_name", 1, 200)
    country_code = v.req_country(data, "country_code")
    industry_code = v.req_digits(data, "industry_code", 4)
    internal_risk_grade = v.req_enum(data, "internal_risk_grade", INTERNAL_RISK_GRADES)
    kyc_status = v.req_enum(data, "kyc_status", KYC_STATUSES)
    sanctions_flag = v.opt_bool(data, "sanctions_flag", False)

    for row in db.applicants.values():
        if row["legal_name"] == legal_name and row["country_code"] == country_code:
            bail("ERR_DUPLICATE_KEY")

    row = new_row(
        legal_name=legal_name,
        country_code=country_code,
        industry_code=industry_code,
        internal_risk_grade=internal_risk_grade,
        kyc_status=kyc_status,
        sanctions_flag=sanctions_flag,
        status="ACTIVE",
        onboarded_by_user_id=principal.user_id,
    )
    db.applicants[row["id"]] = row
    return created(public(row))


@bp.post("/applicants/<applicant_id>/facilities")
def create_facility(applicant_id):
    require(CREDIT_OFFICER)
    data = v.body()
    currency = v.req_currency(data, "currency")
    limit_cents = v.req_int(data, "limit_cents", minimum=100000)
    collateral_required_pct = v.req_int(data, "collateral_required_pct", minimum=0, maximum=100)
    facility_expiry_date = v.req_date(data, "facility_expiry_date")
    must_find("applicants", applicant_id)

    threshold = calc.fdiv(limit_cents * calc.FACILITY_RESTRICT_PCT, 100)
    row = new_row(
        applicant_id=applicant_id,
        currency=currency,
        limit_cents=limit_cents,
        collateral_required_pct=collateral_required_pct,
        collateral_posted_cents=0,
        allocated_cents=0,
        available_cents=limit_cents,
        restrict_threshold_cents=threshold,
        utilisation_posture="OPEN",
        status="ACTIVE",
        facility_expiry_date=facility_expiry_date,
        suspended_reason=None,
    )
    db.facilities[row["id"]] = row
    return created(public(row))


@bp.post("/facilities/<facility_id>/collateral-postings")
def post_collateral(facility_id):
    require(CREDIT_OFFICER)
    data = v.body()
    amount_cents = v.req_int(data, "amount_cents")
    expected_version = v.req_int(data, "expected_facility_version", minimum=1)
    v.opt_str(data, "posting_note", 0, 500)
    facility = must_find("facilities", facility_id)

    if int(facility["version"]) != expected_version:
        bail("ERR_STALE_FACILITY_VERSION")

    new_posted = int(facility["collateral_posted_cents"]) + amount_cents
    if new_posted < 0:
        bail("ERR_COLLATERAL_RELEASE_EXCEEDS_POSTED")
    if new_posted < ledger.collateral_credited_to_open_allocations(facility_id):
        bail("ERR_COLLATERAL_RELEASE_BLOCKED")

    facility["collateral_posted_cents"] = new_posted
    touch(facility)
    return ok(public(facility))


@bp.post("/facilities/<facility_id>/status-changes")
def change_facility_status(facility_id):
    require(CREDIT_OFFICER)
    data = v.body()
    action = v.req_enum(data, "action", FACILITY_ACTIONS)
    reason = v.opt_str(data, "reason", 0, 500)
    facility = must_find("facilities", facility_id)

    if action == "SUSPEND":
        if facility["status"] != "ACTIVE":
            bail("ERR_FACILITY_NOT_ACTIVE")
        facility["status"] = "SUSPENDED"
        facility["suspended_reason"] = "MANUAL_SUSPENSION"
        ledger._set_posture(facility)
        touch(facility)
        ledger.hold_approved_siblings(facility_id)
    elif action == "REINSTATE":
        if facility["status"] != "SUSPENDED":
            bail("ERR_FACILITY_NOT_ACTIVE")
        if int(facility["allocated_cents"]) >= int(facility["restrict_threshold_cents"]):
            bail("ERR_FACILITY_STILL_RESTRICTED")
        facility["status"] = "ACTIVE"
        facility["suspended_reason"] = None
        ledger._set_posture(facility)
        touch(facility)
        ledger.release_held_siblings(facility_id)
    else:  # CLOSE
        if facility["status"] not in ("ACTIVE", "SUSPENDED"):
            bail("ERR_FACILITY_NOT_ACTIVE")
        for row in ledger.facility_allocations(facility_id):
            if row["status"] == "OPEN":
                bail("ERR_FACILITY_HAS_OPEN_ALLOCATION")
        facility["status"] = "CLOSED"
        facility["suspended_reason"] = None
        facility["utilisation_posture"] = "FROZEN"
        touch(facility)

    del reason  # narrative only: the facility carries no free-text reason field
    return ok(public(facility))


# --------------------------------------------------------------------------
# writes: banks and beneficiaries
# --------------------------------------------------------------------------

def _valid_bic(value):
    if len(value) not in (8, 11):
        return False
    return value.isalnum() and value == value.upper()


@bp.post("/banks")
def create_bank():
    require(CREDIT_OFFICER)
    data = v.body()
    bank_name = v.req_str(data, "bank_name", 1, 200)
    swift_bic = v.req_str(data, "swift_bic", 8, 11)
    if not _valid_bic(swift_bic):
        v.bad("swift_bic must be 8 or 11 uppercase alphanumeric characters")
    country_code = v.req_country(data, "country_code")
    country_risk_score = v.req_int(data, "country_risk_score", minimum=0, maximum=100)
    credit_rating = v.req_enum(data, "credit_rating", CREDIT_RATINGS)
    appetite = v.req_int(data, "confirmation_appetite_cents", minimum=0)
    sanctions_flag = v.opt_bool(data, "sanctions_flag", False)

    for row in db.banks.values():
        if row["swift_bic"] == swift_bic:
            bail("ERR_DUPLICATE_KEY")

    row = new_row(
        bank_name=bank_name,
        swift_bic=swift_bic,
        country_code=country_code,
        country_risk_score=country_risk_score,
        credit_rating=credit_rating,
        confirmation_appetite_cents=appetite,
        confirming_line_used_cents=0,
        eligibility_score=0,
        sanctions_flag=sanctions_flag,
        status="ACTIVE",
    )
    row["eligibility_score"] = calc.eligibility_score(row)
    db.banks[row["id"]] = row
    return created(public(row))


@bp.patch("/banks/<bank_id>")
def patch_bank(bank_id):
    require(CREDIT_OFFICER, COMPLIANCE_OFFICER)
    data = v.body()
    status = v.opt_enum(data, "status", BANK_STATUSES)
    sanctions_flag = data.get("sanctions_flag")
    if sanctions_flag is not None:
        sanctions_flag = v.req_bool(data, "sanctions_flag")
    country_risk_score = v.opt_int(data, "country_risk_score", minimum=0, maximum=100)
    appetite = v.opt_int(data, "confirmation_appetite_cents", minimum=0)
    credit_rating = v.opt_enum(data, "credit_rating", CREDIT_RATINGS)
    bank = must_find("banks", bank_id)

    if status is not None:
        bank["status"] = status
    if sanctions_flag is not None:
        bank["sanctions_flag"] = sanctions_flag
    if country_risk_score is not None:
        bank["country_risk_score"] = country_risk_score
    if appetite is not None:
        bank["confirmation_appetite_cents"] = appetite
    if credit_rating is not None:
        bank["credit_rating"] = credit_rating
    bank["eligibility_score"] = calc.eligibility_score(bank)
    touch(bank)
    return ok(public(bank))


@bp.post("/beneficiaries")
def create_beneficiary():
    require(TRADE_FINANCE_OFFICER)
    data = v.body()
    beneficiary_name = v.req_str(data, "beneficiary_name", 1, 200)
    country_code = v.req_country(data, "country_code")
    nominated_bank_id = v.req_id(data, "nominated_bank_id")
    sanctions_flag = v.opt_bool(data, "sanctions_flag", False)
    must_find("banks", nominated_bank_id)

    row = new_row(
        beneficiary_name=beneficiary_name,
        country_code=country_code,
        nominated_bank_id=nominated_bank_id,
        sanctions_flag=sanctions_flag,
        status="ACTIVE",
    )
    db.beneficiaries[row["id"]] = row
    return created(public(row))
