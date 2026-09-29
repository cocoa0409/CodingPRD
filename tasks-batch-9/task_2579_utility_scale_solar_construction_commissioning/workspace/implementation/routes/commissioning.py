"""Capacity and performance-ratio commissioning tests."""

from flask import Blueprint

import calc
import clock
import envelope
import store
import validate
from errors import fail
from routes.common import filter_eq, paginate, project_substation_energized
from validate import ALL_ROLES, authorize, body, dt, e, i, n, s

bp = Blueprint("commissioning", __name__)

TEST_TYPES = ("CAPACITY", "PERFORMANCE_RATIO")
VARIANTS = ("AS_MEASURED", "WEATHER_CORRECTED")
VOIDABLE = ("SCHEDULED", "IN_PROGRESS", "FAILED", "SUSPENDED")


@bp.post("/solar/commissioning-tests")
def create_test():
    authorize("CommissioningEngineer")
    data = body(
        s("project_id"),
        e("test_type", TEST_TYPES),
        dt("scheduled_at"),
        i("expected_project_version"),
        e("correction_variant", VARIANTS, required=False, default="AS_MEASURED"),
    )
    project = store.require_project(data["project_id"])
    if data["expected_project_version"] != project["version"]:
        fail("ERR_STALE_PROJECT_VERSION")

    for earlier in store.ordered(
        [
            t
            for t in store.tests.values()
            if t["project_id"] == project["id"] and t["test_type"] == data["test_type"]
        ]
    ):
        if earlier["status"] in VOIDABLE:
            earlier["status"] = "VOID"
            earlier["void_reason"] = "SUPERSEDED_BY_NEW_TEST"
            earlier["superseded"] = True
            store.touch(earlier)

    row = store.base()
    row.update(
        {
            "project_id": project["id"],
            "test_type": data["test_type"],
            "correction_variant": data["correction_variant"],
            "scheduled_at": data["scheduled_at"],
            "status": "SCHEDULED",
            "interval_count": 0,
            "valid_interval_count": 0,
            "reported_kw_ac": None,
            "reported_performance_ratio": None,
            "pass_threshold_kw_ac": None,
            "finalized_at": None,
            "suspend_reason": None,
            "void_reason": None,
            "superseded": False,
        }
    )
    store.tests[row["id"]] = row
    store.touch(project)
    return envelope.created(row)


@bp.get("/solar/commissioning-tests/<test_id>")
def get_test(test_id):
    authorize(*ALL_ROLES)
    return envelope.ok(store.require_test(test_id))


@bp.get("/solar/projects/<project_id>/commissioning-tests")
def list_tests(project_id):
    authorize(*ALL_ROLES)
    store.require_project(project_id)
    rows = store.children(store.tests, "project_id", project_id)
    rows = filter_eq(rows, "test_type", validate.q("test_type"))
    rows = filter_eq(rows, "status", validate.q("status"))
    return paginate(rows)


@bp.post("/solar/commissioning-tests/<test_id>/intervals")
def append_interval(test_id):
    authorize("CommissioningEngineer")
    data = body(
        dt("sampled_at"),
        n("irradiance_w_m2", ge=0),
        n("measured_kw_ac", ge=0),
        n("ambient_c"),
        n("wind_m_s", ge=0),
    )
    test = store.require_test(test_id)
    if test["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        fail("ERR_TEST_STATE_INVALID")

    valid = calc.interval_is_valid(data["irradiance_w_m2"], data["wind_m_s"], data["ambient_c"])
    row = store.base(versioned=False)
    row.update(
        {
            "commissioning_test_id": test["id"],
            "sampled_at": data["sampled_at"],
            "irradiance_w_m2": data["irradiance_w_m2"],
            "measured_kw_ac": data["measured_kw_ac"],
            "ambient_c": data["ambient_c"],
            "wind_m_s": data["wind_m_s"],
            "is_valid": valid,
            "corrected_kw_ac": calc.corrected_kw_ac(
                data["measured_kw_ac"], data["irradiance_w_m2"], data["ambient_c"]
            )
            if valid
            else None,
        }
    )
    store.intervals[row["id"]] = row

    test["interval_count"] += 1
    if valid:
        test["valid_interval_count"] += 1
    if test["status"] == "SCHEDULED":
        test["status"] = "IN_PROGRESS"
    store.touch(test)
    return envelope.created(row)


@bp.get("/solar/commissioning-tests/<test_id>/intervals")
def list_intervals(test_id):
    authorize(*ALL_ROLES)
    store.require_test(test_id)
    rows = store.children(store.intervals, "commissioning_test_id", test_id)
    rows = filter_eq(rows, "is_valid", validate.qbool("is_valid"))
    return paginate(rows)


@bp.post("/solar/commissioning-tests/<test_id>/finalization")
def finalize_test(test_id):
    authorize("CommissioningEngineer")
    body(s("note", required=False))
    test = store.require_test(test_id)
    if test["status"] != "IN_PROGRESS":
        fail("ERR_TEST_STATE_INVALID")
    project = store.require_project(test["project_id"])
    if not project_substation_energized(project["id"]):
        fail("ERR_SUBSTATION_NOT_ENERGIZED")
    if not calc.valid_intervals(test):
        fail("ERR_NO_VALID_TEST_INTERVALS")

    if test["test_type"] == "CAPACITY":
        threshold, reported, passed = calc.capacity_outcome(test, project)
        test["pass_threshold_kw_ac"] = threshold
        test["reported_kw_ac"] = reported
    else:
        reported, passed = calc.performance_ratio_outcome(test, project)
        test["reported_performance_ratio"] = reported
    test["status"] = "PASSED" if passed else "FAILED"
    test["finalized_at"] = clock.now()
    store.touch(test)
    return envelope.ok(test)
