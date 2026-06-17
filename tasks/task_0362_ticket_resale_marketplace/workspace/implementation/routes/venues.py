from flask import Blueprint

import db
import validate
import response
from middleware import get_user_context, require_role
from services import lookup, serialize, paginate
from services.recompute import recompute_section, recompute_venue

bp = Blueprint("venues", __name__)

READ_ROLES = ("PlatformAdmin", "Seller", "Buyer", "TrustSafety")


@bp.post("/venues")
def create_venue():
    body = validate.get_json_body()
    name = validate.require_string(body, "name")
    timezone = validate.require_string(body, "timezone")
    _, role = get_user_context()
    require_role(role, ("PlatformAdmin",))

    venue = {
        "name": name,
        "timezone": timezone,
        "total_section_count": 0,
    }
    db.stamp_create(venue)
    db.venues[venue["id"]] = venue
    return response.object_response(serialize.public(venue), 201)


@bp.get("/venues/<venue_id>")
def get_venue(venue_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    venue = lookup.get_venue(venue_id)
    return response.object_response(serialize.public(venue), 200)


@bp.post("/sections")
def create_section():
    body = validate.get_json_body()
    venue_id = validate.require_string(body, "venue_id")
    name = validate.require_string(body, "name")
    price_zone = validate.require_enum(body, "price_zone", {"PREMIUM", "STANDARD", "VALUE"})
    face_value_cents = validate.require_int(body, "face_value_cents", minimum=1)
    row_count = validate.require_int(body, "row_count", minimum=1)
    seats_per_row = validate.require_int(body, "seats_per_row", minimum=1)
    _, role = get_user_context()
    require_role(role, ("PlatformAdmin",))

    venue = lookup.get_venue(venue_id)

    section = {
        "venue_id": venue_id,
        "name": name,
        "price_zone": price_zone,
        "face_value_cents": face_value_cents,
        "row_count": row_count,
        "seats_per_row": seats_per_row,
        "capacity": row_count * seats_per_row,
    }
    db.stamp_create(section)
    db.sections[section["id"]] = section
    recompute_venue(venue)
    return response.object_response(serialize.public(section), 201)


@bp.get("/sections/<section_id>")
def get_section(section_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    section = lookup.get_section(section_id)
    return response.object_response(serialize.public(section), 200)


@bp.get("/sections")
def list_sections():
    from flask import request
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    venue_id = request.args.get("venue_id")
    records = list(db.sections.values())
    if venue_id is not None:
        records = [s for s in records if s["venue_id"] == venue_id]
    page, limit, offset, total = paginate.apply_pagination(records)
    return response.array_response(serialize.public_list(page), limit, offset, total)
