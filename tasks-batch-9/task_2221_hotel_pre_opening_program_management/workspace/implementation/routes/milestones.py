"""Milestone network endpoints (PRD §3.2)."""
from flask import Blueprint

import clock
import db
import guards
import repo
import response
import tx
import validate as v
from db import db as store
from errors import ApiError
from middleware import ALL_ROLES, require
from services import derive
from services import schedule as schedule_service

bp = Blueprint("milestones", __name__)


@bp.post("/pre-opening/milestones")
@require("ConstructionManager", "ProgramDirector")
def create_milestone():
    body = v.body()
    program_id = v.req_id(body, "program_id")
    code = v.req_str(body, "code", 1, 64)
    name = v.req_str(body, "name", 1, 120)
    duration_days = v.req_int(body, "duration_days", minimum=1)
    planned_raw, _planned = v.req_date(body, "planned_start_date")

    program = repo.get_program(program_id)
    guards.ensure_not_stabilized(program)
    if program["schedule_state"] not in ("PLANNING", "BASELINED"):
        raise ApiError("ERR_INVALID_PROGRAM_STATE",
                       "Milestones may only be added while the program is PLANNING or BASELINED.")
    for existing in repo.milestones_of(program_id):
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "A milestone with code %s already exists for this program." % code)

    ts = db.stamp()
    milestone = {
        "id": db.new_id(),
        "program_id": program_id,
        "code": code,
        "name": name,
        "duration_days": duration_days,
        "planned_start_date": planned_raw,
        "state": "NOT_STARTED",
        "actual_start_date": None,
        "actual_finish_date": None,
        "actual_duration_days": None,
        "blocked_days_accrued": 0,
        "rework_count": 0,
        "earliest_start_date": None,
        "earliest_finish_date": None,
        "latest_finish_date": None,
        "total_float_days": None,
        "is_critical": False,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    store.milestones[milestone["id"]] = milestone
    tx.commit()
    return response.created(repo.serialize(milestone))


@bp.get("/pre-opening/milestones")
@require(*ALL_ROLES)
def list_milestones():
    program_id = v.q_str("program_id")
    state = v.q_enum("state", repo.MILESTONE_STATES)
    is_critical = v.q_bool("is_critical")
    items = db.sort_created(list(store.milestones.values()))
    if program_id:
        items = [m for m in items if m["program_id"] == program_id]
    if state:
        items = [m for m in items if m["state"] == state]
    if is_critical is not None:
        items = [m for m in items if bool(m["is_critical"]) == is_critical]
    page, meta = v.paginate(items)
    return response.ok_list(repo.serialize_many(page), meta)


@bp.get("/pre-opening/milestones/<milestone_id>")
@require(*ALL_ROLES)
def read_milestone(milestone_id):
    return response.ok(repo.serialize(repo.get_milestone(milestone_id)))


def _finish_start_predecessors(milestone):
    preds = []
    for dep in store.dependencies.values():
        if dep["successor_milestone_id"] != milestone["id"]:
            continue
        if dep["dependency_type"] != "FINISH_START":
            continue
        pred = store.milestones.get(dep["predecessor_milestone_id"])
        if pred is not None:
            preds.append(pred)
    return preds


@bp.post("/pre-opening/milestones/<milestone_id>/start")
@require("ConstructionManager")
def start_milestone(milestone_id):
    milestone = repo.get_milestone(milestone_id)
    program = repo.get_program(milestone["program_id"])
    guards.ensure_not_stabilized(program)
    if milestone["state"] not in ("NOT_STARTED", "REOPENED"):
        raise ApiError("ERR_INVALID_MILESTONE_STATE",
                       "A milestone in state %s may not be started." % milestone["state"])
    if milestone["state"] == "NOT_STARTED":
        if program["schedule_state"] not in ("BASELINED", "CONSTRUCTION_COMPLETE", "LICENSING"):
            raise ApiError("ERR_INVALID_PROGRAM_STATE",
                           "The program's delivery dimension does not permit starting milestones.")
    for pred in _finish_start_predecessors(milestone):
        if pred["state"] != "COMPLETE":
            raise ApiError("ERR_PREDECESSOR_NOT_COMPLETE")

    milestone["state"] = "IN_PROGRESS"
    milestone["actual_start_date"] = clock.fmt_date(clock.today())
    milestone["actual_finish_date"] = None
    tx.commit()
    return response.ok(repo.serialize(milestone))


@bp.post("/pre-opening/milestones/<milestone_id>/complete")
@require("ConstructionManager")
def complete_milestone(milestone_id):
    milestone = repo.get_milestone(milestone_id)
    program = repo.get_program(milestone["program_id"])
    guards.ensure_not_stabilized(program)
    if milestone["state"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_MILESTONE_STATE",
                       "Only an IN_PROGRESS milestone may be completed.")
    for item in repo.punch_items_of(program["id"]):
        if (item["milestone_id"] == milestone["id"]
                and item["severity"] == "CRITICAL"
                and item["state"] != "VERIFIED"):
            raise ApiError("ERR_CRITICAL_PUNCH_OPEN")

    finish = clock.today()
    milestone["state"] = "COMPLETE"
    milestone["actual_finish_date"] = clock.fmt_date(finish)
    start = clock.parse_date_strict(milestone["actual_start_date"])
    milestone["actual_duration_days"] = (finish - start).days if start else None
    if milestone["code"] == "CONSTRUCTION_COMPLETE" and program["schedule_state"] == "BASELINED":
        program["schedule_state"] = "CONSTRUCTION_COMPLETE"
    derive.refresh(program, run_schedule=True)
    tx.commit()
    return response.ok(repo.serialize(milestone))


@bp.post("/pre-opening/milestones/<milestone_id>/reopen")
@require("ConstructionManager")
def reopen_milestone(milestone_id):
    body = v.body()
    v.opt_str(body, "reason", 1, 500)
    milestone = repo.get_milestone(milestone_id)
    program = repo.get_program(milestone["program_id"])
    guards.ensure_not_stabilized(program)
    if milestone["state"] != "COMPLETE":
        raise ApiError("ERR_INVALID_MILESTONE_STATE",
                       "Only a COMPLETE milestone may be reopened.")

    milestone["state"] = "REOPENED"
    milestone["rework_count"] = milestone["rework_count"] + 1
    milestone["actual_finish_date"] = None
    milestone["actual_duration_days"] = None
    derive.refresh(program, run_schedule=True)
    tx.commit()
    return response.ok(repo.serialize(milestone))


@bp.post("/pre-opening/milestone-dependencies")
@require("ConstructionManager", "ProgramDirector")
def create_dependency():
    body = v.body()
    predecessor_id = v.req_id(body, "predecessor_milestone_id")
    successor_id = v.req_id(body, "successor_milestone_id")
    dependency_type = v.opt_enum(body, "dependency_type", repo.DEPENDENCY_TYPES, "FINISH_START")
    lag_days = v.opt_int(body, "lag_days", 0, 0, 120)

    predecessor = repo.get_milestone(predecessor_id)
    successor = repo.get_milestone(successor_id)
    if predecessor["program_id"] != successor["program_id"]:
        raise ApiError("ERR_CROSS_PROGRAM_REFERENCE",
                       "Both ends of a dependency edge must belong to the same program.")
    program = repo.get_program(predecessor["program_id"])
    guards.ensure_not_stabilized(program)

    if predecessor_id == successor_id:
        raise ApiError("ERR_DEPENDENCY_CYCLE",
                       "A self edge counts as a cycle.")
    for dep in repo.dependencies_of_program(program["id"]):
        if (dep["predecessor_milestone_id"] == predecessor_id
                and dep["successor_milestone_id"] == successor_id):
            raise ApiError("ERR_DUPLICATE_DEPENDENCY")

    ts = db.stamp()
    dependency = {
        "id": db.new_id(),
        "predecessor_milestone_id": predecessor_id,
        "successor_milestone_id": successor_id,
        "dependency_type": dependency_type,
        "lag_days": lag_days,
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    milestones = repo.milestones_of(program["id"])
    candidate_edges = repo.dependencies_of_program(program["id"]) + [dependency]
    if schedule_service.has_cycle(milestones, candidate_edges):
        raise ApiError("ERR_DEPENDENCY_CYCLE")

    store.dependencies[dependency["id"]] = dependency
    tx.commit()
    return response.created(repo.serialize(dependency))


@bp.get("/pre-opening/milestones/<milestone_id>/dependencies")
@require(*ALL_ROLES)
def list_dependencies(milestone_id):
    milestone = repo.get_milestone(milestone_id)
    role = v.q_str("role")
    if role is not None:
        normalized = role.lower()
        if normalized not in ("predecessor", "successor"):
            raise v.bad("Query parameter 'role' must be 'predecessor' or 'successor'.")
        role = normalized
    items = []
    for dep in db.sort_created(list(store.dependencies.values())):
        as_pred = dep["predecessor_milestone_id"] == milestone["id"]
        as_succ = dep["successor_milestone_id"] == milestone["id"]
        if not (as_pred or as_succ):
            continue
        if role == "predecessor" and not as_pred:
            continue
        if role == "successor" and not as_succ:
            continue
        items.append(dep)
    page, meta = v.paginate(items)
    return response.ok_list(repo.serialize_many(page), meta)
