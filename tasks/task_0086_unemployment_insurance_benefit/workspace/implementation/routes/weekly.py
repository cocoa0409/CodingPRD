"""WeeklyCertification, WorkSearchContact, EmployerCharge endpoints."""
from datetime import date, timedelta

from flask import Blueprint

import db
from errors import err
from middleware import authenticate, require_role
from response import object_response, array_response
from validate import (
    as_enum, as_int, as_string, check_occ, get_json_body, paginate, serialize,
    validate_iso_date, validate_saturday,
)
from services import calculations as calc
from services import claim_logic

bp = Blueprint("weekly", __name__)

MIN_WORK_SEARCH_CONTACTS = 3

# adjudication_status
PENDING = "PENDING"
ELIGIBLE = "ELIGIBLE"
INELIGIBLE = "INELIGIBLE"
HELD = "HELD"
# payment_status
UNPAID = "UNPAID"
PAID = "PAID"
OFFSET = "OFFSET"
DENIED = "DENIED"

MONETARILY_ELIGIBLE = "MONETARILY_ELIGIBLE"
EXHAUSTED = "EXHAUSTED"

CONTACT_TYPES = {"EMPLOYER_APPLICATION", "INTERVIEW", "JOB_FAIR", "REEMPLOYMENT_WORKSHOP"}


def _week_window(week_ending_date_str):
    """Return (sunday, saturday) date objects for the certification week."""
    saturday = date.fromisoformat(week_ending_date_str)
    sunday = saturday - timedelta(days=6)
    return sunday, saturday


def _compute_work_search_required(claim, work_search_waived):
    """True unless exempt: claim carries active extension that waives work
    search, OR work_search_waived override on the week (PRD §3.5)."""
    if work_search_waived:
        return False
    ext_id = claim.get("emergency_extension_id")
    if ext_id:
        prog = db.extension_programs.get(ext_id)
        if prog and prog.get("is_active") and prog.get("waives_work_search"):
            return False
    return True


# ===========================================================================
# WeeklyCertification
# ===========================================================================
@bp.route("/ui/weekly-certifications", methods=["POST"])
def create_weekly_certification():
    p = authenticate()
    require_role(p, {"Claimant", "ProgramAdmin"})
    body = get_json_body()
    claim_id = as_string(body, "claim_id")
    if claim_id not in db.claims:
        raise err("ERR_NOT_FOUND", "claim_id not found.")
    claim = db.claims[claim_id]
    week_ending = body.get("week_ending_date")
    validate_saturday(week_ending)
    reported = as_int(body, "reported_earnings_cents", required=False, default=0, minimum=0)
    work_search_waived = body.get("work_search_waived", False)
    if not isinstance(work_search_waived, bool):
        raise err("ERR_INVALID_REQUEST", "work_search_waived must be a boolean.")

    # Uniqueness (priority 6): (claim_id, week_ending_date)
    for wc in db.weekly_certifications.values():
        if wc["claim_id"] == claim_id and wc["week_ending_date"] == week_ending:
            raise err("ERR_DUPLICATE_RESOURCE",
                      "Certification for this claim and week already exists.")

    rec = {
        "claim_id": claim_id,
        "week_ending_date": week_ending,
        "reported_earnings_cents": reported,
        "adjudication_status": PENDING,
        "payment_status": UNPAID,
        "work_search_required": _compute_work_search_required(claim, work_search_waived),
        "payable_amount_cents": 0,
        "work_search_waived": work_search_waived,
    }
    db.stamp_create(rec)
    db.weekly_certifications[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/ui/weekly-certifications/<wcid>", methods=["GET"])
def get_weekly_certification(wcid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Claimant", "BenefitPaymentOfficer"})
    rec = db.weekly_certifications.get(wcid)
    if not rec:
        raise err("ERR_NOT_FOUND", "WeeklyCertification not found.")
    return object_response(serialize(rec))


@bp.route("/ui/claims/<cid>/weekly-certifications", methods=["GET"])
def list_claim_weekly_certifications(cid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Claimant", "BenefitPaymentOfficer"})
    if cid not in db.claims:
        raise err("ERR_NOT_FOUND", "Claim not found.")
    items = [wc for wc in db.weekly_certifications.values() if wc["claim_id"] == cid]
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total)


# ===========================================================================
# WorkSearchContact
# ===========================================================================
@bp.route("/ui/weekly-certifications/<wcid>/work-search-contacts", methods=["POST"])
def create_work_search_contact(wcid):
    p = authenticate()
    require_role(p, {"Claimant", "ProgramAdmin"})
    wc = db.weekly_certifications.get(wcid)
    if not wc:
        raise err("ERR_NOT_FOUND", "WeeklyCertification not found.")
    body = get_json_body()
    contact_type = as_enum(body, "contact_type", CONTACT_TYPES)
    contact_date_str = as_string(body, "contact_date")
    contact_date = validate_iso_date(contact_date_str, "contact_date")
    employer_id = body.get("employer_id")
    if employer_id is not None:
        # reference type check (422)
        if employer_id not in db.employers:
            raise err("ERR_INVALID_REFERENCE", "employer_id is not a real Employer.")

    # Temporal (priority 8): contact_date within [Sunday, week_ending_date]
    sunday, saturday = _week_window(wc["week_ending_date"])
    if not (sunday <= contact_date <= saturday):
        raise err("ERR_UNTIMELY", "contact_date is outside the certification week.")

    rec = {
        "weekly_certification_id": wcid,
        "employer_id": employer_id,
        "contact_type": contact_type,
        "contact_date": contact_date_str,
    }
    db.stamp_create(rec, with_version=False)
    db.work_search_contacts[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/ui/weekly-certifications/<wcid>/work-search-contacts", methods=["GET"])
def list_work_search_contacts(wcid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Claimant"})
    if wcid not in db.weekly_certifications:
        raise err("ERR_NOT_FOUND", "WeeklyCertification not found.")
    items = [c for c in db.work_search_contacts.values()
             if c["weekly_certification_id"] == wcid]
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total)


# ===========================================================================
# Adjudicate / Hold / Pay
# ===========================================================================
def _count_contacts(wcid):
    return sum(1 for c in db.work_search_contacts.values()
               if c["weekly_certification_id"] == wcid)


@bp.route("/ui/weekly-certifications/<wcid>/adjudicate", methods=["POST"])
def adjudicate(wcid):
    p = authenticate()
    require_role(p, {"Adjudicator"})
    wc = db.weekly_certifications.get(wcid)
    if not wc:
        raise err("ERR_NOT_FOUND", "WeeklyCertification not found.")
    body = get_json_body()
    decision = as_enum(body, "decision", {"ELIGIBLE", "INELIGIBLE"})

    # state check (priority 7): adjudicate defined from PENDING or HELD
    if wc["adjudication_status"] not in (PENDING, HELD):
        raise err("ERR_INVALID_STATE", "Week is not PENDING or HELD.")

    claim = db.claims[wc["claim_id"]]

    if decision == "ELIGIBLE":
        # Conditions evaluated in order (PRD §3.5 'Adjudicating a week'):
        # 1. parent claim MONETARILY_ELIGIBLE
        if claim["status"] != MONETARILY_ELIGIBLE:
            raise err("ERR_INVALID_STATE",
                      "Parent claim is not MONETARILY_ELIGIBLE.")
        # 2. claimant is_able_and_available == true
        claimant = db.claimants[claim["claimant_id"]]
        if not claimant.get("is_able_and_available"):
            raise err("ERR_NOT_ABLE_AVAILABLE",
                      "Claimant does not attest able-and-available.")
        # 3. work search minimum when required
        if wc["work_search_required"]:
            if _count_contacts(wcid) < MIN_WORK_SEARCH_CONTACTS:
                raise err("ERR_WORK_SEARCH_INSUFFICIENT",
                          "Insufficient work-search contacts for the week.")
        check_occ(body, "expected_weekly_certification_version", wc, "ERR_STALE_VERSION")
        wc["adjudication_status"] = ELIGIBLE
    else:
        # INELIGIBLE from PENDING or HELD
        check_occ(body, "expected_weekly_certification_version", wc, "ERR_STALE_VERSION")
        wc["adjudication_status"] = INELIGIBLE
        wc["payment_status"] = DENIED
    db.touch(wc)
    return object_response(serialize(wc))


@bp.route("/ui/weekly-certifications/<wcid>/hold", methods=["POST"])
def hold(wcid):
    p = authenticate()
    require_role(p, {"Adjudicator"})
    wc = db.weekly_certifications.get(wcid)
    if not wc:
        raise err("ERR_NOT_FOUND", "WeeklyCertification not found.")
    body = get_json_body()
    if wc["adjudication_status"] != PENDING:
        raise err("ERR_INVALID_STATE", "Week is not PENDING.")
    check_occ(body, "expected_weekly_certification_version", wc, "ERR_STALE_VERSION")
    wc["adjudication_status"] = HELD
    db.touch(wc)
    return object_response(serialize(wc))


@bp.route("/ui/weekly-certifications/<wcid>/pay", methods=["POST"])
def pay(wcid):
    p = authenticate()
    require_role(p, {"BenefitPaymentOfficer"})
    wc = db.weekly_certifications.get(wcid)
    if not wc:
        raise err("ERR_NOT_FOUND", "WeeklyCertification not found.")
    body = get_json_body()
    # state check (priority 7): pay defined from payment_status UNPAID
    if wc["payment_status"] != UNPAID:
        raise err("ERR_INVALID_STATE", "Week is not UNPAID.")
    if wc["adjudication_status"] != ELIGIBLE:
        raise err("ERR_INVALID_STATE", "Week is not adjudicated ELIGIBLE.")
    claim = db.claims[wc["claim_id"]]
    if claim["status"] != MONETARILY_ELIGIBLE:
        raise err("ERR_INVALID_STATE", "Parent claim is not MONETARILY_ELIGIBLE.")
    # business fiscal (priority 14): balance not already exhausted (==0)
    if claim["remaining_balance_cents"] == 0:
        raise err("ERR_BALANCE_EXHAUSTED", "Claim balance is already exhausted.")
    # OCC (optional)
    check_occ(body, "expected_weekly_certification_version", wc, "ERR_STALE_VERSION")

    # Compute payable (capped by remaining balance)
    payable = calc.weekly_payable_amount(
        claim["weekly_benefit_amount_cents"],
        wc["reported_earnings_cents"],
        claim["remaining_balance_cents"],
    )
    wc["payable_amount_cents"] = payable
    wc["payment_status"] = PAID

    # Debit claim balance
    claim["remaining_balance_cents"] -= payable

    # Allocate employer charges (cascade hop 2)
    _allocate_charges(claim, wc, payable)

    # Claim mutated by the debit
    db.touch(claim)
    # Exhaustion at exactly 0
    if claim["remaining_balance_cents"] == 0:
        claim["status"] = EXHAUSTED
        db.touch(claim)

    db.touch(wc)
    return object_response(serialize(wc))


def _allocate_charges(claim, wc, payable):
    """Create one EmployerCharge per base-period employer (POSTED), debiting
    each employer's reserve. Uses largest-remainder allocation."""
    if payable <= 0:
        return
    pairs = claim_logic.selected_base_period_employers(claim)
    if not pairs:
        return
    charges = calc.employer_charge_allocation(payable, pairs)
    # Deterministic creation order: by the same employer ordering used for the
    # allocation (created_at ASC, then seq) so created_at on charges is stable.
    ordered_emp_ids = sorted(
        charges.keys(),
        key=lambda eid: next((ca, sq) for (e, w, ca, sq) in pairs if e == eid),
    )
    for emp_id in ordered_emp_ids:
        amount = charges[emp_id]
        rec = {
            "employer_id": emp_id,
            "weekly_certification_id": wc["id"],
            "charge_amount_cents": amount,
            "status": "POSTED",
            "relief_reason": None,
        }
        db.stamp_create(rec)
        db.employer_charges[rec["id"]] = rec
        # Debit employer reserve
        emp = db.employers[emp_id]
        emp["reserve_account_balance_cents"] -= amount
        db.touch(emp)


# ===========================================================================
# EmployerCharge get / list / protest / relieve
# ===========================================================================
@bp.route("/ui/employer-charges/<chid>", methods=["GET"])
def get_employer_charge(chid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Employer"})
    rec = db.employer_charges.get(chid)
    if not rec:
        raise err("ERR_NOT_FOUND", "EmployerCharge not found.")
    return object_response(serialize(rec))


@bp.route("/ui/weekly-certifications/<wcid>/employer-charges", methods=["GET"])
def list_week_employer_charges(wcid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Employer"})
    if wcid not in db.weekly_certifications:
        raise err("ERR_NOT_FOUND", "WeeklyCertification not found.")
    items = [c for c in db.employer_charges.values()
             if c["weekly_certification_id"] == wcid]
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/ui/employer-charges/<chid>/protest", methods=["POST"])
def protest_charge(chid):
    p = authenticate()
    require_role(p, {"Employer"})
    rec = db.employer_charges.get(chid)
    if not rec:
        raise err("ERR_NOT_FOUND", "EmployerCharge not found.")
    body = get_json_body()
    # Ownership: acting Employer must own the charge (employer_id == X-User-ID).
    # This is a forbidden-role-style ownership check.
    if rec["employer_id"] != p.user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Employer does not own this charge.")
    if rec["status"] != "POSTED":
        raise err("ERR_INVALID_STATE", "Charge is not POSTED.")
    check_occ(body, "expected_employer_charge_version", rec, "ERR_STALE_VERSION")
    rec["status"] = "PROTESTED"
    emp = db.employers[rec["employer_id"]]
    emp["charge_protest_count"] += 1
    db.touch(emp)
    db.touch(rec)
    return object_response(serialize(rec))


@bp.route("/ui/employer-charges/<chid>/relieve", methods=["POST"])
def relieve_charge(chid):
    p = authenticate()
    require_role(p, {"Adjudicator"})
    rec = db.employer_charges.get(chid)
    if not rec:
        raise err("ERR_NOT_FOUND", "EmployerCharge not found.")
    body = get_json_body()
    relief_reason = as_enum(body, "relief_reason",
                            {"QUIT_WITHOUT_CAUSE", "MISCONDUCT_DISCHARGE", "CONTINUING_WORK"})
    if rec["status"] != "PROTESTED":
        raise err("ERR_INVALID_STATE", "Charge is not PROTESTED.")
    check_occ(body, "expected_employer_charge_version", rec, "ERR_STALE_VERSION")
    rec["status"] = "RELIEVED"
    rec["relief_reason"] = relief_reason
    emp = db.employers[rec["employer_id"]]
    emp["reserve_account_balance_cents"] += rec["charge_amount_cents"]
    emp["charge_protest_count"] -= 1
    db.touch(emp)
    db.touch(rec)
    return object_response(serialize(rec))
