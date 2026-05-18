"""CollectionAction endpoints — creditor attempt insertion and per-case listing."""

from flask import Blueprint, g

from middleware import require_auth, parse_json_body
from response import success
from services.case_engine import create_collection_action, get_case_or_404
from services.serializers import serialize_collection_action
from db import store
from errors import make_error
from routes._helpers import parse_pagination, build_pagination_meta


collection_actions_bp = Blueprint("collection_actions", __name__)


@collection_actions_bp.post("/collection-actions")
@require_auth(allowed_roles=["Creditor"])
def create_collection_action_route():
    body = parse_json_body(required_fields=["creditor_id", "case_id", "action_kind"])
    with store.lock:
        row, rejected = create_collection_action(
            creditor_id=body["creditor_id"],
            case_id=body["case_id"],
            action_kind=body["action_kind"],
            acting_user_id=g.user_id,
        )
    if rejected:
        # The row is persisted but the response signals the violation. Echo
        # the persisted row inside the error envelope so callers can audit it
        # — but the surface response_type is "error" with the error_id.
        # Per priority-5: ERR_AUTOMATIC_STAY_VIOLATION (409).
        # The CollectionAction row is still queryable via GET listing.
        raise make_error(
            "ERR_AUTOMATIC_STAY_VIOLATION",
            f"Collection action rejected: case stay is active. action_id={row['id']}",
        )
    return success(serialize_collection_action(row), status=201)


@collection_actions_bp.get("/cases/<case_id>/collection-actions")
@require_auth(allowed_roles=["Trustee", "Judge", "Creditor"])
def list_collection_actions_route(case_id: str):
    case = get_case_or_404(case_id)
    limit, offset = parse_pagination()
    # Sort by created_at ascending per PRD §2.3 default sort.
    rows = [ca for ca in store.collection_actions.values() if ca["case_id"] == case["id"]]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    sliced = rows[offset : offset + limit]
    meta_extra = build_pagination_meta(limit, offset, total)
    return success([serialize_collection_action(r) for r in sliced], pagination=meta_extra)
