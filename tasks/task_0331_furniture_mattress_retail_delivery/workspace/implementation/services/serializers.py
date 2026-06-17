"""Serializers: project internal records into the public JSON field set.

Internal-only bookkeeping keys (prefixed with '_') are stripped. Each serializer
lists the exact field order/shape the PRD entity model defines so the response
never leaks internal state.
"""


def _public(record):
    """Drop internal keys (those starting with '_')."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def customer(rec):
    return {
        "id": rec["id"],
        "full_name": rec["full_name"],
        "email": rec["email"],
        "credit_score": rec["credit_score"],
        "monthly_income_cents": rec["monthly_income_cents"],
        "existing_monthly_obligations_cents": rec["existing_monthly_obligations_cents"],
        "open_financing_count": rec["open_financing_count"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def product(rec):
    return {
        "id": rec["id"],
        "sku": rec["sku"],
        "name": rec["name"],
        "category": rec["category"],
        "base_price_cents": rec["base_price_cents"],
        "available_fabrics": rec["available_fabrics"],
        "available_sizes": rec["available_sizes"],
        "is_special_order": rec["is_special_order"],
        "lead_days": rec["lead_days"],
        "protection_eligible": rec["protection_eligible"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def order(rec):
    return {
        "id": rec["id"],
        "customer_id": rec["customer_id"],
        "sales_associate_user_id": rec["sales_associate_user_id"],
        "payment_status": rec["payment_status"],
        "fulfillment_status": rec["fulfillment_status"],
        "merchandise_subtotal_cents": rec["merchandise_subtotal_cents"],
        "service_total_cents": rec["service_total_cents"],
        "order_total_cents": rec["order_total_cents"],
        "amount_refunded_cents": rec["amount_refunded_cents"],
        "delivery_tier": rec["delivery_tier"],
        "earliest_schedulable_date": rec["earliest_schedulable_date"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def order_line(rec):
    return {
        "id": rec["id"],
        "order_id": rec["order_id"],
        "product_id": rec["product_id"],
        "fabric_code": rec["fabric_code"],
        "size_code": rec["size_code"],
        "quantity": rec["quantity"],
        "add_assembly": rec["add_assembly"],
        "add_haul_away": rec["add_haul_away"],
        "unit_config_price_cents": rec["unit_config_price_cents"],
        "line_total_cents": rec["line_total_cents"],
        "addon_fee_cents": rec["addon_fee_cents"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def financing_plan(rec):
    return {
        "id": rec["id"],
        "order_id": rec["order_id"],
        "customer_id": rec["customer_id"],
        "plan_type": rec["plan_type"],
        "term_months": rec["term_months"],
        "financed_principal_cents": rec["financed_principal_cents"],
        "monthly_payment_cents": rec["monthly_payment_cents"],
        "total_of_payments_cents": rec["total_of_payments_cents"],
        "paid_to_date_cents": rec["paid_to_date_cents"],
        "payoff_balance_cents": rec["payoff_balance_cents"],
        "payments_made_count": rec["payments_made_count"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def payment(rec):
    # Payment is immutable: only id + created_at common fields (PRD §2.4).
    return {
        "id": rec["id"],
        "financing_plan_id": rec["financing_plan_id"],
        "amount_cents": rec["amount_cents"],
        "applied_period_index": rec["applied_period_index"],
        "created_at": rec["created_at"],
    }


def delivery_route(rec):
    return {
        "id": rec["id"],
        "region_code": rec["region_code"],
        "service_date": rec["service_date"],
        "shift_start_minute": rec["shift_start_minute"],
        "shift_end_minute": rec["shift_end_minute"],
        "capacity_units": rec["capacity_units"],
        "committed_units": rec["committed_units"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def delivery_stop(rec):
    return {
        "id": rec["id"],
        "route_id": rec["route_id"],
        "order_id": rec["order_id"],
        "window_start_minute": rec["window_start_minute"],
        "window_end_minute": rec["window_end_minute"],
        "service_tier": rec["service_tier"],
        "unit_load": rec["unit_load"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def protection_plan(rec):
    return {
        "id": rec["id"],
        "order_line_id": rec["order_line_id"],
        "tier": rec["tier"],
        "coverage_years": rec["coverage_years"],
        "premium_cents": rec["premium_cents"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def return_request(rec):
    return {
        "id": rec["id"],
        "order_line_id": rec["order_line_id"],
        "order_id": rec["order_id"],
        "reason": rec["reason"],
        "restocking_fee_cents": rec["restocking_fee_cents"],
        "refund_amount_cents": rec["refund_amount_cents"],
        "filed_on": rec["filed_on"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }
