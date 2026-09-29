"""Installation projects: two independent axes plus the fork-join go-live."""

from datetime import timedelta

from flask import Blueprint, g

import lookups
import serializers
from db import db, iso_ms, new_row, ordered, touch
from errors import ApiError
from middleware import CAPITAL_PLANNER, FACILITY_DIRECTOR, guard
from response import created_response, object_response
from validation import (body, bool_field, dt_field, pagination, present, q_str,
                        raw_ref, str_field)

bp = Blueprint("projects", __name__)

DOWNTIME_BUFFER = timedelta(hours=24)
CONSTRUCTION_CHAIN = ("DESIGN", "PERMIT", "BUILD", "COMPLETE")
EQUIPMENT_CHAIN = ("AWAITING_DELIVERY", "DELIVERED", "INSTALLED",
                   "COMMISSIONED")
GO_LIVE_CONSTRUCTION = ("NOT_REQUIRED", "COMPLETE")


def _require_facility(facility_id):
    if g.user_id != facility_id:
        raise ApiError("ERR_FACILITY_SCOPE_VIOLATION")


def _require_open(project):
    if project["record_status"] != "ACTIVE" or project["go_live_at"] is not None:
        raise ApiError("ERR_PROJECT_INVALID_STATE")


def _check_interval(start, end, inclusive_end=False):
    if start is None or end is None:
        return
    if inclusive_end:
        if end < start:
            raise ApiError("ERR_INVALID_INTERVAL")
    elif end <= start:
        raise ApiError("ERR_INVALID_INTERVAL")


def _check_downtime_conflict(department_id, start, end, exclude_id=None):
    lower = start - DOWNTIME_BUFFER
    upper = end + DOWNTIME_BUFFER
    for other in ordered(db.projects.values()):
        if other["id"] == exclude_id:
            continue
        if other["record_status"] != "ACTIVE":
            continue
        if other["department_id"] != department_id:
            continue
        if lower < other["_downtime_end"] and other["_downtime_start"] < upper:
            raise ApiError("ERR_DOWNTIME_WINDOW_CONFLICT")


def _check_construction_capacity(facility_id, start, end, exclude_id=None):
    facility = db.facilities.get(facility_id)
    ceiling = facility["max_concurrent_construction"] if facility else 1
    count = 0
    for other in ordered(db.projects.values()):
        if other["id"] == exclude_id:
            continue
        if other["record_status"] != "ACTIVE":
            continue
        if not other["construction_required"]:
            continue
        if other["facility_id"] != facility_id:
            continue
        if (other["_construction_start"] is None
                or other["_construction_end"] is None):
            continue
        if other["_construction_start"] <= end and start <= other["_construction_end"]:
            count += 1
    if count + 1 > ceiling:
        raise ApiError("ERR_CONSTRUCTION_CAPACITY_EXCEEDED")


def _check_dependency_cycle(predecessor_id, self_id):
    if predecessor_id is None:
        return
    if self_id is not None and predecessor_id == self_id:
        raise ApiError("ERR_PROJECT_DEPENDENCY_CYCLE")
    seen = set()
    cursor = predecessor_id
    while cursor is not None and cursor not in seen:
        if self_id is not None and cursor == self_id:
            raise ApiError("ERR_PROJECT_DEPENDENCY_CYCLE")
        seen.add(cursor)
        row = db.projects.get(cursor)
        if row is None:
            return
        cursor = row["predecessor_project_id"]


@bp.route("/capital/requests/<request_id>/installation-projects",
          methods=["POST"])
@guard(FACILITY_DIRECTOR)
def create_project(request_id):
    request_row = lookups.request_row(request_id)
    data = body()
    ref = raw_ref(data, "predecessor_project_id")
    if ref is not None:
        lookups.project(ref)

    department = lookups.department(request_row["department_id"])
    _require_facility(department["facility_id"])

    downtime_start_raw, downtime_start = dt_field(data, "downtime_start")
    downtime_end_raw, downtime_end = dt_field(data, "downtime_end")
    construction_required = bool_field(data, "construction_required",
                                       required=False, default=False)
    cs_raw, cs = dt_field(data, "construction_start", required=False)
    ce_raw, ce = dt_field(data, "construction_end", required=False)
    predecessor_id = str_field(data, "predecessor_project_id", 1, None,
                               required=False)

    if request_row["status"] != "FUNDED":
        raise ApiError("ERR_REQUEST_INVALID_STATE")

    _check_interval(downtime_start, downtime_end)
    _check_interval(cs, ce, inclusive_end=True)

    if construction_required:
        if cs is None or ce is None:
            raise ApiError("ERR_CONSTRUCTION_WINDOW_REQUIRED")
    elif cs is not None or ce is not None:
        raise ApiError("ERR_CONSTRUCTION_WINDOW_REQUIRED")

    _check_downtime_conflict(department["id"], downtime_start, downtime_end)
    if construction_required:
        _check_construction_capacity(department["facility_id"], cs, ce)
    _check_dependency_cycle(predecessor_id, None)

    row = new_row({
        "request_id": request_row["id"],
        "facility_id": department["facility_id"],
        "department_id": department["id"],
        "predecessor_project_id": predecessor_id,
        "construction_required": construction_required,
        "construction_start": cs_raw,
        "_construction_start": cs,
        "construction_end": ce_raw,
        "_construction_end": ce,
        "downtime_start": downtime_start_raw,
        "_downtime_start": downtime_start,
        "downtime_end": downtime_end_raw,
        "_downtime_end": downtime_end,
        "construction_status": "DESIGN" if construction_required
                               else "NOT_REQUIRED",
        "equipment_status": "AWAITING_DELIVERY",
        "record_status": "ACTIVE",
        "go_live_at": None,
    })
    db.projects[row["id"]] = row
    return created_response(serializers.project(row))


@bp.route("/capital/installation-projects/<project_id>", methods=["PATCH"])
@guard(FACILITY_DIRECTOR)
def patch_project(project_id):
    project = lookups.project(project_id)
    data = body()
    ref = raw_ref(data, "predecessor_project_id")
    if ref is not None:
        lookups.project(ref)

    _require_facility(project["facility_id"])

    downtime_start_raw, downtime_start = dt_field(data, "downtime_start",
                                                  required=False)
    downtime_end_raw, downtime_end = dt_field(data, "downtime_end",
                                              required=False)
    construction_required = bool_field(data, "construction_required",
                                       required=False)
    cs_raw, cs = dt_field(data, "construction_start", required=False)
    ce_raw, ce = dt_field(data, "construction_end", required=False)
    predecessor_id = str_field(data, "predecessor_project_id", 1, None,
                               required=False)

    _require_open(project)

    effective_ds = (downtime_start if downtime_start is not None
                    else project["_downtime_start"])
    effective_de = (downtime_end if downtime_end is not None
                    else project["_downtime_end"])
    _check_interval(effective_ds, effective_de)

    effective_required = (construction_required if construction_required is not None
                          else project["construction_required"])
    if effective_required:
        effective_cs = cs if cs is not None else project["_construction_start"]
        effective_ce = ce if ce is not None else project["_construction_end"]
        effective_cs_raw = (cs_raw if cs_raw is not None
                            else project["construction_start"])
        effective_ce_raw = (ce_raw if ce_raw is not None
                            else project["construction_end"])
    else:
        effective_cs = effective_ce = None
        effective_cs_raw = effective_ce_raw = None
    _check_interval(effective_cs, effective_ce, inclusive_end=True)

    if effective_required:
        if effective_cs is None or effective_ce is None:
            raise ApiError("ERR_CONSTRUCTION_WINDOW_REQUIRED")
    elif present(data, "construction_start") or present(data, "construction_end"):
        if cs is not None or ce is not None:
            raise ApiError("ERR_CONSTRUCTION_WINDOW_REQUIRED")

    _check_downtime_conflict(project["department_id"], effective_ds, effective_de,
                             exclude_id=project["id"])
    if effective_required:
        _check_construction_capacity(project["facility_id"], effective_cs,
                                     effective_ce, exclude_id=project["id"])
    if predecessor_id is not None:
        _check_dependency_cycle(predecessor_id, project["id"])

    project["downtime_start"] = (downtime_start_raw if downtime_start_raw is not None
                                 else project["downtime_start"])
    project["_downtime_start"] = effective_ds
    project["downtime_end"] = (downtime_end_raw if downtime_end_raw is not None
                               else project["downtime_end"])
    project["_downtime_end"] = effective_de
    project["construction_start"] = effective_cs_raw
    project["_construction_start"] = effective_cs
    project["construction_end"] = effective_ce_raw
    project["_construction_end"] = effective_ce

    if construction_required is not None:
        if construction_required and not project["construction_required"]:
            project["construction_status"] = "DESIGN"
        elif not construction_required and project["construction_required"]:
            project["construction_status"] = "NOT_REQUIRED"
        project["construction_required"] = construction_required

    if predecessor_id is not None:
        project["predecessor_project_id"] = predecessor_id

    touch(project)
    return object_response(serializers.project(project))


@bp.route("/capital/installation-projects/<project_id>", methods=["GET"])
@guard()
def get_project(project_id):
    return object_response(serializers.project(lookups.project(project_id)))


@bp.route("/capital/installation-projects", methods=["GET"])
@guard()
def list_projects():
    limit, offset = pagination()
    rows = lookups.filtered(db.projects.values(), [
        ("request_id", q_str("request_id")),
        ("facility_id", q_str("facility_id")),
        ("department_id", q_str("department_id")),
        ("predecessor_project_id", q_str("predecessor_project_id")),
        ("record_status", q_str("record_status")),
        ("construction_status", q_str("construction_status")),
        ("equipment_status", q_str("equipment_status")),
    ])
    return lookups.paginate(rows, limit, offset, serializers.project)


# ---------------------------------------------------------- the two axes

@bp.route("/capital/installation-projects/<project_id>/advance-construction",
          methods=["POST"])
@guard(FACILITY_DIRECTOR)
def advance_construction(project_id):
    project = lookups.project(project_id)
    _require_facility(project["facility_id"])
    _require_open(project)

    current = project["construction_status"]
    if current not in CONSTRUCTION_CHAIN[:-1]:
        raise ApiError("ERR_PROJECT_INVALID_STATE")
    project["construction_status"] = \
        CONSTRUCTION_CHAIN[CONSTRUCTION_CHAIN.index(current) + 1]
    touch(project)
    return object_response(serializers.project(project))


@bp.route("/capital/installation-projects/<project_id>/advance-equipment",
          methods=["POST"])
@guard(FACILITY_DIRECTOR)
def advance_equipment(project_id):
    project = lookups.project(project_id)
    _require_facility(project["facility_id"])
    _require_open(project)

    current = project["equipment_status"]
    if current not in EQUIPMENT_CHAIN[:-1]:
        raise ApiError("ERR_PROJECT_INVALID_STATE")
    project["equipment_status"] = \
        EQUIPMENT_CHAIN[EQUIPMENT_CHAIN.index(current) + 1]
    touch(project)
    return object_response(serializers.project(project))


@bp.route("/capital/installation-projects/<project_id>/go-live",
          methods=["POST"])
@guard(FACILITY_DIRECTOR)
def go_live(project_id):
    project = lookups.project(project_id)
    _require_facility(project["facility_id"])
    _require_open(project)

    # The fork-join guard: an unconverged axis is a project-state fault.
    if project["construction_status"] not in GO_LIVE_CONSTRUCTION:
        raise ApiError("ERR_PROJECT_INVALID_STATE")
    if project["equipment_status"] != "COMMISSIONED":
        raise ApiError("ERR_PROJECT_INVALID_STATE")

    request_row = lookups.request_row(project["request_id"])
    if request_row["status"] != "FUNDED":
        raise ApiError("ERR_REQUEST_INVALID_STATE")

    predecessor_id = project["predecessor_project_id"]
    if predecessor_id:
        predecessor = db.projects.get(predecessor_id)
        if (predecessor is None
                or predecessor["record_status"] != "ACTIVE"
                or predecessor["equipment_status"] != "COMMISSIONED"):
            raise ApiError("ERR_PREDECESSOR_NOT_COMMISSIONED")

    project["go_live_at"] = iso_ms(db.now())
    project["_go_live_at"] = db.now()
    touch(project)

    request_row["status"] = "IMPLEMENTED"
    touch(request_row)
    return object_response(serializers.project(project))


@bp.route("/capital/installation-projects/<project_id>/cancel", methods=["POST"])
@guard(CAPITAL_PLANNER)
def cancel_project(project_id):
    project = lookups.project(project_id)
    data = body()
    str_field(data, "cancellation_reason", 0, 500, required=False)

    _require_open(project)

    project["record_status"] = "CANCELLED"
    touch(project)
    return object_response(serializers.project(project))
