from datetime import date

from flask import Blueprint, request

from db import store, new_entity, touch
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_PERIOD_OVERLAP, ERR_PERIOD_NOT_CLOSABLE,
    ERR_REOPEN_LIMIT,
)
from middleware import require_roles
from response import object_response
from serializers import period_view
from services.aggregates import period_accruals
from validation import Payload, require_exists, list_page

bp = Blueprint("fiscal_periods", __name__, url_prefix="/legal-ops/fiscal-periods")

ALL = ("LegalOpsManager", "LegalOpsAnalyst", "LegalOpsExecutive")


@bp.post("")
@require_roles("LegalOpsManager")
def create_period(user_id, role):
    p = Payload()
    label = p.req_str("label")
    sd = p.req_date("start_date")
    ed = p.req_date("end_date")
    # Temporal business rule (priority 7) runs before payload-shape 400s.
    if sd is not None and ed is not None:
        if not ed > sd:
            raise ApiError(ERR_PERIOD_OVERLAP, 422, "end_date must be strictly after start_date")
        for ep in store.fiscal_periods.values():
            ep_s = date.fromisoformat(ep["start_date"])
            ep_e = date.fromisoformat(ep["end_date"])
            # Inclusive ranges; end+1 == start adjacency is permitted.
            if sd <= ep_e and ep_s <= ed:
                raise ApiError(ERR_PERIOD_OVERLAP, 422, "Fiscal period overlaps an existing period")
    p.finish()
    period = new_entity({
        "label": label,
        "start_date": sd.isoformat(),
        "end_date": ed.isoformat(),
        "status": "OPEN",
        "reopen_count": 0,
        "total_actual_spend_cents": 0,
        "total_accrual_cents": 0,
    })
    store.fiscal_periods[period["id"]] = period
    return object_response(period_view(period), 201)


@bp.get("")
@require_roles(*ALL)
def list_periods(user_id, role):
    items = list(store.fiscal_periods.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_page(items, period_view)


@bp.get("/<pid>")
@require_roles(*ALL)
def get_period(user_id, role, pid):
    return object_response(period_view(require_exists(store.fiscal_periods, pid, "fiscal period")))


@bp.post("/<pid>/soft-close")
@require_roles("LegalOpsAnalyst")
def soft_close(user_id, role, pid):
    period = require_exists(store.fiscal_periods, pid, "fiscal period")
    if period["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Period is not in a state that permits soft-close")
    if period["status"] == "OPEN":
        for m in store.matters.values():
            if m["fiscal_period_id"] == pid and m["status"] == "INTAKE":
                raise ApiError(ERR_INVALID_STATE, 409, "Period still has matters in INTAKE")
    # Accrual auto-expiry sweep: every OUTSTANDING accrual in the period expires.
    affected_matters = set()
    for a in store.accruals.values():
        if a["fiscal_period_id"] == pid and a["status"] == "OUTSTANDING":
            a["status"] = "EXPIRED"
            touch(a)
            affected_matters.add(a["matter_id"])
    from services.aggregates import recompute_matter
    for mid in affected_matters:
        m = store.matters.get(mid)
        if m is not None:
            recompute_matter(m)
    period["status"] = "SOFT_CLOSED"
    period["total_accrual_cents"] = period_accruals(pid)
    touch(period)
    return object_response(period_view(period))


@bp.post("/<pid>/hard-close")
@require_roles("LegalOpsManager")
def hard_close(user_id, role, pid):
    period = require_exists(store.fiscal_periods, pid, "fiscal period")
    if period["status"] != "SOFT_CLOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Period is not SOFT_CLOSED")
    for inv in store.invoices.values():
        if inv["fiscal_period_id"] == pid and inv["payment_status"] == "SUBMITTED":
            raise ApiError(ERR_PERIOD_NOT_CLOSABLE, 422, "Period has SUBMITTED invoices")
    for d in store.dashboards.values():
        if d["fiscal_period_id"] == pid and d["status"] == "DRAFT":
            raise ApiError(ERR_PERIOD_NOT_CLOSABLE, 422, "Period has DRAFT dashboards")
    period["status"] = "HARD_CLOSED"
    touch(period)
    return object_response(period_view(period))


@bp.post("/<pid>/reopen")
@require_roles("LegalOpsManager")
def reopen(user_id, role, pid):
    period = require_exists(store.fiscal_periods, pid, "fiscal period")
    if period["status"] != "HARD_CLOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Period is not HARD_CLOSED")
    if period["reopen_count"] >= 2:
        raise ApiError(ERR_REOPEN_LIMIT, 422, "Fiscal period has already been reopened twice")
    period["status"] = "REOPENED"
    period["reopen_count"] += 1
    touch(period)
    return object_response(period_view(period))
