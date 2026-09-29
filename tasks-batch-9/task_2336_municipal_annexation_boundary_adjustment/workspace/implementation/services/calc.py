"""The twelve pinned calculations of PRD §3, expressed once each.

Every quantity is computed with `decimal.Decimal` and `ROUND_HALF_UP`. The rounding
*orders* that PRD §2.7 pins are honoured by the callers: per-consent, per-filing and
per-parcel amounts are rounded by these helpers before any summation happens.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)

SERVICE_TYPE_ORDER = ("POLICE", "FIRE", "WATER", "SEWER")
FY_DAYS = Decimal(365)
QUARTERS_PER_YEAR = Decimal(4)


def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    return Decimal(str(value))


def quantize(value, places):
    return D(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to a whole cent. Money is always an integer in this system."""
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pct2(value):
    return quantize(value, 2)


def ratio4(value):
    return quantize(value, 4)


def acres2(value):
    return quantize(value, 2)


def ceil_int(value):
    value = D(value)
    whole = int(value.to_integral_value(rounding="ROUND_FLOOR"))
    return whole if D(whole) == value else whole + 1


# ---------------------------------------------------------------------------
# 1. territory_qualification (PRD §3.2)
# ---------------------------------------------------------------------------

def territory_aggregates(parcels):
    """parcel_count, territory_acreage (2 dp) and the exact assessed-value sum."""
    acreage = ZERO
    value = 0
    for parcel in parcels:
        acreage += D(parcel["acreage"])
        value += int(parcel["assessed_value_cents"])
    return len(parcels), acres2(acreage), value


def territory_qualification(case, municipality, statute, territory_acreage):
    contiguity_ratio = ratio4(
        D(case["shared_boundary_feet"]) / D(municipality["corporate_boundary_perimeter_feet"])
    )

    total_lots = D(max(int(case["total_lot_count"]), 1))
    developed_ratio = ratio4(D(case["developed_lot_count"]) / total_lots)

    acreage_denominator = max(D(territory_acreage), Decimal("0.01"))
    density = ratio4(D(case["dwelling_units"]) / acreage_denominator)

    min_developed = D(statute["subdivision_test_min_developed_ratio"])
    min_density = D(statute["urban_density_min_units_per_acre"])
    subdivision_limb = developed_ratio >= min_developed
    density_limb = density >= min_density
    urban_qualified = bool(subdivision_limb or density_limb)

    ramp = D(statute["contiguity_min_ratio"]) * 2
    base = HUNDRED * min(ONE, contiguity_ratio / ramp)
    urban_bonus = Decimal(25) if urban_qualified else ZERO
    density_penalty = Decimal(15) if (density < min_density and developed_ratio < min_developed) else ZERO
    excess_miles = ceil_int(D(case["max_service_distance_miles"]) - 3)
    if excess_miles < 0:
        excess_miles = 0
    distance_penalty = Decimal(10) * D(excess_miles)

    index = base + urban_bonus - density_penalty - distance_penalty
    if index > HUNDRED:
        index = HUNDRED
    if index < ZERO:
        index = ZERO

    return {
        "contiguity_ratio": contiguity_ratio,
        "developed_ratio": developed_ratio,
        "density": density,
        "urban_development_qualified": urban_qualified,
        "qualification_index": pct2(index),
    }


# ---------------------------------------------------------------------------
# 2. petition_sufficiency (PRD §3.3)
# ---------------------------------------------------------------------------

def share_value_cents(assessed_value_cents, ownership_share_pct):
    """Per-consent / per-filing rounded share — rounded BEFORE any summation."""
    return cents(D(assessed_value_cents) * D(ownership_share_pct) / HUNDRED)


def petition_sufficiency(petition, statute, qualifying_consents, territory_value_cents, territory_owner_count):
    value_sum = 0
    owners = set()
    for consent in qualifying_consents:
        value_sum += int(consent["qualified_value_cents"])
        owners.add(consent["property_owner_id"])

    owner_count = len(owners)
    if int(territory_value_cents) == 0:
        value_pct = pct2(0)
    else:
        value_pct = pct2(D(value_sum) / D(territory_value_cents) * HUNDRED)
    if int(territory_owner_count) == 0:
        owner_pct = pct2(0)
    else:
        owner_pct = pct2(D(owner_count) / D(territory_owner_count) * HUNDRED)

    measured = value_pct if statute["signature_basis"] == "ASSESSED_VALUE" else owner_pct
    if petition["petition_type"] == "OWNER_100":
        threshold = HUNDRED
    else:
        threshold = D(statute["signature_threshold_pct"])

    return {
        "qualified_signature_assessed_value_cents": value_sum,
        "qualified_signature_owner_count": owner_count,
        "signature_value_pct": value_pct,
        "signature_owner_pct": owner_pct,
        "measured_pct": measured,
        "threshold_pct": threshold,
        "met": measured >= threshold,
    }


# ---------------------------------------------------------------------------
# 3. fiscal_impact_projection (PRD §3.4)
# ---------------------------------------------------------------------------

def overhead_tier_pct(base_service_cost_cents):
    if base_service_cost_cents < 5000000:
        return Decimal("0.12")
    if base_service_cost_cents < 25000000:
        return Decimal("0.09")
    return Decimal("0.06")


def fiscal_impact_projection(analysis, case, municipality, statute, utility_monthly_base_total):
    property_tax = cents(
        D(case["territory_assessed_value_cents"]) * D(municipality["general_fund_millage_rate"]) / Decimal(1000)
    )
    utility_revenue = int(utility_monthly_base_total) * 12
    shared = int(analysis["projected_population"]) * int(statute["per_capita_shared_revenue_cents"])
    gross = property_tax + utility_revenue + shared

    if analysis["analysis_method"] == "AVERAGE_COST":
        base = cents(
            D(municipality["citywide_annual_service_cost_cents"])
            * D(analysis["projected_population"])
            / D(municipality["citywide_population"])
        )
    else:
        base = (
            int(analysis["marginal_police_cost_cents"])
            + int(analysis["marginal_fire_cost_cents"])
            + int(analysis["marginal_water_cost_cents"])
            + int(analysis["marginal_sewer_cost_cents"])
        )

    tier = overhead_tier_pct(base)
    overhead = cents(D(base) * tier)
    projected_cost = base + overhead
    net = gross - projected_cost
    if net >= 0:
        deficit_ratio = pct2(0)
    elif gross == 0:
        deficit_ratio = pct2(100)
    else:
        deficit_ratio = pct2(D(-net) / D(gross) * HUNDRED)

    return {
        "property_tax_revenue_cents": property_tax,
        "projected_utility_revenue_cents": utility_revenue,
        "shared_revenue_cents": shared,
        "gross_annual_revenue_cents": gross,
        "base_service_cost_cents": base,
        "overhead_tier_pct": pct2(tier),
        "administrative_overhead_cents": overhead,
        "projected_annual_service_cost_cents": projected_cost,
        "net_annual_impact_cents": net,
        "deficit_ratio_pct": deficit_ratio,
    }


# ---------------------------------------------------------------------------
# 4. protest_evaluation (PRD §3.6)
# ---------------------------------------------------------------------------

def protest_evaluation(statute, qualifying_filings, territory_value_cents, territory_owner_count):
    value_sum = 0
    owners = set()
    for filing in qualifying_filings:
        value_sum += int(filing["protest_value_cents"])
        owners.add(filing["property_owner_id"])

    if statute["protest_basis"] == "ASSESSED_VALUE":
        if int(territory_value_cents) == 0:
            protest_pct = pct2(0)
        else:
            protest_pct = pct2(D(value_sum) / D(territory_value_cents) * HUNDRED)
    else:
        if int(territory_owner_count) == 0:
            protest_pct = pct2(0)
        else:
            protest_pct = pct2(D(len(owners)) / D(territory_owner_count) * HUNDRED)

    threshold = D(statute["protest_threshold_pct"])
    return {
        "protest_pct": protest_pct,
        "sustained": protest_pct >= threshold,
    }


# ---------------------------------------------------------------------------
# 5. tax_roll_proration (PRD §3.8)
# ---------------------------------------------------------------------------

def parcel_annual_tax_cents(assessed_value_cents, millage_rate):
    return cents(D(assessed_value_cents) * D(millage_rate) / Decimal(1000))


def parcel_prorated_tax_cents(annual_tax_cents, remaining_days):
    return cents(D(annual_tax_cents) * D(remaining_days) / FY_DAYS)


# ---------------------------------------------------------------------------
# 6. plan_service_readiness (PRD §3.5)
# ---------------------------------------------------------------------------

def plan_service_readiness(commitments, required_service_types):
    """`commitments` must already be filtered to ACTIVE / FULFILLED."""
    cost = 0
    covered = set()
    for commitment in commitments:
        cost += int(commitment["cost_cents"])
        covered.add(commitment["service_type"])

    ordered_types = [t for t in SERVICE_TYPE_ORDER if t in covered]
    if not commitments:
        readiness = "PENDING"
    elif all(t in covered for t in required_service_types) and all(
        c["commitment_status"] == "FULFILLED" for c in commitments
    ):
        readiness = "READY"
    else:
        readiness = "PARTIAL"

    return {
        "committed_cost_cents": cost,
        "covered_service_types": ordered_types,
        "service_readiness": readiness,
    }


# ---------------------------------------------------------------------------
# 7. provider_capacity_encumbrance (PRD §3.5)
# ---------------------------------------------------------------------------

def timeline_days(window_start_date, window_end_date):
    return (window_end_date - window_start_date).days + 1


def capacity_admissible(candidate_start, candidate_end, peers, concurrent_project_capacity):
    """Closed-interval, day-by-day admission test. Touching windows do overlap."""
    day = candidate_start
    while day <= candidate_end:
        occupying = 1
        for start, end in peers:
            if start <= day <= end:
                occupying += 1
        if occupying > int(concurrent_project_capacity):
            return False
        day += timedelta(days=1)
    return True


def encumbered_days(commitments):
    return sum(int(c["timeline_days"]) for c in commitments)


# ---------------------------------------------------------------------------
# 8. hearing_chamber_occupation (PRD §3.6)
# ---------------------------------------------------------------------------

def chamber_conflict(candidate_start, candidate_end, peer_start, peer_end, buffer_minutes):
    buffer = timedelta(minutes=int(buffer_minutes))
    return candidate_start < peer_end + buffer and peer_start < candidate_end + buffer


# ---------------------------------------------------------------------------
# 9. de_annexation_refund (PRD §3.9)
# ---------------------------------------------------------------------------

def quarters_remaining(effective_date):
    quarter = (effective_date.month - 1) // 3 + 1
    return 5 - quarter


def de_annexation_refund_cents(basis, posted_tax_cents, effective_date, fiscal_year_end_date):
    if basis == "DAILY_PRORATION":
        remaining_days = (fiscal_year_end_date - effective_date).days + 1
        return cents(D(posted_tax_cents) * D(remaining_days) / FY_DAYS)
    remaining = quarters_remaining(effective_date)
    return cents(D(posted_tax_cents) * D(remaining) / QUARTERS_PER_YEAR)


# ---------------------------------------------------------------------------
# 10. msd_assessment (PRD §3.9)
# ---------------------------------------------------------------------------

def msd_assessment_cents(committed_cost_cents, msd_cost_recovery_pct):
    return cents(D(committed_cost_cents) * D(msd_cost_recovery_pct))


# ---------------------------------------------------------------------------
# 11. utility_effective_rate (PRD §3.8)
# ---------------------------------------------------------------------------

def utility_effective_monthly_cents(monthly_base_cents, rate_schedule, outside_surcharge_pct):
    if rate_schedule == "OUTSIDE_CITY_SURCHARGE":
        return cents(D(monthly_base_cents) * (ONE + D(outside_surcharge_pct)))
    return int(monthly_base_cents)


# ---------------------------------------------------------------------------
# 12. effective_date_admissibility (PRD §3.8)
# ---------------------------------------------------------------------------

def next_quarter_start(reference_date):
    quarter = (reference_date.month - 1) // 3 + 1
    if quarter == 4:
        return date(reference_date.year + 1, 1, 1)
    return date(reference_date.year, quarter * 3 + 1, 1)


def effective_date_admissible(rule, submitted, clock_date, fiscal_year_end_date):
    if rule == "IMMEDIATE":
        return submitted == clock_date
    if rule == "NEXT_QUARTER_START":
        return submitted == next_quarter_start(clock_date)
    return submitted == fiscal_year_end_date + timedelta(days=1)
