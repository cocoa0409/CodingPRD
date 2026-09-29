"""Championship events: award, hosting, cancellation and settlement (PRD 3.5)."""

from flask import Blueprint

import calc
import response
import serializers
import validation
from db import base_record, db, touch
from errors import ApiError
from middleware import api, raw_body
from routes import common
from services import compliance, distribution

bp = Blueprint("events", __name__)

EVENT_READ_ROLES = (
    "Commissioner",
    "ScheduleCoordinator",
    "FinanceOfficer",
    "Treasurer",
    "Auditor",
    "PlatformAdmin",
    "MemberRepresentative",
)

BLOCKED_HOST_STATUSES = ("DEPARTED", "ADMISSION_DENIED")
OCCUPYING_EVENT_STATUSES = ("SCHEDULED", "HOST_AT_RISK", "HOSTED")
CONFIRMABLE_EVENT_STATUSES = ("SCHEDULED", "HOST_AT_RISK")
POOL_ABSORBING_STATUSES = ("DRAFT", "OPEN", "BOOKS_CLOSED")


@bp.route("/championship-events", methods=["POST"])
@api(("Commissioner", "ScheduleCoordinator"))
def award_event():
    conference = db.conference
    body = raw_body()

    conference_id = validation.get_id(body, "conference_id")
    venue_id = validation.get_id(body, "venue_id")
    host_member_id = validation.get_id(body, "host_member_id")
    revenue_pool_id = validation.get_id(body, "revenue_pool_id")
    sport = validation.get_str(body, "sport")
    fiscal_year = validation.get_int(body, "fiscal_year", minimum=None)
    window_start = validation.get_instant(body, "window_start")
    window_end = validation.get_instant(body, "window_end")

    venue = common.get_venue(venue_id)
    host = common.get_member(host_member_id)
    common.get_pool(revenue_pool_id)

    if host["status"] in BLOCKED_HOST_STATUSES:
        raise ApiError("ERR_MEMBER_STATE_INVALID")

    overlapping = 0
    for event in db.championship_events.values():
        if event["venue_id"] != venue_id:
            continue
        if event["status"] not in OCCUPYING_EVENT_STATUSES:
            continue
        # Both windows are half-open: [start, end).
        if window_start < event["window_end"] and event["window_start"] < window_end:
            overlapping += 1
    if overlapping >= venue["concurrent_event_capacity"]:
        raise ApiError("ERR_VENUE_CAPACITY_EXCEEDED")

    if window_end <= window_start:
        raise ApiError("ERR_INVALID_EVENT_WINDOW")

    host_score = compliance.score(host)
    if host_score < calc.HOST_MINIMUM_SCORE:
        raise ApiError("ERR_HOST_COMPLIANCE_INSUFFICIENT")

    if conference["reserve_posture"] == "FROZEN":
        raise ApiError("ERR_RESERVE_POSTURE_FROZEN")

    event = base_record()
    event.update(
        {
            "conference_id": conference_id,
            "venue_id": venue_id,
            "host_member_id": host_member_id,
            "revenue_pool_id": revenue_pool_id,
            "sport": sport,
            "fiscal_year": fiscal_year,
            "window_start": window_start,
            "window_end": window_end,
            "host_compliance_score_at_award": host_score,
            "ticket_revenue_cents": 0,
            "sponsorship_revenue_cents": 0,
            "event_expense_cents": 0,
            "net_event_revenue_cents": 0,
            "host_share_cents": 0,
            "participant_pool_cents": 0,
            "status": "SCHEDULED",
        }
    )
    db.championship_events[event["id"]] = event
    return response.single(serializers.championship_event(event), 201)


@bp.route("/championship-events/<event_id>", methods=["GET"])
@api(EVENT_READ_ROLES)
def read_event(event_id):
    return response.single(
        serializers.championship_event(common.get_event(event_id))
    )


@bp.route("/championship-events", methods=["GET"])
@api(EVENT_READ_ROLES)
def list_events():
    criteria = {
        "conference_id": common.string_filter("conference_id"),
        "venue_id": common.string_filter("venue_id"),
        "host_member_id": common.string_filter("host_member_id"),
        "revenue_pool_id": common.string_filter("revenue_pool_id"),
        "fiscal_year": common.int_filter("fiscal_year"),
        "status": common.string_filter("status"),
    }
    return common.listing(
        list(db.championship_events.values()),
        serializers.championship_event,
        criteria=criteria,
    )


@bp.route("/championship-events/<event_id>/host", methods=["POST"])
@api(("Commissioner", "ScheduleCoordinator"))
def host_event(event_id):
    event = common.get_event(event_id)
    if event["status"] not in CONFIRMABLE_EVENT_STATUSES:
        raise ApiError("ERR_EVENT_STATE_INVALID")
    event["status"] = "HOSTED"
    touch(event)
    return response.single(serializers.championship_event(event))


@bp.route("/championship-events/<event_id>/cancel", methods=["POST"])
@api(("Commissioner", "ScheduleCoordinator"))
def cancel_event(event_id):
    event = common.get_event(event_id)
    body = raw_body()
    validation.get_optional_str(body, "reason")
    if event["status"] not in CONFIRMABLE_EVENT_STATUSES:
        raise ApiError("ERR_EVENT_STATE_INVALID")
    event["status"] = "CANCELLED"
    touch(event)
    return response.single(serializers.championship_event(event))


@bp.route("/championship-events/<event_id>/settle", methods=["POST"])
@api(("FinanceOfficer",))
def settle_event(event_id):
    event = common.get_event(event_id)
    body = raw_body()
    ticket_revenue_cents = validation.get_int(body, "ticket_revenue_cents")
    sponsorship_revenue_cents = validation.get_int(body, "sponsorship_revenue_cents")
    event_expense_cents = validation.get_int(body, "event_expense_cents")

    if event["status"] != "HOSTED":
        raise ApiError("ERR_EVENT_STATE_INVALID")

    pool = db.revenue_pools.get(event["revenue_pool_id"])
    if pool is None or pool["status"] not in POOL_ABSORBING_STATUSES:
        raise ApiError("ERR_POOL_CLOSED_TO_REVENUE")

    net, host_share, participant_pool = calc.championship_split(
        ticket_revenue_cents, sponsorship_revenue_cents, event_expense_cents
    )
    event.update(
        {
            "ticket_revenue_cents": ticket_revenue_cents,
            "sponsorship_revenue_cents": sponsorship_revenue_cents,
            "event_expense_cents": event_expense_cents,
            "net_event_revenue_cents": net,
            "host_share_cents": host_share,
            "participant_pool_cents": participant_pool,
            "status": "SETTLED",
        }
    )
    touch(event)

    # The deepest cascade in the system (PRD sections 2.9 and 3.5).
    pool["gross_revenue_cents"] += participant_pool
    if pool["status"] in ("OPEN", "BOOKS_CLOSED"):
        if pool["status"] == "BOOKS_CLOSED":
            pool["audited_expense_cents"] = None
        pool["status"] = "DRAFT"
    distribution.supersede_computed_runs(pool)
    touch(pool)

    return response.single(serializers.championship_event(event))
