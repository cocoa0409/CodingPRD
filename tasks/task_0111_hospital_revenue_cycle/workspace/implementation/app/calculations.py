"""Calculation rules per SCAFFOLD §1.3 and PRD §3.5, §3.6, §3.7, §3.8.

All arithmetic operates on integer cents. The single rounding step is in the
coinsurance bucket of the patient-responsibility waterfall (round_half_up).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .clock import days_between_floor, now_dt, parse_iso
from .store import bump_version, get_store


BPS_DIVISOR = 10000
PATIENT_RESPONSIBILITY_DENIAL_CODES = {"PR-1", "PR-2", "PR-3"}
MIN_DAYS_SINCE_BILLED = 90


# ---------------------------------------------------------------------------
# Charge total aggregation
# ---------------------------------------------------------------------------
def charge_total_aggregation(encounter_id: str) -> int:
    """SUM(ChargeItem.amount_cents) for POSTED charges of this encounter.

    PENDING and VOIDED items are excluded.
    """
    store = get_store()
    total = 0
    for charge in store.charges.values():
        if charge["encounter_id"] != encounter_id:
            continue
        if charge["status"] != "POSTED":
            continue
        total += int(charge["amount_cents"])
    return total


# ---------------------------------------------------------------------------
# Patient-responsibility waterfall
# ---------------------------------------------------------------------------
def _round_half_up_cents(raw: Decimal) -> int:
    """Round a Decimal cents value to the nearest whole cent, half-up, once."""
    rounded = raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(rounded)


def patient_responsibility_waterfall(
    billable_cents: int,
    policy: dict[str, Any],
) -> dict[str, int]:
    """Run the deductible / coinsurance / OOP waterfall on `billable_cents`.

    Returns a dict with keys:
      - deductible_portion: cents that fell into the deductible bucket (Step 1)
      - coinsurance_portion: cents that fell into the coinsurance bucket (Step 2)
      - member_uncapped: deductible + coinsurance (Step 3)
      - member_payable: capped against OOP remaining (Step 4)
      - starting_deductible_met: snapshot read at start
      - starting_oop_accumulated: snapshot read at start
    """
    D = int(policy["deductible_cents"])
    DM = int(policy["deductible_met_cents"])
    C = int(policy["coinsurance_rate_bps"])
    M = int(policy["oop_max_cents"])
    OOP = int(policy["oop_accumulated_cents"])

    billable = max(0, int(billable_cents))

    # Step 1 — Deductible bucket.
    deductible_remaining = max(0, D - DM)
    deductible_portion = min(billable, deductible_remaining)

    # Step 2 — Coinsurance bucket.
    post_deductible = billable - deductible_portion
    # raw = post_deductible * C / 10000, rounded half-up to integer cents ONCE.
    raw = Decimal(post_deductible) * Decimal(C) / Decimal(BPS_DIVISOR)
    coinsurance_portion = _round_half_up_cents(raw)

    # Step 3 — Uncapped member side.
    member_uncapped = deductible_portion + coinsurance_portion

    # Step 4 — OOP cap.
    oop_remaining = max(0, M - OOP)
    member_payable = min(member_uncapped, oop_remaining)

    return {
        "deductible_portion": deductible_portion,
        "coinsurance_portion": coinsurance_portion,
        "member_uncapped": member_uncapped,
        "member_payable": member_payable,
        "starting_deductible_met": DM,
        "starting_oop_accumulated": OOP,
    }


def run_estimate(encounter: dict[str, Any]) -> None:
    """patient_responsibility_calc variant 'estimate'.

    billable = Encounter.total_charges_cents. Writes
    Encounter.estimated_patient_responsibility_cents. Does NOT touch policy
    accumulators. Bumps Encounter version & updated_at.
    """
    store = get_store()
    policy = store.policies.get(encounter["policy_id"])
    if policy is None:
        # No policy: estimate stays at 0.
        encounter["estimated_patient_responsibility_cents"] = 0
        bump_version(encounter)
        return
    result = patient_responsibility_waterfall(
        int(encounter.get("total_charges_cents", 0)),
        policy,
    )
    encounter["estimated_patient_responsibility_cents"] = result["member_payable"]
    bump_version(encounter)


def refresh_total_and_estimate(encounter: dict[str, Any]) -> None:
    """Re-run charge_total_aggregation and then estimate variant.

    The PRD describes these as two distinct refreshes; each is its own
    mutation of the encounter. We bump the version twice — once for the
    aggregation refresh and once for the estimate refresh — to faithfully
    model PRD §2.9 ("Each calculation re-derivation is itself a mutation").
    """
    encounter["total_charges_cents"] = charge_total_aggregation(encounter["id"])
    bump_version(encounter)
    run_estimate(encounter)


# ---------------------------------------------------------------------------
# Payer clearance + final patient responsibility
# ---------------------------------------------------------------------------
def run_clearance_and_final(
    encounter: dict[str, Any],
    decision: dict[str, Any],
) -> None:
    """Apply payer_clearance_calc + patient_responsibility_calc 'final'.

    Side effects:
      - Writes Encounter.payer_responsibility_cents and patient_responsibility_cents.
      - Increments policy.deductible_met_cents and oop_accumulated_cents
        (clamped to caps).
      - Bumps Encounter version & updated_at.

    Handles the patient-responsibility denial-code bypass (PR-1/PR-2/PR-3):
    when DENIED with such a code, the entire total_charges_cents flows into
    patient_responsibility_cents bypassing the waterfall.
    """
    store = get_store()
    policy = store.policies[encounter["policy_id"]]
    allowed = int(decision["allowed_amount_cents"])
    total_charges = int(encounter.get("total_charges_cents", 0))
    decision_kind = decision["decision"]
    reason_code = decision.get("denial_reason_code")

    is_patient_resp_denial = (
        decision_kind == "DENIED"
        and reason_code in PATIENT_RESPONSIBILITY_DENIAL_CODES
    )

    if is_patient_resp_denial:
        # Bypass waterfall: entire total_charges flows to patient.
        # Per scaffold formula: "unallowed cents are not billed to the patient
        # UNLESS denial_reason_code is in {PR-1,PR-2,PR-3}, in which case
        # unallowed_cents flows into patient_responsibility_cents in full
        # (not subject to deductible/coinsurance/OOP — bypass the waterfall)".
        # For a DENIED decision allowed is 0, so unallowed == total_charges.
        unallowed = total_charges - allowed
        encounter["payer_responsibility_cents"] = 0
        encounter["patient_responsibility_cents"] = unallowed
        # Accumulators NOT touched in the bypass branch (it skips the waterfall).
    elif decision_kind == "DENIED":
        # Plain DENIED with non-PR reason: contractual write-down, patient owes 0.
        encounter["payer_responsibility_cents"] = 0
        encounter["patient_responsibility_cents"] = 0
        # Accumulators not touched (waterfall did not run on the allowed amount).
    else:
        # APPROVED or PARTIAL: run waterfall against allowed amount.
        result = patient_responsibility_waterfall(allowed, policy)
        member_payable = result["member_payable"]
        encounter["patient_responsibility_cents"] = member_payable
        encounter["payer_responsibility_cents"] = allowed - member_payable

        # Update accumulators (clamped to caps).
        new_dm = int(policy["deductible_met_cents"]) + result["deductible_portion"]
        new_dm = min(new_dm, int(policy["deductible_cents"]))
        policy["deductible_met_cents"] = new_dm

        new_oop = int(policy["oop_accumulated_cents"]) + member_payable
        new_oop = min(new_oop, int(policy["oop_max_cents"]))
        policy["oop_accumulated_cents"] = new_oop

        bump_version(policy)

    bump_version(encounter)


# ---------------------------------------------------------------------------
# Outstanding balance & overpayment
# ---------------------------------------------------------------------------
def outstanding_balance_calc(encounter: dict[str, Any]) -> dict[str, int]:
    """Chronological walk of PatientPayments against patient_responsibility_cents.

    Returns dict with keys: outstanding_balance_cents, overpayment_cents.
    """
    store = get_store()
    running = int(encounter.get("patient_responsibility_cents", 0))
    payments = [
        p for p in store.payments.values()
        if p["encounter_id"] == encounter["id"]
    ]
    # Sort by (posted_at ASC, id ASC) — parse posted_at as ISO timestamp.
    payments.sort(key=lambda p: (p["posted_at"], p["id"]))
    for p in payments:
        amt = int(p["amount_cents"])
        if p["method"] == "REFUND":
            running += amt
        else:
            running -= amt
    if running < 0:
        return {"outstanding_balance_cents": 0, "overpayment_cents": -running}
    return {"outstanding_balance_cents": running, "overpayment_cents": 0}


# ---------------------------------------------------------------------------
# Bad debt write-off helper
# ---------------------------------------------------------------------------
def days_since_billed(encounter: dict[str, Any]) -> int:
    billed_at = encounter.get("billed_at")
    if not billed_at:
        return 0
    billed_dt = parse_iso(billed_at)
    return days_between_floor(now_dt(), billed_dt)
