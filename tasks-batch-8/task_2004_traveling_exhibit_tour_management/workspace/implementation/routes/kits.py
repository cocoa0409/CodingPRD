"""MarketingKit endpoints (PRD §3.4)."""

from flask import Blueprint

import calc
import db
import system
from envelope import ok_object
from errors import fail
from security import require_roles, ALL_ROLES
from serializers import kit_out
from validate import (json_body, req_int, get_tour, get_stop, paginate,
                      sorted_created)

bp = Blueprint("kits", __name__)


@bp.route("/tours/<tour_id>/stops/<stop_id>/marketing-kit", methods=["POST"])
def create_kit(tour_id, stop_id):
    require_roles("TourManager")
    tour = get_tour(tour_id)
    stop = get_stop(tour, stop_id)
    data = json_body()
    kit = db.stamp_new({
        "id": db.new_id(),
        "tour_stop_id": stop["id"],
        "language_count": req_int(data, "language_count"),
        "sponsor_logo_slots": req_int(data, "sponsor_logo_slots"),
        "press_release_sent": False,
        "status": "PLANNED",
        "production_cost_cents": None,
    })
    db.kits[kit["id"]] = kit
    return ok_object(kit_out(kit), status=201)


@bp.route("/tours/<tour_id>/stops/<stop_id>/marketing-kit", methods=["GET"])
def list_kits(tour_id, stop_id):
    require_roles(*ALL_ROLES)
    tour = get_tour(tour_id)
    stop = get_stop(tour, stop_id)
    items = sorted_created(system.kits_of_stop(stop["id"]))
    return paginate([kit_out(k) for k in items])


def _target_kit(stop):
    """The stop's live kit; 404 when no kit exists, 409 when all are retired."""
    kits = system.kits_of_stop(stop["id"])
    if not kits:
        fail("ERR_NOT_FOUND", "No marketing kit exists for this stop")
    kit = system.live_kit(stop["id"])
    if kit is None:
        fail("ERR_INVALID_STATE", "The stop's marketing kit is retired")
    return kit


@bp.route("/tours/<tour_id>/stops/<stop_id>/marketing-kit/send-press-release",
          methods=["POST"])
def send_press_release(tour_id, stop_id):
    require_roles("TourManager")
    tour = get_tour(tour_id)
    stop = get_stop(tour, stop_id)
    kit = _target_kit(stop)
    kit["press_release_sent"] = True
    db.touch(kit)
    return ok_object(kit_out(kit))


@bp.route("/tours/<tour_id>/stops/<stop_id>/marketing-kit/transition",
          methods=["POST"])
def kit_transition(tour_id, stop_id):
    require_roles("TourManager")
    tour = get_tour(tour_id)
    stop = get_stop(tour, stop_id)
    data = json_body()
    action = data.get("action")
    if action not in ("PRODUCE", "DELIVER"):
        fail("ERR_INVALID_REQUEST", "Unrecognized action: %r" % action)
    kit = _target_kit(stop)

    if action == "PRODUCE":
        if kit["status"] != "PLANNED":
            fail("ERR_INVALID_STATE", "PRODUCE is only permitted from PLANNED")
        if stop["status"] not in ("TENTATIVE", "CONTRACTED"):
            fail("ERR_INVALID_STATE",
                 "Production requires a TENTATIVE or CONTRACTED stop")
        kit["production_cost_cents"] = calc.marketing_kit_cost(
            kit["language_count"], kit["sponsor_logo_slots"])
        kit["status"] = "PRODUCED"
        db.touch(kit)
        return ok_object(kit_out(kit))

    # DELIVER
    if kit["status"] != "PRODUCED":
        fail("ERR_INVALID_STATE", "DELIVER is only permitted from PRODUCED")
    if stop["status"] not in ("CONTRACTED", "INSTALLING", "OPEN"):
        fail("ERR_INVALID_STATE",
             "Delivery requires a CONTRACTED, INSTALLING, or OPEN stop")
    if not kit["press_release_sent"]:
        fail("ERR_INVALID_STATE",
             "The press release must be issued before delivery")
    kit["status"] = "DELIVERED"
    db.touch(kit)
    return ok_object(kit_out(kit))
