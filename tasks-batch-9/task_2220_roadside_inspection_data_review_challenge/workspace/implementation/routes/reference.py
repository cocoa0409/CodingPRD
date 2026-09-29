"""Clock, scoring runs, carriers, drivers, codes, thresholds and score rows."""

from flask import Blueprint

from db import base_record, canon, get_or_404, parse_iso, serialize, store, touch
from errors import err
from middleware import ALL_ROLES, actor, scope, scope_rows
from response import created, ok
from routes.helpers import filtered, listing, rows_of
from services import cascade, runs
from services.calc import (CATEGORIES, SEGMENTS, dec, num,
                           quota_limit_for_segment, segment_for_units,
                           utilization_factor_for)
from validation import (body, get_bool, get_enum, get_int, get_num, get_str,
                        get_dt, pagination, q_bool, q_enum, q_str)

bp = Blueprint("reference", __name__)

FITNESS_STATUSES = ("UNRATED", "SATISFACTORY", "CONDITIONAL", "UNSATISFACTORY")
INTERVENTION_STATUSES = ("NONE", "WARNING_LETTER", "INVESTIGATION")
SELECTION_BANDS = ("PASS", "OPTIONAL", "INSPECT")
EMPLOYMENT_STATUSES = ("ACTIVE", "SUSPENDED", "TERMINATED")
ALERT_STATUSES = ("CLEAR", "MONITOR", "ALERT", "NOT_ENOUGH_DATA")


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    actor("FmcsaProgramAuditor")
    b = body()
    raw = get_str(b, "to_iso8601")
    try:
        moment = parse_iso(raw)
    except Exception:
        raise err("ERR_INVALID_REQUEST",
                  "'to_iso8601' must be an ISO 8601 datetime string.")
    previous = store.clock
    store.clock = moment
    return ok({"current_utc": canon(moment), "previous_utc": canon(previous)})


# ---------------------------------------------------------------------------
# scoring runs
# ---------------------------------------------------------------------------

@bp.post("/scoring-runs")
def create_scoring_run():
    actor("FmcsaProgramAuditor")
    b = body()
    note = get_str(b, "note", required=False)
    run = runs.create_run(note)
    return created(serialize(run))


@bp.get("/scoring-runs/<run_id>")
def get_scoring_run(run_id):
    actor(*ALL_ROLES)
    run = get_or_404(store.runs, run_id, "ERR_SCORING_RUN_NOT_FOUND")
    return ok(serialize(run))


# ---------------------------------------------------------------------------
# carriers
# ---------------------------------------------------------------------------

def new_carrier_record(dot_number, legal_name, average_power_units, annual_vmt):
    segment = segment_for_units(average_power_units)
    factor = utilization_factor_for(annual_vmt, average_power_units)
    rec = base_record()
    rec.update({
        "dot_number": dot_number,
        "legal_name": legal_name,
        "average_power_units": average_power_units,
        "annual_vmt": annual_vmt,
        "carrier_segment": segment,
        "utilization_factor": float(factor),
        "safety_fitness_status": "UNRATED",
        "fitness_determined_at": None,
        "fitness_determined_by_user_id": None,
        "intervention_status": "NONE",
        "open_alert_count": 0,
        "max_percentile": None,
        "oos_violation_count_24mo": 0,
        "scored_violation_count": 0,
        "unattributed_violation_count": 0,
        "iss_pre_credit_value": 0.0,
        "data_quality_credit_pct": 0.0,
        "iss_value": 0.0,
        "selection_band": "PASS",
        "challenge_quota_used": 0,
        "challenge_quota_limit": quota_limit_for_segment(segment),
        "accepted_challenge_count_24mo": 0,
        "resolved_challenge_count_24mo": 0,
        "open_coaching_count": 0,
    })
    return rec


@bp.post("/carriers")
def create_carrier():
    actor("FmcsaProgramAuditor")
    b = body()
    dot_number = get_str(b, "dot_number", max_len=8)
    if not dot_number.isdigit() or not 6 <= len(dot_number) <= 8:
        raise err("ERR_INVALID_REQUEST", "'dot_number' must be 6-8 digits.")
    legal_name = get_str(b, "legal_name", max_len=200)
    average_power_units = get_int(b, "average_power_units", minimum=0)
    annual_vmt = get_int(b, "annual_vmt", minimum=0)
    for existing in store.carriers.values():
        if existing["dot_number"] == dot_number:
            raise err("ERR_DUPLICATE_DOT_NUMBER",
                      "A carrier with this dot_number already exists.")
    carrier = new_carrier_record(dot_number, legal_name, average_power_units,
                                annual_vmt)
    store.carriers[carrier["id"]] = carrier
    return created(serialize(carrier))


@bp.get("/carriers")
def list_carriers():
    act = actor(*ALL_ROLES)
    limit, offset = pagination()
    rows = filtered(rows_of(store.carriers), [
        ("safety_fitness_status", q_enum("safety_fitness_status", FITNESS_STATUSES)),
        ("intervention_status", q_enum("intervention_status", INTERVENTION_STATUSES)),
        ("selection_band", q_enum("selection_band", SELECTION_BANDS)),
        ("carrier_segment", q_enum("carrier_segment", SEGMENTS)),
    ])
    rows = scope_rows(act, rows, "id")
    return listing(rows, limit, offset)


@bp.get("/carriers/<carrier_id>")
def get_carrier(carrier_id):
    act = actor(*ALL_ROLES)
    carrier = get_or_404(store.carriers, carrier_id, "ERR_CARRIER_NOT_FOUND")
    scope(act, carrier["id"])
    return ok(serialize(carrier))


@bp.post("/carriers/<carrier_id>/fitness-determination")
def fitness_determination(carrier_id):
    act = actor("FmcsaProgramAuditor")
    b = body()
    determination = get_enum(b, "determination", FITNESS_STATUSES)
    get_str(b, "basis_note")
    carrier = get_or_404(store.carriers, carrier_id, "ERR_CARRIER_NOT_FOUND")
    carrier["safety_fitness_status"] = determination
    carrier["fitness_determined_at"] = store.now_ts()
    carrier["fitness_determined_by_user_id"] = act.user_id
    touch(carrier)
    return ok(serialize(carrier))


@bp.get("/carriers/<carrier_id>/screening-risk")
def screening_risk(carrier_id):
    act = actor(*ALL_ROLES)
    carrier = get_or_404(store.carriers, carrier_id, "ERR_CARRIER_NOT_FOUND")
    scope(act, carrier["id"])
    contributions, excluded = cascade.category_contributions(carrier)
    return ok({
        "carrier_id": carrier["id"],
        "iss_pre_credit_value": carrier["iss_pre_credit_value"],
        "data_quality_credit_pct": carrier["data_quality_credit_pct"],
        "iss_value": carrier["iss_value"],
        "selection_band": carrier["selection_band"],
        "oos_adder": float(cascade.oos_adder_for(carrier)),
        "oos_violation_count_24mo": carrier["oos_violation_count_24mo"],
        "category_contributions": contributions,
        "not_enough_data_categories": excluded,
    })


# ---------------------------------------------------------------------------
# drivers
# ---------------------------------------------------------------------------

@bp.post("/drivers")
def create_driver():
    act = actor("CarrierSafetyManager")
    b = body()
    carrier_id = get_str(b, "carrier_id")
    cdl_number = get_str(b, "cdl_number", max_len=60)
    full_name = get_str(b, "full_name", max_len=200)
    employment_status = get_enum(b, "employment_status", EMPLOYMENT_STATUSES,
                                 required=False, default="ACTIVE")
    carrier = get_or_404(store.carriers, carrier_id, "ERR_CARRIER_NOT_FOUND")
    scope(act, carrier["id"])
    for existing in store.drivers.values():
        if (existing["carrier_id"] == carrier_id
                and existing["cdl_number"] == cdl_number):
            raise err("ERR_DUPLICATE_CDL",
                      "This carrier already has a driver with that cdl_number.")
    driver = base_record()
    driver.update({
        "carrier_id": carrier_id,
        "cdl_number": cdl_number,
        "full_name": full_name,
        "employment_status": employment_status,
        "attributed_violation_count": 0,
        "strict_attribution_score": 0.0,
        "adjudicated_attribution_score": 0.0,
        "coaching_required": False,
        "open_coaching_count": 0,
    })
    store.drivers[driver["id"]] = driver
    return created(serialize(driver))


@bp.get("/drivers")
def list_drivers():
    act = actor(*ALL_ROLES)
    limit, offset = pagination()
    rows = filtered(rows_of(store.drivers), [
        ("carrier_id", q_str("carrier_id")),
        ("employment_status", q_enum("employment_status", EMPLOYMENT_STATUSES)),
        ("coaching_required", q_bool("coaching_required")),
    ])
    rows = scope_rows(act, rows, "carrier_id")
    return listing(rows, limit, offset)


@bp.get("/drivers/<driver_id>")
def get_driver(driver_id):
    act = actor(*ALL_ROLES)
    driver = get_or_404(store.drivers, driver_id, "ERR_DRIVER_NOT_FOUND")
    scope(act, driver["carrier_id"])
    return ok(serialize(driver))


@bp.patch("/drivers/<driver_id>")
def update_driver(driver_id):
    act = actor("CarrierSafetyManager")
    b = body()
    full_name = get_str(b, "full_name", required=False, max_len=200)
    employment_status = get_enum(b, "employment_status", EMPLOYMENT_STATUSES,
                                required=False)
    driver = get_or_404(store.drivers, driver_id, "ERR_DRIVER_NOT_FOUND")
    scope(act, driver["carrier_id"])
    if full_name is not None:
        driver["full_name"] = full_name
    if employment_status is not None:
        driver["employment_status"] = employment_status
    touch(driver)
    if employment_status == "TERMINATED":
        cascade.waive_for_driver_separation(driver)
    return ok(serialize(driver))


@bp.get("/drivers/<driver_id>/attribution-summary")
def attribution_summary(driver_id):
    act = actor(*ALL_ROLES)
    driver = get_or_404(store.drivers, driver_id, "ERR_DRIVER_NOT_FOUND")
    scope(act, driver["carrier_id"])
    return ok({
        "driver_id": driver["id"],
        "attributed_violation_count": driver["attributed_violation_count"],
        "strict_attribution_score": driver["strict_attribution_score"],
        "adjudicated_attribution_score": driver["adjudicated_attribution_score"],
        "coaching_required": driver["coaching_required"],
        "factor_breakdown": cascade.factor_breakdown(driver["id"]),
    })


# ---------------------------------------------------------------------------
# violation codes
# ---------------------------------------------------------------------------

@bp.post("/violation-codes")
def create_violation_code():
    actor("FmcsaProgramAuditor")
    b = body()
    code = get_str(b, "code", max_len=40)
    description = get_str(b, "description", max_len=500)
    basic_category = get_enum(b, "basic_category", CATEGORIES)
    severity_weight = get_int(b, "severity_weight", minimum=1, maximum=10)
    oos_add_on = get_int(b, "oos_add_on", required=False, default=2, minimum=0,
                         maximum=5)
    driver_attributable = get_bool(b, "driver_attributable", required=False,
                                   default=True)
    for existing in store.violation_codes.values():
        if existing["code"] == code:
            raise err("ERR_DUPLICATE_VIOLATION_CODE",
                      "This violation code already exists.")
    record = base_record()
    record.update({
        "code": code,
        "description": description,
        "basic_category": basic_category,
        "severity_weight": severity_weight,
        "oos_add_on": oos_add_on,
        "driver_attributable": driver_attributable,
    })
    store.violation_codes[record["id"]] = record
    return created(serialize(record))


@bp.get("/violation-codes")
def list_violation_codes():
    actor(*ALL_ROLES)
    limit, offset = pagination()
    rows = filtered(rows_of(store.violation_codes), [
        ("basic_category", q_enum("basic_category", CATEGORIES)),
        ("driver_attributable", q_bool("driver_attributable")),
    ])
    return listing(rows, limit, offset)


@bp.get("/violation-codes/<code_id>")
def get_violation_code(code_id):
    actor(*ALL_ROLES)
    record = get_or_404(store.violation_codes, code_id,
                        "ERR_VIOLATION_CODE_NOT_FOUND")
    return ok(serialize(record))


@bp.patch("/violation-codes/<code_id>")
def update_violation_code(code_id):
    actor("FmcsaProgramAuditor")
    b = body()
    severity_weight = get_int(b, "severity_weight", required=False, minimum=1,
                              maximum=10)
    oos_add_on = get_int(b, "oos_add_on", required=False, minimum=0, maximum=5)
    description = get_str(b, "description", required=False, max_len=500)
    driver_attributable = get_bool(b, "driver_attributable", required=False)
    record = get_or_404(store.violation_codes, code_id,
                        "ERR_VIOLATION_CODE_NOT_FOUND")
    if severity_weight is not None:
        record["severity_weight"] = severity_weight
    if oos_add_on is not None:
        record["oos_add_on"] = oos_add_on
    if description is not None:
        record["description"] = description
    if driver_attributable is not None:
        record["driver_attributable"] = driver_attributable
    touch(record)
    return ok(serialize(record))


# ---------------------------------------------------------------------------
# intervention thresholds
# ---------------------------------------------------------------------------

@bp.post("/intervention-thresholds")
def create_threshold():
    actor("FmcsaProgramAuditor")
    b = body()
    basic_category = get_enum(b, "basic_category", CATEGORIES)
    carrier_segment = get_enum(b, "carrier_segment", SEGMENTS)
    effective_from = get_dt(b, "effective_from")
    p50 = get_num(b, "measure_at_p50", exclusive_min=0)
    p65 = get_num(b, "measure_at_p65", exclusive_min=0)
    p80 = get_num(b, "measure_at_p80", exclusive_min=0)
    intervention = get_num(b, "intervention_percentile", required=False,
                           default=65.0, exclusive_min=0, maximum=100)
    monitor = get_num(b, "monitor_percentile", required=False, default=50.0,
                      exclusive_min=0, maximum=100)
    investigation = get_num(b, "investigation_percentile", required=False,
                            default=85.0, exclusive_min=0, maximum=100)
    if not p50 < p65 < p80:
        raise err("ERR_INVALID_REQUEST",
                  "measure_at_p50 < measure_at_p65 < measure_at_p80 is required.")
    if not monitor < intervention:
        raise err("ERR_INVALID_REQUEST",
                  "'monitor_percentile' must be below 'intervention_percentile'.")
    if not intervention <= investigation:
        raise err("ERR_INVALID_REQUEST",
                  "'investigation_percentile' must be at least "
                  "'intervention_percentile'.")
    record = base_record()
    record.update({
        "basic_category": basic_category,
        "carrier_segment": carrier_segment,
        "effective_from": effective_from,
        "measure_at_p50": p50,
        "measure_at_p65": p65,
        "measure_at_p80": p80,
        "intervention_percentile": intervention,
        "monitor_percentile": monitor,
        "investigation_percentile": investigation,
    })
    store.thresholds[record["id"]] = record
    return created(serialize(record))


@bp.get("/intervention-thresholds")
def list_thresholds():
    actor(*ALL_ROLES)
    limit, offset = pagination()
    rows = filtered(rows_of(store.thresholds), [
        ("basic_category", q_enum("basic_category", CATEGORIES)),
        ("carrier_segment", q_enum("carrier_segment", SEGMENTS)),
    ])
    return listing(rows, limit, offset)


# ---------------------------------------------------------------------------
# basic scores
# ---------------------------------------------------------------------------

@bp.get("/basic-scores")
def list_basic_scores():
    act = actor(*ALL_ROLES)
    limit, offset = pagination()
    rows = filtered(rows_of(store.basic_scores), [
        ("carrier_id", q_str("carrier_id")),
        ("basic_category", q_enum("basic_category", CATEGORIES)),
        ("alert_status", q_enum("alert_status", ALERT_STATUSES)),
        ("scoring_run_id", q_str("scoring_run_id")),
        ("threshold_id", q_str("threshold_id")),
    ])
    rows = scope_rows(act, rows, "carrier_id")
    return listing(rows, limit, offset)


@bp.get("/basic-scores/<score_id>")
def get_basic_score(score_id):
    act = actor(*ALL_ROLES)
    row = get_or_404(store.basic_scores, score_id, "ERR_BASIC_SCORE_NOT_FOUND")
    scope(act, row["carrier_id"])
    return ok(serialize(row))
