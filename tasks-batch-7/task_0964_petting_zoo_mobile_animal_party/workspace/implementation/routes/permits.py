"""Top-level permit transitions: submit / decide (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint

from db import store
from errors import (
    raise_err, ERR_PERMIT_NOT_FOUND, ERR_INVALID_STATE,
    ERR_PERMIT_LEAD_TIME, ERR_SEGREGATION_OF_DUTY,
)
from middleware import require
from response import ok
from serializers import ser_permit
from util import body_json, bump, now, v_enum, v_str

bp = Blueprint("permits", __name__)

PERMIT_LEAD_HOURS = 336  # fourteen full days


@bp.post("/petting-zoo/permits/<permit_id>/submit")
def submit_permit(permit_id):
    role, uid = require({"Coordinator"})
    permit = store.permits.get(permit_id)
    if permit is None:
        raise_err(ERR_PERMIT_NOT_FOUND, "Permit not found")
    if permit["status"] not in ("DRAFT", "DENIED"):
        raise_err(ERR_INVALID_STATE, "Permit cannot be submitted from state %s" % permit["status"])
    booking = store.bookings[permit["booking_id"]]
    if booking["start_time"] - now() < timedelta(hours=PERMIT_LEAD_HOURS):
        raise_err(ERR_PERMIT_LEAD_TIME, "Permit submitted less than 336h before event start")
    permit["status"] = "SUBMITTED"
    permit["submitted_by_user_id"] = uid
    permit["denial_reason"] = None  # cleared on resubmission
    bump(permit)
    return ok(ser_permit(permit))


@bp.post("/petting-zoo/permits/<permit_id>/decide")
def decide_permit(permit_id):
    role, uid = require({"ComplianceOfficer"})
    body = body_json()
    decision = v_enum(body, "decision", {"ISSUED", "DENIED"})
    denial_reason = v_str(body, "denial_reason", required=False, default=None)
    permit = store.permits.get(permit_id)
    if permit is None:
        raise_err(ERR_PERMIT_NOT_FOUND, "Permit not found")
    if permit["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Permit is not SUBMITTED")
    # Segregation of duties: decider must differ from the submitter.
    if uid == permit["submitted_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTY,
                  "Permit decider must differ from the permit submitter")
    permit["status"] = decision
    permit["decided_by_user_id"] = uid
    if decision == "DENIED":
        permit["denial_reason"] = denial_reason
    bump(permit)
    return ok(ser_permit(permit))
