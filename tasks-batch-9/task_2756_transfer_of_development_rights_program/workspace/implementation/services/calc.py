"""Calculation rules (PRD 1.3 / 3.x). Decimal throughout, integer cents."""

from decimal import Decimal

from core import dec, rhu, floor_int, q2, add_days, day_of, db, sort_rows

SOIL_MULTIPLIER = {
    "PRIME": Decimal("1.25"),
    "STATEWIDE": Decimal("1.10"),
    "LOCAL": Decimal("1.00"),
    "NONE": Decimal("0.75"),
}

FINDING_WEIGHT = {"COMPLIANT": Decimal("0"), "MINOR_VIOLATION": Decimal("40"), "MAJOR_VIOLATION": Decimal("90")}

BANK_RESALE_MARKUP = Decimal("1.05")     # +500 bps
BANK_PURCHASE_DISCOUNT = Decimal("0.97")  # -300 bps
PRICE_BAND_BPS = 3000
REVERSAL_WINDOW_DAYS = 30
INSPECTION_WINDOW_DAYS = 90


# ---------------------------------------------------------------------------
# 1. parcel_baseline_allocation
# ---------------------------------------------------------------------------
def parcel_baseline_allocation(area, gross_acres, constrained_acres, soil_class, existing_dwelling_units):
    multiplier = SOIL_MULTIPLIER[soil_class]
    if area["allocation_formula_version"] == "V1_NET_ACRE":
        eligible = dec(gross_acres) - dec(constrained_acres)
    else:
        eligible = dec(gross_acres) * dec(area["gross_discount_factor"])
    raw = eligible * dec(area["base_rate_units_per_acre"]) * multiplier
    return max(0, floor_int(raw) - int(existing_dwelling_units))


# ---------------------------------------------------------------------------
# 2. severance_allocation_grant
# ---------------------------------------------------------------------------
def severance_allocation_grant(requested_units, parcel_available, area_available):
    allocated = min(int(requested_units), int(parcel_available), int(area_available))
    residual = int(parcel_available) - allocated
    return allocated, residual


# ---------------------------------------------------------------------------
# 3. easement_restriction_extent
# ---------------------------------------------------------------------------
def easement_restriction_extent(gross_acres, baseline_units, cumulative_severed, existing_dwelling_units):
    if int(baseline_units) <= 0:
        restricted = q2(0)
    else:
        restricted = rhu(dec(gross_acres) * dec(cumulative_severed) / dec(baseline_units), 2)
    permitted = int(existing_dwelling_units) + (int(baseline_units) - int(cumulative_severed))
    return restricted, permitted


# ---------------------------------------------------------------------------
# 4. receiving_bonus_units
# ---------------------------------------------------------------------------
def site_tier_factor(site_acres):
    acres = dec(site_acres)
    if acres >= dec("10.00"):
        return Decimal("1.00")
    if acres >= dec("3.00"):
        return Decimal("0.90")
    return Decimal("0.75")


def bonus_sizing(area, site_acres, requested_bonus_units):
    """Two separate floors: base_units first, then the bonus ceiling."""
    base_units = floor_int(dec(site_acres) * dec(area["base_density_units_per_acre"]))
    tier = site_tier_factor(site_acres)
    max_bonus_units = floor_int(dec(base_units) * dec(area["max_bonus_pct"]) * tier)
    required_backing_units = min(int(requested_bonus_units), max_bonus_units)
    provisional_bonus_units = min(int(requested_bonus_units), floor_int(dec(max_bonus_units) * dec("0.5")))
    return base_units, max_bonus_units, required_backing_units, provisional_bonus_units


def final_bonus_units(requested_bonus_units, max_bonus_units, backed_units):
    return min(int(requested_bonus_units), int(max_bonus_units), int(backed_units))


# ---------------------------------------------------------------------------
# 5. appraisal_reference_value
# ---------------------------------------------------------------------------
def select_appraisal_schedule(neighborhood_code, at):
    candidates = []
    for row in db.appraisal_schedules.values():
        if row["neighborhood_code"] != neighborhood_code:
            continue
        if row["status"] != "ACTIVE":
            continue
        if row["effective_from"] > at:
            continue
        if row["effective_to"] is not None and not (at < row["effective_to"]):
            continue
        candidates.append(row)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (-r["effective_from"].timestamp(), r["created_at"], r["_seq"]))
    return candidates[0]


def per_unit_base_cents(schedule):
    adjusted = dec(schedule["per_unit_value_cents"]) * (
        dec(1) + dec(schedule["equity_adjustment_bps"]) / dec(10000)
    )
    return int(rhu(adjusted, 0))


def appraised_reference_cents(per_unit_cents, units):
    return int(per_unit_cents) * int(units)


# ---------------------------------------------------------------------------
# 6. bank_channel_price
# ---------------------------------------------------------------------------
def channel_gross_cents(channel, per_unit_cents, units, agreed_price_cents):
    if channel == "PRIVATE":
        return int(agreed_price_cents)
    if channel == "BANK_RESALE":
        unit_price = int(rhu(dec(per_unit_cents) * BANK_RESALE_MARKUP, 0))
        return unit_price * int(units)
    unit_price = int(rhu(dec(per_unit_cents) * BANK_PURCHASE_DISCOUNT, 0))
    return unit_price * int(units)


# ---------------------------------------------------------------------------
# 7. settlement_split
# ---------------------------------------------------------------------------
EQUITY_SURCHARGE_BPS = {"HIGH_VALUE": 150, "MODERATE": 75, "UNDERSERVED": 0}


def program_fee_bps(gross_cents):
    if int(gross_cents) <= 5000000:
        return 350
    if int(gross_cents) <= 25000000:
        return 275
    return 200


def settlement_split(gross_cents, equity_tier):
    fee_bps = program_fee_bps(gross_cents)
    fee = int(rhu(dec(gross_cents) * dec(fee_bps) / dec(10000), 0))
    surcharge_bps = EQUITY_SURCHARGE_BPS.get(equity_tier, 0)
    surcharge = int(rhu(dec(gross_cents) * dec(surcharge_bps) / dec(10000), 0))
    net = int(gross_cents) - fee - surcharge
    return fee, surcharge, net


# ---------------------------------------------------------------------------
# 8. price_deviation_band
# ---------------------------------------------------------------------------
def price_deviation_bps(gross_cents, reference_cents):
    if int(reference_cents) == 0:
        return 0
    return int(rhu((dec(gross_cents) - dec(reference_cents)) / dec(reference_cents) * dec(10000), 0))


def deviation_within_band(bps):
    return abs(int(bps)) <= PRICE_BAND_BPS


# ---------------------------------------------------------------------------
# 9. violation_severity_score
# ---------------------------------------------------------------------------
def violation_severity(finding, affected_acres, restricted_acres, prior_violation_count):
    weight = FINDING_WEIGHT[finding]
    restricted = dec(restricted_acres)
    affected = dec(affected_acres)
    if restricted <= 0:
        acre_ratio = Decimal("1") if affected > 0 else Decimal("0")
    else:
        acre_ratio = min(Decimal("1"), affected / restricted)
    prior_component = min(Decimal("100"), dec(prior_violation_count) * Decimal("25"))
    score = rhu(
        Decimal("0.5") * weight
        + Decimal("0.3") * (acre_ratio * Decimal("100"))
        + Decimal("0.2") * prior_component,
        2,
    )
    return score


def cure_days_for(score):
    value = dec(score)
    if value >= dec("70.00"):
        return 30
    if value >= dec("45.00"):
        return 60
    return 90


# ---------------------------------------------------------------------------
# 10. program_evaluation_metrics
# ---------------------------------------------------------------------------
def program_evaluation_metrics(period_start, period_end, equity_weighting):
    start = day_of(period_start)
    end = day_of(period_end)

    def in_window(value):
        return value is not None and start <= day_of(value) <= end

    easements = [
        e
        for e in db.conservation_easements.values()
        if e["recording_status"] in ("RECORDED", "AMENDED") and in_window(e["recorded_at"])
    ]
    preserved = dec(0)
    for e in easements:
        preserved += dec(e["restricted_acres"])
    preserved_acres = q2(preserved)
    easement_count = len(easements)

    certificates = [c for c in db.certificates.values() if in_window(c["issued_at"])]
    issued_units = sum(int(c["units_face"]) for c in certificates)
    retired_units = sum(int(c["units_retired"]) for c in certificates)

    redeemed_units = sum(
        int(r["units"])
        for r in db.certificate_redemptions.values()
        if r["status"] == "CONFIRMED" and in_window(r["confirmed_at"])
    )

    outstanding_units = issued_units - redeemed_units - retired_units

    areas = [a for a in db.receiving_areas.values() if a["status"] in ("ACTIVE", "SUSPENDED")]
    absorbed_total = sum(int(a["absorbed_units"]) for a in areas)
    cap_total = sum(int(a["absorption_cap_units"]) for a in areas)
    absorption_pct = q2(0) if cap_total == 0 else rhu(dec(absorbed_total) / dec(cap_total) * dec(100), 2)

    total_cash_cents = 0
    for p in db.parties.values():
        total_cash_cents += int(p["cash_balance_cents"]) + int(p["fee_revenue_cents"])

    underserved = []
    for e in easements:
        parcel = db.sending_parcels.get(e["sending_parcel_id"])
        area = db.sending_areas.get(parcel["sending_area_id"]) if parcel else None
        if area is not None and area["equity_tier"] == "UNDERSERVED":
            underserved.append(e)

    if equity_weighting == "ACREAGE_WEIGHTED":
        under_acres = dec(0)
        for e in underserved:
            under_acres += dec(e["restricted_acres"])
        equity_index = q2(0) if preserved_acres == 0 else rhu(under_acres / dec(preserved_acres) * dec(100), 2)
    else:
        equity_index = (
            q2(0) if easement_count == 0 else rhu(dec(len(underserved)) / dec(easement_count) * dec(100), 2)
        )

    return {
        "preserved_acres": preserved_acres,
        "easement_count": easement_count,
        "issued_units": issued_units,
        "redeemed_units": redeemed_units,
        "retired_units": retired_units,
        "absorption_pct": absorption_pct,
        "equity_index": equity_index,
        "outstanding_units": outstanding_units,
        "total_cash_cents": total_cash_cents,
    }
