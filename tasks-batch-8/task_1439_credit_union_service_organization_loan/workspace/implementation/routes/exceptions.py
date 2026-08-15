"""Documentation exceptions and the cure loop (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import serialize as ser
from errors import (
    not_found, invalid_state, raise_err,
    ERR_NOT_OWNER, ERR_CURE_EXPIRED,
)
from middleware import (
    auth_context, require_role, body, req_str, req_enum, req_bool, touch,
    paginate, ALL_ROLES,
)
from response import success
from services.cascade import agreement_of_certificate, certificate_maybe_reactivate

bp = Blueprint("exceptions", __name__)

EXCEPTION_TYPES = {"MISSING_NOTE", "STALE_APPRAISAL", "INSURANCE_LAPSE", "UCC_FILING_GAP"}


def _get_exception(eid):
    e = db.exceptions.get(eid)
    if e is None:
        not_found("DocumentationException")
    return e


@bp.post("/network/exceptions")
def create_exception():
    uid, role = auth_context()
    require_role(role, {"BuyerUser"})
    b = body()
    cid = b.get("certificate_id")
    if cid is not None and cid not in db.certificates:
        not_found("ParticipationCertificate")
    cert = db.certificates.get(cid) if cid is not None else None
    # ownership (priority 3): buyer flags an exception on their own certificate
    if cert is not None and cert["buyer_id"] != uid:
        raise_err(ERR_NOT_OWNER, "BuyerUser must own the certificate")
    if cid is None:
        raise_err_missing("certificate_id")
    exc_type = req_enum(b, "exception_type", EXCEPTION_TYPES)
    description = req_str(b, "description")
    # state (priority 7): the create cascade is ACTIVE -> EXCEPTION. PRD §3.6
    # contemplates multiple concurrent exceptions per certificate ("no OTHER
    # exception of the certificate remains in OPEN, CURE_SUBMITTED, REJECTED,
    # or ESCALATED"), so flagging must also be accepted when the certificate
    # is already in EXCEPTION.
    if cert["status"] not in ("ACTIVE", "EXCEPTION"):
        invalid_state("Documentation exceptions can only be flagged on an ACTIVE or EXCEPTION certificate")
    agreement = agreement_of_certificate(cert)
    now = db.clock_now()
    e = db.insert("exception", {
        "certificate_id": cid,
        "exception_type": exc_type,
        "description": description,
        "detected_at": now,
        "cure_deadline": now + timedelta(days=agreement["cure_period_days"]),
        "status": "OPEN",
        "cure_notes": None,
        "cure_attempt_count": 0,
    })
    cert["status"] = "EXCEPTION"
    touch("certificate", cert)
    return success(ser.doc_exception(e), 201)


def raise_err_missing(field):
    from errors import ERR_INVALID_REQUEST
    raise_err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)


@bp.get("/network/exceptions/<eid>")
def get_exception(eid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    return success(ser.doc_exception(_get_exception(eid)))


@bp.get("/network/exceptions")
def list_exceptions():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = list(db.exceptions.values())
    cid = request.args.get("certificate_id")
    if cid is not None:
        items = [e for e in items if e["certificate_id"] == cid]
    st = request.args.get("status")
    if st is not None:
        items = [e for e in items if e["status"] == st]
    page, meta = paginate(items, ser.doc_exception)
    return success(page, 200, meta)


@bp.post("/network/exceptions/<eid>/submit-cure")
def submit_cure(eid):
    uid, role = auth_context()
    require_role(role, {"OriginatorUser"})
    e = _get_exception(eid)
    cert = db.certificates[e["certificate_id"]]
    agreement = agreement_of_certificate(cert)
    if agreement["originator_id"] != uid:
        raise_err(ERR_NOT_OWNER, "OriginatorUser must own the agreement behind the certificate")
    notes = req_str(body(), "cure_notes")
    if e["status"] not in ("OPEN", "REJECTED"):
        invalid_state("Exception must be OPEN or REJECTED to submit a cure")
    # cure deadline is inclusive
    if db.clock_now() > e["cure_deadline"]:
        raise_err(ERR_CURE_EXPIRED, "Cure submission is past the cure_deadline")
    e["status"] = "CURE_SUBMITTED"
    e["cure_notes"] = notes
    e["cure_attempt_count"] += 1
    touch("exception", e)
    return success(ser.doc_exception(e))


@bp.post("/network/exceptions/<eid>/verify-cure")
def verify_cure(eid):
    uid, role = auth_context()
    require_role(role, {"BuyerUser"})
    e = _get_exception(eid)
    cert = db.certificates[e["certificate_id"]]
    if cert["buyer_id"] != uid:
        raise_err(ERR_NOT_OWNER, "BuyerUser must own the certificate")
    accept = req_bool(body(), "accept")
    if e["status"] != "CURE_SUBMITTED":
        invalid_state("Exception must be CURE_SUBMITTED to verify a cure")
    if accept:
        e["status"] = "CURED"
        touch("exception", e)
        certificate_maybe_reactivate(cert)
    else:
        e["status"] = "REJECTED"
        touch("exception", e)
    return success(ser.doc_exception(e))
