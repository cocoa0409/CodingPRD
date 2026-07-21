"""System billing sweep: POST /_billing/run-cycle (PRD §3.3)."""
from datetime import timedelta
from db import db, touch, fmt_ts, now, parse_ts, new_common_fields, add_months
import lookups
from services import calculations as calc

OVERDUE_GRACE_DAYS = 5


def _latest_invoice(policy_id):
    invoices = lookups.invoices_for_policy(policy_id)
    if not invoices:
        return None
    return max(invoices, key=lambda i: (i["created_at"], i["id"]))


def run_billing_cycle():
    clock = now()

    # Step A: mark overdue invoices, cascade ACTIVE -> LAPSED.
    for invoice in list(db.invoices.values()):
        if invoice["status"] != "ISSUED":
            continue
        due = parse_ts(invoice["due_date"])
        if clock >= due + timedelta(days=OVERDUE_GRACE_DAYS):
            invoice["status"] = "OVERDUE"
            touch(invoice)
            policy = db.policies[invoice["policy_id"]]
            if policy["status"] == "ACTIVE":
                policy["status"] = "LAPSED"
                touch(policy)

    # Step B: issue the next invoice when the current one is paid and its period has elapsed.
    for policy in list(db.policies.values()):
        if policy["status"] not in ("ACTIVE", "LAPSED"):
            continue
        current = _latest_invoice(policy["id"])
        if current is None or current["status"] != "PAID":
            continue
        period_end = parse_ts(current["billing_period_end"])
        if clock >= period_end:
            billing_period_start = period_end
            billing_period_end = add_months(billing_period_start, 1)
            due_date = billing_period_start + timedelta(days=10)
            allocation = calc.premium_installment_allocation(policy["monthly_fee_cents"])
            invoice = {
                **new_common_fields(),
                "policy_id": policy["id"],
                "billing_period_start": fmt_ts(billing_period_start),
                "billing_period_end": fmt_ts(billing_period_end),
                "amount_cents": allocation["amount_cents"],
                "insurance_premium_cents": allocation["insurance_premium_cents"],
                "platform_fee_cents": allocation["platform_fee_cents"],
                "state_tax_cents": allocation["state_tax_cents"],
                "due_date": fmt_ts(due_date),
                "status": "ISSUED",
                "paid_at": None,
            }
            db.invoices[invoice["id"]] = invoice

    # Step C: expire policies whose lease has ended.
    for policy in list(db.policies.values()):
        if policy["status"] not in ("ACTIVE", "LAPSED"):
            continue
        lease_end = parse_ts(policy["lease_end_date"])
        if clock >= lease_end:
            policy["status"] = "EXPIRED"
            touch(policy)
