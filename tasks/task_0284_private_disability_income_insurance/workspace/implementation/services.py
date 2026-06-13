"""Business logic: entity bumps, recompute/cascade engine, ledger conservation.

This module owns the cross-entity recompute that keeps benefit periods, the claim
ledger, and the policy's benefit_months_consumed consistent (PRD §2.10 conservation).
"""
from decimal import Decimal

import calc
from db import store, utc_now_iso


# ---------------------------------------------------------------------------
# Common system-field management (PRD §2.5)
# ---------------------------------------------------------------------------
def touch(entity: dict):
    """Mutation of a resource: refresh updated_at and increment version."""
    entity["updated_at"] = utc_now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Income-report resolution for residual factor
# ---------------------------------------------------------------------------
def reports_for_claim(claim_id: str):
    return [r for r in store.income_reports.values() if r["claim_id"] == claim_id]


def effective_income_report(claim_id: str, coverage_month: int):
    """The single non-superseded report with greatest effective_month <= coverage_month.

    Tie-break: earliest created_at (via creation seq), never by id.
    Returns the report dict or None.
    """
    candidates = [
        r for r in reports_for_claim(claim_id)
        if not r["is_superseded"] and r["effective_month"] <= coverage_month
    ]
    if not candidates:
        return None
    # greatest effective_month; tie-break earliest creation order.
    candidates.sort(key=lambda r: (r["effective_month"], -r["_seq"]))
    return candidates[-1]


def loss_ratio_for_coverage(claim: dict, coverage_month: int) -> Decimal:
    rep = effective_income_report(claim["id"], coverage_month)
    if rep is None:
        return Decimal("0.0000")
    return Decimal(str(rep["income_loss_ratio"]))


# ---------------------------------------------------------------------------
# Offset resolution
# ---------------------------------------------------------------------------
def effective_offset_cents(award: dict) -> int:
    """monthly_offset_cents while ESTIMATED; final while FINALIZED; 0 while VOID."""
    if award["status"] == "ESTIMATED":
        return award["monthly_offset_cents"]
    if award["status"] == "FINALIZED":
        return award["final_monthly_offset_cents"]
    return 0


def offsets_for_claim(claim_id: str):
    return [a for a in store.offset_awards.values() if a["claim_id"] == claim_id]


def offset_applied_for_month(claim_id: str, coverage_month: int, exclude_award_id=None) -> int:
    """Sum of effective offsets over non-VOID awards whose closed window contains the month.

    WORKERS_COMP summed before SSDI (deterministic order; final sum order-free).
    """
    awards = [
        a for a in offsets_for_claim(claim_id)
        if a["status"] != "VOID"
        and a["start_month"] <= coverage_month <= a["end_month"]
        and a["id"] != exclude_award_id
    ]
    order = {"WORKERS_COMP": 0, "SSDI": 1}
    awards.sort(key=lambda a: order.get(a["offset_source"], 99))
    return sum(effective_offset_cents(a) for a in awards)


# ---------------------------------------------------------------------------
# Benefit-period pricing
# ---------------------------------------------------------------------------
def compute_benefit_fraction(claim: dict, policy: dict, coverage_month: int) -> Decimal:
    R = loss_ratio_for_coverage(claim, coverage_month)
    return calc.residual_benefit_factor(
        claim["claimed_disability_type"], R,
        policy["occupation_definition"], coverage_month, claim["own_occ_expiry_month"],
    )


def price_period(bp: dict, claim: dict, policy: dict, exclude_award_id=None):
    """(Re)compute benefit_fraction, gross, offset_applied, net for an ACCRUED period.

    benefit_fraction is frozen at accrual time (it feeds benefit_months_consumed and
    must not silently change). offset_applied/net are recomputed against current offsets.
    """
    gross = calc.gross_benefit_cents(
        policy["monthly_benefit_cents"], policy["cola_rider"], policy["cola_annual_rate"],
        bp["coverage_month"], claim["elimination_satisfied_month"],
        Decimal(str(bp["benefit_fraction"])),
    )
    offset_applied = offset_applied_for_month(claim["id"], bp["coverage_month"], exclude_award_id)
    net = calc.net_benefit_cents(gross, offset_applied)
    bp["gross_benefit_cents"] = gross
    bp["offset_applied_cents"] = offset_applied
    bp["net_benefit_cents"] = net


# ---------------------------------------------------------------------------
# Ledger recompute (PRD §3.12)
# ---------------------------------------------------------------------------
def accrued_periods(claim_id: str):
    return [
        bp for bp in store.benefit_periods.values()
        if bp["claim_id"] == claim_id and bp["status"] == "ACCRUED"
    ]


def recompute_ledger_totals(claim_id: str):
    """Recompute total_gross_paid_cents / total_net_paid_cents from ACCRUED periods.

    overpayment_balance_cents is maintained incrementally elsewhere — not touched here.
    Ordered by coverage_month ASC then created_at (seq) ASC (never id).
    """
    ledger = store.claim_ledgers.get(claim_id)
    if ledger is None:
        return
    periods = accrued_periods(claim_id)
    periods.sort(key=lambda bp: (bp["coverage_month"], bp["_seq"]))
    total_gross = sum(bp["gross_benefit_cents"] for bp in periods)
    total_net = sum(bp["net_benefit_cents"] for bp in periods)
    changed = (
        ledger["total_gross_paid_cents"] != total_gross
        or ledger["total_net_paid_cents"] != total_net
    )
    ledger["total_gross_paid_cents"] = total_gross
    ledger["total_net_paid_cents"] = total_net
    if changed:
        touch(ledger)


# ---------------------------------------------------------------------------
# Policy benefit-months consumed (computed, conserved) (PRD §2.10)
# ---------------------------------------------------------------------------
def set_benefit_months_consumed(policy: dict, value: Decimal):
    rounded = calc.round4(value)
    # store as float for JSON; keep canonical 4dp via Decimal arithmetic.
    new_val = float(rounded)
    if policy["benefit_months_consumed"] != new_val:
        policy["benefit_months_consumed"] = new_val
        touch(policy)


def consumed_decimal(policy: dict) -> Decimal:
    return calc.round4(Decimal(str(policy["benefit_months_consumed"])))


def adjust_consumed(policy: dict, delta: Decimal):
    current = consumed_decimal(policy)
    set_benefit_months_consumed(policy, current + delta)


# ---------------------------------------------------------------------------
# Views (JSON serialization for each entity)
# ---------------------------------------------------------------------------
def insurer_view(e: dict) -> dict:
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"], "name": e["name"],
        "current_month_index": e["current_month_index"],
    }


def occupation_class_view(e: dict) -> dict:
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"], "insurer_id": e["insurer_id"], "code": e["code"],
        "risk_tier": e["risk_tier"], "max_benefit_months": e["max_benefit_months"],
        "min_elimination_days": e["min_elimination_days"],
        "own_occ_window_months_cap": e["own_occ_window_months_cap"],
    }


def policyholder_view(e: dict) -> dict:
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"], "insurer_id": e["insurer_id"], "full_name": e["full_name"],
        "pre_disability_monthly_income_cents": e["pre_disability_monthly_income_cents"],
    }


def policy_view(e: dict) -> dict:
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"], "insurer_id": e["insurer_id"],
        "policyholder_id": e["policyholder_id"], "occupation_class_id": e["occupation_class_id"],
        "monthly_benefit_cents": e["monthly_benefit_cents"],
        "benefit_period_months": e["benefit_period_months"],
        "elimination_period_days": e["elimination_period_days"],
        "occupation_definition": e["occupation_definition"],
        "own_occ_window_months": e["own_occ_window_months"],
        "cola_rider": e["cola_rider"], "cola_annual_rate": e["cola_annual_rate"],
        "lifecycle_status": e["lifecycle_status"], "premium_status": e["premium_status"],
        "benefit_months_consumed": e["benefit_months_consumed"],
    }


def claim_view(e: dict) -> dict:
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"], "insurer_id": e["insurer_id"], "policy_id": e["policy_id"],
        "disability_onset_month": e["disability_onset_month"],
        "claimed_disability_type": e["claimed_disability_type"],
        "elimination_satisfied_month": e["elimination_satisfied_month"],
        "own_occ_expiry_month": e["own_occ_expiry_month"],
        "next_proof_due_month": e["next_proof_due_month"],
        "status": e["status"],
    }


def income_report_view(e: dict) -> dict:
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"], "claim_id": e["claim_id"],
        "effective_month": e["effective_month"],
        "current_monthly_income_cents": e["current_monthly_income_cents"],
        "income_loss_ratio": e["income_loss_ratio"], "is_superseded": e["is_superseded"],
    }


def disability_proof_view(e: dict) -> dict:
    # Append-only attestation: only id + created_at (PRD §2.5). Surface the data fields.
    return {
        "id": e["id"], "created_at": e["created_at"], "claim_id": e["claim_id"],
        "attestation_month": e["attestation_month"], "still_disabled": e["still_disabled"],
        "accepted": e["accepted"],
    }


def benefit_period_view(e: dict) -> dict:
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"], "claim_id": e["claim_id"], "policy_id": e["policy_id"],
        "coverage_month": e["coverage_month"], "benefit_fraction": e["benefit_fraction"],
        "gross_benefit_cents": e["gross_benefit_cents"],
        "offset_applied_cents": e["offset_applied_cents"],
        "net_benefit_cents": e["net_benefit_cents"], "status": e["status"],
    }


def offset_award_view(e: dict) -> dict:
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"], "claim_id": e["claim_id"],
        "offset_source": e["offset_source"],
        "monthly_offset_cents": e["monthly_offset_cents"],
        "estimated_offset_cents": e["estimated_offset_cents"],
        "final_monthly_offset_cents": e["final_monthly_offset_cents"],
        "effective_offset_cents": effective_offset_cents(e),
        "start_month": e["start_month"], "end_month": e["end_month"],
        "status": e["status"],
    }


def claim_ledger_view(e: dict) -> dict:
    return {
        "id": e["id"], "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"], "claim_id": e["claim_id"],
        "total_gross_paid_cents": e["total_gross_paid_cents"],
        "total_net_paid_cents": e["total_net_paid_cents"],
        "overpayment_balance_cents": e["overpayment_balance_cents"],
    }
