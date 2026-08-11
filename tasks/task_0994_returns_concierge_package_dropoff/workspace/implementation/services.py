"""Business logic: calculations, state-machine cascades, serializers.
Every rule here traces to PRD.md section 3 and the SCAFFOLD state/calc tables."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import store, touch, stamp, stamp_immutable, fmt_ms, fmt_s
from errors import ApiError

# ------------------------------------------------------------------ enums ---
CONDITIONS = ("NEW", "LIGHT_USE", "DAMAGED", "DEFECTIVE", "WRONG_ITEM")
METHODS = ("LOCKER_QR", "COUNTER_DROP", "HOME_PICKUP")
TIERS = ("STARTER", "GROWTH", "SCALE", "CUSTOM")
LOCATION_KINDS = ("LOCKER", "COUNTER")
SIZE_CLASSES = ("S", "M", "L", "XL")
SIZE_CEILING_CM = {"S": 30, "M": 60, "L": 100, "XL": 150}
LABEL_TYPES = ("QR_CODE", "CARRIER_LABEL")
EXCEPTION_KINDS = ("DAMAGED_ITEM", "LOST_PARCEL", "WRONG_ITEM", "LABEL_FRAUD", "OVERSIZE_REJECT")
RESOLUTIONS = ("APPROVED", "REJECTED")
LEDGER_WRITE_KINDS = ("ADJUSTMENT", "CORRECTION")

ORDER_TERMINAL = ("REFUND_POSTED", "CANCELLED", "REJECTED_CLOSED")
EXCEPTION_OPEN_STATUSES = ("OPEN", "INVESTIGATING", "AWAITING_SHOPPER", "REOPENED")
CYCLE_TERMINAL = ("SETTLED",)

LABEL_TTL = timedelta(days=10)
SLOT_HOLD = timedelta(hours=48)
OVERSIZE_CM = 150
TOTE_MAX_UNITS = 40
TOTE_MAX_WEIGHT_GRAMS = 30000
OVERAGE_HARD_CAP_MULTIPLIER = 2
FRAUD_STRIKE_LIMIT = 2
APPEAL_LIMIT = 2
PICKUP_MAX_ATTEMPTS = 3

DEDUCTION_PCT = {
    "NEW": Decimal("0"),
    "LIGHT_USE": Decimal("0.10"),
    "DAMAGED": Decimal("0.50"),
    "DEFECTIVE": Decimal("0"),
    "WRONG_ITEM": Decimal("1.00"),
}


def _round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------- lookups ------
def get_or_404(collection, rid):
    rec = store[collection].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return rec


def order_items(order_id):
    return [i for i in store["items"].values() if i["return_order_id"] == order_id]


def order_labels(order_id):
    return [l for l in store["labels"].values() if l["return_order_id"] == order_id]


def active_label(order):
    """The order's currently ISSUED label, if any."""
    live = [l for l in order_labels(order["id"]) if l["status"] == "ISSUED"]
    if not live:
        return None
    live.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return live[-1]


def held_reservation(order_id):
    for r in store["reservations"].values():
        if r["return_order_id"] == order_id and r["status"] == "HELD":
            return r
    return None


def reservation_for_label(label_id):
    for r in store["reservations"].values():
        if r.get("label_id") == label_id and r["status"] == "HELD":
            return r
    return None


def merchant_plan(merchant):
    return store["plans"].get(merchant["plan_id"])


def open_exception(order_id):
    for c in store["exceptions"].values():
        if c["return_order_id"] == order_id and c["status"] in EXCEPTION_OPEN_STATUSES:
            return c
    return None


def latest_final(order_id):
    finals = [e for e in store["ledger"].values()
              if e["return_order_id"] == order_id and e["kind"] == "FINAL"]
    if not finals:
        return None
    finals.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return finals[-1]


# ----------------------------------------------------------- deductions -----
def line_deduction_cents(unit_price_cents, quantity, condition, plan, apply_waiver):
    """item_deduction_tiered: per-line round-half-up BEFORE summation."""
    line_gross = unit_price_cents * quantity
    pct = DEDUCTION_PCT[condition]
    if apply_waiver and plan is not None and plan["free_returns"] \
            and condition in ("NEW", "LIGHT_USE"):
        pct = Decimal("0")
    if condition == "DAMAGED":
        pct = Decimal("0.50")  # DAMAGED never waived
    return _round_half_up_cents(Decimal(line_gross) * pct)


def provisional_estimate(items, plan):
    """Pessimistic shopper-facing estimate: declared conditions, no waiver."""
    total = 0
    for it in items:
        line_gross = it["unit_price_cents"] * it["quantity"]
        ded = line_deduction_cents(it["unit_price_cents"], it["quantity"],
                                   it["declared_condition"], plan,
                                   apply_waiver=False)
        total += line_gross - ded
    return total


def final_settlement(order):
    """Final refund: sum over INSPECTED items of gross minus per-line deduction."""
    total = 0
    for it in order_items(order["id"]):
        if it["status"] != "INSPECTED":
            continue
        total += it["unit_price_cents"] * it["quantity"] - (it["deduction_cents"] or 0)
    return total


# ---------------------------------------------------------------- ledger ----
def append_ledger(order_id, kind, amount_cents, note, actor):
    entry = {
        "return_order_id": order_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "note": note,
        "actor_user_id": actor,
    }
    stamp_immutable(entry)
    store["ledger"][entry["id"]] = entry
    return entry


def refund_projection(order_id):
    """Replay ledger in created_at ASC (ties by created_at only; seq keeps
    insertion stability for equal instants)."""
    entries = [e for e in store["ledger"].values() if e["return_order_id"] == order_id]
    entries.sort(key=lambda e: (e["created_at"], e["_seq"]))
    estimated = 0
    final = None
    adj = 0
    corr = 0
    for e in entries:
        if e["kind"] == "ESTIMATE":
            estimated = e["amount_cents"]
        elif e["kind"] == "FINAL":
            final = e["amount_cents"]
        elif e["kind"] == "ADJUSTMENT":
            adj += e["amount_cents"]
        elif e["kind"] == "CORRECTION":
            corr += e["amount_cents"]
    payable = (final or 0) + adj + corr
    return {
        "estimated_cents": estimated,
        "final_cents": final,
        "payable_cents": payable,
        "entry_count": len(entries),
        "refund_status": "POSTED" if final is not None else "ESTIMATED",
    }


# ----------------------------------------------------- order state engine ---
def void_label(label):
    if label["status"] == "ISSUED":
        label["status"] = "VOIDED"
        touch(label)


def release_reservation(res):
    """HELD -> RELEASED: slot -> EMPTY, bound label -> VOIDED."""
    if res["status"] != "HELD":
        return
    res["status"] = "RELEASED"
    touch(res)
    slot = store["slots"].get(res["slot_id"])
    if slot is not None and slot["status"] == "RESERVED":
        slot["status"] = "EMPTY"
        touch(slot)
    label = store["labels"].get(res.get("label_id"))
    if label is not None:
        void_label(label)


def order_fall_back_to_initiated(order):
    """LABEL_ISSUED -> INITIATED cyclic revert (void / release / method change)."""
    if order["status"] == "LABEL_ISSUED":
        order["status"] = "INITIATED"


def resolve_order(order):
    """RESOLVED -> REFUND_POSTED bubble-up: FINAL entry, resolved_at stamp."""
    order["status"] = "RESOLVED"
    plan = merchant_plan(store["merchants"][order["merchant_id"]])
    final = final_settlement(order)
    order["refund_final_cents"] = final
    append_ledger(order["id"], "FINAL", final, "Final settlement", "system")
    order["resolved_at"] = db.now()
    order["status"] = "REFUND_POSTED"
    touch(order)


def reevaluate_order(order):
    """Order-level re-evaluation after an exception resolves (PRD 3.8)."""
    if order["status"] != "EXCEPTION_PENDING":
        return
    if open_exception(order["id"]) is not None:
        return
    pending = [i for i in order_items(order["id"]) if i["status"] == "PENDING"]
    if pending:
        order["status"] = "INSPECTING"
        touch(order)
    else:
        resolve_order(order)


def after_item_inspected(order, just_item):
    """Last-PENDING-item pivot (PRD 3.8)."""
    items = order_items(order["id"])
    if any(i["status"] == "PENDING" for i in items):
        return
    if open_exception(order["id"]) is not None:
        # Resolution deferred to exception resolve; order stays EXCEPTION_PENDING.
        return
    wrong = [i for i in items if i["condition"] == "WRONG_ITEM"]
    if wrong:
        link = just_item["id"] if just_item["condition"] == "WRONG_ITEM" else wrong[0]["id"]
        case = {
            "return_order_id": order["id"],
            "return_item_id": link,
            "kind": "WRONG_ITEM",
            "note": "Auto-created: item inspected as WRONG_ITEM",
            "status": "OPEN",
            "resolution": None,
            "opened_by_user_id": "system",
            "resolved_by_user_id": None,
            "appeal_count": 0,
        }
        stamp(case)
        store["exceptions"][case["id"]] = case
        order["status"] = "EXCEPTION_PENDING"
        touch(order)
        return
    resolve_order(order)


# ------------------------------------------------------------- billing ------
def cycle_fulfilled(cycle):
    out = []
    for o in store["orders"].values():
        if o["merchant_id"] != cycle["merchant_id"]:
            continue
        if o["status"] not in ("REFUND_POSTED", "REJECTED_CLOSED"):
            continue
        ra = o.get("resolved_at")
        if ra is not None and cycle["period_start"] <= ra < cycle["period_end"]:
            out.append(o)
    return out


def cycle_in_flight(cycle):
    out = []
    for o in store["orders"].values():
        if o["merchant_id"] != cycle["merchant_id"]:
            continue
        if o["status"] in ORDER_TERMINAL:
            continue
        if cycle["period_start"] <= o["created_at"] < cycle["period_end"]:
            out.append(o)
    return out


def cycle_refunds_accrued(cycle):
    total = 0
    for o in cycle_fulfilled(cycle):
        fin = latest_final(o["id"])
        if fin is not None:
            total += fin["amount_cents"]
    return total


def open_cycle_covering(merchant_id, instant):
    for c in store["cycles"].values():
        if c["merchant_id"] == merchant_id and c["status"] == "OPEN" \
                and c["period_start"] <= instant < c["period_end"]:
            return c
    return None


def billing_charge(cycle, variant):
    """billing_cycle_charge: pinned evaluation order (PRD 3.2).
    variant: "provisional_preview" counts in-flight; "final_close" does not."""
    merchant = store["merchants"][cycle["merchant_id"]]
    plan = merchant_plan(merchant)
    fulfilled = cycle_fulfilled(cycle)
    in_flight = cycle_in_flight(cycle)
    counted = len(fulfilled) + (len(in_flight) if variant == "provisional_preview" else 0)
    base_cents = plan["monthly_fee_cents"]
    overage_count = max(0, counted - plan["included_returns"])
    overage_fee_cents = overage_count * plan["overage_fee_cents"]
    surcharge = 0
    for o in fulfilled:
        if o["has_oversize_item"]:
            surcharge += plan["oversize_surcharge_cents"]
        if o["method"] == "HOME_PICKUP":
            surcharge += plan["pickup_fee_cents"]
    gross = base_cents + overage_fee_cents + surcharge
    if gross >= 500000:
        pct = Decimal("0.10")
    elif gross >= 200000:
        pct = Decimal("0.05")
    else:
        pct = Decimal("0")
    discount = _round_half_up_cents(Decimal(gross) * pct)
    return {
        "variant": variant,
        "fulfilled_count": len(fulfilled),
        "in_flight_count": len(in_flight),
        "base_cents": base_cents,
        "overage_count": overage_count,
        "overage_fee_cents": overage_fee_cents,
        "surcharge_cents": surcharge,
        "gross_cents": gross,
        "discount_cents": discount,
        "total_cents": gross - discount,
    }


# ---------------------------------------------------------------- zones -----
def windows_overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


def zone_confirmed_for_window(zone_id, ws, we):
    n = 0
    for a in store["appointments"].values():
        if a["zone_id"] == zone_id and a["status"] in ("SCHEDULED", "EN_ROUTE") \
                and windows_overlap(a["window_start"], a["window_end"], ws, we):
            n += 1
    return n


def zone_loads(zone):
    now = db.now()
    confirmed = 0
    demand_extra = 0
    for a in store["appointments"].values():
        if a["zone_id"] != zone["id"]:
            continue
        contains_now = a["window_start"] <= now < a["window_end"]
        if not contains_now:
            continue
        if a["status"] in ("SCHEDULED", "EN_ROUTE"):
            confirmed += 1
        elif a["status"] == "FAILED" and a["attempt_count"] < PICKUP_MAX_ATTEMPTS:
            demand_extra += 1
    return confirmed, confirmed + demand_extra


# ---------------------------------------------------------------- totes -----
def tote_members(tote_id):
    return [o for o in store["orders"].values() if o.get("tote_id") == tote_id]


def tote_manifest(tote_id):
    units = 0
    weight = 0
    for o in tote_members(tote_id):
        units += o["total_units"]
        weight += o["total_weight_grams"]
    return units, weight


def location_slot_counts(location_id):
    reserved = 0
    occupied = 0
    for s in store["slots"].values():
        if s["location_id"] != location_id:
            continue
        if s["status"] == "RESERVED":
            reserved += 1
        elif s["status"] == "OCCUPIED":
            occupied += 1
    return reserved, occupied


# ------------------------------------------------------------ label issue ---
def issue_label(order, label_type, supersedes=None):
    label = {
        "return_order_id": order["id"],
        "label_type": label_type,
        "status": "ISSUED",
        "issued_at": db.now(),
        "expires_at": db.now() + LABEL_TTL,
        "supersedes_label_id": supersedes["id"] if supersedes else None,
    }
    stamp(label)
    store["labels"][label["id"]] = label
    if supersedes is not None:
        supersedes["status"] = "SUPERSEDED"
        touch(supersedes)
    return label


# ----------------------------------------------------------- serializers ----
def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_ms(rec["created_at"]),
        "updated_at": fmt_ms(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_plan(p):
    d = _common(p)
    d.update({
        "tier": p["tier"],
        "monthly_fee_cents": p["monthly_fee_cents"],
        "included_returns": p["included_returns"],
        "overage_fee_cents": p["overage_fee_cents"],
        "pickup_enabled": p["pickup_enabled"],
        "boxless_enabled": p["boxless_enabled"],
        "oversize_enabled": p["oversize_enabled"],
        "free_returns": p["free_returns"],
        "oversize_surcharge_cents": p["oversize_surcharge_cents"],
        "pickup_fee_cents": p["pickup_fee_cents"],
        "status": p["status"],
    })
    return d


def ser_merchant(m):
    d = _common(m)
    d.update({
        "legal_name": m["legal_name"],
        "plan_id": m["plan_id"],
        "status": m["status"],
        "ledger_balance_cents": m["ledger_balance_cents"],
    })
    return d


def ser_cycle(c):
    d = _common(c)
    if c["status"] == "OPEN":
        fulfilled = len(cycle_fulfilled(c))
        in_flight = len(cycle_in_flight(c))
    else:
        fulfilled = c.get("fulfilled_count")
        in_flight = c.get("in_flight_count")
    d.update({
        "merchant_id": c["merchant_id"],
        "period_start": fmt_s(c["period_start"]),
        "period_end": fmt_s(c["period_end"]),
        "status": c["status"],
        "fulfilled_count": fulfilled,
        "in_flight_count": in_flight,
        "refunds_accrued_cents": cycle_refunds_accrued(c),
        "base_cents": c.get("base_cents"),
        "overage_count": c.get("overage_count"),
        "overage_fee_cents": c.get("overage_fee_cents"),
        "surcharge_cents": c.get("surcharge_cents"),
        "gross_cents": c.get("gross_cents"),
        "discount_cents": c.get("discount_cents"),
        "total_cents": c.get("total_cents"),
        "closed_by_user_id": c.get("closed_by_user_id"),
        "settled_by_user_id": c.get("settled_by_user_id"),
    })
    return d


def ser_shopper(s):
    d = _common(s)
    d.update({
        "email": s["email"],
        "full_name": s["full_name"],
        "postal_code": s["postal_code"],
        "status": s["status"],
        "fraud_strikes": s["fraud_strikes"],
    })
    return d


def ser_order(o):
    d = _common(o)
    d.update({
        "shopper_id": o["shopper_id"],
        "merchant_id": o["merchant_id"],
        "method": o["method"],
        "boxless": o["boxless"],
        "status": o["status"],
        "refund_estimate_cents": o["refund_estimate_cents"],
        "refund_final_cents": o["refund_final_cents"],
        "resolved_at": fmt_s(o["resolved_at"]) if o.get("resolved_at") else None,
        "tote_id": o.get("tote_id"),
        "dropoff_location_id": o.get("dropoff_location_id"),
        "total_units": o["total_units"],
        "total_weight_grams": o["total_weight_grams"],
        "has_oversize_item": o["has_oversize_item"],
    })
    return d


def ser_item(i):
    d = _common(i)
    d.update({
        "return_order_id": i["return_order_id"],
        "sku": i["sku"],
        "quantity": i["quantity"],
        "unit_price_cents": i["unit_price_cents"],
        "declared_condition": i["declared_condition"],
        "condition": i["condition"],
        "longest_side_cm": i["longest_side_cm"],
        "weight_grams": i["weight_grams"],
        "status": i["status"],
        "deduction_cents": i["deduction_cents"],
        "inspected_at": fmt_s(i["inspected_at"]) if i.get("inspected_at") else None,
    })
    return d


def ser_location(loc):
    d = _common(loc)
    reserved, occupied = location_slot_counts(loc["id"])
    d.update({
        "name": loc["name"],
        "kind": loc["kind"],
        "postal_code": loc["postal_code"],
        "status": loc["status"],
        "reserved_slot_count": reserved,
        "occupied_slot_count": occupied,
    })
    return d


def ser_slot(s):
    d = _common(s)
    d.update({
        "location_id": s["location_id"],
        "size_class": s["size_class"],
        "status": s["status"],
    })
    return d


def ser_reservation(r):
    d = _common(r)
    d.update({
        "slot_id": r["slot_id"],
        "return_order_id": r["return_order_id"],
        "status": r["status"],
        "hold_start": fmt_s(r["hold_start"]),
        "hold_until": fmt_s(r["hold_until"]),
        "label_id": r["label_id"],
    })
    return d


def ser_label(l):
    d = _common(l)
    d.update({
        "return_order_id": l["return_order_id"],
        "label_type": l["label_type"],
        "status": l["status"],
        "issued_at": fmt_s(l["issued_at"]),
        "expires_at": fmt_s(l["expires_at"]),
        "supersedes_label_id": l["supersedes_label_id"],
    })
    return d


def ser_zone(z):
    d = _common(z)
    confirmed, demand = zone_loads(z)
    d.update({
        "zone_code": z["zone_code"],
        "window_capacity": z["window_capacity"],
        "confirmed_load": confirmed,
        "demand_load": demand,
    })
    return d


def ser_appointment(a):
    d = _common(a)
    d.update({
        "return_order_id": a["return_order_id"],
        "zone_id": a["zone_id"],
        "window_start": fmt_s(a["window_start"]),
        "window_end": fmt_s(a["window_end"]),
        "status": a["status"],
        "attempt_count": a["attempt_count"],
    })
    return d


def ser_route(r):
    d = _common(r)
    d.update({
        "origin_location_id": r["origin_location_id"],
        "destination_facility": r["destination_facility"],
        "weight_capacity_grams": r["weight_capacity_grams"],
        "status": r["status"],
    })
    return d


def ser_tote(t):
    d = _common(t)
    units, weight = tote_manifest(t["id"])
    d.update({
        "route_id": t["route_id"],
        "location_id": t["location_id"],
        "status": t["status"],
        "manifest_units": units,
        "manifest_weight_grams": weight,
        "sealed_by_user_id": t.get("sealed_by_user_id"),
    })
    return d


def ser_ledger_entry(e):
    # Append-only log: id + created_at only; no updated_at / version.
    return {
        "id": e["id"],
        "return_order_id": e["return_order_id"],
        "kind": e["kind"],
        "amount_cents": e["amount_cents"],
        "note": e["note"],
        "actor_user_id": e["actor_user_id"],
        "created_at": fmt_ms(e["created_at"]),
    }


def ser_exception(c):
    d = _common(c)
    d.update({
        "return_order_id": c["return_order_id"],
        "return_item_id": c.get("return_item_id"),
        "kind": c["kind"],
        "note": c["note"],
        "status": c["status"],
        "resolution": c["resolution"],
        "opened_by_user_id": c["opened_by_user_id"],
        "resolved_by_user_id": c["resolved_by_user_id"],
        "appeal_count": c["appeal_count"],
    })
    return d
