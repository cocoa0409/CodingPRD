"""DocumentRecord endpoints (PRD 3.10): file with retention, purge."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_DRIVER_CARRIER_MISMATCH, ERR_RETENTION_NOT_EXPIRED,
    ERR_DOCUMENT_ALREADY_PURGED, ERR_AUDIT_HOLD_ACTIVE,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services import calc
from services.core import stamp_new, touch, OPEN_AUDIT_STATES
from validate import (
    get_body, req_str, opt_str, req_enum, req_datetime,
    require_path_resource, require_ref,
)
from util import new_id, parse_datetime, add_months, fmt_datetime

bp = Blueprint("documents", __name__)

ROLE = ["SafetyManager"]
DOCUMENT_TYPES = [
    "INSPECTION_REPORT", "DQ_FILE", "DRUG_TEST_RECORD", "ALCOHOL_TEST_RECORD",
    "ACCIDENT_REGISTER_ENTRY", "TRAINING_CERTIFICATE",
]


@bp.post("/safety/document-records")
def create_document():
    authorized(ROLE)
    body = get_body()
    # Stage 3: shape
    carrier_id = req_str(body, "carrier_id")
    document_type = req_enum(body, "document_type", DOCUMENT_TYPES)
    filed_at = req_datetime(body, "filed_at")
    driver_id = opt_str(body, "driver_id")
    # Stage 4: body FK existence in declared input order
    require_ref("carriers", carrier_id, "carrier_id")
    driver = None
    if driver_id is not None:
        driver = require_ref("drivers", driver_id, "driver_id")
    # Stage 9: driver-carrier membership
    if driver is not None and driver["carrier_id"] != carrier_id:
        raise_error(ERR_DRIVER_CARRIER_MISMATCH, "driver does not belong to the carrier")
    months = calc.RETENTION_MONTHS[document_type]
    retention_until = fmt_datetime(add_months(parse_datetime(filed_at), months))
    doc = stamp_new({
        "id": new_id(),
        "carrier_id": carrier_id,
        "driver_id": driver_id,
        "document_type": document_type,
        "filed_at": filed_at,
        "retention_months": months,
        "retention_until": retention_until,
        "status": "RETAINED",
    })
    db["document_records"][doc["id"]] = doc
    return success_object(public(doc), 201)


@bp.get("/safety/document-records")
def list_documents():
    return list_response("document_records", filters={
        "carrier_id": request.args.get("carrier_id"),
        "driver_id": request.args.get("driver_id"),
        "document_type": request.args.get("document_type"),
        "status": request.args.get("status"),
    })


@bp.get("/safety/document-records/<rid>")
def get_document(rid):
    return get_one("document_records", rid)


@bp.post("/safety/document-records/<rid>/purge")
def purge(rid):
    authorized(ROLE)
    doc = require_path_resource("document_records", rid)
    if doc["status"] == "RETAINED":
        raise_error(ERR_RETENTION_NOT_EXPIRED, "document retention has not expired")
    if doc["status"] == "PURGED":
        raise_error(ERR_DOCUMENT_ALREADY_PURGED, "document is already PURGED")
    # Stage 10: purge blocked while any audit case of the carrier is open
    for a in db["compliance_audit_cases"].values():
        if a["carrier_id"] == doc["carrier_id"] and a["status"] in OPEN_AUDIT_STATES:
            raise_error(ERR_AUDIT_HOLD_ACTIVE, "an open audit case blocks purging")
    doc["status"] = "PURGED"
    touch(doc)
    return success_object(public(doc))
