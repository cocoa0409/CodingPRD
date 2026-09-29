"""Seat holds: placement, manual release and reads."""
from flask import Blueprint

import calc
from core import (ROLE_ADMIN, ROLE_SALES, READ_ROLES, apply_filters, bad_request, body, bump,
                  base_fields, db, endpoint, err, find_account, find_hold, find_seat, new_id, now,
                  ok, ok_page, opt_str, pagination, paginate, req_datetime, req_enum, req_int,
                  req_str, sort_created)
from routes_accounts import gate_account_written_off, gate_rep_ownership
from routes_setup import gate_selling

bp = Blueprint("holds", __name__)

HOLD_TYPES = ("RENEWAL_HOLD", "UPGRADE_HOLD", "GROUP_HOLD", "ORDER_HOLD")


def covering_hold(seat_id, instant):
    for hold in db.holds.values():
        if hold["seat_id"] != seat_id or hold["hold_status"] != "ACTIVE":
            continue
        if hold["hold_window_start_utc"] <= instant < hold["hold_window_end_utc"]:
            return hold
    return None


def seat_free_for_account(seat, account_id):
    """Order/relocation seat freedom (ladder rung 12)."""
    if seat.get("assigned_account_id") is not None:
        return False
    status = calc.effective_seat_status(seat)
    if status == "AVAILABLE":
        return True
    hold = covering_hold(seat["id"], now())
    return hold is not None and hold["account_id"] == account_id


def release_hold(hold, reason, status="RELEASED"):
    hold["hold_status"] = status
    hold["released_reason"] = reason
    bump(hold)


@bp.route("/ticketing/seat-holds", methods=["POST"])
@endpoint(ROLE_SALES, ROLE_ADMIN)
def create_hold(caller):
    data = body()
    seat_id = req_str(data, "seat_id")
    account_id = req_str(data, "account_id")
    hold_type = req_enum(data, "hold_type", HOLD_TYPES)
    window_start = req_datetime(data, "hold_window_start_utc")
    window_end = req_datetime(data, "hold_window_end_utc")
    expected_seat_version = req_int(data, "expected_seat_version")
    if not (window_end > window_start):
        bad_request("Field 'hold_window_end_utc' must be strictly after 'hold_window_start_utc'.")

    seat = find_seat(seat_id)
    account = find_account(account_id)
    gate_rep_ownership(caller, account)

    season = calc.season_of_seat(seat)
    gate_selling(season)

    if calc.effective_seat_status(seat) != "AVAILABLE":
        err("ERR_SEAT_NOT_AVAILABLE", 409, "The seat is not available.")

    gate_account_written_off(account)

    if expected_seat_version != seat["version"]:
        err("ERR_STALE_SEAT_VERSION", 412, "The seat has been modified since it was read.")

    for existing in db.holds.values():
        if existing["seat_id"] != seat_id or existing["hold_status"] != "ACTIVE":
            continue
        if window_start < existing["hold_window_end_utc"] and existing["hold_window_start_utc"] < window_end:
            err("ERR_HOLD_WINDOW_CONFLICT", 409, "The requested window intersects an ACTIVE hold.")

    if hold_type == "RENEWAL_HOLD" and not (now() < season["renewal_deadline_utc"]):
        err("ERR_RENEWAL_DEADLINE_PASSED", 422, "The renewal deadline has passed.")

    row = {"id": new_id(), "seat_id": seat_id, "account_id": account_id, "origin_order_id": None,
           "hold_type": hold_type, "hold_window_start_utc": window_start,
           "hold_window_end_utc": window_end, "hold_status": "ACTIVE", "released_reason": None}
    row.update(base_fields())
    db.holds[row["id"]] = row

    calc.run_census(season)
    if hold_type == "RENEWAL_HOLD":
        account["renewal_priority_active"] = True
        bump(account)
    bump(seat)
    bump(season)
    return ok(row, 201)


@bp.route("/ticketing/seat-holds/<hold_id>/release", methods=["POST"])
@endpoint(ROLE_SALES, ROLE_ADMIN)
def do_release_hold(caller, hold_id):
    data = body()
    reason = opt_str(data, "release_reason")
    hold = find_hold(hold_id)
    if hold["hold_status"] != "ACTIVE":
        err("ERR_HOLD_NOT_ACTIVE", 409, "Only an ACTIVE hold may be released.")

    release_hold(hold, reason)
    seat = db.seats.get(hold["seat_id"])
    season = calc.season_of_seat(seat) if seat else None
    calc.run_census(season)
    account = db.accounts.get(hold["account_id"])
    if hold["hold_type"] == "RENEWAL_HOLD" and account is not None:
        before = account["renewal_priority_active"]
        calc.refresh_renewal_priority(account)
        if before != account["renewal_priority_active"]:
            bump(account)
    if seat is not None:
        bump(seat)
    return ok(hold)


@bp.route("/ticketing/seat-holds/<hold_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def get_hold(caller, hold_id):
    return ok(find_hold(hold_id))


@bp.route("/ticketing/seat-holds", methods=["GET"])
@endpoint(*READ_ROLES)
def list_holds(caller):
    limit, offset = pagination()
    rows = apply_filters(list(db.holds.values()), [
        ("seat_id", "seat_id"), ("account_id", "account_id"),
        ("origin_order_id", "origin_order_id"), ("hold_status", "hold_status")])
    rows = sort_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_page(page, limit, offset, total)
