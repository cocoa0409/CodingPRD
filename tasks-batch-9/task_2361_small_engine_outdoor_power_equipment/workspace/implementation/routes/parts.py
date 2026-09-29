"""Service parts, the supersession chain and repair-network fulfillment."""

from collections import OrderedDict

from flask import Blueprint

import calc
import store
import svc
import validation as v
from auth import endpoint, ALL_ROLES, user_id, user_role
from errors import ApiError
from response import list_response, object_response
from store import db, set_fields

bp = Blueprint("parts", __name__)

CATEGORIES = ("CARBURETOR_KIT", "IGNITION_MODULE", "BLADE_ASSEMBLY", "FILTER_KIT")
PART_STATUSES = ("ACTIVE", "SUPERSEDED", "OBSOLETE")
REQUEST_STATUSES = ("FILLED", "BACKORDERED", "SUBSTITUTED")
CHANNELS = ("DEALER", "MASS_RETAIL")


def _chain_length(part):
    """Number of supersession links reachable from `part`."""
    length = 0
    seen = {part["id"]}
    cursor = part
    while cursor is not None and cursor.get("superseded_by_part_id"):
        nxt = db.service_parts.get(cursor["superseded_by_part_id"])
        if nxt is None or nxt["id"] in seen:
            break
        seen.add(nxt["id"])
        length += 1
        cursor = nxt
    return length


def _reaches(start, target_id):
    seen = set()
    cursor = start
    while cursor is not None:
        if cursor["id"] == target_id:
            return True
        if cursor["id"] in seen:
            return False
        seen.add(cursor["id"])
        nxt_id = cursor.get("superseded_by_part_id")
        cursor = db.service_parts.get(nxt_id) if nxt_id else None
    return False


@bp.route("/service-parts", methods=["POST"])
@endpoint(["PlantAdmin"])
def create_part():
    payload = v.body()
    platform_id = v.id_field(payload, "engine_platform_id")
    part_number = v.string_field(payload, "part_number", 1, 30)
    category = v.enum_field(payload, "category", CATEGORIES)
    on_hand_qty = v.int_field(payload, "on_hand_qty", 0)
    committed_availability_years = v.int_field(payload, "committed_availability_years", 7)
    last_production_year = v.int_field(payload, "last_production_year", 2020, 2060)
    dealer_lead_time_days = v.int_field(
        payload, "dealer_lead_time_days", 1, 30, required=False, default=2
    )
    mass_retail_lead_time_days = v.int_field(
        payload, "mass_retail_lead_time_days", 1, 60, required=False, default=5
    )

    platform = svc.get_platform(platform_id)
    svc.require_unique(db.service_parts, "part_number", part_number)

    part = store.new_record(OrderedDict([
        ("engine_platform_id", platform["id"]),
        ("part_number", part_number),
        ("category", category),
        ("superseded_by_part_id", None),
        ("on_hand_qty", on_hand_qty),
        ("committed_availability_years", committed_availability_years),
        ("last_production_year", last_production_year),
        ("dealer_lead_time_days", dealer_lead_time_days),
        ("mass_retail_lead_time_days", mass_retail_lead_time_days),
        ("commitment_expires_year", last_production_year + committed_availability_years),
        ("filled_request_count", 0),
        ("substituted_request_count", 0),
        ("backordered_request_count", 0),
        ("fill_rate_pct", None),
        ("status", "ACTIVE"),
    ]))
    db.service_parts[part["id"]] = part
    return object_response(store.public(part), 201)


@bp.route("/service-parts/<part_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_part(part_id):
    part = svc.get_service_part(part_id)
    return object_response(store.public(part), 200)


@bp.route("/service-parts", methods=["GET"])
@endpoint(ALL_ROLES)
def list_parts():
    limit, offset = v.pagination()
    platform_id = v.query_string("engine_platform_id")
    superseded_by = v.query_string("superseded_by_part_id")
    status = v.query_enum("status", PART_STATUSES)
    category = v.query_enum("category", CATEGORIES)
    rows = store.sort_created_asc(list(db.service_parts.values()))
    if platform_id is not None:
        rows = [r for r in rows if r["engine_platform_id"] == platform_id]
    if superseded_by is not None:
        rows = [r for r in rows if r["superseded_by_part_id"] == superseded_by]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    page, total = v.paginate(rows, limit, offset)
    return list_response([store.public(r) for r in page], limit, offset, total)


@bp.route("/service-parts/<part_id>/supersede", methods=["POST"])
@endpoint(["PlantAdmin"])
def supersede_part(part_id):
    payload = v.body()
    successor_id = v.id_field(payload, "successor_part_id")

    part = svc.get_service_part(part_id)
    successor = svc.get_service_part(successor_id)

    if part["status"] != "ACTIVE":
        raise ApiError("ERR_PART_STATE_INVALID", "Only an ACTIVE part may be superseded.")
    if successor["status"] != "ACTIVE":
        raise ApiError("ERR_PART_STATE_INVALID", "The successor part must be ACTIVE.")
    if successor["engine_platform_id"] != part["engine_platform_id"]:
        raise ApiError(
            "ERR_PLATFORM_MISMATCH",
            "The successor must service the same engine platform.",
        )
    if successor["id"] == part["id"]:
        raise ApiError("ERR_SUPERSESSION_CYCLE", "A part may not supersede itself.")
    if _reaches(successor, part["id"]):
        raise ApiError(
            "ERR_SUPERSESSION_CYCLE",
            "The successor's chain loops back to the part being superseded.",
        )
    if 1 + _chain_length(successor) > calc.MAX_SUPERSESSION_DEPTH:
        raise ApiError(
            "ERR_SUPERSESSION_CYCLE",
            "The resulting supersession chain would exceed %d links."
            % calc.MAX_SUPERSESSION_DEPTH,
        )

    set_fields(part, status="SUPERSEDED", superseded_by_part_id=successor["id"])

    backorders = [
        r for r in svc.requests_of_part(part["id"])
        if r["status"] == "BACKORDERED" and r["service_part_id"] == part["id"]
    ]
    on_hand = successor["on_hand_qty"]
    for request_row in backorders:
        if on_hand >= request_row["requested_quantity"]:
            on_hand -= request_row["requested_quantity"]
            set_fields(
                request_row,
                status="SUBSTITUTED",
                shipped_from_part_id=successor["id"],
                promised_ship_date=svc.promised_date(
                    svc.lead_time_for(successor, request_row["channel"])
                ),
            )

    svc.recompute_part_metrics(part)
    svc.recompute_part_metrics(successor, on_hand_qty=on_hand)
    return object_response(store.public(part), 200)


@bp.route("/service-parts/<part_id>/obsolete", methods=["POST"])
@endpoint(["PlantAdmin"])
def obsolete_part(part_id):
    v.body()
    part = svc.get_service_part(part_id)
    if part["status"] not in ("ACTIVE", "SUPERSEDED"):
        raise ApiError("ERR_PART_STATE_INVALID", "The part is already OBSOLETE.")
    if store.clock_date().year <= part["commitment_expires_year"]:
        raise ApiError(
            "ERR_AVAILABILITY_COMMITMENT_ACTIVE",
            "The parts-availability commitment has not yet expired.",
        )
    if (part["backordered_request_count"] or 0) > 0:
        raise ApiError(
            "ERR_OPEN_BACKORDERS_EXIST",
            "The part still carries open backorders.",
        )
    set_fields(part, status="OBSOLETE")
    return object_response(store.public(part), 200)


@bp.route("/service-parts/<part_id>/requests", methods=["GET"])
@endpoint(ALL_ROLES)
def list_part_requests(part_id):
    limit, offset = v.pagination()
    status = v.query_enum("status", REQUEST_STATUSES)
    part = svc.get_service_part(part_id)
    rows = svc.requests_of_part(part["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if user_role() == "ChannelPartner":
        rows = [r for r in rows if r["requester_user_id"] == user_id()]
    page, total = v.paginate(rows, limit, offset)
    return list_response([store.public(r) for r in page], limit, offset, total)


@bp.route("/parts-requests", methods=["POST"])
@endpoint(["ChannelPartner"])
def create_request():
    payload = v.body()
    part_id = v.id_field(payload, "service_part_id")
    requested_quantity = v.int_field(payload, "requested_quantity", 1)
    channel = v.enum_field(payload, "channel", CHANNELS)

    part = svc.get_service_part(part_id)
    if part["status"] != "ACTIVE":
        raise ApiError(
            "ERR_PART_STATE_INVALID",
            "Only an ACTIVE service part may be requested.",
        )

    filled = part["on_hand_qty"] >= requested_quantity
    if filled:
        status = "FILLED"
        shipped_from = part["id"]
        promised = svc.promised_date(svc.lead_time_for(part, channel))
    else:
        status = "BACKORDERED"
        shipped_from = None
        promised = svc.promised_date(calc.BACKORDER_PROMISE_DAYS)

    request_row = store.new_record(OrderedDict([
        ("service_part_id", part["id"]),
        ("shipped_from_part_id", shipped_from),
        ("requested_quantity", requested_quantity),
        ("channel", channel),
        ("requester_user_id", user_id()),
        ("status", status),
        ("promised_ship_date", promised),
    ]))
    db.parts_requests[request_row["id"]] = request_row

    if filled:
        svc.recompute_part_metrics(
            part, on_hand_qty=part["on_hand_qty"] - requested_quantity
        )
    else:
        svc.recompute_part_metrics(part)

    return object_response(store.public(request_row), 201)
