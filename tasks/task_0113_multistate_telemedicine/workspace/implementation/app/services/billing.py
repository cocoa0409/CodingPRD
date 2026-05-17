"""Consult charge calculation, claim/invoice creation, and follow-up windowing."""
from datetime import timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.clock import clock
from app.errors import err_followup_window_empty
from app.store import store
from app.utils import round_half_up_to_cents


BASE_TIER_CENTS = {"BRIEF": 5000, "STANDARD": 10000, "EXTENDED": 18000}
SELF_PAY_DISCOUNT_BPS = 1500
# Follow-up windows
WINDOW_DAYS_II = 30
WINDOW_DAYS_III_TO_V = 60
WINDOW_DAYS_NONCONTROLLED = 90


def compute_base_charge_cents(visit_tier: str) -> int:
    return BASE_TIER_CENTS[visit_tier]


def compute_self_pay_breakdown(base_cents: int) -> Dict[str, int]:
    """Return {discount_cents, amount_due_cents, final_charge_cents}."""
    # discount = base * 0.15 rounded HALF_UP
    discount_decimal = (Decimal(base_cents) * Decimal(SELF_PAY_DISCOUNT_BPS)) / Decimal(10000)
    discount_cents = round_half_up_to_cents(discount_decimal)
    amount_due = base_cents - discount_cents
    return {
        "discount_cents": discount_cents,
        "amount_due_cents": amount_due,
        "final_charge_cents": amount_due,
    }


def compute_insurance_waterfall(
    base_cents: int,
    deductible_remaining_cents: int,
    copay_cents: int,
    coinsurance_bps: int,
) -> Dict[str, int]:
    """Three-step waterfall:
      step1 deductible_applied = min(base, deductible_remaining)
      step2 copay_applied = min(remaining_after_deductible, copay)
      step3 coinsurance_applied = round_half_up(remaining_after_copay * bps / 10000)
    """
    deductible_applied = min(base_cents, max(0, deductible_remaining_cents))
    remaining_after_deductible = base_cents - deductible_applied

    copay_applied = min(remaining_after_deductible, max(0, copay_cents))
    remaining_after_copay = remaining_after_deductible - copay_applied

    coinsurance_decimal = (
        Decimal(remaining_after_copay) * Decimal(max(0, coinsurance_bps))
    ) / Decimal(10000)
    coinsurance_applied = round_half_up_to_cents(coinsurance_decimal)

    patient_responsibility = deductible_applied + copay_applied + coinsurance_applied
    payer_paid = base_cents - patient_responsibility
    if payer_paid < 0:
        payer_paid = 0
    return {
        "billed_cents": base_cents,
        "deductible_applied_cents": deductible_applied,
        "copay_applied_cents": copay_applied,
        "coinsurance_applied_cents": coinsurance_applied,
        "patient_responsibility_cents": patient_responsibility,
        "final_charge_cents": patient_responsibility,
        "expected_payer_paid_cents": payer_paid,
    }


def create_self_pay_invoice(consult_id: str, base_cents: int, now_iso: str) -> Dict[str, Any]:
    breakdown = compute_self_pay_breakdown(base_cents)
    invoice = {
        "id": store.new_id(),
        "consult_id": consult_id,
        "subtotal_cents": base_cents,
        "discount_cents": breakdown["discount_cents"],
        "amount_due_cents": breakdown["amount_due_cents"],
        "status": "ISSUED",
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    store.invoices[invoice["id"]] = invoice
    return invoice


def create_insurance_claim(
    consult_id: str, base_cents: int, patient: Dict[str, Any], now_iso: str
) -> Dict[str, Any]:
    waterfall = compute_insurance_waterfall(
        base_cents=base_cents,
        deductible_remaining_cents=int(patient.get("insurance_deductible_remaining_cents", 0)),
        copay_cents=int(patient.get("insurance_copay_cents", 0)),
        coinsurance_bps=int(patient.get("insurance_coinsurance_bps", 0)),
    )
    claim = {
        "id": store.new_id(),
        "consult_id": consult_id,
        "billed_cents": waterfall["billed_cents"],
        "deductible_applied_cents": waterfall["deductible_applied_cents"],
        "copay_applied_cents": waterfall["copay_applied_cents"],
        "coinsurance_applied_cents": waterfall["coinsurance_applied_cents"],
        "payer_paid_cents": 0,
        "patient_responsibility_cents": waterfall["patient_responsibility_cents"],
        "status": "SUBMITTED",
        "denial_reason": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    store.claims[claim["id"]] = claim
    return claim


def _max_schedule_for_consult(consult_id: str) -> str:
    """Return the highest-precedence DEA schedule among qualifying prescriptions
    under this consult (status IN ISSUED/TRANSMITTED/DISPENSED).
    Precedence II > III > IV > V > NONE.
    """
    order = ["II", "III", "IV", "V", "NONE"]
    found = set()  # set of dea_schedule values
    for rx in store.prescriptions.values():
        if rx.get("consult_id") != consult_id:
            continue
        if rx.get("status") not in {"ISSUED", "TRANSMITTED", "DISPENSED"}:
            continue
        found.add(rx.get("dea_schedule", "NONE"))
    if not found:
        return "NONE"
    for s in order:
        if s in found:
            return s
    return "NONE"


def compute_followup_window_days(consult_id: str) -> int:
    max_sched = _max_schedule_for_consult(consult_id)
    if max_sched == "II":
        return WINDOW_DAYS_II
    if max_sched in ("III", "IV", "V"):
        return WINDOW_DAYS_III_TO_V
    return WINDOW_DAYS_NONCONTROLLED


def create_followup(consult_id: str, now_iso: str) -> Dict[str, Any]:
    days = compute_followup_window_days(consult_id)
    now_dt = clock.now()
    due_by_dt = now_dt + timedelta(days=days)
    if not (due_by_dt > now_dt):
        # Defensive guard from §1.4 priority 12.
        raise err_followup_window_empty()
    due_by_iso = due_by_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{due_by_dt.microsecond // 1000:03d}Z"
    fu = {
        "id": store.new_id(),
        "consult_id": consult_id,
        "due_by": due_by_iso,
        "status": "SCHEDULED",
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    store.followups[fu["id"]] = fu
    return fu
