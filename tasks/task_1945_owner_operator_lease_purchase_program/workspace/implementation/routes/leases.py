"""LeaseAgreement routes, including the terminate/complete/default cascades."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import errors
import middleware
from db import db
from response import success
from services.core import (
    base_entity, touch, run_waterfall, recompute_classification,
)
from services.serialize import serialize_lease
from util import get_body, req_str, req_int, req_dt, opt_int, parse_pagination, paginate

bp = Blueprint("leases", __name__)


def _get_lease_or_404(lease_id):
    lease = db.lease_agreements.get(lease_id)
    if lease is None:
        raise errors.err(errors.ERR_LEASE_NOT_FOUND, "LeaseAgreement not found", 404)
    return lease


def escrow_for_lease(lease_id):
    for e in db.escrow_accounts.values():
        if e["lease_id"] == lease_id:
            return e
    return None


@bp.post("/lease-agreements")
def create_lease():
    middleware.require_roles({"LeaseAdmin"})
    body = get_body()
    owner_operator_id = req_str(body, "owner_operator_id")
    truck_id = req_str(body, "truck_id")
    start_date = req_dt(body, "start_date")
    term_weeks = req_int(body, "term_weeks")
    weekly_payment_cents = req_int(body, "weekly_payment_cents")
    escrow_weekly_contribution_cents = req_int(body, "escrow_weekly_contribution_cents")
    escrow_cap_cents = req_int(body, "escrow_cap_cents")
    buyout_base_price_cents = req_int(body, "buyout_base_price_cents")
    min_revenue_guarantee_weekly_cents = req_int(body, "min_revenue_guarantee_weekly_cents")

    # existence, body FKs validated left-to-right
    if owner_operator_id not in db.owner_operators:
        raise errors.err(errors.ERR_OPERATOR_NOT_FOUND, "OwnerOperator not found", 404)
    if truck_id not in db.trucks:
        raise errors.err(errors.ERR_TRUCK_NOT_FOUND, "Truck not found", 404)

    truck = db.trucks[truck_id]
    has_non_terminal_lease = any(
        l["truck_id"] == truck_id and l["status"] not in ("COMPLETED", "TERMINATED")
        for l in db.lease_agreements.values()
    )
    if truck["status"] != "AVAILABLE" or has_non_terminal_lease:
        raise errors.err(
            errors.ERR_TRUCK_NOT_AVAILABLE,
            "Truck must be AVAILABLE with no other non-terminal lease",
            409,
        )

    lease = base_entity()
    lease.update({
        "owner_operator_id": owner_operator_id,
        "truck_id": truck_id,
        "_start_date": start_date,
        "term_weeks": term_weeks,
        "weekly_payment_cents": weekly_payment_cents,
        "escrow_weekly_contribution_cents": escrow_weekly_contribution_cents,
        "escrow_cap_cents": escrow_cap_cents,
        "buyout_base_price_cents": buyout_base_price_cents,
        "min_revenue_guarantee_weekly_cents": min_revenue_guarantee_weekly_cents,
        "status": "APPLICATION",
        "missed_payment_count": 0,
        "arrears_cents": 0,
        "total_payments_applied_cents": 0,
        "escrow_satisfied": False,
    })
    db.lease_agreements[lease["id"]] = lease

    escrow = base_entity()
    escrow.update({
        "lease_id": lease["id"],
        "balance_cents": 0,
        "total_credited_cents": 0,
        "total_refunded_cents": 0,
        "total_applied_cents": 0,
        "status": "ACCUMULATING",
    })
    db.escrow_accounts[escrow["id"]] = escrow

    return success(serialize_lease(lease), "object", 201)


@bp.get("/lease-agreements")
def list_leases():
    middleware.require_roles(middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.lease_agreements.values())
    op_filter = request.args.get("owner_operator_id")
    truck_filter = request.args.get("truck_id")
    status_filter = request.args.get("status")
    if op_filter is not None:
        items = [l for l in items if l["owner_operator_id"] == op_filter]
    if truck_filter is not None:
        items = [l for l in items if l["truck_id"] == truck_filter]
    if status_filter is not None:
        items = [l for l in items if l["status"] == status_filter]
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    page, pg = paginate(items, limit, offset)
    return success([serialize_lease(l) for l in page], "array", 200, pagination=pg)


@bp.get("/lease-agreements/<lease_id>")
def get_lease(lease_id):
    middleware.require_roles(middleware.ALL_ROLES)
    return success(serialize_lease(_get_lease_or_404(lease_id)), "object", 200)


@bp.post("/lease-agreements/<lease_id>/activate")
def activate_lease(lease_id):
    middleware.require_roles({"LeaseAdmin"})
    lease = _get_lease_or_404(lease_id)
    if lease["status"] != "APPLICATION":
        raise errors.err(errors.ERR_LEASE_NOT_IN_APPLICATION, "Lease is not in APPLICATION", 409)
    operator = db.owner_operators[lease["owner_operator_id"]]
    if recompute_classification(operator) != "VERIFIED":
        raise errors.err(
            errors.ERR_COMPLIANCE_REQUIREMENTS_UNMET,
            "Operator classification_status must be VERIFIED to activate",
            422,
        )
    lease["status"] = "ACTIVE"
    touch(lease)
    truck = db.trucks[lease["truck_id"]]
    truck["status"] = "LEASED"
    touch(truck)
    return success(serialize_lease(lease), "object", 200)


@bp.post("/lease-agreements/<lease_id>/declare-default")
def declare_default(lease_id):
    middleware.require_roles({"LeaseAdmin"})
    lease = _get_lease_or_404(lease_id)
    if lease["status"] != "ACTIVE":
        raise errors.err(errors.ERR_LEASE_NOT_ACTIVE, "Lease is not ACTIVE", 409)
    if lease["missed_payment_count"] < 3:
        raise errors.err(
            errors.ERR_LEASE_NOT_DEFAULT_ELIGIBLE,
            "Lease requires missed_payment_count >= 3 to declare default",
            409,
        )
    lease["status"] = "DEFAULTED"
    touch(lease)

    # Cascade link 1: revoke ACCEPTED lanes
    for lane in db.lane_assignments.values():
        if lane["lease_id"] == lease["id"] and lane["status"] == "ACCEPTED":
            lane["status"] = "REVOKED"
            touch(lane)

    # Cascade link 2: recompute non-final settlements with guarantee stripped
    escrow = escrow_for_lease(lease["id"])
    for s in db.settlement_statements.values():
        if s["lease_id"] == lease["id"] and s["status"] in ("DRAFT", "ISSUED", "DISPUTED"):
            run_waterfall(s, lease, escrow, maintenance_basis="provisional",
                          guarantee_forced_zero=True)
            touch(s)

    return success(serialize_lease(lease), "object", 200)


@bp.post("/lease-agreements/<lease_id>/cure-default")
def cure_default(lease_id):
    middleware.require_roles({"LeaseAdmin"})
    lease = _get_lease_or_404(lease_id)
    body = get_body()
    arrears_payment_cents = opt_int(body, "arrears_payment_cents")
    if arrears_payment_cents is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "arrears_payment_cents is required", 400)
    if lease["status"] != "DEFAULTED":
        raise errors.err(errors.ERR_LEASE_NOT_DEFAULTED, "Lease is not DEFAULTED", 409)
    if arrears_payment_cents < lease["arrears_cents"]:
        raise errors.err(
            errors.ERR_ARREARS_NOT_CLEARED,
            "arrears_payment_cents must be >= arrears_cents",
            422,
        )
    overpayment = arrears_payment_cents - lease["arrears_cents"]
    lease["status"] = "ACTIVE"
    lease["arrears_cents"] = 0
    lease["missed_payment_count"] = 0
    touch(lease)

    if overpayment > 0:
        escrow = escrow_for_lease(lease["id"])
        room = max(0, lease["escrow_cap_cents"] - escrow["balance_cents"])
        credited = min(overpayment, room)
        if credited > 0:
            escrow["balance_cents"] += credited
            escrow["total_credited_cents"] += credited
            touch(escrow)

    return success(serialize_lease(lease), "object", 200)


@bp.post("/lease-agreements/<lease_id>/terminate")
def terminate_lease(lease_id):
    middleware.require_roles({"LeaseAdmin"})
    lease = _get_lease_or_404(lease_id)
    if lease["status"] in ("COMPLETED", "TERMINATED"):
        raise errors.err(errors.ERR_LEASE_ALREADY_TERMINAL, "Lease is already terminal", 409)

    was_active_or_defaulted = lease["status"] in ("ACTIVE", "DEFAULTED")
    lease["status"] = "TERMINATED"
    touch(lease)

    if was_active_or_defaulted:
        truck = db.trucks[lease["truck_id"]]
        if truck["status"] == "LEASED":
            truck["status"] = "IN_RETURN"
            touch(truck)

    # escrow applied to arrears, then REFUND_PENDING / CLOSED
    escrow = escrow_for_lease(lease["id"])
    applied = min(escrow["balance_cents"], lease["arrears_cents"])
    if applied > 0:
        escrow["balance_cents"] -= applied
        escrow["total_applied_cents"] += applied
        lease["arrears_cents"] -= applied
    if escrow["balance_cents"] > 0:
        escrow["status"] = "REFUND_PENDING"
    else:
        escrow["status"] = "CLOSED"
    touch(escrow)

    for lane in db.lane_assignments.values():
        if lane["lease_id"] == lease["id"] and lane["status"] in ("OFFERED", "ACCEPTED"):
            lane["status"] = "REVOKED"
            touch(lane)

    for s in db.settlement_statements.values():
        if s["lease_id"] == lease["id"] and s["status"] in ("DRAFT", "ISSUED", "DISPUTED"):
            s["status"] = "CANCELLED"
            touch(s)

    return success(serialize_lease(lease), "object", 200)


@bp.post("/lease-agreements/<lease_id>/complete")
def complete_lease(lease_id):
    middleware.require_roles({"LeaseAdmin"})
    lease = _get_lease_or_404(lease_id)
    if lease["status"] != "ACTIVE":
        raise errors.err(errors.ERR_LEASE_NOT_ACTIVE, "Lease is not ACTIVE", 409)
    term_end = lease["_start_date"] + timedelta(weeks=lease["term_weeks"])
    if clock.now() < term_end:
        raise errors.err(errors.ERR_LEASE_TERM_NOT_REACHED, "Lease term not reached", 409)

    lease["status"] = "COMPLETED"
    touch(lease)

    truck = db.trucks[lease["truck_id"]]
    if truck["status"] == "LEASED":
        truck["status"] = "IN_RETURN"
        touch(truck)

    escrow = escrow_for_lease(lease["id"])
    if escrow["status"] in ("ACCUMULATING", "FULL"):
        escrow["status"] = "REFUND_PENDING"
        touch(escrow)

    for lane in db.lane_assignments.values():
        if lane["lease_id"] == lease["id"]:
            if lane["status"] == "ACCEPTED":
                lane["status"] = "COMPLETED"
                touch(lane)
            elif lane["status"] == "OFFERED":
                lane["status"] = "REVOKED"
                touch(lane)

    return success(serialize_lease(lease), "object", 200)
