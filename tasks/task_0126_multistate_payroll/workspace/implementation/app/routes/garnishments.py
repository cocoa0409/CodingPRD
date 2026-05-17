"""Garnishment order routes."""
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
    err_employee_not_found,
    err_garnishment_not_active,
    err_garnishment_not_found,
    err_invalid_garnishment_cap,
)
from ..helpers import (
    assert_enum,
    assert_integer,
    assert_string,
    new_uuid,
    occ_check,
    paginate,
    parse_iso_date,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.constants import GARNISHMENT_PRIORITY
from ..services.serialize import serialize_garnishment
from ..store import store

bp = Blueprint("garnishments", __name__)

ORDER_TYPES = ["CHILD_SUPPORT", "FEDERAL_TAX_LEVY", "CREDITOR", "STUDENT_LOAN"]


def _get_employee_or_404(employee_id: str) -> dict:
    emp = store().employees.get(employee_id)
    if emp is None:
        raise err_employee_not_found()
    return emp


def _get_order_or_404(order_id: str) -> dict:
    g = store().garnishment_orders.get(order_id)
    if g is None:
        raise err_garnishment_not_found()
    return g


@bp.post("/garnishment-orders")
@require_roles(ROLE_PAYROLL_MANAGER)
def create_order(**_kw):
    body = require_json_object()
    employee_id = assert_string(body.get("employee_id"), "employee_id")
    order_type = assert_enum(body.get("order_type"), "order_type", ORDER_TYPES)
    total_owed_cents = assert_integer(body.get("total_owed_cents"), "total_owed_cents", minimum=0)
    cap_pct = body.get("cap_pct_of_disposable")
    # ERR_INVALID_GARNISHMENT_CAP per priority 9 — explicit business validation
    if not isinstance(cap_pct, int) or isinstance(cap_pct, bool) or cap_pct < 1 or cap_pct > 100:
        raise err_invalid_garnishment_cap()
    effective_pay_date = parse_iso_date(body.get("effective_pay_date"), "effective_pay_date")

    s = store()
    with s.lock:
        _get_employee_or_404(employee_id)
        ts = now_iso()
        order_id = new_uuid()
        order = {
            "id": order_id,
            "employee_id": employee_id,
            "order_type": order_type,
            "priority_rank": GARNISHMENT_PRIORITY[order_type],
            "total_owed_cents": total_owed_cents,
            "amount_collected_cents": 0,
            "cap_pct_of_disposable": cap_pct,
            "effective_pay_date": effective_pay_date.isoformat(),
            "status": "ACTIVE",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "created_seq": s.next_seq(),
        }
        s.garnishment_orders[order_id] = order
    return created(serialize_garnishment(order))


@bp.get("/garnishment-orders")
@require_roles(ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER, ROLE_TREASURER)
def list_orders(**_kw):
    limit, offset = parse_pagination()
    employee_filter = request.args.get("employee_id")
    status_filter = request.args.get("status")
    with store().lock:
        items = list(store().garnishment_orders.values())
        if employee_filter:
            items = [o for o in items if o["employee_id"] == employee_filter]
        if status_filter:
            items = [o for o in items if o["status"] == status_filter]
        items.sort(key=lambda o: (o["created_at"], o["created_seq"]))
        total = len(items)
        page = paginate(items, limit, offset)
        return listing([serialize_garnishment(o) for o in page], total, limit, offset)


@bp.get("/garnishment-orders/<order_id>")
@require_roles(ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER, ROLE_TREASURER)
def get_order(order_id: str, **_kw):
    with store().lock:
        order = _get_order_or_404(order_id)
        return ok(serialize_garnishment(order))


@bp.post("/garnishment-orders/<order_id>/release")
@require_roles(ROLE_PAYROLL_MANAGER)
def release_order(order_id: str, **_kw):
    body = require_json_object()
    version = body.get("version")
    with store().lock:
        order = _get_order_or_404(order_id)
        occ_check(version, order["version"])
        if order["status"] != "ACTIVE":
            raise err_garnishment_not_active()
        order["status"] = "RELEASED"
        order["updated_at"] = now_iso()
        order["version"] = order["version"] + 1
        return ok(serialize_garnishment(order))
