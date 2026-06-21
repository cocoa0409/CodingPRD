"""Invoice charge computation and ledger reconciliation (PRD §3.6, §3.7)."""
from db import db, touch
from services import calculations as calc
from services.calculations import SEVERITY_RANK


def _tickets_in_window(account_id, period_start, period_end):
    """Yield (weight_ticket, pickup, cart) tuples for COMPLETED pickups belonging
    to this account whose ticket.created_at is in [period_start, period_end)."""
    for wt in db.weight_tickets.values():
        pu = db.pickups.get(wt["pickup_id"])
        if pu is None or pu["outcome"] != "COMPLETED":
            continue
        cart = db.carts.get(pu["cart_id"])
        if cart is None or cart["account_id"] != account_id:
            continue
        if not (period_start <= wt["created_at"] < period_end):
            continue
        yield wt, pu, cart


def compute_charges(invoice):
    """Compute and store the five charge components + total + balance on the
    invoice record, in the pinned evaluation order (PRD §3.6)."""
    account_id = invoice["account_id"]
    period_start = invoice["period_start"]
    period_end = invoice["period_end"]

    # 1. base_fee_cents — sum of ACTIVE ServicePlan.base_monthly_fee_cents.
    base_fee = 0
    for plan in db.service_plans.values():
        if plan["account_id"] == account_id and plan["status"] == "ACTIVE":
            base_fee += plan["base_monthly_fee_cents"]

    # 2. weight_charge_cents — PAYT over TRASH-stream completed tickets in window.
    account = db.accounts[account_id]
    trash_net = []
    for wt, pu, cart in _tickets_in_window(account_id, period_start, period_end):
        if cart["stream"] == "TRASH":
            trash_net.append(wt["net_weight_lbs"])
    weight_charge = calc.payt_weight_charge_cents(trash_net, account["rate_class"])

    # 3. contamination_surcharge_cents — round-per-pickup-then-sum.
    pickup_lines = []
    for wt, pu, cart in _tickets_in_window(account_id, period_start, period_end):
        tags = [
            t for t in db.contamination_tags.values() if t["pickup_id"] == pu["id"]
        ]
        if not tags:
            continue
        highest = max(tags, key=lambda t: SEVERITY_RANK[t["severity"]])
        pickup_lines.append((wt["net_weight_lbs"], highest["severity"]))
    contamination = calc.contamination_surcharge_cents(pickup_lines)

    # 4. diversion_penalty_cents — FINALIZED DiversionPeriod with matching window.
    diversion_penalty = 0
    matched = None
    for dp in db.diversion_periods.values():
        if (
            dp["account_id"] == account_id
            and dp["status"] == "FINALIZED"
            and dp["period_start"] == period_start
            and dp["period_end"] == period_end
        ):
            matched = dp
            break
    if matched is not None:
        diversion_penalty = calc.diversion_penalty_cents(
            account["diversion_floor_pct"], matched["diversion_rate_pct"]
        )

    # 5. credit_cents — sum of APPLIED credits absorbed onto THIS invoice.
    credit = 0
    for cr in db.credits.values():
        if cr["applied_invoice_id"] == invoice["id"] and cr["status"] == "APPLIED":
            credit += cr["amount_cents"]

    invoice["base_fee_cents"] = base_fee
    invoice["weight_charge_cents"] = weight_charge
    invoice["contamination_surcharge_cents"] = contamination
    invoice["diversion_penalty_cents"] = diversion_penalty
    invoice["credit_cents"] = credit
    invoice["total_cents"] = calc.invoice_total_cents(
        base_fee, weight_charge, contamination, diversion_penalty, credit
    )
    invoice["balance_cents"] = invoice["total_cents"]


def absorb_pending_credits(invoice):
    """During issue: move eligible PENDING credits for the account to APPLIED,
    attaching them to this invoice. Each absorbed credit's version is bumped."""
    for cr in db.credits.values():
        if cr["status"] == "PENDING" and cr["account_id"] == invoice["account_id"]:
            cr["status"] = "APPLIED"
            cr["applied_invoice_id"] = invoice["id"]
            touch(cr)


def release_applied_credits(invoice):
    """During void: release credits applied to this invoice back to PENDING."""
    for cr in db.credits.values():
        if cr["status"] == "APPLIED" and cr["applied_invoice_id"] == invoice["id"]:
            cr["status"] = "PENDING"
            cr["applied_invoice_id"] = None
            touch(cr)


def recompute_account_balance(account_id):
    """account_balance_cents is a derived read; bump the account version so the
    OCC token reflects that the balance changed (PRD §2.7/§2.8)."""
    account = db.accounts.get(account_id)
    if account is not None:
        touch(account)
