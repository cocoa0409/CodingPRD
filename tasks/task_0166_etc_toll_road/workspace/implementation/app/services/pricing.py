"""Toll pricing & fine amount calculation.

Per §2.6 and SCAFFOLD §1.3:
    - All sub-products are rounded half-up to whole cents AT EACH STEP.
    - Order: class adjustment -> interop adjustment -> plate surcharge -> HOV check.
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from ..errors import ApiError
from ..store import store


CLASS_MULT = {
    "CLASS_2": Decimal("1.00"),
    "CLASS_3": Decimal("1.50"),
    "CLASS_4": Decimal("2.25"),
    "CLASS_5_PLUS": Decimal("3.50"),
}

PLATE_BILL_SURCHARGE_BPS = 1500
HOV_MIN_OCCUPANTS = 3

BASE_PENALTY = {
    "UNREAD_TRANSPONDER_NO_PLATE": 5000,
    "INSUFFICIENT_FUNDS_ON_PLATE_BILL": 2500,
    "BLOCKED_VEHICLE": 7500,
    "HOV_FRAUD": 10000,
}

LATE_PENALTY_CENTS = 2000

SUSPEND_THRESHOLD_CENTS = 15000


def _half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def class_for_axles(axle_count: int) -> str:
    if axle_count <= 2:
        return "CLASS_2"
    if axle_count == 3:
        return "CLASS_3"
    if axle_count == 4:
        return "CLASS_4"
    return "CLASS_5_PLUS"


def lookup_interop_policy(home_agency: str, gantry_agency: str):
    """Find the newest policy row for (home, gantry). Raises ambiguous error
    only when multiple rows match. Returns None when no row matches.

    Per validation #12 the lookup must be reported as ambiguous when there are
    multiple matching rows; we still use the newest row but signal the issue.
    """
    matches = [
        p for p in store.interop_policies.values()
        if p["home_agency"] == home_agency and p["gantry_agency"] == gantry_agency
    ]
    if not matches:
        return None, False
    matches.sort(key=lambda p: p["created_at"], reverse=True)
    return matches[0], len(matches) > 1


def compute_toll(
    *,
    base_rate_cents: int,
    vehicle_class: str,
    home_agency_code: Optional[str],
    gantry_agency: str,
    capture_method: str,
    hov_exempt_applied: bool,
):
    """Return (gross_toll_cents, net_toll_cents, ambiguous_interop_flag)."""
    mult = CLASS_MULT[vehicle_class]
    gross = _half_up(Decimal(base_rate_cents) * mult)

    ambiguous = False
    if home_agency_code is None or home_agency_code == gantry_agency:
        interop_adjust = 0
    else:
        policy, ambiguous = lookup_interop_policy(home_agency_code, gantry_agency)
        if policy is None:
            interop_adjust = 0
        else:
            delta_bps = int(policy["surcharge_bps"]) - int(policy["discount_bps"])
            interop_adjust = _half_up(Decimal(gross) * Decimal(delta_bps) / Decimal(10000))

    if capture_method == "PLATE":
        plate_surcharge = _half_up(Decimal(gross) * Decimal(PLATE_BILL_SURCHARGE_BPS) / Decimal(10000))
    else:
        plate_surcharge = 0

    if hov_exempt_applied:
        net = 0
    else:
        net = max(0, gross + interop_adjust + plate_surcharge)

    return gross, net, ambiguous


def compute_fine_amount(toll_event: dict, vehicle: Optional[dict], home_agency_code: Optional[str], reason_code: str):
    """Compute (amount_cents, civil_penalty_cents) for a new fine.

    Toll component uses the plate-bill variant of the pricing algorithm.
    """
    if vehicle is not None:
        veh_class = vehicle["vehicle_class"]
    else:
        veh_class = "CLASS_2"
    # toll component: PLATE variant w/ no HOV exemption
    _, net, _ambig = compute_toll(
        base_rate_cents=toll_event["base_rate_cents"],
        vehicle_class=veh_class,
        home_agency_code=home_agency_code,
        gantry_agency=toll_event["agency_code"],
        capture_method="PLATE",
        hov_exempt_applied=False,
    )
    civil_penalty = BASE_PENALTY[reason_code]
    amount = net + civil_penalty
    return amount, civil_penalty
