"""Resource serialisation. Decimals are emitted as JSON numbers; dates and
instants use the formats pinned in PRD Section 2.4."""

from decimal import Decimal

from db import db
from services import calc


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _date(value):
    return value.isoformat() if value is not None else None


def _common(row):
    return {
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def building_out(row):
    out = {
        "id": row["id"],
        "name": row["name"],
        "total_rentable_sf": row["total_rentable_sf"],
        "market_base_rent_psf_annual": _num(row["market_base_rent_psf_annual"]),
        "operating_expense_annual_psf": _num(row["operating_expense_annual_psf"]),
        "total_parking_stalls": row["total_parking_stalls"],
        "patient_min_reserve_pct": _num(row["patient_min_reserve_pct"]),
        "anchor_rentable_sf": row["anchor_rentable_sf"],
        "independent_rentable_sf": row["independent_rentable_sf"],
        "leased_rentable_sf": row["leased_rentable_sf"],
        "vacant_rentable_sf": row["vacant_rentable_sf"],
        "anchor_share_pct": _num(row["anchor_share_pct"]),
        "tenant_mix_posture": row["tenant_mix_posture"],
        "mix_freeze_override": row["mix_freeze_override"],
        "staff_allocated_stalls": row["staff_allocated_stalls"],
        "patient_allocated_stalls": row["patient_allocated_stalls"],
        "unallocated_stalls": row["unallocated_stalls"],
    }
    out.update(_common(row))
    return out


def suite_out(row):
    out = {
        "id": row["id"],
        "building_id": row["building_id"],
        "suite_number": row["suite_number"],
        "floor": row["floor"],
        "rentable_sf": row["rentable_sf"],
        "suite_class": row["suite_class"],
        "power_amps_available": row["power_amps_available"],
        "medical_gas_available": row["medical_gas_available"],
        "shielding_certified": row["shielding_certified"],
        "lead_thickness_mm": _num(row["lead_thickness_mm"]),
        "occupancy_status": row["occupancy_status"],
        "last_vacated_on": _date(row["last_vacated_on"]),
    }
    out.update(_common(row))
    return out


def tenant_out(row):
    out = {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "affiliation": row["affiliation"],
        "primary_specialty": row["primary_specialty"],
        "is_physician_owned": row["is_physician_owned"],
        "npi": row["npi"],
        "delinquency_event_count": row["delinquency_event_count"],
        "referral_compliance_risk_score": row["referral_compliance_risk_score"],
        "strict_cumulative_risk_score": row["strict_cumulative_risk_score"],
        "compliance_watch_status": row["compliance_watch_status"],
    }
    out.update(_common(row))
    return out


def lease_out(row):
    out = {
        "id": row["id"],
        "building_id": row["building_id"],
        "suite_id": row["suite_id"],
        "tenant_id": row["tenant_id"],
        "lease_type": row["lease_type"],
        "master_lease_id": row["master_lease_id"],
        "status": row["status"],
        "term_start": _date(row["term_start"]),
        "term_end": _date(row["term_end"]),
        "term_months": row["term_months"],
        "base_rent_psf_annual": _num(row["base_rent_psf_annual"]),
        "provisional_base_rent_annual": _num(row["provisional_base_rent_annual"]),
        "certified_base_rent_annual": _num(row["certified_base_rent_annual"]),
        "effective_base_rent_annual": _num(row["effective_base_rent_annual"]),
        "fmv_certification_status": row["fmv_certification_status"],
        "certified_fmv_floor_psf": _num(row["certified_fmv_floor_psf"]),
        "certified_fmv_ceiling_psf": _num(row["certified_fmv_ceiling_psf"]),
        "fmv_variance_annual": _num(row["fmv_variance_annual"]),
        "fmv_variance_pct": _num(row["fmv_variance_pct"]),
        "fmv_submitted_by_user_id": row["fmv_submitted_by_user_id"],
        "exclusive_use_specialty": row["exclusive_use_specialty"],
        "radius_restriction_miles": _num(row["radius_restriction_miles"]),
        "signed_lease_on_file": row["signed_lease_on_file"],
        "master_lease_consent_on_file": row["master_lease_consent_on_file"],
        "space_sharing_schedule_on_file": row["space_sharing_schedule_on_file"],
        "after_hours_authorized": row["after_hours_authorized"],
        "rent_concession_locked": row["rent_concession_locked"],
        "holdover_premium_applied": row["holdover_premium_applied"],
        "revision_round": row["revision_round"],
        "termination_reason": row["termination_reason"],
        "terminated_on": _date(row["terminated_on"]),
    }
    out.update(_common(row))
    return out


def appraisal_out(row):
    out = {
        "id": row["id"],
        "lease_id": row["lease_id"],
        "appraiser_firm": row["appraiser_firm"],
        "appraisal_date": _date(row["appraisal_date"]),
        "expires_on": _date(row["expires_on"]),
        "opinion_low_psf": _num(row["opinion_low_psf"]),
        "opinion_high_psf": _num(row["opinion_high_psf"]),
        "opinion_midpoint_psf": _num(row["opinion_midpoint_psf"]),
        "independence_attested": row["independence_attested"],
        "status": row["status"],
        "is_controlling": row["is_controlling"],
        "decision_reason": row["decision_reason"],
    }
    out.update(_common(row))
    return out


def ti_project_out(row):
    out = {
        "id": row["id"],
        "lease_id": row["lease_id"],
        "suite_id": row["suite_id"],
        "target_suite_class": row["target_suite_class"],
        "status": row["status"],
        "shielding_review_status": row["shielding_review_status"],
        "utility_review_status": row["utility_review_status"],
        "lead_thickness_mm": _num(row["lead_thickness_mm"]),
        "power_amps_requested": row["power_amps_requested"],
        "power_amps_drawn": row["power_amps_drawn"],
        "medical_gas_requested": row["medical_gas_requested"],
        "authorized_allowance_total": _num(row["authorized_allowance_total"]),
        "landlord_share_pct": _num(row["landlord_share_pct"]),
        "landlord_committed_amount": _num(row["landlord_committed_amount"]),
        "tenant_committed_amount": _num(row["tenant_committed_amount"]),
        "allowance_remaining": _num(row["allowance_remaining"]),
        "line_item_count": row["line_item_count"],
        "on_hold_from_status": row["on_hold_from_status"],
    }
    out.update(_common(row))
    return out


def ti_line_item_out(row):
    # A line item is immutable: it carries only id and created_at.
    return {
        "id": row["id"],
        "ti_project_id": row["ti_project_id"],
        "sequence_no": row["sequence_no"],
        "description": row["description"],
        "category": row["category"],
        "cost_amount": _num(row["cost_amount"]),
        "landlord_share_pct_override": _num(row["landlord_share_pct_override"]),
        "effective_share_pct": _num(row["effective_share_pct"]),
        "landlord_share_amount": _num(row["landlord_share_amount"]),
        "tenant_share_amount": _num(row["tenant_share_amount"]),
        "created_at": row["created_at"],
    }


def rent_invoice_out(row):
    out = {
        "id": row["id"],
        "lease_id": row["lease_id"],
        "period_start": _date(row["period_start"]),
        "period_end": _date(row["period_end"]),
        "due_date": _date(row["due_date"]),
        "status": row["status"],
        "base_rent_amount": _num(row["base_rent_amount"]),
        "cam_amount": _num(row["cam_amount"]),
        "parking_fee_gross": _num(row["parking_fee_gross"]),
        "pre_waiver_total": _num(row["pre_waiver_total"]),
        "parking_waiver_tier_pct": _num(row["parking_waiver_tier_pct"]),
        "parking_waiver_amount": _num(row["parking_waiver_amount"]),
        "total_amount": _num(row["total_amount"]),
        "amount_paid": _num(row["amount_paid"]),
        "paid_on": _date(row["paid_on"]),
        # days_past_due is live rather than stored: it is recomputed against the
        # clock on every read, so it grows even on days when no close has run
        # (PRD Section 2.10), and it never reads below zero (PRD Section 3.7).
        "days_past_due": max(0, calc.live_days_past_due(row)),
        "days_past_due_at_flag": row["days_past_due_at_flag"],
        "delinquency_tier_weight": row["delinquency_tier_weight"],
        "write_off_justification": row["write_off_justification"],
        "written_off_by_user_id": row["written_off_by_user_id"],
    }
    out.update(_common(row))
    return out


def compliance_case_out(row):
    out = {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "case_type": row["case_type"],
        "basis": row["basis"],
        "status": row["status"],
        "severity": row["severity"],
        "scoring_variant": row["scoring_variant"],
        "risk_score_at_open": row["risk_score_at_open"],
        "opened_on": _date(row["opened_on"]),
        "opened_by_user_id": row["opened_by_user_id"],
        "reopen_count": row["reopen_count"],
        "remediation_summary": row["remediation_summary"],
        "remediation_due_on": _date(row["remediation_due_on"]),
        "report_reference": row["report_reference"],
        "closed_on": _date(row["closed_on"]),
    }
    out.update(_common(row))
    return out


def shared_space_out(row):
    out = {
        "id": row["id"],
        "building_id": row["building_id"],
        "name": row["name"],
        "space_type": row["space_type"],
        "capacity_seats": row["capacity_seats"],
        "opens_at": row["opens_at_raw"],
        "closes_at": row["closes_at_raw"],
    }
    out.update(_common(row))
    return out


def booking_out(row):
    out = {
        "id": row["id"],
        "shared_space_id": row["shared_space_id"],
        "lease_id": row["lease_id"],
        "window_start": row["window_start_raw"],
        "window_end": row["window_end_raw"],
        "occupant_count": row["occupant_count"],
        "is_after_hours": row["is_after_hours"],
        "status": row["status"],
        "cancellation_source": row["cancellation_source"],
    }
    out.update(_common(row))
    return out


def parking_allocation_out(row):
    out = {
        "id": row["id"],
        "building_id": row["building_id"],
        "lease_id": row["lease_id"],
        "category": row["category"],
        "stall_count": row["stall_count"],
        "status": row["status"],
        "revoked_on": _date(row["revoked_on"]),
    }
    out.update(_common(row))
    return out

