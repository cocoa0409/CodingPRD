"""Calculation rules from the scaffold Table 1.3.

All money/RIN arithmetic uses Decimal with ROUND_HALF_UP as specified.
"""
from decimal import Decimal, ROUND_HALF_UP

import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _d(value):
    """Coerce an int/float/str into a Decimal exactly."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up_int(value):
    """Round a Decimal to 0 decimal places, half-up, returning an int."""
    return int(_d(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value):
    """Round a Decimal to 4 decimal places, half-up, returning a float for JSON."""
    q = _d(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# rin_generation_qty
# ---------------------------------------------------------------------------
def compute_rin_qty(gallon_qty, equivalence_value):
    """round_half_up(gallon_qty * equivalence_value), per-lot at generation."""
    return round_half_up_int(_d(gallon_qty) * _d(equivalence_value))


# ---------------------------------------------------------------------------
# rvo_obligation (provisional & final variants)
# ---------------------------------------------------------------------------
def compute_rvo(volume_gal, std_pct):
    """round_half_up(volume_gal * std_pct / 100)."""
    return round_half_up_int(_d(volume_gal) * _d(std_pct) / Decimal("100"))


def compute_provisional_rvos(year_row):
    vol = year_row["projected_volume_gal"]
    year_row["provisional_rvo_cellulosic_rins"] = compute_rvo(vol, year_row["std_cellulosic_pct"])
    year_row["provisional_rvo_biomass_diesel_rins"] = compute_rvo(vol, year_row["std_biomass_diesel_pct"])
    year_row["provisional_rvo_advanced_rins"] = compute_rvo(vol, year_row["std_advanced_pct"])
    year_row["provisional_rvo_total_rins"] = compute_rvo(vol, year_row["std_total_pct"])


def compute_final_rvos(year_row):
    vol = year_row["actual_volume_gal"]
    year_row["final_rvo_cellulosic_rins"] = compute_rvo(vol, year_row["std_cellulosic_pct"])
    year_row["final_rvo_biomass_diesel_rins"] = compute_rvo(vol, year_row["std_biomass_diesel_pct"])
    year_row["final_rvo_advanced_rins"] = compute_rvo(vol, year_row["std_advanced_pct"])
    year_row["final_rvo_total_rins"] = compute_rvo(vol, year_row["std_total_pct"])


def active_rvo(year_row, category):
    """Active RVO for a category: final_* when status != OPEN, else provisional_*."""
    suffix = {
        "CELLULOSIC": "cellulosic",
        "BIOMASS_DIESEL": "biomass_diesel",
        "ADVANCED": "advanced",
        "TOTAL_RENEWABLE": "total",
    }[category]
    if year_row["status"] != "OPEN":
        return year_row[f"final_rvo_{suffix}_rins"]
    return year_row[f"provisional_rvo_{suffix}_rins"]


# ---------------------------------------------------------------------------
# carryover_cap_check
# ---------------------------------------------------------------------------
CARRYOVER_CAP_FRACTION = Decimal("0.20")


def carryover_cap(year_row, category):
    """round_half_up(0.20 * active_rvo_category)."""
    return round_half_up_int(CARRYOVER_CAP_FRACTION * _d(active_rvo(year_row, category)))


# ---------------------------------------------------------------------------
# nested_retirement_accounting
# ---------------------------------------------------------------------------
D_CODE_CATEGORY_MAP = {
    "D3": ("CELLULOSIC", "ADVANCED", "TOTAL_RENEWABLE"),
    "D4": ("BIOMASS_DIESEL", "ADVANCED", "TOTAL_RENEWABLE"),
    "D5": ("ADVANCED", "TOTAL_RENEWABLE"),
    "D6": ("TOTAL_RENEWABLE",),
}

_CATEGORY_SUFFIX = {
    "CELLULOSIC": "cellulosic",
    "BIOMASS_DIESEL": "biomass_diesel",
    "ADVANCED": "advanced",
    "TOTAL_RENEWABLE": "total",
}


def category_suffix(category):
    return _CATEGORY_SUFFIX[category]


def rederive_year_retirement_counters(year_row):
    """Re-derive retired_* and retired_prior_* from scratch over ACCEPTED batches,
    excluding RINs on INVALIDATED lots."""
    for suffix in _CATEGORY_SUFFIX.values():
        year_row[f"retired_{suffix}_rins"] = 0
        year_row[f"retired_prior_{suffix}_rins"] = 0

    for batch in db.retirement_batches.values():
        if batch["obligation_year_id"] != year_row["id"]:
            continue
        if batch["status"] != "ACCEPTED":
            continue
        # Recompute this batch's effective retired qty and prior-vintage portion
        # excluding allocations that sit on INVALIDATED lots.
        effective_qty = 0
        effective_prior = 0
        for alloc in batch["allocations"]:
            lot = db.rin_lots.get(alloc["rin_lot_id"])
            if lot is None:
                continue
            if lot["status"] == "INVALIDATED":
                continue
            effective_qty += alloc["qty"]
            if lot["vintage_year"] == year_row["year"] - 1:
                effective_prior += alloc["qty"]
        if effective_qty == 0 and effective_prior == 0:
            continue
        for category in D_CODE_CATEGORY_MAP[batch["d_code"]]:
            suffix = _CATEGORY_SUFFIX[category]
            year_row[f"retired_{suffix}_rins"] += effective_qty
            year_row[f"retired_prior_{suffix}_rins"] += effective_prior


# ---------------------------------------------------------------------------
# retirement_fifo_allocation
# ---------------------------------------------------------------------------
def fifo_eligible_lots(year_row, d_code, exclude_vintage_filter=False):
    """Eligible lots for a retirement draw.

    Eligibility (all must hold):
      - lot.account_id == year.account_id
      - lot.status == ACTIVE
      - lot.d_code == d_code
      - lot.vintage_year in {year.year, year.year - 1}   (skipped when exclude_vintage_filter)
      - available_qty > 0
      - GENERATED: available balance is eligible
      - PURCHASED: source trade transfer_status == VERIFIED
    """
    lots = []
    for lot in db.rin_lots.values():
        if lot["account_id"] != year_row["account_id"]:
            continue
        if lot["status"] != "ACTIVE":
            continue
        if lot["d_code"] != d_code:
            continue
        if not exclude_vintage_filter:
            if lot["vintage_year"] not in (year_row["year"], year_row["year"] - 1):
                continue
        if lot["available_qty"] <= 0:
            continue
        if lot["origin"] == "PURCHASED":
            trade = db.rin_trades.get(lot["trade_id"])
            if trade is None or trade["transfer_status"] != "VERIFIED":
                continue
        lots.append(lot)
    # Order: created_at ASC, tie-break rin_qty ASC (never id)
    lots.sort(key=lambda l: (l["created_at"], l["rin_qty"]))
    return lots


def fifo_allocate(year_row, d_code, rin_qty):
    """Greedy FIFO draw. Returns (allocations, prior_vintage_qty) or None if insufficient."""
    lots = fifo_eligible_lots(year_row, d_code)
    total = sum(l["available_qty"] for l in lots)
    if total < rin_qty:
        return None
    allocations = []
    prior = 0
    remaining = rin_qty
    for lot in lots:
        if remaining <= 0:
            break
        take = min(lot["available_qty"], remaining)
        if take <= 0:
            continue
        allocations.append({"rin_lot_id": lot["id"], "qty": take})
        if lot["vintage_year"] == year_row["year"] - 1:
            prior += take
        remaining -= take
    return allocations, prior


# ---------------------------------------------------------------------------
# lot_rin_conservation: available_qty is derived, never stored stale
# ---------------------------------------------------------------------------
def sync_available(lot):
    """available_qty = rin_qty - pending - retired - invalidated - expired.

    Per PRD §3.2 and the rin_generation_qty calculation, available_qty equals
    rin_qty at generation (when attached_qty == rin_qty) and is unchanged by
    separation — so attached_qty is NOT subtracted here. Separation moves
    attached -> separated and leaves available_qty unchanged; retirement
    pending/accept, invalidation, and expiry are what reduce available_qty.
    """
    lot["available_qty"] = (
        lot["rin_qty"]
        - lot["pending_retired_qty"]
        - lot["retired_qty"]
        - lot["invalidated_qty"]
        - lot["expired_qty"]
    )


# ---------------------------------------------------------------------------
# posture_derivation
# ---------------------------------------------------------------------------
def derive_posture(year_row):
    """SATISFIED / SHORTFALL / ON_TRACK per the derivation rule."""
    satisfied = True
    for category in _CATEGORY_SUFFIX:
        suffix = _CATEGORY_SUFFIX[category]
        if year_row[f"retired_{suffix}_rins"] < (active_rvo(year_row, category) or 0):
            satisfied = False
            break
    if satisfied:
        return "SATISFIED"
    deadline = db.march31_deadline(year_row["year"] + 1)
    if db.now_utc() > deadline:
        return "SHORTFALL"
    return "ON_TRACK"


def rederive_posture(year_row, bump_version=False):
    now = db.now_utc()
    year_row["compliance_posture"] = derive_posture(year_row)
    if bump_version:
        year_row["version"] += 1
        year_row["updated_at"] = now


# ---------------------------------------------------------------------------
# state_credit_generation
# ---------------------------------------------------------------------------
ENERGY_DENSITY_MJ_PER_GAL = Decimal("120.0")


def compute_credits_tons(ci_standard, ci_used, fuel_gallons):
    """round_half_up((standard - ci_used) * 120.0 * gallons / 1_000_000, 4 dp)."""
    value = (_d(ci_standard) - _d(ci_used)) * ENERGY_DENSITY_MJ_PER_GAL * _d(fuel_gallons) / Decimal("1000000")
    return round_half_up_4dp(value)


def rederive_program_total(program):
    """total_credits_tons = sum of credits_tons over the program's reports, 4dp half-up after summing."""
    total = Decimal("0")
    for rpt in db.state_credit_reports.values():
        if rpt["state_program_id"] == program["id"]:
            total += _d(rpt["credits_tons"])
    program["total_credits_tons"] = round_half_up_4dp(total)
