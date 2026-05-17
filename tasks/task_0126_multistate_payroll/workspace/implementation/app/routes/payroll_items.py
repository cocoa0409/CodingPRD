"""Payroll item routes (including implicit Paycheck creation)."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_PAYROLL_SPECIALIST, require_roles
from ..clock import now_iso
from ..errors import (
    err_duplicate_paycheck_for_employee,
    err_employee_not_found,
    err_invalid_hours,
    err_pay_period_not_found,
    err_pay_period_not_open,
    err_payroll_item_not_found,
    err_terminated_employee,
)
from ..helpers import (
    assert_integer,
    assert_number,
    assert_string,
    new_uuid,
    occ_check,
    require_json_object,
)
from ..responses import created, ok
from ..services.constants import MAX_HOURS_PER_PERIOD
from ..services.serialize import serialize_payroll_item
from ..store import store

bp = Blueprint("payroll_items", __name__)


def _validate_hours(reg: float, ot: float, dbl: float) -> None:
    if reg < 0 or ot < 0 or dbl < 0:
        raise err_invalid_hours("hours must be non-negative")
    if (reg + ot + dbl) > MAX_HOURS_PER_PERIOD:
        raise err_invalid_hours(
            f"Sum of regular+overtime+double must be <= {MAX_HOURS_PER_PERIOD}"
        )


@bp.post("/pay-periods/<pp_id>/payroll-items")
@require_roles(ROLE_PAYROLL_SPECIALIST)
def create_payroll_item(pp_id: str, **_kw):
    s = store()
    with s.lock:
        pp = s.pay_periods.get(pp_id)
        if pp is None:
            raise err_pay_period_not_found()
        body = require_json_object()
        # priority 4: PayPeriod must be OPEN
        if pp["status"] != "OPEN":
            raise err_pay_period_not_open()
        # Body validation
        employee_id = assert_string(body.get("employee_id"), "employee_id")
        regular_hours = assert_number(
            body.get("regular_hours"), "regular_hours", required=False
        ) or 0
        overtime_hours = assert_number(
            body.get("overtime_hours"), "overtime_hours", required=False
        ) or 0
        double_hours = assert_number(
            body.get("double_hours"), "double_hours", required=False
        ) or 0
        retro_adjustment = body.get("retro_adjustment_cents")
        if retro_adjustment is None:
            retro_adjustment = 0
        if isinstance(retro_adjustment, bool) or not isinstance(retro_adjustment, int):
            from ..errors import err_invalid_request
            raise err_invalid_request("retro_adjustment_cents must be an integer")

        # Employee must exist (body-ref existence, after period existence check)
        emp = s.employees.get(employee_id)
        if emp is None:
            raise err_employee_not_found()

        # Terminated-employee check applied here? The PRD allows creating items for terminated
        # employees in final-settlement window. We allow creation; the calculate step will
        # enforce ERR_TERMINATED_EMPLOYEE if outside window.

        # priority 12 hours validity (before duplicate-paycheck)
        _validate_hours(regular_hours, overtime_hours, double_hours)

        # priority 13: duplicate paycheck per (pp, employee)
        for pc in s.paychecks.values():
            if (
                pc["pay_period_id"] == pp_id
                and pc["employee_id"] == employee_id
                and not pc.get("is_retro_correction", False)
            ):
                raise err_duplicate_paycheck_for_employee()

        ts = now_iso()
        item_id = new_uuid()
        item = {
            "id": item_id,
            "pay_period_id": pp_id,
            "employee_id": employee_id,
            "regular_hours": regular_hours,
            "overtime_hours": overtime_hours,
            "double_hours": double_hours,
            "retro_adjustment_cents": retro_adjustment,
            "locked": False,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "created_seq": s.next_seq(),
        }
        s.payroll_items[item_id] = item

        # Implicit Paycheck in DRAFT
        pc_id = new_uuid()
        paycheck = {
            "id": pc_id,
            "pay_period_id": pp_id,
            "payroll_item_id": item_id,
            "employee_id": employee_id,
            "w4_profile_id": None,
            "gross_wages_cents": None,
            "federal_withholding_cents": None,
            "state_withholding_cents": None,
            "local_withholding_cents": None,
            "social_security_cents": None,
            "medicare_base_cents": None,
            "medicare_additional_cents": None,
            "garnishment_total_cents": 0,
            "garnishment_allocations": {},
            "net_pay_cents": None,
            "is_retro_correction": False,
            "correction_of_paycheck_id": None,
            "status": "DRAFT",
            "calculator_id": None,
            "approver_id": None,
            "finalizer_id": None,
            "ss_wages_subject_cents": 0,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "created_seq": s.next_seq(),
        }
        s.paychecks[pc_id] = paycheck

        # paycheck_count++
        pp["paycheck_count"] = pp["paycheck_count"] + 1
        pp["updated_at"] = ts
        pp["version"] = pp["version"] + 1

    return created(serialize_payroll_item(item))


@bp.put("/payroll-items/<item_id>")
@require_roles(ROLE_PAYROLL_SPECIALIST)
def update_payroll_item(item_id: str, **_kw):
    s = store()
    with s.lock:
        item = s.payroll_items.get(item_id)
        if item is None:
            raise err_payroll_item_not_found()
        body = require_json_object()
        version = body.get("version")
        # priority 4: owning PayPeriod OPEN
        pp = s.pay_periods.get(item["pay_period_id"])
        if pp is None or pp["status"] != "OPEN":
            raise err_pay_period_not_open()
        occ_check(version, item["version"])
        # locked check (paycheck reached CALCULATED)
        if item["locked"]:
            from ..errors import err_paycheck_not_draft
            raise err_paycheck_not_draft("Linked paycheck has been CALCULATED; item locked")

        # Build candidate values
        reg = item["regular_hours"]
        ot = item["overtime_hours"]
        dbl = item["double_hours"]
        retro = item["retro_adjustment_cents"]

        if "regular_hours" in body:
            reg = assert_number(body["regular_hours"], "regular_hours", required=False) or 0
        if "overtime_hours" in body:
            ot = assert_number(body["overtime_hours"], "overtime_hours", required=False) or 0
        if "double_hours" in body:
            dbl = assert_number(body["double_hours"], "double_hours", required=False) or 0
        if "retro_adjustment_cents" in body:
            v = body["retro_adjustment_cents"]
            if v is None:
                v = 0
            if isinstance(v, bool) or not isinstance(v, int):
                from ..errors import err_invalid_request
                raise err_invalid_request("retro_adjustment_cents must be an integer")
            retro = v

        _validate_hours(reg, ot, dbl)

        item["regular_hours"] = reg
        item["overtime_hours"] = ot
        item["double_hours"] = dbl
        item["retro_adjustment_cents"] = retro
        item["updated_at"] = now_iso()
        item["version"] = item["version"] + 1
        return ok(serialize_payroll_item(item))
