"""Notice endpoints (PRD 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_NOTICE_LEAD_TIME_INSUFFICIENT, ERR_NOTICE_ORDER_VIOLATION,
    ERR_CASE_ACCESS_DENIED,
)
from middleware import authorized, check_case_read_access, party_side_of, STAFF_READ_ROLES
from response import success_list, success_object
from services.core import (
    new_record, public, append_event, get_case, check_case_not_terminal,
    get_pagination, sort_items, apply_filters,
    NOTICE_TYPES, NOTICE_SIDES, LEAD_DAYS,
)
from util import clock_iso, clock_dt, parse_datetime
from validate import get_body, req_str, req_enum, req_datetime, opt_datetime, require_path, as_datetime

bp = Blueprint("notices", __name__)

READ_ROLES = STAFF_READ_ROLES + ["Party"]


def _party_visible_notice(notice, case, caller):
    if caller.role == "Party":
        side = party_side_of(case, caller.user_id)
        if notice["recipient_side"] not in ("BOTH", side):
            raise_error(ERR_CASE_ACCESS_DENIED,
                        "notice is addressed to the other party")


@bp.post("/cases/<cid>/notices")
def send_notice(cid):
    caller = authorized(["TitleIXCoordinator", "Investigator", "DecisionMaker"])
    case = get_case(cid)
    check_case_not_terminal(case)
    body = get_body()

    # Tier 6 temporal: lead time first, then ordering (validation table order).
    notice_type = body.get("notice_type")
    scheduled = as_datetime(body, "scheduled_event_at")
    if notice_type in LEAD_DAYS and scheduled is not None:
        gap = (parse_datetime(scheduled) - clock_dt()).total_seconds()
        if gap < LEAD_DAYS[notice_type] * 86400:
            raise_error(ERR_NOTICE_LEAD_TIME_INSUFFICIENT,
                        f"{notice_type} notices require {LEAD_DAYS[notice_type]} days of lead time")
    if notice_type == "INTERVIEW":
        if not any(n["case_id"] == cid and n["notice_type"] == "ALLEGATIONS"
                   for n in db["notices"].values()):
            raise_error(ERR_NOTICE_ORDER_VIOLATION,
                        "an ALLEGATIONS notice must exist before any INTERVIEW notice")

    # Tier 11: schema.
    notice_type = req_enum(body, "notice_type", NOTICE_TYPES)
    recipient_side = req_enum(body, "recipient_side", NOTICE_SIDES)
    body_text = req_str(body, "body")
    if notice_type in LEAD_DAYS:
        scheduled_event_at = req_datetime(body, "scheduled_event_at")
    else:
        scheduled_event_at = opt_datetime(body, "scheduled_event_at")

    if notice_type in LEAD_DAYS:
        gap = (parse_datetime(scheduled_event_at) - clock_dt()).total_seconds()
        sufficient = gap >= LEAD_DAYS[notice_type] * 86400
    else:
        sufficient = True
    rec = new_record("notices", {
        "case_id": cid,
        "notice_type": notice_type,
        "recipient_side": recipient_side,
        "body": body_text,
        "scheduled_event_at": scheduled_event_at,
        "sent_at": clock_iso(),
        "lead_time_sufficient": sufficient,
    }, with_version=False)
    append_event(cid, "NOTICE_SENT", caller,
                 {"notice_id": rec["id"], "notice_type": notice_type,
                  "recipient_side": recipient_side})
    return success_object(public(rec), 201)


@bp.get("/cases/<cid>/notices")
def list_notices(cid):
    caller = authorized(READ_ROLES)
    case = get_case(cid)
    check_case_read_access(caller, case)
    items = [n for n in db["notices"].values() if n["case_id"] == cid]
    if caller.role == "Party":
        side = party_side_of(case, caller.user_id)
        items = [n for n in items if n["recipient_side"] in ("BOTH", side)]
    items = apply_filters(items, {
        "notice_type": request.args.get("notice_type"),
        "recipient_side": request.args.get("recipient_side"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/notices/<nid>")
def get_notice(nid):
    caller = authorized(READ_ROLES)
    notice = require_path("notices", nid)
    case = get_case(notice["case_id"])
    check_case_read_access(caller, case)
    _party_visible_notice(notice, case, caller)
    return success_object(public(notice))
