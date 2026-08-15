"""AuditorQuery endpoints."""
import math
from flask import Blueprint, request
from db import db
from middleware import get_user_context, require_roles, parse_pagination
from response import success_object, success_list
from errors import (
    ApiError,
    ERR_QUERY_NOT_FOUND,
    ERR_ENGAGEMENT_POSTURE_LOCKED,
    ERR_QUERY_NOT_OPEN,
    ERR_QUERY_NOT_AWAITING_CLIENT,
    ERR_QUERY_NOT_CLOSABLE,
    ERR_NOT_REQUEST_OWNER,
)
from clock import clock, format_iso, parse_iso
from services.core import (
    stamp_new,
    touch,
    get_engagement_or_404,
    recompute_engagement_derived,
)

bp = Blueprint("queries", __name__)

_VALID_SEVERITIES = ("LOW", "MEDIUM", "HIGH")


def _get_query_or_404(query_id):
    q = db.queries.get(query_id)
    if q is None:
        raise ApiError(ERR_QUERY_NOT_FOUND, "AuditorQuery id not found", 404)
    return q


@bp.route("/api/queries", methods=["POST"])
def create_query():
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    body = request.get_json(force=True, silent=True) or {}

    engagement_id = body.get("engagement_id")
    subject = body.get("subject")
    severity = body.get("severity")
    pbc_request_id = body.get("pbc_request_id")

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
    if not isinstance(subject, str) or not subject.strip():
        raise ApiError("ERR_VALIDATION", "subject is required", 400)
    if severity not in _VALID_SEVERITIES:
        raise ApiError("ERR_VALIDATION", "severity must be LOW, MEDIUM, or HIGH", 400)
    if pbc_request_id is not None:
        if not isinstance(pbc_request_id, str):
            raise ApiError("ERR_VALIDATION", "pbc_request_id must be a string", 400)
        if pbc_request_id not in db.pbc_requests:
            raise ApiError("ERR_VALIDATION", "pbc_request_id not found", 400)

    q = stamp_new(
        {
            "engagement_id": engagement_id,
            "pbc_request_id": pbc_request_id,
            "auditor_user_id": ctx.user_id,
            "subject": subject,
            "severity": severity,
            "raised_at": format_iso(clock.now()),
            "responded_at": None,
            "turnaround_hours": None,
            "status": "OPEN",
        }
    )
    db.queries[q["id"]] = q
    recompute_engagement_derived(eng)
    return success_object(dict(q), 201)


@bp.route("/api/queries", methods=["GET"])
def list_queries():
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    limit, offset = parse_pagination()
    engagement_id = request.args.get("engagement_id")
    status = request.args.get("status")
    items = list(db.queries.values())
    if engagement_id:
        items = [q for q in items if q["engagement_id"] == engagement_id]
    if status:
        items = [q for q in items if q["status"] == status]
    items.sort(key=lambda q: q["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([dict(q) for q in page], limit, offset, total)


@bp.route("/api/queries/<query_id>", methods=["GET"])
def get_query(query_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    q = _get_query_or_404(query_id)
    return success_object(dict(q))


@bp.route("/api/queries/<query_id>/route-to-client", methods=["POST"])
def route_to_client(query_id):
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    q = _get_query_or_404(query_id)
    if q["status"] != "OPEN":
        raise ApiError(
            ERR_QUERY_NOT_OPEN,
            "Route-to-client requires AuditorQuery in OPEN",
            409,
        )
    q["status"] = "AWAITING_CLIENT"
    touch(q)
    eng = db.engagements.get(q["engagement_id"])
    if eng:
        recompute_engagement_derived(eng)
    return success_object(dict(q))


@bp.route("/api/queries/<query_id>/respond", methods=["POST"])
def respond_query(query_id):
    ctx = get_user_context()
    require_roles(ctx, ["Preparer"])
    q = _get_query_or_404(query_id)
    if q["status"] != "AWAITING_CLIENT":
        raise ApiError(
            ERR_QUERY_NOT_AWAITING_CLIENT,
            "Respond requires AuditorQuery in AWAITING_CLIENT",
            409,
        )
    # Ownership: if pbc_request_id set, responder must equal that PBC owner
    if q.get("pbc_request_id"):
        pbc = db.pbc_requests.get(q["pbc_request_id"])
        if pbc is not None and ctx.user_id != pbc["owner_user_id"]:
            raise ApiError(
                ERR_NOT_REQUEST_OWNER,
                "X-User-ID does not match PBCRequest.owner_user_id",
                403,
            )
    body = request.get_json(force=True, silent=True) or {}
    response_text = body.get("response_text")
    if not isinstance(response_text, str) or not response_text.strip():
        raise ApiError("ERR_VALIDATION", "response_text is required", 400)

    responded_at = clock.now()
    q["responded_at"] = format_iso(responded_at)
    raised_dt = parse_iso(q["raised_at"])
    elapsed_seconds = (responded_at - raised_dt).total_seconds()
    # Ceiling division; exact-on-the-hour returns the hour count
    hours = math.ceil(elapsed_seconds / 3600.0)
    # Guard against floating-point drift on exact boundaries
    if abs((elapsed_seconds / 3600.0) - round(elapsed_seconds / 3600.0)) < 1e-9:
        hours = int(round(elapsed_seconds / 3600.0))
    q["turnaround_hours"] = int(hours)
    q["status"] = "RESPONDED"
    touch(q)
    eng = db.engagements.get(q["engagement_id"])
    if eng:
        recompute_engagement_derived(eng)
    return success_object(dict(q))


@bp.route("/api/queries/<query_id>/escalate", methods=["POST"])
def escalate_query(query_id):
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    q = _get_query_or_404(query_id)
    if q["status"] not in ("OPEN", "AWAITING_CLIENT"):
        raise ApiError(
            ERR_QUERY_NOT_OPEN,
            "Escalate requires AuditorQuery in OPEN or AWAITING_CLIENT",
            409,
        )
    q["status"] = "ESCALATED"
    touch(q)
    eng = db.engagements.get(q["engagement_id"])
    if eng:
        recompute_engagement_derived(eng)
    return success_object(dict(q))


@bp.route("/api/queries/<query_id>/close", methods=["POST"])
def close_query(query_id):
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    q = _get_query_or_404(query_id)
    if q["status"] not in ("RESPONDED", "ESCALATED"):
        raise ApiError(
            ERR_QUERY_NOT_CLOSABLE,
            "Close requires AuditorQuery in RESPONDED or ESCALATED",
            409,
        )
    q["status"] = "CLOSED"
    touch(q)
    eng = db.engagements.get(q["engagement_id"])
    if eng:
        recompute_engagement_derived(eng)
    return success_object(dict(q))
