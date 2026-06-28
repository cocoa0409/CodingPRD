"""Serializers: internal record dicts -> API output dicts.

Datetimes are emitted as ISO 8601 UTC with three fractional digits (PRD 2.4).
Derived fields on ContractorAccount are recomputed from the underlying
invoices/orders/ledger at read time (PRD 2.9).
"""
import db
from response import iso_millis


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": iso_millis(rec["created_at"]),
        "updated_at": iso_millis(rec["updated_at"]),
        "version": rec["version"],
    }


def vendor(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "drop_ship_capable": rec["drop_ship_capable"],
        "coop_rebate_pct": rec["coop_rebate_pct"],
        "status": rec["status"],
    })
    return out


def product(rec):
    out = _common(rec)
    out.update({
        "sku": rec["sku"],
        "vendor_id": rec["vendor_id"],
        "sell_mode": rec["sell_mode"],
        "aisle": rec["aisle"],
        "bin": rec["bin"],
        "list_price_cents": rec["list_price_cents"],
        "price_per_foot_cents": rec["price_per_foot_cents"],
        "cut_fee_cents": rec["cut_fee_cents"],
        "on_hand": rec["on_hand"],
        "reorder_point": rec["reorder_point"],
        "reorder_qty": rec["reorder_qty"],
        "reorder_needed": rec["reorder_needed"],
        "status": rec["status"],
    })
    return out


# --- ContractorAccount derived-field recomputation (PRD 2.9) ---

def account_balance_cents(account_id):
    """Settled balance = sum of amount_cents over ISSUED invoices on account."""
    return sum(
        inv["amount_cents"]
        for inv in db.invoices.values()
        if inv["contractor_account_id"] == account_id and inv["status"] == "ISSUED"
    )


def account_committed_cents(account_id):
    """balance_cents + sum of total_cents over PLACED & UNBILLED orders."""
    bal = account_balance_cents(account_id)
    placed = sum(
        o["total_cents"]
        for o in db.sales_orders.values()
        if o["contractor_account_id"] == account_id
        and o["fulfillment_status"] == "PLACED"
        and o["payment_status"] == "UNBILLED"
    )
    return bal + placed


def account_loyalty_points(account_id):
    """Sum of delta_points across the account's ledger entries."""
    return sum(
        e["delta_points"]
        for e in db.loyalty_ledger.values()
        if e["contractor_account_id"] == account_id
    )


def contractor_account(rec):
    out = _common(rec)
    out.update({
        "business_name": rec["business_name"],
        "credit_limit_cents": rec["credit_limit_cents"],
        "net_terms_days": rec["net_terms_days"],
        "balance_cents": account_balance_cents(rec["id"]),
        "committed_cents": account_committed_cents(rec["id"]),
        "loyalty_points": account_loyalty_points(rec["id"]),
        "status": rec["status"],
    })
    return out


def sales_order(rec):
    out = _common(rec)
    out.update({
        "contractor_account_id": rec["contractor_account_id"],
        "fulfillment_status": rec["fulfillment_status"],
        "payment_status": rec["payment_status"],
        "pricing_mode": rec["pricing_mode"],
        "subtotal_cents": rec["subtotal_cents"],
        "loyalty_discount_cents": rec["loyalty_discount_cents"],
        "total_cents": rec["total_cents"],
        "points_accrued": rec["points_accrued"],
    })
    return out


def order_line(rec):
    out = _common(rec)
    out.update({
        "sales_order_id": rec["sales_order_id"],
        "product_id": rec["product_id"],
        "qty": rec["qty"],
        "cut_count": rec["cut_count"],
        "line_total_cents": rec["line_total_cents"],
        "status": rec["status"],
    })
    return out


def invoice(rec):
    out = _common(rec)
    out.update({
        "sales_order_id": rec["sales_order_id"],
        "contractor_account_id": rec["contractor_account_id"],
        "amount_cents": rec["amount_cents"],
        "due_at": iso_millis(rec["due_at"]),
        "status": rec["status"],
    })
    return out


def rental_asset(rec):
    out = _common(rec)
    out.update({
        "asset_tag": rec["asset_tag"],
        "category": rec["category"],
        "daily_rate_cents": rec["daily_rate_cents"],
        "deposit_cents": rec["deposit_cents"],
        "status": rec["status"],
    })
    return out


def rental_agreement(rec):
    out = _common(rec)
    out.update({
        "rental_asset_id": rec["rental_asset_id"],
        "contractor_account_id": rec["contractor_account_id"],
        "start_at": iso_millis(rec["start_at"]),
        "due_at": iso_millis(rec["due_at"]),
        "returned_at": iso_millis(rec["returned_at"]),
        "rental_charge_cents": rec["rental_charge_cents"],
        "status": rec["status"],
    })
    return out


def service_station(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "buffer_minutes": rec["buffer_minutes"],
        "status": rec["status"],
    })
    return out


def service_ticket(rec):
    out = _common(rec)
    out.update({
        "service_station_id": rec["service_station_id"],
        "contractor_account_id": rec["contractor_account_id"],
        "service_type": rec["service_type"],
        "cylinder_certified": rec["cylinder_certified"],
        "scheduled_start": iso_millis(rec["scheduled_start"]),
        "scheduled_end": iso_millis(rec["scheduled_end"]),
        "fee_cents": rec["fee_cents"],
        "status": rec["status"],
    })
    return out


def special_order(rec):
    out = _common(rec)
    out.update({
        "vendor_id": rec["vendor_id"],
        "contractor_account_id": rec["contractor_account_id"],
        "description": rec["description"],
        "quoted_unit_cents": rec["quoted_unit_cents"],
        "qty": rec["qty"],
        "revision_count": rec["revision_count"],
        "confirmed_total_cents": rec["confirmed_total_cents"],
        "status": rec["status"],
    })
    return out


def purchase_order(rec):
    out = _common(rec)
    out.update({
        "vendor_id": rec["vendor_id"],
        "lines": [dict(l) for l in rec["lines"]],
        "gross_cents": rec["gross_cents"],
        "coop_rebate_cents": rec["coop_rebate_cents"],
        "net_cost_cents": rec["net_cost_cents"],
        "status": rec["status"],
    })
    return out


def loyalty_ledger(rec):
    # Immutable audit record: only id + created_at (PRD 2.4), plus its
    # business fields.
    return {
        "id": rec["id"],
        "created_at": iso_millis(rec["created_at"]),
        "contractor_account_id": rec["contractor_account_id"],
        "delta_points": rec["delta_points"],
        "reason": rec["reason"],
        "sales_order_id": rec["sales_order_id"],
    }
