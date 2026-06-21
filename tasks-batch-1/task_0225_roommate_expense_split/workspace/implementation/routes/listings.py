"""RoomListing endpoints (PRD §3.1)."""
from flask import Blueprint, request

import models
import response
import validate
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate

bp = Blueprint("listings", __name__)

ALL_ROLES = {"Roommate", "DisputeMediator", "PlatformOperator"}
SLEEP = {"EARLY_BIRD", "NIGHT_OWL", "FLEXIBLE"}
SPLIT = {"EQUAL", "BY_ROOM_SIZE", "BY_INCOME"}


@bp.route("/room-listings", methods=["POST"])
def create_listing():
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        body = validate.get_json_body()
        lister_id = validate.require_str(body, "lister_id")
        title = validate.require_str(body, "title")
        rent = validate.require_int(body, "monthly_rent_cents", minimum=1)
        capacity = validate.require_int(body, "capacity", minimum=1, maximum=8)
        room_size = validate.require_int(body, "room_size_sqft", minimum=1)
        wants_clean = validate.require_int(body, "wants_cleanliness", minimum=1, maximum=5)
        wants_sleep = validate.require_enum(body, "wants_sleep_schedule", SLEEP)
        no_smokers = validate.optional_bool(body, "no_smokers", False)
        no_pets = validate.optional_bool(body, "no_pets", False)
        split_policy = validate.require_enum(body, "split_policy", SPLIT, default="EQUAL")
        # FK existence (PRD §2.5)
        if lister_id not in db.roommate_profiles:
            raise err("ERR_NOT_FOUND", "lister_id does not exist.")
        listing = {
            "lister_id": lister_id,
            "title": title,
            "monthly_rent_cents": rent,
            "capacity": capacity,
            "room_size_sqft": room_size,
            "wants_cleanliness": wants_clean,
            "wants_sleep_schedule": wants_sleep,
            "no_smokers": no_smokers,
            "no_pets": no_pets,
            "split_policy": split_policy,
            "status": "OPEN",
        }
        models.stamp_create(listing)
        db.room_listings[listing["id"]] = listing
        return response.ok(models.serialize(listing), 201)


@bp.route("/room-listings/<lid>", methods=["GET"])
def get_listing(lid):
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        listing = db.room_listings.get(lid)
        if not listing:
            raise err("ERR_NOT_FOUND", "Listing not found.")
        return response.ok(models.serialize(listing))


@bp.route("/room-listings", methods=["GET"])
def list_listings():
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        limit, offset = parse_pagination()
        items = list(db.room_listings.values())
        lister_id = request.args.get("lister_id")
        if lister_id is not None:
            items = [x for x in items if x["lister_id"] == lister_id]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)
