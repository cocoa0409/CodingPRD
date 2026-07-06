"""Entity -> JSON-ready dict serializers.

Common fields: id, created_at, updated_at, version (WalletLedger carries only
id + created_at). Member money/loyalty and Order/BulkBin computed fields are
derived here at read time so responses always reflect current state.
"""
import store
from store import fmt_dt


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def member_out(m):
    wallet = liab = pts = 0
    for e in store.DB["wallet_ledger"].values():
        if e["member_id"] == m["id"]:
            wallet += e["wallet_delta_cents"]
            liab += e["liability_delta_cents"]
            pts += e["points_delta"]
    d = _common(m)
    d.update({
        "email": m["email"],
        "full_name": m["full_name"],
        "membership_tier": m["membership_tier"],
        "wallet_balance_cents": wallet,
        "deposit_liability_cents": liab,
        "loyalty_points_balance": pts,
    })
    return d


def product_out(p):
    d = _common(p)
    d.update({
        "name": p["name"],
        "category": p["category"],
        "unit_price_cents_per_100g": p["unit_price_cents_per_100g"],
        "bulk_tier_threshold_g": p["bulk_tier_threshold_g"],
        "bulk_tier_price_cents_per_100g": p["bulk_tier_price_cents_per_100g"],
        "allergen_tags": list(p["allergen_tags"]),
        "taxable": p["taxable"],
    })
    return d


def station_out(s):
    d = _common(s)
    d.update({"name": s["name"], "station_status": s["station_status"]})
    return d


def bin_out(b):
    d = _common(b)
    d.update({
        "product_id": b["product_id"],
        "station_id": b["station_id"],
        "capacity_g": b["capacity_g"],
        "reorder_threshold_g": b["reorder_threshold_g"],
        "on_hand_g": b["on_hand_g"],
        "last_recount_g": b["last_recount_g"],
        "last_recount_at": fmt_dt(b["last_recount_at"]),
        "last_shrink_g": b["last_shrink_g"],
        "status": b["status"],
    })
    return d


def container_out(c):
    d = _common(c)
    d.update({
        "member_id": c["member_id"],
        "container_type": c["container_type"],
        "declared_tare_g": c["declared_tare_g"],
        "measured_tare_g": c["measured_tare_g"],
        "deposit_cents": c["deposit_cents"],
        "allergen_hold": c["allergen_hold"],
        "status": c["status"],
    })
    return d


def order_out(o):
    d = _common(o)
    d.update({
        "member_id": o["member_id"],
        "station_id": o["station_id"],
        "fulfillment_channel": o["fulfillment_channel"],
        "fill_window_start_at": fmt_dt(o["fill_window_start_at"]),
        "fill_window_end_at": fmt_dt(o["fill_window_end_at"]),
        "fulfillment_status": o["fulfillment_status"],
        "payment_status": o["payment_status"],
        "subtotal_cents": o["subtotal_cents"],
        "discount_cents": o["discount_cents"],
        "deposit_total_cents": o["deposit_total_cents"],
        "tax_cents": o["tax_cents"],
        "total_cents": o["total_cents"],
        "loyalty_points_earned": o["loyalty_points_earned"],
    })
    return d


def line_out(l):
    d = _common(l)
    d.update({
        "order_id": l["order_id"],
        "product_id": l["product_id"],
        "container_id": l["container_id"],
        "bin_id": l["bin_id"],
        "declared_tare_g": l["declared_tare_g"],
        "estimated_gross_g": l["estimated_gross_g"],
        "gross_weight_g": l["gross_weight_g"],
        "net_weight_g": l["net_weight_g"],
        "line_price_cents": l["line_price_cents"],
        "pricing_stage": l["pricing_stage"],
    })
    return d


def restock_out(t):
    d = _common(t)
    d.update({
        "bin_id": t["bin_id"],
        "requested_fill_g": t["requested_fill_g"],
        "restocked_g": t["restocked_g"],
        "status": t["status"],
    })
    return d


def subscription_out(s):
    d = _common(s)
    d.update({
        "member_id": s["member_id"],
        "product_id": s["product_id"],
        "station_id": s["station_id"],
        "target_net_g": s["target_net_g"],
        "interval_days": s["interval_days"],
        "next_run_at": fmt_dt(s["next_run_at"]),
        "last_run_order_id": s["last_run_order_id"],
        "status": s["status"],
    })
    return d


def vehicle_out(v):
    d = _common(v)
    d.update({"plate": v["plate"], "capacity_orders": v["capacity_orders"]})
    return d


def delivery_out(dl):
    d = _common(dl)
    d.update({
        "order_id": dl["order_id"],
        "vehicle_id": dl["vehicle_id"],
        "member_id": dl["member_id"],
        "window_start_at": fmt_dt(dl["window_start_at"]),
        "window_end_at": fmt_dt(dl["window_end_at"]),
        "status": dl["status"],
    })
    return d


def ledger_out(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "member_id": e["member_id"],
        "entry_type": e["entry_type"],
        "wallet_delta_cents": e["wallet_delta_cents"],
        "liability_delta_cents": e["liability_delta_cents"],
        "points_delta": e["points_delta"],
        "source_kind": e["source_kind"],
        "source_id": e["source_id"],
        "memo": e["memo"],
    }
