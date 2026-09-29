"""The repeat-offender record: strikes, liability indices, tier, window, education (PRD 3.8)."""
from datetime import timedelta
from decimal import Decimal

import clock
import db
from constants import (
    BASE_DISPUTE_WINDOW_DAYS,
    DECAY_FLOOR,
    DECAY_PER_DAY,
    INDEX_STATUSES,
    PARTIAL_WEIGHT,
    ROLLING_WINDOW_DAYS,
    STRIKE_STATUSES,
    TIER_1_MIN,
    TIER_2_MIN,
    TIER_3_MIN,
    TIER_ORDINAL,
    TIER_WINDOW_STEP_DAYS,
    UPHELD_WEIGHT,
)
from util import rhu

ZERO = Decimal("0")


def shipments_of(customer_id):
    return db.all_rows("shipments", lambda s: s.get("customer_id") == customer_id)


def notices_of_customer(customer_id):
    ship_ids = {s["id"] for s in shipments_of(customer_id)}
    return db.all_rows("correction_notices", lambda n: n.get("shipment_id") in ship_ids)


def customer_of_shipment(shipment):
    return db.get("customers", shipment.get("customer_id"))


def recompute_strikes(customer):
    """PRD 2.9: the strike count is a conserved quantity, not an accumulator."""
    count = sum(
        1 for n in notices_of_customer(customer["id"]) if n.get("status") in STRIKE_STATUSES
    )
    if customer.get("offender_strike_count") != count:
        customer["offender_strike_count"] = count
        db.touch(customer)
    return count


def recompute_indices(customer):
    now = clock.now()
    horizon = now - timedelta(days=ROLLING_WINDOW_DAYS)
    rolling = ZERO
    lifetime = ZERO
    for notice in notices_of_customer(customer["id"]):
        if notice.get("resolved_at") is None or notice.get("status") not in INDEX_STATUSES:
            continue
        weight = UPHELD_WEIGHT if notice["status"] == "UPHELD" else PARTIAL_WEIGHT
        lifetime += weight
        resolved_at = notice["resolved_at"]
        if resolved_at >= horizon:
            age_days = int((now - resolved_at).total_seconds() // 86400)
            decay = 1 - DECAY_PER_DAY * age_days
            if decay < DECAY_FLOOR:
                decay = DECAY_FLOOR
            rolling += weight * decay

    rolling = rhu(rolling, 2)
    lifetime = rhu(lifetime, 2)
    tier = tier_for(rolling)
    window = BASE_DISPUTE_WINDOW_DAYS - TIER_WINDOW_STEP_DAYS * TIER_ORDINAL[tier]

    changed = (
        customer.get("liability_index_rolling") != rolling
        or customer.get("liability_index_lifetime") != lifetime
        or customer.get("offender_tier") != tier
        or customer.get("dispute_window_days") != window
    )
    customer["liability_index_rolling"] = rolling
    customer["liability_index_lifetime"] = lifetime
    customer["offender_tier"] = tier
    customer["dispute_window_days"] = window
    if changed:
        db.touch(customer)
    return customer


def tier_for(rolling_index):
    if rolling_index >= TIER_3_MIN:
        return "TIER_3"
    if rolling_index >= TIER_2_MIN:
        return "TIER_2"
    if rolling_index >= TIER_1_MIN:
        return "TIER_1"
    return "TIER_0"


def recompute_record(customer):
    """Strike recount followed by both indices, tier and window."""
    if customer is None:
        return None
    recompute_strikes(customer)
    recompute_indices(customer)
    return customer


def apply_education_threshold(customer):
    """Flips education_status to REQUIRED once the strike threshold is reached."""
    if customer is None:
        return None
    threshold = customer.get("education_threshold_strikes")
    if threshold is None:
        return customer
    if customer.get("offender_strike_count", 0) >= threshold and customer.get(
        "education_status"
    ) in ("NONE", "COMPLETED"):
        customer["education_status"] = "REQUIRED"
        customer["education_required_at"] = clock.now()
        db.touch(customer)
    return customer
