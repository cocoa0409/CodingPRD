"""BillingCycle routes (PRD §3.3)."""
from flask import Blueprint

import db
import middleware
from response import object_response
from services import lookup, ledger
from services.common import (
    get_json_body, require_str, require_datetime, public,
)
from services.calc import round_half_up

bp = Blueprint("billing_cycles", __name__)


@bp.post("/billing-cycles")
def create_cycle():
    middleware.require_role({"BillingClerk"})
    body = get_json_body()

    label = require_str(body, "label")
    require_datetime(body, "period_start")
    require_datetime(body, "period_end")
    require_datetime(body, "due_date")

    rec = db.make_record({
        "label": label,
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "due_date": body["due_date"],
        "status": "OPEN",
    })
    db.billing_cycles[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/billing-cycles/<rid>")
def get_cycle(rid):
    middleware.require_role({"BillingClerk", "Customer"})
    rec = lookup.billing_cycle(rid)
    return object_response(public(rec), 200)


@bp.post("/billing-cycles/<rid>/close")
def close_cycle(rid):
    middleware.require_role({"BillingClerk"})
    cycle = lookup.billing_cycle(rid)

    # Walk every POSTED (unpaid) bill in this cycle; assess late fee; flip the
    # owning account to PAST_DUE (PRD §3.3).
    affected_accounts = set()
    for bill in db.bills.values():
        if bill["billing_cycle_id"] != rid:
            continue
        if bill["status"] != "POSTED":
            continue
        schedule = db.rate_schedules[bill["rate_schedule_id"]]
        # late_fee = unpaid principal * late_fee_pct / 100, round half up.
        # Unpaid principal of a POSTED bill is its total_cents (not yet PAID).
        late_fee = round_half_up(
            bill["total_cents"] * schedule["late_fee_pct"] / 100
        )
        bill["late_fee_cents"] = late_fee
        db.touch(bill)
        affected_accounts.add(bill["account_id"])

    cycle["status"] = "CLOSED"
    db.touch(cycle)

    # Each affected account moves CURRENT -> PAST_DUE (the transition requires
    # >= 1 POSTED unpaid bill in the closing cycle, which holds by construction).
    for aid in affected_accounts:
        account = db.accounts.get(aid)
        if account is None:
            continue
        if account["billing_status"] == "CURRENT":
            account["billing_status"] = "PAST_DUE"
        ledger.reconcile(account)

    return object_response(public(cycle), 200)
