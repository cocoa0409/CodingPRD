"""Rooming-list transmissions and hotel pickup reports (PRD §3.6)."""

from flask import Blueprint

import calc
import serializers as ser
import validators as V
from auth import authenticate
from envelope import created, ok_list, paginate
from errors import fail
from store import STORE, base_record, clock_iso, parse_iso_date, touch

bp = Blueprint("reporting", __name__, url_prefix="/housing")

TRANSMISSION_TYPES = ("INITIAL", "CHANGE", "FINAL")
PICKUP_SOURCES = ("HOTEL",)
REPORT_READ_ROLES = ["BureauCoordinator", "BureauController", "EventOrganizer", "HotelManager"]


@bp.post("/hotel-blocks/<block_id>/rooming-lists")
def transmit_rooming_list(block_id):
    authenticate(["BureauCoordinator"])
    body = V.json_body()
    transmission_type = V.field_enum(body, "transmission_type", TRANSMISSION_TYPES)

    block = V.get_block(block_id)

    history = calc.transmissions_of_block(block["id"])
    included = calc.rooming_list_transmission_set(block)

    # step 24 — a non-empty computed set is required before the type is judged.
    if not included:
        fail("ERR_NO_TRANSMITTABLE_RESERVATIONS", "no reservation is awaiting transmission")

    # step 25 — type legality against the block's history and status
    if transmission_type == "INITIAL" and history:
        fail("ERR_INVALID_TRANSMISSION_TYPE", "the block has already transmitted a batch")
    if transmission_type == "CHANGE" and not history:
        fail("ERR_INVALID_TRANSMISSION_TYPE", "a CHANGE batch requires a prior transmission")
    if transmission_type == "FINAL" and block["status"] not in ("CUTOFF_PASSED", "CLOSED"):
        fail(
            "ERR_INVALID_TRANSMISSION_TYPE",
            "a FINAL batch requires the block to be CUTOFF_PASSED or CLOSED",
        )

    record = base_record(mutable=False)
    record.update(
        {
            "hotel_block_id": block["id"],
            "transmission_type": transmission_type,
            "batch_seq": len(history) + 1,
            "reservation_count": len(included),
            "transmitted_at": clock_iso(),
            "included_reservation_ids": [r["id"] for r in included],
        }
    )
    STORE.transmissions[record["id"]] = record

    for reservation in included:
        reservation["transmission_status"] = "TRANSMITTED"
        touch(reservation)

    return created(ser.transmission_out(record))


@bp.get("/hotel-blocks/<block_id>/rooming-lists")
def list_rooming_lists(block_id):
    authenticate(REPORT_READ_ROLES)
    limit, offset = V.pagination_args()
    block = V.get_block(block_id)

    items = calc.transmissions_of_block(block["id"])
    page, pagination = paginate(items, limit, offset)
    return ok_list([ser.transmission_out(t) for t in page], pagination)


@bp.post("/hotel-blocks/<block_id>/pickup-reports")
def file_pickup_report(block_id):
    principal = authenticate(["HotelManager"])
    body = V.json_body()

    as_of_date = V.field_date(body, "as_of_date")
    rooms_picked_up = V.field_int(body, "reported_rooms_picked_up", minimum=0)
    room_nights = V.field_int(body, "reported_room_nights", minimum=0)
    gross_revenue = V.field_int(body, "reported_gross_revenue_cents", minimum=0)
    source = V.field_enum(body, "source", PICKUP_SOURCES, required=False, default="HOTEL")

    block = V.get_block(block_id)

    # step 6 — only the owning property files pickup
    if block["hotel_id"] != principal.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "the acting hotel does not own this block")

    # step 28 — the cumulative snapshot sequence strictly increases
    history = calc.pickup_reports_of_block(block["id"])
    if history and parse_iso_date(as_of_date) <= parse_iso_date(history[-1]["as_of_date"]):
        fail(
            "ERR_PICKUP_REPORT_OUT_OF_ORDER",
            "as_of_date must be strictly later than %s" % history[-1]["as_of_date"],
        )

    record = base_record(mutable=False)
    record.update(
        {
            "hotel_block_id": block["id"],
            "as_of_date": as_of_date,
            "reported_rooms_picked_up": rooms_picked_up,
            "reported_room_nights": room_nights,
            "reported_gross_revenue_cents": gross_revenue,
            "source": source,
        }
    )
    STORE.pickup_reports[record["id"]] = record
    # Filing a report changes nothing else.
    return created(ser.pickup_report_out(record))


@bp.get("/hotel-blocks/<block_id>/pickup-reports")
def list_pickup_reports(block_id):
    authenticate(REPORT_READ_ROLES)
    limit, offset = V.pagination_args()
    block = V.get_block(block_id)

    items = calc.pickup_reports_of_block(block["id"])
    page, pagination = paginate(items, limit, offset)
    return ok_list([ser.pickup_report_out(p) for p in page], pagination)
