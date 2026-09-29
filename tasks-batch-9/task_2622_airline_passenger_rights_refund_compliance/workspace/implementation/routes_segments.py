"""Flight segments: creation, disruption declaration and operational events (PRD 3.1, 3.2)."""

from flask import Blueprint, request

import calc
import ledger
from auth import ADMIN, AUDITOR, OFFICER, OPS, PASSENGER, authorize, own_booking
from envelope import created, listing, ok
from errors import ApiError
from store import S, new_row, serialize, touch
from validation import field, json_body, must_exist, page, pagination, validate

bp = Blueprint("segments", __name__)

SEGMENT_SPEC = [
    field("sequence_index", "int", True, min=1),
    field("flight_number", "string", True, min_len=3, max_len=7),
    field("origin_iata", "string", True, exact_len=3, pattern="upper_alpha"),
    field("destination_iata", "string", True, exact_len=3, pattern="upper_alpha"),
    field("is_international", "bool", False),
    field("scheduled_departure_utc", "datetime", True),
    field("scheduled_arrival_utc", "datetime", True),
    field("segment_fare_cents", "int", True, cents=True, min=0),
]


@bp.post("/compliance/bookings/<booking_id>/flight-segments")
def add_segment(booking_id):
    authorize([ADMIN, OPS])
    booking = must_exist("booking", booking_id)
    body = json_body()
    data = validate(body, SEGMENT_SPEC)
    if data["scheduled_arrival_utc"] <= data["scheduled_departure_utc"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "scheduled_arrival_utc must be strictly after scheduled_departure_utc.",
        )

    for existing in calc.segments_of(booking_id):
        if existing["sequence_index"] == data["sequence_index"]:
            raise ApiError("ERR_DUPLICATE_SEQUENCE_INDEX")

    row = new_row(
        {
            "booking_id": booking_id,
            "sequence_index": data["sequence_index"],
            "flight_number": data["flight_number"],
            "origin_iata": data["origin_iata"],
            "destination_iata": data["destination_iata"],
            "is_international": data.get("is_international", False),
            "scheduled_departure_utc": data["scheduled_departure_utc"],
            "scheduled_arrival_utc": data["scheduled_arrival_utc"],
            "segment_fare_cents": data["segment_fare_cents"],
            "status": "SCHEDULED",
            "disruption_type": "NONE",
            "revised_arrival_utc": None,
            "delay_minutes": 0,
            "is_significant_delay": False,
            "disruption_declared_at_utc": None,
            "actual_departure_utc": None,
            "actual_arrival_utc": None,
            "cumulative_tarmac_minutes": 0,
            "exempted_tarmac_event_count": 0,
        }
    )
    S.flight_segments[row["id"]] = row
    ledger.bump_booking(booking)
    return created(serialize(row))


@bp.get("/compliance/flight-segments/<segment_id>")
def read_segment(segment_id):
    authorize([ADMIN, OFFICER, OPS, AUDITOR, PASSENGER])
    row = must_exist("flight_segment", segment_id)
    return ok(serialize(row))


@bp.get("/compliance/flight-segments/<segment_id>/tarmac-delay-events")
def list_segment_tarmac_events(segment_id):
    authorize([ADMIN, OPS, AUDITOR])
    must_exist("flight_segment", segment_id)
    limit, offset = pagination()
    rows = calc.events_of(segment_id)
    for param in ("status", "phase"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    total = len(rows)
    return listing([serialize(r) for r in page(rows, limit, offset)], limit, offset, total)


DISRUPTION_SPEC = [
    field("disruption_type", "enum", True, values=["DELAY", "CANCELLATION"]),
    field("declared_at_utc", "datetime", True),
    field("revised_arrival_utc", "datetime", False),
]


def _mint_fare_obligation(booking, segment):
    """Proactive FARE obligation for a disrupted leg, or a suppression tick."""
    if ledger.live_obligation_for(booking["id"], "FARE", "flight_segment_id", segment["id"]):
        ledger.suppress(booking)
        return None
    gross = calc.fare_gross_proactive(booking)
    row = ledger.mint_obligation(
        booking,
        "FARE",
        "PROACTIVE",
        "PROACTIVE_FULL_ITINERARY",
        gross,
        segment["disruption_declared_at_utc"],
        source_field="flight_segment_id",
        source_id=segment["id"],
        cascade=True,
    )
    if row is None:
        ledger.suppress(booking)
    return row


@bp.post("/compliance/flight-segments/<segment_id>/declare-disruption")
def declare_disruption(segment_id):
    authorize([OPS, ADMIN])
    segment = must_exist("flight_segment", segment_id)
    body = json_body()
    data = validate(body, DISRUPTION_SPEC)

    disruption_type = data["disruption_type"]
    revised = data.get("revised_arrival_utc")
    if disruption_type == "DELAY" and revised is None:
        raise ApiError("ERR_INVALID_REQUEST", "revised_arrival_utc is required for a DELAY.")
    if disruption_type == "CANCELLATION" and revised is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "revised_arrival_utc must not be supplied for a CANCELLATION."
        )

    if segment["status"] not in ("SCHEDULED", "DELAYED"):
        raise ApiError("ERR_SEGMENT_STATE_INVALID")

    booking = S.bookings[segment["booking_id"]]
    policy = calc.policy_of(booking)

    if disruption_type == "DELAY":
        new_delay = calc.whole_minutes(segment["scheduled_arrival_utc"], revised)
        if segment["status"] == "DELAYED" and new_delay <= segment["delay_minutes"]:
            raise ApiError("ERR_DELAY_NOT_WORSENED")
        if revised <= segment["scheduled_arrival_utc"]:
            raise ApiError("ERR_REVISED_ARRIVAL_INVALID")

        segment["status"] = "DELAYED"
        segment["disruption_type"] = "DELAY"
        segment["revised_arrival_utc"] = revised
        segment["disruption_declared_at_utc"] = data["declared_at_utc"]
        segment["delay_minutes"] = new_delay
        segment["is_significant_delay"] = calc.significant_delay(segment, policy, new_delay)
        touch(segment)

        if segment["is_significant_delay"]:
            if not ledger.live_obligation_for(
                booking["id"], "FARE", "flight_segment_id", segment["id"]
            ):
                gross = calc.fare_gross_proactive(booking)
                row = ledger.mint_obligation(
                    booking,
                    "FARE",
                    "PROACTIVE",
                    "PROACTIVE_FULL_ITINERARY",
                    gross,
                    segment["disruption_declared_at_utc"],
                    source_field="flight_segment_id",
                    source_id=segment["id"],
                    cascade=True,
                )
                if row is None:
                    ledger.suppress(booking)
        ledger.bump_booking(booking)
        return ok(serialize(segment))

    # ---- CANCELLATION: the deepest cascade, links in a fixed order ----
    # Link one
    segment["status"] = "CANCELLED"
    segment["disruption_type"] = "CANCELLATION"
    segment["disruption_declared_at_utc"] = data["declared_at_utc"]
    segment["delay_minutes"] = 0
    segment["revised_arrival_utc"] = None
    segment["is_significant_delay"] = False
    touch(segment)

    # Link two-a: downstream siblings, ascending sequence_index
    for sibling in calc.segments_of(booking["id"]):
        if sibling["id"] == segment["id"]:
            continue
        if sibling["sequence_index"] <= segment["sequence_index"]:
            continue
        if sibling["status"] != "SCHEDULED":
            continue
        sibling["status"] = "DISRUPTED_UNUSED"
        sibling["disruption_declared_at_utc"] = segment["disruption_declared_at_utc"]
        touch(sibling)

    # Link two-b: undelivered ancillaries on the cancelled leg, ascending created_at
    voided_ancillaries = []
    for purchase in calc.ancillaries_of(booking["id"]):
        if purchase["flight_segment_id"] != segment["id"]:
            continue
        if purchase["delivery_status"] != "PENDING_DELIVERY":
            continue
        purchase["delivery_status"] = "NOT_PROVIDED"
        purchase["non_provision_reason"] = "SERVICE_CANCELLED"
        touch(purchase)
        voided_ancillaries.append(purchase)

    # Link three-a: the fare obligation for the cancelled leg
    _mint_fare_obligation(booking, segment)

    # Link three-b: one face-value obligation per just-cancelled ancillary
    for purchase in voided_ancillaries:
        row = ledger.mint_obligation(
            booking,
            "ANCILLARY",
            "PROACTIVE",
            "FEE_FACE_VALUE",
            purchase["amount_cents"],
            segment["disruption_declared_at_utc"],
            source_field="ancillary_purchase_id",
            source_id=purchase["id"],
            cascade=True,
        )
        if row is None:
            ledger.suppress(booking)
        else:
            purchase["refund_obligation_created"] = True

    # Link four: the booking rollup, exactly one version bump for the whole request
    ledger.bump_booking(booking)
    return ok(serialize(segment))


OPERATION_SPEC = [
    field("operation", "enum", True, values=["DEPARTED", "ARRIVED", "RESTORED"]),
    field("occurred_at_utc", "datetime", True),
]


@bp.post("/compliance/flight-segments/<segment_id>/record-operation")
def record_operation(segment_id):
    authorize([OPS, ADMIN])
    segment = must_exist("flight_segment", segment_id)
    body = json_body()
    data = validate(body, OPERATION_SPEC)
    operation = data["operation"]
    occurred = data["occurred_at_utc"]
    booking = S.bookings[segment["booking_id"]]

    if operation == "DEPARTED":
        if segment["status"] not in ("SCHEDULED", "DELAYED"):
            raise ApiError("ERR_SEGMENT_STATE_INVALID")
        for sibling in calc.segments_of(booking["id"]):
            if sibling["sequence_index"] >= segment["sequence_index"]:
                continue
            if sibling["status"] not in (
                "DEPARTED",
                "ARRIVED",
                "CANCELLED",
                "DISRUPTED_UNUSED",
            ):
                raise ApiError("ERR_SEGMENT_STATE_INVALID")
        segment["status"] = "DEPARTED"
        segment["actual_departure_utc"] = occurred
        touch(segment)
        ledger.bump_booking(booking)
        return ok(serialize(segment))

    if operation == "ARRIVED":
        if segment["status"] != "DEPARTED":
            raise ApiError("ERR_SEGMENT_STATE_INVALID")
        if segment["actual_departure_utc"] is None or occurred <= segment["actual_departure_utc"]:
            raise ApiError("ERR_SEGMENT_STATE_INVALID")
        segment["status"] = "ARRIVED"
        segment["actual_arrival_utc"] = occurred
        touch(segment)
        # a service flown as sold is a service delivered
        for purchase in calc.ancillaries_of(booking["id"]):
            if purchase["flight_segment_id"] != segment["id"]:
                continue
            if purchase["delivery_status"] != "PENDING_DELIVERY":
                continue
            purchase["delivery_status"] = "DELIVERED"
            touch(purchase)
        ledger.bump_booking(booking)
        return ok(serialize(segment))

    # RESTORED
    if segment["status"] != "DELAYED" or segment["disruption_type"] != "DELAY":
        raise ApiError("ERR_SEGMENT_STATE_INVALID")
    segment["status"] = "SCHEDULED"
    segment["disruption_type"] = "NONE"
    segment["revised_arrival_utc"] = None
    segment["delay_minutes"] = 0
    segment["is_significant_delay"] = False
    segment["disruption_declared_at_utc"] = None
    touch(segment)
    ledger.bump_booking(booking)
    return ok(serialize(segment))
