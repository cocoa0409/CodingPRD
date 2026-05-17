"""InsurancePlan routes."""
from __future__ import annotations

from typing import Any

from flask import Blueprint

from ..auth import require_roles
from ..clock import now
from ..errors import (
    err_invalid_amount,
    err_not_found,
    err_validation,
)
from ..helpers import (
    assert_enum,
    assert_string,
    new_uuid,
    require_json_object,
)
from ..responses import created, ok
from ..services.serialize import serialize_insurance_plan
from ..store import store

bp = Blueprint("insurance_plans", __name__, url_prefix="/practice/insurance-plans")

NETWORK_STATUSES = ["IN_NETWORK", "OUT_OF_NETWORK"]
CONTRACT_MODES = ["DEDUCTIBLE_FIRST", "COPAY_ONLY"]


@bp.post("")
@require_roles("PracticeAdmin", "BillingClerk")
def create_plan(**_):
    body = require_json_object()
    payer_name = assert_string(body.get("payer_name"), "payer_name")
    plan_code = assert_string(body.get("plan_code"), "plan_code")
    network_status = assert_enum(body.get("network_status"), "network_status", NETWORK_STATUSES)
    contract_mode = assert_enum(body.get("contract_mode"), "contract_mode", CONTRACT_MODES)
    # Monetary fields — presence/type → ERR_VALIDATION, value (<0) → ERR_INVALID_AMOUNT.
    for f in ("allowed_amount_90791_cents", "allowed_amount_90834_cents", "copay_cents"):
        v = body.get(f)
        if v is None:
            raise err_validation(f"{f} is required")
        if isinstance(v, bool) or not isinstance(v, int):
            raise err_validation(f"{f} must be an integer")
        if v < 0:
            raise err_invalid_amount(f"{f} must be >= 0")
    s = store()
    with s.lock:
        for plan in s.insurance_plans.values():
            if plan["plan_code"] == plan_code:
                raise err_validation("plan_code must be unique")
        pid = new_uuid()
        ts = now()
        row: dict[str, Any] = {
            "id": pid,
            "payer_name": payer_name,
            "plan_code": plan_code,
            "network_status": network_status,
            "contract_mode": contract_mode,
            "allowed_amount_90791_cents": body["allowed_amount_90791_cents"],
            "allowed_amount_90834_cents": body["allowed_amount_90834_cents"],
            "copay_cents": body["copay_cents"],
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        s.insurance_plans[pid] = row
        return created(serialize_insurance_plan(row))


@bp.get("/<pid>")
@require_roles("PracticeAdmin", "BillingClerk")
def get_plan(pid: str, **_):
    s = store()
    row = s.insurance_plans.get(pid)
    if row is None:
        raise err_not_found("InsurancePlan not found")
    return ok(serialize_insurance_plan(row))
