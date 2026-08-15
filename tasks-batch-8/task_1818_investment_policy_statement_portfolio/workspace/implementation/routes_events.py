from datetime import datetime, time, timezone
from flask import Blueprint, request

import store as db
from auth import authorize
from envelope import obj, page
from errors import ApiError
from logic import get_or_404
from serialize import event_out
from validate import pagination, parse_datetime_val, parse_date_str

bp = Blueprint("events", __name__)


def _window_bound(raw, is_from):
    """Accept ISO8601 datetimes; date-only forms bound the whole UTC day."""
    try:
        return parse_datetime_val(raw)
    except ApiError:
        d = parse_date_str(raw)
        t = time.min if is_from else time.max
        return datetime.combine(d, t, tzinfo=timezone.utc)


@bp.get("/advisory/cash-flow-events")
def list_events():
    uid, role = authorize("Advisor", "ComplianceOfficer", "Client")
    limit, offset = pagination()
    rows = sorted(db.events.values(), key=lambda e: (e["created_dt"], e["_seq"]))
    if role == "Client":
        rows = [e for e in rows
                if db.portfolios[e["portfolio_id"]]["client_id"] == uid]
    pf_id = request.args.get("portfolio_id")
    if pf_id is not None:
        rows = [e for e in rows if e["portfolio_id"] == pf_id]
    kind = request.args.get("kind")
    if kind is not None:
        rows = [e for e in rows if e["kind"] == kind]
    raw_from = request.args.get("from")
    if raw_from is not None:
        bound = _window_bound(raw_from, True)
        rows = [e for e in rows if e["occurred_dt"] >= bound]
    raw_to = request.args.get("to")
    if raw_to is not None:
        bound = _window_bound(raw_to, False)
        rows = [e for e in rows if e["occurred_dt"] <= bound]
    total = len(rows)
    return page([event_out(e) for e in rows[offset:offset + limit]],
                limit, offset, total)


@bp.get("/advisory/cash-flow-events/<eid>")
def get_event(eid):
    authorize("Advisor", "ComplianceOfficer")
    e = get_or_404(db.events, eid)
    return obj(event_out(e))
