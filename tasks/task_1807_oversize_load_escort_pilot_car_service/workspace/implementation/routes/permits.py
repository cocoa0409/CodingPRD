"""Permit issuance."""

from flask import Blueprint, request

import db
from errors import (
    ERR_PERMIT_NOT_FOUND,
    ERR_PERMIT_INVALID_STATE,
    ERR_JOB_INVALID_STATE,
    raise_err,
)
from middleware import require_roles
from mutate import mark
from response import success_object
from serializers import ser_permit
from services import cascade
from util import body_json

bp = Blueprint("permits", __name__)


@bp.post("/permits/<id>/issue")
def issue_permit(id):
    require_roles("Dispatcher")
    body_json(request)
    permit = db.permits.get(id)
    if permit is None:
        raise_err(ERR_PERMIT_NOT_FOUND, f"Permit {id} not found")
    if permit["permit_status"] != "APPLIED":
        raise_err(ERR_PERMIT_INVALID_STATE, "Issuance requires the permit to be APPLIED")
    leg = db.legs.get(permit["leg_id"])
    job = cascade.job_of_leg(leg) if leg else None
    if job is None or job["job_status"] not in ("BOOKED", "CLEARED", "SCHEDULED"):
        raise_err(ERR_JOB_INVALID_STATE,
                  "Permits may only be issued while the leg's job is BOOKED, CLEARED, or SCHEDULED")
    permit["permit_status"] = "ISSUED"
    permit["issued_at"] = db.now()
    mark(permit)
    cascade.reevaluate_leg_and_job_gates(leg, promote_from=("DETERMINED",))
    return success_object(ser_permit(permit))
