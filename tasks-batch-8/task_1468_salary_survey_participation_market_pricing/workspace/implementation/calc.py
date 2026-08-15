"""Calculation rules (SCAFFOLD §1.3 / PRD §3.6-3.8).

All money is integer cents; all factors are basis points; every rounding is
half-up to 0 decimal places at exactly the points the rules specify.
"""
from decimal import Decimal, ROUND_HALF_UP, getcontext

from common import ApiError, db, parse_date

getcontext().prec = 50

ANNUAL_AGING_RATE = Decimal("0.03")

METRO_TIER_BP = {
    "US-SF": 12800,
    "US-NYC": 12200,
    "US-SEA": 11200,
    "US-AUS": 10400,
    "US-REMOTE": 9500,
}

CUSTOM_GEO_INDEX_BP = {
    "US-SF": 13100,
    "US-NYC": 12400,
    "US-CHI": 10600,
    "US-REMOTE": 9200,
}

INDUSTRY_PREMIUM_BP = {
    "HIGH_TECH": 10800,
    "FINANCIAL_SERVICES": 11200,
    "HEALTHCARE": 10300,
    "MANUFACTURING": 9800,
    "RETAIL": 9400,
    "ALL_INDUSTRIES": 10000,
}

CONFIDENCE_FACTOR = {
    "HIGH": Decimal("1.00"),
    "MEDIUM": Decimal("0.75"),
    "LOW": Decimal("0.40"),
}
CONSERVATIVE_LOW_FACTOR = Decimal("0.20")
MIN_FULL_SAMPLE = 30
CONSERVATIVE_MIN_SAMPLE = 10

BELOW_RANGE_BP = 8000
BELOW_TARGET_BP = 9500
AT_TARGET_UPPER_BP = 10500
ABOVE_TARGET_BP = 12000
MAX_SINGLE_ADJUSTMENT_BP = 1500

PCT_FIELDS = ("p25_cents", "p50_cents", "p75_cents", "p90_cents")
BLENDED_FIELDS = ("blended_p25_cents", "blended_p50_cents", "blended_p75_cents", "blended_p90_cents")
EXECUTIVE_LEVELS = ("M1", "M2", "M3")


def r0(x):
    """Round half-up to zero decimal places, returning int."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def months_elapsed(effective, as_of):
    """Whole calendar months from effective to as_of, floored at 0.

    A month boundary is crossed when the day-of-month of as_of is >= the
    day-of-month of effective for that month.
    """
    m = (as_of.year - effective.year) * 12 + (as_of.month - effective.month)
    if as_of.day < effective.day:
        m -= 1
    return max(0, m)


def _aging_factor(months):
    # (1 + 0.03) ** (months / 12), computed in high-precision Decimal.
    return (Decimal("1.03").ln() * (Decimal(months) / Decimal(12))).exp()


def geo_differential_bp_for(strategy, job_geo_code):
    """Resolve the geo differential in basis points (None under NATIONAL)."""
    policy = strategy["geo_differential_policy"]
    if policy == "NATIONAL":
        return None
    if policy == "METRO_TIER":
        return METRO_TIER_BP.get(job_geo_code, 10000)
    # CUSTOM_GEO_INDEX
    if job_geo_code not in CUSTOM_GEO_INDEX_BP:
        raise ApiError(
            "ERR_GEO_INDEX_MISSING", 422,
            f"CUSTOM_GEO_INDEX policy has no geo index entry for {job_geo_code}",
        )
    return CUSTOM_GEO_INDEX_BP[job_geo_code]


def compute_composite_values(comp):
    """Run aging -> geographic -> industry -> weighted blend for a composite.

    Returns a dict with blended_pXX_cents, geo_differential_bp, source_count.
    Raises ERR_NO_SOURCES / ERR_GEO_INDEX_MISSING.
    """
    job = db["jobs"][comp["job_id"]]
    org = db["orgs"][job["org_id"]]
    strategy = db["strategies"][comp["strategy_policy_id"]]
    executive = job["career_level"] in EXECUTIVE_LEVELS

    contributing = []
    for m in db["matches"].values():
        if m["job_id"] != job["id"] or m["status"] != "APPROVED":
            continue
        survey = db["surveys"][m["survey_id"]]
        if survey["status"] != "ACCEPTED":
            continue
        vendor = db["vendors"][survey["vendor_id"]]
        if vendor["status"] != "ACTIVE":
            continue
        bench = db["benchmarks"][m["benchmark_id"]]
        if executive and bench["sample_size"] < CONSERVATIVE_MIN_SAMPLE:
            continue  # conservative blend outright excludes thin benchmarks
        contributing.append((m, bench, survey))

    weights = []
    for m, bench, _survey in contributing:
        conf = CONFIDENCE_FACTOR[m["match_confidence"]]
        if executive and m["match_confidence"] == "LOW":
            conf = CONSERVATIVE_LOW_FACTOR
        sample_factor = min(Decimal(1), Decimal(bench["sample_size"]) / Decimal(MIN_FULL_SAMPLE))
        w = (Decimal(m["match_weight_pct"]) / Decimal(100)) * conf * sample_factor
        weights.append(w)

    total_w = sum(weights, Decimal(0))
    if not contributing or total_w == 0:
        raise ApiError("ERR_NO_SOURCES", 409, "Composite has zero APPROVED contributing matches")

    geo_bp = geo_differential_bp_for(strategy, comp["job_geo_code"])

    as_of = parse_date(org["market_as_of_date"])
    premium_adjusted = []
    for (m, bench, survey), w in zip(contributing, weights):
        effective = parse_date(survey["data_effective_date"])
        factor = _aging_factor(months_elapsed(effective, as_of))
        aged = {f: r0(Decimal(bench[f]) * factor) for f in PCT_FIELDS}

        if geo_bp is None:
            geo_adj = aged
        else:
            geo_adj = {f: r0(Decimal(aged[f]) * geo_bp / Decimal(10000)) for f in PCT_FIELDS}

        if strategy["industry_cut"] == "ALL_INDUSTRIES":
            prem_bp = 10000
        elif bench["industry_cut"] == strategy["industry_cut"]:
            prem_bp = INDUSTRY_PREMIUM_BP[strategy["industry_cut"]]
        else:
            prem_bp = 10000
        prem_adj = {f: r0(Decimal(geo_adj[f]) * prem_bp / Decimal(10000)) for f in PCT_FIELDS}
        premium_adjusted.append(prem_adj)

    blended = {}
    for src_f, out_f in zip(PCT_FIELDS, BLENDED_FIELDS):
        acc = Decimal(0)
        for w, vals in zip(weights, premium_adjusted):
            acc += (w / total_w) * Decimal(vals[src_f])
        blended[out_f] = r0(acc)  # rounded exactly once at the final sum

    return {
        **blended,
        "geo_differential_bp": geo_bp,
        "source_count": len(contributing),
    }


def compa_ratio_bp(salary_cents, blended_p50_cents):
    return r0(Decimal(salary_cents) * Decimal(10000) / Decimal(blended_p50_cents))


def position_band(cr_bp):
    if cr_bp < BELOW_RANGE_BP:
        return "BELOW_RANGE"
    if cr_bp < BELOW_TARGET_BP:
        return "BELOW_TARGET"
    if cr_bp <= AT_TARGET_UPPER_BP:
        return "AT_TARGET"
    if cr_bp <= ABOVE_TARGET_BP:
        return "ABOVE_TARGET"
    return "ABOVE_RANGE"


def percentile_attainment_bp(salary_cents, comp):
    p25 = comp["blended_p25_cents"]
    p50 = comp["blended_p50_cents"]
    p75 = comp["blended_p75_cents"]
    p90 = comp["blended_p90_cents"]
    S = Decimal(salary_cents)
    if salary_cents < p25:
        return r0(Decimal(2500) * S / Decimal(p25))
    if salary_cents < p50:
        return 2500 + r0(Decimal(2500) * (S - p25) / Decimal(p50 - p25))
    if salary_cents < p75:
        return 5000 + r0(Decimal(2500) * (S - p50) / Decimal(p75 - p50))
    if salary_cents < p90:
        return 7500 + r0(Decimal(1500) * (S - p75) / Decimal(p90 - p75))
    return 9000 + min(1000, r0(Decimal(1000) * (S - p90) / Decimal(p90)))


def recommended_adjustment_cents(strategy, comp, salary_cents):
    """Advisory recommendation per §3.7 (provisional / final variants share the rule)."""
    target_map = {25: "blended_p25_cents", 50: "blended_p50_cents",
                  75: "blended_p75_cents", 90: "blended_p90_cents"}
    p = strategy["target_percentile"]
    if p in target_map:
        target_cents = comp[target_map[p]]
    else:  # 65 -> midpoint of p50 and p75
        target_cents = r0((Decimal(comp["blended_p50_cents"]) + Decimal(comp["blended_p75_cents"])) / 2)
    raw_gap = max(0, target_cents - salary_cents)
    cap = r0(Decimal(MAX_SINGLE_ADJUSTMENT_BP) * Decimal(salary_cents) / Decimal(10000))
    cr = compa_ratio_bp(salary_cents, comp["blended_p50_cents"])
    if cr >= AT_TARGET_UPPER_BP:
        return 0
    if cr < BELOW_RANGE_BP:
        return min(raw_gap, cap)
    if cr < BELOW_TARGET_BP:
        return min(raw_gap, r0(Decimal(cap) * Decimal("0.6")))
    return 0


def build_market_position_snapshot(report, exclude_job_ids):
    """Snapshot payload per §1.3 market_position_snapshot / PRD §3.8."""
    org_id = report["org_id"]
    exclude = set(exclude_job_ids or [])
    jobs_out = []
    weighted_sum = 0
    total_headcount = 0
    for job in sorted(db["jobs"].values(), key=lambda r: r["_seq"]):
        if job["org_id"] != org_id:
            continue
        cid = job["current_market_composite_id"]
        if not cid or job["id"] in exclude:
            continue
        comp = db["composites"][cid]
        p50 = comp["blended_p50_cents"]
        emps = [e for e in db["employees"].values()
                if e["job_id"] == job["id"] and e["status"] == "ACTIVE"]
        headcount = len(emps)
        ratios = [compa_ratio_bp(e["base_salary_annual_cents"], p50) for e in emps]
        avg = r0(Decimal(sum(ratios)) / Decimal(headcount)) if headcount else 0
        below = sum(1 for c in ratios if position_band(c) in ("BELOW_RANGE", "BELOW_TARGET"))
        above = sum(1 for c in ratios if position_band(c) in ("ABOVE_TARGET", "ABOVE_RANGE"))
        gap = sum(max(0, p50 - e["base_salary_annual_cents"]) for e in emps)
        jobs_out.append({
            "job_id": job["id"],
            "job_code": job["job_code"],
            "career_level": job["career_level"],
            "blended_p50_cents": p50,
            "headcount": headcount,
            "avg_compa_ratio_bp": avg,
            "below_target_count": below,
            "above_target_count": above,
            "total_market_gap_cents": gap,
        })
        weighted_sum += avg * headcount
        total_headcount += headcount
    org_wide = r0(Decimal(weighted_sum) / Decimal(total_headcount)) if total_headcount else 0
    from common import iso
    return {
        "strategy_policy_id": report["pinned_strategy_policy_id"],
        "generated_at_utc": iso(),
        "jobs": jobs_out,
        "org_wide_avg_compa_ratio_bp": org_wide,
    }
