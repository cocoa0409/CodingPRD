"""Calculation rules (SCAFFOLD Table 3 / PRD §2.6, §3).

All money/score arithmetic uses Decimal; never float.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

# ---------------------------------------------------------------------------
# impact_rating
# ---------------------------------------------------------------------------

SEVERITY_HINT_MAP = {"LOW": 1, "MEDIUM": 2, "HIGH": 4, "CRITICAL": 5}
PROVISIONAL_ASSUMED_LIKELIHOOD = 3

TIER_LOW_MAX = 5
TIER_MEDIUM_MAX = 12
TIER_HIGH_MAX = 20


def tier_for(raw):
    """raw is a Decimal (or int). Bands: <5 LOW; [5,12) MEDIUM; [12,20) HIGH; >=20 CRITICAL."""
    if raw < TIER_LOW_MAX:
        return "LOW"
    if raw < TIER_MEDIUM_MAX:
        return "MEDIUM"
    if raw < TIER_HIGH_MAX:
        return "HIGH"
    return "CRITICAL"


def scope_multiplier(lines):
    if lines == 1:
        return Decimal("1.0")
    if 2 <= lines <= 3:
        return Decimal("1.2")
    return Decimal("1.5")


def provisional_risk_tier(severity_hint):
    """Provisional variant: raw = hint_score * 3 * 1.0."""
    raw = Decimal(SEVERITY_HINT_MAP[severity_hint]) * PROVISIONAL_ASSUMED_LIKELIHOOD * Decimal("1.0")
    return tier_for(raw)


def confirmed_impact(likelihood, severity, affected_business_lines):
    """Confirmed variant: raw kept at 1 decimal place."""
    raw = Decimal(likelihood) * Decimal(severity) * scope_multiplier(affected_business_lines)
    raw = raw.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return raw, tier_for(raw)


# ---------------------------------------------------------------------------
# implementation_deadline (PRD §3.6)
# ---------------------------------------------------------------------------

MANDATE_DAYS = {"LOW": 180, "MEDIUM": 90, "HIGH": 45, "CRITICAL": 15}


def mandate_deadline(criticality, confirmed_at):
    """Mandated latest target_completion_date (UTC midnight semantics).

    CRITICAL: base + N calendar days, never rolled.
    LOW/MEDIUM/HIGH: base + N business days (Mon-Fri) counted from the day
    after base; weekend landings roll forward to Monday (no-op by construction
    since only business days are counted).
    """
    base = confirmed_at.date()
    n = MANDATE_DAYS[criticality]
    if criticality == "CRITICAL":
        d = base + timedelta(days=n)
    else:
        d = base
        counted = 0
        while counted < n:
            d += timedelta(days=1)
            if d.weekday() < 5:  # Mon-Fri
                counted += 1
        if d.weekday() >= 5:  # defensive roll-forward
            while d.weekday() >= 5:
                d += timedelta(days=1)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# residual_gap_score
# ---------------------------------------------------------------------------

CRITICALITY_POINTS = {"LOW": 4, "MEDIUM": 8, "HIGH": 16, "CRITICAL": 32}
REVIEW_FULL_DAYS = 90
REVIEW_STALE_DAYS = 180

_CENT = Decimal("0.01")


def effectiveness_factor(control, clock):
    """1.0 if reviewed <= 90 days ago; 0.8 if 91-180; 0.5 if > 180 or never."""
    last = control.get("last_reviewed_at")
    if last is None:
        return Decimal("0.5")
    age = clock - last
    if age <= timedelta(days=REVIEW_FULL_DAYS):
        return Decimal("1.0")
    if age <= timedelta(days=REVIEW_STALE_DAYS):
        return Decimal("0.8")
    return Decimal("0.5")


def next_review_due(control):
    last = control.get("last_reviewed_at")
    if last is None:
        return None
    return last + timedelta(days=control["review_frequency_days"])


def compute_gap_scores(gap, mappings, controls, clock):
    """Return (covered_points, residual_gap_points) as 2-decimal values.

    covered_points = SUM over APPROVED mappings of the gap's obligation of
    coverage_weight * effectiveness_factor(control) at the current clock.
    residual = max(0, requirement_points - covered), round_half_up 2dp.
    """
    covered = Decimal("0")
    for m in mappings:
        if m["obligation_id"] != gap["obligation_id"]:
            continue
        if m["status"] != "APPROVED":
            continue
        control = controls.get(m["control_id"])
        if control is None:
            continue
        covered += Decimal(m["coverage_weight"]) * effectiveness_factor(control, clock)
    covered = covered.quantize(_CENT, rounding=ROUND_HALF_UP)
    residual = Decimal(gap["requirement_points"]) - covered
    if residual < 0:
        residual = Decimal("0")
    residual = residual.quantize(_CENT, rounding=ROUND_HALF_UP)
    return covered, residual


# ---------------------------------------------------------------------------
# training_completion_pct (pinned order: round each department FIRST)
# ---------------------------------------------------------------------------

COMPLETE_THRESHOLD = Decimal("95.0")
EXCEPTION_THRESHOLD = Decimal("80.0")

_TENTH = Decimal("0.1")


def training_completion_pct(records):
    """records: list of {person_ref, department, completed}. Unweighted mean of
    per-department percentages, each department rounded half-up to 1dp first."""
    if not records:
        return Decimal("0.0")
    by_dept = {}
    for r in records:
        d = by_dept.setdefault(r["department"], [0, 0])
        d[0] += 1
        if r["completed"]:
            d[1] += 1
    dept_pcts = []
    for assigned, completed in by_dept.values():
        pct = (Decimal(100) * Decimal(completed) / Decimal(assigned)).quantize(
            _TENTH, rounding=ROUND_HALF_UP)
        dept_pcts.append(pct)
    mean = sum(dept_pcts, Decimal("0")) / Decimal(len(dept_pcts))
    return mean.quantize(_TENTH, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# deadline_posture
# ---------------------------------------------------------------------------

AT_RISK_WINDOW_DAYS = 14


def posture_for(target_completion_date, clock):
    """remaining < 0 -> OVERDUE; 0 <= remaining <= 14d -> AT_RISK; > 14d -> ON_TRACK.
    Exactly at the deadline is NOT overdue."""
    remaining = target_completion_date - clock
    if remaining < timedelta(0):
        return "OVERDUE"
    if remaining <= timedelta(days=AT_RISK_WINDOW_DAYS):
        return "AT_RISK"
    return "ON_TRACK"


# ---------------------------------------------------------------------------
# register_checksum
# ---------------------------------------------------------------------------


def register_checksum(version_number, sorted_codes):
    payload = "v" + str(version_number) + "|" + ",".join(sorted_codes)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# audit_chain_hash
# ---------------------------------------------------------------------------


def audit_event_hash(prev_event_hash, sequence_number, actor_user_id, action,
                     entity_type, entity_id, occurred_at):
    payload = "|".join([
        prev_event_hash,
        str(sequence_number),
        actor_user_id,
        action,
        entity_type,
        entity_id,
        occurred_at,
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# compliance_index / sla_compliance_pct (CommitteeReport finalize)
# ---------------------------------------------------------------------------

TIER_LOW_WEIGHT = 10
TIER_MID_WEIGHT = 20
TIER_HIGH_WEIGHT = 35


def _tier_weight(share):
    """share is an exact Fraction."""
    if share < Fraction(1, 5):
        return TIER_LOW_WEIGHT
    if share < Fraction(1, 2):
        return TIER_MID_WEIGHT
    return TIER_HIGH_WEIGHT


def compliance_index(c1, c2, c3):
    """c1 overdue plans (not VERIFIED), c2 pending triage before period_end,
    c3 open/acknowledged escalations. Shares are exact rationals."""
    total = c1 + c2 + c3
    if total == 0:
        return Decimal("100.0")
    weights = sum(_tier_weight(Fraction(c, total)) for c in (c1, c2, c3))
    index = max(0, 100 - weights)
    return Decimal(index).quantize(_TENTH, rounding=ROUND_HALF_UP)


def sla_compliance_pct(on_time, total_in_window):
    if total_in_window == 0:
        return Decimal("100.0")
    return (Decimal(100) * Decimal(on_time) / Decimal(total_in_window)).quantize(
        _TENTH, rounding=ROUND_HALF_UP)
