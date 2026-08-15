"""ReplenishmentOrder lifecycle endpoints."""

from flask import Blueprint, request

import errors
from db import store, touch
from middleware import (
    authenticate, require_roles, json_body, pagination_params, paginate,
)
from response import success, success_list
from services import (
    recompute_posture, recompute_site_balance, certification_gate,
    has_valid_certificate,
)

bp = Blueprint("orders", __name__)

READ_ROLES = ["DistributorAdmin", "RouteDriver"]


def serialize(o):
    return {
        "id": o["id"],
        "bin_agreement_id": o["bin_agreement_id"],
        "site_id": o["site_id"],
        "part_id": o["part_id"],
        "ordered_qty": o["ordered_qty"],
        "unit_price_cents": o["unit_price_cents"],
        "total_price_cents": o["total_price_cents"],
        "delivery_mode": o["delivery_mode"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def _load_order(oid):
    order = store.orders.get(oid)
    if order is None:
        raise errors.not_found("replenishment order not found")
    return order


@bp.get("/vmi/replenishment-orders/<oid>")
def get_order(oid):
    role = authenticate()
    require_roles(role, READ_ROLES)
    return success(serialize(_load_order(oid)), 200)


@bp.get("/vmi/replenishment-orders")
def list_orders():
    role = authenticate()
    require_roles(role, READ_ROLES)
    limit, offset = pagination_params()
    bin_agreement_id = request.args.get("bin_agreement_id")
    site_id = request.args.get("site_id")
    part_id = request.args.get("part_id")
    status = request.args.get("status")
    items = sorted(store.orders.values(), key=lambda o: o["_seq"])
    if bin_agreement_id is not None:
        items = [o for o in items if o["bin_agreement_id"] == bin_agreement_id]
    if site_id is not None:
        items = [o for o in items if o["site_id"] == site_id]
    if part_id is not None:
        items = [o for o in items if o["part_id"] == part_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(o) for o in page], total, limit, offset)


@bp.post("/vmi/replenishment-orders/<oid>/confirm")
def confirm_order(oid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        order = _load_order(oid)
        # stage 5: transition legality
        if order["status"] != "DRAFT":
            raise errors.invalid_state("order is not DRAFT")
        agr = store.agreements[order["bin_agreement_id"]]
        # stage 6: live agreement
        if agr["status"] not in ("ACTIVE", "AT_CAPACITY"):
            raise errors.retired("bin agreement is RETIRED")
        part = store.parts[order["part_id"]]
        # stage 11: certification gate (compliance flag + valid cert)
        certification_gate(agr, part)
        # stage 14: credit gate
        site = store.sites[order["site_id"]]
        if site["outstanding_balance_cents"] + order["total_price_cents"] > site["credit_limit_cents"]:
            raise errors.credit_exceeded(
                "outstanding_balance_cents + total_price_cents exceeds credit_limit_cents"
            )
        # ---- DRAFT -> CONFIRMED ----
        order["status"] = "CONFIRMED"
        order["delivery_mode"] = site["delivery_mode"]  # version-pinned
        touch(order)
        agr["open_order_qty"] += order["ordered_qty"]
        touch(agr)
        recompute_posture(agr)
        recompute_site_balance(site["id"])
        touch(site)
        return success(serialize(order), 200)


@bp.post("/vmi/replenishment-orders/<oid>/ship")
def ship_order(oid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        order = _load_order(oid)
        if order["status"] != "CONFIRMED":
            raise errors.invalid_state("order is not CONFIRMED")
        order["status"] = "IN_TRANSIT"
        touch(order)
        return success(serialize(order), 200)


@bp.post("/vmi/replenishment-orders/<oid>/deliver")
def deliver_order(oid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["RouteDriver"])
    with store.lock:
        order = _load_order(oid)
        if order["status"] != "IN_TRANSIT":
            raise errors.invalid_state("order is not IN_TRANSIT")
        order["status"] = "DELIVERED"
        touch(order)
        agr = store.agreements[order["bin_agreement_id"]]
        agr["on_hand_qty"] += order["ordered_qty"]
        agr["open_order_qty"] -= order["ordered_qty"]
        touch(agr)
        recompute_posture(agr)
        # delivery settles the outstanding balance
        site = store.sites[order["site_id"]]
        recompute_site_balance(site["id"])
        touch(site)
        return success(serialize(order), 200)


@bp.post("/vmi/replenishment-orders/<oid>/dispute")
def dispute_order(oid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["RouteDriver"])
    with store.lock:
        order = _load_order(oid)
        if order["status"] != "DELIVERED":
            raise errors.invalid_state("order is not DELIVERED")
        # only the most recently delivered order for the agreement (created_at
        # DESC, first row) may be disputed
        delivered = [
            o for o in store.orders.values()
            if o["bin_agreement_id"] == order["bin_agreement_id"]
            and o["status"] == "DELIVERED"
        ]
        delivered.sort(key=lambda o: o["_seq"], reverse=True)
        if not delivered or delivered[0]["id"] != order["id"]:
            raise errors.invalid_state(
                "order is not the most recent DELIVERED order for its agreement"
            )
        order["status"] = "DISPUTED"
        touch(order)
        agr = store.agreements[order["bin_agreement_id"]]
        agr["on_hand_qty"] -= order["ordered_qty"]
        touch(agr)
        recompute_posture(agr)
        return success(serialize(order), 200)


@bp.post("/vmi/replenishment-orders/<oid>/resolve-dispute")
def resolve_dispute(oid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        order = _load_order(oid)
        if order["status"] != "DISPUTED":
            raise errors.invalid_state("order is not DISPUTED")
        order["status"] = "DELIVERED"
        touch(order)
        agr = store.agreements[order["bin_agreement_id"]]
        agr["on_hand_qty"] += order["ordered_qty"]
        touch(agr)
        recompute_posture(agr)
        return success(serialize(order), 200)


@bp.post("/vmi/replenishment-orders/<oid>/release-hold")
def release_hold(oid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        order = _load_order(oid)
        if order["status"] != "ON_HOLD":
            raise errors.invalid_state("order is not ON_HOLD")
        # certification gate: at least one VALID lot certificate for the part
        if not has_valid_certificate(order["part_id"]):
            raise errors.certification_blocked(
                "no VALID lot certificate exists for the order's part"
            )
        order["status"] = "CONFIRMED"
        touch(order)
        return success(serialize(order), 200)


@bp.post("/vmi/replenishment-orders/<oid>/cancel")
def cancel_order(oid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        order = _load_order(oid)
        source = order["status"]
        if source not in ("DRAFT", "ON_HOLD", "DISPUTED"):
            raise errors.invalid_state(
                "order cannot be cancelled from its current state"
            )
        order["status"] = "CANCELLED"
        touch(order)
        if source == "ON_HOLD":
            # compensating unwind: bin and balance both reserved at confirm
            agr = store.agreements[order["bin_agreement_id"]]
            agr["open_order_qty"] -= order["ordered_qty"]
            touch(agr)
            recompute_posture(agr)
            site = store.sites[order["site_id"]]
            recompute_site_balance(site["id"])
            touch(site)
        # DRAFT: nothing was reserved. DISPUTED: stock already pulled back at
        # dispute time and the balance settled at delivery — no compensation.
        return success(serialize(order), 200)
