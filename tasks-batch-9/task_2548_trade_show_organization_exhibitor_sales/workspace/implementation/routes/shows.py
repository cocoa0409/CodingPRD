"""Show lifecycle endpoints (PRD 3.1, 3.2, 3.4, 3.9)."""
from flask import Blueprint

import calc
import guards
import services
import validate
import views
from db import add_days, base_row, by_created, db, fmt_date, parse_date, touch
from errors import ApiError
from middleware import (EXHIBITOR, FLOOR_MANAGER, SALES_REP, SHOW_DIRECTOR, authenticate)
from response import created, object_response

bp = Blueprint("shows", __name__)

TRANSITIONS = {
    "SELLING": ("SPACE_SELECTION",),
    "ON_SITE": ("SELLING",),
    "CLOSED": ("ON_SITE",),
    "CANCELLED": ("PLANNING", "SPACE_SELECTION", "SELLING", "ON_SITE"),
}


def _buffered(show):
    move_in = parse_date(show["move_in_start"])
    move_out = parse_date(show["move_out_end"])
    return (add_days(move_in, -calc.DARK_DAY_BUFFER_DAYS),
            add_days(move_out, calc.DARK_DAY_BUFFER_DAYS))


@bp.route("/shows", methods=["POST"])
def create_show():
    body = validate.body()
    venue_contract_id = validate.text(body, "venue_contract_id", 1, None)
    name = validate.text(body, "name", 1, 120)
    edition_year = validate.integer(body, "edition_year", minimum=2026)
    move_in_start = validate.date_field(body, "move_in_start")
    event_start = validate.date_field(body, "event_start")
    event_end = validate.date_field(body, "event_end")
    move_out_end = validate.date_field(body, "move_out_end")
    gross_sqft = validate.integer(body, "gross_sqft", minimum=1)
    aisle_ratio_pct = validate.integer(body, "aisle_ratio_pct", minimum=0, maximum=90)
    base_rate = validate.integer(body, "base_rate_cents_per_sqft", minimum=1)
    desk_capacity = validate.integer(body, "selection_desk_capacity", minimum=1)

    authenticate((SHOW_DIRECTOR,))
    venue_contract = guards.get_venue_contract(venue_contract_id)
    guards.require_venue_executed(venue_contract)

    if aisle_ratio_pct < venue_contract["min_aisle_ratio_pct"]:
        raise ApiError("ERR_AISLE_RATIO_VIOLATION",
                       "aisle_ratio_pct may not fall below the hall minimum")
    if gross_sqft > venue_contract["hall_gross_sqft"]:
        validate.bad("gross_sqft may not exceed the hall's hall_gross_sqft")

    if not (move_in_start <= event_start <= event_end <= move_out_end):
        raise ApiError("ERR_INVALID_SHOW_WINDOW", "the four show dates must be non-decreasing")

    first_year = venue_contract["contract_year_start"]
    last_year = first_year + venue_contract["contract_year_count"] - 1
    if (not (first_year <= move_in_start.year <= last_year)
            or not (first_year <= move_out_end.year <= last_year)
            or edition_year != event_start.year):
        raise ApiError("ERR_SHOW_OUTSIDE_CONTRACT_TERM",
                       "the occupancy window falls outside the agreement term")

    new_start = add_days(move_in_start, -calc.DARK_DAY_BUFFER_DAYS)
    new_end = add_days(move_out_end, calc.DARK_DAY_BUFFER_DAYS)
    for other in db.shows.values():
        if other["status"] not in ("PLANNING", "SPACE_SELECTION", "SELLING",
                                   "ON_SITE", "CLOSED"):
            continue
        other_contract = db.venue_contracts.get(other["venue_contract_id"])
        if other_contract is None:
            continue
        if (other_contract["venue_code"] != venue_contract["venue_code"]
                or other_contract["hall_code"] != venue_contract["hall_code"]):
            continue
        other_start, other_end = _buffered(other)
        if new_start <= other_end and other_start <= new_end:
            raise ApiError("ERR_HALL_OCCUPANCY_CONFLICT",
                           "the buffered occupancy window overlaps another edition")

    row = base_row()
    row.update({
        "venue_contract_id": venue_contract["id"],
        "name": name,
        "edition_year": edition_year,
        "move_in_start": fmt_date(move_in_start),
        "event_start": fmt_date(event_start),
        "event_end": fmt_date(event_end),
        "move_out_end": fmt_date(move_out_end),
        "gross_sqft": gross_sqft,
        "aisle_ratio_pct": aisle_ratio_pct,
        "base_rate_cents_per_sqft": base_rate,
        "selection_desk_capacity": desk_capacity,
        "status": "PLANNING",
        "selection_round": 0,
        "net_sellable_sqft": 0,
        "advance_order_deadline": None,
        "attrition_shortfall_sqft": 0,
        "attrition_settlement_cents": 0,
        "cancellation_reason": None,
    })
    db.shows[row["id"]] = row
    touch(venue_contract)
    return created(views.show_view(row))


@bp.route("/shows/<show_id>", methods=["GET"])
def read_show(show_id):
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, EXHIBITOR))
    show = guards.get_show(show_id)
    return object_response(views.show_view(show))


@bp.route("/shows/<show_id>/publish-floor-plan", methods=["POST"])
def publish_floor_plan(show_id):
    authenticate((SHOW_DIRECTOR,))
    show = guards.get_show(show_id)
    venue_contract = db.venue_contracts[show["venue_contract_id"]]
    guards.require_venue_executed(venue_contract)
    guards.require_show_status(show, ("PLANNING",))
    if show["aisle_ratio_pct"] < venue_contract["min_aisle_ratio_pct"]:
        raise ApiError("ERR_AISLE_RATIO_VIOLATION",
                       "aisle_ratio_pct may not fall below the hall minimum")
    live_booths = [b for b in calc.show_booths(show["id"]) if b["status"] != "MERGED"]
    if not live_booths:
        raise ApiError("ERR_FLOOR_PLAN_EMPTY", "the floor plan has no unmerged booths")
    booth_area = sum(b["area_sqft"] for b in live_booths)
    if booth_area > calc.sellable_area(show):
        raise ApiError("ERR_FLOOR_INVENTORY_OVERCOMMITTED",
                       "booth area exceeds the show's sellable area")
    show["net_sellable_sqft"] = calc.sellable_area(show)
    show["advance_order_deadline"] = fmt_date(calc.advance_order_deadline(show))
    show["status"] = "SPACE_SELECTION"
    touch(show)
    return object_response(views.show_view(show))


@bp.route("/shows/<show_id>/transition", methods=["POST"])
def transition_show(show_id):
    body = validate.body()
    target_status = validate.enum(body, "target_status",
                                  ("SELLING", "ON_SITE", "CLOSED", "CANCELLED"))
    cancellation_reason = validate.text(body, "cancellation_reason", 1, 500,
                                        required=False, default=None)

    authenticate((SHOW_DIRECTOR,))
    show = guards.get_show(show_id)
    if show["status"] not in TRANSITIONS[target_status]:
        raise ApiError("ERR_INVALID_SHOW_TRANSITION",
                       "%s is not reachable from %s" % (target_status, show["status"]))
    if target_status == "SELLING":
        if any(a["state"] == "ACTIVE" for a in calc.show_appointments(show["id"])):
            raise ApiError("ERR_INVALID_SHOW_TRANSITION",
                           "a selection appointment is still ACTIVE")

    if target_status == "SELLING":
        show["status"] = "SELLING"
        # "On success, every appointment of the show still in state SCHEDULED
        # transitions to EXPIRED with no penalty" (PRD 3.4).
        for appointment in by_created(calc.show_appointments(show["id"])):
            if appointment["state"] == "SCHEDULED":
                appointment["state"] = "EXPIRED"
                touch(appointment)
        touch(show)
    elif target_status == "ON_SITE":
        show["status"] = "ON_SITE"
        touch(show)
    elif target_status == "CLOSED":
        services.close_show(show)
    else:
        services.cancel_show(show, cancellation_reason)
    return object_response(views.show_view(show))


@bp.route("/shows/<show_id>/advance-selection-round", methods=["POST"])
def advance_selection_round(show_id):
    authenticate((SHOW_DIRECTOR, SALES_REP))
    show = guards.get_show(show_id)
    guards.require_show_status(show, ("SPACE_SELECTION",))
    services.advance_selection_round(show)
    return object_response(views.show_view(show))


@bp.route("/shows/<show_id>/post-show-report", methods=["GET"])
def post_show_report(show_id):
    authenticate((SHOW_DIRECTOR, SALES_REP))
    show = guards.get_show(show_id)
    guards.require_show_closed(show)
    return object_response(calc.post_show_report(show))
