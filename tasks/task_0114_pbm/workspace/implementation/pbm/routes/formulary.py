"""/pbm/formulary-entries — formulary tier + copay management."""
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
    as_int,
    as_nonneg_int,
    check_version,
    get_json_body,
    paginate,
    parse_pagination,
    require_field,
)

bp = Blueprint("formulary", __name__)


def _serialize(fe: dict) -> dict:
    return {
        "id": fe["id"],
        "plan_id": fe["plan_id"],
        "drug_id": fe["drug_id"],
        "tier": fe["tier"],
        "copay_cents": fe["copay_cents"],
        "status": fe["status"],
        "created_at": fe["created_at"],
        "updated_at": fe["updated_at"],
        "version": fe["version"],
    }


def _validate_tier(tier_val, key: str = "tier") -> int:
    v = as_int(tier_val, key)
    if v < 1 or v > 5:
        raise APIError(ERR_VALIDATION, "tier must be in 1..5", 422)
    return v


@bp.post("/pbm/formulary-entries")
@require_roles("PBMAdmin")
def create_entry():
    body = get_json_body()
    plan_id = require_field(body, "plan_id")
    drug_id = require_field(body, "drug_id")
    tier = _validate_tier(require_field(body, "tier"))
    copay = as_nonneg_int(require_field(body, "copay_cents"), "copay_cents")

    with STORE.lock:
        if plan_id not in STORE.plans:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Plan {plan_id} not found", 404)
        if drug_id not in STORE.drugs:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Drug {drug_id} not found", 404)
        fe = STORE.init_common_fields({
            "plan_id": plan_id,
            "drug_id": drug_id,
            "tier": tier,
            "copay_cents": copay,
            "status": "ACTIVE",
        })
        STORE.formulary_entries[fe["id"]] = fe
    return success(_serialize(fe), status=201)


@bp.get("/pbm/formulary-entries")
@require_roles("PBMAdmin", "ClinicalReviewer", "ClaimsAdjudicator", "Prescriber")
def list_entries():
    limit, offset = parse_pagination()
    plan_id_filter = request.args.get("plan_id")
    drug_id_filter = request.args.get("drug_id")
    tier_filter = request.args.get("tier")
    status_filter = request.args.get("status")

    with STORE.lock:
        items = list(STORE.formulary_entries.values())
    if plan_id_filter:
        items = [e for e in items if e["plan_id"] == plan_id_filter]
    if drug_id_filter:
        items = [e for e in items if e["drug_id"] == drug_id_filter]
    if tier_filter is not None:
        try:
            tf = int(tier_filter)
            items = [e for e in items if e["tier"] == tf]
        except ValueError:
            items = []
    if status_filter:
        items = [e for e in items if e["status"] == status_filter]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, total = paginate(items, limit, offset)
    return list_success([_serialize(e) for e in page], limit=limit, offset=offset, total_count=total)


@bp.patch("/pbm/formulary-entries/<eid>")
@require_roles("PBMAdmin")
def patch_entry(eid: str):
    body = get_json_body()
    with STORE.lock:
        fe = STORE.formulary_entries.get(eid)
        if fe is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"FormularyEntry {eid} not found", 404)
        check_version(body, fe)
        changed = False
        if "tier" in body:
            new_tier = _validate_tier(body["tier"])
            if new_tier != fe["tier"]:
                fe["tier"] = new_tier
                changed = True
        if "copay_cents" in body:
            new_copay = as_nonneg_int(body["copay_cents"], "copay_cents")
            if new_copay != fe["copay_cents"]:
                fe["copay_cents"] = new_copay
                changed = True
        if changed:
            STORE.bump(fe)
        return success(_serialize(fe))
