"""The eight calculations of the scaffold plus the cascade recomputation
helpers described in PRD 2.9.

Every monetary figure is an exact integer number of cents.  Non-integer
figures (scores, percentages, the 60-month BOE aggregate) are Decimal values
rounded half up to two decimal places (PRD 2.8).
"""
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from store import clock, db, days, touch

TWO = Decimal("0.01")
HUNDRED = Decimal("100")

# --- assurance -------------------------------------------------------------
DEPTH_TIER_SHALLOW_FT = 3000
DEPTH_TIER_MID_FT = 7000
BASE_SHALLOW_CENTS = 250000
BASE_MID_CENTS = 750000
BASE_DEEP_CENTS = 1500000
BLANKET_CAP_CENTS = 25000000
INDIVIDUAL_PER_WELL_CAP_CENTS = 1000000

ASSURANCE_STATUSES = (
    "PRODUCING",
    "INACTIVE",
    "ORPHAN_CANDIDATE",
    "ORPHAN_CONFIRMED",
    "PLUGGING_SCHEDULED",
)
ACTIVE_WELL_EXCLUDED = ("PLUGGED", "RECLAIMED")
ORPHAN_CANDIDATE_STATUSES = ("ORPHAN_CANDIDATE", "ORPHAN_CONFIRMED",
                             "PLUGGING_SCHEDULED")

# --- scoring ---------------------------------------------------------------
METHANE_FULL_SCALE_SCFD = Decimal("5")
POPULATION_MULTIPLIER = Decimal("4")
SURFACE_MULTIPLIER = Decimal("20")
SCREENING_WEIGHTS = (Decimal("0.35"), Decimal("0.30"), Decimal("0.20"),
                     Decimal("0.15"))
REMEDIATION_WEIGHTS = (Decimal("0.20"), Decimal("0.25"), Decimal("0.40"),
                       Decimal("0.15"))
POPULATION_OVERRIDE_THRESHOLD = 5

# --- criteria --------------------------------------------------------------
IDLE_MONTHS_SENTINEL = 999
IDLE_MONTHS_INACTIVE = 12
IDLE_MONTHS_ORPHAN = 24
DEMINIMIS_WINDOW_MONTHS = 60
DEMINIMIS_BOE_CEILING = Decimal("180.00")
SCREENING_SCORE_FLOOR = Decimal("40.00")
GAS_TO_BOE_DIVISOR = Decimal("6")

# --- procurement / field ---------------------------------------------------
BASKET_CEMENT_SACKS = 120
BASKET_RIG_DAYS = 4
BASKET_CASING_FT = 800
PRICE_WEIGHT = Decimal("0.60")
TECHNICAL_WEIGHT = Decimal("0.40")
CREW_DEMOB_BUFFER_DAYS = 2
ADMIN_FEE_PCT = Decimal("0.0425")
REMOB_PCT = Decimal("0.50")

# --- funding ---------------------------------------------------------------
KIND_RANK = {"FORFEITED_BOND": 1, "FEDERAL_GRANT": 2, "STATE_FUND": 3}
TRANSFER_VOID_LOOKBACK_DAYS = 180
FORFEITED_BOND_TERM_DAYS = 3650
REVEGETATION_WAIT_DAYS = 90


def round2(value):
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def round_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_DOWN))


def dec(value):
    return Decimal(str(value))


# =========================================================================
# calculations.orphan_priority_score
# =========================================================================
def methane_component(well):
    raw = round2(dec(well["methane_scfd"]) / METHANE_FULL_SCALE_SCFD)
    return min(raw, HUNDRED)


def groundwater_component(well):
    depth = well["groundwater_depth_ft"]
    if depth <= 50:
        return Decimal("100")
    if depth <= 200:
        return Decimal("75")
    if depth <= 500:
        return Decimal("40")
    return Decimal("10")


def population_component(well):
    raw = round2(dec(well["population_within_1000ft"]) * POPULATION_MULTIPLIER)
    return min(raw, HUNDRED)


def surface_component(well):
    raw = round2(dec(well["surface_disturbance_acres"]) * SURFACE_MULTIPLIER)
    return min(raw, HUNDRED)


def screening_score(well):
    m = methane_component(well)
    g = groundwater_component(well)
    p = population_component(well)
    s = surface_component(well)
    w = SCREENING_WEIGHTS
    return round2(w[0] * m + w[1] * g + w[2] * p + w[3] * s)


def remediation_score(well):
    m = methane_component(well)
    g = groundwater_component(well)
    if well["population_within_1000ft"] >= POPULATION_OVERRIDE_THRESHOLD:
        p = Decimal("100")
    else:
        p = population_component(well)
    s = surface_component(well)
    w = REMEDIATION_WEIGHTS
    return round2(w[0] * m + w[1] * g + w[2] * p + w[3] * s)


def recompute_scores(well):
    well["screening_score"] = screening_score(well)
    well["remediation_score"] = remediation_score(well)


# =========================================================================
# calculations.orphan_classification_criteria
# =========================================================================
def _split_month(value):
    parts = value.split("-")
    return int(parts[0]), int(parts[1])


def _shift_month(year, month, delta):
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def _month_string(year, month):
    return "%04d-%02d" % (year, month)


def compute_idle_months(well):
    lpm = well.get("last_production_month")
    if not lpm:
        return IDLE_MONTHS_SENTINEL
    year, month = _split_month(lpm)
    now = clock()
    return (now.year - year) * 12 + (now.month - month)


def deminimis_window():
    now = clock()
    start_year, start_month = _shift_month(
        now.year, now.month, -(DEMINIMIS_WINDOW_MONTHS - 1)
    )
    return _month_string(start_year, start_month), _month_string(now.year, now.month)


def compute_cumulative_boe(well):
    window_start, window_end = deminimis_window()
    total = Decimal("0")
    for record in db.production_records.values():
        if record["well_id"] != well["id"]:
            continue
        month = record["month"]
        if window_start <= month <= window_end:
            total += dec(record["boe"])
    return round2(total)


def recompute_criteria(well):
    well["idle_months"] = compute_idle_months(well)
    well["cumulative_boe_60mo"] = compute_cumulative_boe(well)


def criteria_met(well):
    return (
        well["idle_months"] >= IDLE_MONTHS_ORPHAN
        and dec(well["cumulative_boe_60mo"]) <= DEMINIMIS_BOE_CEILING
        and dec(well["screening_score"]) >= SCREENING_SCORE_FLOOR
    )


def row_boe(oil_bbl, gas_mcf):
    """Unrounded at the row level (PRD 2.8, 3.1)."""
    return dec(oil_bbl) + dec(gas_mcf) / GAS_TO_BOE_DIVISOR


# =========================================================================
# calculations.operator_financial_assurance_requirement
# =========================================================================
def well_base_cents(well):
    depth = well["total_depth_ft"]
    if depth <= DEPTH_TIER_SHALLOW_FT:
        return BASE_SHALLOW_CENTS
    if depth <= DEPTH_TIER_MID_FT:
        return BASE_MID_CENTS
    return BASE_DEEP_CENTS


def operator_wells(operator_id):
    return [w for w in db.wells.values() if w["operator_id"] == operator_id]


def assurance_requirement(tier, wells):
    included = [w for w in wells if w["status"] in ASSURANCE_STATUSES]
    if tier == "BLANKET":
        total = sum(well_base_cents(w) for w in included)
        return min(total, BLANKET_CAP_CENTS)
    return sum(
        min(well_base_cents(w), INDIVIDUAL_PER_WELL_CAP_CENTS) for w in included
    )


def count_active_wells(wells):
    return len([w for w in wells if w["status"] not in ACTIVE_WELL_EXCLUDED])


def count_orphan_candidates(wells):
    return len([w for w in wells if w["status"] in ORPHAN_CANDIDATE_STATUSES])


def recompute_operator(operator, bump=True):
    """Assurance recomputation cascade (PRD 2.9 / 3.1).

    Refreshes the two counters and required_bond_cents, then applies the
    automatic and reversible ACTIVE <-> DELINQUENT flip.  The row's version is
    bumped exactly once unless the caller already bumped it.
    """
    if operator is None:
        return None
    wells = operator_wells(operator["id"])
    operator["active_well_count"] = count_active_wells(wells)
    operator["orphan_candidate_count"] = count_orphan_candidates(wells)
    operator["required_bond_cents"] = assurance_requirement(
        operator["financial_assurance_tier"], wells
    )
    deficient = operator["bond_amount_cents"] < operator["required_bond_cents"]
    if operator["status"] == "ACTIVE" and deficient:
        operator["status"] = "DELINQUENT"
    elif operator["status"] == "DELINQUENT" and not deficient:
        operator["status"] = "ACTIVE"
    if bump:
        touch(operator)
    return operator


def transferee_required_bond(to_operator, well):
    """Forward-looking requirement for the transferee INCLUDING this well."""
    wells = [w for w in operator_wells(to_operator["id"]) if w["id"] != well["id"]]
    wells = wells + [well]
    return assurance_requirement(to_operator["financial_assurance_tier"], wells)


# =========================================================================
# calculations.bid_composite_score
# =========================================================================
def basket_cost_cents(cement, rig_day, casing, mobilization):
    return (
        BASKET_CEMENT_SACKS * cement
        + BASKET_RIG_DAYS * rig_day
        + BASKET_CASING_FT * casing
        + mobilization
    )


def price_score(lowest_cents, own_cents):
    return round2(HUNDRED * dec(lowest_cents) / dec(own_cents))


def composite_score(price, technical):
    return round2(PRICE_WEIGHT * dec(price) + TECHNICAL_WEIGHT * dec(technical))


def rank_key(bid):
    """composite DESC, then evaluated_unit_cost ASC, then created_at ASC.

    The row id is never a tiebreaker (PRD 3.6).
    """
    return (
        -dec(bid["composite_score"]),
        bid["evaluated_unit_cost_cents"],
        bid["created_at"],
        bid["_seq"],
    )


# =========================================================================
# calculations.plugging_cost_estimate
# =========================================================================
def plugging_estimate_cents(contract, cement_sacks, rig_days, casing_ft):
    """Planned quantities at contract rates plus mobilization once.  The
    estimate deliberately carries NO administrative fee (PRD 3.7)."""
    return (
        cement_sacks * contract["cement_per_sack_cents"]
        + rig_days * contract["rig_day_rate_cents"]
        + casing_ft * contract["casing_per_ft_cents"]
        + contract["mobilization_fee_cents"]
    )


# =========================================================================
# calculations.plugging_actual_cost
# =========================================================================
def mobilization_line_cents(contract, round_number):
    if round_number <= 1:
        return contract["mobilization_fee_cents"]
    return round_cents(dec(contract["mobilization_fee_cents"]) * REMOB_PCT)


def round_cost_cents(contract, round_number, cement_sacks, rig_days, casing_ft):
    """Four line items plus the 4.25 percent administrative fee, which is
    rounded half up PER LINE ITEM before the four fees are summed."""
    lines = [
        cement_sacks * contract["cement_per_sack_cents"],
        rig_days * contract["rig_day_rate_cents"],
        casing_ft * contract["casing_per_ft_cents"],
        mobilization_line_cents(contract, round_number),
    ]
    subtotal = sum(lines)
    admin_fee = sum(round_cents(dec(line) * ADMIN_FEE_PCT) for line in lines)
    return subtotal + admin_fee


def contract_jobs(contract_id):
    return [j for j in db.jobs.values() if j["contract_id"] == contract_id]


def contract_obligation_cents(contract_id, extra_estimate=None):
    """Sum over every job of max(estimate, actual), regardless of status."""
    total = 0
    for job in contract_jobs(contract_id):
        total += max(job["plugging_cost_estimate_cents"], job["actual_cost_cents"])
    if extra_estimate is not None:
        total += extra_estimate
    return total


# =========================================================================
# calculations.job_funding_waterfall
# =========================================================================
def source_available_cents(source):
    return source["authorized_cents"] - source["committed_cents"]


def source_eligible(source, well_operator_id):
    if source["status"] != "ACTIVE":
        return False
    if not source["expires_at"] > clock():
        return False
    if "PLUGGING" not in (source.get("allowable_cost_categories") or []):
        return False
    if source_available_cents(source) <= 0:
        return False
    if source["kind"] == "FORFEITED_BOND":
        if source.get("bond_operator_id") != well_operator_id:
            return False
    return True


def waterfall_order(sources):
    return sorted(
        sources,
        key=lambda s: (
            KIND_RANK.get(s["kind"], 99),
            s["expires_at"],
            s["created_at"],
            s["_seq"],
        ),
    )


def federal_entitlement_cap(source, needed, non_federal_base):
    pct = source.get("federal_match_required_pct")
    if pct is None:
        pct = 0
    if pct == 0:
        return needed
    return floor_cents(dec(non_federal_base) * dec(100 - pct) / dec(pct))


def run_waterfall(pool, needed):
    """Single pass with a pinned order.  Returns (plan, remaining, capped)."""
    plan = []
    remaining = needed
    non_federal_base = 0
    federal_capped = False
    for index, source in enumerate(pool, start=1):
        if remaining <= 0:
            break
        available = source_available_cents(source)
        if source["kind"] == "FEDERAL_GRANT":
            cap = federal_entitlement_cap(source, remaining, non_federal_base)
            contribution = min(remaining, available, cap)
            if contribution < min(remaining, available):
                federal_capped = True
        else:
            contribution = min(remaining, available)
        if contribution <= 0:
            continue
        plan.append({"source": source, "allocated_cents": contribution,
                     "waterfall_rank": index})
        remaining -= contribution
        if source["kind"] != "FEDERAL_GRANT":
            non_federal_base += contribution
    return plan, remaining, federal_capped


def source_committed_cents(source_id):
    return sum(
        a["allocated_cents"]
        for a in db.allocations.values()
        if a["source_id"] == source_id and a["status"] in ("COMMITTED", "DISBURSED")
    )


def source_disbursed_cents(source_id):
    return sum(
        a["disbursed_cents"]
        for a in db.allocations.values()
        if a["source_id"] == source_id and a["status"] == "DISBURSED"
    )


def job_funded_cents(job_id):
    return sum(
        a["allocated_cents"]
        for a in db.allocations.values()
        if a["job_id"] == job_id and a["status"] in ("COMMITTED", "DISBURSED")
    )


# =========================================================================
# calculations.grant_report_figures
# =========================================================================
def _date_part(value):
    return value.strftime("%Y-%m-%d")


def grant_report_figures(source_id, period_start, period_end):
    federal = []
    for allocation in db.allocations.values():
        if allocation["source_id"] != source_id:
            continue
        if allocation["status"] != "DISBURSED":
            continue
        if allocation["disbursed_at"] is None:
            continue
        if not period_start <= _date_part(allocation["disbursed_at"]) <= period_end:
            continue
        federal.append(allocation)

    reported_cost_cents = sum(a["disbursed_cents"] for a in federal)

    counted_job_ids = []
    for allocation in federal:
        job = db.jobs.get(allocation["job_id"])
        if job is None:
            continue
        if job["status"] not in ("PLUGGED", "RECLAIMED"):
            continue
        if job["id"] not in counted_job_ids:
            counted_job_ids.append(job["id"])

    total_cents = 0
    for allocation in db.allocations.values():
        if allocation["status"] != "DISBURSED":
            continue
        if allocation["job_id"] not in counted_job_ids:
            continue
        if allocation["disbursed_at"] is None:
            continue
        if not period_start <= _date_part(allocation["disbursed_at"]) <= period_end:
            continue
        total_cents += allocation["disbursed_cents"]

    if total_cents == 0:
        share = Decimal("0.00")
    else:
        share = round2(HUNDRED * dec(reported_cost_cents) / dec(total_cents))

    return {
        "wells_plugged_count": len(counted_job_ids),
        "reported_cost_cents": reported_cost_cents,
        "federal_share_pct": share,
    }


def apply_report_figures(report):
    figures = grant_report_figures(
        report["source_id"], report["period_start"], report["period_end"]
    )
    report.update(figures)
    return report


# =========================================================================
# licensing propagation (PRD 2.9 / 3.6)
# =========================================================================
def contractor_contracts(contractor_id):
    return [c for c in db.contracts.values() if c["contractor_id"] == contractor_id]


def suspend_contractor_contracts(contractor_id):
    for contract in contractor_contracts(contractor_id):
        if contract["status"] == "ACTIVE":
            contract["status"] = "SUSPENDED"
            touch(contract)


def restore_contractor_contracts(contractor_id):
    for contract in contractor_contracts(contractor_id):
        if contract["status"] == "SUSPENDED":
            contract["status"] = "ACTIVE"
            touch(contract)


# =========================================================================
# orphan-candidate cascade shared by REVOKE and FORFEIT_BOND (PRD 3.5)
# =========================================================================
def promote_wells_to_orphan_candidate(operator_id):
    for well in db.wells.values():
        if well["operator_id"] != operator_id:
            continue
        if well["status"] in ("PRODUCING", "INACTIVE"):
            well["status"] = "ORPHAN_CANDIDATE"
            recompute_scores(well)
            touch(well)


def expire_funding_sources():
    """PRD 2.5: advancing the clock expires every source at or past expires_at."""
    now = clock()
    for source in db.funding_sources.values():
        if source["status"] in ("ACTIVE", "EXHAUSTED") and source["expires_at"] <= now:
            source["status"] = "EXPIRED"
            touch(source)


def refresh_source_availability(source):
    """ACTIVE <-> EXHAUSTED availability cycle (PRD 3.9)."""
    if source["status"] == "ACTIVE":
        if source["committed_cents"] == source["authorized_cents"]:
            source["status"] = "EXHAUSTED"
    elif source["status"] == "EXHAUSTED":
        if source["committed_cents"] < source["authorized_cents"]:
            source["status"] = "ACTIVE"


def lookback_start():
    return clock() - days(TRANSFER_VOID_LOOKBACK_DAYS)
