"""CeuActivity reads and the two review branches (PRD 3.11)."""

from decimal import Decimal

from flask import Blueprint

import serialize
from db import DB, touch
from dispatch import api
from errors import ApiError
from middleware import (
    ROLE_CERTIFICANT,
    ROLE_ELIGIBILITY_REVIEWER,
    ROLE_PROGRAM_ADMIN,
    authenticate,
    ensure_body,
    opt_str,
    peek_body,
    req_enum,
)
from response import object_response
from services import derive, lookup

bp = Blueprint("ceu", __name__)

REVIEW_OUTCOMES = ("APPROVE", "REJECT", "SELECT_FOR_AUDIT")
AUDIT_OUTCOMES = ("VERIFY", "REVOKE")

ZERO = Decimal("0.00")


@bp.get("/ceu-activities/<activity_id>")
@api
def read_activity(activity_id):
    authenticate([ROLE_PROGRAM_ADMIN, ROLE_ELIGIBILITY_REVIEWER, ROLE_CERTIFICANT])
    return object_response(serialize.activity(lookup.activity(activity_id)))


@bp.post("/ceu-activities/<activity_id>/review")
@api
def review_activity(activity_id):
    actor = authenticate([ROLE_ELIGIBILITY_REVIEWER])
    activity = lookup.activity(activity_id)
    body = ensure_body(peek_body())
    outcome = req_enum(body, "outcome", REVIEW_OUTCOMES)
    review_note = opt_str(body, "review_note")

    cycle = lookup.cycle_of_activity(activity)
    certificant = lookup.certificant_of_cycle(cycle)

    # Layer 12, first for the owning cycle and then for the activity itself.
    if cycle["status"] not in ("OPEN", "SATISFIED"):
        raise ApiError("ERR_INVALID_STATE")
    if outcome == "SELECT_FOR_AUDIT":
        if activity["status"] not in ("SUBMITTED", "APPROVED"):
            raise ApiError("ERR_INVALID_STATE")
    elif activity["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")

    # Layer 16.
    if certificant["status"] != "ACTIVE":
        raise ApiError("ERR_CERTIFICANT_NOT_ACTIVE")

    activity["reviewer_user_id"] = actor.user_id
    if review_note is not None:
        activity["review_note"] = review_note

    if outcome == "APPROVE":
        activity["status"] = "APPROVED"
        activity["counted"] = True
    elif outcome == "REJECT":
        activity["status"] = "REJECTED"
        activity["counted"] = False
        activity["credits_counted"] = ZERO
    else:
        # Arriving from APPROVED this compensates the earlier grant.
        activity["status"] = "AUDIT_SELECTED"
        activity["counted"] = False
        activity["credits_counted"] = ZERO
    touch(activity)

    program = lookup.program_of_certificant(certificant)
    derive.reconcile_cycle(cycle, program)
    derive.refresh_certificant_projection(certificant)
    return object_response(serialize.activity(activity))


@bp.post("/ceu-activities/<activity_id>/audit-verify")
@api
def audit_verify_activity(activity_id):
    actor = authenticate([ROLE_ELIGIBILITY_REVIEWER])
    activity = lookup.activity(activity_id)
    body = ensure_body(peek_body())
    outcome = req_enum(body, "outcome", AUDIT_OUTCOMES)
    review_note = opt_str(body, "review_note")

    # Layer 12.
    if activity["status"] != "AUDIT_SELECTED":
        raise ApiError("ERR_INVALID_STATE")

    # Layer 19: the verifier may not be the reviewer who selected the claim.
    if activity["reviewer_user_id"] is not None and activity["reviewer_user_id"] == actor.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    activity["audit_verifier_user_id"] = actor.user_id
    if review_note is not None:
        activity["review_note"] = review_note

    if outcome == "VERIFY":
        activity["status"] = "VERIFIED"
        activity["counted"] = True
    else:
        activity["status"] = "REVOKED"
        activity["counted"] = False
        activity["credits_counted"] = ZERO
    touch(activity)

    cycle = lookup.cycle_of_activity(activity)
    certificant = DB.certificants[cycle["certificant_id"]]
    program = lookup.program_of_certificant(certificant)
    derive.reconcile_cycle(cycle, program)
    derive.refresh_certificant_projection(certificant)
    return object_response(serialize.activity(activity))
