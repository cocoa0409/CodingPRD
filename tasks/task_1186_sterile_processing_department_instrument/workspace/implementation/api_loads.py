"""Sterilization loads: scheduling, orchestration, release, recall, BI attach."""
from datetime import timedelta

from flask import Blueprint

import domain
import store
import views
from common import (
    ANY, ApiError, auth, created, get_body, logical_now, ok, ok_list,
    opt_string, paginate, pagination, query_str, req_datetime, req_fk,
    req_string,
)

bp = Blueprint("loads", __name__)


@bp.post("/spd/sterilization-loads")
def create_load():
    actor = auth(("SpdTechnician",))
    body = get_body()
    sterilizer = req_fk(body, "sterilizer_id", store.STERILIZERS, "Sterilizer")
    planned_start_at = req_datetime(body, "planned_start_at")

    # p8 temporal gate: planned half-open window overlap on this sterilizer
    new_start = planned_start_at
    new_end = planned_start_at + timedelta(minutes=sterilizer["cycle_minutes"])
    for other in store.STERILIZATION_LOADS.values():
        if other["sterilizer_id"] != sterilizer["id"]:
            continue
        if other["status"] not in ("LOADING", "RUNNING"):
            continue
        other_start = other["planned_start_at"]
        other_end = other_start + timedelta(minutes=sterilizer["cycle_minutes"])
        # half-open [start, end): adjacency (shared endpoint) is allowed
        if new_start < other_end and other_start < new_end:
            raise ApiError("ERR_STERILIZER_WINDOW_CONFLICT", 409,
                           "Planned window overlaps another LOADING/RUNNING "
                           "load on this sterilizer.")

    record = store.new_record()
    record.update({
        "sterilizer_id": sterilizer["id"],
        "operator_id": actor.user_id,
        "planned_start_at": planned_start_at,
        "started_at": None,
        "completed_at": None,
        "released_at": None,
        "status": "LOADING",
        "total_chargeback_cents": None,
        "recall_reason": None,
        "recalled_at": None,
        "member_tray_ids": [],
    })
    store.STERILIZATION_LOADS[record["id"]] = record
    return created(views.load_view(record))


@bp.get("/spd/sterilization-loads")
def list_loads():
    auth(ANY)
    limit, offset = pagination()
    sterilizer_id = query_str("sterilizer_id")
    operator_id = query_str("operator_id")
    status = query_str("status")
    rows = [r for r in store.STERILIZATION_LOADS.values()
            if (sterilizer_id is None or r["sterilizer_id"] == sterilizer_id)
            and (operator_id is None or r["operator_id"] == operator_id)
            and (status is None or r["status"] == status)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.load_view(r) for r in page], limit, offset, total)


@bp.get("/spd/sterilization-loads/<load_id>")
def get_load(load_id):
    auth(ANY)
    record = store.fetch(store.STERILIZATION_LOADS, load_id)
    return ok(views.load_view(record))


@bp.post("/spd/sterilization-loads/<load_id>/trays")
def add_tray_to_load(load_id):
    auth(("SpdTechnician",))
    load = store.fetch(store.STERILIZATION_LOADS, load_id)
    body = get_body()
    tray = req_fk(body, "tray_id", store.TRAYS, "Tray")

    # p6 state gates: the load's own gate first, then the linked tray
    if load["status"] != "LOADING":
        raise ApiError("ERR_LOAD_NOT_LOADING", 409,
                       "add-tray requires load LOADING.")
    if tray["status"] != "ASSEMBLED":
        raise ApiError("ERR_TRAY_NOT_ASSEMBLED", 409,
                       "adding to a load requires tray ASSEMBLED.")
    # p9 constraint gate: chamber capacity
    sterilizer = store.STERILIZERS.get(load["sterilizer_id"])
    capacity = sterilizer["chamber_capacity"] if sterilizer else 0
    if domain.tray_count(load) >= capacity:
        raise ApiError("ERR_LOAD_CAPACITY_EXCEEDED", 409,
                       "The load already holds chamber_capacity trays.")

    tray["status"] = "IN_LOAD"
    tray["current_load_id"] = load["id"]
    store.touch(tray)
    load["member_tray_ids"].append(tray["id"])
    store.touch(load)
    return ok(views.load_view(load))


@bp.post("/spd/sterilization-loads/<load_id>/start")
def start_load(load_id):
    actor = auth(("SpdTechnician",))
    load = store.fetch(store.STERILIZATION_LOADS, load_id)
    sterilizer = store.STERILIZERS.get(load["sterilizer_id"])

    # p6 state gates: own first, then the linked sterilizer
    if load["status"] != "LOADING":
        raise ApiError("ERR_LOAD_NOT_LOADING", 409,
                       "start requires load LOADING.")
    if sterilizer is not None and sterilizer["status"] != "IDLE":
        raise ApiError("ERR_STERILIZER_NOT_IDLE", 409,
                       "load start requires sterilizer IDLE.")
    # p8 temporal gate
    if logical_now() < load["planned_start_at"]:
        raise ApiError("ERR_LOAD_PLANNED_START_NOT_REACHED", 409,
                       "The logical clock has not reached planned_start_at.")

    # p9 constraint gates in declared order
    technician = store.TECHNICIANS.get(actor.user_id)
    if technician is None:
        raise ApiError("ERR_NOT_FOUND", 404,
                       "The acting technician does not exist.")
    domain.sweep_technician(technician)
    if technician["status"] == "SUSPENDED":
        raise ApiError("ERR_TECHNICIAN_SUSPENDED", 403,
                       "Load start by a SUSPENDED technician.")
    if technician["status"] == "CERTIFICATION_EXPIRED":
        raise ApiError("ERR_CERTIFICATION_EXPIRED", 403,
                       "Load start by a CERTIFICATION_EXPIRED technician.")
    if sterilizer is not None and \
            sterilizer["method"] not in technician["certified_methods"]:
        raise ApiError("ERR_CERTIFICATION_METHOD_MISMATCH", 403,
                       "Sterilizer method not in certified_methods.")
    if sterilizer is not None and technician["certification_level"] < \
            sterilizer["required_certification_level"]:
        raise ApiError("ERR_CERTIFICATION_LEVEL_INSUFFICIENT", 403,
                       "certification_level below required_certification_level.")
    if sterilizer is not None and sterilizer["method"] == "LOW_TEMP_H2O2":
        rolling, _lifetime = domain.competency_scores(technician["id"])
        if rolling < domain.H2O2_COMPETENCY_GATE:
            raise ApiError("ERR_COMPETENCY_BELOW_THRESHOLD", 403,
                           "LOW_TEMP_H2O2 load start requires "
                           "competency_score >= 70.")
    if domain.tray_count(load) < 1:
        raise ApiError("ERR_LOAD_EMPTY", 409,
                       "start requires at least one tray in the load.")

    load["status"] = "RUNNING"
    load["started_at"] = logical_now()
    store.touch(load)
    if sterilizer is not None:
        sterilizer["status"] = "RUNNING"
        store.touch(sterilizer)
    return ok(views.load_view(load))


@bp.post("/spd/sterilization-loads/<load_id>/complete")
def complete_load(load_id):
    auth(("SpdTechnician",))
    load = store.fetch(store.STERILIZATION_LOADS, load_id)
    if load["status"] != "RUNNING":
        raise ApiError("ERR_LOAD_NOT_RUNNING", 409,
                       "complete requires load RUNNING.")

    now = logical_now()
    load["status"] = "COMPLETED"
    load["completed_at"] = now
    store.touch(load)
    sterilizer = store.STERILIZERS.get(load["sterilizer_id"])
    if sterilizer is not None:
        sterilizer["status"] = "IDLE"
        store.touch(sterilizer)

    # exactly one biological indicator is auto-created at completion
    bi = store.new_record()
    bi.update({
        "load_id": load["id"],
        "lot_number": "AUTO-LOT",
        "status": "INCUBATING",
        "result": "PENDING",
        "due_at": now + timedelta(hours=domain.BI_INCUBATION_HOURS),
        "recorded_at": None,
    })
    store.BIOLOGICAL_INDICATORS[bi["id"]] = bi
    return ok(views.load_view(load))


@bp.post("/spd/sterilization-loads/<load_id>/fail-cycle")
def fail_cycle(load_id):
    auth(("SpdTechnician",))
    load = store.fetch(store.STERILIZATION_LOADS, load_id)
    if load["status"] != "RUNNING":
        raise ApiError("ERR_LOAD_NOT_RUNNING", 409,
                       "fail-cycle requires load RUNNING.")

    load["status"] = "FAILED_CYCLE"
    store.touch(load)
    sterilizer = store.STERILIZERS.get(load["sterilizer_id"])
    if sterilizer is not None:
        sterilizer["status"] = "IDLE"
        store.touch(sterilizer)
    domain.release_member_trays(load, "ASSEMBLED")
    # 8-point competency demerit attributed to the operator
    domain.add_competency_event(load["operator_id"], domain.CYCLE_FAIL_PTS)
    return ok(views.load_view(load))


@bp.post("/spd/sterilization-loads/<load_id>/abort")
def abort_load(load_id):
    auth(("SpdTechnician",))
    load = store.fetch(store.STERILIZATION_LOADS, load_id)
    if load["status"] != "LOADING":
        raise ApiError("ERR_LOAD_NOT_LOADING", 409,
                       "abort requires load LOADING.")

    load["status"] = "ABORTED"
    store.touch(load)
    domain.release_member_trays(load, "ASSEMBLED")
    return ok(views.load_view(load))


@bp.post("/spd/sterilization-loads/<load_id>/release")
def release_load(load_id):
    actor = auth(("SpdSupervisor",))
    load = store.fetch(store.STERILIZATION_LOADS, load_id)

    if load["status"] != "COMPLETED":
        raise ApiError("ERR_LOAD_NOT_RELEASABLE", 409,
                       "release requires load COMPLETED.")
    # p7 patient-safety gates: segregation of duties BEFORE the BI check
    if actor.user_id == load["operator_id"]:
        raise ApiError("ERR_RELEASE_OPERATOR_SEGREGATION", 403,
                       "The operator of a load may never release it.")
    bis = [b for b in store.BIOLOGICAL_INDICATORS.values()
           if b["load_id"] == load["id"]]
    if (len(bis) == 0 or any(
            not (b["status"] == "RESULT_RECORDED" and b["result"] == "NEGATIVE")
            for b in bis)):
        raise ApiError("ERR_BI_NOT_PASSED", 409,
                       "Release requires every BI recorded NEGATIVE.")

    now = logical_now()
    load["status"] = "RELEASED"
    load["released_at"] = now
    store.touch(load)

    sterilizer = store.STERILIZERS.get(load["sterilizer_id"])
    released_tray_ids = []
    for tray_id in list(load["member_tray_ids"]):
        tray = store.TRAYS.get(tray_id)
        if tray is None or tray["status"] != "IN_LOAD":
            continue
        template = store.TRAY_TEMPLATES.get(tray["template_id"])
        packaging = template["packaging_type"] if template else "WRAPPED"
        shelf_hours = domain.SHELF_HOURS[packaging]
        tray["status"] = "STERILE"
        tray["sterility_expires_at"] = now + timedelta(hours=shelf_hours)
        tray["cycles_completed"] = tray["cycles_completed"] + 1
        tray["current_load_id"] = None
        store.touch(tray)
        released_tray_ids.append(tray_id)
        for instrument in store.INSTRUMENTS.values():
            if instrument["assigned_tray_id"] == tray["id"]:
                instrument["usage_cycles"] = instrument["usage_cycles"] + 1
                store.touch(instrument)

    load["total_chargeback_cents"] = domain.chargeback_cents(
        sterilizer, len(released_tray_ids)) if sterilizer is not None else 0
    store.touch(load)
    return ok(views.load_view(load))


@bp.post("/spd/sterilization-loads/<load_id>/recall")
def recall_load_endpoint(load_id):
    auth(("SpdSupervisor", "QualityAuditor"))
    load = store.fetch(store.STERILIZATION_LOADS, load_id)
    body = get_body()
    reason = req_string(body, "reason")
    if load["status"] != "RELEASED":
        raise ApiError("ERR_LOAD_NOT_RECALLABLE", 409,
                       "recall requires load RELEASED.")
    domain.recall_load(load, reason)
    return ok(views.load_view(load))


@bp.post("/spd/sterilization-loads/<load_id>/biological-indicators")
def add_biological_indicator(load_id):
    auth(("QualityAuditor",))
    load = store.fetch(store.STERILIZATION_LOADS, load_id)
    body = get_body()
    lot_number = opt_string(body, "lot_number", default="AUTO-LOT")
    if load["status"] not in ("COMPLETED", "RELEASED"):
        raise ApiError("ERR_BI_LOAD_STATE_INVALID", 409,
                       "Manual BI creation requires the load COMPLETED or "
                       "RELEASED.")

    now = logical_now()
    bi = store.new_record()
    bi.update({
        "load_id": load["id"],
        "lot_number": lot_number,
        "status": "INCUBATING",
        "result": "PENDING",
        "due_at": now + timedelta(hours=domain.BI_INCUBATION_HOURS),
        "recorded_at": None,
    })
    store.BIOLOGICAL_INDICATORS[bi["id"]] = bi
    return created(views.bi_view(bi))
