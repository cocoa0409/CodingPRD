"""Operations: daily sweep and the test-driving logical clock (PRD §3.11, §2.4)."""

from datetime import timezone

from flask import Blueprint

import errors
from db import clock_date, fmt_ts, store, touch
from middleware import body, require_roles
from response import ok
from services import (
    case_source_account,
    credited_total,
    maybe_close_account,
    parse_date,
    parse_iso8601,
    recompute_indirect_1099_corrected,
    skip_scheduled_notices,
)

bp = Blueprint("ops", __name__)


@bp.post("/v1/sweeps/daily")
@require_roles("OperationsAgent")
def daily_sweep():
    today = clock_date()
    notices_sent = 0
    notices_skipped = 0
    cases_marked_incomplete = 0

    # Pass 1: dispatch due follow-up notices.
    for notice in sorted(store.notices.values(), key=lambda n: n["_seq"]):
        if notice["status"] != "SCHEDULED":
            continue
        scheduled = parse_date(notice["scheduled_date"])
        if scheduled is None or today < scheduled:
            continue
        case = store.cases.get(notice["rollover_case_id"])
        if case is not None and case["status"] == "AWAITING_REDEPOSIT":
            notice["status"] = "SENT"
            deadline = parse_date(case.get("rollover_deadline_date"))
            notice["days_remaining"] = (deadline - today).days if deadline is not None else None
            notice["outstanding_cents"] = (case.get("gross_cents") or 0) - credited_total(case["id"])
            touch(notice)
            notices_sent += 1
        elif case is not None and case["status"] in ("COMPLETED", "INCOMPLETE"):
            notice["status"] = "SKIPPED"
            touch(notice)
            notices_skipped += 1

    # Pass 2: catch lapsed 60-day windows on indirect cases.
    for case in sorted(store.cases.values(), key=lambda c: c["_seq"]):
        if case["status"] != "AWAITING_REDEPOSIT" or case["case_type"] != "INDIRECT_ROLLOVER_OUT":
            continue
        deadline = parse_date(case.get("rollover_deadline_date"))
        if deadline is None or today <= deadline:
            continue
        if credited_total(case["id"]) >= (case.get("gross_cents") or 0):
            continue
        case["status"] = "INCOMPLETE"
        touch(case)
        notices_skipped += skip_scheduled_notices(case["id"])
        recompute_indirect_1099_corrected(case)
        maybe_close_account(case_source_account(case))
        cases_marked_incomplete += 1

    return ok(
        {
            "notices_sent": notices_sent,
            "notices_skipped": notices_skipped,
            "cases_marked_incomplete": cases_marked_incomplete,
        }
    )


@bp.post("/_clock/set_current_utc")
@require_roles("OperationsAgent")
def set_clock():
    data = body()
    dt = parse_iso8601(data.get("to_iso8601"))
    if dt is None:
        raise errors.err_validation("to_iso8601 must be an ISO 8601 timestamp")
    store.clock = dt.astimezone(timezone.utc)
    return ok({"current_utc": fmt_ts(store.clock)})
