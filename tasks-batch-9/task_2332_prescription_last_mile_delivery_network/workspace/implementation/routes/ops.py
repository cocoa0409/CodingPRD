"""The routing sweep and the logical clock."""

from flask import Blueprint

import response
import validation as v
from db import db, iso, sort_rows, touch
from middleware import ROLE_OPS, require_roles
from services import cascades
from services import couriers as courier_service
from services import derive
from services import reservations

bp = Blueprint("ops", __name__)


@bp.post("/routing-runs")
@require_roles(ROLE_OPS)
def routing_run():
    expired_offer_count = 0
    closed_window_count = 0
    offers_created_count = 0
    offered_delivery_ids = []

    # Pass 1 — expire stale offers.
    for assignment in sort_rows(list(db.courier_assignments.values())):
        if assignment["status"] != "OFFERED":
            continue
        if db.clock < assignment["offer_expires_at"]:
            continue
        assignment["status"] = "EXPIRED"
        touch(assignment)
        delivery = db.deliveries.get(assignment["delivery_id"])
        if delivery is not None:
            cascades.exclude_courier(delivery, assignment["courier_id"])
            touch(delivery)
        expired_offer_count += 1

    # Pass 2 — close elapsed windows. This sweep is the only thing that closes one.
    for window in sort_rows(list(db.delivery_windows.values())):
        if window["status"] == "CLOSED":
            continue
        if db.clock < window["window_end"]:
            continue
        window["status"] = "CLOSED"
        touch(window)
        closed_window_count += 1

    # Pass 3 — offer every unassigned QUEUED delivery, oldest first.
    for delivery in sort_rows(list(db.deliveries.values())):
        if delivery["custody_status"] != "QUEUED":
            continue
        has_offer = any(a["delivery_id"] == delivery["id"] and a["status"] == "OFFERED"
                        for a in db.courier_assignments.values())
        if has_offer:
            continue
        window = db.delivery_windows.get(delivery["window_id"])
        if window is None:
            continue
        zone = reservations.zone_of(window)
        if zone is None:
            continue
        selected = courier_service.select_courier(delivery, window, zone)
        if selected is None:
            continue
        courier_service.create_offer(delivery, selected,
                                    derive.rolling_reliability_score(selected))
        offers_created_count += 1
        offered_delivery_ids.append(delivery["id"])

    return response.single({
        "expired_offer_count": expired_offer_count,
        "closed_window_count": closed_window_count,
        "offers_created_count": offers_created_count,
        "offered_delivery_ids": offered_delivery_ids,
    }, 200)


@bp.post("/_clock/set_current_utc")
@require_roles(ROLE_OPS)
def set_clock():
    body = v.json_body()
    current_utc = v.datetime_field(body, "current_utc")
    db.clock = current_utc
    return response.single({"current_utc": iso(db.clock)}, 200)
