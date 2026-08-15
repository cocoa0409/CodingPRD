"""Engagement endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_JURISDICTION_NOT_FOUND,
    ERR_REVIEWER_NOT_FOUND,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_LICENSE_STATE_MISMATCH,
    ERR_ENGAGEMENT_NOT_ACTIVE,
    ERR_ENGAGEMENT_NOT_AMENDABLE,
)
from middleware import (
    require_roles, get_json_body, require_fields, reject_unknown_fields,
    require_enum, require_string, require_int, opt_bool,
    parse_pagination, paginate,
)
from response import success_object, success_list
from services.core import (
    license_for_state, refresh_engagement_counts, release_active_assignments,
)
from services.fees import compute_estimated_fee

bp = Blueprint("engagements", __name__)

READ_ROLES = ("PlatformAdmin", "ReviewCoordinator", "Reviewer", "ChiefReviewer", "Applicant")
BUILDING_TYPES = ("RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL", "ESSENTIAL_FACILITY")
RISK_CATEGORIES = ("I", "II", "III", "IV")
SCOPES = ("FULL_REVIEW", "LATERAL_ONLY", "PEER_REVIEW")
ENGAGEMENT_STATUSES = ("REGISTERED", "IN_PROGRESS", "APPROVED", "COMPLETED", "CANCELLED")


def get_engagement_or_404(eid):
    e = db.engagements.get(eid)
    if e is None:
        raise ApiError(ERR_ENGAGEMENT_NOT_FOUND, 404, "No engagement with the given id")
    return e


@bp.post("/plan-review/engagements")
def create_engagement():
    require_roles("ReviewCoordinator")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {
        "project_name", "jurisdiction_id", "applicant_contact_id",
        "reviewer_of_record_id", "building_type", "risk_category", "scope",
        "declared_valuation_cents", "floor_area_sqft", "requested_expedite",
    })
    require_fields(body, [
        "project_name", "jurisdiction_id", "applicant_contact_id",
        "reviewer_of_record_id", "building_type", "risk_category", "scope",
        "declared_valuation_cents", "floor_area_sqft",
    ])
    project_name = require_string(body, "project_name")
    jurisdiction_id = require_string(body, "jurisdiction_id")
    applicant_contact_id = require_string(body, "applicant_contact_id")
    reviewer_of_record_id = require_string(body, "reviewer_of_record_id")
    building_type = require_enum(body, "building_type", BUILDING_TYPES)
    risk_category = require_enum(body, "risk_category", RISK_CATEGORIES)
    scope = require_enum(body, "scope", SCOPES)
    declared_valuation_cents = require_int(body, "declared_valuation_cents")
    floor_area_sqft = require_int(body, "floor_area_sqft")
    requested_expedite = opt_bool(body, "requested_expedite", False)

    # existence: body FKs (jurisdiction_id, then reviewer_of_record_id)
    jurisdiction = db.jurisdictions.get(jurisdiction_id)
    if jurisdiction is None:
        raise ApiError(ERR_JURISDICTION_NOT_FOUND, 404, "No jurisdiction with the given id")
    reviewer = db.reviewers.get(reviewer_of_record_id)
    if reviewer is None:
        raise ApiError(ERR_REVIEWER_NOT_FOUND, 404, "No reviewer with the given id")

    # regulatory: reviewer of record must hold a license for the pinned state
    if license_for_state(reviewer, jurisdiction["state_code"]) is None:
        raise ApiError(ERR_LICENSE_STATE_MISMATCH, 422,
                       "Reviewer of record holds no license for the jurisdiction state")

    entity = db.stamp_new({
        "project_name": project_name,
        "jurisdiction_id": jurisdiction_id,
        "applicant_contact_id": applicant_contact_id,
        "reviewer_of_record_id": reviewer_of_record_id,
        "building_type": building_type,
        "risk_category": risk_category,
        "scope": scope,
        "declared_valuation_cents": declared_valuation_cents,
        "floor_area_sqft": floor_area_sqft,
        "requested_expedite": requested_expedite,
        # pinned snapshot (§2.6)
        "pinned_state_code": jurisdiction["state_code"],
        "pinned_ibc_edition": jurisdiction["ibc_edition"],
        "pinned_asce7_edition": jurisdiction["asce7_edition"],
        "pinned_fee_method": jurisdiction["fee_method"],
        "pinned_turnaround_days": jurisdiction["turnaround_days"],
        "pinned_sla_mode": jurisdiction["sla_mode"],
        "pinned_free_resubmittal_cycles": jurisdiction["free_resubmittal_cycles"],
        "pinned_requires_se_seal": jurisdiction["requires_se_seal"],
        "pinned_allows_deferred_submittals": jurisdiction["allows_deferred_submittals"],
        # computed
        "estimated_fee_cents": 0,   # placeholder, computed below
        "final_fee_cents": None,
        "cycle_count": 0,
        "unresolved_comment_count": 0,
        "deferred_pending_count": 0,
        "status": "REGISTERED",
    })
    entity["estimated_fee_cents"] = compute_estimated_fee(entity)
    db.engagements[entity["id"]] = entity
    return success_object(db.serialize(entity), status=201)


@bp.get("/plan-review/engagements")
def list_engagements():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()

    items = list(db.engagements.values())
    jurisdiction_id = request.args.get("jurisdiction_id")
    reviewer_of_record_id = request.args.get("reviewer_of_record_id")
    status = request.args.get("status")
    if jurisdiction_id is not None:
        items = [e for e in items if e["jurisdiction_id"] == jurisdiction_id]
    if reviewer_of_record_id is not None:
        items = [e for e in items if e["reviewer_of_record_id"] == reviewer_of_record_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]

    for e in items:
        refresh_engagement_counts(e)
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([db.serialize(e) for e in page], limit, offset, total)


@bp.get("/plan-review/engagements/<eid>")
def get_engagement(eid):
    require_roles(*READ_ROLES)
    e = get_engagement_or_404(eid)
    refresh_engagement_counts(e)
    return success_object(db.serialize(e))


@bp.put("/plan-review/engagements/<eid>")
def update_engagement(eid):
    require_roles("ReviewCoordinator")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {
        "declared_valuation_cents", "floor_area_sqft", "requested_expedite",
    })
    e = get_engagement_or_404(eid)

    if e["status"] not in ("REGISTERED", "IN_PROGRESS"):
        raise ApiError(ERR_ENGAGEMENT_NOT_AMENDABLE, 409,
                       "Engagement is not amendable in its current status")

    if "declared_valuation_cents" in body and body["declared_valuation_cents"] is not None:
        e["declared_valuation_cents"] = require_int(body, "declared_valuation_cents")
    if "floor_area_sqft" in body and body["floor_area_sqft"] is not None:
        e["floor_area_sqft"] = require_int(body, "floor_area_sqft")
    if "requested_expedite" in body and body["requested_expedite"] is not None:
        e["requested_expedite"] = opt_bool(body, "requested_expedite")

    db.touch(e)
    refresh_engagement_counts(e)
    return success_object(db.serialize(e))


@bp.post("/plan-review/engagements/<eid>/cancel")
def cancel_engagement(eid):
    require_roles("ReviewCoordinator")
    get_json_body(required=False)
    e = get_engagement_or_404(eid)

    if e["status"] not in ("REGISTERED", "IN_PROGRESS"):
        raise ApiError(ERR_ENGAGEMENT_NOT_ACTIVE, 409,
                       "Engagement cannot be cancelled from its current status")

    # cascade: all non-terminal cycles -> CANCELLED; their ACTIVE assignments -> RELEASED
    for c in list(db.cycles.values()):
        if c["engagement_id"] == e["id"] and c["status"] in ("OPEN", "IN_REVIEW", "COMMENTS_ISSUED"):
            release_active_assignments(c)
            c["status"] = "CANCELLED"
            db.touch(c)

    e["status"] = "CANCELLED"
    db.touch(e)
    refresh_engagement_counts(e)
    return success_object(db.serialize(e))
