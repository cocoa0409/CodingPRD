"""The eight calculation rules of the spec, plus the graph helpers they need.

Every rounding step here is round-half-up and every truncation is toward zero
(PRD section 2.8).  Decimal is used throughout; float never participates in a
rounded comparison.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

import clock
import constants as C
from db import store


# --------------------------------------------------------------------------
# rounding primitives
# --------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def truncate(value, places):
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_DOWN)


def as_number(value):
    """Decimal -> JSON number."""
    if value is None:
        return None
    return float(value)


# --------------------------------------------------------------------------
# graph helpers
# --------------------------------------------------------------------------
def method_of_monitor(monitor):
    return store.reference_methods.get(monitor["reference_method_id"])


def pollutant_of_monitor(monitor):
    method = method_of_monitor(monitor)
    if method is None:
        return None
    return store.pollutants.get(method["pollutant_id"])


def monitor_of_batch(batch):
    return store.monitors.get(batch["monitor_id"])


def pollutant_of_batch(batch):
    monitor = monitor_of_batch(batch)
    if monitor is None:
        return None
    return pollutant_of_monitor(monitor)


def site_of_batch(batch):
    monitor = monitor_of_batch(batch)
    if monitor is None:
        return None
    return store.sites.get(monitor["site_id"])


def network_of_site(site):
    return store.networks.get(site["network_id"])


def sites_of_network(network_id):
    return [s for s in store.sites.values() if s["network_id"] == network_id]


def monitors_of_site(site_id):
    return [m for m in store.monitors.values() if m["site_id"] == site_id]


def monitors_of_network(network_id):
    result = []
    for site in store.sites.values():
        if site["network_id"] == network_id:
            result.extend(monitors_of_site(site["id"]))
    return result


def batches_of_monitor(monitor_id):
    return [b for b in store.data_batches.values() if b["monitor_id"] == monitor_id]


def invalidations_of_batch(batch_id):
    return [i for i in store.invalidations.values() if i["data_batch_id"] == batch_id]


def exclusions_of_batch(batch_id):
    return [e for e in store.exclusions.values() if e["data_batch_id"] == batch_id]


def exclusions_of_demonstration(demonstration_id):
    return [e for e in store.exclusions.values() if e["demonstration_id"] == demonstration_id]


# --------------------------------------------------------------------------
# quarter arithmetic
# --------------------------------------------------------------------------
def quarter_start(year, quarter):
    return datetime(year, 3 * (quarter - 1) + 1, 1, tzinfo=timezone.utc)


def next_quarter_start(year, quarter):
    if quarter == 4:
        return datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    return quarter_start(year, quarter + 1)


def quarter_hour_span(year, quarter):
    delta = next_quarter_start(year, quarter) - quarter_start(year, quarter)
    return int(delta.total_seconds() // 3600)


def whole_days_between(start, end):
    """floor of the elapsed whole days; never a partial day."""
    return int((end - start).total_seconds() // 86400)


# --------------------------------------------------------------------------
# 1. siting_criteria_evaluation
# --------------------------------------------------------------------------
def siting_criteria_evaluation(site):
    """Full input precision; nothing is rounded."""
    violations = set()
    probe = site["probe_height_m"]
    if not (C.PROBE_HEIGHT_MIN_M <= probe <= C.PROBE_HEIGHT_MAX_M):
        violations.add("PROBE_HEIGHT")
    if site["site_type"] == "POPULATION_ORIENTED" and site["distance_to_roadway_m"] < C.POPULATION_ROADWAY_MIN_M:
        violations.add("ROADWAY_SETBACK")
    if site["site_type"] == "SOURCE_ORIENTED" and site["distance_to_source_m"] > C.SOURCE_MAX_DISTANCE_M:
        violations.add("SOURCE_DISTANCE")
    if site["site_type"] == "BACKGROUND" and site["distance_to_roadway_m"] < C.BACKGROUND_ROADWAY_MIN_M:
        violations.add("BACKGROUND_ISOLATION")
    required_clearance = C.OBSTRUCTION_RATIO * (site["obstruction_height_m"] - probe)
    if required_clearance > 0 and site["distance_to_obstruction_m"] < required_clearance:
        violations.add("OBSTRUCTION_CLEARANCE")
    codes = sorted(violations)
    return codes, len(codes) > 0


def refresh_siting(site):
    codes, required = siting_criteria_evaluation(site)
    site["siting_violation_codes"] = codes
    site["siting_waiver_required"] = required
    return site


# --------------------------------------------------------------------------
# 2. qc_event_outcome_evaluation
# --------------------------------------------------------------------------
def qc_event_outcome_evaluation(event_type, method, span_drift_pct, zero_drift_value, declared_failure):
    """Absolute drift is rounded to two decimals BEFORE the comparison; the
    comparison at the limit is inclusive, so d == limit is PASS."""
    if event_type == "SPAN_CHECK":
        reading = round_half_up(abs(dec(span_drift_pct)), 2)
        limit = dec(method["max_span_drift_pct"])
    elif event_type == "ZERO_CHECK":
        reading = round_half_up(abs(dec(zero_drift_value)), 2)
        limit = dec(method["zero_drift_limit"])
    else:
        return "FAIL" if declared_failure else "PASS"
    if reading <= limit:
        return "PASS"
    if reading <= limit * dec(C.WARN_MULTIPLIER):
        return "WARN"
    return "FAIL"


# --------------------------------------------------------------------------
# 3. monitor_qc_posture (two variants)
# --------------------------------------------------------------------------
def _band(elapsed_days, interval):
    if elapsed_days <= interval:
        return "QC_CURRENT"
    if elapsed_days <= interval + C.QC_GRACE_DAYS:
        return "QC_DUE"
    return "QC_DELINQUENT"


def monitor_qc_posture(monitor):
    """Returns (calendar_elapsed_posture, in_service_elapsed_posture)."""
    method = method_of_monitor(monitor)
    if method is None:
        return monitor.get("qc_posture", "QC_DUE"), monitor.get("qc_posture_in_service", "QC_DUE")
    baseline = monitor.get("last_span_check_at") or monitor.get("installed_at")
    if baseline is None:
        return monitor.get("qc_posture", "QC_DUE"), monitor.get("qc_posture_in_service", "QC_DUE")
    interval = method["required_span_check_interval_days"]
    elapsed = whole_days_between(baseline, clock.now())
    calendar = _band(elapsed, interval)
    in_service_elapsed = elapsed - monitor.get("out_of_service_day_count", 0)
    if in_service_elapsed < 0:
        in_service_elapsed = 0
    in_service = _band(in_service_elapsed, interval)
    return calendar, in_service


def refresh_qc_posture(monitor):
    """A DECOMMISSIONED instrument keeps its last computed posture."""
    if monitor["monitor_status"] == "DECOMMISSIONED":
        return monitor
    calendar, in_service = monitor_qc_posture(monitor)
    monitor["qc_posture"] = calendar
    monitor["qc_posture_in_service"] = in_service
    return monitor


def effective_qc_posture(monitor):
    if monitor["monitor_status"] == "DECOMMISSIONED":
        return monitor.get("qc_posture", "QC_DUE")
    return monitor_qc_posture(monitor)[0]


# --------------------------------------------------------------------------
# 4. batch_hour_accounting  (S1 .. S7, order is normative)
# --------------------------------------------------------------------------
def batch_hour_accounting(batch):
    applied = [i for i in invalidations_of_batch(batch["id"]) if i["status"] == "APPLIED"]
    # S1 excused hours leave the denominator
    excused = sum(i["hours_affected"] for i in applied if i["invalidation_code"] in C.EXCUSED_CODES)
    # S2 non-excused hours stay in the denominator and count against the quarter
    invalidated = sum(i["hours_affected"] for i in applied if i["invalidation_code"] not in C.EXCUSED_CODES)
    # S3 only EFFECTIVE exclusions contribute
    event_excluded = sum(
        e["hours_affected"] for e in exclusions_of_batch(batch["id"]) if e["status"] == "EFFECTIVE"
    )
    # S4 adjusted denominator
    adjusted = batch["scheduled_hour_count"] - excused - event_excluded
    # S5 valid hours
    valid = adjusted - invalidated
    # S6 completeness, rounded once to one decimal
    if adjusted == 0:
        completeness = Decimal("0.0")
    else:
        completeness = round_half_up(dec(100) * dec(valid) / dec(adjusted), 1)
    # S7 threshold comparison against the ROUNDED figure, inclusive
    pollutant = pollutant_of_batch(batch)
    if pollutant is None:
        eligible = False
    else:
        eligible = completeness >= dec(pollutant["completeness_threshold_pct"])
    return {
        "excused_hour_count": excused,
        "invalidated_hour_count": invalidated,
        "event_excluded_hour_count": event_excluded,
        "adjusted_scheduled_hour_count": adjusted,
        "valid_hour_count": valid,
        "completeness_pct": completeness,
        "regulatory_use_eligible": eligible,
    }


def refresh_hour_accounting(batch):
    batch.update(batch_hour_accounting(batch))
    return batch


def batch_is_eligible(batch):
    return batch_hour_accounting(batch)["regulatory_use_eligible"]


# --------------------------------------------------------------------------
# 5. primary_monitor_selection
# --------------------------------------------------------------------------
PRIMARY_POOL_STATUSES = ("OPERATING", "OUT_OF_SERVICE", "DECOMMISSIONED")


def primary_monitor_selection(site_id, pollutant_id):
    """Returns the chosen monitor, or None when the candidate pool is empty."""
    candidates = []
    for monitor in monitors_of_site(site_id):
        if not monitor.get("is_primary_for_design_value"):
            continue
        if monitor["monitor_status"] not in PRIMARY_POOL_STATUSES:
            continue
        pollutant = pollutant_of_monitor(monitor)
        if pollutant is None or pollutant["id"] != pollutant_id:
            continue
        candidates.append(monitor)
    if not candidates:
        return None
    candidates.sort(key=lambda m: (m["poc"], m["created_at"], m["_seq"]))
    return candidates[0]


# --------------------------------------------------------------------------
# 6. design_value_computation (two variants)
# --------------------------------------------------------------------------
def _concentration_of(batch, variant):
    if variant == "EXCLUDING_CONCURRED_EVENTS":
        has_effective = any(
            e["status"] == "EFFECTIVE" for e in exclusions_of_batch(batch["id"])
        )
        if has_effective and batch.get("quarterly_mean_concentration_event_adjusted") is not None:
            return dec(batch["quarterly_mean_concentration_event_adjusted"])
    return dec(batch["quarterly_mean_concentration"])


def design_value_computation(pollutant, primary_monitor_id, period_end_year, variant):
    places = pollutant["rounding_decimals"]
    years = [period_end_year - 2, period_end_year - 1, period_end_year]
    annual_statistics = []
    complete_year_count = 0
    monitor_batches = batches_of_monitor(primary_monitor_id)
    for year in years:
        qualifying = [
            b for b in monitor_batches
            if b["year"] == year
            and b["validation_status"] == "VALIDATED"
            and batch_is_eligible(b)
        ]
        if len(qualifying) != C.QUARTERS_PER_YEAR:
            continue
        complete_year_count += 1
        values = [_concentration_of(b, variant) for b in qualifying]
        form = pollutant["standard_form"]
        if form == "ANNUAL_MEAN":
            raw_annual = sum(values, Decimal(0)) / dec(C.QUARTERS_PER_YEAR)
        elif form == "FOURTH_MAX_8HR":
            fourths = [dec(b["fourth_high_daily_max"]) for b in qualifying
                       if b.get("fourth_high_daily_max") is not None]
            raw_annual = max(fourths) if fourths else Decimal(0)
        else:  # PERCENTILE_98
            raw_annual = max(values)
        # STEP-1 rounding, once per year
        annual_statistics.append(round_half_up(raw_annual, places))
    if complete_year_count != pollutant["design_value_years"]:
        design_value = None
        attainment_status = "INSUFFICIENT_DATA"
    else:
        # STEP-2: average the ALREADY ROUNDED annual statistics, then truncate
        raw_dv = sum(annual_statistics, Decimal(0)) / dec(pollutant["design_value_years"])
        design_value = truncate(raw_dv, places)
        if design_value > dec(pollutant["primary_standard_value"]):
            attainment_status = "NONATTAINMENT"
        else:
            attainment_status = "ATTAINMENT"
    return {
        "annual_statistics": annual_statistics,
        "complete_year_count": complete_year_count,
        "design_value": design_value,
        "attainment_status": attainment_status,
    }


# --------------------------------------------------------------------------
# site.current_attainment_status
# --------------------------------------------------------------------------
def current_attainment_status(site_id):
    rows = [
        d for d in store.design_values.values()
        if d["site_id"] == site_id and d["status"] in ("PROVISIONAL", "FINAL")
    ]
    if not rows:
        return "UNDETERMINED"
    rows.sort(key=lambda d: (d["created_at"], d["period_end_year"], d["_seq"]), reverse=True)
    return rows[0]["attainment_status"]


def operating_monitor_count(site_id):
    return len([m for m in monitors_of_site(site_id) if m["monitor_status"] == "OPERATING"])


# --------------------------------------------------------------------------
# network census (PRD section 2.9)
# --------------------------------------------------------------------------
_STATUS_COUNTER = {
    "PROPOSED": "proposed_site_count",
    "SITING_APPROVED": "approved_site_count",
    "OPERATING": "operating_site_count",
    "SUSPENDED": "suspended_site_count",
    "SHUTDOWN": "shutdown_site_count",
    "RELOCATED": "relocated_site_count",
}

DELINQUENT_COUNTED_MONITOR_STATUSES = {"APPROVED", "OPERATING", "OUT_OF_SERVICE"}
WAIVER_COUNTED_SITE_STATUSES = {"SITING_APPROVED", "OPERATING", "SUSPENDED"}


def network_census(network_id):
    census = {
        "total_site_count": 0,
        "proposed_site_count": 0,
        "approved_site_count": 0,
        "operating_site_count": 0,
        "suspended_site_count": 0,
        "shutdown_site_count": 0,
        "relocated_site_count": 0,
        "delinquent_monitor_count": 0,
        "waiver_required_site_count": 0,
    }
    waivered = 0
    for site in sites_of_network(network_id):
        census["total_site_count"] += 1
        key = _STATUS_COUNTER.get(site["status"])
        if key:
            census[key] += 1
        _codes, required = siting_criteria_evaluation(site)
        if required and site["status"] in WAIVER_COUNTED_SITE_STATUSES:
            waivered += 1
    census["waiver_required_site_count"] = waivered
    delinquent = 0
    for monitor in monitors_of_network(network_id):
        if monitor["monitor_status"] not in DELINQUENT_COUNTED_MONITOR_STATUSES:
            continue
        if effective_qc_posture(monitor) == "QC_DELINQUENT":
            delinquent += 1
    census["delinquent_monitor_count"] = delinquent
    return census


# --------------------------------------------------------------------------
# 7. certification_package_rollup
# --------------------------------------------------------------------------
def certification_deadline(year):
    return datetime(year + 1, C.CERTIFICATION_DEADLINE_MONTH, C.CERTIFICATION_DEADLINE_DAY,
                    0, 0, 0, tzinfo=timezone.utc)


def package_scope_batches(network_id, pollutant_id, year):
    """Every quarter reached through Monitor -> Site -> Network and
    Monitor -> ReferenceMethod -> Pollutant for the package's year, in ANY
    validation standing."""
    result = []
    for batch in store.data_batches.values():
        if batch["year"] != year:
            continue
        monitor = monitor_of_batch(batch)
        if monitor is None:
            continue
        site = store.sites.get(monitor["site_id"])
        if site is None or site["network_id"] != network_id:
            continue
        pollutant = pollutant_of_monitor(monitor)
        if pollutant is None or pollutant["id"] != pollutant_id:
            continue
        result.append(batch)
    return result


def package_selected_batches(package):
    selected = [
        b for b in package_scope_batches(package["network_id"], package["pollutant_id"], package["year"])
        if b["validation_status"] == "VALIDATED"
    ]
    selected.sort(key=lambda b: (b["year"], b["quarter"], b["created_at"], b["_seq"]))
    return selected


def certification_package_rollup(package):
    selected = package_selected_batches(package)
    included = len(selected)
    accounting = [batch_hour_accounting(b) for b in selected]
    eligible = len([a for a in accounting if a["regulatory_use_eligible"]])
    numerator = sum(a["valid_hour_count"] for a in accounting)
    denominator = sum(a["adjusted_scheduled_hour_count"] for a in accounting)
    if denominator == 0:
        rollup = Decimal("0.0")
    else:
        rollup = round_half_up(dec(100) * dec(numerator) / dec(denominator), 1)
    return {
        "included_batch_count": included,
        "eligible_batch_count": eligible,
        "rollup_completeness_pct": rollup,
        "certification_ready": included >= 1 and eligible == included,
    }


# --------------------------------------------------------------------------
# 8. network_adequacy_score
# --------------------------------------------------------------------------
def required_population_site_count(population):
    if population < 500000:
        return 1
    if population < 1000000:
        return 2
    if population < 2500000:
        return 3
    return 4


def network_adequacy_score(network):
    # A: population tier
    required_pop = required_population_site_count(network["metropolitan_population"])
    # B: credited coverage, each credit individually capped
    operating = [s for s in sites_of_network(network["id"]) if s["status"] == "OPERATING"]
    population_credit = min(
        len([s for s in operating if s["site_type"] == "POPULATION_ORIENTED"]), required_pop)
    source_credit = min(
        len([s for s in operating if s["site_type"] == "SOURCE_ORIENTED"]), C.REQUIRED_SOURCE_SITES)
    background_credit = min(
        len([s for s in operating if s["site_type"] == "BACKGROUND"]), C.REQUIRED_BACKGROUND_SITES)
    denominator = required_pop + C.REQUIRED_SOURCE_SITES + C.REQUIRED_BACKGROUND_SITES
    coverage_ratio = round_half_up(
        dec(population_credit + source_credit + background_credit) / dec(denominator), 4)
    # C: two multiplicative, individually capped degradation factors
    census = network_census(network["id"])
    qc_factor = Decimal(1) - min(dec(C.QC_PENALTY_CAP),
                                 dec(C.QC_PENALTY_PER_MONITOR) * dec(census["delinquent_monitor_count"]))
    siting_factor = Decimal(1) - min(dec(C.SITING_PENALTY_CAP),
                                     dec(C.SITING_PENALTY_PER_SITE) * dec(census["waiver_required_site_count"]))
    adequacy_score = round_half_up(dec(100) * coverage_ratio * qc_factor * siting_factor, 1)
    # D: banding, inclusive at each lower bound
    if adequacy_score >= dec(C.ADEQUATE_MIN_SCORE):
        tier = "ADEQUATE"
    elif adequacy_score >= dec(C.CONDITIONAL_MIN_SCORE):
        tier = "CONDITIONAL"
    else:
        tier = "INADEQUATE"
    return {
        "required_population_site_count": required_pop,
        "coverage_ratio": coverage_ratio,
        "adequacy_score": adequacy_score,
        "adequacy_tier": tier,
    }


# --------------------------------------------------------------------------
# the reference-method designation test (validation priority 50)
# --------------------------------------------------------------------------
def method_is_currently_designated(method):
    if method is None:
        return False
    if method["designation_status"] not in C.USABLE_DESIGNATION_STATUSES:
        return False
    if method["effective_from"] > clock.now():
        return False
    withdrawn = method.get("withdrawn_on")
    if withdrawn is not None and withdrawn <= clock.now():
        return False
    return True
