"""Exercise notice endpoints (§3.5): create (OCC), deliver, reject, acknowledge."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_NOTICE_WINDOW_CLOSED,
    ERR_NOTICE_ALREADY_OPEN, ERR_STALE_VERSION, ERR_VALIDATION,
    ERR_ACK_AFTER_WINDOW, ERR_FORBIDDEN,
)
from middleware import authorized, READ_ROLES
from response import success_object
from services.core import (
    new_record, touch, refresh, public, option_notices, try_complete_exercise,
)
from routes.helpers import resolve_option, resolve_notice, paged
from util import CLOCK, fmt_dt, parse_date_value
from validate import get_body, req_int, req_enum, req_str

bp = Blueprint("notices", __name__)

DELIVERY_METHODS = ["CERTIFIED_MAIL", "COURIER", "PERSONAL_DELIVERY", "EMAIL_IF_PERMITTED"]


def _check_broker_ownership(caller, pid):
    """The acting Broker must be the BROKER contact registered for this portfolio."""
    contact = db["contacts"].get(caller.user_id)
    if (contact is None or contact["portfolio_id"] != pid
            or contact["contact_kind"] != "BROKER"):
        raise_error(ERR_FORBIDDEN,
                    "acting broker is not the broker contact registered for this portfolio")


@bp.post("/portfolios/<pid>/leases/<lid>/options/<oid>/notices")
def create_notice(pid, lid, oid):
    caller = authorized(["AssetManager"])
    _p, lease, option = resolve_option(pid, lid, oid)
    body = get_body()
    delivery_method = req_enum(body, "delivery_method", DELIVERY_METHODS)
    expected = req_int(body, "expected_lease_version")

    # priority 5: state admissibility (lease, then option)
    if lease["status"] not in ("ACTIVE", "EXPIRING"):
        raise_error(ERR_INVALID_STATE,
                    "exercise notice requires the parent lease to be ACTIVE or EXPIRING")
    if option["status"] not in ("AVAILABLE", "WINDOW_OPEN", "NOTICE_SENT"):
        raise_error(ERR_INVALID_STATE,
                    "option state does not permit exercise notice delivery")
    notices = option_notices(oid)
    if option["status"] == "NOTICE_SENT":
        # re-delivery path: every prior notice must be VOID or REJECTED; an open
        # SENT/DELIVERED notice is the priority-13 duplicate case, checked below
        if (not any(n["status"] in ("SENT", "DELIVERED") for n in notices)
                and not all(n["status"] in ("VOID", "REJECTED") for n in notices)):
            raise_error(ERR_INVALID_STATE,
                        "prior notices do not permit a re-delivery")

    # priority 6: notice-window membership, both bounds inclusive (date granularity)
    clock_date = CLOCK.today()
    open_d = parse_date_value(option["notice_window_open_date"])
    close_d = parse_date_value(option["notice_window_close_date"])
    if not (open_d <= clock_date <= close_d):
        raise_error(ERR_NOTICE_WINDOW_CLOSED,
                    "clock date is outside the option notice window")

    # priority 13: no duplicate open notice
    if any(n["status"] in ("SENT", "DELIVERED") for n in notices):
        raise_error(ERR_NOTICE_ALREADY_OPEN,
                    "an exercise notice in SENT or DELIVERED already exists on this option")

    # priority 14: OCC on Lease.version
    if expected != lease["version"]:
        raise_error(ERR_STALE_VERSION, "expected_lease_version does not match the lease version")

    now = CLOCK.now()
    # re-delivery supersedes the previously REJECTED notice(s)
    for n in notices:
        if n["status"] == "REJECTED":
            n["status"] = "VOID"
            touch(n)
    notice = new_record("notices", {
        "option_id": oid,
        "delivery_method": delivery_method,
        "sent_at": fmt_dt(now),
        "delivered_at": None,
        "acknowledged_at": None,
        "status": "SENT",
        "rejection_reason": None,
    })
    option["status"] = "NOTICE_SENT"
    refresh(option)
    touch(lease)
    return success_object(public(notice), 201)


@bp.get("/portfolios/<pid>/leases/<lid>/options/<oid>/notices")
def list_notices(pid, lid, oid):
    authorized(READ_ROLES)
    resolve_option(pid, lid, oid)
    status = request.args.get("status")
    items = option_notices(oid)
    if status is not None:
        items = [n for n in items if n["status"] == status]
    return paged(items, public)


@bp.get("/portfolios/<pid>/leases/<lid>/options/<oid>/notices/<nid>")
def get_notice(pid, lid, oid, nid):
    authorized(READ_ROLES)
    _p, _l, _o, notice = resolve_notice(pid, lid, oid, nid)
    return success_object(public(notice))


@bp.post("/portfolios/<pid>/leases/<lid>/options/<oid>/notices/<nid>/deliver")
def deliver_notice(pid, lid, oid, nid):
    caller = authorized(["Broker"])
    _p, _l, _o, notice = resolve_notice(pid, lid, oid, nid)
    _check_broker_ownership(caller, pid)
    if notice["status"] != "SENT":
        raise_error(ERR_INVALID_STATE, "only a SENT notice can be marked delivered")
    notice["status"] = "DELIVERED"
    notice["delivered_at"] = fmt_dt(CLOCK.now())
    touch(notice)
    return success_object(public(notice))


@bp.post("/portfolios/<pid>/leases/<lid>/options/<oid>/notices/<nid>/reject")
def reject_notice(pid, lid, oid, nid):
    caller = authorized(["Broker"])
    _p, _l, _o, notice = resolve_notice(pid, lid, oid, nid)
    _check_broker_ownership(caller, pid)
    body = get_body()
    reason = req_str(body, "rejection_reason")
    if notice["status"] != "SENT":
        raise_error(ERR_INVALID_STATE, "only a SENT notice can be rejected")
    notice["status"] = "REJECTED"
    notice["rejection_reason"] = reason
    touch(notice)
    return success_object(public(notice))


@bp.post("/portfolios/<pid>/leases/<lid>/options/<oid>/notices/<nid>/acknowledge")
def acknowledge_notice(pid, lid, oid, nid):
    authorized(["LandlordCounsel"])
    _p, _l, option, notice = resolve_notice(pid, lid, oid, nid)
    if notice["status"] != "DELIVERED":
        raise_error(ERR_INVALID_STATE, "only a DELIVERED notice can be acknowledged")
    # acknowledgment must land on or before the notice-window close date
    if CLOCK.today() > parse_date_value(option["notice_window_close_date"]):
        raise_error(ERR_ACK_AFTER_WINDOW,
                    "acknowledgment attempted after notice_window_close_date")
    now = CLOCK.now()
    notice["status"] = "ACKNOWLEDGED"
    notice["acknowledged_at"] = fmt_dt(now)
    touch(notice)
    # cascade hop 1: parent Option NOTICE_SENT -> EXERCISED (pricing gate permitting)
    try_complete_exercise(option, now)
    return success_object(public(notice))
