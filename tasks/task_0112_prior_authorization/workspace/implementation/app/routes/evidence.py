"""Clinical evidence routes (scoped under an authorization request)."""
from flask import Blueprint, g, jsonify, request

from ..auth import require_auth
from ..clock import clock_now_iso
from ..errors import APIError
from ..helpers import (
    get_json_body,
    get_pagination_params,
    optional_field,
    require_field,
)
from ..responses import list_response, success_response
from ..services.calculations import recompute_evidence_metrics
from ..services.lookups import get_authorization_or_404, get_evidence_or_404
from ..services.serialize import serialize_evidence
from ..store import get_lock, get_store, new_id, stamp_update


bp = Blueprint("evidence", __name__)


VALID_EVIDENCE_CATEGORIES = {"LAB", "IMAGING", "NOTES", "MED_HISTORY", "OTHER"}


def _ensure_provider_owns(auth: dict) -> None:
    if g.user_role == "Provider" and auth.get("provider_id") != g.user_id:
        raise APIError("ERR_FORBIDDEN", "Provider does not own this authorization")


@bp.post("/authorization-requests/<auth_id>/clinical-evidence")
@require_auth("Provider")
def attach_evidence(auth_id: str):
    with get_lock():
        auth = get_authorization_or_404(auth_id)
        _ensure_provider_owns(auth)

        body = get_json_body()
        category = require_field(body, "category")
        if category not in VALID_EVIDENCE_CATEGORIES:
            raise APIError(
                "ERR_VALIDATION",
                f"category must be one of {sorted(VALID_EVIDENCE_CATEGORIES)}",
            )
        title = require_field(body, "title")
        uri = require_field(body, "uri")
        byte_size = require_field(body, "byte_size")
        sourced_from_request_id = optional_field(body, "sourced_from_request_id", None)

        # Validation #11 — reuse must match prior_request_id.
        if sourced_from_request_id is not None:
            if auth.get("prior_request_id") != sourced_from_request_id:
                raise APIError(
                    "ERR_EVIDENCE_REUSE_MISMATCH",
                    "sourced_from_request_id must equal the authorization's prior_request_id",
                )

        # Validation #22 — byte_size.
        if (
            not isinstance(byte_size, int)
            or isinstance(byte_size, bool)
            or byte_size <= 0
            or byte_size > 50_000_000
        ):
            raise APIError(
                "ERR_EVIDENCE_SIZE_INVALID",
                "byte_size must be > 0 and <= 50,000,000",
            )

        store = get_store()

        # Validation #23 — uri unique among ATTACHED rows for this auth.
        for e in store.clinical_evidence.values():
            if e["authorization_request_id"] != auth["id"]:
                continue
            if e["status"] != "ATTACHED":
                continue
            if e["uri"] == uri:
                raise APIError(
                    "ERR_EVIDENCE_DUPLICATE_URI",
                    "An ATTACHED evidence row with this uri already exists for this authorization",
                )

        ev = {
            "id": new_id(),
            "authorization_request_id": auth["id"],
            "category": category,
            "title": title,
            "uri": uri,
            "byte_size": byte_size,
            "sourced_from_request_id": sourced_from_request_id,
            "status": "ATTACHED",
            "created_at": clock_now_iso(),
        }
        store.clinical_evidence[ev["id"]] = ev

        # Recompute parent metrics (reuse discount, then completeness).
        recompute_evidence_metrics(auth)
        stamp_update(auth)

    body_out, status = success_response(serialize_evidence(ev), status=201)
    return jsonify(body_out), status


@bp.get("/authorization-requests/<auth_id>/clinical-evidence")
@require_auth(
    "PlatformAdmin",
    "Provider",
    "InitialReviewer",
    "MedicalDirector",
    "ExternalReviewer",
    "PayerReviewer",
)
def list_evidence(auth_id: str):
    auth = get_authorization_or_404(auth_id)
    _ensure_provider_owns(auth)
    limit, offset = get_pagination_params()
    status_filter = request.args.get("status")
    category_filter = request.args.get("category")

    items = [
        e
        for e in get_store().clinical_evidence.values()
        if e["authorization_request_id"] == auth_id
    ]
    if status_filter is not None:
        items = [e for e in items if e["status"] == status_filter]
    if category_filter is not None:
        items = [e for e in items if e["category"] == category_filter]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    serialized = [serialize_evidence(e) for e in page]
    body_out, status = list_response(serialized, total=total, limit=limit, offset=offset)
    return jsonify(body_out), status


@bp.post("/authorization-requests/<auth_id>/clinical-evidence/<evidence_id>/withdraw")
@require_auth("Provider")
def withdraw_evidence(auth_id: str, evidence_id: str):
    with get_lock():
        # PRD §2.7: validate parent before child.
        auth = get_authorization_or_404(auth_id)
        _ensure_provider_owns(auth)
        ev = get_evidence_or_404(evidence_id)
        if ev["authorization_request_id"] != auth_id:
            # Evidence belongs to a different authorization → treat as not found
            # under this parent path.
            raise APIError("ERR_NOT_FOUND", "ClinicalEvidence not found under this authorization")
        if ev["status"] != "ATTACHED":
            raise APIError(
                "ERR_INVALID_STATE", "Only ATTACHED evidence may be withdrawn"
            )

        ev["status"] = "WITHDRAWN"
        # Evidence has no version/updated_at fields (PRD §2.4 exception).
        recompute_evidence_metrics(auth)
        stamp_update(auth)

    body_out, status = success_response(serialize_evidence(ev))
    return jsonify(body_out), status
