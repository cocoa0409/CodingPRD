"""The nightly billing run: five passes in the pinned order (PRD 2.12)."""
from datetime import timedelta

import config
from clock import clock, parse_date
from db import by_seq, db, new_id
from response import touch
from services import cancellation, dunning, engagement, holds as holds_service
from services.derive import (
    group_seats,
    recompute_group_counters,
    subscription_invoices,
)
from services.pricing import assemble_invoice, recompute_next_price

PASSES = ("HOLDS", "EXPIRY", "BILLING", "DUNNING", "ENGAGEMENT")

SCOPE_PASSES = {
    "FULL": PASSES,
    "HOLDS_ONLY": ("HOLDS",),
    "EXPIRY_ONLY": ("EXPIRY",),
    "BILLING_ONLY": ("BILLING",),
    "DUNNING_ONLY": ("DUNNING",),
    "ENGAGEMENT_ONLY": ("ENGAGEMENT",),
}


def _plan(sub):
    return db.offer_plans.get(sub["offer_plan_id"])


def _reader(sub):
    return db.readers.get(sub["reader_id"])


def run(scope):
    report = {
        "run_id": new_id(),
        "scope": scope,
        "holds_activated": [],
        "holds_completed": [],
        "subscriptions_paused": [],
        "subscriptions_resumed": [],
        "cancellations_completed": [],
        "seats_expired": [],
        "invoices_created": [],
        "subscriptions_cancelled_nonpay": [],
        "cards_updated": [],
        "readers_rescored": [],
    }
    active_passes = SCOPE_PASSES[scope]
    if "HOLDS" in active_passes:
        _holds_pass(report)
    if "EXPIRY" in active_passes:
        _expiry_pass(report)
    if "BILLING" in active_passes:
        _billing_pass(report)
    if "DUNNING" in active_passes:
        _dunning_pass(report)
    if "ENGAGEMENT" in active_passes:
        _engagement_pass(report)
    return report


def _holds_pass(report):
    today = clock.date()
    for hold in by_seq(list(db.holds.values())):
        if hold["status"] != "SCHEDULED":
            continue
        if parse_date(hold["start_date"]) > today:
            continue
        sub = db.subscriptions.get(hold["subscription_id"])
        if sub is None or sub["lifecycle_status"] not in ("ACTIVE", "PAUSED"):
            continue
        outcome = holds_service.activate_hold(hold, sub, _plan(sub))
        report["holds_activated"].append(hold["id"])
        if outcome == "paused":
            report["subscriptions_paused"].append(sub["id"])
            reader = _reader(sub)
            if reader is not None:
                touch(reader)

    for hold in by_seq(list(db.holds.values())):
        if hold["status"] != "ACTIVE":
            continue
        if not parse_date(hold["end_date"]) < today:
            continue
        sub = db.subscriptions.get(hold["subscription_id"])
        if sub is None:
            continue
        outcome = holds_service.complete_hold(hold, sub, _plan(sub))
        report["holds_completed"].append(hold["id"])
        if outcome == "resumed":
            report["subscriptions_resumed"].append(sub["id"])
            reader = _reader(sub)
            if reader is not None:
                touch(reader)


def _expiry_pass(report):
    today = clock.date()

    for sub in by_seq(list(db.subscriptions.values())):
        if sub["lifecycle_status"] != "CANCEL_SCHEDULED":
            continue
        effective_on = sub.get("cancel_effective_on")
        if effective_on is None or not today > parse_date(effective_on):
            continue
        sub["lifecycle_status"] = "CANCELLED"
        if sub["print_fulfillment_status"] == "STOPPED_AT_CYCLE_END":
            sub["print_fulfillment_status"] = "STOPPED"
        touch(sub)
        for req in by_seq(cancellation.requests_of(sub["id"])):
            if req["status"] == "CONFIRMED":
                cancellation.complete(req)
                report["cancellations_completed"].append(req["id"])
        reader = _reader(sub)
        if reader is not None:
            touch(reader)

    for req in by_seq(list(db.cancellation_requests.values())):
        if req["status"] not in config.CANCELLATION_OPEN_STATUSES:
            continue
        age_days = (today - req["_created_dt"].date()).days
        if age_days < config.CANCELLATION_REQUEST_EXPIRY_DAYS:
            continue
        cancellation.abandon(req)

    for seat in by_seq(list(db.seats.values())):
        if seat["status"] != "INVITED":
            continue
        if not today > parse_date(seat["invite_expires_on"]):
            continue
        seat["status"] = "EXPIRED"
        touch(seat)
        report["seats_expired"].append(seat["id"])
        group = db.group_accounts.get(seat["group_account_id"])
        if group is not None:
            recompute_group_counters(group)
            touch(group)
        seat_reader = db.readers.get(seat["reader_id"])
        if seat_reader is not None:
            touch(seat_reader)


def _has_open_invoice(sub):
    for invoice in subscription_invoices(sub["id"]):
        if invoice["status"] in ("OPEN", "PAST_DUE"):
            return True
    return False


def _billing_pass(report):
    today = clock.date()
    for sub in by_seq(list(db.subscriptions.values())):
        if sub["lifecycle_status"] not in ("PENDING_ACTIVATION", "ACTIVE"):
            continue
        paid_through = sub.get("paid_through_on")
        if paid_through is None or parse_date(paid_through) > today:
            continue
        if _has_open_invoice(sub):
            continue
        plan = _plan(sub)
        if plan is None:
            continue
        sub["cycle_index"] = sub["cycle_index"] + 1
        sub["cycle_start_on"] = (
            parse_date(sub["cycle_start_on"]) + timedelta(days=plan["cycle_days"])
        ).isoformat()
        invoice = assemble_invoice(sub, plan, sub["cycle_index"], sub["cycle_start_on"])
        touch(sub)
        report["invoices_created"].append(invoice["id"])


def _dunning_pass(report):
    for sub in by_seq(list(db.subscriptions.values())):
        reader = _reader(sub)
        if dunning.card_updater_sweep(sub, reader):
            report["cards_updated"].append(reader["id"])

    for sub in by_seq(list(db.subscriptions.values())):
        if sub["dunning_status"] != "RECOVERED":
            continue
        if any(i["status"] == "PAST_DUE" for i in subscription_invoices(sub["id"])):
            continue
        sub["dunning_status"] = "CURRENT"
        sub["dunning_first_failed_on"] = None
        touch(sub)
        reader = _reader(sub)
        if reader is not None and engagement.reband_churn(reader):
            touch(reader)


def _engagement_pass(report):
    for reader in by_seq(list(db.readers.values())):
        changed = engagement.maybe_reset_meter_period(reader)
        if engagement.rescore(reader):
            changed = True
        if engagement.refresh_propensity(reader):
            changed = True
        if changed:
            touch(reader)
        report["readers_rescored"].append(reader["id"])


def group_seat_ids(group_account_id):
    return [s["id"] for s in group_seats(group_account_id)]


def recompute_all_next_prices(plan, statuses):
    for sub in by_seq(list(db.subscriptions.values())):
        if sub["offer_plan_id"] != plan["id"]:
            continue
        if sub["lifecycle_status"] not in statuses:
            continue
        recompute_next_price(sub, plan)
