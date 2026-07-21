from flask import Blueprint

import store
from common import (ApiError, authorize, ok_object, serialize, get_body,
                    require_enum, require_int, require_month, require_present)

bp = Blueprint("scores", __name__)


@bp.post("/api/score-snapshots")
def create_score_snapshot():
    uid, role = authorize(["PlatformAdmin"])
    body = get_body()
    # existence of tenant_id FK (priority 3) before invalid_request (priority 4)
    require_present(body, "tenant_id")
    tenant_id = body.get("tenant_id")
    if not isinstance(tenant_id, str) or tenant_id not in store.tenants:
        # if it's missing/wrong-type it is really invalid_request, but a well-formed
        # unknown id is a not-found; treat any unresolved reference as not-found.
        if isinstance(tenant_id, str):
            raise ApiError("ERR_TENANT_NOT_FOUND", "tenant not found")
        raise ApiError("ERR_INVALID_REQUEST", "invalid tenant_id")
    bureau = require_enum(body, "bureau", store.BUREAUS)
    score = require_int(body, "score")
    if score < 300 or score > 850:
        raise ApiError("ERR_INVALID_REQUEST", "score out of range 300..850")
    as_of_month = require_month(body, "as_of_month")

    s = store.base_fields(with_version=False)
    s.update({
        "tenant_id": tenant_id,
        "bureau": bureau,
        "score": score,
        "as_of_month": as_of_month,
    })
    store.score_snapshots[s["id"]] = s
    return ok_object(serialize(s), 201)
