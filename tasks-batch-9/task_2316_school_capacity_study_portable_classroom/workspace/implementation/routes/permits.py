"""Permitting: one fork, two joins (PRD 3.7)."""

from flask import Blueprint

import constants as C
from clock import clock
from db import db, public, touch
from errors import fail
from middleware import require
from response import ok
from routes.common import list_response
from services import cascade
from validation import get_body, lookup, need_enum, need_string, opt_string

bp = Blueprint("permits", __name__)


@bp.get("/permits/<permit_id>")
def read_permit(permit_id):
    require(C.ALL_EXCEPT_CREW_LEAD)
    return ok(public(lookup("permit", permit_id)))


@bp.get("/permits")
def list_permits():
    require(C.ALL_EXCEPT_CREW_LEAD)
    return list_response(db.permits, ["placement_request_id", "permit_type", "status"])


@bp.post("/permits/<permit_id>/decision")
def decide_permit(permit_id):
    require(["BuildingOfficial"])
    permit = lookup("permit", permit_id)
    body = get_body()
    decision = need_enum(body, "decision", C.PERMIT_DECISIONS)
    correction_note = opt_string(body, "correction_note", None, 1, 2000)
    if decision == "CORRECTIONS_REQUIRED" and correction_note is None:
        need_string(body, "correction_note", 1, 2000)
    # rule 10
    if permit["status"] != "SUBMITTED":
        fail("ERR_PERMIT_STATE_INVALID",
             "A permit in %s cannot be decided." % permit["status"])
    req = db.requests[permit["placement_request_id"]]
    # rule 24
    if req["status"] != "PERMIT_PENDING":
        fail("ERR_PERMIT_REQUEST_NOT_PENDING",
             "The owning placement request is %s, not PERMIT_PENDING." % req["status"])

    siblings = [
        p for p in db.permits.values()
        if p["placement_request_id"] == req["id"] and p["id"] != permit["id"]
    ]

    if decision == "CORRECTIONS_REQUIRED":
        permit["status"] = "CORRECTIONS_REQUIRED"
        permit["correction_note"] = correction_note
        touch(permit)
        return ok(public(permit))

    if decision == "DENIED":
        permit["status"] = "DENIED"
        touch(permit)
        cascade.permit_join_denied(req)
        return ok(public(permit))

    # APPROVED: rule 40 is evaluated before any mutation when this approval
    # would be the last outstanding permit of the request.
    joins = all(p["status"] == "APPROVED" for p in siblings)
    if joins:
        budget = db.budgets.get(req["capital_budget_id"])
        estimate = req["estimated_relocation_cost_cents"]
        if budget is not None and budget["uncommitted_cents"] < estimate:
            fail("ERR_BUDGET_INSUFFICIENT",
                 "The appropriation has %d uncommitted cents; %d are needed."
                 % (budget["uncommitted_cents"], estimate))

    permit["status"] = "APPROVED"
    permit["approved_on"] = clock.iso()
    touch(permit)

    if joins:
        cascade.permit_join_approved(req)
    return ok(public(permit))


@bp.post("/permits/<permit_id>/resubmit")
def resubmit_permit(permit_id):
    require(["PermitCoordinator"])
    permit = lookup("permit", permit_id)
    body = get_body()
    need_string(body, "correction_response", 1, 2000)
    # rule 10
    if permit["status"] != "CORRECTIONS_REQUIRED":
        fail("ERR_PERMIT_STATE_INVALID",
             "A permit in %s cannot be refiled." % permit["status"])
    req = db.requests[permit["placement_request_id"]]
    # rule 24
    if req["status"] != "PERMIT_PENDING":
        fail("ERR_PERMIT_REQUEST_NOT_PENDING",
             "The owning placement request is %s, not PERMIT_PENDING." % req["status"])

    permit["status"] = "SUBMITTED"
    permit["review_cycle_count"] = permit["review_cycle_count"] + 1
    permit["submitted_on"] = clock.iso()
    touch(permit)
    return ok(public(permit))
