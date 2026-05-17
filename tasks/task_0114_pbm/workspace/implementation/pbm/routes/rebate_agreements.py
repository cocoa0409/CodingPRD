"""/pbm/rebate-agreements — manufacturer rebate agreements."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import require_roles
from ..envelope import success, list_success
from ..errors import (
    APIError,
    ERR_RESOURCE_NOT_FOUND,
    ERR_VALIDATION,
)
from ..store import STORE
from ..validation import (
    as_nonneg_int,
    as_number,
    get_json_body,
    paginate,
    parse_pagination,
    require_field,
)

bp = Blueprint("rebate_agreements", __name__)


def serialize_agreement(a: dict) -> dict:
    return {
        "id": a["id"],
        "drug_id": a["drug_id"],
        "manufacturer_name": a["manufacturer_name"],
        "rebate_rate": a["rebate_rate"],
        "clawback_window_days": a["clawback_window_days"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.post("/pbm/rebate-agreements")
@require_roles("PBMAdmin")
def create_agreement():
    body = get_json_body()
    drug_id = require_field(body, "drug_id")
    manufacturer = require_field(body, "manufacturer_name")
    rate = as_number(require_field(body, "rebate_rate"), "rebate_rate")
    if not (0 <= rate <= 1):
        raise APIError(ERR_VALIDATION, "rebate_rate must satisfy 0 <= rate <= 1", 422)
    window = body.get("clawback_window_days", 90)
    window = as_nonneg_int(window, "clawback_window_days")

    with STORE.lock:
        if drug_id not in STORE.drugs:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Drug {drug_id} not found", 404)
        agreement = STORE.init_common_fields({
            "drug_id": drug_id,
            "manufacturer_name": manufacturer,
            "rebate_rate": rate,
            "clawback_window_days": window,
            "status": "ACTIVE",
        })
        STORE.rebate_agreements[agreement["id"]] = agreement
    return success(serialize_agreement(agreement), status=201)


@bp.get("/pbm/rebate-agreements")
@require_roles("PBMAdmin")
def list_agreements():
    limit, offset = parse_pagination()
    drug_id_filter = request.args.get("drug_id")
    status_filter = request.args.get("status")
    with STORE.lock:
        items = list(STORE.rebate_agreements.values())
    if drug_id_filter:
        items = [a for a in items if a["drug_id"] == drug_id_filter]
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, total = paginate(items, limit, offset)
    return list_success(
        [serialize_agreement(a) for a in page],
        limit=limit, offset=offset, total_count=total,
    )
