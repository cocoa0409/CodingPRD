"""Serializers: internal records -> API resource views (PRD §2.5 fields)."""
import core
import domain


def depot_view(d):
    reserved = domain.depot_reserved_pallets(d["id"])
    return {
        "id": d["id"],
        "name": d["name"],
        "freezer_capacity_pallets": d["freezer_capacity_pallets"],
        "freezer_reserved_pallets": reserved,
        "freezer_free_pallets": d["freezer_capacity_pallets"] - reserved,
        "posture": domain.depot_posture(d),
        "ops_run_index": d["ops_run_index"],
        "version": d["version"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
    }


def customer_view(c):
    return {
        "id": c["id"],
        "account_name": c["account_name"],
        "kind": c["kind"],
        "tier": c["tier"],
        "credit_terms": c["credit_terms"],
        "credit_limit_cents": c["credit_limit_cents"],
        "credit_balance_cents": c["credit_balance_cents"],
        "outstanding_exposure_cents": domain.settled_exposure(c["id"]),
        "standing": domain.customer_standing(c["id"]),
        "version": c["version"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
    }


def cert_view(c):
    return {
        "id": c["id"],
        "customer_id": c["customer_id"],
        "handler_name": c["handler_name"],
        "certificate_number": c["certificate_number"],
        "max_dry_ice_lbs": c["max_dry_ice_lbs"],
        "expires_at": core.fmt_dt(c["expires_at"]),
        "status": c["status"],
        "version": c["version"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
    }


def book_view(b):
    return {
        "id": b["id"],
        "scope_label": b["scope_label"],
        "effective_from": core.fmt_dt(b["effective_from"]),
        "status": b["status"],
        "lines": b["lines"],
        "pallet_deposit_cents": b["pallet_deposit_cents"],
        "delivery_fee_cents": b["delivery_fee_cents"],
        "free_delivery_threshold_cents": b["free_delivery_threshold_cents"],
        "volume_discount_tiers": b["volume_discount_tiers"],
        "surge_surcharge_bps": b["surge_surcharge_bps"],
        "version": b["version"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
    }


def window_view(w):
    return {
        "id": w["id"],
        "depot_id": w["depot_id"],
        "start_date": w["start_date"].isoformat(),
        "end_date": w["end_date"].isoformat(),
        "admission_policy": w["admission_policy"],
        "daily_pallet_cap": w["daily_pallet_cap"],
        "status": domain.window_status(w),
        "version": w["version"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
    }


def route_view(r):
    return {
        "id": r["id"],
        "customer_id": r["customer_id"],
        "depot_id": r["depot_id"],
        "weekday": r["weekday"],
        "window_start": r["window_start"],
        "window_end": r["window_end"],
        "standing_lines": r["standing_lines"],
        "status": r["status"],
        "last_generated_date": (r["last_generated_date"].isoformat()
                                if r["last_generated_date"] else None),
        "version": r["version"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def order_view(o):
    pallets, dry = domain.order_measures(o["id"])
    return {
        "id": o["id"],
        "customer_id": o["customer_id"],
        "depot_id": o["depot_id"],
        "recurring_route_id": o["recurring_route_id"],
        "channel": o["channel"],
        "event_date": o["event_date"].isoformat(),
        "window_start": o["window_start"],
        "window_end": o["window_end"],
        "fulfillment_status": o["fulfillment_status"],
        "billing_status": o["billing_status"],
        "delivery_slot_id": o["delivery_slot_id"],
        "dispatch_run_id": o["dispatch_run_id"],
        "invoice_id": o["invoice_id"],
        "price_book_id": o["price_book_id"],
        "price_book_version": o["price_book_version"],
        "pricing_mode": o["pricing_mode"],
        "pallets_required": pallets,
        "dry_ice_lbs": dry,
        "merchandise_subtotal_cents": o["merchandise_subtotal_cents"],
        "discount_cents": o["discount_cents"],
        "delivery_fee_cents": o["delivery_fee_cents"],
        "surcharge_cents": o["surcharge_cents"],
        "deposit_cents": o["deposit_cents"],
        "total_cents": o["total_cents"],
        "quoted_at": o["quoted_at"],
        "confirmed_at": o["confirmed_at"],
        "fulfilled_at": o["fulfilled_at"],
        "version": o["version"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
    }


def line_view(l):
    return {
        "id": l["id"],
        "order_id": l["order_id"],
        "product_form": l["product_form"],
        "packaging": l["packaging"],
        "quantity_units": l["quantity_units"],
        "unit_weight_lbs": l["unit_weight_lbs"],
        "unit_price_cents": l["unit_price_cents"],
        "line_total_cents": l["line_total_cents"],
        "version": l["version"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
    }


def slot_view(s):
    return {
        "id": s["id"],
        "depot_id": s["depot_id"],
        "date": s["date"].isoformat(),
        "window_start": s["window_start"],
        "window_end": s["window_end"],
        "capacity_pallets": s["capacity_pallets"],
        "reserved_pallets": domain.slot_reserved_pallets(s["id"]),
        "status": domain.slot_status(s),
        "version": s["version"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
    }


def hold_view(h):
    return {
        "id": h["id"],
        "depot_id": h["depot_id"],
        "order_id": h["order_id"],
        "zone": h["zone"],
        "pallets_required": h["pallets_required"],
        "interval_start": core.fmt_dt(h["interval_start"]),
        "interval_end": core.fmt_dt(h["interval_end"]),
        "status": h["status"],
        "version": h["version"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
    }


def run_view(r):
    pallets, dry = domain.run_assignment_totals(r["id"])
    return {
        "id": r["id"],
        "depot_id": r["depot_id"],
        "run_date": r["run_date"].isoformat(),
        "vehicle_label": r["vehicle_label"],
        "max_pallets": r["max_pallets"],
        "ventilated_dry_ice_cap_lbs": r["ventilated_dry_ice_cap_lbs"],
        "assigned_pallets": pallets,
        "assigned_dry_ice_lbs": dry,
        "status": r["status"],
        "version": r["version"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def invoice_view(i):
    return {
        "id": i["id"],
        "customer_id": i["customer_id"],
        "period_start": i["period_start"].isoformat(),
        "period_end": i["period_end"].isoformat(),
        "status": i["status"],
        "merchandise_subtotal_cents": i["merchandise_subtotal_cents"],
        "discount_cents": i["discount_cents"],
        "delivery_fee_cents": i["delivery_fee_cents"],
        "surcharge_cents": i["surcharge_cents"],
        "deposit_cents": i["deposit_cents"],
        "total_cents": i["total_cents"],
        "amount_paid_cents": i["amount_paid_cents"],
        "balance_due_cents": i["balance_due_cents"],
        "due_date": i["due_date"].isoformat() if i["due_date"] else None,
        "issued_by_user_id": i["issued_by_user_id"],
        "voided_by_user_id": i["voided_by_user_id"],
        "version": i["version"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
    }


def payment_view(p):
    return {
        "id": p["id"],
        "customer_id": p["customer_id"],
        "amount_cents": p["amount_cents"],
        "method": p["method"],
        "received_at": p["received_at"],
        "applied_cents": p["applied_cents"],
        "overpayment_cents": p["overpayment_cents"],
        "allocations": p["allocations"],
        "created_at": p["created_at"],
    }


def entry_view(e):
    return {
        "id": e["id"],
        "order_id": e["order_id"],
        "depot_id": e["depot_id"],
        "requested_pallets": e["requested_pallets"],
        "status": e["status"],
        "queued_at": e["queued_at"],
        "promoted_at": e["promoted_at"],
        "created_at": e["created_at"],
    }
