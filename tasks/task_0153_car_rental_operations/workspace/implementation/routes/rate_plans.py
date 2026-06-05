"""RatePlan endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
import lookup
import serialize
import util
from middleware import get_principal, require_roles
from pagination import paginate
from response import array_response, object_response

bp = Blueprint("rate_plans", __name__)


@bp.route("/rate-plans", methods=["POST"])
def create_rate_plan():
    _, role = get_principal()
    require_roles(role, {"FleetManager"})
    body = request.get_json(silent=True) or {}

    location_id = util.require_str(body, "location_id")
    class_id = util.require_str(body, "class_id")
    daily = util.require_int(body, "daily_rate_cents", minimum=1)
    weekly = util.require_int(body, "weekly_rate_cents", minimum=1)
    effective_from_raw = util.require_str(body, "effective_from")
    active = util.optional_bool(body, "active", default=True)

    # Existence (left-to-right): location then class.
    lookup.get_location(location_id)
    lookup.get_vehicle_class(class_id)
    # Normalize/validate the datetime.
    util.parse_iso8601(effective_from_raw)

    rec = util.stamp_new(
        {
            "location_id": location_id,
            "class_id": class_id,
            "daily_rate_cents": daily,
            "weekly_rate_cents": weekly,
            "active": active,
            "effective_from": effective_from_raw,
        }
    )
    db.rate_plans[rec["id"]] = rec
    return object_response(serialize.rate_plan(rec), 201)


@bp.route("/rate-plans", methods=["GET"])
def list_rate_plans():
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent"})

    location_id = request.args.get("location_id")
    class_id = request.args.get("class_id")
    active_raw = request.args.get("active")
    active = None
    if active_raw is not None:
        active = active_raw.lower() == "true"

    matches = [
        p
        for p in db.rate_plans.values()
        if (location_id is None or p["location_id"] == location_id)
        and (class_id is None or p["class_id"] == class_id)
        and (active is None or p["active"] == active)
    ]
    page, limit, offset, total = paginate(matches)
    return array_response(
        [serialize.rate_plan(p) for p in page], limit, offset, total, 200
    )


@bp.route("/rate-plans/<plan_id>", methods=["GET"])
def get_rate_plan(plan_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent"})
    rec = lookup.get_rate_plan(plan_id)
    return object_response(serialize.rate_plan(rec), 200)
