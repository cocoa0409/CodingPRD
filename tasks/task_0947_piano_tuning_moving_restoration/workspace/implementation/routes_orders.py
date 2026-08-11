"""Service orders, milestones, parts lots and allocations (PRD 3.6)."""

from flask import Blueprint, jsonify, request

import calc
import serialize
import services
from core import (
    ALLOCATION_STATUSES, CLOCK, DB, LOCK, MILESTONE_STATUSES, ORDER_STATUSES,
    PART_TYPES, Ctx, by_created, fail, make_row, need_order, need_other,
    need_quote, not_terminal, ok, page, parse_iso, touch,
)

bp = Blueprint("orders", __name__)

ORDER_TERMINAL = ("COMPLETED", "CANCELLED", "VOIDED_BY_REBUILD")
MILESTONE_TERMINAL = ("ACCEPTED", "CANCELLED")
ALLOCATION_TERMINAL = ("CONSUMED", "RELEASED")


def _order_client(order):
    return order["client_id"]


def _milestone_order(stone):
    return DB.service_orders.get(stone["service_order_id"])


# ---------------------------------------------------------------------------
# Service orders
# ---------------------------------------------------------------------------

@bp.post("/service-orders")
def create_service_order():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager"])
        body = ctx.read_body(["quote_id"])
        quote = need_quote(body["quote_id"])
        tech = None
        if body.get("assigned_technician_id") is not None:
            tech = need_other("technicians", body["assigned_technician_id"])

        client = DB.clients.get(quote["client_id"])
        if client is not None and client["status"] != "ACTIVE":
            fail("ERR_CLIENT_NOT_ACTIVE", "The owning client is not ACTIVE.")
        if tech is not None and tech["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "The technician is not ACTIVE.")

        if quote["status"] != "APPROVED":
            fail("ERR_INVALID_STATE", "Only an APPROVED quote realises an order.")
        if any(o["quote_id"] == quote["id"] for o in DB.service_orders.values()):
            fail("ERR_INVALID_STATE", "This quote already has a service order.")

        if tech is not None and not calc.cert_ok(tech["certification_level"],
                                                 quote["service_type"]):
            fail("ERR_TECH_CERT_INSUFFICIENT",
                 "The technician may not perform %s." % quote["service_type"])

        expires = parse_iso(quote["expires_at"]) if quote["expires_at"] else None
        if expires is not None and not CLOCK.dt < expires:
            fail("ERR_QUOTE_EXPIRED", "The quote has expired.")

        instrument = DB.instruments.get(quote["instrument_id"])
        minutes, visit_variant = calc.service_order_duration(
            quote["service_type"], instrument["instrument_class"],
            instrument["pitch_raise_tier"])
        contract_total = quote["total_cents"]
        deposit_held = quote["deposit_required_cents"]
        order = make_row(
            quote_id=quote["id"],
            instrument_id=quote["instrument_id"],
            client_id=quote["client_id"],
            assigned_technician_id=tech["id"] if tech else None,
            service_type=quote["service_type"],
            contract_total_cents=contract_total,
            billed_cents=0,
            unbilled_cents=contract_total,
            deposit_held_cents=deposit_held,
            deposit_applied_cents=0,
            deposit_refunded_cents=0,
            deposit_forfeited_cents=0,
            estimated_minutes=minutes,
            visit_plan_variant=visit_variant,
            started_at=None,
            completed_at=None,
            status="PENDING",
        )
        if quote["service_type"] == "REBUILD":
            order["_parts_requirement"] = calc.parts_requirement(
                instrument["instrument_class"])
        DB.service_orders[order["id"]] = order

        for spec in calc.milestone_schedule(quote["service_type"], contract_total):
            stone = make_row(
                service_order_id=order["id"],
                sequence_index=spec["sequence_index"],
                label=spec["label"],
                amount_cents=spec["amount_cents"],
                rejection_count=0,
                released_by_user_id=None,
                released_at=None,
                accepted_at=None,
                status="PENDING",
            )
            DB.milestones[stone["id"]] = stone

        if deposit_held > 0:
            services.post_ledger(order["client_id"], "DEPOSIT_CHARGE",
                                 -deposit_held, service_order_id=order["id"])
            services.recompute_balance_for(order["client_id"])
        payload, status = ok(serialize.service_order(order), 201)
        return jsonify(payload), status


@bp.get("/service-orders")
def list_service_orders():
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Technician", "Client"])
        client_filter = request.args.get("client_id")
        if client_filter:
            ctx.scope_client(client_filter)
        tech_filter = request.args.get("assigned_technician_id")
        if tech_filter:
            ctx.scope_tech(tech_filter)
        status_f = ctx.enum_q("status", ORDER_STATUSES)
        limit, offset = ctx.pagination()
        rows = by_created(DB.rows("service_orders"))
        for key in ("quote_id", "instrument_id", "client_id",
                    "assigned_technician_id"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        if ctx.is_client:
            rows = [r for r in rows if r["client_id"] == ctx.user_id]
        payload, http = page(rows, limit, offset, serialize.service_order)
        return jsonify(payload), http


@bp.get("/service-orders/<oid>")
def read_service_order(oid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Technician", "Client"])
        existing = DB.service_orders.get(oid)
        if existing is not None:
            ctx.scope_client(existing["client_id"])
            ctx.scope_tech(existing["assigned_technician_id"])
        order = need_order(oid)
        payload, status = ok(serialize.service_order(order))
        return jsonify(payload), status


@bp.post("/service-orders/<oid>/start")
def start_service_order(oid):
    with LOCK:
        ctx = Ctx(["Technician", "ShopManager", "PlatformAdmin"])
        existing = DB.service_orders.get(oid)
        if existing is not None:
            ctx.scope_tech(existing["assigned_technician_id"])
        ctx.read_body([])
        order = need_order(oid)
        not_terminal(order["status"], ORDER_TERMINAL)
        if order["status"] != "PENDING":
            fail("ERR_INVALID_STATE",
                 "No order edge from %s to IN_PROGRESS." % order["status"])
        if not order["assigned_technician_id"]:
            fail("ERR_INVALID_STATE", "The order has no assigned technician.")
        if order["service_type"] == "REBUILD":
            instrument = DB.instruments.get(order["instrument_id"])
            if instrument is None or instrument["custody_status"] != "IN_SHOP":
                fail("ERR_INVALID_CUSTODY_STATE",
                     "A REBUILD may only start while the instrument is IN_SHOP.")
        order["status"] = "IN_PROGRESS"
        order["started_at"] = CLOCK.stamp()
        touch(order)
        stones = [m for m in DB.milestones.values()
                  if m["service_order_id"] == order["id"]
                  and m["status"] == "PENDING"]
        for stone in sorted(stones, key=lambda m: m["sequence_index"]):
            stone["status"] = "READY"
            touch(stone)
        payload, status = ok(serialize.service_order(order))
        return jsonify(payload), status


@bp.post("/service-orders/<oid>/resume")
def resume_service_order(oid):
    with LOCK:
        ctx = Ctx(["ShopManager", "PlatformAdmin"])
        ctx.read_body([])
        order = need_order(oid)
        client = DB.clients.get(order["client_id"])
        if client is not None and client["status"] != "ACTIVE":
            fail("ERR_CLIENT_NOT_ACTIVE", "The owning client is not ACTIVE.")
        not_terminal(order["status"], ORDER_TERMINAL)
        if order["status"] != "ON_HOLD":
            fail("ERR_INVALID_STATE",
                 "No order edge from %s to IN_PROGRESS." % order["status"])
        order["status"] = "IN_PROGRESS"
        touch(order)
        payload, status = ok(serialize.service_order(order))
        return jsonify(payload), status


@bp.post("/service-orders/<oid>/complete")
def complete_service_order(oid):
    with LOCK:
        ctx = Ctx(["Technician", "ShopManager", "PlatformAdmin"])
        existing = DB.service_orders.get(oid)
        if existing is not None:
            ctx.scope_tech(existing["assigned_technician_id"])
        ctx.read_body([])
        order = need_order(oid)
        not_terminal(order["status"], ORDER_TERMINAL)
        if order["status"] != "IN_PROGRESS":
            fail("ERR_INVALID_STATE",
                 "No order edge from %s to COMPLETED." % order["status"])
        stones = [m for m in DB.milestones.values()
                  if m["service_order_id"] == order["id"]]
        if any(m["status"] != "ACCEPTED" for m in stones):
            fail("ERR_INVALID_STATE", "Every milestone must be ACCEPTED first.")

        order["status"] = "COMPLETED"
        order["completed_at"] = CLOCK.stamp()
        touch(order)
        services.mint_warranty(order)
        instrument = DB.instruments.get(order["instrument_id"])
        if instrument is not None:
            services.advance_condition_on_complete(order, instrument)
            if order["service_type"] in ("TUNE", "PITCH_RAISE"):
                instrument["last_tuning_date"] = CLOCK.date.isoformat()
                touch(instrument)
        for alloc in by_created([a for a in DB.parts_allocations.values()
                                 if a["service_order_id"] == order["id"]
                                 and a["status"] in ("RESERVED", "PARTIAL")]):
            services.consume_allocation(alloc)
        payload, status = ok(serialize.service_order(order))
        return jsonify(payload), status


@bp.post("/service-orders/<oid>/cancel")
def cancel_service_order(oid):
    with LOCK:
        ctx = Ctx(["ShopManager", "PlatformAdmin"])
        ctx.read_body([])
        order = need_order(oid)
        not_terminal(order["status"], ORDER_TERMINAL)
        if order["status"] not in ("PENDING", "ON_HOLD"):
            fail("ERR_INVALID_STATE",
                 "No order edge from %s to CANCELLED." % order["status"])
        order["status"] = "CANCELLED"
        touch(order)
        stones = [m for m in DB.milestones.values()
                  if m["service_order_id"] == order["id"]
                  and m["status"] in ("PENDING", "READY", "RELEASED")]
        for stone in sorted(stones, key=lambda m: m["sequence_index"]):
            stone["status"] = "CANCELLED"
            touch(stone)
        for alloc in by_created([a for a in DB.parts_allocations.values()
                                 if a["service_order_id"] == order["id"]
                                 and a["status"] in ("RESERVED", "PARTIAL")]):
            services.release_allocation(alloc)
        refund = order["deposit_held_cents"] - order["deposit_applied_cents"]
        order["deposit_refunded_cents"] = refund
        services.post_ledger(order["client_id"], "DEPOSIT_REFUND", refund,
                             service_order_id=order["id"])
        services.recompute_balance_for(order["client_id"])
        payload, status = ok(serialize.service_order(order))
        return jsonify(payload), status


@bp.get("/service-orders/<oid>/milestones")
def list_milestones(oid):
    with LOCK:
        ctx = Ctx(["PlatformAdmin", "ShopManager", "Technician", "Client"])
        existing = DB.service_orders.get(oid)
        if existing is not None:
            ctx.scope_client(existing["client_id"])
            ctx.scope_tech(existing["assigned_technician_id"])
        status_f = ctx.enum_q("status", MILESTONE_STATUSES)
        limit, offset = ctx.pagination()
        order = need_order(oid)
        rows = [m for m in DB.milestones.values()
                if m["service_order_id"] == order["id"]]
        rows.sort(key=lambda m: m["sequence_index"])
        if status_f:
            rows = [m for m in rows if m["status"] == status_f]
        payload, http = page(rows, limit, offset, serialize.milestone)
        return jsonify(payload), http


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------

@bp.post("/parts-lots")
def create_parts_lot():
    with LOCK:
        ctx = Ctx(["ShopManager", "PlatformAdmin"])
        body = ctx.read_body(["part_type", "lot_code", "initial_qty"])
        ctx.enum("part_type", PART_TYPES)
        ctx.number("initial_qty", lo=1, hi=1000, integer=True)
        if any(l["lot_code"] == body["lot_code"] for l in DB.parts_lots.values()):
            fail("ERR_DUPLICATE_LOT_CODE",
                 "lot_code %s already exists." % body["lot_code"])
        row = make_row(
            part_type=body["part_type"],
            lot_code=body["lot_code"],
            initial_qty=body["initial_qty"],
            on_hand_qty=body["initial_qty"],
            allocated_qty=0,
            consumed_qty=0,
            status="OPEN",
        )
        DB.parts_lots[row["id"]] = row
        payload, status = ok(serialize.parts_lot(row), 201)
        return jsonify(payload), status


@bp.get("/parts-lots/<lid>")
def read_parts_lot(lid):
    with LOCK:
        Ctx(["ShopManager", "PlatformAdmin", "Technician"])
        row = need_other("parts_lots", lid)
        payload, status = ok(serialize.parts_lot(row))
        return jsonify(payload), status


@bp.post("/service-orders/<oid>/parts-allocations")
def create_parts_allocation(oid):
    with LOCK:
        ctx = Ctx(["ShopManager", "PlatformAdmin"])
        body = ctx.read_body(["parts_lot_id", "requested_qty",
                              "expected_parts_lot_version"])
        ctx.number("requested_qty", lo=1, hi=calc.PARTS_MAX_REQUEST_QTY,
                   integer=True)
        order = need_order(oid)
        lot = need_other("parts_lots", body["parts_lot_id"])
        if body["expected_parts_lot_version"] != lot["version"]:
            fail("ERR_STALE_PARTS_LOT_VERSION",
                 "expected_parts_lot_version does not match.")
        requested = body["requested_qty"]
        available = lot["on_hand_qty"]
        floor_qty = calc.partial_floor(requested)
        if available >= requested:
            allocated, alloc_status = requested, "RESERVED"
        elif available >= floor_qty:
            allocated, alloc_status = available, "PARTIAL"
        else:
            fail("ERR_PARTS_INSUFFICIENT",
                 "The lot cannot even fill the partial floor.")
        row = make_row(
            parts_lot_id=lot["id"],
            service_order_id=order["id"],
            requested_qty=requested,
            allocated_qty=allocated,
            status=alloc_status,
        )
        DB.parts_allocations[row["id"]] = row
        lot["on_hand_qty"] -= allocated
        lot["allocated_qty"] += allocated
        if lot["on_hand_qty"] == 0:
            lot["status"] = "DEPLETED"
        touch(lot)
        payload, status = ok(serialize.parts_allocation(row), 201)
        return jsonify(payload), status


@bp.get("/parts-allocations")
def list_parts_allocations():
    with LOCK:
        ctx = Ctx(["ShopManager", "PlatformAdmin", "Technician"])
        status_f = ctx.enum_q("status", ALLOCATION_STATUSES)
        limit, offset = ctx.pagination()
        rows = by_created(DB.rows("parts_allocations"))
        for key in ("parts_lot_id", "service_order_id"):
            value = request.args.get(key)
            if value:
                rows = [r for r in rows if r[key] == value]
        if status_f:
            rows = [r for r in rows if r["status"] == status_f]
        payload, http = page(rows, limit, offset, serialize.parts_allocation)
        return jsonify(payload), http


@bp.get("/parts-allocations/<aid>")
def read_parts_allocation(aid):
    with LOCK:
        Ctx(["ShopManager", "PlatformAdmin", "Technician"])
        row = need_other("parts_allocations", aid)
        payload, status = ok(serialize.parts_allocation(row))
        return jsonify(payload), status


@bp.post("/parts-allocations/<aid>/consume")
def consume_parts_allocation(aid):
    with LOCK:
        ctx = Ctx(["Technician", "ShopManager", "PlatformAdmin"])
        existing = DB.parts_allocations.get(aid)
        if existing is not None:
            owner = DB.service_orders.get(existing["service_order_id"])
            if owner is not None:
                ctx.scope_tech(owner["assigned_technician_id"])
        ctx.read_body([])
        alloc = need_other("parts_allocations", aid)
        not_terminal(alloc["status"], ALLOCATION_TERMINAL)
        if alloc["status"] not in ("RESERVED", "PARTIAL"):
            fail("ERR_INVALID_STATE",
                 "No allocation edge from %s to CONSUMED." % alloc["status"])
        order = DB.service_orders.get(alloc["service_order_id"])
        if order is not None and order["status"] not in ("IN_PROGRESS", "COMPLETED"):
            fail("ERR_INVALID_STATE",
                 "The order must be IN_PROGRESS or COMPLETED to consume parts.")
        services.consume_allocation(alloc)
        payload, status = ok(serialize.parts_allocation(alloc))
        return jsonify(payload), status


@bp.post("/parts-allocations/<aid>/release")
def release_parts_allocation(aid):
    with LOCK:
        ctx = Ctx(["ShopManager", "PlatformAdmin"])
        ctx.read_body([])
        alloc = need_other("parts_allocations", aid)
        not_terminal(alloc["status"], ALLOCATION_TERMINAL)
        if alloc["status"] not in ("RESERVED", "PARTIAL"):
            fail("ERR_INVALID_STATE",
                 "No allocation edge from %s to RELEASED." % alloc["status"])
        services.release_allocation(alloc)
        payload, status = ok(serialize.parts_allocation(alloc))
        return jsonify(payload), status


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

@bp.post("/milestones/<mid>/release")
def release_milestone(mid):
    with LOCK:
        ctx = Ctx(["ShopManager", "PlatformAdmin"], sod=True)
        ctx.read_body([])
        stone = need_other("milestones", mid)
        order = _milestone_order(stone)
        not_terminal(stone["status"], MILESTONE_TERMINAL)
        if stone["status"] != "READY":
            fail("ERR_INVALID_STATE",
                 "No milestone edge from %s to RELEASED." % stone["status"])
        if order is None or order["status"] != "IN_PROGRESS":
            fail("ERR_INVALID_STATE", "The service order must be IN_PROGRESS.")
        lower = [m for m in DB.milestones.values()
                 if m["service_order_id"] == order["id"]
                 and m["sequence_index"] < stone["sequence_index"]]
        if any(m["status"] != "ACCEPTED" for m in lower):
            fail("ERR_MILESTONE_SEQUENCE",
                 "Every lower sequence_index must be ACCEPTED first.")
        if stone["sequence_index"] == 1:
            client = DB.clients.get(order["client_id"])
            if client is not None and client["account_credit_cents"] < 0:
                fail("ERR_DEPOSIT_NOT_SETTLED", "The deposit is not settled.")
        stone["status"] = "RELEASED"
        stone["released_by_user_id"] = ctx.user_id
        stone["released_at"] = CLOCK.stamp()
        touch(stone)
        payload, status = ok(serialize.milestone(stone))
        return jsonify(payload), status


@bp.post("/milestones/<mid>/accept")
def accept_milestone(mid):
    with LOCK:
        ctx = Ctx(["Client", "PlatformAdmin"])
        existing = DB.milestones.get(mid)
        if existing is not None:
            owner = _milestone_order(existing)
            if owner is not None:
                ctx.scope_client(owner["client_id"])
        ctx.read_body([])
        stone = need_other("milestones", mid)
        order = _milestone_order(stone)
        not_terminal(stone["status"], MILESTONE_TERMINAL)
        if stone["status"] != "RELEASED":
            fail("ERR_INVALID_STATE",
                 "No milestone edge from %s to ACCEPTED." % stone["status"])
        if order is None or order["status"] != "IN_PROGRESS":
            fail("ERR_INVALID_STATE", "The service order must be IN_PROGRESS.")
        client = DB.clients.get(order["client_id"])
        available = services.order_unapplied_deposit(order)
        balance = client["account_credit_cents"] if client else 0
        if balance + available < stone["amount_cents"]:
            fail("ERR_INSUFFICIENT_CREDIT",
                 "The client cannot cover this milestone.")

        applied = min(stone["amount_cents"], max(0, available))
        residual = stone["amount_cents"] - applied
        order["deposit_applied_cents"] += applied
        order["billed_cents"] += stone["amount_cents"]
        order["unbilled_cents"] = order["contract_total_cents"] - order["billed_cents"]
        touch(order)
        stone["status"] = "ACCEPTED"
        stone["accepted_at"] = CLOCK.stamp()
        touch(stone)
        if residual > 0:
            services.post_ledger(order["client_id"], "MILESTONE_CHARGE",
                                 -residual, service_order_id=order["id"])
            services.recompute_balance_for(order["client_id"])
        payload, status = ok(serialize.milestone(stone))
        return jsonify(payload), status


@bp.post("/milestones/<mid>/reject")
def reject_milestone(mid):
    with LOCK:
        ctx = Ctx(["Client", "PlatformAdmin"])
        existing = DB.milestones.get(mid)
        if existing is not None:
            owner = _milestone_order(existing)
            if owner is not None:
                ctx.scope_client(owner["client_id"])
        ctx.read_body([])
        stone = need_other("milestones", mid)
        not_terminal(stone["status"], MILESTONE_TERMINAL)
        if stone["status"] != "RELEASED":
            fail("ERR_INVALID_STATE",
                 "No milestone edge from %s to REJECTED." % stone["status"])
        if stone["rejection_count"] >= calc.MILESTONE_REJECTION_RETRY_LIMIT:
            fail("ERR_ATTEMPT_LIMIT_EXCEEDED", "The rejection cap is reached.")
        stone["rejection_count"] += 1
        stone["released_by_user_id"] = None
        stone["released_at"] = None
        stone["status"] = "READY"
        touch(stone)
        payload, status = ok(serialize.milestone(stone))
        return jsonify(payload), status
