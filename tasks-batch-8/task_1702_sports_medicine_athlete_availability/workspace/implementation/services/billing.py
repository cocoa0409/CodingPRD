"""Claim adjudication calculation (pinned evaluation order)."""
from decimal import Decimal, ROUND_HALF_UP

from db import touch, logical_now_iso


def adjudicate_claim(claim, policy, deny):
    """Runs claim_adjudication against CURRENT policy accumulators.
    Mutates claim and (on non-denial) policy. Returns final claim status."""
    claim["adjudicated_at"] = logical_now_iso()

    if deny:
        # Denial: zeros; policy accumulators unchanged
        claim["payer_paid_cents"] = 0
        claim["patient_resp_cents"] = 0
        claim["deductible_applied_cents"] = 0
        touch(claim)
        return "DENIED"

    allowed = claim["billed_amount_cents"]
    remaining_deductible = max(0, policy["deductible_cents"] - policy["deductible_met_cents"])
    deductible_applied = min(allowed, remaining_deductible)
    after_deductible = allowed - deductible_applied
    patient_coins = int(
        (Decimal(after_deductible * (100 - policy["coinsurance_pct"])) / Decimal(100))
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    patient_resp_pre_cap = deductible_applied + patient_coins
    remaining_oop = max(0, policy["oop_max_cents"] - policy["oop_accrued_cents"])
    patient_resp = min(patient_resp_pre_cap, remaining_oop)
    payer_paid = allowed - patient_resp
    credited_deductible = min(deductible_applied, patient_resp)

    claim["payer_paid_cents"] = payer_paid
    claim["patient_resp_cents"] = patient_resp
    claim["deductible_applied_cents"] = deductible_applied
    touch(claim)

    policy["deductible_met_cents"] += credited_deductible
    policy["oop_accrued_cents"] += patient_resp
    if policy["oop_accrued_cents"] >= policy["oop_max_cents"]:
        policy["status"] = "EXHAUSTED"
    touch(policy)

    return "PAID"
