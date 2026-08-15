"""CrewCall endpoints: post under a stop, list, settle/cancel."""

from flask import Blueprint

import db
from db import touch
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_STOP_INVALID_STATE, ERR_CREW_INVALID_STATE,
                    ERR_CREW_COMPLEMENT_SHORT)
from middleware import authenticate, require_roles
from response import success, success_list
from services import domain, calc
from util import (get_body, reject_unknown, require_present, as_enum,
                  parse_iso_datetime, paginate)

bp = Blueprint("crew_calls", __name__)

CALL_TYPES = ("LOAD_IN", "LOAD_OUT", "SHOW_RUN")
CREW_STATUSES = ("POSTED", "SETTLED", "CANCELLED")


def _validate_lines(lines):
    """lines: non-empty array of {position, rate_cents_per_hour}; unique positions."""
    if not isinstance(lines, list) or len(lines) == 0:
        raise err(ERR_INVALID_REQUEST, 400, "lines must be a non-empty array")
    seen = set()
    for i, line in enumerate(lines):
        if not isinstance(line, dict) or set(line.keys()) != {"position", "rate_cents_per_hour"}:
            raise err(ERR_INVALID_REQUEST, 400,
                      "Each line must carry exactly position and rate_cents_per_hour")
        pos = line["position"]
        if not isinstance(pos, str):
            raise err(ERR_INVALID_REQUEST, 400, "line position must be a string")
        rate = line["rate_cents_per_hour"]
        if isinstance(rate, bool) or not isinstance(rate, int) or rate < 0:
            raise err(ERR_INVALID_REQUEST, 400,
                      "line rate_cents_per_hour must be a non-negative integer")
        if pos in seen:
            raise err(ERR_INVALID_REQUEST, 400,
                      "line positions must be unique within the call")
        seen.add(pos)
    return lines


def _validate_actual_lines(actual_lines, planned):
    """actual_lines positions must match the planned positions exactly (1:1)."""
    if not isinstance(actual_lines, list):
        raise err(ERR_INVALID_REQUEST, 400, "actual_lines must be an array")
    planned_positions = {l["position"] for l in planned}
    seen = set()
    for entry in actual_lines:
        if not isinstance(entry, dict) or set(entry.keys()) != {"position", "hours_worked"}:
            raise err(ERR_INVALID_REQUEST, 400,
                      "Each actual line must carry exactly position and hours_worked")
        pos = entry["position"]
        hours = entry["hours_worked"]
        if not isinstance(pos, str) \
                or isinstance(hours, bool) or not isinstance(hours, (int, float)) \
                or hours < 0:
            raise err(ERR_INVALID_REQUEST, 400,
                      "actual line entries require a position and non-negative hours_worked")
        if pos in seen:
            raise err(ERR_INVALID_REQUEST, 400,
                      "actual_lines positions must be unique")
        seen.add(pos)
    if seen != planned_positions:
        raise err(ERR_INVALID_REQUEST, 400,
                  "actual_lines positions must match the planned lines exactly")
    return actual_lines


@bp.route("/stops/<stop_id>/crew-calls", methods=["POST"])
def create_crew_call(stop_id):
    _, role = authenticate()
    require_roles(role, ("TourManager",))
    stop = db.stops.get(stop_id)
    if stop is None:
        raise err(ERR_NOT_FOUND, 404, "Stop not found")
    body = get_body()
    reject_unknown(body, {"call_type", "scheduled_start", "lines"})
    call_type = as_enum(require_present(body, "call_type"), "call_type", CALL_TYPES)
    sched_raw = require_present(body, "scheduled_start")
    parse_iso_datetime(sched_raw, "scheduled_start")  # shape validation
    lines = _validate_lines(require_present(body, "lines"))
    # State (priority 5): post only while ADVANCED | READY | PLAYING.
    if stop["booking_status"] not in ("ADVANCED", "READY", "PLAYING"):
        raise err(ERR_STOP_INVALID_STATE, 409,
                  "Crew calls may be posted only while ADVANCED, READY or PLAYING")
    # Crew complement (priority 6): a satisfied CREW_MINIMUM check floors the
    # line count; the venue's crew_available caps it.
    for c in domain.checks_of_stop(stop_id):
        if c["item"] == "CREW_MINIMUM" and c["status"] in ("PASS", "WAIVED"):
            if len(lines) < c["required_value"]:
                raise err(ERR_CREW_COMPLEMENT_SHORT, 422,
                          "Lines below the satisfied CREW_MINIMUM requirement")
    venue = db.venues[stop["venue_id"]]
    if len(lines) > venue["crew_available"]:
        raise err(ERR_CREW_COMPLEMENT_SHORT, 422,
                  "Lines exceed the venue's crew_available")
    rec = db.new_record()
    rec.update({
        "stop_id": stop_id,
        "call_type": call_type,
        "scheduled_start": sched_raw,
        "lines": lines,
        "actual_lines": None,
        "total_pay_cents": None,
        "cancellation_penalty_cents": None,
        "status": "POSTED",
    })
    db.crew_calls[rec["id"]] = rec
    return success(db.serialize("crew_call", rec), 201)


@bp.route("/stops/<stop_id>/crew-calls", methods=["GET"])
def list_crew_calls(stop_id):
    authenticate()
    if db.stops.get(stop_id) is None:
        raise err(ERR_NOT_FOUND, 404, "Stop not found")
    items = sorted(domain.crew_of_stop(stop_id), key=lambda c: c["_seq"])
    data, total, limit, offset = paginate(items, lambda r: db.serialize("crew_call", r))
    return success_list(data, total, limit, offset, 200)


@bp.route("/crew-calls/<cc_id>", methods=["PUT"])
def put_crew_call(cc_id):
    _, role = authenticate()
    require_roles(role, ("TourManager",))
    cc = db.crew_calls.get(cc_id)
    if cc is None:
        raise err(ERR_NOT_FOUND, 404, "Crew call not found")
    body = get_body()
    reject_unknown(body, {"status", "actual_lines"})
    target = as_enum(require_present(body, "status"), "status", CREW_STATUSES)
    if target == "POSTED":
        raise err(ERR_CREW_INVALID_STATE, 409, "No crew-call transition to POSTED")
    actual = None
    if target == "SETTLED":
        # actual_lines presence + position match are request shape (priority 4).
        actual = _validate_actual_lines(require_present(body, "actual_lines"),
                                        cc["lines"])
    if cc["status"] != "POSTED":
        raise err(ERR_CREW_INVALID_STATE, 409,
                  "SETTLED/CANCELLED are only reachable from POSTED")
    if target == "SETTLED":
        rates = {l["position"]: l["rate_cents_per_hour"] for l in cc["lines"]}
        cc["actual_lines"] = actual
        # Round once per line, then sum (calc_crew_call_pay).
        cc["total_pay_cents"] = sum(
            calc.crew_line_pay(a["hours_worked"], rates[a["position"]])
            for a in actual)
        cc["status"] = "SETTLED"
    else:  # CANCELLED
        sched = parse_iso_datetime(cc["scheduled_start"], "scheduled_start")
        cc["cancellation_penalty_cents"] = calc.crew_cancellation_penalty(
            cc["lines"], sched, db.logical_clock["dt"])
        cc["status"] = "CANCELLED"
    touch(cc)
    return success(db.serialize("crew_call", cc), 200)
