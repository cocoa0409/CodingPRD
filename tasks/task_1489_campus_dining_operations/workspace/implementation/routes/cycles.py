"""MenuCycle endpoints."""
from flask import Blueprint

from db import DB, new_id, next_seq
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import get_cycle, get_hall, ser, stamp, touch
from util import as_int, as_iso_date, as_str, body, parse_ymd, required
from routes.common import list_endpoint

bp = Blueprint("cycles", __name__)


@bp.post("/menu-cycles")
def create_cycle():
    auth(["DiningAdmin"])
    data = body()
    dining_hall_id = required(data, "dining_hall_id")
    if isinstance(dining_hall_id, str):
        get_hall(dining_hall_id)
    name = as_str(required(data, "name"), "name")
    weeks = as_int(required(data, "cycle_length_weeks"), "cycle_length_weeks")
    if not 1 <= weeks <= 8:
        raise ApiError("ERR_VALIDATION", 400, "cycle_length_weeks must be 1..8")
    start = as_iso_date(required(data, "start_date"), "start_date")
    end = as_iso_date(required(data, "end_date"), "end_date")
    if parse_ymd(end) <= parse_ymd(start):
        raise ApiError("ERR_VALIDATION", 400, "end_date must be after start_date")
    if not isinstance(dining_hall_id, str):
        raise ApiError("ERR_VALIDATION", 400, "dining_hall_id must be a string")
    rec = {
        "id": new_id(),
        "dining_hall_id": dining_hall_id,
        "name": name,
        "cycle_length_weeks": weeks,
        "start_date": start,
        "end_date": end,
        "status": "DRAFT",
        "_seq": next_seq(),
    }
    stamp(rec)
    DB["menu_cycles"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/menu-cycles")
def list_cycles():
    return list_endpoint(
        "menu_cycles", [("dining_hall_id", "dining_hall_id"), ("status", "status")]
    )


@bp.get("/menu-cycles/<cid>")
def get_one_cycle(cid):
    auth(ALL_ROLES)
    return ok(ser(get_cycle(cid)))


@bp.post("/menu-cycles/<cid>/publish")
def publish_cycle(cid):
    auth(["DiningAdmin"])
    cycle = get_cycle(cid)
    if cycle["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "MenuCycle is not DRAFT")
    # Tier 6: every ACTIVE recipe at the hall must be allergen-reviewed.
    for recipe in DB["recipes"].values():
        if (
            recipe["dining_hall_id"] == cycle["dining_hall_id"]
            and recipe["status"] == "ACTIVE"
            and not recipe["allergen_reviewed"]
        ):
            raise ApiError(
                "ERR_ALLERGEN_UNDECLARED",
                422,
                "An ACTIVE recipe at the hall has not been allergen-reviewed",
            )
    # Tier 7: half-open interval overlap with other PUBLISHED cycles at the hall.
    start, end = parse_ymd(cycle["start_date"]), parse_ymd(cycle["end_date"])
    for other in DB["menu_cycles"].values():
        if (
            other["id"] != cycle["id"]
            and other["dining_hall_id"] == cycle["dining_hall_id"]
            and other["status"] == "PUBLISHED"
        ):
            o_start, o_end = parse_ymd(other["start_date"]), parse_ymd(other["end_date"])
            if start < o_end and o_start < end:
                raise ApiError(
                    "ERR_CYCLE_OVERLAP",
                    409,
                    "Overlaps another PUBLISHED cycle at this hall",
                )
    cycle["status"] = "PUBLISHED"
    touch(cycle)
    return ok(ser(cycle))


@bp.post("/menu-cycles/<cid>/archive")
def archive_cycle(cid):
    auth(["DiningAdmin"])
    cycle = get_cycle(cid)
    if cycle["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError("ERR_INVALID_STATE", 409, "MenuCycle cannot be archived")
    cycle["status"] = "ARCHIVED"
    touch(cycle)
    return ok(ser(cycle))
