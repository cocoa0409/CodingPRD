"""Phased commissioning: packages, scripts, witnessing and load bank runs."""

from flask import Blueprint, g

import db
import validation as v
from constants import (
    CONCURRENT_LOADBANK_MAX,
    PACKAGE_LEVELS,
    ROLE_COMMISSIONING_AGENT,
    ROLE_WITNESS_AUTHORITY,
    STAFF_ROLES,
    WITNESS_DECISIONS,
)
from errors import ApiError
from middleware import endpoint
from output import created, filtered, listing, ok, require
from services import calc
from util import D, q

bp = Blueprint("commissioning", __name__)

READ_ROLES = list(STAFF_ROLES)
CA = [ROLE_COMMISSIONING_AGENT]
WA = [ROLE_WITNESS_AUTHORITY]

LEVEL_ORDER = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}


# ---------------------------------------------------- commissioning packages ----

@bp.post("/commissioning-packages")
@endpoint(CA)
def create_package():
    payload = v.body()
    hall_id = v.fk_field(payload, "hall_id")
    level = v.enum_field(payload, "level", PACKAGE_LEVELS)
    title = v.string_field(payload, "title")
    target_load = v.number_field(payload, "target_load_kw", gt=0, places=2)
    expected = v.int_field(payload, "expected_hall_version")

    hall = require("halls", hall_id)

    if expected != hall["version"]:
        raise ApiError("ERR_STALE_HALL_VERSION")
    if hall["status"] != "COMMISSIONING":
        raise ApiError("ERR_HALL_PHASE_INVALID")

    package = db.new_row(
        "packages",
        {
            "hall_id": hall["id"],
            "level": level,
            "title": title,
            "target_load_kw": target_load,
            "script_revision": 0,
            "script_status": "NOT_STARTED",
            "witness_status": "PENDING",
            "package_state": "DRAFT",
            "executed_by_user_id": None,
            "witnessed_by_user_id": None,
            "superseded_by_package_id": None,
            "measured_load_kw": None,
        },
    )
    for prior in db.where("packages", hall_id=hall["id"], level=level):
        if prior["id"] == package["id"] or prior["package_state"] == "SUPERSEDED":
            continue
        prior["superseded_by_package_id"] = package["id"]
        calc.project_package(prior)
        db.touch(prior)
    db.touch(hall)
    return created(package)


@bp.get("/commissioning-packages")
@endpoint(READ_ROLES)
def list_packages():
    return listing(
        filtered(
            "packages",
            {
                "hall_id": "hall_id",
                "level": "level",
                "package_state": "package_state",
            },
        )
    )


@bp.get("/commissioning-packages/<package_id>")
@endpoint(READ_ROLES)
def read_package(package_id):
    return ok(require("packages", package_id))


@bp.post("/commissioning-packages/<package_id>/approve-script")
@endpoint(CA)
def approve_script(package_id):
    payload = v.body()
    revision = v.int_field(payload, "script_revision")
    package = require("packages", package_id)

    if package["package_state"] == "SUPERSEDED":
        raise ApiError("ERR_INVALID_STATE")
    if package["script_status"] != "NOT_STARTED":
        raise ApiError("ERR_INVALID_STATE")

    hall = db.get("halls", package["hall_id"])
    if hall["status"] != "COMMISSIONING":
        raise ApiError("ERR_HALL_PHASE_INVALID")

    mine = LEVEL_ORDER[package["level"]]
    for peer in db.where("packages", hall_id=hall["id"]):
        if LEVEL_ORDER[peer["level"]] >= mine:
            continue
        if peer["package_state"] not in ("CERTIFIED", "SUPERSEDED"):
            raise ApiError("ERR_LEVEL_PREREQ_NOT_MET")

    package["script_status"] = "SCRIPT_APPROVED"
    package["script_revision"] = revision
    calc.project_package(package)
    db.touch(package)
    return ok(package)


@bp.post("/commissioning-packages/<package_id>/execute-script")
@endpoint(CA, needs_user_id=True)
def execute_script(package_id):
    package = require("packages", package_id)

    if package["package_state"] == "SUPERSEDED":
        raise ApiError("ERR_INVALID_STATE")
    if package["script_status"] != "SCRIPT_APPROVED":
        raise ApiError("ERR_INVALID_STATE")

    hall = db.get("halls", package["hall_id"])
    if hall["thermal_posture"] != "NOMINAL":
        raise ApiError("ERR_THERMAL_POSTURE_NOT_NOMINAL")

    if package["level"] in ("L4", "L5"):
        evidence = [
            t
            for t in db.where(
                "load_bank_tests", package_id=package["id"], status="COMPLETED"
            )
            if t["result"] == "PASS"
            and t["measured_kw"] is not None
            and D(t["measured_kw"]) >= D(package["target_load_kw"])
        ]
        if not evidence:
            raise ApiError("ERR_LOADBANK_PREREQ_MISSING")

    package["script_status"] = "EXECUTED"
    package["executed_by_user_id"] = g.user_id
    if package["witness_status"] == "REJECTED":
        package["witness_status"] = "PENDING"
    calc.project_package(package)
    db.touch(package)
    return ok(package)


@bp.post("/commissioning-packages/<package_id>/witness")
@endpoint(WA, needs_user_id=True)
def witness_package(package_id):
    payload = v.body()
    decision = v.enum_field(payload, "decision", WITNESS_DECISIONS)
    v.optional_string_or_null(payload, "witness_note")
    package = require("packages", package_id)

    if package["package_state"] == "SUPERSEDED":
        raise ApiError("ERR_INVALID_STATE")
    if package["script_status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_STATE")

    if package["executed_by_user_id"] is not None and (
        g.user_id == package["executed_by_user_id"]
    ):
        raise ApiError("ERR_WITNESS_SAME_AS_EXECUTOR")

    hall = db.get("halls", package["hall_id"])
    if decision == "WITNESSED" and hall["thermal_posture"] != "NOMINAL":
        raise ApiError("ERR_THERMAL_POSTURE_NOT_NOMINAL")

    package["witness_status"] = decision
    package["witnessed_by_user_id"] = g.user_id
    if decision == "REJECTED":
        package["script_status"] = "SCRIPT_APPROVED"
    calc.project_package(package)
    db.touch(package)

    calc.evaluate_hall_live(hall)
    return ok(package)


# ----------------------------------------------------------- load bank runs ----

@bp.post("/load-bank-tests")
@endpoint(CA)
def create_load_bank_test():
    payload = v.body()
    package_id = v.fk_field(payload, "package_id")
    target_kw = v.number_field(payload, "target_kw", gt=0, places=2)
    window_start = v.datetime_field(payload, "window_start")
    window_end = v.datetime_field(payload, "window_end")
    v.window_order(window_start, window_end)
    steps = v.step_sequence_field(payload, "step_pct_sequence")

    package = require("packages", package_id)
    if package["script_status"] != "SCRIPT_APPROVED":
        raise ApiError("ERR_SCRIPT_NOT_APPROVED")

    hall = db.get("halls", package["hall_id"])
    peers = calc.load_bank_peers(hall, window_start, window_end)
    if len(peers) + 1 > CONCURRENT_LOADBANK_MAX:
        raise ApiError("ERR_LOADBANK_CONCURRENCY_EXCEEDED")

    demand = calc.load_bank_reserve_demand(peers, target_kw)
    if demand > D(hall["commissioning_reserve_kw"]):
        raise ApiError("ERR_COMMISSIONING_RESERVE_EXCEEDED")

    test = db.new_row(
        "load_bank_tests",
        {
            "package_id": package["id"],
            "target_kw": target_kw,
            "window_start": window_start,
            "window_end": window_end,
            "step_pct_sequence": steps,
            "status": "SCHEDULED",
            "measured_kw": None,
            "measured_return_delta_t_f": None,
            "result": None,
            "abort_reason": None,
        },
    )
    return created(test)


@bp.get("/load-bank-tests")
@endpoint(READ_ROLES)
def list_load_bank_tests():
    return listing(
        filtered("load_bank_tests", {"package_id": "package_id", "status": "status"})
    )


@bp.get("/load-bank-tests/<test_id>")
@endpoint(READ_ROLES)
def read_load_bank_test(test_id):
    return ok(require("load_bank_tests", test_id))


@bp.post("/load-bank-tests/<test_id>/start")
@endpoint(CA)
def start_load_bank_test(test_id):
    test = require("load_bank_tests", test_id)
    if test["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    package = db.get("packages", test["package_id"])
    if package["script_status"] != "SCRIPT_APPROVED":
        raise ApiError("ERR_SCRIPT_NOT_APPROVED")

    now = db.clock_now()
    if now < test["window_start"] or now >= test["window_end"]:
        raise ApiError("ERR_OUTSIDE_EXECUTION_WINDOW")

    hall = db.get("halls", package["hall_id"])
    if hall["thermal_posture"] != "NOMINAL":
        raise ApiError("ERR_THERMAL_POSTURE_NOT_NOMINAL")

    test["status"] = "RUNNING"
    db.touch(test)
    return ok(test)


@bp.post("/load-bank-tests/<test_id>/complete")
@endpoint(CA)
def complete_load_bank_test(test_id):
    payload = v.body()
    measured_kw = v.number_field(payload, "measured_kw", ge=0)
    delta_t = v.number_field(payload, "measured_return_delta_t_f", ge=0)
    test = require("load_bank_tests", test_id)

    if test["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE")

    measured_kw = q(measured_kw, 2)
    delta_t = q(delta_t, 1)
    test["status"] = "COMPLETED"
    test["measured_kw"] = measured_kw
    test["measured_return_delta_t_f"] = delta_t
    test["result"] = calc.grade_load_bank(test, measured_kw, delta_t)
    db.touch(test)

    calc.apply_package_measured_load(db.get("packages", test["package_id"]))
    return ok(test)


@bp.post("/load-bank-tests/<test_id>/abort")
@endpoint(CA)
def abort_load_bank_test(test_id):
    payload = v.body()
    reason = v.string_field(payload, "abort_reason", allow_empty=False)
    test = require("load_bank_tests", test_id)

    if test["status"] not in ("SCHEDULED", "RUNNING"):
        raise ApiError("ERR_INVALID_STATE")

    test["status"] = "ABORTED"
    test["abort_reason"] = reason
    db.touch(test)
    return ok(test)
