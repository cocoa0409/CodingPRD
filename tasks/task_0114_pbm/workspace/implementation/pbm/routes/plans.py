"""/pbm/plans — Plan CRUD."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import require_roles
from ..envelope import success, list_success
from ..errors import (
    APIError,
    ERR_OOP_BELOW_DEDUCTIBLE,
    ERR_RESOURCE_NOT_FOUND,
    ERR_VALIDATION,
)
from ..store import STORE
from ..validation import (
    as_nonneg_int,
    as_number,
    check_version,
    get_json_body,
    paginate,
    parse_pagination,
    require_field,
)

bp = Blueprint("plans", __name__)


def _serialize(p: dict) -> dict:
    return {
        "id": p["id"],
        "name": p["name"],
        "deductible_cents": p["deductible_cents"],
        "oop_max_cents": p["oop_max_cents"],
        "coinsurance_rate": p["coinsurance_rate"],
        "mail_order_discount_rate": p["mail_order_discount_rate"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def _validate_rate(value, key: str, *, exclusive_low: bool = False) -> float:
    v = as_number(value, key)
    if exclusive_low:
        if not (0 < v <= 1):
            raise APIError(ERR_VALIDATION, f"{key} must satisfy 0 < rate <= 1", 422)
    else:
        if not (0 <= v <= 1):
            raise APIError(ERR_VALIDATION, f"{key} must satisfy 0 <= rate <= 1", 422)
    return v


@bp.post("/pbm/plans")
@require_roles("PBMAdmin")
def create_plan():
    body = get_json_body()
    name = require_field(body, "name")
    deductible = as_nonneg_int(require_field(body, "deductible_cents"), "deductible_cents")
    oop_max = as_nonneg_int(require_field(body, "oop_max_cents"), "oop_max_cents")
    coinsurance = _validate_rate(require_field(body, "coinsurance_rate"), "coinsurance_rate")
    mail_order_raw = body.get("mail_order_discount_rate", 0.90)
    mail_order = _validate_rate(mail_order_raw, "mail_order_discount_rate", exclusive_low=True)

    if oop_max < deductible:
        raise APIError(ERR_OOP_BELOW_DEDUCTIBLE, "oop_max_cents must be >= deductible_cents", 422)

    with STORE.lock:
        plan = STORE.init_common_fields({
            "name": name,
            "deductible_cents": deductible,
            "oop_max_cents": oop_max,
            "coinsurance_rate": coinsurance,
            "mail_order_discount_rate": mail_order,
            "status": "ACTIVE",
        })
        STORE.plans[plan["id"]] = plan
    return success(_serialize(plan), status=201)


@bp.get("/pbm/plans")
@require_roles("PBMAdmin", "ClinicalReviewer", "ClaimsAdjudicator", "Prescriber")
def list_plans():
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    with STORE.lock:
        items = list(STORE.plans.values())
    if status_filter:
        items = [p for p in items if p["status"] == status_filter]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, total = paginate(items, limit, offset)
    return list_success([_serialize(p) for p in page], limit=limit, offset=offset, total_count=total)


@bp.get("/pbm/plans/<pid>")
@require_roles("PBMAdmin", "ClinicalReviewer", "ClaimsAdjudicator", "Prescriber")
def get_plan(pid: str):
    with STORE.lock:
        plan = STORE.plans.get(pid)
    if plan is None:
        raise APIError(ERR_RESOURCE_NOT_FOUND, f"Plan {pid} not found", 404)
    return success(_serialize(plan))


@bp.patch("/pbm/plans/<pid>")
@require_roles("PBMAdmin")
def patch_plan(pid: str):
    body = get_json_body()
    with STORE.lock:
        plan = STORE.plans.get(pid)
        if plan is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Plan {pid} not found", 404)
        check_version(body, plan)

        updated = dict(plan)
        if "deductible_cents" in body:
            updated["deductible_cents"] = as_nonneg_int(body["deductible_cents"], "deductible_cents")
        if "oop_max_cents" in body:
            updated["oop_max_cents"] = as_nonneg_int(body["oop_max_cents"], "oop_max_cents")
        if "coinsurance_rate" in body:
            updated["coinsurance_rate"] = _validate_rate(body["coinsurance_rate"], "coinsurance_rate")
        if "mail_order_discount_rate" in body:
            updated["mail_order_discount_rate"] = _validate_rate(
                body["mail_order_discount_rate"], "mail_order_discount_rate", exclusive_low=True
            )

        if updated["oop_max_cents"] < updated["deductible_cents"]:
            raise APIError(ERR_OOP_BELOW_DEDUCTIBLE, "oop_max_cents must be >= deductible_cents", 422)

        # Detect actual mutation -> bump version
        changed = any(
            updated[k] != plan[k]
            for k in ("deductible_cents", "oop_max_cents", "coinsurance_rate", "mail_order_discount_rate")
        )
        if changed:
            plan.update(updated)
            STORE.bump(plan)
        return success(_serialize(plan))
