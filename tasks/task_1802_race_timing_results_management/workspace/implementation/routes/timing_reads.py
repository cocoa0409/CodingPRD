from flask import Blueprint, request

import db
from db import next_seq
from errors import ApiError, ERR_DUPLICATE_READ, ERR_READ_INGEST_CLOSED
from middleware import endpoint
from response import ok
from serializers import ser_timing_read
from services import recompute as engine
from util import fmt_dt
from clock import now
import uuid
from validators import get_body, get_or_404, list_page, v_dt

bp = Blueprint("timing_reads", __name__)

_READERS = ("RaceDirector", "TimingOperator", "RaceOfficial")
_INGEST_STATES = ("IN_PROGRESS", "PROVISIONAL_PUBLISHED", "AMENDMENT_OPEN")


@bp.post("/race-timing/timing-reads")
@endpoint("TimingOperator")
def ingest_read():
    body = get_body(("timing_point_id", "chip_id", "read_timestamp"))
    # body identifiers resolve left to right
    point = get_or_404(db.timing_points, body.get("timing_point_id"))
    chip = get_or_404(db.chips, body.get("chip_id"))
    read_dt = v_dt(body, "read_timestamp")

    race = db.races.get(point["race_id"])
    # ingest gate before deduplication
    if race is None or race["status"] not in _INGEST_STATES:
        raise ApiError(
            ERR_READ_INGEST_CLOSED,
            409,
            "The race is not accepting timing reads in its current state",
        )
    for r in db.timing_reads.values():
        if (
            r["timing_point_id"] == point["id"]
            and r["chip_id"] == chip["id"]
            and r["read_timestamp"] == read_dt
        ):
            raise ApiError(
                ERR_DUPLICATE_READ,
                409,
                "An identical read (point, chip, timestamp) is already on the log",
            )

    # classification at ingest
    reg = db.registrations.get(chip["current_registration_id"] or "")
    scored = (
        reg is not None
        and reg["lifecycle_status"] == "CHECKED_IN"
        and reg["race_id"] == point["race_id"]
    )
    read = {
        "id": str(uuid.uuid4()),
        "created_at": fmt_dt(now()),
        "_seq": next_seq(),
        "timing_point_id": point["id"],
        "chip_id": chip["id"],
        "read_timestamp": read_dt,
        "status": "SCORED" if scored else "REJECTED",
        "reject_reason": None if scored else "CHIP_NOT_CHECKED_IN",
        "adjusted_by_correction_id": None,
    }
    db.timing_reads[read["id"]] = read

    if scored:
        engine.pace_check(reg, point, read_dt, chip["id"], read["id"])
    return ok(ser_timing_read(read), 201)


@bp.get("/race-timing/timing-reads/<read_id>")
@endpoint(*_READERS)
def get_read(read_id):
    return ok(ser_timing_read(get_or_404(db.timing_reads, read_id)))


@bp.get("/race-timing/timing-reads")
@endpoint(*_READERS)
def list_reads():
    items = list(db.timing_reads.values())
    for param in (
        "timing_point_id",
        "chip_id",
        "status",
        "adjusted_by_correction_id",
    ):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    return list_page(items, ser_timing_read)
