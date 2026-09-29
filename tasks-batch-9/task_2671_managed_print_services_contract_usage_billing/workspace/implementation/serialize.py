"""Output shapes.  Every resource but CostTier and StatementLine carries the
full id / created_at / updated_at / version quartet (PRD 2.4)."""
import derive
from util import fmt_dt


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = fmt_dt(row["created_at"])
    out["updated_at"] = fmt_dt(row["updated_at"])
    out["version"] = row["version"]
    return out


def contract(row):
    out = {
        "id": row["id"],
        "customer_name": row["customer_name"],
        "term_months": row["term_months"],
        "status": row["status"],
        "included_service_scope": row["included_service_scope"],
        "minimum_mono_pages_per_period": row["minimum_mono_pages_per_period"],
        "minimum_color_pages_per_period": row["minimum_color_pages_per_period"],
        "monthly_service_fee_cents": row["monthly_service_fee_cents"],
        "response_sla_hours_critical": row["response_sla_hours_critical"],
        "response_sla_hours_standard": row["response_sla_hours_standard"],
        "labor_rate_cents_per_hour": row["labor_rate_cents_per_hour"],
        "early_termination_fee_cents": row["early_termination_fee_cents"],
        "active_device_count": derive.active_device_count(row["id"]),
        "consumables_committed_cents": derive.consumables_committed_cents(row["id"]),
        "true_up_balance_cents": row["true_up_balance_cents"],
        "lifetime_billed_cents": row["lifetime_billed_cents"],
        "suspension_count": row["suspension_count"],
        "suspension_reason": row["suspension_reason"],
    }
    return _common(row, out)


def cost_tier(row):
    return {
        "id": row["id"],
        "contract_id": row["contract_id"],
        "page_class": row["page_class"],
        "tier_index": row["tier_index"],
        "from_page": row["from_page"],
        "to_page": row["to_page"],
        "rate_micro_dollars_per_page": row["rate_micro_dollars_per_page"],
        "created_at": fmt_dt(row["created_at"]),
    }


def site(row):
    out = {
        "id": row["id"],
        "contract_id": row["contract_id"],
        "name": row["name"],
        "address_region": row["address_region"],
        "secure_release_state": row["secure_release_state"],
        "release_method": row["release_method"],
        "network_vlan_tag": row["network_vlan_tag"],
        "toner_unit_cap": row["toner_unit_cap"],
        "open_toner_units": derive.open_toner_units(row["id"]),
    }
    return _common(row, out)


def stock(row):
    out = {
        "id": row["id"],
        "site_id": row["site_id"],
        "part_sku": row["part_sku"],
        "on_hand_qty": row["on_hand_qty"],
        "reserved_qty": derive.reserved_qty(row["site_id"], row["part_sku"]),
    }
    return _common(row, out)


def device(row):
    device_id = row["id"]
    out = {
        "id": device_id,
        "contract_id": row["contract_id"],
        "site_id": row["site_id"],
        "asset_tag": row["asset_tag"],
        "model_code": row["model_code"],
        "color_capable": row["color_capable"],
        "rated_monthly_duty_cycle": row["rated_monthly_duty_cycle"],
        "lifecycle_state": row["lifecycle_state"],
        "supply_state": row["supply_state"],
        "toner_level_pct": row["toner_level_pct"],
        "last_accepted_mono_meter": row["last_accepted_mono_meter"],
        "last_accepted_color_meter": row["last_accepted_color_meter"],
        "last_read_at": fmt_dt(row["last_read_at"]),
        "lifetime_mono_pages": derive.lifetime_mono_pages(device_id),
        "lifetime_color_pages": derive.lifetime_color_pages(device_id),
        "pages_since_last_cartridge": derive.pages_since_last_cartridge(device_id),
        "offline_exception_count": derive.offline_exception_count(device_id),
        "waste_event_count": derive.waste_event_count(device_id),
        "secure_release_enrolled": row["secure_release_enrolled"],
        "assessed_monthly_mono_pages": row["assessed_monthly_mono_pages"],
        "assessed_monthly_color_pages": row["assessed_monthly_color_pages"],
        "baseline_cost_micro_dollars_per_page": row["baseline_cost_micro_dollars_per_page"],
        "baseline_overhead_cents_per_month": row["baseline_overhead_cents_per_month"],
        "right_sizing_action": row["right_sizing_action"],
        "refresh_due": row["refresh_due"],
        "replaced_by_device_id": row["replaced_by_device_id"],
        "removal_order_id": row["removal_order_id"],
    }
    return _common(row, out)


def technician(row):
    out = {
        "id": row["id"],
        "full_name": row["full_name"],
        "home_region": row["home_region"],
        "skill_level": row["skill_level"],
        "travel_buffer_minutes": row["travel_buffer_minutes"],
        "open_dispatch_count": derive.open_dispatch_count(row["id"]),
    }
    return _common(row, out)


def meter_read(row):
    out = {
        "id": row["id"],
        "device_id": row["device_id"],
        "billing_period_id": row["billing_period_id"],
        "source": row["source"],
        "status": row["status"],
        "mono_meter": row["mono_meter"],
        "color_meter": row["color_meter"],
        "toner_level_pct": row["toner_level_pct"],
        "coverage_start": fmt_dt(row["coverage_start"]),
        "coverage_end": fmt_dt(row["coverage_end"]),
        "mono_delta": row["mono_delta"],
        "color_delta": row["color_delta"],
        "exception_reason": row["exception_reason"],
        "read_at": fmt_dt(row["read_at"]),
        "submitted_by_user_id": row["submitted_by_user_id"],
        "resolved_by_user_id": row["resolved_by_user_id"],
        "resolution_note": row["resolution_note"],
        "voided_reason": row["voided_reason"],
    }
    return _common(row, out)


def period(row):
    out = {
        "id": row["id"],
        "contract_id": row["contract_id"],
        "period_start": fmt_dt(row["period_start"]),
        "period_end": fmt_dt(row["period_end"]),
        "status": row["status"],
        "sweep_run_count": row["sweep_run_count"],
        "exception_open_count": derive.exception_open_count(row["id"]),
        "provisional_total_cents": row["provisional_total_cents"],
        "final_total_cents": row["final_total_cents"],
    }
    return _common(row, out)


def statement(row):
    out = {
        "id": row["id"],
        "billing_period_id": row["billing_period_id"],
        "variant": row["variant"],
        "projection_basis": row["projection_basis"],
        "mono_pages_billed": row["mono_pages_billed"],
        "color_pages_billed": row["color_pages_billed"],
        "mono_tier_index": row["mono_tier_index"],
        "color_tier_index": row["color_tier_index"],
        "mono_rate_micro_dollars_per_page": row["mono_rate_micro_dollars_per_page"],
        "color_rate_micro_dollars_per_page": row["color_rate_micro_dollars_per_page"],
        "usage_subtotal_cents": row["usage_subtotal_cents"],
        "shortfall_pages": row["shortfall_pages"],
        "shortfall_cents": row["shortfall_cents"],
        "service_labor_cents": row["service_labor_cents"],
        "sla_credit_cents": row["sla_credit_cents"],
        "waste_penalty_cents": row["waste_penalty_cents"],
        "total_cents": row["total_cents"],
        "generated_at": fmt_dt(row["generated_at"]),
    }
    return _common(row, out)


def statement_line(row):
    return {
        "id": row["id"],
        "statement_id": row["statement_id"],
        "device_id": row["device_id"],
        "page_class": row["page_class"],
        "pages": row["pages"],
        "rate_micro_dollars_per_page": row["rate_micro_dollars_per_page"],
        "amount_cents": row["amount_cents"],
        "created_at": fmt_dt(row["created_at"]),
    }


def order(row):
    out = {
        "id": row["id"],
        "device_id": row["device_id"],
        "part_type": row["part_type"],
        "quantity": row["quantity"],
        "unit_price_cents": row["unit_price_cents"],
        "committed_cents": row["committed_cents"],
        "status": row["status"],
        "trigger_source": row["trigger_source"],
        "pages_since_last_cartridge_at_order": row["pages_since_last_cartridge_at_order"],
        "waste_flagged": row["waste_flagged"],
        "delivered_at": fmt_dt(row["delivered_at"]),
        "cancel_reason": row["cancel_reason"],
    }
    return _common(row, out)


def ticket(row):
    out = {
        "id": row["id"],
        "device_id": row["device_id"],
        "assigned_technician_id": row["assigned_technician_id"],
        "severity": row["severity"],
        "status": row["status"],
        "symptom_code": row["symptom_code"],
        "part_sku": row["part_sku"],
        "opened_at": fmt_dt(row["opened_at"]),
        "respond_by": fmt_dt(row["respond_by"]),
        "window_start": fmt_dt(row["window_start"]),
        "window_end": fmt_dt(row["window_end"]),
        "hold_started_at": fmt_dt(row["hold_started_at"]),
        "parts_hold_hours": row["parts_hold_hours"],
        "responded_at": fmt_dt(row["responded_at"]),
        "hours_late": row["hours_late"],
        "labor_hours": row["labor_hours"],
        "labor_cents": row["labor_cents"],
        "sla_credit_cents": row["sla_credit_cents"],
    }
    return _common(row, out)


def review(row):
    out = {
        "id": row["id"],
        "contract_id": row["contract_id"],
        "quarter_label": row["quarter_label"],
        "status": row["status"],
        "authored_by_user_id": row["authored_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "baseline_savings_cents": row["baseline_savings_cents"],
        "realized_savings_cents": row["realized_savings_cents"],
        "volume_trend_pct": row["volume_trend_pct"],
        "retain_count": row["retain_count"],
        "downgrade_count": row["downgrade_count"],
        "upgrade_count": row["upgrade_count"],
        "consolidate_count": row["consolidate_count"],
        "refresh_due_device_count": row["refresh_due_device_count"],
    }
    return _common(row, out)


def removal(row):
    out = {
        "id": row["id"],
        "contract_id": row["contract_id"],
        "status": row["status"],
        "scheduled_for": fmt_dt(row["scheduled_for"]),
        "device_count": derive.removal_device_count(row["id"]),
        "sanitization_method": row["sanitization_method"],
        "sanitization_certificate_ref": row["sanitization_certificate_ref"],
        "unbilled_pages_charge_cents": row["unbilled_pages_charge_cents"],
        "early_termination_fee_applied_cents": row["early_termination_fee_applied_cents"],
        "device_residual_credit_cents": row["device_residual_credit_cents"],
        "gross_settlement_cents": row["gross_settlement_cents"],
        "sanitization_fee_cents": row["sanitization_fee_cents"],
        "net_settlement_cents": row["net_settlement_cents"],
        "settled_at": fmt_dt(row["settled_at"]),
    }
    return _common(row, out)
