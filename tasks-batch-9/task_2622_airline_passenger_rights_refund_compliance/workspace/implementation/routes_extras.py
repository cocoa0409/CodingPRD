"""Ancillary purchases and checked bags (PRD 3.3)."""

from flask import Blueprint, request

import calc
import ledger
from auth import ADMIN, AUDITOR, OFFICER, PASSENGER, authorize
from envelope import created, listing, ok
from errors import ApiError
from store import S, new_row, serialize, touch
from validation import body_fk, field, json_body, must_exist, page, pagination, validate

bp = Blueprint("extras", __name__)

SERVICE_TYPES = ["SEAT_SELECTION", "WIFI", "ENTERTAINMENT", "PRIORITY_BOARDING", "LOUNGE_ACCESS"]
NON_PROVISION_REASONS = ["EQUIPMENT_SWAP", "SYSTEM_OUTAGE", "SEAT_REASSIGNED", "SERVICE_CANCELLED"]

ANCILLARY_SPEC = [
    field("booking_id", "string", True),
    field("flight_segment_id", "string", True),
    field("service_type", "enum", True, values=SERVICE_TYPES),
    field("amount_cents", "int", True, cents=True, min=1),
]


@bp.post("/compliance/ancillary-purchases")
def create_ancillary():
    authorize([ADMIN, OFFICER])
    body = json_body()
    booking = body_fk(body, "booking_id", "booking")
    segment = body_fk(body, "flight_segment_id", "flight_segment")
    data = validate(body, ANCILLARY_SPEC)
    if segment["booking_id"] != booking["id"]:
        raise ApiError("ERR_SEGMENT_BOOKING_MISMATCH")

    row = new_row(
        {
            "booking_id": booking["id"],
            "flight_segment_id": segment["id"],
            "service_type": data["service_type"],
            "amount_cents": data["amount_cents"],
            "delivery_status": "PENDING_DELIVERY",
            "non_provision_reason": None,
            "refund_obligation_created": False,
            # Internal: the mark-not-provided instant, the obligation clock start
            # for an ANCILLARY basis (PRD 3.6). Never serialized.
            "_occurred_at_utc": None,
        }
    )
    S.ancillary_purchases[row["id"]] = row
    ledger.bump_booking(booking)
    return created(serialize(row))


@bp.get("/compliance/ancillary-purchases")
def list_ancillaries():
    authorize([ADMIN, OFFICER, AUDITOR, PASSENGER])
    limit, offset = pagination()
    rows = sorted(S.ancillary_purchases.values(), key=lambda r: r["_seq"])
    for param in ("booking_id", "flight_segment_id", "service_type", "delivery_status"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    total = len(rows)
    return listing([serialize(r) for r in page(rows, limit, offset)], limit, offset, total)


@bp.get("/compliance/ancillary-purchases/<purchase_id>")
def read_ancillary(purchase_id):
    authorize([ADMIN, OFFICER, AUDITOR, PASSENGER])
    row = must_exist("ancillary_purchase", purchase_id)
    return ok(serialize(row))


NOT_PROVIDED_SPEC = [
    field("non_provision_reason", "enum", True, values=NON_PROVISION_REASONS),
    field("occurred_at_utc", "datetime", True),
]


@bp.post("/compliance/ancillary-purchases/<purchase_id>/mark-not-provided")
def mark_not_provided(purchase_id):
    authorize([OFFICER, ADMIN])
    purchase = must_exist("ancillary_purchase", purchase_id)
    body = json_body()
    data = validate(body, NOT_PROVIDED_SPEC)

    if purchase["delivery_status"] != "PENDING_DELIVERY":
        raise ApiError("ERR_ANCILLARY_STATE_INVALID")
    segment = S.flight_segments.get(purchase["flight_segment_id"])
    if segment is not None and segment["status"] == "ARRIVED":
        raise ApiError("ERR_ANCILLARY_STATE_INVALID")

    booking = S.bookings[purchase["booking_id"]]
    purchase["delivery_status"] = "NOT_PROVIDED"
    purchase["non_provision_reason"] = data["non_provision_reason"]
    purchase["_occurred_at_utc"] = data["occurred_at_utc"]
    touch(purchase)

    row = ledger.mint_obligation(
        booking,
        "ANCILLARY",
        "PROACTIVE",
        "FEE_FACE_VALUE",
        purchase["amount_cents"],
        data["occurred_at_utc"],
        source_field="ancillary_purchase_id",
        source_id=purchase["id"],
        cascade=True,
    )
    if row is None:
        ledger.suppress(booking)
    else:
        purchase["refund_obligation_created"] = True
    ledger.bump_booking(booking)
    return ok(serialize(purchase))


BAG_SPEC = [
    field("booking_id", "string", True),
    field("tag_number", "string", True, exact_len=10),
    field("fee_cents", "int", True, cents=True, min=0),
    field("checked_at_utc", "datetime", True),
    field("scheduled_delivery_utc", "datetime", True),
]


@bp.post("/compliance/checked-bags")
def create_bag():
    authorize([ADMIN, OFFICER])
    body = json_body()
    booking = body_fk(body, "booking_id", "booking")
    data = validate(body, BAG_SPEC)
    if data["scheduled_delivery_utc"] <= data["checked_at_utc"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "scheduled_delivery_utc must be strictly after checked_at_utc.",
        )
    for existing in S.checked_bags.values():
        if existing["tag_number"] == data["tag_number"]:
            raise ApiError("ERR_DUPLICATE_TAG_NUMBER")

    row = new_row(
        {
            "booking_id": booking["id"],
            "tag_number": data["tag_number"],
            "fee_cents": data["fee_cents"],
            "checked_at_utc": data["checked_at_utc"],
            "scheduled_delivery_utc": data["scheduled_delivery_utc"],
            "delivered_at_utc": None,
            "loss_declared_at_utc": None,
            "status": "IN_TRANSIT",
            "delivery_delay_hours": 0,
            "fee_refund_obligated": False,
        }
    )
    S.checked_bags[row["id"]] = row
    ledger.bump_booking(booking)
    return created(serialize(row))


RESOLVE_SPEC = [
    field("resolution", "enum", True, values=["DELIVERED", "DECLARED_LOST"]),
    field("delivered_at_utc", "datetime", False),
    field("loss_declared_at_utc", "datetime", False),
]


def _mint_bag_obligation(booking, bag, start_instant):
    row = ledger.mint_obligation(
        booking,
        "BAGGAGE_FEE",
        "PROACTIVE",
        "FEE_FACE_VALUE",
        bag["fee_cents"],
        start_instant,
        source_field="checked_bag_id",
        source_id=bag["id"],
        cascade=True,
    )
    if row is None:
        ledger.suppress(booking)
    else:
        bag["fee_refund_obligated"] = True
    return row


@bp.post("/compliance/checked-bags/<bag_id>/resolve")
def resolve_bag(bag_id):
    authorize([OFFICER, ADMIN])
    bag = must_exist("checked_bag", bag_id)
    body = json_body()
    data = validate(body, RESOLVE_SPEC)
    resolution = data["resolution"]

    if resolution == "DELIVERED" and data.get("delivered_at_utc") is None:
        raise ApiError("ERR_INVALID_REQUEST", "delivered_at_utc is required for a DELIVERED resolution.")
    if resolution == "DECLARED_LOST" and data.get("loss_declared_at_utc") is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "loss_declared_at_utc is required for a DECLARED_LOST resolution."
        )

    if bag["status"] != "IN_TRANSIT":
        raise ApiError("ERR_BAG_STATE_INVALID")

    instant = (
        data["delivered_at_utc"] if resolution == "DELIVERED" else data["loss_declared_at_utc"]
    )
    if instant < bag["checked_at_utc"]:
        raise ApiError("ERR_DELIVERY_BEFORE_CHECKIN")

    booking = S.bookings[bag["booking_id"]]
    policy = calc.policy_of(booking)

    if resolution == "DELIVERED":
        delay_hours = calc.hours_2dp(bag["scheduled_delivery_utc"], instant)
        threshold = calc.bag_threshold_hours(booking, policy)
        bag["delivered_at_utc"] = instant
        bag["delivery_delay_hours"] = delay_hours
        late = delay_hours >= threshold
        bag["status"] = "DELIVERED_LATE" if late else "DELIVERED_ON_TIME"
        touch(bag)
        if late:
            _mint_bag_obligation(booking, bag, instant)
            ledger.bump_booking(booking)
        # An on-time delivery owes nothing, so no booking link runs (PRD 3.3).
    else:
        bag["loss_declared_at_utc"] = instant
        bag["status"] = "DECLARED_LOST"
        touch(bag)
        _mint_bag_obligation(booking, bag, instant)
        ledger.bump_booking(booking)

    return ok(serialize(bag))
