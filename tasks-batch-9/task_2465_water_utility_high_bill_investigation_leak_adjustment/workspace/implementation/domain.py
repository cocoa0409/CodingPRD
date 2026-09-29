"""Domain services: ledger, derived account state, bill computation and the
shared read/baseline derivations.
"""

from datetime import datetime, timezone

import calc
from core import (
    ADJ_ROLLING_WINDOW_MONTHS,
    HOLD_ACTIVE_STATUSES,
    as_date,
    as_dt,
    base_record,
    insert,
    maybe,
    minus_months,
    now_iso,
    register_new,
    rows,
    store,
    touch,
)

LIVE_READ_TYPES = ("ACTUAL", "CORRECTED")


# ---------------------------------------------------------------------------
# Simple relations
# ---------------------------------------------------------------------------
def account_of(rec_account_id):
    return maybe("service_accounts", rec_account_id)


def schedule_for_account(account):
    return maybe("rate_schedules", account["rate_schedule_id"])


def period_of_bill(bill):
    return maybe("billing_periods", bill["period_id"])


def schedule_of_bill(bill):
    account = maybe("service_accounts", bill["account_id"])
    return schedule_for_account(account) if account else None


def period_containing(day):
    """The billing period whose [start_date, end_date] window contains `day`."""
    for period in rows("billing_periods"):
        if as_date(period["start_date"]) <= day <= as_date(period["end_date"]):
            return period
    return None


def bills_of_account(account_id):
    return [b for b in rows("bills") if b["account_id"] == account_id]


def investigations_of_account(account_id):
    return [i for i in rows("investigations") if i["account_id"] == account_id]


def arrangements_of_account(account_id):
    return [a for a in rows("payment_arrangements") if a["account_id"] == account_id]


def ledger_of_account(account_id):
    return [e for e in rows("ledger_entries") if e["account_id"] == account_id]


def ledger_sort_key(entry):
    return (entry.get("effective_at") or "", entry.get("created_at") or "", entry["_seq"])


def reading_sort_key(reading):
    return (reading.get("read_date") or "", reading.get("created_at") or "", reading["_seq"])


# ---------------------------------------------------------------------------
# Meter readings
# ---------------------------------------------------------------------------
def all_reads(meter_id):
    return sorted(
        [r for r in rows("meter_readings") if r["meter_id"] == meter_id],
        key=reading_sort_key,
    )


def live_reads(meter_id, types=LIVE_READ_TYPES):
    return [
        r
        for r in all_reads(meter_id)
        if r.get("superseded_by_reading_id") is None
        and (types is None or r["read_type"] in types)
    ]


def latest_live_read(meter_id):
    live = live_reads(meter_id, types=None)
    return live[-1] if live else None


def nearest_live_read_before(meter_id, read_date):
    candidates = [
        r for r in live_reads(meter_id, types=None) if r["read_date"] < read_date
    ]
    return candidates[-1] if candidates else None


def register_baseline(meter):
    return int(meter["initial_register_value"])


def consumption_since_prior(meter, read_date, reading_value):
    prior = nearest_live_read_before(meter["id"], read_date)
    prior_value = int(prior["reading_value"]) if prior else register_baseline(meter)
    return int(reading_value) - prior_value


def opening_read_value(meter, period_start):
    """Greatest live ACTUAL/CORRECTED read at or before the period start."""
    candidates = [
        r for r in live_reads(meter["id"]) if as_date(r["read_date"]) <= period_start
    ]
    if candidates:
        return int(candidates[-1]["reading_value"]), True
    return register_baseline(meter), False


def closing_read_value(meter, period_start, period_end):
    candidates = [
        r
        for r in live_reads(meter["id"])
        if period_start <= as_date(r["read_date"]) <= period_end
    ]
    if candidates:
        return int(candidates[-1]["reading_value"])
    return None


def derive_consumption(meter, period):
    start = as_date(period["start_date"])
    end = as_date(period["end_date"])
    opening, _ = opening_read_value(meter, start)
    closing = closing_read_value(meter, start, end)
    if closing is None:
        return 0
    return max(0, closing - opening)


# ---------------------------------------------------------------------------
# Submeter sewer credit
# ---------------------------------------------------------------------------
def submeter_credit_gallons(bill, meter, period, schedule, estimated_flag):
    if estimated_flag:
        return 0
    start = as_date(period["start_date"])
    end = as_date(period["end_date"])
    start_instant = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)

    total = 0
    eligible = False
    for child in rows("meters"):
        if child.get("parent_meter_id") != meter["id"]:
            continue
        if child["meter_type"] != "IRRIGATION_SUBMETER":
            continue

        candidates = [
            r for r in live_reads(child["id"]) if as_date(r["read_date"]) <= start
        ]
        if candidates:
            opening = int(candidates[-1]["reading_value"])
        elif as_dt(child["created_at"]) < start_instant:
            opening = register_baseline(child)
        else:
            continue

        closing = closing_read_value(child, start, end)
        if closing is None:
            continue

        eligible = True
        total += max(0, closing - opening)

    if not eligible:
        return 0
    return min(total, int(schedule["submeter_sewer_credit_cap_gallons"]))


# ---------------------------------------------------------------------------
# Bill computation
# ---------------------------------------------------------------------------
def compute_bill_charges(bill):
    """(Re)compute the consumption and charge fields of a bill in place."""
    account = maybe("service_accounts", bill["account_id"])
    period = period_of_bill(bill)
    meter = maybe("meters", bill["meter_id"])
    schedule = schedule_for_account(account)

    bill["consumption_gallons"] = derive_consumption(meter, period)
    bill["water_charge_cents"] = calc.tiered_water_charge(
        bill["consumption_gallons"], schedule, period["season"]
    )
    bill["submeter_credit_gallons"] = submeter_credit_gallons(
        bill, meter, period, schedule, bool(bill["estimated_flag"])
    )
    billable, sewer = calc.sewer_charge(
        bill["consumption_gallons"], bill["submeter_credit_gallons"], schedule
    )
    bill["sewer_billable_gallons"] = billable
    bill["sewer_charge_cents"] = sewer
    bill["total_charge_cents"] = bill["water_charge_cents"] + bill["sewer_charge_cents"]
    recompute_adjusted_total(bill)


def baseline_pool(bill):
    period = period_of_bill(bill)
    target_start = as_date(period["start_date"])
    season = period["season"]
    pool = []
    for other in rows("bills"):
        if other["id"] == bill["id"]:
            continue
        if other["account_id"] != bill["account_id"]:
            continue
        if other["meter_id"] != bill["meter_id"]:
            continue
        other_period = period_of_bill(other)
        if other_period is None or other_period["season"] != season:
            continue
        if as_date(other_period["end_date"]) >= target_start:
            continue
        if other["billing_status"] not in ("ISSUED", "ADJUSTED", "UPHELD_AS_BILLED"):
            continue
        if other["anomaly_flag"]:
            continue
        if other["estimated_flag"]:
            continue
        pool.append(other)
    pool.sort(
        key=lambda b: (
            as_date(period_of_bill(b)["end_date"]).isoformat(),
            b["created_at"],
            b["_seq"],
        ),
        reverse=True,
    )
    return pool


def compute_bill_baseline(bill):
    pool = baseline_pool(bill)
    baseline, count = calc.seasonal_baseline([b["consumption_gallons"] for b in pool])
    bill["seasonal_baseline_gallons"] = baseline
    bill["baseline_sample_count"] = count
    ratio, flag = calc.anomaly_screen(bill["consumption_gallons"], baseline)
    bill["anomaly_ratio"] = ratio
    bill["anomaly_flag"] = flag


def trigger_rebill_pending(meter, read_day):
    """A CORRECTED read (manual or FAST-cascade driven) recomputes the bill of the
    containing period and moves it to REBILL_PENDING."""
    period = period_containing(read_day)
    if period is None or period["status"] == "LOCKED":
        return None
    for bill in sorted(rows("bills"), key=lambda b: (b["created_at"], b["_seq"])):
        if bill["meter_id"] != meter["id"] or bill["period_id"] != period["id"]:
            continue
        if bill["billing_status"] not in ("ISSUED", "UNDER_INVESTIGATION", "ADJUSTED"):
            continue
        compute_bill_charges(bill)
        bill["billing_status"] = "REBILL_PENDING"
        touch(bill)
        return bill
    return None


def recompute_adjusted_total(bill):
    posted = [
        a
        for a in rows("leak_adjustments")
        if a["bill_id"] == bill["id"] and a["status"] == "POSTED"
    ]
    credit = sum(int(a["net_credit_cents"] or 0) for a in posted)
    bill["adjusted_total_cents"] = int(bill["total_charge_cents"] or 0) - credit


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
def add_ledger_entry(account, entry_type, source_kind, amount_cents, bill_id=None,
                     source_id=None, memo=None, effective_at=None):
    entry = {
        "id": base_record()["id"],
        "created_at": now_iso(),
        "_seq": store.next_seq(),
        "account_id": account["id"],
        "bill_id": bill_id,
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "source_kind": source_kind,
        "source_id": source_id,
        "memo": memo,
        "effective_at": effective_at or now_iso(),
    }
    # AccountLedgerEntry carries only id and created_at -- no updated_at/version.
    ordered = {
        "id": entry["id"],
        "created_at": entry["created_at"],
        "account_id": entry["account_id"],
        "bill_id": entry["bill_id"],
        "entry_type": entry["entry_type"],
        "amount_cents": entry["amount_cents"],
        "source_kind": entry["source_kind"],
        "source_id": entry["source_id"],
        "memo": entry["memo"],
        "effective_at": entry["effective_at"],
        "_seq": entry["_seq"],
    }
    insert("ledger_entries", ordered)
    register_new(ordered)
    return ordered


def bill_charge_total(bill_id):
    total = 0
    for entry in rows("ledger_entries"):
        if entry["bill_id"] == bill_id and entry["source_kind"] in (
            "BILL_CHARGE",
            "REBILL_CHARGE",
        ):
            total += int(entry["amount_cents"])
    return total


# ---------------------------------------------------------------------------
# Derived account state
# ---------------------------------------------------------------------------
def account_balance(account_id):
    return sum(int(e["amount_cents"]) for e in ledger_of_account(account_id))


def refresh_account(account):
    """Recompute balance -> hold counters -> credit_status -> service_status."""
    before = (
        account["balance_cents"],
        account["credit_status"],
        account["service_status"],
        account["open_investigation_hold_count"],
        account["open_rebill_count"],
        account["shutoff_scheduled_for"],
    )

    account["balance_cents"] = account_balance(account["id"])

    old_holds = int(account["open_investigation_hold_count"] or 0) + int(
        account["open_rebill_count"] or 0
    )
    hold_count = 0
    for inv in investigations_of_account(account["id"]):
        if inv["status"] in HOLD_ACTIVE_STATUSES:
            hold_count += 1
    rebill_count = 0
    for bill in bills_of_account(account["id"]):
        if bill["billing_status"] == "REBILL_PENDING":
            rebill_count += 1
    account["open_investigation_hold_count"] = hold_count
    account["open_rebill_count"] = rebill_count
    new_holds = hold_count + rebill_count

    statuses = set(a["status"] for a in arrangements_of_account(account["id"]))
    account["credit_status"] = calc.credit_status(account["balance_cents"], statuses)

    service = account["service_status"]
    if account["credit_status"] in ("CURRENT", "IN_ARRANGEMENT") and service in (
        "SHUTOFF_SCHEDULED",
        "SHUTOFF_HELD",
        "SHUTOFF_EXECUTED",
    ):
        account["service_status"] = "ACTIVE"
        account["shutoff_scheduled_for"] = None
    elif service == "SHUTOFF_SCHEDULED" and old_holds == 0 and new_holds > 0:
        account["service_status"] = "SHUTOFF_HELD"
    elif service == "SHUTOFF_HELD" and new_holds == 0:
        account["service_status"] = "SHUTOFF_SCHEDULED"

    after = (
        account["balance_cents"],
        account["credit_status"],
        account["service_status"],
        account["open_investigation_hold_count"],
        account["open_rebill_count"],
        account["shutoff_scheduled_for"],
    )
    if before != after:
        touch(account)
    return account


# ---------------------------------------------------------------------------
# Rolling 12-month adjustment window
# ---------------------------------------------------------------------------
def rolling_window_conflict(adjustment, account_id, reference_end_date):
    """True when another APPROVED/POSTED adjustment on the account already sits
    inside the trailing ADJ_ROLLING_WINDOW_MONTHS window, ignoring the row this
    adjustment supersedes."""
    window_start = minus_months(reference_end_date, ADJ_ROLLING_WINDOW_MONTHS)
    for other in rows("leak_adjustments"):
        if other["id"] == adjustment["id"]:
            continue
        if other["id"] == adjustment.get("supersedes_adjustment_id"):
            continue
        if other["status"] not in ("APPROVED", "POSTED"):
            continue
        bill = maybe("bills", other["bill_id"])
        if bill is None or bill["account_id"] != account_id:
            continue
        period = period_of_bill(bill)
        if period is None:
            continue
        if window_start <= as_date(period["end_date"]) <= reference_end_date:
            return True
    return False


# ---------------------------------------------------------------------------
# Investigation helpers
# ---------------------------------------------------------------------------
def verified_proofs(investigation_id):
    return sorted(
        [
            p
            for p in rows("repair_proofs")
            if p["investigation_id"] == investigation_id and p["status"] == "VERIFIED"
        ],
        key=lambda p: (p["created_at"], p["version"], p["_seq"]),
    )


def open_investigations_for_bill(bill_id):
    return [
        i
        for i in rows("investigations")
        if i["bill_id"] == bill_id
        and i["status"] not in ("RESOLVED", "CLOSED_NO_ADJUSTMENT")
    ]


def sync_investigation_hold(investigation):
    investigation["shutoff_hold_active"] = investigation["status"] in HOLD_ACTIVE_STATUSES
