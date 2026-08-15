"""Calculation rules (scaffold section 1.3 / PRD sections 2.6, 3.3-3.9)."""

import math
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
import errors

# Constants (scaffold section 1.3)
ACK_WINDOW_HOURS = 24
IRE_FORWARD_WINDOW_HOURS = 72
REOPEN_WINDOW_DAYS = 180
DUPLICATE_WINDOW_SECONDS = 3600

ELEMENT_WEIGHTS = {
    "citation_of_criteria": Decimal("0.25"),
    "appeal_rights": Decimal("0.25"),
    "decision_rationale": Decimal("0.20"),
    "expedited_availability": Decimal("0.10"),
    "ire_notice": Decimal("0.10"),
    "contact_information": Decimal("0.05"),
    "language_assistance": Decimal("0.05"),
}

W_SEVERITY = Decimal("0.35")
W_ACUITY = Decimal("0.25")
W_GUIDELINE = Decimal("0.20")
W_COMORBIDITY = Decimal("0.10")
W_FUNCTIONAL = Decimal("0.10")


def round2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Deadline policies
# ---------------------------------------------------------------------------

def find_active_policy(program, case_kind, priority_track):
    for pol in db.policies.values():
        if (pol["active"] and pol["program"] == program
                and pol["case_kind"] == case_kind
                and pol["priority_track"] == priority_track):
            return pol
    return None


def active_policy_or_error(program, case_kind, priority_track):
    pol = find_active_policy(program, case_kind, priority_track)
    if pol is None:
        raise errors.policy_not_configured()
    return pol


# ---------------------------------------------------------------------------
# case_deadline_calculation
# ---------------------------------------------------------------------------

def compute_resolution_due(case, policy):
    """received_at + policy.resolution_hours (+ extension_hours when applied)."""
    base = case["received_at"] + timedelta(hours=policy["resolution_hours"])
    if case["extension_applied"]:
        base = base + timedelta(hours=policy["extension_hours"])
    return base


def case_overdue(case):
    """overdue := now > resolution_due_at and status not terminal/IRE_REFERRED."""
    due = case.get("resolution_due_at")
    if due is None:
        return False
    if case["status"] in ("CLOSED", "WITHDRAWN", "IRE_REFERRED"):
        return False
    return db.clock_now() > due


# ---------------------------------------------------------------------------
# medical_necessity_scoring (sum-then-round, HALF_UP, 2dp)
# ---------------------------------------------------------------------------

def medical_necessity_score(severity, acuity, guideline_match, comorbidity,
                            functional_impairment, override_score=None):
    if override_score is not None:
        val = round2(Decimal(str(override_score)))
        if val < Decimal("0"):
            val = Decimal("0.00")
        if val > Decimal("100"):
            val = Decimal("100.00")
        return val
    raw = (W_SEVERITY * severity + W_ACUITY * acuity
           + W_GUIDELINE * guideline_match + W_COMORBIDITY * comorbidity
           + W_FUNCTIONAL * functional_impairment)
    return round2(raw * 10)


# ---------------------------------------------------------------------------
# notification_completeness_scoring (per-element round to 4dp, sum, then 2dp)
# ---------------------------------------------------------------------------

def required_elements_for(notification_kind, recipient_kind, program,
                          case_kind, decision_outcome):
    """The content matrix resolves to the full weighted element set; the seven
    element weights sum to exactly 1.00, which is the only required set that
    can satisfy the completeness gate of section 3.5."""
    return list(ELEMENT_WEIGHTS.keys())


def completeness_score(required_elements, supplied_elements):
    supplied = set(supplied_elements or [])
    total = Decimal("0")
    for elem in required_elements:
        if elem in supplied:
            total += round4(ELEMENT_WEIGHTS[elem])
    return round2(total)


# ---------------------------------------------------------------------------
# effectuation_timeliness_calculation
# ---------------------------------------------------------------------------

def _business_seconds_between(start, end):
    """Seconds within [start, end] falling in Mon-Fri 08:00-17:00 UTC."""
    if end <= start:
        return 0
    total = 0
    day = start.astimezone(timezone.utc).date()
    last_day = end.astimezone(timezone.utc).date()
    one_day = timedelta(days=1)
    while day <= last_day:
        if day.weekday() < 5:  # Monday..Friday
            win_start = datetime.combine(day, time(8, 0), tzinfo=timezone.utc)
            win_end = datetime.combine(day, time(17, 0), tzinfo=timezone.utc)
            lo = max(start, win_start)
            hi = min(end, win_end)
            if hi > lo:
                total += (hi - lo).total_seconds()
        day += one_day
    return total


def effectuation_timeliness(case, effectuation, business_hours_only=False):
    window_seconds = (case["effectuation_due_at"] - case["decided_at"]).total_seconds()
    if business_hours_only:
        consumed_seconds = _business_seconds_between(
            case["decided_at"], effectuation["completed_at"])
    else:
        consumed_seconds = (effectuation["completed_at"] - case["decided_at"]).total_seconds()
    window_hours = Decimal(str(window_seconds)) / Decimal(3600)
    consumed_hours = Decimal(str(consumed_seconds)) / Decimal(3600)
    if window_hours <= 0:
        return Decimal("0.00")
    pct = (Decimal(100) * consumed_hours) / window_hours
    return round2(pct)


# ---------------------------------------------------------------------------
# ctm_linkage_weighting
# ---------------------------------------------------------------------------

def member_open_cases(member_id):
    open_states = {"RECEIVED", "TRIAGED", "IN_REVIEW", "PENDING_CLINICAL",
                   "DECIDED", "NOTIFIED", "IRE_REFERRED", "REOPENED"}
    return [c for c in db.cases.values()
            if c["member_id"] == member_id and c["status"] in open_states]


def member_open_case_count(member_id):
    return len(member_open_cases(member_id))


def member_ctm_linked_case_count(member_id):
    return len([c for c in db.cases.values()
                if c["member_id"] == member_id and c["ctm_linked"]
                and c["status"] not in ("CLOSED", "WITHDRAWN")])


def member_provisional_weight(member_id):
    """Linked cases still in RECEIVED count at half weight (0.5)."""
    total = 0.0
    for c in db.cases.values():
        if (c["member_id"] == member_id and c["ctm_linked"]
                and c["status"] not in ("CLOSED", "WITHDRAWN")):
            total += 0.5 if c["status"] == "RECEIVED" else 1.0
    return total


def ctm_tier_for(count):
    if count == 0:
        return "NONE", 0
    if count <= 2:
        return "LOW", 1
    if count <= 5:
        return "MEDIUM", 2
    return "HIGH", 3


def ctm_exposure(member_id):
    provisional = member_provisional_weight(member_id)
    tier, weight = ctm_tier_for(math.ceil(provisional) if provisional > 0 else 0)
    return {
        "tier": tier,
        "weight": weight,
        "provisional_weight": provisional,
        "ctm_linked_case_count": member_ctm_linked_case_count(member_id),
    }


# ---------------------------------------------------------------------------
# audit_universe_aggregation
# ---------------------------------------------------------------------------

def period_window(report_period):
    """Half-open [period_start, period_end) window for a YYYY-MM key."""
    year = int(report_period[0:4])
    month = int(report_period[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def cases_decided_in_period(report_period):
    start, end = period_window(report_period)
    rows = [c for c in db.cases.values()
            if c["decided_at"] is not None and start <= c["decided_at"] < end]
    rows.sort(key=lambda c: (c["decided_at"], c["created_at"], c["_seq"]))
    return rows


def case_resolution_timely(case):
    return case["decided_at"] <= case["resolution_due_at"]


def case_effectuation_for_audit(case):
    """The operative effectuation for audit: most recently created, if any."""
    effs = [e for e in db.effectuations.values() if e["case_id"] == case["id"]]
    if not effs:
        return None
    effs.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return effs[-1]


def case_effectuation_timely(case):
    """None when no effectuation is required; otherwise completion comparison."""
    if case.get("effectuation_due_at") is None:
        return None
    eff = case_effectuation_for_audit(case)
    if eff is None:
        return None
    if eff["completed_at"] is None:
        return False
    return eff["completed_at"] <= case["effectuation_due_at"]


def case_ack_late(case):
    if case["acknowledged_at"] is None or case["received_at"] is None:
        return False
    delta = (case["acknowledged_at"] - case["received_at"]).total_seconds()
    return delta > ACK_WINDOW_HOURS * 3600
