"""W-4 profile routes — including pre-fill."""
from __future__ import annotations

from flask import Blueprint

from ..auth import (
    ROLE_PAYROLL_MANAGER,
    ROLE_PAYROLL_SPECIALIST,
    ROLE_TREASURER,
    require_roles,
)
from ..clock import now_iso, parse_iso_date_str
from ..errors import (
    err_employee_not_found,
    err_no_prior_year_w4,
    err_pay_period_not_found,
    err_w4_prefill_already_done,
)
from ..helpers import (
    assert_enum,
    assert_integer,
    assert_string,
    new_uuid,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing
from ..services.lookups import (
    find_latest_prior_year_w4,
    has_prefilled_w4_for_year,
)
from ..services.serialize import serialize_w4
from ..store import store

bp = Blueprint("w4_profiles", __name__)


FILING_STATUSES = ["SINGLE", "MARRIED_JOINT", "HEAD_OF_HOUSEHOLD"]


def _get_employee_or_404(employee_id: str) -> dict:
    emp = store().employees.get(employee_id)
    if emp is None:
        raise err_employee_not_found()
    return emp


def _get_pay_period_or_404(pp_id: str) -> dict:
    pp = store().pay_periods.get(pp_id)
    if pp is None:
        raise err_pay_period_not_found()
    return pp


@bp.post("/employees/<employee_id>/w4-profiles")
@require_roles(ROLE_PAYROLL_SPECIALIST)
def create_w4(employee_id: str, **_kw):
    s = store()
    with s.lock:
        _get_employee_or_404(employee_id)
        body = require_json_object()
        filing_status = assert_enum(body.get("filing_status"), "filing_status", FILING_STATUSES)
        dependents = assert_integer(
            body.get("dependents_amount_cents"), "dependents_amount_cents",
            required=False, minimum=0,
        ) or 0
        other_income = assert_integer(
            body.get("other_income_cents"), "other_income_cents",
            required=False, minimum=0,
        ) or 0
        additional_wh = assert_integer(
            body.get("additional_withholding_cents"), "additional_withholding_cents",
            required=False, minimum=0,
        ) or 0
        state_allowances = assert_integer(
            body.get("state_allowances"), "state_allowances",
            required=False, minimum=0,
        ) or 0
        effective_pay_period_id = assert_string(
            body.get("effective_pay_period_id"), "effective_pay_period_id"
        )
        _get_pay_period_or_404(effective_pay_period_id)

        ts = now_iso()
        w4_id = new_uuid()
        w4 = {
            "id": w4_id,
            "employee_id": employee_id,
            "filing_status": filing_status,
            "dependents_amount_cents": dependents,
            "other_income_cents": other_income,
            "additional_withholding_cents": additional_wh,
            "state_allowances": state_allowances,
            "prefilled_from_prior_year": False,
            "effective_pay_period_id": effective_pay_period_id,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "created_seq": s.next_seq(),
        }
        s.w4_profiles[w4_id] = w4
    return created(serialize_w4(w4))


@bp.post("/employees/<employee_id>/w4-profiles/prefill")
@require_roles(ROLE_PAYROLL_SPECIALIST)
def prefill_w4(employee_id: str, **_kw):
    s = store()
    with s.lock:
        _get_employee_or_404(employee_id)
        body = require_json_object()
        effective_pay_period_id = assert_string(
            body.get("effective_pay_period_id"), "effective_pay_period_id"
        )
        eff_pp = _get_pay_period_or_404(effective_pay_period_id)
        target_year = parse_iso_date_str(eff_pp["pay_date"]).year

        # ERR_W4_PREFILL_ALREADY_DONE check
        if has_prefilled_w4_for_year(employee_id, target_year):
            raise err_w4_prefill_already_done()

        # Find prior-year W-4
        prior = find_latest_prior_year_w4(employee_id, target_year)
        if prior is None:
            raise err_no_prior_year_w4()

        ts = now_iso()
        w4_id = new_uuid()
        w4 = {
            "id": w4_id,
            "employee_id": employee_id,
            "filing_status": prior["filing_status"],
            "dependents_amount_cents": prior["dependents_amount_cents"],
            "other_income_cents": prior["other_income_cents"],
            "additional_withholding_cents": 0,
            "state_allowances": prior["state_allowances"],
            "prefilled_from_prior_year": True,
            "effective_pay_period_id": effective_pay_period_id,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "created_seq": s.next_seq(),
        }
        s.w4_profiles[w4_id] = w4
    return created(serialize_w4(w4))


@bp.get("/employees/<employee_id>/w4-profiles")
@require_roles(ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER, ROLE_TREASURER)
def list_w4(employee_id: str, **_kw):
    limit, offset = parse_pagination()
    with store().lock:
        _get_employee_or_404(employee_id)
        items = [w for w in store().w4_profiles.values() if w["employee_id"] == employee_id]
        items.sort(key=lambda w: (w["created_at"], w["created_seq"]))
        total = len(items)
        page = paginate(items, limit, offset)
        return listing([serialize_w4(w) for w in page], total, limit, offset)
