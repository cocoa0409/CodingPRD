"""Domain services: roll-ups, cascades, the editing pass and the weighting pass."""
import math
from datetime import timedelta
from decimal import Decimal

from calculations import (CREDIT_FACTOR, DESIGN_DENOMINATOR_STATUSES,
                          boost_reservation_cents, fill_grade, redistribute)
from store import created_key, db
from util import D, date_key, format_iso, parse_iso, round_half_up, rhu_int

ACTIVE_INTERVAL_STATES = ("RAW", "EDITED", "ASCRIBED")


# --------------------------------------------------------------- roll-ups
def compute_posture(open_audit_count, quota_cell_count, filled_cell_count,
                    under_target_cell_count):
    if open_audit_count >= 1:
        return "FROZEN"
    if quota_cell_count >= 1 and filled_cell_count == quota_cell_count:
        return "CLOSED"
    if under_target_cell_count == 0:
        return "RESTRICTED"
    return "OPEN"


def recompute_cell(cell):
    """Re-count in-tab, re-grade the fill, and arm/disarm the incentive boost."""
    households = db.where("households", quota_cell_id=cell["id"])
    intab = len([h for h in households if h["status"] == "ACTIVE"])
    rate, status = fill_grade(intab, cell["target_households"])
    changed = False
    if cell["intab_count"] != intab:
        cell["intab_count"] = intab
        changed = True
    if D(cell["fill_rate"]) != rate:
        cell["fill_rate"] = rate
        changed = True
    if cell["quota_status"] != status:
        cell["quota_status"] = status
        changed = True
    if status == "UNDER_TARGET" and not cell["incentive_boost_active"]:
        cell["incentive_boost_active"] = True
        cell["effective_incentive_multiplier"] = D("1.25")
        changed = True
    elif status != "UNDER_TARGET" and cell["incentive_boost_active"]:
        cell["incentive_boost_active"] = False
        cell["effective_incentive_multiplier"] = D("1.00")
        changed = True
    if changed:
        db.touch(cell)
    return changed


def recompute_market(market):
    """Recompute every market roll-up, then re-evaluate the posture."""
    cells = db.where("quota_cells", market_id=market["id"])
    households = db.where("households", market_id=market["id"])
    audits = db.where("accreditation_audits", market_id=market["id"])
    values = {
        "quota_cell_count": len(cells),
        "filled_cell_count": len([c for c in cells
                                  if c["quota_status"] == "FILLED"]),
        "under_target_cell_count": len([c for c in cells
                                        if c["quota_status"] == "UNDER_TARGET"]),
        "open_audit_count": len([a for a in audits if a["state"] == "OPEN"]),
        "incentive_budget_committed_cents": sum(
            h["incentive_accrued_cents"] for h in households),
        "incentive_budget_reserved_cents": sum(
            boost_reservation_cents(c["base_incentive_cents"],
                                    c["target_households"])
            for c in cells if c["incentive_boost_active"]),
    }
    changed = False
    for key, value in values.items():
        if market[key] != value:
            market[key] = value
            changed = True
    posture = compute_posture(values["open_audit_count"],
                              values["quota_cell_count"],
                              values["filled_cell_count"],
                              values["under_target_cell_count"])
    if market["recruitment_posture"] != posture:
        market["recruitment_posture"] = posture
        market["posture_changed_at"] = db.now_iso()
        changed = True
    if changed:
        db.touch(market)
    return changed


def refresh_household_rollups(household):
    cell = db.get("quota_cells", household["quota_cell_id"])
    if cell is not None:
        recompute_cell(cell)
    market = db.get("markets", household["market_id"])
    if market is not None:
        recompute_market(market)


def pending_reserved_cents(market, extra_reserved=0, extra_committed=0):
    return (market["incentive_budget_committed_cents"] + extra_committed
            + market["incentive_budget_reserved_cents"] + extra_reserved)


# --------------------------------------------------------------- compliance
def refresh_rolling_compliance(household):
    """30-day rolling window ending at the clock, reported days only."""
    upper = db.clock
    lower = upper - timedelta(days=30)
    minutes_by_day = {}
    for row in db.where("tuning_intervals", household_id=household["id"]):
        if row["state"] not in ACTIVE_INTERVAL_STATES:
            continue
        start = parse_iso(row["start_iso"])
        if start is None or start < lower or start >= upper:
            continue
        key = date_key(start)
        minutes_by_day[key] = minutes_by_day.get(key, 0) + row["tuning_minutes"]
    evaluated = len(minutes_by_day)
    compliant = len([m for m in minutes_by_day.values() if m >= 30])
    if evaluated == 0:
        rate = D("0.0000")
    else:
        rate = round_half_up(D(compliant) / D(evaluated), 4)
    if D(household["compliance_rate_rolling_30"]) != rate:
        household["compliance_rate_rolling_30"] = rate
        db.touch(household)
    return rate


def run_scoped_compliance(household_id, run):
    """Every calendar day of the run window counts, credited minutes only."""
    evaluated = int(math.ceil(run["window_minutes"] / 1440.0))
    minutes_by_day = {}
    for row in db.where("tuning_intervals", household_id=household_id,
                        processing_run_id=run["id"]):
        if row["state"] not in ("EDITED", "ASCRIBED"):
            continue
        start = parse_iso(row["start_iso"])
        if start is None:
            continue
        key = date_key(start)
        minutes_by_day[key] = minutes_by_day.get(key, 0) + row["usable_minutes"]
    compliant = len([m for m in minutes_by_day.values() if m >= 30])
    if evaluated <= 0:
        return D("0.0000")
    return round_half_up(D(compliant) / D(evaluated), 4)


# --------------------------------------------------------------- fault cascade
def fault_cascade(meter):
    """Links 2-5 of the meter fault cascade; each link is genuinely conditional."""
    if meter["meter_type"] != "TV_TUNER":
        return False
    household = db.get("households", meter["household_id"])
    if household is None:
        return False
    healthy = [m for m in db.where("meters", household_id=household["id"])
               if m["meter_type"] == "TV_TUNER"
               and m["install_status"] == "INSTALLED"
               and m["health_status"] == "HEALTHY"]
    if healthy:
        return False
    if household["status"] != "ACTIVE":
        return False
    household["status"] = "FAULT_HOLD"
    db.touch(household)
    refresh_household_rollups(household)
    return True


def repair_cascade(meter):
    """The exact compensating counterpart of the fault cascade."""
    if meter["meter_type"] != "TV_TUNER" or meter["install_status"] != "INSTALLED":
        return False
    household = db.get("households", meter["household_id"])
    if household is None:
        return False
    if household["status"] != "FAULT_HOLD":
        return False
    if household["enumeration_verdict"] != "COMPLIANT":
        return False
    household["status"] = "ACTIVE"
    db.touch(household)
    refresh_household_rollups(household)
    return True


def detect_faults(run, rule_set):
    """Coverage scan across every INSTALLED meter of the run's market."""
    threshold = rule_set["fault_missing_minutes_threshold"]
    suspect_floor = rhu_int(D(threshold) / D(2))
    window_start = run["window_start_iso"]
    window_end = run["window_end_iso"]
    households = {h["id"]: h for h in db.where("households",
                                               market_id=run["market_id"])}
    meters = [m for m in db.all("meters")
              if m["install_status"] == "INSTALLED" and m["household_id"] in households]
    meters.sort(key=created_key)
    scanned_households = []
    faulted = 0
    for meter in meters:
        covered = 0
        for row in db.where("tuning_intervals", meter_id=meter["id"]):
            if row["state"] not in ACTIVE_INTERVAL_STATES:
                continue
            if row["start_iso"] >= window_start and row["end_iso"] <= window_end:
                covered += row["tuning_minutes"]
        missing = max(0, run["window_minutes"] - covered)
        if meter["missing_minutes_last_scan"] != missing:
            meter["missing_minutes_last_scan"] = missing
            db.touch(meter)
        if missing >= threshold and meter["health_status"] != "FAULTED":
            meter["health_status"] = "FAULTED"
            meter["last_fault_code"] = "MISSING_INTERVALS"
            meter["fault_count"] = meter["fault_count"] + 1
            db.touch(meter)
            faulted += 1
            fault_cascade(meter)
        elif (threshold > missing >= suspect_floor
              and meter["health_status"] == "HEALTHY"):
            meter["health_status"] = "SUSPECT"
            db.touch(meter)
        if meter["household_id"] not in scanned_households:
            scanned_households.append(meter["household_id"])
    for household_id in scanned_households:
        household = db.get("households", household_id)
        if household is not None:
            refresh_rolling_compliance(household)
    return faulted


# --------------------------------------------------------------- run artefacts
def release_run_artifacts(run):
    """Return claimed intervals to the pool and drop derived rows."""
    for row in list(db.where("tuning_intervals", processing_run_id=run["id"])):
        if row["ascribed"]:
            db.delete("tuning_intervals", row)
            continue
        row["state"] = "RAW"
        row["processing_run_id"] = None
        row["usable_minutes"] = 0
        row["invalidation_reason"] = None
        db.touch(row)
    for row in list(db.where("household_weights", processing_run_id=run["id"])):
        db.delete("household_weights", row)


def delete_weight_rows(run):
    for row in list(db.where("household_weights", processing_run_id=run["id"])):
        db.delete("household_weights", row)


def hold_deliverables_of_runs(run_ids, states=("SCHEDULED", "REQUESTED",
                                               "IN_PROGRESS",
                                               "REVISION_REQUESTED")):
    """Cascade hold with the system-reserved UPSTREAM_RUN_REPIN reason."""
    rows = [d for d in db.all("client_deliverables")
            if d["processing_run_id"] in run_ids and d["state"] in states]
    rows.sort(key=created_key)
    for row in rows:
        row["held_from_state"] = row["state"]
        row["state"] = "HELD"
        row["hold_reason"] = "UPSTREAM_RUN_REPIN"
        db.touch(row)
        client = db.get("clients", row["client_id"])
        if client is not None:
            client["held_deliverable_count"] = client["held_deliverable_count"] + 1
            client["delivery_sla_credit_cents"] = (
                client["delivery_sla_credit_cents"]
                + rhu_int(D(client["tier_base_fee_cents"]) * D("0.05")))
            db.touch(client)
    return rows


def repin_runs(runs, reason, clear_weights=False):
    """Force runs to PENDING_REPIN, then hold their non-terminal deliverables."""
    runs = sorted(runs, key=created_key)
    for run in runs:
        was_weighted = run["state"] in ("EDITED", "WEIGHTED")
        run["state"] = "PENDING_REPIN"
        run["repin_required_reason"] = reason
        if clear_weights and was_weighted:
            delete_weight_rows(run)
            run["total_weight_mass"] = D("0.0000")
            run["projected_average_audience"] = None
        db.touch(run)
    if runs:
        hold_deliverables_of_runs([run["id"] for run in runs])
    return runs


# --------------------------------------------------------------- editing pass
def _claim_key(row):
    return (row["household_id"], row["meter_id"], row["start_iso"],
            row["created_at"], row["_seq"])


def edit_pass(run, rule_set):
    """Seven ordered steps; later steps read what earlier steps wrote."""
    market_households = {h["id"] for h in db.where("households",
                                                   market_id=run["market_id"])}
    # 1. Claim.
    claimed = [r for r in db.all("tuning_intervals")
               if r["state"] == "RAW"
               and r["household_id"] in market_households
               and r["start_iso"] >= run["window_start_iso"]
               and r["end_iso"] <= run["window_end_iso"]]
    claimed.sort(key=_claim_key)
    for row in claimed:
        row["processing_run_id"] = run["id"]
        db.touch(row)
    # 2. Invalid tuning.  3. Credit.
    for row in claimed:
        if row["tuning_minutes"] > rule_set["invalid_tuning_max_minutes"]:
            row["state"] = "INVALIDATED"
            row["invalidation_reason"] = "OVER_MAX_TUNING"
            row["usable_minutes"] = 0
        else:
            row["state"] = "EDITED"
            row["invalidation_reason"] = None
            row["usable_minutes"] = rhu_int(
                D(row["tuning_minutes"]) * CREDIT_FACTOR[row["source_methodology"]])
    # 4. Meter fault.
    for row in claimed:
        meter = db.get("meters", row["meter_id"])
        if meter is not None and meter["health_status"] == "FAULTED":
            row["state"] = "INVALIDATED"
            row["invalidation_reason"] = "METER_FAULTED"
            row["usable_minutes"] = 0
    # 5. Ascription.
    meter_order = []
    for row in claimed:
        if row["meter_id"] not in meter_order:
            meter_order.append(row["meter_id"])
    for meter_id in meter_order:
        meter = db.get("meters", meter_id)
        if meter is None or meter["meter_type"] == "PORTABLE_OOH":
            continue
        records = [r for r in claimed
                   if r["meter_id"] == meter_id and r["state"] == "EDITED"]
        records.sort(key=lambda r: (r["start_iso"], r["created_at"], r["_seq"]))
        for index in range(len(records) - 1):
            earlier = records[index]
            later = records[index + 1]
            end_dt = parse_iso(earlier["end_iso"])
            start_dt = parse_iso(later["start_iso"])
            if end_dt is None or start_dt is None:
                continue
            gap = int(math.floor((start_dt - end_dt).total_seconds() / 60.0))
            if gap < 1 or gap > rule_set["missing_interval_ascription_minutes"]:
                continue
            factor = CREDIT_FACTOR[earlier["source_methodology"]]
            db.insert("tuning_intervals", {
                "meter_id": earlier["meter_id"],
                "household_id": earlier["household_id"],
                "processing_run_id": run["id"],
                "source_methodology": earlier["source_methodology"],
                "start_iso": earlier["end_iso"],
                "end_iso": later["start_iso"],
                "station_code": earlier["station_code"],
                "tuning_minutes": gap,
                "usable_minutes": rhu_int(D(gap) * factor),
                "state": "ASCRIBED",
                "invalidation_reason": None,
                "ascribed": True,
            })
    # 6. Outlier households.
    household_order = []
    for row in claimed:
        if row["household_id"] not in household_order:
            household_order.append(row["household_id"])
    outlier_count = 0
    cap = rule_set["outlier_household_minutes_cap"]
    for household_id in household_order:
        rows = db.where("tuning_intervals", household_id=household_id,
                        processing_run_id=run["id"])
        total = sum(r["usable_minutes"] for r in rows
                    if r["state"] in ("EDITED", "ASCRIBED"))
        if total <= cap:
            continue
        outlier_count += 1
        for row in list(rows):
            if row["ascribed"]:
                db.delete("tuning_intervals", row)
            else:
                row["state"] = "INVALIDATED"
                row["invalidation_reason"] = "OUTLIER_HOUSEHOLD"
                row["usable_minutes"] = 0
                db.touch(row)
    # 7. Tally.
    remaining = db.where("tuning_intervals", processing_run_id=run["id"])
    contributing = []
    for row in remaining:
        if row["state"] in ("EDITED", "ASCRIBED") and row["usable_minutes"] > 0:
            household = db.get("households", row["household_id"])
            if (household is not None and household["status"] == "ACTIVE"
                    and household["id"] not in contributing):
                contributing.append(household["id"])
    run["invalidated_interval_count"] = len(
        [r for r in remaining if r["state"] == "INVALIDATED"])
    run["ascribed_interval_count"] = len(
        [r for r in remaining if r["state"] == "ASCRIBED"])
    run["outlier_household_count"] = outlier_count
    run["contributing_household_count"] = len(contributing)
    if run["outlier_household_count"] > 0:
        run["limitation_disclosures"].append("OUTLIER_HOUSEHOLDS_EXCLUDED")
    if run["ascribed_interval_count"] > 0:
        run["limitation_disclosures"].append("ASCRIBED_INTERVALS_PRESENT")
    run["state"] = "EDITED"
    db.touch(run)
    return run


# --------------------------------------------------------------- weighting pass
def data_households(run):
    """Households holding >=1 EDITED/ASCRIBED record of this run with minutes."""
    ordered_ids = []
    for row in db.where("tuning_intervals", processing_run_id=run["id"]):
        if row["state"] in ("EDITED", "ASCRIBED") and row["usable_minutes"] > 0:
            if row["household_id"] not in ordered_ids:
                ordered_ids.append(row["household_id"])
    households = [db.get("households", hid) for hid in ordered_ids]
    households = [h for h in households if h is not None]
    households.sort(key=created_key)
    return households


def household_usable_minutes(run, household_id):
    total = 0
    for row in db.where("tuning_intervals", processing_run_id=run["id"],
                        household_id=household_id):
        if row["state"] in ("EDITED", "ASCRIBED"):
            total += row["usable_minutes"]
    return total


def cell_denominator(cell_id, variant, contributor_ids):
    rows = db.where("households", quota_cell_id=cell_id)
    if variant == "DESIGN":
        return len([r for r in rows
                    if r["status"] in DESIGN_DENOMINATOR_STATUSES])
    return len([r for r in rows if r["id"] in contributor_ids])


def weight_pass(run, rule_set, universe, variant):
    delete_weight_rows(run)
    households = data_households(run)
    contributor_ids = set(h["id"] for h in households)
    populations = {}
    for entry in universe["cell_populations"]:
        populations[entry["quota_cell_id"]] = entry
    denominators = {}
    for household in households:
        cell_id = household["quota_cell_id"]
        if cell_id not in denominators:
            denominators[cell_id] = cell_denominator(cell_id, variant,
                                                     contributor_ids)
    excluded = [cell_id for cell_id, value in denominators.items()
                if value == 0 or cell_id not in populations]
    rows = []
    for household in households:
        cell_id = household["quota_cell_id"]
        if cell_id in excluded:
            continue
        usable = household_usable_minutes(run, household["id"])
        population = populations[cell_id]["population_households"]
        base = round_half_up(D(population) / D(denominators[cell_id]), 4)
        row = db.insert("household_weights", {
            "processing_run_id": run["id"],
            "household_id": household["id"],
            "weight_variant": variant,
            "base_weight": base,
            "adjusted_weight": base,
            "usable_minutes": usable,
            "contribution": D("0.00"),
            "run_compliance_rate": run_scoped_compliance(household["id"], run),
            "capped": False,
        })
        rows.append(row)
    mass = redistribute(rows, rule_set["outlier_weight_ratio_cap"])
    raw_total = Decimal(0)
    for row in rows:
        contribution = round_half_up(
            D(row["adjusted_weight"]) * D(row["usable_minutes"])
            / D(run["window_minutes"]), 2)
        row["contribution"] = contribution
        raw_total += contribution
    run["weight_variant"] = variant
    run["total_weight_mass"] = mass
    run["projected_average_audience"] = rhu_int(raw_total)
    run["excluded_cell_count"] = len(excluded)
    run["limitation_disclosures"] = [
        code for code in run["limitation_disclosures"]
        if code not in ("CELL_NO_CONTRIBUTORS", "WEIGHT_CAP_APPLIED")]
    if len(excluded) > 0:
        run["limitation_disclosures"].append("CELL_NO_CONTRIBUTORS")
    if any(row["capped"] for row in rows):
        run["limitation_disclosures"].append("WEIGHT_CAP_APPLIED")
    run["state"] = "WEIGHTED"
    db.touch(run)
    return rows
