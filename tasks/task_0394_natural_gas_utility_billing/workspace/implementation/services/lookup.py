"""Existence lookups with left-to-right nested addressing (PRD §2.5).

Each helper raises ERR_NOT_FOUND when the id does not resolve, or when a child
exists but does not belong to the named parent (treated as not found in
context).
"""

from db import store
from errors import ERR_NOT_FOUND, err


def get_account(account_id):
    acc = store.accounts.get(account_id)
    if acc is None:
        raise err(ERR_NOT_FOUND, "Account not found")
    return acc


def get_rate_schedule(rs_id):
    rs = store.rate_schedules.get(rs_id)
    if rs is None:
        raise err(ERR_NOT_FOUND, "Rate schedule not found")
    return rs


def get_pga_schedule(pga_id):
    pga = store.pga_schedules.get(pga_id)
    if pga is None:
        raise err(ERR_NOT_FOUND, "PGA schedule not found")
    return pga


def get_meter(meter_id):
    m = store.meters.get(meter_id)
    if m is None:
        raise err(ERR_NOT_FOUND, "Meter not found")
    return m


def get_meter_under_account(account_id, meter_id):
    m = get_meter(meter_id)
    if m["account_id"] != account_id:
        raise err(ERR_NOT_FOUND, "Meter not found for account")
    return m


def get_read(read_id):
    r = store.meter_reads.get(read_id)
    if r is None:
        raise err(ERR_NOT_FOUND, "Meter read not found")
    return r


def get_read_under_meter(meter_id, read_id):
    r = get_read(read_id)
    if r["premise_meter_id"] != meter_id:
        raise err(ERR_NOT_FOUND, "Meter read not found for meter")
    return r


def get_bill(bill_id):
    b = store.bills.get(bill_id)
    if b is None:
        raise err(ERR_NOT_FOUND, "Bill not found")
    return b


def get_bill_under_account(account_id, bill_id):
    b = get_bill(bill_id)
    if b["account_id"] != account_id:
        raise err(ERR_NOT_FOUND, "Bill not found for account")
    return b


def get_budget_plan(plan_id):
    p = store.budget_plans.get(plan_id)
    if p is None:
        raise err(ERR_NOT_FOUND, "Budget plan not found")
    return p


def get_budget_plan_under_account(account_id, plan_id):
    p = get_budget_plan(plan_id)
    if p["account_id"] != account_id:
        raise err(ERR_NOT_FOUND, "Budget plan not found for account")
    return p


def get_payment(payment_id):
    p = store.payments.get(payment_id)
    if p is None:
        raise err(ERR_NOT_FOUND, "Payment not found")
    return p


def get_deposit(deposit_id):
    d = store.deposits.get(deposit_id)
    if d is None:
        raise err(ERR_NOT_FOUND, "Deposit not found")
    return d


def get_deposit_under_account(account_id, deposit_id):
    d = get_deposit(deposit_id)
    if d["account_id"] != account_id:
        raise err(ERR_NOT_FOUND, "Deposit not found for account")
    return d


def get_credit(credit_id):
    c = store.low_income_credits.get(credit_id)
    if c is None:
        raise err(ERR_NOT_FOUND, "Low-income credit not found")
    return c


def get_credit_under_account(account_id, credit_id):
    c = get_credit(credit_id)
    if c["account_id"] != account_id:
        raise err(ERR_NOT_FOUND, "Low-income credit not found for account")
    return c


def get_service_order(order_id):
    o = store.service_orders.get(order_id)
    if o is None:
        raise err(ERR_NOT_FOUND, "Service order not found")
    return o


def get_ticket(ticket_id):
    t = store.tickets.get(ticket_id)
    if t is None:
        raise err(ERR_NOT_FOUND, "Ticket not found")
    return t


def account_meters(account_id):
    return [m for m in store.meters.values() if m["account_id"] == account_id]


def account_has_active_emergency(account_id):
    """True when any OPEN/DISPATCHED/MADE_SAFE ticket exists on the account's
    meters (PRD §3.9 emergency safety hold)."""
    meter_ids = {m["id"] for m in account_meters(account_id)}
    for t in store.tickets.values():
        if t["premise_meter_id"] in meter_ids and t["status"] in ("OPEN", "DISPATCHED", "MADE_SAFE"):
            return True
    return False
