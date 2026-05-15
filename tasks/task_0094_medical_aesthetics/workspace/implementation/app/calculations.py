"""Calculation rules per scaffold §1.3."""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .store import get_store


# ============================================================================
# customer_risk_score
# ============================================================================
def compute_customer_risk_score(customer: dict[str, Any]) -> float:
    hd = customer.get("health_declaration") or {}
    base = 0.0
    if hd.get("is_pregnant"):
        base += 30
    if hd.get("has_uncontrolled_hypertension"):
        base += 25
    if hd.get("has_active_infection"):
        base += 20
    if hd.get("has_bleeding_disorder"):
        base += 25
    base += 5 * len(customer.get("allergies") or [])
    base += 3 * len(customer.get("medication_history") or [])
    ae_count = int(customer.get("adverse_event_count") or 0)
    ae_factor = 1.0 + 0.25 * ae_count
    raw = Decimal(str(base)) * Decimal(str(ae_factor))
    # round half-up to 1 decimal
    rounded = raw.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    rounded_f = float(rounded)
    if rounded_f < 0.0:
        return 0.0
    if rounded_f > 100.0:
        return 100.0
    return rounded_f


# ============================================================================
# plan_total_provisional
# ============================================================================
def compute_plan_provisional_total(items: list[dict[str, Any]]) -> int:
    total = 0
    for item in items:
        project = get_store().projects.get(item["project_id"])
        if not project:
            # Caller should have validated; fail safe
            return 0
        tier = _find_tier(project, item["tier_code"])
        if not tier:
            return 0
        qty = int(item.get("quantity", 1) or 1)
        line = int(tier["base_price_cents"]) * qty
        total += line
    return total


def _find_tier(project: dict[str, Any], tier_code: str) -> dict[str, Any] | None:
    for t in project.get("pricing_tiers") or []:
        if t.get("tier_code") == tier_code:
            return t
    return None


# ============================================================================
# plan_total_final
# ============================================================================
def compute_plan_final_total(plan: dict[str, Any]) -> int:
    """Compute final total using current snapshot (project as of approval time).

    Pricing snapshotted via locked_project_versions; we use live project rows but
    treat them as the snapshot at the moment of computation. Promotional rate is
    500bps if items >= 3 else 0.
    """
    items = plan.get("items") or []
    promo_rate_bps = 500 if len(items) >= 3 else 0
    total = 0
    for item in items:
        project = get_store().projects.get(item["project_id"])
        if not project:
            continue
        tier = _find_tier(project, item["tier_code"])
        if not tier:
            continue
        qty = int(item.get("quantity", 1) or 1)
        line_gross = int(tier["base_price_cents"]) * qty
        line_discount = (line_gross * promo_rate_bps) // 10000  # floor div
        line_net = line_gross - line_discount
        total += line_net
    return total


# ============================================================================
# prep_lead_time
# ============================================================================
PREP_DRUG = 4
PREP_CONSUMABLE = 2
SURGICAL_PAD = 30
ROUNDING_STEP_MINUTES = 5


def _ceil_to_step(n: int, step: int) -> int:
    if n <= 0:
        return 0
    return ((n + step - 1) // step) * step


def compute_prep_lead_minutes(project: dict[str, Any]) -> int:
    per_sku = []
    for bom in project.get("bom") or []:
        sku = get_store().consumable_skus.get(bom["sku_id"])
        if not sku:
            continue
        per_unit = PREP_DRUG if sku.get("kind") == "DRUG" else PREP_CONSUMABLE
        raw = int(bom.get("quantity") or 0) * per_unit
        per_sku.append(_ceil_to_step(raw, ROUNDING_STEP_MINUTES))
    base_lead = max(per_sku) if per_sku else 0
    if project.get("category") == "SURGICAL":
        base_lead += SURGICAL_PAD
    return base_lead


# ============================================================================
# installment_schedule
# ============================================================================
TERM_APR_TABLE = {3: 0, 6: 600, 12: 1200, 24: 1800}
MIN_CREDIT_SCORE = {3: 500, 6: 600, 12: 700, 24: 750}
GRACE_DAYS = 7


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_installment_schedule(principal_cents: int, term_months: int, activated_at_dt) -> tuple[int, list[dict[str, Any]]]:
    """Return (apr_bps, schedule)."""
    apr_bps = TERM_APR_TABLE[term_months]
    schedule: list[dict[str, Any]] = []
    P = principal_cents
    n = term_months
    from .clock import add_months, format_iso

    if apr_bps == 0:
        # zero-APR: every interest 0; monthly_total = round_half_up(P/n), last absorbs residual
        monthly_total = _round_half_up(Decimal(P) / Decimal(n))
        balance = P
        for i in range(1, n + 1):
            if i < n:
                interest_cents = 0
                principal_cents_period = monthly_total
                if principal_cents_period > balance:
                    principal_cents_period = balance
            else:
                principal_cents_period = balance
                interest_cents = 0
            balance -= principal_cents_period
            due = add_months(activated_at_dt, i)
            schedule.append(
                {
                    "index": i,
                    "due_date": format_iso(due),
                    "principal_cents": principal_cents_period,
                    "interest_cents": interest_cents,
                    "total_cents": principal_cents_period + interest_cents,
                    "status": "PENDING",
                }
            )
        return apr_bps, schedule

    # Interest-bearing tiers
    monthly_rate = Decimal(apr_bps) / Decimal(10000) / Decimal(12)
    one_plus_r_n = (Decimal(1) + monthly_rate) ** n
    monthly_total = _round_half_up(
        Decimal(P) * monthly_rate * one_plus_r_n / (one_plus_r_n - Decimal(1))
    )

    balance = P
    for i in range(1, n + 1):
        if i < n:
            interest_cents = _round_half_up(Decimal(balance) * monthly_rate)
            principal_cents_period = monthly_total - interest_cents
            if principal_cents_period < 0:
                principal_cents_period = 0
            if principal_cents_period > balance:
                principal_cents_period = balance
            total_cents = principal_cents_period + interest_cents
        else:
            principal_cents_period = balance
            interest_cents = _round_half_up(Decimal(balance) * monthly_rate)
            total_cents = principal_cents_period + interest_cents
        balance -= principal_cents_period
        due = add_months(activated_at_dt, i)
        schedule.append(
            {
                "index": i,
                "due_date": format_iso(due),
                "principal_cents": principal_cents_period,
                "interest_cents": interest_cents,
                "total_cents": total_cents,
                "status": "PENDING",
            }
        )
    return apr_bps, schedule


# ============================================================================
# adverse_event_trigger
# ============================================================================
SEVERE_SYMPTOMS = {"INFECTION", "NECROSIS", "ANAPHYLAXIS"}
MODERATE_SYMPTOMS = {"PERSISTENT_PAIN", "SWELLING_BEYOND_NORMAL", "NUMBNESS"}


def map_feedback_to_ae_severity(feedback: dict[str, Any]) -> str | None:
    """Return None or severity string MINOR/MODERATE/SEVERE."""
    if not feedback:
        return None
    satisfaction = feedback.get("satisfaction")
    symptoms = feedback.get("symptoms") or []
    for s in symptoms:
        if s in SEVERE_SYMPTOMS:
            return "SEVERE"
    if satisfaction == 1:
        return "MODERATE"
    for s in symptoms:
        if s in MODERATE_SYMPTOMS:
            return "MODERATE"
    if satisfaction == 2:
        return "MINOR"
    return None
