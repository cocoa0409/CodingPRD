"""Denied boarding records: the statutory ladder and informed consent (PRD 3.4)."""

from flask import Blueprint, request

import calc
import ledger
from auth import ADMIN, AUDITOR, OFFICER, OPS, authorize
from envelope import created, listing, ok
from errors import ApiError
from store import S, new_row, serialize, touch
from validation import body_fk, field, json_body, must_exist, page, pagination, validate

bp = Blueprint("denied", __name__)

RECORD_SPEC = [
    field("booking_id", "string", True),
    field("flight_segment_id", "string", True),
    field("category", "enum", True, values=["VOLUNTARY", "INVOLUNTARY"]),
    field("oversale_confirmed", "bool", False),
    field("written_disclosure_provided", "bool", False),
    field("one_way_fare_cents", "int", True, cents=True, min=1),
    field("substitute_arrival_utc", "datetime", True),
    field("voluntary_agreed_amount_cents", "int", False, cents=True, min=0),
]


@bp.post("/compliance/denied-boarding-records")
def create_record():
    authorize([OFFICER, ADMIN])
    body = json_body()
    booking = body_fk(body, "booking_id", "booking")
    segment = body_fk(body, "flight_segment_id", "flight_segment")
    data = validate(body, RECORD_SPEC)

    category = data["category"]
    agreed = data.get("voluntary_agreed_amount_cents")
    if category == "VOLUNTARY" and agreed is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "voluntary_agreed_amount_cents is required for a VOLUNTARY denied boarding.",
        )
    if category == "INVOLUNTARY" and agreed is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "voluntary_agreed_amount_cents must not be supplied for an INVOLUNTARY denied boarding.",
        )

    if data["substitute_arrival_utc"] < segment["scheduled_arrival_utc"]:
        raise ApiError("ERR_SUBSTITUTE_BEFORE_SCHEDULED")
    if segment["booking_id"] != booking["id"]:
        raise ApiError("ERR_SEGMENT_BOOKING_MISMATCH")

    delay_minutes = calc.whole_minutes(
        segment["scheduled_arrival_utc"], data["substitute_arrival_utc"]
    )
    if delay_minutes < 0:
        delay_minutes = 0

    row = new_row(
        {
            "booking_id": booking["id"],
            "flight_segment_id": segment["id"],
            "category": category,
            "oversale_confirmed": data.get("oversale_confirmed", True),
            "written_disclosure_provided": data.get("written_disclosure_provided", False),
            "one_way_fare_cents": data["one_way_fare_cents"],
            "substitute_arrival_utc": data["substitute_arrival_utc"],
            "voluntary_agreed_amount_cents": agreed,
            "substitute_delay_minutes": delay_minutes,
            "statutory_compensation_cents": 0,
            "compensation_cents": 0,
            "effective_category": None,
            "status": "RECORDED",
            "finalized_at_utc": None,
        }
    )
    S.denied_boarding_records[row["id"]] = row
    return created(serialize(row))


@bp.get("/compliance/denied-boarding-records")
def list_records():
    authorize([ADMIN, OFFICER, OPS, AUDITOR])
    limit, offset = pagination()
    rows = sorted(S.denied_boarding_records.values(), key=lambda r: r["_seq"])
    for param in ("booking_id", "flight_segment_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    declared = request.args.get("category")
    if declared is None:
        declared = request.args.get("declared_category")
    if declared is not None:
        rows = [r for r in rows if r["category"] == declared]
    total = len(rows)
    return listing([serialize(r) for r in page(rows, limit, offset)], limit, offset, total)


@bp.get("/compliance/denied-boarding-records/<record_id>")
def read_record(record_id):
    authorize([ADMIN, OFFICER, OPS, AUDITOR])
    row = must_exist("denied_boarding_record", record_id)
    return ok(serialize(row))


FINALIZE_SPEC = [field("finalized_at_utc", "datetime", True)]


@bp.post("/compliance/denied-boarding-records/<record_id>/finalize")
def finalize_record(record_id):
    authorize([OFFICER, ADMIN])
    record = must_exist("denied_boarding_record", record_id)
    body = json_body()
    data = validate(body, FINALIZE_SPEC)

    if record["status"] != "RECORDED":
        raise ApiError("ERR_DENIED_BOARDING_STATE_INVALID")

    segment = S.flight_segments[record["flight_segment_id"]]
    booking = S.bookings[record["booking_id"]]

    statutory = calc.statutory_ladder(
        record["one_way_fare_cents"],
        record["substitute_delay_minutes"],
        segment["is_international"],
    )
    effective = calc.resolve_effective_category(record)

    if effective == "VOLUNTARY":
        floor = calc.voluntary_floor(statutory)
        agreed = record["voluntary_agreed_amount_cents"] or 0
        if agreed < floor:
            raise ApiError("ERR_VOLUNTARY_BELOW_DISCLOSURE_FLOOR")
        compensation = agreed
        variant = "VOLUNTARY_NEGOTIATED"
    else:
        compensation = statutory
        variant = "INVOLUNTARY_STATUTORY"

    record["statutory_compensation_cents"] = statutory
    record["effective_category"] = effective
    record["compensation_cents"] = compensation
    record["finalized_at_utc"] = data["finalized_at_utc"]
    record["status"] = "FINALIZED" if effective == record["category"] else "RECATEGORIZED"
    touch(record)

    row = ledger.mint_obligation(
        booking,
        "DENIED_BOARDING",
        "PROACTIVE",
        variant,
        compensation,
        record["finalized_at_utc"],
        source_field="denied_boarding_record_id",
        source_id=record["id"],
        cascade=True,
    )
    if row is None:
        ledger.suppress(booking)
    ledger.bump_booking(booking)
    return ok(serialize(record))
