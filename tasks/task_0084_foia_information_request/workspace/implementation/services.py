"""Business logic: calculations, deadline arithmetic, and audit logging.

All money is integer cents. Decimal + ROUND_HALF_UP is used wherever a
fractional cent or fractional score could appear (PRD §2.7).
"""

import math
from decimal import Decimal, ROUND_HALF_UP

import db
from clock import (
    add_working_days,
    end_of_working_day,
    now,
    parse_iso,
    to_iso,
    working_days_between,
)

# ---- Fee assessment constants (scaffold §1.3 fee_assessment) ----------------
SEARCH_RATE_CENTS_PER_QH = 1000
REVIEW_RATE_CENTS_PER_QH = 1000
DUP_CENTS_PER_PAGE = 10
FREE_PAGES = 100
FREE_SEARCH_HOURS = 2
ADVANCE_PAYMENT_THRESHOLD_CENTS = 25000

# ---- Fee-waiver scoring constants -------------------------------------------
W_PUBLIC_UNDERSTANDING = Decimal("0.40")
W_NOT_COMMERCIAL_INTEREST = Decimal("0.30")
W_MEANINGFUL_CONTRIBUTION = Decimal("0.20")
W_ABILITY_TO_DISSEMINATE = Decimal("0.10")
WAIVER_GRANT_THRESHOLD = 70

# ---- Deadline constants -----------------------------------------------------
WORKING_DAYS_BASE = 20
EXTENSION_WORKING_DAYS = 10
APPEAL_WINDOW_DAYS = 90
REVERSE_NOTICE_DAYS = 10


def _round_half_up(value) -> int:
    """Round a numeric value half-up to the nearest whole integer (cents/score)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- §1.3 fee_assessment ----------------------------------------------------
def assess_fee(fee_category: str, search_hours, review_hours, billable_pages, waiver_granted: bool):
    """Returns (assessed_fee_cents, requires_advance_payment).

    Order pinned: bill search/review per quarter-hour (round UP to whole QH),
    compute each component from rates, round each component half-up, then sum
    the rounded components (PRD §2.7, §3.4)."""
    search_qh = math.ceil(search_hours * 4)
    review_qh = math.ceil(review_hours * 4)

    search_cost = _round_half_up(search_qh * SEARCH_RATE_CENTS_PER_QH)
    review_cost = _round_half_up(review_qh * REVIEW_RATE_CENTS_PER_QH)
    dup_cost_full = _round_half_up(billable_pages * DUP_CENTS_PER_PAGE)

    if fee_category == "COMMERCIAL":
        assessed = search_cost + review_cost + dup_cost_full
    elif fee_category in ("EDUCATIONAL", "NEWS_MEDIA"):
        chargeable_pages = max(0, billable_pages - FREE_PAGES)
        assessed = _round_half_up(chargeable_pages * DUP_CENTS_PER_PAGE)
    else:  # OTHER
        free_search_qh = FREE_SEARCH_HOURS * 4
        chargeable_qh = max(0, search_qh - free_search_qh)
        search_cost_other = _round_half_up(chargeable_qh * SEARCH_RATE_CENTS_PER_QH)
        chargeable_pages = max(0, billable_pages - FREE_PAGES)
        dup_cost_other = _round_half_up(chargeable_pages * DUP_CENTS_PER_PAGE)
        assessed = search_cost_other + dup_cost_other

    if waiver_granted:
        assessed = 0

    requires_advance_payment = assessed > ADVANCE_PAYMENT_THRESHOLD_CENTS
    return assessed, requires_advance_payment


# ---- §1.3 fee_waiver_eligibility_score --------------------------------------
def waiver_score(f_pu: bool, f_nc: bool, f_mc: bool, f_ad: bool):
    """Returns (score:int 0..100, granted:bool). Commercial-ineligibility is
    enforced by the caller before invoking this."""
    weighted = (
        W_PUBLIC_UNDERSTANDING * (1 if f_pu else 0)
        + W_NOT_COMMERCIAL_INTEREST * (1 if f_nc else 0)
        + W_MEANINGFUL_CONTRIBUTION * (1 if f_mc else 0)
        + W_ABILITY_TO_DISSEMINATE * (1 if f_ad else 0)
    )
    score = _round_half_up(Decimal(100) * weighted)
    granted = score >= WAIVER_GRANT_THRESHOLD
    return score, granted


# ---- §1.3 deadline_projection ----------------------------------------------
def compute_base_due_at(received_at_iso: str) -> str:
    received = parse_iso(received_at_iso)
    base = add_working_days(received, WORKING_DAYS_BASE)
    return to_iso(end_of_working_day(base))


def recompute_effective_due_at(deadline: dict):
    """effective_due_at = add_working_days(received_at, 20 + extension + tolled).

    base_due_at is anchored on received_at + 20; effective adds the extension
    and tolled working days on top of the base day, all in working days."""
    base = parse_iso(deadline["base_due_at"])
    extra = deadline["extension_days_added"] + deadline["tolled_working_days"]
    eff = add_working_days(base, extra)
    deadline["effective_due_at"] = to_iso(end_of_working_day(eff))


def deadline_outcome(deadline: dict) -> str:
    """MET iff now <= effective_due_at (inclusive boundary), else MISSED."""
    eff = parse_iso(deadline["effective_due_at"])
    return "MET" if now() <= eff else "MISSED"


# ---- §1.3 outstanding_balance_recompute -------------------------------------
def recompute_outstanding_balance(requester_id: str):
    total = 0
    for r in db.requests.values():
        if r["requester_id"] != requester_id:
            continue
        if r["fee_payment_status"] != "DUE":
            continue
        fe = current_fee_estimate(r["id"])
        if fe is not None:
            total += fe["assessed_fee_cents"]
    req = db.requesters.get(requester_id)
    if req is not None:
        req["outstanding_balance_cents"] = total
        db.touch(req)


def current_fee_estimate(request_id: str):
    """The single current FeeEstimate of a request (latest by creation)."""
    candidates = [fe for fe in db.fee_estimates.values() if fe["request_id"] == request_id]
    if not candidates:
        return None
    candidates.sort(key=lambda o: (o["created_at"], o.get("_seq", 0)))
    return candidates[-1]


def get_deadline(request_id: str):
    for d in db.deadlines.values():
        if d["request_id"] == request_id:
            return d
    return None


# ---- Audit trail ------------------------------------------------------------
def append_audit(request_id: str, event_type: str, detail: str, actor_role: str):
    ev = {
        "request_id": request_id,
        "event_type": event_type,
        "detail": detail,
        "actor_role": actor_role,
    }
    db.stamp_create(ev, versioned=False)
    db.audit_events[ev["id"]] = ev
    return ev


# ---- Records for a request --------------------------------------------------
def records_for_request(request_id: str):
    return [r for r in db.records.values() if r["request_id"] == request_id]


def exemptions_for_request(request_id: str):
    return [e for e in db.exemptions.values() if e["request_id"] == request_id]


def record_has_record_exemption(record_id: str) -> bool:
    for e in db.exemptions.values():
        if e["applies_to_kind"] == "RECORD" and e.get("record_id") == record_id:
            return True
    return False


def objection_for_record(record_id: str):
    """Return the most recent objection on a record, if any."""
    cands = [o for o in db.objections.values() if o["record_id"] == record_id]
    if not cands:
        return None
    cands.sort(key=lambda o: (o["created_at"], o.get("_seq", 0)))
    return cands[-1]
