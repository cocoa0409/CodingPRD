"""Refrigeration monitoring: cases, readings, breach runs and excursions (PRD 3.3)."""

from flask import Blueprint

import calc
import cascade
import common
import derive
import envelope
import serial
import validate as v
from common import CASE_TYPES, EXCURSION_STATES, MONITORING_STATES, PRODUCT_CLASSES
from db import db, new_row
from errors import ApiError
from security import (ALL_ROLES, BMS_GATEWAY, ENERGY_MANAGER, MAINTENANCE_TECH,
                      NON_GATEWAY_ROLES, PLATFORM_ADMIN, roles, require_store_scope)

bp = Blueprint("cases", __name__)


def open_excursion_of(case):
    """The single non-closed excursion of a case, if any."""
    for excursion in derive.case_excursions(case["id"]):
        if excursion["state"] != "CLOSED":
            return excursion
    return None


@bp.route("/stores/<store_id>/refrigeration-cases", methods=["POST"])
@roles(PLATFORM_ADMIN, ENERGY_MANAGER)
def register_case(store_id):
    body = v.body()
    case_code = v.get_str(body, "case_code", min_len=1)
    case_type = v.get_enum(body, "case_type", CASE_TYPES)
    product_class = v.get_enum(body, "product_class", PRODUCT_CLASSES)
    alarm_high_f = v.get_num(body, "alarm_high_f", 1)
    alarm_low_f = v.get_num(body, "alarm_low_f", 1)
    product_value_usd = v.get_num(body, "product_value_usd", 2, ge=0)
    if not alarm_high_f > alarm_low_f:
        v.bad("'alarm_high_f' must be strictly above 'alarm_low_f'")
    store = common.get_store(store_id)
    common.require_bms_commissioned(store)
    for existing in derive.store_cases(store_id):
        if existing["case_code"] == case_code:
            v.bad("case code '%s' already exists in this store" % case_code)
    case = new_row(db.cases, {
        "store_id": store_id,
        "case_code": case_code,
        "case_type": case_type,
        "product_class": product_class,
        "alarm_high_f": alarm_high_f,
        "alarm_low_f": alarm_low_f,
        "product_value_usd": product_value_usd,
        "monitoring_state": "ARMED",
        "consecutive_breach_count": 0,
        "last_reading_temp_f": None,
        "last_reading_iso": None,
        "_run": [],
    })
    return envelope.created(serial.case(case))


@bp.route("/refrigeration-cases/<case_id>", methods=["GET"])
@roles(*ALL_ROLES)
def get_case(case_id):
    case = common.get_case(case_id)
    return envelope.ok(serial.case(case))


@bp.route("/refrigeration-cases/<case_id>/excursions", methods=["GET"])
@roles(*NON_GATEWAY_ROLES)
def list_case_excursions(case_id):
    limit, offset = v.query_pagination()
    state = v.query_enum("state", EXCURSION_STATES)
    common.get_case(case_id)
    items = derive.case_excursions(case_id)
    items = common.apply_eq(items, "state", state)
    return common.list_response(items, serial.excursion, limit, offset)


# ------------------------------------------------------------------ readings ---

def _apply_ladder(excursion, store):
    """Exposure ladder plus the escalation cascade; returns the cascade counters."""
    minutes = calc.exposure_minutes(excursion["first_breach_iso"],
                                    excursion["last_breach_iso"])
    excursion["exposure_minutes"] = minutes
    state, mandate = calc.exposure_ladder(minutes)
    if state == "OPEN":
        # An acknowledged excursion reverts to OPEN when the case re-breaches.
        if excursion["state"] in ("OPEN", "ACKNOWLEDGED"):
            excursion["state"] = "OPEN"
    else:
        excursion["state"] = state
    excursion["mandatory_disposition"] = mandate
    cascade.touch(excursion)
    return cascade.recompute_posture(store)


@bp.route("/refrigeration-cases/<case_id>/readings", methods=["POST"])
@roles(BMS_GATEWAY)
def ingest_reading(case_id):
    body = v.body()
    temp_f = v.get_num(body, "temp_f", 1)
    reading_iso = v.get_dt(body, "reading_iso")
    case = common.get_case(case_id)
    require_store_scope(case["store_id"])
    store = derive.store_of_case(case)

    case["last_reading_temp_f"] = temp_f
    case["last_reading_iso"] = reading_iso
    cascade.touch(case)

    counters = {"dr_events_opted_out": 0, "overrides_revoked": 0}
    if case["monitoring_state"] != "BYPASSED":
        excursion = open_excursion_of(case)
        if calc.breaches(case, temp_f):
            deviation = calc.breach_deviation(case, temp_f)
            case["consecutive_breach_count"] = case["consecutive_breach_count"] + 1
            case.setdefault("_run", []).append(
                {"iso": reading_iso, "temp": temp_f, "dev": deviation})
            if excursion is not None:
                excursion["last_breach_iso"] = reading_iso
                if (deviation > excursion["_peak_dev"]
                        or (deviation == excursion["_peak_dev"]
                            and reading_iso < excursion["_peak_iso"])):
                    excursion["peak_temp_f"] = temp_f
                    excursion["_peak_dev"] = deviation
                    excursion["_peak_iso"] = reading_iso
                result = _apply_ladder(excursion, store)
                counters["dr_events_opted_out"] = result["dr_events_opted_out"]
                counters["overrides_revoked"] = result["overrides_revoked"]
            elif case["consecutive_breach_count"] >= calc.GRACE_READINGS:
                run = case["_run"]
                best = run[0]
                for entry in run[1:]:
                    if (entry["dev"] > best["dev"]
                            or (entry["dev"] == best["dev"]
                                and entry["iso"] < best["iso"])):
                        best = entry
                excursion = new_row(db.excursions, {
                    "case_id": case["id"],
                    "first_breach_iso": run[0]["iso"],
                    "last_breach_iso": reading_iso,
                    "peak_temp_f": best["temp"],
                    "exposure_minutes": 0,
                    "state": "OPEN",
                    "product_value_usd": case["product_value_usd"],
                    "mandatory_disposition": "NONE",
                    "acknowledged_by_user_id": None,
                    "disposition": None,
                    "corrective_action_note": None,
                    "documented_by_user_id": None,
                    "documented_at_iso": None,
                    "closed_at_iso": None,
                    "_peak_dev": best["dev"],
                    "_peak_iso": best["iso"],
                })
                case["monitoring_state"] = "ALARM"
                if store is not None:
                    cascade.touch(store)
                result = _apply_ladder(excursion, store)
                counters["dr_events_opted_out"] = result["dr_events_opted_out"]
                counters["overrides_revoked"] = result["overrides_revoked"]
        else:
            case["consecutive_breach_count"] = 0
            case["_run"] = []

    excursion = open_excursion_of(case)
    return envelope.ok({
        "case_id": case["id"],
        "monitoring_state": case["monitoring_state"],
        "consecutive_breach_count": case["consecutive_breach_count"],
        "last_reading_temp_f": serial.q(case["last_reading_temp_f"], 1),
        "last_reading_iso": serial.fmt_iso(case["last_reading_iso"]),
        "excursion_id": excursion["id"] if excursion else None,
        "excursion_state": excursion["state"] if excursion else None,
        "exposure_minutes": excursion["exposure_minutes"] if excursion else None,
        "peak_temp_f": serial.q(excursion["peak_temp_f"], 1) if excursion else None,
        "mandatory_disposition": (excursion["mandatory_disposition"]
                                 if excursion else None),
        "store_energy_posture": store["energy_posture"] if store else None,
        "dr_events_opted_out": counters["dr_events_opted_out"],
        "overrides_revoked": counters["overrides_revoked"],
    })


# ---------------------------------------------------------- monitoring state ---

@bp.route("/refrigeration-cases/<case_id>/monitoring-state", methods=["POST"])
@roles(MAINTENANCE_TECH)
def set_monitoring_state(case_id):
    body = v.body()
    target_state = v.get_enum(body, "target_state", MONITORING_STATES)
    case = common.get_case(case_id)
    current = case["monitoring_state"]
    if target_state == current:
        raise ApiError("ERR_CASE_STATE_INVALID")
    if target_state == "BYPASSED" and current != "ARMED":
        raise ApiError("ERR_CASE_STATE_INVALID")
    if target_state == "ARMED" and current != "BYPASSED":
        raise ApiError("ERR_CASE_STATE_INVALID")
    if target_state == "ALARM":
        raise ApiError("ERR_CASE_STATE_INVALID")
    case["monitoring_state"] = target_state
    case["consecutive_breach_count"] = 0
    case["_run"] = []
    cascade.touch(case)
    return envelope.ok(serial.case(case))
