"""MutualAidCrew endpoints: engage, get, list, mark_arrived, assign_lodging,
demobilize, depart, cancel."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db, parse_iso, iso_ms
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_EVENT_NOT_ACTIVE, ERR_OUTSIDE_ENGAGEMENT_WINDOW, ERR_CROSS_EVENT_LINK,
    ERR_LODGING_NOT_COMMITTED, ERR_WINDOW_OUTSIDE_BLOCK, ERR_NO_ROOMS_AVAILABLE,
)
from services.core import (
    get_body, req_string, req_enum, req_int, req_datetime, paginate,
    new_common, bump,
    get_event, get_ma_crew, get_block, serialize_ma_crew, sort_created_asc,
    post_ledger_entry, check_event_not_closed, block_rooms_allocated,
    CREW_TYPES, DEPARTURE_REASONS, EARLY_EXIT_PENALTY_PCT,
)

bp = Blueprint("mutual_aid_crews", __name__)


@bp.route("/om/mutual-aid-crews", methods=["POST"])
def create_ma_crew():
    require_roles(["MutualAidCoordinator"])
    body = get_body()
    event_id = req_string(body, "storm_event_id")
    event = get_event(event_id)
    company = req_string(body, "company_name")
    ctype = req_enum(body, "crew_type", CREW_TYPES)
    roster = req_int(body, "roster_size", minimum=1)
    county = req_string(body, "service_county_code")
    daily = req_int(body, "daily_rate_cents", minimum=0)
    per_diem = req_int(body, "per_diem_cents", minimum=0)
    win_start = req_datetime(body, "committed_window_start")
    win_end = req_datetime(body, "committed_window_end")
    if not (win_end > win_start):
        raise_err(ERR_INVALID_REQUEST,
                  "committed_window_end must be after committed_window_start")
    check_event_not_closed(event)
    c = new_common()
    c.update({
        "storm_event_id": event_id,
        "company_name": company,
        "crew_type": ctype,
        "roster_size": roster,
        "service_county_code": county,
        "daily_rate_cents": daily,
        "per_diem_cents": per_diem,
        "committed_window_start": body["committed_window_start"],
        "committed_window_end": body["committed_window_end"],
        "ma_status": "REQUESTED",
        "arrived_at": None,
        "departed_at": None,
        "lodging_block_id": None,
        "engagement_cost_cents": None,
    })
    db.mutual_aid_crews[c["id"]] = c
    return success_object(serialize_ma_crew(c), status=201)


@bp.route("/om/mutual-aid-crews/<mid>", methods=["GET"])
def get_one(mid):
    require_roles(ALL_ROLES)
    c = get_ma_crew(mid)
    return success_object(serialize_ma_crew(c))


@bp.route("/om/mutual-aid-crews", methods=["GET"])
def list_ma_crews():
    require_roles(ALL_ROLES)
    items = list(db.mutual_aid_crews.values())
    event_id = request.args.get("storm_event_id")
    block_id = request.args.get("lodging_block_id")
    status = request.args.get("ma_status")
    if event_id is not None:
        items = [c for c in items if c["storm_event_id"] == event_id]
    if block_id is not None:
        items = [c for c in items if c.get("lodging_block_id") == block_id]
    if status is not None:
        items = [c for c in items if c["ma_status"] == status]
    items = sort_created_asc(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_ma_crew(c) for c in page], limit, offset, total)


@bp.route("/om/mutual-aid-crews/<mid>/mark_arrived", methods=["POST"])
def mark_arrived(mid):
    require_roles(["MutualAidCoordinator"])
    c = get_ma_crew(mid)
    if c["ma_status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Mutual-aid crew in {c['ma_status']} cannot arrive")
    event = get_event(c["storm_event_id"])
    check_event_not_closed(event)
    if event["event_status"] != "ACTIVE":
        raise_err(ERR_EVENT_NOT_ACTIVE, "Arrival requires the event ACTIVE")
    now = db.now()
    ws = parse_iso(c["committed_window_start"])
    we = parse_iso(c["committed_window_end"])
    if not (ws <= now < we):
        raise_err(ERR_OUTSIDE_ENGAGEMENT_WINDOW,
                  "Logical now is outside the committed engagement window")
    c["ma_status"] = "AVAILABLE"
    c["arrived_at"] = iso_ms(now)
    bump(c)
    return success_object(serialize_ma_crew(c))


@bp.route("/om/mutual-aid-crews/<mid>/assign_lodging", methods=["POST"])
def assign_lodging(mid):
    require_roles(["MutualAidCoordinator"])
    c = get_ma_crew(mid)
    body = get_body()
    block_id = req_string(body, "lodging_block_id")
    block = get_block(block_id)
    if c["ma_status"] not in ("AVAILABLE",):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Mutual-aid crew in {c['ma_status']} cannot be assigned lodging")
    event = get_event(c["storm_event_id"])
    check_event_not_closed(event)
    # Block must be COMMITTED.
    if block["block_status"] != "COMMITTED":
        raise_err(ERR_LODGING_NOT_COMMITTED, "Lodging block is not COMMITTED")
    # Same storm event.
    if block["storm_event_id"] != c["storm_event_id"]:
        raise_err(ERR_CROSS_EVENT_LINK, "Lodging block and crew belong to different events")
    # Crew window contained in block window.
    cws = parse_iso(c["committed_window_start"])
    cwe = parse_iso(c["committed_window_end"])
    bws = parse_iso(block["window_start"])
    bwe = parse_iso(block["window_end"])
    if cws < bws or cwe > bwe:
        raise_err(ERR_WINDOW_OUTSIDE_BLOCK,
                  "Crew committed window is not contained in the block window")
    # Capacity: rooms_allocated + roster_size <= room_count.
    allocated = block_rooms_allocated(block["id"])
    if allocated + c["roster_size"] > block["room_count"]:
        raise_err(ERR_NO_ROOMS_AVAILABLE, "Not enough rooms available in the block")

    # Record the assignment fact for later cost allocation.
    db.lodging_assignments.append({
        "block_id": block["id"],
        "crew_id": c["id"],
        "roster_size": c["roster_size"],
        "window_start": c["committed_window_start"],
        "window_end": c["committed_window_end"],
        "created_at": iso_ms(db.now()),
        "_mono": db.next_mono(),
    })
    c["lodging_block_id"] = block["id"]
    bump(c)
    bump(block)
    return success_object(serialize_ma_crew(c))


@bp.route("/om/mutual-aid-crews/<mid>/demobilize", methods=["POST"])
def demobilize(mid):
    require_roles(["MutualAidCoordinator"])
    c = get_ma_crew(mid)
    if c["ma_status"] != "AVAILABLE":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Mutual-aid crew in {c['ma_status']} cannot demobilize")
    # No in-flight work: no assigned WO in DISPATCHED or IN_PROGRESS.
    for w in db.work_orders.values():
        if w.get("assigned_mutual_aid_crew_id") == mid and \
                w["execution_status"] in ("DISPATCHED", "IN_PROGRESS"):
            raise_err(ERR_INVALID_STATE_TRANSITION,
                      "Crew has in-flight work orders")
    c["ma_status"] = "DEMOBILIZING"
    # Release lodging.
    if c.get("lodging_block_id"):
        block = db.lodging_blocks.get(c["lodging_block_id"])
        c["lodging_block_id"] = None
        if block is not None:
            bump(block)  # rooms_allocated is derived from crew assignments
    bump(c)
    return success_object(serialize_ma_crew(c))


@bp.route("/om/mutual-aid-crews/<mid>/depart", methods=["POST"])
def depart(mid):
    require_roles(["MutualAidCoordinator"])
    c = get_ma_crew(mid)
    body = get_body()
    reason = req_enum(body, "departure_reason", DEPARTURE_REASONS)
    if c["ma_status"] != "DEMOBILIZING":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Mutual-aid crew in {c['ma_status']} cannot depart")
    event = get_event(c["storm_event_id"])
    check_event_not_closed(event)

    now = db.now()
    c["ma_status"] = "DEPARTED"
    c["departed_at"] = iso_ms(now)

    # Engagement cost per mutual_aid_engagement_cost.
    daily_cost = c["daily_rate_cents"] + c["roster_size"] * c["per_diem_cents"]
    ws = parse_iso(c["committed_window_start"])
    we = parse_iso(c["committed_window_end"])
    arrived = parse_iso(c["arrived_at"]) if c.get("arrived_at") else ws
    billable_start = max(ws, arrived)
    actual_seconds = (now - billable_start).total_seconds()
    actual_days = max(1, math.ceil(actual_seconds / 86400.0)) if actual_seconds > 0 else 1
    labor_amount = actual_days * daily_cost

    penalty = 0
    if reason == "EARLY_RELEASE" and now < we:
        remaining_seconds = (we - now).total_seconds()
        remaining_days = math.ceil(remaining_seconds / 86400.0) if remaining_seconds > 0 else 0
        pen_dec = (Decimal(remaining_days) * Decimal(c["daily_rate_cents"])
                   * EARLY_EXIT_PENALTY_PCT)
        penalty = int(pen_dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    c["engagement_cost_cents"] = labor_amount + penalty
    bump(c)

    post_ledger_entry(
        storm_event_id=c["storm_event_id"], work_order_id=None,
        entry_type="LABOR_MUTUAL_AID", cost_class="O_AND_M",
        county_code=c["service_county_code"], amount_cents=labor_amount,
    )
    if penalty > 0:
        post_ledger_entry(
            storm_event_id=c["storm_event_id"], work_order_id=None,
            entry_type="MUTUAL_AID_PENALTY", cost_class="O_AND_M",
            county_code=c["service_county_code"], amount_cents=penalty,
        )
    return success_object(serialize_ma_crew(c))


@bp.route("/om/mutual-aid-crews/<mid>/cancel", methods=["POST"])
def cancel(mid):
    require_roles(["MutualAidCoordinator"])
    c = get_ma_crew(mid)
    if c["ma_status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Mutual-aid crew in {c['ma_status']} cannot be cancelled")
    c["ma_status"] = "CANCELLED"
    bump(c)
    return success_object(serialize_ma_crew(c))
