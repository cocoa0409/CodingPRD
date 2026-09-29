"""System implementation and test-run endpoints (PRD §3.5)."""
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
from middleware import ALL_ROLES, actor, require
from services import derive

bp = Blueprint("systems", __name__)


@bp.post("/pre-opening/system-implementations")
@require("SystemsIntegrator", "ProgramDirector")
def create_system():
    body = v.body()
    program_id = v.req_id(body, "program_id")
    system_type = v.req_enum(body, "system_type", repo.SYSTEM_TYPES)
    prerequisite_system_id = v.opt_id(body, "prerequisite_system_id")
    is_required = v.opt_bool(body, "is_required", True)

    program = repo.get_program(program_id)
    prerequisite = None
    if prerequisite_system_id is not None:
        prerequisite = repo.get_system(prerequisite_system_id)
        if prerequisite["program_id"] != program_id:
            raise ApiError("ERR_CROSS_PROGRAM_REFERENCE",
                           "The prerequisite system belongs to another program.")
    guards.ensure_not_stabilized(program)
    for existing in repo.systems_of(program_id):
        if existing["system_type"] == system_type:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "A %s implementation already exists for this program." % system_type)

    ts = db.stamp()
    system = {
        "id": db.new_id(),
        "program_id": program_id,
        "system_type": system_type,
        "prerequisite_system_id": prerequisite_system_id,
        "is_required": is_required,
        "state": "PLANNED",
        "latest_pass_rate": None,
        "cumulative_pass_rate": None,
        "open_blocker_count": 0,
        "test_run_count": 0,
        "certified_by_user_id": None,
        "certified_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    store.systems[system["id"]] = system
    derive.refresh(program)
    tx.commit()
    return response.created(repo.serialize(system))


@bp.get("/pre-opening/system-implementations")
@require(*ALL_ROLES)
def list_systems():
    program_id = v.q_str("program_id")
    prerequisite_system_id = v.q_str("prerequisite_system_id")
    state = v.q_enum("state", repo.SYSTEM_STATES)
    items = db.sort_created(list(store.systems.values()))
    if program_id:
        items = [s for s in items if s["program_id"] == program_id]
    if prerequisite_system_id:
        items = [s for s in items if s["prerequisite_system_id"] == prerequisite_system_id]
    if state:
        items = [s for s in items if s["state"] == state]
    page, meta = v.paginate(items)
    return response.ok_list(repo.serialize_many(page), meta)


@bp.get("/pre-opening/system-implementations/<system_id>")
@require(*ALL_ROLES)
def read_system(system_id):
    return response.ok(repo.serialize(repo.get_system(system_id)))


@bp.post("/pre-opening/system-implementations/<system_id>/test-runs")
@require("SystemsIntegrator")
def create_test_run(system_id):
    body = v.body()
    executed_raw, _executed = v.req_instant(body, "executed_at")
    cases_total = v.req_int(body, "cases_total", minimum=0)
    cases_passed = v.req_int(body, "cases_passed", minimum=0)
    blocker_count = v.req_int(body, "blocker_count", minimum=0)
    if cases_passed > cases_total:
        raise v.bad("cases_passed must not exceed cases_total.")

    system = repo.get_system(system_id)
    program = repo.get_program(system["program_id"])
    guards.ensure_not_stabilized(program)
    if cases_total == 0:
        raise ApiError("ERR_TEST_RUN_EMPTY")

    pass_rate = derive.run_pass_rate(cases_passed, cases_total)
    run = {
        "id": db.new_id(),
        "system_implementation_id": system_id,
        "executed_at": executed_raw,
        "cases_total": cases_total,
        "cases_passed": cases_passed,
        "blocker_count": blocker_count,
        "pass_rate": pass_rate,
        "result": derive.run_result(pass_rate, blocker_count),
        "executed_by_user_id": actor(),
        "created_at": db.stamp(),
        "_seq": db.next_seq(),
    }
    store.test_runs[run["id"]] = run

    if system["state"] == "CERTIFIED":
        system["certified_by_user_id"] = None
        system["certified_at"] = None
    derive.reconcile_system(system)
    latest = system["latest_pass_rate"]
    system["state"] = "FAILED" if (latest is None or latest < 0.50) else "TESTING"

    derive.refresh(program)
    tx.commit(system_id)
    return response.created(repo.serialize(run))


@bp.get("/pre-opening/system-implementations/<system_id>/test-runs")
@require(*ALL_ROLES)
def list_test_runs(system_id):
    system = repo.get_system(system_id)
    runs = repo.test_runs_of(system["id"])
    runs = sorted(
        runs,
        key=lambda r: (clock.parse_instant(r["executed_at"]), r["created_at"], r["_seq"]),
        reverse=True,
    )
    page, meta = v.paginate(runs)
    return response.ok_list(repo.serialize_many(page), meta)


@bp.post("/pre-opening/system-implementations/<system_id>/certify")
@require("SystemsIntegrator", "ProgramDirector")
def certify_system(system_id):
    system = repo.get_system(system_id)
    program = repo.get_program(system["program_id"])

    # tier 6 -- segregation of duties precedes state admissibility (PRD §2.10)
    latest = derive.latest_run(system["id"])
    if latest is not None and latest["executed_by_user_id"] == actor():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The user who executed the most recent test run may not certify the system.")
    guards.ensure_not_stabilized(program)
    if system["state"] != "TESTING":
        raise ApiError("ERR_INVALID_SYSTEM_STATE",
                       "A system in state %s may not be certified." % system["state"])
    if system["latest_pass_rate"] is None or system["latest_pass_rate"] < 0.95:
        raise ApiError("ERR_SYSTEM_PASS_RATE_BELOW_THRESHOLD")
    if system["open_blocker_count"] != 0:
        raise ApiError("ERR_OPEN_BLOCKERS_PRESENT")
    if system["prerequisite_system_id"]:
        prerequisite = store.systems.get(system["prerequisite_system_id"])
        if prerequisite is None or prerequisite["state"] != "CERTIFIED":
            raise ApiError("ERR_PREREQUISITE_SYSTEM_NOT_CERTIFIED")

    system["state"] = "CERTIFIED"
    system["certified_by_user_id"] = actor()
    system["certified_at"] = clock.fmt_instant(clock.now())
    derive.refresh(program)
    tx.commit()
    return response.ok(repo.serialize(system))
