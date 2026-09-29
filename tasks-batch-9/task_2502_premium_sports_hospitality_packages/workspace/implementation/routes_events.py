"""Logical clock, operations rollover and the Event lifecycle (PRD 3.1, 3.8, 3.9)."""
from flask import Blueprint, g

import calc
import services
from auth import (
    CLIENT_PORTAL_USER,
    CLIENT_SERVICE_AGENT,
    COMMERCIAL_DIRECTOR,
    COMMERCIAL_MANAGER,
    FINANCE_CONTROLLER,
    OPERATIONS_MANAGER,
    RIGHTS_MANAGER,
    guard,
)
from common import get_event
from errors import ERR_INVALID_EVENT_STATE, fail
from response import object_response
from store import (
    apply_silent,
    create_record,
    db,
    event_json,
    logical_now,
    set_logical_now,
    touch,
    update_record,
)
from util import fmt_ts, plus_days
from validation import (
    bad,
    body,
    opt_datetime,
    req_datetime,
    req_enum,
    req_string,
    req_string_array,
    query_filter,
)

bp = Blueprint("events", __name__)

SPORTS = ("FOOTBALL", "BASKETBALL", "MOTORSPORT", "TENNIS", "RUGBY")
ALL_ROLES = (
    RIGHTS_MANAGER,
    COMMERCIAL_MANAGER,
    COMMERCIAL_DIRECTOR,
    CLIENT_SERVICE_AGENT,
    OPERATIONS_MANAGER,
    FINANCE_CONTROLLER,
    CLIENT_PORTAL_USER,
)


# --- logical clock ----------------------------------------------------------


@bp.route("/_clock/set_current_utc", methods=["POST"])
@guard(OPERATIONS_MANAGER)
def set_clock():
    data = body()
    moment = req_datetime(data, "current_utc")
    set_logical_now(moment)
    return object_response({"current_utc": fmt_ts(logical_now())})


# --- operations rollover ----------------------------------------------------


@bp.route("/operations/daily-run", methods=["POST"])
@guard(OPERATIONS_MANAGER)
def daily_run():
    body()
    now = logical_now()

    # 1. lapse promises that the rights holder never honoured
    lapsing = []
    for tranche in db.release_tranches.values():
        if tranche["tranche_state"] != "PENDING":
            continue
        if not (tranche["promised_release_at"] < now):
            continue
        deal = db.rights_deals.get(tranche["rights_deal_id"])
        if deal is None or deal["deal_status"] in ("SETTLED", "TERMINATED"):
            continue
        lapsing.append(tranche)
    lapsing.sort(key=lambda t: (t["promised_release_at"], t["created_at"], t["_seq"]))

    lapsed_count = 0
    shortfall_count = 0
    for tranche in lapsing:
        deal = db.rights_deals[tranche["rights_deal_id"]]
        previous_status = deal["deal_status"]
        update_record(tranche, {"tranche_state": "LAPSED", "lapsed_at": now})
        services.apply_deal_state(deal, with_status=True, force=True, waterfall=True)
        lapsed_count += 1
        if deal["deal_status"] == "SHORTFALL_DECLARED" and previous_status != "SHORTFALL_DECLARED":
            shortfall_count += 1

    # 2. age money
    aged_count = 0
    for installment in calc.all_of(db.payment_installments):
        if installment["installment_state"] != "SCHEDULED":
            continue
        if not (installment["due_at"] < now):
            continue
        update_record(installment, {"installment_state": "OVERDUE"})
        aged_count += 1

    # 3. re-evaluate credit standing in both directions
    status_changes = 0
    for client in calc.all_of(db.clients):
        values = calc.client_exposure_values(client)
        values["client_status"] = calc.credit_standing_for(values["overdue_installment_count"])
        if values["client_status"] != client["client_status"]:
            status_changes += 1
        update_record(client, values)

    # 4. re-derive fixture risk for everything the sweep touched
    for event in calc.all_of(db.events):
        services.recompute_event_risk(event)

    return object_response(
        {
            "run_at": fmt_ts(now),
            "lapsed_tranche_count": lapsed_count,
            "overdue_installment_count": aged_count,
            "shortfall_deal_count": shortfall_count,
            "client_status_change_count": status_changes,
        }
    )


# --- Event ------------------------------------------------------------------


@bp.route("/events", methods=["POST"])
@guard(RIGHTS_MANAGER)
def create_event():
    data = body()
    name = req_string(data, "name")
    sport = req_enum(data, "sport", SPORTS)
    venue_name = req_string(data, "venue_name")
    zones = req_string_array(data, "hospitality_zone_codes", unique=True, non_empty=True)
    event_date = req_datetime(data, "event_date")

    event = create_record(
        db.events,
        {
            "name": name,
            "sport": sport,
            "venue_name": venue_name,
            "hospitality_zone_codes": zones,
            "event_date": event_date,
            "original_event_date": None,
            "status": "SCHEDULED",
            "rebook_deadline_at": None,
            "postponement_count": 0,
            "fulfillment_risk_score": 0,
            "risk_posture": "NORMAL",
        },
    )
    return object_response(event_json(event), 201)


@bp.route("/events/<event_id>", methods=["GET"])
@guard(*ALL_ROLES)
def read_event(event_id):
    event = get_event(event_id)
    apply_silent(event, calc.event_risk_values(event))
    return object_response(event_json(event))


@bp.route("/events/<event_id>/postpone", methods=["POST"])
@guard(RIGHTS_MANAGER)
def postpone_event(event_id):
    # PRD 2.7: request shape (step 4) is answered before existence (step 5).
    data = body()
    new_event_date = opt_datetime(data, "new_event_date")
    event = get_event(event_id)

    if event["status"] not in calc.LIVE_EVENT_STATUSES:
        fail(ERR_INVALID_EVENT_STATE, "A cancelled or completed fixture cannot be postponed.")
    now = logical_now()
    if new_event_date is not None and not (new_event_date > now):
        fail(ERR_INVALID_EVENT_STATE, "new_event_date must be strictly after the current instant.")

    if event["status"] == "POSTPONED":
        if new_event_date is None:
            fail(
                ERR_INVALID_EVENT_STATE,
                "A postponed fixture needs a replacement new_event_date.",
            )
        event["status"] = "RESCHEDULED"
        event["event_date"] = new_event_date
    else:
        if event["original_event_date"] is None:
            event["original_event_date"] = event["event_date"]
        if new_event_date is not None:
            event["event_date"] = new_event_date
        event["status"] = "POSTPONED"
        event["postponement_count"] = event["postponement_count"] + 1
        event["rebook_deadline_at"] = plus_days(now, calc.REBOOK_WINDOW_DAYS)
        services.postpone_freeze_cascade(event)

    event.update(calc.event_risk_values(event))
    touch(event)
    return object_response(event_json(event))


@bp.route("/events/<event_id>/cancel", methods=["POST"])
@guard(RIGHTS_MANAGER)
def cancel_event(event_id):
    event = get_event(event_id)
    body()
    if event["status"] not in calc.LIVE_EVENT_STATUSES:
        fail(ERR_INVALID_EVENT_STATE, "This fixture can no longer be cancelled.")

    event["status"] = "CANCELLED"
    services.cancel_event_cascade(event)
    event.update(calc.event_risk_values(event))
    touch(event)
    return object_response(event_json(event))


@bp.route("/events/<event_id>/complete", methods=["POST"])
@guard(RIGHTS_MANAGER)
def complete_event(event_id):
    event = get_event(event_id)
    body()
    if event["status"] not in ("SCHEDULED", "RESCHEDULED"):
        fail(ERR_INVALID_EVENT_STATE, "Only a scheduled or rescheduled fixture can be completed.")
    if event["event_date"] > logical_now():
        fail(ERR_INVALID_EVENT_STATE, "A fixture that has not kicked off cannot be completed.")
    for booking in calc.bookings_of_event(event["id"]):
        if booking["fulfillment_status"] in ("RESERVED", "REBOOK_PENDING"):
            fail(
                ERR_INVALID_EVENT_STATE,
                "Every booking must be delivered or disposed of before the books close.",
            )

    event["status"] = "COMPLETED"
    services.complete_event_cascade(event)
    event.update(calc.event_risk_values(event))
    touch(event)
    return object_response(event_json(event))


@bp.route("/events/<event_id>/margin-report", methods=["GET"])
@guard(FINANCE_CONTROLLER, COMMERCIAL_DIRECTOR)
def event_margin_report(event_id):
    event = get_event(event_id)
    variant = query_filter("variant")
    if variant is not None and variant not in ("PROVISIONAL", "FINAL"):
        bad("Query parameter `variant` must be PROVISIONAL or FINAL.")
    if variant is None:
        variant = "PROVISIONAL" if event["status"] in calc.LIVE_EVENT_STATUSES else "FINAL"
    apply_silent(event, calc.event_risk_values(event))
    return object_response(calc.margin_report(event, variant))
