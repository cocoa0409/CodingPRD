"""HarvestOrder + ProcessingBatch + ProductLot endpoints (PRD §3.7-§3.10)."""
from flask import Blueprint, request

import errors
import serializers
import calculations
from common import (stamp_create, touch, get_body, require_number, require_int,
                    parse_dt, parse_iso, to_iso, must_get, require_fk, paginate)
from db import store
from middleware import require_roles, ALL_ROLES
from response import object_response, array_response
from domain import recompute_lot_weights

bp = Blueprint("harvest_processing", __name__)


# ---------------------------------------------------------------------------
# Withdrawal / health gate shared by harvest schedule & start (PRD §3.7, §3.8)
# ---------------------------------------------------------------------------
def _check_harvest_gate(cohort):
    """Operational + health + withdrawal gate. operational_status SUSPENDED ->
    ERR_TANK_NOT_OPERATIONAL; non-HEALTHY or within withdrawal -> ERR_WITHDRAWAL_ACTIVE."""
    if cohort["operational_status"] != "ACTIVE":
        raise errors.tank_not_operational()
    if cohort["health_status"] != "HEALTHY":
        raise errors.withdrawal_active()
    if cohort["withdrawal_until"] is not None:
        if store.clock < parse_iso(cohort["withdrawal_until"]):
            raise errors.withdrawal_active()


# ===========================================================================
# HarvestOrder
# ===========================================================================
@bp.route("/harvest-orders", methods=["POST"])
def create_harvest_order():
    require_roles({"HarvestOperator"})
    body = get_body()
    cohort_id, cohort = require_fk(body, "cohort_id", store.cohorts)
    planned_fish_count = require_int(body, "planned_fish_count", gt=0)
    scheduled_at = parse_dt(body, "scheduled_at")
    with store.lock:
        rec = {
            "cohort_id": cohort_id,
            "planned_fish_count": planned_fish_count,
            "scheduled_at": to_iso(scheduled_at),
            "harvested_fish_count": None,
            "harvested_live_weight_kg": None,
            "status": "DRAFT",
        }
        stamp_create(rec)
        store.harvest_orders[rec["id"]] = rec
        data = serializers.harvest_order_out(rec)
    return object_response(data, 201)


@bp.route("/harvest-orders", methods=["GET"])
def list_harvest_orders():
    require_roles(ALL_ROLES)
    cohort_id = request.args.get("cohort_id")
    status = request.args.get("status")
    with store.lock:
        items = list(store.harvest_orders.values())
        if cohort_id is not None:
            items = [o for o in items if o["cohort_id"] == cohort_id]
        if status is not None:
            items = [o for o in items if o["status"] == status]
        window, limit, offset, total = paginate(items)
        data = [serializers.harvest_order_out(o) for o in window]
    return array_response(data, limit, offset, total)


@bp.route("/harvest-orders/<oid>", methods=["GET"])
def get_harvest_order(oid):
    require_roles(ALL_ROLES)
    with store.lock:
        rec = must_get(store.harvest_orders, oid)
        data = serializers.harvest_order_out(rec)
    return object_response(data, 200)


@bp.route("/harvest-orders/<oid>/schedule", methods=["POST"])
def schedule_harvest_order(oid):
    require_roles({"HarvestOperator"})
    with store.lock:
        order = must_get(store.harvest_orders, oid)
        if order["status"] not in {"DRAFT", "BLOCKED"}:
            raise errors.invalid_state()
        cohort = store.cohorts.get(order["cohort_id"])
        if cohort is None:
            raise errors.not_found()
        _check_harvest_gate(cohort)
        if order["planned_fish_count"] > cohort["fish_count"]:
            raise errors.harvest_count_exceeds()
        order["status"] = "SCHEDULED"
        touch(order)
        data = serializers.harvest_order_out(order)
    return object_response(data, 200)


@bp.route("/harvest-orders/<oid>/start", methods=["POST"])
def start_harvest_order(oid):
    require_roles({"HarvestOperator"})
    with store.lock:
        order = must_get(store.harvest_orders, oid)
        if order["status"] != "SCHEDULED":
            raise errors.invalid_state()
        cohort = store.cohorts.get(order["cohort_id"])
        if cohort is None:
            raise errors.not_found()
        _check_harvest_gate(cohort)
        order["status"] = "IN_PROGRESS"
        touch(order)
        cohort["lifecycle_status"] = "HARVESTING"
        touch(cohort)
        data = serializers.harvest_order_out(order)
    return object_response(data, 200)


@bp.route("/harvest-orders/<oid>/complete", methods=["POST"])
def complete_harvest_order(oid):
    require_roles({"HarvestOperator"})
    with store.lock:
        order = must_get(store.harvest_orders, oid)
        if order["status"] != "IN_PROGRESS":
            raise errors.invalid_state()
        cohort = store.cohorts.get(order["cohort_id"])
        if cohort is None:
            raise errors.not_found()
        body = get_body()
        harvested_fish = require_int(body, "harvested_fish_count", gt=0)
        harvested_weight = require_number(body, "harvested_live_weight_kg", gt=0)
        if harvested_fish > cohort["fish_count"]:
            raise errors.harvest_count_exceeds()

        order["harvested_fish_count"] = harvested_fish
        order["harvested_live_weight_kg"] = harvested_weight
        order["status"] = "COMPLETED"
        touch(order)

        cohort["fish_count"] -= harvested_fish
        if cohort["fish_count"] == 0:
            cohort["lifecycle_status"] = "HARVESTED"
        # Final FCR is computed at completion (PRD §3.7); it is a derived figure
        # tied to this harvest and surfaced via the order, not persisted on the
        # cohort schema. We compute it to honor the calculation contract.
        calculations.final_fcr(cohort, harvested_fish, harvested_weight)
        touch(cohort)

        data = serializers.harvest_order_out(order)
    return object_response(data, 200)


@bp.route("/harvest-orders/<oid>/cancel", methods=["POST"])
def cancel_harvest_order(oid):
    require_roles({"HarvestOperator"})
    with store.lock:
        order = must_get(store.harvest_orders, oid)
        if order["status"] not in {"DRAFT", "SCHEDULED", "BLOCKED"}:
            raise errors.invalid_state()
        order["status"] = "CANCELLED"
        touch(order)
        data = serializers.harvest_order_out(order)
    return object_response(data, 200)


# ===========================================================================
# ProcessingBatch
# ===========================================================================
@bp.route("/processing-batches", methods=["POST"])
def create_processing_batch():
    require_roles({"HarvestOperator"})
    body = get_body()
    harvest_order_id, order = require_fk(body, "harvest_order_id", store.harvest_orders)
    with store.lock:
        # A batch may be created only from a COMPLETED harvest order (PRD §3.9).
        if order["status"] != "COMPLETED":
            raise errors.invalid_state()
        rec = {
            "harvest_order_id": harvest_order_id,
            "input_live_weight_kg": order["harvested_live_weight_kg"],
            "estimated_yield_kg": 0,
            "actual_processed_weight_kg": None,
            "status": "DRAFT",
        }
        stamp_create(rec)
        store.processing_batches[rec["id"]] = rec
        data = serializers.processing_batch_out(rec)
    return object_response(data, 201)


@bp.route("/processing-batches", methods=["GET"])
def list_processing_batches():
    require_roles(ALL_ROLES)
    harvest_order_id = request.args.get("harvest_order_id")
    status = request.args.get("status")
    with store.lock:
        items = list(store.processing_batches.values())
        if harvest_order_id is not None:
            items = [b for b in items if b["harvest_order_id"] == harvest_order_id]
        if status is not None:
            items = [b for b in items if b["status"] == status]
        window, limit, offset, total = paginate(items)
        data = [serializers.processing_batch_out(b) for b in window]
    return array_response(data, limit, offset, total)


@bp.route("/processing-batches/<bid>", methods=["GET"])
def get_processing_batch(bid):
    require_roles(ALL_ROLES)
    with store.lock:
        rec = must_get(store.processing_batches, bid)
        data = serializers.processing_batch_out(rec)
    return object_response(data, 200)


def _species_for_batch(batch):
    order = store.harvest_orders.get(batch["harvest_order_id"])
    if order is None:
        return None
    cohort = store.cohorts.get(order["cohort_id"])
    if cohort is None:
        return None
    return store.species.get(cohort["species_id"])


@bp.route("/processing-batches/<bid>/start", methods=["POST"])
def start_processing_batch(bid):
    require_roles({"HarvestOperator"})
    with store.lock:
        batch = must_get(store.processing_batches, bid)
        if batch["status"] != "DRAFT":
            raise errors.invalid_state()
        order = store.harvest_orders.get(batch["harvest_order_id"])
        if order is None or order["status"] != "COMPLETED":
            raise errors.invalid_state()
        species = _species_for_batch(batch)
        yield_pct = species["default_processing_yield_pct"] if species else 0
        batch["estimated_yield_kg"] = calculations.estimate_processing_yield(
            batch["input_live_weight_kg"], yield_pct)
        batch["status"] = "PROCESSING"
        touch(batch)
        data = serializers.processing_batch_out(batch)
    return object_response(data, 200)


@bp.route("/processing-batches/<bid>/complete", methods=["POST"])
def complete_processing_batch(bid):
    require_roles({"HarvestOperator"})
    with store.lock:
        batch = must_get(store.processing_batches, bid)
        if batch["status"] != "PROCESSING":
            raise errors.invalid_state()
        body = get_body()
        actual = require_number(body, "actual_processed_weight_kg", gt=0)
        price = require_number(body, "price_per_kg", gt=0)
        if actual > batch["input_live_weight_kg"]:
            raise errors.processing_weight_exceeds()

        batch["actual_processed_weight_kg"] = actual
        batch["status"] = "COMPLETED"
        touch(batch)

        # Create exactly one ProductLot (PRD §3.9 / §3.10).
        species = _species_for_batch(batch)
        species_id = None
        if species is not None:
            species_id = species["id"]
        lot = {
            "processing_batch_id": batch["id"],
            "species_id": species_id,
            "total_weight_kg": actual,
            "reserved_weight_kg": 0,
            "available_weight_kg": actual,
            "shipped_weight_kg": 0,
            "price_per_kg": price,
            "status": "AVAILABLE" if actual > 0 else "DEPLETED",
        }
        stamp_create(lot)
        store.product_lots[lot["id"]] = lot

        data = serializers.processing_batch_out(batch)
    return object_response(data, 200)


@bp.route("/processing-batches/<bid>/reject", methods=["POST"])
def reject_processing_batch(bid):
    require_roles({"HarvestOperator"})
    with store.lock:
        batch = must_get(store.processing_batches, bid)
        if batch["status"] != "PROCESSING":
            raise errors.invalid_state()
        batch["status"] = "REJECTED"
        touch(batch)
        data = serializers.processing_batch_out(batch)
    return object_response(data, 200)


# ===========================================================================
# ProductLot (read-only endpoints)
# ===========================================================================
@bp.route("/product-lots", methods=["GET"])
def list_product_lots():
    require_roles(ALL_ROLES)
    processing_batch_id = request.args.get("processing_batch_id")
    species_id = request.args.get("species_id")
    status = request.args.get("status")
    with store.lock:
        items = list(store.product_lots.values())
        if processing_batch_id is not None:
            items = [l for l in items if l["processing_batch_id"] == processing_batch_id]
        if species_id is not None:
            items = [l for l in items if l["species_id"] == species_id]
        if status is not None:
            items = [l for l in items if l["status"] == status]
        window, limit, offset, total = paginate(items)
        data = [serializers.product_lot_out(l) for l in window]
    return array_response(data, limit, offset, total)


@bp.route("/product-lots/<lid>", methods=["GET"])
def get_product_lot(lid):
    require_roles(ALL_ROLES)
    with store.lock:
        rec = must_get(store.product_lots, lid)
        data = serializers.product_lot_out(rec)
    return object_response(data, 200)
