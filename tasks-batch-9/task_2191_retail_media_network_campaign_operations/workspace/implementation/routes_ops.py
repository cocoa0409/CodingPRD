"""Operational fixtures: the logical clock and the daily checkpoint sweep.

Both endpoints live at the host root, outside the /rmn prefix (PRD 4).
"""
import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint

from core import F, db, fail, fmt_dt, now, ok, parse_dt, rows, sort_rows, touch
import derive as D
import helpers as H
from guard import guard
from routes_campaign import activate_eligible_line_items

bp = Blueprint("ops", __name__)

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
POOL_CLOSE_HOURS = 24


@bp.post("/_clock/set_current_utc")
def set_clock():
    specs = (F("current_utc", "datetime", required=True),)
    ctx = guard(("NetworkAdmin",), body_specs=specs)
    db.clock = ctx.data["current_utc"]
    return ok({"current_utc": fmt_dt(db.clock)})


def _as_of(raw):
    if raw is None:
        return None
    if isinstance(raw, str) and _DATE_ONLY.match(raw.strip()):
        return parse_dt(raw.strip() + "T00:00:00Z")
    parsed = parse_dt(raw) if isinstance(raw, str) else None
    if parsed is None:
        fail("ERR_VALIDATION", "as_of_date must be an ISO-8601 date or instant.")
    return parsed


# ---------------------------------------------------------------------------
# Family one: elapsed flights, opened plan windows
# ---------------------------------------------------------------------------
def _sweep_plans_open():
    promoted = 0
    for plan in sort_rows(rows("budget_plan")):
        if plan["plan_status"] != "APPROVED":
            continue
        if now() < plan["window_start_at"]:
            continue
        adv = db.advertisers.get(plan["advertiser_id"])
        if adv is None or adv["onboarding_status"] != "ACTIVE":
            continue
        H.promote_plan_active(plan)
        promoted += 1
    return promoted


def _sweep_campaigns_start():
    started = 0
    for camp in sort_rows(rows("campaign")):
        if camp["delivery_status"] != "SCHEDULED":
            continue
        if not (camp["flight_start_at"] <= now() < camp["flight_end_at"]):
            continue
        adv = db.advertisers.get(camp["advertiser_id"])
        plan = D.plan_of_campaign(camp)
        if adv is None or adv["onboarding_status"] != "ACTIVE":
            continue
        if plan is None or plan["plan_status"] not in ("APPROVED", "ACTIVE"):
            continue
        camp["delivery_status"] = "DELIVERING"
        H.promote_plan_active(plan)
        activate_eligible_line_items(camp)
        D.recompute_pacing(camp)
        touch(camp)
        H.fire_billing(camp, "ACCRUING")
        started += 1
    return started


def _sweep_campaigns_end():
    completed = 0
    for camp in sort_rows(rows("campaign")):
        if camp["delivery_status"] not in ("DELIVERING", "PAUSED"):
            continue
        if now() < camp["flight_end_at"]:
            continue
        camp["delivery_status"] = "COMPLETED"
        touch(camp)
        for li in D.line_items_of_campaign(camp["id"]):
            if li["line_item_status"] in ("ELIGIBLE", "SERVING", "OOS_PAUSED",
                                          "MANUAL_PAUSED"):
                H.end_line_item(li)
        H.fire_billing(camp, "PENDING_INVOICE")
        completed += 1
    return completed


# ---------------------------------------------------------------------------
# Family two: pacing
# ---------------------------------------------------------------------------
def _sweep_pacing():
    count = 0
    for camp in sort_rows(rows("campaign")):
        before = camp["pacing_index"]
        D.recompute_pacing(camp)
        if camp["pacing_index"] != before:
            touch(camp)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Family three: drained budget plans
# ---------------------------------------------------------------------------
def _sweep_plan_exhaustion():
    exhausted = 0
    for plan in sort_rows(rows("budget_plan")):
        if H.exhaust_plan_if_drained(plan):
            exhausted += 1
    return exhausted


# ---------------------------------------------------------------------------
# Family four: dispute service levels
# ---------------------------------------------------------------------------
def _sweep_disputes():
    breached = 0
    for dispute in sort_rows(rows("dispute")):
        due = dispute["sla_due_at"]
        if due is None or dispute["first_response_at"] is not None:
            continue
        if now() < due:
            continue
        if dispute["dispute_status"] not in ("SUBMITTED", "UNDER_REVIEW",
                                            "INFO_REQUESTED"):
            continue
        dispute["sla_breached"] = True
        if dispute["dispute_status"] in ("UNDER_REVIEW", "INFO_REQUESTED"):
            # a service level failure escalates at level one and re-runs the
            # clock, clearing first_response_at back to null
            dispute["dispute_status"] = "ESCALATED"
            dispute["escalation_level"] = 1
            dispute["first_response_at"] = None
            D.recompute_sla(dispute)
            dispute["sla_breached"] = True
        touch(dispute)
        breached += 1
    return breached


# ---------------------------------------------------------------------------
# Trade fund period end: RECONCILING then CLOSED
# ---------------------------------------------------------------------------
def _quarter_end(code):
    year, quarter = code.split("-Q")
    month = int(quarter) * 3
    if month == 12:
        return datetime(int(year) + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(int(year), month + 1, 1, tzinfo=timezone.utc)


def _sweep_pools():
    moved = 0
    for pool in sort_rows(rows("trade_fund_account")):
        if pool["account_status"] == "OPEN" and \
                now() >= _quarter_end(pool["fiscal_period_code"]):
            invoices = D.invoices_of_pool(pool["id"])
            if all(inv["invoice_status"] in ("SETTLED", "WRITTEN_OFF",
                                            "ADJUSTED") for inv in invoices):
                pool["account_status"] = "RECONCILING"
                pool["last_reconciled_at"] = now()
                touch(pool)
                moved += 1
                continue
        if pool["account_status"] == "RECONCILING":
            if D.pool_reserved(pool) != 0:
                continue
            reconciled = pool["last_reconciled_at"]
            if reconciled is None or \
                    now() < reconciled + timedelta(hours=POOL_CLOSE_HOURS):
                continue
            pool["account_status"] = "CLOSED"
            touch(pool)
            moved += 1
    return moved


@bp.post("/_ops/run-daily-checkpoint")
def run_daily_checkpoint():
    ctx = guard(("NetworkAdmin",))
    as_of = _as_of(ctx.raw.get("as_of_date"))
    saved = db.clock
    if as_of is not None:
        db.clock = as_of
    try:
        summary = {
            "as_of": fmt_dt(now()),
            "plans_promoted": _sweep_plans_open(),
            "campaigns_activated": _sweep_campaigns_start(),
            "campaigns_completed": _sweep_campaigns_end(),
            "campaigns_repaced": _sweep_pacing(),
            "plans_exhausted": _sweep_plan_exhaustion(),
            "disputes_breached": _sweep_disputes(),
            "pools_advanced": _sweep_pools(),
        }
    finally:
        db.clock = saved
    return ok(summary)
