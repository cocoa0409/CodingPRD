"""SLA clock arithmetic and calculations (PRD §2.8, §2.9, §3.2, §3.4, §3.6)."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store

RESOLVE_REOPEN_PENALTY_MINUTES = 60
REOPEN_WINDOW_MINUTES = 1440  # 24h
CSAT_WINDOW_MINUTES = 2880  # 48h
REJECT_VETO_THRESHOLD = 1

PRIORITY_WEIGHT = {"P1": 8, "P2": 4, "P3": 2, "P4": 1}


def _mult(policy, priority):
    pm = policy.get("priority_multipliers") or {}
    return pm.get(priority)


def _ceil_minutes(base, mult):
    """ceil(base * mult) to whole minutes. mult may be int/float/decimal-like."""
    product = Decimal(str(base)) * Decimal(str(mult))
    return int(math.ceil(product))


def whole_minutes_between(later, earlier):
    """Floor of elapsed minutes between two datetimes (PRD §2.8)."""
    delta = (later - earlier).total_seconds()
    return int(delta // 60)


def compute_due_dates_provisional(ticket, policy):
    """Provisional variant at open (PRD §3.2 / calc sla_due_dates)."""
    priority = ticket["priority"]
    mult = _mult(policy, priority)
    eff_response = _ceil_minutes(policy["response_target_minutes"], mult)
    eff_resolve = _ceil_minutes(policy["resolve_target_minutes"], mult)
    opened_at = ticket["opened_at"]
    ticket["response_due_at"] = opened_at + timedelta(minutes=eff_response)
    ticket["resolve_due_at"] = opened_at + timedelta(minutes=eff_resolve)


def recompute_due_dates_final(ticket, policy):
    """Final variant on reprioritize (PRD §3.3 / calc sla_due_dates final).

    Re-derive both windows from the NEW priority but anchor on the ORIGINAL
    opened_at, re-adding accumulated paused_total_minutes to resolve_due_at.
    response_due_at recomputed only if first response not yet recorded.
    """
    priority = ticket["priority"]
    mult = _mult(policy, priority)
    opened_at = ticket["opened_at"]

    # response_due_at: only if first response not yet recorded (response_due_at
    # is cleared to null at first response).
    if ticket.get("response_due_at") is not None:
        eff_response = _ceil_minutes(policy["response_target_minutes"], mult)
        ticket["response_due_at"] = opened_at + timedelta(minutes=eff_response)

    eff_resolve = _ceil_minutes(policy["resolve_target_minutes"], mult)
    reopen_penalty = RESOLVE_REOPEN_PENALTY_MINUTES * ticket.get("reopen_count", 0)
    effective = eff_resolve + ticket.get("paused_total_minutes", 0) + reopen_penalty
    ticket["resolve_due_at"] = opened_at + timedelta(minutes=effective)


def policy_for_ticket(ticket):
    cat = store.categories.get(ticket["category_id"])
    if cat is None:
        return None
    return store.sla_policies.get(cat.get("sla_policy_id"))


# --- group load score (PRD §3.9 / calc group_load_score) ---

def group_load_score(group_id):
    from services.common import LOAD_STATES

    DIVISOR = Decimal(3)
    terms = []
    count = 0
    for t in store.tickets.values():
        if t.get("assignment_group_id") != group_id:
            continue
        if t["lifecycle_state"] not in LOAD_STATES:
            continue
        count += 1
        w = Decimal(PRIORITY_WEIGHT[t["priority"]])
        breached = t.get("sla_state") in ("RESPONSE_BREACHED", "RESOLVE_BREACHED")
        breach_factor = Decimal("1.5") if breached else Decimal("1.0")
        term = (w * breach_factor / DIVISOR).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        terms.append(term)
    total = sum(terms, Decimal("0"))
    load_score = total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(load_score), count


# --- CSAT index (PRD §3.7 / calc csat_index) ---

def group_csat(group_id):
    """Returns dict with csat_index, avg_score, response_rate, eligible_count."""
    # Eligible surveys: counts_toward_index true AND ticket.assignment_group_id == group.
    eligible_scores = []
    for s in store.csat_surveys.values():
        if not s.get("counts_toward_index"):
            continue
        ticket = store.tickets.get(s["ticket_id"])
        if ticket is None:
            continue
        if ticket.get("assignment_group_id") != group_id:
            continue
        eligible_scores.append(s["score"])

    eligible_count = len(eligible_scores)

    # avg_score
    if eligible_count > 0:
        avg = Decimal(sum(eligible_scores)) / Decimal(eligible_count)
        avg_score = avg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        avg_score = Decimal("0.00")

    # response_rate denominator: resolved-or-closed tickets in group resolved
    # within the window (PRD §3.7 step 3).
    denom = 0
    now = store.now()
    for t in store.tickets.values():
        if t.get("assignment_group_id") != group_id:
            continue
        if t["lifecycle_state"] not in ("RESOLVED", "CLOSED"):
            continue
        resolved_at = t.get("resolved_at")
        if resolved_at is None:
            continue
        # "resolved within the window": resolved_at within CSAT_WINDOW_MINUTES of now.
        elapsed = whole_minutes_between(now, resolved_at)
        if elapsed <= CSAT_WINDOW_MINUTES:
            denom += 1

    if denom == 0:
        return {
            "csat_index": 0.0,
            "avg_score": float(avg_score),
            "response_rate": 0.0,
            "eligible_count": eligible_count,
        }

    response_rate = (Decimal(eligible_count) / Decimal(denom)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    csat_index = (avg_score * Decimal(20) * response_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return {
        "csat_index": float(csat_index),
        "avg_score": float(avg_score),
        "response_rate": float(response_rate),
        "eligible_count": eligible_count,
    }


# --- breach evaluation on clock advance (PRD §3.9 / §2.8) ---

def evaluate_breaches_on_advance():
    """Fire breach transitions for tickets whose due instant was just crossed.

    Returns list of ticket ids transitioned to a breached sla_state.
    """
    from services.common import touch

    now = store.now()
    breached = []
    for t in store.tickets.values():
        if t.get("sla_state") != "RUNNING":
            continue
        # response leg: still awaiting first response (response_due_at not null)
        if t.get("response_due_at") is not None and now > t["response_due_at"]:
            t["sla_state"] = "RESPONSE_BREACHED"
            touch(t)
            breached.append(t["id"])
            continue
        # resolve leg: still unresolved
        if t["lifecycle_state"] not in ("RESOLVED", "CLOSED", "CANCELLED"):
            rd = t.get("resolve_due_at")
            if rd is not None and now > rd:
                t["sla_state"] = "RESOLVE_BREACHED"
                touch(t)
                breached.append(t["id"])
    return breached
