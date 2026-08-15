from flask import Blueprint, request

from db import store, new_entity, touch
from errors import ApiError, ERR_INVALID_AMOUNT, ERR_INVALID_STATE, ERR_PERIOD_CLOSED
from middleware import require_roles
from response import object_response
from serializers import accrual_view
from services.aggregates import recompute_matter, recompute_period
from validation import Payload, require_exists, list_page

bp = Blueprint("accruals", __name__, url_prefix="/legal-ops/accruals")

ALL = ("LegalOpsManager", "LegalOpsAnalyst", "LegalOpsExecutive")


@bp.post("")
@require_roles("LegalOpsAnalyst")
def create_accrual(user_id, role):
    p = Payload()
    matter_id = p.req_str("matter_id")
    fp_id = p.req_str("fiscal_period_id")
    firm_id = p.req_str("firm_id")
    amount = p.req_int("amount_cents")
    matter = fp = None
    if matter_id is not None:
        matter = require_exists(store.matters, matter_id, "matter")
    if fp_id is not None:
        fp = require_exists(store.fiscal_periods, fp_id, "fiscal period")
    if firm_id is not None:
        require_exists(store.firms, firm_id, "firm")
    # Calendar gate (priority 8) evaluated before the amount check (priority 12).
    if fp is not None and fp["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_PERIOD_CLOSED, 409, "Fiscal period is not OPEN or REOPENED")
    if amount is not None and amount < 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "amount_cents must be >= 0")
    p.finish()
    a = new_entity({
        "matter_id": matter_id,
        "fiscal_period_id": fp_id,
        "firm_id": firm_id,
        "amount_cents": amount,
        "status": "OUTSTANDING",
    })
    store.accruals[a["id"]] = a
    # Side effects: raise matter + period accrual aggregates immediately.
    recompute_matter(matter)
    recompute_period(fp)
    return object_response(accrual_view(a), 201)


@bp.get("")
@require_roles(*ALL)
def list_accruals(user_id, role):
    items = list(store.accruals.values())
    for param in ("matter_id", "fiscal_period_id", "firm_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a[param] == v]
    return list_page(items, accrual_view)


@bp.get("/<aid>")
@require_roles(*ALL)
def get_accrual(user_id, role, aid):
    return object_response(accrual_view(require_exists(store.accruals, aid, "accrual")))


@bp.post("/<aid>/release")
@require_roles("LegalOpsAnalyst")
def release_accrual(user_id, role, aid):
    a = require_exists(store.accruals, aid, "accrual")
    if a["status"] != "OUTSTANDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Accrual is not OUTSTANDING")
    period = store.fiscal_periods.get(a["fiscal_period_id"])
    if period is not None and period["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_PERIOD_CLOSED, 409, "Fiscal period is not OPEN or REOPENED")
    a["status"] = "RELEASED"
    touch(a)
    matter = store.matters.get(a["matter_id"])
    if matter is not None:
        recompute_matter(matter)
    if period is not None:
        recompute_period(period)
    return object_response(accrual_view(a))
