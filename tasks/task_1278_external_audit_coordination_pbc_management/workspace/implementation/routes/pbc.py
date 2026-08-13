"""PBCRequest endpoints (including evidence upload and review)."""
import re
from flask import Blueprint, request
from db import db
from middleware import get_user_context, require_roles, parse_pagination
from response import success_object, success_list
from errors import (
    ApiError,
    ERR_PBC_NOT_FOUND,
    ERR_ENGAGEMENT_POSTURE_LOCKED,
    ERR_PBC_NOT_OPEN_FOR_UPLOAD,
    ERR_PBC_NOT_SUBMITTABLE,
    ERR_PBC_NOT_UNDER_REVIEW,
    ERR_NO_PENDING_EVIDENCE,
    ERR_NOT_REQUEST_OWNER,
    ERR_INVALID_EVIDENCE_FILE,
    ERR_INVALID_HASH,
    ERR_DEADLINE_AFTER_FILING,
    ERR_STALE_ENGAGEMENT_VERSION,
    ERR_ENGAGEMENT_NOT_IN_FIELDWORK,
)
from clock import clock, format_iso, parse_date
from services.core import (
    stamp_new,
    touch,
    get_engagement_or_404,
    recompute_engagement_derived,
    pbc_view_with_aging,
)

bp = Blueprint("pbc", __name__)

MAX_EVIDENCE_BYTES = 100 * 1024 * 1024  # 100 MiB cap for evidence uploads
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _get_pbc_or_404(pbc_id):
    pbc = db.pbc_requests.get(pbc_id)
    if pbc is None:
        raise ApiError(ERR_PBC_NOT_FOUND, "PBCRequest id not found", 404)
    return pbc


@bp.route("/api/pbc-requests", methods=["POST"])
def create_pbc():
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    body = request.get_json(force=True, silent=True) or {}

    engagement_id = body.get("engagement_id")
    title = body.get("title")
    owner_user_id = body.get("owner_user_id")
    due_date = body.get("due_date")

    if not isinstance(engagement_id, str) or not engagement_id.strip():
        raise ApiError("ERR_VALIDATION", "engagement_id is required", 400)
    eng = get_engagement_or_404(engagement_id)
    recompute_engagement_derived(eng)
    # Priority 4: posture lock
    if eng["posture"] == "LOCKED":
        raise ApiError(
            ERR_ENGAGEMENT_POSTURE_LOCKED,
            "Engagement posture is LOCKED; mutating endpoint forbidden",
            409,
        )
    if not isinstance(title, str) or not title.strip():
        raise ApiError("ERR_VALIDATION", "title is required", 400)
    if not isinstance(owner_user_id, str) or not owner_user_id.strip():
        raise ApiError("ERR_VALIDATION", "owner_user_id is required", 400)
    if not isinstance(due_date, str) or not due_date.strip():
        raise ApiError("ERR_VALIDATION", "due_date is required", 400)
    # Priority 14: deadline alignment
    try:
        due = parse_date(due_date)
        filing = parse_date(eng["filing_deadline"])
    except Exception:
        raise ApiError("ERR_VALIDATION", "due_date must be YYYY-MM-DD", 400)
    if due > filing:
        raise ApiError(
            ERR_DEADLINE_AFTER_FILING,
            "PBCRequest.due_date must be on or before engagement.filing_deadline",
            422,
        )

    pbc = stamp_new(
        {
            "engagement_id": engagement_id,
            "title": title,
            "owner_user_id": owner_user_id,
            "due_date": due_date,
            "current_evidence_id": None,
            "rejection_count": 0,
            "status": "OPEN",
        }
    )
    db.pbc_requests[pbc["id"]] = pbc
    recompute_engagement_derived(eng)
    return success_object(pbc_view_with_aging(pbc), 201)


@bp.route("/api/pbc-requests", methods=["GET"])
def list_pbc():
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    limit, offset = parse_pagination()
    engagement_id = request.args.get("engagement_id")
    status = request.args.get("status")
    items = list(db.pbc_requests.values())
    if engagement_id:
        items = [p for p in items if p["engagement_id"] == engagement_id]
    if status:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([pbc_view_with_aging(p) for p in page], limit, offset, total)


@bp.route("/api/pbc-requests/<pbc_id>", methods=["GET"])
def get_pbc(pbc_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    pbc = _get_pbc_or_404(pbc_id)
    return success_object(pbc_view_with_aging(pbc))


@bp.route("/api/pbc-requests/<pbc_id>/submit", methods=["POST"])
def submit_pbc(pbc_id):
    ctx = get_user_context()
    require_roles(ctx, ["Preparer"])
    pbc = _get_pbc_or_404(pbc_id)
    eng = get_engagement_or_404(pbc["engagement_id"])
    recompute_engagement_derived(eng)
    # Priority 4: posture lock
    if eng["posture"] == "LOCKED":
        raise ApiError(
            ERR_ENGAGEMENT_POSTURE_LOCKED,
            "Engagement posture is LOCKED; mutating endpoint forbidden",
            409,
        )
    # Priority 5: state
    if pbc["status"] != "IN_PROGRESS":
        raise ApiError(
            ERR_PBC_NOT_SUBMITTABLE,
            "Submit requires PBCRequest in IN_PROGRESS",
            409,
        )
    # Priority 8: ownership
    if ctx.user_id != pbc["owner_user_id"]:
        raise ApiError(
            ERR_NOT_REQUEST_OWNER,
            "X-User-ID does not match PBCRequest.owner_user_id",
            403,
        )
    has_pending = any(
        e["pbc_request_id"] == pbc_id and e["status"] == "PENDING_REVIEW"
        for e in db.evidence_uploads.values()
    )
    if not has_pending:
        raise ApiError(
            ERR_NO_PENDING_EVIDENCE,
            "Submit requires at least one PENDING_REVIEW EvidenceUpload",
            409,
        )
    pbc["status"] = "SUBMITTED"
    touch(pbc)
    recompute_engagement_derived(eng)
    return success_object(pbc_view_with_aging(pbc))


@bp.route("/api/pbc-requests/<pbc_id>/review", methods=["POST"])
def review_pbc(pbc_id):
    ctx = get_user_context()
    require_roles(ctx, ["ExternalAuditor"])
    pbc = _get_pbc_or_404(pbc_id)
    eng = get_engagement_or_404(pbc["engagement_id"])
    recompute_engagement_derived(eng)
    # Priority 4: posture lock
    if eng["posture"] == "LOCKED":
        raise ApiError(
            ERR_ENGAGEMENT_POSTURE_LOCKED,
            "Engagement posture is LOCKED; mutating endpoint forbidden",
            409,
        )
    # Priority 5: state
    if pbc["status"] != "SUBMITTED":
        raise ApiError(
            ERR_PBC_NOT_UNDER_REVIEW,
            "Review requires PBCRequest in SUBMITTED",
            409,
        )
    body = request.get_json(force=True, silent=True) or {}
    decision = body.get("decision")
    if decision == "ACCEPT":
        # All PENDING_REVIEW -> ACCEPTED
        latest_accepted_id = None
        latest_seq = -1
        for e in db.evidence_uploads.values():
            if e["pbc_request_id"] == pbc_id and e["status"] == "PENDING_REVIEW":
                e["status"] = "ACCEPTED"
                touch(e)
                if e["version_seq"] > latest_seq:
                    latest_seq = e["version_seq"]
                    latest_accepted_id = e["id"]
        # Prior ACCEPTED -> SUPERSEDED (keep only latest)
        for e in db.evidence_uploads.values():
            if (
                e["pbc_request_id"] == pbc_id
                and e["status"] == "ACCEPTED"
                and e["id"] != latest_accepted_id
            ):
                e["status"] = "SUPERSEDED"
                touch(e)
        pbc["current_evidence_id"] = latest_accepted_id
        pbc["rejection_count"] = 0
        pbc["status"] = "ACCEPTED"
        touch(pbc)
    elif decision == "REJECT":
        for e in db.evidence_uploads.values():
            if e["pbc_request_id"] == pbc_id and e["status"] == "PENDING_REVIEW":
                e["status"] = "REJECTED"
                touch(e)
        pbc["rejection_count"] = pbc.get("rejection_count", 0) + 1
        pbc["status"] = "REJECTED"
        touch(pbc)
    else:
        raise ApiError("ERR_VALIDATION", "decision must be ACCEPT or REJECT", 400)
    recompute_engagement_derived(eng)
    return success_object(pbc_view_with_aging(pbc))


@bp.route("/api/pbc-requests/<pbc_id>/evidence-uploads", methods=["POST"])
def upload_evidence(pbc_id):
    ctx = get_user_context()
    require_roles(ctx, ["Preparer"])
    pbc = _get_pbc_or_404(pbc_id)
    eng = get_engagement_or_404(pbc["engagement_id"])
    recompute_engagement_derived(eng)
    # Priority 4: posture lock
    if eng["posture"] == "LOCKED":
        raise ApiError(
            ERR_ENGAGEMENT_POSTURE_LOCKED,
            "Engagement posture is LOCKED; mutating endpoint forbidden",
            409,
        )
    # Priority 5: state
    if pbc["status"] not in ("OPEN", "REJECTED"):
        raise ApiError(
            ERR_PBC_NOT_OPEN_FOR_UPLOAD,
            "Evidence upload requires PBCRequest in OPEN or REJECTED",
            409,
        )
    if eng["status"] != "FIELDWORK":
        raise ApiError(
            ERR_ENGAGEMENT_NOT_IN_FIELDWORK,
            "Operation requires engagement in FIELDWORK",
            409,
        )
    # Priority 8: ownership
    if ctx.user_id != pbc["owner_user_id"]:
        raise ApiError(
            ERR_NOT_REQUEST_OWNER,
            "X-User-ID does not match PBCRequest.owner_user_id",
            403,
        )
    # Priority 9: field shape
    body = request.get_json(force=True, silent=True) or {}
    file_name = body.get("file_name")
    file_size_bytes = body.get("file_size_bytes")
    sha256 = body.get("sha256")
    if not isinstance(file_name, str) or not file_name.strip():
        raise ApiError("ERR_VALIDATION", "file_name is required", 400)
    if (
        not isinstance(file_size_bytes, int)
        or isinstance(file_size_bytes, bool)
        or file_size_bytes <= 0
        or file_size_bytes > MAX_EVIDENCE_BYTES
    ):
        raise ApiError(
            ERR_INVALID_EVIDENCE_FILE,
            "file_size_bytes out of range (0, MAX_EVIDENCE_BYTES]",
            400,
        )
    if not isinstance(sha256, str) or not _SHA256_RE.match(sha256):
        raise ApiError(
            ERR_INVALID_HASH,
            "sha256 must be 64 lowercase hex characters",
            400,
        )
    # Priority 15: OCC
    expected_engagement_version = body.get("expected_engagement_version")
    if expected_engagement_version is None:
        raise ApiError(
            ERR_STALE_ENGAGEMENT_VERSION,
            "expected_engagement_version is required",
            412,
        )
    if expected_engagement_version != eng["version"]:
        raise ApiError(
            ERR_STALE_ENGAGEMENT_VERSION,
            "expected_engagement_version does not match current engagement.version",
            412,
        )

    # Create evidence
    max_seq = 0
    for e in db.evidence_uploads.values():
        if e["pbc_request_id"] == pbc_id and e["version_seq"] > max_seq:
            max_seq = e["version_seq"]
    ev = stamp_new(
        {
            "pbc_request_id": pbc_id,
            "engagement_id": pbc["engagement_id"],
            "uploader_user_id": ctx.user_id,
            "version_seq": max_seq + 1,
            "file_name": file_name,
            "file_size_bytes": file_size_bytes,
            "sha256": sha256,
            "uploaded_at": format_iso(clock.now()),
            "status": "PENDING_REVIEW",
        }
    )
    db.evidence_uploads[ev["id"]] = ev
    pbc["status"] = "IN_PROGRESS"
    touch(pbc)
    # Bump engagement version (upload increments parent engagement version)
    touch(eng)
    recompute_engagement_derived(eng)
    return success_object(dict(ev), 201)
