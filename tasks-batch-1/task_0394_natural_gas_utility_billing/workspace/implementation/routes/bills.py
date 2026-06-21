"""Bill endpoints (PRD §3.5, §3.6) — draft, issue, void, list, get."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_DUPLICATE,
    ERR_BILLING_PERIOD_OVERLAP,
    ERR_INVALID_STATE,
    ERR_STALE_ACCOUNT_VERSION,
    ERR_PGA_NOT_FOUND,
    ERR_READ_REQUIRED,
    ERR_INVALID_REQUEST,
    err,
)
from middleware import authenticate, require_role, require_account_ownership
from response import success
from services.common import (
    get_body,
    require_fields,
    require_string,
    require_month,
    require_int,
    attach_common_fields,
    bump,
    parse_dt,
    add_days_iso,
    paginate,
)
from services.serialize import view_bill
from services import lookup, calc

bp = Blueprint("bills", __name__)


@bp.route("/accounts/<account_id>/bills", methods=["POST"])
def create_bill(account_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin"})
    with store.lock:
        account = lookup.get_account(account_id)
        body = get_body()
        require_fields(body, ["service_month", "to_read_id"])
        service_month = require_month(body, "service_month")
        to_read_id = require_string(body, "to_read_id")

        # Existence (priority 3): validate FK ids left-to-right.
        to_read = lookup.get_read(to_read_id)
        from_read_id = body.get("from_read_id")
        from_read = None
        if from_read_id is not None:
            if not isinstance(from_read_id, str):
                raise err(ERR_INVALID_REQUEST, "from_read_id must be a string")
            from_read = lookup.get_read(from_read_id)
        corrects_bill_id = body.get("corrects_bill_id")
        corrected_bill = None
        if corrects_bill_id is not None:
            if not isinstance(corrects_bill_id, str):
                raise err(ERR_INVALID_REQUEST, "corrects_bill_id must be a string")
            corrected_bill = lookup.get_bill(corrects_bill_id)

        meter_id = to_read["premise_meter_id"]

        # Duplicate (priority 5): at most one non-CORRECTED bill per
        # (account, service_month). A rebill (corrects_bill_id set) is exempt.
        if corrects_bill_id is None:
            for b in store.bills.values():
                if (b["account_id"] == account_id and b["service_month"] == service_month
                        and b["status"] != "CORRECTED" and b["status"] != "VOID"
                        and not b.get("corrects_bill_id")):
                    raise err(ERR_DUPLICATE, "A bill already exists for this account and service month")

        # Billing-period overlap (priority 5.1): closed interval on same meter.
        _check_period_overlap(meter_id, from_read, to_read, corrects_bill_id)

        rec = {
            "account_id": account_id,
            "service_month": service_month,
            "from_read_id": from_read_id,
            "to_read_id": to_read_id,
            "corrects_bill_id": corrects_bill_id,
            "therms_billed": 0,
            "commodity_charge_cents": 0,
            "distribution_charge_cents": 0,
            "fixed_charge_cents": 0,
            "low_income_credit_cents": 0,
            "amount_due_cents": 0,
            "budget_billed_cents": 0,
            "status": "DRAFT",
            "due_date": None,
            "paid_cents": 0,
        }
        attach_common_fields(rec)
        store.bills[rec["id"]] = rec
        return success(view_bill(rec), 201)


def _bill_window(bill):
    """Return (start_dt, end_dt) read-date window for an existing bill, or None
    when it cannot be determined."""
    to_read = store.meter_reads.get(bill.get("to_read_id"))
    if to_read is None:
        return None
    end = parse_dt(to_read["read_date"])
    from_read = store.meter_reads.get(bill.get("from_read_id")) if bill.get("from_read_id") else None
    start = parse_dt(from_read["read_date"]) if from_read else end
    return start, end


def _check_period_overlap(meter_id, from_read, to_read, corrects_bill_id):
    new_end = parse_dt(to_read["read_date"])
    new_start = parse_dt(from_read["read_date"]) if from_read else new_end
    for b in store.bills.values():
        if b["status"] in ("VOID", "CORRECTED"):
            continue
        # Exempt the very bill a rebill is correcting.
        if corrects_bill_id is not None and b["id"] == corrects_bill_id:
            continue
        b_to = store.meter_reads.get(b.get("to_read_id"))
        if b_to is None or b_to["premise_meter_id"] != meter_id:
            continue
        win = _bill_window(b)
        if win is None:
            continue
        ex_start, ex_end = win
        # Closed interval: touching endpoints DO collide.
        if new_start <= ex_end and ex_start <= new_end:
            raise err(ERR_BILLING_PERIOD_OVERLAP, "Bill period overlaps an existing bill on this meter")


@bp.route("/accounts/<account_id>/bills/<bill_id>/issue", methods=["POST"])
def issue_bill(account_id, bill_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin"})
    with store.lock:
        account = lookup.get_account(account_id)
        bill = lookup.get_bill_under_account(account_id, bill_id)
        body = get_body()
        require_fields(body, ["expected_account_version"])
        expected = require_int(body, "expected_account_version")

        # State check (priority 6): must be DRAFT to issue.
        if bill["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "Bill is not DRAFT")

        # Referential prerequisites (priority 10) precede OCC (priority 11)
        # per PRD §2.10 relative ordering.
        pga = _find_pga(account["customer_class"], bill["service_month"])
        if pga is None:
            raise err(ERR_PGA_NOT_FOUND, "No PGA schedule for customer class and service month")

        to_read = store.meter_reads.get(bill["to_read_id"])
        if to_read is None or to_read["status"] != "POSTED" or to_read["read_type"] not in ("ACTUAL", "ESTIMATED"):
            raise err(ERR_READ_REQUIRED, "A valid closing read is required")
        from_read = store.meter_reads.get(bill["from_read_id"]) if bill.get("from_read_id") else None
        if from_read is not None:
            if parse_dt(to_read["read_date"]) <= parse_dt(from_read["read_date"]):
                raise err(ERR_READ_REQUIRED, "Closing read must be newer than opening read")

        # OCC (priority 11).
        if expected != account["version"]:
            raise err(ERR_STALE_ACCOUNT_VERSION, "expected_account_version does not match current account version")

        rate_schedule = store.rate_schedules[account["rate_schedule_id"]]
        charges = calc.compute_bill_charges(
            account, to_read, rate_schedule, pga, account["low_income_tier"])
        bill.update(charges)

        # Budget vs actual-cost (PRD §3.5).
        active_plan = _active_budget_plan(account_id)
        if active_plan is not None:
            bill["budget_billed_cents"] = active_plan["monthly_installment_cents"]
        else:
            bill["budget_billed_cents"] = bill["amount_due_cents"]

        bill["status"] = "ISSUED"
        bill["due_date"] = add_days_iso(calc.clock_now(), calc.PAYMENT_TERM_DAYS)
        bump(bill)

        # Mark closing read consumed.
        to_read["bill_id"] = bill["id"]
        if from_read is not None:
            from_read["bill_id"] = from_read.get("bill_id") or bill["id"]

        # Correction cascade: original ISSUED bill in same month -> CORRECTED.
        if bill.get("corrects_bill_id"):
            original = store.bills.get(bill["corrects_bill_id"])
            if original is not None and original["status"] == "ISSUED":
                original["status"] = "CORRECTED"
                bump(original)

        # Account version bump on issue.
        bump(account)

        # Budget accrual cascade.
        if active_plan is not None:
            active_plan["accrued_actual_cents"] += bill["amount_due_cents"]
            active_plan["accrued_budget_cents"] += bill["budget_billed_cents"]
            bump(active_plan)

        return success(view_bill(bill), 200)


@bp.route("/accounts/<account_id>/bills/<bill_id>/void", methods=["POST"])
def void_bill(account_id, bill_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin"})
    with store.lock:
        account = lookup.get_account(account_id)
        bill = lookup.get_bill_under_account(account_id, bill_id)
        if bill["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "Only DRAFT bills can be voided")
        bill["status"] = "VOID"
        bump(bill)
        # Release reads in the window.
        for rid in (bill.get("to_read_id"), bill.get("from_read_id")):
            if not rid:
                continue
            read = store.meter_reads.get(rid)
            if read is not None and read.get("bill_id") == bill["id"]:
                read["bill_id"] = None
        return success(view_bill(bill), 200)


@bp.route("/bills", methods=["GET"])
def list_bills():
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "Account"})
    account_id = request.args.get("account_id")
    from_read_id = request.args.get("from_read_id")
    to_read_id = request.args.get("to_read_id")
    corrects_bill_id = request.args.get("corrects_bill_id")
    records = list(store.bills.values())
    if account_id is not None:
        records = [b for b in records if b["account_id"] == account_id]
    if from_read_id is not None:
        records = [b for b in records if b.get("from_read_id") == from_read_id]
    if to_read_id is not None:
        records = [b for b in records if b.get("to_read_id") == to_read_id]
    if corrects_bill_id is not None:
        records = [b for b in records if b.get("corrects_bill_id") == corrects_bill_id]
    if principal.role == "Account":
        records = [b for b in records if b["account_id"] == principal.user_id]
    page, list_meta = paginate(records)
    return success([view_bill(b) for b in page], 200, list_meta=list_meta)


@bp.route("/bills/<bill_id>", methods=["GET"])
def get_bill(bill_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "Account"})
    bill = lookup.get_bill(bill_id)
    require_account_ownership(principal, bill["account_id"])
    return success(view_bill(bill), 200)


def _find_pga(customer_class, service_month):
    for p in store.pga_schedules.values():
        if p["customer_class"] == customer_class and p["effective_month"] == service_month:
            return p
    return None


def _active_budget_plan(account_id):
    for p in store.budget_plans.values():
        if p["account_id"] == account_id and p["status"] == "ACTIVE":
            return p
    return None
