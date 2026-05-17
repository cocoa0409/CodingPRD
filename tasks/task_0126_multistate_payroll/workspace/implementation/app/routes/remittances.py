"""Remittance period routes."""
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
    err_duplicate_remittance,
    err_no_amendment_basis,
    err_open_pay_periods_in_month,
    err_remittance_not_draft,
    err_remittance_not_finalized,
    err_remittance_not_found,
    err_remittance_not_remitted,
    err_segregation_of_duties,
    err_unapproved_paychecks_in_month,
)
from ..helpers import (
    assert_integer,
    new_uuid,
    occ_check,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.lookups import (
    pay_periods_in_year_month,
    paychecks_in_year_month,
)
from ..services.serialize import serialize_remittance
from ..store import store

bp = Blueprint("remittances", __name__)


def _get_remittance_or_404(r_id: str) -> dict:
    r = store().remittances.get(r_id)
    if r is None:
        raise err_remittance_not_found()
    return r


@bp.post("/remittance-periods")
@require_roles(ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER)
def create_remittance(**_kw):
    body = require_json_object()
    tax_year = assert_integer(body.get("tax_year"), "tax_year", minimum=1900, maximum=9999)
    tax_month = assert_integer(body.get("tax_month"), "tax_month", minimum=1, maximum=12)

    s = store()
    with s.lock:
        for r in s.remittances.values():
            if r["tax_year"] == tax_year and r["tax_month"] == tax_month:
                raise err_duplicate_remittance()
        ts = now_iso()
        r_id = new_uuid()
        r = {
            "id": r_id,
            "tax_year": tax_year,
            "tax_month": tax_month,
            "total_federal_withholding_cents": 0,
            "total_state_withholding_cents": 0,
            "total_local_withholding_cents": 0,
            "total_social_security_cents": 0,
            "total_medicare_cents": 0,
            "total_medicare_additional_cents": 0,
            "state_breakdown": [],
            "status": "DRAFT",
            "finalizer_id": None,
            "amender_id": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "created_seq": s.next_seq(),
        }
        s.remittances[r_id] = r
    return created(serialize_remittance(r))


@bp.get("/remittance-periods")
@require_roles(ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER, ROLE_TREASURER)
def list_remittances(**_kw):
    limit, offset = parse_pagination()
    tax_year_filter = request.args.get("tax_year")
    status_filter = request.args.get("status")
    with store().lock:
        items = list(store().remittances.values())
        if tax_year_filter is not None:
            try:
                ty = int(tax_year_filter)
            except (TypeError, ValueError):
                ty = None
            if ty is not None:
                items = [r for r in items if r["tax_year"] == ty]
        if status_filter:
            items = [r for r in items if r["status"] == status_filter]
        items.sort(key=lambda r: (r["created_at"], r["created_seq"]))
        total = len(items)
        page = paginate(items, limit, offset)
        return listing([serialize_remittance(r) for r in page], total, limit, offset)


@bp.get("/remittance-periods/<r_id>")
@require_roles(ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER, ROLE_TREASURER)
def get_remittance(r_id: str, **_kw):
    with store().lock:
        r = _get_remittance_or_404(r_id)
        return ok(serialize_remittance(r))


def _aggregate(r: dict) -> None:
    """Aggregate monthly totals from APPROVED/PAID paychecks into r in place."""
    tax_year = r["tax_year"]
    tax_month = r["tax_month"]
    paychecks = paychecks_in_year_month(tax_year, tax_month)
    fed = 0
    state = 0
    local = 0
    ss = 0
    med = 0
    med_add = 0
    by_state: dict[str, int] = {}
    s = store()
    for pc in paychecks:
        if pc["status"] not in ("APPROVED", "PAID"):
            continue
        fed += pc.get("federal_withholding_cents") or 0
        state_amt = pc.get("state_withholding_cents") or 0
        state += state_amt
        local += pc.get("local_withholding_cents") or 0
        ss += pc.get("social_security_cents") or 0
        med += pc.get("medicare_base_cents") or 0
        med_add += pc.get("medicare_additional_cents") or 0
        emp = s.employees.get(pc["employee_id"])
        if emp is not None:
            work_state = emp["work_state"]
            by_state[work_state] = by_state.get(work_state, 0) + state_amt
    r["total_federal_withholding_cents"] = fed
    r["total_state_withholding_cents"] = state
    r["total_local_withholding_cents"] = local
    r["total_social_security_cents"] = ss * 2  # employer match
    r["total_medicare_cents"] = med * 2        # employer match base only
    r["total_medicare_additional_cents"] = med_add  # no employer match
    # Stable ordering by state name
    r["state_breakdown"] = [
        {"state": k, "amount_cents": by_state[k]} for k in sorted(by_state.keys())
    ]


@bp.post("/remittance-periods/<r_id>/finalize")
@require_roles(ROLE_PAYROLL_MANAGER)
def finalize_remittance(r_id: str, _caller_id: str | None = None, **_kw):
    s = store()
    with s.lock:
        r = _get_remittance_or_404(r_id)
        body = require_json_object()
        version = body.get("version")
        if r["status"] != "DRAFT":
            raise err_remittance_not_draft()
        # Preconditions
        periods = pay_periods_in_year_month(r["tax_year"], r["tax_month"])
        if any(p["status"] != "CLOSED" for p in periods):
            raise err_open_pay_periods_in_month()
        paychecks = paychecks_in_year_month(r["tax_year"], r["tax_month"])
        if any(pc["status"] in ("DRAFT", "CALCULATED") for pc in paychecks):
            raise err_unapproved_paychecks_in_month()
        occ_check(version, r["version"])

        _aggregate(r)
        r["status"] = "FINALIZED"
        r["finalizer_id"] = _caller_id
        r["updated_at"] = now_iso()
        r["version"] = r["version"] + 1
        return ok(serialize_remittance(r))


@bp.post("/remittance-periods/<r_id>/reopen")
@require_roles(ROLE_PAYROLL_MANAGER)
def reopen_remittance(r_id: str, **_kw):
    s = store()
    with s.lock:
        r = _get_remittance_or_404(r_id)
        body = require_json_object()
        version = body.get("version")
        if r["status"] != "FINALIZED":
            raise err_remittance_not_finalized()
        # Cannot reopen if ever remitted — i.e. status was never REMITTED.
        # We track this with a flag.
        if r.get("ever_remitted"):
            raise err_remittance_not_finalized("Remittance has been remitted before; cannot reopen")
        occ_check(version, r["version"])
        r["status"] = "DRAFT"
        r["total_federal_withholding_cents"] = 0
        r["total_state_withholding_cents"] = 0
        r["total_local_withholding_cents"] = 0
        r["total_social_security_cents"] = 0
        r["total_medicare_cents"] = 0
        r["total_medicare_additional_cents"] = 0
        r["state_breakdown"] = []
        r["updated_at"] = now_iso()
        r["version"] = r["version"] + 1
        return ok(serialize_remittance(r))


@bp.post("/remittance-periods/<r_id>/remit")
@require_roles(ROLE_TREASURER)
def remit_remittance(r_id: str, _caller_id: str | None = None, **_kw):
    s = store()
    with s.lock:
        r = _get_remittance_or_404(r_id)
        body = require_json_object()
        version = body.get("version")
        if r["status"] not in ("FINALIZED", "AMENDED"):
            raise err_remittance_not_finalized()
        # SOD: differ from finalizer (and amender if applicable)
        if _caller_id == r.get("finalizer_id"):
            raise err_segregation_of_duties("Treasurer must differ from finalizer")
        if r["status"] == "AMENDED" and _caller_id == r.get("amender_id"):
            raise err_segregation_of_duties("Treasurer must differ from amender")
        occ_check(version, r["version"])
        r["status"] = "REMITTED"
        r["ever_remitted"] = True
        r["updated_at"] = now_iso()
        r["version"] = r["version"] + 1
        return ok(serialize_remittance(r))


@bp.post("/remittance-periods/<r_id>/amend")
@require_roles(ROLE_PAYROLL_MANAGER)
def amend_remittance(r_id: str, _caller_id: str | None = None, **_kw):
    s = store()
    with s.lock:
        r = _get_remittance_or_404(r_id)
        body = require_json_object()
        version = body.get("version")
        if r["status"] != "REMITTED":
            raise err_remittance_not_remitted()
        # At least one VOIDED paycheck in this month with a correction paycheck APPROVED
        paychecks = paychecks_in_year_month(r["tax_year"], r["tax_month"])
        # Find VOIDED paychecks; check that there exists a correction paycheck (any month)
        # for the same source that has reached APPROVED.
        # Per scaffold: "At least one Paycheck in (tax_year, tax_month) is now VOIDED
        # with a corresponding correction Paycheck APPROVED"
        store_ref = store()
        has_basis = False
        for vpc in paychecks:
            if vpc["status"] != "VOIDED":
                continue
            # Find a correction paycheck whose correction_of_paycheck_id == vpc.id
            for cpc in store_ref.paychecks.values():
                if cpc.get("correction_of_paycheck_id") == vpc["id"] and cpc["status"] == "APPROVED":
                    has_basis = True
                    break
            if has_basis:
                break
        if not has_basis:
            raise err_no_amendment_basis()

        occ_check(version, r["version"])

        _aggregate(r)
        r["status"] = "AMENDED"
        r["amender_id"] = _caller_id
        r["updated_at"] = now_iso()
        r["version"] = r["version"] + 1
        return ok(serialize_remittance(r))
