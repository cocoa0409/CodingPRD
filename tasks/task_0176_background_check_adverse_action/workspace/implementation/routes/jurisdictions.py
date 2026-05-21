"""Routes: /fcra/jurisdiction-policies*."""
from __future__ import annotations

from flask import Blueprint

from core.auth import require_roles
from core.envelope import get_json_body, success_response
from core.pagination import paginate, parse_pagination
from core.serializers import serialize_jurisdiction
from core.store import store
from core.utils import lock
from services.jurisdiction_service import upsert_jurisdiction


bp = Blueprint("jurisdictions", __name__)


@bp.route("/fcra/jurisdiction-policies", methods=["GET"])
@require_roles("Recruiter", "Adjudicator", "PlatformAdmin")
def list_jurisdictions():
    limit, offset = parse_pagination()
    rows = sorted(
        store.jurisdiction_policies.values(),
        key=lambda r: r["created_at"],
    )
    sliced, pmeta = paginate(rows, limit, offset)
    return success_response(
        [serialize_jurisdiction(r) for r in sliced],
        response_type="array",
        pagination=pmeta,
    )


@bp.route("/fcra/jurisdiction-policies/<code>", methods=["PUT"])
@require_roles("PlatformAdmin")
def put_jurisdiction(code):
    body = get_json_body()
    with lock():
        row = upsert_jurisdiction(code, body)
    return success_response(serialize_jurisdiction(row))
