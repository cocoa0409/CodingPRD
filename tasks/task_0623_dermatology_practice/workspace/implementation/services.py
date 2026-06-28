"""Cross-cutting business logic: derived-field reconciliation, calculations,
cascades, and recall spawning.

Every behavior traces to a verbatim PRD sentence; section references are noted.
"""
import clock
import db
import helpers

# --- calculation constants (scaffold §1.3) ---
CASH_PROMPT_PAY_DISCOUNT = 0.10
TIER_DISCOUNT = {"SILVER": 0.05, "GOLD": 0.15}
TIER_BONUS = {"SILVER": 0.00, "GOLD": 0.10}
STEP_DOWN_PER_ROUND = 0.05
MIN_ROUND_FACTOR = 0.80
ADMIN_UPLIFT_RATE = 0.04
ADMIN_UPLIFT_CAP_CENTS = 25000
BIOPSY_RECALL_MONTHS = {"BENIGN": 12, "INDETERMINATE": 6, "MALIGNANT": 3}
ROUTINE_RECALL_MONTHS = 12


# ---------------------------------------------------------------------------
# Derived: Encounter.open_biopsy_count (PRD 2.5)
# ---------------------------------------------------------------------------
def recompute_open_biopsy_count(encounter):
    """open_biopsy_count = number of child biopsies whose status in {COLLECTED, AT_LAB}.

    When the derived field changes, that change is a mutation of the parent: it
    refreshes updated_at and increments version (PRD 2.5).
    """
    eid = encounter["id"]
    count = sum(
        1 for b in db.biopsies.values()
        if b["encounter_id"] == eid and b["status"] in ("COLLECTED", "AT_LAB")
    )
    if count != encounter["open_biopsy_count"]:
        encounter["open_biopsy_count"] = count
        db.touch(encounter)


# ---------------------------------------------------------------------------
# Recall reminder spawning
# ---------------------------------------------------------------------------
def spawn_recall(patient_id, reason, due_at_dt, biopsy_id=None):
    row = {
        "patient_id": patient_id,
        "biopsy_id": biopsy_id,
        "reason": reason,
        "due_at": db.iso(due_at_dt),
        "status": "PENDING",
    }
    db.stamp_new(row)
    db.recall_reminders[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# Calculation: biologic_charge_amount (scaffold §1.3, PRD 3.7)
# ---------------------------------------------------------------------------
def biologic_charge_amount(prior_auth):
    base = prior_auth["list_price_cents"]
    submission_round = prior_auth["submission_round"]
    round_factor = max(
        MIN_ROUND_FACTOR,
        1 - STEP_DOWN_PER_ROUND * (submission_round - 1),
    )
    allowed_after_rounds = helpers.mul_round(base, round_factor)
    uplift = min(ADMIN_UPLIFT_CAP_CENTS, helpers.mul_round(allowed_after_rounds, ADMIN_UPLIFT_RATE))
    return allowed_after_rounds + uplift


# ---------------------------------------------------------------------------
# Calculation: charge_patient_responsibility (scaffold §1.3, PRD 3.7)
# ---------------------------------------------------------------------------
def compute_charge_split(charge, patient):
    """Dual-variant split. Mutates charge with responsibility fields and, on the
    INSURANCE path, debits patient.insurance_deductible_remaining_cents.
    """
    pay_path = charge["pay_path"]
    if pay_path == "INSURANCE":
        allowed = charge["insurer_allowed_cents"]
        ded_apply = min(allowed, patient["insurance_deductible_remaining_cents"])
        charge["deductible_applied_cents"] = ded_apply
        remainder = allowed - ded_apply
        patient_coins = helpers.mul_round(remainder, patient["insurance_coinsurance_rate"])
        charge["patient_responsibility_cents"] = ded_apply + patient_coins
        charge["insurer_responsibility_cents"] = allowed - charge["patient_responsibility_cents"]
        # write-back side effect
        patient["insurance_deductible_remaining_cents"] -= ded_apply
        db.touch(patient)
    else:  # CASH
        charge["patient_responsibility_cents"] = helpers.mul_round(
            charge["billed_amount_cents"], 1 - CASH_PROMPT_PAY_DISCOUNT
        )
        charge["insurer_responsibility_cents"] = 0
        charge["deductible_applied_cents"] = 0


# ---------------------------------------------------------------------------
# Calculation: cosmetic_redemption_split (scaffold §1.3, PRD 3.6)
# ---------------------------------------------------------------------------
def compute_redemption(membership, list_price_cents):
    """Returns (redeemed_cents, out_of_pocket_cents) for the redemption.

    Discount multiply rounds BEFORE the wallet min().
    """
    tier_discount = TIER_DISCOUNT[membership["tier"]]
    discounted_price = helpers.mul_round(list_price_cents, 1 - tier_discount)
    available = membership["unit_balance_cents"]
    redeemed = min(discounted_price, available)
    out_of_pocket = discounted_price - redeemed
    return redeemed, out_of_pocket


# ---------------------------------------------------------------------------
# Calculation: membership_wallet_grant (scaffold §1.3, PRD 3.6)
# ---------------------------------------------------------------------------
def membership_wallet_grant(membership):
    bonus_rate = TIER_BONUS[membership["tier"]]
    purchased = membership["purchased_unit_cents"]
    return purchased + helpers.mul_round(purchased, bonus_rate)


# ---------------------------------------------------------------------------
# Step therapy satisfaction (scaffold §1.3, PRD 3.9)
# ---------------------------------------------------------------------------
def recompute_satisfied_steps(prior_auth):
    paid = prior_auth["id"]
    prior_auth["satisfied_step_count"] = sum(
        1 for t in db.step_therapy_trials.values()
        if t["prior_auth_id"] == paid and t["outcome"] == "FAILED"
    )
