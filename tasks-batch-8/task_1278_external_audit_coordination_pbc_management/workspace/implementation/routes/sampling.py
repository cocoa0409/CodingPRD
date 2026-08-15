"""SamplingRequest endpoints."""
from flask import Blueprint, request
from db import db
from middleware import get_user_context, require_roles, parse_pagination
from response import success_object, success_list
from errors import (
    ApiError,
    ERR_SAMPLING_NOT_FOUND,
    ERR_ENGAGEMENT_POSTURE_LOCKED,
    ERR_SAMPLING_NOT_DRAFT,
    ERR_SAMPLING_NOT_DISPATCHED,
    ERR_SAMPLING_NOT_IN_PROGRESS,
    ERR_SAMPLING_NOT_CANCELLABLE,
    ERR_INVALID_SAMPLING_WINDOW,
    ERR_INVALID_SAMPLE_SIZE,
    ERR_NO_SAMPLING_LOCATIONS,
    ERR_SAMPLING_WINDOW_OVERLAP,
    ERR_LOCATION_NOT_FOUND,
)
from clock import parse_date
from services.core import (
    stamp_new,
    touch,
    get_engagement_or_404,
    recompute_engagement_derived,
)

bp = Blueprint("sampling", __name__)


def _get_sampling_or_404(sampling_id):
    s = db.sampling_requests.get(sampling_id)
    if s is None:
        raise ApiError(ERR_SAMPLING_NOT_FOUND, "SamplingRequest id not found", 404)
    return s


def _validate_window(window_start, window_end):
    try:
        start = parse_date(window_start)
        end = parse_date(window_end)
    except Exception:
        raise ApiError(
            ERR_INVALID_SAMPLING_WINDOW,
            "window_end must be > window_start",
            400,
        )
    if end <= start:
        raise ApiError(
            ERR_INVALID_SAMPLING_WINDOW,
            "window_end must be > window_start",
            400,
        )
    return start, end


@bp.route("/api/sampling-requests", methods=["POST"])
def create_sampling():
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    body = request.get_json(force=True, silent=True) or {}

    engagement_id = body.get("engagement_id")
    title = body.get("title")
    location_ids = body.get("location_ids")
    window_start = body.get("window_start")
    window_end = body.get("window_end")
    sample_size = body.get("sample_size")

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
    if not isinstance(title, str) or not title.strip():
        raise ApiError("ERR_VALIDATION", "title is required", 400)
    # Field shape validations (priority 9)
    if not isinstance(location_ids, list) or len(location_ids) == 0:
        raise ApiError(
            ERR_NO_SAMPLING_LOCATIONS,
            "location_ids array must be non-empty",
            400,
        )
    for lid in location_ids:
        if not isinstance(lid, str) or lid not in db.locations:
            raise ApiError(ERR_LOCATION_NOT_FOUND, "Location id not found", 404)
        loc = db.locations[lid]
        if loc["engagement_id"] != engagement_id:
            raise ApiError(
                ERR_LOCATION_NOT_FOUND,
                "Location does not belong to this engagement",
                404,
            )
    if not isinstance(window_start, str) or not window_start.strip():
        raise ApiError("ERR_VALIDATION", "window_start is required", 400)
    if not isinstance(window_end, str) or not window_end.strip():
        raise ApiError("ERR_VALIDATION", "window_end is required", 400)
    _validate_window(window_start, window_end)
    if (
        not isinstance(sample_size, int)
        or isinstance(sample_size, bool)
        or sample_size < 1
    ):
        raise ApiError(
            ERR_INVALID_SAMPLE_SIZE, "sample_size must be >= 1", 400
        )

    s = stamp_new(
        {
            "engagement_id": engagement_id,
            "title": title,
            "location_ids": list(location_ids),
            "window_start": window_start,
            "window_end": window_end,
            "sample_size": sample_size,
            "status": "DRAFT",
        }
    )
    db.sampling_requests[s["id"]] = s
    return success_object(dict(s), 201)


@bp.route("/api/sampling-requests", methods=["GET"])
def list_sampling():
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    limit, offset = parse_pagination()
    engagement_id = request.args.get("engagement_id")
    status = request.args.get("status")
    items = list(db.sampling_requests.values())
    if engagement_id:
        items = [s for s in items if s["engagement_id"] == engagement_id]
    if status:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([dict(s) for s in page], limit, offset, total)


@bp.route("/api/sampling-requests/<sampling_id>", methods=["GET"])
def get_sampling(sampling_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    s = _get_sampling_or_404(sampling_id)
    return success_object(dict(s))


@bp.route("/api/sampling-requests/<sampling_id>/dispatch", methods=["POST"])
def dispatch_sampling(sampling_id):
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    s = _get_sampling_or_404(sampling_id)
    eng = get_engagement_or_404(s["engagement_id"])
    recompute_engagement_derived(eng)
    if eng["posture"] == "LOCKED":
        raise ApiError(
            ERR_ENGAGEMENT_POSTURE_LOCKED,
            "Engagement posture is LOCKED; mutating endpoint forbidden",
            409,
        )
    if s["status"] != "DRAFT":
        raise ApiError(
            ERR_SAMPLING_NOT_DRAFT,
            "Dispatch requires SamplingRequest in DRAFT",
            409,
        )
    # Re-check window and location list
    start, end = _validate_window(s["window_start"], s["window_end"])
    if not s.get("location_ids"):
        raise ApiError(
            ERR_NO_SAMPLING_LOCATIONS,
            "location_ids array must be non-empty",
            400,
        )
    # Overlap check per location (half-open [start, end))
    for loc_id in s["location_ids"]:
        for other in db.sampling_requests.values():
            if other["id"] == s["id"]:
                continue
            if other["engagement_id"] != s["engagement_id"]:
                continue
            if other["status"] not in ("DISPATCHED", "IN_PROGRESS"):
                continue
            if loc_id not in other.get("location_ids", []):
                continue
            o_start = parse_date(other["window_start"])
            o_end = parse_date(other["window_end"])
            # Overlap if new.start < existing.end AND existing.start < new.end
            if start < o_end and o_start < end:
                raise ApiError(
                    ERR_SAMPLING_WINDOW_OVERLAP,
                    "New sampling window overlaps an existing DISPATCHED/IN_PROGRESS sampling request on the same location",
                    409,
                )
    s["status"] = "DISPATCHED"
    touch(s)
    return success_object(dict(s))


@bp.route("/api/sampling-requests/<sampling_id>/start", methods=["POST"])
def start_sampling(sampling_id):
    ctx = get_user_context()
    require_roles(ctx, ["Preparer"])
    s = _get_sampling_or_404(sampling_id)
    if s["status"] != "DISPATCHED":
        raise ApiError(
            ERR_SAMPLING_NOT_DISPATCHED,
            "Start requires SamplingRequest in DISPATCHED",
            409,
        )
    s["status"] = "IN_PROGRESS"
    touch(s)
    return success_object(dict(s))


@bp.route("/api/sampling-requests/<sampling_id>/complete", methods=["POST"])
def complete_sampling(sampling_id):
    ctx = get_user_context()
    require_roles(ctx, ["Preparer"])
    s = _get_sampling_or_404(sampling_id)
    if s["status"] != "IN_PROGRESS":
        raise ApiError(
            ERR_SAMPLING_NOT_IN_PROGRESS,
            "Complete requires SamplingRequest in IN_PROGRESS",
            409,
        )
    s["status"] = "COMPLETE"
    touch(s)
    return success_object(dict(s))


@bp.route("/api/sampling-requests/<sampling_id>/cancel", methods=["POST"])
def cancel_sampling(sampling_id):
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    s = _get_sampling_or_404(sampling_id)
    if s["status"] not in ("DRAFT", "DISPATCHED", "IN_PROGRESS"):
        raise ApiError(
            ERR_SAMPLING_NOT_CANCELLABLE,
            "Cancel requires SamplingRequest in DRAFT, DISPATCHED, or IN_PROGRESS",
            409,
        )
    s["status"] = "CANCELLED"
    touch(s)
    return success_object(dict(s))
