"""Club sites."""
from flask import Blueprint

import db
import middleware
import response
from services import domain, validate

bp = Blueprint("clubs", __name__)


@bp.post("/fleetcare/clubs")
def create_club():
    middleware.auth(middleware.CONTRACT_ADMIN)
    body = middleware.body()
    name = validate.string(body, "name", min_len=1, max_len=120)
    region = validate.region_code(body, "region_code")
    open_minute = validate.integer(body, "operating_open_minute", minimum=0, maximum=1439,
                                   required=False, default=300)
    close_minute = validate.integer(body, "operating_close_minute", minimum=1, maximum=1440,
                                    required=False, default=1380)
    max_concurrent = validate.integer(body, "max_concurrent_visits", minimum=1,
                                      required=False, default=1)
    if close_minute <= open_minute:
        validate.bad("operating_close_minute must be strictly greater than operating_open_minute")

    row = db.base_row()
    row.update({
        "name": name,
        "region_code": region,
        "operating_open_minute": open_minute,
        "operating_close_minute": close_minute,
        "max_concurrent_visits": max_concurrent,
        "covered_unit_count": 0,
        "open_safety_lockout_count": 0,
    })
    db.clubs[row["id"]] = row
    return response.created_response(row)


@bp.get("/fleetcare/clubs")
def list_clubs():
    middleware.auth(*middleware.ALL_ROLES)
    return response.listing(db.clubs, {"region_code": response.arg("region_code")})


@bp.get("/fleetcare/clubs/<club_id>")
def read_club(club_id):
    ctx = middleware.auth(*middleware.ALL_ROLES)
    middleware.require_club_scope(ctx, club_id)
    return response.object_response(domain.need_club(club_id))
