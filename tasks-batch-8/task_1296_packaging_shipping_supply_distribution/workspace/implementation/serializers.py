"""Entity -> wire dict serializers. Computed fields are derived on read."""
import db
from util import fmt_ts, fmt_date_as_ts

RECEIVABLE_ORDER_STATUSES = {"STOCK_RESERVED", "PARTIALLY_BACKORDERED", "CUSTOM_PRODUCTION", "SHIPPED"}


def account_open_receivable(account_id):
    """calc_open_receivable: recomputed in full on every read (cannot drift)."""
    total = 0
    for o in db.orders.values():
        if (o["account_id"] == account_id
                and o["invoice_status"] == "OPEN"
                and o["status"] in RECEIVABLE_ORDER_STATUSES):
            total += o["grand_total_cents"]
    return total


def ser_common(e):
    return {
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_account(a):
    out = {
        "id": a["id"],
        "company_name": a["company_name"],
        "account_type": a["account_type"],
        "status": a["status"],
        "credit_limit_cents": a["credit_limit_cents"],
        "po_required": a["po_required"],
        "default_warehouse_code": a["default_warehouse_code"],
        "open_receivable_cents": account_open_receivable(a["id"]),
    }
    out.update(ser_common(a))
    return out


def ser_product(p):
    out = {
        "id": p["id"],
        "sku": p["sku"],
        "name": p["name"],
        "category": p["category"],
        "base_price_cents": p["base_price_cents"],
        "uom": p["uom"],
        "case_qty": p["case_qty"],
        "pallet_qty": p["pallet_qty"],
        "weight_lbs_per_unit": p["weight_lbs_per_unit"],
        "density_pcf": p["density_pcf"],
        "oversize": p["oversize"],
        "is_custom_print": p["is_custom_print"],
        "lead_time_days": p["lead_time_days"],
        "ship_method": p["ship_method"],
        "status": p["status"],
    }
    out.update(ser_common(p))
    return out


def ser_warehouse(w):
    out = {
        "id": w["id"],
        "code": w["code"],
        "name": w["name"],
        "zone": w["zone"],
        "ship_cutoff_time": w["ship_cutoff_time"],
        "timezone": w["timezone"],
        "oversize_capable": w["oversize_capable"],
        "press_count": w["press_count"],
        "status": w["status"],
    }
    out.update(ser_common(w))
    return out


def ser_inventory(inv):
    out = {
        "id": inv["id"],
        "product_id": inv["product_id"],
        "warehouse_id": inv["warehouse_id"],
        "on_hand_qty": inv["on_hand_qty"],
        "reserved_qty": inv["reserved_qty"],
        "available_qty": inv["on_hand_qty"] - inv["reserved_qty"],
        "backorderable": inv["backorderable"],
        "reorder_point_qty": inv["reorder_point_qty"],
    }
    out.update(ser_common(inv))
    return out


def ser_quantity_break(b):
    # QuantityBreak carries only id + created_at (no updated_at / version).
    return {
        "id": b["id"],
        "product_id": b["product_id"],
        "min_qty": b["min_qty"],
        "unit_price_cents": b["unit_price_cents"],
        "sort_seq": b["sort_seq"],
        "effective_from": fmt_ts(b["effective_from"]),
        "effective_to": fmt_ts(b["effective_to"]),
        "created_at": fmt_ts(b["created_at"]),
    }


def ser_order(o):
    out = {
        "id": o["id"],
        "account_id": o["account_id"],
        "status": o["status"],
        "ship_zone": o["ship_zone"],
        "po_number": o["po_number"],
        "subtotal_cents": o["subtotal_cents"],
        "pallet_discount_cents": o["pallet_discount_cents"],
        "oversize_surcharge_cents": o["oversize_surcharge_cents"],
        "freight_estimate_cents": o["freight_estimate_cents"],
        "grand_total_cents": o["grand_total_cents"],
        "invoice_status": o["invoice_status"],
        "submitted_at": fmt_ts(o["submitted_at"]),
        "promised_ship_date": fmt_date_as_ts(o["promised_ship_date"]),
    }
    out.update(ser_common(o))
    return out


def ser_order_line(l):
    out = {
        "id": l["id"],
        "order_id": l["order_id"],
        "product_id": l["product_id"],
        "qty": l["qty"],
        "requested_warehouse_code": l["requested_warehouse_code"],
        "print_artwork_ref": l["print_artwork_ref"],
        "over_under_tolerance_pct": l["over_under_tolerance_pct"],
        "unit_price_cents": l["unit_price_cents"],
        "freight_class": l["freight_class"],
        "allocated_warehouse_id": l["allocated_warehouse_id"],
        "status": l["status"],
        "shipped_qty": l["shipped_qty"],
    }
    out.update(ser_common(l))
    return out


def ser_job(j):
    out = {
        "id": j["id"],
        "order_line_id": j["order_line_id"],
        "warehouse_id": j["warehouse_id"],
        "status": j["status"],
        "actual_qty": j["actual_qty"],
        "receive_note": j["receive_note"],
        "started_at": fmt_ts(j["started_at"]),
        "occupied_until": fmt_ts(j["occupied_until"]),
    }
    out.update(ser_common(j))
    return out


def ser_return(r):
    out = {
        "id": r["id"],
        "order_id": r["order_id"],
        "return_type": r["return_type"],
        "status": r["status"],
        "reason_code": r["reason_code"],
        "restock_fee_cents": r["restock_fee_cents"],
        "refund_cents": r["refund_cents"],
        "requested_at": fmt_ts(r["requested_at"]),
    }
    out.update(ser_common(r))
    return out


def ser_return_line(rl):
    out = {
        "id": rl["id"],
        "return_id": rl["return_id"],
        "order_line_id": rl["order_line_id"],
        "qty": rl["qty"],
    }
    out.update(ser_common(rl))
    return out


def ser_notification(n):
    out = {
        "id": n["id"],
        "account_id": n["account_id"],
        "product_id": n["product_id"],
        "status": n["status"],
        "notified_at": fmt_ts(n["notified_at"]),
    }
    out.update(ser_common(n))
    return out
