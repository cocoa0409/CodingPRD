"""Going on and off pump, and extracorporeal membrane oxygenation runs."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import constants as C
import serialize
import svc
import valid as V
from auth import ROLE_CHIEF, ROLE_CONTRACT_ADMIN, ROLE_PERFUSIONIST, endpoint
from envelope import ok, ok_list
from errors import ApiError
from store import db, insert, ordered, stamp_new, touch

D = Decimal
bp = Blueprint("runs", __name__)

RUN_READ = (ROLE_CONTRACT_ADMIN, ROLE_CHIEF, ROLE_PERFUSIONIST)


def _covering_slot(case):
    sid = case.get("_covering_slot_id")
    return db.call_rotation_slots.get(sid) if sid else None


@bp.post("/bypass-cases/<cid>/start-bypass")
@endpoint([ROLE_PERFUSIONIST])
def start_bypass(actor, cid):
    case = svc.get_case(cid)
    if actor.user_id != case.get("assigned_perfusionist_id"):
        raise ApiError("ERR_NOT_ASSIGNED_PERFUSIONIST")
    if case["bypass_status"] != "SETUP_VERIFIED":
        raise ApiError("ERR_CASE_NOT_SETUP_VERIFIED")
    if case["readiness_flag"] != "NONE":
        raise ApiError("ERR_DEVICE_FALLBACK_REQUIRED")

    primary = db.perfusion_devices.get(case.get("primary_device_id"))
    backup = db.perfusion_devices.get(case.get("backup_device_id"))
    if primary is None or primary["status"] != "RESERVED":
        raise ApiError("ERR_DEVICE_NOT_AVAILABLE")
    if backup is None or backup["status"] not in ("RESERVED", "AVAILABLE"):
        raise ApiError("ERR_DEVICE_NOT_AVAILABLE")

    now = db.now()
    case["bypass_status"] = "ON_BYPASS"
    case["bypass_started_at"] = now
    touch(case)

    primary["status"] = "IN_USE"
    touch(primary)

    slot = _covering_slot(case)
    if (slot is not None and slot["status"] == "SCHEDULED"
            and slot["window_start"] <= now < slot["window_end"]):
        slot["status"] = "ACTIVE"
        touch(slot)

    perf = db.perfusionists.get(case["assigned_perfusionist_id"])
    if perf is not None:
        svc.set_readiness(perf, "ADMISSION")

    return ok(serialize.bypass_case(case))


@bp.post("/bypass-cases/<cid>/end-bypass")
@endpoint([ROLE_PERFUSIONIST])
def end_bypass(actor, cid):
    body = V.payload()
    V.require(body, "pump_time_minutes", "cross_clamp_minutes", "lowest_hematocrit_pct")
    pump = V.vint(body, "pump_time_minutes", minimum=0, maximum=2880, required=True)
    clamp = V.vint(body, "cross_clamp_minutes", minimum=0, required=True)
    hct = V.vnum(body, "lowest_hematocrit_pct", minimum=5, maximum=45, required=True)
    adverse = V.vint(body, "adverse_event_count", minimum=0, default=0)

    case = svc.get_case(cid)
    if actor.user_id != case.get("assigned_perfusionist_id"):
        raise ApiError("ERR_NOT_ASSIGNED_PERFUSIONIST")
    if case["bypass_status"] != "ON_BYPASS":
        raise ApiError("ERR_CASE_NOT_ON_BYPASS")
    if clamp > pump:
        raise ApiError("ERR_CROSS_CLAMP_EXCEEDS_PUMP_TIME")

    primary = db.perfusion_devices.get(case.get("primary_device_id"))
    backup = db.perfusion_devices.get(case.get("backup_device_id"))

    case["bypass_status"] = "OFF_BYPASS"
    case["bypass_ended_at"] = db.now()
    case["pump_time_minutes"] = pump
    case["cross_clamp_minutes"] = clamp
    case["lowest_hematocrit_pct"] = hct
    case["adverse_event_count"] = adverse
    touch(case)

    if primary is not None:
        primary["runtime_hours_since_service"] = (
            D(primary["runtime_hours_since_service"]) + D(pump) / D(60))
        clean = (primary["alarm_count_since_service"] == 0
                 and D(primary["runtime_hours_since_service"]) < D(primary["service_interval_hours"]))
        if clean:
            if calc.device_open_reservation_count(primary["id"]) == 0:
                primary["status"] = "AVAILABLE"
            else:
                primary["status"] = "RESERVED"
            touch(primary)
        else:
            primary["status"] = "NEEDS_SERVICE"
            touch(primary)
            svc.append_event_log(primary["id"], "SELF_TEST_FAIL", actor.user_id,
                                 "service interval reached at end of case", 0)

    if backup is not None and backup["status"] == "RESERVED":
        backup["status"] = "AVAILABLE"
        touch(backup)

    slot = _covering_slot(case)
    if slot is not None and slot["status"] == "ACTIVE":
        still_on_pump = any(
            other["id"] != case["id"]
            and other.get("assigned_perfusionist_id") == slot["perfusionist_id"]
            and other["bypass_status"] == "ON_BYPASS"
            for other in db.bypass_cases.values()
        )
        if not still_on_pump:
            slot["status"] = "COMPLETED"
            touch(slot)

    return ok(serialize.bypass_case(case))


# --------------------------------------------------------------- ECMO

@bp.post("/bypass-cases/<cid>/ecmo-runs")
@endpoint([ROLE_PERFUSIONIST, ROLE_CHIEF])
def open_run(actor, cid):
    body = V.payload()
    V.require(body, "mode")
    mode = V.venum(body, "mode", C.ECMO_MODES, required=True)

    case = svc.get_case(cid)
    if actor.user_id != case.get("assigned_perfusionist_id"):
        raise ApiError("ERR_NOT_ASSIGNED_PERFUSIONIST")
    if case["bypass_status"] != "ON_BYPASS":
        raise ApiError("ERR_CASE_NOT_ON_BYPASS")
    perf = db.perfusionists.get(case["assigned_perfusionist_id"])
    if perf is None or not perf["ecmo_privileged"]:
        raise ApiError("ERR_ECMO_PRIVILEGE_REQUIRED")
    if svc.perfusionist_has_breached_run(perf["id"]):
        raise ApiError("ERR_ECMO_STAFFING_BREACH")

    row = {
        "case_id": case["id"],
        "primary_perfusionist_id": perf["id"],
        "relief_slot_id": None,
        "mode": mode,
        "cannulated_at": db.now(),
        "last_handoff_at": None,
        "decannulated_at": None,
        "status": "RUNNING",
        "billable_hours": 0,
        "ecmo_fee_cents": 0,
    }
    stamp_new(row)
    insert("ecmo_runs", row)
    return ok(serialize.ecmo_run(row), 201)


@bp.get("/ecmo-runs/<rid>")
@endpoint(RUN_READ)
def read_run(actor, rid):
    return ok(serialize.ecmo_run(svc.get_run(rid)))


@bp.get("/ecmo-runs")
@endpoint(RUN_READ)
def list_runs(actor):
    limit, offset = V.pagination()
    rows = ordered("ecmo_runs")
    for key in ("case_id", "primary_perfusionist_id", "relief_slot_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return ok_list([serialize.ecmo_run(r) for r in V.page(rows, limit, offset)],
                   limit, offset, len(rows))


@bp.post("/ecmo-runs/<rid>/handoffs")
@endpoint([ROLE_CHIEF])
def handoff_run(actor, rid):
    body = V.payload()
    V.require(body, "relief_slot_id")
    slot_id = V.vstr(body, "relief_slot_id", required=True)

    run = svc.get_run(rid)
    slot = svc.get_slot(slot_id)
    if run["status"] != "RELIEF_PENDING":
        raise ApiError("ERR_ECMO_RUN_STATE_INVALID")

    holder = db.perfusionists.get(slot["perfusionist_id"])
    if holder is None or holder["employment_status"] != "ACTIVE":
        raise ApiError("ERR_PERFUSIONIST_NOT_ACTIVE")
    if not holder["ecmo_privileged"]:
        raise ApiError("ERR_ECMO_PRIVILEGE_REQUIRED")
    if svc.perfusionist_has_breached_run(holder["id"], exclude_run_id=run["id"]):
        raise ApiError("ERR_ECMO_STAFFING_BREACH")

    case = db.bypass_cases.get(run["case_id"])
    now = db.now()
    if (slot["slot_type"] != "ECMO_RELIEF"
            or slot["consumed"]
            or case is None
            or slot["contract_id"] != case["contract_id"]
            or not (slot["window_start"] <= now < slot["window_end"])
            or slot["perfusionist_id"] == run["primary_perfusionist_id"]):
        raise ApiError("ERR_RELIEF_SLOT_INVALID")

    run["status"] = "RUNNING"
    run["primary_perfusionist_id"] = slot["perfusionist_id"]
    run["relief_slot_id"] = slot["id"]
    run["last_handoff_at"] = now
    touch(run)

    slot["status"] = "ACTIVE"
    slot["consumed"] = True
    touch(slot)

    return ok(serialize.ecmo_run(run))


@bp.post("/ecmo-runs/<rid>/decannulate")
@endpoint([ROLE_PERFUSIONIST])
def decannulate_run(actor, rid):
    run = svc.get_run(rid)
    if actor.user_id != run.get("primary_perfusionist_id"):
        raise ApiError("ERR_NOT_ASSIGNED_PERFUSIONIST")
    if run["status"] not in ("RUNNING", "RELIEF_PENDING"):
        raise ApiError("ERR_ECMO_RUN_STATE_INVALID")

    case = db.bypass_cases.get(run["case_id"])
    contract = db.hospital_contracts.get(case["contract_id"]) if case else None

    run["decannulated_at"] = db.now()
    run["status"] = "DECANNULATED"
    if contract is not None:
        hours, fee = calc.ecmo_run_billing(contract, run)
        run["billable_hours"] = hours
        run["ecmo_fee_cents"] = fee
    touch(run)

    slot = db.call_rotation_slots.get(run.get("relief_slot_id"))
    if slot is not None and slot["status"] == "ACTIVE":
        slot["status"] = "COMPLETED"
        touch(slot)

    perf = db.perfusionists.get(run["primary_perfusionist_id"])
    if perf is not None:
        svc.set_readiness(perf, "ADMISSION")

    return ok(serialize.ecmo_run(run))
