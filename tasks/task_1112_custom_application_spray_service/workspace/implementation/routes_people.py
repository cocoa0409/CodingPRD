"""People & machines: applicators, equipment, calibration records, weather observations."""

from decimal import Decimal
from flask import Blueprint, request

from store import store
from util import (require_roles, get_body, req_str, req_nonempty_str, req_pos_int,
                  req_num, req_nonneg_num, req_pos_num, req_dt, req_bool, req_present,
                  ok, paginate, round_2dp, dec, now, validation_error, not_found,
                  invalid_state, conflict)
from domain import (new_mutable, new_evidence, serialize, touch, CATEGORIES,
                    CALIBRATION_VALID_PERIOD, PASS_ERROR_PCT_MAX,
                    revert_scheduled_work_orders, latest_observation, observation_fresh,
                    envelope_passes)

bp = Blueprint("people", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Applicators
# ---------------------------------------------------------------------------

@bp.post("/applicators")
def create_applicator():
    require_roles("CoopAdmin")
    body = get_body()
    display_name = req_nonempty_str(body, "display_name")
    license_no = req_nonempty_str(body, "license_no")
    expires = req_dt(body, "license_expires_on")
    cats = req_present(body, "license_categories")
    if not isinstance(cats, list):
        raise validation_error("license_categories must be an array")
    for c in cats:
        if not isinstance(c, str) or c not in CATEGORIES:
            raise validation_error("license_categories entries must be one of %s"
                                   % sorted(CATEGORIES))
    a = new_mutable({
        "display_name": display_name,
        "license_no": license_no,
        "license_expires_on": expires,
        "license_categories": list(cats),
        "status": "ACTIVE",
        "penalty_points_lifetime": 0,
        "rolling_score_365": 0,
    })
    store.applicators[a["id"]] = a
    return ok(serialize("applicator", a), 201)


@bp.get("/applicators/<aid>")
def get_applicator(aid):
    require_roles("Dispatcher", "ComplianceOfficer", "CoopAdmin", "Applicator")
    a = store.applicators.get(aid)
    if a is None:
        raise not_found("applicator not found")
    return ok(serialize("applicator", a))


@bp.post("/applicators/<aid>/reinstate")
def reinstate_applicator(aid):
    require_roles("ComplianceOfficer")
    a = store.applicators.get(aid)
    if a is None:
        raise not_found("applicator not found")
    if a["status"] != "SUSPENDED":
        raise invalid_state("only a SUSPENDED applicator can be reinstated")
    for c in store.drift_complaints.values():
        if c["applicator_id"] == aid and c["status"] == "INVESTIGATING":
            raise conflict("ERR_INVESTIGATION_PENDING",
                           "a drift complaint against this applicator is still INVESTIGATING")
    a["status"] = "ACTIVE"
    touch(a)
    return ok(serialize("applicator", a))


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------

@bp.post("/equipment")
def create_equipment():
    require_roles("CoopAdmin")
    body = get_body()
    unit_label = req_nonempty_str(body, "unit_label")
    tank = req_pos_int(body, "tank_capacity_gal")
    e = new_mutable({
        "unit_label": unit_label,
        "tank_capacity_gal": tank,
        "status": "AVAILABLE",
        "calibration_valid_until": None,
    })
    store.equipment[e["id"]] = e
    return ok(serialize("equipment", e), 201)


@bp.get("/equipment/<eid>")
def get_equipment(eid):
    require_roles("Dispatcher", "Applicator", "CoopAdmin", "ComplianceOfficer")
    e = store.equipment.get(eid)
    if e is None:
        raise not_found("equipment not found")
    return ok(serialize("equipment", e))


# ---------------------------------------------------------------------------
# Calibration records (evidence; verdict computed; PASS extends validity,
# FAIL marks CALIBRATION_DUE and reverts its SCHEDULED work orders to DRAFT)
# ---------------------------------------------------------------------------

@bp.post("/calibration-records")
def create_calibration_record():
    uid, role = require_roles("Applicator", "CoopAdmin")
    body = get_body()
    equipment_id = req_str(body, "equipment_id")
    target = req_pos_num(body, "target_gpa")
    measured = req_nonneg_num(body, "measured_gpa")
    if role == "CoopAdmin":
        applicator_id = req_str(body, "applicator_id")
    else:
        applicator_id = uid
    eq = store.equipment.get(equipment_id)
    if eq is None:
        raise not_found("equipment not found")
    if applicator_id not in store.applicators:
        raise not_found("applicator not found")
    performed_at = now()
    error_pct = round_2dp(abs(dec(measured) - dec(target)) / dec(target) * Decimal(100))
    verdict = "PASS" if error_pct <= PASS_ERROR_PCT_MAX else "FAIL"
    rec = new_evidence({
        "equipment_id": equipment_id,
        "applicator_id": applicator_id,
        "performed_at": performed_at,
        "target_gpa": target,
        "measured_gpa": measured,
        "error_pct": error_pct,
        "verdict": verdict,
    })
    store.calibration_records[rec["id"]] = rec
    if verdict == "PASS":
        # PASS extends validity 180 days and (re)marks AVAILABLE, even from CALIBRATION_DUE
        eq["calibration_valid_until"] = performed_at + CALIBRATION_VALID_PERIOD
        eq["status"] = "AVAILABLE"
        touch(eq)
    else:
        # FAIL never changes calibration_valid_until; drops AVAILABLE units to
        # CALIBRATION_DUE and reverts their scheduled work
        if eq["status"] != "CALIBRATION_DUE":
            eq["status"] = "CALIBRATION_DUE"
            touch(eq)
        revert_scheduled_work_orders(equipment_id=eq["id"])
    return ok(serialize("calibration_record", rec), 201)


@bp.get("/calibration-records/<rid>")
def get_calibration_record(rid):
    require_roles("Dispatcher", "Applicator", "CoopAdmin", "ComplianceOfficer")
    r = store.calibration_records.get(rid)
    if r is None:
        raise not_found("calibration record not found")
    return ok(serialize("calibration_record", r))


@bp.get("/calibration-records")
def list_calibration_records():
    require_roles("Dispatcher", "Applicator", "CoopAdmin", "ComplianceOfficer")
    items = sorted(store.calibration_records.values(),
                   key=lambda r: (r["created_at"], r["_seq"]))
    eq_id = request.args.get("equipment_id")
    if eq_id is not None:
        items = [r for r in items if r["equipment_id"] == eq_id]
    ap_id = request.args.get("applicator_id")
    if ap_id is not None:
        items = [r for r in items if r["applicator_id"] == ap_id]
    return paginate([serialize("calibration_record", r) for r in items])


# ---------------------------------------------------------------------------
# Weather observations (evidence; may push IN_PROGRESS work orders to WEATHER_HOLD)
# ---------------------------------------------------------------------------

@bp.post("/weather-observations")
def create_weather_observation():
    uid, _role = require_roles("Applicator", "Dispatcher")
    body = get_body()
    observed_at = req_dt(body, "observed_at")
    wind = req_nonneg_num(body, "wind_mph")
    temp = req_num(body, "temp_f")
    inversion = req_bool(body, "inversion_present")
    obs = new_evidence({
        "observed_at": observed_at,
        "wind_mph": wind,
        "temp_f": temp,
        "inversion_present": inversion,
        "recorded_by_user_id": uid,
    })
    store.weather_observations[obs["id"]] = obs
    # Cascade: any IN_PROGRESS work order whose mix envelope the freshest
    # observation now violates moves to WEATHER_HOLD (assignment retained).
    latest = latest_observation()
    if latest is not None:
        fresh = observation_fresh(latest)
        for w in store.work_orders.values():
            if w["status"] != "IN_PROGRESS":
                continue
            rx = store.prescriptions[w["prescription_id"]]
            if (not fresh) or (not envelope_passes(rx, latest)):
                w["status"] = "WEATHER_HOLD"
                touch(w)
    return ok(serialize("weather_observation", obs), 201)


@bp.get("/weather-observations")
def list_weather_observations():
    require_roles("Applicator", "Dispatcher", "CoopAdmin", "ComplianceOfficer")
    # documented exception to created_at-ascending: newest observed_at first
    items = sorted(store.weather_observations.values(),
                   key=lambda o: (o["observed_at"], o["created_at"], o["_seq"]),
                   reverse=True)
    return paginate([serialize("weather_observation", o) for o in items])
