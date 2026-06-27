"""Grain Elevator & Marketing Co-op API — entry point and all routes.

In-memory only: all state lives in db.store (Python dicts keyed by id) and is
wiped on every process restart. No seeding, no preloaded entities, no disk I/O.
"""
import os
from datetime import timedelta

from flask import Flask, request

import errors
import response
from db import store
from middleware import require_roles
from common import (
    stamp_create, touch, must_get, require_fk, get_body, paginate,
    require_str, require_number, optional_number, require_int,
    require_enum, optional_enum, parse_dt, parse_iso, round2, round4, floor2, D,
)
from serialize import public, public_list
import calculations as calc

app = Flask(__name__)


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return response.error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(_e):
    return response.error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(_e):
    return response.error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, errors.ApiError):
        return response.error_response(err.error_id, err.message, err.http_status)
    return response.error_response("ERR_INVALID_REQUEST", str(err), 422)


# ===========================================================================
# Helpers for current price board / version recompute
# ===========================================================================
def current_price_board(commodity_id):
    """The board with the greatest created_at among boards for this commodity."""
    boards = [b for b in store.price_boards.values()
              if b["commodity_id"] == commodity_id]
    if not boards:
        return None
    return max(boards, key=lambda b: (b["created_at"], b["_seq"]))


def is_current_board(board):
    cur = current_price_board(board["commodity_id"])
    return cur is not None and cur["id"] == board["id"]


def board_view(board):
    """PriceBoard view computes is_current dynamically."""
    out = public(board)
    out["is_current"] = is_current_board(board)
    return out


def position_available(position):
    return position["bushels_available"]


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    require_roles({"Merchandiser"})
    body = get_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise errors.invalid_request("Missing required field 'to_iso8601'.")
    dt = parse_iso(body["to_iso8601"])
    if dt is None:
        raise errors.invalid_request("Field 'to_iso8601' is not a valid ISO 8601 datetime.")
    with store.lock:
        store.clock = dt
    return response.object_response({})


# ===========================================================================
# Commodity
# ===========================================================================
COMMODITY_SYMBOLS = {"CORN", "SOYBEANS", "WHEAT"}


@app.route("/commodities", methods=["POST"])
def create_commodity():
    require_roles({"Merchandiser"})
    body = get_body()
    symbol = require_enum(body, "symbol", COMMODITY_SYMBOLS)
    test_weight = require_number(body, "test_weight_lbs_per_bushel", non_negative=True)
    base_moisture = require_number(body, "base_moisture_pct", non_negative=True)
    shrink = require_number(body, "shrink_pct_per_point", non_negative=True)
    drying = require_number(body, "drying_cents_per_point_per_bushel", non_negative=True)
    futures_bu = body.get("futures_contract_bushels")
    if futures_bu is None:
        futures_bu = 5000
    else:
        futures_bu = require_int(body, "futures_contract_bushels", non_negative=True)

    with store.lock:
        # symbol unique across Commodity
        for c in store.commodities.values():
            if c["symbol"] == symbol:
                raise errors.invalid_request("Commodity symbol must be unique.")
        rec = {
            "symbol": symbol,
            "test_weight_lbs_per_bushel": test_weight,
            "base_moisture_pct": base_moisture,
            "shrink_pct_per_point": shrink,
            "drying_cents_per_point_per_bushel": drying,
            "futures_contract_bushels": futures_bu,
        }
        stamp_create(rec)
        store.commodities[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/commodities/<cid>", methods=["GET"])
def get_commodity(cid):
    require_roles({"Merchandiser", "GradeClerk", "SettlementOfficer", "RiskManager", "ShippingClerk"})
    rec = must_get(store.commodities, cid)
    return response.object_response(public(rec))


# ===========================================================================
# PriceBoard
# ===========================================================================
@app.route("/commodities/price-boards", methods=["POST"])
def create_price_board():
    require_roles({"Merchandiser"})
    body = get_body()
    with store.lock:
        commodity_id, _ = require_fk(body, "commodity_id", store.commodities)
        futures_price = require_number(body, "futures_price")
        cash_basis = require_number(body, "cash_basis")
        cash_price = round4(D(futures_price) + D(cash_basis))
        rec = {
            "commodity_id": commodity_id,
            "futures_price": futures_price,
            "cash_basis": cash_basis,
            "cash_price": cash_price,
        }
        stamp_create(rec)
        store.price_boards[rec["id"]] = rec
    return response.object_response(board_view(rec), 201)


@app.route("/commodities/price-boards/<bid>", methods=["GET"])
def get_price_board(bid):
    require_roles({"Merchandiser", "GradeClerk", "SettlementOfficer", "RiskManager", "ShippingClerk"})
    rec = must_get(store.price_boards, bid)
    return response.object_response(board_view(rec))


@app.route("/commodities/price-boards", methods=["GET"])
def list_price_boards():
    require_roles({"Merchandiser", "GradeClerk", "SettlementOfficer", "RiskManager", "ShippingClerk"})
    commodity_id = request.args.get("commodity_id")
    is_current_filter = request.args.get("is_current")
    records = list(store.price_boards.values())
    if commodity_id is not None:
        records = [r for r in records if r["commodity_id"] == commodity_id]
    if is_current_filter is not None:
        want = is_current_filter.lower() in ("true", "1", "yes")
        records = [r for r in records if is_current_board(r) == want]
    window, limit, offset, total = paginate(records)
    return response.array_response([board_view(r) for r in window], limit, offset, total)


# ===========================================================================
# Member
# ===========================================================================
@app.route("/commodities/members", methods=["POST"])
def create_member():
    require_roles({"Merchandiser"})
    body = get_body()
    name = require_str(body, "name")
    with store.lock:
        rec = {
            "name": name,
            "equity_credit_dollars": 0,
            "cash_paid_dollars": 0,
            "net_priced_bushels": 0,
        }
        stamp_create(rec)
        store.members[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/commodities/members/<mid>", methods=["GET"])
def get_member(mid):
    require_roles({"Merchandiser", "GradeClerk", "SettlementOfficer", "RiskManager", "ShippingClerk"})
    rec = must_get(store.members, mid)
    return response.object_response(public(rec))


@app.route("/commodities/members/<mid>/allocations", methods=["GET"])
def list_member_allocations(mid):
    require_roles({"Merchandiser", "SettlementOfficer"})
    must_get(store.members, mid)
    records = [a for a in store.patronage_allocations.values() if a["member_id"] == mid]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


# ===========================================================================
# ScaleTicket
# ===========================================================================
DEPOSIT_TYPES = {"DELAYED_PRICE", "WAREHOUSE_RECEIPT"}


@app.route("/commodities/scale-tickets", methods=["POST"])
def create_scale_ticket():
    require_roles({"GradeClerk"})
    body = get_body()
    with store.lock:
        # Existence (priority 3) precedes body field constraints (priority 4).
        member_id, _ = require_fk(body, "member_id", store.members)
        commodity_id, _ = require_fk(body, "commodity_id", store.commodities)

        gross = require_number(body, "gross_weight_lbs", non_negative=True)
        tare = require_number(body, "tare_weight_lbs", non_negative=True)
        moisture = require_number(body, "moisture_pct", non_negative=True)
        deposit_type = require_enum(body, "deposit_account_type", DEPOSIT_TYPES)
        dockage = optional_number(body, "dockage_pct", default=0, non_negative=True)

        if not (gross > tare):
            raise errors.invalid_request("gross_weight_lbs must be strictly greater than tare_weight_lbs.")

        rec = {
            "member_id": member_id,
            "commodity_id": commodity_id,
            "gross_weight_lbs": gross,
            "tare_weight_lbs": tare,
            "moisture_pct": moisture,
            "dockage_pct": dockage,
            "deposit_account_type": deposit_type,
            "status": "WEIGHED",
            "net_weight_lbs": None,
            "clean_weight_lbs": None,
            "moisture_points": None,
            "wet_bushels": None,
            "net_dry_bushels": None,
            "drying_charge_dollars": None,
            "storage_position_id": None,
        }
        stamp_create(rec)
        store.scale_tickets[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/commodities/scale-tickets/<tid>", methods=["GET"])
def get_scale_ticket(tid):
    require_roles({"Merchandiser", "GradeClerk", "SettlementOfficer"})
    rec = must_get(store.scale_tickets, tid)
    return response.object_response(public(rec))


@app.route("/commodities/scale-tickets", methods=["GET"])
def list_scale_tickets():
    require_roles({"Merchandiser", "GradeClerk", "SettlementOfficer"})
    member_id = request.args.get("member_id")
    commodity_id = request.args.get("commodity_id")
    storage_position_id = request.args.get("storage_position_id")
    records = list(store.scale_tickets.values())
    if member_id is not None:
        records = [r for r in records if r["member_id"] == member_id]
    if commodity_id is not None:
        records = [r for r in records if r["commodity_id"] == commodity_id]
    if storage_position_id is not None:
        records = [r for r in records if r["storage_position_id"] == storage_position_id]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/commodities/scale-tickets/<tid>/grade", methods=["POST"])
def grade_scale_ticket(tid):
    require_roles({"GradeClerk"})
    with store.lock:
        ticket = must_get(store.scale_tickets, tid)
        if ticket["status"] != "WEIGHED":
            raise errors.invalid_state("Only a WEIGHED ticket can be graded.")
        commodity = store.commodities[ticket["commodity_id"]]
        results = calc.grade_in(ticket, commodity)
        ticket.update(results)

        # Create the StoragePosition (STORED)
        pos = {
            "member_id": ticket["member_id"],
            "commodity_id": ticket["commodity_id"],
            "scale_ticket_id": ticket["id"],
            "program": ticket["deposit_account_type"],
            "bushels": results["net_dry_bushels"],
            "bushels_available": results["net_dry_bushels"],
            "status": "STORED",
            "storage_start_date": _iso_from_clock(store.clock),
            "_storage_start_dt": store.clock,
            "frozen_days": 0,
            "receipt_id": None,
            "_frozen_at": None,  # internal: clock instant of current freeze
        }
        stamp_create(pos)
        store.storage_positions[pos["id"]] = pos

        ticket["storage_position_id"] = pos["id"]
        ticket["status"] = "GRADED"
        touch(ticket)
    return response.object_response(public(ticket))


@app.route("/commodities/scale-tickets/<tid>/void", methods=["POST"])
def void_scale_ticket(tid):
    require_roles({"GradeClerk"})
    with store.lock:
        ticket = must_get(store.scale_tickets, tid)
        if ticket["status"] != "WEIGHED":
            raise errors.invalid_state("Only a WEIGHED ticket can be voided.")
        ticket["status"] = "VOIDED"
        touch(ticket)
    return response.object_response(public(ticket))


def _iso_from_clock(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ===========================================================================
# StoragePosition
# ===========================================================================
@app.route("/commodities/storage-positions/<pid>", methods=["GET"])
def get_storage_position(pid):
    require_roles({"Merchandiser", "GradeClerk", "SettlementOfficer", "ShippingClerk"})
    rec = must_get(store.storage_positions, pid)
    return response.object_response(public(rec))


@app.route("/commodities/storage-positions", methods=["GET"])
def list_storage_positions():
    require_roles({"Merchandiser", "GradeClerk", "SettlementOfficer", "ShippingClerk"})
    member_id = request.args.get("member_id")
    commodity_id = request.args.get("commodity_id")
    scale_ticket_id = request.args.get("scale_ticket_id")
    receipt_id = request.args.get("receipt_id")
    records = list(store.storage_positions.values())
    if member_id is not None:
        records = [r for r in records if r["member_id"] == member_id]
    if commodity_id is not None:
        records = [r for r in records if r["commodity_id"] == commodity_id]
    if scale_ticket_id is not None:
        records = [r for r in records if r["scale_ticket_id"] == scale_ticket_id]
    if receipt_id is not None:
        records = [r for r in records if r["receipt_id"] == receipt_id]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/commodities/storage-positions/<pid>/freeze-charge", methods=["POST"])
def freeze_charge(pid):
    require_roles({"Merchandiser"})
    with store.lock:
        pos = must_get(store.storage_positions, pid)
        if pos["status"] != "STORED":
            raise errors.invalid_state("Position must be STORED to freeze its charge.")
        if pos["program"] != "DELAYED_PRICE":
            raise errors.program_mismatch("Only DELAYED_PRICE positions accrue per-day storage and can be charge-frozen.")
        pos["status"] = "CHARGE_FROZEN"
        pos["_frozen_at"] = store.clock
        touch(pos)
    return response.object_response(public(pos))


@app.route("/commodities/storage-positions/<pid>/unfreeze-charge", methods=["POST"])
def unfreeze_charge(pid):
    require_roles({"Merchandiser"})
    with store.lock:
        pos = must_get(store.storage_positions, pid)
        if pos["status"] != "CHARGE_FROZEN":
            raise errors.invalid_state("Position must be CHARGE_FROZEN to unfreeze.")
        frozen_at = pos.get("_frozen_at")
        if frozen_at is not None:
            whole_days = (store.clock - frozen_at).days
            if whole_days < 0:
                whole_days = 0
            pos["frozen_days"] = pos["frozen_days"] + whole_days
        pos["_frozen_at"] = None
        pos["status"] = "STORED"
        touch(pos)
    return response.object_response(public(pos))


# ===========================================================================
# WarehouseReceipt
# ===========================================================================
@app.route("/commodities/warehouse-receipts", methods=["POST"])
def create_warehouse_receipt():
    require_roles({"Merchandiser"})
    body = get_body()
    with store.lock:
        _, pos = require_fk(body, "storage_position_id", store.storage_positions)
        rec = {
            "storage_position_id": pos["id"],
            "member_id": pos["member_id"],
            "bushels": pos["bushels"],
            "status": "ISSUED",
        }
        stamp_create(rec)
        store.warehouse_receipts[rec["id"]] = rec
        pos["receipt_id"] = rec["id"]
        touch(pos)
    return response.object_response(public(rec), 201)


@app.route("/commodities/warehouse-receipts/<rid>", methods=["GET"])
def get_warehouse_receipt(rid):
    require_roles({"Merchandiser", "SettlementOfficer", "ShippingClerk"})
    rec = must_get(store.warehouse_receipts, rid)
    return response.object_response(public(rec))


@app.route("/commodities/warehouse-receipts", methods=["GET"])
def list_warehouse_receipts():
    require_roles({"Merchandiser", "SettlementOfficer", "ShippingClerk"})
    storage_position_id = request.args.get("storage_position_id")
    member_id = request.args.get("member_id")
    records = list(store.warehouse_receipts.values())
    if storage_position_id is not None:
        records = [r for r in records if r["storage_position_id"] == storage_position_id]
    if member_id is not None:
        records = [r for r in records if r["member_id"] == member_id]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


# ===========================================================================
# Contract
# ===========================================================================
CONTRACT_TYPES = {"CASH", "FORWARD", "BASIS", "HTA"}


@app.route("/commodities/contracts", methods=["POST"])
def create_contract():
    require_roles({"Merchandiser"})
    body = get_body()
    with store.lock:
        member_id, _ = require_fk(body, "member_id", store.members)
        commodity_id, _ = require_fk(body, "commodity_id", store.commodities)
        contract_type = require_enum(body, "contract_type", CONTRACT_TYPES)
        contracted_bushels = require_number(body, "contracted_bushels", non_negative=True)
        futures_leg = optional_number(body, "futures_leg", default=None)
        basis_leg = optional_number(body, "basis_leg", default=None)

        # Required legs per type (PRD §3.4)
        if contract_type == "FORWARD":
            if futures_leg is None or basis_leg is None:
                raise errors.invalid_request("FORWARD contract requires both futures_leg and basis_leg.")
        elif contract_type == "BASIS":
            if basis_leg is None:
                raise errors.invalid_request("BASIS contract requires basis_leg at create.")
            futures_leg = None  # futures floats, fixed later
        elif contract_type == "HTA":
            if futures_leg is None:
                raise errors.invalid_request("HTA contract requires futures_leg at create.")
            basis_leg = None  # basis floats, fixed later
        else:  # CASH
            futures_leg = None
            basis_leg = None

        rec = {
            "member_id": member_id,
            "commodity_id": commodity_id,
            "contract_type": contract_type,
            "contracted_bushels": contracted_bushels,
            "futures_leg": futures_leg,
            "basis_leg": basis_leg,
            "net_price": None,
            "status": "OPEN",
            "priced_bushels": 0,
        }
        if contract_type == "FORWARD":
            rec["net_price"] = calc.net_price(futures_leg, basis_leg)
        stamp_create(rec)
        store.contracts[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/commodities/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    require_roles({"Merchandiser", "SettlementOfficer"})
    rec = must_get(store.contracts, cid)
    return response.object_response(public(rec))


@app.route("/commodities/contracts", methods=["GET"])
def list_contracts():
    require_roles({"Merchandiser", "SettlementOfficer"})
    member_id = request.args.get("member_id")
    commodity_id = request.args.get("commodity_id")
    records = list(store.contracts.values())
    if member_id is not None:
        records = [r for r in records if r["member_id"] == member_id]
    if commodity_id is not None:
        records = [r for r in records if r["commodity_id"] == commodity_id]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/commodities/contracts/<cid>/fix-price", methods=["POST"])
def fix_price(cid):
    require_roles({"Merchandiser"})
    with store.lock:
        contract = must_get(store.contracts, cid)
        if contract["status"] != "OPEN":
            raise errors.invalid_state("Only an OPEN contract can be fixed.")
        ctype = contract["contract_type"]

        # Leg-already-fixed check (priority 7) before no-current-price (priority 8)
        if ctype == "BASIS":
            if contract["futures_leg"] is not None:
                raise errors.leg_already_fixed("Futures leg already fixed.")
        elif ctype == "HTA":
            if contract["basis_leg"] is not None:
                raise errors.leg_already_fixed("Basis leg already fixed.")
        elif ctype == "CASH":
            if contract["futures_leg"] is not None or contract["basis_leg"] is not None:
                raise errors.leg_already_fixed("A leg is already fixed.")
        else:  # FORWARD does not pass through fix-price
            raise errors.leg_already_fixed("FORWARD contracts do not go through fix-price.")

        board = current_price_board(contract["commodity_id"])
        if board is None:
            raise errors.no_current_price()

        if ctype == "BASIS":
            contract["futures_leg"] = board["futures_price"]
        elif ctype == "HTA":
            contract["basis_leg"] = board["cash_basis"]
        elif ctype == "CASH":
            contract["futures_leg"] = board["futures_price"]
            contract["basis_leg"] = board["cash_basis"]

        contract["net_price"] = calc.net_price(contract["futures_leg"], contract["basis_leg"])
        contract["status"] = "PRICED"
        touch(contract)
    return response.object_response(public(contract))


@app.route("/commodities/contracts/<cid>/cancel", methods=["POST"])
def cancel_contract(cid):
    require_roles({"Merchandiser"})
    with store.lock:
        contract = must_get(store.contracts, cid)
        if contract["status"] not in ("OPEN", "PRICED"):
            raise errors.invalid_state("Only OPEN or PRICED contracts can be cancelled.")
        if contract["priced_bushels"] != 0:
            raise errors.contract_has_settlements()
        contract["status"] = "CANCELLED"
        touch(contract)
    return response.object_response(public(contract))


# ===========================================================================
# Settlement
# ===========================================================================
STORAGE_BASIS = {"ESTIMATE", "ACTUAL"}


def settlement_view(rec):
    """Settlement view. Per PRD §1 storage accruals (and the proceeds the GET
    endpoint surfaces) are 'recomputed on demand from the latest posted board and
    the server's logical clock rather than stored statically'. For a DRAFT
    settlement, the computed proceeds and storage charge are derived live from the
    current contract net price, position, storage basis, and logical clock. Once a
    settlement is SETTLED the figures are frozen at post time and read as stored."""
    out = public(rec)
    if rec["status"] == "DRAFT":
        contract = store.contracts.get(rec["contract_id"])
        position = store.storage_positions.get(rec["storage_position_id"])
        if (contract is not None and position is not None
                and contract.get("net_price") is not None):
            priced_bushels = rec["priced_bushels"]
            gross = round2(D(priced_bushels) * D(contract["net_price"]))
            charge = calc.storage_charge(position, priced_bushels,
                                         rec["storage_basis"], store.clock)
            out["gross_proceeds_dollars"] = gross
            out["storage_charge_dollars"] = charge
            out["net_proceeds_dollars"] = round2(D(gross) - D(charge))
    return out


@app.route("/commodities/settlements", methods=["POST"])
def create_settlement():
    require_roles({"SettlementOfficer"})
    body = get_body()
    with store.lock:
        contract_id, _ = require_fk(body, "contract_id", store.contracts)
        storage_position_id, _ = require_fk(body, "storage_position_id", store.storage_positions)
        priced_bushels = require_number(body, "priced_bushels", non_negative=True)
        storage_basis = optional_enum(body, "storage_basis", STORAGE_BASIS, default="ACTUAL")
        rec = {
            "contract_id": contract_id,
            "storage_position_id": storage_position_id,
            "priced_bushels": priced_bushels,
            "storage_basis": storage_basis,
            "gross_proceeds_dollars": None,
            "storage_charge_dollars": None,
            "net_proceeds_dollars": None,
            "status": "DRAFT",
        }
        stamp_create(rec)
        store.settlements[rec["id"]] = rec
    return response.object_response(settlement_view(rec), 201)


@app.route("/commodities/settlements/<sid>", methods=["GET"])
def get_settlement(sid):
    require_roles({"Merchandiser", "SettlementOfficer"})
    rec = must_get(store.settlements, sid)
    return response.object_response(settlement_view(rec))


@app.route("/commodities/settlements", methods=["GET"])
def list_settlements():
    require_roles({"Merchandiser", "SettlementOfficer"})
    contract_id = request.args.get("contract_id")
    storage_position_id = request.args.get("storage_position_id")
    records = list(store.settlements.values())
    if contract_id is not None:
        records = [r for r in records if r["contract_id"] == contract_id]
    if storage_position_id is not None:
        records = [r for r in records if r["storage_position_id"] == storage_position_id]
    window, limit, offset, total = paginate(records)
    return response.array_response([settlement_view(r) for r in window], limit, offset, total)


@app.route("/commodities/settlements/<sid>/post", methods=["POST"])
def post_settlement(sid):
    require_roles({"SettlementOfficer"})
    body = get_body()
    if "expected_storage_position_version" not in body or body["expected_storage_position_version"] is None:
        raise errors.invalid_request("Missing required field 'expected_storage_position_version'.")
    expected_version = body["expected_storage_position_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise errors.invalid_request("Field 'expected_storage_position_version' must be an integer.")

    with store.lock:
        settlement = must_get(store.settlements, sid)
        # State gate (priority 5)
        if settlement["status"] != "DRAFT":
            raise errors.invalid_state("Only a DRAFT settlement can be posted.")

        contract = store.contracts[settlement["contract_id"]]
        position = store.storage_positions[settlement["storage_position_id"]]

        # priority 6: commodity/member coherence
        if (contract["commodity_id"] != position["commodity_id"] or
                contract["member_id"] != position["member_id"]):
            raise errors.commodity_mismatch()

        # priority 9: contract priced (PRICED, or FORWARD with both legs fixed)
        contract_ready = (
            contract["status"] == "PRICED" or
            (contract["contract_type"] == "FORWARD" and contract["status"] == "OPEN"
             and contract["futures_leg"] is not None and contract["basis_leg"] is not None)
        )
        if not contract_ready:
            raise errors.contract_not_priced()

        # priority 10: contract overfill
        priced_bushels = settlement["priced_bushels"]
        remaining_room = D(contract["contracted_bushels"]) - D(contract["priced_bushels"])
        if D(priced_bushels) > remaining_room:
            raise errors.contract_overfill()

        # priority 11: insufficient bushels
        if D(priced_bushels) > D(position["bushels_available"]):
            raise errors.insufficient_bushels()

        # priority 18: OCC on storage position version
        if expected_version != position["version"]:
            raise errors.stale_version()

        # --- Compute proceeds ---
        gross = round2(D(priced_bushels) * D(contract["net_price"]))
        charge = calc.storage_charge(position, priced_bushels,
                                     settlement["storage_basis"], store.clock)
        net = round2(D(gross) - D(charge))
        settlement["gross_proceeds_dollars"] = gross
        settlement["storage_charge_dollars"] = charge
        settlement["net_proceeds_dollars"] = net

        # --- Cascade ---
        # Position drawdown + version bump (priced_bushels <= available guaranteed above)
        position["bushels_available"] = round4(D(position["bushels_available"]) - D(priced_bushels))
        if position["bushels_available"] == 0:
            position["status"] = "DEPLETED"
            _cancel_position_receipt(position)
        touch(position)

        # Contract fill
        contract["priced_bushels"] = round4(D(contract["priced_bushels"]) + D(priced_bushels))
        if D(contract["priced_bushels"]) >= D(contract["contracted_bushels"]):
            contract["status"] = "SETTLED"
        touch(contract)

        # Scale ticket -> SETTLED_IN if still GRADED
        ticket = store.scale_tickets.get(position["scale_ticket_id"])
        if ticket is not None and ticket["status"] == "GRADED":
            ticket["status"] = "SETTLED_IN"
            touch(ticket)

        # Member ledger
        member = store.members[contract["member_id"]]
        member["cash_paid_dollars"] = round2(D(member["cash_paid_dollars"]) + D(net))
        member["net_priced_bushels"] = round4(D(member["net_priced_bushels"]) + D(priced_bushels))
        touch(member)

        # Settlement finalize
        settlement["status"] = "SETTLED"
        touch(settlement)
    return response.object_response(public(settlement))


def _cancel_position_receipt(position):
    rid = position.get("receipt_id")
    if rid is not None:
        receipt = store.warehouse_receipts.get(rid)
        if receipt is not None and receipt["status"] == "ISSUED":
            receipt["status"] = "CANCELLED"
            touch(receipt)


@app.route("/commodities/settlements/<sid>/cancel", methods=["POST"])
def cancel_settlement(sid):
    require_roles({"SettlementOfficer"})
    with store.lock:
        settlement = must_get(store.settlements, sid)
        if settlement["status"] != "DRAFT":
            raise errors.invalid_state("Only a DRAFT settlement can be cancelled.")
        settlement["status"] = "CANCELLED"
        touch(settlement)
    return response.object_response(public(settlement))


# ===========================================================================
# LoadoutBay
# ===========================================================================
@app.route("/commodities/loadout-bays", methods=["POST"])
def create_loadout_bay():
    require_roles({"Merchandiser"})
    body = get_body()
    name = require_str(body, "name")
    with store.lock:
        rec = {"name": name}
        stamp_create(rec)
        store.loadout_bays[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/commodities/loadout-bays/<bid>", methods=["GET"])
def get_loadout_bay(bid):
    require_roles({"Merchandiser", "ShippingClerk"})
    rec = must_get(store.loadout_bays, bid)
    return response.object_response(public(rec))


@app.route("/commodities/loadout-bays", methods=["GET"])
def list_loadout_bays():
    require_roles({"Merchandiser", "ShippingClerk"})
    window, limit, offset, total = paginate(list(store.loadout_bays.values()))
    return response.array_response(public_list(window), limit, offset, total)


# ===========================================================================
# DryerLine
# ===========================================================================
@app.route("/commodities/dryer-lines", methods=["POST"])
def create_dryer_line():
    require_roles({"Merchandiser"})
    body = get_body()
    name = require_str(body, "name")
    buffer_min = body.get("cleanout_buffer_minutes")
    if buffer_min is None:
        buffer_min = 30
    else:
        buffer_min = require_int(body, "cleanout_buffer_minutes", non_negative=True)
    with store.lock:
        rec = {"name": name, "cleanout_buffer_minutes": buffer_min}
        stamp_create(rec)
        store.dryer_lines[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/commodities/dryer-lines/<lid>", methods=["GET"])
def get_dryer_line(lid):
    require_roles({"Merchandiser", "GradeClerk"})
    rec = must_get(store.dryer_lines, lid)
    return response.object_response(public(rec))


@app.route("/commodities/dryer-lines", methods=["GET"])
def list_dryer_lines():
    require_roles({"Merchandiser", "GradeClerk"})
    window, limit, offset, total = paginate(list(store.dryer_lines.values()))
    return response.array_response(public_list(window), limit, offset, total)


# ===========================================================================
# DryingReservation
# ===========================================================================
@app.route("/commodities/drying-reservations", methods=["POST"])
def create_drying_reservation():
    require_roles({"GradeClerk"})
    body = get_body()
    with store.lock:
        dryer_line_id, line = require_fk(body, "dryer_line_id", store.dryer_lines)
        scale_ticket_id, _ = require_fk(body, "scale_ticket_id", store.scale_tickets)
        window_start = parse_dt(body, "window_start")
        window_end = parse_dt(body, "window_end")

        buffer_min = line["cleanout_buffer_minutes"]
        for existing in store.drying_reservations.values():
            if existing["dryer_line_id"] != dryer_line_id:
                continue
            if existing["status"] != "RESERVED":
                continue
            if calc.dryer_conflict(window_start, window_end,
                                   existing["_window_start_dt"], existing["_window_end_dt"],
                                   buffer_min):
                raise errors.resource_window_conflict()

        rec = {
            "dryer_line_id": dryer_line_id,
            "scale_ticket_id": scale_ticket_id,
            "window_start": body["window_start"],
            "window_end": body["window_end"],
            "status": "RESERVED",
            "_window_start_dt": window_start,
            "_window_end_dt": window_end,
        }
        stamp_create(rec)
        store.drying_reservations[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/commodities/drying-reservations/<rid>", methods=["GET"])
def get_drying_reservation(rid):
    require_roles({"Merchandiser", "GradeClerk"})
    rec = must_get(store.drying_reservations, rid)
    return response.object_response(public(rec))


@app.route("/commodities/drying-reservations", methods=["GET"])
def list_drying_reservations():
    require_roles({"Merchandiser", "GradeClerk"})
    dryer_line_id = request.args.get("dryer_line_id")
    scale_ticket_id = request.args.get("scale_ticket_id")
    records = list(store.drying_reservations.values())
    if dryer_line_id is not None:
        records = [r for r in records if r["dryer_line_id"] == dryer_line_id]
    if scale_ticket_id is not None:
        records = [r for r in records if r["scale_ticket_id"] == scale_ticket_id]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/commodities/drying-reservations/<rid>/release", methods=["POST"])
def release_drying_reservation(rid):
    require_roles({"GradeClerk"})
    with store.lock:
        rec = must_get(store.drying_reservations, rid)
        if rec["status"] != "RESERVED":
            raise errors.invalid_state("Only a RESERVED reservation can be released.")
        rec["status"] = "RELEASED"
        touch(rec)
    return response.object_response(public(rec))


# ===========================================================================
# Shipment
# ===========================================================================
@app.route("/commodities/shipments", methods=["POST"])
def create_shipment():
    require_roles({"ShippingClerk"})
    body = get_body()
    with store.lock:
        commodity_id, _ = require_fk(body, "commodity_id", store.commodities)
        storage_position_id, _ = require_fk(body, "storage_position_id", store.storage_positions)
        loadout_bay_id, _ = require_fk(body, "loadout_bay_id", store.loadout_bays)
        bushels = require_number(body, "bushels", non_negative=True)
        bay_window_start = parse_dt(body, "bay_window_start")
        bay_window_end = parse_dt(body, "bay_window_end")

        for existing in store.shipments.values():
            if existing["loadout_bay_id"] != loadout_bay_id:
                continue
            if existing["status"] not in ("SCHEDULED", "LOADED", "SHIPPED"):
                continue
            if calc.bay_conflict(bay_window_start, bay_window_end,
                                 existing["_bay_window_start_dt"], existing["_bay_window_end_dt"]):
                raise errors.resource_window_conflict()

        rec = {
            "commodity_id": commodity_id,
            "storage_position_id": storage_position_id,
            "loadout_bay_id": loadout_bay_id,
            "bushels": bushels,
            "bay_window_start": body["bay_window_start"],
            "bay_window_end": body["bay_window_end"],
            "status": "SCHEDULED",
            "_bay_window_start_dt": bay_window_start,
            "_bay_window_end_dt": bay_window_end,
        }
        stamp_create(rec)
        store.shipments[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/commodities/shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    require_roles({"Merchandiser", "ShippingClerk"})
    rec = must_get(store.shipments, sid)
    return response.object_response(public(rec))


@app.route("/commodities/shipments", methods=["GET"])
def list_shipments():
    require_roles({"Merchandiser", "ShippingClerk"})
    commodity_id = request.args.get("commodity_id")
    storage_position_id = request.args.get("storage_position_id")
    loadout_bay_id = request.args.get("loadout_bay_id")
    records = list(store.shipments.values())
    if commodity_id is not None:
        records = [r for r in records if r["commodity_id"] == commodity_id]
    if storage_position_id is not None:
        records = [r for r in records if r["storage_position_id"] == storage_position_id]
    if loadout_bay_id is not None:
        records = [r for r in records if r["loadout_bay_id"] == loadout_bay_id]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/commodities/shipments/<sid>/load", methods=["POST"])
def load_shipment(sid):
    require_roles({"ShippingClerk"})
    with store.lock:
        shipment = must_get(store.shipments, sid)
        if shipment["status"] != "SCHEDULED":
            raise errors.invalid_state("Only a SCHEDULED shipment can be loaded.")
        position = store.storage_positions[shipment["storage_position_id"]]
        # PRD §3.7: bushels check then position-state check.
        if D(shipment["bushels"]) > D(position["bushels_available"]):
            raise errors.insufficient_bushels()
        if position["status"] not in ("STORED", "CHARGE_FROZEN"):
            raise errors.invalid_state("Position must be STORED or CHARGE_FROZEN to load from.")

        position["bushels_available"] = round4(D(position["bushels_available"]) - D(shipment["bushels"]))
        if position["bushels_available"] == 0:
            position["status"] = "DEPLETED"
            _cancel_position_receipt(position)
        touch(position)

        shipment["status"] = "LOADED"
        touch(shipment)
    return response.object_response(public(shipment))


@app.route("/commodities/shipments/<sid>/ship", methods=["POST"])
def ship_shipment(sid):
    require_roles({"ShippingClerk"})
    with store.lock:
        shipment = must_get(store.shipments, sid)
        if shipment["status"] != "LOADED":
            raise errors.invalid_state("Only a LOADED shipment can be shipped.")
        shipment["status"] = "SHIPPED"
        touch(shipment)
    return response.object_response(public(shipment))


@app.route("/commodities/shipments/<sid>/cancel", methods=["POST"])
def cancel_shipment(sid):
    require_roles({"ShippingClerk"})
    with store.lock:
        shipment = must_get(store.shipments, sid)
        if shipment["status"] != "SCHEDULED":
            raise errors.invalid_state("Only a SCHEDULED shipment can be cancelled.")
        shipment["status"] = "CANCELLED"
        touch(shipment)
    return response.object_response(public(shipment))


# ===========================================================================
# HedgePosition
# ===========================================================================
HEDGE_SIDES = {"SHORT", "LONG"}


@app.route("/commodities/hedge-positions", methods=["POST"])
def create_hedge_position():
    require_roles({"RiskManager"})
    body = get_body()
    with store.lock:
        commodity_id, _ = require_fk(body, "commodity_id", store.commodities)
        side = require_enum(body, "side", HEDGE_SIDES)
        contracts = require_int(body, "contracts", non_negative=True)
        entry_futures_price = require_number(body, "entry_futures_price")
        initial, _maintenance = calc.margin_totals(contracts)
        rec = {
            "commodity_id": commodity_id,
            "side": side,
            "contracts": contracts,
            "entry_futures_price": entry_futures_price,
            "mark_futures_price": None,
            "posted_margin_dollars": float(initial),
            "unrealized_pnl_dollars": 0,
            "account_equity_dollars": float(initial),
            "margin_call_dollars": 0,
            "status": "OPEN",
        }
        stamp_create(rec)
        store.hedge_positions[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/commodities/hedge-positions/<hid>", methods=["GET"])
def get_hedge_position(hid):
    require_roles({"Merchandiser", "RiskManager"})
    rec = must_get(store.hedge_positions, hid)
    return response.object_response(public(rec))


@app.route("/commodities/hedge-positions", methods=["GET"])
def list_hedge_positions():
    require_roles({"Merchandiser", "RiskManager"})
    commodity_id = request.args.get("commodity_id")
    records = list(store.hedge_positions.values())
    if commodity_id is not None:
        records = [r for r in records if r["commodity_id"] == commodity_id]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/commodities/hedge-positions/<hid>/mark", methods=["POST"])
def mark_hedge_position(hid):
    require_roles({"RiskManager"})
    body = get_body()
    mark_price = require_number(body, "mark_futures_price")
    with store.lock:
        pos = must_get(store.hedge_positions, hid)
        if pos["status"] != "OPEN":
            raise errors.invalid_state("Only an OPEN hedge position can be marked.")
        commodity = store.commodities[pos["commodity_id"]]
        contract_bu = commodity["futures_contract_bushels"]
        initial, maintenance = calc.margin_totals(pos["contracts"])

        pnl = calc.compute_pnl(pos["side"], pos["entry_futures_price"], mark_price,
                               contract_bu, pos["contracts"])
        equity = round2(D(pos["posted_margin_dollars"]) + D(pnl))

        pos["mark_futures_price"] = mark_price
        pos["unrealized_pnl_dollars"] = pnl
        pos["account_equity_dollars"] = equity

        # Strict <: equal does NOT trigger a call
        if D(equity) < maintenance:
            pos["margin_call_dollars"] = round2(initial - D(equity))
            pos["status"] = "MARGIN_CALL"
        else:
            pos["margin_call_dollars"] = 0
            # stays OPEN
        touch(pos)
    return response.object_response(public(pos))


@app.route("/commodities/hedge-positions/<hid>/meet-call", methods=["POST"])
def meet_call(hid):
    require_roles({"RiskManager"})
    body = get_body()
    deposit = require_number(body, "deposit_dollars", non_negative=True)
    if "expected_hedge_position_version" not in body or body["expected_hedge_position_version"] is None:
        raise errors.invalid_request("Missing required field 'expected_hedge_position_version'.")
    expected_version = body["expected_hedge_position_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise errors.invalid_request("Field 'expected_hedge_position_version' must be an integer.")

    with store.lock:
        pos = must_get(store.hedge_positions, hid)
        # state gate
        if pos["status"] != "MARGIN_CALL":
            raise errors.invalid_state("Position must be in MARGIN_CALL to meet a call.")
        # OCC guard (priority 18)
        if expected_version != pos["version"]:
            raise errors.stale_version()
        # deposit sufficiency (priority 13)
        if D(deposit) < D(pos["margin_call_dollars"]):
            raise errors.margin_call_unmet()

        pos["posted_margin_dollars"] = round2(D(pos["posted_margin_dollars"]) + D(deposit))
        pos["account_equity_dollars"] = round2(D(pos["posted_margin_dollars"]) + D(pos["unrealized_pnl_dollars"]))
        pos["margin_call_dollars"] = 0
        pos["status"] = "OPEN"
        touch(pos)
    return response.object_response(public(pos))


@app.route("/commodities/hedge-positions/<hid>/close", methods=["POST"])
def close_hedge_position(hid):
    require_roles({"RiskManager"})
    with store.lock:
        pos = must_get(store.hedge_positions, hid)
        if pos["status"] not in ("OPEN", "MARGIN_CALL"):
            raise errors.invalid_state("Only an OPEN or MARGIN_CALL position can be closed.")
        pos["status"] = "CLOSED"
        touch(pos)
    return response.object_response(public(pos))


# ===========================================================================
# PatronagePeriod
# ===========================================================================
@app.route("/commodities/patronage-periods", methods=["POST"])
def create_patronage_period():
    require_roles({"Merchandiser"})
    body = get_body()
    label = require_str(body, "label")
    pool = require_number(body, "pool_dollars", non_negative=True)
    cash_pct = require_number(body, "qualified_cash_pct", non_negative=True)
    with store.lock:
        rec = {
            "label": label,
            "pool_dollars": pool,
            "qualified_cash_pct": cash_pct,
            "status": "OPEN",
            "total_bushels": 0,
        }
        stamp_create(rec)
        store.patronage_periods[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@app.route("/commodities/patronage-periods/<pid>", methods=["GET"])
def get_patronage_period(pid):
    require_roles({"Merchandiser", "SettlementOfficer"})
    rec = must_get(store.patronage_periods, pid)
    return response.object_response(public(rec))


@app.route("/commodities/patronage-periods/<pid>/allocations", methods=["GET"])
def list_period_allocations(pid):
    require_roles({"Merchandiser", "SettlementOfficer"})
    must_get(store.patronage_periods, pid)
    records = [a for a in store.patronage_allocations.values() if a["patronage_period_id"] == pid]
    window, limit, offset, total = paginate(records)
    return response.array_response(public_list(window), limit, offset, total)


@app.route("/commodities/patronage-periods/<pid>/close", methods=["POST"])
def close_patronage_period(pid):
    require_roles({"Merchandiser"})
    with store.lock:
        period = must_get(store.patronage_periods, pid)
        if period["status"] != "OPEN":
            raise errors.invalid_state("Only an OPEN patronage period can be closed.")

        all_members = list(store.members.values())
        total_bushels = D(0)
        for m in all_members:
            total_bushels += D(m["net_priced_bushels"])
        if total_bushels <= 0:
            raise errors.empty_patronage_pool()

        period["total_bushels"] = float(total_bushels)

        # Eligible: net_priced_bushels > 0, ordered DESC by net_priced_bushels,
        # tie-break created_at ASC (id NEVER a tie-break).
        eligible = [m for m in all_members if D(m["net_priced_bushels"]) > 0]
        eligible.sort(key=lambda m: (-D(m["net_priced_bushels"]), m["created_at"], m["_seq"]))

        pool = D(period["pool_dollars"])
        cash_pct = D(period["qualified_cash_pct"])

        rows = []
        sum_allocation = D(0)
        sum_cash = D(0)
        for m in eligible:
            mb = D(m["net_priced_bushels"])
            allocation = D(str(round2(pool * mb / total_bushels)))
            cash_raw = allocation * cash_pct
            cash = D(str(floor2(cash_raw)))
            equity = D(str(round2(allocation - cash)))
            rows.append({"member": m, "member_bushels": float(mb),
                         "allocation": allocation, "cash": cash, "equity": equity})
            sum_allocation += allocation
            sum_cash += cash

        # cash_remainder = round(sum(allocation)*cash_pct, 2) - sum(cash)
        cash_remainder = D(str(round2(sum_allocation * cash_pct))) - sum_cash
        if rows:
            lead = rows[0]
            lead["cash"] = lead["cash"] + cash_remainder
            lead["equity"] = lead["equity"] - cash_remainder

        for row in rows:
            m = row["member"]
            alloc_rec = {
                "patronage_period_id": period["id"],
                "member_id": m["id"],
                "member_bushels": row["member_bushels"],
                "allocation_dollars": float(row["allocation"]),
                "cash_dollars": float(row["cash"]),
                "equity_dollars": float(row["equity"]),
            }
            stamp_create(alloc_rec, with_version=False)
            store.patronage_allocations[alloc_rec["id"]] = alloc_rec

            # Cascade member ledger
            m["equity_credit_dollars"] = round2(D(m["equity_credit_dollars"]) + row["equity"])
            m["cash_paid_dollars"] = round2(D(m["cash_paid_dollars"]) + row["cash"])
            touch(m)

        period["status"] = "CLOSED"
        touch(period)
    return response.object_response(public(period))


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
