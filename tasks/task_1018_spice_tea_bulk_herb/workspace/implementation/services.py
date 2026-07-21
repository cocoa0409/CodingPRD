"""Domain logic: derived fields, allergens, FEFO, exposure, serialization."""
import store as db
from store import clock_now, touch


# ---------------------------------------------------------------------------
# Freshness / lot status (PRD 2.7)
# ---------------------------------------------------------------------------
def lot_status(lot):
    if clock_now() >= lot["_best_by_dt"]:
        return "EXPIRED"
    if lot["grams_on_hand"] == 0:
        return "DEPLETED"
    return "AVAILABLE"


# ---------------------------------------------------------------------------
# Stock state rollup (PRD 2.9)
# ---------------------------------------------------------------------------
def compute_stock_state(product_id):
    for lot in db.inventory_lots.values():
        if lot["product_id"] == product_id:
            if lot["grams_on_hand"] > 0 and lot_status(lot) == "AVAILABLE":
                return "IN_STOCK"
    return "OUT_OF_STOCK"


def reconcile_stock(product_id):
    """Update stored stock_state; bump version only if it actually flips."""
    p = db.products.get(product_id)
    if p is None:
        return
    new = compute_stock_state(product_id)
    if p["stock_state"] != new:
        p["stock_state"] = new
        touch(p)


# ---------------------------------------------------------------------------
# Effective allergens (PRD 3.1)
# ---------------------------------------------------------------------------
def effective_allergens(product_id, _seen=None):
    if _seen is None:
        _seen = set()
    if product_id in _seen:
        return set()
    _seen.add(product_id)
    p = db.products.get(product_id)
    if p is None:
        return set()
    if p["kind"] == "SIMPLE":
        return set(p.get("allergen_tags") or [])
    result = set()
    for comp in db.blend_components.values():
        if comp["blend_product_id"] == product_id:
            result |= effective_allergens(comp["component_product_id"], _seen)
    return result


# ---------------------------------------------------------------------------
# Account exposure (PRD 3.5)
# ---------------------------------------------------------------------------
def account_exposures(account_id):
    committed = 0
    projected_extra = 0
    for o in db.customer_orders.values():
        if o["wholesale_account_id"] != account_id:
            continue
        if o["fulfillment_status"] in ("CONFIRMED", "PACKED", "SHIPPED"):
            committed += o.get("held_exposure_cents") or 0
        elif o["fulfillment_status"] == "PRICED":
            projected_extra += o.get("provisional_total_cents") or 0
    projected = committed + projected_extra
    return committed, projected


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def _base(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_product(p):
    out = _base(p)
    out.update({
        "name": p["name"],
        "category": p["category"],
        "kind": p["kind"],
        "unit_price_cents_per_gram": p["unit_price_cents_per_gram"],
        "tare_default_grams": p["tare_default_grams"],
        "allergen_tags": p["allergen_tags"],
        "shelf_life_days": p["shelf_life_days"],
        "status": p["status"],
        "stock_state": compute_stock_state(p["id"]),
    })
    return out


def ser_blend_component(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "blend_product_id": c["blend_product_id"],
        "component_product_id": c["component_product_id"],
        "weight_ratio_bps": c["weight_ratio_bps"],
    }


def ser_lot(lot):
    out = _base(lot)
    out.update({
        "product_id": lot["product_id"],
        "source_batch_id": lot["source_batch_id"],
        "lot_code": lot["lot_code"],
        "grams_received": lot["grams_received"],
        "grams_on_hand": lot["grams_on_hand"],
        "received_at": lot["received_at"],
        "best_by": lot["best_by"],
        "status": lot_status(lot),
    })
    return out


def ser_production_line(pl):
    out = _base(pl)
    out.update({"name": pl["name"]})
    return out


def ser_batch(b):
    out = _base(b)
    out.update({
        "blend_product_id": b["blend_product_id"],
        "production_line_id": b["production_line_id"],
        "target_output_grams": b["target_output_grams"],
        "produced_grams": b["produced_grams"],
        "scheduled_start": b["scheduled_start"],
        "scheduled_end": b["scheduled_end"],
        "status": b["status"],
    })
    return out


def ser_labeling_station(s):
    out = _base(s)
    out.update({"name": s["name"]})
    return out


def ser_tin_run(t):
    out = _base(t)
    out.update({
        "labeling_station_id": t["labeling_station_id"],
        "product_ids": t["product_ids"],
        "allergen_set": t["allergen_set"],
        "scheduled_start": t["scheduled_start"],
        "scheduled_end": t["scheduled_end"],
    })
    return out


def ser_account(a):
    committed, projected = account_exposures(a["id"])
    available = a["credit_limit_cents"] - committed
    out = _base(a)
    out.update({
        "business_name": a["business_name"],
        "tier": a["tier"],
        "credit_limit_cents": a["credit_limit_cents"],
        "committed_exposure_cents": committed,
        "projected_exposure_cents": projected,
        "available_credit_cents": available,
        "status": a["status"],
    })
    return out


def ser_order(o):
    out = _base(o)
    out.update({
        "wholesale_account_id": o["wholesale_account_id"],
        "fulfillment_status": o["fulfillment_status"],
        "allergen_ack": o["allergen_ack"],
        "total_net_grams": o["total_net_grams"],
        "provisional_total_cents": o["provisional_total_cents"],
        "final_total_cents": o["final_total_cents"],
        "held_exposure_cents": o["held_exposure_cents"],
    })
    return out


def ser_order_line(l):
    out = _base(l)
    out.update({
        "order_id": l["order_id"],
        "product_id": l["product_id"],
        "requested_grams": l["requested_grams"],
        "gross_grams": l["gross_grams"],
        "tare_grams": l["tare_grams"],
        "net_grams": l["net_grams"],
        "allocated_lot_id": l["allocated_lot_id"],
        "provisional_line_cents": l["provisional_line_cents"],
        "final_line_cents": l["final_line_cents"],
    })
    return out
