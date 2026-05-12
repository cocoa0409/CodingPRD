"""Fine amount calculation per scaffold calculations.fine_amount."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from clock import now, parse_iso


TYPE_BASE = {
    "OVERSTAY": 2000,
    "NON_PAYING": 3000,
    "BLOCKING": 5000,
    "WRONG_ZONE": 4000,
}

TYPE_MULTIPLIER = {
    "OVERSTAY": Decimal("1.0"),
    "NON_PAYING": Decimal("1.5"),
    "BLOCKING": Decimal("2.0"),
    "WRONG_ZONE": Decimal("1.25"),
}

PHOTO_SURCHARGE_CENTS = 1500
REPEAT_TIER1_CENTS = 1000
REPEAT_TIER2_CENTS = 2500
REPEAT_TIER3_CENTS = 5000


def _count_prior_violations(vehicle_id: str, exclude_id: str = None) -> int:
    """Count prior violations attributed to this vehicle (excluding the new one)
    whose status is PAID/TOWED_AWAY OR (PENDING and within last 90 days).
    """
    n = now()
    threshold = n - timedelta(days=90)
    count = 0
    for v in db.violations.values():
        if v.get("vehicle_id") != vehicle_id:
            continue
        if exclude_id and v["id"] == exclude_id:
            continue
        st = v.get("status")
        if st in ("PAID", "TOWED_AWAY"):
            count += 1
            continue
        if st == "PENDING":
            try:
                det = parse_iso(v["detected_at"])
            except Exception:
                continue
            if det >= threshold:
                count += 1
    return count


def compute_fine_amount(vehicle_id: str, violation_type: str, exclude_violation_id: str = None):
    """Returns (amount_cents, components_dict) per scaffold formula."""
    base = TYPE_BASE[violation_type]
    multiplier = TYPE_MULTIPLIER[violation_type]
    photo_surcharge = PHOTO_SURCHARGE_CENTS if violation_type in ("BLOCKING", "WRONG_ZONE") else 0
    prior = _count_prior_violations(vehicle_id, exclude_id=exclude_violation_id)
    if prior == 0:
        repeat = 0
    elif prior == 1:
        repeat = REPEAT_TIER1_CENTS
    elif prior == 2:
        repeat = REPEAT_TIER2_CENTS
    else:
        repeat = REPEAT_TIER3_CENTS

    # Multiply base * multiplier in Decimal, round HALF_UP, then add integer surcharges.
    raw = (Decimal(base) * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    amount = int(raw) + photo_surcharge + repeat
    components = {
        "base_cents": base,
        "type_multiplier": float(multiplier),
        "repeat_offender_surcharge_cents": repeat,
        "photo_required_surcharge_cents": photo_surcharge,
    }
    return amount, components
