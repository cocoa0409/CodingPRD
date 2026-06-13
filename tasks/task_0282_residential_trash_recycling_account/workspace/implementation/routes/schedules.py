"""Pickup schedules and curb-outcome events (PRD §3.6, §3.7, §3.8, §3.9)."""
from flask import Blueprint, request

import db
import clock
from errors import err
from response import ok, ok_list
from routes.helpers import gate, require_ownership
from services import validate as V
from services import calc
from services.common import new_record, touch, sort_by_created
from services.lookup import get_or_404
from services.serialize import schedule_out, event_out
from util import parse_dt, to_midnight

bp = Blueprint("schedules", __name__)

STREAMS = {"TRASH", "RECYCLING"}
SCHEDULE_STATES = {"PLANNED", "COMPLETED", "MISSED", "CANCELLED"}
OUTCOMES = {"COLLECTED", "MISSED", "CONTAMINATED"}


def _schedule_sort_key(s):
    # service_date ASC, then TRASH before RECYCLING on the same date
    sd = to_midnight(parse_dt(s["service_date"]))
    stream_rank = 0 if s["stream"] == "TRASH" else 1
    return (sd, stream_rank, s["_seq"])


@bp.route("/accounts/<aid>/pickup-schedules", methods=["GET"])
def list_schedules(aid):
    user_id, role = gate({"Dispatcher", "AccountHolder"})
    a = get_or_404(db.service_accounts, aid)
    require_ownership(role, user_id, a["id"])
    limit, offset = V.parse_pagination(request.args)
    stream = request.args.get("stream")
    status = request.args.get("status")
    if stream is not None and stream not in STREAMS:
        raise err("ERR_INVALID_REQUEST", "Invalid stream filter.")
    if status is not None and status not in SCHEDULE_STATES:
        raise err("ERR_INVALID_REQUEST", "Invalid status filter.")

    items = [s for s in db.pickup_schedules.values() if s["account_id"] == a["id"]]
    if stream is not None:
        items = [s for s in items if s["stream"] == stream]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=_schedule_sort_key)
    total = len(items)
    page = V.paginate(items, limit, offset)
    return ok_list([schedule_out(s) for s in page], limit, offset, total)


@bp.route("/pickup-schedules/<sid>", methods=["GET"])
def get_schedule(sid):
    user_id, role = gate({"Dispatcher", "AccountHolder", "CrewLead"})
    s = get_or_404(db.pickup_schedules, sid)
    require_ownership(role, user_id, s["account_id"])
    return ok(schedule_out(s))


@bp.route("/pickup-schedules/<sid>/events", methods=["POST"])
def report_event(sid):
    gate({"CrewLead"})
    s = get_or_404(db.pickup_schedules, sid)
    body = V.get_body(request)
    outcome = V.require_enum(body, "outcome", OUTCOMES)
    reported_at = V.require_dt(body, "reported_at")
    # priority 5: when a CONTAMINATED outcome is reported, severity must be a
    # valid enum member (well-formedness precedes the state/stream checks).
    severity = None
    if outcome == "CONTAMINATED":
        severity = V.require_enum(body, "severity", {"MINOR", "MAJOR"})

    account = db.service_accounts.get(s["account_id"])

    # priority 7: state legality (schedule PLANNED and parent account ACTIVE)
    if s["status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", "Schedule is not PLANNED.")
    if account is None or account["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Parent account is not ACTIVE.")

    # priority 12: reported_at must be >= effective_pickup_date
    eff = to_midnight(parse_dt(s["effective_pickup_date"]))
    if reported_at < eff:
        raise err("ERR_REPORT_TOO_EARLY", "Cannot report a pickup before it was due.")

    # priority 13: CONTAMINATED only on RECYCLING
    if outcome == "CONTAMINATED" and s["stream"] != "RECYCLING":
        raise err("ERR_CONTAMINATION_NOT_RECYCLING", "Contamination only on RECYCLING schedules.")

    from util import format_ts
    event = new_record({
        "schedule_id": s["id"],
        "outcome": outcome,
        "reported_at": format_ts(reported_at),
    })
    db.pickup_events[event["id"]] = event

    if outcome == "COLLECTED":
        s["status"] = "COMPLETED"
    elif outcome == "MISSED":
        s["status"] = "MISSED"
        _issue_missed_credit(account, s, event)
    elif outcome == "CONTAMINATED":
        # recycling still hauled away -> schedule completes; open a notice
        s["status"] = "COMPLETED"
        _open_contamination_notice(account, event, severity)

    touch(s)
    return ok(event_out(event), 201)


def _issue_missed_credit(account, schedule, event):
    amount = calc.missed_credit_amount(account["id"], schedule["stream"], clock.now())
    credit = new_record({
        "account_id": account["id"],
        "pickup_event_id": event["id"],
        "amount_cents": amount,
        "applied_invoice_id": None,
        "status": "ISSUED",
    })
    db.missed_pickup_credits[credit["id"]] = credit


def _open_contamination_notice(account, event, severity):
    notice = new_record({
        "account_id": account["id"],
        "pickup_event_id": event["id"],
        "severity": severity,
        "fee_cents": 0,
        "status": "OPEN",
    })
    db.contamination_notices[notice["id"]] = notice
    notice["fee_cents"] = calc.contamination_fee(account["id"], severity, notice["_seq"])


@bp.route("/pickup-schedules/<sid>/events", methods=["GET"])
def list_events(sid):
    user_id, role = gate({"Dispatcher", "AccountHolder", "CrewLead"})
    s = get_or_404(db.pickup_schedules, sid)
    require_ownership(role, user_id, s["account_id"])
    limit, offset = V.parse_pagination(request.args)
    items = [e for e in db.pickup_events.values() if e["schedule_id"] == s["id"]]
    items = sort_by_created(items)
    total = len(items)
    page = V.paginate(items, limit, offset)
    return ok_list([event_out(e) for e in page], limit, offset, total)
