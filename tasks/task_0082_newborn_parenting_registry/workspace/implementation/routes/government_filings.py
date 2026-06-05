"""GovernmentFiling resource (PRD §3.7)."""

from flask import Blueprint, request

import db
import services
from errors import (
    APIError,
    ERR_BIRTH_CERT_PREREQUISITE,
    ERR_LEGAL_NAME_REQUIRED,
    invalid_request,
    invalid_state,
    not_found,
)
from helpers import (
    get_body,
    optional_field,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("government_filings", __name__)

FILING_TYPES = {"BIRTH_CERTIFICATE", "SSN_APPLICATION"}
FILING_STATUSES = {"PENDING", "SUBMITTED", "ACCEPTED", "REJECTED", "LATE_FLAGGED", "CANCELLED"}
ACK_OUTCOMES = {"ACCEPTED", "REJECTED"}


def _get_filing(filing_id):
    f = db.government_filings.get(filing_id)
    if f is None:
        raise not_found("Government filing not found.")
    return f


def _refresh_deadline(filing):
    newborn = db.newborns.get(filing["newborn_id"])
    if newborn is not None:
        filing["filing_deadline"] = services.compute_filing_deadline(
            newborn["birth_datetime"], filing["filing_type"])


@bp.post("/government-filings")
def create_filing():
    require_roles("VitalRecordsOfficer")
    body = get_body()
    newborn_id = require_field(body, "newborn_id", str)
    newborn = db.newborns.get(newborn_id)
    if newborn is None:
        raise not_found("newborn_id does not resolve to a newborn.")
    filing_type = require_field(body, "filing_type", str)
    require_enum(filing_type, "filing_type", FILING_TYPES)
    filing_deadline = services.compute_filing_deadline(newborn["birth_datetime"], filing_type)
    row = {
        "id": db.new_id(),
        "newborn_id": newborn_id,
        "filing_type": filing_type,
        "filing_deadline": filing_deadline,
        "submitted_at": None,
        "acknowledged_at": None,
        "reference_number": None,
        "status": "PENDING",
    }
    db.stamp_create(row)
    db.government_filings[row["id"]] = row
    return ok_object(db.public(row), 201)


@bp.get("/government-filings/<filing_id>")
def get_filing(filing_id):
    require_roles("VitalRecordsOfficer", "RegistrySupervisor")
    f = _get_filing(filing_id)
    _refresh_deadline(f)
    return ok_object(db.public(f))


@bp.get("/government-filings")
def list_filings():
    require_roles("VitalRecordsOfficer", "RegistrySupervisor")
    limit, offset = parse_pagination()
    newborn_id = request.args.get("newborn_id")
    filing_type = request.args.get("filing_type")
    status = request.args.get("status")
    rows = list(db.government_filings.values())
    if newborn_id is not None:
        rows = [r for r in rows if r["newborn_id"] == newborn_id]
    if filing_type is not None:
        require_enum(filing_type, "filing_type", FILING_TYPES)
        rows = [r for r in rows if r["filing_type"] == filing_type]
    if status is not None:
        require_enum(status, "status", FILING_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array([db.public(r) for r in page], limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.post("/government-filings/<filing_id>/submit")
def submit_filing(filing_id):
    require_roles("VitalRecordsOfficer")
    f = _get_filing(filing_id)

    # State (priority 5): submit/resubmit defined from PENDING or REJECTED.
    if f["status"] not in ("PENDING", "REJECTED"):
        raise invalid_state("Only a PENDING or REJECTED filing may be submitted.")

    newborn = db.newborns.get(f["newborn_id"])

    # Legal-name requirement (priority 11).
    if newborn is None or not newborn.get("legal_name"):
        raise APIError(ERR_LEGAL_NAME_REQUIRED,
                       "Newborn.legal_name must be non-null to submit a filing.", 422)

    # Birth-cert prerequisite (priority 9) for SSN_APPLICATION.
    if f["filing_type"] == "SSN_APPLICATION":
        has_cert = any(
            o["newborn_id"] == f["newborn_id"]
            and o["filing_type"] == "BIRTH_CERTIFICATE"
            and o["status"] in ("SUBMITTED", "LATE_FLAGGED", "ACCEPTED")
            for o in db.government_filings.values()
        )
        if not has_cert:
            raise APIError(ERR_BIRTH_CERT_PREREQUISITE,
                           "SSN application requires the birth-certificate filing to be "
                           "at least submitted.", 422)

    _refresh_deadline(f)
    now_iso = db.current_utc_iso()
    f["submitted_at"] = now_iso
    actor = request.headers.get("X-User-Role")

    # Lateness: submitted_at strictly after filing_deadline.
    resubmit = (f["status"] == "REJECTED")
    if not resubmit and db.parse_iso(now_iso) > db.parse_iso(f["filing_deadline"]):
        f["status"] = "LATE_FLAGGED"
        db.stamp_update(f)
        services.append_audit("FILING_LATE_FLAGGED", actor, f["newborn_id"],
                              {"government_filing_id": filing_id})
    else:
        f["status"] = "SUBMITTED"
        db.stamp_update(f)
        services.append_audit("FILING_SUBMITTED", actor, f["newborn_id"],
                              {"government_filing_id": filing_id})
    return ok_object(db.public(f))


@bp.post("/government-filings/<filing_id>/acknowledge")
def acknowledge_filing(filing_id):
    require_roles("VitalRecordsOfficer")
    f = _get_filing(filing_id)
    body = get_body()
    outcome = require_field(body, "outcome", str)
    require_enum(outcome, "outcome", ACK_OUTCOMES)
    reference_number = optional_field(body, "reference_number", str, default=None)

    if f["status"] not in ("SUBMITTED", "LATE_FLAGGED"):
        raise invalid_state("Only a SUBMITTED or LATE_FLAGGED filing may be acknowledged.")

    if outcome == "ACCEPTED":
        if not reference_number:
            raise invalid_request("reference_number is required to accept a filing.")
        f["reference_number"] = reference_number
        f["acknowledged_at"] = db.current_utc_iso()
        f["status"] = "ACCEPTED"
    else:  # REJECTED
        f["acknowledged_at"] = db.current_utc_iso()
        f["status"] = "REJECTED"
    db.stamp_update(f)
    return ok_object(db.public(f))


@bp.post("/government-filings/<filing_id>/cancel")
def cancel_filing(filing_id):
    require_roles("VitalRecordsOfficer")
    f = _get_filing(filing_id)
    if f["status"] != "PENDING":
        raise invalid_state("Only a PENDING filing may be cancelled.")
    f["status"] = "CANCELLED"
    db.stamp_update(f)
    return ok_object(db.public(f))
