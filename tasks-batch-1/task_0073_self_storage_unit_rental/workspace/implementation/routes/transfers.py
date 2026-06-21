from flask import Blueprint, request

import errors
from errors import err
from db import db
from models import make_common, touch, serialize
from middleware import get_identity, require_role
from helpers import (get_json_body, lookup, parse_pagination, paginate,
                     sort_by_created, require_tenant_owns_lease)
from response import success, list_response
from services import calc, domain

bp = Blueprint("transfers", __name__)

TERMINAL_AP = ("SOLD", "REDEEMED", "CANCELLED")


def _has_nonterminal_proceeding(lease_id):
    return any(
        ap["lease_id"] == lease_id and ap["status"] not in TERMINAL_AP
        for ap in db.auction_proceedings.values()
    )


@bp.post("/transfer-orders")
def create_transfer():
    _, role = get_identity()
    require_role(role, {"FacilityManager"})
    body = get_json_body()

    lease_id = body.get("lease_id")
    to_unit_id = body.get("to_unit_id")
    if not isinstance(lease_id, str) or not lease_id:
        raise err(errors.ERR_INVALID_REQUEST, "lease_id is required")
    if not isinstance(to_unit_id, str) or not to_unit_id:
        raise err(errors.ERR_INVALID_REQUEST, "to_unit_id is required")
    lease = lookup(db.leases, lease_id, "lease")
    to_unit = lookup(db.units, to_unit_id, "unit")

    if "expected_lease_version" not in body or body["expected_lease_version"] is None:
        raise err(errors.ERR_INVALID_REQUEST, "expected_lease_version is required")
    expected = body["expected_lease_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(errors.ERR_INVALID_REQUEST, "expected_lease_version must be an integer")

    # Lease must be ACTIVE.
    if lease["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Lease must be ACTIVE to transfer")

    # Destination unit must be AVAILABLE.
    if to_unit["status"] != "AVAILABLE":
        raise err(errors.ERR_UNIT_NOT_AVAILABLE, "Destination unit is not AVAILABLE")

    # Non-terminal auction proceeding blocks transfer.
    if _has_nonterminal_proceeding(lease_id):
        raise err(errors.ERR_LEASE_HAS_ACTIVITY, "Lease has a non-terminal auction proceeding")

    # OCC.
    if expected != lease["version"]:
        raise err(errors.ERR_STALE_VERSION, "expected_lease_version does not match lease version")

    order = make_common()
    order.update({
        "lease_id": lease_id,
        "from_unit_id": lease["unit_id"],
        "to_unit_id": to_unit_id,
        "status": "REQUESTED",
        "prorated_adjustment_cents": None,
    })
    db.transfer_orders[order["id"]] = order

    touch(lease)  # increments version by 1
    return success(serialize(order), 201)


@bp.get("/transfer-orders/<transfer_order_id>")
def get_transfer(transfer_order_id):
    user_id, role = get_identity()
    require_role(role, {"FacilityManager", "Tenant"})
    order = lookup(db.transfer_orders, transfer_order_id, "transfer order")
    lease = db.leases.get(order["lease_id"])
    if lease is not None:
        require_tenant_owns_lease(user_id, role, lease)
    return success(serialize(order), 200)


@bp.get("/transfer-orders")
def list_transfers():
    user_id, role = get_identity()
    require_role(role, {"FacilityManager", "Tenant"})
    limit, offset = parse_pagination()
    items = list(db.transfer_orders.values())
    lease_id = request.args.get("lease_id")
    from_unit_id = request.args.get("from_unit_id")
    to_unit_id = request.args.get("to_unit_id")
    status = request.args.get("status")
    if lease_id is not None:
        items = [o for o in items if o["lease_id"] == lease_id]
    if from_unit_id is not None:
        items = [o for o in items if o["from_unit_id"] == from_unit_id]
    if to_unit_id is not None:
        items = [o for o in items if o["to_unit_id"] == to_unit_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if role == "Tenant":
        owned = {l["id"] for l in db.leases.values() if l["tenant_id"] == user_id}
        items = [o for o in items if o["lease_id"] in owned]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize(o) for o in page], total, limit, offset)


@bp.post("/transfer-orders/<transfer_order_id>/complete")
def complete_transfer(transfer_order_id):
    _, role = get_identity()
    require_role(role, {"FacilityManager"})
    order = lookup(db.transfer_orders, transfer_order_id, "transfer order")

    if order["status"] != "REQUESTED":
        raise err(errors.ERR_INVALID_STATE, "Transfer order must be REQUESTED to complete")

    lease = db.leases.get(order["lease_id"])
    if lease is None:
        raise err(errors.ERR_NOT_FOUND, "lease not found")
    if lease["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Lease must be ACTIVE to complete transfer")

    to_unit = db.units.get(order["to_unit_id"])
    if to_unit is None:
        raise err(errors.ERR_NOT_FOUND, "destination unit not found")
    if to_unit["status"] != "AVAILABLE":
        raise err(errors.ERR_UNIT_NOT_AVAILABLE, "Destination unit is not AVAILABLE")

    facility = db.facilities.get(lease["facility_id"])
    clock = db.clock.now()

    old_unit = db.units.get(lease["unit_id"])

    # Prorated rent adjustment for remainder of current period.
    old_policy = domain.active_policy_for_lease(lease["id"])
    insurance_prem = old_policy["monthly_premium_cents"] if old_policy else 0
    _, _, _, old_monthly = calc.monthly_components(
        lease["monthly_rate_cents"], lease["climate_controlled"],
        facility["climate_premium_pct"], insurance_prem,
    )
    _, _, _, new_monthly = calc.monthly_components(
        to_unit["monthly_rate_cents"], to_unit["climate_controlled"],
        facility["climate_premium_pct"], insurance_prem,
    )

    period_end = domain.next_billing_date(clock, lease["billing_day"])
    period_start = domain.add_months(period_end, -1)
    days_in_period = max(1, (period_end - period_start).days)
    days_remaining = max(0, calc.whole_days_between(period_end, clock))

    from decimal import Decimal
    adjustment = calc.round_half_up(
        Decimal(new_monthly - old_monthly) * Decimal(days_remaining) / Decimal(days_in_period)
    )

    # Swap units.
    if old_unit is not None:
        old_unit["status"] = "AVAILABLE"
        old_unit["current_lease_id"] = None
        touch(old_unit)
    to_unit["status"] = "OCCUPIED"
    to_unit["current_lease_id"] = lease["id"]
    touch(to_unit)

    lease["unit_id"] = to_unit["id"]
    lease["monthly_rate_cents"] = to_unit["monthly_rate_cents"]
    lease["climate_controlled"] = to_unit["climate_controlled"]

    order["prorated_adjustment_cents"] = adjustment
    if adjustment > 0:
        domain.append_ledger(lease, "CHARGE", adjustment, "MANUAL", order["id"])
    elif adjustment < 0:
        domain.append_ledger(lease, "CREDIT", adjustment, "MANUAL", order["id"])

    touch(lease)
    domain.recompute_occupied(facility["id"])

    order["status"] = "COMPLETED"
    touch(order)
    return success(serialize(order), 200)


@bp.post("/transfer-orders/<transfer_order_id>/cancel")
def cancel_transfer(transfer_order_id):
    _, role = get_identity()
    require_role(role, {"FacilityManager"})
    order = lookup(db.transfer_orders, transfer_order_id, "transfer order")

    if order["status"] != "REQUESTED":
        raise err(errors.ERR_INVALID_STATE, "Transfer order must be REQUESTED to cancel")

    order["status"] = "CANCELLED"
    touch(order)
    return success(serialize(order), 200)
