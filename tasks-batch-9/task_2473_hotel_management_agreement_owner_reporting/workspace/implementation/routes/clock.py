"""The logical clock and the five-step epoch sweep (PRD §2.10)."""

from flask import Blueprint

import validate as v
from auth import authenticate
from db import by_seq, store, touch
from response import ok
from timeutil import cmp_iso

bp = Blueprint("clock", __name__)


def _strictly_before(deadline_iso, clock_iso):
    if deadline_iso is None:
        return False
    return cmp_iso(deadline_iso, clock_iso) < 0


def _at_or_before(deadline_iso, clock_iso):
    if deadline_iso is None:
        return False
    return cmp_iso(deadline_iso, clock_iso) <= 0


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["PlatformAdmin"])
    body = v.body()
    to_iso8601 = v.req_datetime(body, "to_iso8601")

    # the clock moves first; every sweep step compares against the NEW value
    store.set_clock(to_iso8601)
    now = store.now_iso

    # 1. deemed budget approval -- strictly past the owner decision deadline
    deemed = 0
    for budget in by_seq(list(store.budgets.values())):
        if budget["status"] == "SUBMITTED" and _strictly_before(
            budget["owner_decision_deadline_utc"], now
        ):
            budget["status"] = "DEEMED_APPROVED"
            touch(budget)
            deemed += 1

    # 2. overdue working capital calls -- strictly past the due date
    overdue = 0
    for call in by_seq(list(store.working_capital_calls.values())):
        if call["status"] == "REQUESTED" and _strictly_before(call["due_date_utc"], now):
            call["status"] = "OVERDUE"
            touch(call)
            overdue += 1

    # 3. lapsed cure rights -- strictly past the cure deadline
    lapsed = 0
    for test in by_seq(list(store.performance_tests.values())):
        if test["status"] in ("FAILED_CURABLE", "CURE_ELECTED") and _strictly_before(
            test["cure_deadline_utc"], now
        ):
            test["status"] = "TERMINATION_TRIGGERED"
            touch(test)
            lapsed += 1

    # 4. deadlocked disputes -- at or past the standstill end (exclusive window)
    deadlocked = 0
    for dispute in by_seq(list(store.brand_disputes.values())):
        if dispute["status"] == "ESCALATED_TO_FRANCHISOR" and _at_or_before(
            dispute["standstill_end_utc"], now
        ):
            dispute["status"] = "DEADLOCKED"
            touch(dispute)
            deadlocked += 1

    # 5. terminated agreements -- at or past the effective instant
    terminated = 0
    for agreement in by_seq(list(store.agreements.values())):
        if agreement["status"] == "TERMINATION_NOTICED" and _at_or_before(
            agreement["termination_effective_utc"], now
        ):
            agreement["status"] = "TERMINATED"
            agreement["distribution_hold"] = True
            touch(agreement)
            terminated += 1

    return ok(
        {
            "current_utc": now,
            "deemed_approved_budget_count": deemed,
            "overdue_call_count": overdue,
            "lapsed_cure_count": lapsed,
            "deadlocked_dispute_count": deadlocked,
            "terminated_agreement_count": terminated,
        }
    )
