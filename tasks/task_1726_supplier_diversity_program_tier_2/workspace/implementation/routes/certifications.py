"""Certification review state machine (PRD 3.2)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_CERT_NOT_REVIEWABLE,
    ERR_CERT_WINDOW_EXPIRED,
    ERR_CERT_WINDOW_OVERLAP,
    ERR_SOD_VIOLATION,
)
from middleware import authorized
from response import success_object
from services.core import (
    touch,
    pub_certification,
    refresh_diverse_eligible,
    refresh_risk_scores,
    recompute_events_for_supplier,
)
from util import clock_date
from validate import get_body, req_str, req_date, get_resource

bp = Blueprint("certifications", __name__)

REVIEWERS = ["DiversityAdmin", "DiversityAnalyst"]


def _supplier_of(cert):
    return db["suppliers"].get(cert["supplier_id"])


@bp.route("/api/v1/certifications/<rid>/begin-review", methods=["POST"])
def begin_review(rid):
    authorized(REVIEWERS)
    cert = get_resource("certifications", rid)
    if cert["status"] != "SUBMITTED":
        raise_error(ERR_CERT_NOT_REVIEWABLE, "begin-review requires status SUBMITTED")
    cert["status"] = "UNDER_REVIEW"
    touch(cert)
    return success_object(pub_certification(cert))


@bp.route("/api/v1/certifications/<rid>/request-info", methods=["POST"])
def request_info(rid):
    authorized(REVIEWERS)
    cert = get_resource("certifications", rid)
    if cert["status"] != "UNDER_REVIEW":
        raise_error(ERR_CERT_NOT_REVIEWABLE, "request-info requires status UNDER_REVIEW")
    body = get_body()
    note = req_str(body, "note")
    cert["status"] = "INFO_REQUESTED"
    cert["review_note"] = note
    touch(cert)
    # CONSERVATIVE risk variant carries an info-requested term (PRD 3.10)
    supplier = _supplier_of(cert)
    if supplier is not None and refresh_risk_scores(supplier):
        touch(supplier)
    return success_object(pub_certification(cert))


@bp.route("/api/v1/certifications/<rid>/resubmit", methods=["POST"])
def resubmit(rid):
    caller = authorized(REVIEWERS)
    cert = get_resource("certifications", rid)
    if cert["status"] != "INFO_REQUESTED":
        raise_error(ERR_CERT_NOT_REVIEWABLE, "resubmit requires status INFO_REQUESTED")
    body = get_body()
    certificate_number = req_str(body, "certificate_number")
    valid_from = req_date(body, "valid_from")
    valid_to = req_date(body, "valid_to")
    if valid_to < valid_from:
        raise_error(ERR_INVALID_REQUEST, "valid_to must be on or after valid_from")
    cert["certificate_number"] = certificate_number
    cert["valid_from"] = valid_from
    cert["valid_to"] = valid_to
    cert["status"] = "SUBMITTED"
    cert["submitted_by_user_id"] = caller.user_id
    touch(cert)
    return success_object(pub_certification(cert))


@bp.route("/api/v1/certifications/<rid>/verify", methods=["POST"])
def verify(rid):
    caller = authorized(REVIEWERS)
    cert = get_resource("certifications", rid)
    # State tier: review action attempted from an undefined state.
    if cert["status"] != "UNDER_REVIEW":
        raise_error(ERR_CERT_NOT_REVIEWABLE, "verify requires status UNDER_REVIEW")
    # Segregation-of-duties tier: verifier != submitter.
    if caller.user_id == cert["submitted_by_user_id"]:
        raise_error(ERR_SOD_VIOLATION, "verifier must differ from submitter")
    # Overlap tier: no other VERIFIED/EXPIRED same-type cert with an
    # overlapping closed [valid_from, valid_to] window (boundary day counts).
    for other in db["certifications"].values():
        if other["id"] == cert["id"]:
            continue
        if other["supplier_id"] != cert["supplier_id"]:
            continue
        if other["cert_type"] != cert["cert_type"]:
            continue
        if other["status"] not in ("VERIFIED", "EXPIRED"):
            continue
        if other["valid_from"] <= cert["valid_to"] and cert["valid_from"] <= other["valid_to"]:
            raise_error(
                ERR_CERT_WINDOW_OVERLAP,
                "overlapping VERIFIED/EXPIRED certification window for the same type",
            )
    # Temporal tier: window must not already be expired at the clock date.
    if cert["valid_to"] < clock_date():
        raise_error(ERR_CERT_WINDOW_EXPIRED, "certification window has expired")
    cert["status"] = "VERIFIED"
    cert["verified_by_user_id"] = caller.user_id
    touch(cert)
    supplier = _supplier_of(cert)
    if supplier is not None:
        changed = False
        # First verified certification activates a REGISTERED supplier.
        if supplier["status"] == "REGISTERED":
            supplier["status"] = "ACTIVE"
            changed = True
        if refresh_diverse_eligible(supplier):
            changed = True
            recompute_events_for_supplier(supplier["id"])
        if changed:
            touch(supplier)
    return success_object(pub_certification(cert))


@bp.route("/api/v1/certifications/<rid>/reject", methods=["POST"])
def reject(rid):
    caller = authorized(REVIEWERS)
    cert = get_resource("certifications", rid)
    if cert["status"] != "UNDER_REVIEW":
        raise_error(ERR_CERT_NOT_REVIEWABLE, "reject requires status UNDER_REVIEW")
    if caller.user_id == cert["submitted_by_user_id"]:
        raise_error(ERR_SOD_VIOLATION, "rejecter must differ from submitter")
    body = get_body()
    reason = req_str(body, "reason")
    cert["status"] = "REJECTED"
    cert["review_note"] = reason
    touch(cert)
    return success_object(pub_certification(cert))
