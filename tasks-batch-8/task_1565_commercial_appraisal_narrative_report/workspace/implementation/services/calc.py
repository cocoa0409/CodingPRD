from decimal import Decimal, ROUND_HALF_UP

# --- Constants from the scaffold calculations table ---
FEE_BASE_CENTS = {"LOW": 250000, "STANDARD": 450000, "HIGH": 900000}
MIN_TURNAROUND_DAYS = {"LOW": 10, "STANDARD": 15, "HIGH": 25}
EXPEDITED_THRESHOLD_DAYS = {"LOW": 20, "STANDARD": 30, "HIGH": 45}
PER_SF_RATE_CENTS = {"LOW": 12, "STANDARD": 18, "HIGH": 30}
SIZE_SURCHARGE_THRESHOLD_SF = 50000
SIZE_SURCHARGE_BLOCK_SF = 10000
SIZE_SURCHARGE_PER_BLOCK_CENTS = 15000
APPROACH_ADDON_CENTS = 75000
EXPEDITED_MULTIPLIER = "1.25"
EXPEDITED_FLAT_CENTS = 100000
VOLUME_TIER_1_THRESHOLD_CENTS = 5000000
VOLUME_TIER_2_THRESHOLD_CENTS = 15000000
MARKET_VACANCY_RATE = "0.05"
MIN_EXPENSE_RATIO = "0.30"
RESERVE_RATE = "0.02"
SUPPORT_TOLERANCE_BPS = 25
HIGH_TIER_SF = 100000
LOW_TIER_SF = 10000


def D(v):
    return v if isinstance(v, Decimal) else Decimal(str(v))


def rhu(x):
    """Round half-up to whole cents (integer)."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def complexity_tier(property_type, building_sf, intended_use):
    if (
        property_type == "SPECIAL_PURPOSE"
        or intended_use == "LITIGATION"
        or building_sf >= HIGH_TIER_SF
    ):
        return "HIGH"
    if (
        building_sf < LOW_TIER_SF
        and property_type in ("RETAIL", "INDUSTRIAL")
        and intended_use == "FINANCING"
    ):
        return "LOW"
    return "STANDARD"


def minimum_turnaround_days(tier):
    return MIN_TURNAROUND_DAYS[tier]


def volume_discount_tier(total_billed_cents):
    if total_billed_cents >= VOLUME_TIER_2_THRESHOLD_CENTS:
        return "TIER_2"
    if total_billed_cents >= VOLUME_TIER_1_THRESHOLD_CENTS:
        return "TIER_1"
    return "NONE"


def _volume_discount_pct(total_billed_cents):
    if total_billed_cents >= VOLUME_TIER_2_THRESHOLD_CENTS:
        return D("0.10")
    if total_billed_cents >= VOLUME_TIER_1_THRESHOLD_CENTS:
        return D("0.05")
    return D("0")


def fee_quote(eng, client):
    """Pinned evaluation order: (1) pre-discount subtotal from the engagement's
    own fields; (2) discount pct from client.total_billed_cents as it stands now;
    (3) fee = round_half_up(pre_discount * (1 - discount_pct))."""
    tier = eng["complexity_tier"]
    expedited = eng["requested_turnaround_days"] < EXPEDITED_THRESHOLD_DAYS[tier]
    if eng["fee_schedule"] == "PER_SF":
        pre_discount = PER_SF_RATE_CENTS[tier] * eng["building_sf"] + (
            EXPEDITED_FLAT_CENTS if expedited else 0
        )
    else:  # TIERED
        base = FEE_BASE_CENTS[tier]
        sf = eng["building_sf"]
        size_surcharge = 0
        if sf > SIZE_SURCHARGE_THRESHOLD_SF:
            excess = sf - SIZE_SURCHARGE_THRESHOLD_SF
            blocks = (excess + SIZE_SURCHARGE_BLOCK_SF - 1) // SIZE_SURCHARGE_BLOCK_SF
            size_surcharge = blocks * SIZE_SURCHARGE_PER_BLOCK_CENTS
        approach_addon = max(0, eng["planned_approach_count"] - 1) * APPROACH_ADDON_CENTS
        subtotal = base + size_surcharge + approach_addon
        pre_discount = (
            rhu(D(subtotal) * D(EXPEDITED_MULTIPLIER)) if expedited else subtotal
        )
    discount_pct = _volume_discount_pct(client["total_billed_cents"])
    return rhu(D(pre_discount) * (D(1) - discount_pct))


def noi_variants(sub):
    """Returns (noi_trailing_cents, noi_stabilized_cents); stabilized steps are
    pinned and each rounded half-up to whole cents."""
    sgr = sub["scheduled_gross_rent_cents"]
    vac = sub["vacancy_loss_cents"]
    reimb = sub["expense_reimbursements_cents"]
    opex = sub["operating_expenses_cents"]
    trailing = sgr - vac + reimb - opex
    effective_gross = rhu(D(sgr) * (D(1) - D(MARKET_VACANCY_RATE)))
    stabilized_expenses = max(opex, rhu(D(sgr) * D(MIN_EXPENSE_RATIO)))
    reserves = rhu(D(sgr) * D(RESERVE_RATE))
    stabilized = effective_gross + reimb - stabilized_expenses - reserves
    return trailing, stabilized


def comparable_rates(sale_price_cents, noi_at_sale_cents, adjustment_pct):
    implied = rhu(D(noi_at_sale_cents) * 10000 / D(sale_price_cents))
    adjusted = rhu(D(implied) * (1 + D(adjustment_pct) / 100))
    return implied, adjusted


def supported_cap_rate_bps(comps):
    sel = [c for c in comps if c["selected_for_support"]]
    if not sel:
        return None
    return rhu(D(sum(c["adjusted_cap_rate_bps"] for c in sel)) / D(len(sel)))


def evidence_statement(subs):
    """The engagement's ACCEPTED OPERATING_STATEMENT with the greatest
    period_end; tie-break: greatest created_at (then creation sequence)."""
    cands = [
        s
        for s in subs
        if s["submission_type"] == "OPERATING_STATEMENT" and s["status"] == "ACCEPTED"
    ]
    if not cands:
        return None
    return max(
        cands, key=lambda s: (s["_period_end_dt"], s["created_at"], s["_seq"])
    )


def direct_cap_value(stmt, cap_rate_bps):
    return rhu(D(stmt["noi_stabilized_cents"]) * 10000 / D(cap_rate_bps))


def dcf_value(stmt, approach):
    """Each annual PV rounded half-up to cents first, then summed; terminal value
    rounded half-up once. DCF supersedes direct capitalization."""
    y1 = D(stmt["noi_trailing_cents"])
    g = D(approach["revenue_growth_bps_annual"]) / 10000
    r = D(approach["dcf_discount_rate_bps"]) / 10000
    xc = D(approach["dcf_exit_cap_bps"]) / 10000
    n = approach["dcf_holding_period_years"]
    pv_sum = 0
    for t in range(1, n + 1):
        pv_sum += rhu(y1 * (1 + g) ** (t - 1) / (1 + r) ** t)
    terminal = rhu((y1 * (1 + g) ** n / xc) / (1 + r) ** n)
    return pv_sum + terminal


def sales_comparison_value(comps, building_sf):
    sel = [c for c in comps if c["selected_for_support"]]
    units = [
        rhu(D(c["sale_price_cents"]) * (1 + D(c["adjustment_pct"]) / 100) / D(c["size_sf"]))
        for c in sel
    ]
    mean = D(sum(units)) / D(len(units))
    return rhu(mean * D(building_sf))


def cost_approach_value(approach):
    return approach["land_value_cents"] + rhu(
        D(approach["replacement_cost_cents"]) * (1 - D(approach["depreciation_pct"]) / 100)
    )


def reconciled_value(included_approaches):
    """Round each approach's weighted contribution to whole cents FIRST, then sum."""
    return sum(
        rhu(D(a["indicated_value_cents"]) * D(a["weight_pct"]) / 100)
        for a in included_approaches
    )
