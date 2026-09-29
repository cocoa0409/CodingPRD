"""Controlled research area access grants (PRD 3.7)."""

from flask import Blueprint

import db
import response
import util
import validate
from errors import ApiError
from middleware import RSO, require, require_any
from routes.common import must_exist, render_list
from services import cascade, derive, enums as E, present

bp = Blueprint("grants", __name__)

GRANT_TRANSITIONS = (
    ("REQUESTED", "ACTIVE"),
    ("REQUESTED", "SUSPENDED"),
    ("REQUESTED", "REVOKED"),
    ("ACTIVE", "SUSPENDED"),
    ("ACTIVE", "REVOKED"),
    ("SUSPENDED", "ACTIVE"),
    ("SUSPENDED", "REVOKED"),
)


@bp.post("/controlled-access-grants")
def create_grant():
    require(RSO)
    data = validate.body()

    # step 5 — body foreign keys in declaration order
    project = must_exist("project", data.get("project_id"))
    investigator = must_exist("investigator", data.get("investigator_id"))

    valid_from = validate.req_instant(data, "valid_from")
    valid_until = validate.req_instant(data, "valid_until")
    expected = data.get("expected_project_version")
    if expected is None:
        validate.bad("Field 'expected_project_version' is required.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        validate.bad("Field 'expected_project_version' must be an integer.")

    # step 8 — parent version match
    if expected != project["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "Project version is %d." % project["version"])

    # step 15 — one unrevoked grant per project + investigator
    for existing in derive.project_grants(project["id"]):
        if existing["investigator_id"] != investigator["id"]:
            continue
        if existing["status"] != "REVOKED":
            raise ApiError("ERR_DUPLICATE_ACCESS_GRANT",
                           "An unrevoked access grant already exists for this "
                           "project and investigator.")

    # step 17 — interval sanity
    if util.parse_dt(valid_until) <= util.parse_dt(valid_from):
        raise ApiError("ERR_INVALID_GRANT_WINDOW",
                       "valid_until must fall strictly after valid_from.")

    record = db.base_record()
    record.update({
        "project_id": project["id"],
        "investigator_id": investigator["id"],
        "valid_from": valid_from,
        "valid_until": valid_until,
        "peak_concurrency_at_request": 0,
        "status": "REQUESTED",
        "status_reason": "NONE",
        "activated_at": None,
        "revoked_at": None,
    })
    # informational projection — never enforced at request time
    record["peak_concurrency_at_request"] = derive.peak_concurrency(
        project["id"], valid_from, valid_until, record["id"])
    db.grants[record["id"]] = record
    cascade.recompute_project(project)
    return response.object_response(present.grant(record), 201)


@bp.get("/controlled-access-grants/<grant_id>")
def read_grant(grant_id):
    require_any()
    record = must_exist("grant", grant_id)
    return response.object_response(present.grant(record))


@bp.get("/controlled-access-grants")
def list_grants():
    require_any()
    project_id = validate.filter_value("project_id")
    investigator_id = validate.filter_value("investigator_id")
    status = validate.filter_enum("status", E.GRANT_STATUSES)

    rows = []
    for record in db.ordered(db.grants.values()):
        if project_id and record["project_id"] != project_id:
            continue
        if investigator_id and record["investigator_id"] != investigator_id:
            continue
        if status and record["status"] != status:
            continue
        rows.append(record)
    return render_list(rows, present.grant)


@bp.post("/controlled-access-grants/<grant_id>/status")
def set_grant_status(grant_id):
    require(RSO)
    data = validate.body()
    record = must_exist("grant", grant_id)

    to_status = validate.req_enum(data, "to_status", E.GRANT_STATUSES)
    current = record["status"]
    if (current, to_status) not in GRANT_TRANSITIONS:
        raise ApiError("ERR_INVALID_GRANT_TRANSITION",
                       "Grant status cannot move %s -> %s." % (current, to_status))

    project = db.projects.get(record["project_id"])
    investigator = db.investigators.get(record["investigator_id"])

    if to_status == "ACTIVE":
        if project is None or project["security_status"] != "CLEARED":
            raise ApiError("ERR_PROJECT_NOT_CLEARED",
                           "The project's security_status must be CLEARED.")
        if current == "REQUESTED":
            active_row = None
            for row in derive.project_personnel(project["id"]):
                if row["investigator_id"] == record["investigator_id"] and \
                        row["status"] == "ACTIVE":
                    active_row = row
                    break
            if active_row is None:
                raise ApiError("ERR_PERSONNEL_NOT_ACTIVE",
                               "The investigator holds no ACTIVE personnel row "
                               "on this project.")
        # step 11 — posture gate
        posture = derive.posture_of(investigator) if investigator else None
        if posture not in ("CLEAR", "REVIEW_REQUIRED"):
            raise ApiError("ERR_INVESTIGATOR_POSTURE_BLOCKS_ACCESS",
                           "A %s investigator may not hold area access."
                           % posture)
        # step 13 — training gate
        if not derive.has_satisfied_course(record["investigator_id"],
                                          "CONTROLLED_AREA_SAFETY"):
            raise ApiError("ERR_AREA_TRAINING_INCOMPLETE",
                           "CONTROLLED_AREA_SAFETY training is not satisfied.")
        # step 19 — half-open capacity projection
        peak = derive.peak_concurrency(project["id"], record["valid_from"],
                                       record["valid_until"], record["id"])
        if peak > int(project["controlled_area_capacity"]):
            raise ApiError("ERR_AREA_CAPACITY_EXCEEDED",
                           "Peak occupancy %d exceeds the area capacity of %d."
                           % (peak, int(project["controlled_area_capacity"])))

        record["peak_concurrency_at_request"] = peak
        record["status"] = "ACTIVE"
        record["status_reason"] = "NONE"
        if current == "REQUESTED":
            record["activated_at"] = db.clock_str()
        db.touch(record)
        cascade.recompute_project(project)

    elif to_status == "SUSPENDED":
        record["status"] = "SUSPENDED"
        record["status_reason"] = "OFFICER_ACTION"
        db.touch(record)
        if current == "ACTIVE":
            cascade.recompute_project(project)

    else:  # REVOKED
        record["status"] = "REVOKED"
        record["status_reason"] = "OFFICER_ACTION"
        if current in ("ACTIVE", "SUSPENDED"):
            record["revoked_at"] = db.clock_str()
        db.touch(record)
        if current == "ACTIVE":
            cascade.recompute_project(project)

    return response.object_response(present.grant(record))
