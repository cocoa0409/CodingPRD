"""Payment endpoints (PRD §3.12)."""

from flask import Blueprint, request

from db import store
from errors import ERR_INVALID_REQUEST, err
from middleware import authenticate, require_role, require_account_ownership
from response import success
from services.common import (
    get_body,
    require_fields,
    require_string,
    require_int,
    attach_event_fields,
    parse_dt,
    to_iso,
    paginate,
)
from services.serialize import view_payment
from services import lookup, calc

bp = Blueprint("payments", __name__)


@bp.route("/accounts/<account_id>/payments", methods=["POST"])
def post_payment(account_id):
    principal = authenticate()
    require_role(principal, {"CustomerService", "Account"})
    with store.lock:
        account = lookup.get_account(account_id)
        require_account_ownership(principal, account_id)
        body = get_body()
        require_fields(body, ["bill_id", "amount_cents"])
        bill_id = require_string(body, "bill_id")
        amount_cents = require_int(body, "amount_cents", exclusive_min=0)

        bill = lookup.get_bill_under_account(account_id, bill_id)

        if "posted_date" in body and body["posted_date"] is not None:
            posted_dt = parse_dt(body["posted_date"])
        else:
            posted_dt = calc.clock_now()
        posted_iso = to_iso(posted_dt)

        on_time = calc.is_on_time(posted_dt, bill) if bill.get("due_date") else True

        rec = {
            "account_id": account_id,
            "bill_id": bill_id,
            "amount_cents": amount_cents,
            "posted_date": posted_iso,
            "status": "POSTED",
            "on_time": on_time,
        }
        attach_event_fields(rec)
        store.payments[rec["id"]] = rec

        # Update bill paid_cents and possibly transition to PAID.
        _recompute_bill_payment(account, bill)

        return success(view_payment(rec), 201)


def _recompute_bill_payment(account, bill):
    posted = [p for p in store.payments.values()
              if p["bill_id"] == bill["id"] and p["status"] == "POSTED"]
    bill["paid_cents"] = sum(p["amount_cents"] for p in posted)

    # Threshold: amount_due_cents for ordinary, budget_billed_cents for budget bill.
    # PRD §3.12: the customer owes budget_billed_cents for a budget bill.
    # budget_billed_cents equals amount_due_cents for a non-budget bill, so it is
    # the correct threshold in both cases.
    threshold = bill["budget_billed_cents"]

    if bill["status"] == "ISSUED" and bill["paid_cents"] >= threshold:
        bill["status"] = "PAID"
        from services.common import bump
        bump(bill)
        # The last allocating payment determines on-time standing.
        last = max(posted, key=lambda p: p["_seq"])
        if last["on_time"]:
            account["consecutive_ontime_payments"] += 1
        else:
            account["consecutive_ontime_payments"] = 0


@bp.route("/payments", methods=["GET"])
def list_payments():
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "Account"})
    account_id = request.args.get("account_id")
    bill_id = request.args.get("bill_id")
    records = list(store.payments.values())
    if account_id is not None:
        records = [p for p in records if p["account_id"] == account_id]
    if bill_id is not None:
        records = [p for p in records if p["bill_id"] == bill_id]
    if principal.role == "Account":
        records = [p for p in records if p["account_id"] == principal.user_id]
    page, list_meta = paginate(records)
    return success([view_payment(p) for p in page], 200, list_meta=list_meta)


@bp.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "Account"})
    payment = lookup.get_payment(payment_id)
    require_account_ownership(principal, payment["account_id"])
    return success(view_payment(payment), 200)
