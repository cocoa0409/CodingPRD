"""DynoBooking and DynoTestRun endpoints."""

import uuid

from flask import Blueprint, request

from db import db
from errors import (
    ApiError, ERR_ORDER_NOT_FOUND, ERR_BOOKING_NOT_FOUND, ERR_DYNO_RUN_NOT_FOUND,
    ERR_ORDER_NOT_IN_DYNO_QUEUE, ERR_NO_ACTIVE_DYNO_BOOKING,
    ERR_BOOKING_IN_PAST, ERR_DYNO_CELL_OVERLAP, ERR_DYNO_ATTEMPT_EXHAUSTED,
    ERR_INVALID_REQUEST,
)
from middleware import require_role
from response import success
from services.allocation import release_reservations, promotion_scan
from services.calculations import compute_dyno_score, MAX_DYNO_ATTEMPTS
from services.serializers import booking_view, run_view
from validators import (
    get_json_body, require_fields, check_string, invalid, parse_iso8601,
    parse_limit_offset, paginate,
)

bp = Blueprint("dyno", __name__)


# ---------------- DynoBooking ----------------

@bp.post("/api/dyno-bookings")
def create_booking():
    require_role({"RemanTechnician"})
    body = get_json_body()
    require_fields(body, ["reman_order_id", "dyno_cell_code", "start_utc", "end_utc"])
    check_string(body["reman_order_id"], "reman_order_id")
    check_string(body["dyno_cell_code"], "dyno_cell_code")
    start = parse_iso8601(body["start_utc"], "start_utc")
    end = parse_iso8601(body["end_utc"], "end_utc")
    if end <= start:
        invalid("end_utc must be > start_utc")

    order = db.reman_orders.get(body["reman_order_id"])
    if order is None:
        raise ApiError(ERR_ORDER_NOT_FOUND, "RemanOrder id does not exist", 404)

    if order["status"] != "DYNO_QUEUE":
        raise ApiError(
            ERR_ORDER_NOT_IN_DYNO_QUEUE,
            "dyno booking requires status DYNO_QUEUE",
            409,
        )
    if end <= db.now():
        raise ApiError(
            ERR_BOOKING_IN_PAST,
            "dyno booking end_utc is not after the current logical time",
            422,
        )
    # Half-open overlap on the same cell: [start, end) vs [start, end).
    for b in db.dyno_bookings.values():
        if b["dyno_cell_code"] != body["dyno_cell_code"]:
            continue
        if b["status"] != "BOOKED":
            continue
        if start < b["end_utc"] and b["start_utc"] < end:
            raise ApiError(
                ERR_DYNO_CELL_OVERLAP,
                "half-open dyno window overlaps an existing BOOKED window on the same cell",
                409,
            )

    bk = {
        "id": str(uuid.uuid4()),
        "reman_order_id": order["id"],
        "dyno_cell_code": body["dyno_cell_code"],
        "start_utc": start,
        "end_utc": end,
        "status": "BOOKED",
        "created_at": db.now(),
    }
    db.dyno_bookings[bk["id"]] = bk
    return success(booking_view(bk), "object", 201)


@bp.get("/api/dyno-bookings")
def list_bookings():
    require_role({"Any"})
    items = list(db.dyno_bookings.values())
    oid = request.args.get("reman_order_id")
    cell = request.args.get("dyno_cell_code")
    if oid is not None:
        items = [b for b in items if b["reman_order_id"] == oid]
    if cell is not None:
        items = [b for b in items if b["dyno_cell_code"] == cell]
    items.sort(key=lambda b: b["created_at"])
    limit, offset = parse_limit_offset(request.args)
    page, pg = paginate(items, limit, offset)
    return success([booking_view(b) for b in page], "array", 200, pg)


@bp.get("/api/dyno-bookings/<bid>")
def get_booking(bid):
    require_role({"Any"})
    b = db.dyno_bookings.get(bid)
    if b is None:
        raise ApiError(ERR_BOOKING_NOT_FOUND, "DynoBooking id does not exist", 404)
    return success(booking_view(b), "object", 200)


# ---------------- DynoTestRun ----------------

@bp.post("/api/dyno-test-runs")
def create_run():
    require_role({"DynoOperator"})
    body = get_json_body()
    require_fields(body, ["reman_order_id", "gear_pressures_kpa"])
    check_string(body["reman_order_id"], "reman_order_id")
    pressures = body["gear_pressures_kpa"]
    if not isinstance(pressures, list):
        invalid("Field gear_pressures_kpa must be an array")

    order = db.reman_orders.get(body["reman_order_id"])
    if order is None:
        raise ApiError(ERR_ORDER_NOT_FOUND, "RemanOrder id does not exist", 404)

    targets = sorted(order["pinned_spec"]["dyno_targets"], key=lambda t: t["gear"])
    if len(pressures) != len(targets):
        invalid("gear_pressures_kpa length must match pinned dyno_targets length")
    for v in pressures:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            invalid("gear_pressures_kpa entries must be numbers")

    # State gates in order: order status, covering booking, attempt budget.
    if order["status"] != "DYNO_QUEUE":
        raise ApiError(
            ERR_ORDER_NOT_IN_DYNO_QUEUE,
            "dyno run requires status DYNO_QUEUE",
            409,
        )
    now = db.now()
    covering = None
    for b in db.dyno_bookings.values():
        if (
            b["reman_order_id"] == order["id"]
            and b["status"] == "BOOKED"
            and b["start_utc"] <= now < b["end_utc"]
        ):
            covering = b
            break
    if covering is None:
        raise ApiError(
            ERR_NO_ACTIVE_DYNO_BOOKING,
            "no BOOKED DynoBooking for this order covers the current logical time",
            409,
        )
    if order["dyno_attempts_used"] >= MAX_DYNO_ATTEMPTS:
        raise ApiError(
            ERR_DYNO_ATTEMPT_EXHAUSTED,
            "dyno_attempts_used already equals MAX_DYNO_ATTEMPTS (3)",
            422,
        )

    score, verdict = compute_dyno_score(pressures, order["pinned_spec"]["dyno_targets"])
    prior_runs = sum(
        1 for r in db.dyno_test_runs.values() if r["reman_order_id"] == order["id"]
    )
    run = {
        "id": str(uuid.uuid4()),
        "reman_order_id": order["id"],
        "dyno_booking_id": covering["id"],
        "attempt_number": prior_runs + 1,
        "gear_pressures_kpa": pressures,
        "shift_quality_score": score,
        "verdict": verdict,
        "created_at": now,
    }
    db.dyno_test_runs[run["id"]] = run

    order["dyno_attempts_used"] += 1
    order["last_shift_quality_score"] = score

    if verdict == "PASS":
        order["status"] = "DYNO_PASSED"
    elif verdict == "MARGINAL":
        # Stays in DYNO_QUEUE; cal_status stays VERIFIED.
        pass
    else:  # FAIL
        if run["attempt_number"] < MAX_DYNO_ATTEMPTS:
            order["status"] = "REWORK"
            if order["cal_status"] == "VERIFIED":
                order["cal_status"] = "SUPERSEDED"
        else:
            # Third fail: terminal ENGINEERING_REVIEW with release + promotion.
            order["status"] = "ENGINEERING_REVIEW"
            if order["cal_status"] == "VERIFIED":
                order["cal_status"] = "SUPERSEDED"
            release_reservations(order)
            order["updated_at"] = now
            order["version"] += 1
            promotion_scan()
            return success(run_view(run), "object", 201)
    order["updated_at"] = now
    order["version"] += 1
    return success(run_view(run), "object", 201)


@bp.get("/api/dyno-test-runs")
def list_runs():
    require_role({"Any"})
    items = list(db.dyno_test_runs.values())
    oid = request.args.get("reman_order_id")
    bid = request.args.get("dyno_booking_id")
    if oid is not None:
        items = [r for r in items if r["reman_order_id"] == oid]
    if bid is not None:
        items = [r for r in items if r["dyno_booking_id"] == bid]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_limit_offset(request.args)
    page, pg = paginate(items, limit, offset)
    return success([run_view(r) for r in page], "array", 200, pg)


@bp.get("/api/dyno-test-runs/<rid>")
def get_run(rid):
    require_role({"Any"})
    r = db.dyno_test_runs.get(rid)
    if r is None:
        raise ApiError(ERR_DYNO_RUN_NOT_FOUND, "DynoTestRun id does not exist", 404)
    return success(run_view(r), "object", 200)
