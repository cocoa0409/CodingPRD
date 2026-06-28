"""MillShipment routes (PRD §3.7): ship, settle + hedge realization cascade."""
from flask import Blueprint

import errors
import response
import serializers
from calc import line_valuation_cents, round_half_up
from db import db, stamp_create, touch
from helpers import (as_int, as_string, get_json_body, parse_pagination,
                     paginate, query_arg, require_fields)
from middleware import authenticate, require_roles

bp = Blueprint("mill_shipments", __name__)

SHIPMENT_STATUSES = {"SHIPPED", "SETTLED"}
READ_ROLES = {"YardManager", "SettlementAccountant", "ComplianceOfficer"}


def _container_tickets(container_id):
    """ScaleTickets assigned to a container whose status is RELEASED or PAID."""
    return [t for t in db.tickets.values()
            if t.get("container_id") == container_id
            and t["status"] in ("RELEASED", "PAID")]


def _expected_settlement(container_id):
    """Forward-looking sell-side estimate, per-line round then accumulate."""
    total = 0
    for t in _container_tickets(container_id):
        for li in db.line_items.values():
            if li["ticket_id"] != t["id"]:
                continue
            price = db.commodity_prices.get(li["commodity_price_id"])
            if price is None:
                continue
            total += line_valuation_cents(li["weight_lb"], price["mill_price_cents_per_lb"])
    return total


@bp.route("/yard/mill-shipments", methods=["POST"])
def create_shipment():
    _uid, role = authenticate()
    require_roles(role, {"YardManager", "SettlementAccountant"})
    body = get_json_body()
    require_fields(body, ["container_id"])
    container_id = as_string(body["container_id"], "container_id")
    hedge_position_id = body.get("hedge_position_id")
    if hedge_position_id is not None and not isinstance(hedge_position_id, str):
        raise errors.invalid_request("hedge_position_id must be a string or null.")
    # Existence (priority 3): container, and hedge if provided.
    container = db.containers.get(container_id)
    if container is None:
        raise errors.not_found("Container not found.")
    if hedge_position_id is not None and hedge_position_id not in db.hedges:
        raise errors.not_found("Hedge position not found.")
    # State (priority 4): container must be DISPATCHED.
    if container["status"] != "DISPATCHED":
        raise errors.invalid_state("Container is not DISPATCHED.")
    # Unique shipment per container.
    for s in db.mill_shipments.values():
        if s["container_id"] == container_id:
            raise errors.invalid_state("Container already has a mill shipment.")

    record = {
        "container_id": container_id,
        "category": container["category"],
        "shipped_weight_lb": container["loaded_weight_lb"],
        "expected_settlement_cents": _expected_settlement(container_id),
        "final_settlement_cents": None,
        "settlement_variance_cents": None,
        "hedge_position_id": hedge_position_id,
        "status": "SHIPPED",
    }
    stamp_create(record)
    db.mill_shipments[record["id"]] = record
    # Consume the container -> CLOSED.
    container["status"] = "CLOSED"
    touch(container)
    return response.success(serializers.mill_shipment(record), 201)


@bp.route("/yard/mill-shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    authenticate()
    record = db.mill_shipments.get(sid)
    if not record:
        raise errors.not_found("Mill shipment not found.")
    return response.success(serializers.mill_shipment(record), 200)


@bp.route("/yard/mill-shipments", methods=["GET"])
def list_shipments():
    authenticate()
    limit, offset = parse_pagination()
    container_id = query_arg("container_id")
    hedge_position_id = query_arg("hedge_position_id")
    status = query_arg("status")
    if status is not None and status not in SHIPMENT_STATUSES:
        raise errors.invalid_request("status filter is invalid.")
    rows = list(db.mill_shipments.values())
    if container_id is not None:
        rows = [r for r in rows if r["container_id"] == container_id]
    if hedge_position_id is not None:
        rows = [r for r in rows if r.get("hedge_position_id") == hedge_position_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.success_list(
        [serializers.mill_shipment(r) for r in page], limit, offset, total)


@bp.route("/yard/mill-shipments/<sid>/settle", methods=["POST"])
def settle_shipment(sid):
    _uid, role = authenticate()
    require_roles(role, {"SettlementAccountant"})
    shipment = db.mill_shipments.get(sid)
    if not shipment:
        raise errors.not_found("Mill shipment not found.")
    # State (priority 4): only from SHIPPED.
    if shipment["status"] != "SHIPPED":
        raise errors.invalid_state("Mill shipment is not SHIPPED.")
    body = get_json_body()
    require_fields(body, ["final_settlement_cents"])
    final = as_int(body["final_settlement_cents"], "final_settlement_cents", minimum=0)

    hedge_id = shipment.get("hedge_position_id")
    hedge = None
    if hedge_id is not None:
        hedge = db.hedges.get(hedge_id)
        # Hedge still must exist (created with it; defensive).
        if hedge is None:
            raise errors.not_found("Hedge position not found.")
        # Linked-hedge settle must carry expected_hedge_version.
        if "expected_hedge_version" not in body or body["expected_hedge_version"] is None:
            raise errors.invalid_request("expected_hedge_version is required for a hedged settle.")
        expected_hedge_version = as_int(
            body["expected_hedge_version"], "expected_hedge_version")
        # Hedge must be OPEN and category match.
        if hedge["status"] != "OPEN":
            raise errors.invalid_state("Hedge position is not OPEN.")
        if hedge["category"] != shipment["category"]:
            raise errors.category_mismatch("Hedge category does not match shipment.")
        # Hedge over-realization (priority 11): shipped weight must fit remaining.
        remaining = hedge["hedged_weight_lb"] - hedge["realized_weight_lb"]
        if shipment["shipped_weight_lb"] > remaining:
            raise errors.hedge_over_realized()
        # OCC (priority 13): hedge version match.
        if expected_hedge_version != hedge["version"]:
            raise errors.stale_hedge_version()

    # Commit: compute variance.
    shipment["final_settlement_cents"] = final
    shipment["settlement_variance_cents"] = final - shipment["expected_settlement_cents"]
    shipment["status"] = "SETTLED"
    touch(shipment)

    # Hedge realization cascade.
    if hedge is not None:
        shipped = shipment["shipped_weight_lb"]
        effective_mill_price = round_half_up(final / shipped) if shipped else 0
        realize_lb = min(shipped, hedge["hedged_weight_lb"] - hedge["realized_weight_lb"])
        leg_pnl = round_half_up(
            realize_lb * (hedge["locked_price_cents_per_lb"] - effective_mill_price))
        hedge["realized_weight_lb"] += realize_lb
        hedge["realized_pnl_cents"] += leg_pnl
        if hedge["realized_weight_lb"] >= hedge["hedged_weight_lb"]:
            hedge["status"] = "CLOSED"
        touch(hedge)

    return response.success(serializers.mill_shipment(shipment), 200)
