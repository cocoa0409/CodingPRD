"""CertificateOfCoverage endpoints (PRD §3.5): totalization lifecycle."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_COC_ALREADY_OPEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record, open_split_of, touch
from util import CLOCK, parse_date
from validate import get_body, req_date, req_field, req_str, require_fk, require_path_resource

bp = Blueprint("certificates", __name__)

OPEN_COC_STATES = {"REQUESTED", "SUBMITTED", "ISSUED"}


@bp.post("/mobility/certificates-of-coverage")
def create_certificate():
    authorized(["VendorCoordinator"])
    body = get_body()
    asg = require_fk("assignments", req_field(body, "assignment_id"), "assignment_id")
    application_ref = req_str(body, "application_ref")
    for c in db["certificates_of_coverage"].values():
        if c["assignment_id"] == asg["id"] and c["status"] in OPEN_COC_STATES:
            raise_error(ERR_COC_ALREADY_OPEN, "an open certificate of coverage already exists")
    rec = new_record("certificates_of_coverage", {
        "assignment_id": asg["id"],
        "application_ref": application_ref,
        "status": "REQUESTED",
        "valid_from": None,
        "valid_until": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/mobility/certificates-of-coverage/<rid>")
def get_certificate(rid):
    return get_one("certificates_of_coverage", rid)


@bp.get("/mobility/certificates-of-coverage")
def list_certificates():
    return list_response("certificates_of_coverage", {
        "assignment_id": request.args.get("assignment_id"),
    })


@bp.post("/mobility/certificates-of-coverage/<rid>/submit")
def submit_certificate(rid):
    authorized(["VendorCoordinator"])
    c = require_path_resource("certificates_of_coverage", rid)
    if c["status"] != "REQUESTED":
        raise_error(ERR_INVALID_STATE, "only a REQUESTED certificate can be submitted")
    c["status"] = "SUBMITTED"
    touch(c)
    return success_object(public(c))


@bp.post("/mobility/certificates-of-coverage/<rid>/mark-issued")
def mark_issued(rid):
    authorized(["VendorCoordinator"])
    body = get_body()
    c = require_path_resource("certificates_of_coverage", rid)
    valid_from = req_date(body, "valid_from")
    valid_until = req_date(body, "valid_until")
    if valid_until <= valid_from:
        raise_error(ERR_INVALID_REQUEST, "valid_until must be strictly after valid_from")
    if c["status"] not in ("SUBMITTED", "REJECTED"):
        raise_error(ERR_INVALID_STATE, "only a SUBMITTED or REJECTED certificate can be issued")
    c["status"] = "ISSUED"
    c["valid_from"] = valid_from.isoformat()
    c["valid_until"] = valid_until.isoformat()
    touch(c)
    # Issuance flips the split's exemption flag on.
    split = open_split_of(c["assignment_id"])
    if split is not None and not split["coc_exempt"]:
        split["coc_exempt"] = True
        touch(split)
    # A window already elapsed against the logical clock expires immediately
    # (coverage end is inclusive: expiry only once the clock date is past it).
    if CLOCK.today() > valid_until:
        from services.core import expire_certificate
        expire_certificate(c)
    return success_object(public(c))


@bp.post("/mobility/certificates-of-coverage/<rid>/mark-rejected")
def mark_rejected(rid):
    authorized(["VendorCoordinator"])
    c = require_path_resource("certificates_of_coverage", rid)
    if c["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "only a SUBMITTED certificate can be rejected")
    c["status"] = "REJECTED"
    touch(c)
    return success_object(public(c))
