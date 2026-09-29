"""Store registration, the OCC read channel, posture commands and merge awards."""

from decimal import Decimal

from flask import Blueprint

from constants import ALL_ROLES, LANE_CONFIGS, STAFFING_BASES
from db import base_row, db
from errors import fail
from middleware import authenticate, get_restaurant, require_not_accuracy_hold, require_not_frozen, scope
from response import ok
from serialize import merge_slot as merge_slot_json
from serialize import restaurant as restaurant_json
from services import merge as merge_service
from services.rollup import lookup_band, recompute
from validation import body_or_400, opt_enum, opt_int, req_enum, req_int, req_str

bp = Blueprint("restaurants", __name__)


@bp.route("/restaurants", methods=["POST"])
def create_restaurant():
    authenticate(("ProgramAdmin",))
    body = body_or_400()

    name = req_str(body, "name")
    store_number = req_str(body, "store_number")
    lane_config = req_enum(body, "lane_config", LANE_CONFIGS)
    capacity = req_int(body, "merge_slots_capacity", minimum=1, maximum=12)
    budget = req_int(body, "labor_minutes_budget", minimum=0, maximum=5000)
    staffing_basis = opt_enum(body, "staffing_basis", STAFFING_BASES, "OBSERVED")

    for row in db.restaurants.values():
        if row["store_number"] == store_number:
            fail("ERR_DUPLICATE_STORE_NUMBER",
                 "store_number %s is already registered" % store_number)

    band = lookup_band(Decimal("0.0"))

    row = base_row()
    row.update({
        "name": name,
        "store_number": store_number,
        "lane_config": lane_config,
        "merge_slots_capacity": capacity,
        "merge_slots_free": capacity,
        "labor_minutes_budget": budget,
        "labor_minutes_committed": 0,
        "labor_minutes_available": budget,
        "staffing_basis": staffing_basis,
        "cars_closed_trailing": 0,
        "cars_per_hour_observed": Decimal("0.0"),
        "cars_per_hour_effective": Decimal("0.0"),
        "volume_tier": band["tier"],
        "required_oot_count": 0,
        "deployed_oot_count": 0,
        "open_remake_count": 0,
        "remake_cost_accrued_cents": 0,
        "posture_override": "NONE",
        "freeze_reason": None,
        "service_posture": "OPEN",
    })
    db.restaurants[row["id"]] = row
    return ok(restaurant_json(row), 201)


@bp.route("/restaurants/<restaurant_id>", methods=["GET"])
def read_restaurant(restaurant_id):
    authenticate(ALL_ROLES)
    return ok(restaurant_json(get_restaurant(restaurant_id)))


@bp.route("/restaurants/<restaurant_id>", methods=["PATCH"])
def patch_restaurant(restaurant_id):
    actor = authenticate(("Operator",))
    restaurant = get_restaurant(restaurant_id)
    scope(actor, restaurant_id)
    body = body_or_400()

    staffing_basis = opt_enum(body, "staffing_basis", STAFFING_BASES)
    budget = opt_int(body, "labor_minutes_budget", minimum=0, maximum=5000)

    if staffing_basis is not None:
        restaurant["staffing_basis"] = staffing_basis
    if budget is not None:
        restaurant["labor_minutes_budget"] = budget

    recompute(restaurant, explicit=True)
    return ok(restaurant_json(restaurant))


@bp.route("/restaurants/<restaurant_id>/freeze", methods=["POST"])
def freeze_restaurant(restaurant_id):
    actor = authenticate(("Operator",))
    restaurant = get_restaurant(restaurant_id)
    scope(actor, restaurant_id)
    body = body_or_400()
    reason = req_str(body, "freeze_reason")

    require_not_frozen(restaurant)

    restaurant["posture_override"] = "FROZEN"
    restaurant["freeze_reason"] = reason
    recompute(restaurant, explicit=True)
    return ok(restaurant_json(restaurant))


@bp.route("/restaurants/<restaurant_id>/unfreeze", methods=["POST"])
def unfreeze_restaurant(restaurant_id):
    actor = authenticate(("Operator",))
    restaurant = get_restaurant(restaurant_id)
    scope(actor, restaurant_id)

    if restaurant["posture_override"] != "FROZEN":
        fail("ERR_POSTURE_FROZEN", "the store is not frozen")

    restaurant["posture_override"] = "NONE"
    restaurant["freeze_reason"] = None
    recompute(restaurant, explicit=True)
    return ok(restaurant_json(restaurant))


@bp.route("/restaurants/<restaurant_id>/merge-award", methods=["POST"])
def merge_award(restaurant_id):
    actor = authenticate(("ShiftLeader",))
    restaurant = get_restaurant(restaurant_id)
    scope(actor, restaurant_id)

    require_not_frozen(restaurant)
    require_not_accuracy_hold(restaurant)

    slot = merge_service.award(restaurant)
    recompute(restaurant)
    return ok(merge_slot_json(slot), 201)
