"""Business logic: deadline arithmetic, renewal fees, sweeps, cascades, comment accuracy."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store
from timeutil import now
from common import touch

# Exam sets spawned on first submit, per registration_category.
CATEGORY_EXAMS = {
    "RR": ["SIE", "S7", "S63"],
    "IA": ["SIE", "S66"],
    "PRINCIPAL": ["SIE", "S7", "S24"],
}

AMENDMENT_WINDOW_DAYS = 30
U5_WINDOW_DAYS = 30
INQUIRY_RESPONSE_DAYS = 15
EXAM_CREDIT_DAYS = 120

FIRST_REGISTRATION_BASE_CENTS = 10000
ADDITIONAL_REGISTRATION_BASE_CENTS = 5000
STATE_JURISDICTION_FEE_CENTS = 5000
SRO_JURISDICTION_FEE_CENTS = 0
LATE_BLOCK_DAYS = 14
LATE_PCT_PER_BLOCK = 25
LATE_PCT_CAP = 100

MAX_DEFICIENCIES = 3

SRO_CODES = {"FINRA", "NYSE", "NASDAQ"}

# comment_accuracy_check contradiction map (case-insensitive substrings).
CONTRADICTION_MAP = {
    "VOLUNTARY": ["fired", "discharged", "terminated for cause"],
    "PERMITTED_TO_RESIGN": ["voluntary resignation of"],
    "DISCHARGED": ["resigned voluntarily", "quit"],
    "DECEASED": ["resigned", "fired", "discharged"],
}


# ---------------------------------------------------------------- computations
def open_inquiry_count(firm_id):
    return sum(
        1
        for q in store.regulatory_inquiries.values()
        if q["firm_id"] == firm_id and q["status"] in ("OPEN", "PENDING_RESPONSE")
    )


def fingerprint_required(applicant_id):
    """True when the applicant has no FingerprintSubmission with status CLEARED."""
    for fs in store.fingerprint_submissions.values():
        if fs["status"] != "CLEARED":
            continue
        req = store.registration_requests.get(fs["registration_request_id"])
        if req and req["applicant_id"] == applicant_id:
            return False
    return True


def compute_deadline(basis, anchor_date, n_days):
    """amendment_deadline calculation; inclusive through 23:59:59.999Z of the result date."""
    if basis == "REGULATORY":
        d = anchor_date
        added = 0
        while added < n_days:
            d += timedelta(days=1)
            if d.weekday() < 5:  # Mon..Fri; holiday calendar is empty
                added += 1
    else:  # CALENDAR
        d = anchor_date + timedelta(days=n_days)
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)


def firm_basis(firm_id):
    firm = store.firms.get(firm_id)
    if firm is None:
        return "CALENDAR"
    return firm.get("deadline_basis", "CALENDAR")


def applicant_active_registration(applicant_id):
    """Most recently ACTIVE request by approved_at, tie-break created_at ASC."""
    cands = [
        r
        for r in store.registration_requests.values()
        if r["applicant_id"] == applicant_id and r["status"] == "ACTIVE"
    ]
    if not cands:
        return None
    cands.sort(key=lambda r: (r["approved_at"], -r["_seq"]))
    return cands[-1]


def event_firm_basis(applicant_id):
    """Deadline basis governing a disclosure event: the applicant's ACTIVE firm's basis."""
    req = applicant_active_registration(applicant_id)
    if req is None:
        return "CALENDAR"
    return firm_basis(req["firm_id"])


def jurisdiction_fee(request_id):
    return sum(
        s["annual_fee_cents"]
        for s in store.jurisdiction_selections.values()
        if s["registration_request_id"] == request_id and s["status"] == "APPROVED"
    )


def firm_rank(req):
    """Count of the firm's other ACTIVE registrations approved before this one
    (tie-break created_at ASC). For a non-ACTIVE request, projected as of now."""
    if req["status"] == "ACTIVE" and req["approved_at"] is not None:
        my_key = (req["approved_at"], req["_seq"])
    else:
        my_key = (now(), req["_seq"])
    rank = 0
    for r in store.registration_requests.values():
        if r["firm_id"] != req["firm_id"] or r["id"] == req["id"]:
            continue
        if r["status"] != "ACTIVE" or r["approved_at"] is None:
            continue
        if (r["approved_at"], r["_seq"]) < my_key:
            rank += 1
    return rank


def late_surcharge(base_fee_cents, cycle_year, on_date):
    jan1 = datetime(cycle_year, 1, 1).date()
    days_late = max(0, (on_date - jan1).days)
    blocks = days_late // LATE_BLOCK_DAYS
    pct = min(blocks * LATE_PCT_PER_BLOCK, LATE_PCT_CAP)
    amount = Decimal(base_fee_cents) * Decimal(pct) / Decimal(100)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fee_components(req, cycle_year, on_date):
    """renewal_fee calculation: (jurisdiction, base, surcharge, total)."""
    j = jurisdiction_fee(req["id"])
    base = FIRST_REGISTRATION_BASE_CENTS if firm_rank(req) == 0 else ADDITIONAL_REGISTRATION_BASE_CENTS
    s = late_surcharge(base, cycle_year, on_date)
    return j, base, s, j + base + s


def payable_total_cents(invoice, on_date):
    s = late_surcharge(invoice["base_fee_cents"], invoice["cycle_year"], on_date)
    return invoice["jurisdiction_fee_cents"] + invoice["base_fee_cents"] + s


def comment_disposition(termination_reason, comment_text):
    forbidden = CONTRADICTION_MAP.get(termination_reason, [])
    text = (comment_text or "").lower()
    score = sum(1 for sub in forbidden if sub in text)
    return "CONSISTENT" if score == 0 else "INCONSISTENT"


# ------------------------------------------------------------------ sweeps
def sweep_clock():
    """Time-based system transitions evaluated when the logical clock is set."""
    now_dt = now()
    # 1) APPROVED -> ACTIVE day rollover first (activation locks exam credits).
    for req in store.registration_requests.values():
        if req["status"] == "APPROVED" and req["approved_at"] is not None:
            if now_dt.date() > req["approved_at"].date():
                req["status"] = "ACTIVE"
                touch(req)
    # 2) ExamRequirement PASSED -> EXPIRED sweep (boundary is >=).
    for er in store.exam_requirements.values():
        if er["status"] != "PASSED" or er["credit_expiry_at"] is None:
            continue
        parent = store.registration_requests.get(er["registration_request_id"])
        if parent is None or parent["status"] in ("ACTIVE", "TERMINATED"):
            continue
        if now_dt >= er["credit_expiry_at"]:
            er["status"] = "EXPIRED"
            touch(er)


# ------------------------------------------------------------------ cascades
def void_issued_invoices(request_id):
    for inv in store.renewal_invoices.values():
        if inv["registration_request_id"] == request_id and inv["status"] == "ISSUED":
            inv["status"] = "VOID"
            touch(inv)


def cascade_request_withdrawn(req):
    for sel in store.jurisdiction_selections.values():
        if sel["registration_request_id"] == req["id"] and sel["status"] == "SELECTED":
            sel["status"] = "RELINQUISHED"
            touch(sel)
    void_issued_invoices(req["id"])


def cascade_request_terminated(req):
    for sel in store.jurisdiction_selections.values():
        if sel["registration_request_id"] == req["id"] and sel["status"] == "APPROVED":
            sel["status"] = "RELINQUISHED"
            touch(sel)
    void_issued_invoices(req["id"])
    # Revoke APPROVED affiliations built on this registration; each revocation
    # cascades to void ISSUED invoices on the second firm's corresponding registration.
    for aff in store.affiliation_requests.values():
        if aff["first_registration_request_id"] != req["id"] or aff["status"] != "APPROVED":
            continue
        aff["status"] = "REVOKED"
        touch(aff)
        for other in store.registration_requests.values():
            if (
                other["applicant_id"] == aff["applicant_id"]
                and other["firm_id"] == aff["second_firm_id"]
            ):
                void_issued_invoices(other["id"])


def recompute_issued_invoice_jurisdiction_fees(request_id):
    """Relinquishment echo: recompute jurisdiction_fee_cents on ISSUED invoices."""
    j = jurisdiction_fee(request_id)
    for inv in store.renewal_invoices.values():
        if inv["registration_request_id"] == request_id and inv["status"] == "ISSUED":
            inv["jurisdiction_fee_cents"] = j
            inv["total_cents"] = j + inv["base_fee_cents"] + inv["late_surcharge_cents"]
            touch(inv)
