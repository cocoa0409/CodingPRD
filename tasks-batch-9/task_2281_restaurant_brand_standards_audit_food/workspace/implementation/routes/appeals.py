"""The appeal path: disputes against a scored item of a finalized visit."""

from flask import Blueprint, g

import db
import serializers
from common import dec, touch
from errors import fail
from middleware import (
    begin,
    body,
    filter_enum,
    filter_value,
    listing,
    opt_str,
    req_enum,
    req_id,
    req_int,
    req_str,
    require,
    resolve_identity,
)
from response import object_response
from services import calc, cascade

bp = Blueprint("appeals", __name__)

DISPUTE_STATUSES = (
    "FILED",
    "INFO_REQUESTED",
    "EVIDENCE_REVIEW",
    "UPHELD",
    "AMENDED",
    "WITHDRAWN",
)
OPEN_DISPUTE_STATUSES = ("FILED", "INFO_REQUESTED", "EVIDENCE_REVIEW")
RESOLVE_OUTCOMES = ("UPHELD", "AMENDED")
MAX_INFO_REQUESTS = 2


def _visit_of_scored_item(scored):
    return db.store.audit_visits.get(scored["visit_id"])


def _location_of_scored_item(scored):
    visit = _visit_of_scored_item(scored)
    if visit is None:
        return None
    return db.store.locations.get(visit["location_id"])


def _max_points_of(scored):
    rubric_item = db.store.rubric_items.get(scored["rubric_item_id"])
    return rubric_item["max_points"] if rubric_item is not None else 0


def _check_points(scored, value, field):
    if value <= scored["points_awarded"] or value > _max_points_of(scored):
        fail(
            "ERR_DISPUTE_POINTS_INVALID",
            "%s must be strictly above %s and at most %s."
            % (field, scored["points_awarded"], _max_points_of(scored)),
        )


def _require_reviewer_standing(dispute):
    """Steps 12, 13 and 14 for the two calibration-reviewer actions."""
    auditor = g.actor
    if auditor["status"] == "SUSPENDED":
        fail("ERR_AUDITOR_SUSPENDED", "A SUSPENDED auditor may not review a dispute.")
    if auditor["status"] != "CERTIFIED":
        fail("ERR_AUDITOR_NOT_CERTIFIED", "Only a CERTIFIED auditor may review a dispute.")
    scored = db.store.scored_items.get(dispute["scored_item_id"])
    visit = _visit_of_scored_item(scored) if scored is not None else None
    if visit is not None and visit["auditor_id"] == g.user_id:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "A reviewer may not adjudicate a dispute against their own scoring.",
        )


# --------------------------------------------------------------------------
# POST /disputes
# --------------------------------------------------------------------------

@bp.route("/disputes", methods=["POST"])
def file_dispute():
    begin("Franchisee")
    resolve_identity()
    payload = body()
    scored_item_id = req_id(payload, "scored_item_id")

    # 5: the acting franchisee must operate the location behind the scored item.
    probe = db.store.scored_items.get(scored_item_id)
    if probe is not None:
        location = _location_of_scored_item(probe)
        if location is not None and location["franchisee_id"] != g.user_id:
            fail(
                "ERR_NOT_RESOURCE_OWNER",
                "The acting franchisee does not operate the audited location.",
            )

    requested_points = req_int(payload, "requested_points")
    req_str(payload, "reason", 10, 1000)
    reason = payload["reason"]

    scored = require("scored_item", scored_item_id)
    visit = _visit_of_scored_item(scored)

    if visit is None or visit["status"] != "FINALIZED":
        fail("ERR_INVALID_VISIT_STATE", "A scored item may only be appealed once its visit is FINALIZED.")
    if scored["status"] in ("AMENDED", "UPHELD"):
        fail("ERR_INVALID_VISIT_STATE", "The scored item has already been adjudicated.")

    _check_points(scored, requested_points, "requested_points")

    for existing in db.store.disputes.values():
        if existing["scored_item_id"] == scored_item_id \
                and existing["status"] in OPEN_DISPUTE_STATUSES:
            fail("ERR_DISPUTE_ALREADY_OPEN", "Another dispute on this scored item is still live.")

    record = db.new_record()
    record.update({
        "scored_item_id": scored_item_id,
        "filed_by_franchisee_id": g.user_id,
        "reviewer_auditor_id": None,
        "requested_points": requested_points,
        "reason": reason,
        "status": "FILED",
        "info_request_count": 0,
        "resolution_points": None,
        "filed_at": db.store.clock,
        "resolved_at": None,
    })
    db.store.disputes[record["id"]] = record

    scored["status"] = "UNDER_DISPUTE"
    touch(scored)
    return object_response(serializers.dispute(record), 201)


# --------------------------------------------------------------------------
# Dispute reads
# --------------------------------------------------------------------------

@bp.route("/disputes/<dispute_id>", methods=["GET"])
def read_dispute(dispute_id):
    begin("BrandAdmin", "Franchisee", "CalibrationReviewer")
    dispute = require("dispute", dispute_id)
    resolve_identity()
    return object_response(serializers.dispute(dispute))


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    begin("BrandAdmin", "Franchisee", "CalibrationReviewer")
    resolve_identity()
    scored_item_id = filter_value("scored_item_id")
    filed_by = filter_value("filed_by_franchisee_id")
    reviewer = filter_value("reviewer_auditor_id")
    status = filter_enum("status", DISPUTE_STATUSES)

    records = []
    for dispute in db.store.disputes.values():
        if scored_item_id is not None and dispute["scored_item_id"] != scored_item_id:
            continue
        if filed_by is not None and dispute["filed_by_franchisee_id"] != filed_by:
            continue
        if reviewer is not None and dispute["reviewer_auditor_id"] != reviewer:
            continue
        if status is not None and dispute["status"] != status:
            continue
        records.append(dispute)
    return listing(records, serializers.dispute)


@bp.route("/disputes/<dispute_id>/evidence-photos", methods=["GET"])
def list_dispute_photos(dispute_id):
    begin("BrandAdmin", "Franchisee", "CalibrationReviewer")
    require("dispute", dispute_id)
    resolve_identity()
    records = [
        p for p in db.store.evidence_photos.values()
        if p["dispute_id"] == dispute_id
    ]
    return listing(records, serializers.evidence_photo)


# --------------------------------------------------------------------------
# POST /disputes/{id}/request-info
# --------------------------------------------------------------------------

@bp.route("/disputes/<dispute_id>/request-info", methods=["POST"])
def request_dispute_info(dispute_id):
    begin("CalibrationReviewer")
    dispute = require("dispute", dispute_id)
    resolve_identity()
    payload = body()
    req_str(payload, "information_requested", 1, 1000)

    if dispute["status"] not in ("FILED", "EVIDENCE_REVIEW"):
        fail(
            "ERR_INVALID_DISPUTE_STATE",
            "A dispute in %s may not receive an information request." % dispute["status"],
        )

    _require_reviewer_standing(dispute)

    if dispute["info_request_count"] >= MAX_INFO_REQUESTS:
        fail("ERR_INFO_REQUEST_LIMIT_REACHED", "At most two information rounds are accepted.")

    dispute["status"] = "INFO_REQUESTED"
    dispute["info_request_count"] = dispute["info_request_count"] + 1
    if dispute["reviewer_auditor_id"] is None:
        dispute["reviewer_auditor_id"] = g.user_id
    touch(dispute)
    return object_response(serializers.dispute(dispute))


# --------------------------------------------------------------------------
# POST /disputes/{id}/supplement
# --------------------------------------------------------------------------

@bp.route("/disputes/<dispute_id>/supplement", methods=["POST"])
def supplement_dispute(dispute_id):
    begin("Franchisee")
    dispute = require("dispute", dispute_id)
    resolve_identity()
    if dispute["filed_by_franchisee_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting franchisee did not file this dispute.")
    payload = body()
    opt_str(payload, "note", 0, 1000)

    if dispute["status"] not in ("FILED", "INFO_REQUESTED"):
        fail(
            "ERR_INVALID_DISPUTE_STATE",
            "A dispute in %s may not be supplemented." % dispute["status"],
        )

    attached = any(
        photo["dispute_id"] == dispute_id
        for photo in db.store.evidence_photos.values()
    )
    if not attached:
        fail("ERR_EVIDENCE_REQUIRED", "At least one evidence photo must reference this dispute.")

    dispute["status"] = "EVIDENCE_REVIEW"
    touch(dispute)
    return object_response(serializers.dispute(dispute))


# --------------------------------------------------------------------------
# POST /disputes/{id}/resolve
# --------------------------------------------------------------------------

def _amendment_cascade(scored, granted_points):
    scored["amended_points_awarded"] = granted_points
    scored["status"] = "AMENDED"
    calc.derive_scored_item(scored)
    touch(scored)

    visit = _visit_of_scored_item(scored)
    if visit is not None:
        calc.recompute_visit_scores(visit, "FINAL")

    location = _location_of_scored_item(scored)
    if location is None:
        return

    calc.recompute_repeat_violation_count(location)
    calc.recompute_standing_score(location)

    if not scored["is_violation"]:
        for action in sorted(db.store.corrective_actions.values(), key=db.sort_key):
            if action["scored_item_id"] != scored["id"]:
                continue
            if action["status"] in ("VERIFIED", "VOIDED"):
                continue
            cascade.void_corrective_action(action, location)

    cascade.recompute_open_action_count(location)

    franchisee = db.store.franchisees.get(location["franchisee_id"])
    if franchisee is not None:
        cascade.recompute_franchisee(franchisee)
    brand = db.store.brands.get(location["brand_id"])
    if brand is not None:
        cascade.recompute_brand_counts(brand)
        cascade.recompute_brand_risk(brand)


@bp.route("/disputes/<dispute_id>/resolve", methods=["POST"])
def resolve_dispute(dispute_id):
    begin("CalibrationReviewer")
    dispute = require("dispute", dispute_id)
    resolve_identity()
    payload = body()
    outcome = req_enum(payload, "outcome", RESOLVE_OUTCOMES)
    req_str(payload, "rationale", 1, 2000)
    granted_points = None
    if outcome == "AMENDED":
        granted_points = req_int(payload, "granted_points")

    if dispute["status"] != "EVIDENCE_REVIEW":
        fail(
            "ERR_INVALID_DISPUTE_STATE",
            "Only a dispute in EVIDENCE_REVIEW may be resolved.",
        )

    _require_reviewer_standing(dispute)

    scored = db.store.scored_items.get(dispute["scored_item_id"])
    if scored is None:
        fail("ERR_SCORED_ITEM_NOT_FOUND", "The disputed scored item no longer exists.")

    if outcome == "AMENDED":
        _check_points(scored, granted_points, "granted_points")

    if dispute["reviewer_auditor_id"] is None:
        dispute["reviewer_auditor_id"] = g.user_id
    dispute["resolved_at"] = db.store.clock

    if outcome == "UPHELD":
        dispute["status"] = "UPHELD"
        dispute["resolution_points"] = dec(scored["points_awarded"])
        touch(dispute)
        scored["status"] = "UPHELD"
        touch(scored)
    else:
        dispute["status"] = "AMENDED"
        dispute["resolution_points"] = dec(granted_points)
        touch(dispute)
        _amendment_cascade(scored, granted_points)

    return object_response(serializers.dispute(dispute))


# --------------------------------------------------------------------------
# POST /disputes/{id}/withdraw
# --------------------------------------------------------------------------

@bp.route("/disputes/<dispute_id>/withdraw", methods=["POST"])
def withdraw_dispute(dispute_id):
    begin("Franchisee")
    dispute = require("dispute", dispute_id)
    resolve_identity()
    if dispute["filed_by_franchisee_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting franchisee did not file this dispute.")
    payload = body()
    opt_str(payload, "note", 0, 1000)

    if dispute["status"] not in OPEN_DISPUTE_STATUSES:
        fail(
            "ERR_INVALID_DISPUTE_STATE",
            "A dispute in %s may not be withdrawn." % dispute["status"],
        )

    dispute["status"] = "WITHDRAWN"
    dispute["resolved_at"] = db.store.clock
    touch(dispute)

    scored = db.store.scored_items.get(dispute["scored_item_id"])
    if scored is not None and scored["status"] == "UNDER_DISPUTE":
        scored["status"] = "SCORED"
        touch(scored)

    return object_response(serializers.dispute(dispute))
