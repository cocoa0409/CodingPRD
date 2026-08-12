"""Calculation rules (SCAFFOLD §1.3). All money math uses exact integer
rationals with round-half-up to whole cents — never floats."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, clock

CPI_LOOKUP_BPS = 250
PCT_DENOM = 10000
PERIODS_PER_YEAR = 12
DEFAULT_GROSS_UP_FLOOR_BPS = 9500
VARIABLE_SET = {"CAM", "UTILITIES"}
RECOVERABLE_BY_STRUCTURE = {
    "NNN": {"CAM", "TAX", "INSURANCE", "UTILITIES", "MANAGEMENT_FEE"},
    "MODIFIED_GROSS": {"CAM", "TAX"},
    "GROSS": set(),
}
WINDOW_DAYS = 365


def round_half_up(numer, denom=1):
    """round_half_up(numer / denom) to an integer, using exact arithmetic."""
    q = (Decimal(numer) / Decimal(denom)).quantize(Decimal("1"),
                                                   rounding=ROUND_HALF_UP)
    return int(q)


def d(s):
    """Parse an ISO YYYY-MM-DD date string to a date."""
    return date.fromisoformat(s)


def fiscal_year_window(property_row, fiscal_year):
    """[fy_start, fy_end) for the given calendar fiscal-year label.

    The fiscal year labeled Y ends on the last day of the property's
    fiscal_year_end_month within calendar year Y and begins the day after the
    prior year's fiscal year end.
    """
    m = property_row["fiscal_year_end_month"]
    if m == 12:
        fy_end = date(fiscal_year + 1, 1, 1)
    else:
        fy_end = date(fiscal_year, m + 1, 1)
    if m == 12:
        fy_start = date(fiscal_year, 1, 1)
    else:
        fy_start = date(fiscal_year - 1, m + 1, 1)
    return fy_start, fy_end


def current_fiscal_year(property_row):
    """Calendar fiscal-year label containing the current logical date."""
    today = clock.current().date()
    m = property_row["fiscal_year_end_month"]
    fy_end_this = date(today.year, m + 1, 1) if m != 12 else date(today.year + 1, 1, 1)
    if today < fy_end_this:
        return today.year
    return today.year + 1


# ---------------------------------------------------------------- escalated_rent_for_period

def escalated_rent_for_period(line, step):
    """effective_rent_cents for one RentScheduleLine (pinned evaluation order)."""
    base = line["base_rent_cents"]
    if step is None:
        return base
    if step["kind"] == "FIXED_PCT":
        return round_half_up(base * (PCT_DENOM + step["pct_bps"]), PCT_DENOM)
    if step["kind"] == "CPI_LOOKUP":
        return round_half_up(base * (PCT_DENOM + CPI_LOOKUP_BPS), PCT_DENOM)
    if step["kind"] == "STEPPED_AMOUNT":
        return base + step["amount_cents"]
    return base


# ---------------------------------------------------------------- annual_rent_total

def annual_rent_total(lease_id, fy_start, fy_end):
    """Sum of effective_rent_cents over lines overlapping the fiscal window.
    No pro-ration: any overlap contributes the full line amount."""
    total = 0
    for line in db["rent_schedule_lines"].values():
        if line["lease_id"] != lease_id:
            continue
        if d(line["period_start"]) < fy_end and d(line["period_end"]) > fy_start:
            total += line["effective_rent_cents"]
    return total


def recompute_cached_annual_rent(lease):
    prop = db["properties"][lease["property_id"]]
    fy = current_fiscal_year(prop)
    fy_start, fy_end = fiscal_year_window(prop, fy)
    lease["cached_annual_rent_cents"] = annual_rent_total(
        lease["id"], fy_start, fy_end)


# ---------------------------------------------------------------- straight_line_rent

def straight_line_rent(lease_id, fy_start, fy_end):
    """GAAP straight-line rent allocated into the fiscal window by days."""
    lines = [l for l in db["rent_schedule_lines"].values()
             if l["lease_id"] == lease_id]
    if not lines:
        return 0
    total_rent = sum(l["effective_rent_cents"] for l in lines)
    term_days = sum((d(l["period_end"]) - d(l["period_start"])).days
                    for l in lines)
    if term_days <= 0:
        return 0
    fy_days = 0
    for l in lines:
        start = max(d(l["period_start"]), fy_start)
        end = min(d(l["period_end"]), fy_end)
        if start < end:
            fy_days += (end - start).days
    return round_half_up(total_rent * fy_days, term_days)


# ---------------------------------------------------------------- recovery_billing_estimate

def estimate_for_billing(lease, pool):
    """ESTIMATE variant: pool budget projected into one monthly period."""
    return round_half_up(
        pool["budgeted_cents"] * lease["pro_rata_share_bps"],
        PCT_DENOM * PERIODS_PER_YEAR)


def recoverable_categories(lease):
    return RECOVERABLE_BY_STRUCTURE[lease["recovery_structure"]]


# ---------------------------------------------------------------- occupancy_rate

def occupancy_rate_bps(property_id, fiscal_year):
    prop = db["properties"][property_id]
    fy_start, fy_end = fiscal_year_window(prop, fiscal_year)
    occupied = 0
    for lease in db["leases"].values():
        if lease["property_id"] != property_id:
            continue
        if lease["status"] != "ACTIVE":
            continue
        if d(lease["commencement_date"]) < fy_end and \
           d(lease["expiration_date"]) > fy_start:
            occupied += lease["leased_sf"]
    if occupied == 0:
        return 0, 0
    return occupied, round_half_up(occupied * PCT_DENOM,
                                   prop["total_rentable_sf"])


# ---------------------------------------------------------------- reconciliation_final

def compute_reconciliation_final(recon):
    """FINAL variant: true up all billings of (lease, fiscal_year) to actuals.

    Returns (true_up_cents, gross_up_applied).
    """
    lease = db["leases"][recon["lease_id"]]
    fy = recon["fiscal_year"]
    occupied_sf, occ_bps = occupancy_rate_bps(lease["property_id"], fy)

    pools = [p for p in db["recovery_pools"].values()
             if p["property_id"] == lease["property_id"]
             and p["fiscal_year"] == fy
             and p["category"] in recoverable_categories(lease)]
    pools.sort(key=lambda p: p["created_at"])

    billings = [b for b in db["recovery_billings"].values()
                if b["lease_id"] == lease["id"] and b["fiscal_year"] == fy]

    gross_up_applied = False
    for pool in pools:
        if occ_bps < pool["gross_up_floor_pct_bps"] and \
           pool["category"] in VARIABLE_SET:
            if occ_bps > 0:
                grossed = round_half_up(
                    pool["actual_cents"] * pool["gross_up_floor_pct_bps"],
                    occ_bps)
            else:
                # Zero occupancy: observed occupancy is 0; scale base by the
                # floor (0% occupancy edge — default floor applies).
                grossed = round_half_up(
                    pool["actual_cents"] * pool["gross_up_floor_pct_bps"],
                    PCT_DENOM)
            pool_fired = True
        else:
            grossed = pool["actual_cents"]
            pool_fired = False
        gross_up_applied = gross_up_applied or pool_fired

        year_share = round_half_up(grossed * lease["pro_rata_share_bps"],
                                   PCT_DENOM)

        pool_rows = [b for b in billings if b["pool_id"] == pool["id"]]
        pool_rows.sort(key=lambda b: (b["period_index"], b["created_at"]))
        if not pool_rows:
            continue
        monthly = round_half_up(year_share, PERIODS_PER_YEAR)
        # PRD §3.6 step 4: rows one through eleven each receive the yearly
        # share divided by twelve and rounded half-up; the twelfth row
        # receives the remainder so the rows sum to the yearly share exactly.
        # The waterfall is keyed on period_index (not list position) so that
        # a partial set of rows still receives the conceptual per-row amount.
        for row in pool_rows:
            if 1 <= row["period_index"] <= PERIODS_PER_YEAR - 1:
                row["final_cents"] = monthly
            elif row["period_index"] == PERIODS_PER_YEAR:
                row["final_cents"] = year_share - (PERIODS_PER_YEAR - 1) * monthly

    sum_final = sum(b["final_cents"] or 0 for b in billings)
    sum_estimate = sum(b["estimate_cents"] or 0 for b in billings)
    return sum_final - sum_estimate, gross_up_applied
