"""Row -> JSON projections.  Internal bookkeeping keys (prefixed with '_') are
never exposed, and the two derived fields are computed at serialization time."""

from store import fmt_dt


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "updated_at": fmt_dt(row["updated_at"]),
        "version": row["version"],
    }


def _event(row):
    return {"id": row["id"], "created_at": fmt_dt(row["created_at"])}


def prescriber(row):
    import services

    out = _common(row)
    out.update(
        {
            "npi": row["npi"],
            "full_name": row["full_name"],
            "license_state": row["license_state"],
            "max_rx_validity_months": row["max_rx_validity_months"],
            "status": row["status"],
            "verified_rx_count": services.verified_rx_count(row["id"]),
        }
    )
    return out


def prescription(row):
    out = _common(row)
    out.update(
        {
            "prescriber_id": row["prescriber_id"],
            "patient_id": row["patient_id"],
            "prescriber_npi_claimed": row["prescriber_npi_claimed"],
            "prescriber_license_state_claimed": row["prescriber_license_state_claimed"],
            "sphere_od": row["sphere_od"],
            "sphere_os": row["sphere_os"],
            "cylinder_od": row["cylinder_od"],
            "cylinder_os": row["cylinder_os"],
            "axis_od": row["axis_od"],
            "axis_os": row["axis_os"],
            "add_power_od": row["add_power_od"],
            "add_power_os": row["add_power_os"],
            "prism_diopter_od": row["prism_diopter_od"],
            "prism_diopter_os": row["prism_diopter_os"],
            "pd_distance_mm": row["pd_distance_mm"],
            "issued_on": row["issued_on"],
            "expires_at": fmt_dt(row["expires_at"]),
            "verification_status": row["verification_status"],
            "verification_note": row["verification_note"],
            "verified_at": fmt_dt(row["verified_at"]),
            "requires_multifocal": row["requires_multifocal"],
            "resubmit_count": row["resubmit_count"],
        }
    )
    return out


def patient(row):
    import services

    out = _common(row)
    out.update(
        {
            "full_name": row["full_name"],
            "date_of_birth": row["date_of_birth"],
            "insurance_plan_id": row["insurance_plan_id"],
            "member_number": row["member_number"],
            "benefit_period_start": row["benefit_period_start"],
            "benefit_used_cents": services.benefit_used_cents(row),
            "status": row["status"],
        }
    )
    return out


def insurance_plan(row):
    out = _common(row)
    out.update(
        {
            "plan_code": row["plan_code"],
            "frame_allowance_cents": row["frame_allowance_cents"],
            "lens_base_allowance_cents": row["lens_base_allowance_cents"],
            "coating_allowance_cents": row["coating_allowance_cents"],
            "progressive_copay_cents": row["progressive_copay_cents"],
            "coinsurance_pct": row["coinsurance_pct"],
            "annual_benefit_cap_cents": row["annual_benefit_cap_cents"],
            "expedite_covered": row["expedite_covered"],
            "specialty_requires_prior_auth": row["specialty_requires_prior_auth"],
        }
    )
    return out


def lens_design(row):
    out = _common(row)
    out.update(
        {
            "design_code": row["design_code"],
            "design_type": row["design_type"],
            "material": row["material"],
            "allowed_coatings": list(row["allowed_coatings"]),
            "retail_price_cents": row["retail_price_cents"],
            "min_fitting_height_mm": row["min_fitting_height_mm"],
            "min_blank_diameter_mm": row["min_blank_diameter_mm"],
            "product_tier": row["product_tier"],
            "stock_sku_available": row["stock_sku_available"],
            "base_curve": row["base_curve"],
        }
    )
    return out


def tolerance_standard(row):
    out = _common(row)
    out.update(
        {
            "design_type": row["design_type"],
            "power_band_min_abs": row["power_band_min_abs"],
            "power_band_max_abs": row["power_band_max_abs"],
            "sphere_tolerance_diopters": row["sphere_tolerance_diopters"],
            "cylinder_tolerance_diopters": row["cylinder_tolerance_diopters"],
            "axis_tolerance_degrees": row["axis_tolerance_degrees"],
            "prism_tolerance_pd": row["prism_tolerance_pd"],
            "allowed_cosmetic_defect_codes": list(row["allowed_cosmetic_defect_codes"]),
            "effective_from": row["effective_from"],
        }
    )
    return out


def lens_blank_lot(row):
    out = _common(row)
    out.update(
        {
            "lens_design_id": row["lens_design_id"],
            "blank_sku": row["blank_sku"],
            "diameter_mm": row["diameter_mm"],
            "received_qty": row["received_qty"],
            "on_hand_qty": row["on_hand_qty"],
            "allocated_qty": row["allocated_qty"],
            "consumed_qty": row["consumed_qty"],
            "scrapped_qty": row["scrapped_qty"],
            "status": row["status"],
            "received_on": row["received_on"],
        }
    )
    return out


def rx_order(row):
    out = _common(row)
    out.update(
        {
            "patient_id": row["patient_id"],
            "prescription_id": row["prescription_id"],
            "lens_design_id": row["lens_design_id"],
            "frame_sku": row["frame_sku"],
            "frame_retail_cents": row["frame_retail_cents"],
            "requested_coatings": list(row["requested_coatings"]),
            "monocular_pd_od_mm": row["monocular_pd_od_mm"],
            "monocular_pd_os_mm": row["monocular_pd_os_mm"],
            "fitting_height_mm": row["fitting_height_mm"],
            "expedite_requested": row["expedite_requested"],
            "prior_auth_reference": row["prior_auth_reference"],
            "product_tier": row["product_tier"],
            "fulfillment_status": row["fulfillment_status"],
            "billing_status": row["billing_status"],
            "quote_variant": row["quote_variant"],
            "gross_charge_cents": row["gross_charge_cents"],
            "estimated_benefit_cents": row["estimated_benefit_cents"],
            "insurance_benefit_cents": row["insurance_benefit_cents"],
            "patient_portion_cents": row["patient_portion_cents"],
            "lab_writeoff_cents": row["lab_writeoff_cents"],
            "patient_paid_cents": row["patient_paid_cents"],
            "expedite_fee_cents": row["expedite_fee_cents"],
            "patient_balance_due_cents": row["patient_portion_cents"] - row["patient_paid_cents"],
            "promised_tat_hours": row["promised_tat_hours"],
            "promised_due_at": fmt_dt(row["promised_due_at"]),
            "tat_commitment_status": row["tat_commitment_status"],
            "remake_count": row["remake_count"],
            "benefit_applied_at": fmt_dt(row["benefit_applied_at"]),
            "created_by_optician_id": row["created_by_optician_id"],
        }
    )
    return out


def frame_layout(row):
    out = _common(row)
    out.update(
        {
            "rx_order_id": row["rx_order_id"],
            "trace_source": row["trace_source"],
            "a_mm": row["a_mm"],
            "b_mm": row["b_mm"],
            "ed_mm": row["ed_mm"],
            "dbl_mm": row["dbl_mm"],
            "fitting_height_override_mm": row["fitting_height_override_mm"],
            "effective_fitting_height_mm": row["effective_fitting_height_mm"],
            "decentration_h_od_mm": row["decentration_h_od_mm"],
            "decentration_h_os_mm": row["decentration_h_os_mm"],
            "decentration_v_mm": row["decentration_v_mm"],
            "required_blank_diameter_mm": row["required_blank_diameter_mm"],
            "layout_status": row["layout_status"],
        }
    )
    return out


def lab_job(row):
    out = _common(row)
    out.update(
        {
            "rx_order_id": row["rx_order_id"],
            "frame_layout_id": row["frame_layout_id"],
            "blank_lot_id": row["blank_lot_id"],
            "route": row["route"],
            "status": row["status"],
            "rework_cycle_count": row["rework_cycle_count"],
            "breakage_count": row["breakage_count"],
            "released_at": fmt_dt(row["released_at"]),
            "scrap_reason": row["scrap_reason"],
        }
    )
    return out


def lab_machine(row):
    out = _common(row)
    out.update(
        {
            "machine_code": row["machine_code"],
            "machine_type": row["machine_type"],
            "calibration_buffer_minutes": row["calibration_buffer_minutes"],
            "status": row["status"],
        }
    )
    return out


def finishing_bay(row):
    out = _common(row)
    out.update(
        {
            "bay_code": row["bay_code"],
            "concurrent_capacity": row["concurrent_capacity"],
            "status": row["status"],
        }
    )
    return out


def lab_operation(row):
    out = _common(row)
    out.update(
        {
            "lab_job_id": row["lab_job_id"],
            "machine_id": row["machine_id"],
            "bay_id": row["bay_id"],
            "blank_lot_id": row["blank_lot_id"],
            "operation_type": row["operation_type"],
            "window_start": fmt_dt(row["window_start"]),
            "window_end": fmt_dt(row["window_end"]),
            "status": row["status"],
            "performed_by_user_id": row["performed_by_user_id"],
            "breakage_reason": row["breakage_reason"],
            "cancel_reason": row["cancel_reason"],
        }
    )
    return out


def quality_inspection(row):
    out = _event(row)
    out.update(
        {
            "lab_job_id": row["lab_job_id"],
            "tolerance_standard_id": row["tolerance_standard_id"],
            "eye": row["eye"],
            "measured_sphere": row["measured_sphere"],
            "measured_cylinder": row["measured_cylinder"],
            "measured_axis": row["measured_axis"],
            "measured_prism": row["measured_prism"],
            "cosmetic_defect_codes": list(row["cosmetic_defect_codes"]),
            "inspector_user_id": row["inspector_user_id"],
            "cycle_index": row["cycle_index"],
            "sphere_delta": row["sphere_delta"],
            "cylinder_delta": row["cylinder_delta"],
            "axis_delta": row["axis_delta"],
            "prism_delta": row["prism_delta"],
            "verdict": row["verdict"],
            "failed_metrics": list(row["failed_metrics"]),
        }
    )
    return out


def remake_case(row):
    out = _common(row)
    out.update(
        {
            "lab_job_id": row["lab_job_id"],
            "quality_inspection_id": row["quality_inspection_id"],
            "defect_codes": list(row["defect_codes"]),
            "warranty_claim": row["warranty_claim"],
            "warranty_covered": row["warranty_covered"],
            "responsibility": row["responsibility"],
            "adjudication_method": row["adjudication_method"],
            "lab_share_pct": row["lab_share_pct"],
            "lab_chargeback_cents": row["lab_chargeback_cents"],
            "status": row["status"],
        }
    )
    return out


def settlement_entry(row):
    out = _event(row)
    out.update(
        {
            "rx_order_id": row["rx_order_id"],
            "entry_type": row["entry_type"],
            "amount_cents": row["amount_cents"],
            "memo": row["memo"],
            "effective_at": fmt_dt(row["effective_at"]),
        }
    )
    return out
