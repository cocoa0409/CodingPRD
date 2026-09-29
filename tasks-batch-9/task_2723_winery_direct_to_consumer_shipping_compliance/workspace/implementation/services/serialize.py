"""Explicit per-entity serializers.

Every field named in SCAFFOLD 1.1 is emitted; no internal bookkeeping key is
ever leaked. Derived counters are recomputed at read time so they can never
drift from the rows they summarise.
"""
from rounding import liters_out
from services import derive, volume


def _common(row):
    out = {"id": row["id"], "created_at": row["created_at"]}
    if "version" in row:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def winery(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "ttb_permit_number": row["ttb_permit_number"],
        "home_state_code": row["home_state_code"],
        "annual_production_gallons": row["annual_production_gallons"],
        "status": row["status"],
        "suspension_reason": row["suspension_reason"],
    })
    out.update(derive.winery_derived(row))
    return out


def state_rule(row):
    out = _common(row)
    out.update({
        "state_code": row["state_code"],
        "allows_dtc": row["allows_dtc"],
        "per_consumer_limit_liters": liters_out(row["per_consumer_limit_liters"]),
        "per_consumer_period": row["per_consumer_period"],
        "per_winery_annual_limit_liters": liters_out(row["per_winery_annual_limit_liters"]),
        "excise_rate_per_liter_cents": row["excise_rate_per_liter_cents"],
        "large_format_surcharge_cents_per_liter": row["large_format_surcharge_cents_per_liter"],
        "excise_cap_cents_per_shipment": row["excise_cap_cents_per_shipment"],
        "sales_tax_rate_bps": row["sales_tax_rate_bps"],
        "tax_on_shipping": row["tax_on_shipping"],
        "excise_in_tax_base": row["excise_in_tax_base"],
        "adult_signature_required": row["adult_signature_required"],
        "requires_carrier_program": row["requires_carrier_program"],
        "reporting_frequency": row["reporting_frequency"],
        "zero_filing_required": row["zero_filing_required"],
        "min_purchaser_age": row["min_purchaser_age"],
        "renewal_lead_days": row["renewal_lead_days"],
    })
    return out


def prohibited_zip(row):
    out = _common(row)
    out.update({
        "state_rule_id": row["state_rule_id"],
        "zip_code": row["zip_code"],
        "reason": row["reason"],
        "effective_from": row["effective_from"],
    })
    return out


def carrier_program(row):
    out = _common(row)
    out.update({
        "carrier_code": row["carrier_code"],
        "program_name": row["program_name"],
        "states_served": list(row["states_served"]),
        "requires_enrollment": row["requires_enrollment"],
        "adult_signature_service_code": row["adult_signature_service_code"],
    })
    return out


def carrier_enrollment(row):
    out = _common(row)
    out.update({
        "winery_id": row["winery_id"],
        "carrier_program_id": row["carrier_program_id"],
        "account_number": row["account_number"],
        "status": row["status"],
        "approved_at": row["approved_at"],
        "decided_by_user_id": row["decided_by_user_id"],
    })
    return out


def consumer(row):
    out = _common(row)
    out.update({
        "full_name": row["full_name"],
        "email": row["email"],
        "birthdate": row["birthdate"],
        "address_line": row["address_line"],
        "city": row["city"],
        "state_code": row["state_code"],
        "zip_code": row["zip_code"],
        "id_verification_method": row["id_verification_method"],
        "id_verified_at": row["id_verified_at"],
    })
    out.update(volume.consumer_derived(row))
    return out


def state_permit(row):
    out = _common(row)
    out.update({
        "winery_id": row["winery_id"],
        "state_code": row["state_code"],
        "permit_number": row["permit_number"],
        "permit_type": row["permit_type"],
        "effective_date": row["effective_date"],
        "expiration_date": row["expiration_date"],
        "status": row["status"],
        "renewal_reference": row["renewal_reference"],
        "renewal_filed_at": row["renewal_filed_at"],
        "revocation_reason": row["revocation_reason"],
        "renewal_cycle_count": row["renewal_cycle_count"],
    })
    return out


def club_subscription(row):
    out = _common(row)
    out.update({
        "consumer_id": row["consumer_id"],
        "winery_id": row["winery_id"],
        "cadence": row["cadence"],
        "sku": row["sku"],
        "bottles_per_shipment": row["bottles_per_shipment"],
        "bottle_ml": row["bottle_ml"],
        "unit_price_cents": row["unit_price_cents"],
        "next_run_date": row["next_run_date"],
        "status": row["status"],
        "hold_start_date": row["hold_start_date"],
        "hold_release_date": row["hold_release_date"],
        "hold_reason": row["hold_reason"],
        "last_hold_release_date": row["last_hold_release_date"],
        "missed_run_count": row["missed_run_count"],
        "annual_allotment": row["annual_allotment"],
    })
    out.update(derive.subscription_derived(row))
    return out


def order(row):
    out = _common(row)
    out.update({
        "winery_id": row["winery_id"],
        "consumer_id": row["consumer_id"],
        "club_subscription_id": row["club_subscription_id"],
        "ship_to_address_line": row["ship_to_address_line"],
        "ship_to_state_code": row["ship_to_state_code"],
        "ship_to_zip": row["ship_to_zip"],
        "compliance_status": row["compliance_status"],
        "fulfillment_status": row["fulfillment_status"],
        "rejection_error_id": row["rejection_error_id"],
        "override_applied": row["override_applied"],
        "total_liters": liters_out(row["total_liters"]),
        "subtotal_cents": row["subtotal_cents"],
        "shipping_gross_cents": row["shipping_gross_cents"],
        "shipping_tiered_cents": row["shipping_tiered_cents"],
        "shipping_discount_cents": row["shipping_discount_cents"],
        "shipping_cents": row["shipping_cents"],
        "excise_tax_cents": row["excise_tax_cents"],
        "sales_tax_cents": row["sales_tax_cents"],
        "pre_fee_total_cents": row["pre_fee_total_cents"],
        "compliance_handling_fee_cents": row["compliance_handling_fee_cents"],
        "total_cents": row["total_cents"],
        "excise_reversed_cents": row["excise_reversed_cents"],
        "sales_tax_reversed_cents": row["sales_tax_reversed_cents"],
        "adult_signature_required": row["adult_signature_required"],
        "cleared_at": row["cleared_at"],
        "returned_at": row["returned_at"],
    })
    return out


def order_line(row):
    out = _common(row)
    out.update({
        "order_id": row["order_id"],
        "line_index": row["line_index"],
        "sku": row["sku"],
        "bottle_ml": row["bottle_ml"],
        "bottles": row["bottles"],
        "unit_price_cents": row["unit_price_cents"],
        "line_liters": liters_out(row["line_liters"]),
        "line_subtotal_cents": row["line_subtotal_cents"],
        "allocated_shipping_cents": row["allocated_shipping_cents"],
        "line_taxable_cents": row["line_taxable_cents"],
        "line_sales_tax_cents": row["line_sales_tax_cents"],
    })
    return out


def shipment(row):
    out = _common(row)
    out.update({
        "order_id": row["order_id"],
        "carrier_enrollment_id": row["carrier_enrollment_id"],
        "replacement_of_shipment_id": row["replacement_of_shipment_id"],
        "tracking_number": row["tracking_number"],
        "adult_signature_required": row["adult_signature_required"],
        "adult_signature_service_code": row["adult_signature_service_code"],
        "status": row["status"],
        "exception_code": row["exception_code"],
        "reroute_zip": row["reroute_zip"],
        "reroute_count": row["reroute_count"],
        "signed_by": row["signed_by"],
        "signer_age_verified": row["signer_age_verified"],
        "delivered_at": row["delivered_at"],
        "returned_at": row["returned_at"],
    })
    return out


def compliance_exception(row):
    out = _common(row)
    out.update({
        "order_id": row["order_id"],
        "raised_rule": row["raised_rule"],
        "justification": row["justification"],
        "status": row["status"],
        "requested_by_user_id": row["requested_by_user_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "decision_note": row["decision_note"],
        "decided_at": row["decided_at"],
    })
    return out


def ledger_entry(row):
    out = _common(row)
    out.update({
        "consumer_id": row["consumer_id"],
        "winery_id": row["winery_id"],
        "order_id": row["order_id"],
        "shipment_id": row["shipment_id"],
        "state_code": row["state_code"],
        "liters": liters_out(row["liters"]),
        "event_type": row["event_type"],
        "occurred_at": row["occurred_at"],
        "reason": row["reason"],
    })
    return out


def remittance(row):
    out = _common(row)
    out.update({
        "winery_id": row["winery_id"],
        "supersedes_remittance_id": row["supersedes_remittance_id"],
        "state_code": row["state_code"],
        "period_type": row["period_type"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "basis": row["basis"],
        "status": row["status"],
        "excise_accrued_cents": row["excise_accrued_cents"],
        "excise_reversed_cents": row["excise_reversed_cents"],
        "excise_due_cents": row["excise_due_cents"],
        "sales_tax_accrued_cents": row["sales_tax_accrued_cents"],
        "sales_tax_reversed_cents": row["sales_tax_reversed_cents"],
        "sales_tax_due_cents": row["sales_tax_due_cents"],
        "liters_total": liters_out(row["liters_total"]),
        "shipment_count": row["shipment_count"],
        "included_order_ids": list(row["included_order_ids"]),
        "filed_at": row["filed_at"],
        "filed_by_user_id": row["filed_by_user_id"],
        "remitted_at": row["remitted_at"],
        "remitted_by_user_id": row["remitted_by_user_id"],
        "payment_reference": row["payment_reference"],
    })
    return out
