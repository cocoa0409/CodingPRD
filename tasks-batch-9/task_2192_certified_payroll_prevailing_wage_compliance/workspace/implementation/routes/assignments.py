"""Contract assignments (tiers) and their participation machine."""

from flask import Blueprint, request

import db
import derive
import serializers as s
import validators as v
from auth import ALL_ROLES, authenticate
from errors import ApiError
from response import created, ok, paginated, pagination

bp = Blueprint("assignments", __name__)

MAX_TIER = 4


def get_assignment(assignment_id):
    return v.lookup(db.contract_assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")


def _require_standing(contractor):
    if contractor["debarment_status"] != "CLEAR" or contractor["registration_status"] != "REGISTERED":
        raise ApiError(
            "ERR_CONTRACTOR_DEBARRED",
            "The contractor must be CLEAR and REGISTERED for this operation.",
        )


@bp.route("/projects/<project_id>/contract-assignments", methods=["POST"])
def create_assignment(project_id):
    authenticate(["PortalAdmin"])
    project = v.lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    payload = v.body()
    upper = v.resolve_fk(
        payload, "upper_tier_assignment_id", db.contract_assignments, "ERR_ASSIGNMENT_NOT_FOUND"
    )
    contractor = v.resolve_fk(payload, "contractor_id", db.contractors, "ERR_CONTRACTOR_NOT_FOUND")
    if contractor is None:
        v.bad("contractor_id is required.")
    subcontract_amount_cents = v.req_int(payload, "subcontract_amount_cents", minimum=1)

    tier = 0
    if upper is not None:
        tier = upper["tier"] + 1
        if tier > MAX_TIER:
            v.bad("tier may not exceed %d." % MAX_TIER)

    _require_standing(contractor)

    if upper is not None and upper["project_id"] != project["id"]:
        raise ApiError(
            "ERR_UPPER_TIER_NOT_ACTIVE", "The named upper tier belongs to another project."
        )

    row = db.base_row()
    row.update(
        {
            "project_id": project["id"],
            "contractor_id": contractor["id"],
            "upper_tier_assignment_id": upper["id"] if upper else None,
            "tier": tier,
            "subcontract_amount_cents": subcontract_amount_cents,
            "status": "INVITED",
            "cumulative_certified_hours": 0,
            "cumulative_restitution_cents": 0,
            "open_finding_count": 0,
        }
    )
    db.contract_assignments[row["id"]] = row
    return created(s.assignment(row))


def _filtered(rows_filter):
    limit, offset = pagination()
    return paginated(db.ordered(db.contract_assignments, rows_filter), s.assignment, limit, offset)


@bp.route("/projects/<project_id>/contract-assignments", methods=["GET"])
def list_project_assignments(project_id):
    authenticate(ALL_ROLES)
    project = v.lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    status = request.args.get("status")
    tier = request.args.get("tier")

    def keep(row):
        if row["project_id"] != project["id"]:
            return False
        if status is not None and row["status"] != status:
            return False
        if tier is not None and str(row["tier"]) != str(tier):
            return False
        return True

    return _filtered(keep)


@bp.route("/contract-assignments", methods=["GET"])
def list_assignments():
    authenticate(ALL_ROLES)
    project = request.args.get("project_id")
    contractor = request.args.get("contractor_id")
    upper = request.args.get("upper_tier_assignment_id")
    status = request.args.get("status")

    def keep(row):
        if project is not None and row["project_id"] != project:
            return False
        if contractor is not None and row["contractor_id"] != contractor:
            return False
        if upper is not None and row["upper_tier_assignment_id"] != upper:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return _filtered(keep)


@bp.route("/contract-assignments/<assignment_id>", methods=["GET"])
def read_assignment(assignment_id):
    authenticate(ALL_ROLES)
    return ok(s.assignment(get_assignment(assignment_id)))


@bp.route("/contract-assignments/<assignment_id>/activate", methods=["POST"])
def activate_assignment(assignment_id):
    authenticate(["PortalAdmin"])
    assignment = get_assignment(assignment_id)
    project = db.projects.get(assignment["project_id"])

    if assignment["status"] != "INVITED":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE", "Only an INVITED tier may be activated.")
    if project is None or project["status"] not in ("AWARDED", "ACTIVE"):
        raise ApiError(
            "ERR_INVALID_ASSIGNMENT_STATE",
            "The owning project must be AWARDED or ACTIVE to activate a tier.",
        )

    _require_standing(db.contractors.get(assignment["contractor_id"]))

    if assignment["upper_tier_assignment_id"] is not None:
        upper = db.contract_assignments.get(assignment["upper_tier_assignment_id"])
        if upper is None or upper["status"] != "ACTIVE":
            raise ApiError("ERR_UPPER_TIER_NOT_ACTIVE", "The upper tier is not ACTIVE.")

    assignment["status"] = "ACTIVE"
    db.touch(assignment)
    derive.recompute_project(project)
    return ok(s.assignment(assignment))


@bp.route("/contract-assignments/<assignment_id>/reinstate", methods=["POST"])
def reinstate_assignment(assignment_id):
    authenticate(["AgencyComplianceOfficer"])
    assignment = get_assignment(assignment_id)
    payload = v.body()
    v.req_nonempty_string(payload, "reason")

    if assignment["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE", "Only a SUSPENDED tier may be reinstated.")
    if assignment["open_finding_count"] != 0:
        raise ApiError(
            "ERR_INVALID_ASSIGNMENT_STATE",
            "Every finding on this tier must be closed before reinstatement.",
        )

    _require_standing(db.contractors.get(assignment["contractor_id"]))

    assignment["status"] = "ACTIVE"
    db.touch(assignment)
    derive.recompute_project(db.projects.get(assignment["project_id"]))
    return ok(s.assignment(assignment))
