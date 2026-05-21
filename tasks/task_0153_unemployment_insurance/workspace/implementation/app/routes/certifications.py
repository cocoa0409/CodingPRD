"""WeeklyCertification routes."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import (
    ROLE_ADJUDICATOR,
    ROLE_APPEAL_OFFICER,
    ROLE_CLAIMANT,
    ROLE_SYSTEM_ADMIN,
    current_user_id,
    require_auth,
)
from ..envelope import paginate, parse_pagination, success_array, success_object
from ..errors import APIError
from ..serializers import serialize_certification
from ..services.entities import audit_certification, submit_weekly_certification
from ..store import get_store
from ..validators import (
    get_json_body,
    optional_int,
    require_bool,
    require_enum,
    require_int,
    require_list,
    require_string,
)
from ._helpers import lookup_certification, lookup_claim, require_claim_owner, sort_by_created_at

bp = Blueprint("certifications", __name__)


@bp.post("/claims/<claim_id>/weekly-certifications")
@require_auth([ROLE_CLAIMANT])
def cert_submit(claim_id: str):
    lookup_claim(claim_id)
    body = get_json_body()
    week_ending = require_string(body, "week_ending_date")
    earnings = require_int(body, "earnings_reported_cents", min_val=0)
    able = require_bool(body, "able_and_available")
    entries = require_list(body, "work_search_entries")
    cert = submit_weekly_certification(
        claim_id,
        current_user_id(),
        {
            "week_ending_date": week_ending,
            "earnings_reported_cents": earnings,
            "able_and_available": able,
            "work_search_entries": entries,
        },
    )
    return jsonify(success_object(serialize_certification(cert))), 201


@bp.get("/claims/<claim_id>/weekly-certifications")
@require_auth([ROLE_CLAIMANT, ROLE_ADJUDICATOR, ROLE_APPEAL_OFFICER, ROLE_SYSTEM_ADMIN])
def cert_list_for_claim(claim_id: str):
    cl = lookup_claim(claim_id)
    require_claim_owner(cl)
    status_filter = request.args.get("status")
    limit, offset = parse_pagination()
    store = get_store()
    items = [c for c in store.weekly_certifications.values() if c["claim_id"] == claim_id]
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return jsonify(success_array(
        [serialize_certification(c) for c in page],
        limit=limit, offset=offset, total_count=total,
    )), 200


@bp.get("/weekly-certifications/<cert_id>")
@require_auth([ROLE_CLAIMANT, ROLE_ADJUDICATOR, ROLE_APPEAL_OFFICER, ROLE_SYSTEM_ADMIN])
def cert_read(cert_id: str):
    cert = lookup_certification(cert_id)
    # Owner check (Claimant can only read certs on their own claims).
    store = get_store()
    claim = store.claims.get(cert["claim_id"])
    if claim is not None:
        require_claim_owner(claim)
    return jsonify(success_object(serialize_certification(cert))), 200


@bp.post("/weekly-certifications/<cert_id>/audit")
@require_auth([ROLE_ADJUDICATOR])
def cert_audit(cert_id: str):
    lookup_certification(cert_id)
    body = get_json_body()
    classification = require_enum(body, "classification", {"AGENCY_ERROR", "NON_FRAUD", "FRAUD"})
    reason = require_string(body, "reason")
    version = optional_int(body, "version", min_val=0)
    cert = audit_certification(cert_id, classification, reason, version)
    return jsonify(success_object(serialize_certification(cert))), 200
