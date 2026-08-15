"""Business logic: the 11 calculation rules and cascade helpers (PRD section 3).

Precision discipline (PRD section 2.6):
  - per-record kBtu conversion, round_half_up to integer, THEN sum
  - EUI / percentages at exactly 2 decimals, round_half_up
  - money in integer cents, round_half_up
  - lateness in whole 86400-second days (floor)
"""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from db import store

KBTU_FACTOR = {
    "ELECTRICITY": Decimal("3.412"),
    "NATURAL_GAS": Decimal("100"),
    "DISTRICT_STEAM": Decimal("1194"),
    "FUEL_OIL": Decimal("138.5"),
}
PROPERTY_TYPES = ["OFFICE", "MULTIFAMILY", "RETAIL", "HOTEL", "INDUSTRIAL"]
SPACE_TYPES = ["OFFICE", "RETAIL", "RESIDENTIAL", "COMMON", "OTHER"]
COMMODITIES = ["ELECTRICITY", "NATURAL_GAS", "DISTRICT_STEAM", "FUEL_OIL"]

OWNER_RESTRICTION_THRESHOLD_CENTS = 100000
SCORE_MIN_COMPLETENESS_PCT = Decimal("75")
SCORE_BASE = Decimal("50")
SCORE_MIN = 1
SCORE_MAX = 100


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------

def D(x):
    return Decimal(str(x))


def round2(x):
    return D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round0(x):
    return D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def f2(x):
    """Round half-up to 2 decimals and return as float for storage."""
    return float(round2(x))


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def building_accounts(building_id):
    return [a for a in store.utility_accounts.values() if a["building_id"] == building_id]


def building_units(building_id):
    return [u for u in store.tenant_units.values() if u["building_id"] == building_id]


def unit_grants(unit_id):
    return [g for g in store.consent_grants.values() if g["tenant_unit_id"] == unit_id]


def report_for(building_id, cycle_id):
    for r in store.reports.values():
        if r["building_id"] == building_id and r["cycle_id"] == cycle_id:
            return r
    return None


def cycle_by_year(year):
    for c in store.cycles.values():
        if c["cycle_year"] == year:
            return c
    return None


def perf_std(cycle, property_type):
    for s in cycle["performance_standards"]:
        if isinstance(s, dict) and s.get("property_type") == property_type:
            return s
    return None


def year_bounds(year):
    return (datetime(year, 1, 1, tzinfo=timezone.utc),
            datetime(year + 1, 1, 1, tzinfo=timezone.utc))


def record_year(record):
    """The calendar year fully containing the record's half-open period, else None."""
    ps, pe = record["period_start"], record["period_end"]
    start, end = year_bounds(ps.year)
    if ps >= start and pe <= end:
        return ps.year
    return None


# ---------------------------------------------------------------------------
# Calculation: whole_building_kbtu_aggregation (pinned convert-then-round per record)
# ---------------------------------------------------------------------------

def compute_kbtu(commodity, consumption_value):
    return int(round0(D(consumption_value) * KBTU_FACTOR[commodity]))


def compute_aggregated_kbtu(building, cycle):
    start, end = year_bounds(cycle["cycle_year"])
    total = 0
    for a in building_accounts(building["id"]):
        for r in store.usage_records.values():
            if r["utility_account_id"] != a["id"] or r["status"] != "ACTIVE":
                continue
            if r["period_start"] >= start and r["period_end"] <= end:
                total += r["kbtu"]
    return total


# ---------------------------------------------------------------------------
# Calculation: site_eui
# ---------------------------------------------------------------------------

def compute_site_eui(aggregated_kbtu, building):
    return f2(D(aggregated_kbtu) / D(building["gross_floor_area_sqft"]))


# ---------------------------------------------------------------------------
# ConsentGrant lazy expiry (GRANTED -> EXPIRED when clock date > valid_to)
# ---------------------------------------------------------------------------

def grant_effective_status(grant):
    if grant["status"] == "GRANTED" and grant.get("valid_to"):
        try:
            vt = date.fromisoformat(grant["valid_to"])
        except (ValueError, TypeError):
            return grant["status"]
        if db.LOGICAL_CLOCK.date() > vt:
            return "EXPIRED"
    return grant["status"]


def present_grant(grant):
    g = dict(grant)
    g["status"] = grant_effective_status(grant)
    return g


# ---------------------------------------------------------------------------
# Calculation: data_completeness_ratio
# ---------------------------------------------------------------------------

def compute_completeness(building, cycle):
    units = building_units(building["id"])
    unit_total = sum(u["floor_area_sqft"] for u in units)
    common = max(building["gross_floor_area_sqft"] - unit_total, 0)
    year = cycle["cycle_year"]
    year_start, year_end = date(year, 1, 1), date(year, 12, 31)
    consented = 0
    for u in units:
        for g in unit_grants(u["id"]):
            if grant_effective_status(g) != "GRANTED":
                continue
            if (date.fromisoformat(g["valid_from"]) <= year_start
                    and date.fromisoformat(g["valid_to"]) >= year_end):
                consented += u["floor_area_sqft"]
                break
    return f2(D(100) * D(common + consented) / D(building["gross_floor_area_sqft"]))


def window_covers_year(grant, year):
    """True when the grant window fully covers the given calendar year (closed dates)."""
    if not grant.get("valid_from") or not grant.get("valid_to"):
        return False
    try:
        vf = date.fromisoformat(grant["valid_from"])
        vt = date.fromisoformat(grant["valid_to"])
    except (ValueError, TypeError):
        return False
    return vf <= date(year, 1, 1) and vt >= date(year, 12, 31)


# ---------------------------------------------------------------------------
# Calculation: coverage_determination
# ---------------------------------------------------------------------------

def covered(building, cycle):
    if building["status"] != "ACTIVE":
        return False
    if building["gross_floor_area_sqft"] < cycle["covered_floor_area_threshold_sqft"]:
        return False
    if building["property_type"] not in cycle["covered_property_types"]:
        return False
    for er in store.exemption_requests.values():
        if (er["building_id"] == building["id"] and er["cycle_id"] == cycle["id"]
                and er["request_type"] == "EXEMPTION" and er["status"] == "APPROVED"):
            return False
    return True


def approved_extension(building_id, cycle_id):
    for er in store.exemption_requests.values():
        if (er["building_id"] == building_id and er["cycle_id"] == cycle_id
                and er["request_type"] == "EXTENSION" and er["status"] == "APPROVED"):
            return er
    return None


def effective_deadline(building_id, cycle):
    ext = approved_extension(building_id, cycle["id"])
    if ext is not None and ext.get("extended_deadline_at") is not None:
        return ext["extended_deadline_at"]
    return cycle["filing_deadline_at"]


def whole_days_between(moment, deadline):
    """max(0, floor((moment - deadline) / 86400))."""
    seconds = (moment - deadline).total_seconds()
    return max(0, int(seconds // 86400))


# ---------------------------------------------------------------------------
# Report recompute helper
# ---------------------------------------------------------------------------

def recompute_report(report, with_completeness=True):
    """Recompute aggregated_kbtu + site_eui (+ completeness); touches the report."""
    building = store.buildings[report["building_id"]]
    cycle = store.cycles[report["cycle_id"]]
    report["aggregated_kbtu"] = compute_aggregated_kbtu(building, cycle)
    report["site_eui"] = compute_site_eui(report["aggregated_kbtu"], building)
    if with_completeness:
        report["data_completeness_pct"] = compute_completeness(building, cycle)
    db.touch(report)


# ---------------------------------------------------------------------------
# Calculation: owner_fine_exposure
# ---------------------------------------------------------------------------

def owner_exposures(owner_id):
    """Returns (outstanding_fines_cents, settled_exposure_cents, projected_exposure_cents)."""
    building_ids = {b["id"] for b in store.buildings.values() if b["owner_id"] == owner_id}
    settled = 0
    assessed = 0
    for f in store.fines.values():
        if f["building_id"] not in building_ids:
            continue
        if f["status"] == "NOTICED":
            settled += f["final_amount_cents"] or 0
        elif f["status"] == "ASSESSED":
            assessed += f["provisional_amount_cents"] or 0
    return settled + assessed, settled, settled + assessed


def recompute_owner_exposure(owner_id):
    owner = store.owners.get(owner_id)
    if owner is None:
        return
    outstanding, _, _ = owner_exposures(owner_id)
    standing = "RESTRICTED" if outstanding > OWNER_RESTRICTION_THRESHOLD_CENTS else "NORMAL"
    if owner["outstanding_fines_cents"] != outstanding or owner["standing"] != standing:
        owner["outstanding_fines_cents"] = outstanding
        owner["standing"] = standing
        db.touch(owner)


# ---------------------------------------------------------------------------
# Creation helpers (fine, anomaly, publication supersede cascade)
# ---------------------------------------------------------------------------

def create_fine(building_id, cycle_id, fine_type, provisional, days_late=0):
    fine = db.new_common({
        "id": db.new_id(),
        "building_id": building_id,
        "cycle_id": cycle_id,
        "fine_type": fine_type,
        "status": "ASSESSED",
        "provisional_amount_cents": provisional,
        "final_amount_cents": None,
        "days_late": days_late,
        "assessed_at": db.LOGICAL_CLOCK,
        "noticed_at": None,
        "paid_at": None,
        "waive_reason": None,
    })
    store.fines[fine["id"]] = fine
    building = store.buildings.get(building_id)
    if building is not None:
        recompute_owner_exposure(building["owner_id"])
    return fine


def create_anomaly(report_id, anomaly_type, detail):
    flag = db.new_common({
        "id": db.new_id(),
        "report_id": report_id,
        "anomaly_type": anomaly_type,
        "status": "OPEN",
        "detail": detail,
        "resolution_note": None,
        "waive_reason": None,
    })
    store.anomaly_flags[flag["id"]] = flag
    return flag


def supersede_publications_for(report):
    """PUBLISHED publications that included this report -> SUPERSEDED + replacement DRAFT."""
    for pub in list(store.publications.values()):
        if (pub["cycle_id"] == report["cycle_id"] and pub["status"] == "PUBLISHED"
                and report["id"] in pub.get("_included_report_ids", [])):
            pub["status"] = "SUPERSEDED"
            pub["superseded_at"] = db.LOGICAL_CLOCK
            db.touch(pub)
            replacement = db.new_common({
                "id": db.new_id(),
                "cycle_id": pub["cycle_id"],
                "publication_version": pub["publication_version"] + 1,
                "status": "DRAFT",
                "included_report_count": 0,
                "published_at": None,
                "superseded_at": None,
                "_included_report_ids": [],
            })
            store.publications[replacement["id"]] = replacement


# ---------------------------------------------------------------------------
# Calculation: energy_score_labeling (as-reported + weather-normalized variants)
# ---------------------------------------------------------------------------

def compute_scores_and_label(report, cycle, std):
    if D(report["data_completeness_pct"]) < SCORE_MIN_COMPLETENESS_PCT:
        report["score_as_reported"] = None
        report["score_weather_normalized"] = None
        report["label_grade"] = "INSUFFICIENT_DATA"
        return
    site = D(report["site_eui"])
    raw = SCORE_BASE + (D(std["median_eui"]) - site) * D(std["score_slope"])
    score = max(SCORE_MIN, min(SCORE_MAX, int(round0(raw))))
    report["score_as_reported"] = score
    normalized_eui = round2(site * D(cycle["weather_adjustment_factor"]))
    raw_wn = SCORE_BASE + (D(std["median_eui"]) - normalized_eui) * D(std["score_slope"])
    score_wn = max(SCORE_MIN, min(SCORE_MAX, int(round0(raw_wn))))
    report["score_weather_normalized"] = score_wn
    if score >= 90:
        label = "A"
    elif score >= 75:
        label = "B"
    elif score >= 50:
        label = "C"
    elif score >= 25:
        label = "D"
    else:
        label = "E"
    report["label_grade"] = label


# ---------------------------------------------------------------------------
# Calculation: trajectory_target_eui (pinned evaluation order)
# ---------------------------------------------------------------------------

def compute_target_eui(report, cycle, building, std):
    candidates = []
    for r in store.reports.values():
        if r["building_id"] != building["id"] or r["id"] == report["id"]:
            continue
        if r["status"] not in ("VERIFIED", "CERTIFIED"):
            continue
        rc = store.cycles.get(r["cycle_id"])
        if rc is None or rc["cycle_year"] >= cycle["cycle_year"]:
            continue
        if r.get("verified_site_eui") is None:
            continue
        candidates.append((rc["cycle_year"], r["created_at"], r["_seq"], r))
    if candidates:
        candidates.sort(key=lambda t: (t[0], t[1], t[2]))
        baseline = D(candidates[0][3]["verified_site_eui"])
        years = cycle["cycle_year"] - candidates[0][0]
    else:
        baseline = D(std["baseline_eui_default"])
        years = 1
    retention = D(1) - D(std["annual_reduction_pct"]) / D(100)
    return f2(baseline * (retention ** years))


# ---------------------------------------------------------------------------
# Calculation: performance_shortfall_fine (close-filing sweep)
# ---------------------------------------------------------------------------

def performance_shortfall_check(building, cycle, report):
    std = perf_std(cycle, building["property_type"])
    if std is None:
        return
    target = report.get("target_eui")
    if target is None:
        return
    target_d = D(target)
    threshold = round2(target_d * (D(1) + D(std["shortfall_tolerance_pct"]) / D(100)))
    site = D(report["site_eui"])
    if site <= threshold:
        return
    shortfall_pct = round2((site - threshold) / target_d * D(100))
    fine = int(round0(D(building["gross_floor_area_sqft"])
                      * D(std["fine_rate_cents_per_sqft"]) * shortfall_pct))
    fine = min(fine, int(std["performance_fine_cap_cents"]))
    create_fine(building["id"], cycle["id"], "PERFORMANCE_SHORTFALL", fine)


def close_filing_sweep(cycle):
    for b in list(store.buildings.values()):
        if not covered(b, cycle):
            continue
        rep = report_for(b["id"], cycle["id"])
        if rep is None or rep["status"] not in ("VERIFIED", "CERTIFIED"):
            create_fine(b["id"], cycle["id"], "NON_COMPLIANCE",
                        int(cycle["non_compliance_fine_cents"]))
        else:
            performance_shortfall_check(b, cycle, rep)


# ---------------------------------------------------------------------------
# Calculation: yoy_anomaly_detection (at submit). Does NOT touch the report;
# the submit orchestrator touches once after all mutations.
# ---------------------------------------------------------------------------

def yoy_anomaly_check(report, cycle, building):
    priors = []
    for r in store.reports.values():
        if r["building_id"] != building["id"] or r["id"] == report["id"]:
            continue
        if r["status"] not in ("VERIFIED", "CERTIFIED"):
            continue
        rc = store.cycles.get(r["cycle_id"])
        if rc is None or rc["cycle_year"] >= cycle["cycle_year"]:
            continue
        priors.append((rc["cycle_year"], r["created_at"], r["_seq"], r))
    if not priors:
        return
    priors.sort(key=lambda t: (t[0], t[1], t[2]))
    prior = priors[-1][3]
    prior_kbtu = prior["aggregated_kbtu"]
    if not prior_kbtu or prior_kbtu <= 0:
        return
    delta = round2(abs(D(report["aggregated_kbtu"]) - D(prior_kbtu)) / D(prior_kbtu) * D(100))
    if delta <= D(cycle["anomaly_yoy_threshold_pct"]):
        return
    for f in store.anomaly_flags.values():
        if f["report_id"] == report["id"] and f["anomaly_type"] == "CONSUMPTION_SPIKE":
            return
    create_anomaly(report["id"], "CONSUMPTION_SPIKE",
                   "Year-over-year aggregated consumption delta of %s%% exceeds the "
                   "cycle threshold" % delta)
    report["status"] = "FLAGGED"


# ---------------------------------------------------------------------------
# Calculation: correction_delta_evaluation (post-verification usage void).
# Does NOT touch the report; the void cascade's recompute already touched it.
# ---------------------------------------------------------------------------

def correction_delta_check(report, cycle):
    base_raw = report.get("verified_site_eui")
    if base_raw is None:
        return
    base = D(base_raw)
    new = D(report["site_eui"])
    if base == 0:
        if new == 0:
            return
        delta = Decimal("999999999")
    else:
        delta = round2(abs(new - base) / base * D(100))
    if delta > D(cycle["correction_tolerance_pct"]):
        report["status"] = "FLAGGED"
        create_anomaly(report["id"], "VERIFICATION_REOPENED",
                       "Post-verification usage correction moved site EUI by %s%%, beyond "
                       "the correction tolerance" % delta)
        supersede_publications_for(report)


# ---------------------------------------------------------------------------
# Usage-record cascades
# ---------------------------------------------------------------------------

def usage_upload_cascade(building_id, record):
    """Recompute aggregates on the building's DRAFT|FLAGGED report for the record's year."""
    year = record_year(record)
    if year is None:
        return
    cycle = cycle_by_year(year)
    if cycle is None:
        return
    report = report_for(building_id, cycle["id"])
    if report is None or report["status"] not in ("DRAFT", "FLAGGED"):
        return
    recompute_report(report, with_completeness=False)


def usage_void_cascade(building_id, years):
    """Recompute the affected reports (any status) and run the correction check."""
    for year in sorted(years):
        cycle = cycle_by_year(year)
        if cycle is None:
            continue
        report = report_for(building_id, cycle["id"])
        if report is None:
            continue
        recompute_report(report,
                         with_completeness=(report["status"] in ("DRAFT", "FLAGGED")))
        if report["status"] in ("VERIFIED", "CERTIFIED"):
            correction_delta_check(report, cycle)


# ---------------------------------------------------------------------------
# Verification sign-off: aggregates + scores + label + target, freeze baseline
# ---------------------------------------------------------------------------

def verify_report(report, cycle, building, std):
    # Final verification-time recompute of all three aggregates.
    report["aggregated_kbtu"] = compute_aggregated_kbtu(building, cycle)
    report["site_eui"] = compute_site_eui(report["aggregated_kbtu"], building)
    report["data_completeness_pct"] = compute_completeness(building, cycle)
    report["status"] = "VERIFIED"
    report["verified_at"] = db.LOGICAL_CLOCK
    report["verified_site_eui"] = report["site_eui"]
    compute_scores_and_label(report, cycle, std)
    report["target_eui"] = compute_target_eui(report, cycle, building, std)
    db.touch(report)


def suppress_scores(report):
    report["score_as_reported"] = None
    report["score_weather_normalized"] = None
    report["label_grade"] = "INSUFFICIENT_DATA"
