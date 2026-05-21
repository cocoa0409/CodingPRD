"""Calculation rules — severity score, composite decision, cooling off,
criminal-record age cutoff, eligibility-posture aggregation.

All formulas follow the scaffold's `calculations` table verbatim.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from core.clock import (
    add_business_days,
    count_business_days_between,
    logical_now,
)
from core.store import store
from core.utils import parse_date, parse_iso


# ---------------------------------------------------------------------------
# Constants (mirror the scaffold's `constants` blocks)
# ---------------------------------------------------------------------------
INFRACTION_SCORE = 5
MISDEMEANOR_SCORE = 25
FELONY_SCORE = 70
LICENSE_SUSPENDED_BONUS = 20
EDUCATION_UNVERIFIED_PENALTY = 40

FEDERAL_CONSIDER_THRESHOLD = 15
FEDERAL_INELIGIBLE_FAIL_COUNT = 2
JURISDICTIONAL_AGGREGATE_CONSIDER = 30
JURISDICTIONAL_AGGREGATE_INELIGIBLE_BY_STATE = {
    "CA": 80,
    "NY": 75,
    "IL": 70,
    "TX": 60,
    "FL": 55,
    "MA": 80,
    "WA": 70,
}

FEDERAL_MIN_BUSINESS_DAYS = 5
ADVERSE_LOCK_WINDOW_DAYS = 365
DAYS_PER_YEAR = 365.25


# ---------------------------------------------------------------------------
# Criminal record age cutoff
# ---------------------------------------------------------------------------
def criminal_record_reportable(conviction_date_str: str, lookback_years: int) -> bool:
    """True when the conviction is within the jurisdiction's lookback window."""
    try:
        conv = parse_date(conviction_date_str)
    except Exception:
        try:
            conv = parse_iso(conviction_date_str)
        except Exception:
            # Malformed -> treat as not reportable (forces score 0).
            return False
    now = logical_now()
    age_seconds = (now - conv).total_seconds()
    age_years_exact = age_seconds / (DAYS_PER_YEAR * 86400)
    return age_years_exact <= float(lookback_years)


# ---------------------------------------------------------------------------
# verification_severity_score
# ---------------------------------------------------------------------------
def compute_severity_score(item: dict, candidate: dict) -> int:
    kind = item.get("kind")
    raw = item.get("raw_finding") or {}

    if kind == "CRIMINAL":
        sev = raw.get("severity")
        conv_date = raw.get("conviction_date")
        jur = store.jurisdiction_policies.get(candidate.get("residence_jurisdiction"))
        lookback = int(jur["criminal_lookback_years"]) if jur is not None else 0
        if not conv_date or not criminal_record_reportable(conv_date, lookback):
            base = 0
        else:
            base = {
                "INFRACTION": INFRACTION_SCORE,
                "MISDEMEANOR": MISDEMEANOR_SCORE,
                "FELONY": FELONY_SCORE,
            }.get(sev, 0)
        return min(base, 100)

    if kind == "MVR":
        v = int(raw.get("violations_3yr", 0) or 0)
        if v == 0:
            tier = 0
        elif v == 1:
            tier = 10
        elif v == 2:
            tier = 25
        else:
            tier = 50
        bonus = LICENSE_SUSPENDED_BONUS if raw.get("license_status") == "SUSPENDED" else 0
        return min(tier + bonus, 100)

    if kind == "EDUCATION":
        return 0 if bool(raw.get("claim_verified")) else EDUCATION_UNVERIFIED_PENALTY

    return 0


# ---------------------------------------------------------------------------
# adjudication_composite_decision (jurisdictional variant — canonical)
# ---------------------------------------------------------------------------
def compute_composite_decision(order: dict, candidate: dict) -> str:
    """Return PENDING / CLEAR / CONSIDER / INELIGIBLE for the order."""
    items = store.list_items_for_order(order["id"])
    contributing_states = {"RETURNED", "PASSED", "FAILED"}
    contributing = [i for i in items if i.get("status") in contributing_states]
    if not contributing or len(contributing) < len(items):
        # Not every item has reached a contributing terminal status yet.
        # If ANY item is still QUEUED/IN_PROGRESS/DISPUTED/REWORK_REQUIRED
        # then the decision is still PENDING.
        non_contributing = [
            i for i in items if i.get("status") not in contributing_states
        ]
        if non_contributing:
            return "PENDING"
    if not contributing:
        return "PENDING"

    aggregate = sum(int(i.get("severity_score", 0)) for i in contributing)
    state = candidate.get("residence_jurisdiction")
    ineligible_cut = JURISDICTIONAL_AGGREGATE_INELIGIBLE_BY_STATE.get(state, 80)

    if aggregate <= JURISDICTIONAL_AGGREGATE_CONSIDER:
        return "CLEAR"
    if aggregate < ineligible_cut:
        return "CONSIDER"
    return "INELIGIBLE"


# ---------------------------------------------------------------------------
# cooling_off_period
# ---------------------------------------------------------------------------
def compute_earliest_final_eligible_at(
    *,
    pre_adverse_sent_at_iso: str,
    waiting_period_business_days: int,
    pause_start_iso: Optional[str] = None,
) -> str:
    """Return ISO timestamp for ``earliest_final_eligible_at``.

    elapsed = business days strictly after pre_adverse_sent_at, up to
    either ``pause_start_iso`` (if set) or logical now.
    remaining = max(0, required - elapsed)
    eligible_at = add_business_days(logical_now, remaining)
    """
    from core.utils import format_iso

    required = max(FEDERAL_MIN_BUSINESS_DAYS, int(waiting_period_business_days))
    sent_at = parse_iso(pre_adverse_sent_at_iso)
    end = parse_iso(pause_start_iso) if pause_start_iso else logical_now()
    elapsed = count_business_days_between(sent_at, end)
    remaining = max(0, required - elapsed)
    if remaining == 0:
        return format_iso(logical_now())
    eligible = add_business_days(logical_now(), remaining)
    return format_iso(eligible)


# ---------------------------------------------------------------------------
# eligibility_posture_recompute
# ---------------------------------------------------------------------------
TERMINAL_ORDER_STATUSES = {"COMPLETED_CLEAR", "TERMINATED_ADVERSE", "CANCELLED"}


def recompute_eligibility_posture(candidate: dict) -> None:
    """Mutates candidate['eligibility_posture'] per the aggregation rule."""
    candidate_id = candidate["id"]
    orders = store.list_orders_for_candidate(candidate_id)

    open_orders = [o for o in orders if o.get("status") not in TERMINAL_ORDER_STATUSES]
    if open_orders:
        candidate["eligibility_posture"] = "UNDER_REVIEW"
        return

    # No open orders. Look for TERMINATED_ADVERSE with adverse_flow window.
    now = logical_now()
    lock_threshold = now - timedelta(days=ADVERSE_LOCK_WINDOW_DAYS)
    any_historical_adverse = False
    locked = False
    for o in orders:
        if o.get("status") != "TERMINATED_ADVERSE":
            continue
        any_historical_adverse = True
        flow = store.adverse_flow_for_order(o["id"])
        if flow is None:
            continue
        faa = flow.get("final_adverse_action_at")
        if not faa:
            continue
        try:
            faa_dt = parse_iso(faa)
        except Exception:
            continue
        # Within 365 days?
        if (now - faa_dt) <= timedelta(days=ADVERSE_LOCK_WINDOW_DAYS):
            locked = True

    if locked:
        candidate["eligibility_posture"] = "LOCKED"
    elif any_historical_adverse:
        candidate["eligibility_posture"] = "ADVERSE"
    else:
        candidate["eligibility_posture"] = "ELIGIBLE"
