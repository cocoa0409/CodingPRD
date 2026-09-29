"""Projects and the project lifecycle machine."""

from flask import Blueprint, request

import calc
import db
import derive
import serializers as s
import validators as v
from auth import ALL_ROLES, authenticate
from errors import ApiError
from response import created, ok, paginated, pagination

bp = Blueprint("projects", __name__)

ZONES = ("BASE", "ZONE1", "ZONE2")
FUNDING_SOURCES = ("FEDERAL_DAVIS_BACON", "STATE_ONLY", "DUAL")
TARGET_STATUSES = ("ACTIVE", "SUBSTANTIALLY_COMPLETE", "CLOSED")


def get_project(project_id):
    return v.lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")


@bp.route("/projects", methods=["POST"])
def create_project():
    authenticate(["PortalAdmin"])
    payload = v.body()
    determination = v.resolve_fk(
        payload, "wage_determination_id", db.wage_determinations, "ERR_DETERMINATION_NOT_FOUND"
    )
    portal = v.resolve_fk(
        payload, "reporting_portal_id", db.reporting_portals, "ERR_PORTAL_NOT_FOUND"
    )
    project_name = v.req_string(payload, "project_name", min_len=2, max_len=120)
    awarding_agency = v.req_string(payload, "awarding_agency", min_len=1)
    locality_code = v.req_string(payload, "locality_code", min_len=4, max_len=24, upper=True)
    zone_code = v.opt_enum(payload, "zone_code", ZONES, default="BASE")
    if determination is None:
        v.bad("wage_determination_id is required.")
    if portal is None:
        v.bad("reporting_portal_id is required.")
    funding_source = v.req_enum(payload, "funding_source", FUNDING_SOURCES)
    contract_award_date = v.req_instant(payload, "contract_award_date")

    if determination["locality_code"] != locality_code:
        v.bad("locality_code must equal the locality_code of the locked determination.")
    if determination["effective_date"] > contract_award_date:
        v.bad("The determination's effective_date must fall at or before contract_award_date.")

    v.unique_or_reject(
        db.projects, lambda r: r["project_name"] == project_name, "project_name must be unique."
    )

    row = db.base_row()
    row.update(
        {
            "project_name": project_name,
            "awarding_agency": awarding_agency,
            "locality_code": locality_code,
            "zone_code": zone_code,
            "wage_determination_id": determination["id"],
            "reporting_portal_id": portal["id"],
            "funding_source": funding_source,
            "contract_award_date": contract_award_date,
            "status": "AWARDED",
            "posture": "OPEN",
            "open_finding_count": 0,
            "open_critical_finding_count": 0,
            "outstanding_restitution_cents": 0,
            "suspended_assignment_count": 0,
        }
    )
    db.projects[row["id"]] = row
    return created(s.project(row))


@bp.route("/projects", methods=["GET"])
def list_projects():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    determination = request.args.get("wage_determination_id")
    portal = request.args.get("reporting_portal_id")
    status = request.args.get("status")
    posture = request.args.get("posture")
    locality = request.args.get("locality_code")

    def keep(row):
        if determination is not None and row["wage_determination_id"] != determination:
            return False
        if portal is not None and row["reporting_portal_id"] != portal:
            return False
        if status is not None and row["status"] != status:
            return False
        if posture is not None and row["posture"] != posture:
            return False
        if locality is not None and row["locality_code"] != locality:
            return False
        return True

    return paginated(db.ordered(db.projects, keep), s.project, limit, offset)


@bp.route("/projects/<project_id>", methods=["GET"])
def read_project(project_id):
    authenticate(ALL_ROLES)
    return ok(s.project(get_project(project_id)))


def _invalid(message):
    raise ApiError("ERR_INVALID_PROJECT_STATUS_TRANSITION", message)


@bp.route("/projects/<project_id>/status", methods=["POST"])
def set_project_status(project_id):
    authenticate(["PortalAdmin"])
    project = get_project(project_id)
    payload = v.body()
    to_status = v.req_enum(payload, "to_status", TARGET_STATUSES)

    if to_status == "ACTIVE":
        if project["status"] != "AWARDED":
            _invalid("Only an AWARDED project may be advanced to ACTIVE.")
        primes = [
            a
            for a in derive.assignments_of_project(project["id"])
            if a["tier"] == 0 and a["status"] == "ACTIVE"
        ]
        if not primes:
            _invalid("At least one tier-0 assignment must be ACTIVE.")
        project["status"] = "ACTIVE"
        db.touch(project)
        derive.recompute_project(project)
        return ok(s.project(project))

    if to_status == "SUBSTANTIALLY_COMPLETE":
        if project["status"] != "ACTIVE":
            _invalid("Only an ACTIVE project may be advanced to SUBSTANTIALLY_COMPLETE.")
        if project["posture"] == "FROZEN":
            raise ApiError("ERR_PROJECT_FROZEN", "A FROZEN project may not be advanced.")
        project["status"] = "SUBSTANTIALLY_COMPLETE"
        db.touch(project)
        derive.recompute_project(project)
        return ok(s.project(project))

    if project["status"] != "SUBSTANTIALLY_COMPLETE":
        _invalid("Only a SUBSTANTIALLY_COMPLETE project may be closed.")
    blocked = project["open_finding_count"] != 0 or project["outstanding_restitution_cents"] != 0
    if not blocked:
        for submission in derive.submissions_of_project(project["id"]):
            if submission["workflow_status"] in calc.NON_TERMINAL_WORKFLOW_STATUSES:
                blocked = True
                break
    if blocked:
        raise ApiError(
            "ERR_OPEN_FINDINGS_BLOCK_CLOSEOUT",
            "Open findings, outstanding restitution or unfiled payroll block closeout.",
        )
    project["status"] = "CLOSED"
    project["posture"] = "OPEN"
    db.touch(project)
    for assignment in derive.assignments_of_project(project["id"]):
        if assignment["status"] in ("INVITED", "ACTIVE", "SUSPENDED"):
            assignment["status"] = "TERMINATED"
            db.touch(assignment)
    derive.recompute_project(project)
    return ok(s.project(project))
