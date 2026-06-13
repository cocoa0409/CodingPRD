"""ShutoffOrder routes (PRD §3.9)."""
from flask import Blueprint, request

import clock
import db
import errors
import middleware
from response import object_response, array_response
from services import lookup, ledger
from services.common import (
    get_json_body, require_str, require_datetime, public, public_list,
    parse_pagination, paginate, parse_datetime,
)
from routes.moratoriums import moratorium_covers

bp = Blueprint("shutoff_orders", __name__)


def _active_protection(account_id):
    """An ACTIVE assistance enrollment on the account that grants protection."""
    for e in db.assistance_enrollments.values():
        if e["account_id"] == account_id and e["status"] == "ACTIVE" and e["grants_shutoff_protection"]:
            return True
    return False


@bp.post("/shutoff-orders")
def schedule():
    middleware.require_role({"FieldOps"})
    body = get_json_body()

    account_id = require_str(body, "account_id")
    triggering_bill_id = require_str(body, "triggering_bill_id")
    account = lookup.account(account_id)
    lookup.bill(triggering_bill_id)
    scheduled_for = require_datetime(body, "scheduled_for")

    # State legality (PRD §3.9): transition into SHUTOFF_PENDING is defined out
    # of PAST_DUE.
    if account["billing_status"] != "PAST_DUE":
        raise errors.err(errors.ERR_INVALID_STATE, "Shutoff scheduling requires the account to be PAST_DUE.")

    # Business rules in validation-priority order: moratorium (10), protection
    # (11), arrears (14).
    if moratorium_covers(scheduled_for):
        raise errors.err(errors.ERR_MORATORIUM_ACTIVE, "An active moratorium covers the scheduled date.")
    if _active_protection(account_id):
        raise errors.err(errors.ERR_SHUTOFF_PROTECTED, "Account has assistance that grants shutoff protection.")
    schedule_rec = db.rate_schedules[account["rate_schedule_id"]]
    if account["past_due_cents"] < schedule_rec["arrears_shutoff_threshold_cents"]:
        raise errors.err(errors.ERR_ARREARS_BELOW_THRESHOLD, "past_due_cents is below the arrears shutoff threshold.")

    rec = db.make_record({
        "account_id": account_id,
        "triggering_bill_id": triggering_bill_id,
        "scheduled_for": body["scheduled_for"],
        "reconnect_fee_charged_cents": 0,
        "status": "SCHEDULED",
    })
    db.shutoff_orders[rec["id"]] = rec

    account["billing_status"] = "SHUTOFF_PENDING"
    ledger.reconcile(account)
    return object_response(public(rec), 201)


@bp.get("/shutoff-orders/<rid>")
def get_one(rid):
    middleware.require_role({"FieldOps", "BillingClerk", "Customer"})
    rec = lookup.shutoff_order(rid)
    middleware.require_owner(rec["account_id"])
    return object_response(public(rec), 200)


@bp.get("/shutoff-orders")
def list_all():
    middleware.require_role({"FieldOps", "BillingClerk", "Customer"})
    limit, offset = parse_pagination()

    records = list(db.shutoff_orders.values())
    account_id = request.args.get("account_id")
    triggering_bill_id = request.args.get("triggering_bill_id")
    status = request.args.get("status")

    if account_id is not None:
        records = [r for r in records if r["account_id"] == account_id]
    if triggering_bill_id is not None:
        records = [r for r in records if r["triggering_bill_id"] == triggering_bill_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]

    if middleware.get_role() == "Customer":
        uid = middleware.get_user_id()
        records = [r for r in records if r["account_id"] == uid]

    window, total = paginate(records, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)


@bp.post("/shutoff-orders/<rid>/execute")
def execute(rid):
    middleware.require_role({"FieldOps"})
    order = lookup.shutoff_order(rid)

    # State: execute defined only from SCHEDULED.
    if order["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a SCHEDULED order may be executed.")

    now = clock.now()
    # Business rules: not-due (12) before moratorium (10) per PRD §3.9 prose
    # ("the current server clock has reached or passed scheduled_for (otherwise
    # ERR_SHUTOFF_NOT_DUE), no active moratorium covers the current clock date
    # (otherwise ERR_MORATORIUM_ACTIVE)"). PRD prose wins on ordering.
    scheduled_for = parse_datetime(order["scheduled_for"])
    if now < scheduled_for:
        raise errors.err(errors.ERR_SHUTOFF_NOT_DUE, "Current clock is before scheduled_for.")
    if moratorium_covers(now):
        raise errors.err(errors.ERR_MORATORIUM_ACTIVE, "An active moratorium covers the current clock date.")

    account = db.accounts[order["account_id"]]
    # Account.service_status must still be ACTIVE.
    if account["service_status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Account service is not ACTIVE.")

    order["status"] = "EXECUTED"
    db.touch(order)
    account["service_status"] = "SUSPENDED"
    ledger.reconcile(account)
    return object_response(public(order), 200)


@bp.post("/shutoff-orders/<rid>/reconnect")
def reconnect(rid):
    middleware.require_role({"FieldOps"})
    order = lookup.shutoff_order(rid)

    # Reconnect requires EXECUTED (PRD §3.9).
    if order["status"] != "EXECUTED":
        raise errors.err(errors.ERR_NOT_EXECUTED, "Reconnect requires the order to be EXECUTED.")

    account = db.accounts[order["account_id"]]
    schedule = db.rate_schedules[account["rate_schedule_id"]]

    order["status"] = "RECONNECTED"
    order["reconnect_fee_charged_cents"] = schedule["reconnect_fee_cents"]
    db.touch(order)

    # balance_due increases by reconnect fee (captured by reconciliation since
    # the order is now RECONNECTED); service_status -> RESTORED.
    account["service_status"] = "RESTORED"
    ledger.reconcile(account)
    return object_response(public(order), 200)


@bp.post("/shutoff-orders/<rid>/cancel")
def cancel(rid):
    middleware.require_role({"FieldOps"})
    order = lookup.shutoff_order(rid)

    # Cancel allowed only while SCHEDULED (PRD §3.9).
    if order["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a SCHEDULED order may be cancelled.")

    order["status"] = "CANCELLED"
    db.touch(order)

    account = db.accounts[order["account_id"]]
    # If no other still-active shutoff order, billing_status falls back to PAST_DUE.
    others_active = any(
        o["id"] != rid and o["account_id"] == account["id"]
        and o["status"] in ("SCHEDULED", "EXECUTED")
        for o in db.shutoff_orders.values()
    )
    if not others_active and account["billing_status"] == "SHUTOFF_PENDING":
        account["billing_status"] = "PAST_DUE"
    ledger.reconcile(account)
    return object_response(public(order), 200)
