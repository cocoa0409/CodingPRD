"""Derived counters, the two append-only journals and the liability projection."""
import clock
import db
from db import touch

OPEN_COUNT_STATES = ("OPEN", "COUNTING", "JAM_HOLD")
LIABILITY_EXEMPT_TYPES = ("HANDLING_FEE", "MATERIAL_REVENUE")
BATCHED_STATES = ("ACCUMULATING", "SORTED", "BALED", "SOLD")


# --- credit journal -------------------------------------------------------

def account_entries(account_id):
    return db.ordered(db.credit_entries, lambda e: e["account_id"] == account_id)


def recompute_account_balance(account):
    total = sum(e["amount_cents"] for e in account_entries(account["id"]))
    account["credit_balance_cents"] = total
    touch(account)
    return total


def append_credit_entry(account, entry_type, amount_cents, source_kind,
                        source_ref_id, memo=None):
    entry = db.new_record({
        "account_id": account["id"],
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "balance_after_cents": 0,
        "source_kind": source_kind,
        "source_ref_id": source_ref_id,
        "memo": memo,
    }, versioned=False)
    db.credit_entries[entry["id"]] = entry
    balance = recompute_account_balance(account)
    entry["balance_after_cents"] = balance
    return entry


# --- deposit ledger ------------------------------------------------------

def period_entries(period_id):
    return db.ordered(db.ledger_entries, lambda e: e["period_id"] == period_id)


def replay_period(period):
    """Rebuild the liability projection and the quarter's roll-ups from the ledger."""
    running = 0
    deposits = 0
    containers_initiated = 0
    redemptions = 0
    containers_redeemed = 0
    material = 0
    for entry in period_entries(period["id"]):
        etype = entry["entry_type"]
        if etype not in LIABILITY_EXEMPT_TYPES:
            running += entry["amount_cents"]
        entry["liability_after_cents"] = running
        if etype == "DEPOSIT_INITIATED":
            deposits += entry["amount_cents"]
            containers_initiated += entry["container_count"]
        elif etype in ("REDEMPTION_PAID", "BAG_DROP_CREDIT"):
            redemptions += entry["amount_cents"]
            containers_redeemed += entry["container_count"]
        elif etype == "REDEMPTION_REVERSED":
            redemptions += entry["amount_cents"]
            containers_redeemed -= entry["container_count"]
        elif etype == "MATERIAL_REVENUE":
            material += entry["amount_cents"]
    period["deposits_initiated_cents"] = deposits
    period["containers_initiated_count"] = containers_initiated
    period["redemptions_paid_cents"] = -redemptions
    period["containers_redeemed_count"] = containers_redeemed
    period["material_revenue_cents"] = material
    period["outstanding_liability_cents"] = running
    touch(period)
    return running


def append_ledger_entry(period, entry_type, amount_cents, container_count,
                        source_kind, source_ref_id):
    entry = db.new_record({
        "period_id": period["id"],
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "container_count": int(container_count),
        "liability_after_cents": 0,
        "source_kind": source_kind,
        "source_ref_id": source_ref_id,
    }, versioned=False)
    db.ledger_entries[entry["id"]] = entry
    return entry


def period_contains(period, date_str):
    return date_str is not None and period["start_date"] <= date_str <= period["end_date"]


def periods_containing(date_str):
    return [p for p in db.ordered(db.periods) if period_contains(p, date_str)]


def periods_overlapping(start_date, end_date):
    return [p for p in db.ordered(db.periods)
            if p["start_date"] <= end_date and start_date <= p["end_date"]]


# --- redemption centre counters -----------------------------------------

def center_machines(center_id):
    return db.ordered(db.machines, lambda m: m["center_id"] == center_id)


def center_visits(center_id):
    return db.ordered(db.visits, lambda v: v.get("center_id") == center_id)


def visit_lots(visit_id):
    return db.ordered(db.lots, lambda l: l["visit_id"] == visit_id)


def recompute_center_machine_counts(center):
    machines = center_machines(center["id"])
    center["machine_count"] = sum(1 for m in machines if m["status"] != "RETIRED")
    center["out_of_service_machine_count"] = sum(
        1 for m in machines if m["status"] == "OUT_OF_SERVICE")
    touch(center)


def recompute_center_containers(center):
    accepted = 0
    for visit in center_visits(center["id"]):
        if visit["count_status"] == "COUNTED":
            accepted += sum(l["accepted_quantity"] for l in visit_lots(visit["id"]))
    batched = sum(b["container_count"] for b in db.batches.values()
                  if b["center_id"] == center["id"] and b["status"] in BATCHED_STATES)
    center["accepted_container_count"] = accepted
    center["batched_container_count"] = batched
    center["unbatched_container_count"] = accepted - batched
    touch(center)


def recompute_center_withheld(center):
    center["withheld_visit_count"] = sum(
        1 for v in center_visits(center["id"]) if v["payout_status"] == "WITHHELD")
    touch(center)


def center_has_open_visits(center_id):
    return any(v["count_status"] in OPEN_COUNT_STATES for v in center_visits(center_id))


def retailer_has_open_visits(retailer_id):
    return any(v["count_status"] in OPEN_COUNT_STATES for v in db.visits.values()
               if v.get("retailer_id") == retailer_id)


def maybe_suspend_for_fleet_down(center):
    """Cascade OPERATIONAL -> SUSPENDED when the whole fleet is out of service."""
    if center is None:
        return
    if (center["status"] == "OPERATIONAL"
            and center["machine_count"] >= 1
            and center["out_of_service_machine_count"] >= center["machine_count"]):
        center["status"] = "SUSPENDED"
        center["suspension_reason"] = "MACHINE_FLEET_DOWN"
        touch(center)


def clear_retailer_exemption(retailer):
    retailer["obligation_status"] = "OBLIGATED"
    retailer["nearest_center_id"] = None
    retailer["nearest_center_distance_miles"] = None
    retailer["exemption_granted_at"] = None
    touch(retailer)


def close_center_cascades(center):
    for machine in center_machines(center["id"]):
        if machine["status"] != "RETIRED":
            machine["status"] = "RETIRED"
            touch(machine)
    recompute_center_machine_counts(center)
    for retailer in db.ordered(db.retailers):
        if (retailer.get("nearest_center_id") == center["id"]
                and retailer["obligation_status"] == "EXEMPT"):
            clear_retailer_exemption(retailer)


# --- account standing ----------------------------------------------------

def record_strike(account, reason):
    """Adds one fraud strike. Returns True when this strike flags the account."""
    account["fraud_strikes"] = int(account["fraud_strikes"]) + 1
    account["last_strike_reason"] = reason
    touch(account)
    if account["fraud_strikes"] == 2 and account["status"] == "ACTIVE":
        account["status"] = "FLAGGED"
        touch(account)
        return True
    return False


def account_bag_drops(account_id):
    return db.ordered(db.bag_drops, lambda b: b["account_id"] == account_id)


def stamp_now(rec, field):
    rec[field] = clock.now_iso()
