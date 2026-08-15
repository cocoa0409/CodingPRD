"""Lease agreements (PRD 3.3)."""
from flask import Blueprint, g, request

import domain
from calc import early_termination_fee
from envelope import ok, ok_list
from errors import ApiError, invalid_state, not_found, validation
from http_util import (
    LEASE_TYPES, get_body, parse_pagination, require_roles,
    v_date, v_enum, v_int, v_str,
)
from store import db, new_entity, today, touch

bp_leases = Blueprint("leases", __name__)

READ_ROLES = ("SystemAdmin", "LeaseAdmin", "FleetPlanner", "BillingAnalyst", "ComplianceOfficer")
LEASE_STATUSES = {"DRAFT", "PENDING_APPROVAL", "ACTIVE", "EXPIRED", "TERMINATED"}


def _load_lessee_ref(lessee_id):
    lessee = db.lessees.get(lessee_id)
    if lessee is None:
        raise not_found("ERR_LESSEE_NOT_FOUND", f"Lessee {lessee_id} not found")
    return lessee


@bp_leases.route("/lease-agreements", methods=["POST"])
@require_roles("LeaseAdmin")
def create_lease():
    body = get_body()
    lessee_id = v_str(body, "lessee_id")
    lease_type = v_enum(body, "lease_type", LEASE_TYPES)
    rate = v_int(body, "base_daily_rate_cents", min=1)
    share_pct = v_int(body, "car_hire_lessor_share_pct", min=0, max=100)
    cap = v_int(body, "authorized_repair_cap_cents", min=0)
    start = v_date(body, "start_date")
    end = v_date(body, "end_date")
    _load_lessee_ref(lessee_id)
    lease = new_entity(
        {
            "lessee_id": lessee_id,
            "lease_type": lease_type,
            "base_daily_rate_cents": rate,
            "car_hire_lessor_share_pct": share_pct,
            "authorized_repair_cap_cents": cap,
            "start_date": start,
            "end_date": end,
            "submitted_by_user_id": None,
            "early_termination_fee_cents": None,
            "status": "DRAFT",
        }
    )
    db.leases[lease["id"]] = lease
    return ok(domain.serialize_lease(lease), status=201)


@bp_leases.route("/lease-agreements", methods=["GET"])
@require_roles(*READ_ROLES)
def list_leases():
    limit, offset = parse_pagination()
    items = sorted(db.leases.values(), key=lambda l: (l["created_at"], l["_created_seq"]))
    for l in items:
        domain.lazy_expire_lease(l)
    lessee_id = request.args.get("lessee_id")
    status = request.args.get("status")
    if lessee_id is not None:
        items = [l for l in items if l["lessee_id"] == lessee_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.serialize_lease(l) for l in page], limit, offset, total)


@bp_leases.route("/lease-agreements/<lease_id>", methods=["GET"])
@require_roles(*READ_ROLES, "LesseeRep")
def get_lease(lease_id):
    lease = domain.load_lease(lease_id)
    domain.check_lessee_ownership(lease["lessee_id"])
    return ok(domain.serialize_lease(lease))


@bp_leases.route("/lease-agreements/<lease_id>/submit", methods=["POST"])
@require_roles("LeaseAdmin")
def submit_lease(lease_id):
    lease = domain.load_lease(lease_id)
    if lease["status"] != "DRAFT":
        raise invalid_state(f"Lease in status {lease['status']} cannot be submitted")
    lessee = db.lessees.get(lease["lessee_id"])
    if lessee is None or lessee["status"] != "ACTIVE":
        raise ApiError("ERR_LESSEE_NOT_ACTIVE", 409, "Lessee is not ACTIVE")
    lease["status"] = "PENDING_APPROVAL"
    lease["submitted_by_user_id"] = g.user_id
    touch(lease)
    return ok(domain.serialize_lease(lease))


@bp_leases.route("/lease-agreements/<lease_id>/approve", methods=["POST"])
@require_roles("ComplianceOfficer")
def approve_lease(lease_id):
    lease = domain.load_lease(lease_id)
    if lease["status"] != "PENDING_APPROVAL":
        raise invalid_state(f"Lease in status {lease['status']} cannot be approved")
    lessee = db.lessees.get(lease["lessee_id"])
    if lessee is None or lessee["status"] != "ACTIVE":
        raise ApiError("ERR_LESSEE_NOT_ACTIVE", 409, "Lessee is not ACTIVE")
    if lease["end_date"] <= lease["start_date"]:
        raise ApiError(
            "ERR_INVALID_DATE_RANGE", 422,
            "Lease end_date must be strictly after start_date",
        )
    lease["status"] = "ACTIVE"
    touch(lease)
    return ok(domain.serialize_lease(lease))


@bp_leases.route("/lease-agreements/<lease_id>/reject", methods=["POST"])
@require_roles("ComplianceOfficer")
def reject_lease(lease_id):
    lease = domain.load_lease(lease_id)
    if lease["status"] != "PENDING_APPROVAL":
        raise invalid_state(f"Lease in status {lease['status']} cannot be rejected")
    lease["status"] = "DRAFT"
    touch(lease)
    return ok(domain.serialize_lease(lease))


@bp_leases.route("/lease-agreements/<lease_id>", methods=["PATCH"])
@require_roles("LeaseAdmin")
def amend_lease(lease_id):
    lease = domain.load_lease(lease_id)
    body = get_body()
    expected = v_int(body, "expected_lease_version")
    new_rate = v_int(body, "base_daily_rate_cents", required=False, min=1)
    new_share = v_int(body, "car_hire_lessor_share_pct", required=False, min=0, max=100)
    new_cap = v_int(body, "authorized_repair_cap_cents", required=False, min=0)
    new_end = v_date(body, "end_date", required=False)
    if lease["status"] not in ("DRAFT", "ACTIVE"):
        raise invalid_state(f"Lease in status {lease['status']} cannot be amended")
    if expected != lease["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412,
            f"expected_lease_version {expected} does not match current version {lease['version']}",
        )
    if new_rate is not None:
        lease["base_daily_rate_cents"] = new_rate
    if new_share is not None:
        lease["car_hire_lessor_share_pct"] = new_share
    if new_cap is not None:
        lease["authorized_repair_cap_cents"] = new_cap
    if new_end is not None:
        lease["end_date"] = new_end
    touch(lease)
    return ok(domain.serialize_lease(lease))


@bp_leases.route("/lease-agreements/<lease_id>/terminate", methods=["POST"])
@require_roles("LeaseAdmin")
def terminate_lease(lease_id):
    lease = domain.load_lease(lease_id)
    if lease["status"] != "ACTIVE":
        raise invalid_state(f"Lease in status {lease['status']} cannot be terminated")
    fee = early_termination_fee(lease, today())
    lease["early_termination_fee_cents"] = fee
    lease["status"] = "TERMINATED"
    touch(lease)
    # cascade: every SCHEDULED assignment of this lease -> CANCELLED
    for a in db.assignments.values():
        if a["lease_id"] == lease_id and a["status"] == "SCHEDULED":
            a["status"] = "CANCELLED"
            a["cancellation_reason"] = "LEASE_TERMINATED"
            touch(a)
    lessee = db.lessees.get(lease["lessee_id"])
    if lessee is not None:
        domain.balance_add(lessee, fee)
    return ok(domain.serialize_lease(lease))


@bp_leases.route("/lease-agreements/<lease_id>/assignments", methods=["GET"])
@require_roles(*READ_ROLES)
def lease_assignments(lease_id):
    domain.load_lease(lease_id)
    limit, offset = parse_pagination()
    items = [
        a for a in db.assignments.values() if a["lease_id"] == lease_id
    ]
    items.sort(key=lambda a: (a["created_at"], a["_created_seq"]))
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.serialize_assignment(a) for a in page], limit, offset, total)
