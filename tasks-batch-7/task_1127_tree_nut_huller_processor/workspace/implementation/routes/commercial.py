"""Buyer contracts, shipments, settlements, byproduct sales (PRD §3.7-§3.9)
and the logical-clock test-driving endpoint (PRD §2.5)."""
from flask import Blueprint, request

import db
import response
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_BUYER_NOT_FOUND, ERR_BIN_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND, ERR_SHIPMENT_NOT_FOUND, ERR_SETTLEMENT_NOT_FOUND,
    ERR_LOT_NOT_FOUND, ERR_STALE_CONTRACT_VERSION, ERR_INVALID_STATE,
    ERR_BIN_FUMIGATION_ACTIVE, ERR_SPEC_MISMATCH,
    ERR_CONTRACT_REMAINING_EXCEEDED, ERR_INSUFFICIENT_STORED,
    ERR_BYPRODUCT_STOCK_EXCEEDED,
)
from middleware import authenticate, require_roles, forbid_unless, body
from validate import (
    req_string, req_number, req_int, req_enum, opt_enum_filter, check_range,
    check_state, is_int, SIZE_SPECS, CONTRACT_STATUSES, CONTRACT_TERMINAL,
    SHIPMENT_STATUSES, SHIPMENT_TERMINAL, SETTLEMENT_STATUSES, SETTLEMENT_TERMINAL,
)
from services import calc, cascade
from services.serialize import (
    contract_out, shipment_out, settlement_out, byproduct_sale_out,
)

bp = Blueprint("commercial", __name__)

CONTRACT_READ_ROLES = ["PlantAdmin", "Buyer", "PlantOperator"]
SHIPMENT_READ_ROLES = ["PlantAdmin", "PlantOperator", "Buyer"]
SETTLEMENT_READ_ROLES = ["PlantAdmin", "Grower"]
CONTRACT_PRODUCT_FORMS = ("IN_SHELL", "KERNEL")
BYPRODUCT_FORMS = ("HULL", "SHELL")


def _get_contract_or_404(rid):
    rec = db.store.contracts.get(rid)
    if rec is None:
        raise ApiError(ERR_CONTRACT_NOT_FOUND, 404, "Contract not found: %s" % rid)
    return rec


def _get_shipment_or_404(rid):
    rec = db.store.shipments.get(rid)
    if rec is None:
        raise ApiError(ERR_SHIPMENT_NOT_FOUND, 404, "Shipment not found: %s" % rid)
    return rec


def _get_settlement_or_404(rid):
    rec = db.store.settlements.get(rid)
    if rec is None:
        raise ApiError(ERR_SETTLEMENT_NOT_FOUND, 404, "Settlement not found: %s" % rid)
    return rec


# --------------------------------------------------------------- contracts

@bp.route("/contracts", methods=["POST"])
def create_contract():
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    b = body()
    buyer_id = b.get("buyer_id")
    if buyer_id is not None and buyer_id not in db.store.buyers:
        raise ApiError(ERR_BUYER_NOT_FOUND, 404, "Buyer not found: %s" % buyer_id)
    buyer_id = req_string(b, "buyer_id")
    product_form = req_enum(b, "product_form", CONTRACT_PRODUCT_FORMS)
    size_spec = req_enum(b, "size_spec", SIZE_SPECS)
    max_defects = check_range(req_number(b, "max_defects_pct"), "max_defects_pct", ge=0, lt=1)
    price = check_range(req_int(b, "price_cents_per_lb"), "price_cents_per_lb", gt=0)
    required = check_range(req_number(b, "required_qty_lbs"), "required_qty_lbs", gt=0)
    rec = db.stamp({
        "id": db.new_id(),
        "buyer_id": buyer_id,
        "product_form": product_form,
        "size_spec": size_spec,
        "max_defects_pct": max_defects,
        "price_cents_per_lb": price,
        "required_qty_lbs": calc.round2(required),
        "status": "OPEN",
    })
    db.store.contracts[rec["id"]] = rec
    return response.ok(contract_out(rec), 201)


@bp.route("/contracts", methods=["GET"])
def list_contracts():
    auth = authenticate()
    require_roles(auth, CONTRACT_READ_ROLES)
    buyer_id = request.args.get("buyer_id")
    status = opt_enum_filter(request.args, "status", CONTRACT_STATUSES)
    items = list(db.store.contracts.values())
    if auth.is_buyer:
        items = [c for c in items if c["buyer_id"] == auth.user_id]
    elif buyer_id is not None:
        items = [c for c in items if c["buyer_id"] == buyer_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return response.paginate(items, contract_out)


@bp.route("/contracts/<rid>", methods=["GET"])
def get_contract(rid):
    auth = authenticate()
    require_roles(auth, CONTRACT_READ_ROLES)
    rec = _get_contract_or_404(rid)
    if auth.is_buyer:
        forbid_unless(rec["buyer_id"] == auth.user_id)
    return response.ok(contract_out(rec))


@bp.route("/contracts/<rid>/suspend", methods=["POST"])
def suspend_contract(rid):
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    rec = _get_contract_or_404(rid)
    check_state(rec, ("OPEN",), CONTRACT_TERMINAL, "BuyerContract")
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    return response.ok(contract_out(rec))


@bp.route("/contracts/<rid>/resume", methods=["POST"])
def resume_contract(rid):
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    rec = _get_contract_or_404(rid)
    check_state(rec, ("SUSPENDED",), CONTRACT_TERMINAL, "BuyerContract")
    rec["status"] = "OPEN"
    db.touch(rec)
    return response.ok(contract_out(rec))


@bp.route("/contracts/<rid>/close", methods=["POST"])
def close_contract(rid):
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    rec = _get_contract_or_404(rid)
    check_state(rec, ("OPEN", "SUSPENDED", "FULFILLED"), ("CLOSED",), "BuyerContract")
    reserved, _ = calc.contract_reserved_delivered(rec["id"])
    if calc.D(reserved) != 0:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Contract has reserved quantity and cannot be closed")
    rec["status"] = "CLOSED"
    db.touch(rec)
    return response.ok(contract_out(rec))


# --------------------------------------------------------------- shipments

@bp.route("/shipments", methods=["POST"])
def create_shipment():
    auth = authenticate()
    require_roles(auth, ["PlantOperator"])
    b = body()
    # existence (3): canonical FK order — bin_id before contract_id
    bin_id = b.get("bin_id")
    if bin_id is not None and bin_id not in db.store.bins:
        raise ApiError(ERR_BIN_NOT_FOUND, 404, "Bin not found: %s" % bin_id)
    contract_id = b.get("contract_id")
    if contract_id is not None and contract_id not in db.store.contracts:
        raise ApiError(ERR_CONTRACT_NOT_FOUND, 404, "Contract not found: %s" % contract_id)
    bin_id = req_string(b, "bin_id")
    contract_id = req_string(b, "contract_id")
    bin_rec = db.store.bins[bin_id]
    contract = db.store.contracts[contract_id]
    # OCC (4) before remaining shape (5)
    expected = b.get("expected_contract_version")
    if is_int(expected) and expected != contract["version"]:
        raise ApiError(ERR_STALE_CONTRACT_VERSION, 412,
                       "expected_contract_version does not match the contract's current version")
    # shape (5)
    quantity = check_range(req_number(b, "quantity_lbs"), "quantity_lbs", gt=0)
    if "expected_contract_version" not in b or b["expected_contract_version"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Missing required field: expected_contract_version")
    if not is_int(expected):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_contract_version must be an integer")
    # state (6): contract must be OPEN
    check_state(contract, ("OPEN",), CONTRACT_TERMINAL, "BuyerContract")
    # safety (7): fumigation lockout after lazy clearance
    if bin_rec["status"] != "AVAILABLE":
        raise ApiError(ERR_BIN_FUMIGATION_ACTIVE, 422,
                       "Bin is in %s status (fumigation lockout)" % bin_rec["status"])
    # FIFO reservation walk over the bin's STORED placements of the contract's form
    allocations, remaining_need = calc.fifo_allocate(bin_id, contract["product_form"], quantity)
    # physical (9): sizing-spec gate
    if contract["size_spec"] != "UNSIZED":
        for a in allocations:
            lot = db.store.lots[a["lot_id"]]
            if lot["size_spec"] != contract["size_spec"]:
                raise ApiError(ERR_SPEC_MISMATCH, 422,
                               "Allocated placement lot size_spec does not match the contract")
    # fiscal (10): contract remaining, then pool sufficiency
    c_view = contract_out(contract)
    if calc.D(c_view["reserved_qty_lbs"]) + calc.D(c_view["delivered_qty_lbs"]) \
            + calc.D(quantity) > calc.D(contract["required_qty_lbs"]):
        raise ApiError(ERR_CONTRACT_REMAINING_EXCEEDED, 422,
                       "reserved + delivered + quantity exceeds required_qty_lbs")
    if remaining_need > 0:
        raise ApiError(ERR_INSUFFICIENT_STORED, 422,
                       "FIFO free pool of matching STORED placements is insufficient")
    rec = db.stamp({
        "id": db.new_id(),
        "contract_id": contract_id,
        "bin_id": bin_id,
        "quantity_lbs": calc.round2(quantity),
        "allocations": allocations,
        "status": "PLANNED",
    })
    db.store.shipments[rec["id"]] = rec
    for a in allocations:
        db.touch(db.store.placements[a["placement_id"]])
    # creation increments the contract's version (PRD §2.7)
    db.touch(contract)
    db.touch(bin_rec)
    return response.ok(shipment_out(rec), 201)


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    auth = authenticate()
    require_roles(auth, SHIPMENT_READ_ROLES)
    contract_id = request.args.get("contract_id")
    bin_id = request.args.get("bin_id")
    status = opt_enum_filter(request.args, "status", SHIPMENT_STATUSES)
    items = list(db.store.shipments.values())
    if auth.is_buyer:
        items = [s for s in items
                 if db.store.contracts[s["contract_id"]]["buyer_id"] == auth.user_id]
    if contract_id is not None:
        items = [s for s in items if s["contract_id"] == contract_id]
    if bin_id is not None:
        items = [s for s in items if s["bin_id"] == bin_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return response.paginate(items, shipment_out)


@bp.route("/shipments/<rid>", methods=["GET"])
def get_shipment(rid):
    auth = authenticate()
    require_roles(auth, SHIPMENT_READ_ROLES)
    rec = _get_shipment_or_404(rid)
    if auth.is_buyer:
        forbid_unless(db.store.contracts[rec["contract_id"]]["buyer_id"] == auth.user_id)
    return response.ok(shipment_out(rec))


@bp.route("/shipments/<rid>/confirm", methods=["POST"])
def confirm_shipment(rid):
    auth = authenticate()
    require_roles(auth, ["PlantOperator"])
    rec = _get_shipment_or_404(rid)
    check_state(rec, ("PLANNED",), SHIPMENT_TERMINAL, "Shipment")
    bin_rec = db.store.bins[rec["bin_id"]]
    # safety (7): fumigation lockout after lazy clearance
    if bin_rec["status"] != "AVAILABLE":
        raise ApiError(ERR_BIN_FUMIGATION_ACTIVE, 422,
                       "Bin is in %s status (fumigation lockout)" % bin_rec["status"])
    # deliver: consume allocated weight; placements reaching 0 -> WITHDRAWN
    for a in rec["allocations"]:
        p = db.store.placements[a["placement_id"]]
        p["remaining_lbs"] = calc.round2(calc.D(p["remaining_lbs"]) - calc.D(a["quantity_lbs"]))
        if calc.D(p["remaining_lbs"]) <= 0:
            p["remaining_lbs"] = 0
            p["status"] = "WITHDRAWN"
        db.touch(p)
    rec["status"] = "DELIVERED"
    db.touch(rec)
    contract = db.store.contracts[rec["contract_id"]]
    # bubble-up: OPEN -> FULFILLED when delivered reaches required exactly
    delivered = sum(calc.D(s["quantity_lbs"]) for s in db.store.shipments.values()
                    if s["contract_id"] == contract["id"] and s["status"] == "DELIVERED")
    if contract["status"] == "OPEN" and delivered == calc.D(contract["required_qty_lbs"]):
        contract["status"] = "FULFILLED"
    db.touch(contract)
    db.touch(bin_rec)
    return response.ok(shipment_out(rec))


@bp.route("/shipments/<rid>/cancel", methods=["POST"])
def cancel_shipment(rid):
    auth = authenticate()
    require_roles(auth, ["PlantOperator"])
    rec = _get_shipment_or_404(rid)
    check_state(rec, ("PLANNED",), SHIPMENT_TERMINAL, "Shipment")
    # compensation: release reservations only; remaining_lbs untouched
    for a in rec["allocations"]:
        db.touch(db.store.placements[a["placement_id"]])
    rec["status"] = "CANCELLED"
    db.touch(rec)
    contract = db.store.contracts[rec["contract_id"]]
    db.touch(contract)
    db.touch(db.store.bins[rec["bin_id"]])
    return response.ok(shipment_out(rec))


# -------------------------------------------------------------- settlements

@bp.route("/settlements", methods=["POST"])
def create_settlement():
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    b = body()
    lot_id = b.get("lot_id")
    if lot_id is not None and lot_id not in db.store.lots:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "Lot not found: %s" % lot_id)
    lot_id = req_string(b, "lot_id")
    lot = db.store.lots[lot_id]
    # state (6): lot PROCESSED with a recorded KERNEL_GRADE test
    if lot["status"] != "PROCESSED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Settlement requires a PROCESSED lot, is %s" % lot["status"])
    if calc.latest_test(lot["id"], "KERNEL_GRADE") is None:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Settlement requires a recorded KERNEL_GRADE lab test")
    grower = db.store.growers[lot["grower_id"]]
    graded = lot["graded_kernel_weight_lbs"]
    base, premium, deduction, total = calc.settlement_components(lot, grower, graded)
    rec = db.stamp({
        "id": db.new_id(),
        "lot_id": lot_id,
        "grower_id": lot["grower_id"],
        "graded_kernel_weight_lbs": graded,
        "base_cents": base,
        "premium_cents": premium,
        "moisture_deduction_cents": deduction,
        "total_cents": total,
        "status": "DRAFT",
    })
    db.store.settlements[rec["id"]] = rec
    return response.ok(settlement_out(rec), 201)


@bp.route("/settlements", methods=["GET"])
def list_settlements():
    auth = authenticate()
    require_roles(auth, SETTLEMENT_READ_ROLES)
    lot_id = request.args.get("lot_id")
    grower_id = request.args.get("grower_id")
    status = opt_enum_filter(request.args, "status", SETTLEMENT_STATUSES)
    items = list(db.store.settlements.values())
    if auth.is_grower:
        items = [s for s in items if s["grower_id"] == auth.user_id]
    elif grower_id is not None:
        items = [s for s in items if s["grower_id"] == grower_id]
    if lot_id is not None:
        items = [s for s in items if s["lot_id"] == lot_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return response.paginate(items, settlement_out)


@bp.route("/settlements/<rid>", methods=["GET"])
def get_settlement(rid):
    auth = authenticate()
    require_roles(auth, SETTLEMENT_READ_ROLES)
    rec = _get_settlement_or_404(rid)
    if auth.is_grower:
        forbid_unless(rec["grower_id"] == auth.user_id)
    return response.ok(settlement_out(rec))


def _settlement_action(rid, valid_from, fn):
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    rec = _get_settlement_or_404(rid)
    check_state(rec, valid_from, SETTLEMENT_TERMINAL, "Settlement")
    fn(rec)
    db.touch(rec)
    return response.ok(settlement_out(rec))


@bp.route("/settlements/<rid>/approve", methods=["POST"])
def approve_settlement(rid):
    def do(rec):
        rec["status"] = "ISSUED"
        db.touch(db.store.growers[rec["grower_id"]])
    return _settlement_action(rid, ("DRAFT",), do)


@bp.route("/settlements/<rid>/void", methods=["POST"])
def void_settlement(rid):
    def do(rec):
        rec["status"] = "DRAFT"
        db.touch(db.store.growers[rec["grower_id"]])
    return _settlement_action(rid, ("ISSUED",), do)


@bp.route("/settlements/<rid>/pay", methods=["POST"])
def pay_settlement(rid):
    def do(rec):
        rec["status"] = "PAID"
        db.touch(db.store.growers[rec["grower_id"]])
        lot = db.store.lots.get(rec["lot_id"])
        if lot is not None and lot["status"] == "PROCESSED":
            lot["status"] = "SETTLED"
            db.touch(lot)
    return _settlement_action(rid, ("ISSUED",), do)


@bp.route("/settlements/<rid>/cancel", methods=["POST"])
def cancel_settlement(rid):
    def do(rec):
        rec["status"] = "CANCELLED"
    return _settlement_action(rid, ("DRAFT",), do)


# ----------------------------------------------------------- byproduct sales

@bp.route("/byproduct-sales", methods=["POST"])
def create_byproduct_sale():
    auth = authenticate()
    require_roles(auth, ["PlantOperator"])
    b = body()
    product_form = req_enum(b, "product_form", BYPRODUCT_FORMS)
    quantity = check_range(req_number(b, "quantity_lbs"), "quantity_lbs", gt=0)
    price = check_range(req_int(b, "price_cents_per_lb"), "price_cents_per_lb", gt=0)
    buyer_name = req_string(b, "buyer_name")
    # fiscal (10): plant-wide stock ceiling
    stock = calc.byproduct_available_stock(product_form)
    if calc.D(quantity) > stock:
        raise ApiError(ERR_BYPRODUCT_STOCK_EXCEEDED, 422,
                       "Sale quantity exceeds available %s stock" % product_form)
    rec = db.stamp({
        "id": db.new_id(),
        "product_form": product_form,
        "quantity_lbs": calc.round2(quantity),
        "price_cents_per_lb": price,
        "buyer_name": buyer_name,
        "total_cents": calc.round0(calc.D(quantity) * calc.D(price)),
    })
    db.store.byproduct_sales[rec["id"]] = rec
    return response.ok(byproduct_sale_out(rec), 201)


@bp.route("/byproduct-sales", methods=["GET"])
def list_byproduct_sales():
    auth = authenticate()
    require_roles(auth, ["PlantAdmin", "PlantOperator"])
    product_form = opt_enum_filter(request.args, "product_form", BYPRODUCT_FORMS)
    items = list(db.store.byproduct_sales.values())
    if product_form is not None:
        items = [s for s in items if s["product_form"] == product_form]
    return response.paginate(items, byproduct_sale_out)


# ------------------------------------------------------------ logical clock

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    b = body()
    raw = req_string(b, "to_iso8601")
    dt = db.parse_iso(raw)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 timestamp")
    db.store.clock = dt
    # setting the clock triggers lazy fumigation clearance
    cascade.lazy_clearance()
    return response.ok({"current_utc": db.fmt_clock(db.store.clock)})
