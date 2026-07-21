"""Public JSON serialization for each entity, including computed fields."""
from timeutil import fmt_iso
import services


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def trade_account(rec):
    tier, pct = services.account_tier_and_pct(rec)
    out = _common(rec)
    out.update(
        {
            "business_name": rec["business_name"],
            "contact_email": rec["contact_email"],
            "credit_limit_cents": rec["credit_limit_cents"],
            "available_credit_cents": services.account_available_credit(rec),
            "annual_spend_cents": services.account_annual_spend(rec),
            "tier": tier,
            "discount_pct": float(pct),
            "status": rec["status"],
        }
    )
    return out


def fixture_model(rec):
    out = _common(rec)
    out.update(
        {
            "sku_base": rec["sku_base"],
            "category": rec["category"],
            "base_price_cents": rec["base_price_cents"],
            "base_wattage": rec["base_wattage"],
            "energy_star": rec["energy_star"],
            "special_order_only": rec["special_order_only"],
            "supplier_lead_days": rec["supplier_lead_days"],
            "options": [dict(o) for o in rec.get("options", [])],
        }
    )
    return out


def order(rec):
    out = _common(rec)
    out.update(
        {
            "trade_account_id": rec.get("trade_account_id"),
            "customer_name": rec["customer_name"],
            "fulfillment_status": rec["fulfillment_status"],
            "payment_status": rec["payment_status"],
            "subtotal_estimate_cents": rec["subtotal_estimate_cents"],
            "discount_estimate_cents": rec["discount_estimate_cents"],
            "total_estimate_cents": rec["total_estimate_cents"],
            "subtotal_final_cents": rec["subtotal_final_cents"],
            "discount_final_cents": rec["discount_final_cents"],
            "total_final_cents": rec["total_final_cents"],
            "committed_credit_cents": rec["committed_credit_cents"],
            "amount_paid_cents": rec["amount_paid_cents"],
            "settled_at": fmt_iso(rec.get("settled_at")),
        }
    )
    return out


def order_line(rec):
    out = _common(rec)
    out.update(
        {
            "order_id": rec["order_id"],
            "fixture_model_id": rec["fixture_model_id"],
            "selected_option_ids": list(rec["selected_option_ids"]),
            "configured_sku": rec["configured_sku"],
            "quantity": rec["quantity"],
            "unit_price_cents": rec["unit_price_cents"],
            "is_special_order": rec["is_special_order"],
            "line_status": rec["line_status"],
        }
    )
    return out


def special_order(rec):
    out = _common(rec)
    out.update(
        {
            "order_id": rec["order_id"],
            "order_line_id": rec["order_line_id"],
            "supplier_lead_days": rec["supplier_lead_days"],
            "status": rec["status"],
            "confirmed_at": fmt_iso(rec.get("confirmed_at")),
            "estimated_ready_date": fmt_iso(rec.get("estimated_ready_date")),
            "actual_ready_date": fmt_iso(rec.get("actual_ready_date")),
            "variance_days": rec.get("variance_days"),
        }
    )
    return out


def design_consult(rec):
    out = _common(rec)
    out.update(
        {
            "trade_account_id": rec["trade_account_id"],
            "order_id": rec.get("order_id"),
            "room_type": rec["room_type"],
            "fee_cents": rec["fee_cents"],
            "status": rec["status"],
            "revision_count": rec["revision_count"],
        }
    )
    return out


def installer(rec):
    out = _common(rec)
    out.update(
        {
            "name": rec["name"],
            "service_area": rec["service_area"],
            "daily_capacity": rec["daily_capacity"],
            "active_referral_count": rec["active_referral_count"],
        }
    )
    return out


def install_referral(rec):
    out = _common(rec)
    out.update(
        {
            "order_id": rec["order_id"],
            "installer_id": rec["installer_id"],
            "delivery_job_id": rec["delivery_job_id"],
            "appointment_start": fmt_iso(rec.get("appointment_start")),
            "appointment_end": fmt_iso(rec.get("appointment_end")),
            "status": rec["status"],
        }
    )
    return out


def delivery_truck(rec):
    out = _common(rec)
    out.update(
        {
            "name": rec["name"],
            "capacity_units": rec["capacity_units"],
        }
    )
    return out


def delivery_job(rec):
    out = _common(rec)
    out.update(
        {
            "order_id": rec["order_id"],
            "delivery_truck_id": rec["delivery_truck_id"],
            "window_start": fmt_iso(rec["window_start"]),
            "window_end": fmt_iso(rec["window_end"]),
            "status": rec["status"],
        }
    )
    return out


def return_request(rec):
    out = _common(rec)
    out.update(
        {
            "order_id": rec["order_id"],
            "order_line_id": rec["order_line_id"],
            "reason": rec["reason"],
            "status": rec["status"],
            "restocking_fee_cents": rec.get("restocking_fee_cents"),
            "refund_cents": rec.get("refund_cents"),
        }
    )
    return out


def rebate_program(rec):
    out = _common(rec)
    out.update(
        {
            "name": rec["name"],
            "rebate_rate": rec["rebate_rate"],
            "wattage_ceiling": rec["wattage_ceiling"],
            "budget_total_cents": rec["budget_total_cents"],
            "budget_remaining_cents": services.rebate_budget_remaining(rec),
        }
    )
    return out


def rebate_claim(rec):
    out = _common(rec)
    out.update(
        {
            "order_id": rec["order_id"],
            "rebate_program_id": rec["rebate_program_id"],
            "claimed_cents": rec["claimed_cents"],
            "status": rec["status"],
        }
    )
    return out
