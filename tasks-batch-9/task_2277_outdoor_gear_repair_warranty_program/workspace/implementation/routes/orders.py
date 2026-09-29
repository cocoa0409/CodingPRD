"""Repair orders, work blocks, estimates, invoicing, payment and the endgame."""

from flask import Blueprint

import calc
import services as svc
from core import (
    db, dt_of, end_of_day, fail, get_body, iso, new_row, now, ordered, page,
    pagination, q_bool, q_str, require, respond, respond_list, set_fields, touch,
    v_bool, v_enum, v_instant, v_int, v_string,
)

bp = Blueprint("orders", __name__)

WORK_STATES = (
    "QUEUED", "IN_WORK", "BENCH_DONE", "QC_PASSED", "RELEASED", "IRREPARABLE",
    "CLOSED_UNREPAIRED",
)
BILLING_STATES = (
    "NOT_BILLABLE", "ESTIMATE_PENDING", "ESTIMATE_SENT", "ESTIMATE_APPROVED",
    "ESTIMATE_DECLINED", "INVOICED", "PAID",
)
ESTIMATE_STATES = (
    "SENT", "APPROVED", "DECLINED", "EXPIRED", "SUPERSEDED", "INVOICED", "PAID",
)
ESTIMATE_VARIANTS = ("PROVISIONAL", "FINAL")
BLOCK_STATES = ("SCHEDULED", "COMPLETED", "CANCELLED")


# --------------------------------------------------------------------------- #
# Repair orders
# --------------------------------------------------------------------------- #

@bp.post("/repair-orders")
def create_order():
    require("ServiceAgent")
    body = get_body()

    # check 7
    claim = svc.fk(body, "warranty_claim_id", db.warranty_claims, "ERR_CLAIM_NOT_FOUND")
    # check 9
    if claim is None:
        fail("ERR_INVALID_REQUEST", "Field 'warranty_claim_id' is required.")
    expedite = v_bool(body, "expedite_requested", default=False)

    # check 11 -- only an adjudicated claim may carry an order
    if claim["status"] not in (
        "WARRANTY_APPROVED", "PAID_REPAIR_OFFERED", "REPLACEMENT_AUTHORIZED"
    ):
        fail("ERR_INVALID_CLAIM_STATE")
    # check 39 -- one live order, and only an order-authorising decision
    if claim["decision"] not in ("WARRANTY_REPAIR", "PAID_REPAIR_OFFERED"):
        fail("ERR_ORDER_ALREADY_OPEN")
    if svc.order_of_claim(claim, non_terminal_only=True) is not None:
        fail("ERR_ORDER_ALREADY_OPEN")

    center = svc.center_of(claim)
    item = svc.item_behind_claim(claim)
    model = svc.model_of_item(item)
    live = svc.live_assessment(claim)
    required_work_types = list(live["required_work_types"]) if live is not None else []

    warranty = claim["decision"] == "WARRANTY_REPAIR"

    # turnaround commitment -- the evaluation order is pinned by the PRD
    snapshot = svc.queue_depth_of(center)
    multiplier = svc.surge_multiplier_for(center, snapshot)
    parts_wait = calc.PARTS_WAIT_DAYS[model["parts_support_status"]]
    base_days = calc.base_days(model["category"], required_work_types)
    promised = calc.promised_days(base_days, multiplier, parts_wait)
    promised_return_at = end_of_day(now().date(), promised)

    row = new_row()
    row.update({
        "service_center_id": claim["service_center_id"],
        "warranty_claim_id": claim["id"],
        "gear_item_id": claim["gear_item_id"],
        "order_kind": "WARRANTY_REPAIR" if warranty else "PAID_REPAIR",
        "work_status": "QUEUED",
        "billing_status": "NOT_BILLABLE" if warranty else "ESTIMATE_PENDING",
        "required_work_types": required_work_types,
        "expedite_requested": expedite,
        "queue_depth_snapshot": snapshot,
        "surge_multiplier_applied": float(multiplier),
        "parts_wait_days": parts_wait,
        "promised_days": promised,
        "promised_return_at": iso(promised_return_at),
        "commitment_breached": False,
        "qc_fail_count": 0,
        "provisional_estimate_total_cents": None,
        "final_invoice_total_cents": None,
        "paid_amount_cents": 0,
        "released_at": None,
    })

    if item is not None:
        set_fields(item, disposition_status="IN_REPAIR")

    db.repair_orders[row["id"]] = row
    svc.recompute_center_queue(center)
    return respond(svc.ser(row), 201)


@bp.get("/repair-orders/<order_id>")
def read_order(order_id):
    ctx = require(
        "Customer", "ServiceAgent", "RepairTechnician", "PartsCoordinator", "ProgramAdmin"
    )
    order = svc.need(db.repair_orders, order_id, "ERR_REPAIR_ORDER_NOT_FOUND")
    svc.guard_owner(ctx, svc.item_behind_order(order))
    return respond(svc.ser(order))


@bp.get("/repair-orders")
def list_orders():
    require("Customer", "ServiceAgent", "RepairTechnician", "PartsCoordinator", "ProgramAdmin")
    center_id = q_str("service_center_id")
    claim_id = q_str("warranty_claim_id")
    item_id = q_str("gear_item_id")
    work_status = q_str("work_status")
    if work_status is not None and work_status not in WORK_STATES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'work_status' is not a recognised value.")
    billing_status = q_str("billing_status")
    if billing_status is not None and billing_status not in BILLING_STATES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'billing_status' is not a recognised value.")
    breached = q_bool("commitment_breached")
    limit, offset = pagination()

    rows = []
    for order in ordered(db.repair_orders):
        if center_id is not None and order["service_center_id"] != center_id:
            continue
        if claim_id is not None and order["warranty_claim_id"] != claim_id:
            continue
        if item_id is not None and order["gear_item_id"] != item_id:
            continue
        if work_status is not None and order["work_status"] != work_status:
            continue
        if billing_status is not None and order["billing_status"] != billing_status:
            continue
        if breached is not None and order["commitment_breached"] != breached:
            continue
        rows.append(order)
    window, total = page(rows, limit, offset)
    return respond_list(svc.ser_all(window), limit, offset, total)


# --------------------------------------------------------------------------- #
# Work blocks
# --------------------------------------------------------------------------- #

@bp.post("/work-blocks")
def create_block():
    ctx = require("ServiceAgent", "RepairTechnician")
    body = get_body()

    # check 7 / 8 -- references resolve
    order = svc.fk(body, "repair_order_id", db.repair_orders, "ERR_REPAIR_ORDER_NOT_FOUND")
    named = svc.fk(body, "technician_id", db.technicians, "ERR_TECHNICIAN_NOT_FOUND")

    # check 9 -- shape
    if order is None:
        fail("ERR_INVALID_REQUEST", "Field 'repair_order_id' is required.")
    work_type = v_enum(body, "work_type", calc.WORK_TYPES, required=True)
    start_at = v_instant(body, "start_at", required=True)
    end_at = v_instant(body, "end_at", required=True)

    # check 12 / 13 -- both dimensions gate the bench
    if order["work_status"] not in ("QUEUED", "IN_WORK"):
        fail("ERR_INVALID_WORK_STATE")
    if order["billing_status"] not in ("NOT_BILLABLE", "ESTIMATE_APPROVED"):
        fail("ERR_INVALID_BILLING_STATE")

    subject = named if named is not None else (ctx.actor if ctx.is_tech else None)
    # check 20
    if subject is not None and subject["status"] != "ACTIVE":
        fail("ERR_TECHNICIAN_NOT_ACTIVE")
    # check 21 -- certification, only for an explicitly named technician
    if named is not None:
        level = svc.cert_level(named, work_type)
        if level is None or level < calc.WORK_TYPE_MIN_LEVEL[work_type]:
            fail("ERR_TECHNICIAN_NOT_CERTIFIED")
    # check 25
    if subject is not None and subject["service_center_id"] != order["service_center_id"]:
        fail("ERR_TECHNICIAN_CENTER_MISMATCH")
    # check 32
    if start_at >= end_at:
        fail("ERR_INVALID_WINDOW")
    # check 34 -- a named technician may not double-book
    if named is not None and svc.technician_conflict(named["id"], start_at, end_at):
        fail("ERR_TECHNICIAN_WINDOW_CONFLICT")
    # check 41 -- the centre's daily bench ceiling
    center = svc.center_of(order)
    scheduled_today = svc.scheduled_blocks_on_date(order["service_center_id"], start_at.date())
    if center is not None and scheduled_today >= center["bench_capacity_blocks_per_day"]:
        fail("ERR_BENCH_CAPACITY_EXCEEDED")

    technician = named
    routed = False
    if technician is None:
        # check 48 -- the routing selector must find somebody
        technician = svc.route_technician(
            order["service_center_id"], work_type, start_at, end_at
        )
        if technician is None:
            fail("ERR_NO_ELIGIBLE_TECHNICIAN")
        routed = True

    duration = int((end_at - start_at).total_seconds() // 60)

    row = new_row()
    row.update({
        "technician_id": technician["id"],
        "repair_order_id": order["id"],
        "work_type": work_type,
        "start_at": iso(start_at),
        "end_at": iso(end_at),
        "duration_minutes": duration,
        "actual_minutes": None,
        "status": "SCHEDULED",
        "routed_by_selector": routed,
    })
    db.work_blocks[row["id"]] = row

    set_fields(
        technician,
        scheduled_minutes_open=technician["scheduled_minutes_open"] + duration,
    )
    if order["work_status"] == "QUEUED":
        set_fields(order, work_status="IN_WORK")

    return respond(svc.ser(row), 201)


@bp.get("/work-blocks/<block_id>")
def read_block(block_id):
    require("ServiceAgent", "RepairTechnician", "ProgramAdmin")
    block = svc.need(db.work_blocks, block_id, "ERR_WORK_BLOCK_NOT_FOUND")
    return respond(svc.ser(block))


@bp.get("/work-blocks")
def list_blocks():
    require("ServiceAgent", "RepairTechnician", "ProgramAdmin")
    technician_id = q_str("technician_id")
    order_id = q_str("repair_order_id")
    work_type = q_str("work_type")
    if work_type is not None and work_type not in calc.WORK_TYPES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'work_type' is not a recognised value.")
    status = q_str("status")
    if status is not None and status not in BLOCK_STATES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'status' is not a recognised value.")
    limit, offset = pagination()

    rows = []
    for block in ordered(db.work_blocks):
        if technician_id is not None and block["technician_id"] != technician_id:
            continue
        if order_id is not None and block["repair_order_id"] != order_id:
            continue
        if work_type is not None and block["work_type"] != work_type:
            continue
        if status is not None and block["status"] != status:
            continue
        rows.append(block)
    window, total = page(rows, limit, offset)
    return respond_list(svc.ser_all(window), limit, offset, total)


@bp.post("/work-blocks/<block_id>/cancel")
def cancel_block(block_id):
    require("ServiceAgent", "RepairTechnician")
    block = svc.need(db.work_blocks, block_id, "ERR_WORK_BLOCK_NOT_FOUND")
    body = get_body()
    v_string(body, "reason", max_len=500)

    if block["status"] != "SCHEDULED":
        fail("ERR_ALREADY_TERMINAL")

    svc.cancel_block(block)
    return respond(svc.ser(block))


# --------------------------------------------------------------------------- #
# Estimates
# --------------------------------------------------------------------------- #

def _validate_labor_lines(raw):
    if not isinstance(raw, list) or not raw:
        fail("ERR_INVALID_REQUEST", "Field 'labor_lines' must be a non-empty array.")
    lines = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each labour line must be an object.")
        work_type = entry.get("work_type")
        minutes = entry.get("minutes")
        if work_type not in calc.WORK_TYPES:
            fail("ERR_INVALID_REQUEST", "Labour line 'work_type' is not recognised.")
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
            fail("ERR_INVALID_REQUEST", "Labour line 'minutes' must be a non-negative integer.")
        lines.append({"work_type": work_type, "minutes": minutes})
    return lines


def _validate_parts_lines(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        fail("ERR_INVALID_REQUEST", "Field 'parts_lines' must be an array.")
    lines = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each parts line must be an object.")
        part_code = entry.get("part_code")
        units = entry.get("units")
        unit_price = entry.get("unit_price_cents")
        if not isinstance(part_code, str) or not part_code.strip():
            fail("ERR_INVALID_REQUEST", "Parts line 'part_code' must be a non-blank string.")
        if isinstance(units, bool) or not isinstance(units, int) or units < 0:
            fail("ERR_INVALID_REQUEST", "Parts line 'units' must be a non-negative integer.")
        if (
            isinstance(unit_price, bool)
            or not isinstance(unit_price, int)
            or unit_price < 0
        ):
            fail("ERR_INVALID_REQUEST", "Parts line 'unit_price_cents' must be a non-negative integer.")
        lines.append({
            "part_code": part_code,
            "units": units,
            "unit_price_cents": unit_price,
        })
    return lines


@bp.post("/repair-orders/<order_id>/estimates")
def create_estimate(order_id):
    require("ServiceAgent")
    order = svc.need(db.repair_orders, order_id, "ERR_REPAIR_ORDER_NOT_FOUND")
    body = get_body()

    # check 9 -- shape
    expected_version = v_int(body, "expected_repair_order_version", required=True, min_value=1)
    if "labor_lines" not in body or body["labor_lines"] is None:
        fail("ERR_INVALID_REQUEST", "Field 'labor_lines' is required.")
    labor_lines = _validate_labor_lines(body["labor_lines"])
    parts_lines = _validate_parts_lines(body.get("parts_lines"))

    # check 13 -- ESTIMATE_APPROVED is carved out and answered by check 40
    if order["billing_status"] != "ESTIMATE_APPROVED":
        if order["billing_status"] not in ("ESTIMATE_PENDING", "ESTIMATE_SENT"):
            fail("ERR_INVALID_BILLING_STATE")
    # check 17
    if order["work_status"] in calc.ORDER_WORK_TERMINAL:
        fail("ERR_ALREADY_TERMINAL")
    # check 19 -- optimistic concurrency on the order
    if expected_version != order["version"]:
        fail("ERR_STALE_REPAIR_ORDER_VERSION")
    # check 40
    for estimate in svc.order_estimates(order["id"]):
        if estimate["status"] == "APPROVED":
            fail("ERR_ESTIMATE_ALREADY_APPROVED")

    for estimate in svc.order_estimates(order["id"]):
        if estimate["status"] == "SENT":
            set_fields(estimate, status="SUPERSEDED")

    row = svc.new_estimate(order, "PROVISIONAL", "SENT", labor_lines, parts_lines)

    if not set_fields(order, billing_status="ESTIMATE_SENT"):
        touch(order)

    return respond(svc.ser(row), 201)


@bp.get("/repair-orders/<order_id>/estimates")
def list_order_estimates(order_id):
    ctx = require("Customer", "ServiceAgent", "ProgramAdmin")
    order = svc.need(db.repair_orders, order_id, "ERR_REPAIR_ORDER_NOT_FOUND")
    svc.guard_owner(ctx, svc.item_behind_order(order))
    status = q_str("status")
    if status is not None and status not in ESTIMATE_STATES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'status' is not a recognised value.")
    variant = q_str("variant")
    if variant is not None and variant not in ESTIMATE_VARIANTS:
        fail("ERR_INVALID_REQUEST", "Query parameter 'variant' is not a recognised value.")
    limit, offset = pagination()

    rows = []
    for estimate in svc.order_estimates(order["id"]):
        if status is not None and estimate["status"] != status:
            continue
        if variant is not None and estimate["variant"] != variant:
            continue
        rows.append(estimate)
    window, total = page(rows, limit, offset)
    return respond_list(svc.ser_all(window), limit, offset, total)


@bp.get("/repair-estimates/<estimate_id>")
def read_estimate(estimate_id):
    ctx = require("Customer", "ServiceAgent", "ProgramAdmin")
    estimate = svc.need(db.repair_estimates, estimate_id, "ERR_ESTIMATE_NOT_FOUND")
    svc.guard_owner(ctx, svc.item_behind_estimate(estimate))
    return respond(svc.ser(estimate))


@bp.post("/repair-estimates/<estimate_id>/approve")
def approve_estimate(estimate_id):
    ctx = require("Customer")
    estimate = svc.need(db.repair_estimates, estimate_id, "ERR_ESTIMATE_NOT_FOUND")
    svc.guard_owner(ctx, svc.item_behind_estimate(estimate))
    get_body()
    order = db.repair_orders.get(estimate["repair_order_id"])

    # check 14
    if estimate["status"] != "SENT":
        fail("ERR_INVALID_ESTIMATE_STATE")
    # check 17
    if order is not None and order["work_status"] in calc.ORDER_WORK_TERMINAL:
        fail("ERR_ALREADY_TERMINAL")
    # check 35
    valid_until = dt_of(estimate["valid_until"])
    if valid_until is not None and now() > valid_until:
        fail("ERR_ESTIMATE_EXPIRED")

    set_fields(estimate, status="APPROVED", decided_at=iso(now()))
    if order is not None:
        set_fields(
            order,
            provisional_estimate_total_cents=estimate["total_cents"],
            billing_status="ESTIMATE_APPROVED",
        )
    return respond(svc.ser(estimate))


@bp.post("/repair-estimates/<estimate_id>/decline")
def decline_estimate(estimate_id):
    ctx = require("Customer")
    estimate = svc.need(db.repair_estimates, estimate_id, "ERR_ESTIMATE_NOT_FOUND")
    svc.guard_owner(ctx, svc.item_behind_estimate(estimate))
    body = get_body()
    v_string(body, "decline_reason", max_len=500)
    order = db.repair_orders.get(estimate["repair_order_id"])

    # check 14
    if estimate["status"] != "SENT":
        fail("ERR_INVALID_ESTIMATE_STATE")
    # check 17
    if order is not None and order["work_status"] in calc.ORDER_WORK_TERMINAL:
        fail("ERR_ALREADY_TERMINAL")

    set_fields(estimate, status="DECLINED", decided_at=iso(now()))
    if order is not None:
        svc.decline_cascade(estimate, order)
    return respond(svc.ser(estimate))


# --------------------------------------------------------------------------- #
# Bench completion and quality control
# --------------------------------------------------------------------------- #

@bp.post("/repair-orders/<order_id>/bench-complete")
def bench_complete(order_id):
    ctx = require("RepairTechnician")
    order = svc.need(db.repair_orders, order_id, "ERR_REPAIR_ORDER_NOT_FOUND")
    body = get_body()

    raw = body.get("work_log")
    if raw is None:
        fail("ERR_INVALID_REQUEST", "Field 'work_log' is required.")
    if not isinstance(raw, list) or not raw:
        fail("ERR_INVALID_REQUEST", "Field 'work_log' must be a non-empty array.")

    # check 8 -- every referenced block resolves
    entries = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each work_log entry must be an object.")
        block = svc.need(db.work_blocks, entry.get("work_block_id"), "ERR_WORK_BLOCK_NOT_FOUND")
        entries.append((block, entry))

    # check 9 -- shape of the logged minutes
    logged = {}
    for block, entry in entries:
        minutes = entry.get("actual_minutes")
        if (
            isinstance(minutes, bool)
            or not isinstance(minutes, int)
            or minutes < 1
            or minutes > 600
        ):
            fail("ERR_INVALID_REQUEST", "'actual_minutes' must be an integer 1..600.")
        logged[block["id"]] = (block, minutes)

    # check 12
    if order["work_status"] != "IN_WORK":
        fail("ERR_INVALID_WORK_STATE")
    # check 20
    if ctx.actor["status"] != "ACTIVE":
        fail("ERR_TECHNICIAN_NOT_ACTIVE")
    # check 28
    for block, _minutes in logged.values():
        if block["repair_order_id"] != order["id"] or block["status"] != "SCHEDULED":
            fail("ERR_WORK_BLOCK_NOT_ON_ORDER")
    # check 46 -- every required lane worked once the log is applied
    covered = set()
    for block in svc.order_blocks(order["id"]):
        if block["status"] == "COMPLETED" or block["id"] in logged:
            covered.add(block["work_type"])
    for work_type in order["required_work_types"]:
        if work_type not in covered:
            fail("ERR_WORK_TYPES_INCOMPLETE")

    for block, minutes in logged.values():
        set_fields(block, status="COMPLETED", actual_minutes=minutes)
        technician = db.technicians.get(block["technician_id"])
        if technician is not None:
            set_fields(
                technician,
                scheduled_minutes_open=(
                    technician["scheduled_minutes_open"] - block["duration_minutes"]
                ),
                completed_minutes=technician["completed_minutes"] + minutes,
            )

    set_fields(order, work_status="BENCH_DONE")
    return respond(svc.ser(order))


@bp.post("/repair-orders/<order_id>/qc-inspections")
def qc_inspection(order_id):
    ctx = require("RepairTechnician")
    order = svc.need(db.repair_orders, order_id, "ERR_REPAIR_ORDER_NOT_FOUND")
    body = get_body()
    outcome = v_enum(body, "outcome", ("PASS", "FAIL"), required=True)
    v_string(body, "notes", min_len=1, max_len=2000)

    # check 12
    if order["work_status"] != "BENCH_DONE":
        fail("ERR_INVALID_WORK_STATE")
    # check 20
    if ctx.actor["status"] != "ACTIVE":
        fail("ERR_TECHNICIAN_NOT_ACTIVE")
    # check 22 -- segregation of duties
    for assessment in svc.claim_assessments_of(order["warranty_claim_id"]):
        if assessment["assessor_technician_id"] == ctx.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES")
    # check 47 -- no part may still be merely reserved
    for reservation in svc.order_reservations(order["id"]):
        if reservation["status"] == "RESERVED":
            fail("ERR_PARTS_NOT_SETTLED")

    if outcome == "PASS":
        set_fields(order, work_status="QC_PASSED")
        return respond(svc.ser(order))

    if order["qc_fail_count"] < calc.QC_FAIL_LIMIT - 1:
        set_fields(
            order,
            qc_fail_count=order["qc_fail_count"] + 1,
            work_status="IN_WORK",
        )
        return respond(svc.ser(order))

    set_fields(order, qc_fail_count=calc.QC_FAIL_LIMIT)
    svc.condemn_order(order)
    return respond(svc.ser(order))


@bp.post("/repair-orders/<order_id>/close-irreparable")
def close_irreparable(order_id):
    require("ServiceAgent", "RepairTechnician")
    order = svc.need(db.repair_orders, order_id, "ERR_REPAIR_ORDER_NOT_FOUND")
    body = get_body()
    v_string(body, "reason", required=True, min_len=1, max_len=2000)

    # check 12
    if order["work_status"] not in calc.QUEUE_STATES:
        fail("ERR_INVALID_WORK_STATE")

    svc.condemn_order(order)
    return respond(svc.ser(order))


# --------------------------------------------------------------------------- #
# Invoice, payment, release
# --------------------------------------------------------------------------- #

@bp.post("/repair-orders/<order_id>/invoice")
def invoice(order_id):
    require("ServiceAgent")
    order = svc.need(db.repair_orders, order_id, "ERR_REPAIR_ORDER_NOT_FOUND")
    get_body()

    # check 12
    if order["work_status"] != "QC_PASSED":
        fail("ERR_INVALID_WORK_STATE")
    # check 50
    if order["billing_status"] != "ESTIMATE_APPROVED":
        fail("ERR_ESTIMATE_NOT_APPROVED")

    labor_lines, parts_lines = svc.final_lines(order)
    row = svc.new_estimate(order, "FINAL", "INVOICED", labor_lines, parts_lines)
    set_fields(
        order,
        final_invoice_total_cents=row["total_cents"],
        billing_status="INVOICED",
    )
    return respond(svc.ser(row), 201)


@bp.post("/repair-orders/<order_id>/payments")
def payment(order_id):
    ctx = require("Customer", "ServiceAgent")
    order = svc.need(db.repair_orders, order_id, "ERR_REPAIR_ORDER_NOT_FOUND")
    svc.guard_owner(ctx, svc.item_behind_order(order))
    body = get_body()
    amount = v_int(body, "amount_cents", required=True, min_value=0)

    # check 13
    if order["billing_status"] != "INVOICED":
        fail("ERR_INVALID_BILLING_STATE")
    # check 51 -- settlement is exact
    outstanding = (order["final_invoice_total_cents"] or 0) - order["paid_amount_cents"]
    if amount != outstanding:
        fail("ERR_PAYMENT_AMOUNT_MISMATCH")

    set_fields(
        order,
        paid_amount_cents=order["paid_amount_cents"] + amount,
        billing_status="PAID",
    )
    for estimate in svc.order_estimates(order["id"]):
        if estimate["variant"] == "FINAL" and estimate["status"] == "INVOICED":
            set_fields(estimate, status="PAID")
    return respond(svc.ser(order))


@bp.post("/repair-orders/<order_id>/release-to-customer")
def release_to_customer(order_id):
    require("ServiceAgent")
    order = svc.need(db.repair_orders, order_id, "ERR_REPAIR_ORDER_NOT_FOUND")
    get_body()

    # check 12
    if order["work_status"] != "QC_PASSED":
        fail("ERR_INVALID_WORK_STATE")
    # check 52
    if order["billing_status"] != "NOT_BILLABLE" and order["billing_status"] != "PAID":
        fail("ERR_BALANCE_OUTSTANDING")

    claim = svc.claim_of_order(order)
    item = svc.item_behind_order(order)
    center = svc.center_of(order)

    set_fields(order, work_status="RELEASED", released_at=iso(now()))
    if item is not None:
        set_fields(item, disposition_status="RETURNED")
    if claim is not None:
        set_fields(claim, status="CLOSED_FULFILLED")
        if order["order_kind"] == "WARRANTY_REPAIR":
            if svc.release_claim_liability(claim, "ORDER_RELEASED", basis="REPAIR"):
                svc.recompute_center_liability(center)
    svc.recompute_center_queue(center)
    return respond(svc.ser(order))
