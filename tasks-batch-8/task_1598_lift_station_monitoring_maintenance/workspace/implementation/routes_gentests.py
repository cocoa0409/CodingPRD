"""GeneratorTest routes: schedule/list/get, start/finish/fail/abort/cancel
(PRD 3.7)."""
from flask import Blueprint, request

import db
import services
from envelope import success
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_TEST_DURATION_TOO_SHORT,
)
from helpers import (
    body, bad, is_int, is_num, req_enum, req_instant, opt_str, paginate,
    TEST_KINDS,
)
from middleware import require_roles
from routes_stations import get_station_or_404
from serializers import ser_generator_test

bp = Blueprint("generator_tests", __name__)

TEST_READ_ROLES = (
    "UtilityAdmin", "OperationsSupervisor", "Operator", "MaintenancePlanner",
)


def get_test_or_404(tid):
    t = db.generator_tests.get(tid)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Generator test not found")
    return t


@bp.post("/stations/<sid>/generator-tests")
def create_test(sid):
    require_roles("MaintenancePlanner", "OperationsSupervisor")
    st = get_station_or_404(sid)
    services.check_posture(st)
    b = body()
    scheduled = req_instant(b, "scheduled_for")
    kind = req_enum(b, "test_kind", TEST_KINDS)
    load = b.get("load_percent")
    if load is None or not is_num(load):
        bad("load_percent is required and must be a number")
    if load < 0 or load > 100:
        bad("load_percent must be in [0, 100]")
    notes = opt_str(b, "outcome_notes", None)
    t = {
        "id": db.new_id(),
        "station_id": sid,
        "scheduled_for": scheduled,
        "test_kind": kind,
        "status": "SCHEDULED",
        "started_at": None,
        "duration_minutes": None,
        "load_percent": load,
        "outcome_notes": notes,
    }
    db.stamp(t)
    db.generator_tests[t["id"]] = t
    services.sync_station(st)
    return success(ser_generator_test(t), 201)


@bp.get("/stations/<sid>/generator-tests")
def list_station_tests(sid):
    require_roles(*TEST_READ_ROLES)
    get_station_or_404(sid)
    items = [t for t in db.generator_tests.values() if t["station_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, meta = paginate(items)
    return success([ser_generator_test(t) for t in page], 200, meta)


@bp.get("/generator-tests")
def list_tests():
    require_roles(*TEST_READ_ROLES)
    items = list(db.generator_tests.values())
    stid = request.args.get("station_id")
    if stid is not None:
        items = [t for t in items if t["station_id"] == stid]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    kind = request.args.get("test_kind")
    if kind is not None:
        items = [t for t in items if t["test_kind"] == kind]
    page, meta = paginate(items)
    return success([ser_generator_test(t) for t in page], 200, meta)


@bp.get("/generator-tests/<tid>")
def get_test(tid):
    require_roles(*TEST_READ_ROLES)
    return success(ser_generator_test(get_test_or_404(tid)))


# --------------------------------------------------------------------- lifecycle


@bp.post("/generator-tests/<tid>/start")
def start_test(tid):
    require_roles("Operator")
    t = get_test_or_404(tid)
    st = db.stations[t["station_id"]]
    if t["status"] not in ("SCHEDULED", "OVERDUE"):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a SCHEDULED or OVERDUE test can be started",
        )
    # Start is refused at FROZEN and EMERGENCY stations (PRD 3.7).
    services.check_posture(st)
    if not st["has_backup_generator"]:
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Station has no backup generator to test",
        )
    t["started_at"] = db.now()
    t["status"] = "RUNNING"
    db.touch(t)
    services.sync_station(st)
    return success(ser_generator_test(t))


@bp.post("/generator-tests/<tid>/finish")
def finish_test(tid):
    require_roles("Operator")
    t = get_test_or_404(tid)
    st = db.stations[t["station_id"]]
    if t["status"] != "RUNNING":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a RUNNING test can be finished")
    services.check_posture(st)
    b = body()
    duration = b.get("duration_minutes")
    if duration is None or not is_int(duration):
        bad("duration_minutes is required and must be an integer")
    # temporal (priority 18): minimum duration depends on test kind
    minimum = 30 if t["test_kind"] == "LOAD_BANK" else 15
    if duration < minimum:
        raise ApiError(
            ERR_TEST_DURATION_TOO_SHORT, 422,
            "duration_minutes must be >= %d for %s" % (minimum, t["test_kind"]),
        )
    t["duration_minutes"] = duration
    t["status"] = "PASSED"
    db.touch(t)
    services.sync_station(st)
    return success(ser_generator_test(t))


@bp.post("/generator-tests/<tid>/fail")
def fail_test(tid):
    require_roles("Operator")
    t = get_test_or_404(tid)
    st = db.stations[t["station_id"]]
    if t["status"] != "RUNNING":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a RUNNING test can be failed")
    services.check_posture(st)
    t["status"] = "FAILED"
    db.touch(t)
    services.auto_alarm(st["id"], "MAJOR", "GEN_TEST_FAILED")
    services.sync_station(st)
    return success(ser_generator_test(t))


@bp.post("/generator-tests/<tid>/abort")
def abort_test(tid):
    require_roles("Operator")
    t = get_test_or_404(tid)
    st = db.stations[t["station_id"]]
    if t["status"] != "RUNNING":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a RUNNING test can be aborted")
    services.check_posture(st)
    t["status"] = "ABORTED"
    db.touch(t)
    services.sync_station(st)
    return success(ser_generator_test(t))


@bp.post("/generator-tests/<tid>/cancel")
def cancel_test(tid):
    require_roles("OperationsSupervisor")
    t = get_test_or_404(tid)
    st = db.stations[t["station_id"]]
    if t["status"] not in ("SCHEDULED", "OVERDUE"):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a SCHEDULED or OVERDUE test can be cancelled",
        )
    services.check_posture(st)
    t["status"] = "CANCELLED"
    db.touch(t)
    services.sync_station(st)
    return success(ser_generator_test(t))
