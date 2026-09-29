"""Change orders: negotiation, Cascade A and the compensating rescission.

PRD §3.8.
"""

from flask import Blueprint

import calc
import find
import services
import validate
from db import db, new_row, touch
from errors import ApiError
from middleware import (
    ALL_ROLES,
    COMMITTEE_REP,
    PURCHASING_OFFICER,
    acting_user_id,
    authorize,
    committee_scope_for_change_order,
    committee_scope_for_unit,
)
from response import created, listing, ok

bp = Blueprint("changes", __name__)


def _require_amendable(unit):
    """Rung 13 — guards all six change-order operations."""
    if unit is None or unit["build_status"] in services.AMENDABLE_EXCLUDED_BUILD_STATUSES:
        raise ApiError("ERR_UNIT_NOT_AMENDABLE")


def _require_markup_cap(items):
    """Rung 47 — the contractual markup cap, checked over every supplied line."""
    for item in items:
        if calc.dec(item["markup_pct"]) > calc.MARKUP_CAP_PCT:
            raise ApiError("ERR_MARKUP_CAP_EXCEEDED")


def _unit_of(change_order):
    return db.unit_orders.get(change_order["unit_order_id"])


@bp.post("/change-orders")
@authorize(COMMITTEE_REP)
def raise_change_order():
    data = validate.body()
    unit_order_id = validate.req_ref(data, "unit_order_id")
    inspection_trip_id = validate.req_ref(data, "inspection_trip_id")
    items = validate.line_items(data)
    weight_delta_front_kg = validate.req_int(data, "weight_delta_front_kg", -2000, 2000)
    weight_delta_rear_kg = validate.req_int(data, "weight_delta_rear_kg", -2000, 2000)
    expected_unit_order_version = validate.req_int(
        data, "expected_unit_order_version", 0
    )

    unit = find.unit_order(unit_order_id)
    trip = find.inspection_trip(inspection_trip_id)

    committee_scope_for_unit(unit)

    # Rung 7 — the amendment must be priced against the baseline the committee
    # actually read, so a stale version is reported ahead of every lower rung.
    if expected_unit_order_version != int(unit["version"]):
        raise ApiError("ERR_STALE_UNIT_ORDER_VERSION")

    _require_amendable(unit)

    if trip["unit_order_id"] != unit["id"]:
        raise ApiError("ERR_TRIP_UNIT_MISMATCH")

    _require_markup_cap(items)

    row = new_row(
        {
            "unit_order_id": unit["id"],
            "inspection_trip_id": trip["id"],
            "line_items": items,
            "weight_delta_front_kg": weight_delta_front_kg,
            "weight_delta_rear_kg": weight_delta_rear_kg,
            "price_delta_cents": calc.change_order_price_delta(items),
            "revision_count": 0,
            "raised_by_user_id": acting_user_id(),
            "approved_by_user_id": None,
            "status": "DRAFT",
            "applied_at": None,
        }
    )
    db.change_orders[row["id"]] = row

    unit["open_change_order_count"] = calc.unit_open_change_order_count(unit["id"])
    touch(unit)

    return created(row)


@bp.get("/change-orders")
@authorize(*ALL_ROLES)
def list_change_orders():
    limit, offset = validate.pagination()
    unit_order_id = validate.query_filter("unit_order_id")
    inspection_trip_id = validate.query_filter("inspection_trip_id")
    status = validate.query_filter("status")
    rows = list(db.change_orders.values())
    if unit_order_id is not None:
        rows = [r for r in rows if r["unit_order_id"] == unit_order_id]
    if inspection_trip_id is not None:
        rows = [r for r in rows if r["inspection_trip_id"] == inspection_trip_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows, limit, offset)


@bp.get("/change-orders/<change_order_id>")
@authorize(*ALL_ROLES)
def read_change_order(change_order_id):
    return ok(find.change_order(change_order_id))


@bp.post("/change-orders/<change_order_id>/submit")
@authorize(COMMITTEE_REP)
def submit_change_order(change_order_id):
    change_order = find.change_order(change_order_id)
    committee_scope_for_change_order(change_order)
    _require_amendable(_unit_of(change_order))
    if change_order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CHANGE_ORDER_STATE")

    trip = db.trips.get(change_order["inspection_trip_id"])
    if trip is None or trip["status"] != "HELD":
        raise ApiError("ERR_INSPECTION_TRIP_NOT_HELD")

    change_order["status"] = "SUBMITTED"
    touch(change_order)
    return ok(change_order)


@bp.post("/change-orders/<change_order_id>/negotiate")
@authorize(PURCHASING_OFFICER)
def negotiate_change_order(change_order_id):
    change_order = find.change_order(change_order_id)
    _require_amendable(_unit_of(change_order))
    if change_order["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CHANGE_ORDER_STATE")
    change_order["status"] = "IN_NEGOTIATION"
    touch(change_order)
    return ok(change_order)


@bp.post("/change-orders/<change_order_id>/revise")
@authorize(COMMITTEE_REP)
def revise_change_order(change_order_id):
    data = validate.body()
    items = validate.line_items(data)
    weight_delta_front_kg = validate.req_int(data, "weight_delta_front_kg", -2000, 2000)
    weight_delta_rear_kg = validate.req_int(data, "weight_delta_rear_kg", -2000, 2000)

    change_order = find.change_order(change_order_id)
    committee_scope_for_change_order(change_order)
    _require_amendable(_unit_of(change_order))
    if change_order["status"] != "IN_NEGOTIATION":
        raise ApiError("ERR_INVALID_CHANGE_ORDER_STATE")
    _require_markup_cap(items)

    # The fresh array wholly replaces the previous one; the delta is repriced
    # from scratch rather than adjusted.
    change_order["line_items"] = items
    change_order["weight_delta_front_kg"] = weight_delta_front_kg
    change_order["weight_delta_rear_kg"] = weight_delta_rear_kg
    change_order["price_delta_cents"] = calc.change_order_price_delta(items)
    change_order["revision_count"] = int(change_order["revision_count"]) + 1
    change_order["status"] = "SUBMITTED"
    touch(change_order)
    return ok(change_order)


@bp.post("/change-orders/<change_order_id>/approve")
@authorize(PURCHASING_OFFICER)
def approve_change_order(change_order_id):
    change_order = find.change_order(change_order_id)
    unit = _unit_of(change_order)
    _require_amendable(unit)
    if change_order["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CHANGE_ORDER_STATE")

    program = db.programs.get(unit["program_id"])

    # Rung 52 — the resulting committed figure is priced before anything is
    # written, because a hard-ceiling breach must persist nothing at all.
    if program is not None:
        prospective_unit_total = (
            int(unit["price_cents"])
            + calc.unit_change_order_total(unit["id"])
            + int(change_order["price_delta_cents"])
        )
        prospective = calc.program_committed_cents(
            program["id"], overrides={unit["id"]: prospective_unit_total}
        )
        if prospective > int(program["contract_ceiling_cents"]):
            raise ApiError("ERR_CONTRACT_CEILING_EXCEEDED")

    change_order["status"] = "APPROVED"
    change_order["approved_by_user_id"] = acting_user_id()
    change_order["applied_at"] = services.clock_raw()
    touch(change_order)

    services.apply_change_order_cascade(change_order, unit, program)
    return ok(change_order)


@bp.post("/change-orders/<change_order_id>/reject")
@authorize(PURCHASING_OFFICER)
def reject_change_order(change_order_id):
    change_order = find.change_order(change_order_id)
    unit = _unit_of(change_order)
    _require_amendable(unit)
    if change_order["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CHANGE_ORDER_STATE")

    change_order["status"] = "REJECTED"
    touch(change_order)

    # A rejected change order never entered the unit's total, so the only effect
    # on the unit is that its open-amendment count drops by one.
    unit["open_change_order_count"] = calc.unit_open_change_order_count(unit["id"])
    touch(unit)
    return ok(change_order)


@bp.post("/change-orders/<change_order_id>/rescind")
@authorize(PURCHASING_OFFICER)
def rescind_change_order(change_order_id):
    change_order = find.change_order(change_order_id)
    unit = _unit_of(change_order)
    _require_amendable(unit)
    if change_order["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_CHANGE_ORDER_STATE")

    program = db.programs.get(unit["program_id"])
    change_order["status"] = "RESCINDED"
    touch(change_order)
    services.reverse_change_order(change_order, unit, program)
    return ok(change_order)
