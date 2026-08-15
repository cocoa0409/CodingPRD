"""Operator endpoints: logical clock, time sweep, and call-volume analytics."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import store
from errors import invalid_request
from middleware import require_roles
from response import ok_object
from services import run_time_sweep, ISSUE_CATEGORIES
from util import get_payload, check_unknown, require, parse_dt, query_enum

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("AgencyAdmin")
    data = get_payload()
    check_unknown(data, {"to_iso8601"})
    raw = require(data, "to_iso8601")
    store.clock = parse_dt(raw, "to_iso8601")
    return ok_object({"current_utc": raw})


@bp.route("/_ops/run_time_sweep", methods=["POST"])
def sweep():
    require_roles("AgencyAdmin")
    return ok_object(run_time_sweep())


@bp.route("/hotline/analytics/call-volume", methods=["GET"])
def call_volume():
    require_roles("Analyst", "HotlineSupervisor", "AgencyAdmin")
    raw_from = request.args.get("from_iso8601")
    raw_to = request.args.get("to_iso8601")
    from_dt = parse_dt(raw_from, "from_iso8601") if raw_from is not None else None
    to_dt = parse_dt(raw_to, "to_iso8601") if raw_to is not None else None
    if from_dt is not None and to_dt is not None and to_dt < from_dt:
        invalid_request("to_iso8601 must not precede from_iso8601")
    jurisdiction_id = request.args.get("jurisdiction_id")
    issue_category = query_enum("issue_category", ISSUE_CATEGORIES)
    view = request.args.get("view") or "RAW"
    if view not in ("RAW", "DEDUPLICATED"):
        invalid_request("view must be one of: RAW, DEDUPLICATED")

    def in_window(t):
        if t is None:
            return False
        if from_dt is not None and t < from_dt:
            return False
        if to_dt is not None and t >= to_dt:
            return False
        return True

    # eligible sessions: reached ACTIVE at least once, actual_start_at in the
    # half-open window, caller not excluded from aggregation
    eligible = []
    for s in store.sessions.values():
        if s["session_status"] not in ("ACTIVE", "WRAPPED_UP", "DROPPED"):
            continue
        if not in_window(s["actual_start_at"]):
            continue
        if jurisdiction_id is not None and s["jurisdiction_id"] != jurisdiction_id:
            continue
        if issue_category is not None and s["issue_category"] != issue_category:
            continue
        caller = store.callers.get(s["caller_id"])
        if caller is not None and caller["do_not_aggregate"]:
            continue
        eligible.append(s)

    if view == "RAW":
        call_count = len(eligible)
    else:
        identified = set()
        anonymous_sessions = 0
        for s in eligible:
            caller = store.callers.get(s["caller_id"])
            if caller is not None and not caller["is_anonymous"]:
                identified.add(s["caller_id"])
            else:
                anonymous_sessions += 1
        call_count = len(identified) + anonymous_sessions

    escalated_case_count = 0
    for c in store.cases.values():
        if not in_window(c["last_escalated_at"]):
            continue
        if jurisdiction_id is not None and c["jurisdiction_id"] != jurisdiction_id:
            continue
        if issue_category is not None and c["issue_category"] != issue_category:
            continue
        escalated_case_count += 1

    if call_count == 0:
        rate = 0
    else:
        rate = float(
            (Decimal(escalated_case_count) / Decimal(call_count)).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        )
    return ok_object({
        "call_count": call_count,
        "escalated_case_count": escalated_case_count,
        "escalation_rate": rate,
        "view": view,
    })
