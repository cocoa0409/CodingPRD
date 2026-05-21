"""All monetary and policy calculations for the T&E API.

Conventions:
- All amounts are integer cents.
- round_half_up everywhere a fractional cent appears.
- Per-leg-round-then-sum for mileage.
- Provisional vs final variants are distinguished by the source of the
  PerDiemRate (live resolve vs pinned-by-id).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Tuple

from core.store import store
from core.utils import parse_iso, round_half_up_cents
from services.per_diem_service import resolve_per_diem, resolve_per_diem_by_id


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
FIRST_LAST_DAY_FRACTION = Decimal("0.75")
IRS_BUSINESS_RATE_CENTS = Decimal("67")
MILEAGE_OVERLAP_THRESHOLD = Decimal("30.0")
MILEAGE_PERSONAL_OVERLAP_RATE_CENTS = Decimal("21")

MEAL_SHARES = {
    "BREAKFAST": Decimal("0.25"),
    "LUNCH": Decimal("0.30"),
    "DINNER": Decimal("0.45"),
    "INCIDENTAL": Decimal("0.05"),
}

RENTAL_DAILY_CAP_CENTS = 6500
CDW_DAILY_CAP_CENTS = 1500
CORPORATE_CDW_STATES = {"CA", "TX", "NY", "FL", "WA"}

LLF_VARIANCE_TOLERANCE_CENTS = 10000


# -----------------------------------------------------------------------------
# Trip budget — provisional + final
# -----------------------------------------------------------------------------
def compute_trip_budget(
    trip: dict,
    *,
    variant: str = "provisional",
) -> Tuple[int, Optional[dict]]:
    """Compute estimated_budget_cents.

    Returns (budget_cents, resolved_rate). The resolved_rate is the PerDiemRate
    used for the calculation; the caller can store its id for pinning when
    appropriate.
    """
    start = parse_iso(trip["start_date"])
    end = parse_iso(trip["end_date"])
    if start is None or end is None:
        return 0, None

    nights = (end.date() - start.date()).days
    mie_days = nights + 1

    if variant == "final" and trip.get("pinned_per_diem_rate_id"):
        rate = resolve_per_diem_by_id(trip["pinned_per_diem_rate_id"])
    else:
        rate = resolve_per_diem(trip["destination_city"], trip["destination_state"], start)

    if rate is None:
        return 0, None

    lodging_cap = int(rate["lodging_cap_cents"])
    mie_cap = int(rate["mie_cap_cents"])

    lodging_budget = lodging_cap * nights

    if mie_days == 1:
        mie_budget = round_half_up_cents(Decimal(mie_cap) * FIRST_LAST_DAY_FRACTION)
    else:
        first_last = 2 * round_half_up_cents(Decimal(mie_cap) * FIRST_LAST_DAY_FRACTION)
        middle = (mie_days - 2) * mie_cap
        mie_budget = first_last + middle

    return lodging_budget + mie_budget, rate


# -----------------------------------------------------------------------------
# Mileage reimbursement
# -----------------------------------------------------------------------------
def has_same_date_rental(report_id: str, expense_date: str, self_line_id: Optional[str] = None) -> bool:
    """True if a same-date RENTAL_CAR line exists on the report (not VOIDED)."""
    target = parse_iso(expense_date)
    if target is None:
        return False
    for line in store.expense_lines.values():
        if line["report_id"] != report_id:
            continue
        if self_line_id is not None and line["id"] == self_line_id:
            continue
        if line.get("category") != "RENTAL_CAR":
            continue
        if line.get("line_status") == "VOIDED":
            continue
        d = parse_iso(line.get("expense_date"))
        if d is None:
            continue
        if d.date() == target.date():
            return True
    return False


def compute_mileage_reimbursement(line: dict) -> int:
    miles = Decimal(str(line["miles_driven"]))
    if has_same_date_rental(line["report_id"], line["expense_date"], line.get("id")) and miles > MILEAGE_OVERLAP_THRESHOLD:
        base = round_half_up_cents(MILEAGE_OVERLAP_THRESHOLD * IRS_BUSINESS_RATE_CENTS)
        excess = round_half_up_cents(
            (miles - MILEAGE_OVERLAP_THRESHOLD) * MILEAGE_PERSONAL_OVERLAP_RATE_CENTS
        )
        return base + excess
    return round_half_up_cents(miles * IRS_BUSINESS_RATE_CENTS)


# -----------------------------------------------------------------------------
# Meal itemization
# -----------------------------------------------------------------------------
def _resolve_meal_rate(trip: dict, expense_date: str, variant: str) -> Optional[dict]:
    when = parse_iso(expense_date)
    if when is None:
        return None
    if variant == "final" and trip.get("pinned_per_diem_rate_id"):
        return resolve_per_diem_by_id(trip["pinned_per_diem_rate_id"])
    return resolve_per_diem(trip["destination_city"], trip["destination_state"], when)


def compute_meal_reimbursement(
    line: dict, trip: dict, variant: str = "provisional"
) -> Tuple[int, str, Optional[int]]:
    """Returns (reimbursable_cents, policy_status_hint, per_meal_cap_cents).

    The policy_status_hint is "IN_POLICY" or "OUT_OF_POLICY" — the caller is
    free to override if downstream OOP cascades apply.
    """
    if line.get("meal_was_provided"):
        return 0, "IN_POLICY", None

    rate = _resolve_meal_rate(trip, line["expense_date"], variant)
    if rate is None:
        # If no rate available, treat as 0 and mark provisionally OUT_OF_POLICY.
        return 0, "OUT_OF_POLICY", None

    meal_type = line.get("meal_type")
    share = MEAL_SHARES.get(meal_type)
    if share is None:
        return 0, "OUT_OF_POLICY", None

    per_meal_cap = round_half_up_cents(Decimal(int(rate["mie_cap_cents"])) * share)

    method = line.get("per_diem_method")
    if method == "PER_DIEM":
        return per_meal_cap, "IN_POLICY", per_meal_cap

    # ACTUAL
    claimed = int(line.get("amount_claimed_cents") or 0)
    if claimed <= per_meal_cap:
        return claimed, "IN_POLICY", per_meal_cap
    return per_meal_cap, "OUT_OF_POLICY", per_meal_cap


# -----------------------------------------------------------------------------
# Rental car & CDW
# -----------------------------------------------------------------------------
def compute_rental_reimbursement(line: dict, trip: dict) -> Tuple[int, str]:
    rental_days = int(line["rental_days"])
    claimed = int(line.get("amount_claimed_cents") or 0)
    base_cap = rental_days * RENTAL_DAILY_CAP_CENTS
    claimed_base = min(claimed, base_cap)

    cdw_purchased = bool(line.get("cdw_purchased"))
    dest_state = (trip.get("destination_state") or "").strip().upper()

    if cdw_purchased:
        if dest_state in CORPORATE_CDW_STATES:
            cdw_allowed = 0
        else:
            cdw_allowed = rental_days * CDW_DAILY_CAP_CENTS

        if claimed > base_cap:
            cdw_component = min(claimed - base_cap, cdw_allowed)
            total = claimed_base + cdw_component
            # Determine policy_status: in-policy when claimed equals total (no
            # excess remained beyond the allowed CDW cap).
            policy = "IN_POLICY" if claimed <= base_cap + cdw_allowed else "OUT_OF_POLICY"
            return total, policy
        # No excess to cover by CDW
        policy = "IN_POLICY" if claimed <= base_cap else "OUT_OF_POLICY"
        return claimed_base, policy

    # No CDW purchased
    policy = "IN_POLICY" if claimed <= base_cap else "OUT_OF_POLICY"
    return claimed_base, policy


# -----------------------------------------------------------------------------
# Flight — Lowest Logical Fare variance
# -----------------------------------------------------------------------------
def _resolve_flight_rate(trip: dict, expense_date: str, variant: str) -> Optional[dict]:
    when = parse_iso(expense_date)
    if when is None:
        return None
    if variant == "final" and trip.get("pinned_per_diem_rate_id"):
        return resolve_per_diem_by_id(trip["pinned_per_diem_rate_id"])
    return resolve_per_diem(trip["destination_city"], trip["destination_state"], when)


def compute_flight_reimbursement(
    line: dict, trip: dict, variant: str = "provisional"
) -> Tuple[int, str, Optional[int]]:
    """Returns (reimbursable_cents, policy_status, llf_cents)."""
    rate = _resolve_flight_rate(trip, line["expense_date"], variant)
    claimed = int(line.get("amount_claimed_cents") or 0)
    if rate is None:
        # No rate => can't compute variance; default IN_POLICY with claimed
        return claimed, "IN_POLICY", None

    llf = int(rate["lodging_cap_cents"]) + int(rate["mie_cap_cents"])
    variance = claimed - llf
    if variance <= LLF_VARIANCE_TOLERANCE_CENTS:
        return claimed, "IN_POLICY", llf
    return llf, "OUT_OF_POLICY", llf


# -----------------------------------------------------------------------------
# Other / Lodging passthrough
# -----------------------------------------------------------------------------
def compute_lodging_reimbursement(
    line: dict, trip: dict, variant: str = "provisional"
) -> Tuple[int, str]:
    """LODGING: ACTUAL means we reimburse min(claimed, nights*lodging_cap);
    PER_DIEM means reimburse nights*lodging_cap (but for a single line we
    fall back to claimed if it's <= the per-night cap).

    For policy: in-policy iff claimed <= lodging_cap_cents (per-night, per the
    PRD semantics that a line represents a single night)."""
    rate_when = parse_iso(line["expense_date"])
    if variant == "final" and trip.get("pinned_per_diem_rate_id"):
        rate = resolve_per_diem_by_id(trip["pinned_per_diem_rate_id"])
    else:
        rate = resolve_per_diem(trip["destination_city"], trip["destination_state"], rate_when)

    claimed = int(line.get("amount_claimed_cents") or 0)

    if rate is None:
        return claimed, "IN_POLICY"

    cap = int(rate["lodging_cap_cents"])
    method = line.get("per_diem_method")

    if method == "PER_DIEM":
        return cap, "IN_POLICY"

    # ACTUAL
    if claimed <= cap:
        return claimed, "IN_POLICY"
    return cap, "OUT_OF_POLICY"


def compute_other_reimbursement(line: dict) -> Tuple[int, str]:
    claimed = int(line.get("amount_claimed_cents") or 0)
    return claimed, "IN_POLICY"
