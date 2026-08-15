"""Marker endpoints (PRD §3.5) — approve (fabric reservation + OCC), cut
(bundle creation), cancel (compensation)."""

from decimal import Decimal

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_CUTTING_MANAGER
from response import success_object
from util import (
    get_body, req_str, req_int, req_num, fk_exists, validate_size_quantities,
)
from errors import (
    invalid_request, invalid_state, stale_version, marker_not_draft,
    marker_not_approved, roll_not_available, insufficient_fabric,
    cut_exceeds_uncut,
)
from services.calc import marker_allocation, round_dec
from services.core import (
    base_record, touch, public, get_marker, get_production_order,
)
from routes.common import list_response, active_filters

bp = Blueprint("markers", __name__)


@bp.route("/markers", methods=["POST"])
def create_marker():
    require_roles([ROLE_CUTTING_MANAGER])
    body = get_body()
    fk_exists(body, "production_order_id", store.production_orders,
              "ProductionOrder")
    fk_exists(body, "fabric_roll_id", store.fabric_rolls, "FabricRoll")
    production_order_id = req_str(body, "production_order_id")
    fabric_roll_id = req_str(body, "fabric_roll_id")
    marker_length_yards = req_num(body, "marker_length_yards", gt=0)
    planned_pieces = req_int(body, "planned_pieces", min_v=1)

    rec = base_record()
    rec.update({
        "production_order_id": production_order_id,
        "fabric_roll_id": fabric_roll_id,
        "marker_length_yards": round_dec(marker_length_yards, 2),
        "planned_pieces": planned_pieces,
        "allocated_yards": Decimal("0"),
        "utilization_gross_pct": None,
        "utilization_net_pct": None,
        "status": "DRAFT",
    })
    store.markers[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/markers", methods=["GET"])
def list_markers():
    require_roles(ALL_ROLES)
    filters = active_filters([
        ("production_order_id", request.args.get("production_order_id")),
        ("fabric_roll_id", request.args.get("fabric_roll_id")),
    ])
    return list_response(store.markers.values(), filters)


@bp.route("/markers/<marker_id>", methods=["GET"])
def get_marker_endpoint(marker_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_marker(marker_id)))


@bp.route("/markers/<marker_id>/approve", methods=["POST"])
def approve_marker(marker_id):
    require_roles([ROLE_CUTTING_MANAGER])
    marker = get_marker(marker_id)
    body = get_body()
    expected = req_int(body, "expected_fabric_roll_version")
    roll = store.fabric_rolls[marker["fabric_roll_id"]]
    # OCC on FabricRoll.version — checked before state (PRD §2.7).
    if expected != roll["version"]:
        raise stale_version(
            f"expected_fabric_roll_version {expected} does not match current "
            f"roll version {roll['version']}")
    # Marker from-state before any business rule (PRD §3.5).
    if marker["status"] != "DRAFT":
        raise marker_not_draft("marker must be DRAFT to approve")
    if roll["status"] != "AVAILABLE":
        raise roll_not_available("referenced fabric roll is not AVAILABLE")
    allocated, gross, net = marker_allocation(marker["marker_length_yards"])
    # Yardage test is checked last; equality is permitted (PRD §3.5).
    if roll["available_yards"] < allocated:
        raise insufficient_fabric(
            "roll available_yards is below the computed allocated_yards")

    marker["allocated_yards"] = allocated
    marker["utilization_gross_pct"] = gross
    marker["utilization_net_pct"] = net
    marker["status"] = "APPROVED"
    touch(marker)
    roll["allocated_yards"] += allocated
    roll["available_yards"] = (
        roll["usable_yards"] - roll["allocated_yards"] - roll["consumed_yards"])
    touch(roll)
    return success_object(public(marker))


@bp.route("/markers/<marker_id>/cut", methods=["POST"])
def cut_marker(marker_id):
    require_roles([ROLE_CUTTING_MANAGER])
    marker = get_marker(marker_id)
    body = get_body()
    lines = validate_size_quantities(body)
    if marker["status"] != "APPROVED":
        raise marker_not_approved("marker must be APPROVED to cut")
    order = get_production_order(marker["production_order_id"])
    if order["production_status"] != "CUTTING":
        raise invalid_state(
            "the marker's production order must be CUTTING to cut")
    # Per-size cumulative cut must not exceed ordered qty (PRD §3.5).
    ordered = {l["size"]: l["qty"] for l in order["size_quantities"]}
    already_cut = {}
    for b in store.bundles.values():
        if b["production_order_id"] == order["id"]:
            already_cut[b["size"]] = already_cut.get(b["size"], 0) + b["qty"]
    for line in lines:
        allowed = ordered.get(line["size"], 0)
        if already_cut.get(line["size"], 0) + line["qty"] > allowed:
            raise cut_exceeds_uncut(
                f"cut exceeds the remaining uncut quantity for size "
                f"{line['size']!r}")
    if sum(l["qty"] for l in lines) != marker["planned_pieces"]:
        raise invalid_request(
            "cut quantities must sum exactly to the marker's planned_pieces")

    # Convert the reservation into consumption (PRD §2.9 ledger).
    roll = store.fabric_rolls[marker["fabric_roll_id"]]
    reservation = marker["allocated_yards"]
    roll["allocated_yards"] -= reservation
    roll["consumed_yards"] += reservation
    roll["available_yards"] = (
        roll["usable_yards"] - roll["allocated_yards"] - roll["consumed_yards"])
    touch(roll)
    if roll["available_yards"] == 0 and roll["status"] == "AVAILABLE":
        roll["status"] = "DEPLETED"
        touch(roll)  # depletion increments the roll's version a second time
    marker["allocated_yards"] = Decimal("0")
    marker["status"] = "CUT"
    touch(marker)

    # One TICKETED bundle per size line, in supplied order.
    for n, line in enumerate(lines, start=1):
        b = base_record()
        b.update({
            "marker_id": marker["id"],
            "production_order_id": order["id"],
            "size": line["size"],
            "qty": line["qty"],
            "ticket_no": f"{order['_order_seq']}-{line['size']}-{n}",
            "status": "TICKETED",
            "pre_rework_status": None,
            "completed_through_seq": 0,
        })
        store.bundles[b["id"]] = b
    return success_object(public(marker))


@bp.route("/markers/<marker_id>/cancel", methods=["POST"])
def cancel_marker(marker_id):
    require_roles([ROLE_CUTTING_MANAGER])
    get_body()
    marker = get_marker(marker_id)
    if marker["status"] not in ("DRAFT", "APPROVED"):
        raise invalid_state("only a DRAFT or APPROVED marker can be cancelled")
    if marker["status"] == "APPROVED":
        # Compensation: return the reservation to the roll (PRD §3.5).
        roll = store.fabric_rolls[marker["fabric_roll_id"]]
        roll["allocated_yards"] -= marker["allocated_yards"]
        roll["available_yards"] = (
            roll["usable_yards"] - roll["allocated_yards"]
            - roll["consumed_yards"])
        touch(roll)
        marker["allocated_yards"] = Decimal("0")
    marker["status"] = "CANCELLED"
    touch(marker)
    return success_object(public(marker))
