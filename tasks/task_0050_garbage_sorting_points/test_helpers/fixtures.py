"""Composite setup helpers for the Garbage Sorting Points test suite.

Most claims need the system in a state reached through 4-12 API calls
(community -> household -> resident -> verify -> point-rule -> activate ->
clock advance -> disposal commit -> ...). These helpers encapsulate the
preambles.

Identity threading (PRD §2.1):

  Resident is the only entity_backed role. PRD §2.1: 'When X-User-Role is
  Resident, X-User-ID is the id of the acting Resident entity; ownership
  checks on any resource that references a Resident compare the resource's
  resident_id foreign-key field to X-User-ID.'  Every Resident-issued call
  in this module uses make_resident_headers(resident['id']) with the real
  Resident.id — never the shared fallback.

  Disposal commits and redemption submits go through Resident headers
  threaded with the real Resident.id. Violation appeals likewise.

Setup helpers use get_success_data (lenient validator), so broken
preconditions surface as obvious 'Setup failed' rather than ambiguous
assertion failures.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    activate_point_rule_payload,
    advance_clock_payload,
    appeal_violation_payload,
    correct_disposal_payload,
    create_community_payload,
    create_disposal_payload,
    create_household_payload,
    create_mall_item_payload,
    create_point_rule_payload,
    create_ranking_period_payload,
    create_resident_payload,
    create_violation_payload,
    decide_violation_payload,
    return_redemption_order_payload,
    submit_redemption_order_payload,
    unique_suffix,
    verify_resident_payload,
    void_disposal_payload,
)
from .test_users import (
    TEST_USERS,
    make_appeal_reviewer_headers,
    make_community_admin_headers,
    make_resident_headers,
    make_system_operator_headers,
)


# ===========================================================================
# Clock helpers
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Return ISO 8601 UTC with three fractional digits and 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def advance_clock(to_iso: str) -> Dict[str, Any]:
    """PRD §3.9: SystemOperator advances logical clock to `to`."""
    return get_success_data(
        api_client.advance_clock(to_iso, make_system_operator_headers()),
    )


def run_sweep() -> Dict[str, Any]:
    """PRD §3.9: SystemOperator runs the restriction-expiry sweep."""
    return get_success_data(
        api_client.run_sweep(make_system_operator_headers()),
    )


# ===========================================================================
# Bootstrap: Community -> Household -> Resident (verified)
# ===========================================================================
def create_community(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_community(
            create_community_payload(**overrides),
            make_system_operator_headers(),
        ),
    )


def create_household(community_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_household(
            community_id,
            create_household_payload(**overrides),
            make_community_admin_headers(),
        ),
    )


def create_resident(
    community_id: str, household_id: str, **overrides: Any,
) -> Dict[str, Any]:
    """Creates a PENDING/INACTIVE resident."""
    return get_success_data(
        api_client.create_resident(
            community_id, household_id,
            create_resident_payload(**overrides),
            make_community_admin_headers(),
        ),
    )


def verify_resident(
    community_id: str, household_id: str, resident_id: str,
    decision: str = "APPROVE",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.verify_resident(
            community_id, household_id, resident_id,
            verify_resident_payload(decision=decision),
            make_community_admin_headers(),
        ),
    )


def setup_verified_resident(
    community_overrides: Optional[Dict[str, Any]] = None,
    household_overrides: Optional[Dict[str, Any]] = None,
    resident_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create community + household + VERIFIED/ACTIVE resident.

    Returns (community, household, resident) where resident is the fresh
    server snapshot AFTER verification (so identity_status == VERIFIED,
    account_status == ACTIVE)."""
    community = create_community(**(community_overrides or {}))
    household = create_household(community["id"], **(household_overrides or {}))
    resident = create_resident(
        community["id"], household["id"], **(resident_overrides or {}),
    )
    verified = verify_resident(community["id"], household["id"], resident["id"])
    return community, household, verified


# ===========================================================================
# PointRule helpers
# ===========================================================================
def create_point_rule(
    community_id: str, **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_point_rule(
            community_id, create_point_rule_payload(**overrides),
            make_community_admin_headers(),
        ),
    )


def activate_point_rule(
    community_id: str, rule_id: str, activated_at: str,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.activate_point_rule(
            community_id, rule_id,
            activate_point_rule_payload(activated_at),
            make_community_admin_headers(),
        ),
    )


def retire_point_rule(community_id: str, rule_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.retire_point_rule(
            community_id, rule_id, make_community_admin_headers(),
        ),
    )


def setup_active_point_rule(
    community_id: str,
    activated_at_iso: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create + activate a PointRule. Caller must first advance clock to
    a time at or before `activated_at_iso` so backdating is not triggered."""
    rule = create_point_rule(community_id, **overrides)
    return activate_point_rule(community_id, rule["id"], activated_at_iso)


# ===========================================================================
# Disposal helpers
# ===========================================================================
def submit_disposal(
    community: Dict[str, Any], household: Dict[str, Any],
    resident: Dict[str, Any], disposal_time: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Submit a disposal as the resident — uses Resident.id for X-User-ID
    so ownership / household-membership checks pass.

    Ensures the server logical clock is at or after disposal_time so the
    PRD §3.3 'disposal_time at or before current logical clock' check
    passes (the clock can only advance forward, so this is idempotent)."""
    # Advance clock to disposal_time (no-op if clock is already past it).
    advance_clock(disposal_time)
    headers = make_resident_headers(resident["id"])
    payload = create_disposal_payload(
        resident_id=resident["id"], disposal_time=disposal_time,
        **overrides,
    )
    return get_success_data(
        api_client.create_disposal(
            community["id"], household["id"], payload, headers,
        ),
    )


def correct_disposal(
    community_id: str, household_id: str, disposal_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.correct_disposal(
            community_id, household_id, disposal_id,
            correct_disposal_payload(**overrides),
            make_community_admin_headers(),
        ),
    )


def void_disposal(
    community_id: str, household_id: str, disposal_id: str,
    reason: str = "Voided in setup",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.void_disposal(
            community_id, household_id, disposal_id,
            void_disposal_payload(reason),
            make_community_admin_headers(),
        ),
    )


# ===========================================================================
# Mall + Redemption helpers
# ===========================================================================
def create_mall_item(community_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_mall_item(
            community_id, create_mall_item_payload(**overrides),
            make_community_admin_headers(),
        ),
    )


def submit_redemption(
    community: Dict[str, Any], household: Dict[str, Any],
    resident: Dict[str, Any], item: Dict[str, Any],
    quantity: int = 1,
) -> Dict[str, Any]:
    headers = make_resident_headers(resident["id"])
    payload = submit_redemption_order_payload(
        mall_item_id=item["id"], household_id=household["id"],
        resident_id=resident["id"], quantity=quantity,
    )
    return get_success_data(
        api_client.submit_redemption_order(community["id"], payload, headers),
    )


def confirm_redemption(community_id: str, order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.confirm_redemption_order(
            community_id, order_id, make_community_admin_headers(),
        ),
    )


def fulfill_redemption(community_id: str, order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.fulfill_redemption_order(
            community_id, order_id, make_community_admin_headers(),
        ),
    )


def deliver_redemption(community_id: str, order_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.deliver_redemption_order(
            community_id, order_id, make_community_admin_headers(),
        ),
    )


def return_redemption(
    community_id: str, order_id: str, reason: str = "Damaged on arrival",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.return_redemption_order(
            community_id, order_id,
            return_redemption_order_payload(reason),
            make_community_admin_headers(),
        ),
    )


# ===========================================================================
# Violation helpers
# ===========================================================================
def record_violation(
    community_id: str, resident_id: str, occurred_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_violation(
            community_id,
            create_violation_payload(
                resident_id=resident_id, occurred_at=occurred_at, **overrides,
            ),
            make_community_admin_headers(),
        ),
    )


def appeal_violation(
    community_id: str, resident: Dict[str, Any], violation_id: str,
    reason: str = "I dispute this finding",
) -> Dict[str, Any]:
    headers = make_resident_headers(resident["id"])
    return get_success_data(
        api_client.appeal_violation(
            community_id, violation_id,
            appeal_violation_payload(reason), headers,
        ),
    )


def accept_review_violation(
    community_id: str, violation_id: str,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.accept_review_violation(
            community_id, violation_id, make_appeal_reviewer_headers(),
        ),
    )


def decide_violation(
    community_id: str, violation_id: str, decision: str,
    reason: str = "Reviewer decision",
) -> Dict[str, Any]:
    return get_success_data(
        api_client.decide_violation(
            community_id, violation_id,
            decide_violation_payload(decision=decision, reason=reason),
            make_appeal_reviewer_headers(),
        ),
    )


def walk_violation_to_upheld(
    community: Dict[str, Any], resident: Dict[str, Any], violation_id: str,
) -> Dict[str, Any]:
    """NEW -> APPEALED -> UNDER_REVIEW -> UPHELD."""
    appeal_violation(community["id"], resident, violation_id)
    accept_review_violation(community["id"], violation_id)
    return decide_violation(
        community["id"], violation_id, "UPHOLD", "Reviewer upheld in setup",
    )


def walk_violation_to_overturned(
    community: Dict[str, Any], resident: Dict[str, Any], violation_id: str,
) -> Dict[str, Any]:
    """NEW -> APPEALED -> UNDER_REVIEW -> OVERTURNED."""
    appeal_violation(community["id"], resident, violation_id)
    accept_review_violation(community["id"], violation_id)
    return decide_violation(
        community["id"], violation_id, "OVERTURN",
        "Reviewer overturned in setup",
    )


# ===========================================================================
# RankingPeriod helpers
# ===========================================================================
def create_ranking_period(
    community_id: str, granularity: str, dimension: str,
    window_start: str, window_end: str,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_ranking_period(
            community_id,
            create_ranking_period_payload(
                granularity=granularity, dimension=dimension,
                window_start=window_start, window_end=window_end,
            ),
            make_community_admin_headers(),
        ),
    )


def close_ranking_period(
    community_id: str, period_id: str,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_ranking_period(
            community_id, period_id, make_community_admin_headers(),
        ),
    )


def publish_ranking_period(
    community_id: str, period_id: str,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.publish_ranking_period(
            community_id, period_id, make_community_admin_headers(),
        ),
    )


# ===========================================================================
# Reads
# ===========================================================================
def fetch_community(community_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_community(community_id, make_community_admin_headers()),
    )


def fetch_household(community_id: str, household_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_household(
            community_id, household_id, make_community_admin_headers(),
        ),
    )


def fetch_resident(
    community_id: str, household_id: str, resident_id: str,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_resident(
            community_id, household_id, resident_id,
            make_community_admin_headers(),
        ),
    )


def fetch_disposal(
    community_id: str, household_id: str, disposal_id: str,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_disposal(
            community_id, household_id, disposal_id,
            make_community_admin_headers(),
        ),
    )


def fetch_violation(community_id: str, violation_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_violation(
            community_id, violation_id, make_community_admin_headers(),
        ),
    )


def fetch_redemption_order(
    community_id: str, order_id: str,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_redemption_order(
            community_id, order_id, make_community_admin_headers(),
        ),
    )


def fetch_ranking_period(community_id: str, period_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_ranking_period(
            community_id, period_id, make_community_admin_headers(),
        ),
    )


def list_points_txns(
    community_id: str, household_id: str,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    resp = api_client.list_points_transactions(
        community_id, household_id,
        make_community_admin_headers(), params=params,
    )
    body = resp.json()
    return body.get("data", [])


def list_audit_logs(
    community_id: str, params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    resp = api_client.list_audit_logs(
        community_id, make_community_admin_headers(), params=params,
    )
    body = resp.json()
    return body.get("data", [])


def list_violations(
    community_id: str, params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    resp = api_client.list_violations(
        community_id, make_community_admin_headers(), params=params,
    )
    body = resp.json()
    return body.get("data", [])


def get_effectiveness(community_id: str, rule_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_point_rule_effectiveness(
            community_id, rule_id, make_community_admin_headers(),
        ),
    )


# ===========================================================================
# COMPOSITE TIER — for difficulty-design recipes
# ===========================================================================
def setup_scoring_scenario(
    *,
    base_rate_per_kg: float = 10.00,
    daily_cap_points: int = 10000,
    bonus_consecutive_threshold_days: int = 99,
    bonus_consecutive_multiplier: float = 1.20,
    peak_period_start_hour: int = 0,
    peak_period_end_hour: int = 0,
    peak_period_bonus_flat: int = 5,
    category_bonus_flat: int = 0,
    category: str = "RECYCLABLE",
    rule_activated_at_iso: Optional[str] = None,
    advance_clock_to_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Full bootstrap to the point where a disposal can be submitted.

    Returns dict with keys: community, household, resident, rule.
    """
    bootstrap_t = rule_activated_at_iso or "2030-01-01T00:00:00.000Z"
    advance_clock(bootstrap_t)
    community, household, resident = setup_verified_resident()
    rule = setup_active_point_rule(
        community["id"], activated_at_iso=bootstrap_t,
        category=category,
        base_rate_per_kg=base_rate_per_kg,
        daily_cap_points=daily_cap_points,
        bonus_consecutive_threshold_days=bonus_consecutive_threshold_days,
        bonus_consecutive_multiplier=bonus_consecutive_multiplier,
        peak_period_start_hour=peak_period_start_hour,
        peak_period_end_hour=peak_period_end_hour,
        peak_period_bonus_flat=peak_period_bonus_flat,
        category_bonus_flat=category_bonus_flat,
    )
    if advance_clock_to_iso is not None:
        advance_clock(advance_clock_to_iso)
    return {
        "community": community,
        "household": household,
        "resident": resident,
        "rule": rule,
    }


def setup_with_daily_cap_burned(
    *,
    burn_amount: int = 150,
    daily_cap_points: int = 200,
    base_rate_per_kg: float = 10.00,
    scenario_date: str = "2030-01-01",
) -> Dict[str, Any]:
    """Create scenario, then 'burn' `burn_amount` points by submitting one
    soaker disposal so the cap headroom equals daily_cap_points - burn_amount.

    Used for cap-overflow tests. Returns the standard scenario dict.
    Caller can then submit a follow-up disposal that exercises the cap.
    The bootstrap clock is at scenario_date 00:00, then advanced to 08:30
    so the soaker disposal is in-bounds; rule has no peak bonus
    (peak hour window is 0..0 — empty).
    """
    bootstrap = f"{scenario_date}T00:00:00.000Z"
    after_advance = f"{scenario_date}T08:30:00.000Z"
    scenario = setup_scoring_scenario(
        base_rate_per_kg=base_rate_per_kg,
        daily_cap_points=daily_cap_points,
        bonus_consecutive_threshold_days=365,
        peak_period_start_hour=0,
        peak_period_end_hour=0,
        category_bonus_flat=0,
        rule_activated_at_iso=bootstrap,
        advance_clock_to_iso=after_advance,
    )
    # weight that yields raw=burn_amount: weight = burn_amount / base_rate
    weight = float(burn_amount) / float(base_rate_per_kg)
    submit_disposal(
        scenario["community"], scenario["household"], scenario["resident"],
        disposal_time=after_advance,
        scoring_method="MANUAL", accuracy_score=1.000,
        weight_kg=round(weight, 3),
    )
    return scenario


def setup_ranking_window(
    *,
    granularity: str = "WEEKLY",
    dimension: str = "HOUSEHOLD",
    window_start_iso: str = "2030-02-01T00:00:00.000Z",
    window_end_iso: str = "2030-02-08T00:00:00.000Z",
    base_rate_per_kg: float = 10.00,
    daily_cap_points: int = 10000,
) -> Dict[str, Any]:
    """Create scenario whose PointRule is active throughout the window, and
    a ranking period covering [start, end). Caller submits disposals then
    advances clock to window_end and closes."""
    bootstrap = "2030-01-31T00:00:00.000Z"
    scenario = setup_scoring_scenario(
        base_rate_per_kg=base_rate_per_kg,
        daily_cap_points=daily_cap_points,
        bonus_consecutive_threshold_days=365,
        peak_period_start_hour=0,
        peak_period_end_hour=0,
        rule_activated_at_iso=bootstrap,
        advance_clock_to_iso=window_start_iso,
    )
    period = create_ranking_period(
        scenario["community"]["id"], granularity, dimension,
        window_start_iso, window_end_iso,
    )
    scenario["period"] = period
    return scenario


def setup_violation_chain(
    *,
    violation_type: str = "MIS_SORTING",
    count: int = 3,
    first_occurred_at_iso: str = "2030-01-05T10:00:00.000Z",
    spacing_days: int = 1,
) -> Dict[str, Any]:
    """Create a verified resident and record `count` violations of the same
    type spaced `spacing_days` apart so the escalation tiers light up.

    Returns dict: community, household, resident, violations (list).
    """
    bootstrap = "2030-01-01T00:00:00.000Z"
    advance_clock(bootstrap)
    community, household, resident = setup_verified_resident()
    # Advance to first occurrence so occurred_at <= now()
    advance_clock(first_occurred_at_iso)
    violations: List[Dict[str, Any]] = []
    base_dt = datetime.fromisoformat(first_occurred_at_iso.replace("Z", "+00:00"))
    for i in range(count):
        when = base_dt + timedelta(days=spacing_days * i)
        when_iso = iso_z(when)
        # Keep clock at or after `when`
        advance_clock(when_iso)
        v = record_violation(
            community["id"], resident["id"], when_iso,
            violation_type=violation_type,
        )
        violations.append(v)
    return {
        "community": community,
        "household": household,
        "resident": resident,
        "violations": violations,
    }


__all__ = [
    "iso_z",
    "advance_clock",
    "run_sweep",
    "create_community",
    "create_household",
    "create_resident",
    "verify_resident",
    "setup_verified_resident",
    "create_point_rule",
    "activate_point_rule",
    "retire_point_rule",
    "setup_active_point_rule",
    "submit_disposal",
    "correct_disposal",
    "void_disposal",
    "create_mall_item",
    "submit_redemption",
    "confirm_redemption",
    "fulfill_redemption",
    "deliver_redemption",
    "return_redemption",
    "record_violation",
    "appeal_violation",
    "accept_review_violation",
    "decide_violation",
    "walk_violation_to_upheld",
    "walk_violation_to_overturned",
    "create_ranking_period",
    "close_ranking_period",
    "publish_ranking_period",
    "fetch_community",
    "fetch_household",
    "fetch_resident",
    "fetch_disposal",
    "fetch_violation",
    "fetch_redemption_order",
    "fetch_ranking_period",
    "list_points_txns",
    "list_audit_logs",
    "list_violations",
    "get_effectiveness",
    "setup_scoring_scenario",
    "setup_with_daily_cap_burned",
    "setup_ranking_window",
    "setup_violation_chain",
]
