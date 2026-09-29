"""Entity serializers (field lists follow SCAFFOLD 1.1 exactly)."""

from decimal import Decimal

from db import db
from services import calc, flows


def _num(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def branch(row):
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "region_code": row["region_code"],
        "will_call_enabled": row["will_call_enabled"],
        "cutoff_hour_utc": row["cutoff_hour_utc"],
        "overnight_surcharge_cents": row["overnight_surcharge_cents"],
        "branch_status": row["branch_status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def part(row):
    return {
        "id": row["id"],
        "part_number": row["part_number"],
        "oem_code": row["oem_code"],
        "description": row["description"],
        "category": row["category"],
        "lifecycle_status": row["lifecycle_status"],
        "superseded_by_part_id": row["superseded_by_part_id"],
        "list_price_cents": row["list_price_cents"],
        "core_required": row["core_required"],
        "core_deposit_cents": row["core_deposit_cents"],
        "weight_grams": row["weight_grams"],
        "cert_level_required": calc.cert_level_required(row),
        "is_returnable": calc.is_returnable(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def model_part_xref(row):
    return {
        "id": row["id"],
        "model_number": row["model_number"],
        "part_id": row["part_id"],
        "position_code": row["position_code"],
        "xref_source": row["xref_source"],
        "created_at": row["created_at"],
    }


def pricing_tier(row):
    return {
        "id": row["id"],
        "tier_code": row["tier_code"],
        "name": row["name"],
        "discount_pct_electrical": _num(row["discount_pct_electrical"]),
        "discount_pct_mechanical": _num(row["discount_pct_mechanical"]),
        "discount_pct_cosmetic": _num(row["discount_pct_cosmetic"]),
        "discount_pct_sealed_system": _num(row["discount_pct_sealed_system"]),
        "min_annual_volume_cents": row["min_annual_volume_cents"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def servicer_account(row):
    return {
        "id": row["id"],
        "business_name": row["business_name"],
        "oem_authorizations": list(row["oem_authorizations"]),
        "credit_terms": row["credit_terms"],
        "credit_limit_cents": row["credit_limit_cents"],
        "core_liability_limit_cents": row["core_liability_limit_cents"],
        "pricing_tier_id": row["pricing_tier_id"],
        "account_status": row["account_status"],
        "credit_used_cents": row["credit_used_cents"],
        "core_liability_cents": row["core_liability_cents"],
        "delinquency_score": row["delinquency_score"],
        "rolling_12m_volume_cents": row["rolling_12m_volume_cents"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def technician_certification(row):
    return {
        "id": row["id"],
        "servicer_account_id": row["servicer_account_id"],
        "technician_name": row["technician_name"],
        "oem_code": row["oem_code"],
        "cert_level": row["cert_level"],
        "training_completed_at": row["training_completed_at"],
        "expires_at": row["expires_at"],
        "cert_status": row["cert_status"],
        "is_effective": flows.cert_is_effective(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def inventory_record(row):
    return {
        "id": row["id"],
        "branch_id": row["branch_id"],
        "part_id": row["part_id"],
        "on_hand_units": row["on_hand_units"],
        "reserved_units": row["reserved_units"],
        "available_units": row["on_hand_units"] - row["reserved_units"],
        "reorder_point": row["reorder_point"],
        "last_counted_at": row["last_counted_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def price_file(row):
    return {
        "id": row["id"],
        "file_version": row["file_version"],
        "effective_at": row["effective_at"],
        "effective_until": row["effective_until"],
        "price_file_status": row["price_file_status"],
        "line_count": len(flows.price_file_lines_of(row)),
        "published_at": row["published_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def price_file_line(row):
    return {
        "id": row["id"],
        "price_file_id": row["price_file_id"],
        "part_id": row["part_id"],
        "new_list_price_cents": row["new_list_price_cents"],
        "new_core_deposit_cents": row["new_core_deposit_cents"],
        "new_lifecycle_status": row["new_lifecycle_status"],
        "previous_list_price_cents": row["previous_list_price_cents"],
        "previous_lifecycle_status": row["previous_lifecycle_status"],
        "previous_core_deposit_cents": row["previous_core_deposit_cents"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def part_order(row):
    invoiced = row.get("invoiced_total_cents")
    variance = 0 if invoiced is None else invoiced - row["total_cents"]
    return {
        "id": row["id"],
        "servicer_account_id": row["servicer_account_id"],
        "fulfillment_mode": row["fulfillment_mode"],
        "pickup_branch_id": row["pickup_branch_id"],
        "ship_to_zip": row["ship_to_zip"],
        "purchase_order_ref": row["purchase_order_ref"],
        "fulfillment_status": row["fulfillment_status"],
        "hold_reason": row["hold_reason"],
        "settlement_status": row["settlement_status"],
        "pricing_basis": row["pricing_basis"],
        "credit_decided_by_user_id": row["credit_decided_by_user_id"],
        "subtotal_cents": row["subtotal_cents"],
        "core_deposit_total_cents": row["core_deposit_total_cents"],
        "freight_cents": row["freight_cents"],
        "total_cents": row["total_cents"],
        "invoiced_total_cents": invoiced,
        "price_variance_cents": variance,
        "fulfilled_at": row["fulfilled_at"],
        "tracking_ref": row["tracking_ref"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def order_line(row):
    return {
        "id": row["id"],
        "part_order_id": row["part_order_id"],
        "requested_part_id": row["requested_part_id"],
        "resolved_part_id": row["resolved_part_id"],
        "quantity": row["quantity"],
        "supersession_hops": row["supersession_hops"],
        "unit_price_cents": row["unit_price_cents"],
        "extended_price_cents": row["extended_price_cents"],
        "invoiced_unit_price_cents": row["invoiced_unit_price_cents"],
        "core_deposit_cents": row["core_deposit_cents"],
        "returned_units": row["returned_units"],
        "line_status": row["line_status"],
        "allocation_branch_id": row["allocation_branch_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def substitute_request(row):
    return {
        "id": row["id"],
        "order_line_id": row["order_line_id"],
        "obsolete_part_id": row["obsolete_part_id"],
        "proposed_substitute_part_id": row["proposed_substitute_part_id"],
        "request_status": row["request_status"],
        "price_variance_pct": _num(row["price_variance_pct"]),
        "source": row["source"],
        "created_by_price_file_id": row["created_by_price_file_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def warranty_claim(row):
    return {
        "id": row["id"],
        "servicer_account_id": row["servicer_account_id"],
        "order_line_id": row["order_line_id"],
        "oem_code": row["oem_code"],
        "defect_code": row["defect_code"],
        "appliance_model_number": row["appliance_model_number"],
        "claim_status": row["claim_status"],
        "resubmission_count": row["resubmission_count"],
        "submitted_at": row["submitted_at"],
        "oem_reference": row["oem_reference"],
        "claim_amount_cents": row["claim_amount_cents"],
        "credit_amount_cents": row["credit_amount_cents"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def return_authorization(row):
    return {
        "id": row["id"],
        "servicer_account_id": row["servicer_account_id"],
        "order_line_id": row["order_line_id"],
        "quantity": row["quantity"],
        "reason_code": row["reason_code"],
        "return_branch_id": row["return_branch_id"],
        "ra_status": row["ra_status"],
        "days_since_fulfilled_at_request": row["days_since_fulfilled_at_request"],
        "gross_return_cents": row["gross_return_cents"],
        "restocking_fee_pct": _num(row["restocking_fee_pct"]),
        "restocking_fee_cents": row["restocking_fee_cents"],
        "credit_amount_cents": row["credit_amount_cents"],
        "core_deposit_refund_cents": row["core_deposit_refund_cents"],
        "fee_waived": row["fee_waived"],
        "created_by_user_id": row["created_by_user_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "received_at": row["received_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def credit_summary(account):
    used = flows.credit_used_cents(account["id"])
    liability = flows.core_liability_cents(account["id"])
    return {
        "credit_limit_cents": account["credit_limit_cents"],
        "credit_used_cents": used,
        "available_credit_cents": account["credit_limit_cents"] - used,
        "core_liability_cents": liability,
        "core_liability_limit_cents": account["core_liability_limit_cents"],
        "delinquency_score_rolling": flows.delinquency_score(account, "rolling"),
        "delinquency_score_lifetime": flows.delinquency_score(account, "lifetime"),
        "rolling_12m_volume_cents": flows.rolling_12m_volume_cents(account),
        "open_order_count": flows.open_order_count(account["id"]),
        "effective_cert_count": flows.effective_cert_count(account["id"]),
    }
