"""RetainedDocument endpoints: holds, retention expiry, purge (PRD 3.9)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_DOCUMENT_NOT_PURGEABLE, ERR_AUDIT_HOLD_ACTIVE,
)
from middleware import get_caller, check_role
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.core import touch
from util import CLOCK, parse_date
from validate import (
    get_body, check_allowed, req_date, require_path_resource,
)

bp = Blueprint("retained_documents", __name__, url_prefix="/erate")


@bp.get("/retained-documents")
def list_documents():
    return list_collection("retained_documents", {
        "subject_type": request.args.get("subject_type"),
        "subject_id": request.args.get("subject_id"),
        "funding_cycle_id": request.args.get("funding_cycle_id"),
        "status": request.args.get("status"),
    })


@bp.get("/retained-documents/<rid>")
def get_document(rid):
    return get_one("retained_documents", rid)


@bp.post("/retained-documents/<rid>/place-hold")
def place_hold(rid):
    caller = get_caller()
    check_role(caller, ["Auditor"])
    body = get_body()
    check_allowed(body, {"hold_start_date", "hold_end_date"})
    hold_start = req_date(body, "hold_start_date")
    hold_end = req_date(body, "hold_end_date")
    if not parse_date(hold_end) > parse_date(hold_start):
        raise_error(ERR_INVALID_REQUEST,
                    "hold_end_date must fall strictly after hold_start_date")
    doc = require_path_resource("retained_documents", rid)
    if doc["status"] != "RETAINED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "document is not RETAINED")
    doc["hold_start_date"] = hold_start
    doc["hold_end_date"] = hold_end
    doc["status"] = "HELD"
    touch(doc)
    return success_object(public(doc))


@bp.post("/retained-documents/<rid>/release-hold")
def release_hold(rid):
    caller = get_caller()
    check_role(caller, ["Auditor"])
    body = get_body()
    check_allowed(body, set())
    doc = require_path_resource("retained_documents", rid)
    if doc["status"] != "HELD":
        raise_error(ERR_INVALID_STATE_TRANSITION, "document is not HELD")
    doc["hold_start_date"] = None
    doc["hold_end_date"] = None
    doc["status"] = "RETAINED"
    touch(doc)
    return success_object(public(doc))


@bp.post("/retained-documents/<rid>/purge")
def purge(rid):
    caller = get_caller()
    check_role(caller, ["Auditor"])
    body = get_body()
    check_allowed(body, set())
    doc = require_path_resource("retained_documents", rid)
    if doc["status"] not in ("RETAINED", "HELD"):
        raise_error(ERR_INVALID_STATE_TRANSITION, "document is not purgeable")
    today = CLOCK.today()
    # Purging requires the clock date strictly greater than retained_until_date;
    # purging ON the retention date is forbidden.
    if today <= parse_date(doc["retained_until_date"]):
        raise_error(ERR_DOCUMENT_NOT_PURGEABLE,
                    "the ten-year retention horizon has not lapsed")
    if doc["status"] == "HELD":
        # Half-open hold containment [hold_start_date, hold_end_date):
        # purging on hold_end_date itself is allowed.
        hold_start = parse_date(doc["hold_start_date"])
        hold_end = parse_date(doc["hold_end_date"])
        if hold_start <= today < hold_end:
            raise_error(ERR_AUDIT_HOLD_ACTIVE,
                        "the clock date is inside the document's audit hold interval")
    doc["status"] = "PURGED"
    touch(doc)
    return success_object(public(doc))
