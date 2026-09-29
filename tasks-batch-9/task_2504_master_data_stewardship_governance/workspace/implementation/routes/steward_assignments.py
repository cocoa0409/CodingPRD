"""Accountability assignments with half-open intervals and handover (PRD 3.1)."""

from flask import Blueprint

import db
import response
import validation as v
from auth import endpoint
from errors import fail

bp = Blueprint("steward_assignments", __name__)

ROLES = ("DATA_OWNER", "DATA_STEWARD", "CUSTODIAN")
STATUSES = ("ACTIVE", "SUPERSEDED")
READERS = ("GovernanceAdmin", "DataOwner", "DataSteward", "Auditor")


def _intersects(a_from, a_to, b_from, b_to):
    """Half-open [from, to) intersection; None means open-ended."""
    if a_to is not None and b_from >= a_to:
        return False
    if b_to is not None and a_from >= b_to:
        return False
    return True


@bp.post("/mdm/steward-assignments")
@endpoint("GovernanceAdmin")
def create_assignment():
    body = v.body()
    domain_id = v.req_str(body, "domain_id", 1)
    steward_id = v.req_str(body, "steward_id", 1)
    steward_role = v.req_enum(body, "steward_role", ROLES)
    effective_from = v.req_dt(body, "effective_from")
    effective_to = v.opt_dt(body, "effective_to")
    supersede = v.opt_bool(body, "supersede_incumbent", False)
    expected_version = v.req_int(body, "expected_domain_version")

    domain = db.resolve(db.store.domains, domain_id, "ERR_DOMAIN_NOT_FOUND")
    steward = db.resolve(db.store.stewards, steward_id, "ERR_STEWARD_NOT_FOUND")

    if expected_version != domain["version"]:
        fail("ERR_STALE_DOMAIN_VERSION",
             "expected_domain_version does not match the domain's current version.")

    if effective_to is not None and effective_to <= effective_from:
        fail("ERR_INVALID_INTERVAL", "effective_to must fall strictly after effective_from.")

    clashes = []
    for assignment in db.assignments_of(domain_id):
        if assignment["status"] != "ACTIVE":
            continue
        if assignment["steward_role"] != steward_role:
            continue
        if _intersects(assignment["effective_from"], assignment["effective_to"],
                       effective_from, effective_to):
            clashes.append(assignment)

    incumbent = None
    if clashes:
        if supersede:
            for candidate in clashes:
                if (candidate["effective_to"] is None
                        and candidate["effective_from"] < effective_from):
                    incumbent = candidate
                    break
        if incumbent is None or len(clashes) > 1:
            fail("ERR_ASSIGNMENT_OVERLAP",
                 "The accountability interval intersects an ACTIVE assignment for the same role.")

    assignment = db.create("StewardAssignment", {
        "domain_id": domain["id"],
        "steward_id": steward["id"],
        "steward_role": steward_role,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "ACTIVE",
        "superseded_at": None,
    })

    if incumbent is not None:
        incumbent["effective_to"] = effective_from
        incumbent["status"] = "SUPERSEDED"
        incumbent["superseded_at"] = db.now()
        db.bump(incumbent)

    db.store.steward_assignments[assignment["id"]] = assignment
    db.touch_domain(domain)
    return response.created(assignment)


@bp.get("/mdm/steward-assignments")
@endpoint(*READERS)
def list_assignments():
    limit, offset = v.pagination()
    domain_id = v.str_filter("domain_id")
    steward_id = v.str_filter("steward_id")
    steward_role = v.enum_filter("steward_role", ROLES)
    status = v.enum_filter("status", STATUSES)

    rows = db.ordered(db.store.steward_assignments)
    if domain_id is not None:
        rows = [r for r in rows if r["domain_id"] == domain_id]
    if steward_id is not None:
        rows = [r for r in rows if r["steward_id"] == steward_id]
    if steward_role is not None:
        rows = [r for r in rows if r["steward_role"] == steward_role]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.collection(rows, limit, offset)


@bp.get("/mdm/steward-assignments/<assignment_id>")
@endpoint(*READERS)
def read_assignment(assignment_id):
    assignment = db.resolve(db.store.steward_assignments, assignment_id,
                            "ERR_ASSIGNMENT_NOT_FOUND")
    return response.entity(assignment)
