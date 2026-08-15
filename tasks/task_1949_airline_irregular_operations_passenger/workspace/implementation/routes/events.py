"""Disruption event lifecycle + listings + cost ledger reads."""

from flask import Blueprint

import errors
from db import db, now
from middleware import authenticate, require_role
from response import success_list, success_object
from serializers import (
    serialize_cost_entry,
    serialize_event,
    serialize_flight,
)
from services.core import stamp_new, touch, voucher_face_outstanding
from validators import (
    get_json_body_optional,
    opt_query_enum,
    pagination_params,
    req_int,
    req_string,
    get_json_body,
)

bp = Blueprint("events", __name__)

CLASSIFICATIONS = {"WEATHER", "ATC", "MECHANICAL", "CREW_SHORTAGE"}
EVENT_STATUSES = {"OPEN", "ASSESSING", "RECOVERY", "CLOSED"}
EVENT_READ_ROLES = ["DutyManager", "OpsController", "ReaccommodationAgent",
                    "FinanceProcessor", "OpsAdmin"]
COST_READ_ROLES = ["DutyManager", "FinanceProcessor", "OpsAdmin"]


@bp.post("/irops/disruption-events")
def create_event():
    caller = authenticate()
    require_role(caller, ["DutyManager"])
    body = get_json_body()
    event_code = req_string(body, "event_code")
    hub = req_string(body, "hub")
    classification = body.get("classification")
    if not isinstance(classification, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "classification must be a string")
    if classification not in CLASSIFICATIONS:
        errors.raise_error(errors.ERR_INVALID_ENUM,
                           "classification value %r outside declared enum domain" % classification)
    cost_cap = req_int(body, "cost_cap_cents")
    e = stamp_new({
        "event_code": event_code,
        "hub": hub,
        "classification": classification,
        "is_controllable": classification in ("MECHANICAL", "CREW_SHORTAGE"),
        "event_status": "OPEN",
        "cost_cap_cents": cost_cap,
        "detected_at": now(),
        "affected_booking_count": 0,
        "affected_passenger_count": 0,
        "accrual_total_cents": 0,
        "settled_total_cents": 0,
    })
    db.disruption_events[e["id"]] = e
    return success_object(serialize_event(e), 201)


@bp.get("/irops/disruption-events/<eid>")
def get_event(eid):
    caller = authenticate()
    require_role(caller, EVENT_READ_ROLES)
    e = db.disruption_events.get(eid)
    if e is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "DisruptionEvent not found")
    return success_object(serialize_event(e), 200)


@bp.get("/irops/disruption-events")
def list_events():
    caller = authenticate()
    require_role(caller, EVENT_READ_ROLES)
    status = opt_query_enum("event_status", EVENT_STATUSES)
    classification = opt_query_enum("classification", CLASSIFICATIONS)
    limit, offset = pagination_params()
    items = sorted(db.disruption_events.values(), key=lambda e: e["created_at"])
    if status is not None:
        items = [e for e in items if e["event_status"] == status]
    if classification is not None:
        items = [e for e in items if e["classification"] == classification]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_event(e) for e in page], limit, offset, total)


@bp.get("/irops/disruption-events/<eid>/flights")
def list_event_flights(eid):
    caller = authenticate()
    require_role(caller, EVENT_READ_ROLES)
    e = db.disruption_events.get(eid)
    if e is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "DisruptionEvent not found")
    limit, offset = pagination_params()
    items = sorted(
        [f for f in db.flights.values() if f["disruption_event_id"] == eid],
        key=lambda f: f["created_at"],
    )
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_flight(f) for f in page], limit, offset, total)


@bp.get("/irops/disruption-events/<eid>/cost-entries")
def list_cost_entries(eid):
    caller = authenticate()
    require_role(caller, COST_READ_ROLES)
    e = db.disruption_events.get(eid)
    if e is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "DisruptionEvent not found")
    limit, offset = pagination_params()
    items = sorted(
        [ce for ce in db.cost_entries.values() if ce["disruption_event_id"] == eid],
        key=lambda ce: ce["created_at"],
    )
    total = len(items)
    page = items[offset:offset + limit]
    from serializers import serialize_cost_entry as sc
    return success_list([sc(ce) for ce in page], limit, offset, total)


@bp.get("/irops/disruption-events/<eid>/cost-summary")
def cost_summary(eid):
    caller = authenticate()
    require_role(caller, COST_READ_ROLES)
    e = db.disruption_events.get(eid)
    if e is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "DisruptionEvent not found")
    entries = [ce for ce in db.cost_entries.values() if ce["disruption_event_id"] == eid]
    out = {
        "accrual_total_cents": e["accrual_total_cents"],
        "settled_total_cents": e["settled_total_cents"],
        "entry_count": len(entries),
        "voucher_face_outstanding_cents": voucher_face_outstanding(eid),
    }
    return success_object(out, 200)


def _lifecycle(eid, expected_from, to, action):
    caller = authenticate()
    require_role(caller, ["DutyManager"])
    e = db.disruption_events.get(eid)
    if e is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "DisruptionEvent not found")
    if e["event_status"] != expected_from:
        errors.raise_error(errors.ERR_EVENT_INVALID_STATE,
                           "Cannot %s an event in state %s" % (action, e["event_status"]))
    e["event_status"] = to
    touch(e)
    return success_object(serialize_event(e), 200)


@bp.post("/irops/disruption-events/<eid>/assess")
def assess(eid):
    return _lifecycle(eid, "OPEN", "ASSESSING", "assess")


@bp.post("/irops/disruption-events/<eid>/declare-recovery")
def declare_recovery(eid):
    return _lifecycle(eid, "ASSESSING", "RECOVERY", "declare-recovery")


@bp.post("/irops/disruption-events/<eid>/reopen")
def reopen(eid):
    return _lifecycle(eid, "RECOVERY", "ASSESSING", "reopen")


@bp.post("/irops/disruption-events/<eid>/close")
def close(eid):
    caller = authenticate()
    require_role(caller, ["DutyManager"])
    e = db.disruption_events.get(eid)
    if e is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "DisruptionEvent not found")
    if e["event_status"] != "RECOVERY":
        errors.raise_error(errors.ERR_EVENT_INVALID_STATE,
                           "Cannot close an event in state %s" % e["event_status"])
    # open-child checks
    for c in db.reaccommodation_cases.values():
        if c["disruption_event_id"] == eid and c["case_status"] in ("QUEUED", "OFFERED", "ESCALATED"):
            errors.raise_error(errors.ERR_EVENT_CLOSE_BLOCKED,
                               "Event has open reaccommodation cases")
    for v in db.vouchers.values():
        if v["disruption_event_id"] == eid and v["voucher_status"] == "ISSUED":
            errors.raise_error(errors.ERR_EVENT_CLOSE_BLOCKED,
                               "Event has ISSUED vouchers")
    # bookings with a case on this event still ELIGIBLE_PENDING
    case_booking_ids = {c["booking_id"] for c in db.reaccommodation_cases.values()
                        if c["disruption_event_id"] == eid}
    for bid in case_booking_ids:
        b = db.bookings.get(bid)
        if b is not None and b["compensation_status"] == "ELIGIBLE_PENDING":
            errors.raise_error(errors.ERR_EVENT_CLOSE_BLOCKED,
                               "Event has ELIGIBLE_PENDING bookings")
    for el in db.refund_elections.values():
        if el["booking_id"] in case_booking_ids and el["election_status"] == "PENDING":
            errors.raise_error(errors.ERR_EVENT_CLOSE_BLOCKED,
                               "Event has PENDING refund elections")
    e["event_status"] = "CLOSED"
    touch(e)
    return success_object(serialize_event(e), 200)
