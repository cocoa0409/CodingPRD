"""FieldworkVisit endpoints."""
from datetime import timedelta
from flask import Blueprint, request
from db import db
from middleware import get_user_context, require_roles, parse_pagination
from response import success_object, success_list
from errors import (
    ApiError,
    ERR_VISIT_NOT_FOUND,
    ERR_ENGAGEMENT_POSTURE_LOCKED,
    ERR_VISIT_NOT_SCHEDULED,
    ERR_INVALID_VISIT_WINDOW,
    ERR_VISIT_WINDOW_OVERLAP,
    ERR_DEADLINE_AFTER_FILING,
    ERR_LOCATION_NOT_FOUND,
)
from clock import parse_date
from services.core import (
    stamp_new,
    touch,
    get_engagement_or_404,
    recompute_engagement_derived,
)

bp = Blueprint("visits", __name__)


def _get_visit_or_404(visit_id):
    v = db.fieldwork_visits.get(visit_id)
    if v is None:
        raise ApiError(ERR_VISIT_NOT_FOUND, "FieldworkVisit id not found", 404)
    return v


@bp.route("/api/fieldwork-visits", methods=["POST"])
def create_visit():
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    body = request.get_json(force=True, silent=True) or {}

    engagement_id = body.get("engagement_id")
    auditor_user_id = body.get("auditor_user_id")
    location_id = body.get("location_id")
    visit_start = body.get("visit_start")
    visit_end = body.get("visit_end")

    if not isinstance(engagement_id, str) or not engagement_id.strip():
        raise ApiError("ERR_VALIDATION", "engagement_id is required", 400)
    eng = get_engagement_or_404(engagement_id)
    recompute_engagement_derived(eng)
    if eng["posture"] == "LOCKED":
        raise ApiError(
            ERR_ENGAGEMENT_POSTURE_LOCKED,
            "Engagement posture is LOCKED; mutating endpoint forbidden",
            409,
        )
    if not isinstance(auditor_user_id, str) or not auditor_user_id.strip():
        raise ApiError("ERR_VALIDATION", "auditor_user_id is required", 400)
    if not isinstance(location_id, str) or not location_id.strip():
        raise ApiError("ERR_VALIDATION", "location_id is required", 400)
    loc = db.locations.get(location_id)
    if loc is None or loc["engagement_id"] != engagement_id:
        raise ApiError(ERR_LOCATION_NOT_FOUND, "Location id not found", 404)
    if not isinstance(visit_start, str) or not visit_start.strip():
        raise ApiError("ERR_VALIDATION", "visit_start is required", 400)
    if not isinstance(visit_end, str) or not visit_end.strip():
        raise ApiError("ERR_VALIDATION", "visit_end is required", 400)

    # Priority 9: visit window shape
    try:
        start = parse_date(visit_start)
        end = parse_date(visit_end)
    except Exception:
        raise ApiError(
            ERR_INVALID_VISIT_WINDOW,
            "visit_end must be >= visit_start",
            400,
        )
    if end < start:
        raise ApiError(
            ERR_INVALID_VISIT_WINDOW,
            "visit_end must be >= visit_start",
            400,
        )

    # Priority 14: visit_end strictly before filing_deadline
    filing = parse_date(eng["filing_deadline"])
    if end >= filing:
        raise ApiError(
            ERR_DEADLINE_AFTER_FILING,
            "FieldworkVisit.visit_end must be before engagement.filing_deadline",
            422,
        )

    # Priority 11: same-auditor overlap (closed intervals + 1-day buffer)
    for other in db.fieldwork_visits.values():
        if other["auditor_user_id"] != auditor_user_id:
            continue
        if other["status"] != "SCHEDULED":
            continue
        o_start = parse_date(other["visit_start"])
        o_end = parse_date(other["visit_end"])
        # Closed-interval overlap: new.start <= existing.end AND existing.start <= new.end
        if start <= o_end and o_start <= end:
            raise ApiError(
                ERR_VISIT_WINDOW_OVERLAP,
                "New fieldwork visit overlaps an existing SCHEDULED visit for the same auditor",
                409,
            )
        # 1-day buffer: when new starts after existing ends, new.start must be at least 1 day after existing.end
        if start > o_end:
            gap = (start - o_end).days
            if gap < 1:
                raise ApiError(
                    ERR_VISIT_WINDOW_OVERLAP,
                    "A 1-day buffer is required between visits by the same auditor",
                    409,
                )
        # Symmetric buffer: when existing starts after new ends
        if o_start > end:
            gap = (o_start - end).days
            if gap < 1:
                raise ApiError(
                    ERR_VISIT_WINDOW_OVERLAP,
                    "A 1-day buffer is required between visits by the same auditor",
                    409,
                )

    v = stamp_new(
        {
            "engagement_id": engagement_id,
            "auditor_user_id": auditor_user_id,
            "location_id": location_id,
            "visit_start": visit_start,
            "visit_end": visit_end,
            "status": "SCHEDULED",
        }
    )
    db.fieldwork_visits[v["id"]] = v
    return success_object(dict(v), 201)


@bp.route("/api/fieldwork-visits", methods=["GET"])
def list_visits():
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    limit, offset = parse_pagination()
    engagement_id = request.args.get("engagement_id")
    location_id = request.args.get("location_id")
    status = request.args.get("status")
    items = list(db.fieldwork_visits.values())
    if engagement_id:
        items = [v for v in items if v["engagement_id"] == engagement_id]
    if location_id:
        items = [v for v in items if v["location_id"] == location_id]
    if status:
        items = [v for v in items if v["status"] == status]
    items.sort(key=lambda v: v["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([dict(v) for v in page], limit, offset, total)


@bp.route("/api/fieldwork-visits/<visit_id>", methods=["GET"])
def get_visit(visit_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    v = _get_visit_or_404(visit_id)
    return success_object(dict(v))


@bp.route("/api/fieldwork-visits/<visit_id>/complete", methods=["POST"])
def complete_visit(visit_id):
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    v = _get_visit_or_404(visit_id)
    if v["status"] != "SCHEDULED":
        raise ApiError(
            ERR_VISIT_NOT_SCHEDULED,
            "Complete requires FieldworkVisit in SCHEDULED",
            409,
        )
    v["status"] = "COMPLETED"
    touch(v)
    return success_object(dict(v))


@bp.route("/api/fieldwork-visits/<visit_id>/cancel", methods=["POST"])
def cancel_visit(visit_id):
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    v = _get_visit_or_404(visit_id)
    if v["status"] != "SCHEDULED":
        raise ApiError(
            ERR_VISIT_NOT_SCHEDULED,
            "Cancel requires FieldworkVisit in SCHEDULED",
            409,
        )
    v["status"] = "CANCELLED"
    touch(v)
    return success_object(dict(v))
