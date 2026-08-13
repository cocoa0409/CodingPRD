"""RepresentationLetter endpoints."""
from flask import Blueprint, request
from db import db
from middleware import get_user_context, require_roles, parse_pagination
from response import success_object, success_list
from errors import (
    ApiError,
    ERR_REP_LETTER_NOT_FOUND,
    ERR_ENGAGEMENT_POSTURE_LOCKED,
    ERR_REP_LETTER_NOT_DRAFT,
    ERR_REP_LETTER_NOT_PENDING,
    ERR_REP_LETTER_SOD_VIOLATION,
    ERR_ENGAGEMENT_NOT_CLOSING,
    ERR_STALE_ENGAGEMENT_VERSION,
)
from clock import clock, format_iso
from services.core import (
    stamp_new,
    touch,
    get_engagement_or_404,
    recompute_engagement_derived,
    rep_letter_for_engagement,
    cascade_rep_letter_signed,
)

bp = Blueprint("rep_letters", __name__)


def _get_letter_or_404(letter_id):
    letter = db.representation_letters.get(letter_id)
    if letter is None:
        raise ApiError(
            ERR_REP_LETTER_NOT_FOUND, "RepresentationLetter id not found", 404
        )
    return letter


@bp.route("/api/representation-letters", methods=["POST"])
def create_letter():
    ctx = get_user_context()
    require_roles(ctx, ["Preparer"])
    body = request.get_json(force=True, silent=True) or {}
    engagement_id = body.get("engagement_id")
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
    letter = stamp_new(
        {
            "engagement_id": engagement_id,
            "prepared_by_user_id": None,
            "signed_by_user_id": None,
            "signed_at": None,
            "status": "DRAFT",
        }
    )
    db.representation_letters[letter["id"]] = letter
    return success_object(dict(letter), 201)


@bp.route("/api/representation-letters", methods=["GET"])
def list_letters():
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    limit, offset = parse_pagination()
    engagement_id = request.args.get("engagement_id")
    items = list(db.representation_letters.values())
    if engagement_id:
        items = [l for l in items if l["engagement_id"] == engagement_id]
    items.sort(key=lambda l: l["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([dict(l) for l in page], limit, offset, total)


@bp.route("/api/representation-letters/<letter_id>", methods=["GET"])
def get_letter(letter_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller", "Preparer", "ExternalAuditor"])
    letter = _get_letter_or_404(letter_id)
    return success_object(dict(letter))


@bp.route("/api/representation-letters/<letter_id>/submit", methods=["POST"])
def submit_letter(letter_id):
    ctx = get_user_context()
    require_roles(ctx, ["Preparer"])
    letter = _get_letter_or_404(letter_id)
    eng = get_engagement_or_404(letter["engagement_id"])
    recompute_engagement_derived(eng)
    # Priority 4: posture lock
    if eng["posture"] == "LOCKED":
        raise ApiError(
            ERR_ENGAGEMENT_POSTURE_LOCKED,
            "Engagement posture is LOCKED; mutating endpoint forbidden",
            409,
        )
    # Priority 5: state
    if letter["status"] != "DRAFT":
        raise ApiError(
            ERR_REP_LETTER_NOT_DRAFT,
            "Submit requires RepresentationLetter in DRAFT",
            409,
        )
    if eng["status"] != "FIELDWORK_COMPLETE":
        raise ApiError(
            ERR_ENGAGEMENT_NOT_CLOSING,
            "Submit requires engagement in FIELDWORK_COMPLETE",
            409,
        )
    letter["prepared_by_user_id"] = ctx.user_id
    letter["status"] = "PENDING_SIGNATURE"
    touch(letter)
    return success_object(dict(letter))


@bp.route("/api/representation-letters/<letter_id>/sign", methods=["POST"])
def sign_letter(letter_id):
    ctx = get_user_context()
    require_roles(ctx, ["Controller"])
    letter = _get_letter_or_404(letter_id)
    eng = get_engagement_or_404(letter["engagement_id"])
    recompute_engagement_derived(eng)
    # Priority 5: state
    if letter["status"] != "PENDING_SIGNATURE":
        raise ApiError(
            ERR_REP_LETTER_NOT_PENDING,
            "Sign requires RepresentationLetter in PENDING_SIGNATURE",
            409,
        )
    # Priority 6: SoD
    if ctx.user_id == letter.get("prepared_by_user_id"):
        raise ApiError(
            ERR_REP_LETTER_SOD_VIOLATION,
            "RepresentationLetter signer must differ from prepared_by_user_id",
            403,
        )
    # Priority 15: OCC
    body = request.get_json(force=True, silent=True) or {}
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

    letter["signed_by_user_id"] = ctx.user_id
    letter["signed_at"] = format_iso(clock.now())
    letter["status"] = "SIGNED"
    touch(letter)
    # Cascades: freeze PBC, invalidate pending evidence, withdraw proposed fee changes
    cascade_rep_letter_signed(eng)
    # Bump engagement version (sign increments parent engagement version)
    touch(eng)
    recompute_engagement_derived(eng)
    return success_object(dict(letter))
