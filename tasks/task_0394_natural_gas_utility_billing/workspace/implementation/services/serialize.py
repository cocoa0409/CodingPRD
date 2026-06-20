"""Public serialization of entities, computing `source: computed` fields on read.

Each `view_*` returns the exact field set the PRD/scaffold defines for that
entity, with computed fields refreshed against current store state and clock.
"""

from db import store
from services.common import public, parse_dt
from services import calc


def view_rate_schedule(rec):
    return public(rec)


def view_pga_schedule(rec):
    return public(rec)


def view_account(rec):
    out = public(rec)
    aid = rec["id"]
    out["balance_cents"] = calc.account_balance_cents(aid)
    out["past_due_cents"] = calc.account_past_due_cents(aid)
    out["deposit_held_cents"] = calc.account_deposit_held_cents(aid)
    out["shutoff_eligible"] = calc.account_shutoff_eligible(aid)
    return out


def meter_last_index(meter):
    """Most recent non-VOID read reading_index, else install_index (PRD §3.2)."""
    best = None
    best_key = None
    for r in store.meter_reads.values():
        if r["premise_meter_id"] != meter["id"]:
            continue
        if r["status"] == "VOID":
            continue
        rd = parse_dt(r["read_date"])
        key = (rd, r["_seq"])
        if best_key is None or key > best_key:
            best_key = key
            best = r
    if best is None:
        return meter["install_index"]
    return best["reading_index"]


def view_meter(rec):
    out = public(rec)
    out["last_index"] = meter_last_index(rec)
    return out


def view_meter_read(rec):
    return public(rec)


def view_bill(rec):
    return public(rec)


def view_budget_plan(rec):
    return public(rec)


def view_payment(rec):
    return public(rec)


def view_service_order(rec):
    return public(rec)


def view_ticket(rec):
    return public(rec)


def view_deposit(rec):
    return public(rec)


def view_low_income_credit(rec):
    return public(rec)


def view_clock(rec):
    return dict(rec)
