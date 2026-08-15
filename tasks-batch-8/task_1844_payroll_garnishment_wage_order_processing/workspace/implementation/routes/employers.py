"""Employer enrollment and configuration (PRD §3.1)."""

from flask import Blueprint, g

from db import logical_now, next_seq, store
from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, fail
from middleware import (
    ALL_ROLES,
    ROLE_ADMIN,
    authorize,
    get_body,
    opt_enum,
    opt_int,
    pagination,
    public,
    req_enum,
    req_int,
    req_object,
    req_str,
    req_date,
    sort_created,
)
from response import list_response, object_response
from services import audit
from util import new_uuid, render_instant

bp = Blueprint("employers", __name__)

REMITTANCE_TIMINGS = ("SAME_DAY", "NEXT_BUSINESS_DAY", "THREE_BUSINESS_DAYS")
FEE_POLICIES = ("NONE", "PER_ORDER")


def _validate_calendar(body):
    calendar = req_object(body, "payroll_calendar")
    for key in ("period_start", "period_end", "pay_date"):
        if key not in calendar or not isinstance(calendar[key], str):
            fail(ERR_INVALID_REQUEST, 400,
                 "payroll_calendar must include '%s' (YYYY-MM-DD)." % key)
        req_date(calendar, key)
    return {
        "period_start": calendar["period_start"],
        "period_end": calendar["period_end"],
        "pay_date": calendar["pay_date"],
    }


def get_employer_or_404(employer_id):
    employer = store.employers.get(employer_id)
    if employer is None:
        fail(ERR_NOT_FOUND, 404, "Employer '%s' does not exist." % employer_id)
    return employer


@bp.post("/employers")
def create_employer():
    authorize(ROLE_ADMIN)
    body = get_body()
    legal_name = req_str(body, "legal_name")
    fein = req_str(body, "fein")
    remittance_timing = req_enum(body, "remittance_timing", REMITTANCE_TIMINGS)
    calendar = _validate_calendar(body)
    fee_policy = req_enum(body, "administrative_fee_policy", FEE_POLICIES)
    admin_fee_cents = opt_int(body, "admin_fee_cents", 0)
    if admin_fee_cents < 0:
        fail(ERR_INVALID_REQUEST, 400, "admin_fee_cents must be >= 0.")

    if any(e["fein"] == fein for e in store.employers.values()):
        fail(ERR_INVALID_REQUEST, 400, "fein '%s' is already registered." % fein)

    now = render_instant(logical_now())
    employer = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "legal_name": legal_name,
        "fein": fein,
        "remittance_timing": remittance_timing,
        "payroll_calendar": calendar,
        "administrative_fee_policy": fee_policy,
        "admin_fee_cents": admin_fee_cents,
        "_seq": next_seq(),
    }
    store.employers[employer["id"]] = employer
    return object_response(public(employer), 201)


@bp.get("/employers/<employerId>")
def get_employer(employerId):
    authorize(*ALL_ROLES)
    return object_response(public(get_employer_or_404(employerId)))


@bp.patch("/employers/<employerId>")
def update_employer(employerId):
    authorize(ROLE_ADMIN)
    employer = get_employer_or_404(employerId)
    body = get_body()
    changes = {}

    timing = opt_enum(body, "remittance_timing", REMITTANCE_TIMINGS)
    if timing is not None:
        employer["remittance_timing"] = timing
        changes["remittance_timing"] = timing
    policy = opt_enum(body, "administrative_fee_policy", FEE_POLICIES)
    if policy is not None:
        employer["administrative_fee_policy"] = policy
        changes["administrative_fee_policy"] = policy
    fee = opt_int(body, "admin_fee_cents")
    if fee is not None:
        if fee < 0:
            fail(ERR_INVALID_REQUEST, 400, "admin_fee_cents must be >= 0.")
        employer["admin_fee_cents"] = fee
        changes["admin_fee_cents"] = fee

    employer["version"] += 1
    employer["updated_at"] = render_instant(logical_now())
    audit.append_audit(employer["id"], "Employer", employer["id"],
                       "employer.update", details={"changes": changes})
    return object_response(public(employer))


@bp.get("/employers/<employerId>/employees")
def list_employer_employees(employerId):
    authorize(*ALL_ROLES)
    get_employer_or_404(employerId)
    limit, offset = pagination()
    items = sort_created(
        [e for e in store.employees.values() if e["employer_id"] == employerId]
    )
    page = items[offset:offset + limit]
    return list_response([public(e) for e in page], len(items), limit, offset)


@bp.get("/employers/<employerId>/payroll-runs")
def list_employer_runs(employerId):
    authorize(*ALL_ROLES)
    get_employer_or_404(employerId)
    limit, offset = pagination()
    items = sort_created(
        [r for r in store.runs.values() if r["employer_id"] == employerId]
    )
    page = items[offset:offset + limit]
    return list_response([public(r) for r in page], len(items), limit, offset)


@bp.get("/employers/<employerId>/remittances")
def list_employer_remittances(employerId):
    authorize(*ALL_ROLES)
    get_employer_or_404(employerId)
    limit, offset = pagination()
    items = [r for r in store.remittances.values() if r["employer_id"] == employerId]
    from flask import request
    authority_id = request.args.get("authority_id")
    payroll_run_id = request.args.get("payroll_run_id")
    status = request.args.get("status")
    if authority_id is not None:
        items = [r for r in items if r["authority_id"] == authority_id]
    if payroll_run_id is not None:
        items = [r for r in items if r["payroll_run_id"] == payroll_run_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_created(items)
    page = items[offset:offset + limit]
    return list_response([public(r) for r in page], len(items), limit, offset)
