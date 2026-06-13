"""Entity serializers. Computed fields are derived at read time.

Internal-only keys (prefixed _) are stripped from output.
"""
import db
from services import calc
from services.common import public


def plan_out(p):
    return {
        "id": p["id"],
        "tier": p["tier"],
        "trash_cart_size_gallons": p["trash_cart_size_gallons"],
        "recycling_cart_size_gallons": p["recycling_cart_size_gallons"],
        "monthly_base_cents": p["monthly_base_cents"],
        "extra_cart_monthly_cents": p["extra_cart_monthly_cents"],
        "extra_pickup_base_cents": p["extra_pickup_base_cents"],
        "bulk_item_cents": p["bulk_item_cents"],
        "archived": p["archived"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def account_out(a):
    return {
        "id": a["id"],
        "plan_id": a["plan_id"],
        "zone_id": a["zone_id"],
        "service_address": a["service_address"],
        "holder_name": a["holder_name"],
        "status": a["status"],
        "billing_status": a["billing_status"],
        "autopay_enabled": a["autopay_enabled"],
        "stored_payment_token": a["stored_payment_token"],
        "account_balance_cents": calc.account_balance_cents(a["id"]),
        "credit_balance_cents": calc.credit_balance_cents(a["id"]),
        "service_start_date": a["service_start_date"],
        "transferred_from_account_id": a["transferred_from_account_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def zone_out(z):
    return {
        "id": z["id"],
        "name": z["name"],
        "base_pickup_weekday": z["base_pickup_weekday"],
        "recycling_week_parity": z["recycling_week_parity"],
        "created_at": z["created_at"],
        "updated_at": z["updated_at"],
        "version": z["version"],
    }


def holiday_out(h):
    return {
        "id": h["id"],
        "zone_id": h["zone_id"],
        "holiday_date": h["holiday_date"],
        "shift_direction": h["shift_direction"],
        "created_at": h["created_at"],
    }


def cart_out(c):
    return {
        "id": c["id"],
        "account_id": c["account_id"],
        "cart_type": c["cart_type"],
        "size_gallons": c["size_gallons"],
        "is_extra": c["is_extra"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def schedule_out(s):
    return {
        "id": s["id"],
        "account_id": s["account_id"],
        "service_date": s["service_date"],
        "stream": s["stream"],
        "effective_pickup_date": s["effective_pickup_date"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def event_out(e):
    return {
        "id": e["id"],
        "schedule_id": e["schedule_id"],
        "outcome": e["outcome"],
        "reported_at": e["reported_at"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def extra_out(r):
    return {
        "id": r["id"],
        "account_id": r["account_id"],
        "requested_date": r["requested_date"],
        "bulk_item_count": r["bulk_item_count"],
        "charge_cents": r["charge_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def invoice_out(inv):
    return {
        "id": inv["id"],
        "account_id": inv["account_id"],
        "period_start": inv["period_start"],
        "period_end": inv["period_end"],
        "gross_amount_cents": inv["gross_amount_cents"],
        "credit_applied_cents": inv["credit_applied_cents"],
        "amount_due_cents": inv["amount_due_cents"],
        "due_date": inv["due_date"],
        "status": inv["status"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


def payment_out(p):
    return {
        "id": p["id"],
        "invoice_id": p["invoice_id"],
        "amount_cents": p["amount_cents"],
        "method": p["method"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def credit_out(c):
    return {
        "id": c["id"],
        "account_id": c["account_id"],
        "pickup_event_id": c["pickup_event_id"],
        "amount_cents": c["amount_cents"],
        "applied_invoice_id": c["applied_invoice_id"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def notice_out(n):
    return {
        "id": n["id"],
        "account_id": n["account_id"],
        "pickup_event_id": n["pickup_event_id"],
        "severity": n["severity"],
        "fee_cents": n["fee_cents"],
        "status": n["status"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }
