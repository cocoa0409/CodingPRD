"""Complaint intake, adjudication and pattern clustering (§3.9)."""

from flask import Blueprint

import calculations as calc
import lookup
import validation as v
from db import base_row, by_created_at, db, now_iso, public, touch
from derive import (
    consents_of_contact,
    ensure_internal_suppression,
    recompute_clusters,
    recompute_contact,
    rows,
    touch_contact,
    verified_attempt_count,
)
from errors import ApiError
from middleware import endpoint, payload
from response import created, listing, ok
from util import pct

bp = Blueprint("complaints", __name__)

SOURCES = ("DIRECT", "STATE_AG", "FTC", "LITIGATION")
VIOLATION_TYPES = ("NO_CONSENT", "DNC_VIOLATION", "TIME_WINDOW", "ABANDONMENT", "RECORDING_CONSENT")
STATUSES = ("OPEN", "SUBSTANTIATED", "DISMISSED")
READ_ROLES = ["ComplianceOfficer", "CampaignManager", "PlatformAdmin", "Consumer"]


@bp.post("/compliance/complaints")
@endpoint(["ComplianceOfficer", "DialerOperator", "Consumer"])
def intake_complaint():
    body = payload()
    contact_id = v.req_str(body, "contact_id")
    campaign_id = v.opt_str(body, "campaign_id")
    source = v.req_enum(body, "source", SOURCES)
    alleged_violation_type = v.req_enum(body, "alleged_violation_type", VIOLATION_TYPES)
    narrative = v.req_str(body, "narrative")
    litigation_flag = v.opt_bool(body, "litigation_flag", False)

    contact = lookup.contact(contact_id)
    if campaign_id is not None:
        lookup.campaign(campaign_id)

    recompute_contact(contact)
    row = base_row()
    row.update(
        {
            "contact_id": contact_id,
            "campaign_id": campaign_id,
            "source": source,
            "alleged_violation_type": alleged_violation_type,
            "narrative": narrative,
            "litigation_flag": litigation_flag,
            "received_at": now_iso(),
            "status": "OPEN",
            "provisional_risk_score": pct(
                calc.provisional_risk_score(
                    source, alleged_violation_type, contact["attempts_charged"]
                )
            ),
            "adjudicated_risk_score": None,
            "verified_attempt_count": None,
            "exposure_cents": None,
            "willful": None,
            "finding_note": None,
            "dismissal_note": None,
            "pattern_cluster_size": 1,
        }
    )
    db.complaints[row["id"]] = row
    recompute_clusters(row, skip_anchor_touch=True)
    return created(public(row))


@bp.get("/compliance/complaints/<complaint_id>")
@endpoint(READ_ROLES)
def read_complaint(complaint_id):
    return ok(public(lookup.complaint(complaint_id)))


@bp.get("/compliance/complaints")
@endpoint(READ_ROLES)
def list_complaints():
    limit, offset = v.pagination()
    contact_id = v.query_str("contact_id")
    campaign_id = v.query_str("campaign_id")
    status = v.query_enum("status", STATUSES)
    litigation_flag = v.query_bool("litigation_flag")
    alleged_violation_type = v.query_enum("alleged_violation_type", VIOLATION_TYPES)

    matches = rows("complaints")
    if contact_id is not None:
        matches = [c for c in matches if c["contact_id"] == contact_id]
    if campaign_id is not None:
        matches = [c for c in matches if c["campaign_id"] == campaign_id]
    if status is not None:
        matches = [c for c in matches if c["status"] == status]
    if litigation_flag is not None:
        matches = [c for c in matches if c["litigation_flag"] == litigation_flag]
    if alleged_violation_type is not None:
        matches = [c for c in matches if c["alleged_violation_type"] == alleged_violation_type]
    matches = by_created_at(matches)
    page, total = v.paginate(matches, limit, offset)
    return listing([public(c) for c in page], limit, offset, total)


@bp.post("/compliance/complaints/<complaint_id>/substantiate")
@endpoint(["ComplianceOfficer"])
def substantiate(complaint_id):
    body = payload()
    willful = v.req_bool(body, "willful")
    finding_note = v.req_str(body, "finding_note")
    complaint = lookup.complaint(complaint_id)
    if complaint["status"] != "OPEN":
        raise ApiError("ERR_COMPLAINT_STATE_INVALID", "Only an OPEN complaint may be substantiated.")

    verified = verified_attempt_count(complaint["contact_id"], complaint["campaign_id"])
    complaint["status"] = "SUBSTANTIATED"
    complaint["willful"] = willful
    complaint["finding_note"] = finding_note
    complaint["verified_attempt_count"] = verified
    complaint["adjudicated_risk_score"] = pct(
        calc.adjudicated_risk_score(
            complaint["source"],
            complaint["alleged_violation_type"],
            verified,
            complaint["litigation_flag"],
        )
    )
    complaint["exposure_cents"] = calc.statutory_exposure(verified, willful)
    touch(complaint)

    contact = db.contacts.get(complaint["contact_id"])
    if contact is not None:
        recompute_contact(contact)
        if contact["risk_tier"] == "CRITICAL":
            for record in by_created_at(consents_of_contact(contact["id"])):
                if record["status"] != "ACTIVE":
                    continue
                record["status"] = "SUSPENDED"
                record["suspended_reason"] = "CRITICAL risk tier"
                touch(record)
            ensure_internal_suppression(contact)
        touch_contact(contact)

    recompute_clusters(complaint, skip_anchor_touch=True)
    return ok(public(complaint))


@bp.post("/compliance/complaints/<complaint_id>/dismiss")
@endpoint(["ComplianceOfficer"])
def dismiss(complaint_id):
    body = payload()
    dismissal_note = v.req_str(body, "dismissal_note")
    complaint = lookup.complaint(complaint_id)
    if complaint["status"] != "OPEN":
        raise ApiError("ERR_COMPLAINT_STATE_INVALID", "Only an OPEN complaint may be dismissed.")
    complaint["status"] = "DISMISSED"
    complaint["dismissal_note"] = dismissal_note
    touch(complaint)
    recompute_clusters(complaint, skip_anchor_touch=True)
    return ok(public(complaint))
