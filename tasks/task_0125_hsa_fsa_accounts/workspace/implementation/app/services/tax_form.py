"""Tax-form recapture computation (SCAFFOLD §1.3 deduction_recapture)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from ..store import store
from .caps import HSA_PENALTY_RATE_BPS


def _round_half_up(value: Decimal) -> int:
    """Round half-up to a whole cent (integer)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _is_non_qualified_for_event(event: dict) -> bool:
    """Return True if a CLAIM_PAID event refers to a NON_QUALIFIED expense."""
    if event["event_type"] != "CLAIM_PAID":
        return False
    claim = store.claims.get(event["subject_id"])
    if claim is None:
        return False
    expense = store.qualified_expenses_by_code.get(claim["expense_code"])
    if expense is None:
        return False
    return expense["category"] == "NON_QUALIFIED"


def compute_chronological(plan_year_id: str, plan_year: dict) -> dict:
    """Replay audit events in (occurred_at, id) order maintaining a deductible accumulator."""
    cap_total = plan_year["contribution_cap_cents"] + plan_year["catch_up_cap_cents"]

    # All events for this plan year, sorted by (occurred_at, id).
    events = [ev for ev in store.audit_events if ev.get("plan_year_id") == plan_year_id]
    events.sort(key=lambda e: (e["occurred_at"], e["id"]))

    available_deductible = 0
    contributions_seen = 0
    recapture_cents = 0

    for ev in events:
        et = ev["event_type"]
        if et == "CONTRIBUTION_POSTED":
            delta = ev["cents_delta"]
            # Cap room remaining
            remaining_room = max(0, cap_total - contributions_seen)
            applied = min(delta, remaining_room)
            available_deductible += applied
            contributions_seen += delta
        elif et == "CONTRIBUTION_REVERSED":
            # Negative cents_delta (reversal). Symmetric handling: clamp current accumulators.
            delta = ev["cents_delta"]  # negative
            # Undo from contributions_seen and available_deductible — assume reversal undoes
            # an earlier counted contribution. We bound to >= 0.
            contributions_seen += delta
            if contributions_seen < 0:
                contributions_seen = 0
            # Reduce deductible by absolute reversed amount, clamped at 0.
            available_deductible = max(0, available_deductible + delta)
        elif et == "CLAIM_PAID" and _is_non_qualified_for_event(ev):
            abs_amt = abs(ev["cents_delta"])
            penalty = _round_half_up(Decimal(abs_amt) * Decimal(HSA_PENALTY_RATE_BPS) / Decimal(10_000))
            gross = abs_amt + penalty
            applied = min(gross, available_deductible)
            recapture_cents += applied
            available_deductible -= applied
        elif et == "CLAIM_REVERSED":
            # Undo a previously taken recapture if the underlying claim was non-qualified.
            claim = store.claims.get(ev["subject_id"])
            if claim is None:
                continue
            expense = store.qualified_expenses_by_code.get(claim["expense_code"])
            if expense is not None and expense["category"] == "NON_QUALIFIED":
                # Symmetric undo, bounded at 0.
                abs_amt = abs(ev["cents_delta"])
                penalty = _round_half_up(Decimal(abs_amt) * Decimal(HSA_PENALTY_RATE_BPS) / Decimal(10_000))
                gross = abs_amt + penalty
                undo = min(gross, recapture_cents)
                recapture_cents -= undo
                available_deductible += undo

    deductible_cents = available_deductible
    tax_basis_cents = deductible_cents - recapture_cents
    return {
        "deductible_cents": deductible_cents,
        "recapture_cents": recapture_cents,
        "tax_basis_cents": tax_basis_cents,
        "basis": "chronological",
    }


def compute_forward_looking(plan_year_id: str, plan_year: dict) -> dict:
    cap_total = plan_year["contribution_cap_cents"] + plan_year["catch_up_cap_cents"]
    deductible_cents = min(plan_year["contributions_ytd_cents"], cap_total)

    recapture_cents = 0
    for claim in store.claims.values():
        if claim.get("plan_year_id") != plan_year_id:
            continue
        if claim["status"] != "PAID":
            continue
        # Exclude twin reversed claims (reversed_from_id is set)
        if claim.get("reversed_from_id"):
            continue
        expense = store.qualified_expenses_by_code.get(claim["expense_code"])
        if expense is None or expense["category"] != "NON_QUALIFIED":
            continue
        paid = claim["paid_amount_cents"] or 0
        # paid_amount * 1.20, round half-up to whole cent
        amount = Decimal(paid) * (Decimal(1) + Decimal(HSA_PENALTY_RATE_BPS) / Decimal(10_000))
        recapture_cents += _round_half_up(amount)

    tax_basis_cents = deductible_cents - recapture_cents
    return {
        "deductible_cents": deductible_cents,
        "recapture_cents": recapture_cents,
        "tax_basis_cents": tax_basis_cents,
        "basis": "forward_looking",
    }
