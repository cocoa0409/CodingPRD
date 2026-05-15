"""All algorithmic calculations from SCAFFOLD §1.3."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..clock import floor_days_between, now_dt, parse_iso
from ..constants import (
    ABNORMAL_WINDOW_DAYS,
    CATEGORY_WEIGHT,
    CLOSE_DISTANCE,
    CLOSE_RAW_THRESHOLD,
    DURATION_CAP,
    DURATION_DENOM,
    EVENT_WEIGHT,
    EXPOSURE_WINDOW_DAYS,
    ISOLATION_MIN_DAYS,
    REQUIRED_NEGATIVE_TESTS,
    SLA_SOFT_OVERDUE_HOURS,
    TIER_HIGH_THRESHOLD,
    TIER_MEDIUM_THRESHOLD,
    TIER_WEIGHT,
    TIER_WINDOW_DAYS,
    W_ASYMPTOMATIC,
    W_CHAIN,
    W_CONFIRMED,
)
from ..store import get_store


def round_half_up_2(x: float) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- #
# case_density_risk_score
# --------------------------------------------------------------------------- #

def _persons_in_region(district_code: str) -> set[str]:
    store = get_store()
    return {pid for pid, p in store.persons.items() if p.get("district_code") == district_code}


def _connected_components(node_ids: set[str], edges: list[tuple[str, str]]) -> int:
    if not node_ids:
        return 0
    parent = {n: n for n in node_ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in edges:
        if a in parent and b in parent:
            union(a, b)
    roots = {find(n) for n in node_ids}
    return len(roots)


def compute_case_density_score(region: dict[str, Any]) -> tuple[float, str]:
    """Returns (final_score, tier) for a region.
    Tier mapping closed-interval, top-down:
      >= 50 -> HIGH
      >= 10 -> MEDIUM
      otherwise -> LOW
    """
    store = get_store()
    district = region.get("district_code")
    pop = int(region.get("population") or 0)
    if pop <= 0:
        return 0.0, "LOW"

    now = now_dt()
    window_start = now.replace() if False else None  # placeholder, used inline below

    # Window: reported_at in (now - TIER_WINDOW_DAYS, now]
    from datetime import timedelta
    start_ts = now - timedelta(days=TIER_WINDOW_DAYS)

    persons_in = _persons_in_region(district)

    confirmed_count = 0
    asymptomatic_count = 0
    case_person_ids: set[str] = set()
    for case in store.cases.values():
        if case.get("person_id") not in persons_in:
            continue
        if case.get("status") == "DEDUPLICATED":
            continue
        reported_at = parse_iso(case.get("reported_at")) if case.get("reported_at") else None
        if reported_at is None:
            continue
        # Reported within (now - TIER_WINDOW_DAYS, now]
        if not (start_ts < reported_at <= now):
            continue
        if case.get("status") in ("CONFIRMED", "UNDER_TRACING"):
            confirmed_count += 1
            case_person_ids.add(case["person_id"])
        if case.get("case_type") == "ASYMPTOMATIC":
            asymptomatic_count += 1
            case_person_ids.add(case["person_id"])

    # chain_count: distinct connected components of the ContactEvent
    # subgraph restricted to persons-with-a-case-in-window. Per PRD §3.6,
    # the subgraph's vertex set is only those case-persons who actually
    # appear in at least one in-window contact event — case-persons with
    # zero contact events contribute nothing to the chain count.
    candidate = case_person_ids & persons_in
    edges: list[tuple[str, str]] = []
    edge_nodes: set[str] = set()
    for ev in store.contact_events.values():
        try:
            et = parse_iso(ev.get("event_time"))
        except Exception:
            continue
        if et > now:
            continue
        s = ev.get("source_person_id")
        t = ev.get("target_person_id")
        if s in candidate and t in candidate:
            edges.append((s, t))
            edge_nodes.add(s)
            edge_nodes.add(t)
    chain_count = _connected_components(edge_nodes, edges)

    density = (confirmed_count * W_CONFIRMED + asymptomatic_count * W_ASYMPTOMATIC) / pop * 100000.0
    density = round_half_up_2(density)
    raw = density + chain_count * W_CHAIN
    score = round_half_up_2(raw)

    if score >= TIER_HIGH_THRESHOLD:
        tier = "HIGH"
    elif score >= TIER_MEDIUM_THRESHOLD:
        tier = "MEDIUM"
    else:
        tier = "LOW"
    return score, tier


# --------------------------------------------------------------------------- #
# contact_exposure_score
# --------------------------------------------------------------------------- #

def _event_raw_weight(event: dict[str, Any]) -> float:
    base = EVENT_WEIGHT.get(event.get("event_type"), 0)
    dist = float(event.get("distance_meters", 0) or 0)
    proximity = 1.0 if dist <= CLOSE_DISTANCE else 0.5
    dur = float(event.get("duration_minutes", 0) or 0)
    duration_factor = min(dur / DURATION_DENOM, DURATION_CAP)
    return base * proximity * duration_factor


def classify_tier(event: dict[str, Any]) -> str:
    """Compute the edge's tier given event fields. CLOSE if raw>=5.0 else SUB_CLOSE."""
    raw = _event_raw_weight(event)
    return "CLOSE" if raw >= CLOSE_RAW_THRESHOLD else "SUB_CLOSE"


def compute_exposure_score(person_id: str, projection: bool = False) -> float:
    """Replays ContactEvents targeting person_id in trailing EXPOSURE_WINDOW_DAYS."""
    from datetime import timedelta

    store = get_store()
    now = now_dt()
    start_ts = now - timedelta(days=EXPOSURE_WINDOW_DAYS)

    # Determine which source-person Cases are DEDUPLICATED — exclude those events.
    dedup_persons: set[str] = set()
    for c in store.cases.values():
        if c.get("status") == "DEDUPLICATED":
            dedup_persons.add(c.get("person_id"))

    relevant: list[tuple[Any, str, dict[str, Any]]] = []
    for ev in store.contact_events.values():
        if ev.get("target_person_id") != person_id:
            continue
        if ev.get("source_person_id") in dedup_persons:
            continue
        try:
            et = parse_iso(ev.get("event_time"))
        except Exception:
            continue
        if not (start_ts < et <= now):
            continue
        relevant.append((et, ev.get("id"), ev))

    relevant.sort(key=lambda triple: (triple[0], triple[1]))

    score = 0.0
    for et, _eid, ev in relevant:
        raw = _event_raw_weight(ev)
        days_since = floor_days_between(now, et)
        if projection and days_since <= 1:
            # Projection variant: treat events within trailing 1 day as days_since=0.
            days_since_used = 0
        else:
            days_since_used = days_since
        decay = max(0.0, 1.0 - days_since_used / EXPOSURE_WINDOW_DAYS)
        score += raw * decay

    return round_half_up_2(score)


# --------------------------------------------------------------------------- #
# isolation_release_eligibility
# --------------------------------------------------------------------------- #

def evaluate_release(isolation: dict[str, Any]) -> str:
    """Returns one of NOT_ELIGIBLE, EXTEND, RELEASE."""
    from datetime import timedelta

    store = get_store()
    now = now_dt()
    mode = isolation.get("mode")
    min_req = ISOLATION_MIN_DAYS.get(mode, 14)
    start_dt = parse_iso(isolation.get("start_date"))
    elapsed_days = floor_days_between(now, start_dt)
    if elapsed_days < min_req:
        return "NOT_ELIGIBLE"

    # Abnormal reports in trailing ABNORMAL_WINDOW_DAYS (relative to now)
    win_start = now - timedelta(days=ABNORMAL_WINDOW_DAYS)
    for rep in store.daily_reports.values():
        if rep.get("isolation_id") != isolation.get("id"):
            continue
        if not rep.get("is_abnormal"):
            continue
        try:
            rd = parse_iso(rep.get("report_date"))
        except Exception:
            continue
        if win_start < rd <= now:
            return "EXTEND"

    # Count of NEGATIVE PCR TestOrders for this person with collected_at > start_date
    person_id = isolation.get("person_id")
    negative_tests = []
    for to in store.test_orders.values():
        if to.get("person_id") != person_id:
            continue
        if to.get("status") != "RESULTED":
            continue
        if to.get("result") != "NEGATIVE":
            continue
        if to.get("test_type") != "PCR":
            continue
        collected = to.get("collected_at")
        if not collected:
            continue
        try:
            cdt = parse_iso(collected)
        except Exception:
            continue
        if cdt > start_dt:
            negative_tests.append(cdt)

    if len(negative_tests) < REQUIRED_NEGATIVE_TESTS:
        return "EXTEND"

    distinct_dates = {(d.year, d.month, d.day) for d in negative_tests}
    if len(distinct_dates) < REQUIRED_NEGATIVE_TESTS:
        return "EXTEND"

    return "RELEASE"


# --------------------------------------------------------------------------- #
# tracing_sla_breach
# --------------------------------------------------------------------------- #

def compute_sla_severity(task: dict[str, Any]) -> str:
    """Returns NONE, SOFT, or HARD."""
    if task.get("status") not in ("DISPATCHED", "IN_PROGRESS", "NEEDS_REVISION"):
        return "NONE"
    due_at = task.get("due_at")
    if not due_at:
        return "NONE"
    try:
        due_dt = parse_iso(due_at)
    except Exception:
        return "NONE"
    now = now_dt()
    if not (now > due_dt):
        return "NONE"
    hours_over = (now - due_dt).total_seconds() / 3600.0
    if hours_over <= SLA_SOFT_OVERDUE_HOURS:
        return "SOFT"
    return "HARD"


# --------------------------------------------------------------------------- #
# SupplyRequest priority_score
# --------------------------------------------------------------------------- #

def compute_priority_score(institution: dict[str, Any], item: dict[str, Any]) -> int:
    # Tier weight from institution's region.current_risk_tier
    store = get_store()
    district = institution.get("district_code") if institution else None
    tier = "LOW"
    if district:
        for r in store.regions.values():
            if r.get("district_code") == district:
                tier = r.get("current_risk_tier") or "LOW"
                break
    tier_w = TIER_WEIGHT.get(tier, 0)
    cat_w = CATEGORY_WEIGHT.get(item.get("category"), 0) if item else 0
    return tier_w + cat_w
