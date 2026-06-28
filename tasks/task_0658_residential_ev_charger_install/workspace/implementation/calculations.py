"""Calculation rules (SCAFFOLD §1.3, PRD §3.2, §3.4, §3.8).

All money is integer cents; all electrical loads are integer VA. Fractional terms
are rounded half up via Decimal/ROUND_HALF_UP — never float.
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a Decimal (or numeric) to the nearest whole integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- panel load constants (NEC 220.83 / 220.87) ---
GENERAL_VA_PER_SQFT = 3
SMALL_APPLIANCE_CIRCUITS_VA = 1500
SMALL_APPLIANCE_CIRCUIT_COUNT = 2
LAUNDRY_VA = 1500
STD_FIRST_TIER_VA = 8000
STD_REMAINDER_FACTOR = Decimal("0.40")
LOAD_STUDY_FACTOR = Decimal("1.25")
CONTINUOUS_FACTOR = Decimal("1.25")


def panel_capacity_va(service_voltage, main_breaker_amps):
    return service_voltage * main_breaker_amps


def existing_demand_va(assessment_method, floor_area_sqft, declared_fixed_appliance_va,
                       max_measured_demand_va):
    """Existing demand under the chosen NEC method (PRD §3.2)."""
    if assessment_method == "STANDARD_220_83":
        general_va = floor_area_sqft * GENERAL_VA_PER_SQFT
        small_appliance_va = SMALL_APPLIANCE_CIRCUIT_COUNT * SMALL_APPLIANCE_CIRCUITS_VA
        laundry_va = LAUNDRY_VA
        other_total_va = (general_va + small_appliance_va + laundry_va
                          + declared_fixed_appliance_va)
        # NEC 220.83(A): first 8000 VA at 100%, remainder at 40%.
        remainder = other_total_va - STD_FIRST_TIER_VA
        if remainder <= 0:
            # When the combined total is at or below 8000, the remainder term is
            # zero (negative remainder * 0.40 would understate). Existing demand is
            # 8000 + round_half_up(0.40 * remainder); for remainder<=0 we follow the
            # literal formula (8000 + 0.40*remainder could go below total). The
            # formula is pinned as written: 8000 + round_half_up(0.40*(total-8000)).
            return STD_FIRST_TIER_VA + round_half_up(STD_REMAINDER_FACTOR * Decimal(remainder))
        return STD_FIRST_TIER_VA + round_half_up(STD_REMAINDER_FACTOR * Decimal(remainder))
    else:  # LOAD_STUDY_220_87
        return round_half_up(LOAD_STUDY_FACTOR * Decimal(max_measured_demand_va))


def charger_required_va(rated_amps, service_voltage):
    """Charger continuous draw: round_half_up(1.25 * rated_amps * service_voltage)."""
    return round_half_up(CONTINUOUS_FACTOR * Decimal(rated_amps) * Decimal(service_voltage))


def compute_assessment(assessment, prop, charger):
    """Compute existing_demand_va, spare_capacity_va, charger_fits in place."""
    cap = panel_capacity_va(prop["service_voltage"], prop["main_breaker_amps"])
    demand = existing_demand_va(
        assessment["assessment_method"],
        prop["floor_area_sqft"],
        assessment["declared_fixed_appliance_va"],
        assessment["max_measured_demand_va"],
    )
    spare = cap - demand
    required = charger_required_va(charger["rated_amps"], prop["service_voltage"])
    assessment["existing_demand_va"] = demand
    assessment["spare_capacity_va"] = spare
    # boundary inclusive: exact equality FITS (>=)
    assessment["charger_fits"] = spare >= required


# --- quote pricing constants ---
DISC_TIER_HI_CENTS = 200000
DISC_TIER_MID_CENTS = 100000
DISC_PCT_HI = Decimal("0.10")
DISC_PCT_MID = Decimal("0.05")
PERMIT_HI_NET_CENTS = 150000
PERMIT_MID_NET_CENTS = 90000
PERMIT_HI_CENTS = 20000
PERMIT_MID_CENTS = 15000
PERMIT_LO_CENTS = 12000
TAX_RATE = Decimal("0.0825")


def quote_tax(parts_line_cents):
    """Per-line round-half-up then sum (PINNED ORDER; labor not taxed)."""
    total = 0
    for line in parts_line_cents:
        total += round_half_up(TAX_RATE * Decimal(line))
    return total


def compute_quote(quote):
    """Compute base_subtotal, discount, tax, permit_fee, quote_total in place.

    Pinned order: discount keyed on subtotal -> net -> permit fee keyed on net
    -> tax (per-line) -> total = net + tax + permit.
    """
    labor = quote["labor_cents"]
    parts = quote["parts_line_cents"]
    base_subtotal = labor + sum(parts)

    if base_subtotal >= DISC_TIER_HI_CENTS:
        disc_pct = DISC_PCT_HI
    elif base_subtotal >= DISC_TIER_MID_CENTS:
        disc_pct = DISC_PCT_MID
    else:
        disc_pct = Decimal("0")
    discount = round_half_up(disc_pct * Decimal(base_subtotal))
    net_after_discount = base_subtotal - discount

    if net_after_discount >= PERMIT_HI_NET_CENTS:
        permit_fee = PERMIT_HI_CENTS
    elif net_after_discount >= PERMIT_MID_NET_CENTS:
        permit_fee = PERMIT_MID_CENTS
    else:
        permit_fee = PERMIT_LO_CENTS

    tax = quote_tax(parts)
    total = net_after_discount + tax + permit_fee

    quote["base_subtotal_cents"] = base_subtotal
    quote["discount_cents"] = discount
    quote["tax_cents"] = tax
    quote["permit_fee_cents"] = permit_fee
    quote["quote_total_cents"] = total


# --- incentive constants ---
FED_RATE = Decimal("0.30")
FED_CAP_CENTS = 100000
BASIC_BASE_CENTS = 25000
PREMIUM_BASE_CENTS = 50000
PANEL_UPGRADE_ADDER_CENTS = 30000
STACK_CAP_PCT = Decimal("0.80")


def incentive_award(program_kind, eligible_cost_cents, utility_program_tier,
                    includes_panel_upgrade, fed_existing):
    """Compute the incentive award (SCAFFOLD §1.3 incentive_award, PRD §3.8).

    fed_existing is the award_cents of this job's FEDERAL_45W claim in
    {SUBMITTED, PAID} (earliest by created_at), else 0 — relevant only for the
    utility branch.
    """
    if program_kind == "FEDERAL_45W":
        return min(round_half_up(FED_RATE * Decimal(eligible_cost_cents)), FED_CAP_CENTS)
    # UTILITY_REBATE
    base = PREMIUM_BASE_CENTS if utility_program_tier == "PREMIUM" else BASIC_BASE_CENTS
    adder = PANEL_UPGRADE_ADDER_CENTS if includes_panel_upgrade else 0
    util_raw = base + adder
    stack_cap = round_half_up(STACK_CAP_PCT * Decimal(eligible_cost_cents))
    if fed_existing + util_raw > stack_cap:
        return max(0, stack_cap - fed_existing)
    return util_raw
