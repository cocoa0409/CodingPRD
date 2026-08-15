"""Vehicle subscription routes (PRD 3.4). Closed-interval windows; adjacency
IS a conflict. Parallel dimensions: lifecycle status x payment_standing."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import (
    body_json,
    ctx,
    list_response,
    need_str,
    ownership_guard,
    require_role,
)
from response import ok
from services.sweep import close_subscription
from util import parse_date

bp = Blueprint("subscriptions", __name__)


@bp.post("/api/vehicle-subscriptions")
def create_subscription():
    uid, role = ctx()
    require_role(role, ("CarrierManager",))
    body = body_json()
    cid = body.get("carrier_id")
    vid = body.get("vehicle_id")
    # Rung 3: direct carrier_id comparison, plus resolution through the vehicle
    if isinstance(cid, str):
        ownership_guard(cid, uid)
    veh = store.vehicles.get(vid) if isinstance(vid, str) else None
    if veh is not None:
        ownership_guard(veh["carrier_id"], uid)
    # Rung 4: existence, type order — carrier before vehicle
    carrier = store.carriers.get(cid) if isinstance(cid, str) else None
    if isinstance(cid, str) and carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND", 404, "carrier id does not exist")
    if isinstance(vid, str) and veh is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND", 404, "vehicle id does not exist")
    # Rung 7: carrier must be ACTIVE
    if carrier is not None and carrier["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CARRIER_NOT_ACTIVE", 409, "carrier must be ACTIVE to create subscriptions"
        )
    # Rung 9: temporal sanity — start on/after today, start not after end
    sd = parse_date(body.get("service_start_date"))
    ed = parse_date(body.get("service_end_date"))
    today = db.today()
    if sd is not None and ed is not None:
        if sd < today or sd > ed or ed < today:
            raise ApiError(
                "ERR_INVALID_DATE_RANGE",
                400,
                "service_start_date must be >= today and <= service_end_date, and service_end_date must not be in the past",
            )
    # Rung 10: closed-interval overlap; adjacency (start == existing end) conflicts
    if veh is not None and sd is not None and ed is not None:
        for s in store.subscriptions.values():
            if s["vehicle_id"] == vid and s["status"] != "CLOSED":
                if sd <= s["_end"] and s["_start"] <= ed:
                    raise ApiError(
                        "ERR_SUBSCRIPTION_WINDOW_OVERLAP",
                        409,
                        "window overlaps an existing non-CLOSED subscription of this vehicle",
                    )
    # Rung 12: fields
    cid = need_str(body, "carrier_id")
    vid = need_str(body, "vehicle_id")
    if sd is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "service_start_date must be a YYYY-MM-DD date"
        )
    if ed is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "service_end_date must be a YYYY-MM-DD date"
        )
    # Rung 15: past-due standing blocks new subscriptions
    if any(
        i["carrier_id"] == cid and i["status"] == "PAST_DUE"
        for i in store.invoices.values()
    ):
        raise ApiError(
            "ERR_CARRIER_PAST_DUE", 402, "carrier has past-due standing"
        )
    rec = {
        "id": db.new_id(),
        "_seq": store.next_seq(),
        "carrier_id": cid,
        "vehicle_id": vid,
        "service_start_date": sd.isoformat(),
        "service_end_date": ed.isoformat(),
        "_start": sd,
        "_end": ed,
        "status": "ACTIVE" if sd <= today else "SCHEDULED",
        "payment_standing": "CURRENT",
        "paused_at": None,
        "paused_days_current_period": 0,
        "closed_reason": None,
        "version": 1,
    }
    db.stamp(rec)
    store.subscriptions[rec["id"]] = rec
    return ok(db.public(rec), 201)


@bp.get("/api/vehicle-subscriptions")
def list_subscriptions():
    return list_response(
        store.subscriptions.values(),
        [
            ("carrier_id", "carrier_id"),
            ("vehicle_id", "vehicle_id"),
            ("status", "status"),
            ("payment_standing", "payment_standing"),
        ],
    )


@bp.get("/api/vehicle-subscriptions/<subscriptionId>")
def get_subscription(subscriptionId):
    ctx()
    sub = store.subscriptions.get(subscriptionId)
    if sub is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "subscription id does not exist")
    return ok(db.public(sub), 200)


@bp.post("/api/vehicle-subscriptions/<subscriptionId>/cancel")
def cancel_subscription(subscriptionId):
    uid, role = ctx()
    require_role(role, ("CarrierManager",))
    sub = store.subscriptions.get(subscriptionId)
    # Rung 3 / 4
    if sub is not None:
        ownership_guard(sub["carrier_id"], uid)
    if sub is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND", 404, "subscription id does not exist")
    # Rung 5
    if sub["status"] not in ("SCHEDULED", "ACTIVE", "PAUSED"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            409,
            f"subscription in status {sub['status']} cannot be cancelled",
        )
    close_subscription(sub, "CANCELLED")
    return ok(db.public(sub), 200)
