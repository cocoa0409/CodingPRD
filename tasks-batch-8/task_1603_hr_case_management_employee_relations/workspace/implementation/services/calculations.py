"""Calculation rules (scaffold §1.3, PRD §3).

All decimal quantities round half-up to exactly two decimal places; credibility
and calibration scores are clamped to [0.00, 1.00] BEFORE rounding (PRD §2.10).
"""
import hashlib
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db
from util import (
    CLOCK, compute_sla_due_date, compute_overdue_business_days,
    quarter_start, quarter_end_date, fmt_dt_ms,
)

CENT = Decimal("0.01")


def _round2(d: Decimal) -> Decimal:
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def _clamp01(d: Decimal) -> Decimal:
    if d < Decimal("0"):
        return Decimal("0")
    if d > Decimal("1"):
        return Decimal("1")
    return d


# ---------------------------------------------------------------------------
# credibility_score — dual sanctioned variants over the same inputs
# ---------------------------------------------------------------------------

def credibility_scores(corroboration_count: int, contradiction_count: int,
                       account_age_days: int):
    """Returns (score_corroboration, score_recency), each clamped then rounded
    half-up to 2 decimal places."""
    base = Decimal("0.50")
    corro_cap = min(corroboration_count, 4)
    contra_cap = min(contradiction_count, 3)

    score_c = base + Decimal("0.10") * corro_cap - Decimal("0.15") * contra_cap
    score_c = _round2(_clamp01(score_c))

    recency_decay = Decimal("0.005") * min(account_age_days, 60)
    score_r = (base + Decimal("0.06") * corro_cap
               - Decimal("0.10") * contra_cap - recency_decay)
    score_r = _round2(_clamp01(score_r))
    return float(score_c), float(score_r)


def active_score(assessment) -> float:
    """The score named by the assessment's active_variant."""
    if assessment["active_variant"] == "RECENCY_WEIGHTED":
        return assessment["score_recency"]
    return assessment["score_corroboration"]


# ---------------------------------------------------------------------------
# action_calibration — cross-case calibration score at approval quorum
# ---------------------------------------------------------------------------

FALLBACK_MEDIAN = {"LOW": 10, "MEDIUM": 30, "HIGH": 60, "CRITICAL": 85}
HISTORY_WINDOW_DAYS = 365
MIN_HISTORY_FOR_MEDIAN = 3


def findings_of(case_id):
    return [f for f in db["findings"].values() if f["case_id"] == case_id]


def actions_of(finding_id):
    return [a for a in db["recommended_actions"].values()
            if a["finding_id"] == finding_id]


def _median(values):
    """Median of a non-empty list of ints as an exact Decimal."""
    vals = sorted(values)
    n = len(vals)
    if n % 2 == 1:
        return Decimal(vals[n // 2])
    return (Decimal(vals[n // 2 - 1]) + Decimal(vals[n // 2])) / Decimal(2)


def action_calibration(finding, case):
    """Calibration score in [0.00, 1.00]: 1 - |proposed_max - hist_median| / 100,
    floored at 0, rounded half-up to 2dp. History = other APPROVED findings in
    the same case category approved within the trailing 365 days."""
    now = CLOCK.now()
    window_start = now - timedelta(days=HISTORY_WINDOW_DAYS)
    hist_scores = []
    for other in db["findings"].values():
        if other["id"] == finding["id"]:
            continue
        if other["approval_status"] != "APPROVED":
            continue
        approved_at = other.get("_approved_at")
        if approved_at is None or not (window_start <= approved_at <= now):
            continue
        other_case = db["cases"].get(other["case_id"])
        if other_case is None or other_case["category"] != case["category"]:
            continue
        accepted = [a["severity_points"] for a in actions_of(other["id"])
                    if a["status"] == "ACCEPTED"]
        hist_scores.append(max(accepted) if accepted else 0)

    if len(hist_scores) >= MIN_HISTORY_FOR_MEDIAN:
        reference = _median(hist_scores)
    else:
        reference = Decimal(FALLBACK_MEDIAN[case["severity"]])

    proposed = [a["severity_points"] for a in actions_of(finding["id"])
                if a["status"] == "PROPOSED"]
    proposed_max = Decimal(max(proposed)) if proposed else Decimal(0)

    deviation = abs(proposed_max - reference)
    score = max(Decimal("0"), Decimal("100") - deviation) / Decimal("100")
    return float(_round2(score))


def calibration_winner(finding):
    """The PROPOSED action with max severity_points; ties broken by earliest
    created_at (insertion order as final tiebreak). None when no PROPOSED
    action exists."""
    proposed = [a for a in actions_of(finding["id"]) if a["status"] == "PROPOSED"]
    if not proposed:
        return None
    proposed.sort(key=lambda a: (-a["severity_points"], a["_created_dt"], a["_seq"]))
    return proposed[0]


# ---------------------------------------------------------------------------
# trend_case_rate — dual window variants over manager/location scopes
# ---------------------------------------------------------------------------

def employee_in_scope(emp, scope_type: str, scope_key: str) -> bool:
    """MANAGER: emp is the scope_key employee or their manager chain (walked
    transitively through manager_id) includes scope_key.
    LOCATION: emp.location_code == scope_key."""
    if emp is None:
        return False
    if scope_type == "LOCATION":
        return emp["location_code"] == scope_key
    # MANAGER
    cur = emp
    seen = set()
    while cur is not None and cur["id"] not in seen:
        if cur["id"] == scope_key:
            return True
        seen.add(cur["id"])
        nxt = cur.get("manager_id")
        cur = db["employees"].get(nxt) if nxt else None
    return False


def case_in_scope(case, scope_type, scope_key) -> bool:
    subject = db["employees"].get(case["subject_employee_id"])
    return employee_in_scope(subject, scope_type, scope_key)


def case_closures_in_window(case, window_kind, as_of):
    """Closure instants of this case inside the window. A reopened-and-reclosed
    case contributes once per distinct closure (PRD §3.7)."""
    hits = []
    for closed_at in case.get("_closures", []):
        if window_kind == "ROLLING_90D":
            if as_of - timedelta(days=90) < closed_at <= as_of:
                hits.append(closed_at)
        else:  # CALENDAR_QUARTER: [quarter_start(as_of), as_of]
            if quarter_start(as_of) <= closed_at <= as_of:
                hits.append(closed_at)
    return hits


def headcount_in_scope(scope_type, scope_key, window_kind, as_of):
    """ROLLING_90D: ACTIVE employees in scope at as_of.
    CALENDAR_QUARTER: ACTIVE or ON_LEAVE employees in scope hired on or before
    the quarter's final day.

    PRD §3.7: the headcount is "the number of employees in scope — the same
    manager-chain or location test applied to employee records" with the
    window-variant employment_status filter. Every employee record counts;
    carrying an Investigator profile does not remove an employee from the
    workforce denominator.
    """
    qend = quarter_end_date(as_of) if window_kind == "CALENDAR_QUARTER" else None
    count = 0
    for emp in db["employees"].values():
        if not employee_in_scope(emp, scope_type, scope_key):
            continue
        if window_kind == "ROLLING_90D":
            if emp["employment_status"] == "ACTIVE":
                count += 1
        else:
            if (emp["employment_status"] in ("ACTIVE", "ON_LEAVE")
                    and emp["_hire_date"].date() <= qend):
                count += 1
    return count


def compute_trend_figures(scope_type, scope_key, window_kind, as_of):
    """Returns (closed_case_count, substantiated_count, headcount). The caller
    applies the zero-headcount rule and the per-scope rounding."""
    closed_count = 0
    substantiated = 0
    for case in db["cases"].values():
        if not case_in_scope(case, scope_type, scope_key):
            continue
        closures = case_closures_in_window(case, window_kind, as_of)
        if not closures:
            continue
        closed_count += len(closures)
        finals = findings_of(case["id"])
        final_finding = None
        if finals:
            finals.sort(key=lambda f: (f["_created_dt"], f["_seq"]))
            final_finding = finals[-1]
        if final_finding is not None and \
                final_finding["substantiation_status"] == "SUBSTANTIATED":
            substantiated += len(closures)
    headcount = headcount_in_scope(scope_type, scope_key, window_kind, as_of)
    return closed_count, substantiated, headcount


def trend_rate(closed_case_count: int, headcount: int) -> float:
    """Per-scope rate, rounded half-up to 2dp immediately. Cross-scope rollups
    (if ever requested) must sum UNROUNDED rates and round once — summing
    pre-rounded rates is forbidden (PRD §2.10)."""
    return float(_round2(Decimal(closed_case_count) / Decimal(headcount)
                         * Decimal(100)))


# ---------------------------------------------------------------------------
# litigation_manifest — deterministic projection of the case file
# ---------------------------------------------------------------------------

MANIFEST_TYPE_ORDER = {"EVIDENCE": 0, "INTERVIEW": 1, "FINDING": 2, "NOTICE": 3}


def compute_manifest(case_id):
    """One entry per non-ARCHIVED EvidenceItem, per COMPLETED Interview, per
    Finding, per SENT ClosureNotice. Ordered by created_at ASC with entry-type
    tie-break EVIDENCE < INTERVIEW < FINDING < NOTICE; id is never a sort key.
    Returns (member_ids_frozenset, [line, ...])."""
    entries = []
    for ev in db["evidence_items"].values():
        if ev["case_id"] == case_id and ev["status"] != "ARCHIVED":
            entries.append(("EVIDENCE", ev))
    for iv in db["interviews"].values():
        if iv["case_id"] == case_id and iv["status"] == "COMPLETED":
            entries.append(("INTERVIEW", iv))
    for f in db["findings"].values():
        if f["case_id"] == case_id:
            entries.append(("FINDING", f))
    for n in db["closure_notices"].values():
        if n["case_id"] == case_id and n["delivery_status"] == "SENT":
            entries.append(("NOTICE", n))
    entries.sort(key=lambda e: (e[1]["_created_dt"],
                                MANIFEST_TYPE_ORDER[e[0]],
                                e[1]["_seq"]))
    lines = [f"{etype}:{rec['id']}:{fmt_dt_ms(rec['_updated_dt'])}"
             for etype, rec in entries]
    member_ids = frozenset((etype, rec["id"]) for etype, rec in entries)
    return member_ids, lines


def manifest_hash(lines) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# SLA / overdue re-exports for route modules
# ---------------------------------------------------------------------------

def sla_due_date_for(intake_dt, channel):
    holidays = {h["_date"] for h in db["holidays"].values()}
    return compute_sla_due_date(intake_dt, channel["sla_business_days"], holidays)


def overdue_days_for(case):
    if case.get("_sla_due_dt") is None:
        return 0
    holidays = {h["_date"] for h in db["holidays"].values()}
    return compute_overdue_business_days(CLOCK.now(), case["_sla_due_dt"], holidays)
