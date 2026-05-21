"""/foia/exemption-claims — immutable exemption assertions."""

from __future__ import annotations

from flask import Blueprint, g, request as flask_request

from ..auth import require_auth
from ..envelope import ok_array, ok_object
from ..errors import (
    ApiError,
    ERR_DUPLICATE_EXEMPTION,
    ERR_FK_NOT_FOUND,
    ERR_INVALID_STATE,
)
from ..serializers import serialize_exemption_claim
from ..store import append_audit, store
from ..util import (
    get_pagination,
    paginate,
    require_enum,
    require_json_body,
    require_str,
)


exemption_claims_bp = Blueprint("exemption_claims", __name__)

EXEMPTION_CODES = ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9")
REDACTION_SCOPES = ("FULL", "PARTIAL")


@exemption_claims_bp.post("/foia/exemption-claims")
@require_auth({"Officer"})
def create_claim():
    payload = require_json_body()
    record_id = require_str(payload, "record_id", max_len=200)
    exemption_code = require_enum(payload, "exemption_code", EXEMPTION_CODES)
    redaction_scope = require_enum(payload, "redaction_scope", REDACTION_SCOPES)
    rationale = require_str(payload, "rationale", max_len=1000)

    record = store.responsive_records.get(record_id)
    if record is None:
        raise ApiError(ERR_FK_NOT_FOUND, 404, "Referenced record does not exist.")
    if record["disposition"] != "PENDING_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "ExemptionClaim allowed only on PENDING_REVIEW records.",
        )

    with store.lock:
        # Duplicate (record_id, exemption_code) check.
        for c in store.exemption_claims.values():
            if c["record_id"] == record_id and c["exemption_code"] == exemption_code:
                raise ApiError(
                    ERR_DUPLICATE_EXEMPTION,
                    409,
                    "Duplicate exemption code on this record.",
                )

        entity = {
            "record_id": record_id,
            "exemption_code": exemption_code,
            "redaction_scope": redaction_scope,
            "rationale": rationale,
        }
        store.stamp_create(entity, versioned=False)
        store.exemption_claims[entity["id"]] = entity
        append_audit(
            subject_type="REQUEST",
            subject_id=record["request_id"],
            event_code="EXEMPTION_CLAIMED",
            actor_role=g.user_role,
            actor_id=g.user_id,
            payload={
                "record_id": record_id,
                "exemption_code": exemption_code,
                "redaction_scope": redaction_scope,
            },
        )
    return ok_object(serialize_exemption_claim(entity), status=201)


@exemption_claims_bp.get("/foia/exemption-claims")
@require_auth({"Officer", "AppealAuthority", "Requester"})
def list_claims():
    limit, offset = get_pagination()
    rec_filter = flask_request.args.get("record_id")
    code_filter = flask_request.args.get("exemption_code")
    items = list(store.exemption_claims.values())
    if rec_filter:
        items = [c for c in items if c["record_id"] == rec_filter]
    if code_filter:
        items = [c for c in items if c["exemption_code"] == code_filter]
    items.sort(key=lambda c: c["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    return ok_array(
        [serialize_exemption_claim(c) for c in page],
        limit=limit,
        offset=offset,
        total_count=total,
        has_more=has_more,
    )
