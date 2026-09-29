"""Entity to JSON projections."""

from db import iso
from services import derive


def _num(value):
    return float(value) if value is not None else None


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def health_plan(row):
    data = {
        "name": row["name"],
        "payer_type": row["payer_type"],
        "member_cost_share_pct": _num(row["member_cost_share_pct"]),
    }
    data.update(_common(row))
    return data


def plan_grant(row):
    data = {
        "health_plan_id": row["health_plan_id"],
        "benefit_year": row["benefit_year"],
        "grant_budget_cents": row["grant_budget_cents"],
        "per_delivery_cap_cents": row["per_delivery_cap_cents"],
        "committed_cents": derive.grant_committed_cents(row),
        "consumed_cents": derive.grant_consumed_cents(row),
        "remaining_cents": derive.grant_remaining_cents(row),
        "status": derive.grant_status(row),
    }
    data.update(_common(row))
    return data


def pharmacy(row):
    data = {
        "name": row["name"],
        "state_code": row["state_code"],
        "cold_chain_certified": row["cold_chain_certified"],
        "controlled_license_tier": row["controlled_license_tier"],
        "return_window_minutes": row["return_window_minutes"],
    }
    data.update(_common(row))
    return data


def patient(row):
    data = {
        "full_name": row["full_name"],
        "date_of_birth": row["date_of_birth"],
        "phone_last4": row["phone_last4"],
        "address_line": row["address_line"],
        "zone_code": row["zone_code"],
        "hipaa_consent_status": row["hipaa_consent_status"],
        "masked_name": row["masked_name"],
    }
    data.update(_common(row))
    return data


def delivery_zone(row):
    data = {
        "zone_code": row["zone_code"],
        "distance_band_miles": _num(row["distance_band_miles"]),
        "base_fee_cents": row["base_fee_cents"],
        "per_mile_cents": row["per_mile_cents"],
        "cold_pack_fee_cents": row["cold_pack_fee_cents"],
        "controlled_handling_fee_cents": row["controlled_handling_fee_cents"],
        "after_hours_fee_cents": row["after_hours_fee_cents"],
        "cold_chain_supported": row["cold_chain_supported"],
        "controlled_delivery_allowed": row["controlled_delivery_allowed"],
    }
    data.update(_common(row))
    return data


def delivery_window(row):
    reserved = derive.reserved_slots(row)
    data = {
        "zone_id": row["zone_id"],
        "courier_mode": row["courier_mode"],
        "window_start": iso(row["window_start"]),
        "window_end": iso(row["window_end"]),
        "capacity_slots": row["capacity_slots"],
        "reserved_slots": reserved,
        "available_slots": max(row["capacity_slots"] - reserved, 0),
        "is_after_hours": row["is_after_hours"],
        "status": row["status"],
    }
    data.update(_common(row))
    return data


def pharmacy_order(row):
    data = {
        "pharmacy_id": row["pharmacy_id"],
        "patient_id": row["patient_id"],
        "health_plan_id": row["health_plan_id"],
        "rx_line_count": row["rx_line_count"],
        "cold_chain_required": row["cold_chain_required"],
        "controlled_schedule": row["controlled_schedule"],
        "total_rx_value_cents": row["total_rx_value_cents"],
        "signature_required": row["signature_required"],
        "required_id_verification": row["required_id_verification"],
        "hold_count": row["hold_count"],
        "status": row["status"],
    }
    data.update(_common(row))
    return data


def courier(row):
    data = {
        "display_name": row["display_name"],
        "mode": row["mode"],
        "served_zone_codes": list(row["served_zone_codes"]),
        "cold_chain_equipped": row["cold_chain_equipped"],
        "controlled_certified": row["controlled_certified"],
        "status": row["status"],
        "active_delivery_count": derive.active_delivery_count(row),
        "attempt_total_count": derive.attempt_total_count(row),
        "delivered_count": derive.delivered_count(row),
        "rolling_reliability_score": _num(derive.rolling_reliability_score(row)),
        "lifetime_reliability_score": _num(derive.lifetime_reliability_score(row)),
    }
    data.update(_common(row))
    return data


def delivery(row):
    data = {
        "order_id": row["order_id"],
        "window_id": row["window_id"],
        "courier_id": row["courier_id"],
        "reship_of_delivery_id": row["reship_of_delivery_id"],
        "custody_status": row["custody_status"],
        "settlement_status": row["settlement_status"],
        "handling_class": row["handling_class"],
        "signature_required": row["signature_required"],
        "required_id_verification": row["required_id_verification"],
        "attempt_count": derive.attempt_count(row),
        "last_attempt_at": iso(derive.last_attempt_at(row)),
        "excluded_courier_ids": list(row["excluded_courier_ids"]),
        "cold_chain_seal_id": row["cold_chain_seal_id"],
        "picked_up_at": iso(row["picked_up_at"]),
        "delivered_at": iso(row["delivered_at"]),
        "return_due_at": iso(row["return_due_at"]),
        "fee_subtotal_cents": row["fee_subtotal_cents"],
    }
    data.update(_common(row))
    return data


def courier_assignment(row):
    data = {
        "delivery_id": row["delivery_id"],
        "courier_id": row["courier_id"],
        "mode": row["mode"],
        "status": row["status"],
        "offered_at": iso(row["offered_at"]),
        "offer_expires_at": iso(row["offer_expires_at"]),
        "responded_at": iso(row["responded_at"]),
        "rank_score": _num(row["rank_score"]),
        "revoked_by_ops_user_id": row["revoked_by_ops_user_id"],
    }
    data.update(_common(row))
    return data


def delivery_attempt(row):
    return {
        "id": row["id"],
        "delivery_id": row["delivery_id"],
        "courier_id": row["courier_id"],
        "attempt_no": row["attempt_no"],
        "attempted_at": iso(row["attempted_at"]),
        "requested_outcome": row["requested_outcome"],
        "outcome": row["outcome"],
        "id_verification_method": row["id_verification_method"],
        "signature_captured": row["signature_captured"],
        "recipient_relationship": row["recipient_relationship"],
        "pod_photo_ref": row["pod_photo_ref"],
        "elapsed_since_pickup_minutes": row["elapsed_since_pickup_minutes"],
        "reliability_credit": _num(row["reliability_credit"]),
        "created_at": row["created_at"],
    }


def fee_allocation(row):
    data = {
        "delivery_id": row["delivery_id"],
        "plan_grant_id": row["plan_grant_id"],
        "variant": row["variant"],
        "status": row["status"],
        "base_line_cents": row["base_line_cents"],
        "mileage_line_cents": row["mileage_line_cents"],
        "cold_pack_line_cents": row["cold_pack_line_cents"],
        "controlled_line_cents": row["controlled_line_cents"],
        "after_hours_line_cents": row["after_hours_line_cents"],
        "reattempt_line_cents": row["reattempt_line_cents"],
        "fee_subtotal_cents": row["fee_subtotal_cents"],
        "cost_share_pct_applied": _num(row["cost_share_pct_applied"]),
        "patient_gross_share_cents": row["patient_gross_share_cents"],
        "plan_grant_cents": row["plan_grant_cents"],
        "absorption_tier_cents": row["absorption_tier_cents"],
        "pharmacy_absorption_cents": row["pharmacy_absorption_cents"],
        "patient_payable_cents": row["patient_payable_cents"],
        "pharmacy_payable_cents": row["pharmacy_payable_cents"],
    }
    data.update(_common(row))
    return data


def exception_case(row):
    data = {
        "delivery_id": row["delivery_id"],
        "reship_delivery_id": row["reship_delivery_id"],
        "exception_type": row["exception_type"],
        "status": row["status"],
        "opened_by_ops_user_id": row["opened_by_ops_user_id"],
        "adjudicated_by_ops_user_id": row["adjudicated_by_ops_user_id"],
        "disposition": row["disposition"],
        "credit_cents": row["credit_cents"],
        "notes": row["notes"],
    }
    data.update(_common(row))
    return data


def disclosure(row):
    return {
        "id": row["id"],
        "delivery_id": row["delivery_id"],
        "courier_id": row["courier_id"],
        "disclosed_at": iso(row["disclosed_at"]),
        "purpose": row["purpose"],
        "fields_disclosed": list(row["fields_disclosed"]),
        "redacted_field_count": row["redacted_field_count"],
        "minimization_profile": row["minimization_profile"],
        "created_at": row["created_at"],
    }
