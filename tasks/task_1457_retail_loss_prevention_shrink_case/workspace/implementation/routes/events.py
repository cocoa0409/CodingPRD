"""POS exception events + alert aggregation (PRD §3.2)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, parse_iso, fmt_iso
from middleware import get_auth, require_role, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.validate import (
    body, req_string, opt_string, req_int, req_enum, req_datetime, get_or_404,
)
from services.entities import make_exception_event, make_alert, pub, touch
from services.calculations import (
    score_events, OPEN_THRESHOLD, ESCALATE_THRESHOLD, WINDOW_DAYS, WEIGHTS,
)
from errors import err409, ERR_STORE_CLOSED

bp = Blueprint("events", __name__)

EXCEPTION_TYPES = [
    "REFUND_NO_RECEIPT", "HIGH_VALUE_VOID", "PRICE_OVERRIDE",
    "NO_SALE_DRAWER", "SUSPEND_CANCEL", "SWEETHEART_SCAN",
    "SELF_CHECKOUT_MISMATCH",
]


def _refresh_alert_rollups(alert):
    """Recompute score, counts, totals, window over member events and re-evaluate
    escalation. Touch the alert (mutation)."""
    members = [db.exception_events[eid] for eid in alert["_member_event_ids"]]
    alert["score"] = float(score_events(members))
    alert["event_count"] = len(members)
    alert["total_amount_cents"] = sum(e["amount_cents"] for e in members)
    if members:
        occ = [e["occurred_at"] for e in members]
        alert["window_start"] = min(occ)
        alert["window_end"] = max(occ)
    # escalation (inclusive boundary) — only from OPEN
    from decimal import Decimal
    if alert["status"] == "OPEN" and Decimal(str(alert["score"])) >= ESCALATE_THRESHOLD:
        alert["status"] = "ESCALATED"
    touch(alert)


@bp.route("/exception-events", methods=["POST"])
def create_event():
    user_id, role = get_auth()
    require_role(role, {"PosFeed"})
    data = body()
    store_id = req_string(data, "store_id")
    register_ref = req_string(data, "register_ref")
    txn_ref = req_string(data, "txn_ref")
    exception_type = req_enum(data, "exception_type", EXCEPTION_TYPES)
    amount_cents = req_int(data, "amount_cents", minimum=1)
    occurred_at = req_datetime(data, "occurred_at")
    employee_id = opt_string(data, "employee_id")

    store = get_or_404(db.stores, store_id, "store")
    if employee_id is not None:
        get_or_404(db.employees, employee_id, "employee")
    if store["status"] != "ACTIVE":
        raise err409(ERR_STORE_CLOSED, "Store is CLOSED")

    event = make_exception_event(store_id, register_ref, txn_ref, exception_type,
                                 amount_cents, occurred_at, employee_id)
    db.exception_events[event["id"]] = event

    # --- alert aggregation ---
    group_alert = None
    for a in db.alerts.values():
        if (a["store_id"] == store_id and a["employee_id"] == employee_id
                and a["status"] in ("OPEN", "ESCALATED")):
            group_alert = a
            break

    if group_alert is not None:
        # attach: event joins the group's live alert; score recomputed
        event["status"] = "AGGREGATED"
        touch(event)
        group_alert["_member_event_ids"].append(event["id"])
        _refresh_alert_rollups(group_alert)
    else:
        # candidate set: UNAGGREGATED events same group within 30-day window
        new_occ = parse_iso(occurred_at)
        window_start = new_occ - timedelta(days=WINDOW_DAYS)
        candidates = []
        for e in db.exception_events.values():
            if (e["store_id"] == store_id and e["employee_id"] == employee_id
                    and e["status"] == "UNAGGREGATED"):
                occ = parse_iso(e["occurred_at"])
                if window_start <= occ <= new_occ:
                    candidates.append(e)
        cand_score = score_events(candidates)
        if cand_score >= OPEN_THRESHOLD:
            alert = make_alert(store_id, employee_id)
            db.alerts[alert["id"]] = alert
            for e in candidates:
                e["status"] = "AGGREGATED"
                touch(e)
                alert["_member_event_ids"].append(e["id"])
            _refresh_alert_rollups(alert)

    return success_object(pub(event), status=201)


@bp.route("/exception-events", methods=["GET"])
def list_events():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    store_id = _q("store_id")
    employee_id = _q("employee_id")
    status = _q("status")
    exception_type = _q("exception_type")
    items = sorted(db.exception_events.values(),
                   key=lambda e: (e["created_at"], e["id"]))
    if store_id is not None:
        items = [e for e in items if e["store_id"] == store_id]
    if employee_id is not None:
        items = [e for e in items if e["employee_id"] == employee_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if exception_type is not None:
        items = [e for e in items if e["exception_type"] == exception_type]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pub(e) for e in page], limit, offset, total)


@bp.route("/exception-events/<event_id>", methods=["GET"])
def get_event(event_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    event = get_or_404(db.exception_events, event_id, "exception event")
    return success_object(pub(event))


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None
