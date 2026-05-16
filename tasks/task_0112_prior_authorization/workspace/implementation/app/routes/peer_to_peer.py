"""Peer-to-peer review routes."""
from flask import Blueprint, g, jsonify

from ..auth import require_auth
from ..errors import APIError
from ..helpers import check_version, get_json_body, optional_field, require_field
from ..responses import success_response
from ..services.calculations import recompute_evidence_metrics
from ..services.lookups import get_authorization_or_404, get_peer_review_or_404
from ..services.serialize import serialize_p2p
from ..store import get_lock, stamp_update


bp = Blueprint("peer_to_peer", __name__)


VALID_P2P_OUTCOMES = {"UPHELD", "OVERTURNED", "NO_SHOW"}


def _ensure_provider_owns_for_p2p(auth: dict) -> None:
    if g.user_role == "Provider" and auth.get("provider_id") != g.user_id:
        raise APIError(
            "ERR_FORBIDDEN", "Provider does not own the parent authorization"
        )


@bp.get("/peer-to-peer-reviews/<p2p_id>")
@require_auth("PlatformAdmin", "Provider", "InitialReviewer", "PayerReviewer")
def get_p2p(p2p_id: str):
    p2p = get_peer_review_or_404(p2p_id)
    # Provider ownership: only the requesting provider may see their auth's p2p.
    if g.user_role == "Provider":
        auth = get_authorization_or_404(p2p["authorization_request_id"])
        _ensure_provider_owns_for_p2p(auth)
    body_out, status = success_response(serialize_p2p(p2p))
    return jsonify(body_out), status


@bp.post("/peer-to-peer-reviews/<p2p_id>/complete")
@require_auth("PayerReviewer")
def complete_p2p(p2p_id: str):
    with get_lock():
        p2p = get_peer_review_or_404(p2p_id)
        if p2p["status"] != "SCHEDULED":
            raise APIError(
                "ERR_INVALID_STATE", "PeerToPeerReview must be SCHEDULED to complete"
            )
        body = get_json_body()
        check_version(p2p, body.get("version"))

        outcome = require_field(body, "outcome")
        if outcome not in VALID_P2P_OUTCOMES:
            raise APIError(
                "ERR_INVALID_P2P_OUTCOME",
                f"outcome must be one of {sorted(VALID_P2P_OUTCOMES)}",
            )
        notes = optional_field(body, "notes", None)

        p2p["status"] = "COMPLETED"
        p2p["outcome"] = outcome
        if notes is not None:
            p2p["notes"] = notes
        stamp_update(p2p)

        # Cascade: parent PEER_REVIEW -> UNDER_REVIEW; recompute completeness if OVERTURNED.
        auth = get_authorization_or_404(p2p["authorization_request_id"])
        if auth["status"] == "PEER_REVIEW":
            auth["status"] = "UNDER_REVIEW"
        # Always recompute parent metrics so the post_p2p bonus reflects the
        # newly-completed review (variant: post_p2p when latest outcome=OVERTURNED).
        recompute_evidence_metrics(auth)
        stamp_update(auth)

    body_out, status = success_response(serialize_p2p(p2p))
    return jsonify(body_out), status


@bp.post("/peer-to-peer-reviews/<p2p_id>/cancel")
@require_auth("Provider", "PayerReviewer")
def cancel_p2p(p2p_id: str):
    with get_lock():
        p2p = get_peer_review_or_404(p2p_id)
        auth = get_authorization_or_404(p2p["authorization_request_id"])
        # Provider ownership.
        if g.user_role == "Provider" and auth.get("provider_id") != g.user_id:
            raise APIError(
                "ERR_FORBIDDEN", "Provider does not own the parent authorization"
            )
        if p2p["status"] != "SCHEDULED":
            raise APIError("ERR_INVALID_STATE", "Only SCHEDULED P2P may be cancelled")

        body = get_json_body()
        check_version(p2p, body.get("version"))

        p2p["status"] = "CANCELLED"
        stamp_update(p2p)

        # Revert parent: PEER_REVIEW -> UNDER_REVIEW.
        if auth["status"] == "PEER_REVIEW":
            auth["status"] = "UNDER_REVIEW"
            stamp_update(auth)

    body_out, status = success_response(serialize_p2p(p2p))
    return jsonify(body_out), status
