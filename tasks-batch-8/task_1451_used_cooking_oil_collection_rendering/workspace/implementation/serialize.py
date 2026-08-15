"""Entity serializers: public wire shape = scaffold fields + common fields.

Customer.missed_pickup_count and Customer.rebate_balance_cents are derived
aggregates computed live on read (PRD 2.10, 3.1); every other field is stored.
"""

import calc


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def customer(rec):
    out = {
        "name": rec["name"],
        "site_address": rec["site_address"],
        "site_max_container_gal": rec["site_max_container_gal"],
        "status": rec["status"],
        "missed_pickup_count": calc.missed_pickup_count(rec["id"]),
        "rebate_balance_cents": calc.rebate_balance_cents(rec["id"]),
    }
    out.update(_common(rec))
    return out


def contract(rec):
    out = {
        "customer_id": rec["customer_id"],
        "pricing_mode": rec["pricing_mode"],
        "index_code": rec["index_code"],
        "floor_cents_per_gal": rec["floor_cents_per_gal"],
        "cap_cents_per_gal": rec["cap_cents_per_gal"],
        "service_fee_cents": rec["service_fee_cents"],
        "overage_threshold_gal": rec["overage_threshold_gal"],
        "overage_rate_cents_per_gal": rec["overage_rate_cents_per_gal"],
        "term_start": rec["term_start"],
        "term_end": rec["term_end"],
        "status": rec["status"],
        "status_before_renewal": rec["status_before_renewal"],
        "offered_term_start": rec["offered_term_start"],
        "offered_term_end": rec["offered_term_end"],
        "activated_at": rec["activated_at"],
        "competitor_name": rec["competitor_name"],
        "poach_offer_cents_per_gal": rec["poach_offer_cents_per_gal"],
        "termination_reason": rec["termination_reason"],
    }
    out.update(_common(rec))
    return out


def container(rec):
    out = {
        "customer_id": rec["customer_id"],
        "capacity_gallons": rec["capacity_gallons"],
        "est_fill_rate_gal_per_week": rec["est_fill_rate_gal_per_week"],
        "lock_code": rec["lock_code"],
        "status": rec["status"],
        "last_completed_pickup_date": rec["last_completed_pickup_date"],
    }
    out.update(_common(rec))
    return out


def truck(rec):
    out = {
        "plate": rec["plate"],
        "tank_capacity_gallons": rec["tank_capacity_gallons"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def manifest(rec):
    out = {
        "truck_id": rec["truck_id"],
        "driver_ref": rec["driver_ref"],
        "service_date": rec["service_date"],
        "status": rec["status"],
        "projected_fill_gallons": rec["projected_fill_gallons"],
        "start_level_gallons": rec["start_level_gallons"],
        "end_level_gallons": rec["end_level_gallons"],
        "spill_loss_gallons": rec["spill_loss_gallons"],
        "collected_gallons": calc.collected_gallons(rec["id"]),
    }
    out.update(_common(rec))
    return out


def visit(rec):
    out = {
        "manifest_id": rec["manifest_id"],
        "container_id": rec["container_id"],
        "scheduled_date": rec["scheduled_date"],
        "status": rec["status"],
        "pump_gallons": rec["pump_gallons"],
        "field_moisture_pct": rec["field_moisture_pct"],
        "net_gallons_provisional": rec["net_gallons_provisional"],
        "retry_count": rec["retry_count"],
        "failure_reason": rec["failure_reason"],
        "void_reason": rec["void_reason"],
        "skipped_at": rec["skipped_at"],
        "completed_at": rec["completed_at"],
    }
    out.update(_common(rec))
    return out


def sample(rec):
    out = {
        "pickup_visit_id": rec["pickup_visit_id"],
        "status": rec["status"],
        "lab_moisture_pct": rec["lab_moisture_pct"],
        "lab_impurity_pct": rec["lab_impurity_pct"],
        "grade": rec["grade"],
        "dispute_note": rec["dispute_note"],
    }
    out.update(_common(rec))
    return out


def quote(rec):
    out = {
        "index_code": rec["index_code"],
        "week_start": rec["week_start"],
        "price_cents_per_gal": rec["price_cents_per_gal"],
        "status": rec["status"],
        "published_at": rec["published_at"],
    }
    out.update(_common(rec))
    return out


def settlement(rec):
    out = {
        "customer_id": rec["customer_id"],
        "period_start": rec["period_start"],
        "period_end": rec["period_end"],
        "status": rec["status"],
        "provisional_total_cents": rec["provisional_total_cents"],
        "final_total_cents": rec["final_total_cents"],
        "paid_at": rec["paid_at"],
    }
    out.update(_common(rec))
    return out


def line(rec):
    out = {
        "settlement_id": rec["settlement_id"],
        "pickup_visit_id": rec["pickup_visit_id"],
        "variant": rec["variant"],
        "pricing_mode": rec["pricing_mode"],
        "gallons_billed": rec["gallons_billed"],
        "rate_cents_per_gal": rec["rate_cents_per_gal"],
        "line_amount_cents": rec["line_amount_cents"],
    }
    out.update(_common(rec))
    return out


def complaint(rec):
    out = {
        "customer_id": rec["customer_id"],
        "pickup_visit_id": rec["pickup_visit_id"],
        "category": rec["category"],
        "severity": rec["severity"],
        "note": rec["note"],
        "status": rec["status"],
        "resolved_at": rec["resolved_at"],
        "reopen_count": rec["reopen_count"],
        "resolution_note": rec["resolution_note"],
    }
    out.update(_common(rec))
    return out


def theft(rec):
    out = {
        "container_id": rec["container_id"],
        "evidence_note": rec["evidence_note"],
        "status": rec["status"],
        "resolution_note": rec["resolution_note"],
    }
    out.update(_common(rec))
    return out


def batch(rec):
    out = {
        "manifest_id": rec["manifest_id"],
        "input_gallons": rec["input_gallons"],
        "weighted_moisture_pct": rec["weighted_moisture_pct"],
        "est_yield_gallons": rec["est_yield_gallons"],
        "actual_output_gallons": rec["actual_output_gallons"],
        "yield_rate": rec["yield_rate"],
        "sale_price_cents_per_gal": rec["sale_price_cents_per_gal"],
        "sale_revenue_cents": rec["sale_revenue_cents"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out
