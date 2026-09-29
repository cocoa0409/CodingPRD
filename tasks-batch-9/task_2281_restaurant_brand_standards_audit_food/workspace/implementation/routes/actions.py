"""The corrective-action loop, photo evidence and the overdue sweep."""

from flask import Blueprint, g

import db
import serializers
from common import touch
from errors import fail
from middleware import (
    begin,
    body,
    filter_enum,
    filter_value,
    listing,
    opt_id,
    opt_str,
    req_dt,
    req_enum,
    req_str,
    require,
    resolve_identity,
)
from response import object_response
from services import cascade

bp = Blueprint("actions", __name__)

ACTION_STATUSES = (
    "ASSIGNED",
    "SUBMITTED",
    "VERIFIED",
    "REJECTED",
    "OVERDUE",
    "ESCALATED",
    "VOIDED",
)
ACTION_SEVERITIES = ("STANDARD", "CRITICAL")
VERIFY_OUTCOMES = ("ACCEPTED", "REJECTED")
SUBMIT_BLOCKED_STATES = ("SUBMITTED", "VERIFIED", "VOIDED")


# --------------------------------------------------------------------------
# Corrective-action reads
# --------------------------------------------------------------------------

@bp.route("/corrective-actions/<action_id>", methods=["GET"])
def read_corrective_action(action_id):
    begin("BrandAdmin", "Auditor", "Franchisee")
    action = require("corrective_action", action_id)
    resolve_identity()
    return object_response(serializers.corrective_action(action))


@bp.route("/corrective-actions", methods=["GET"])
def list_corrective_actions():
    begin("BrandAdmin", "Auditor", "Franchisee")
    resolve_identity()
    scored_item_id = filter_value("scored_item_id")
    location_id = filter_value("location_id")
    franchisee_id = filter_value("assigned_franchisee_id")
    status = filter_enum("status", ACTION_STATUSES)
    severity = filter_enum("severity", ACTION_SEVERITIES)

    records = []
    for action in db.store.corrective_actions.values():
        if scored_item_id is not None and action["scored_item_id"] != scored_item_id:
            continue
        if location_id is not None and action["location_id"] != location_id:
            continue
        if franchisee_id is not None and action["assigned_franchisee_id"] != franchisee_id:
            continue
        if status is not None and action["status"] != status:
            continue
        if severity is not None and action["severity"] != severity:
            continue
        records.append(action)
    return listing(records, serializers.corrective_action)


@bp.route("/corrective-actions/<action_id>/evidence-photos", methods=["GET"])
def list_action_photos(action_id):
    begin("BrandAdmin", "Auditor", "Franchisee")
    require("corrective_action", action_id)
    resolve_identity()
    records = [
        p for p in db.store.evidence_photos.values()
        if p["corrective_action_id"] == action_id
    ]
    return listing(records, serializers.evidence_photo)


@bp.route("/corrective-actions/<action_id>/escalation-events", methods=["GET"])
def list_action_escalation_events(action_id):
    begin("BrandAdmin", "Franchisee")
    require("corrective_action", action_id)
    resolve_identity()
    records = [
        e for e in db.store.escalation_events.values()
        if e["corrective_action_id"] == action_id
    ]
    return listing(records, serializers.escalation_event)


# --------------------------------------------------------------------------
# POST /corrective-actions/{id}/submit
# --------------------------------------------------------------------------

@bp.route("/corrective-actions/<action_id>/submit", methods=["POST"])
def submit_corrective_action(action_id):
    begin("Franchisee")
    action = require("corrective_action", action_id)
    resolve_identity()
    if action["assigned_franchisee_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting franchisee is not assigned this action.")
    payload = body()
    opt_str(payload, "remediation_note", 0, 1000)

    status = action["status"]
    if status in SUBMIT_BLOCKED_STATES \
            or (status == "ESCALATED" and action["severity"] != "CRITICAL"):
        fail(
            "ERR_INVALID_CORRECTIVE_ACTION_STATE",
            "A corrective action in %s may not be submitted." % status,
        )

    if action["evidence_photo_count"] < 1:
        fail("ERR_EVIDENCE_REQUIRED", "At least one evidence photo must be attached.")

    if status == "ESCALATED":
        fail(
            "ERR_LATE_CURE_NOT_ALLOWED",
            "An escalated CRITICAL corrective action may not be cured late.",
        )

    action["status"] = "SUBMITTED"
    action["submission_count"] = action["submission_count"] + 1
    action["submitted_at"] = db.store.clock
    touch(action)

    location = db.store.locations.get(action["location_id"])
    if location is not None:
        cascade.recompute_open_action_count(location)
    return object_response(serializers.corrective_action(action))


# --------------------------------------------------------------------------
# POST /corrective-actions/{id}/verify
# --------------------------------------------------------------------------

@bp.route("/corrective-actions/<action_id>/verify", methods=["POST"])
def verify_corrective_action(action_id):
    begin("Auditor")
    action = require("corrective_action", action_id)
    resolve_identity()
    payload = body()
    outcome = req_enum(payload, "outcome", VERIFY_OUTCOMES)
    rejection_reason = opt_str(payload, "rejection_reason", 1, 1000)
    if outcome == "REJECTED" and rejection_reason is None:
        fail("ERR_INVALID_REQUEST", "Field 'rejection_reason' is required when outcome is REJECTED.")

    if action["status"] != "SUBMITTED":
        fail(
            "ERR_INVALID_CORRECTIVE_ACTION_STATE",
            "Only a SUBMITTED corrective action may be verified.",
        )

    auditor = g.actor
    if auditor["status"] == "SUSPENDED":
        fail("ERR_AUDITOR_SUSPENDED", "A SUSPENDED auditor may not verify remediation.")
    if auditor["status"] != "CERTIFIED":
        fail("ERR_AUDITOR_NOT_CERTIFIED", "Only a CERTIFIED auditor may verify remediation.")

    location = db.store.locations.get(action["location_id"])

    if outcome == "ACCEPTED":
        action["status"] = "VERIFIED"
        action["verified_at"] = db.store.clock
        touch(action)
        if location is not None:
            cascade.recompute_open_action_count(location)
            brand = db.store.brands.get(location["brand_id"])
            if brand is not None:
                cascade.recompute_brand_counts(brand)
                cascade.recompute_brand_risk(brand)
    else:
        action["status"] = "REJECTED"
        action["rejection_count"] = action["rejection_count"] + 1
        touch(action)
        if location is not None:
            cascade.recompute_open_action_count(location)

    return object_response(serializers.corrective_action(action))


# --------------------------------------------------------------------------
# POST /evidence-photos
# --------------------------------------------------------------------------

@bp.route("/evidence-photos", methods=["POST"])
def create_evidence_photo():
    begin("Franchisee", "Auditor")
    resolve_identity()
    payload = body()
    action_id = opt_id(payload, "corrective_action_id")
    dispute_id = opt_id(payload, "dispute_id")

    # 5: ownership, evaluated against whichever target actually resolves.
    if g.role == "Franchisee":
        if action_id is not None:
            action = db.store.corrective_actions.get(action_id)
            if action is not None and action["assigned_franchisee_id"] != g.user_id:
                fail(
                    "ERR_NOT_RESOURCE_OWNER",
                    "The acting franchisee is not assigned this corrective action.",
                )
        elif dispute_id is not None:
            dispute = db.store.disputes.get(dispute_id)
            if dispute is not None and dispute["filed_by_franchisee_id"] != g.user_id:
                fail("ERR_NOT_RESOURCE_OWNER", "The acting franchisee did not file this dispute.")

    file_uri = req_str(payload, "file_uri", 1, 500)
    if not file_uri.startswith("s3://"):
        fail("ERR_INVALID_REQUEST", "Field 'file_uri' must start with 's3://'.")
    captured_at = req_dt(payload, "captured_at")
    caption = opt_str(payload, "caption", 0, 200)

    action = None
    dispute = None
    if action_id is not None:
        action = require("corrective_action", action_id)
    if dispute_id is not None:
        dispute = require("dispute", dispute_id)

    if (action_id is None) == (dispute_id is None):
        fail(
            "ERR_EVIDENCE_TARGET_AMBIGUOUS",
            "Name exactly one of corrective_action_id and dispute_id.",
        )

    if captured_at > db.store.clock:
        fail("ERR_TIMESTAMP_IN_FUTURE", "captured_at may not be after the logical clock.")

    record = db.new_record(light=True)
    record.update({
        "corrective_action_id": action_id,
        "dispute_id": dispute_id,
        "file_uri": file_uri,
        "captured_at": captured_at,
        "caption": caption,
        "uploaded_by_role": g.role,
    })
    db.store.evidence_photos[record["id"]] = record

    if action is not None:
        cascade.recompute_evidence_photo_count(action)
    return object_response(serializers.evidence_photo(record), 201)


# --------------------------------------------------------------------------
# POST /overdue-sweeps
# --------------------------------------------------------------------------

@bp.route("/overdue-sweeps", methods=["POST"])
def overdue_sweep():
    begin("BrandAdmin")
    resolve_identity()
    body()

    candidates = [
        a for a in db.store.corrective_actions.values()
        if a["status"] in ("ASSIGNED", "REJECTED") and a["due_at"] < db.store.clock
    ]
    candidates.sort(key=db.sort_key)

    swept_count = 0
    overdue_count = 0
    escalated_count = 0
    escalated_locations = []
    touched_locations = []

    for action in candidates:
        action["status"] = "OVERDUE"
        touch(action)
        swept_count += 1
        # Every swept action lands in OVERDUE; a CRITICAL one then continues on.
        overdue_count += 1
        location = db.store.locations.get(action["location_id"])
        if location is not None and location["id"] not in [l["id"] for l in touched_locations]:
            touched_locations.append(location)

        if action["severity"] == "CRITICAL" and location is not None:
            cascade.escalate_corrective_action(action, location)
            escalated_count += 1
            if location["id"] not in escalated_locations:
                escalated_locations.append(location["id"])
        else:
            if location is not None:
                cascade.recompute_open_action_count(location)

    for location in touched_locations:
        cascade.cascade_location(location)

    return object_response({
        "swept_count": swept_count,
        "overdue_count": overdue_count,
        "escalated_count": escalated_count,
        "escalated_location_count": len(escalated_locations),
    })
