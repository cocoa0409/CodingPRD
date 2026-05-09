"""Calculation rules (PRD §3.3, §3.5, §3.6 — SCAFFOLD §1.3)."""
from decimal import Decimal, ROUND_HALF_UP

from db import db


# --------------------------------------------------------------------- #
# Constants pulled verbatim from SCAFFOLD.calculations
# --------------------------------------------------------------------- #

HOUSEHOLD_TYPE_PTS = {
    "LOW_INCOME": 30,
    "NEW_CITIZEN": 15,
    "RELOCATION": 20,
    "TALENT": 25,
}
DISABILITY_PTS = 20
SPECIAL_CARE_PTS = {
    "NONE": 0,
    "VETERAN": 15,
    "MARTYR_FAMILY": 18,
    "SINGLE_PARENT": 10,
    "ELDERLY_LIVE_ALONE": 12,
}
RESIDENCE_PTS_PER_PERIOD = 1
RESIDENCE_PTS_CAP = 20

# Rent-reduction tiering (basis points)
TIER_BPS_LT_30 = 5000
TIER_BPS_LT_50 = 3000
TIER_BPS_LT_80 = 1500
TIER_BPS_ELSE = 0

CATEGORY_BOOST = {
    "MAJOR_ILLNESS": 1500,
    "UNEMPLOYMENT": 1000,
    "DISABILITY": 1500,
    "ELDER_CARE": 500,
}
MAX_BPS = 10000

# Apartment-type → bedroom_count
APARTMENT_BEDROOMS = {
    "STUDIO": 0,
    "ONE_BEDROOM": 1,
    "TWO_BEDROOM": 2,
    "THREE_BEDROOM": 3,
}

# Family-size tolerance per apartment type (allocation_selector)
FAMILY_SIZE_TOLERANCE = {
    "STUDIO": {1},
    "ONE_BEDROOM": {1, 2},
    "TWO_BEDROOM": {2, 3, 4},
    "THREE_BEDROOM": {4, 5, 6, 7},
}


# --------------------------------------------------------------------- #
# Rounding helpers
# --------------------------------------------------------------------- #

def round_half_up_int(value) -> int:
    """Round HALF_UP to integer cents. Accepts int / float / Decimal / str."""
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------- #
# Queue score (PRD §3.3)
# --------------------------------------------------------------------- #

def compute_queue_score(application: dict, *, current_period_index: int) -> int:
    household_type = application.get("household_type")
    members = application.get("household_members") or []
    residence_start = int(application.get("residence_start_period", 0))

    ht_pts = HOUSEHOLD_TYPE_PTS.get(household_type, 0)

    any_disability = any(bool(m.get("has_disability")) for m in members)
    dis_pts = DISABILITY_PTS if any_disability else 0

    raw_residence = max(0, current_period_index - residence_start)
    res_pts = min(raw_residence * RESIDENCE_PTS_PER_PERIOD, RESIDENCE_PTS_CAP)

    sc_pts = 0
    for m in members:
        cat = m.get("special_care_category", "NONE")
        sc_pts = max(sc_pts, SPECIAL_CARE_PTS.get(cat, 0))

    return int(ht_pts + dis_pts + res_pts + sc_pts)


def compute_tie_break_key(application: dict) -> str:
    """Composite tie-break key (PRD §3.3): residence_start_period asc,
    created_at asc, id asc — encoded for lex compare.
    """
    rsp = int(application.get("residence_start_period", 0))
    return f"{rsp:020d}|{application.get('created_at', '')}|{application.get('id', '')}"


# --------------------------------------------------------------------- #
# Rent-reduction discount tiering (PRD §3.6)
# --------------------------------------------------------------------- #

def _base_bps_from_ratio(income_cents: int, base_rent_cents: int) -> int:
    """ratio = income/base_rent; tier comparisons strictly less-than."""
    if base_rent_cents <= 0:
        # Defensive: treat zero base rent as 'else' branch
        return TIER_BPS_ELSE
    ratio = Decimal(income_cents) / Decimal(base_rent_cents)
    if ratio < Decimal("0.30"):
        return TIER_BPS_LT_30
    if ratio < Decimal("0.50"):
        return TIER_BPS_LT_50
    if ratio < Decimal("0.80"):
        return TIER_BPS_LT_80
    return TIER_BPS_ELSE


def compute_reduction_bps(income_cents: int, base_rent_cents: int,
                          hardship_category: str) -> int:
    base = _base_bps_from_ratio(income_cents, base_rent_cents)
    boost = CATEGORY_BOOST.get(hardship_category, 0)
    return int(min(MAX_BPS, base + boost))


# --------------------------------------------------------------------- #
# Per-room rent (PRD §3.6, monthly_effective_rent)
# --------------------------------------------------------------------- #

def _room_fractions(apartment_type: str, bedroom_count: int) -> list[Decimal]:
    """Return ordered list of per-slot fractional shares (sum = 1)."""
    if apartment_type == "STUDIO":
        return [Decimal("1")]
    # 40% living room + remaining 60% split evenly across bedrooms
    living = Decimal("40") / Decimal("100")
    bedroom_frac = (Decimal("60") / Decimal("100")) / Decimal(bedroom_count)
    return [living] + [bedroom_frac] * bedroom_count


def _active_rent_reduction_bps(contract: dict, current_period_index: int) -> int:
    """Highest final_discount_bps among RentReductions on this contract whose
    status == FINAL_APPROVED and validity_start_period <= current_period_index <
    validity_end_period. Tie-break: latest created_at desc, then id desc.
    """
    candidates = []
    for rr in db.rent_reductions.values():
        if rr.get("contract_id") != contract.get("id"):
            continue
        if rr.get("status") != "FINAL_APPROVED":
            continue
        vs = rr.get("validity_start_period")
        ve = rr.get("validity_end_period")
        if vs is None or ve is None:
            continue
        if vs <= current_period_index < ve:
            candidates.append(rr)
    if not candidates:
        return 0
    candidates.sort(
        key=lambda r: (r.get("final_discount_bps", 0),
                       r.get("created_at", ""),
                       r.get("id", "")),
        reverse=True,
    )
    return int(candidates[0].get("final_discount_bps", 0))


def _active_annual_review_adjustment(contract: dict) -> int:
    """Sum of rent_adjustment_cents across all FINALIZED reviews of the parent
    application (deltas accumulate per PRD §3.7).
    """
    application_id = contract.get("application_id")
    total = 0
    for r in db.annual_reviews.values():
        if r.get("application_id") != application_id:
            continue
        if r.get("status") != "FINALIZED":
            continue
        adj = r.get("rent_adjustment_cents")
        if adj is None:
            continue
        total += int(adj)
    return total


def compute_monthly_effective_rent(contract: dict, *, current_period_index: int) -> int:
    """Per-room rounded HALF_UP cents → sum, then add active annual-review deltas."""
    unit = db.housing_units.get(contract.get("housing_unit_id"))
    if not unit:
        return contract.get("monthly_effective_rent_cents", 0)

    apartment_type = unit.get("apartment_type")
    bedroom_count = int(unit.get("bedroom_count", 0))
    base_rent = Decimal(int(unit.get("monthly_base_rent_cents", 0)))

    discount_bps = _active_rent_reduction_bps(contract, current_period_index)
    discount_factor = (Decimal(MAX_BPS) - Decimal(discount_bps)) / Decimal(MAX_BPS)

    fractions = _room_fractions(apartment_type, bedroom_count)
    per_room_amounts: list[int] = []
    for frac in fractions:
        amt = base_rent * frac * discount_factor
        per_room_amounts.append(round_half_up_int(amt))

    base_total = sum(per_room_amounts)
    return int(base_total + _active_annual_review_adjustment(contract))


# --------------------------------------------------------------------- #
# Deposit (PRD §3.5 / SCAFFOLD calculations.deposit_amount)
# --------------------------------------------------------------------- #

def compute_deposit_amount(monthly_base_rent_cents: int) -> int:
    """deposit = round_half_up(base * 2). base is integer cents → just *2."""
    return round_half_up_int(Decimal(int(monthly_base_rent_cents)) * Decimal(2))
