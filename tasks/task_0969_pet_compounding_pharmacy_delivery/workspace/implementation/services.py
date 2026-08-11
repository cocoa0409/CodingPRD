from datetime import timedelta
from decimal import Decimal

import db
from errors import ApiError
from util import (new_resource, touch, now_iso, clock_date, parse_date, rhu, dec,
                  fmt_dt)

CONTROLLED_SURCHARGE_CENTS = 1500
WASTE_SHRINK_PCT = Decimal("0.03")
MAX_CREDIT_SHARE = Decimal("0.5")
REFILL_ELIGIBILITY_PCT_NUM = 3  # 0.75 == 3/4
REFILL_ELIGIBILITY_PCT_DEN = 4
EXCURSION_BREACH_MINUTES = 30
COOLER_CONDITIONING_HOURS = 2

SHIPPING_BASE_CENTS = {"STANDARD": 500, "EXPRESS": 900, "OVERNIGHT": 1500}
COLD_CHAIN_SURCHARGE_CENTS = 1200
ICE_PACK_PER_24H_CENTS = 300
ZONE_TRANSIT_HOURS = {"Z1": 24, "Z2": 48, "Z3": 72}
SHIPPING_FEE_CAP_CENTS = 3500

IN_FLIGHT_ORDER_STATES = {"COMPOUNDING", "FLAVORING", "REWORK", "QA_PENDING",
                          "READY_TO_DISPATCH", "RECALL_HOLD"}
HOLDABLE_ORDER_STATES = {"ALLOCATED", "COMPOUNDING", "FLAVORING", "QA_PENDING",
                         "READY_TO_DISPATCH"}
QUARANTINABLE_TRANSIT = {"LABEL_CREATED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"}


def get_or_404(coll, rid, label="resource"):
    r = coll.get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", "{} {} not found".format(label, rid), 404)
    return r


def weight_mult(w):
    w = dec(w)
    if w < 5:
        return Decimal("1.00")
    if w < 15:
        return Decimal("1.15")
    if w < 30:
        return Decimal("1.30")
    return Decimal("1.50")


def compute_provisional(rx, pet, drug, flavoring):
    base = rx["quantity"] * drug["unit_cost_cents"]
    flav = flavoring["surcharge_cents"] if flavoring else 0
    mult = weight_mult(pet["weight_kg"])
    total = rhu(dec(base + flav) * mult)
    if rx["schedule_snapshot"] != "NON_CONTROLLED":
        total += CONTROLLED_SURCHARGE_CENTS
    return total


def order_allocations(order):
    return sorted(
        (a for a in db.lot_allocations.values() if a["compound_order_id"] == order["id"]),
        key=lambda a: a["_seq"])


def compute_final_price(order, rx, pet, flavoring):
    lot_component = 0
    for a in order_allocations(order):
        if a["status"] != "CONSUMED":
            continue
        lot = db.lots[a["lot_id"]]
        lot_component += rhu(dec(a["qty_consumed"]) * dec(lot["unit_cost_cents"])
                             * (Decimal("1") + WASTE_SHRINK_PCT))
    flav = flavoring["surcharge_cents"] if flavoring else 0
    mult = weight_mult(pet["weight_kg"])
    total = rhu(dec(lot_component + flav) * mult)
    if rx["schedule_snapshot"] != "NON_CONTROLLED":
        total += CONTROLLED_SURCHARGE_CENTS
    return total


def waterfall(amount_cents, policy):
    deductible_applied = min(amount_cents,
                             policy["deductible_cents"] - policy["deductible_met_cents"])
    if deductible_applied < 0:
        deductible_applied = 0
    after_deductible = amount_cents - deductible_applied
    covered = rhu(dec(after_deductible) * dec(policy["coverage_pct"]))
    payout = min(covered, policy["annual_limit_cents"] - policy["annual_used_cents"])
    return payout, deductible_applied


def shipping_fee(service_level, destination_zone, requires_cold_chain):
    base = SHIPPING_BASE_CENTS[service_level]
    cold = COLD_CHAIN_SURCHARGE_CENTS if requires_cold_chain else 0
    hours = ZONE_TRANSIT_HOURS[destination_zone]
    days = -(-hours // 24)  # ceil
    ice = days * ICE_PACK_PER_24H_CENTS
    return min(SHIPPING_FEE_CAP_CENTS, base + cold + ice)


# ---- controlled substance log ----

def cs_append(lot, entry_type, qty_delta, recorded_by, order_id=None):
    drug = db.drug_catalog_items[lot["drug_catalog_item_id"]]
    if drug["schedule"] == "NON_CONTROLLED":
        return None
    prior = [e for e in db.cs_entries.values() if e["lot_id"] == lot["id"]]
    prior.sort(key=lambda e: e["_seq"])
    balance = (prior[-1]["running_balance"] if prior else 0) + qty_delta
    if balance < 0:
        raise ApiError("ERR_WASTE_EXCEEDS_ON_HAND",
                       "entry would drive the controlled running balance below zero", 422)
    entry = new_resource({
        "lot_id": lot["id"],
        "compound_order_id": order_id,
        "entry_type": entry_type,
        "qty_delta": qty_delta,
        "running_balance": balance,
        "recorded_by": recorded_by,
        "recorded_at": now_iso(),
    }, versioned=False)
    db.cs_entries[entry["id"]] = entry
    return entry


def update_lot_exhaustion(lot):
    if lot["status"] == "ACTIVE" and lot["qty_on_hand"] == 0 and lot["qty_reserved"] == 0:
        lot["status"] = "EXHAUSTED"
    elif lot["status"] == "EXHAUSTED" and lot["qty_on_hand"] > 0:
        lot["status"] = "ACTIVE"


# ---- order helpers ----

def release_reserved_allocations(order):
    for a in order_allocations(order):
        if a["status"] != "RESERVED":
            continue
        lot = db.lots[a["lot_id"]]
        lot["qty_reserved"] -= a["qty_allocated"]
        lot["qty_on_hand"] += a["qty_allocated"]
        a["status"] = "RELEASED"
        touch(a)
        update_lot_exhaustion(lot)
        touch(lot)


def refund_order(order, touch_order=True):
    if order["payment_status"] != "PAID":
        return
    order["payment_status"] = "REFUNDED"
    if order.get("paid_via") == "WELLNESS_CREDIT":
        enr = db.enrollments.get(order.get("_credit_enrollment_id") or "")
        used = order.get("_credits_used", 0)
        if enr is not None and used:
            enr["credits_remaining"] += used
            enr["credits_consumed"] -= used
            touch(enr)
    if touch_order:
        touch(order)


def cancel_order_internal(order):
    release_reserved_allocations(order)
    for r in db.bench_reservations.values():
        if r["compound_order_id"] == order["id"] and r["status"] == "BOOKED":
            r["status"] = "RELEASED"
            touch(r)
    refund_order(order, touch_order=False)
    order["status"] = "CANCELLED"
    touch(order)


def order_lots(order):
    seen = {}
    for a in order_allocations(order):
        if a["status"] in ("RESERVED", "CONSUMED"):
            seen[a["lot_id"]] = db.lots[a["lot_id"]]
    return list(seen.values())


def active_recall_touches_lot(lot):
    rid = lot.get("recall_id")
    if rid:
        rec = db.recalls.get(rid)
        if rec is not None and rec["status"] == "ACTIVE":
            return True
    for rec in db.recalls.values():
        if rec["status"] != "ACTIVE":
            continue
        if rec["scope"] == "LOT" and rec.get("lot_id") == lot["id"]:
            return True
        if rec["scope"] == "CATALOG_ITEM" and \
                rec.get("drug_catalog_item_id") == lot["drug_catalog_item_id"]:
            return True
    return False


def check_no_active_recall(order):
    for lot in order_lots(order):
        if active_recall_touches_lot(lot):
            raise ApiError("ERR_RECALL_ACTIVE_ON_LOT",
                           "an ACTIVE recall touches a lot allocated to the order", 409)


def check_recall_hold(order, action):
    """A held order rejects every action except resume and cancel."""
    if order["status"] == "RECALL_HOLD" and action not in ("resume", "cancel"):
        raise ApiError("ERR_RECALL_HOLD_ACTIVE",
                       "order is under a recall hold; only resume and cancel are allowed",
                       409)


# ---- compound order creation (shared by endpoint and auto-ship run) ----

def create_compound_order(rx, flavoring, is_refill):
    if rx["status"] == "EXPIRED":
        raise ApiError("ERR_PRESCRIPTION_EXPIRED", "prescription is expired", 409)
    if rx["status"] != "VERIFIED":
        raise ApiError("ERR_PRESCRIPTION_NOT_VERIFIED",
                       "prescription is not VERIFIED", 409)
    siblings = sorted(
        (o for o in db.compound_orders.values() if o["prescription_id"] == rx["id"]),
        key=lambda o: o["_seq"])
    for o in siblings:
        if o["status"] in IN_FLIGHT_ORDER_STATES:
            raise ApiError("ERR_ORDER_IN_PROGRESS",
                           "another order of this prescription is in flight", 409)
    pet = db.pets[rx["pet_id"]]
    if flavoring is not None:
        if set(flavoring["allergen_tags"]) & set(pet["allergies"]):
            raise ApiError("ERR_ALLERGEN_CONFLICT",
                           "flavoring allergen tag intersects pet allergies", 422)
        if pet["species"] not in flavoring["compatible_species"]:
            raise ApiError("ERR_SPECIES_FLAVOR_INCOMPATIBLE",
                           "pet species is not compatible with the flavoring", 422)
    if is_refill:
        if rx["schedule_snapshot"] == "C_II":
            raise ApiError("ERR_CONTROLLED_REFILL_FORBIDDEN",
                           "refills are forbidden on C_II prescriptions", 422)
        if pet["status"] != "ALIVE":
            raise ApiError("ERR_PET_DECEASED", "pet is deceased", 422)
        if rx["refills_remaining"] <= 0:
            raise ApiError("ERR_REFILLS_EXHAUSTED", "no refills remaining", 422)
        threshold = (REFILL_ELIGIBILITY_PCT_NUM * rx["days_supply"]
                     + REFILL_ELIGIBILITY_PCT_DEN - 1) // REFILL_ELIGIBILITY_PCT_DEN
        dispensed = [o for o in siblings if o["status"] == "DISPENSED"]
        if dispensed:
            last_date = parse_date(dispensed[-1]["created_at"][:10])
            if (clock_date() - last_date).days < threshold:
                raise ApiError("ERR_REFILL_TOO_EARLY",
                               "refill eligibility window has not elapsed", 422)
    supersedes = None
    for o in siblings:
        if o["status"] in ("CREATED", "ALLOCATED"):
            cancel_order_internal(o)
            supersedes = o["id"]
    formula = db.formulas[rx["formula_id"]]
    drug = db.drug_catalog_items[formula["drug_catalog_item_id"]]
    provisional = compute_provisional(rx, pet, drug, flavoring)
    if is_refill:
        fill_number = max([o["fill_number"] for o in siblings] + [0]) + 1
    else:
        fill_number = 1
    order = new_resource({
        "prescription_id": rx["id"],
        "owner_id": rx["owner_id"],
        "flavoring_id": flavoring["id"] if flavoring else None,
        "is_refill": bool(is_refill),
        "fill_number": fill_number,
        "supersedes_order_id": supersedes,
        "status": "CREATED",
        "hold_origin_state": None,
        "payment_status": "UNPAID",
        "paid_via": None,
        "quantity_snapshot": rx["quantity"],
        "provisional_price_cents": provisional,
        "final_price_cents": None,
        "compounding_pharmacist_id": None,
        "qa_pharmacist_id": None,
        "_wasted_total": 0,
        "_credits_used": 0,
        "_credit_enrollment_id": None,
    })
    db.compound_orders[order["id"]] = order
    if is_refill:
        rx["refills_remaining"] -= 1
        if rx["refills_remaining"] == 0:
            rx["status"] = "EXHAUSTED"
    touch(rx)
    return order


# ---- FEFO allocation ----

def fefo_candidates(rx, formula):
    drug_id = formula["drug_catalog_item_id"]
    min_exp = clock_date() + timedelta(days=rx["days_supply"])
    cands = [l for l in db.lots.values()
             if l["drug_catalog_item_id"] == drug_id
             and l["status"] == "ACTIVE"
             and parse_date(l["expiration_date"]) is not None
             and parse_date(l["expiration_date"]) >= min_exp]
    cands.sort(key=lambda l: (parse_date(l["expiration_date"]), l["_seq"]))
    return cands


# ---- schedule cascades ----

def cancel_schedules_for_prescription(rx_id):
    for s in db.auto_ship_schedules.values():
        if s["prescription_id"] == rx_id and s["status"] in ("ACTIVE", "PAUSED"):
            s["status"] = "CANCELLED"
            touch(s)


def cancel_schedules_for_enrollment(enrollment_id):
    for s in db.auto_ship_schedules.values():
        if s.get("enrollment_id") == enrollment_id and s["status"] in ("ACTIVE", "PAUSED"):
            s["status"] = "CANCELLED"
            touch(s)


def pause_schedules_for_prescription(rx_id):
    for s in db.auto_ship_schedules.values():
        if s["prescription_id"] == rx_id and s["status"] == "ACTIVE":
            s["status"] = "PAUSED"
            touch(s)


# ---- shipment quarantine ----

def send_cooler_to_conditioning(sh):
    cid = sh.get("cooler_asset_id")
    if not cid:
        return
    cooler = db.cooler_assets.get(cid)
    if cooler is not None and cooler["status"] == "ASSIGNED":
        cooler["status"] = "CONDITIONING"
        cooler["conditioning_available_at"] = fmt_dt(
            db.clock() + timedelta(hours=COOLER_CONDITIONING_HOURS))
        touch(cooler)


def quarantine_shipment(sh):
    if sh["transit_status"] not in QUARANTINABLE_TRANSIT:
        return
    sh["transit_status"] = "QUARANTINED"
    order = db.compound_orders[sh["compound_order_id"]]
    refund_order(order)
    send_cooler_to_conditioning(sh)
    touch(sh)


# ---- recalls ----

def covered_lots(recall):
    if recall["scope"] == "LOT":
        lot = db.lots.get(recall.get("lot_id") or "")
        return [lot] if lot is not None else []
    return [l for l in db.lots.values()
            if l["drug_catalog_item_id"] == recall.get("drug_catalog_item_id")]


def activate_recall_cascade(recall):
    lots = covered_lots(recall)
    covered_ids = {l["id"] for l in lots}
    for lot in lots:
        if lot["status"] == "ACTIVE":
            lot["status"] = "QUARANTINED"
            lot["recall_id"] = recall["id"]
            touch(lot)
    # hold in-flight orders
    held = []
    for order in sorted(db.compound_orders.values(), key=lambda o: o["_seq"]):
        if order["status"] not in HOLDABLE_ORDER_STATES:
            continue
        lot_ids = {a["lot_id"] for a in order_allocations(order)
                   if a["status"] in ("RESERVED", "CONSUMED")}
        if not (lot_ids & covered_ids):
            continue
        order["hold_origin_state"] = order["status"]
        order["status"] = "RECALL_HOLD"
        if order["hold_origin_state"] == "COMPOUNDING":
            for r in db.bench_reservations.values():
                if r["compound_order_id"] == order["id"] and r["status"] == "IN_USE":
                    r["status"] = "RELEASED"
                    touch(r)
        touch(order)
        held.append(order)
    for order in held:
        for sh in sorted(db.shipments.values(), key=lambda s: s["_seq"]):
            if sh["compound_order_id"] == order["id"] and \
                    sh["transit_status"] in QUARANTINABLE_TRANSIT:
                quarantine_shipment(sh)
        pause_schedules_for_prescription(order["prescription_id"])
    # recall tasks for dispensed orders
    for order in sorted(db.compound_orders.values(), key=lambda o: o["_seq"]):
        if order["status"] != "DISPENSED":
            continue
        lot_ids = {a["lot_id"] for a in order_allocations(order)
                   if a["status"] in ("RESERVED", "CONSUMED")}
        if not (lot_ids & covered_ids):
            continue
        task = new_resource({
            "recall_id": recall["id"],
            "compound_order_id": order["id"],
            "owner_id": order["owner_id"],
            "channel": "EMAIL",
            "status": "PENDING",
        })
        db.recall_tasks[task["id"]] = task
