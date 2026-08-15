"""RecipientAgency endpoints."""
from flask import Blueprint

from db import DB, new_id
from middleware import auth
from response import ok
from services import CATEGORIES, get_agency, ser_agency, stamp
from util import as_enum, as_int, as_list, as_str, body, reject_unknown, required

bp = Blueprint("agencies", __name__)


@bp.post("/api/recipient-agencies")
def create_agency():
    auth(["DispatchAdmin"])
    data = body()
    allowed = {
        "name",
        "accepts_categories",
        "capacity_cold_held_lbs",
        "capacity_hot_held_lbs",
        "capacity_produce_lbs",
        "capacity_shelf_stable_lbs",
    }
    reject_unknown(data, allowed)
    name = as_str(required(data, "name"), "name")
    accepts = as_list(required(data, "accepts_categories"), "accepts_categories")
    if len(accepts) == 0:
        from errors import ApiError

        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "accepts_categories must be non-empty"
        )
    accepts = [as_enum(c, "accepts_categories", CATEGORIES) for c in accepts]
    caps = {}
    for cat in CATEGORIES:
        field = "capacity_" + cat.lower() + "_lbs"
        caps[field] = as_int(required(data, field), field, minimum=0)
    rec = {
        "id": new_id(),
        "name": name,
        "accepts_categories": accepts,
        "capacity_cold_held_lbs": caps["capacity_cold_held_lbs"],
        "capacity_hot_held_lbs": caps["capacity_hot_held_lbs"],
        "capacity_produce_lbs": caps["capacity_produce_lbs"],
        "capacity_shelf_stable_lbs": caps["capacity_shelf_stable_lbs"],
        "committed_cold_held_lbs": 0,
        "committed_hot_held_lbs": 0,
        "committed_produce_lbs": 0,
        "committed_shelf_stable_lbs": 0,
        "received_total_lbs": 0,
    }
    stamp(rec)
    DB["agencies"][rec["id"]] = rec
    return ok(ser_agency(rec), status=201)


@bp.get("/api/recipient-agencies/<aid>")
def get_one_agency(aid):
    user_id, role = auth(["DispatchAdmin", "AgencyCoordinator"])
    return ok(ser_agency(get_agency(aid, user_id, role)))
