"""Tour route endpoints (including nested script-version creation/listing)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import DB, new_id, now
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    lookup,
    ser_docent,
    ser_route,
    ser_script,
    ser_slot,
    sort_items,
    stamp,
    touch,
)
from util import body, pagination_args, req_enum, req_int, req_str

bp = Blueprint("tour_routes", __name__)

ROUTE_KINDS = ("STANDARD", "SCHOOL", "CANDLELIGHT")
SLOT_STATUSES = ("SCHEDULED", "OPEN", "FULL", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def _paginate(items, serializer):
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(x) for x in page], total, limit, offset)


@bp.post("/tour-routes")
def create_route():
    auth(["MuseumAdmin"])
    data = body()
    # Tier 3 (existence): room references inside room_ids.
    raw_rooms = data.get("room_ids")
    if isinstance(raw_rooms, list):
        for rid in raw_rooms:
            lookup("rooms", rid)
    # Tier 4 (request shape).
    name = req_str(data, "name")
    kind = req_enum(data, "kind", ROUTE_KINDS)
    room_ids = data.get("room_ids")
    if (
        not isinstance(room_ids, list)
        or len(room_ids) < 1
        or not all(isinstance(x, str) for x in room_ids)
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "room_ids must be a non-empty array of room ids",
        )
    duration = req_int(data, "duration_minutes", minimum=10)
    base_price = req_int(data, "base_price_cents", minimum=0)
    # Tier 7 (collection safety): candlelight prohibition.
    if kind == "CANDLELIGHT":
        for rid in room_ids:
            if DB["rooms"][rid]["collection_tier"] == "LIGHT_SENSITIVE":
                raise ApiError(
                    "ERR_CANDLELIGHT_LIGHT_SENSITIVE",
                    422,
                    "CANDLELIGHT routes may not include LIGHT_SENSITIVE rooms",
                )
    rec = {
        "id": new_id(),
        "name": name,
        "kind": kind,
        "room_ids": list(room_ids),
        "duration_minutes": duration,
        "base_price_cents": base_price,
        "status": "DRAFT",
        "published_script_id": None,
    }
    stamp(rec)
    DB["routes"][rec["id"]] = rec
    return ok(ser_route(rec), 201)


@bp.get("/tour-routes")
def list_routes():
    auth(ALL_ROLES)
    items = list(DB["routes"].values())
    script_filter = request.args.get("published_script_id")
    if script_filter is not None:
        items = [r for r in items if r["published_script_id"] == script_filter]
    return _paginate(sort_items(items), ser_route)


@bp.get("/tour-routes/<rid>")
def get_route(rid):
    auth(ALL_ROLES)
    return ok(ser_route(lookup("routes", rid)))


@bp.post("/tour-routes/<rid>/activate")
def activate_route(rid):
    auth(["MuseumAdmin"])
    route = lookup("routes", rid)
    if route["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DRAFT route can be activated")
    route["status"] = "ACTIVE"
    touch(route)
    return ok(ser_route(route))


@bp.post("/tour-routes/<rid>/retire")
def retire_route(rid):
    auth(["MuseumAdmin"])
    route = lookup("routes", rid)
    if route["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ACTIVE route can be retired")
    t = now()
    for slot in DB["slots"].values():
        if (
            slot["route_id"] == route["id"]
            and slot["status"] in ("SCHEDULED", "OPEN", "FULL")
            and slot["_start_dt"] > t
        ):
            raise ApiError(
                "ERR_ROUTE_HAS_FUTURE_SLOTS",
                409,
                "Route has future non-cancelled slots",
            )
    route["status"] = "RETIRED"
    touch(route)
    return ok(ser_route(route))


@bp.get("/tour-routes/<rid>/script-versions")
def list_route_scripts(rid):
    auth(ALL_ROLES)
    route = lookup("routes", rid)
    items = sort_items(
        [s for s in DB["scripts"].values() if s["route_id"] == route["id"]]
    )
    return _paginate(items, ser_script)


@bp.post("/tour-routes/<rid>/script-versions")
def create_script(rid):
    auth(["Curator", "MuseumAdmin"])
    route = lookup("routes", rid)
    data = body()
    content_text = req_str(data, "content_text")
    standards = data.get("curriculum_standards")
    if standards is None:
        standards = []
    if not isinstance(standards, list) or not all(
        isinstance(x, str) for x in standards
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "curriculum_standards must be an array of strings",
        )
    existing = [s for s in DB["scripts"].values() if s["route_id"] == route["id"]]
    version_no = max((s["version_no"] for s in existing), default=0) + 1
    rec = {
        "id": new_id(),
        "route_id": route["id"],
        "version_no": version_no,
        "content_text": content_text,
        "curriculum_standards": list(standards),
        "status": "DRAFT",
        "accuracy_score": None,
        "reviewer_notes": None,
    }
    stamp(rec)
    DB["scripts"][rec["id"]] = rec
    return ok(ser_script(rec), 201)


@bp.get("/tour-routes/<rid>/tour-slots")
def list_route_slots(rid):
    auth(ALL_ROLES)
    route = lookup("routes", rid)
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in SLOT_STATUSES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid slot status filter")
    items = [s for s in DB["slots"].values() if s["route_id"] == route["id"]]
    if status_filter is not None:
        items = [s for s in items if s["status"] == status_filter]
    return _paginate(sort_items(items), ser_slot)


@bp.get("/tour-routes/<rid>/survey-summary")
def route_survey_summary(rid):
    auth(["MuseumAdmin", "Curator"])
    route = lookup("routes", rid)
    surveys = [
        s
        for s in DB["surveys"].values()
        if s["status"] in ("SUBMITTED", "REVIEWED")
        and DB["slots"].get(s["slot_id"]) is not None
        and DB["slots"][s["slot_id"]]["route_id"] == route["id"]
    ]
    count = len(surveys)
    if count:
        avg_overall = float(
            (
                Decimal(sum(s["overall_rating"] for s in surveys)) / Decimal(count)
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        avg_clarity = float(
            (
                Decimal(sum(s["interpretation_clarity"] for s in surveys))
                / Decimal(count)
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
    else:
        avg_overall = 0.0
        avg_clarity = 0.0
    return ok(
        {
            "survey_count": count,
            "avg_overall_rating": avg_overall,
            "avg_interpretation_clarity": avg_clarity,
        }
    )


@bp.get("/tour-routes/<rid>/docents")
def list_route_docents(rid):
    auth(["MuseumAdmin", "DocentCoordinator"])
    route = lookup("routes", rid)
    items = sort_items(
        [d for d in DB["docents"].values() if route["id"] in d["certified_route_ids"]]
    )
    return _paginate(items, ser_docent)
