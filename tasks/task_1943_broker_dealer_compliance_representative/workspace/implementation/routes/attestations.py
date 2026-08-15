"""Attestation endpoints (PRD 3.8): entity-backed rep self-attestation."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ATTESTATION_DEADLINE_PASSED,
    ERR_ATTESTATION_NOT_PENDING,
    ERR_MEETING_NOT_HELD,
    ERR_NOT_ATTESTATION_OWNER,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import public, touch
from util import clock_ts, parse_date, today
from validate import require_path_resource

bp = Blueprint("attestations", __name__)


@bp.get("/attestations")
def list_attestations():
    return list_response("attestations", filters={
        "meeting_id": request.args.get("meeting_id"),
        "rep_id": request.args.get("rep_id"),
        "status": request.args.get("status"),
    })


@bp.get("/attestations/<rid>")
def get_attestation(rid):
    return get_one("attestations", rid)


@bp.post("/attestations/<rid>/attest")
def attest(rid):
    caller = authorized(["RegisteredRep"])
    att = require_path_resource("attestations", rid)
    # Entity-backed ownership carries its own code (PRD 2.10 step 2)
    if caller.user_id != att["rep_id"]:
        raise_error(ERR_NOT_ATTESTATION_OWNER,
                    "a representative may attest only their own attestations")
    # State
    if att["status"] != "PENDING":
        raise_error(ERR_ATTESTATION_NOT_PENDING,
                    "attest is allowed only on a PENDING attestation")
    # Temporal: attestation permitted while current date <= attest_deadline
    # (the deadline day itself is still attestable)
    if today() > parse_date(att["attest_deadline"]):
        raise_error(ERR_ATTESTATION_DEADLINE_PASSED,
                    "the attestation deadline has passed")
    # Cross-entity constraint: the parent meeting must be HELD
    meeting = db["meetings"].get(att["meeting_id"])
    if meeting is None or meeting["status"] != "HELD":
        raise_error(ERR_MEETING_NOT_HELD,
                    "the parent meeting must be HELD before attesting")
    att["attested_at"] = clock_ts()
    att["status"] = "ATTESTED"
    touch(att)
    return success_object(public(att))
