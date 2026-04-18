"""Lease routes."""
from datetime import date

from flask import Blueprint

from clock import get_now, parse_iso
from common import stamp_new, stamp_update, get_json_body, check_version
from db import db
from errors import api_error
from middleware import require_roles, get_auth
from response import success
from services.tenant import recompute_tenant
from services.bill import get_or_create_draft_bill, add_bill_line, recompute_bill_totals
from decimal import Decimal
from services.money import round_half_up_to_int


bp = Blueprint("leases", __name__)

PENALTY_FACTOR = Decimal("0.3")


def _parse_date(s):
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _floor_months_between(from_date: date, to_date: date) -> int:
    """Count full calendar-month boundaries strictly after from_date up to and including to_date."""
    if to_date <= from_date:
        return 0
    count = 0
    y, m = from_date.year, from_date.month
    # Next month's 1st (strictly after from_date):
    while True:
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1
        boundary = date(y, m, 1)
        if boundary > to_date:
            break
        count += 1
    return count


@bp.route("/leases", methods=["POST"])
def create_lease():
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    tenant_id = body.get("tenant_id")
    billing_plan = body.get("billing_plan")
    term_start_date = body.get("term_start_date")
    term_end_date = body.get("term_end_date")

    if not tenant_id:
        raise api_error("ERR_REFERENCED_ENTITY_MISSING", "tenant_id required")
    if tenant_id not in db.tenants:
        raise api_error("ERR_REFERENCED_ENTITY_MISSING", "tenant not found")
    if billing_plan not in ("HOURLY", "DAILY", "MONTHLY"):
        raise api_error("ERR_INVALID_TIME_WINDOW", "invalid billing_plan")
    if not term_start_date or not term_end_date:
        raise api_error("ERR_INVALID_TIME_WINDOW", "term dates required")
    monthly_rate = body.get("monthly_rate_cents", 0)
    if not isinstance(monthly_rate, int) or monthly_rate < 0:
        raise api_error("ERR_INVALID_TIME_WINDOW", "monthly_rate_cents must be non-negative integer")

    lease = {
        "tenant_id": tenant_id,
        "billing_plan": billing_plan,
        "monthly_rate_cents": monthly_rate,
        "term_start_date": term_start_date,
        "term_end_date": term_end_date,
        "status": "DRAFT",
        "termination_effective_date": None,
        "termination_penalty_cents": 0,
    }
    stamp_new(lease)
    db.leases[lease["id"]] = lease
    return success(lease, status=201)


@bp.route("/leases/<lease_id>", methods=["GET"])
def get_lease(lease_id):
    require_roles(["PlatformAdmin", "TenantAdmin"])
    lease = db.leases.get(lease_id)
    if not lease:
        raise api_error("ERR_NOT_FOUND", "lease not found")
    return success(lease)


@bp.route("/leases/<lease_id>/activate", methods=["POST"])
def activate_lease(lease_id):
    require_roles(["PlatformAdmin"])
    lease = db.leases.get(lease_id)
    if not lease:
        raise api_error("ERR_NOT_FOUND", "lease not found")
    body = get_json_body()
    check_version(lease, body)
    if lease["status"] != "DRAFT":
        raise api_error("ERR_INVALID_LEASE_STATE", "lease not in DRAFT")
    tenant = db.tenants.get(lease["tenant_id"])
    if not tenant or tenant["status"] != "ACTIVE":
        raise api_error("ERR_INVALID_LEASE_STATE", "tenant not ACTIVE")
    sd = _parse_date(lease["term_start_date"])
    ed = _parse_date(lease["term_end_date"])
    if not sd or not ed or sd > ed:
        raise api_error("ERR_INVALID_TIME_WINDOW", "invalid term dates")

    lease["status"] = "ACTIVE"
    stamp_update(lease)
    return success(lease)


@bp.route("/leases/<lease_id>/request-termination", methods=["POST"])
def request_termination(lease_id):
    user_id, role = require_roles(["TenantAdmin"])
    lease = db.leases.get(lease_id)
    if not lease:
        raise api_error("ERR_NOT_FOUND", "lease not found")
    body = get_json_body()
    check_version(lease, body)
    if lease["status"] != "ACTIVE":
        raise api_error("ERR_INVALID_LEASE_STATE", "lease not ACTIVE")

    # TenantAdmin must belong to this lease's tenant
    caller = db.members.get(user_id)
    if not caller or caller["tenant_id"] != lease["tenant_id"]:
        raise api_error("ERR_FORBIDDEN", "TenantAdmin may only act on own tenant leases")

    lease["status"] = "TERMINATION_REQUESTED"
    stamp_update(lease)

    # Cascade-cancel future reservations
    now = get_now()
    for r in db.reservations.values():
        if r["tenant_id"] == lease["tenant_id"] and r["status"] in ("PENDING", "CONFIRMED"):
            start_at = parse_iso(r["start_at"])
            if start_at > now:
                r["status"] = "CANCELLED"
                r["provisional_fee_cents"] = 0
                stamp_update(r)

    recompute_tenant(lease["tenant_id"])
    return success(lease)


@bp.route("/leases/<lease_id>/withdraw-termination", methods=["POST"])
def withdraw_termination(lease_id):
    user_id, role = require_roles(["TenantAdmin"])
    lease = db.leases.get(lease_id)
    if not lease:
        raise api_error("ERR_NOT_FOUND", "lease not found")
    body = get_json_body()
    check_version(lease, body)
    if lease["status"] != "TERMINATION_REQUESTED":
        raise api_error("ERR_INVALID_LEASE_STATE", "lease not TERMINATION_REQUESTED")

    caller = db.members.get(user_id)
    if not caller or caller["tenant_id"] != lease["tenant_id"]:
        raise api_error("ERR_FORBIDDEN", "TenantAdmin may only act on own tenant leases")

    lease["status"] = "ACTIVE"
    stamp_update(lease)
    return success(lease)


@bp.route("/leases/<lease_id>/begin-review", methods=["POST"])
def begin_review(lease_id):
    user_id, role = require_roles(["PlatformAdmin"])
    lease = db.leases.get(lease_id)
    if not lease:
        raise api_error("ERR_NOT_FOUND", "lease not found")
    body = get_json_body()
    check_version(lease, body)
    if lease["status"] != "TERMINATION_REQUESTED":
        raise api_error("ERR_INVALID_LEASE_STATE", "lease not TERMINATION_REQUESTED")

    lease["status"] = "TERMINATION_REVIEWING"
    lease["reviewer_user_id"] = user_id
    stamp_update(lease)
    recompute_tenant(lease["tenant_id"])
    return success(lease)


@bp.route("/leases/<lease_id>/finalize-termination", methods=["POST"])
def finalize_termination(lease_id):
    user_id, role = require_roles(["PlatformAdmin"])
    lease = db.leases.get(lease_id)
    if not lease:
        raise api_error("ERR_NOT_FOUND", "lease not found")
    body = get_json_body()
    check_version(lease, body)
    if lease["status"] != "TERMINATION_REVIEWING":
        raise api_error("ERR_INVALID_LEASE_STATE", "lease not TERMINATION_REVIEWING")

    if lease.get("reviewer_user_id") == user_id:
        raise api_error("ERR_SEGREGATION_OF_DUTIES",
                        "finalize-termination must be performed by a different PlatformAdmin than begin-review")

    # Check no open reservations
    for r in db.reservations.values():
        if r["tenant_id"] == lease["tenant_id"] and r["status"] in ("PENDING", "CONFIRMED", "IN_USE"):
            raise api_error("ERR_HAS_OPEN_RESERVATIONS",
                            "tenant has open reservations; cancel or complete first")

    # No DRAFT bills
    for b in db.bills.values():
        if b["tenant_id"] == lease["tenant_id"] and b["status"] == "DRAFT":
            raise api_error("ERR_HAS_DRAFT_BILLS", "tenant has DRAFT bills; issue or void first")

    # Compute termination_effective_date := today()
    today = get_now().date()
    lease["termination_effective_date"] = today.isoformat()

    # Compute penalty
    end_d = _parse_date(lease["term_end_date"])
    remaining_full_months = _floor_months_between(today, end_d) if end_d else 0
    remaining_full_months = max(0, remaining_full_months)
    if lease["billing_plan"] == "MONTHLY":
        penalty = round_half_up_to_int(
            Decimal(remaining_full_months) * Decimal(lease["monthly_rate_cents"]) * PENALTY_FACTOR
        )
    else:
        penalty = 0
    lease["termination_penalty_cents"] = penalty
    lease["status"] = "TERMINATED"
    stamp_update(lease)

    # Append BillLine to current DRAFT bill (create if missing)
    if penalty > 0:
        bill = get_or_create_draft_bill(lease["tenant_id"])
        add_bill_line(bill, "TERMINATION_PENALTY", lease["id"], penalty)
        recompute_bill_totals(bill)

    # Cascade: Tenant.status := TERMINATING
    tenant = db.tenants.get(lease["tenant_id"])
    if tenant:
        tenant["status"] = "TERMINATING"
        stamp_update(tenant)
        recompute_tenant(tenant["id"])

    return success(lease)


@bp.route("/leases/<lease_id>/reject-termination", methods=["POST"])
def reject_termination(lease_id):
    require_roles(["PlatformAdmin"])
    lease = db.leases.get(lease_id)
    if not lease:
        raise api_error("ERR_NOT_FOUND", "lease not found")
    body = get_json_body()
    check_version(lease, body)
    if lease["status"] != "TERMINATION_REVIEWING":
        raise api_error("ERR_INVALID_LEASE_STATE", "lease not TERMINATION_REVIEWING")

    lease["status"] = "REJECTED"
    stamp_update(lease)
    recompute_tenant(lease["tenant_id"])
    return success(lease)
