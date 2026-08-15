"""Routes: shipments and shipment lines."""

from datetime import timedelta, date, datetime, time, timezone
from decimal import Decimal

from flask import Blueprint

from db import store
from errors import raise_error
from middleware import require_roles, ALL_ROLES
from response import success, list_response
from util import (get_body, get_body_optional, pagination_params, parse_date, parse_dt,
                  dec, q2, q0)
from services.core import (
    stamp_new, touch, logical_now,
    get_shipment, get_contract, ser_shipment, ser_line,
    shipment_lines, recompute_shipment_aggregates, recompute_batch_pools,
    recompute_contract_week_reserved, cancel_shipment_cascade,
    week_bounds_for_contract, DOCK_MAX_SHIPMENTS_PER_DAY,
)

bp = Blueprint("shipments", __name__)


def _q(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.post("/shipments")
def create_shipment():
    require_roles("ContractsManager")
    fields = {"contract_id", "ship_date", "window_start_at", "window_end_at",
              "expected_contract_version", "lines"}
    body = get_body(fields, fields)
    contract_id = body["contract_id"]
    if not isinstance(contract_id, str):
        raise_error("ERR_INVALID_REQUEST", "contract_id must be a string")
    contract = store.contracts.get(contract_id)
    if contract is None:
        raise_error("ERR_NOT_FOUND", "RetailContract not found")
    ship_date = parse_date(body["ship_date"], "ship_date")
    window_start = parse_dt(body["window_start_at"], "window_start_at")
    window_end = parse_dt(body["window_end_at"], "window_end_at")
    expected_version = body["expected_contract_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise_error("ERR_INVALID_REQUEST", "expected_contract_version must be an integer")
    lines_in = body["lines"]
    if not isinstance(lines_in, list) or not lines_in:
        raise_error("ERR_INVALID_REQUEST", "lines must be a non-empty array")
    parsed_lines = []
    for ln in lines_in:
        if not isinstance(ln, dict):
            raise_error("ERR_INVALID_REQUEST", "each line must be an object")
        extra = set(ln.keys()) - {"batch_id", "reserved_lb"}
        if extra:
            raise_error("ERR_INVALID_REQUEST", f"unknown line fields: {sorted(extra)}")
        if "batch_id" not in ln or "reserved_lb" not in ln:
            raise_error("ERR_INVALID_REQUEST", "line requires batch_id and reserved_lb")
        if not isinstance(ln["batch_id"], str):
            raise_error("ERR_INVALID_REQUEST", "line batch_id must be a string")
        batch = store.batches.get(ln["batch_id"])
        if batch is None:
            raise_error("ERR_NOT_FOUND", f"Batch {ln['batch_id']} not found")
        reserved = dec(ln["reserved_lb"], "reserved_lb")
        if reserved <= 0:
            raise_error("ERR_INVALID_REQUEST", "reserved_lb must be > 0")
        parsed_lines.append((batch, q2(reserved)))
    # cross-entity posture (priority 6)
    if contract["contract_status"] != "ACTIVE":
        raise_error("ERR_CONTRACT_NOT_ACTIVE", "Contract not ACTIVE")
    for batch, _ in parsed_lines:
        if batch["production_status"] != "PACKED":
            raise_error("ERR_BATCH_NOT_PACKED", "Line batch not PACKED")
    # reference coherence (priority 8)
    for batch, _ in parsed_lines:
        if batch["crop_id"] != contract["crop_id"]:
            raise_error("ERR_SHIPMENT_CROP_MISMATCH", "Line batch crop mismatch")
    # temporal (priority 9): ship_date == harvest UTC date of every line's batch;
    # window endpoints on ship_date, start < end
    for batch, _ in parsed_lines:
        if batch.get("harvested_at") is None or batch["harvested_at"].date() != ship_date:
            raise_error("ERR_SHIP_DATE_MISMATCH", "ship_date differs from batch harvest date")
    if window_start.date() != ship_date or window_end.date() != ship_date or not (window_start < window_end):
        raise_error("ERR_SHIP_DATE_MISMATCH", "Window must fall on ship_date with start < end")
    # capacity (priority 10): dock day quota
    dock_load = 0
    for s in store.shipments.values():
        sd = s["ship_date"]
        if isinstance(sd, str):
            sd = date.fromisoformat(sd)
        if sd == ship_date and s["shipment_status"] in ("RESERVED", "PACKED", "SHIPPED"):
            dock_load += 1
    if dock_load >= DOCK_MAX_SHIPMENTS_PER_DAY:
        raise_error("ERR_DOCK_CAPACITY_EXCEEDED", "Dock capacity exceeded")
    # weekly commitment pool
    ws, we = week_bounds_for_contract(contract, ship_date)
    week_reserved = Decimal("0")
    for s in store.shipments.values():
        if s["contract_id"] != contract["id"]:
            continue
        if s["shipment_status"] not in ("RESERVED", "PACKED"):
            continue
        sd = s["ship_date"]
        if isinstance(sd, str):
            sd = date.fromisoformat(sd)
        if ws <= sd < we:
            week_reserved += Decimal(str(s.get("reserved_lb") or 0))
    new_reserved = sum((r for _, r in parsed_lines), Decimal("0"))
    if week_reserved + new_reserved > Decimal(contract["weekly_commitment_lb"]):
        raise_error("ERR_CONTRACT_COMMITMENT_EXCEEDED", "Weekly commitment exceeded")
    # per-batch pounds check (aggregate per batch across lines)
    per_batch = {}
    for batch, r in parsed_lines:
        per_batch[batch["id"]] = per_batch.get(batch["id"], Decimal("0")) + r
    for batch_id, total in per_batch.items():
        batch = store.batches[batch_id]
        if total > Decimal(str(batch.get("packed_available_lb") or 0)):
            raise_error("ERR_BATCH_POUNDS_INSUFFICIENT", "Batch packed_available_lb insufficient")
    # OCC (priority 11)
    if expected_version != contract["version"]:
        raise_error("ERR_STALE_VERSION", "Stale contract version")
    # commit
    shipment = stamp_new({
        "contract_id": contract["id"],
        "ship_date": ship_date,
        "window_start_at": window_start,
        "window_end_at": window_end,
        "shipment_status": "RESERVED",
        "reserved_lb": Decimal("0"),
        "packed_lb": Decimal("0"),
        "shipped_lb": Decimal("0"),
        "has_shortage": False,
        "has_safety_block": False,
        "invoice_total_cents": 0,
    })
    store.shipments[shipment["id"]] = shipment
    touched_batches = {}
    for batch, reserved in parsed_lines:
        line = stamp_new({
            "shipment_id": shipment["id"],
            "batch_id": batch["id"],
            "reserved_lb": reserved,
            "packed_lb": None,
            "shipped_lb": Decimal("0"),
            "line_status": "RESERVED",
        })
        store.shipment_lines[line["id"]] = line
        touched_batches[batch["id"]] = batch
    for batch in touched_batches.values():
        recompute_batch_pools(batch)
        touch(batch)
    recompute_shipment_aggregates(shipment)
    recompute_contract_week_reserved(contract)
    touch(contract)
    return success(ser_shipment(shipment), status=201)


@bp.get("/shipments")
def list_shipments():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.shipments.values())
    cid = _q("contract_id")
    sd = _q("ship_date")
    st = _q("shipment_status")
    if cid is not None:
        items = [s for s in items if s["contract_id"] == cid]
    if sd is not None:
        items = [s for s in items if (s["ship_date"].isoformat() if isinstance(s["ship_date"], date) else s["ship_date"]) == sd]
    if st is not None:
        items = [s for s in items if s["shipment_status"] == st]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    return list_response(items, ser_shipment, limit, offset)


@bp.get("/shipments/<sid>")
def get_shipment_route(sid):
    require_roles(*ALL_ROLES)
    return success(ser_shipment(get_shipment(sid)))


@bp.get("/shipments/<sid>/lines")
def list_shipment_lines(sid):
    require_roles(*ALL_ROLES)
    shipment = get_shipment(sid)
    limit, offset = pagination_params()
    items = shipment_lines(shipment["id"])
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    return list_response(items, ser_line, limit, offset)


@bp.post("/shipments/<sid>/confirm-pack")
def confirm_pack(sid):
    require_roles("ContractsManager")
    body = get_body({"lines"}, {"lines"})
    shipment = get_shipment(sid)
    if shipment["shipment_status"] != "RESERVED":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Shipment not RESERVED")
    lines_in = body["lines"]
    if not isinstance(lines_in, list) or not lines_in:
        raise_error("ERR_INVALID_REQUEST", "lines must be a non-empty array")
    packed_by_line = {}
    for ln in lines_in:
        if not isinstance(ln, dict):
            raise_error("ERR_INVALID_REQUEST", "each line must be an object")
        extra = set(ln.keys()) - {"line_id", "packed_lb"}
        if extra:
            raise_error("ERR_INVALID_REQUEST", f"unknown line fields: {sorted(extra)}")
        if "line_id" not in ln or "packed_lb" not in ln:
            raise_error("ERR_INVALID_REQUEST", "line requires line_id and packed_lb")
        if not isinstance(ln["line_id"], str):
            raise_error("ERR_INVALID_REQUEST", "line_id must be a string")
        line = store.shipment_lines.get(ln["line_id"])
        if line is None:
            raise_error("ERR_NOT_FOUND", f"ShipmentLine {ln['line_id']} not found")
        if line["shipment_id"] != shipment["id"]:
            raise_error("ERR_NOT_FOUND", "Line does not belong to shipment")
        packed = dec(ln["packed_lb"], "packed_lb")
        if packed < 0:
            raise_error("ERR_INVALID_REQUEST", "packed_lb must be non-negative")
        packed_by_line[line["id"]] = q2(packed)
    my_lines = shipment_lines(shipment["id"])
    # every line must get a packed_lb value
    for l in my_lines:
        if l["id"] not in packed_by_line:
            raise_error("ERR_INVALID_REQUEST", "Every line requires a packed_lb value")
    # apply atomically
    touched_batches = {}
    for l in my_lines:
        packed = packed_by_line[l["id"]]
        if packed > l["reserved_lb"]:
            raise_error("ERR_INVALID_REQUEST", "packed_lb may not exceed reserved_lb")
        l["packed_lb"] = packed
        if packed == l["reserved_lb"]:
            l["line_status"] = "PACKED"
        else:
            l["line_status"] = "SHORTED"
        touch(l)
        touched_batches[l["batch_id"]] = store.batches.get(l["batch_id"])
    for batch in touched_batches.values():
        if batch is not None:
            recompute_batch_pools(batch)
            touch(batch)
    shipment["shipment_status"] = "PACKED"
    recompute_shipment_aggregates(shipment)
    touch(shipment)
    contract = store.contracts.get(shipment["contract_id"])
    if contract is not None:
        recompute_contract_week_reserved(contract)
        touch(contract)
    return success(ser_shipment(shipment))


@bp.post("/shipments/<sid>/ship")
def ship_shipment(sid):
    require_roles("ContractsManager")
    get_body_optional(set())
    shipment = get_shipment(sid)
    if shipment["shipment_status"] not in ("RESERVED", "PACKED"):
        raise_error("ERR_INVALID_STATE_TRANSITION", "Shipment not RESERVED/PACKED")
    my_lines = shipment_lines(shipment["id"])
    # lifecycle state: every line must have been through confirm-pack
    for l in my_lines:
        if l["line_status"] == "RESERVED":
            raise_error("ERR_LINE_NOT_PACKED", "Line still RESERVED")
    # food-safety gates (priority 7)
    for l in my_lines:
        if l["line_status"] not in ("PACKED", "SHORTED"):
            continue
        batch = store.batches.get(l["batch_id"])
        if batch is None:
            continue
        if batch["safety_status"] == "PENDING":
            raise_error("ERR_BATCH_SAFETY_PENDING", "Batch safety PENDING")
        if batch["safety_status"] == "QUARANTINED":
            raise_error("ERR_BATCH_QUARANTINED", "Batch QUARANTINED")
        if batch["safety_status"] == "CONDEMNED":
            raise_error("ERR_BATCH_CONDEMNED", "Batch CONDEMNED")
    # window (priority 9)
    now = logical_now()
    if now < shipment["window_start_at"] or now > shipment["window_end_at"]:
        raise_error("ERR_SHIPMENT_WINDOW_CLOSED", "Outside dock window")
    sd = shipment["ship_date"]
    if isinstance(sd, str):
        sd = date.fromisoformat(sd)
    if now.date() != sd:
        raise_error("ERR_SHIPMENT_WINDOW_CLOSED", "Clock date != ship_date")
    # commit
    contract = store.contracts.get(shipment["contract_id"])
    touched_batches = {}
    invoice = 0
    for l in my_lines:
        if l["line_status"] in ("PACKED", "SHORTED"):
            l["line_status"] = "SHIPPED"
            l["shipped_lb"] = l["packed_lb"] or Decimal("0")
            touch(l)
            touched_batches[l["batch_id"]] = store.batches.get(l["batch_id"])
            if contract is not None:
                amount = q0(Decimal(str(l["shipped_lb"])) * Decimal(contract["price_per_pound_cents"]))
                invoice += int(amount)
    for batch in touched_batches.values():
        if batch is not None:
            recompute_batch_pools(batch)
            touch(batch)
    shipment["shipment_status"] = "SHIPPED"
    shipment["invoice_total_cents"] = invoice
    recompute_shipment_aggregates(shipment)
    touch(shipment)
    if contract is not None:
        recompute_contract_week_reserved(contract)
        touch(contract)
    return success(ser_shipment(shipment))


@bp.post("/shipments/<sid>/cancel")
def cancel_shipment(sid):
    require_roles("ContractsManager")
    get_body_optional(set())
    shipment = get_shipment(sid)
    if shipment["shipment_status"] not in ("RESERVED", "PACKED"):
        raise_error("ERR_INVALID_STATE_TRANSITION", "Shipment not RESERVED/PACKED")
    cancel_shipment_cascade(shipment, "CANCELED")
    return success(ser_shipment(shipment))
