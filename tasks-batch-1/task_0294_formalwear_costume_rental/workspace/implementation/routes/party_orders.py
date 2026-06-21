"""PartyOrder endpoints (PRD §3.9)."""
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_NOT_COORDINATOR,
    ERR_STALE_VERSION,
    ERR_FORBIDDEN,
)
from middleware import authenticate, require_role
from response import success, list_success
from services import views, helpers

bp = Blueprint("party_orders", __name__)


@bp.route("/party-orders", methods=["POST"])
def create_party_order():
    user_id, role = authenticate()
    require_role(role, {"Customer", "StoreClerk"})
    body = helpers.get_json_body()

    coordinator_customer_id = helpers.as_str(body, "coordinator_customer_id")
    helpers.find("Customer", coordinator_customer_id)
    if role == "Customer" and user_id != coordinator_customer_id:
        raise err(ERR_FORBIDDEN, "Customer may only create parties they coordinate")
    event_date_iso = helpers.as_str(body, "event_date_iso")
    required_member_count = helpers.as_int_min(body, "required_member_count", 1)

    party = {
        "coordinator_customer_id": coordinator_customer_id,
        "event_date_iso": event_date_iso,
        "required_member_count": required_member_count,
        "posture_explicit": None,  # sticky LOCKED/DISSOLVED; else derived
    }
    db.stamp_create(party)
    db.party_orders[party["id"]] = party
    return success(views.party_order_view(party), status=201)


@bp.route("/party-orders/<pid>", methods=["GET"])
def get_party_order(pid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    party = helpers.find("PartyOrder", pid)
    return success(views.party_order_view(party))


@bp.route("/party-orders", methods=["GET"])
def list_party_orders():
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    limit, offset = helpers.parse_pagination()
    records = list(db.party_orders.values())
    if role == "Customer":
        records = [p for p in records if p["coordinator_customer_id"] == user_id]
    coordinator_customer_id = request.args.get("coordinator_customer_id")
    posture = request.args.get("posture")
    if coordinator_customer_id is not None:
        records = [p for p in records if p["coordinator_customer_id"] == coordinator_customer_id]
    if posture is not None:
        records = [p for p in records if views.derive_posture(p) == posture]
    page, total = helpers.paginate_sorted(records, limit, offset)
    return list_success([views.party_order_view(p) for p in page], limit, offset, total)


@bp.route("/party-orders/<pid>/lock", methods=["POST"])
def lock_party_order(pid):
    user_id, role = authenticate()
    require_role(role, {"Customer"})
    party = helpers.find("PartyOrder", pid)
    body = helpers.get_json_body()

    posture = views.derive_posture(party)
    # State: lock defined only from READY (priority 6).
    if posture != "READY":
        raise err(ERR_INVALID_STATE, "Party is not READY")
    # Coordinator-only (ERR_NOT_COORDINATOR).
    if user_id != party["coordinator_customer_id"]:
        raise err(ERR_NOT_COORDINATOR, "Only the coordinator may lock the party")
    # OCC: expected_party_order_version must match (ERR_STALE_VERSION).
    expected = body.get("expected_party_order_version")
    if expected is None or expected != party["version"]:
        raise err(ERR_STALE_VERSION, "expected_party_order_version mismatch")

    party["posture_explicit"] = "LOCKED"
    db.touch(party)
    return success(views.party_order_view(party))


@bp.route("/party-orders/<pid>/dissolve", methods=["POST"])
def dissolve_party_order(pid):
    user_id, role = authenticate()
    require_role(role, {"Customer"})
    party = helpers.find("PartyOrder", pid)

    posture = views.derive_posture(party)
    # State: dissolve defined only from FORMING (priority 6).
    if posture != "FORMING":
        raise err(ERR_INVALID_STATE, "Party is not FORMING")
    # Coordinator-only (ERR_NOT_COORDINATOR).
    if user_id != party["coordinator_customer_id"]:
        raise err(ERR_NOT_COORDINATOR, "Only the coordinator may dissolve the party")

    # Cascade: PENDING members -> CANCELLED; CONFIRMED members release unit.
    for r in db.reservations.values():
        if r["party_order_id"] != party["id"]:
            continue
        if r["status"] == "PENDING":
            r["status"] = "CANCELLED"
            db.touch(r)
        elif r["status"] == "CONFIRMED":
            if r["garment_unit_id"]:
                unit = db.garment_units.get(r["garment_unit_id"])
                if unit is not None and unit["status"] == "RESERVED":
                    unit["status"] = "AVAILABLE"
                    db.touch(unit)
            r["status"] = "CANCELLED"
            db.touch(r)

    party["posture_explicit"] = "DISSOLVED"
    db.touch(party)
    return success(views.party_order_view(party))
