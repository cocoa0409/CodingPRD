"""Account ledger recompute and charge calculations (PRD §3, SCAFFOLD §1.3).

All monetary values are integer cents (PRD §2.8). The only rounding is the
floor applied to the damage fee after multiplication.
"""
import math

from db import db
from services.common import make_record, touch

# Constants (SCAFFOLD §1.3 + PRD §3).
SHORTAGE_UNIT_CENTS = 1500
PAST_DUE_THRESHOLD_CENTS = 50000
DAMAGE_RETIRE_STRIKES = 4
LIGHT_STRIKE_THRESHOLD = 2
HEAVY_STRIKE_THRESHOLD = 4
LIGHT_DAMAGE_PCT = 0.25
MODERATE_DAMAGE_PCT = 0.50
HEAVY_DAMAGE_PCT = 0.75


# ---------------------------------------------------------------------------
# Account derived fields
# ---------------------------------------------------------------------------
def recompute_account(account):
    """Recompute outstanding_cents, active_wearer_count and billing_status.

    outstanding_cents = sum of amount_cents of this account's unpaid charges.
    active_wearer_count = count of this account's ACTIVE wearers.
    billing_status crosses CURRENT->PAST_DUE strictly above the threshold (>),
    and the system reverse edge PAST_DUE->CURRENT fires at or below (<=).
    Manual ON_HOLD is never altered by this automatic recompute.

    Returns True if a tracked field actually changed (so callers bump version
    only on real change).
    """
    acct_id = account["id"]

    outstanding = sum(
        sc["amount_cents"]
        for sc in db.service_charges.values()
        if sc["account_id"] == acct_id and not sc["paid"]
    )
    active_wearers = sum(
        1
        for w in db.wearers.values()
        if w["account_id"] == acct_id and w["roster_status"] == "ACTIVE"
    )

    changed = False
    if account["outstanding_cents"] != outstanding:
        account["outstanding_cents"] = outstanding
        changed = True
    if account["active_wearer_count"] != active_wearers:
        account["active_wearer_count"] = active_wearers
        changed = True

    # Automatic billing_status system transitions. ON_HOLD is only set/cleared
    # by the explicit place-hold/release-hold admin actions, never here.
    status = account["billing_status"]
    new_status = status
    if status == "CURRENT" and outstanding > PAST_DUE_THRESHOLD_CENTS:
        new_status = "PAST_DUE"
    elif status == "PAST_DUE" and outstanding <= PAST_DUE_THRESHOLD_CENTS:
        new_status = "CURRENT"

    if new_status != status:
        account["billing_status"] = new_status
        changed = True

    if changed:
        touch(account)
    return changed


# ---------------------------------------------------------------------------
# Charge creation
# ---------------------------------------------------------------------------
def create_charge(visit_id, account_id, charge_type, amount_cents):
    """Create a ServiceCharge row (paid=false)."""
    return make_record("service_charges", {
        "service_visit_id": visit_id,
        "account_id": account_id,
        "charge_type": charge_type,
        "amount_cents": amount_cents,
        "paid": False,
    })


# ---------------------------------------------------------------------------
# Loss / damage fee (SCAFFOLD §1.3 loss_damage_fee; PRD §3.6)
# ---------------------------------------------------------------------------
def loss_fee(garment_type):
    """Loss bills full replacement cost, no tiering."""
    return garment_type["replacement_cost_cents"]


def damage_fee(garment, garment_type):
    """Tiered fraction of replacement cost selected by soil_strikes.

    Order pinned: pick multiplier from soil_strikes FIRST, multiply, floor,
    then clamp to the full replacement cost.
    """
    strikes = garment["soil_strikes"]
    if strikes >= HEAVY_STRIKE_THRESHOLD:
        mult = HEAVY_DAMAGE_PCT
    elif strikes >= LIGHT_STRIKE_THRESHOLD:
        mult = MODERATE_DAMAGE_PCT
    else:
        mult = LIGHT_DAMAGE_PCT
    replacement = garment_type["replacement_cost_cents"]
    raw = math.floor(replacement * mult)
    return min(raw, replacement)


# ---------------------------------------------------------------------------
# Provisional service charge (PRD §3.9)
# ---------------------------------------------------------------------------
def provisional_service_charge(visit, account):
    """Return (rental_cents, shortage_cents).

    rental: sum of garment_type.weekly_rate_cents over every garment of the
    account whose lifecycle_status == ASSIGNED at delivery time.
    shortage: max(0, expected - actual - grace) * SHORTAGE_UNIT_CENTS.
    """
    acct_id = account["id"]
    rental = 0
    for g in db.garments.values():
        if g["account_id"] == acct_id and g["lifecycle_status"] == "ASSIGNED":
            gt = db.garment_types[g["garment_type_id"]]
            rental += gt["weekly_rate_cents"]

    shortfall = max(
        0,
        visit["expected_soil_count"]
        - visit["actual_soil_count"]
        - account["shortage_grace_units"],
    )
    shortage = shortfall * SHORTAGE_UNIT_CENTS
    return rental, shortage


# ---------------------------------------------------------------------------
# Finalized service charge (PRD §3.10)
# ---------------------------------------------------------------------------
def finalized_service_charge(visit, account):
    """Return (rental_cents, shortage_cents).

    rental: sum of weekly_rate_cents over the account's garments that are
    ASSIGNED AND cycled_through_wash_this_visit == True.
    shortage: reconciled shortfall = max(0, expected - actual - grace); forgive
    one extra unit when billing_status == CURRENT; units * SHORTAGE_UNIT_CENTS.

    The good-standing flag is read from the account's billing_status BEFORE the
    reconciliation's own ledger recompute (i.e. its posture going into reconcile).
    """
    acct_id = account["id"]
    rental = 0
    for g in db.garments.values():
        if (
            g["account_id"] == acct_id
            and g["lifecycle_status"] == "ASSIGNED"
            and g["cycled_through_wash_this_visit"]
        ):
            gt = db.garment_types[g["garment_type_id"]]
            rental += gt["weekly_rate_cents"]

    reconciled_shortfall = max(
        0,
        visit["expected_soil_count"]
        - visit["actual_soil_count"]
        - account["shortage_grace_units"],
    )
    forgiven = 1 if account["billing_status"] == "CURRENT" else 0
    shortage_units = max(0, reconciled_shortfall - forgiven)
    shortage = shortage_units * SHORTAGE_UNIT_CENTS
    return rental, shortage
