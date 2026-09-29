"""The recomputation cascade of PRD 2.10 and the calculations of SCAFFOLD 1.3.

A recompute refreshes updated_at / version only when it actually changed a
stored value: writing a derived field is a mutation (PRD 2.5), leaving one
untouched is not.
"""

from decimal import Decimal

from db import TS, base_record, sorted_rows, store, touch
from errors import err
from services.calc import (ACTIVE_STATUSES, CATEGORIES, CATEGORY_WEIGHT,
                           COACHING_TRIGGER, INVESTIGATION_ALERT_COUNT,
                           LOOKBACK_DAYS, OOS_ADDER_CAP,
                           OOS_ADDER_PER_VIOLATION, band_for_iss, credit_tier,
                           dec, num, percentile_for, power_unit_exposure,
                           quota_limit_for_segment, rhu, time_weight_for_age,
                           utilization_factor_for, whole_days)

OPEN_COACHING_STATUSES = ("ASSIGNED", "IN_PROGRESS", "OVERDUE")
WAIVABLE_STATUSES = ("ASSIGNED", "IN_PROGRESS")

CARRIER_KEYS = (
    "utilization_factor",
    "carrier_segment",
    "challenge_quota_limit",
    "challenge_quota_used",
    "oos_violation_count_24mo",
    "scored_violation_count",
    "unattributed_violation_count",
    "accepted_challenge_count_24mo",
    "resolved_challenge_count_24mo",
    "open_coaching_count",
    "open_alert_count",
    "max_percentile",
    "intervention_status",
    "iss_pre_credit_value",
    "data_quality_credit_pct",
    "iss_value",
    "selection_band",
)

DRIVER_KEYS = (
    "attributed_violation_count",
    "strict_attribution_score",
    "adjudicated_attribution_score",
    "coaching_required",
    "open_coaching_count",
)

REPORT_ROLLUP_KEYS = ("active_violation_count", "total_time_weighted_severity")

SCORE_KEYS = (
    "scoring_run_id",
    "threshold_id",
    "snapshot_utc",
    "total_time_weighted_severity",
    "challenged_time_weighted_severity",
    "included_violation_count",
    "relevant_inspection_count",
    "denominator_value",
    "provisional_measure",
    "certified_measure",
    "percentile",
    "alert_status",
)


def snap(rec, keys):
    state = {}
    for key in keys:
        value = rec.get(key)
        state[key] = value.raw if isinstance(value, TS) else value
    return state


def finish(rec, before):
    """Bump the record only when one of the watched fields actually moved."""
    for key, value in before.items():
        current = rec.get(key)
        if isinstance(current, TS):
            current = current.raw
        if current != value:
            touch(rec)
            return True
    return False


# --------------------------------------------------------------------------
# collection helpers
# --------------------------------------------------------------------------

def violations_of_report(report_id):
    return sorted_rows([v for v in store.violations.values()
                        if v["report_id"] == report_id])


def reports_of_carrier(carrier_id):
    return [r for r in store.reports.values()
            if r.get("attributed_carrier_id") == carrier_id]


def adjudications_of_violation(violation_id):
    return sorted_rows([a for a in store.adjudications.values()
                        if a["violation_id"] == violation_id])


def assignments_of_driver(driver_id):
    return sorted_rows([c for c in store.coaching.values()
                        if c["driver_id"] == driver_id])


def assignments_of_violation(violation_id):
    return sorted_rows([c for c in store.coaching.values()
                        if c.get("violation_id") == violation_id])


def all_carriers():
    return sorted_rows(list(store.carriers.values()))


def all_drivers():
    return sorted_rows(list(store.drivers.values()))


# --------------------------------------------------------------------------
# violation severity pin
# --------------------------------------------------------------------------

def pin_violation(violation, report, basis_dt):
    """calculations.violation_severity_pin. Returns True when a field moved."""
    if violation["status"] == "REMOVED":
        if violation.get("time_weighted_severity") != 0.0:
            violation["time_weighted_severity"] = 0.0
            return True
        return False
    code = store.violation_codes.get(violation["effective_violation_code_id"])
    if code is None:
        return False
    age = whole_days(basis_dt, report["inspection_start"].dt)
    weight = time_weight_for_age(age)
    code_weight = code["severity_weight"]
    oos_add_on = code["oos_add_on"] if violation.get("out_of_service") else 0
    severity = float((dec(code_weight) + dec(oos_add_on)) * dec(weight))
    changed = (violation.get("time_weight") != weight
               or violation.get("code_weight_snapshot") != code_weight
               or violation.get("oos_add_on_snapshot") != oos_add_on
               or violation.get("pinned_violation_code_version") != code["version"]
               or violation.get("time_weighted_severity") != severity
               or violation.get("basic_category") != code["basic_category"])
    violation["time_weight"] = weight
    violation["code_weight_snapshot"] = code_weight
    violation["oos_add_on_snapshot"] = oos_add_on
    violation["pinned_violation_code_version"] = code["version"]
    violation["time_weighted_severity"] = severity
    violation["basic_category"] = code["basic_category"]
    return changed


def repin_violation(violation, basis_dt=None):
    """Re-pin one violation from the current code row (correction side effect)."""
    report = store.reports.get(violation["report_id"])
    if report is None:
        return False
    return pin_violation(violation, report, basis_dt or store.now())


def has_stale_code_pin(violation):
    pinned = violation.get("pinned_violation_code_version")
    if pinned is None:
        return False
    code = store.violation_codes.get(violation["effective_violation_code_id"])
    if code is None:
        return False
    return code["version"] != pinned


# --------------------------------------------------------------------------
# report rollup
# --------------------------------------------------------------------------

def rollup_report(report):
    """Recompute the report's rolled-up totals; bumps the report when they move."""
    before = snap(report, REPORT_ROLLUP_KEYS)
    rows = violations_of_report(report["id"])
    active = [v for v in rows if v["status"] in ACTIVE_STATUSES]
    total = dec(0)
    for v in active:
        total += dec(v.get("time_weighted_severity") or 0)
    report["active_violation_count"] = len(active)
    report["total_time_weighted_severity"] = float(rhu(total, 1))
    return finish(report, before)


# --------------------------------------------------------------------------
# BasicScore rows
# --------------------------------------------------------------------------

def score_rows_of_carrier(carrier_id):
    return [s for s in store.basic_scores.values() if s["carrier_id"] == carrier_id]


def score_row(carrier_id, category):
    for row in store.basic_scores.values():
        if row["carrier_id"] == carrier_id and row["basic_category"] == category:
            return row
    return None


def select_threshold(category, segment, snapshot_dt):
    candidates = [t for t in store.thresholds.values()
                  if t["basic_category"] == category
                  and t["carrier_segment"] == segment
                  and t["effective_from"].dt <= snapshot_dt]
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t["effective_from"].dt, t["created_at"].dt,
                                   t["_seq"]),
                    reverse=True)
    return candidates[0]


def relevant_inspection_count(carrier_id, snapshot_dt):
    count = 0
    for report in reports_of_carrier(carrier_id):
        if report["status"] != "SCORED":
            continue
        if whole_days(snapshot_dt, report["inspection_start"].dt) <= LOOKBACK_DAYS:
            count += 1
    return count


def included_violations(carrier_id, category):
    result = []
    for v in store.violations.values():
        if v["status"] not in ACTIVE_STATUSES:
            continue
        if v.get("basic_category") != category:
            continue
        if (v.get("time_weight") or 0) <= 0:
            continue
        report = store.reports.get(v["report_id"])
        if report is None or report["status"] != "SCORED":
            continue
        if report.get("attributed_carrier_id") != carrier_id:
            continue
        result.append(v)
    return result


def recompute_basic_scores(carrier, snapshot_ts, run_id=None, create=False,
                           strict=False):
    """calculations.basic_measure_recompute over the carrier's four rows."""
    existing = score_rows_of_carrier(carrier["id"])
    if not existing and not create:
        return 0
    snapshot_dt = snapshot_ts.dt
    factor = utilization_factor_for(carrier["annual_vmt"],
                                    carrier["average_power_units"])
    carrier["utilization_factor"] = float(factor)
    exposure = power_unit_exposure(carrier["average_power_units"], factor)
    ric = relevant_inspection_count(carrier["id"], snapshot_dt)
    written = 0
    for category in CATEGORIES:
        rows = included_violations(carrier["id"], category)
        total = dec(0)
        challenged = dec(0)
        for v in rows:
            severity = dec(v.get("time_weighted_severity") or 0)
            total += severity
            if v.get("under_challenge"):
                challenged += severity
        included_count = len(rows)
        if category == "VEHICLE_MAINTENANCE":
            denominator = dec(ric)
            if denominator < Decimal("1.0"):
                denominator = Decimal("1.0")
        elif category == "HOURS_OF_SERVICE":
            alternative = dec(ric) * Decimal("2.0")
            denominator = exposure if exposure < alternative else alternative
            if denominator < Decimal("1.0"):
                denominator = Decimal("1.0")
        else:
            denominator = exposure
        provisional = rhu(total / denominator, 3)
        certified = rhu((total - challenged) / denominator, 3)
        threshold = select_threshold(category, carrier["carrier_segment"],
                                     snapshot_dt)
        if threshold is None and included_count > 0 and strict:
            raise err("ERR_THRESHOLD_NOT_CONFIGURED")
        if ric == 0:
            percentile = None
            alert = "NOT_ENOUGH_DATA"
        else:
            percentile = percentile_for(certified, threshold)
            if threshold is None:
                alert = "CLEAR"
            elif percentile >= dec(threshold["intervention_percentile"]):
                alert = "ALERT"
            elif percentile >= dec(threshold["monitor_percentile"]):
                alert = "MONITOR"
            else:
                alert = "CLEAR"
        row = score_row(carrier["id"], category)
        before = None
        if row is None:
            row = base_record()
            row["carrier_id"] = carrier["id"]
            row["basic_category"] = category
            store.basic_scores[row["id"]] = row
        else:
            before = snap(row, SCORE_KEYS)
        row["scoring_run_id"] = run_id
        row["threshold_id"] = threshold["id"] if threshold else None
        row["snapshot_utc"] = snapshot_ts
        row["total_time_weighted_severity"] = float(rhu(total, 1))
        row["challenged_time_weighted_severity"] = float(rhu(challenged, 1))
        row["included_violation_count"] = included_count
        row["relevant_inspection_count"] = ric
        row["denominator_value"] = float(denominator)
        row["provisional_measure"] = float(provisional)
        row["certified_measure"] = float(certified)
        row["percentile"] = None if percentile is None else float(percentile)
        row["alert_status"] = alert
        if before is not None:
            finish(row, before)
        written += 1
    return written


# --------------------------------------------------------------------------
# carrier derived counters
# --------------------------------------------------------------------------

def recompute_carrier_counters(carrier):
    carrier_id = carrier["id"]
    oos = 0
    scored = 0
    unattributed = 0
    for v in store.violations.values():
        if v["status"] not in ACTIVE_STATUSES:
            continue
        report = store.reports.get(v["report_id"])
        if report is None or report["status"] != "SCORED":
            continue
        if report.get("attributed_carrier_id") != carrier_id:
            continue
        scored += 1
        if not v.get("driver_id"):
            unattributed += 1
        if v.get("out_of_service") and (v.get("time_weight") or 0) > 0:
            oos += 1
    carrier["oos_violation_count_24mo"] = oos
    carrier["scored_violation_count"] = scored
    carrier["unattributed_violation_count"] = unattributed
    carrier["challenge_quota_limit"] = quota_limit_for_segment(
        carrier["carrier_segment"])
    recompute_challenge_counters(carrier)
    count_open_coaching_carrier(carrier)


def recompute_challenge_counters(carrier):
    now = store.now()
    accepted = 0
    resolved = 0
    for ch in store.challenges.values():
        if ch.get("carrier_id") != carrier["id"]:
            continue
        if ch["status"] not in ("RESOLVED_ACCEPTED", "RESOLVED_REJECTED"):
            continue
        resolved_at = ch.get("resolved_at")
        if resolved_at is None:
            continue
        if whole_days(now, resolved_at.dt) > LOOKBACK_DAYS:
            continue
        resolved += 1
        if ch["status"] == "RESOLVED_ACCEPTED":
            accepted += 1
    carrier["accepted_challenge_count_24mo"] = accepted
    carrier["resolved_challenge_count_24mo"] = resolved


def count_open_coaching_carrier(carrier):
    count = 0
    for c in store.coaching.values():
        if (c.get("carrier_id") == carrier["id"]
                and c["status"] in OPEN_COACHING_STATUSES):
            count += 1
    carrier["open_coaching_count"] = count


def count_open_coaching_driver(driver):
    count = 0
    for c in store.coaching.values():
        if c["driver_id"] == driver["id"] and c["status"] in OPEN_COACHING_STATUSES:
            count += 1
    driver["open_coaching_count"] = count


def refresh_open_coaching(driver_id, carrier_id):
    driver = store.drivers.get(driver_id)
    if driver is not None:
        before = snap(driver, ("open_coaching_count",))
        count_open_coaching_driver(driver)
        finish(driver, before)
    carrier = store.carriers.get(carrier_id)
    if carrier is not None:
        before = snap(carrier, ("open_coaching_count",))
        count_open_coaching_carrier(carrier)
        finish(carrier, before)


# --------------------------------------------------------------------------
# intervention posture and screening risk
# --------------------------------------------------------------------------

def recompute_posture(carrier):
    rows = score_rows_of_carrier(carrier["id"])
    open_alerts = len([r for r in rows if r["alert_status"] == "ALERT"])
    best = None
    best_row = None
    for row in rows:
        if row.get("percentile") is None:
            continue
        value = dec(row["percentile"])
        if best is None or value > best:
            best = value
            best_row = row
    carrier["open_alert_count"] = open_alerts
    carrier["max_percentile"] = None if best is None else float(best)
    status = "NONE"
    if open_alerts >= INVESTIGATION_ALERT_COUNT:
        status = "INVESTIGATION"
    else:
        bar = None
        if best_row is not None and best_row.get("threshold_id"):
            threshold = store.thresholds.get(best_row["threshold_id"])
            if threshold is not None:
                bar = dec(threshold["investigation_percentile"])
        if best is not None and bar is not None and best >= bar:
            status = "INVESTIGATION"
        elif open_alerts >= 1:
            status = "WARNING_LETTER"
    carrier["intervention_status"] = status


def category_contributions(carrier):
    """Per-category screening contributions, each rounded before summing."""
    result = []
    excluded = []
    for category in CATEGORIES:
        row = score_row(carrier["id"], category)
        weight = CATEGORY_WEIGHT[category]
        percentile = None if row is None else row.get("percentile")
        alert = None if row is None else row.get("alert_status")
        if row is None or alert == "NOT_ENOUGH_DATA" or percentile is None:
            contribution = Decimal("0.00")
            excluded.append(category)
        else:
            contribution = rhu(dec(percentile) * weight, 2)
        result.append({
            "basic_category": category,
            "percentile": percentile,
            "category_weight": float(weight),
            "contribution": float(contribution),
            "alert_status": alert,
        })
    return result, excluded


def oos_adder_for(carrier):
    adder = dec(carrier.get("oos_violation_count_24mo") or 0) * OOS_ADDER_PER_VIOLATION
    if adder > OOS_ADDER_CAP:
        adder = OOS_ADDER_CAP
    return adder


def recompute_screening(carrier):
    contributions, _excluded = category_contributions(carrier)
    raw = dec(0)
    for entry in contributions:
        raw += dec(entry["contribution"])
    raw += oos_adder_for(carrier)
    if raw > Decimal("100.0"):
        raw = Decimal("100.0")
    pre_credit = rhu(raw, 1)
    tier = credit_tier(pre_credit)
    resolved = carrier.get("resolved_challenge_count_24mo") or 0
    divisor = dec(resolved if resolved > 0 else 1)
    accepted_rate = dec(carrier.get("accepted_challenge_count_24mo") or 0) / divisor
    if accepted_rate > Decimal("1.0"):
        accepted_rate = Decimal("1.0")
    credit = rhu(tier * accepted_rate, 4)
    iss = rhu(pre_credit * (Decimal("1.0") - credit), 1)
    carrier["iss_pre_credit_value"] = float(pre_credit)
    carrier["data_quality_credit_pct"] = float(credit)
    carrier["iss_value"] = float(iss)
    carrier["selection_band"] = band_for_iss(iss)


def epoch_for(carrier_id):
    """The aging basis already stamped on the carrier's score rows, if any."""
    for row in score_rows_of_carrier(carrier_id):
        if row.get("snapshot_utc") is not None:
            return row["snapshot_utc"]
    return None


def recount_carrier(carrier):
    """Counters -> intervention posture -> screening risk, no score rewrite."""
    if carrier is None:
        return
    before = snap(carrier, CARRIER_KEYS)
    recompute_carrier_counters(carrier)
    recompute_posture(carrier)
    recompute_screening(carrier)
    finish(carrier, before)


def recount_carrier_id(carrier_id):
    recount_carrier(store.carriers.get(carrier_id))


def cascade_carrier(carrier, snapshot_ts=None, run_id=None, create=False,
                    strict=False):
    """Score rows -> counters -> intervention posture -> screening risk.

    Without an explicit snapshot the carrier's current scoring epoch is reused:
    a cascade triggered by a data change must not silently re-age the scores.
    """
    if carrier is None:
        return
    snapshot = snapshot_ts or epoch_for(carrier["id"]) or store.now_ts()
    before = snap(carrier, CARRIER_KEYS)
    recompute_basic_scores(carrier, snapshot, run_id=run_id, create=create,
                          strict=strict)
    recompute_carrier_counters(carrier)
    recompute_posture(carrier)
    recompute_screening(carrier)
    finish(carrier, before)


def cascade_carrier_id(carrier_id, **kwargs):
    carrier = store.carriers.get(carrier_id)
    if carrier is not None:
        cascade_carrier(carrier, **kwargs)


# --------------------------------------------------------------------------
# driver aggregates
# --------------------------------------------------------------------------

def court_factor(violation_id):
    best = None
    for adj in adjudications_of_violation(violation_id):
        if adj.get("superseded"):
            continue
        if adj.get("court_result_recorded_at") is None:
            continue
        if best is None:
            best = adj
            continue
        key_new = (adj["court_result_recorded_at"].dt, adj["created_at"].dt,
                   adj["_seq"])
        key_old = (best["court_result_recorded_at"].dt, best["created_at"].dt,
                   best["_seq"])
        if key_new > key_old:
            best = adj
    if best is None:
        return Decimal("1.0"), None
    status = best["court_status"]
    if status in ("DISMISSED", "NOT_GUILTY"):
        return Decimal("0.0"), best
    if status == "REDUCED":
        return Decimal("0.5"), best
    return Decimal("1.0"), best


def driver_violation_sets(driver_id):
    attributed = []
    included = []
    for v in store.violations.values():
        if v.get("driver_id") != driver_id:
            continue
        if v["status"] not in ACTIVE_STATUSES:
            continue
        report = store.reports.get(v["report_id"])
        if report is None or report["status"] != "SCORED":
            continue
        attributed.append(v)
        if (v.get("time_weight") or 0) > 0:
            included.append(v)
    return attributed, sorted_rows(included)


def recompute_driver(driver, adjudicated_only=False):
    if driver is None:
        return
    before = snap(driver, DRIVER_KEYS)
    attributed, included = driver_violation_sets(driver["id"])
    strict_total = dec(0)
    adjudicated_total = dec(0)
    for v in included:
        severity = dec(v.get("time_weighted_severity") or 0)
        strict_total += severity
        factor, _adj = court_factor(v["id"])
        adjudicated_total += severity * factor
    adjudicated_score = rhu(adjudicated_total, 2)
    if not adjudicated_only:
        driver["attributed_violation_count"] = len(attributed)
        driver["strict_attribution_score"] = float(rhu(strict_total, 2))
    driver["adjudicated_attribution_score"] = float(adjudicated_score)
    driver["coaching_required"] = adjudicated_score >= COACHING_TRIGGER
    count_open_coaching_driver(driver)
    finish(driver, before)


def recompute_driver_id(driver_id, adjudicated_only=False):
    if not driver_id:
        return
    recompute_driver(store.drivers.get(driver_id), adjudicated_only)


def recompute_drivers(driver_ids):
    wanted = set([d for d in driver_ids if d])
    for driver in all_drivers():
        if driver["id"] in wanted:
            recompute_driver(driver)


def factor_breakdown(driver_id):
    _attributed, included = driver_violation_sets(driver_id)
    breakdown = []
    for v in included:
        factor, adj = court_factor(v["id"])
        severity = dec(v.get("time_weighted_severity") or 0)
        breakdown.append({
            "violation_id": v["id"],
            "time_weighted_severity": float(severity),
            "severity_factor": float(factor),
            "adjudication_id": adj["id"] if adj else None,
            "weighted_contribution": num(severity * factor, 2),
        })
    return breakdown


# --------------------------------------------------------------------------
# coaching waivers
# --------------------------------------------------------------------------

def waive_assignment(assignment, reason, statuses=WAIVABLE_STATUSES):
    if assignment["status"] not in statuses:
        return False
    assignment["status"] = "WAIVED"
    assignment["waived_reason"] = reason
    touch(assignment)
    refresh_open_coaching(assignment["driver_id"], assignment.get("carrier_id"))
    return True


def waive_for_removed_violation(violation_id, reason="VIOLATION_REMOVED"):
    count = 0
    for assignment in assignments_of_violation(violation_id):
        if waive_assignment(assignment, reason):
            count += 1
    return count


def waive_for_attribution_change(violation_id, driver_id,
                                 reason="ATTRIBUTION_CLEARED"):
    count = 0
    for assignment in assignments_of_violation(violation_id):
        if driver_id is not None and assignment["driver_id"] != driver_id:
            continue
        if waive_assignment(assignment, reason):
            count += 1
    return count


def waive_for_driver_separation(driver):
    count = 0
    for assignment in assignments_of_driver(driver["id"]):
        if waive_assignment(assignment, "DRIVER_SEPARATED",
                            statuses=OPEN_COACHING_STATUSES):
            count += 1
    return count


def waive_stale_assignments(violation):
    """Waive the assignments one violation change has made pointless."""
    if violation["status"] == "REMOVED":
        return waive_for_removed_violation(violation["id"])
    count = 0
    for assignment in assignments_of_violation(violation["id"]):
        if assignment["driver_id"] != violation.get("driver_id"):
            if waive_assignment(assignment, "ATTRIBUTION_CLEARED"):
                count += 1
    return count


# --------------------------------------------------------------------------
# challenge coverage
# --------------------------------------------------------------------------

def covered_violations(challenge):
    """The violations a challenge's under_challenge flag covers."""
    if challenge["challenge_type"] in ("INCORRECT_VIOLATION_CODE",
                                       "VIOLATION_NOT_SUPPORTED"):
        target = challenge.get("target_violation_id")
        violation = store.violations.get(target) if target else None
        return [violation] if violation else []
    return violations_of_report(challenge["report_id"])


def set_under_challenge(challenge, flag):
    changed = []
    for violation in covered_violations(challenge):
        if violation.get("under_challenge") != flag:
            violation["under_challenge"] = flag
            touch(violation)
            changed.append(violation)
    return changed
