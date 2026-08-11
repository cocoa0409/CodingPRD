"""FingerprintSubmission endpoints."""
from flask import Blueprint

from db import store
from middleware import auth
from common import (
    body, get_or_404, fk_or_404, required, require_enum, new_entity, touch,
    serialize, list_page,
)
from response import success_obj, success_list
from errors import err_invalid_state
from timeutil import now

bp = Blueprint("fingerprints", __name__)

READ_ROLES = ("SystemOperator", "ComplianceOfficer", "RegistrationPrincipal", "Regulator")


@bp.post("/registration-desk/fingerprint-submissions")
def create_submission():
    auth("RegistrationPrincipal")
    data = body()
    req = fk_or_404(store.registration_requests, data.get("registration_request_id"))
    required(data, "registration_request_id")
    channel = require_enum(required(data, "submission_channel"), {"ELECTRONIC", "HARD_CARD"}, "submission_channel")
    fs = new_entity()
    fs.update({
        "registration_request_id": req["id"],
        "submission_channel": channel,
        "status": "SUBMITTED",
        "rejection_reason": None,
        "processed_at": None,
    })
    store.fingerprint_submissions[fs["id"]] = fs
    return success_obj(serialize(fs), 201)


@bp.get("/registration-desk/fingerprint-submissions")
def list_submissions():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(
        store.fingerprint_submissions,
        (
            ("registration_request_id", "registration_request_id", str),
            ("status", "status", str),
        ),
    )
    return success_list([serialize(s) for s in page], limit, offset, total)


@bp.get("/registration-desk/fingerprint-submissions/<id>")
def get_submission(id):
    auth(*READ_ROLES)
    fs = get_or_404(store.fingerprint_submissions, id)
    return success_obj(serialize(fs), 200)


@bp.post("/registration-desk/fingerprint-submissions/<id>/process")
def process_submission(id):
    auth("SystemOperator")
    fs = get_or_404(store.fingerprint_submissions, id)
    # Priority 5: a submission that has left SUBMITTED cannot be processed again.
    if fs["status"] != "SUBMITTED":
        raise err_invalid_state("only a SUBMITTED fingerprint submission may be processed")
    # Priority 9: outcome field shape.
    data = body()
    outcome = require_enum(required(data, "outcome"), {"CLEARED", "REJECTED"}, "outcome")
    fs["status"] = outcome
    fs["processed_at"] = now()
    if outcome == "REJECTED":
        fs["rejection_reason"] = data.get("rejection_reason")
    touch(fs)
    return success_obj(serialize(fs), 200)
