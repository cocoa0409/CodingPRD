"""Response shapes. Field names, nullability and decimal scales come straight
from SCAFFOLD.yaml entities and PRD.md §2.4 / §2.7.

Light entities (Jurisdiction, WeightGroupFee, JurisdictionMileageLeg,
ReturnJurisdictionLine, DistanceScheduleLine) carry `id` and `created_at` only:
no `updated_at` and no `version` (PRD §2.4).
"""

from common import (
    GALLON_SCALE,
    MILE_SCALE,
    MONEY_SCALE,
    PERCENT_SCALE,
    RATE_SCALE,
    RATIO_SCALE,
    fnum,
)


def _base(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def _light(row):
    return {"id": row["id"], "created_at": row["created_at"]}


def carrier_out(row):
    out = _base(row)
    out.update({
        "legal_name": row["legal_name"],
        "usdot_number": row["usdot_number"],
        "base_jurisdiction_code": row["base_jurisdiction_code"],
        "bond_ceiling_amount": fnum(row["bond_ceiling_amount"], MONEY_SCALE),
        "ifta_license_status": row["ifta_license_status"],
        "irp_account_status": row["irp_account_status"],
        "tax_paid_gallons_ytd": fnum(row["tax_paid_gallons_ytd"], GALLON_SCALE),
        "unsubstantiated_mileage_ratio": fnum(row["unsubstantiated_mileage_ratio"], RATIO_SCALE),
        "audit_flag": row["audit_flag"],
        "latest_prepared_fleet_mpg": fnum(row["latest_prepared_fleet_mpg"], MONEY_SCALE),
        "suspension_count": row["suspension_count"],
    })
    return out


def jurisdiction_out(row):
    out = _light(row)
    out.update({
        "jurisdiction_code": row["jurisdiction_code"],
        "name": row["name"],
        "fuel_tax_rate_per_gallon": fnum(row["fuel_tax_rate_per_gallon"], RATE_SCALE),
        "surcharge_rate_per_gallon": fnum(row["surcharge_rate_per_gallon"], RATE_SCALE),
        "is_surcharge_jurisdiction": row["is_surcharge_jurisdiction"],
    })
    return out


def weight_group_fee_out(row):
    out = _light(row)
    out.update({
        "jurisdiction_code": row["jurisdiction_code"],
        "weight_group_code": row["weight_group_code"],
        "declared_weight_lbs": row["declared_weight_lbs"],
        "annual_fee_amount": fnum(row["annual_fee_amount"], MONEY_SCALE),
    })
    return out


def vehicle_out(row):
    out = _base(row)
    out.update({
        "carrier_id": row["carrier_id"],
        "unit_number": row["unit_number"],
        "vin": row["vin"],
        "weight_group_code": row["weight_group_code"],
        "factory_price_amount": fnum(row["factory_price_amount"], MONEY_SCALE),
        "registration_year": row["registration_year"],
        "vehicle_status": row["vehicle_status"],
        "credential_status": row["credential_status"],
        "replaced_vehicle_id": row["replaced_vehicle_id"],
        "activated_on_date": row["activated_on_date"],
    })
    return out


def driver_out(row):
    out = _base(row)
    out.update({
        "carrier_id": row["carrier_id"],
        "full_name": row["full_name"],
        "cdl_number": row["cdl_number"],
        "driver_status": row["driver_status"],
    })
    return out


def trip_record_out(row):
    out = _base(row)
    out.update({
        "carrier_id": row["carrier_id"],
        "vehicle_id": row["vehicle_id"],
        "trip_start_utc": row["trip_start_utc"],
        "trip_end_utc": row["trip_end_utc"],
        "start_odometer": fnum(row["start_odometer"], MILE_SCALE),
        "end_odometer": fnum(row["end_odometer"], MILE_SCALE),
        "odometer_delta_miles": fnum(row["odometer_delta_miles"], MILE_SCALE),
        "gap_miles_from_previous": fnum(row["gap_miles_from_previous"], MILE_SCALE),
        "mileage_source": row["mileage_source"],
        "trip_status": row["trip_status"],
        "reconstructed_by_user_id": row["reconstructed_by_user_id"],
        "supporting_document_reference": row["supporting_document_reference"],
        "accepted_leg_miles_total": fnum(row["accepted_leg_miles_total"], MILE_SCALE),
    })
    return out


def mileage_leg_out(row):
    out = _light(row)
    out.update({
        "trip_record_id": row["trip_record_id"],
        "jurisdiction_code": row["jurisdiction_code"],
        "leg_miles": fnum(row["leg_miles"], MILE_SCALE),
        "leg_sequence": row["leg_sequence"],
        "leg_status": row["leg_status"],
    })
    return out


def fuel_purchase_out(row):
    out = _base(row)
    out.update({
        "carrier_id": row["carrier_id"],
        "vehicle_id": row["vehicle_id"],
        "jurisdiction_code": row["jurisdiction_code"],
        "purchase_date": row["purchase_date"],
        "gallons": fnum(row["gallons"], GALLON_SCALE),
        "tax_paid_flag": row["tax_paid_flag"],
        "receipt_reference": row["receipt_reference"],
        "purchase_status": row["purchase_status"],
        "disallow_reason_code": row["disallow_reason_code"],
    })
    return out


def fuel_tax_return_out(row):
    out = _base(row)
    out.update({
        "carrier_id": row["carrier_id"],
        "filing_year": row["filing_year"],
        "filing_quarter": row["filing_quarter"],
        "settlement_basis": row["settlement_basis"],
        "return_status": row["return_status"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "filed_by_user_id": row["filed_by_user_id"],
        "total_fleet_miles": fnum(row["total_fleet_miles"], MILE_SCALE),
        "total_tax_paid_gallons": fnum(row["total_tax_paid_gallons"], GALLON_SCALE),
        "fleet_mpg": fnum(row["fleet_mpg"], MONEY_SCALE),
        "reconstructed_mileage_ratio": fnum(row["reconstructed_mileage_ratio"], RATIO_SCALE),
        "total_net_tax_due": fnum(row["total_net_tax_due"], MONEY_SCALE),
        "reconstruction_penalty_amount": fnum(row["reconstruction_penalty_amount"], MONEY_SCALE),
        "total_amount_due": fnum(row["total_amount_due"], MONEY_SCALE),
        "audit_assessment_delta": fnum(row["audit_assessment_delta"], MONEY_SCALE),
        "filed_at": row["filed_at"],
    })
    return out


def return_line_out(row):
    out = _light(row)
    out.update({
        "fuel_tax_return_id": row["fuel_tax_return_id"],
        "jurisdiction_code": row["jurisdiction_code"],
        "taxable_miles": fnum(row["taxable_miles"], MILE_SCALE),
        "taxable_gallons": fnum(row["taxable_gallons"], GALLON_SCALE),
        "tax_paid_gallons": fnum(row["tax_paid_gallons"], GALLON_SCALE),
        "net_taxable_gallons": fnum(row["net_taxable_gallons"], GALLON_SCALE),
        "base_tax_amount": fnum(row["base_tax_amount"], MONEY_SCALE),
        "surcharge_amount": fnum(row["surcharge_amount"], MONEY_SCALE),
        "net_tax_amount": fnum(row["net_tax_amount"], MONEY_SCALE),
        "line_status": row["line_status"],
    })
    return out


def registration_application_out(row):
    out = _base(row)
    out.update({
        "carrier_id": row["carrier_id"],
        "registration_year": row["registration_year"],
        "weight_group_code": row["weight_group_code"],
        "distance_basis": row["distance_basis"],
        "application_status": row["application_status"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "apportioned_vehicle_count": row["apportioned_vehicle_count"],
        "fleet_total_distance_miles": fnum(row["fleet_total_distance_miles"], MILE_SCALE),
        "base_fee_total": fnum(row["base_fee_total"], MONEY_SCALE),
        "total_apportioned_fee": fnum(row["total_apportioned_fee"], MONEY_SCALE),
        "apportion_frozen_at": row["apportion_frozen_at"],
    })
    return out


def schedule_line_out(row):
    out = _light(row)
    out.update({
        "registration_application_id": row["registration_application_id"],
        "jurisdiction_code": row["jurisdiction_code"],
        "reported_distance_miles": fnum(row["reported_distance_miles"], MILE_SCALE),
        "effective_distance_miles": fnum(row["effective_distance_miles"], MILE_SCALE),
        "apportion_percent": fnum(row["apportion_percent"], PERCENT_SCALE),
        "jurisdiction_fee_amount": fnum(row["jurisdiction_fee_amount"], MONEY_SCALE),
        "line_status": row["line_status"],
    })
    return out


def fleet_change_request_out(row):
    out = _base(row)
    out.update({
        "registration_application_id": row["registration_application_id"],
        "vehicle_id": row["vehicle_id"],
        "replaced_vehicle_id": row["replaced_vehicle_id"],
        "change_type": row["change_type"],
        "effective_date": row["effective_date"],
        "prorate_months": row["prorate_months"],
        "fee_delta": fnum(row["fee_delta"], MONEY_SCALE),
        "change_status": row["change_status"],
        "requested_by_user_id": row["requested_by_user_id"],
        "decided_by_user_id": row["decided_by_user_id"],
        "reversal_reason_code": row["reversal_reason_code"],
    })
    return out


def credential_out(row):
    out = _base(row)
    out.update({
        "vehicle_id": row["vehicle_id"],
        "registration_application_id": row["registration_application_id"],
        "distributed_to_driver_id": row["distributed_to_driver_id"],
        "credential_type": row["credential_type"],
        "registration_year": row["registration_year"],
        "valid_from_date": row["valid_from_date"],
        "valid_to_date": row["valid_to_date"],
        "credential_status": row["credential_status"],
        "distributed_at": row["distributed_at"],
        "voided_reason_code": row["voided_reason_code"],
    })
    return out


def audit_selection_out(row):
    out = _base(row)
    out.update({
        "carrier_id": row["carrier_id"],
        "selection_year": row["selection_year"],
        "selection_quarter": row["selection_quarter"],
        "late_filing_count": row["late_filing_count"],
        "retention_deficiency_count": row["retention_deficiency_count"],
        "risk_score": row["risk_score"],
        "post_review_risk_score": row["post_review_risk_score"],
        "expected_records_count": row["expected_records_count"],
        "records_missing_count": row["records_missing_count"],
        "retention_deficiency_ratio": fnum(row["retention_deficiency_ratio"], RATIO_SCALE),
        "selection_status": row["selection_status"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
    })
    return out
