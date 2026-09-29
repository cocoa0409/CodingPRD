"""Soil sampling, chain of custody, laboratory reporting and retraction."""

from datetime import timedelta

from flask import Blueprint

import calculations as calc
from db import assign, commit, create, db
from errors import ApiError
from middleware import (authenticate, body, filter_arg, int_filter_arg, opt_id,
                        pagination, req_enum, req_int, req_num, req_str,
                        require_sample_owner, resolve)
from response import entity_response, list_response
from services import project as svc

bp = Blueprint("soil_samples", __name__)

READ_ROLES = ("ProjectCoordinator", "FieldTechnician", "LabAnalyst",
              "LicensedSiteProfessional", "ComplianceOfficer")


@bp.post("/soil-samples")
def create_sample():
    user_id, role = authenticate(("FieldTechnician",))
    payload = body()
    project_id = opt_id(payload, "tank_project_id")
    project = resolve("tank_projects", project_id) if project_id else None
    work_order_id = opt_id(payload, "work_order_id")
    work_order = resolve("work_orders", work_order_id) if work_order_id else None
    laboratory_id = opt_id(payload, "laboratory_id")
    laboratory = resolve("laboratories", laboratory_id) if laboratory_id else None
    retest_id = opt_id(payload, "retest_of_sample_id")
    retest_target = resolve("soil_samples", retest_id) if retest_id else None
    if project is None:
        raise ApiError("ERR_INVALID_REQUEST", "tank_project_id is required.")
    if work_order is None:
        raise ApiError("ERR_INVALID_REQUEST", "work_order_id is required.")
    if laboratory is None:
        raise ApiError("ERR_INVALID_REQUEST", "laboratory_id is required.")

    sample_point = req_enum(payload, "sample_point", calc.SAMPLE_POINTS)
    depth_inches = req_int(payload, "depth_inches", exclusive_min=0)

    if project["status"] not in ("SAMPLING", "REMEDIATION_ACTIVE"):
        raise ApiError("ERR_PROJECT_STATE_INVALID")
    reopening = project["status"] == "REMEDIATION_ACTIVE"
    if reopening and svc.open_change_order_count(project) > 0:
        # Reopening sampling is blocked while remediation scoping is unsettled.
        raise ApiError("ERR_PROJECT_STATE_INVALID")

    if retest_target is not None:
        if retest_target["tank_project_id"] != project["id"] \
                or retest_target["status"] != "INVALIDATED":
            raise ApiError("ERR_RETEST_TARGET_INVALID")

    if reopening:
        assign(project, "sampling_round", int(project["sampling_round"]) + 1)
        svc.clear_classification(project)
        assign(project, "status", "SAMPLING")

    sample = create("soil_samples", {
        "tank_project_id": project["id"],
        "work_order_id": work_order["id"],
        "laboratory_id": laboratory["id"],
        "retest_of_sample_id": retest_target["id"] if retest_target else None,
        "sampling_round": project["sampling_round"],
        "sample_point": sample_point,
        "depth_inches": depth_inches,
        "collected_at": db.now(),
        "collected_by_user_id": user_id,
        "dispatched_at": None,
        "received_at": None,
        "reported_at": None,
        "holding_time_elapsed_hours": None,
        "turnaround_hours": None,
        "turnaround_breach": False,
        "tph_mg_kg": None,
        "benzene_mg_kg": None,
        "qc_flag": "NONE",
        "status": "COLLECTED",
    })
    svc.recompute_blockers(project)
    return entity_response(sample, 201)


@bp.get("/soil-samples")
def list_samples():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    project_id = filter_arg("tank_project_id")
    work_order_id = filter_arg("work_order_id")
    laboratory_id = filter_arg("laboratory_id")
    retest_id = filter_arg("retest_of_sample_id")
    sampling_round = int_filter_arg("sampling_round")
    status = filter_arg("status")
    rows = list(db.soil_samples.values())
    if project_id is not None:
        rows = [r for r in rows if r["tank_project_id"] == project_id]
    if work_order_id is not None:
        rows = [r for r in rows if r["work_order_id"] == work_order_id]
    if laboratory_id is not None:
        rows = [r for r in rows if r["laboratory_id"] == laboratory_id]
    if retest_id is not None:
        rows = [r for r in rows if r["retest_of_sample_id"] == retest_id]
    if sampling_round is not None:
        rows = [r for r in rows if r["sampling_round"] == sampling_round]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, limit, offset)


@bp.get("/soil-samples/<sample_id>")
def read_sample(sample_id):
    authenticate(READ_ROLES)
    return entity_response(resolve("soil_samples", sample_id))


@bp.post("/soil-samples/<sample_id>/chain-of-custody")
def chain_of_custody(sample_id):
    user_id, role = authenticate(("FieldTechnician", "LabAnalyst"))
    sample = resolve("soil_samples", sample_id)
    require_sample_owner(sample, user_id, role)
    payload = body()
    event = req_enum(payload, "event", ("DISPATCH", "RECEIVE", "VOID"))
    if event == "RECEIVE" and role != "LabAnalyst":
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    if event in ("DISPATCH", "VOID") and role != "FieldTechnician":
        raise ApiError("ERR_ROLE_NOT_PERMITTED")

    project = db.tank_projects.get(sample["tank_project_id"])

    if event == "DISPATCH":
        if sample["status"] != "COLLECTED":
            raise ApiError("ERR_SAMPLE_STATE_INVALID")
        assign(sample, "status", "IN_TRANSIT")
        assign(sample, "dispatched_at", db.now())
    elif event == "VOID":
        if sample["status"] not in ("COLLECTED", "IN_TRANSIT"):
            raise ApiError("ERR_SAMPLE_STATE_INVALID")
        assign(sample, "status", "VOIDED")
        if project is not None:
            svc.recompute_blockers(project)
    else:  # RECEIVE
        if sample["status"] != "IN_TRANSIT":
            raise ApiError("ERR_SAMPLE_STATE_INVALID")
        _receive(sample, project)
    return entity_response(sample)


def _receive(sample, project):
    lab = db.laboratories.get(sample["laboratory_id"])
    now = db.now()
    if lab is None or not lab["accredited"]:
        raise ApiError("ERR_LAB_NOT_ACCREDITED")

    # rule 13 — capacity (closed analysis window) then holding time.
    window = timedelta(hours=int(lab["committed_turnaround_hours"]))
    occupied = 0
    for other in db.soil_samples.values():
        if other is sample or other["laboratory_id"] != lab["id"]:
            continue
        if other["status"] != "AT_LAB" or other["received_at"] is None:
            continue
        if other["received_at"] <= now <= other["received_at"] + window:
            occupied += 1
    if occupied >= int(lab["max_concurrent_analyses"]):
        raise ApiError("ERR_LAB_CAPACITY_EXCEEDED")

    elapsed = calc.elapsed_hours(sample["collected_at"], now)
    assign(sample, "holding_time_elapsed_hours", elapsed)
    if elapsed > calc.dec(lab["holding_time_hours"]):
        # Persist-then-reject: the aliquot is legally worthless.
        assign(sample, "status", "INVALIDATED")
        assign(sample, "qc_flag", "HOLDING_TIME_EXCEEDED")
        if project is not None:
            svc.recompute_blockers(project)
        commit()
        raise ApiError("ERR_HOLDING_TIME_EXCEEDED")

    assign(sample, "received_at", now)
    assign(sample, "status", "AT_LAB")


@bp.post("/soil-samples/<sample_id>/result")
def post_result(sample_id):
    user_id, role = authenticate(("LabAnalyst",))
    sample = resolve("soil_samples", sample_id)
    require_sample_owner(sample, user_id, role)
    payload = body()
    tph = req_num(payload, "tph_mg_kg", minimum=0)
    benzene = req_num(payload, "benzene_mg_kg", minimum=0)

    if sample["status"] != "AT_LAB":
        raise ApiError("ERR_SAMPLE_STATE_INVALID")

    lab = db.laboratories.get(sample["laboratory_id"])
    now = db.now()
    assign(sample, "tph_mg_kg", tph)
    assign(sample, "benzene_mg_kg", benzene)
    assign(sample, "reported_at", now)
    turnaround = calc.elapsed_hours(sample["received_at"], now)
    assign(sample, "turnaround_hours", turnaround)
    assign(sample, "turnaround_breach",
           bool(lab is not None and turnaround > calc.dec(lab["committed_turnaround_hours"])))
    assign(sample, "status", "RESULTED")

    project = db.tank_projects.get(sample["tank_project_id"])
    if project is not None:
        svc.evaluate_round_completion(project)
        svc.recompute_blockers(project)
    return entity_response(sample)


@bp.post("/soil-samples/<sample_id>/retract-result")
def retract_result(sample_id):
    user_id, role = authenticate(("LabAnalyst",))
    sample = resolve("soil_samples", sample_id)
    require_sample_owner(sample, user_id, role)
    payload = body()
    req_str(payload, "reason")

    if sample["status"] != "RESULTED":
        raise ApiError("ERR_SAMPLE_STATE_INVALID")
    project = db.tank_projects.get(sample["tank_project_id"])
    if project is None or project["status"] not in (
            "SAMPLING", "ASSESSED", "CLEARED", "REMEDIATION_ACTIVE"):
        raise ApiError("ERR_PROJECT_STATE_INVALID")
    if sample["sampling_round"] != project["sampling_round"]:
        raise ApiError("ERR_SAMPLE_STATE_INVALID")

    assign(sample, "status", "INVALIDATED")
    assign(sample, "qc_flag", "RESULT_RETRACTED")
    svc.clear_classification(project)
    assign(project, "status", "SAMPLING")
    svc.recompute_blockers(project)
    return entity_response(sample)
