"""Entity lifecycle helpers and derived-field recomputation.

Every mutation refreshes updated_at and increments version by exactly one
(PRD 2.4), including cascade-driven mutations. Within a single request each
resource is bumped at most once (a multi-step cascade on one resource is one
logical mutation).
"""
from flask import g

from db import db, next_seq
from errors import raise_error, ERR_NOT_FOUND
from util import new_id, now_ts, round_half_up_int


def new_entity(collection: str, fields: dict) -> dict:
    ts = now_ts()
    ent = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    ent.update(fields)
    db[collection][ent["id"]] = ent
    return ent


def touch(ent):
    if ent is None:
        return
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    key = id(ent)
    if key in seen:
        return
    seen.add(key)
    ent["version"] = int(ent.get("version", 1)) + 1
    ent["updated_at"] = now_ts()


def get_or_404(collection: str, entity_id):
    ent = db[collection].get(entity_id) if isinstance(entity_id, str) else None
    if ent is None:
        raise_error(ERR_NOT_FOUND, f"{collection} resource not found: {entity_id}")
    return ent


def find_all(collection: str, **filters):
    out = []
    for ent in db[collection].values():
        ok = True
        for k, v in filters.items():
            if v is not None and ent.get(k) != v:
                ok = False
                break
        if ok:
            out.append(ent)
    out.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return out


# ---------------------------------------------------------------------------
# Lookups across aggregates
# ---------------------------------------------------------------------------

def lines_of_order(order_id, include_cancelled=False):
    lines = [l for l in db["order_lines"].values() if l["order_id"] == order_id]
    if not include_cancelled:
        lines = [l for l in lines if l["status"] != "CANCELLED"]
    lines.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return lines


def events_of_order(order_id, include_cancelled=False):
    evts = [e for e in db["install_events"].values() if e["order_id"] == order_id]
    if not include_cancelled:
        evts = [e for e in evts if e["status"] != "CANCELLED"]
    return evts


def punches_of_order(order_id):
    return [p for p in db["punch_items"].values() if p["order_id"] == order_id]


def claims_of_punch(punch_item_id):
    return [c for c in db["manufacturer_claims"].values() if c["punch_item_id"] == punch_item_id]


def dealership_of_order(order):
    customer = db["customers"].get(order["customer_id"])
    if customer is None:
        return None
    return db["dealerships"].get(customer["dealership_id"])


def dealership_of_line(line):
    order = db["project_orders"].get(line["order_id"])
    if order is None:
        return None
    return dealership_of_order(order)


# ---------------------------------------------------------------------------
# Derived field recomputation
# ---------------------------------------------------------------------------

def recompute_order_totals(order):
    """order_total_rollup: pinned evaluation order (scaffold Table 3)."""
    lines = lines_of_order(order["id"])
    total_list = sum(l["unit_list_price_cents"] * l["quantity"] for l in lines)
    total_net = sum(l["line_total_cents"] for l in lines)
    fee_pct = 8 if total_list >= 5_000_000 else 12
    install_fee = round_half_up_int(total_net * fee_pct, 100)
    order["total_list_cents"] = total_list
    order["total_net_cents"] = total_net
    order["install_fee_cents"] = install_fee
    order["grand_total_cents"] = total_net + install_fee - order.get("credit_applied_cents", 0)
    touch(order)


def credit_cap_cents(order) -> int:
    dealership = dealership_of_order(order)
    cap_pct = dealership["credit_cap_pct"] if dealership else 0
    base = order["total_net_cents"] + order["install_fee_cents"]
    return (base * cap_pct) // 100  # floor (PRD 2.5)


def recompute_promised_date(order):
    """promised_date = max over non-CANCELLED lines of (confirmed else provisional
    promise date); null when no line carries a date."""
    old = order.get("promised_date")
    best = None
    for line in lines_of_order(order["id"]):
        d = line.get("confirmed_promise_date") or line.get("provisional_promise_date")
        if d and (best is None or d > best):
            best = d
    order["promised_date"] = best
    touch(order)
    return old, best


def recompute_install_posture(order):
    """order_install_posture (scaffold Table 3)."""
    events = events_of_order(order["id"])
    punches = punches_of_order(order["id"])
    if any(p["severity"] == "CRITICAL" and p["status"] in ("OPEN", "READY_FOR_VERIFY") for p in punches):
        posture = "BLOCKED"
    elif events and all(e["status"] == "COMPLETED" for e in events):
        posture = "COMPLETE"
    elif any(e["status"] == "IN_PROGRESS" for e in events):
        posture = "IN_PROGRESS"
    elif any(e["status"] == "CONFIRMED" for e in events):
        posture = "SCHEDULED"
    else:
        posture = "NOT_SCHEDULED"
    order["install_posture"] = posture
    if posture == "COMPLETE" and order["status"] == "DELIVERED":
        order["status"] = "INSTALLED"
    touch(order)


def recompute_line_received(line):
    """line.received_units = sum over non-CANCELLED reservations; full receipt
    bubbles ACKNOWLEDGED (or OPEN replacement) lines to RECEIVED, and an
    ACKNOWLEDGED order whose lines are all RECEIVED advances to DELIVERED."""
    reservations = [
        r for r in db["staging_reservations"].values()
        if r["order_line_id"] == line["id"] and r["status"] != "CANCELLED"
    ]
    line["received_units"] = sum(r["received_units"] for r in reservations)
    if line["received_units"] >= line["quantity"] and line["status"] in ("ACKNOWLEDGED", "OPEN"):
        line["status"] = "RECEIVED"
    touch(line)
    order = db["project_orders"].get(line["order_id"])
    if order is not None and order["status"] == "ACKNOWLEDGED":
        siblings = lines_of_order(order["id"])
        if siblings and all(l["status"] == "RECEIVED" for l in siblings):
            order["status"] = "DELIVERED"
            touch(order)


def recompute_customer_balance(customer):
    """customer_credit_ledger (scaffold Table 3): conserved derived balance."""
    cid = customer["id"]
    lots = [l for l in db["liquidation_lots"].values() if l["customer_id"] == cid]
    bal = sum(
        (l.get("final_credit_cents") or 0)
        for l in lots
        if l["status"] in ("CREDIT_ISSUED", "REDEEMED")
    )
    for claim in db["manufacturer_claims"].values():
        if claim["status"] == "SETTLED" and claim["remedy_requested"] == "CREDIT":
            punch = db["punch_items"].get(claim["punch_item_id"])
            if punch is None:
                continue
            order = db["project_orders"].get(punch["order_id"])
            if order is not None and order["customer_id"] == cid:
                bal += claim.get("settled_amount_cents") or 0
    for order in db["project_orders"].values():
        if order["customer_id"] == cid and order["status"] != "CANCELLED":
            bal -= order.get("credit_applied_cents") or 0
    # Manual redemption forfeits the unredeemed remainder (auto-redeemed lots
    # have remainder 0, so this term is exact for both paths).
    for lot in lots:
        if lot["status"] == "REDEEMED":
            bal -= (lot.get("final_credit_cents") or 0) - (lot.get("redeemed_cents") or 0)
    # Restocking fees debited from the ledger on ACKNOWLEDGED-order cancels.
    bal -= customer.get("_fee_debits", 0)
    customer["liquidation_credit_balance_cents"] = bal
    touch(customer)


def apply_lot_consumption_fifo(customer_id, amount_cents):
    """Consume lot credit FIFO by created_at ascending (PRD 3.8). Returns the
    list of (lot_id, cents) consumed for later rollback on order cancel."""
    lots = [
        l for l in db["liquidation_lots"].values()
        if l["customer_id"] == customer_id
        and l["status"] == "CREDIT_ISSUED"
        and (l.get("final_credit_cents") or 0) - (l.get("redeemed_cents") or 0) > 0
    ]
    lots.sort(key=lambda e: (e["created_at"], e["_seq"]))
    consumption = []
    remaining = amount_cents
    for lot in lots:
        if remaining <= 0:
            break
        available = lot["final_credit_cents"] - lot["redeemed_cents"]
        take = min(available, remaining)
        lot["redeemed_cents"] += take
        remaining -= take
        consumption.append((lot["id"], take))
        if lot["redeemed_cents"] >= lot["final_credit_cents"]:
            lot["status"] = "REDEEMED"  # automatic redemption
            lot["_manual_redeem"] = False
        touch(lot)
    return consumption


def rollback_lot_consumption(consumption):
    """Reverse a prior apply_credit FIFO consumption (order cancel restores the
    ledger; the lot-level FIFO pool is restored with it)."""
    for lot_id, cents in consumption:
        lot = db["liquidation_lots"].get(lot_id)
        if lot is None:
            continue
        if lot["status"] == "REDEEMED" and lot.get("_manual_redeem"):
            # Remainder already forfeited; do not resurrect forfeited credit.
            continue
        lot["redeemed_cents"] = max(0, lot.get("redeemed_cents", 0) - cents)
        if lot["status"] == "REDEEMED" and lot["redeemed_cents"] < (lot.get("final_credit_cents") or 0):
            lot["status"] = "CREDIT_ISSUED"
        touch(lot)


def plan_budget_recompute(plan):
    typicals = [t for t in db["typicals"].values() if t["space_plan_id"] == plan["id"]]
    plan["budget_cents"] = sum(t["extended_budget_cents"] for t in typicals)
    touch(plan)
