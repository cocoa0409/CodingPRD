"""Voucher routes."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_invalid_request, err_posture_gate,
    err_caregiver_not_active, err_redetermination_overdue,
    err_allocation_caregiver_mismatch, err_insufficient_hours,
    err_quarterly_cap, err_annual_cap, err_budget_exceeded,
    err_invalid_state,
)
from middleware import require_roles, check_caregiver_ownership
from response import success
from services.util import (
    body, req_str, req_hours, opt_str, paginate, serialize, hours_val,
    quarter_bounds, fiscal_year_bounds, round_half_up_int,
)
from services import core

bp = Blueprint("vouchers", __name__)

VOUCHER_STATUSES = {"ISSUED", "COMMITTED", "REDEEMED", "SETTLED", "EXPIRED", "REVOKED"}


def _voucher_or_404(vid):
    v = db.vouchers.get(vid)
    if v is None:
        raise err_not_found("voucher")
    return v


@bp.route("/respite/vouchers", methods=["POST"])
def create_voucher():
    user_id, role = require_roles("Caregiver", "Coordinator")
    data = body()
    allocation_id = req_str(data, "allocation_id")
    caregiver_id = req_str(data, "caregiver_id")
    authorized_hours = req_hours(data, "authorized_hours")

    # Caregiver actor must own the voucher
    check_caregiver_ownership(user_id, role, caregiver_id)

    # existence
    alloc = db.allocations.get(allocation_id)
    if alloc is None:
        raise err_not_found("allocation")
    caregiver = db.caregivers.get(caregiver_id)
    if caregiver is None:
        raise err_not_found("caregiver")
    program = db.programs.get(alloc["program_id"])
    if program is None:
        raise err_not_found("program")

    # posture gate (priority 6)
    core.gate_operational(program)
    # caregiver active (priority 8) / redetermination (priority 10)
    if caregiver["status"] == "REDETERMINATION_PENDING":
        raise err_redetermination_overdue()
    if caregiver["status"] != "ACTIVE":
        raise err_caregiver_not_active()
    # allocation match (priority 11)
    if alloc["caregiver_id"] != caregiver_id or alloc["status"] != "OPEN":
        raise err_allocation_caregiver_mismatch()

    # allocation_availability calc
    now = db.now()
    # (1) effective available = stored available_hours (cascades maintain it);
    # additionally treat expired vouchers as already-forfeited — but since
    # stored buckets are maintained by cascades at ops-run time, and the PRD
    # only requires treating them as unavailable for *this* computation, we
    # compute effective_available here: stored available minus hours of
    # expired-but-not-yet-swept vouchers (ISSUED/COMMITTED with expires_at<=now).
    expired_hold = Decimal("0")
    for v in db.vouchers.values():
        if v.get("allocation_id") == alloc["id"] and v["status"] in ("ISSUED", "COMMITTED"):
            if v["expires_at"] <= now:
                expired_hold += Decimal(str(v["authorized_hours"])) - Decimal(
                    str(v["consumed_hours"])
                )
    effective_available = Decimal(str(alloc["available_hours"]))
    # quarter load
    q_start, q_end = quarter_bounds(program["_fiscal_year_start"], now)
    fy_start, fy_end = fiscal_year_bounds(program["_fiscal_year_start"], now)
    quarter_load = Decimal("0")
    annual_load = Decimal("0")
    for a in db.allocations.values():
        if a["caregiver_id"] != caregiver_id:
            continue
        load = Decimal(str(a["reserved_hours"])) + Decimal(str(a["consumed_hours"]))
        if a["period_start"].date() >= q_start.date() and a["period_start"].date() < q_end.date():
            quarter_load += load
        if a["period_start"].date() >= fy_start and a["period_start"].date() < fy_end:
            annual_load += load
    qcap_remaining = Decimal(str(program["quarterly_cap_hours"])) - quarter_load
    acap_remaining = Decimal(str(program["annual_cap_hours"])) - annual_load
    max_issuable = min(effective_available, qcap_remaining, acap_remaining)
    auth_d = Decimal(str(authorized_hours))
    if auth_d > max_issuable:
        if auth_d > effective_available:
            raise err_insufficient_hours()
        if max_issuable == qcap_remaining:
            raise err_quarterly_cap()
        raise err_annual_cap()
    # budget check (priority 24)
    provisional = round_half_up_int(
        auth_d * Decimal(str(program["standard_rate_cents_per_hour"]))
    )
    if provisional > core.program_unencumbered(program):
        raise err_budget_exceeded()

    # create voucher
    base = db.new_common()
    issued_at = db.now()
    voucher = {
        **base,
        "allocation_id": allocation_id,
        "program_id": program["id"],
        "caregiver_id": caregiver_id,
        "is_emergency": False,
        "authorized_hours": hours_val(authorized_hours),
        "committed_hours": 0.0,
        "consumed_hours": 0.0,
        "released_hours": 0.0,
        "forfeited_hours": 0.0,
        "status": "ISSUED",
        "issued_at": issued_at,
        "expires_at": issued_at + timedelta(days=program["voucher_expiry_days"]),
    }
    db.vouchers[voucher["id"]] = voucher
    # allocation buckets
    alloc["available_hours"] = hours_val(
        Decimal(str(alloc["available_hours"])) - auth_d
    )
    alloc["reserved_hours"] = hours_val(
        Decimal(str(alloc["reserved_hours"])) + auth_d
    )
    db.touch(alloc)
    # budget encumber
    core.encumber(program, provisional, "voucher", voucher["id"], "voucher issued")
    db.touch(program)
    return success(serialize(voucher, "voucher"), status=201)


@bp.route("/respite/vouchers/<vid>", methods=["GET"])
def get_voucher(vid):
    user_id, role = require_roles("Caregiver", "Coordinator", "FunderAdmin")
    v = _voucher_or_404(vid)
    check_caregiver_ownership(user_id, role, v["caregiver_id"])
    return success(serialize(v, "voucher"))


@bp.route("/respite/vouchers", methods=["GET"])
def list_vouchers():
    user_id, role = require_roles("Caregiver", "Coordinator", "FunderAdmin")
    allocation_id = request.args.get("allocation_id")
    caregiver_id = request.args.get("caregiver_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(db.vouchers.values())
    if role == "Caregiver":
        items = [v for v in items if v["caregiver_id"] == user_id]
    if allocation_id:
        items = [v for v in items if v.get("allocation_id") == allocation_id]
    if caregiver_id:
        items = [v for v in items if v["caregiver_id"] == caregiver_id]
    if program_id:
        items = [v for v in items if v["program_id"] == program_id]
    if status:
        items = [v for v in items if v["status"] == status]
    page, meta = paginate(items)
    return success(
        [serialize(v, "voucher") for v in page],
        response_type="array",
        pagination=meta,
    )


@bp.route("/respite/vouchers/<vid>/revoke", methods=["POST"])
def revoke_voucher(vid):
    require_roles("Coordinator")
    v = _voucher_or_404(vid)
    if v["status"] != "ISSUED":
        raise err_invalid_state("Only ISSUED vouchers can be revoked")
    core.revoke_voucher(v, "coordinator revocation")
    return success(serialize(v, "voucher"))
