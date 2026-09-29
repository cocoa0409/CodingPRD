"""PermitRecord endpoints — the bifurcated state / local approval tracks."""

from flask import Blueprint

import auth
import serialize
import services
import validate
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from store import base_row, db, now, sorted_rows, touch

bp = Blueprint("permits", __name__)

TRACKS = ("STATE_MODULAR_PROGRAM", "LOCAL_AHJ")
SCOPES = ("PLAN_REVIEW", "INSIGNIA", "FOUNDATION", "SET", "OCCUPANCY")
STATUSES = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "CONDITIONS_ISSUED",
    "APPROVED",
    "DENIED",
    "EXPIRED",
)
DECISIONS = ("START_REVIEW", "ISSUE_CONDITIONS", "APPROVE", "DENY")

TRACK_SCOPES = {
    "STATE_MODULAR_PROGRAM": ("PLAN_REVIEW", "INSIGNIA"),
    "LOCAL_AHJ": ("FOUNDATION", "SET", "OCCUPANCY"),
}
ROLE_TRACK = {
    "StateProgramOfficer": "STATE_MODULAR_PROGRAM",
    "AuthorityHavingJurisdiction": "LOCAL_AHJ",
}


@bp.post("/modular/permits")
@auth.endpoint("ProgramAdmin")
def create_permit():
    data = validate.body(optional=False)
    project_id = validate.field_id(data, "project_id")
    track = validate.field_enum(data, "track", TRACKS)
    scope = validate.field_enum(data, "scope", SCOPES)
    expires_at = validate.field_dt(data, "expires_at", required=False)

    # the scope <-> track binding is a declared §1.1 constraint, so rank 3
    if scope not in TRACK_SCOPES[track]:
        raise validate.bad("scope %s is not valid on track %s" % (scope, track))

    # rank 5
    services.get_project(project_id)

    row = base_row()
    row.update(
        {
            "project_id": project_id,
            "track": track,
            "scope": scope,
            "status": "SUBMITTED",
            "pinned_package_id": None,
            "conditions_count": 0,
            "insignia_count_issued": 0,
            "decided_at": None,
            "decided_by_user_id": None,
            "expires_at": expires_at,
        }
    )
    db.permits[row["id"]] = row
    return created(serialize.permit(row))


@bp.get("/modular/permits/<permit_id>")
@auth.endpoint(
    "ProgramAdmin",
    "StateProgramOfficer",
    "AuthorityHavingJurisdiction",
    "SiteSuperintendent",
    "DesignEngineer",
)
def read_permit(permit_id):
    return ok(serialize.permit(services.get_permit(permit_id)))


@bp.get("/modular/permits")
@auth.endpoint(
    "ProgramAdmin",
    "StateProgramOfficer",
    "AuthorityHavingJurisdiction",
    "SiteSuperintendent",
    "DesignEngineer",
    "LenderDrawAdministrator",
)
def list_permits():
    project_id = validate.field_str_query("project_id")
    pinned_package_id = validate.field_str_query("pinned_package_id")
    track = validate.enum_query("track", TRACKS)
    scope = validate.enum_query("scope", SCOPES)
    status = validate.enum_query("status", STATUSES)
    rows = sorted_rows(list(db.permits.values()))
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if pinned_package_id is not None:
        rows = [r for r in rows if r["pinned_package_id"] == pinned_package_id]
    if track is not None:
        rows = [r for r in rows if r["track"] == track]
    if scope is not None:
        rows = [r for r in rows if r["scope"] == scope]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, meta = paginate(rows)
    return ok_list([serialize.permit(r) for r in page], meta)


@bp.post("/modular/permits/<permit_id>/decide")
@auth.endpoint("StateProgramOfficer", "AuthorityHavingJurisdiction")
def decide_permit(permit_id):
    data = validate.body(optional=False)
    decision = validate.field_enum(data, "decision", DECISIONS)
    conditions_count = validate.field_int(
        data, "conditions_count", required=False, minimum=0
    )
    expires_at = validate.field_dt(data, "expires_at", required=False)

    row = services.get_permit(permit_id)

    # rank 7 — the deciding role owns exactly one track
    if ROLE_TRACK[auth.role()] != row["track"]:
        raise ApiError(
            "ERR_PERMIT_TRACK_ROLE_MISMATCH",
            "role %s cannot decide a %s application" % (auth.role(), row["track"]),
        )

    # rank 54
    status = row["status"]
    if status not in ("SUBMITTED", "UNDER_REVIEW", "CONDITIONS_ISSUED"):
        raise ApiError(
            "ERR_PERMIT_ALREADY_DECIDED", "status %s is already decided" % status
        )
    if decision == "START_REVIEW" and status != "SUBMITTED":
        raise ApiError(
            "ERR_PERMIT_ALREADY_DECIDED", "review has already started on this application"
        )
    if decision == "ISSUE_CONDITIONS" and status not in ("SUBMITTED", "UNDER_REVIEW"):
        raise ApiError(
            "ERR_PERMIT_ALREADY_DECIDED",
            "conditions cannot be issued from status %s" % status,
        )

    project = db.projects.get(row["project_id"])

    if decision == "APPROVE":
        # rank 83 — an insignia release needs the live plan-review approval
        if row["scope"] == "INSIGNIA":
            if services.live_plan_review(row["project_id"]) is None:
                raise ApiError(
                    "ERR_PLAN_REVIEW_PREREQUISITE",
                    "the state plan review is not approved and live",
                )
        # rank 84 — a plan review pins exactly one FROZEN revision
        frozen = None
        if row["scope"] == "PLAN_REVIEW":
            frozen_rows = [
                p
                for p in services.packages_of_project(row["project_id"])
                if p["freeze_state"] == "FROZEN"
            ]
            if len(frozen_rows) != 1:
                raise ApiError(
                    "ERR_NO_FROZEN_PACKAGE",
                    "the project must have exactly one FROZEN design package",
                )
            frozen = frozen_rows[0]

        row["status"] = "APPROVED"
        row["decided_at"] = now()
        row["decided_by_user_id"] = auth.user_id()
        if expires_at is not None:
            row["expires_at"] = expires_at
        if frozen is not None:
            row["pinned_package_id"] = frozen["id"]
        if row["scope"] == "INSIGNIA" and project is not None:
            row["insignia_count_issued"] = project["planned_module_count"]
        touch(row)

    elif decision == "START_REVIEW":
        row["status"] = "UNDER_REVIEW"
        row["decided_at"] = now()
        row["decided_by_user_id"] = auth.user_id()
        if expires_at is not None:
            row["expires_at"] = expires_at
        touch(row)
        return ok(serialize.permit(row))

    elif decision == "ISSUE_CONDITIONS":
        row["status"] = "CONDITIONS_ISSUED"
        row["conditions_count"] += max(1, conditions_count or 0)
        row["decided_at"] = now()
        row["decided_by_user_id"] = auth.user_id()
        if expires_at is not None:
            row["expires_at"] = expires_at
        touch(row)

    else:  # DENY
        row["status"] = "DENIED"
        row["decided_at"] = now()
        row["decided_by_user_id"] = auth.user_id()
        row["pinned_package_id"] = None
        touch(row)

    if project is not None:
        services.refresh_project(project)
        touch(project)
    return ok(serialize.permit(row))
