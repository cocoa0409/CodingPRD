from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

SQFT_PER_KW = Decimal("70")
USAGE_OFFSET = Decimal("1.0")
SYSTEM_DERATE = Decimal("0.80")
ITC_RATE = Decimal("0.30")
ITC_RATE_CAP = Decimal("0.40")
STATE_ADDER = {
    "CA": Decimal("0.00"),
    "NJ": Decimal("0.10"),
    "MA": Decimal("0.10"),
    "TX": Decimal("0.00"),
    "AZ": Decimal("0.10"),
}


def _round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _floor_2dp(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)


def design_feasible(peak_sun_hours, shading_factor):
    """ERR_DESIGN_INFEASIBLE when peak_sun_hours == 0 or (1 - shading) == 0."""
    psh = Decimal(str(peak_sun_hours))
    sh = Decimal(str(shading_factor))
    if psh == 0:
        return False
    if (Decimal("1.0") - sh) == 0:
        return False
    return True


def size_system(roof_area_sqft, annual_kwh_usage, peak_sun_hours, shading_factor):
    area_cap = _floor_2dp(Decimal(roof_area_sqft) / SQFT_PER_KW)
    psh = Decimal(str(peak_sun_hours))
    sh = Decimal(str(shading_factor))
    usage_target = (Decimal(annual_kwh_usage) * USAGE_OFFSET) / (
        psh * Decimal("365") * (Decimal("1.0") - sh)
    )
    usage_target = _floor_2dp(usage_target)
    size = min(area_cap, usage_target)
    return float(size)


def estimate_production(system_size_kw, peak_sun_hours, shading_factor):
    val = (
        Decimal(str(system_size_kw))
        * Decimal(str(peak_sun_hours))
        * Decimal("365")
        * (Decimal("1.0") - Decimal(str(shading_factor)))
        * SYSTEM_DERATE
    )
    return _round_half_up(val)


def itc_credit(gross_system_cost_cents, state_code):
    adder = STATE_ADDER.get(state_code, Decimal("0.00"))
    effective = ITC_RATE + adder
    if effective > ITC_RATE_CAP:
        effective = ITC_RATE_CAP
    return _round_half_up(Decimal(gross_system_cost_cents) * effective)


def financing_monthly_payment(plan, project):
    model = plan["model"]
    if model == "LEASE":
        return int(plan["lease_monthly_cents"])
    if model == "LOAN":
        principal = Decimal(plan["loan_principal_cents"])
        r = Decimal(str(plan["loan_apr"])) / Decimal("12")
        n = int(plan["term_years"]) * 12
        if r == 0:
            return _round_half_up(principal / Decimal(n))
        one_plus = (Decimal("1") + r)
        factor = (r * (one_plus ** n)) / ((one_plus ** n) - Decimal("1"))
        return _round_half_up(principal * factor)
    if model == "PPA":
        annual = Decimal(str(project["estimated_annual_production_kwh"])) * Decimal(
            str(plan["ppa_rate_cents_per_kwh"])
        )
        return _round_half_up(annual / Decimal("12"))
    return 0


def srec_sale_settlement(srec_count, price_cents_per_srec, broker_fee_pct):
    gross = srec_count * int(price_cents_per_srec)
    fee = _round_half_up(Decimal(gross) * Decimal(str(broker_fee_pct)))
    net = gross - fee
    return gross, net


def net_metering_settlement(kwh_produced, kwh_consumed, bank_before, utility):
    rate = Decimal(str(utility["net_metering_rate_cents_per_kwh"]))
    ratio = Decimal(str(utility["export_credit_ratio"]))
    net_kwh = int(kwh_produced) - int(kwh_consumed)
    if net_kwh >= 0:
        export_kwh = net_kwh
        credited = export_kwh  # whole kWh already (integers)
        bill_credit = _round_half_up(Decimal(credited) * rate * ratio)
        bank_after = bank_before + export_kwh
    else:
        deficit = -net_kwh
        drawn = min(bank_before, deficit)
        bank_after = bank_before - drawn
        billable = deficit - drawn
        bill_credit = -_round_half_up(Decimal(billable) * rate)
    return net_kwh, bill_credit, bank_after


def production_shortfall_eval(claim, project, periods, policy, utility):
    if claim["claim_type"] == "EQUIPMENT_DEFECT":
        measured = 0
    else:
        ws = claim["claimed_window_start"]
        we = claim["claimed_window_end"]
        measured = sum(
            int(p["kwh_produced"])
            for p in periods
            if p["status"] == "SETTLED"
            and p["project_id"] == project["id"]
            and p["period_start"] >= ws
            and p["period_end"] <= we
        )
    guaranteed = int(
        (
            Decimal(str(project["estimated_annual_production_kwh"]))
            * Decimal(str(policy["production_guarantee_pct"]))
        ).quantize(Decimal("1"), rounding=ROUND_FLOOR)
    )
    shortfall = max(0, guaranteed - measured)
    rate = Decimal(str(utility["net_metering_rate_cents_per_kwh"]))
    payout = _round_half_up(Decimal(shortfall) * rate)
    return measured, shortfall, payout
