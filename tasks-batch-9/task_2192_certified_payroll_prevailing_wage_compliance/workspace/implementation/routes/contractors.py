"""Contractors, their staff rosters and the formal debarment decision."""

from flask import Blueprint, request

import db
import derive
import serializers as s
import validators as v
from auth import ALL_ROLES, authenticate
from errors import ApiError
from response import created, ok, paginated, pagination

bp = Blueprint("contractors", __name__)

REGISTRATION_STATUSES = ("REGISTERED", "LAPSED")
CAPABILITIES = ("PREPARER", "CERTIFIER", "BOTH")


def get_contractor(contractor_id):
    return v.lookup(db.contractors, contractor_id, "ERR_CONTRACTOR_NOT_FOUND")


@bp.route("/contractors", methods=["POST"])
def create_contractor():
    authenticate(["PortalAdmin"])
    payload = v.body()
    parent = v.resolve_fk(payload, "parent_contractor_id", db.contractors, "ERR_CONTRACTOR_NOT_FOUND")
    legal_name = v.req_string(payload, "legal_name", min_len=2, max_len=120)
    dir_registration_number = v.req_string(payload, "dir_registration_number", min_len=1)
    registration_status = v.opt_enum(
        payload, "registration_status", REGISTRATION_STATUSES, default="REGISTERED"
    )

    v.unique_or_reject(
        db.contractors, lambda r: r["legal_name"] == legal_name, "legal_name must be unique."
    )
    v.unique_or_reject(
        db.contractors,
        lambda r: r["dir_registration_number"] == dir_registration_number,
        "dir_registration_number must be unique.",
    )

    row = db.base_row()
    row.update(
        {
            "legal_name": legal_name,
            "parent_contractor_id": parent["id"] if parent else None,
            "dir_registration_number": dir_registration_number,
            "registration_status": registration_status,
            "debarment_status": "CLEAR",
            "debarment_risk_score": 0,
            "last_finding_at": None,
            "open_critical_finding_count": 0,
            "outstanding_restitution_cents": 0,
        }
    )
    db.contractors[row["id"]] = row
    return created(s.contractor(row))


@bp.route("/contractors", methods=["GET"])
def list_contractors():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    parent = request.args.get("parent_contractor_id")
    debarment_status = request.args.get("debarment_status")
    registration_status = request.args.get("registration_status")

    def keep(row):
        if parent is not None and row["parent_contractor_id"] != parent:
            return False
        if debarment_status is not None and row["debarment_status"] != debarment_status:
            return False
        if registration_status is not None and row["registration_status"] != registration_status:
            return False
        return True

    return paginated(db.ordered(db.contractors, keep), s.contractor, limit, offset)


@bp.route("/contractors/<contractor_id>", methods=["GET"])
def read_contractor(contractor_id):
    authenticate(ALL_ROLES)
    return ok(s.contractor(get_contractor(contractor_id)))


@bp.route("/contractors/<contractor_id>/debarment", methods=["POST"])
def decide_debarment(contractor_id):
    authenticate(["LaborStandardsAuditor"])
    contractor = get_contractor(contractor_id)
    payload = v.body()
    to_status = v.req_enum(payload, "to_status", ("DEBARRED", "CLEAR"))
    v.req_nonempty_string(payload, "reason")

    if contractor["debarment_status"] != "PROPOSED":
        raise ApiError(
            "ERR_CONTRACTOR_DEBARRED",
            "Only a contractor in PROPOSED may be debarred or restored.",
        )

    if to_status == "CLEAR":
        contractor["debarment_status"] = "CLEAR"
        db.touch(contractor)
        return ok(s.contractor(contractor))

    contractor["debarment_status"] = "DEBARRED"
    db.touch(contractor)
    touched_projects = []
    for assignment in derive.assignments_of_contractor(contractor["id"]):
        if assignment["status"] in ("INVITED", "ACTIVE"):
            assignment["status"] = "SUSPENDED"
            db.touch(assignment)
            if assignment["project_id"] not in touched_projects:
                touched_projects.append(assignment["project_id"])
    for project_id in touched_projects:
        derive.recompute_project(db.projects.get(project_id))
    return ok(s.contractor(contractor))


@bp.route("/contractors/<contractor_id>/staff", methods=["POST"])
def create_staff(contractor_id):
    authenticate(["PortalAdmin"])
    contractor = get_contractor(contractor_id)
    payload = v.body()
    full_name = v.req_string(payload, "full_name", min_len=1)
    capability = v.req_enum(payload, "capability", CAPABILITIES)
    notary = v.opt_string(payload, "notary_reference_number")

    row = db.base_row(versioned=False)
    row.update(
        {
            "contractor_id": contractor["id"],
            "full_name": full_name,
            "capability": capability,
            "notary_reference_number": notary,
        }
    )
    db.contractor_staff[row["id"]] = row
    return created(s.staff(row))


@bp.route("/contractors/<contractor_id>/staff", methods=["GET"])
def list_staff(contractor_id):
    authenticate(ALL_ROLES)
    contractor = get_contractor(contractor_id)
    limit, offset = pagination()
    capability = request.args.get("capability")

    def keep(row):
        if row["contractor_id"] != contractor["id"]:
            return False
        if capability is not None and row["capability"] != capability:
            return False
        return True

    return paginated(db.ordered(db.contractor_staff, keep), s.staff, limit, offset)
