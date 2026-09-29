"""Refrigeration systems, leak-rate projection and retirement (PRD 3.1, 3.4, 3.7)."""
from decimal import Decimal

from flask import Blueprint, request

import constants
import db
import response
import util
import validate
from errors import ApiError, invalid
from middleware import (COMPLIANCE_MANAGER, endpoint, read_endpoint,
                        require_store_scope)
from services import guards, ledger, posture

bp = Blueprint("systems", __name__)

ZERO_1 = Decimal("0.0")


def derive_applicability(full_charge_lbs):
    if full_charge_lbs >= constants.REGULATED_CHARGE_FLOOR:
        return "REGULATED"
    return "EXEMPT"


def derive_required_certification(full_charge_lbs, refrigerant_type):
    if full_charge_lbs < constants.TYPE_I_CHARGE_CEILING:
        return "TYPE_I"
    if refrigerant_type["pressure_class"] == "LOW":
        return "TYPE_III"
    return "TYPE_II"


def rederive(system, refrigerant_type):
    system["applicability"] = derive_applicability(system["full_charge_lbs"])
    system["threshold_pct"] = constants.THRESHOLD_BY_CATEGORY[system["system_category"]]
    system["required_certification_type"] = derive_required_certification(
        system["full_charge_lbs"], refrigerant_type)


@bp.post("/systems")
@endpoint([COMPLIANCE_MANAGER])
def create_system():
    payload = validate.body()
    store_id = validate.req_id(payload, "store_id")
    refrigerant_type_id = validate.req_id(payload, "refrigerant_type_id")
    system_category = validate.req_enum(payload, "system_category",
                                        constants.SYSTEM_CATEGORIES)
    full_charge_lbs = validate.req_decimal(payload, "full_charge_lbs")
    if full_charge_lbs <= Decimal("0"):
        raise invalid("full_charge_lbs must be greater than 0")
    initial_charge_lbs = validate.req_decimal(payload, "initial_charge_lbs",
                                              minimum=Decimal("0"))
    if initial_charge_lbs > full_charge_lbs:
        raise invalid("initial_charge_lbs must not exceed full_charge_lbs")
    installed_on = validate.req_instant(payload, "installed_on")
    leak_rate_method = validate.opt_enum(payload, "leak_rate_method",
                                         constants.LEAK_RATE_METHODS,
                                         default="ROLLING_AVERAGE")
    store = db.require("stores", store_id)
    refrigerant_type = db.require("refrigerant_types", refrigerant_type_id)

    system = db.new_entity()
    system.update({
        "store_id": store_id,
        "refrigerant_type_id": refrigerant_type_id,
        "system_category": system_category,
        "full_charge_lbs": full_charge_lbs,
        "initial_charge_lbs": initial_charge_lbs,
        "current_charge_lbs": initial_charge_lbs,
        "installed_on": installed_on,
        "leak_rate_method": leak_rate_method,
        "leak_rate_pct": ZERO_1,
        "leak_rate_baseline_at": installed_on,
        "exceedance_count_12mo": 0,
        "operational_status": "ACTIVE",
        "compliance_state": "COMPLIANT",
        "retrofit_due_on": None,
        "retired_on": None,
        "retirement_reason_code": None,
        "replaced_by_system_id": None,
    })
    rederive(system, refrigerant_type)
    db.insert("systems", system)
    posture.recompute_store(store)
    return response.created(system)


@bp.get("/systems")
@read_endpoint
def list_systems():
    filters = {
        "store_id": request.args.get("store_id"),
        "refrigerant_type_id": request.args.get("refrigerant_type_id"),
        "replaced_by_system_id": request.args.get("replaced_by_system_id"),
        "applicability": request.args.get("applicability"),
        "operational_status": request.args.get("operational_status"),
        "compliance_state": request.args.get("compliance_state"),
    }
    return response.listing(db.values("systems"), filters)


@bp.get("/systems/<system_id>")
@read_endpoint
def get_system(system_id):
    system = db.require("systems", system_id)
    require_store_scope(system["store_id"])
    return response.ok(system)


@bp.get("/systems/<system_id>/leak-rate-projection")
@read_endpoint
def leak_rate_projection(system_id):
    system = db.require("systems", system_id)
    raw_method = request.args.get("method")
    if raw_method is not None and raw_method not in constants.LEAK_RATE_METHODS:
        raise invalid("method must be one of %s"
                      % ", ".join(constants.LEAK_RATE_METHODS))
    method = raw_method or system["leak_rate_method"]
    as_of = db.now()
    raw_as_of = request.args.get("as_of")
    if raw_as_of is not None:
        parsed = util.parse_instant(raw_as_of)
        if parsed is None:
            raise invalid("as_of must be an ISO 8601 UTC instant")
        as_of = parsed
    rate, added, window_start, window_end = ledger.leak_rate(
        system, method=method, as_of=as_of)
    would_trigger = (system["applicability"] == "REGULATED"
                     and rate >= system["threshold_pct"])
    return response.ok({
        "system_id": system["id"],
        "method": method,
        "leak_rate_pct": rate,
        "refrigerant_added_lbs_in_window": added,
        "window_start": window_start,
        "window_end": window_end,
        "threshold_pct": system["threshold_pct"],
        "would_trigger_leak_event": would_trigger,
    })


@bp.post("/systems/<system_id>/retirement")
@endpoint([COMPLIANCE_MANAGER])
def retire_system(system_id):
    payload = validate.body()
    reason_code = validate.req_str(payload, "retirement_reason_code")
    retrofit_plan_id = validate.opt_id(payload, "retrofit_plan_id")
    replacement_system_id = validate.opt_id(payload, "replacement_system_id")
    system = db.require("systems", system_id)
    plan = None
    if retrofit_plan_id is not None:
        plan = db.require("retrofit_plans", retrofit_plan_id)
    replacement = None
    if replacement_system_id is not None:
        replacement = db.require("systems", replacement_system_id)
    guards.require_active_system(system)
    if replacement is not None:
        if (replacement["operational_status"] != "ACTIVE"
                or replacement["store_id"] != system["store_id"]):
            raise ApiError("ERR_CROSS_STORE_RESOURCE")
    if system["current_charge_lbs"] != Decimal("0.0"):
        raise ApiError("ERR_SYSTEM_CHARGE_NOT_RECOVERED")

    open_events = [
        event for event in ledger.system_events(system["id"])
        if event["status"] not in constants.TERMINAL_LEAK_EVENT_STATUSES
    ]
    retire_plan_covers = (
        plan is not None
        and plan["plan_type"] == "RETIRE"
        and plan["status"] in ("APPROVED", "IN_PROGRESS")
    )
    if open_events and not retire_plan_covers:
        raise ApiError("ERR_OPEN_LEAK_EVENT_BLOCKS_RETIREMENT")

    clock = db.now()
    system["operational_status"] = "RETIRED"
    system["retired_on"] = clock
    system["retirement_reason_code"] = reason_code
    if replacement is not None:
        system["replaced_by_system_id"] = replacement["id"]
    for event in open_events:
        snap = db.snapshot(event)
        event["status"] = "VOIDED"
        event["closed_at"] = clock
        db.commit(event, snap)
    posture.system_cascade(system)
    return response.ok(system)
