"""Shared cross-entity helpers: bale assignment, batch recompute, open-cycle lookup."""
from db import db, new_record, touch, iso_now
from services import calc


def get_open_cycle():
    for c in db.cycles.values():
        if c["status"] == "OPEN":
            return c
    return None


def get_or_create_accumulating_bale(category):
    for b in db.bales.values():
        if b["category"] == category and b["status"] == "ACCUMULATING":
            return b
    rec = new_record()
    rec.update({
        "category": category,
        "status": "ACCUMULATING",
        "vendor_id": None,
        "weight_lbs": 0,
        "item_count": 0,
        "estimated_revenue_cents": 0,
        "actual_weight_lbs": None,
        "settled_revenue_cents": None,
        "settled_cycle_id": None,
        "sealed_at": None,
        "shipped_at": None,
        "settled_at": None,
    })
    db.bales[rec["id"]] = rec
    return rec


def recompute_bale_estimate(bale):
    if bale["status"] == "ACCUMULATING" or bale["vendor_id"] is None:
        bale["estimated_revenue_cents"] = calc.bale_estimate_pre_seal(
            bale["category"], bale["weight_lbs"])
    else:
        vendor = db.vendors.get(bale["vendor_id"])
        if vendor is not None:
            bale["estimated_revenue_cents"] = calc.bale_estimate_post_seal(
                vendor, bale["category"], bale["weight_lbs"])


def assign_item_to_bale(item, category):
    """RECYCLE triage / markdown pull: feed the item into the category's
    ACCUMULATING bale (auto-create), grow weight/count, set bale_id, recompute
    estimate (cascade hop: item -> bale -> estimate)."""
    bale = get_or_create_accumulating_bale(category)
    bale["item_count"] += 1
    bale["weight_lbs"] = round(float(bale["weight_lbs"]) + float(item["weight_lbs"]), 6)
    item["bale_id"] = bale["id"]
    recompute_bale_estimate(bale)
    touch(bale)
    return bale


def recompute_batch_rollups(batch):
    """Recompute item_count / untriaged_count / provisional_value_cents /
    sold_item_count from the item store."""
    items = [i for i in db.items.values() if i["batch_id"] == batch["id"]]
    batch["item_count"] = len(items)
    batch["untriaged_count"] = sum(1 for i in items if i["status"] == "RECEIVED")
    batch["provisional_value_cents"] = sum(i["provisional_value_cents"] for i in items)
    batch["sold_item_count"] = sum(1 for i in items if i["status"] == "SOLD")


def recompute_route_rollups(route):
    stops = [s for s in db.stops.values() if s["route_id"] == route["id"]]
    route["stop_count"] = len(stops)
    route["total_volume_cuft"] = round(sum(
        float(s["estimated_volume_cuft"]) for s in stops
        if s["status"] in ("SCHEDULED", "EN_ROUTE")), 6)


def recompute_shift_assigned_count(shift):
    shift["assigned_count"] = sum(
        1 for a in db.assignments.values()
        if a["shift_id"] == shift["id"] and a["status"] in ("ASSIGNED", "CONFIRMED"))


def recompute_session_totals(session):
    completed = [s for s in db.sales.values()
                 if s["till_session_id"] == session["id"] and s["status"] == "COMPLETED"]
    session["cash_sales_cents"] = sum(
        s["total_cents"] for s in completed if s["payment_method"] == "CASH")
    session["card_sales_cents"] = sum(
        s["total_cents"] for s in completed if s["payment_method"] == "CARD")
    session["expected_cash_cents"] = session["opening_float_cents"] + session["cash_sales_cents"]


def issued_receipt_for_batch(batch_id):
    for r in db.receipts.values():
        if r["batch_id"] == batch_id and r["status"] == "ISSUED":
            return r
    return None
