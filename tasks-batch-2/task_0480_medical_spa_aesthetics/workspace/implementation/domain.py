"""Domain calculations, derived-field recomputation, and serialization.

All money in whole-cent integers. Decimal + ROUND_HALF_UP for charge rounding.
The logical clock governs every expiry/validity check.
"""
from decimal import Decimal
from datetime import timedelta

from db import db, now_iso
from clock import clock
from helpers import round_half_up

# Domain constants (SCAFFOLD domain_constants)
GOOD_FAITH_EXAM_VALIDITY_DAYS = 365
MAX_TOUCHUP_ROUNDS = 2
POINT_VALUE_CENTS = 1
RATE_SCALE_BPS = 10000


# --------------------------------------------------------------------------
# Mutation bookkeeping: refresh updated_at + bump version on owning resource.
# --------------------------------------------------------------------------
def touch(entity):
    """Refresh updated_at and increment version. For common-fields entities."""
    if "version" in entity:
        entity["version"] += 1
    if "updated_at" in entity:
        entity["updated_at"] = now_iso()


# --------------------------------------------------------------------------
# Clock helpers
# --------------------------------------------------------------------------
def lot_expired(lot):
    """A lot is expired once logical clock >= expiration_date."""
    return clock.now() >= lot["_expiration_dt"]


def standing_order_active(order):
    return order["status"] == "SIGNED" and clock.now() < order["_valid_until_dt"]


def exam_fresh(consultation):
    """Good-faith exam fresh while exam_clock_utc + 365d > current clock."""
    if consultation["status"] != "EXAM_COMPLETE" or consultation.get("_exam_clock_dt") is None:
        return False
    horizon = consultation["_exam_clock_dt"] + timedelta(days=GOOD_FAITH_EXAM_VALIDITY_DAYS)
    return horizon > clock.now()


# --------------------------------------------------------------------------
# Lot ledger
# --------------------------------------------------------------------------
def recompute_lot_remaining(lot):
    lot["remaining_units"] = lot["total_units"] - lot["reserved_units"] - lot["consumed_units"]


def fefo_candidates(product):
    """AVAILABLE, non-expired lots of `product`, ordered FEFO.

    Sort by (expiration_date ASC, created_at ASC); lot id never used as tiebreak.
    created_at tie-break implemented via insertion seq for stability.
    """
    cands = [
        lot for lot in db.injectable_lots.values()
        if lot["product"] == product
        and lot["status"] == "AVAILABLE"
        and not lot_expired(lot)
    ]
    cands.sort(key=lambda l: (l["_expiration_dt"], l["created_at"], l["_seq"]))
    return cands


def available_units(product):
    return sum(lot["remaining_units"] for lot in fefo_candidates(product))


# --------------------------------------------------------------------------
# session_charge calculation (PRD §3.6)
# --------------------------------------------------------------------------
def compute_final_charge(actual_units, list_price_per_unit_cents,
                         member_discount_pct, loyalty_points_redeemed):
    # round PER LINE, then sum, then subtract loyalty redemption, floor 0.
    line = (Decimal(actual_units) * Decimal(list_price_per_unit_cents)
            * (Decimal(1) - Decimal(str(member_discount_pct))))
    line_cents = round_half_up(line)
    subtotal_cents = line_cents  # single product line
    loyalty_redemption_cents = loyalty_points_redeemed * POINT_VALUE_CENTS
    final_charge_cents = max(0, subtotal_cents - loyalty_redemption_cents)
    return final_charge_cents


# --------------------------------------------------------------------------
# provisional_series_cost calculation (PRD §3.6)
# --------------------------------------------------------------------------
def compute_provisional_series_cost(plan):
    remaining = plan["planned_sessions"] - plan["sessions_committed"]
    if remaining < 0:
        remaining = 0
    return (remaining
            * plan["planned_units_per_session"]
            * plan["list_price_per_unit_cents"])


def recompute_plan_provisional(plan):
    plan["provisional_series_cost_cents"] = compute_provisional_series_cost(plan)


def recompute_plan_deposit_paid(plan):
    total = sum(
        d["amount_cents"] for d in db.deposits.values()
        if d["treatment_plan_id"] == plan["id"] and d["status"] == "POSTED"
    )
    plan["deposit_paid_cents"] = total


# --------------------------------------------------------------------------
# Provider computed counters + complication rate (PRD §3.8)
# --------------------------------------------------------------------------
def recompute_provider_counts(provider):
    pid = provider["id"]
    open_count = 0
    resolved_count = 0
    for c in db.complication_cases.values():
        if c["injector_provider_id"] == pid:
            if c["status"] in ("OPEN", "IN_TOUCHUP"):
                open_count += 1
            elif c["status"] == "RESOLVED":
                resolved_count += 1
    committed = 0
    for s in db.treatment_sessions.values():
        if s["injector_provider_id"] == pid and s["status"] in (
                "COMMITTED", "RESOLVED", "COMPLICATION_OPEN"):
            committed += 1
    provider["open_complication_count"] = open_count
    provider["resolved_complication_count"] = resolved_count
    provider["committed_session_count"] = committed


def complication_rate_bps(committed, numerator):
    if committed == 0:
        return 0
    return round_half_up(Decimal(numerator) * Decimal(RATE_SCALE_BPS) / Decimal(committed))


# --------------------------------------------------------------------------
# Patient photo consent flag (PRD §3.5)
# --------------------------------------------------------------------------
def recompute_patient_consent(patient):
    pid = patient["id"]
    has = any(
        p["patient_id"] == pid and p["kind"] == "CONSENT" and p["signed"] is True
        for p in db.consent_photos.values()
    )
    patient["photo_consent_on_file"] = has


# --------------------------------------------------------------------------
# Loyalty account lookup
# --------------------------------------------------------------------------
def loyalty_account_for_patient(patient_id):
    for acc in db.loyalty_accounts.values():
        if acc["patient_id"] == patient_id:
            return acc
    return None


def recompute_loyalty_balance(account):
    account["points_balance"] = account["points_earned"] - account["points_redeemed"]


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------
_INTERNAL_PREFIX = "_"


def _public(entity):
    return {k: v for k, v in entity.items() if not k.startswith(_INTERNAL_PREFIX)}


def serialize_provider(provider):
    out = _public(provider)
    committed = provider["committed_session_count"]
    out["provisional_complication_rate_bps"] = complication_rate_bps(
        committed,
        provider["open_complication_count"] + provider["resolved_complication_count"])
    out["settled_complication_rate_bps"] = complication_rate_bps(
        committed, provider["resolved_complication_count"])
    return out


def serialize(entity, kind):
    if kind == "Provider":
        return serialize_provider(entity)
    return _public(entity)
