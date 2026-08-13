"""Recipe endpoints."""
from flask import Blueprint

from db import DB, new_id, next_seq
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import ALLERGENS, DIETARY_FLAGS, STATIONS, get_hall, get_recipe, ser, stamp, touch
from util import as_bool, as_enum, as_int, as_list, as_num, as_str, body, required
from routes.common import list_endpoint

bp = Blueprint("recipes", __name__)


def _validate_tags(tags, field):
    as_list(tags, field)
    for t in tags:
        as_enum(t, field, ALLERGENS)
    return tags


def _validate_flags(flags, field):
    as_list(flags, field)
    for f in flags:
        as_enum(f, field, DIETARY_FLAGS)
    return flags


def _validate_share(share):
    as_num(share, "popularity_share")
    if not (0 < share <= 1):
        raise ApiError("ERR_VALIDATION", 400, "popularity_share must be in (0, 1]")
    return share


def _validate_cost(cost):
    as_int(cost, "unit_cost_cents")
    if cost <= 0:
        raise ApiError("ERR_VALIDATION", 400, "unit_cost_cents must be > 0")
    return cost


def _check_empty_tags_rule(tags, reviewed):
    if len(tags) == 0 and not reviewed:
        raise ApiError(
            "ERR_VALIDATION",
            400,
            "An empty allergen_tags array requires allergen_reviewed to be true",
        )


@bp.post("/recipes")
def create_recipe():
    auth(["KitchenLead"])
    data = body()
    dining_hall_id = required(data, "dining_hall_id")
    if isinstance(dining_hall_id, str):
        get_hall(dining_hall_id)
    name = as_str(required(data, "name"), "name")
    station = as_enum(required(data, "station"), "station", STATIONS)
    allergen_tags = _validate_tags(required(data, "allergen_tags"), "allergen_tags")
    dietary_flags = _validate_flags(required(data, "dietary_flags"), "dietary_flags")
    popularity_share = _validate_share(required(data, "popularity_share"))
    unit_cost_cents = _validate_cost(required(data, "unit_cost_cents"))
    reviewed = data.get("allergen_reviewed", False)
    if "allergen_reviewed" in data:
        reviewed = as_bool(data["allergen_reviewed"], "allergen_reviewed")
    _check_empty_tags_rule(allergen_tags, reviewed)
    if not isinstance(dining_hall_id, str):
        raise ApiError("ERR_VALIDATION", 400, "dining_hall_id must be a string")
    rec = {
        "id": new_id(),
        "dining_hall_id": dining_hall_id,
        "name": name,
        "station": station,
        "allergen_tags": allergen_tags,
        "dietary_flags": dietary_flags,
        "popularity_share": popularity_share,
        "unit_cost_cents": unit_cost_cents,
        "allergen_reviewed": reviewed,
        "status": "ACTIVE",
        "_seq": next_seq(),
    }
    stamp(rec)
    DB["recipes"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/recipes")
def list_recipes():
    return list_endpoint(
        "recipes",
        [
            ("dining_hall_id", "dining_hall_id"),
            ("station", "station"),
            ("status", "status"),
        ],
    )


@bp.get("/recipes/<rid>")
def get_one_recipe(rid):
    auth(ALL_ROLES)
    return ok(ser(get_recipe(rid)))


@bp.patch("/recipes/<rid>")
def patch_recipe(rid):
    auth(["KitchenLead"])
    recipe = get_recipe(rid)
    data = body()
    new = dict(recipe)
    if "name" in data and data["name"] is not None:
        new["name"] = as_str(data["name"], "name")
    if "station" in data and data["station"] is not None:
        new["station"] = as_enum(data["station"], "station", STATIONS)
    if "allergen_tags" in data and data["allergen_tags"] is not None:
        new["allergen_tags"] = _validate_tags(data["allergen_tags"], "allergen_tags")
    if "dietary_flags" in data and data["dietary_flags"] is not None:
        new["dietary_flags"] = _validate_flags(data["dietary_flags"], "dietary_flags")
    if "popularity_share" in data and data["popularity_share"] is not None:
        new["popularity_share"] = _validate_share(data["popularity_share"])
    if "unit_cost_cents" in data and data["unit_cost_cents"] is not None:
        new["unit_cost_cents"] = _validate_cost(data["unit_cost_cents"])
    if "allergen_reviewed" in data and data["allergen_reviewed"] is not None:
        new["allergen_reviewed"] = as_bool(data["allergen_reviewed"], "allergen_reviewed")
    _check_empty_tags_rule(new["allergen_tags"], new["allergen_reviewed"])
    for key in (
        "name",
        "station",
        "allergen_tags",
        "dietary_flags",
        "popularity_share",
        "unit_cost_cents",
        "allergen_reviewed",
    ):
        recipe[key] = new[key]
    touch(recipe)
    return ok(ser(recipe))


@bp.post("/recipes/<rid>/suspend")
def suspend_recipe(rid):
    auth(["DiningAdmin"])
    recipe = get_recipe(rid)
    if recipe["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Recipe is not ACTIVE")
    recipe["status"] = "SUSPENDED"
    touch(recipe)
    return ok(ser(recipe))


@bp.post("/recipes/<rid>/reinstate")
def reinstate_recipe(rid):
    auth(["DiningAdmin"])
    recipe = get_recipe(rid)
    if recipe["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Recipe is not SUSPENDED")
    if not recipe["allergen_reviewed"]:
        raise ApiError(
            "ERR_ALLERGEN_UNDECLARED", 422, "Recipe has not been allergen-reviewed"
        )
    recipe["status"] = "ACTIVE"
    touch(recipe)
    return ok(ser(recipe))
