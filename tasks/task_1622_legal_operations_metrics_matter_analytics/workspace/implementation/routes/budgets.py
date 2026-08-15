from flask import Blueprint, request

from db import store, new_entity, touch
from errors import (
    ApiError, ERR_INVALID_AMOUNT, ERR_STALE_VERSION,
)
from middleware import require_roles
from response import object_response
from serializers import budget_view
from services.aggregates import department_thresholds, derive_posture, recompute_budget
from validation import Payload, require_exists, list_page

bp = Blueprint("budgets", __name__, url_prefix="/legal-ops/budgets")

ALL = ("LegalOpsManager", "LegalOpsAnalyst", "LegalOpsExecutive")


@bp.post("")
@require_roles("LegalOpsManager")
def create_budget(user_id, role):
    p = Payload()
    fp_id = p.req_str("fiscal_period_id")
    pa_id = p.req_str("practice_area_id")
    mt_id = p.opt_str("matter_type_id")
    allocated = p.req_int("allocated_cents")
    if fp_id is not None:
        require_exists(store.fiscal_periods, fp_id, "fiscal period")
    if pa_id is not None:
        require_exists(store.practice_areas, pa_id, "practice area")
    if mt_id is not None:
        require_exists(store.matter_types, mt_id, "matter type")
    # Amount rule (priority 12) before payload shape (20).
    if allocated is not None and allocated < 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "allocated_cents must be >= 0")
    p.finish()
    b = new_entity({
        "fiscal_period_id": fp_id,
        "practice_area_id": pa_id,
        "matter_type_id": mt_id,
        "allocated_cents": allocated,
        "consumed_cents": 0,
        "posture": "OK",
    })
    store.budgets[b["id"]] = b
    return object_response(budget_view(b), 201)


@bp.get("")
@require_roles(*ALL)
def list_budgets(user_id, role):
    items = list(store.budgets.values())
    for param in ("fiscal_period_id", "practice_area_id", "matter_type_id", "posture"):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if b[param] == v]
    return list_page(items, budget_view)


@bp.get("/<bid>")
@require_roles(*ALL)
def get_budget(user_id, role, bid):
    return object_response(budget_view(require_exists(store.budgets, bid, "budget")))


@bp.patch("/<bid>")
@require_roles("LegalOpsManager")
def update_budget(user_id, role, bid):
    b = require_exists(store.budgets, bid, "budget")
    p = Payload()
    allocated = p.opt_int("allocated_cents", nullable=False)
    expected = p.opt_int("expected_budget_version", nullable=False)
    # Amount check (priority 12) runs before OCC (priority 18).
    if allocated is not None and allocated < 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "allocated_cents must be >= 0")
    if expected is not None and expected != b["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_budget_version does not match current version")
    p.finish()
    b["allocated_cents"] = allocated
    # Posture re-derives immediately after an allocation change (PRD section 2.7).
    warning, critical = department_thresholds()
    b["posture"] = derive_posture(b["consumed_cents"], b["allocated_cents"], warning, critical)
    touch(b)
    return object_response(budget_view(b))
