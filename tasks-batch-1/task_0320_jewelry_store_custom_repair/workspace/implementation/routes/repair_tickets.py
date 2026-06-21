"""Repair tickets — intake, bench, fork-join floor (PRD §3.4)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_caller, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.calc import repair_total
from services.common import (
    get_body, require_str, require_int, require_enum, require_datetime, optional_bool,
    resolve_fk, resolve_path, require_own_version, bench_conflict, parse_dt,
)

bp = Blueprint("repair_tickets", __name__)

REPAIR_KINDS = {"RESIZE", "STONE_RESET", "POLISH", "CLASP_REPAIR", "WARRANTY"}


def create_repair_ticket_record(customer_id, inventory_item_id, repair_kind, rush,
                                promised_at, warranty_claim_id=None,
                                parts_cents=0, labor_cents=0):
    """Internal factory — also used by the warranty-claim spawn cascade."""
    rec = db.new_record()
    rec.update({
        "customer_id": customer_id, "inventory_item_id": inventory_item_id,
        "repair_kind": repair_kind, "parts_cents": parts_cents, "labor_cents": labor_cents,
        "rush": rush, "rush_surcharge_cents": 0, "total_cents": 0,
        "promised_at": promised_at, "bench_id": None, "scheduled_start": None,
        "scheduled_end": None, "warranty_claim_id": warranty_claim_id, "status": "INTAKE",
    })
    db.repair_tickets[rec["id"]] = rec
    return rec


@bp.route("/repair-tickets", methods=["POST"])
def create_repair_ticket():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager"})
    body = get_body()
    customer_id = require_str(body, "customer_id")
    resolve_fk(db.customers, customer_id)
    inventory_item_id = body.get("inventory_item_id")
    if inventory_item_id is not None:
        if not isinstance(inventory_item_id, str):
            raise ApiError("ERR_INVALID_REQUEST", "inventory_item_id must be a string")
        resolve_fk(db.inventory_items, inventory_item_id)
    repair_kind = require_enum(body, "repair_kind", REPAIR_KINDS)
    rush = optional_bool(body, "rush", default=False)
    promised_at = require_datetime(body, "promised_at")
    rec = create_repair_ticket_record(customer_id, inventory_item_id, repair_kind, rush, promised_at)
    return success(serialize.repair_ticket(rec), status=201)


@bp.route("/repair-tickets", methods=["GET"])
def list_repair_tickets():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Goldsmith", "Customer"})
    limit, offset = parse_pagination()
    f_customer = request.args.get("customer_id")
    f_item = request.args.get("inventory_item_id")
    f_warranty = request.args.get("warranty_claim_id")
    f_bench = request.args.get("bench_id")
    records = []
    for t in db.repair_tickets.values():
        if f_customer is not None and t["customer_id"] != f_customer:
            continue
        if f_item is not None and t.get("inventory_item_id") != f_item:
            continue
        if f_warranty is not None and t.get("warranty_claim_id") != f_warranty:
            continue
        if f_bench is not None and t.get("bench_id") != f_bench:
            continue
        records.append(t)
    page, meta = paginate(records, limit, offset)
    return success([serialize.repair_ticket(r) for r in page], status=200, pagination=meta)


@bp.route("/repair-tickets/<tid>", methods=["GET"])
def get_repair_ticket(tid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Goldsmith", "Customer"})
    rec = resolve_path(db.repair_tickets, tid)
    return success(serialize.repair_ticket(rec), status=200)


@bp.route("/repair-tickets/<tid>/schedule", methods=["POST"])
def schedule_ticket(tid):
    _, role = get_caller()
    require_role(role, {"Goldsmith", "StoreManager"})
    rec = resolve_path(db.repair_tickets, tid)
    body = get_body()
    bench_id = require_str(body, "bench_id")
    resolve_fk(db.workbenches, bench_id)
    start = require_datetime(body, "scheduled_start")
    end = require_datetime(body, "scheduled_end")
    if not (parse_dt(end) > parse_dt(start)):
        raise ApiError("ERR_INVALID_REQUEST", "scheduled_end must be after scheduled_start")
    # Half-open bench overlap check (PRD §2.10).
    if bench_conflict(bench_id, start, end, rec["id"]):
        raise ApiError("ERR_BENCH_CONFLICT", "Bench window conflicts with another reservation")
    require_own_version(rec, body)
    rec["bench_id"] = bench_id
    rec["scheduled_start"] = start
    rec["scheduled_end"] = end
    db.touch(rec)
    return success(serialize.repair_ticket(rec), status=200)


@bp.route("/repair-tickets/<tid>/assess", methods=["POST"])
def assess_ticket(tid):
    _, role = get_caller()
    require_role(role, {"Goldsmith"})
    rec = resolve_path(db.repair_tickets, tid)
    body = get_body()
    if rec["status"] != "INTAKE":
        raise ApiError("ERR_INVALID_STATE", "Ticket is not INTAKE")
    parts = require_int(body, "parts_cents", ge=0)
    labor = require_int(body, "labor_cents", ge=0)
    require_own_version(rec, body)
    is_warranty = rec["repair_kind"] == "WARRANTY"
    if is_warranty:
        parts, labor = 0, 0
    rec["parts_cents"] = parts
    rec["labor_cents"] = labor
    surcharge, total = repair_total(parts, labor, rec["rush"], is_warranty)
    rec["rush_surcharge_cents"] = surcharge
    rec["total_cents"] = total
    rec["status"] = "ASSESSED"
    db.touch(rec)
    # Cross-entity: move store-owned piece into the shop.
    if rec.get("inventory_item_id"):
        item = db.inventory_items.get(rec["inventory_item_id"])
        if item is not None:
            item["status"] = "IN_REPAIR"
            db.touch(item)
    return success(serialize.repair_ticket(rec), status=200)


@bp.route("/repair-tickets/<tid>/order-parts", methods=["POST"])
def order_parts(tid):
    _, role = get_caller()
    require_role(role, {"Goldsmith"})
    rec = resolve_path(db.repair_tickets, tid)
    body = get_body()
    if rec["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", "Ticket is not ASSESSED")
    if rec["parts_cents"] <= 0:
        raise ApiError("ERR_NO_PARTS_NEEDED", "No parts needed for this ticket")
    require_own_version(rec, body)
    rec["status"] = "AWAITING_PARTS"
    db.touch(rec)
    return success(serialize.repair_ticket(rec), status=200)


@bp.route("/repair-tickets/<tid>/parts-received", methods=["POST"])
def parts_received(tid):
    _, role = get_caller()
    require_role(role, {"Goldsmith"})
    rec = resolve_path(db.repair_tickets, tid)
    body = get_body()
    if rec["status"] != "AWAITING_PARTS":
        raise ApiError("ERR_INVALID_STATE", "Ticket is not AWAITING_PARTS")
    require_own_version(rec, body)
    rec["status"] = "IN_REPAIR"
    db.touch(rec)
    return success(serialize.repair_ticket(rec), status=200)


@bp.route("/repair-tickets/<tid>/start-repair", methods=["POST"])
def start_repair(tid):
    _, role = get_caller()
    require_role(role, {"Goldsmith"})
    rec = resolve_path(db.repair_tickets, tid)
    body = get_body()
    if rec["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", "Ticket is not ASSESSED")
    require_own_version(rec, body)
    rec["status"] = "IN_REPAIR"
    db.touch(rec)
    return success(serialize.repair_ticket(rec), status=200)


@bp.route("/repair-tickets/<tid>/submit-qc", methods=["POST"])
def submit_qc(tid):
    _, role = get_caller()
    require_role(role, {"Goldsmith"})
    rec = resolve_path(db.repair_tickets, tid)
    body = get_body()
    if rec["status"] != "IN_REPAIR":
        raise ApiError("ERR_INVALID_STATE", "Ticket is not IN_REPAIR")
    require_own_version(rec, body)
    rec["status"] = "QC"
    db.touch(rec)
    return success(serialize.repair_ticket(rec), status=200)


@bp.route("/repair-tickets/<tid>/pass-qc", methods=["POST"])
def pass_qc(tid):
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    rec = resolve_path(db.repair_tickets, tid)
    body = get_body()
    if rec["status"] != "QC":
        raise ApiError("ERR_INVALID_STATE", "Ticket is not in QC")
    require_own_version(rec, body)
    rec["status"] = "READY"
    db.touch(rec)
    return success(serialize.repair_ticket(rec), status=200)


@bp.route("/repair-tickets/<tid>/fail-qc", methods=["POST"])
def fail_qc(tid):
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    rec = resolve_path(db.repair_tickets, tid)
    body = get_body()
    if rec["status"] != "QC":
        raise ApiError("ERR_INVALID_STATE", "Ticket is not in QC")
    require_own_version(rec, body)
    rec["status"] = "IN_REPAIR"
    db.touch(rec)
    return success(serialize.repair_ticket(rec), status=200)


@bp.route("/repair-tickets/<tid>/pickup", methods=["POST"])
def pickup_ticket(tid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate"})
    rec = resolve_path(db.repair_tickets, tid)
    body = get_body()
    if rec["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", "Ticket is not READY")
    require_own_version(rec, body)
    rec["status"] = "PICKED_UP"
    db.touch(rec)
    # Restore store-owned piece.
    if rec.get("inventory_item_id"):
        item = db.inventory_items.get(rec["inventory_item_id"])
        if item is not None:
            item["status"] = "IN_STOCK"
            db.touch(item)
    # Bubble up to resolve the originating warranty claim.
    if rec.get("warranty_claim_id"):
        claim = db.warranty_claims.get(rec["warranty_claim_id"])
        if claim is not None and claim["status"] == "APPROVED":
            claim["status"] = "RESOLVED"
            db.touch(claim)
    return success(serialize.repair_ticket(rec), status=200)


@bp.route("/repair-tickets/<tid>/cancel", methods=["POST"])
def cancel_ticket(tid):
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    rec = resolve_path(db.repair_tickets, tid)
    body = get_body()
    if rec["status"] in ("READY", "PICKED_UP", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE", "Ticket cannot be cancelled from its current state")
    require_own_version(rec, body)
    rec["status"] = "CANCELLED"
    db.touch(rec)
    if rec.get("inventory_item_id"):
        item = db.inventory_items.get(rec["inventory_item_id"])
        if item is not None:
            item["status"] = "IN_STOCK"
            db.touch(item)
    if rec.get("warranty_claim_id"):
        claim = db.warranty_claims.get(rec["warranty_claim_id"])
        if claim is not None and claim["status"] == "APPROVED":
            claim["status"] = "REJECTED"
            db.touch(claim)
    return success(serialize.repair_ticket(rec), status=200)
