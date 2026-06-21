"""Business-logic services: computed-field recomputation, calculations,
ledger movements, and cross-entity recompute helpers.

Stored ledger fields (payout_balance_cents, clawback_owed_cents,
wallet_balance_cents) are mutated explicitly by the workflows that move money,
because the settlement-reversal waterfall reads a balance before mutating it
(PRD 3.9.1). Aggregate computed fields (held_balance_cents,
lifetime_net_earnings_cents, reliability_score, counts) are recomputed from the
authoritative collections so no incremental drift accumulates (PRD 3.10).
"""
import db
from common import touch, round_half_up, round_half_up_1dp


# ===========================================================================
# Tutor computed fields
# ===========================================================================
def recompute_tutor_lifetime_and_reliability(tutor):
    """lifetime_net_earnings_cents (PRD 3.2 / scaffold) + reliability_score (PRD 3.10).

    lifetime_net_earnings_cents = sum of tutor_net_cents across this tutor's
    SETTLED settlements.
    reliability_score recomputed in full from sessions/bookings/refund-cases.
    """
    tid = tutor["id"]
    lifetime = sum(
        s["tutor_net_cents"] for s in db.settlements.values()
        if s["tutor_id"] == tid and s["status"] == "SETTLED"
    )
    tutor["lifetime_net_earnings_cents"] = lifetime

    confirmed_sessions = sum(
        1 for s in db.sessions.values()
        if s["tutor_id"] == tid and s["delivery_status"] == "CONFIRMED"
    )
    no_show_count = sum(
        1 for b in db.bookings.values()
        if b["tutor_id"] == tid and b["status"] == "NO_SHOW"
    )
    arbitrated_refund_count = sum(
        1 for r in db.refund_cases.values()
        if r["tutor_id"] == tid and r["status"] == "RESOLVED_REFUND"
        and r.get("_resolved_via_arbitration") is True
    )

    chronic = 100.0 * confirmed_sessions / max(1, confirmed_sessions + no_show_count)
    acute_penalty = 8 * no_show_count + 12 * arbitrated_refund_count
    score = chronic - acute_penalty
    if score < 0:
        score = 0.0
    if score > 100:
        score = 100.0
    tutor["reliability_score"] = round_half_up_1dp(score)


def recompute_tutor_derived(tutor):
    """active_subject_count and is_payable (PRD 3.2)."""
    tid = tutor["id"]
    tutor["active_subject_count"] = sum(
        1 for t in db.subject_tags.values()
        if t["tutor_id"] == tid and t["status"] == "APPROVED"
    )
    tutor["is_payable"] = (
        tutor["verification_status"] == "VERIFIED"
        and tutor["clawback_owed_cents"] == 0
    )


# ===========================================================================
# Parent account computed fields (PRD 2.9, 3.4)
# ===========================================================================
def recompute_parent_balances(parent):
    """held_balance_cents, available_balance_cents, child_count.

    wallet_balance_cents is a stored ledger field (deposits add, settlement
    debits subtract, refund credits add).
    """
    pid = parent["id"]
    held = sum(
        b["hold_amount_cents"] for b in db.bookings.values()
        if b["parent_account_id"] == pid
        and b["status"] in ("SCHEDULED", "RESCHEDULE_REQUESTED", "DELIVERED")
    )
    parent["held_balance_cents"] = held
    available = parent["wallet_balance_cents"] - held
    if available < 0:
        available = 0
    parent["available_balance_cents"] = available
    parent["child_count"] = sum(
        1 for s in db.students.values()
        if s["parent_account_id"] == pid and s["status"] != "ARCHIVED"
    )


# ===========================================================================
# Calculations
# ===========================================================================
OVERTIME_GRACE_MINUTES = 15
FLOOR_MINUTES = 1
STUDENT_GAP_MINUTES = 15


def compute_hold_amount(quoted_rate_cents, planned_minutes, is_trial, trial_max_billed_minutes):
    """wallet_hold_amount calc (PRD 3.5 / scaffold)."""
    if is_trial:
        minutes = min(planned_minutes, trial_max_billed_minutes)
        return round_half_up(quoted_rate_cents * minutes, 60)
    return round_half_up(quoted_rate_cents * planned_minutes, 60)


def compute_billed_minutes(actual_minutes, planned_minutes, is_trial, trial_max_billed_minutes):
    """billed_minutes calc (PRD 3.7 / scaffold)."""
    capped = min(actual_minutes, planned_minutes + OVERTIME_GRACE_MINUTES)
    if is_trial:
        billed = min(capped, trial_max_billed_minutes)
    else:
        billed = capped
    if billed < FLOOR_MINUTES:
        billed = FLOOR_MINUTES
    return billed


def select_commission_bps_standard(policy, lifetime_net_earnings_cents):
    """Tier selection (PRD 3.8): largest index i with breakpoint[i] <= lifetime."""
    breakpoints = policy["tier_breakpoints_cents"]
    rates = policy["tier_rates_bps"]
    idx = 0
    for i, bp in enumerate(breakpoints):
        if bp <= lifetime_net_earnings_cents:
            idx = i
        else:
            break
    return rates[idx]


# ===========================================================================
# Active commission policy lookup
# ===========================================================================
def active_policy():
    for p in db.commission_policies.values():
        if p["status"] == "ACTIVE":
            return p
    return None
