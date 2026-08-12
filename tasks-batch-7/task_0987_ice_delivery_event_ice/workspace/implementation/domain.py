"""Domain logic: derived state, pricing engine, capacity gates, cascades.

Implements SCAFFOLD §1.3 calculation rules:
  order_line_pricing, order_total_composition (PROVISIONAL/FINAL variants),
  credit_exposure (SETTLED / FORWARD_LOOKING), freezer_capacity_and_posture,
  bunker_interval_exclusion, slot_reservation_capacity, surge_admission,
  waitlist_promotion_selection, payment_waterfall, invoice_consolidation,
  ops_run_sweeps.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import core
from core import fail
from store import (BOOKS, CERTS, CUSTOMERS, DEPOTS, ENTRIES, HOLDS, INVOICES,
                   ORDER_LINES, ORDERS, ROUTES, RUNS, SLOTS, SURGE_WINDOWS)

# Pinned constants (SCAFFOLD §1.3)
HANDLING_BPS = 700
WEIGHT_LBS = {
    ("CUBE", "BAG"): 7, ("CUBE", "PALLET"): 960,
    ("BLOCK", "BAG"): 25, ("BLOCK", "PALLET"): 300,
    ("DRY_ICE", "BAG"): 10, ("DRY_ICE", "PALLET"): 500,
}
GRACE_MINUTES = 60
VENTILATION_BUFFER_MINUTES = 30
STAGING_LEAD_HOURS = 4
ROUTE_GENERATION_LEAD_DAYS = 3

SLOT_RESERVED_STATUSES = {"QUOTED", "CONFIRMED", "WAITLISTED", "STAGED", "IN_TRANSIT"}
SURGE_COMMITTED_STATUSES = {"CONFIRMED", "STAGED", "READY_FOR_PICKUP", "IN_TRANSIT"}
RUN_ASSIGNED_STATUSES = {"STAGED", "IN_TRANSIT", "DELIVERED"}
BILLABLE_FULFILLMENTS = {"DELIVERED", "PICKED_UP", "NO_SHOW"}
PIPELINE_FULFILLMENTS = {"CONFIRMED", "WAITLISTED", "STAGED", "READY_FOR_PICKUP",
                         "IN_TRANSIT", "DELIVERED", "PICKED_UP", "NO_SHOW"}
OPEN_INVOICE_STATUSES = {"ISSUED", "PARTIALLY_PAID", "OVERDUE"}
TERMS_DAYS = {"PREPAID": 0, "NET_15": 15, "NET_30": 30}


def rhu(num):
    """Round half up to whole cents (PRD §2.8)."""
    return int(Decimal(num).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity lookups
# ---------------------------------------------------------------------------
def order_lines(order_id):
    return sorted((l for l in ORDER_LINES.values() if l["order_id"] == order_id),
                  key=lambda l: l["_seq"])


def order_measures(order_id):
    """pallets_required and dry_ice_lbs, derived from the lines (PRD §3.4)."""
    pallets = 0
    dry = 0
    for l in order_lines(order_id):
        if l["packaging"] == "PALLET":
            pallets += l["quantity_units"]
        else:
            pallets += -(-l["quantity_units"] // 20)  # ceil(qty/20)
        if l["product_form"] == "DRY_ICE":
            dry += l["quantity_units"] * WEIGHT_LBS[(l["product_form"], l["packaging"])]
    return pallets, dry


def has_dry_ice(order_id):
    return any(l["product_form"] == "DRY_ICE" for l in order_lines(order_id))


# ---------------------------------------------------------------------------
# Depot freezer accounting + posture (SCAFFOLD: freezer_capacity_and_posture)
# ---------------------------------------------------------------------------
def depot_reserved_pallets(depot_id):
    # DRY_ICE_BUNKER holds are excluded from every freezer sum (PRD §2.9).
    return sum(h["pallets_required"] for h in HOLDS.values()
               if h["depot_id"] == depot_id
               and h["status"] in ("RESERVED", "OCCUPIED")
               and h["zone"] == "GENERAL_FREEZER")


def depot_posture(depot):
    free = depot["freezer_capacity_pallets"] - depot_reserved_pallets(depot["id"])
    if free <= 0:
        return "FROZEN"
    if free <= -(-depot["freezer_capacity_pallets"] // 5):  # ceil(capacity * 20%)
        return "SURGE_CONSTRAINED"
    return "OPEN"


def bump_depot(depot_id):
    d = DEPOTS[depot_id]
    d["version"] += 1
    d["updated_at"] = core.stamp()


# ---------------------------------------------------------------------------
# Slots (slot_reservation_capacity)
# ---------------------------------------------------------------------------
def slot_reserved_pallets(slot_id):
    return sum(order_measures(o["id"])[0] for o in ORDERS.values()
               if o["delivery_slot_id"] == slot_id
               and o["fulfillment_status"] in SLOT_RESERVED_STATUSES)


def slot_status(slot):
    if slot["closed"]:
        return "CLOSED"
    if slot_reserved_pallets(slot["id"]) >= slot["capacity_pallets"]:
        return "FULL"
    return "OPEN"


def bump_slot(slot):
    slot["version"] += 1
    slot["updated_at"] = core.stamp()


def release_slot_reservation(order):
    sid = order["delivery_slot_id"]
    if sid is not None:
        order["delivery_slot_id"] = None
        bump_slot(SLOTS[sid])


# ---------------------------------------------------------------------------
# Surge windows (surge_admission); status derived from logical date (PRD §3.1)
# ---------------------------------------------------------------------------
def window_status(w):
    t = core.today()
    if t < w["start_date"]:
        return "SCHEDULED"
    if t > w["end_date"]:
        return "ENDED"
    return "ACTIVE"


def covering_active_windows(depot_id, event_date):
    return [w for w in SURGE_WINDOWS.values()
            if w["depot_id"] == depot_id
            and w["start_date"] <= event_date <= w["end_date"]
            and window_status(w) == "ACTIVE"]


def surge_applies(depot_id, event_date):
    return len(covering_active_windows(depot_id, event_date)) > 0


def committed_pallets(depot_id, event_date):
    return sum(order_measures(o["id"])[0] for o in ORDERS.values()
               if o["depot_id"] == depot_id and o["event_date"] == event_date
               and o["fulfillment_status"] in SURGE_COMMITTED_STATUSES)


# ---------------------------------------------------------------------------
# Pricing engine (order_line_pricing + order_total_composition)
# ---------------------------------------------------------------------------
def match_tier(book, line):
    best = None
    for row in book["lines"]:
        if row["product_form"] != line["product_form"] or row["packaging"] != line["packaging"]:
            continue
        q = line["quantity_units"]
        if q >= row["tier_min_units"] and (row["tier_max_units"] is None or q <= row["tier_max_units"]):
            if best is None or row["tier_min_units"] > best["tier_min_units"]:
                best = row
    if best is None:
        fail("ERR_INVALID_REQUEST", 400,
             "No pricing tier in the pinned price book matches a line")
    return best


def active_book():
    for b in BOOKS.values():
        if b["status"] == "ACTIVE":
            return b
    return None


def compute_pricing(order, book):
    """Pure (re)compute of the full price stack; returns a pricing dict.

    Pinned evaluation order (PRD §3.4): per-line rounding BEFORE summation;
    discount and surcharge are the only rounded stack steps; deposit exempt
    from discount and surcharge bases.
    """
    line_prices = []
    for l in order_lines(order["id"]):
        row = match_tier(book, l)
        up = row["unit_price_cents"]
        if l["product_form"] == "DRY_ICE":
            lt = rhu(Decimal(l["quantity_units"]) * up
                     * (Decimal(10000 + HANDLING_BPS) / Decimal(10000)))
        else:
            lt = l["quantity_units"] * up
        line_prices.append({"line_id": l["id"], "unit_price_cents": up,
                            "line_total_cents": lt})
    subtotal = sum(lp["line_total_cents"] for lp in line_prices)

    best_tier = None
    for t in book["volume_discount_tiers"]:
        if t["threshold_cents"] <= subtotal and (
                best_tier is None or t["threshold_cents"] > best_tier["threshold_cents"]):
            best_tier = t
    discount = 0
    if best_tier is not None:
        discount = rhu(Decimal(subtotal) * best_tier["discount_bps"] / Decimal(10000))

    post = subtotal - discount
    if order["channel"] == "WILL_CALL":
        fee = 0
    elif post >= book["free_delivery_threshold_cents"]:
        fee = 0
    else:
        fee = book["delivery_fee_cents"]

    if surge_applies(order["depot_id"], order["event_date"]):
        surcharge = rhu(Decimal(post) * book["surge_surcharge_bps"] / Decimal(10000))
    else:
        surcharge = 0

    deposit = sum(l["quantity_units"] * book["pallet_deposit_cents"]
                  for l in order_lines(order["id"]) if l["packaging"] == "PALLET")
    total = post + fee + surcharge + deposit
    return {"line_prices": line_prices,
            "merchandise_subtotal_cents": subtotal,
            "discount_cents": discount,
            "delivery_fee_cents": fee,
            "surcharge_cents": surcharge,
            "deposit_cents": deposit,
            "total_cents": total}


def apply_pricing(order, book, pricing, mode):
    for lp in pricing["line_prices"]:
        l = ORDER_LINES[lp["line_id"]]
        if l["unit_price_cents"] != lp["unit_price_cents"] or \
                l["line_total_cents"] != lp["line_total_cents"]:
            l["unit_price_cents"] = lp["unit_price_cents"]
            l["line_total_cents"] = lp["line_total_cents"]
            l["version"] += 1
            l["updated_at"] = core.stamp()
    for k in ("merchandise_subtotal_cents", "discount_cents", "delivery_fee_cents",
              "surcharge_cents", "deposit_cents", "total_cents"):
        order[k] = pricing[k]
    order["pricing_mode"] = mode


def touch_order(order):
    order["version"] += 1
    order["updated_at"] = core.stamp()


# ---------------------------------------------------------------------------
# Cold-storage holds
# ---------------------------------------------------------------------------
def hold_interval(order, zone):
    ws = core.combine(order["event_date"], order["window_start"])
    we = core.combine(order["event_date"], order["window_end"])
    if zone == "GENERAL_FREEZER":
        return (ws - timedelta(hours=STAGING_LEAD_HOURS),
                we + timedelta(minutes=GRACE_MINUTES))
    return (ws, we + timedelta(minutes=GRACE_MINUTES + VENTILATION_BUFFER_MINUTES))


def create_hold(order):
    pallets, _ = order_measures(order["id"])
    zone = "DRY_ICE_BUNKER" if has_dry_ice(order["id"]) else "GENERAL_FREEZER"
    start, end = hold_interval(order, zone)
    ts = core.stamp()
    h = {"id": core.new_id(), "_seq": core.next_seq(),
         "depot_id": order["depot_id"], "order_id": order["id"],
         "zone": zone, "pallets_required": pallets,
         "interval_start": start, "interval_end": end,
         "status": "RESERVED", "version": 1,
         "created_at": ts, "updated_at": ts}
    HOLDS[h["id"]] = h
    bump_depot(order["depot_id"])
    return h


def active_hold_for_order(order_id):
    for h in HOLDS.values():
        if h["order_id"] == order_id and h["status"] in ("RESERVED", "OCCUPIED"):
            return h
    return None


def latest_hold_for_order(order_id):
    hs = [h for h in HOLDS.values() if h["order_id"] == order_id]
    return max(hs, key=lambda h: h["_seq"]) if hs else None


def release_hold(hold, new_status="RELEASED", promoted_collector=None):
    """Hold -> RELEASED/EXPIRED with depot recompute; posture easing out of
    FROZEN immediately triggers the waitlist promotion sweep (PRD §3.6)."""
    depot = DEPOTS[hold["depot_id"]]
    before = depot_posture(depot)
    hold["status"] = new_status
    hold["version"] += 1
    hold["updated_at"] = core.stamp()
    bump_depot(depot["id"])
    after = depot_posture(depot)
    if before == "FROZEN" and after != "FROZEN":
        promotion_sweep(depot["id"], promoted_collector)


# ---------------------------------------------------------------------------
# Confirm-time capacity gates
# ---------------------------------------------------------------------------
def bunker_conflict(order):
    """bunker_interval_exclusion: half-open [ws, we+90m) vs other same-depot
    DRY_ICE_BUNKER holds in RESERVED/OCCUPIED; adjacency admitted."""
    cand_s = core.combine(order["event_date"], order["window_start"])
    cand_e = core.combine(order["event_date"], order["window_end"]) + timedelta(
        minutes=GRACE_MINUTES + VENTILATION_BUFFER_MINUTES)
    for h in HOLDS.values():
        if h["depot_id"] != order["depot_id"] or h["zone"] != "DRY_ICE_BUNKER":
            continue
        if h["status"] not in ("RESERVED", "OCCUPIED"):
            continue
        if cand_s < h["interval_end"] and h["interval_start"] < cand_e:
            return True
    return False


def freezer_peak_ok(order, depot, pallets):
    """Peak-overlap admission over I = [ws-4h, we+60m): at every instant the
    summed pallets of overlapping same-depot GENERAL_FREEZER holds plus the
    candidate's must stay within capacity (half-open intervals)."""
    cand_s = core.combine(order["event_date"], order["window_start"]) - timedelta(
        hours=STAGING_LEAD_HOURS)
    cand_e = core.combine(order["event_date"], order["window_end"]) + timedelta(
        minutes=GRACE_MINUTES)
    holds = [h for h in HOLDS.values()
             if h["depot_id"] == depot["id"] and h["zone"] == "GENERAL_FREEZER"
             and h["status"] in ("RESERVED", "OCCUPIED")]
    points = {cand_s}
    for h in holds:
        if cand_s < h["interval_start"] < cand_e:
            points.add(h["interval_start"])
    for t in points:
        load = sum(h["pallets_required"] for h in holds
                   if h["interval_start"] <= t < h["interval_end"])
        if load + pallets > depot["freezer_capacity_pallets"]:
            return False
    return True


def qualifying_cert(customer_id, dry_lbs, window_end_dt):
    for c in CERTS.values():
        if c["customer_id"] != customer_id:
            continue
        if (c["status"] == "ACTIVE" and c["expires_at"] >= window_end_dt
                and c["max_dry_ice_lbs"] >= dry_lbs):
            return True
    return False


# ---------------------------------------------------------------------------
# Customer credit (credit_exposure: SETTLED vs FORWARD_LOOKING)
# ---------------------------------------------------------------------------
def settled_exposure(customer_id):
    return sum(i["balance_due_cents"] for i in INVOICES.values()
               if i["customer_id"] == customer_id
               and i["status"] in OPEN_INVOICE_STATUSES)


def forward_exposure(customer_id):
    pipeline = sum(o["total_cents"] or 0 for o in ORDERS.values()
                   if o["customer_id"] == customer_id
                   and o["fulfillment_status"] in PIPELINE_FULFILLMENTS
                   and o["billing_status"] == "UNBILLED")
    return settled_exposure(customer_id) + pipeline


def customer_standing(customer_id):
    for i in INVOICES.values():
        if i["customer_id"] == customer_id and i["status"] == "OVERDUE":
            return "HOLD"
    return "GOOD"


# ---------------------------------------------------------------------------
# Waitlist promotion (waitlist_promotion_selection)
# ---------------------------------------------------------------------------
def promotion_sweep(depot_id, collector=None):
    """Greedy promotion in pinned rank order while headroom permits."""
    cands = []
    for e in ENTRIES.values():
        if e["depot_id"] != depot_id or e["status"] != "QUEUED":
            continue
        o = ORDERS[e["order_id"]]
        if o["fulfillment_status"] != "WAITLISTED":
            continue
        if o["event_date"] <= core.today():
            continue
        _, dry = order_measures(o["id"])
        if dry > 0:
            we_dt = core.combine(o["event_date"], o["window_end"])
            if not qualifying_cert(o["customer_id"], dry, we_dt):
                continue
        cands.append((e, o))
    cands.sort(key=lambda eo: (
        0 if CUSTOMERS[eo[1]["customer_id"]]["tier"] == "PRIORITY" else 1,
        eo[0]["queued_at"],
        eo[1]["event_date"],
        eo[1]["created_at"],
    ))
    for e, o in cands:
        if e["status"] != "QUEUED":  # may have changed earlier in this sweep
            continue
        depot = DEPOTS[depot_id]
        if depot_posture(depot) == "FROZEN":
            continue
        ok_surge = True
        for w in covering_active_windows(depot_id, o["event_date"]):
            if w["admission_policy"] == "RATIONED":
                if committed_pallets(depot_id, o["event_date"]) + \
                        e["requested_pallets"] > w["daily_pallet_cap"]:
                    ok_surge = False
                    break
        if not ok_surge:
            continue
        if o["delivery_slot_id"] is not None:
            slot = SLOTS[o["delivery_slot_id"]]
            if slot_reserved_pallets(slot["id"]) + e["requested_pallets"] > \
                    slot["capacity_pallets"]:
                continue
        promote_entry(e, o)
        if collector is not None:
            collector.append(e["id"])


def promote_entry(entry, order):
    """QUEUED -> PROMOTED; order WAITLISTED -> CONFIRMED with FINAL pricing,
    confirmed_at, and a fresh RESERVED hold (PRD §3.6 hop 4)."""
    entry["status"] = "PROMOTED"
    entry["promoted_at"] = core.stamp()
    book = BOOKS[order["price_book_id"]]
    apply_pricing(order, book, compute_pricing(order, book), "FINAL")
    order["fulfillment_status"] = "CONFIRMED"
    order["confirmed_at"] = core.stamp()
    touch_order(order)
    create_hold(order)


def enqueue_waitlist(order):
    pallets, _ = order_measures(order["id"])
    e = {"id": core.new_id(), "_seq": core.next_seq(),
         "order_id": order["id"], "depot_id": order["depot_id"],
         "requested_pallets": pallets, "status": "QUEUED",
         "queued_at": core.stamp(), "promoted_at": None,
         "created_at": core.stamp()}
    ENTRIES[e["id"]] = e
    return e


# ---------------------------------------------------------------------------
# Dispatch runs
# ---------------------------------------------------------------------------
def run_assigned_orders(run_id):
    return [o for o in ORDERS.values()
            if o["dispatch_run_id"] == run_id
            and o["fulfillment_status"] in RUN_ASSIGNED_STATUSES]


def run_assignment_totals(run_id):
    pallets = 0
    dry = 0
    for o in run_assigned_orders(run_id):
        p, d = order_measures(o["id"])
        pallets += p
        dry += d
    return pallets, dry


# ---------------------------------------------------------------------------
# Invoices / payments
# ---------------------------------------------------------------------------
def invoice_orders(invoice_id):
    return sorted((o for o in ORDERS.values() if o["invoice_id"] == invoice_id),
                  key=lambda o: o["_seq"])


def mark_invoice_paid(invoice):
    invoice["status"] = "PAID"
    for o in invoice_orders(invoice["id"]):
        if o["billing_status"] == "INVOICED":
            o["billing_status"] = "PAID"
            touch_order(o)


def payment_waterfall(customer, payment):
    eligible = [i for i in INVOICES.values()
                if i["customer_id"] == customer["id"]
                and i["status"] in OPEN_INVOICE_STATUSES]
    eligible.sort(key=lambda i: (i["due_date"], i["created_at"]))
    remaining = payment["amount_cents"]
    allocations = []
    for inv in eligible:
        if remaining <= 0:
            break
        apply_amt = min(remaining, inv["balance_due_cents"])
        if apply_amt <= 0:
            continue
        inv["amount_paid_cents"] += apply_amt
        inv["balance_due_cents"] = inv["total_cents"] - inv["amount_paid_cents"]
        remaining -= apply_amt
        allocations.append({"invoice_id": inv["id"], "applied_cents": apply_amt})
        if inv["balance_due_cents"] == 0:
            mark_invoice_paid(inv)
        elif inv["status"] != "OVERDUE":
            inv["status"] = "PARTIALLY_PAID"
        inv["version"] += 1
        inv["updated_at"] = core.stamp()
    payment["applied_cents"] = payment["amount_cents"] - remaining
    payment["overpayment_cents"] = remaining
    payment["allocations"] = allocations
    if remaining > 0:
        customer["credit_balance_cents"] += remaining
        customer["version"] += 1
        customer["updated_at"] = core.stamp()


# ---------------------------------------------------------------------------
# Ops-run checkpoint (ops_run_sweeps): eight sweeps in pinned order (PRD §3.9)
# ---------------------------------------------------------------------------
WEEKDAY_INDEX = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}


def spawn_route_order(route, occurrence):
    ts = core.stamp()
    oid = core.new_id()
    order = {"id": oid, "_seq": core.next_seq(),
             "customer_id": route["customer_id"], "depot_id": route["depot_id"],
             "recurring_route_id": route["id"], "channel": "DELIVERY",
             "event_date": occurrence,
             "window_start": route["window_start"], "window_end": route["window_end"],
             "fulfillment_status": "DRAFT", "billing_status": "UNBILLED",
             "delivery_slot_id": None, "dispatch_run_id": None, "invoice_id": None,
             "price_book_id": None, "price_book_version": None, "pricing_mode": None,
             "merchandise_subtotal_cents": None, "discount_cents": None,
             "delivery_fee_cents": None, "surcharge_cents": None,
             "deposit_cents": None, "total_cents": None,
             "quoted_at": None, "confirmed_at": None, "fulfilled_at": None,
             "version": 1, "created_at": ts, "updated_at": ts}
    ORDERS[oid] = order
    for ln in route["standing_lines"]:
        lid = core.new_id()
        lts = core.stamp()
        ORDER_LINES[lid] = {"id": lid, "_seq": core.next_seq(), "order_id": oid,
                            "product_form": ln["product_form"],
                            "packaging": ln["packaging"],
                            "quantity_units": ln["quantity_units"],
                            "unit_weight_lbs": WEIGHT_LBS[(ln["product_form"],
                                                           ln["packaging"])],
                            "unit_price_cents": None, "line_total_cents": None,
                            "version": 1, "created_at": lts, "updated_at": lts}
    return order


def route_next_occurrence(route):
    today_d = core.today()
    if route["last_generated_date"] is not None:
        start = route["last_generated_date"] + timedelta(days=1)
    else:
        start = today_d
    end = today_d + timedelta(days=ROUTE_GENERATION_LEAD_DAYS)
    d = start
    while d <= end:
        if d.weekday() == WEEKDAY_INDEX[route["weekday"]]:
            return d
        d += timedelta(days=1)
    return None


def run_ops_sweeps(depot):
    """Executes the eight pinned sweeps; every step observes prior effects.
    Returns the per-step identifier lists."""
    result = {"activated_book_ids": [], "expired_cert_ids": [],
              "closed_slot_ids": [], "expired_hold_ids": [],
              "no_show_order_ids": [], "overdue_invoice_ids": [],
              "expired_entry_ids": [], "generated_order_ids": [],
              "promoted_entry_ids": []}
    clock = core.now()
    today_d = core.today()

    # 1. PriceBook activation (instant comparison)
    for b in sorted(BOOKS.values(), key=lambda b: (b["effective_from"], b["_seq"])):
        if b["status"] == "SCHEDULED" and b["effective_from"] <= clock:
            for other in BOOKS.values():
                if other["status"] == "ACTIVE":
                    other["status"] = "SUPERSEDED"
                    other["version"] += 1
                    other["updated_at"] = core.stamp()
            b["status"] = "ACTIVE"
            b["version"] += 1
            b["updated_at"] = core.stamp()
            result["activated_book_ids"].append(b["id"])

    # 2. Certification expiry (instant comparison)
    for c in sorted(CERTS.values(), key=lambda c: c["_seq"]):
        if c["status"] in ("ACTIVE", "SUSPENDED") and c["expires_at"] < clock:
            c["status"] = "EXPIRED"
            c["version"] += 1
            c["updated_at"] = core.stamp()
            result["expired_cert_ids"].append(c["id"])

    # 3. Slot closure (date comparison), scoped to this depot
    for s in sorted(SLOTS.values(), key=lambda s: s["_seq"]):
        if s["depot_id"] == depot["id"] and not s["closed"] and s["date"] < today_d:
            s["closed"] = True
            bump_slot(s)
            result["closed_slot_ids"].append(s["id"])

    # 4. No-show sweep (instant comparison), scoped to this depot
    for h in sorted(HOLDS.values(), key=lambda h: h["_seq"]):
        if h["depot_id"] != depot["id"] or h["status"] != "OCCUPIED":
            continue
        if clock <= h["interval_end"]:
            continue
        o = ORDERS[h["order_id"]]
        if o["channel"] == "WILL_CALL" and o["fulfillment_status"] == "READY_FOR_PICKUP":
            o["fulfillment_status"] = "NO_SHOW"
            o["fulfilled_at"] = core.stamp()
            touch_order(o)
            release_hold(h, "EXPIRED", result["promoted_entry_ids"])
            result["expired_hold_ids"].append(h["id"])
            result["no_show_order_ids"].append(o["id"])

    # 5. Invoice overdue sweep (date comparison; invoices are platform-global)
    for inv in sorted(INVOICES.values(), key=lambda i: i["_seq"]):
        if (inv["status"] in ("ISSUED", "PARTIALLY_PAID")
                and inv["due_date"] is not None and today_d > inv["due_date"]
                and inv["balance_due_cents"] > 0):
            inv["status"] = "OVERDUE"
            inv["version"] += 1
            inv["updated_at"] = core.stamp()
            result["overdue_invoice_ids"].append(inv["id"])

    # 6. Waitlist expiry sweep (date comparison), scoped to this depot
    for e in sorted(ENTRIES.values(), key=lambda e: e["_seq"]):
        if e["depot_id"] != depot["id"] or e["status"] != "QUEUED":
            continue
        o = ORDERS[e["order_id"]]
        if o["event_date"] <= today_d:
            e["status"] = "EXPIRED"
            if o["fulfillment_status"] == "WAITLISTED":
                o["fulfillment_status"] = "CANCELLED"
                release_slot_reservation(o)
                touch_order(o)
            result["expired_entry_ids"].append(e["id"])

    # 7. Route generation, scoped to routes served by this depot
    for r in sorted(ROUTES.values(), key=lambda r: r["_seq"]):
        if r["depot_id"] != depot["id"] or r["status"] != "ACTIVE":
            continue
        occ = route_next_occurrence(r)
        if occ is not None:
            o = spawn_route_order(r, occ)
            r["last_generated_date"] = occ
            r["version"] += 1
            r["updated_at"] = core.stamp()
            result["generated_order_ids"].append(o["id"])

    # 8. Waitlist promotion sweep for this depot
    promotion_sweep(depot["id"], result["promoted_entry_ids"])

    return result
