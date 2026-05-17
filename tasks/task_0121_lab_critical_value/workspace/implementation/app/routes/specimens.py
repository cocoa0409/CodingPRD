"""Specimen read endpoints + transport-leg create/list under specimen."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_LAB_DIRECTOR, ROLE_LAB_TECH, ROLE_ORDERING_PROVIDER, require_roles
from ..clock import now
from ..errors import (
    err_invalid_state,
    err_time_order_invalid,
    err_transport_chain_broken,
    err_validation,
)
from ..helpers import (
    assert_string,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing, ok
from ..services.lookups import get_lab_order, get_specimen
from ..services.serialize import specimen_view, transport_leg_view
from ..services.workflows import bump, create_common_fields
from ..store import store

bp = Blueprint("specimens", __name__)


@bp.route("/specimens/<sid>", methods=["GET"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_TECH, ROLE_LAB_DIRECTOR)
def fetch_specimen(sid, **_):
    row = get_specimen(sid)
    return ok(specimen_view(row))


@bp.route("/specimens/<sid>/transport-legs", methods=["POST"])
@require_roles(ROLE_LAB_TECH)
def create_transport_leg(sid, **_):
    body = require_json_object()
    from_loc = assert_string(body.get("from_location"), "from_location")
    to_loc = assert_string(body.get("to_location"), "to_location")
    departed_at = parse_iso8601(body.get("departed_at"), "departed_at")
    courier = assert_string(body.get("courier_id"), "courier_id")

    with store().lock:
        specimen = get_specimen(sid)
        # State (priority 5): only COLLECTED (for first leg) or IN_TRANSIT (subsequent) allowed
        if specimen["status"] not in ("COLLECTED", "IN_TRANSIT"):
            raise err_invalid_state(
                f"Specimen must be COLLECTED or IN_TRANSIT to add a leg (was {specimen['status']})"
            )

        existing_legs = sorted(
            (l for l in store().transport_legs.values() if l["specimen_id"] == sid),
            key=lambda l: l["leg_index"],
        )

        # Time order (priority 11)
        if existing_legs:
            prev = existing_legs[-1]
            # Chain monotonicity (priority 12): previous must be ARRIVED, from_location must match
            if prev["status"] != "ARRIVED":
                raise err_transport_chain_broken("previous leg is not ARRIVED")
            if from_loc != prev["to_location"]:
                raise err_transport_chain_broken("from_location does not match previous to_location")
            # departed_at >= max(prev.arrived_at? — spec says >= specimen.collected_at; we enforce that, but also implicit)
            if departed_at < specimen["collected_at"]:
                raise err_time_order_invalid("departed_at must be >= collected_at")
        else:
            # First leg: departed_at >= specimen.collected_at
            if departed_at < specimen["collected_at"]:
                raise err_time_order_invalid("first leg departed_at must be >= collected_at")

        leg_index = (existing_legs[-1]["leg_index"] + 1) if existing_legs else 1

        leg = {
            "id": create_common_fields()["id"],  # but we want only id + created_at
        }
        # TransportLeg is immutable in OCC sense — store only id + created_at
        leg = {
            "id": leg["id"],
            "created_at": now(),
            "specimen_id": sid,
            "leg_index": leg_index,
            "from_location": from_loc,
            "to_location": to_loc,
            "departed_at": departed_at,
            "arrived_at": None,
            "courier_id": courier,
            "status": "DEPARTED",
        }
        store().transport_legs[leg["id"]] = leg

        # First leg cascade: Specimen COLLECTED -> IN_TRANSIT; Order COLLECTED -> IN_TRANSIT
        if leg_index == 1:
            specimen["status"] = "IN_TRANSIT"
            bump(specimen)
            order = get_lab_order(specimen["lab_order_id"])
            if order["status"] == "COLLECTED":
                order["status"] = "IN_TRANSIT"
                bump(order)
    return created(transport_leg_view(leg))


@bp.route("/specimens/<sid>/transport-legs", methods=["GET"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_TECH, ROLE_LAB_DIRECTOR)
def list_transport_legs(sid, **_):
    limit, offset = parse_pagination()
    get_specimen(sid)  # existence check
    items = sorted(
        (l for l in store().transport_legs.values() if l["specimen_id"] == sid),
        key=lambda l: l["leg_index"],
    )
    total = len(items)
    page = paginate(items, limit, offset)
    return listing([transport_leg_view(l) for l in page], total, limit, offset)
