"""Business-logic services: state machines, cascades, allocation waterfall.

Every mutation here traces to a §3 narrative in the PRD. Each entity touched by
a cascade independently has its updated_at refreshed and its version bumped
(PRD §2.9), EXCEPT the computed-ledger fields on PatientAccount/Provider whose
side-effect notes in the scaffold do not list a version bump (current_balance,
available_credit, monthly_settled_volume, settled_net, delinquency_strikes);
those move under the cascade without an explicit per-cascade version bump unless
the scaffold transition lists one (e.g. account close bumps the account).
"""
import db
import calculations as calc
from models import touch


# ---------------------------------------------------------------------
# PatientAccount delinquency machine + cure helper
# ---------------------------------------------------------------------
def _open_statement(account_id):
    """Return the single OPEN BillingStatement for an account, or None."""
    for stmt in db.billing_statements.values():
        if stmt["patient_account_id"] == account_id and stmt["status"] == "OPEN":
            return stmt
    return None


def _amount_paid_in_cycle(account_id, period_start, period_end):
    """Sum POSTED Payment.amount_cents within [period_start, period_end].

    When period_end is None (an auto-opened next cycle whose end is not yet
    fixed) the upper bound is open: count every POSTED payment at/after
    period_start. This is used by the in-cycle cure check before close.
    """
    total = 0
    for payment in db.payments.values():
        if payment["patient_account_id"] != account_id:
            continue
        if payment["status"] != "POSTED":
            continue
        posted_at = payment["posted_at"]
        if posted_at is None:
            continue
        if posted_at < period_start:
            continue
        if period_end is not None and posted_at > period_end:
            continue
        total += payment["amount_cents"]
    return total


def maybe_cure_on_payment(account):
    """A payment may lift the open cycle's paid-in amount to satisfy the open
    statement's minimum; if the account is DELINQUENT, cure it (PRD §3.4/§3.7)."""
    if account["status"] != "DELINQUENT":
        return
    stmt = _open_statement(account["id"])
    if stmt is None:
        return
    paid = _amount_paid_in_cycle(account["id"], stmt["period_start"], stmt["period_end"])
    minimum = stmt.get("minimum_payment_due_cents")
    if minimum is None:
        # The open statement's minimum is computed at close; before close, use the
        # live minimum against the current balance to test satisfaction.
        minimum = calc.minimum_payment(account, account["current_balance_cents"])
    if paid >= minimum:
        account["delinquency_strikes"] = 0
        account["status"] = "ACTIVE"


def maybe_cure_on_balance_decrement(account):
    """A refund's balance decrement may satisfy the open statement minimum and
    cure a DELINQUENT account (PRD §3.9). The decrement lowers the open
    minimum (open principal shrinks); cure if the in-cycle paid amount now meets
    the recomputed minimum."""
    if account["status"] != "DELINQUENT":
        return
    stmt = _open_statement(account["id"])
    if stmt is None:
        return
    paid = _amount_paid_in_cycle(account["id"], stmt["period_start"], stmt["period_end"])
    minimum = calc.minimum_payment(account, account["current_balance_cents"])
    if paid >= minimum:
        account["delinquency_strikes"] = 0
        account["status"] = "ACTIVE"


# ---------------------------------------------------------------------
# Payment allocation waterfall (PRD §3.4 / SCAFFOLD payment_allocation)
# ---------------------------------------------------------------------
def _open_purchases_for_account(account_id):
    purchases = []
    for purchase in db.financed_purchases.values():
        if purchase["patient_account_id"] != account_id:
            continue
        if purchase["settlement_status"] in ("REFUNDED", "VOID"):
            continue
        principal_open = purchase["principal_cents"] - purchase["principal_paid_cents"]
        interest_open = purchase["deferred_interest_posted_cents"] - purchase["_interest_paid_cents"]
        if principal_open <= 0 and interest_open <= 0:
            continue
        purchases.append(purchase)
    # primary sort: promo_end ASC; tie-break: created_at ASC (then seq for determinism).
    purchases.sort(key=lambda p: (p["promo_end"], p["created_at"], p["_seq"]))
    return purchases


def allocate_payment(account, payment):
    """Run the waterfall, mutate purchases + balance, flip promo axis, cure."""
    remaining = payment["amount_cents"]
    allocation = []
    flipped_purchases = []  # purchase ids flipped DEFERRED->PAID_IN_FULL by this payment
    clock_now = db.clock.now()

    for purchase in _open_purchases_for_account(account["id"]):
        interest_open = purchase["deferred_interest_posted_cents"] - purchase["_interest_paid_cents"]
        interest_applied = min(remaining, max(0, interest_open))
        remaining -= interest_applied
        principal_open = purchase["principal_cents"] - purchase["principal_paid_cents"]
        principal_applied = min(remaining, max(0, principal_open))
        remaining -= principal_applied

        if principal_applied > 0 or interest_applied > 0:
            purchase["_interest_paid_cents"] += interest_applied
            purchase["principal_paid_cents"] += principal_applied
            allocation.append({
                "financed_purchase_id": purchase["id"],
                "principal_applied_cents": principal_applied,
                "interest_applied_cents": interest_applied,
            })
            # promo axis flip: principal fully paid while DEFERRED and clock < promo_end.
            if (purchase["promo_status"] == "DEFERRED"
                    and purchase["principal_paid_cents"] == purchase["principal_cents"]
                    and clock_now < purchase["promo_end"]):
                purchase["promo_status"] = "PAID_IN_FULL"
                flipped_purchases.append(purchase["id"])
            touch(purchase)
        if remaining == 0:
            break

    payment["allocation"] = allocation
    # Balance decrements by the full payment amount, floored at 0 (surplus only
    # reduces toward zero, never negative — PRD §3.4).
    account["current_balance_cents"] = max(0, account["current_balance_cents"] - payment["amount_cents"])
    payment["_flipped_purchase_ids"] = flipped_purchases

    # A payment may cure an open delinquency.
    maybe_cure_on_payment(account)


def reverse_payment(account, payment):
    """Unwind a payment's allocation (PRD §3.4)."""
    clock_now = db.clock.now()
    for line in payment["allocation"]:
        purchase = db.financed_purchases.get(line["financed_purchase_id"])
        if purchase is None:
            continue
        purchase["principal_paid_cents"] -= line["principal_applied_cents"]
        purchase["_interest_paid_cents"] -= line["interest_applied_cents"]
        # Revert a PAID_IN_FULL that this payment alone caused, if still pre-promo_end.
        if (purchase["id"] in payment.get("_flipped_purchase_ids", [])
                and purchase["promo_status"] == "PAID_IN_FULL"
                and clock_now < purchase["promo_end"]):
            purchase["promo_status"] = "DEFERRED"
        touch(purchase)
    account["current_balance_cents"] += payment["amount_cents"]


# ---------------------------------------------------------------------
# Settlement creation + fee (PRD §3.5)
# ---------------------------------------------------------------------
def create_settlement(purchase, provider):
    from models import new_entity
    recompute_provider_volumes(provider)
    gross = purchase["principal_cents"]
    rate, fee, net = calc.settlement_fee(provider, gross)
    settlement = new_entity({
        "financed_purchase_id": purchase["id"],
        "provider_id": provider["id"],
        "gross_cents": gross,
        "discount_rate_applied": rate,
        "discount_fee_cents": fee,
        "net_cents": net,
        "status": "PENDING",
        "_paid_month": None,  # (year, month) of clock when paid; for monthly-volume reset
        "_was_paid": False,   # ever transitioned to PAID (settled_net contribution)
    })
    db.settlements[settlement["id"]] = settlement
    return settlement


# ---------------------------------------------------------------------
# Derived provider ledger fields (PRD §3.5 / SCAFFOLD Provider computed fields)
# ---------------------------------------------------------------------
def recompute_provider_volumes(provider):
    """monthly_settled_volume_cents = sum(gross of PAID settlements paid in the
    current clock month). settled_net_cents = sum(net WHERE PAID) - sum(net of
    settlements that were PAID then CLAWED_BACK). Recomputed on read/use so the
    month-boundary reset is automatic when the clock crosses a month."""
    cur_month = _clock_month()
    monthly = 0
    net = 0
    for s in db.settlements.values():
        if s["provider_id"] != provider["id"]:
            continue
        if s["status"] == "PAID":
            net += s["net_cents"]
            if s.get("_paid_month") == cur_month:
                monthly += s["gross_cents"]
        elif s["status"] == "CLAWED_BACK" and s.get("_was_paid"):
            # was PAID before clawback: paid net was added then removed -> net 0 contribution.
            # monthly volume for a current-month paid-then-clawed settlement nets to 0 too.
            pass
    provider["monthly_settled_volume_cents"] = monthly
    provider["settled_net_cents"] = net


# ---------------------------------------------------------------------
# Refund / void cascade (PRD §3.9)
# ---------------------------------------------------------------------
def apply_void(purchase, account):
    purchase["settlement_status"] = "VOID"
    unpaid_principal = purchase["principal_cents"] - purchase["principal_paid_cents"]
    account["available_credit_cents"] += purchase["principal_cents"]
    account["current_balance_cents"] -= unpaid_principal
    touch(purchase)


def apply_refund(purchase, account):
    purchase["settlement_status"] = "REFUNDED"
    # Settlement clawback cascade.
    settlement = _settlement_for_purchase(purchase)
    if settlement is not None:
        provider = db.providers.get(settlement["provider_id"])
        was_paid = settlement["status"] == "PAID"
        settlement["status"] = "CLAWED_BACK"
        touch(settlement)
        if was_paid and provider is not None:
            # Provider ledger figures are derived; recompute reflects the clawback.
            recompute_provider_volumes(provider)
            touch(provider)
    # Restore credit + decrement balance by then-current outstanding (incl. posted interest).
    account["available_credit_cents"] += purchase["principal_cents"]
    outstanding = (purchase["principal_cents"] - purchase["principal_paid_cents"]
                   + purchase["deferred_interest_posted_cents"])
    account["current_balance_cents"] -= outstanding
    touch(purchase)
    # Cure delinquency if the decrement satisfies the open statement minimum.
    maybe_cure_on_balance_decrement(account)


def _settlement_for_purchase(purchase):
    for settlement in db.settlements.values():
        if settlement["financed_purchase_id"] == purchase["id"]:
            return settlement
    return None


def _clock_month():
    now = db.clock.now()
    return (now.year, now.month)
