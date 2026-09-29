"""Pinned calculation rules (PRD sections 2.7, 2.10, 3.x)."""
from decimal import Decimal

from util import (
    anniversary_count,
    dec,
    floor_int,
    rhu,
    rhu3,
    rhu_cents,
)

# --- constants -------------------------------------------------------------
WIND_COEFF_LBS_PER_SQFT = Decimal(30)
ELEV_TIER_1_LIMIT_FT = Decimal(100)
ELEV_TIER_2_LIMIT_FT = Decimal(200)
ELEV_MULT_TIER_1 = Decimal("1.00")
ELEV_MULT_TIER_2 = Decimal("1.25")
ELEV_MULT_TIER_3 = Decimal("1.50")

STRUCTURAL_PASS_LIMIT_PCT = Decimal("95.0")
STRUCTURAL_CAPACITY_LIMIT_PCT = Decimal("100.0")
RESTRICTED_LOAD_PCT = Decimal("90.0")

STANDARD_REVIEW_DAYS = 45
SLA_CREDIT_PCT = Decimal("0.25")

ESCALATION_CAP_MULTIPLE = Decimal("1.50")

ENG_FEE_PCT = Decimal("0.12")
DISCOUNT_TIER_1_CENTS = 10000000
DISCOUNT_TIER_2_CENTS = 25000000
DISCOUNT_TIER_1_PCT = Decimal("0.015")
DISCOUNT_TIER_2_PCT = Decimal("0.03")

RETRO_CAP_MONTHS = 24
UNAUTHORIZED_RATE_CENTS_PER_LOAD_UNIT = Decimal(25)
UNAUTHORIZED_PENALTY_MULTIPLIER = Decimal("1.5")

DELINQUENCY_THRESHOLD_CENTS = 5000000

ELEVATION_SEPARATION_BUFFER_FT = Decimal(10)
RENEWAL_WINDOW_DAYS = 365


# --- equipment line load ---------------------------------------------------

def elevation_multiplier(mount_elevation_ft):
    elev = dec(mount_elevation_ft)
    if elev < ELEV_TIER_1_LIMIT_FT:
        return ELEV_MULT_TIER_1
    if elev < ELEV_TIER_2_LIMIT_FT:
        return ELEV_MULT_TIER_2
    return ELEV_MULT_TIER_3


def equipment_line_load_units(unit_weight_lbs, wind_area_sqft, quantity, mount_elevation_ft):
    raw = ((dec(unit_weight_lbs) + WIND_COEFF_LBS_PER_SQFT * dec(wind_area_sqft))
           * dec(quantity) * elevation_multiplier(mount_elevation_ft))
    return rhu3(raw)


# --- structural analysis ---------------------------------------------------

def loading_pct(included_load_units, rated_capacity_load_units):
    rated = dec(rated_capacity_load_units)
    if rated == 0:
        return rhu3(0)
    return rhu3(Decimal(100) * dec(included_load_units) / rated)


def analysis_result(projected_loading_pct):
    pct = dec(projected_loading_pct)
    if pct <= STRUCTURAL_PASS_LIMIT_PCT:
        return "PASS"
    if pct < STRUCTURAL_CAPACITY_LIMIT_PCT:
        return "MODIFICATION_REQUIRED"
    return "CAPACITY_EXCEEDED"


# --- rent ------------------------------------------------------------------

def ground_lease_rent_at(base_monthly_rent_cents, escalator_pct, commencement_date, as_of):
    """Simple (non-compound) escalation, rounded exactly once."""
    n = anniversary_count(commencement_date, as_of)
    factor = Decimal(1) + dec(escalator_pct) / Decimal(100) * Decimal(n)
    return rhu_cents(dec(base_monthly_rent_cents) * factor)


def amendment_rent_at(base_monthly_rent_cents, escalator_pct, effective_date, as_of):
    """Compound escalation, rounded to whole cents at every anniversary, capped."""
    n = anniversary_count(effective_date, as_of)
    running = dec(base_monthly_rent_cents)
    step = Decimal(1) + dec(escalator_pct) / Decimal(100)
    for _ in range(n):
        running = rhu(running * step, 0)
    cap = rhu(dec(base_monthly_rent_cents) * ESCALATION_CAP_MULTIPLE, 0)
    return int(min(running, cap))


# --- SLA credit ------------------------------------------------------------

def sla_credit_cents(mla_base_monthly_rent_cents):
    return rhu_cents(dec(mla_base_monthly_rent_cents) * SLA_CREDIT_PCT)


# --- modification project cost pipeline ------------------------------------

def project_total_cost(base_construction_cents):
    """Seven pinned steps; the discount tier is chosen once, never re-derived."""
    base_construction = dec(base_construction_cents)
    base_engineering_fee = rhu_cents(base_construction * ENG_FEE_PCT)
    base_total = int(base_construction) + base_engineering_fee
    if base_total >= DISCOUNT_TIER_2_CENTS:
        discount_pct = DISCOUNT_TIER_2_PCT
    elif base_total >= DISCOUNT_TIER_1_CENTS:
        discount_pct = DISCOUNT_TIER_1_PCT
    else:
        discount_pct = Decimal(0)
    final_construction = int(base_construction) - rhu_cents(base_construction * discount_pct)
    engineering_fee = rhu_cents(dec(final_construction) * ENG_FEE_PCT)
    total_cost = final_construction + engineering_fee
    return {
        "base_construction_cost_cents": int(base_construction),
        "volume_discount_pct": discount_pct,
        "engineering_fee_cents": engineering_fee,
        "total_cost_cents": total_cost,
    }


def allocate_shares(total_cost_cents, beneficiaries, basis):
    """Floor each share, then hand the whole remainder to one beneficiary.

    `beneficiaries` is a list of dicts carrying basis_load_units,
    basis_created_at, basis_seq, tenant_created_at and tenant_seq.
    Returns a parallel list of integer share amounts.
    """
    total_cost = dec(total_cost_cents)
    total_basis = sum((dec(b["basis_load_units"]) for b in beneficiaries), Decimal(0))
    shares = []
    for b in beneficiaries:
        if basis == "EQUAL_SHARE":
            shares.append(floor_int(total_cost / Decimal(len(beneficiaries))))
        else:
            shares.append(floor_int(total_cost * dec(b["basis_load_units"]) / total_basis))
    remainder = int(total_cost) - sum(shares)
    if beneficiaries:
        order = sorted(
            range(len(beneficiaries)),
            key=lambda i: (
                beneficiaries[i]["basis_created_at"],
                beneficiaries[i]["basis_seq"],
                beneficiaries[i]["tenant_created_at"],
                beneficiaries[i]["tenant_seq"],
                dec(beneficiaries[i]["basis_load_units"]),
            ),
        )
        shares[order[0]] += remainder
    return shares


# --- retroactive unauthorized billing --------------------------------------

def retro_months(audit_date, installed_on_date, basis):
    gross = 12 * (audit_date.year - installed_on_date.year) + (audit_date.month - installed_on_date.month)
    if audit_date.day < installed_on_date.day:
        gross -= 1
    gross = max(gross, 0)
    if basis == "DISCOVERY_LIMITED":
        return min(gross, RETRO_CAP_MONTHS)
    return gross


def retro_billing_cents(months_billable, observed_load_units):
    monthly_rate = rhu_cents(UNAUTHORIZED_RATE_CENTS_PER_LOAD_UNIT * dec(observed_load_units))
    return rhu_cents(dec(months_billable) * dec(monthly_rate) * UNAUTHORIZED_PENALTY_MULTIPLIER)
