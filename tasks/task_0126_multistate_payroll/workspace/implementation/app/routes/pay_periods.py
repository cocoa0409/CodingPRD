"""Pay period routes."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import (
    ROLE_PAYROLL_MANAGER,
    ROLE_PAYROLL_SPECIALIST,
    ROLE_TREASURER,
    require_roles,
)
from ..clock import now_iso
from ..errors import (
    err_invalid_pay_period_dates,
    err_no_payroll_items,
    err_pay_period_not_found,
    err_pay_period_not_lockable,
    err_uncalculated_items,
)
from ..helpers import (
    new_uuid,
    occ_check,
    paginate,
    parse_iso_date,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.lookups import paychecks_in_pay_period
from ..services.serialize import serialize_pay_period
from ..store import store

bp = Blueprint("pay_periods", __name__)


def _get_pay_period_or_404(pp_id: str) -> dict:
    pp = store().pay_periods.get(pp_id)
    if pp is None:
        raise err_pay_period_not_found()
    return pp


@bp.post("/pay-periods")
@require_roles(ROLE_PAYROLL_SPECIALIST)
def create_pay_period(**_kw):
    body = require_json_object()
    period_start = parse_iso_date(body.get("period_start"), "period_start")
    period_end = parse_iso_date(body.get("period_end"), "period_end")
    pay_date = parse_iso_date(body.get("pay_date"), "pay_date")
    if period_end < period_start:
        raise err_invalid_pay_period_dates("period_end must be >= period_start")
    if pay_date < period_end:
        raise err_invalid_pay_period_dates("pay_date must be >= period_end")

    s = store()
    with s.lock:
        ts = now_iso()
        pp_id = new_uuid()
        pp = {
            "id": pp_id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "pay_date": pay_date.isoformat(),
            "status": "OPEN",
            "paycheck_count": 0,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "created_seq": s.next_seq(),
        }
        s.pay_periods[pp_id] = pp
    return created(serialize_pay_period(pp))


@bp.get("/pay-periods")
@require_roles(ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER, ROLE_TREASURER)
def list_pay_periods(**_kw):
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    with store().lock:
        items = list(store().pay_periods.values())
        if status_filter:
            items = [p for p in items if p["status"] == status_filter]
        items.sort(key=lambda p: (p["created_at"], p["created_seq"]))
        total = len(items)
        page = paginate(items, limit, offset)
        return listing([serialize_pay_period(p) for p in page], total, limit, offset)


@bp.get("/pay-periods/<pp_id>")
@require_roles(ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER, ROLE_TREASURER)
def get_pay_period(pp_id: str, **_kw):
    with store().lock:
        pp = _get_pay_period_or_404(pp_id)
        return ok(serialize_pay_period(pp))


@bp.post("/pay-periods/<pp_id>/lock")
@require_roles(ROLE_PAYROLL_SPECIALIST)
def lock_pay_period(pp_id: str, **_kw):
    body = require_json_object()
    version = body.get("version")
    with store().lock:
        pp = _get_pay_period_or_404(pp_id)
        occ_check(version, pp["version"])
        if pp["status"] != "OPEN":
            raise err_pay_period_not_lockable("Pay period is not OPEN")
        # Precondition: at least one PayrollItem AND every PayrollItem has a Paycheck in CALCULATED or later
        items_in_period = [
            it for it in store().payroll_items.values() if it["pay_period_id"] == pp_id
        ]
        if not items_in_period:
            raise err_no_payroll_items()
        paychecks = paychecks_in_pay_period(pp_id)
        # Map item -> paycheck
        item_ids = {it["id"] for it in items_in_period}
        # For each item, find the (non-correction) paycheck
        for item_id in item_ids:
            related = [pc for pc in paychecks if pc["payroll_item_id"] == item_id]
            if not related:
                raise err_uncalculated_items()
            # The original non-correction paycheck (or any) — if any is DRAFT, fail
            # Actually the rule is: all PayrollItems must have a Paycheck in CALCULATED or later
            # If any related paycheck is DRAFT → ERR_UNCALCULATED_ITEMS
            if any(pc["status"] == "DRAFT" for pc in related):
                raise err_uncalculated_items()

        pp["status"] = "LOCKED"
        pp["updated_at"] = now_iso()
        pp["version"] = pp["version"] + 1
        return ok(serialize_pay_period(pp))
