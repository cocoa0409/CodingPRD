"""Contractor registration, reads and the vendor state machine (PRD §3.1)."""
from flask import Blueprint

import serialize
from core import (
    ADMIN, READ_ROLES, authenticate, body, db, fail, lookup, new_common, ok,
    ordered, paginate, parse_date, present, qfilter, touch,
)
from ladder import (
    assert_transition, assert_version, require_action, require_str,
    require_version_field,
)

bp = Blueprint("contractor", __name__)

CONTRACTOR_TRANSITIONS = {
    "SUSPEND": ("ACTIVE",),
    "REACTIVATE": ("SUSPENDED",),
}


@bp.post("/contractors")
def create_contractor():
    authenticate([ADMIN])
    payload = body()
    association = None
    if present(payload, "association_id"):
        association = lookup("associations", payload["association_id"])
    if association is None:
        fail("ERR_INVALID_REQUEST", "association_id is required.")
    require_str(payload, "company_name")
    require_str(payload, "insurance_expires_on")
    if parse_date(payload["insurance_expires_on"]) is None:
        fail("ERR_INVALID_REQUEST", "insurance_expires_on must be an ISO date (YYYY-MM-DD).")

    rec = new_common()
    rec.update({
        "association_id": association["id"],
        "company_name": payload["company_name"],
        "insurance_expires_on": payload["insurance_expires_on"],
        "status": "ACTIVE",
    })
    db.contractors[rec["id"]] = rec
    return ok(serialize.contractor(rec), 201)


@bp.get("/contractors/<contractor_id>")
def read_contractor(contractor_id):
    authenticate(READ_ROLES)
    return ok(serialize.contractor(lookup("contractors", contractor_id)))


@bp.get("/contractors")
def list_contractors():
    authenticate(READ_ROLES)
    rows = ordered(db.contractors)
    rows = qfilter(rows, "association_id")
    rows = qfilter(rows, "status")
    return paginate(rows, serialize.contractor)


@bp.post("/contractors/<contractor_id>/state")
def contractor_state(contractor_id):
    authenticate([ADMIN])
    contractor = lookup("contractors", contractor_id)
    payload = body()
    action = require_action(payload, tuple(CONTRACTOR_TRANSITIONS))
    expected = require_version_field(payload, "expected_contractor_version")
    assert_version(expected, contractor)
    assert_transition(contractor["status"], CONTRACTOR_TRANSITIONS, action)

    contractor["status"] = "SUSPENDED" if action == "SUSPEND" else "ACTIVE"
    touch(contractor)
    return ok(serialize.contractor(contractor))
