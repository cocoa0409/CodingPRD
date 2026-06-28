"""Swap request operation routes (PRD §3.8, §3.9)."""
from flask import Blueprint, request

import errors
from clock import clock
from db import db, touch
from middleware import get_identity, require_roles, parse_pagination
from response import object_response, array_response
from services import calc, serialize, common
from services import invoices as inv_svc

bp = Blueprint("swaps", __name__)


@bp.route("/swap-requests/<srid>", methods=["GET"])
def get_swap(srid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"})
    rec = common.resolve(db.swap_requests, srid)
    return object_response(serialize.serialize_swap_request(rec))


@bp.route("/swap-requests", methods=["GET"])
def list_swaps():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"})
    limit, offset = parse_pagination()
    records = list(db.swap_requests.values())
    records = common.filter_equals(records, "subscription_id", request.args.get("subscription_id"))
    records = common.filter_equals(records, "from_vehicle_id", request.args.get("from_vehicle_id"))
    records = common.filter_equals(records, "to_vehicle_id", request.args.get("to_vehicle_id"))
    records = common.filter_equals(records, "status", request.args.get("status"))
    page, total = common.paginate_sorted(records, limit, offset)
    return array_response([serialize.serialize_swap_request(r) for r in page], limit, offset, total)


@bp.route("/swap-requests/<srid>/approve", methods=["POST"])
def approve_swap(srid):
    _, role = get_identity()
    require_roles(role, {"FleetOperator"})  # exclusive (PRD §3.8)
    swap = common.resolve(db.swap_requests, srid)
    body = common.get_body()
    expected_version = common.require_int(body, "expected_vehicle_version")

    # priority 6: state — REQUESTED only.
    if swap["status"] != "REQUESTED":
        raise errors.invalid_state("Swap must be REQUESTED to approve.")
    sub = db.subscriptions[swap["subscription_id"]]
    if sub["lifecycle_status"] != "ACTIVE":
        raise errors.invalid_state("Subscription must be ACTIVE to approve a swap.")
    target = db.vehicles[swap["to_vehicle_id"]]
    # target AVAILABLE (any plan tier — upgrade/downgrade allowed) (PRD §3.8).
    if target["status"] != "AVAILABLE":
        raise errors.invalid_state("Target vehicle must be AVAILABLE.")
    # priority 15: OCC on target Vehicle.version.
    if expected_version != target["version"]:
        raise errors.stale_vehicle_version()

    # Fork: reserve target while from_vehicle stays ASSIGNED (PRD §3.8).
    target["status"] = "RESERVED"
    target["active_subscription_id"] = sub["id"]
    touch(target)
    swap["status"] = "APPROVED"
    touch(swap)
    common.recompute_fleet(target["fleet_id"])
    return object_response(serialize.serialize_swap_request(swap))


@bp.route("/swap-requests/<srid>/complete", methods=["POST"])
def complete_swap(srid):
    _, role = get_identity()
    require_roles(role, {"FleetOperator"})  # exclusive (PRD §3.8)
    swap = common.resolve(db.swap_requests, srid)
    if swap["status"] != "APPROVED":
        raise errors.invalid_state("Swap must be APPROVED to complete.")
    from_vehicle = db.vehicles[swap["from_vehicle_id"]]
    to_vehicle = db.vehicles[swap["to_vehicle_id"]]
    if from_vehicle["status"] != "ASSIGNED" or to_vehicle["status"] != "RESERVED":
        raise errors.invalid_state("from_vehicle must be ASSIGNED and to_vehicle RESERVED.")

    sub = db.subscriptions[swap["subscription_id"]]
    from_plan = db.subscription_plans[from_vehicle["plan_id"]]
    to_plan = db.subscription_plans[to_vehicle["plan_id"]]

    # compute fee + net adjustment (gated on swaps_used BEFORE increment) (PRD §3.9).
    swap_fee, net = calc.swap_net_adjustment(
        from_plan, to_plan, sub["cycle_start_iso"], clock.now(), sub["swaps_used"]
    )
    swap["swap_fee_applied_cents"] = swap_fee
    swap["net_adjustment_cents"] = net

    # post SWAP invoice for net adjustment (may be negative) (PRD §3.8).
    inv_svc.post_invoice(sub["id"], "SWAP", swap["id"], net)

    # diverging branches (PRD §3.8).
    from_vehicle["status"] = "IN_INSPECTION"
    from_vehicle["active_subscription_id"] = None
    touch(from_vehicle)
    to_vehicle["status"] = "ASSIGNED"
    touch(to_vehicle)

    sub["active_vehicle_id"] = to_vehicle["id"]
    sub["plan_id"] = to_vehicle["plan_id"]
    sub["swaps_used"] = sub["swaps_used"] + 1
    touch(sub)

    swap["status"] = "COMPLETED"
    touch(swap)

    # recompute both fleets.
    common.recompute_fleet(from_vehicle["fleet_id"])
    common.recompute_fleet(to_vehicle["fleet_id"])
    return object_response(serialize.serialize_swap_request(swap))


@bp.route("/swap-requests/<srid>/reject", methods=["POST"])
def reject_swap(srid):
    _, role = get_identity()
    require_roles(role, {"FleetOperator"})  # exclusive (PRD §3.8)
    swap = common.resolve(db.swap_requests, srid)
    if swap["status"] not in ("REQUESTED", "APPROVED"):
        raise errors.invalid_state("Swap must be REQUESTED or APPROVED to reject.")

    if swap["status"] == "APPROVED":
        # compensating action: revert target reservation (PRD §3.8).
        target = db.vehicles[swap["to_vehicle_id"]]
        target["status"] = "AVAILABLE"
        target["active_subscription_id"] = None
        touch(target)
        common.recompute_fleet(target["fleet_id"])

    swap["status"] = "REJECTED"
    touch(swap)
    return object_response(serialize.serialize_swap_request(swap))
