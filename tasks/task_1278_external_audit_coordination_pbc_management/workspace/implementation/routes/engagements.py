"""AuditEngagement endpoints."""
from flask import Blueprint, request
from db import db
from middleware import get_user_context, require_roles, parse_pagination
from response import success_object, success_list
from errors import (
    ApiError,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_ENGAGEMENT_NOT_IN_PLANNING,
    ERR_ENGAGEMENT_NOT_IN_FIELDWORK,
    ERR_ENGAGEMENT_NOT_CLOSING,
    ERR_ENGAGEMENT_NOT_CANCELLABLE,
    ERR_NO_LOCATIONS_DEFINED,
    ERR_UNRESOLVED_PBC_REQUESTS,
    ERR_UNRESOLVED_QUERIES,
    ERR_REP_LETTER_NOT_SIGNED,
    ERR_PASSED_ADJUSTMENTS_EXCEED_MATERIALITY,
)
from services.core import (
    stamp_new,
    touch,
    get_engagement_or_404,
    recompute_engagement_derived,
    rep_letter_for_engagement,
    cascade_engagement_cancelled,
    engagement_view,
)

bp = Blueprint("engagements", __name__)


def _validate_positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


@bp.route("/api/audit-engagements", methods=["POST"])
def create_engagement():
    ctx = get_user_context()
    require_roles(ctx, ["Controller"])
    body = request.get_json(force=True, silent=True) or {}

    client_name = body.get("client_name")
    fiscal_year_end = body.get("fiscal_year_end")
    base_fee_cents = body.get("base_fee_cents")
    materiality_cents = body.get("materiality_cents")
    filing_deadline = body.get("filing_deadline")

    # Field-shape validation (priority 9 family, generic 400)
    if not isinstance(client_name, str) or not client_name.strip():
        raise ApiError("ERR_VALIDATION", "client_name is required", 400)
    if not isinstance(fiscal_year_end, str) or not fiscal_year_end.strip():
        raise ApiError("ERR_VALIDATION", "fiscal_year_end is required", 400)
    if not _validate_positive_int(base_fee_cents):
        raise ApiError("ERR_VALIDATION", "base_fee_cents must be > 0", 400)
    if not _validate_positive_int(materiality_cents):
        raise ApiError("ERR_VALIDATION", "materiality_cents must be > 0", 400)
    if not isinstance(filing_deadline, str) or not filing_deadline.strip():
        raise ApiError("ERR_VALIDATION", "filing_deadline is required", 400)

    eng = stamp_new(
        {
            "client_name": client_name,
            "fiscal_year_end": fiscal_year_end,
            "base_fee_cents": base_fee_cents,
            "materiality_cents": materiality_cents,
            "filing_deadline": filing_deadline,
            "status": "PLANNING",
            "total_fee_cents": base_fee_cents,
            "open_pbc_count": 0,
            "open_query_count": 0,
            "passed_adjustment_total_cents": 0,
            "posture": "OPEN",
        }
    )
    db.engagements[eng["id"]] = eng
    return success_object(engagement_view(eng), 201)


@bp.route("/api/audit-engagements", methods=["GET"])
def list_engagements():
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    limit, offset = parse_pagination()
    items = sorted(db.engagements.values(), key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([engagement_view(e) for e in page], limit, offset, total)


@bp.route("/api/audit-engagements/<engagement_id>", methods=["GET"])
def get_engagement(engagement_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    eng = get_engagement_or_404(engagement_id)
    return success_object(engagement_view(eng))


@bp.route("/api/audit-engagements/<engagement_id>/commence-fieldwork", methods=["POST"])
def commence_fieldwork(engagement_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller"])
    eng = get_engagement_or_404(engagement_id)
    if eng["status"] != "PLANNING":
        raise ApiError(
            ERR_ENGAGEMENT_NOT_IN_PLANNING,
            "commence-fieldwork requires engagement in PLANNING",
            409,
        )
    has_location = any(
        loc["engagement_id"] == engagement_id for loc in db.locations.values()
    )
    if not has_location:
        raise ApiError(
            ERR_NO_LOCATIONS_DEFINED,
            "commence-fieldwork requires at least one Location",
            409,
        )
    eng["status"] = "FIELDWORK"
    touch(eng)
    recompute_engagement_derived(eng)
    return success_object(engagement_view(eng))


@bp.route("/api/audit-engagements/<engagement_id>/complete-fieldwork", methods=["POST"])
def complete_fieldwork(engagement_id):
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    eng = get_engagement_or_404(engagement_id)
    if eng["status"] != "FIELDWORK":
        raise ApiError(
            ERR_ENGAGEMENT_NOT_IN_FIELDWORK,
            "complete-fieldwork requires engagement in FIELDWORK",
            409,
        )
    unresolved_pbc = any(
        p["engagement_id"] == engagement_id
        and p["status"] in ("OPEN", "IN_PROGRESS", "SUBMITTED", "REJECTED")
        for p in db.pbc_requests.values()
    )
    if unresolved_pbc:
        raise ApiError(
            ERR_UNRESOLVED_PBC_REQUESTS,
            "complete-fieldwork requires zero unresolved PBC requests",
            409,
        )
    unresolved_queries = any(
        q["engagement_id"] == engagement_id
        and q["status"] in ("OPEN", "AWAITING_CLIENT", "ESCALATED")
        for q in db.queries.values()
    )
    if unresolved_queries:
        raise ApiError(
            ERR_UNRESOLVED_QUERIES,
            "complete-fieldwork requires zero unresolved queries",
            409,
        )
    eng["status"] = "FIELDWORK_COMPLETE"
    touch(eng)
    recompute_engagement_derived(eng)
    return success_object(engagement_view(eng))


@bp.route("/api/audit-engagements/<engagement_id>/issue-report", methods=["POST"])
def issue_report(engagement_id):
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    eng = get_engagement_or_404(engagement_id)
    if eng["status"] != "FIELDWORK_COMPLETE":
        raise ApiError(
            ERR_ENGAGEMENT_NOT_CLOSING,
            "issue-report requires engagement in FIELDWORK_COMPLETE",
            409,
        )
    letter = rep_letter_for_engagement(engagement_id)
    if letter is None or letter["status"] != "SIGNED":
        raise ApiError(
            ERR_REP_LETTER_NOT_SIGNED,
            "issue-report requires RepresentationLetter.status == SIGNED",
            409,
        )
    recompute_engagement_derived(eng)
    if eng["passed_adjustment_total_cents"] >= eng["materiality_cents"]:
        raise ApiError(
            ERR_PASSED_ADJUSTMENTS_EXCEED_MATERIALITY,
            "passed_adjustment_total_cents must be strictly less than materiality_cents",
            402,
        )
    eng["status"] = "REPORT_ISSUED"
    touch(eng)
    recompute_engagement_derived(eng)
    return success_object(engagement_view(eng))


@bp.route("/api/audit-engagements/<engagement_id>/cancel", methods=["POST"])
def cancel_engagement(engagement_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller"])
    eng = get_engagement_or_404(engagement_id)
    if eng["status"] not in ("PLANNING", "FIELDWORK"):
        raise ApiError(
            ERR_ENGAGEMENT_NOT_CANCELLABLE,
            "Cancel requires PLANNING or FIELDWORK",
            409,
        )
    eng["status"] = "CANCELLED"
    cascade_engagement_cancelled(eng)
    touch(eng)
    recompute_engagement_derived(eng)
    return success_object(engagement_view(eng))
