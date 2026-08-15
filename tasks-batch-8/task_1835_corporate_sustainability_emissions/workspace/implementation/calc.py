"""Business calculations and cascade helpers (PRD 2.6, 2.7, 3.4, 3.7, 3.8).

All emissions arithmetic uses Decimal with round-half-up; precision depends on
the layer: record lines 4dp, scope totals / spend lines 2dp, percentages 1dp.
Rounding order is pinned: round each line first, then sum, then round the sum.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from store import db, now_iso, touch

D0 = Decimal("1")
D1 = Decimal("0.1")
D2 = Decimal("0.01")
D4 = Decimal("0.0001")

READINESS_THRESHOLD = Decimal("80.0")
TRAJECTORY_TOLERANCE = Decimal("2.0")
BASELINE_SIGNIFICANCE = Decimal("5.0")

REQUIRED_SECTIONS = {
    "CDP": ["GOVERNANCE", "RISKS", "EMISSIONS", "TARGETS"],
    "GRI": ["DISCLOSURE_305", "ENERGY"],
    "ECOVADIS": ["ENVIRONMENT"],
}


def dec(x):
    return Decimal(str(x))


def r1(x):
    return x.quantize(D1, rounding=ROUND_HALF_UP)


def r2(x):
    return x.quantize(D2, rounding=ROUND_HALF_UP)


def r4(x):
    return x.quantize(D4, rounding=ROUND_HALF_UP)


def inventory_for_cycle(cycle_id):
    for inv in db.inventories.values():
        if inv["cycle_id"] == cycle_id:
            return inv
    return None


# ---------------------------------------------------------------------------
# assurance_readiness_pct (PRD 3.4)
# ---------------------------------------------------------------------------
def recompute_readiness(cycle):
    """Quantity-weighted share of APPROVED records covered by >=1 VERIFIED
    evidence item. Recomputed on record approve/reject/void, evidence verify,
    and supersession. Does not bump the cycle version (not an explicit
    cycle-version workflow)."""
    approved = [
        r for r in db.records.values()
        if r["cycle_id"] == cycle["id"] and r["status"] == "APPROVED"
    ]
    if not approved:
        cycle["readiness_pct"] = 0.0
        return
    total = sum((dec(r["quantity"]) for r in approved), D0 * 0)
    covered = Decimal(0)
    for r in approved:
        if any(
            e["activity_record_id"] == r["id"] and e["status"] == "VERIFIED"
            for e in db.evidence.values()
        ):
            covered += dec(r["quantity"])
    cycle["readiness_pct"] = float(r1(covered / total * 100))


# ---------------------------------------------------------------------------
# questionnaire_completeness (PRD 3.9)
# ---------------------------------------------------------------------------
def recompute_completeness(q):
    req = REQUIRED_SECTIONS[q["framework"]]
    answered = sum(1 for s in req if s in q["sections"])
    q["completeness_pct"] = float(r1(Decimal(answered) / Decimal(len(req)) * 100))


# ---------------------------------------------------------------------------
# Staleness propagation (PRD 2.6)
# ---------------------------------------------------------------------------
def mark_inventory_stale(cycle):
    """Link 1: drop the cycle's inventory to STALE. The inventory version
    advances only when the status actually transitions."""
    inv = inventory_for_cycle(cycle["id"])
    if inv is not None and inv["status"] != "STALE":
        inv["status"] = "STALE"
        touch(inv)


def cascade_staleness(cycle):
    """The heavy three-link cascade: inventory STALE -> watching ACTIVE targets
    NOT_EVALUATED -> affected questionnaires emissions_section_stale."""
    mark_inventory_stale(cycle)
    year = cycle["reporting_year"]
    for t in sorted(db.targets.values(), key=lambda x: x["_seq"]):
        if (
            t["status"] == "ACTIVE"
            and t["base_year"] < year <= t["target_year"]
            and t["trajectory_status"] != "NOT_EVALUATED"
        ):
            t["trajectory_status"] = "NOT_EVALUATED"
            touch(t)
    for q in sorted(db.questionnaires.values(), key=lambda x: x["_seq"]):
        if (
            q["cycle_id"] == cycle["id"]
            and q["status"] in ("DRAFT", "IN_REVIEW", "APPROVED")
            and "EMISSIONS" in q["sections"]
            and not q["emissions_section_stale"]
        ):
            q["emissions_section_stale"] = True
            touch(q)


# ---------------------------------------------------------------------------
# Factor resolution
# ---------------------------------------------------------------------------
def find_factor_covering(scope_category, region_code, instant):
    """The unique PUBLISHED factor for (scope_category, region_code) whose
    CLOSED [valid_from, valid_to] window contains `instant`."""
    for fac in sorted(db.factors.values(), key=lambda x: x["_seq"]):
        if fac["status"] != "PUBLISHED":
            continue
        if fac["scope_category"] != scope_category:
            continue
        if fac["region_code"] != region_code:
            continue
        if fac["_vf"] <= instant <= fac["_vt"]:
            return fac
    return None


def factor_covers_period(factor, ps, pe):
    """True iff the factor is PUBLISHED and [period_start, period_end] is
    fully inside its CLOSED [valid_from, valid_to] window."""
    return (
        factor["status"] == "PUBLISHED"
        and factor["_vf"] <= ps
        and pe <= factor["_vt"]
    )


# ---------------------------------------------------------------------------
# inventory_aggregation + market_based_scope2 (PRD 3.7)
# ---------------------------------------------------------------------------
def recalc_inventory(cycle):
    inv = inventory_for_cycle(cycle["id"])
    approved = [
        r for r in db.records.values()
        if r["cycle_id"] == cycle["id"] and r["status"] == "APPROVED"
    ]
    zero = Decimal(0)

    scope1 = r2(sum(
        (dec(r["tco2e"]) for r in approved if r["activity_type"] == "STATIONARY_FUEL"),
        zero,
    ))
    scope2_location = r2(sum(
        (dec(r["tco2e"]) for r in approved if r["activity_type"] == "ELECTRICITY"),
        zero,
    ))
    travel = r2(sum(
        (dec(r["tco2e"]) for r in approved if r["activity_type"] == "BUSINESS_TRAVEL"),
        zero,
    ))

    midpoint = datetime(cycle["reporting_year"], 7, 1, tzinfo=timezone.utc)
    eeio = find_factor_covering("SCOPE3_EEIO_SPEND", "GLOBAL", midpoint)

    def spend_line(e):
        if eeio is None:
            return Decimal("0.00")
        return r2(dec(e["spend_usd"]) * dec(eeio["value_tco2e_per_unit"]))

    engagements = [e for e in db.engagements.values() if e["cycle_id"] == cycle["id"]]
    accepted_supplier = sum(
        (dec(e["supplier_tco2e"]) for e in engagements if e["status"] == "ACCEPTED"),
        zero,
    )
    spend_non_accepted = sum(
        (spend_line(e) for e in engagements if e["status"] != "ACCEPTED"), zero
    )
    spend_all = sum((spend_line(e) for e in engagements), zero)
    scope3 = r2(travel + accepted_supplier + spend_non_accepted)
    scope3_provisional = r2(travel + spend_all)

    # Market-based scope 2: site-by-site waterfall over sites with >= 1
    # APPROVED ELECTRICITY record in this cycle.
    site_ids = sorted(
        {r["site_id"] for r in approved if r["activity_type"] == "ELECTRICITY"}
    )
    market_sum = zero
    for sid in site_ids:
        site_mwh = sum(
            (
                dec(r["quantity"])
                for r in approved
                if r["activity_type"] == "ELECTRICITY" and r["site_id"] == sid
            ),
            zero,
        )
        retired = sum(
            (
                dec(i["quantity_mwh"])
                for i in db.instruments.values()
                if i["status"] == "RETIRED"
                and i["retired_for_cycle_id"] == cycle["id"]
                and i["retired_for_site_id"] == sid
            ),
            zero,
        )
        covered = min(site_mwh, retired)
        residual = site_mwh - covered
        rate = zero
        site = db.sites.get(sid)
        if site is not None:
            res_factor = find_factor_covering(
                "SCOPE2_RESIDUAL_MIX", site["grid_region_code"], midpoint
            )
            if res_factor is not None:
                rate = dec(res_factor["value_tco2e_per_unit"])
            else:
                grid_factor = find_factor_covering(
                    "SCOPE2_GRID", site["grid_region_code"], midpoint
                )
                if grid_factor is not None:
                    rate = dec(grid_factor["value_tco2e_per_unit"])
        # Retired instruments are zero-emission: covered * 0 + residual * rate.
        market_sum += r4(residual * rate)
    scope2_market = r2(market_sum)

    total = r2(scope1 + scope2_market + scope3)

    inv["scope1_tco2e"] = float(scope1)
    inv["scope2_location_tco2e"] = float(scope2_location)
    inv["scope2_market_tco2e"] = float(scope2_market)
    inv["scope3_tco2e"] = float(scope3)
    inv["scope3_provisional_tco2e"] = float(scope3_provisional)
    inv["total_tco2e"] = float(total)
    inv["computed_at"] = now_iso()
    inv["status"] = "CURRENT"
    touch(inv)
    return inv


def coverage_total(target, inv):
    if target["scope_coverage"] == "SCOPE1_2":
        return dec(inv["scope1_tco2e"]) + dec(inv["scope2_market_tco2e"])
    return dec(inv["total_tco2e"])


# ---------------------------------------------------------------------------
# target_trajectory_status (PRD 3.8)
# ---------------------------------------------------------------------------
def evaluate_targets_for_cycle(cycle, inv):
    """Re-evaluate every ACTIVE target watching this cycle after a recalc."""
    year = cycle["reporting_year"]
    for t in sorted(db.targets.values(), key=lambda x: x["_seq"]):
        if t["status"] != "ACTIVE":
            continue
        if not (t["base_year"] < year <= t["target_year"]):
            continue
        coverage = coverage_total(t, inv)
        base = dec(t["base_year_total_tco2e"])
        if base == 0:
            actual = Decimal("0.0")
        else:
            actual = r1((base - coverage) / base * 100)
        span = t["target_year"] - t["base_year"]
        required = r1(dec(t["reduction_pct"]) * (year - t["base_year"]) / span)
        # Boundary is inclusive: exactly at (required - 2.0) is ON_TRACK.
        status = (
            "ON_TRACK" if actual >= (required - TRAJECTORY_TOLERANCE) else "OFF_TRACK"
        )
        if t["trajectory_status"] != status:
            t["trajectory_status"] = status
            touch(t)
