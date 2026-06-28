"""Time-driven reconciliation fired on every clock advance (PRD §2.6).

On clock advance:
  - Appraisals whose half-open validity window has closed: VALID -> EXPIRED.
  - Policies that are PAST_DUE and sat past GRACE_DAYS: ACTIVE -> LAPSED.
    (A PAID policy never lapses on a clock advance.)
  - ACTIVE items on inflation-guarded policies are revalued once per full
    policy year newly elapsed since bound_at_iso.
Each mutated resource gets its updated_at refreshed and version incremented.
"""
from datetime import timedelta
from dateutil_min import add_months  # local minimal month-arithmetic helper

import calc
import clock
import db


def on_clock_advance():
    now = clock.now()
    _expire_appraisals(now)
    _revalue_items(now)
    _lapse_policies(now)


def _expire_appraisals(now):
    for ap in db.appraisals.values():
        if ap["status"] != "VALID":
            continue
        eff = clock.parse_iso(ap["effective_date_iso"])
        if eff is None:
            continue
        window_end = add_months(eff, ap["valid_months"])
        # Half-open [eff, eff + valid_months): EXPIRED at or after window_end.
        if now >= window_end:
            ap["status"] = "EXPIRED"
            db.touch(ap)


def _revalue_items(now):
    for policy in db.policies.values():
        if policy.get("inflation_guard_mode", "NONE") == "NONE":
            continue
        bound = clock.parse_iso(policy.get("bound_at_iso"))
        if bound is None:
            continue
        epochs = _completed_years(bound, now)
        if epochs <= 0:
            continue
        epochs = min(epochs, calc.MAX_EPOCHS)
        for it in db.scheduled_items.values():
            if it["policy_id"] != policy["id"]:
                continue
            if it["item_status"] != "ACTIVE":
                continue
            if it.get("revaluation_epoch", 0) == epochs:
                continue
            new_value, applied_epoch = calc.revalue_item(it, policy, epochs)
            it["current_value_cents"] = new_value
            it["revaluation_epoch"] = applied_epoch
            db.touch(it)
        # current_value_cents feeds the policy aggregates.
        calc.recompute_policy_aggregates(policy)
        db.touch(policy)


def _lapse_policies(now):
    for policy in db.policies.values():
        if policy["coverage_status"] != "ACTIVE":
            continue
        if policy["billing_status"] != "PAST_DUE":
            continue
        anchor = clock.parse_iso(policy.get("past_due_since"))
        if anchor is None:
            continue
        if now >= anchor + timedelta(days=calc.GRACE_DAYS):
            policy["coverage_status"] = "LAPSED"
            db.touch(policy)


def _completed_years(bound_dt, now_dt):
    """Number of whole 12-month periods elapsed since bound_dt, floored."""
    if now_dt < bound_dt:
        return 0
    years = 0
    while add_months(bound_dt, (years + 1) * 12) <= now_dt:
        years += 1
        if years >= calc.MAX_EPOCHS:
            break
    return years
