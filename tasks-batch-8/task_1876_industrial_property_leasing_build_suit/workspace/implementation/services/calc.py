"""Calculation rules per SCAFFOLD.yaml §1.3 and PRD §2.7, §3.2, §3.3, §3.5, §3.7.

All monetary/rate math uses Decimal, rounded half-up. Pinned rounding orders:
- aggregate rent: sum unrounded yearly terms, round once to cents;
- broker commission: round each tier to cents first, then sum;
- remainder pinning: half-cent side remainder -> LANDLORD_REP; installment
  remainder -> installment 2.
"""
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 50

CENTS = Decimal("0.01")
FOUR = Decimal("0.0001")


def D(v):
    return v if isinstance(v, Decimal) else Decimal(str(v))


def rhu2(v):
    return D(v).quantize(CENTS, rounding=ROUND_HALF_UP)


def rhu4(v):
    return D(v).quantize(FOUR, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# site_match_scoring (§1.3 / PRD §3.2)
# ---------------------------------------------------------------------------
MATCH_CAP = Decimal("1.25")
W_CLEAR_HEIGHT = Decimal("0.30")
W_DOCK_DOORS = Decimal("0.30")
W_POWER = Decimal("0.20")
W_YARD = Decimal("0.20")


def match_evaluation(site, req):
    """Returns (match_score Decimal 2dp, hard_minimums_met bool). Stateless."""
    pairs = [
        (site["clear_height_ft"], req["min_clear_height_ft"], W_CLEAR_HEIGHT),
        (site["dock_doors"], req["min_dock_doors"], W_DOCK_DOORS),
        (site["power_amps"], req["min_power_amps"], W_POWER),
        (site["yard_depth_ft"], req["min_yard_depth_ft"], W_YARD),
    ]
    total = Decimal("0")
    for site_attr, req_min, weight in pairs:
        req_min = D(req_min)
        if req_min == 0:
            ratio = MATCH_CAP  # a zero minimum is trivially met at the cap
        else:
            ratio = D(site_attr) / req_min
        capped = min(ratio, MATCH_CAP)
        total += weight * capped / MATCH_CAP * 100
    score = rhu2(total)
    hard = hard_minimums_met(site, req)
    return score, hard


def hard_minimums_met(site, req):
    return (
        D(site["clear_height_ft"]) >= D(req["min_clear_height_ft"])
        and site["dock_doors"] >= req["min_dock_doors"]
        and site["power_amps"] >= req["min_power_amps"]
        and site["yard_depth_ft"] >= req["min_yard_depth_ft"]
        and site["total_sf"] >= req["min_sf"]
    )


# ---------------------------------------------------------------------------
# aggregate_rent + net_effective_rent (§1.3 / PRD §3.3)
# ---------------------------------------------------------------------------
TI_CAP_PSF = Decimal("50")


def aggregate_rent(base_rate_psf, leased_sf, term_years, escalation_pct):
    """Sum the unrounded yearly terms first, then round once to cents."""
    base = D(base_rate_psf)
    sf = D(leased_sf)
    esc = D(escalation_pct)
    total = Decimal("0")
    for y in range(int(term_years)):
        total += base * sf * ((Decimal("1") + esc) ** y)
    return rhu2(total)


def net_effective_rent_psf(aggregate_rent_total, base_rate_psf, leased_sf,
                           term_years, free_rent_months, ti_allowance_psf):
    """Evaluation order pinned: aggregate first, then credits, then division."""
    base = D(base_rate_psf)
    sf = D(leased_sf)
    free_rent_credit = rhu2(D(free_rent_months) * (base * sf / Decimal("12")))
    ti_credit = rhu2(min(D(ti_allowance_psf), TI_CAP_PSF) * sf)
    ner_total = D(aggregate_rent_total) - free_rent_credit - ti_credit
    return rhu2(ner_total / (D(term_years) * sf))


def recompute_loi_economics(loi):
    loi["aggregate_rent_total"] = aggregate_rent(
        loi["base_rate_psf"], loi["leased_sf"], loi["term_years"],
        loi["escalation_pct"])
    loi["net_effective_rent_psf"] = net_effective_rent_psf(
        loi["aggregate_rent_total"], loi["base_rate_psf"], loi["leased_sf"],
        loi["term_years"], loi["free_rent_months"], loi["ti_allowance_psf"])


# ---------------------------------------------------------------------------
# bts_cost_rent_conversion (§1.3 / PRD §3.5) — pinned two-pass evaluation
# ---------------------------------------------------------------------------
TARGET_YIELD = Decimal("0.08")
DEV_COMM_PCT = Decimal("0.04")
MARKET_MARKUP = Decimal("0.05")


def bts_cost_rent_conversion(hard_cost_total, soft_cost_total, contingency_pct,
                             pricing_method, leased_sf, term_years,
                             escalation_pct, asking_rate_psf):
    # pass 1
    base_cost = (D(hard_cost_total) + D(soft_cost_total)) * (Decimal("1") + D(contingency_pct))
    provisional_base_rate_psf = rhu2(base_cost * TARGET_YIELD / D(leased_sf))
    provisional_ar = aggregate_rent(provisional_base_rate_psf, leased_sf,
                                    term_years, escalation_pct)
    commission_cost_estimate = rhu2(DEV_COMM_PCT * provisional_ar)
    # pass 2 — monetary amounts are carried at 2dp (PRD §2.7)
    total_project_cost = rhu2(base_cost + commission_cost_estimate)
    yield_on_cost_rate = rhu2(total_project_cost * TARGET_YIELD / D(leased_sf))
    if pricing_method == "YIELD_ON_COST":
        converted_base_rate_psf = yield_on_cost_rate
    else:  # MARKET_COMP — never below market
        converted_base_rate_psf = max(
            D(asking_rate_psf), rhu2(yield_on_cost_rate * (Decimal("1") + MARKET_MARKUP)))
    yield_on_cost = rhu4(converted_base_rate_psf * D(leased_sf) / total_project_cost)
    return {
        "provisional_base_rate_psf": provisional_base_rate_psf,
        "commission_cost_estimate": commission_cost_estimate,
        "total_project_cost": total_project_cost,
        "converted_base_rate_psf": converted_base_rate_psf,
        "yield_on_cost": yield_on_cost,
    }


# ---------------------------------------------------------------------------
# broker_commission (§1.3 / PRD §3.7) — tiers rounded before summing
# ---------------------------------------------------------------------------
COMM_TIER1_RATE = Decimal("0.05")
COMM_TIER1_CAP = Decimal("500000")
COMM_TIER2_RATE = Decimal("0.03")
SIDE_SPLIT = Decimal("0.5")
INSTALLMENT_SPLIT = Decimal("0.5")


def commission_basis_amount(loi):
    if loi["commission_basis"] == "GROSS_AGGREGATE":
        return D(loi["aggregate_rent_total"])
    return rhu2(D(loi["net_effective_rent_psf"]) * D(loi["term_years"]) * D(loi["leased_sf"]))


def split_commission(basis):
    """Returns (tenant_total, landlord_total): tiers rounded to cents first,
    then summed; the half-cent side remainder is pinned to LANDLORD_REP."""
    basis = D(basis)
    tier1 = rhu2(COMM_TIER1_RATE * min(basis, COMM_TIER1_CAP))
    tier2 = rhu2(COMM_TIER2_RATE * max(Decimal("0"), basis - COMM_TIER1_CAP))
    combined = tier1 + tier2
    tenant_total = rhu2(SIDE_SPLIT * combined)
    landlord_total = combined - tenant_total
    return tenant_total, landlord_total


def split_installments(total_commission):
    """installment_1 = half rounded half-up to cents; the remainder is pinned
    to installment 2."""
    total = D(total_commission)
    i1 = rhu2(INSTALLMENT_SPLIT * total)
    return i1, total - i1


# ---------------------------------------------------------------------------
# delivery_delay_abatement (§1.3 / PRD §3.5) — 30-day grace, floored at zero
# ---------------------------------------------------------------------------
DELAY_GRACE_DAYS = 30


def delivery_delay_abatement(planned_dt, actual_dt):
    delay_days = (actual_dt - planned_dt).days
    return max(0, delay_days - DELAY_GRACE_DAYS)
