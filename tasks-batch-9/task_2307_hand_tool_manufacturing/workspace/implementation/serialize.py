"""Resource serializers. Numbers become JSON numbers, datetimes ISO-8601 UTC."""

from calculations import num
from envelope import iso_ms


def sku_out(row):
    return {
        "id": row["id"],
        "sku_code": row["sku_code"],
        "tool_family": row["tool_family"],
        "channel": row["channel"],
        "nominal_size_mm": row["nominal_size_mm"],
        "alloy_grade": row["alloy_grade"],
        "list_price_cents": row["list_price_cents"],
        "warranty_tier": row["warranty_tier"],
        "supersedes_sku_id": row["supersedes_sku_id"],
        "lineage_depth": row["lineage_depth"],
        "proof_torque_required_nm": num(row["proof_torque_required_nm"]),
        "brand_risk_score": row["brand_risk_score"],
        "warranty_posture": row["warranty_posture"],
        "confirmed_counterfeit_count": row["confirmed_counterfeit_count"],
        "units_received_total": row["units_received_total"],
        "units_on_hand": row["units_on_hand"],
        "units_reserved": row["units_reserved"],
        "units_shipped": row["units_shipped"],
        "created_at": iso_ms(row["created_at"]),
        "updated_at": iso_ms(row["updated_at"]),
        "version": row["version"],
    }


def lot_out(row):
    return {
        "id": row["id"],
        "sku_id": row["sku_id"],
        "lot_code": row["lot_code"],
        "unit_count": row["unit_count"],
        "specimen_pool_total": row["specimen_pool_total"],
        "specimens_available": row["specimens_available"],
        "specimens_committed": row["specimens_committed"],
        "specimens_consumed": row["specimens_consumed"],
        "process_status": row["process_status"],
        "cert_status": row["cert_status"],
        "disposition": row["disposition"],
        "hardness_index_sample": num(row["hardness_index_sample"]),
        "hardness_index_pooled": num(row["hardness_index_pooled"]),
        "proof_torque_required_nm": num(row["proof_torque_required_nm"]),
        "rework_cycle_count": row["rework_cycle_count"],
        "certified_at": iso_ms(row["certified_at"]) if row["certified_at"] else None,
        "created_at": iso_ms(row["created_at"]),
        "updated_at": iso_ms(row["updated_at"]),
        "version": row["version"],
    }


def furnace_out(row):
    return {
        "id": row["id"],
        "furnace_code": row["furnace_code"],
        "max_charge_kg": row["max_charge_kg"],
        "alloy_grades_supported": list(row["alloy_grades_supported"]),
        "status": row["status"],
        "created_at": iso_ms(row["created_at"]),
        "updated_at": iso_ms(row["updated_at"]),
        "version": row["version"],
    }


def campaign_out(row):
    return {
        "id": row["id"],
        "lot_id": row["lot_id"],
        "furnace_id": row["furnace_id"],
        "window_start": row["window_start_raw"],
        "window_end": row["window_end_raw"],
        "charge_kg": row["charge_kg"],
        "buffered_end": iso_ms(row["buffered_end"]),
        "soak_minutes": row["soak_minutes"],
        "status": row["status"],
        "created_at": iso_ms(row["created_at"]),
        "updated_at": iso_ms(row["updated_at"]),
        "version": row["version"],
    }


def chamber_out(row):
    return {
        "id": row["id"],
        "chamber_code": row["chamber_code"],
        "coupon_capacity": row["coupon_capacity"],
        "created_at": iso_ms(row["created_at"]),
        "updated_at": iso_ms(row["updated_at"]),
        "version": row["version"],
    }


def run_out(row):
    readings = row["readings"]
    return {
        "id": row["id"],
        "lot_id": row["lot_id"],
        "chamber_id": row["chamber_id"],
        "test_type": row["test_type"],
        "specimen_count": row["specimen_count"],
        "window_start": row["window_start_raw"],
        "window_end": row["window_end_raw"],
        "mandatory": row["mandatory"],
        "readings": list(readings) if readings is not None else None,
        "mean_reading": num(row["mean_reading"]),
        "governing_statistic": num(row["governing_statistic"]),
        "requirement_value": num(row["requirement_value"]),
        "result_margin_pct": num(row["result_margin_pct"]),
        "status": row["status"],
        "void_reason": row["void_reason"],
        "created_at": iso_ms(row["created_at"]),
        "updated_at": iso_ms(row["updated_at"]),
        "version": row["version"],
    }


def pack_out(row):
    return {
        "id": row["id"],
        "pack_code": row["pack_code"],
        "pack_type": row["pack_type"],
        "primary_sku_id": row["primary_sku_id"],
        "member_subtotal_cents": row["member_subtotal_cents"],
        "security_surcharge_cents": row["security_surcharge_cents"],
        "pack_total_cents": row["pack_total_cents"],
        "distinct_member_count": row["distinct_member_count"],
        "status": row["status"],
        "created_at": iso_ms(row["created_at"]),
        "updated_at": iso_ms(row["updated_at"]),
        "version": row["version"],
    }


def pack_member_out(row):
    return {
        "id": row["id"],
        "pack_id": row["pack_id"],
        "sku_id": row["sku_id"],
        "quantity": row["quantity"],
        "line_extended_cents": row["line_extended_cents"],
        "created_at": iso_ms(row["created_at"]),
    }


def program_out(row):
    return {
        "id": row["id"],
        "program_code": row["program_code"],
        "reserve_funded_cents": row["reserve_funded_cents"],
        "fraud_score_threshold": row["fraud_score_threshold"],
        "reserve_balance_cents": row["reserve_balance_cents"],
        "open_hold_count": row["open_hold_count"],
        "created_at": iso_ms(row["created_at"]),
        "updated_at": iso_ms(row["updated_at"]),
        "version": row["version"],
    }


def claimant_out(row):
    return {
        "id": row["id"],
        "email": row["email"],
        "claimant_type": row["claimant_type"],
        "status": row["status"],
        "fraud_risk_score_intake": row["fraud_risk_score_intake"],
        "fraud_risk_score_adjudication": row["fraud_risk_score_adjudication"],
        "lifetime_claim_count": row["lifetime_claim_count"],
        "created_at": iso_ms(row["created_at"]),
        "updated_at": iso_ms(row["updated_at"]),
        "version": row["version"],
    }


def claim_out(row):
    return {
        "id": row["id"],
        "claimant_id": row["claimant_id"],
        "sku_id": row["sku_id"],
        "program_id": row["program_id"],
        "serial_code": row["serial_code"],
        "claim_reason": row["claim_reason"],
        "status": row["status"],
        "fraud_score_at_intake": row["fraud_score_at_intake"],
        "reserve_charge_cents": row["reserve_charge_cents"],
        "replacement_unit_count": row["replacement_unit_count"],
        "line_count": row["line_count"],
        "hold_reason": row["hold_reason"],
        "held_by_user_id": row["held_by_user_id"],
        "fraud_cleared": row["fraud_cleared"],
        "denial_code": row["denial_code"],
        "shipment_ref": row["shipment_ref"],
        "revocation_reason": row["revocation_reason"],
        "created_at": iso_ms(row["created_at"]),
        "updated_at": iso_ms(row["updated_at"]),
        "version": row["version"],
    }


def claim_line_out(row):
    return {
        "id": row["id"],
        "claim_id": row["claim_id"],
        "component_code": row["component_code"],
        "component_list_price_cents": row["component_list_price_cents"],
        "quantity": row["quantity"],
        "line_reserve_cents": row["line_reserve_cents"],
        "created_at": iso_ms(row["created_at"]),
    }


def report_out(row):
    return {
        "id": row["id"],
        "sku_id": row["sku_id"],
        "channel_name": row["channel_name"],
        "seller_handle": row["seller_handle"],
        "evidence_grade": row["evidence_grade"],
        "unit_estimate": row["unit_estimate"],
        "risk_points": row["risk_points"],
        "status": row["status"],
        "confirmation_note": row["confirmation_note"],
        "dismissal_note": row["dismissal_note"],
        "created_at": iso_ms(row["created_at"]),
        "updated_at": iso_ms(row["updated_at"]),
        "version": row["version"],
    }
