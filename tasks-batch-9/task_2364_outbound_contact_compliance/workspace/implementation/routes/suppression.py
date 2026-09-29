"""Do-not-call list membership (§3.4)."""

from flask import Blueprint

import lookup
import validation as v
from db import base_row, by_created_at, db, now_iso, public, touch
from derive import contact_by_phone, invalidate_internal_scrubs, rows
from errors import ApiError
from middleware import endpoint, payload
from response import created, listing, ok

bp = Blueprint("suppression", __name__)

LIST_TYPES = ("NATIONAL", "STATE", "INTERNAL")
SOURCES = ("FTC_DNC_DOWNLOAD", "STATE_REGISTRY", "CONSUMER_REQUEST", "LITIGATION_HOLD")
REMOVAL_REASONS = ("CONSENT_REINSTATED", "REGISTRY_DELISTING", "DATA_ERROR")
STATUSES = ("ACTIVE", "REMOVED")


@bp.post("/compliance/suppression-entries")
@endpoint(["ComplianceOfficer", "PlatformAdmin"])
def add_entry():
    body = payload()
    list_type = v.req_enum(body, "list_type", LIST_TYPES)
    phone_number = v.req_phone(body, "phone_number")
    if list_type == "STATE":
        state_code = v.req_state(body, "state_code")
    else:
        state_code = v.opt_state(body, "state_code")
    source = v.req_enum(body, "source", SOURCES)
    source_refreshed_at = v.req_datetime(body, "source_refreshed_at")

    row = base_row()
    row.update(
        {
            "list_type": list_type,
            "phone_number": phone_number,
            "state_code": state_code,
            "source": source,
            "source_refreshed_at": source_refreshed_at,
            "status": "ACTIVE",
            "removed_at": None,
            "removal_reason": None,
        }
    )
    db.suppression_entries[row["id"]] = row

    if list_type == "INTERNAL":
        contact = contact_by_phone(phone_number)
        if contact is not None:
            invalidate_internal_scrubs(contact["state_code"])
    return created(public(row))


@bp.get("/compliance/suppression-entries")
@endpoint(["ComplianceOfficer", "CampaignManager", "DialerOperator", "PlatformAdmin"])
def list_entries():
    limit, offset = v.pagination()
    list_type = v.query_enum("list_type", LIST_TYPES)
    phone_number = v.query_str("phone_number")
    state_code = v.query_str("state_code")
    status = v.query_enum("status", STATUSES)

    matches = rows("suppression_entries")
    if list_type is not None:
        matches = [r for r in matches if r["list_type"] == list_type]
    if phone_number is not None:
        matches = [r for r in matches if r["phone_number"] == phone_number]
    if state_code is not None:
        matches = [r for r in matches if r["state_code"] == state_code]
    if status is not None:
        matches = [r for r in matches if r["status"] == status]
    matches = by_created_at(matches)
    page, total = v.paginate(matches, limit, offset)
    return listing([public(r) for r in page], limit, offset, total)


@bp.post("/compliance/suppression-entries/<entry_id>/remove")
@endpoint(["ComplianceOfficer"])
def remove_entry(entry_id):
    body = payload()
    reason = v.req_enum(body, "removal_reason", REMOVAL_REASONS)
    entry = lookup.suppression_entry(entry_id)
    if entry["status"] != "ACTIVE":
        raise ApiError(
            "ERR_SUPPRESSION_ENTRY_STATE_INVALID", "Only an ACTIVE entry may be removed."
        )
    entry["status"] = "REMOVED"
    entry["removed_at"] = now_iso()
    entry["removal_reason"] = reason
    touch(entry)
    return ok(public(entry))
