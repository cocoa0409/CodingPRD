"""Shared helpers: lookups, field validation, calculations, cascades."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import (
    loans, borrowers, properties, cases, listings, suspensions,
    title_commitments, liens, agreements, appointments, reports,
    disbursements, waivers, recordings, evictions,
    now_dt, today, iso_ts, touch,
)
from errors import err

# ---------------------------------------------------------------------------
# Constants from the scaffold
# ---------------------------------------------------------------------------

MARKETING_MIN_DAYS = 90
MIN_VACATE_NOTICE_DAYS = 10
INSPECTION_MIN_NOTICE_HOURS = 24
INSPECTION_TRAVEL_BUFFER_MINUTES = 30
HOLDOVER_GRACE_DAYS = 3
HOLDOVER_DAILY_PENALTY_CENTS = 15000
RECORDING_DEADLINE_DAYS = 30
MAX_NEGOTIATION_ROUNDS = 3

TIER_1_MAX_CENTS = 10000000
TIER_1_BASE_CENTS = 300000
TIER_2_MAX_CENTS = 25000000
TIER_2_BASE_CENTS = 500000
TIER_3_MAX_CENTS = 50000000
TIER_3_BASE_CENTS = 750000
TIER_4_BASE_CENTS = 1150000
ASSISTANCE_FLOOR_CENTS = 150000
ASSISTANCE_CAP_CENTS = 1200000

OCC_MULT = {
    "OWNER_OCCUPIED": Decimal("1.0"),
    "TENANT_OCCUPIED": Decimal("0.8"),
    "SECOND_HOME": Decimal("0.5"),
}
HARDSHIP_BONUS = {
    "INVOLUNTARY_UNEMPLOYMENT": 100000,
    "MEDICAL": 50000,
    "DIVORCE": 25000,
    "NONE": 0,
}

ITEM_BASE_CENTS = {
    "CLEANLINESS_FAIL": 14999,
    "DEBRIS_REMOVAL": 24999,
    "APPLIANCE_REMOVED": 39999,
    "FIXTURE_DAMAGE": 59999,
    "STRUCTURAL_DAMAGE": 149999,
}
SEVERITY_MULT = {
    "STANDARD": Decimal("1.0"),
    "MATERIAL": Decimal("1.5"),
}

PENALTY_CAP_PCT = Decimal("0.5")

# Enum domains
ENUM_FORECLOSURE_REFERRAL = {"NONE", "REFERRED", "ACTIVE", "WITHDRAWN"}
ENUM_HARDSHIP = {"INVOLUNTARY_UNEMPLOYMENT", "MEDICAL", "DIVORCE", "NONE"}
ENUM_CONDITION_GRADE = {"A", "B", "C", "D"}
ENUM_OCCUPANCY = {"OWNER_OCCUPIED", "TENANT_OCCUPIED", "SECOND_HOME"}
ENUM_CONDITION_STANDARD = {"BROOM_CLEAN"}
ENUM_PROGRAM_TYPE = {"DEED_IN_LIEU", "CASH_FOR_KEYS"}
ENUM_DECISION = {"PASS", "FAIL"}
ENUM_APPOINTMENT_TYPE = {"HANDOVER", "RE_INSPECTION"}
ENUM_ITEM_CODE = {"CLEANLINESS_FAIL", "DEBRIS_REMOVAL", "APPLIANCE_REMOVED",
                  "FIXTURE_DAMAGE", "STRUCTURAL_DAMAGE"}
ENUM_SEVERITY = {"STANDARD", "MATERIAL"}
ENUM_PURPOSE = {"RELOCATION_ASSISTANCE"}
ENUM_DISMISSAL_REASON = {"OCCUPANT_VACATED", "OTHER"}


# ---------------------------------------------------------------------------
# Entity lookups (404 errors)
# ---------------------------------------------------------------------------

def get_loan_or_404(loan_id):
    rec = loans.get(loan_id)
    if rec is None:
        raise err("ERR_LOAN_NOT_FOUND", f"Loan {loan_id} not found")
    return rec


def get_borrower_or_404(borrower_id):
    rec = borrowers.get(borrower_id)
    if rec is None:
        raise err("ERR_BORROWER_NOT_FOUND", f"Borrower {borrower_id} not found")
    return rec


def get_property_or_404(prop_id):
    rec = properties.get(prop_id)
    if rec is None:
        raise err("ERR_PROPERTY_NOT_FOUND", f"Property {prop_id} not found")
    return rec


def get_case_or_404(case_id):
    rec = cases.get(case_id)
    if rec is None:
        raise err("ERR_CASE_NOT_FOUND", f"Case {case_id} not found")
    return rec


def get_listing_or_404(listing_id):
    rec = listings.get(listing_id)
    if rec is None:
        raise err("ERR_LISTING_NOT_FOUND", f"Listing {listing_id} not found")
    return rec


def get_commitment_or_404(tc_id):
    rec = title_commitments.get(tc_id)
    if rec is None:
        raise err("ERR_TITLE_COMMITMENT_NOT_FOUND",
                  f"Title commitment {tc_id} not found")
    return rec


def get_agreement_or_404(agreement_id):
    rec = agreements.get(agreement_id)
    if rec is None:
        raise err("ERR_AGREEMENT_NOT_FOUND", f"Agreement {agreement_id} not found")
    return rec


def get_appointment_or_404(appt_id):
    rec = appointments.get(appt_id)
    if rec is None:
        raise err("ERR_APPOINTMENT_NOT_FOUND", f"Appointment {appt_id} not found")
    return rec


def get_report_or_404(report_id):
    rec = reports.get(report_id)
    if rec is None:
        raise err("ERR_REPORT_NOT_FOUND", f"Report {report_id} not found")
    return rec


def get_disbursement_or_404(disb_id):
    rec = disbursements.get(disb_id)
    if rec is None:
        raise err("ERR_DISBURSEMENT_NOT_FOUND",
                  f"Disbursement {disb_id} not found")
    return rec


def get_waiver_or_404(waiver_id):
    rec = waivers.get(waiver_id)
    if rec is None:
        raise err("ERR_WAIVER_NOT_FOUND", f"Waiver {waiver_id} not found")
    return rec


def get_recording_or_404(rec_id):
    rec = recordings.get(rec_id)
    if rec is None:
        raise err("ERR_RECORDING_NOT_FOUND", f"Recording {rec_id} not found")
    return rec


def get_eviction_or_404(ev_id):
    rec = evictions.get(ev_id)
    if rec is None:
        raise err("ERR_EVICTION_CASE_NOT_FOUND",
                  f"Eviction case {ev_id} not found")
    return rec


# ---------------------------------------------------------------------------
# Request body validation helpers
# ---------------------------------------------------------------------------

def body_json():
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def req_str(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be a non-empty string")
    return v


def opt_str(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be a string")
    return v


def req_int(data, field):
    v = data.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be an integer")
    return v


def opt_int(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be an integer")
    return v


def req_number(data, field):
    v = data.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be a number")
    return v


def req_bool(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be a boolean")
    return v


def req_enum(data, field, domain):
    v = data.get(field)
    if v is None or not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' is required")
    if v not in domain:
        raise err("ERR_INVALID_ENUM", f"Field '{field}' value '{v}' is not in the declared domain")
    return v


def opt_enum(data, field, domain, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be a string")
    if v not in domain:
        raise err("ERR_INVALID_ENUM", f"Field '{field}' value '{v}' is not in the declared domain")
    return v


def req_iso_date(data, field):
    v = data.get(field)
    if v is None:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' is required")
    d = db.parse_date(v)
    if d is None:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be an ISO date (YYYY-MM-DD)")
    return v, d


def req_iso_datetime(data, field):
    v = data.get(field)
    if v is None:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' is required")
    dt = db.parse_dt(v)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be an ISO 8601 datetime")
    return v, dt


# ---------------------------------------------------------------------------
# Borrower read-ownership helper
# ---------------------------------------------------------------------------

def check_borrower_case_read(user_id, role, case):
    """For endpoints where Borrower role may read only own cases' sub-resources."""
    if role == "Borrower" and case["borrower_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Borrower may access only their own case's resources")


# ---------------------------------------------------------------------------
# Lazy offer expiry
# ---------------------------------------------------------------------------

def lazy_expire_agreement(agreement):
    """OFFERED agreement whose offer_expires_at has passed flips to EXPIRED.

    Silent flip (with version bump) on reads/actions. Returns the agreement.
    """
    if agreement["status"] == "OFFERED" and agreement.get("offer_expires_at"):
        exp = db.parse_dt(agreement["offer_expires_at"])
        if exp is not None and now_dt() > exp:
            agreement["status"] = "EXPIRED"
            touch(agreement)
    return agreement


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def compute_per_diem(upb_cents, note_annual_rate):
    """round_half_up(UPB * rate / 365) in whole cents."""
    prod = Decimal(upb_cents) * Decimal(str(note_annual_rate)) / Decimal(365)
    return int(prod.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def provisional_assistance_quote(loan, prop, borrower):
    """tier -> occupancy multiply -> round_half_up -> hardship add -> floor -> cap."""
    upb = loan["unpaid_principal_balance_cents"]
    if upb < TIER_1_MAX_CENTS:
        base = TIER_1_BASE_CENTS
    elif upb < TIER_2_MAX_CENTS:
        base = TIER_2_BASE_CENTS
    elif upb < TIER_3_MAX_CENTS:
        base = TIER_3_BASE_CENTS
    else:
        base = TIER_4_BASE_CENTS
    mult = OCC_MULT[prop["occupancy_type"]]
    step1 = int((Decimal(base) * mult).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    step2 = step1 + HARDSHIP_BONUS[borrower["hardship_type"]]
    step3 = max(step2, ASSISTANCE_FLOOR_CENTS)
    return min(step3, ASSISTANCE_CAP_CENTS)


def condition_deduction_schedule(line_items):
    """Per-item round_half_up, then sum."""
    total = 0
    for line in line_items:
        base = ITEM_BASE_CENTS[line["item_code"]]
        mult = SEVERITY_MULT[line["severity"]]
        line_cents = int((Decimal(base) * mult).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total += line_cents
    return total


def holdover_penalty_accrual(vacate: date, handover: date):
    """15000 * max(0, (handover - vacate).days - 3)."""
    days_late = max(0, (handover - vacate).days - HOLDOVER_GRACE_DAYS)
    return HOLDOVER_DAILY_PENALTY_CENTS * days_late


def final_assistance_settlement(provisional, total_deduction_cents, vacate, handover):
    penalty_cap = int((Decimal(provisional) * PENALTY_CAP_PCT).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    accrual = holdover_penalty_accrual(vacate, handover)
    holdover_penalty = min(accrual, penalty_cap)
    return max(0, provisional - total_deduction_cents - holdover_penalty)


def deficiency_waiver_amount(loan, accepted_at_date: date, end_date: date):
    """accrual_base + per_diem * days - FMV, floored at 0."""
    accrual_base = (loan["unpaid_principal_balance_cents"]
                    + loan["accrued_interest_cents"]
                    + loan["escrow_advances_cents"]
                    + loan["foreclosure_fees_cents"])
    days = (end_date - accepted_at_date).days
    return max(0, accrual_base + loan["per_diem_interest_cents"] * days
               - loan["fair_market_value_cents"])


# ---------------------------------------------------------------------------
# Creditable marketing days
# ---------------------------------------------------------------------------

def compute_creditable_days(listing, eval_date: date):
    """clamp -> sort -> merge -> subtract; whole days."""
    list_d = db.parse_date(listing["list_date"])
    span_days = max(0, (eval_date - list_d).days)

    intervals = []
    for s in suspensions.values():
        if s["listing_id"] != listing["id"]:
            continue
        start_dt = db.parse_dt(s["started_at"])
        start_d = start_dt.date()
        if s.get("ended_at"):
            end_d = db.parse_dt(s["ended_at"]).date()
        else:
            end_d = eval_date
        # clamp to [list_date, eval_date]
        c_start = max(start_d, list_d)
        c_end = min(end_d, eval_date)
        if c_end < c_start:
            continue
        intervals.append((c_start, c_end, s["created_at"]))

    # sort by started_at, tie-break earlier created_at first
    intervals.sort(key=lambda t: (t[0], t[2]))

    # merge overlapping OR touching (adjacency gap == 0 merges)
    merged = []
    for start_d, end_d, _ in intervals:
        if merged and start_d <= merged[-1][1] + timedelta(days=1):
            if end_d > merged[-1][1]:
                merged[-1] = (merged[-1][0], end_d)
        else:
            merged.append((start_d, end_d))

    suspended_days = sum((e - s).days for s, e in merged)
    return max(0, span_days - suspended_days)


def listing_eval_date(listing):
    """Current logical date for non-CLOSED; closing date for CLOSED (frozen)."""
    if listing["status"] == "CLOSED" and listing.get("closed_at"):
        return db.parse_dt(listing["closed_at"]).date()
    return today()


def refresh_creditable_days(listing):
    eval_d = listing_eval_date(listing)
    listing["creditable_days"] = compute_creditable_days(listing, eval_d)
    return listing


# ---------------------------------------------------------------------------
# Case helpers
# ---------------------------------------------------------------------------

def case_accepted_agreement(case):
    """The case's ACCEPTED or COMPLETED agreement, if any."""
    for a in agreements.values():
        if a["case_id"] == case["id"] and a["status"] in ("ACCEPTED", "COMPLETED"):
            return a
    return None


def applicable_agreement_for_remaining(case):
    """Agreement used for remaining_assistance_cents: the case's most recent
    ACCEPTED/COMPLETED agreement, else the most recently created agreement."""
    cands = [a for a in agreements.values() if a["case_id"] == case["id"]]
    if not cands:
        return None
    active = [a for a in cands if a["status"] in ("ACCEPTED", "COMPLETED")]
    pool = active if active else cands
    pool.sort(key=lambda a: a["created_at"])
    return pool[-1]


def recompute_remaining(case):
    a = applicable_agreement_for_remaining(case)
    if a is None:
        case["remaining_assistance_cents"] = None
        return
    if a["status"] in ("ACCEPTED", "COMPLETED") and a.get("final_assistance_cents") is not None:
        applicable = a["final_assistance_cents"]
    else:
        applicable = a["provisional_assistance_cents"]
    case["remaining_assistance_cents"] = applicable - case["total_disbursed_cents"]


def case_listings(case_id):
    return [l for l in listings.values() if l["case_id"] == case_id]


def case_commitments(case_id):
    return [t for t in title_commitments.values() if t["case_id"] == case_id]


def case_evictions(case_id):
    return [e for e in evictions.values() if e["case_id"] == case_id]


def case_waiver(case_id):
    for w in waivers.values():
        if w["case_id"] == case_id:
            return w
    return None


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def withdraw_cascade(case):
    """Deep teardown cascade for case withdrawal."""
    for a in agreements.values():
        if a["case_id"] == case["id"] and a["status"] in ("DRAFT", "OFFERED", "COUNTERED", "ACCEPTED"):
            a["status"] = "TERMINATED"
            touch(a)
    for l in listings.values():
        if l["case_id"] == case["id"] and l["status"] in ("ACTIVE", "SUSPENDED"):
            _close_listing(l)
    for d in disbursements.values():
        if d["case_id"] == case["id"] and d["status"] in ("PENDING", "APPROVED"):
            d["status"] = "VOIDED"
            touch(d)
    loan = loans.get(case["loan_id"])
    if loan is not None and loan["status"] == "WORKOUT_IN_PROGRESS":
        loan["status"] = "ACTIVE_DELINQUENT"
        touch(loan)
    # If withdrawing from HOLDOVER_ESCALATED, dismiss ESCALATED evictions with OTHER
    for e in evictions.values():
        if e["case_id"] == case["id"] and e["status"] == "ESCALATED":
            e["status"] = "DISMISSED"
            e["dismissal_reason"] = "OTHER"
            touch(e)


def _close_listing(listing):
    """Close a listing: closes any open suspension, freezes creditable_days."""
    for s in suspensions.values():
        if s["listing_id"] == listing["id"] and s.get("ended_at") is None:
            s["ended_at"] = iso_ts(now_dt())
            touch(s)
    listing["status"] = "CLOSED"
    listing["closed_at"] = iso_ts(now_dt())
    refresh_creditable_days(listing)
    touch(listing)


def terminate_accepted_agreement(agreement):
    """ACCEPTED -> TERMINATED; case AGREEMENT_ACTIVE -> TERMS_NEGOTIATION."""
    agreement["status"] = "TERMINATED"
    touch(agreement)
    case = cases.get(agreement["case_id"])
    if case is not None and case["status"] == "AGREEMENT_ACTIVE":
        case["status"] = "TERMS_NEGOTIATION"
        recompute_remaining(case)
        touch(case)


def eviction_file_cascade(case):
    """On eviction filing: case HOLDOVER_ESCALATED -> EVICTION_IN_PROGRESS with cascade."""
    case["status"] = "EVICTION_IN_PROGRESS"
    for a in agreements.values():
        if a["case_id"] == case["id"] and a["status"] == "ACCEPTED":
            a["status"] = "TERMINATED"
            touch(a)
    for d in disbursements.values():
        if d["case_id"] == case["id"] and d["status"] in ("PENDING", "APPROVED"):
            d["status"] = "VOIDED"
            touch(d)
    if case["program_type"] == "DEED_IN_LIEU":
        loan = loans.get(case["loan_id"])
        if loan is not None and loan["status"] == "WORKOUT_IN_PROGRESS":
            loan["status"] = "FORECLOSURE_PROCEEDING"
            touch(loan)
    touch(case)


def execute_waiver_and_complete_loan(case, recorded_dt):
    """Hop 2/3 of recording confirmation: waiver execution + loan completion."""
    waiver = case_waiver(case["id"])
    loan = loans[case["loan_id"]]
    if waiver is not None and waiver["status"] == "DOCUMENTED":
        agreement = case_accepted_agreement(case) or _last_case_agreement(case)
        accepted_d = db.parse_dt(agreement["accepted_at"]).date()
        recorded_d = recorded_dt.date()
        final_amt = deficiency_waiver_amount(loan, accepted_d, recorded_d)
        waiver["final_waiver_cents"] = final_amt
        waiver["pre_waiver_deficiency_cents"] = final_amt
        waiver["waived_amount_cents"] = final_amt
        waiver["status"] = "EXECUTED"
        touch(waiver)
        loan["deficiency_balance_cents"] = waiver["pre_waiver_deficiency_cents"] - waiver["waived_amount_cents"]
    loan["status"] = "DEED_IN_LIEU_COMPLETED"
    loan["servicing_system_synced"] = True
    if loan["foreclosure_referral_status"] == "REFERRED":
        loan["foreclosure_referral_status"] = "WITHDRAWN"
    touch(loan)


def _last_case_agreement(case_id):
    cands = [a for a in agreements.values() if a["case_id"] == case_id]
    if not cands:
        return None
    cands.sort(key=lambda a: a["created_at"])
    return cands[-1]


def complete_case(case):
    """Case completion cascade shared by the CFK fork and DIL recording."""
    case["status"] = "COMPLETED"
    touch(case)
    agreement = case_accepted_agreement(case)
    if agreement is not None and agreement["status"] == "ACCEPTED":
        agreement["status"] = "COMPLETED"
        touch(agreement)
