from flask import Blueprint, request, g

from errors import (
    raise_error, ERR_NOT_FOUND, ERR_REFERENCED_ENTITY_MISSING, ERR_INVALID_LEASE_STATE,
    ERR_SEGREGATION_OF_DUTIES, ERR_HAS_OPEN_RESERVATIONS, ERR_HAS_DRAFT_BILLS, ERR_FORBIDDEN,
)
from response import success
from middleware import require_roles
from util import add_common_fields, bump, check_version, parse_date, parse_iso, now_iso_string
from db import db
from services.lease_service import compute_termination_penalty, lease_view
from services.bill_service import get_or_create_draft_bill, append_line, recompute_bill_totals
from services.tenant_service import refresh_tenant

bp = Blueprint("leases", __name__)


@bp.route("/leases", methods=["POST"])
def draft_lease():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    tenant_id = body.get("tenant_id")
    billing_plan = body.get("billing_plan")
    monthly_rate = body.get("monthly_rate_cents", 0)
    term_start = body.get("term_start_date")
    term_end = body.get("term_end_date")

    if billing_plan not in ("HOURLY", "DAILY", "MONTHLY"):
        raise_error(("ERR_INVALID_INPUT", 422), "billing_plan must be HOURLY/DAILY/MONTHLY")
    if not isinstance(monthly_rate, int) or monthly_rate < 0:
        raise_error(("ERR_INVALID_INPUT", 422), "monthly_rate_cents must be >= 0")
    ts = parse_date(term_start)
    te = parse_date(term_end)
    if ts is None or te is None:
        raise_error(("ERR_INVALID_INPUT", 422), "Invalid term dates")
    tenant = db.tenants.get(tenant_id)
    if not tenant:
        raise_error(ERR_REFERENCED_ENTITY_MISSING, "Tenant not found")

    lease = {
        "tenant_id": tenant_id,
        "billing_plan": billing_plan,
        "monthly_rate_cents": monthly_rate,
        "term_start_date": term_start,
        "term_end_date": term_end,
        "status": "DRAFT",
        "reviewer_user_id": None,
        "termination_penalty_cents": None,
        "termination_effective_date": None,
    }
    add_common_fields(lease, db.now(), db.new_id())
    db.leases[lease["id"]] = lease
    return success(lease_view(lease), 201)


@bp.route("/leases/<lease_id>", methods=["GET"])
def get_lease(lease_id):
    require_roles("PlatformAdmin", "TenantAdmin")
    lease = db.leases.get(lease_id)
    if not lease:
        raise_error(ERR_NOT_FOUND, "Lease not found")
    if g.user_role == "TenantAdmin":
        m = g.acting_member
        if not m or m["tenant_id"] != lease["tenant_id"]:
            raise_error(ERR_FORBIDDEN, "Lease not accessible")
    return success(lease_view(lease))


@bp.route("/leases/<lease_id>/activate", methods=["POST"])
def activate_lease(lease_id):
    require_roles("PlatformAdmin")
    lease = db.leases.get(lease_id)
    if not lease:
        raise_error(ERR_NOT_FOUND, "Lease not found")
    body = request.get_json(silent=True) or {}
    check_version(lease, body.get("version"))
    if lease["status"] != "DRAFT":
        raise_error(ERR_INVALID_LEASE_STATE, "Only DRAFT leases can be activated")
    tenant = db.tenants.get(lease["tenant_id"])
    if not tenant or tenant["status"] != "ACTIVE":
        raise_error(("ERR_INVALID_LEASE_STATE", 409), "Tenant must be ACTIVE")
    ts = parse_date(lease["term_start_date"])
    te = parse_date(lease["term_end_date"])
    if ts > te:
        raise_error(("ERR_INVALID_LEASE_STATE", 409), "term_start_date must not be after term_end_date")
    lease["status"] = "ACTIVE"
    bump(lease, db.now())
    return success(lease_view(lease))


@bp.route("/leases/<lease_id>/request-termination", methods=["POST"])
def request_termination(lease_id):
    require_roles("TenantAdmin")
    lease = db.leases.get(lease_id)
    if not lease:
        raise_error(ERR_NOT_FOUND, "Lease not found")
    body = request.get_json(silent=True) or {}
    check_version(lease, body.get("version"))
    m = g.acting_member
    if not m or m["tenant_id"] != lease["tenant_id"]:
        raise_error(ERR_FORBIDDEN, "Cannot act on another tenant's lease")
    if lease["status"] != "ACTIVE":
        raise_error(ERR_INVALID_LEASE_STATE, "Lease is not ACTIVE")
    lease["status"] = "TERMINATION_REQUESTED"
    bump(lease, db.now())

    # Cascade: cancel future PENDING/CONFIRMED reservations of this tenant
    now = db.now()
    for r in db.reservations.values():
        if r["tenant_id"] != lease["tenant_id"]:
            continue
        if r["status"] in ("PENDING", "CONFIRMED"):
            start_at_dt = parse_iso(r["start_at"])
            if start_at_dt is not None and start_at_dt > now:
                r["status"] = "CANCELLED"
                r["provisional_fee_cents"] = 0
                bump(r, now)
    return success(lease_view(lease))


@bp.route("/leases/<lease_id>/withdraw-termination", methods=["POST"])
def withdraw_termination(lease_id):
    require_roles("TenantAdmin")
    lease = db.leases.get(lease_id)
    if not lease:
        raise_error(ERR_NOT_FOUND, "Lease not found")
    body = request.get_json(silent=True) or {}
    check_version(lease, body.get("version"))
    m = g.acting_member
    if not m or m["tenant_id"] != lease["tenant_id"]:
        raise_error(ERR_FORBIDDEN, "Cannot act on another tenant's lease")
    if lease["status"] != "TERMINATION_REQUESTED":
        raise_error(ERR_INVALID_LEASE_STATE, "Lease is not in TERMINATION_REQUESTED")
    lease["status"] = "ACTIVE"
    bump(lease, db.now())
    return success(lease_view(lease))


@bp.route("/leases/<lease_id>/begin-review", methods=["POST"])
def begin_review(lease_id):
    require_roles("PlatformAdmin")
    lease = db.leases.get(lease_id)
    if not lease:
        raise_error(ERR_NOT_FOUND, "Lease not found")
    body = request.get_json(silent=True) or {}
    check_version(lease, body.get("version"))
    if lease["status"] != "TERMINATION_REQUESTED":
        raise_error(ERR_INVALID_LEASE_STATE, "Lease is not in TERMINATION_REQUESTED")
    lease["status"] = "TERMINATION_REVIEWING"
    lease["reviewer_user_id"] = g.user_id
    bump(lease, db.now())
    # Recompute tenant access_posture (now it may be RESTRICTED)
    tenant = db.tenants.get(lease["tenant_id"])
    if tenant:
        refresh_tenant(tenant)
    return success(lease_view(lease))


@bp.route("/leases/<lease_id>/finalize-termination", methods=["POST"])
def finalize_termination(lease_id):
    require_roles("PlatformAdmin")
    lease = db.leases.get(lease_id)
    if not lease:
        raise_error(ERR_NOT_FOUND, "Lease not found")
    body = request.get_json(silent=True) or {}
    check_version(lease, body.get("version"))
    if lease["status"] != "TERMINATION_REVIEWING":
        raise_error(ERR_INVALID_LEASE_STATE, "Lease is not in TERMINATION_REVIEWING")
    if lease.get("reviewer_user_id") == g.user_id:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "Finalizer must differ from reviewer")

    tenant_id = lease["tenant_id"]
    # Check no open reservations
    for r in db.reservations.values():
        if r["tenant_id"] == tenant_id and r["status"] in ("PENDING", "CONFIRMED", "IN_USE"):
            raise_error(ERR_HAS_OPEN_RESERVATIONS, "Open reservations exist")
    # Check no DRAFT bills
    for b in db.bills.values():
        if b["tenant_id"] == tenant_id and b["status"] == "DRAFT":
            raise_error(ERR_HAS_DRAFT_BILLS, "DRAFT bills exist")

    now = db.now()
    effective_date = now.date()
    penalty = compute_termination_penalty(lease, effective_date)

    lease["status"] = "TERMINATED"
    lease["termination_effective_date"] = effective_date.isoformat()
    lease["termination_penalty_cents"] = penalty
    bump(lease, now)

    # Append bill line for termination penalty (creates DRAFT bill if needed)
    if penalty > 0:
        tenant = db.tenants.get(tenant_id)
        bill = get_or_create_draft_bill(tenant_id)
        append_line(bill, "TERMINATION_PENALTY", lease["id"], penalty)
        recompute_bill_totals(bill)
        bump(bill, now)

    # Tenant -> TERMINATING
    tenant = db.tenants.get(tenant_id)
    if tenant:
        tenant["status"] = "TERMINATING"
        refresh_tenant(tenant)
        bump(tenant, now)

    # Schedule badge suspends for all badges of this tenant's members
    members_of_tenant = {m["id"] for m in db.members.values() if m["tenant_id"] == tenant_id}
    for badge in db.access_badges.values():
        if badge["member_id"] in members_of_tenant and badge["status"] == "ACTIVE":
            badge["scheduled_suspend_on"] = effective_date.isoformat()

    return success(lease_view(lease))


@bp.route("/leases/<lease_id>/reject-termination", methods=["POST"])
def reject_termination(lease_id):
    require_roles("PlatformAdmin")
    lease = db.leases.get(lease_id)
    if not lease:
        raise_error(ERR_NOT_FOUND, "Lease not found")
    body = request.get_json(silent=True) or {}
    check_version(lease, body.get("version"))
    if lease["status"] != "TERMINATION_REVIEWING":
        raise_error(ERR_INVALID_LEASE_STATE, "Lease is not in TERMINATION_REVIEWING")
    lease["status"] = "REJECTED"
    bump(lease, db.now())
    tenant = db.tenants.get(lease["tenant_id"])
    if tenant:
        refresh_tenant(tenant)
    return success(lease_view(lease))
