"""Entity serializers. Derived fields are recomputed on read; reads never mutate rows."""

import calc
from db import iso, iso_date


def _common(row):
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def vendor(row):
    out = _common(row)
    out.update({
        "vendor_code": row["vendor_code"],
        "legal_name": row["legal_name"],
        "cost_model": row["cost_model"],
        "commission_rate_bps": row["commission_rate_bps"],
        "wholesale_discount_bps": row["wholesale_discount_bps"],
        "inventory_refresh_cadence_minutes": row["inventory_refresh_cadence_minutes"],
        "safety_buffer_units": row["safety_buffer_units"],
        "oversell_grace_units": row["oversell_grace_units"],
        "default_lead_time_days": row["default_lead_time_days"],
        "ack_sla_hours": row["ack_sla_hours"],
        "ship_sla_grace_hours": row["ship_sla_grace_hours"],
        "onboarding_status": row["onboarding_status"],
        "integration_round": row["integration_round"],
        "certified_by_user_id": row["certified_by_user_id"],
        "activated_by_user_id": row["activated_by_user_id"],
        "suspension_reason": row["suspension_reason"],
        "performance_tier": row["performance_tier"],
        "promise_padding_days": row["promise_padding_days"],
        "settlement_balance_cents": row["settlement_balance_cents"],
        "chargeback_balance_cents": row["chargeback_balance_cents"],
    })
    return out


def integration_test(row):
    out = _common(row)
    out.update({
        "vendor_id": row["vendor_id"],
        "message_type": row["message_type"],
        "round_number": row["round_number"],
        "sample_payload_digest": row["sample_payload_digest"],
        "reported_error_count": row["reported_error_count"],
        "status": row["status"],
        "created_by_user_id": row["created_by_user_id"],
        "evaluated_by_user_id": row["evaluated_by_user_id"],
        "defect_notes": row["defect_notes"],
        "evaluated_at": iso(row["evaluated_at"]),
    })
    return out


def item(row):
    view = calc.availability(row)
    out = _common(row)
    out.update({
        "vendor_id": row["vendor_id"],
        "fallback_item_id": row["fallback_item_id"],
        "sku": row["sku"],
        "lead_time_days": row["lead_time_days"],
        "ship_method": row["ship_method"],
        "unit_retail_cents": row["unit_retail_cents"],
        "unit_wholesale_cost_cents": row["unit_wholesale_cost_cents"],
        "reverse_freight_owner": row["reverse_freight_owner"],
        "restock_policy": row["restock_policy"],
        "defect_window_days": row["defect_window_days"],
        "status": row["status"],
        "suppression_reason": row["suppression_reason"],
        "effective_on_hand_units": view["effective_on_hand_units"],
        "inventory_is_stale": view["inventory_is_stale"],
        "reserved_units": row["reserved_units"],
        "available_units": view["available_units"],
        "last_inventory_refresh_at": iso(row["last_inventory_refresh_at"]),
        "lifetime_reserved_units": row["lifetime_reserved_units"],
        "lifetime_released_units": row["lifetime_released_units"],
        "lifetime_shipped_units": row["lifetime_shipped_units"],
        "unit_cost_cents": row["unit_cost_cents"],
    })
    return out


def rule(row):
    out = _common(row)
    out.update({
        "vendor_id": row["vendor_id"],
        "zone_code": row["zone_code"],
        "ship_method": row["ship_method"],
        "transit_days": row["transit_days"],
        "cutoff_hour_utc": row["cutoff_hour_utc"],
        "surcharge_cents": row["surcharge_cents"],
        "status": row["status"],
        "inactivated_by_suspension": row["inactivated_by_suspension"],
    })
    return out


def blackout(row):
    out = _common(row)
    out.update({
        "vendor_id": row["vendor_id"],
        "start_date": iso_date(row["start_date"]),
        "end_date": iso_date(row["end_date"]),
        "reopen_buffer_days": row["reopen_buffer_days"],
        "reason": row["reason"],
        "status": row["status"],
    })
    return out


def snapshot(row):
    out = _common(row)
    out.update({
        "item_id": row["item_id"],
        "on_hand_units": row["on_hand_units"],
        "effective_from": iso(row["effective_from"]),
        "effective_to": iso(row["effective_to"]),
        "source": row["source"],
        "status": row["status"],
        "feed_sequence": row["feed_sequence"],
    })
    return out


def order(row):
    total_retail, total_cost, margin = calc.order_totals(row)
    refunded = calc.order_refunded_cents(row)
    out = _common(row)
    out.update({
        "order_ref": row["order_ref"],
        "customer_zone_code": row["customer_zone_code"],
        "placed_at": iso(row["placed_at"]),
        "fulfillment_status": calc.fulfillment_status(row),
        "financial_status": calc.financial_status(row),
        "quoted_promise_date": iso_date(row["quoted_promise_date"]),
        "recomputed_promise_date": iso_date(row["recomputed_promise_date"]),
        "promise_variant_in_effect": calc.promise_variant_in_effect(row),
        "total_retail_cents": total_retail,
        "total_cost_cents": total_cost,
        "margin_cents": margin,
        "refunded_cents": refunded,
        "net_retail_cents": calc.net_retail_cents(row),
        "retailer_absorbed_cents": calc.order_retailer_absorbed_cents(row),
    })
    return out


def line(row):
    out = _common(row)
    out.update({
        "order_id": row["order_id"],
        "item_id": row["item_id"],
        "line_number": row["line_number"],
        "quantity": row["quantity"],
        "unit_retail_cents": row["unit_retail_cents"],
        "unit_cost_cents": row["unit_cost_cents"],
        "surcharge_cents": row["surcharge_cents"],
        "status": row["status"],
        "transmitted_at": iso(row["transmitted_at"]),
        "acknowledged_at": iso(row["acknowledged_at"]),
        "shipped_at": iso(row["shipped_at"]),
        "ack_deadline_at": iso(row["ack_deadline_at"]),
        "ship_deadline_at": iso(row["ship_deadline_at"]),
        "ack_sla_breached": calc.ack_sla_breached(row),
        "ship_sla_breached": calc.ship_sla_breached(row),
        "transmit_attempt_count": row["transmit_attempt_count"],
        "line_promise_date": iso_date(calc.line_promise_date(row)),
        "returned_units": calc.line_returned_units(row),
    })
    return out


def shipment(row):
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "line_id": row["line_id"],
        "carrier": row["carrier"],
        "tracking_number": row["tracking_number"],
        "ship_date": iso_date(row["ship_date"]),
        "shipped_units": row["shipped_units"],
        "package_count": row["package_count"],
        "ship_hours": row["ship_hours"],
        "on_time": row["on_time"],
    }


def ret(row):
    out = _common(row)
    out.update({
        "line_id": row["line_id"],
        "routed_vendor_id": row["routed_vendor_id"],
        "reason_code": row["reason_code"],
        "quantity_returned": row["quantity_returned"],
        "status": row["status"],
        "routing_destination": row["routing_destination"],
        "reverse_freight_owner": row["reverse_freight_owner"],
        "restock_disposition": row["restock_disposition"],
        "refund_base_cents": row["refund_base_cents"],
        "restocking_fee_cents": row["restocking_fee_cents"],
        "customer_freight_charge_cents": row["customer_freight_charge_cents"],
        "refund_cents": row["refund_cents"],
        "vendor_chargeback_cents": row["vendor_chargeback_cents"],
        "restocked_units": row["restocked_units"],
        "rejection_reason": row["rejection_reason"],
    })
    return out


def scorecard(row):
    out = _common(row)
    out.update({
        "vendor_id": row["vendor_id"],
        "period_start": iso_date(row["period_start"]),
        "period_end": iso_date(row["period_end"]),
        "metric_variant": row["metric_variant"],
        "seeded_prior_avg_ship_hours": row["seeded_prior_avg_ship_hours"],
        "seeded_prior_on_time_ship_rate_bps": row["seeded_prior_on_time_ship_rate_bps"],
        "seeded_prior_cancellation_rate_bps": row["seeded_prior_cancellation_rate_bps"],
        "seeded_prior_defect_rate_bps": row["seeded_prior_defect_rate_bps"],
        "transmitted_line_count": row["transmitted_line_count"],
        "shipped_line_count": row["shipped_line_count"],
        "cancelled_line_count": row["cancelled_line_count"],
        "defect_return_count": row["defect_return_count"],
        "transmitted_unit_count": row["transmitted_unit_count"],
        "shipped_unit_count": row["shipped_unit_count"],
        "cancelled_unit_count": row["cancelled_unit_count"],
        "defect_unit_count": row["defect_unit_count"],
        "on_time_ship_rate_bps": row["on_time_ship_rate_bps"],
        "cancellation_rate_bps": row["cancellation_rate_bps"],
        "defect_rate_bps": row["defect_rate_bps"],
        "avg_ship_hours": row["avg_ship_hours"],
        "composite_score": row["composite_score"],
        "tier": row["tier"],
        "promise_padding_days": row["promise_padding_days"],
        "status": row["status"],
        "published_at": iso(row["published_at"]),
    })
    return out
