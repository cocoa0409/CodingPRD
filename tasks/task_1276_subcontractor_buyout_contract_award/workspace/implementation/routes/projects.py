"""Project endpoints."""
from flask import Blueprint

from db import DB, DEFAULT_CLOCK, new_id
from errors import ApiError
from middleware import ALL_ROLES, SUMMARY_ROLES, auth
from response import ok
from services import (
    get_project,
    reevaluate_certificates_for_project,
    ser_package,
    ser_project,
    sorted_created,
    stamp,
    touch,
)
from util import as_int, as_iso_dt, as_num, as_str, basis_arg, body, required

bp = Blueprint("projects", __name__)


@bp.post("/projects")
def create_project():
    auth(["GCAdmin"])
    data = body()
    name = as_str(required(data, "name"), "name")
    project_number = as_str(required(data, "project_number"), "project_number")
    estimated_budget_cents = as_int(
        required(data, "estimated_budget_cents"), "estimated_budget_cents"
    )
    buyout_target_savings_pct = as_num(
        required(data, "buyout_target_savings_pct"), "buyout_target_savings_pct"
    )
    for p in DB["projects"].values():
        if p["project_number"] == project_number:
            raise ApiError("ERR_VALIDATION", 422, "project_number must be unique")
    rec = {
        "id": new_id(),
        "name": name,
        "project_number": project_number,
        "estimated_budget_cents": estimated_budget_cents,
        "buyout_target_savings_pct": buyout_target_savings_pct,
        "status": "SETUP",
        "current_time_utc": DEFAULT_CLOCK,
    }
    stamp(rec)
    DB["projects"][rec["id"]] = rec
    return ok(ser_project(rec), status=201)


@bp.get("/projects/<pid>")
def get_one_project(pid):
    auth(ALL_ROLES)
    return ok(ser_project(get_project(pid)))


@bp.post("/projects/<pid>/open")
def open_project(pid):
    auth(["GCAdmin"])
    p = get_project(pid)
    if p["status"] != "SETUP":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Project is not in SETUP"
        )
    p["status"] = "BUYOUT_OPEN"
    touch(p)
    return ok(ser_project(p))


@bp.post("/projects/<pid>/clock")
def advance_clock(pid):
    auth(["GCAdmin"])
    p = get_project(pid)
    data = body()
    to_iso8601 = as_iso_dt(required(data, "to_iso8601"), "to_iso8601")
    p["current_time_utc"] = to_iso8601
    touch(p)
    reevaluate_certificates_for_project(p)
    return ok(ser_project(p))


@bp.get("/projects/<pid>/buyout-summary")
def buyout_summary(pid):
    auth(SUMMARY_ROLES)
    p = get_project(pid)
    basis = basis_arg()
    pkgs = sorted_created(
        [pk for pk in DB["trade_packages"].values() if pk["project_id"] == p["id"]]
    )
    items = [ser_package(pk, basis) for pk in pkgs]
    data = {
        "total_estimated_cents": sum(pk["estimated_budget_cents"] for pk in pkgs),
        "total_awarded_cents": sum(i["awarded_value_cents"] for i in items),
        "total_savings_cents": sum(i["buyout_savings_cents"] for i in items),
        "packages": items,
    }
    return ok(data)
