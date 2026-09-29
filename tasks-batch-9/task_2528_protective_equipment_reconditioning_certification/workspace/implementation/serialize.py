"""Entity serializers — one per entity, explicit field lists (PRD 2.3)."""
from util import iso, num_out


def _dt(record, field):
    """Datetimes supplied by the caller echo back verbatim; derived ones are ISO."""
    raw = record.get("_raw") or {}
    if field in raw:
        return raw[field]
    value = record.get(field)
    return iso(value) if value is not None else None


def _common(record, versioned=True):
    out = {
        "id": record["id"],
        "created_at": iso(record["created_at"]),
    }
    if versioned:
        out["updated_at"] = iso(record["updated_at"])
        out["version"] = record["version"]
    return out


def customer_account(record):
    out = {
        "org_name": record["org_name"],
        "org_type": record["org_type"],
        "sport": record["sport"],
        "contact_email": record["contact_email"],
        "status": record["status"],
        "billing_hold_reason": record["billing_hold_reason"],
        "liability_waiver_version": record["liability_waiver_version"],
        "liability_waiver_signed_at": _dt(record, "liability_waiver_signed_at"),
        "liability_waiver_signer": record["liability_waiver_signer"],
        "liability_waiver_status": record["liability_waiver_status"],
        "open_shipment_count": record["open_shipment_count"],
        "loaner_recall_due_at": _dt(record, "loaner_recall_due_at"),
    }
    out.update(_common(record))
    return out


def model_spec(record):
    out = {
        "manufacturer": record["manufacturer"],
        "model_code": record["model_code"],
        "standard_code": record["standard_code"],
        "shell_material": record["shell_material"],
        "max_service_life_years": record["max_service_life_years"],
        "warranty_years": record["warranty_years"],
        "record_retention_years": record["record_retention_years"],
        "pass_si_max": num_out(record["pass_si_max"]),
        "repair_si_max": num_out(record["repair_si_max"]),
        "max_retest_count": record["max_retest_count"],
        "reconditionable": record["reconditionable"],
        "required_component_codes": list(record["required_component_codes"]),
        "component_criteria": record["component_criteria"],
    }
    out.update(_common(record))
    return out


def approved_part(record):
    out = {
        "model_spec_id": record["model_spec_id"],
        "part_number": record["part_number"],
        "component_code": record["component_code"],
        "oem_approved": record["oem_approved"],
        "unit_price_cents": record["unit_price_cents"],
        "received_qty": record["received_qty"],
        "on_hand_qty": record["on_hand_qty"],
        "reserved_qty": record["reserved_qty"],
        "consumed_qty": record["consumed_qty"],
    }
    out.update(_common(record))
    return out


def test_bench(record):
    out = {
        "bench_code": record["bench_code"],
        "test_type": record["test_type"],
        "cooldown_minutes": record["cooldown_minutes"],
        "daily_session_quota": record["daily_session_quota"],
        "calibration_valid_until": _dt(record, "calibration_valid_until"),
    }
    out.update(_common(record))
    return out


def loaner_unit(record):
    out = {
        "model_spec_id": record["model_spec_id"],
        "asset_tag": record["asset_tag"],
        "condition_grade": record["condition_grade"],
        "certification_valid_until": _dt(record, "certification_valid_until"),
        "assignment_count": record["assignment_count"],
        "status": record["status"],
    }
    out.update(_common(record))
    return out


def intake_shipment(record):
    out = {
        "customer_account_id": record["customer_account_id"],
        "sport": record["sport"],
        "service_tier": record["service_tier"],
        "declared_unit_count": record["declared_unit_count"],
        "season_start_date": _dt(record, "season_start_date"),
        "season_end_date": _dt(record, "season_end_date"),
        "counted_unit_count": record["counted_unit_count"],
        "discrepancy_count": record["discrepancy_count"],
        "discrepancy_resolution": record["discrepancy_resolution"],
        "units_registered": record["units_registered"],
        "units_in_process": record["units_in_process"],
        "units_certified": record["units_certified"],
        "units_condemned": record["units_condemned"],
        "units_released": record["units_released"],
        "accepted_at": _dt(record, "accepted_at"),
        "raw_due_at": _dt(record, "raw_due_at"),
        "committed_due_at": _dt(record, "committed_due_at"),
        "loaner_required": record["loaner_required"],
        "provisional_total_cents": record["provisional_total_cents"],
        "final_total_cents": record["final_total_cents"],
        "settlement_locked": record["settlement_locked"],
        "status": record["status"],
    }
    out.update(_common(record))
    return out


def equipment_unit(record):
    out = {
        "intake_shipment_id": record["intake_shipment_id"],
        "serial_number": record["serial_number"],
        "declared_model_code": record["declared_model_code"],
        "model_spec_id": record["model_spec_id"],
        "manufacture_date": _dt(record, "manufacture_date"),
        "age_basis": record["age_basis"],
        "service_age_years": record["service_age_years"],
        "life_expired": record["life_expired"],
        "inspection_verdict_summary": record["inspection_verdict_summary"],
        "condemn_required": record["condemn_required"],
        "warranty_coverage": record["warranty_coverage"],
        "retest_count": record["retest_count"],
        "current_si": num_out(record["current_si"]),
        "certified_at": _dt(record, "certified_at"),
        "record_retention_until": _dt(record, "record_retention_until"),
        "records_purged_at": _dt(record, "records_purged_at"),
        "condemn_reason": record["condemn_reason"],
        "recon_status": record["recon_status"],
        "custody_status": record["custody_status"],
        "released_to": record["released_to"],
    }
    out.update(_common(record))
    return out


def component_inspection(record):
    out = {
        "equipment_unit_id": record["equipment_unit_id"],
        "component_code": record["component_code"],
        "measurement_value": num_out(record["measurement_value"]),
        "measurement_unit": record["measurement_unit"],
        "note": record["note"],
        "replace_threshold_applied": num_out(record["replace_threshold_applied"]),
        "fail_threshold_applied": num_out(record["fail_threshold_applied"]),
        "metric_direction_applied": record["metric_direction_applied"],
        "verdict": record["verdict"],
        "inspector_user_id": record["inspector_user_id"],
    }
    out.update(_common(record, versioned=False))
    return out


def shell_test(record):
    out = {
        "equipment_unit_id": record["equipment_unit_id"],
        "test_bench_id": record["test_bench_id"],
        "window_start": _dt(record, "window_start"),
        "window_end": _dt(record, "window_end"),
        "conditioning": record["conditioning"],
        "attempt_index": record["attempt_index"],
        "peak_g_front": num_out(record["peak_g_front"]),
        "peak_g_side": num_out(record["peak_g_side"]),
        "peak_g_crown": num_out(record["peak_g_crown"]),
        "severity_index": num_out(record["severity_index"]),
        "computed_result": record["computed_result"],
        "determination": record["determination"],
        "override_reason": record["override_reason"],
        "determined_by_user_id": record["determined_by_user_id"],
        "status": record["status"],
    }
    out.update(_common(record))
    return out


def part_line(line):
    return {
        "line_index": line["line_index"],
        "approved_part_id": line["approved_part_id"],
        "part_number": line["part_number"],
        "component_code": line["component_code"],
        "quantity": line["quantity"],
        "lot_code": line["lot_code"],
        "oem_cert_ref": line["oem_cert_ref"],
        "unit_price_cents_snapshot": line["unit_price_cents_snapshot"],
        "line_total_cents": line["line_total_cents"],
        "status": line["status"],
    }


def repair_order(record):
    out = {
        "equipment_unit_id": record["equipment_unit_id"],
        "part_lines": [part_line(line) for line in record["part_lines"]],
        "reserved_parts_cents": record["reserved_parts_cents"],
        "installed_parts_cents": record["installed_parts_cents"],
        "labor_cents": record["labor_cents"],
        "warranty_claim_ref": record["warranty_claim_ref"],
        "verification_failure_count": record["verification_failure_count"],
        "opened_by_user_id": record["opened_by_user_id"],
        "installed_by_user_id": record["installed_by_user_id"],
        "verified_by_user_id": record["verified_by_user_id"],
        "cancel_reason": record["cancel_reason"],
        "status": record["status"],
    }
    out.update(_common(record))
    return out


def certification_label(record):
    out = {
        "equipment_unit_id": record["equipment_unit_id"],
        "label_code": record["label_code"],
        "standard_code_snapshot": record["standard_code_snapshot"],
        "certified_on": _dt(record, "certified_on"),
        "daily_sequence": record["daily_sequence"],
        "issued_by_user_id": record["issued_by_user_id"],
        "void_reason": record["void_reason"],
        "voided_at": _dt(record, "voided_at"),
        "voided_by_user_id": record["voided_by_user_id"],
        "status": record["status"],
    }
    out.update(_common(record))
    return out


def destruction_record(record):
    out = {
        "equipment_unit_id": record["equipment_unit_id"],
        "condemn_reason_snapshot": record["condemn_reason_snapshot"],
        "method": record["method"],
        "witness_name": record["witness_name"],
        "witnessed_by_user_id": record["witnessed_by_user_id"],
        "witnessed_at": _dt(record, "witnessed_at"),
        "verification_ref": record["verification_ref"],
        "verified_by_user_id": record["verified_by_user_id"],
        "verified_at": _dt(record, "verified_at"),
        "status": record["status"],
    }
    out.update(_common(record))
    return out


def loaner_assignment(record):
    out = {
        "customer_account_id": record["customer_account_id"],
        "requested_model_spec_id": record["requested_model_spec_id"],
        "loaner_unit_id": record["loaner_unit_id"],
        "window_start": _dt(record, "window_start"),
        "window_end": _dt(record, "window_end"),
        "selected_by": record["selected_by"],
        "returned_at": _dt(record, "returned_at"),
        "status": record["status"],
    }
    out.update(_common(record))
    return out
