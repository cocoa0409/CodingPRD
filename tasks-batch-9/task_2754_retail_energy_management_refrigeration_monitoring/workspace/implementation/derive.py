"""Reachability helpers and the store's derived ledger and counter fields."""

from decimal import Decimal

from db import db, rows
from util import D, month_bounds, q, rhu

DEFAULT_REALIZATION_RATE = Decimal("0.85")


def _by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def store_accounts(store_id):
    return _by_created([a for a in db.accounts.values() if a["store_id"] == store_id])


def store_cases(store_id):
    return _by_created([c for c in db.cases.values() if c["store_id"] == store_id])


def store_overrides(store_id):
    return _by_created([o for o in db.overrides.values() if o["store_id"] == store_id])


def store_faults(store_id):
    return _by_created([f for f in db.faults.values() if f["store_id"] == store_id])


def store_retrofits(store_id):
    return _by_created([p for p in db.retrofits.values() if p["store_id"] == store_id])


def account_bills(account_id):
    return _by_created([b for b in db.bills.values()
                        if b["utility_account_id"] == account_id])


def account_intervals(account_id):
    return _by_created([i for i in db.intervals.values()
                        if i["utility_account_id"] == account_id])


def account_events(account_id):
    return _by_created([e for e in db.dr_events.values()
                        if e["utility_account_id"] == account_id])


def case_excursions(case_id):
    return _by_created([x for x in db.excursions.values() if x["case_id"] == case_id])


def fault_work_orders(fault_id):
    return _by_created([w for w in db.work_orders.values() if w["fault_id"] == fault_id])


def store_events(store_id):
    out = []
    for account in store_accounts(store_id):
        out.extend(account_events(account["id"]))
    return _by_created(out)


def store_excursions(store_id):
    out = []
    for case in store_cases(store_id):
        out.extend(case_excursions(case["id"]))
    return _by_created(out)


def store_work_orders(store_id):
    out = []
    for fault in store_faults(store_id):
        out.extend(fault_work_orders(fault["id"]))
    return _by_created(out)


def store_bills(store_id):
    out = []
    for account in store_accounts(store_id):
        out.extend(account_bills(account["id"]))
    return _by_created(out)


def case_of_excursion(excursion):
    return db.cases.get(excursion["case_id"])


def store_of_case(case):
    return db.stores.get(case["store_id"])


def store_of_account(account):
    return db.stores.get(account["store_id"])


def store_of_excursion(excursion):
    case = case_of_excursion(excursion)
    return store_of_case(case) if case else None


def account_of_bill(bill):
    return db.accounts.get(bill["utility_account_id"])


def account_of_event(event):
    return db.accounts.get(event["utility_account_id"])


def fault_of_work_order(work_order):
    return db.faults.get(work_order["fault_id"])


def store_of_work_order(work_order):
    fault = fault_of_work_order(work_order)
    return db.stores.get(fault["store_id"]) if fault else None


# ------------------------------------------------------- derived quantities ---

def alarm_case_count(store_id):
    return len([c for c in store_cases(store_id) if c["monitoring_state"] == "ALARM"])


def urgent_work_order_count(store_id):
    return len([w for w in store_work_orders(store_id)
                if w["priority"] == "URGENT" and w["state"] in ("OPEN", "SCHEDULED")])


def override_kwh_used_month(store_id):
    start, end = month_bounds(db.clock)
    total = Decimal(0)
    for override in store_overrides(store_id):
        if override["state"] not in ("SCHEDULED", "ACTIVE", "EXPIRED"):
            continue
        if start <= override["start_iso"] < end:
            total += override["projected_kwh"]
    return q(total, 2)


def verified_savings_kwh_ytd(store_id):
    total = Decimal(0)
    for project in store_retrofits(store_id):
        if project["state"] == "VERIFIED" and project["measured_savings_kwh"] is not None:
            total += project["measured_savings_kwh"]
    return q(total, 2)


def portfolio_realization_rate(store_id):
    values = [p["realization_rate"] for p in store_retrofits(store_id)
              if p["state"] in ("VERIFIED", "SHORTFALL_REVIEW")
              and p["realization_rate"] is not None]
    if not values:
        return rhu(DEFAULT_REALIZATION_RATE, 4)
    total = Decimal(0)
    for value in values:
        total += value
    return rhu(total / Decimal(len(values)), 4)


def dr_optout_count(account_id):
    return len([e for e in account_events(account_id)
                if e["event_state"] == "OPTED_OUT"
                and e["opt_out_reason"] == "FOOD_SAFETY_POSTURE"])


def dr_incentive_accrued_usd(account_id):
    total = Decimal(0)
    for event in account_events(account_id):
        if event["settlement_state"] == "SETTLED" and event["incentive_usd"] is not None:
            total += event["incentive_usd"]
    return q(total, 2)


def refrigeration_fault_density(store_id):
    return len([f for f in store_faults(store_id)
                if f["equipment_class"] == "REFRIGERATION"
                and f["state"] in ("DETECTED", "TRIAGED")])
