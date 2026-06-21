"""AgencyOrder + OrderLine endpoints: submit, fetch, lines, approve (FEFO+OCC),
reject, recall, cancel."""
from flask import Blueprint, request

from db import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_AGENCY_SUSPENDED,
    ERR_CYCLE_NOT_OPEN,
    ERR_AGENCY_SCOPE_VIOLATION,
    ERR_FAIR_SHARE_EXCEEDED,
    ERR_STALE_LOT_VERSION,
)
from middleware import get_identity, require_role
from response import object_response, array_response
from services import models
from services.calc import round2, fair_share_cap_lbs
from services.reservation import (
    run_fefo_reservation,
    release_reservations,
    fefo_earliest_lot,
)
from services.validate import (
    get_json_body,
    parse_pagination,
    paginate,
    require_int,
    require_number,
    require_enum,
)
from routes.lookups import get_agency, get_cycle, get_order

bp = Blueprint("orders", __name__)

READ_ROLES_ALL = {"FoodBankOperator", "AllocationManager", "ComplianceAuditor", "AgencyCoordinator"}


def _has_packed_or_finalized_event(order_id):
    for e in db.distribution_events.values():
        if e["agency_order_id"] == order_id and e["status"] in ("PACKED", "FINALIZED"):
            return True
    return False


def _already_drawn(agency_id, cycle_id):
    """Sum approved_lbs over the agency's orders in this cycle whose status is
    APPROVED or FULFILLED (PRD §3.4)."""
    total = 0.0
    for o in db.agency_orders.values():
        if (
            o["agency_id"] == agency_id
            and o["allocation_cycle_id"] == cycle_id
            and o["status"] in ("APPROVED", "FULFILLED")
        ):
            total += o["approved_lbs"]
    return total


@bp.post("/agency-orders")
def submit_order():
    user_id, role = get_identity()
    require_role(role, {"AgencyCoordinator"})
    body = get_json_body()

    # existence (priority 4) — FKs validated left to right.
    if "agency_id" not in body or not isinstance(body.get("agency_id"), str):
        raise err(ERR_INVALID_REQUEST, "Missing or invalid agency_id.")
    agency = get_agency(body["agency_id"])
    if "allocation_cycle_id" not in body or not isinstance(
        body.get("allocation_cycle_id"), str
    ):
        raise err(ERR_INVALID_REQUEST, "Missing or invalid allocation_cycle_id.")
    cycle = get_cycle(body["allocation_cycle_id"])

    # agency-scope ownership (priority 3): coordinator must own the agency.
    if agency["id"] != user_id:
        raise err(ERR_AGENCY_SCOPE_VIOLATION, "Order agency is not the caller's agency.")

    # request well-formedness (priority 5): lines array.
    lines = body.get("lines")
    if lines is None or not isinstance(lines, list) or len(lines) == 0:
        raise err(ERR_INVALID_REQUEST, "lines must be a non-empty array.")
    parsed_lines = []
    for entry in lines:
        if not isinstance(entry, dict):
            raise err(ERR_INVALID_REQUEST, "Each line must be an object.")
        fc = require_enum(entry, "food_category", models.FOOD_CATEGORIES)
        rl = require_number(entry, "requested_lbs", positive=True)
        parsed_lines.append((fc, round2(rl)))

    # agency standing (priority 9) then cycle openness (priority 10).
    if agency["status"] == "SUSPENDED":
        raise err(ERR_AGENCY_SUSPENDED, "Ordering agency is suspended.")
    if cycle["status"] != "OPEN":
        raise err(ERR_CYCLE_NOT_OPEN, "Allocation cycle is not OPEN.")

    order = models._common_create()
    order.update(
        {
            "agency_id": agency["id"],
            "allocation_cycle_id": cycle["id"],
            "requested_lbs": 0,
            "approved_lbs": 0,
            "status": "SUBMITTED",
        }
    )
    db.agency_orders[order["id"]] = order
    for fc, rl in parsed_lines:
        line = models._common_create()
        line.update(
            {
                "agency_order_id": order["id"],
                "food_category": fc,
                "requested_lbs": rl,
                "reserved_lbs": 0,
                "reserved_lot_id": None,
                "line_status": "PENDING",
            }
        )
        db.order_lines[line["id"]] = line
    models.recompute_order_requested(order)
    return object_response(models.serialize_order(order), status=201)


@bp.get("/agency-orders/<order_id>")
def fetch_order(order_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES_ALL)
    order = get_order(order_id)
    return object_response(models.serialize_order(order))


@bp.get("/agency-orders/<order_id>/order-lines")
def order_lines(order_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES_ALL)
    order = get_order(order_id)
    limit, offset = parse_pagination()
    line_status = request.args.get("line_status")
    lines = models.order_lines_of(order["id"])
    if line_status is not None:
        lines = [l for l in lines if l["line_status"] == line_status]
    page, total = paginate(lines, limit, offset)
    return array_response([models.serialize_line(l) for l in page], limit, offset, total)


@bp.post("/agency-orders/<order_id>/approve")
def approve_order(order_id):
    user_id, role = get_identity()
    require_role(role, {"AllocationManager"})
    order = get_order(order_id)
    body = get_json_body()
    expected = require_int(body, "expected_lot_version")

    # state legality (priority 6)
    if order["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Order is not SUBMITTED.")

    agency = db.agencies[order["agency_id"]]
    cycle = db.allocation_cycles[order["allocation_cycle_id"]]

    # agency standing (priority 9)
    if agency["status"] == "SUSPENDED":
        raise err(ERR_AGENCY_SUSPENDED, "Ordering agency is suspended.")
    # cycle openness (priority 10)
    if cycle["status"] != "OPEN":
        raise err(ERR_CYCLE_NOT_OPEN, "Allocation cycle is not OPEN.")

    # fair-share cap (priority 13)
    cap = fair_share_cap_lbs(
        cycle["total_pool_lbs"], agency["fair_share_weight"], cycle["total_fair_share_weight"]
    )
    drawn = _already_drawn(agency["id"], cycle["id"])
    remaining_cap = cap - drawn
    if order["requested_lbs"] > remaining_cap:
        raise err(ERR_FAIR_SHARE_EXCEEDED, "Order exceeds remaining fair-share cap.")

    # OCC on FEFO-earliest lot (priority 14). Pin the lot the manager observed.
    earliest = fefo_earliest_lot(order)
    if earliest is not None:
        if expected != earliest["version"]:
            raise err(ERR_STALE_LOT_VERSION, "Stale inventory lot version.")

    # FEFO reservation cascade.
    approved = run_fefo_reservation(order)
    order["approved_lbs"] = round2(approved)
    order["status"] = "APPROVED"
    models.touch(order)
    return object_response(models.serialize_order(order))


@bp.post("/agency-orders/<order_id>/reject")
def reject_order(order_id):
    user_id, role = get_identity()
    require_role(role, {"AllocationManager"})
    order = get_order(order_id)
    if order["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Order is not SUBMITTED.")
    order["status"] = "REJECTED"
    models.touch(order)
    return object_response(models.serialize_order(order))


@bp.post("/agency-orders/<order_id>/recall")
def recall_order(order_id):
    user_id, role = get_identity()
    require_role(role, {"AllocationManager"})
    order = get_order(order_id)
    if order["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "Order is not APPROVED.")
    if _has_packed_or_finalized_event(order["id"]):
        raise err(ERR_INVALID_STATE, "Order has a PACKED or FINALIZED event.")
    release_reservations(order)
    order["approved_lbs"] = 0
    order["status"] = "SUBMITTED"
    models.touch(order)
    return object_response(models.serialize_order(order))


@bp.post("/agency-orders/<order_id>/cancel")
def cancel_order(order_id):
    user_id, role = get_identity()
    require_role(role, {"AgencyCoordinator"})
    order = get_order(order_id)
    # scope ownership (priority 3)
    if order["agency_id"] != user_id:
        raise err(ERR_AGENCY_SCOPE_VIOLATION, "Order is not the caller's agency's.")
    if order["status"] not in ("SUBMITTED", "APPROVED"):
        raise err(ERR_INVALID_STATE, "Order is not SUBMITTED or APPROVED.")
    if order["status"] == "APPROVED":
        if _has_packed_or_finalized_event(order["id"]):
            raise err(ERR_INVALID_STATE, "Order has a PACKED or FINALIZED event.")
        release_reservations(order)
    order["status"] = "CANCELLED"
    models.touch(order)
    return object_response(models.serialize_order(order))
