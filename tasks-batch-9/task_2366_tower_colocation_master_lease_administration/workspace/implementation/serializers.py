"""Explicit per-entity JSON projections."""
import services
from util import iso, num


def _date(record, field):
    """Calendar-date fields echo the caller's own rendering when there is one."""
    raw = record.get("_date_raw", {}).get(field)
    if raw is not None:
        return raw
    value = record.get(field)
    if value is None:
        return None
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def _common(record):
    return {
        "id": record["id"],
        "created_at": iso(record["created_at"]),
        "updated_at": iso(record["updated_at"]),
        "version": record["version"],
    }


def tower(record):
    out = {
        "site_name": record["site_name"],
        "structure_type": record["structure_type"],
        "rated_capacity_load_units": num(record["rated_capacity_load_units"]),
        "min_colocation_elevation_ft": num(record["min_colocation_elevation_ft"]),
        "max_elevation_ft": num(record["max_elevation_ft"]),
        "ground_space_total_sqft": num(record["ground_space_total_sqft"]),
        "baseline_reserved_load_units": num(record["baseline_reserved_load_units"]),
        "baseline_reserved_ground_sqft": num(record["baseline_reserved_ground_sqft"]),
        "reserved_load_units": num(services.tower_reserved_load_units(record)),
        "reserved_load_pct": num(services.tower_reserved_load_pct(record)),
        "reserved_ground_space_sqft": num(services.tower_reserved_ground_space(record)),
        "available_ground_space_sqft": num(services.tower_available_ground_space(record)),
        "capacity_posture": services.tower_capacity_posture(record),
        "open_review_count": services.tower_open_review_count(record),
        "occupied_elevation_bands": [
            {
                "amendment_id": band["amendment_id"],
                "bottom_ft": num(band["bottom_ft"]),
                "top_ft": num(band["top_ft"]),
                "tenant_id": band["tenant_id"],
            }
            for band in services.tower_occupied_bands(record)
        ],
    }
    out.update(_common(record))
    return out


def capacity_summary(record):
    bands = services.tower_occupied_bands(record)
    return {
        "tower_id": record["id"],
        "rated_capacity_load_units": num(record["rated_capacity_load_units"]),
        "reserved_load_units": num(services.tower_reserved_load_units(record)),
        "reserved_load_pct": num(services.tower_reserved_load_pct(record)),
        "available_ground_space_sqft": num(services.tower_available_ground_space(record)),
        "capacity_posture": services.tower_capacity_posture(record),
        "open_review_count": services.tower_open_review_count(record),
        "occupied_band_count": len(bands),
        "capacity_hold_application_count": services.tower_capacity_hold_count(record),
    }


def landlord(record):
    out = {
        "legal_name": record["legal_name"],
        "remit_contact_email": record["remit_contact_email"],
        "w9_on_file": record["w9_on_file"],
    }
    out.update(_common(record))
    return out


def ground_lease(record):
    out = {
        "tower_id": record["tower_id"],
        "landlord_id": record["landlord_id"],
        "base_monthly_rent_cents": record["base_monthly_rent_cents"],
        "escalator_pct": num(record["escalator_pct"]),
        "commencement_date": _date(record, "commencement_date"),
        "term_end_date": _date(record, "term_end_date"),
        "renewal_option_count": record["renewal_option_count"],
        "renewal_term_years": record["renewal_term_years"],
        "buyout_price_cents": record["buyout_price_cents"],
        "status": record["status"],
        "renewals_exercised": record["renewals_exercised"],
        "current_monthly_rent_cents": services.ground_lease_current_rent(record),
        "paid_through_date": _date(record, "paid_through_date"),
        "buyout_paid_cents": record["buyout_paid_cents"],
    }
    out.update(_common(record))
    return out


def landlord_payment(record):
    return {
        "id": record["id"],
        "ground_lease_id": record["ground_lease_id"],
        "period_start_date": _date(record, "period_start_date"),
        "period_end_date": _date(record, "period_end_date"),
        "months_covered": record["months_covered"],
        "amount_cents": record["amount_cents"],
        "created_at": iso(record["created_at"]),
    }


def tenant(record):
    out = {
        "legal_name": record["legal_name"],
        "carrier_code": record["carrier_code"],
        "outstanding_balance_cents": record["outstanding_balance_cents"],
        "credit_status": services.credit_status_for(record),
    }
    out.update(_common(record))
    return out


def mla(record):
    out = {
        "tenant_id": record["tenant_id"],
        "base_monthly_rent_cents": record["base_monthly_rent_cents"],
        "escalator_pct": num(record["escalator_pct"]),
        "initial_term_years": record["initial_term_years"],
        "renewal_terms_count": record["renewal_terms_count"],
        "expires_on": _date(record, "expires_on"),
        "expedited_review_days": record["expedited_review_days"],
        "status": record["status"],
        "application_privilege": services.application_privilege_for(record),
        "executed_amendment_count": services.executed_amendment_count(record),
    }
    out.update(_common(record))
    return out


def application(record):
    out = {
        "tower_id": record["tower_id"],
        "master_lease_agreement_id": record["master_lease_agreement_id"],
        "requested_elevation_bottom_ft": num(record["requested_elevation_bottom_ft"]),
        "requested_elevation_top_ft": num(record["requested_elevation_top_ft"]),
        "requested_ground_space_sqft": num(record["requested_ground_space_sqft"]),
        "expedited_requested": record["expedited_requested"],
        "status": record["status"],
        "submitted_at": iso(record["submitted_at"]),
        "review_deadline_at": iso(record["review_deadline_at"]),
        "sla_breached": record["sla_breached"],
        "total_load_units": num(record["total_load_units"]),
        "revision_count": record["revision_count"],
        "rejection_reason": record.get("rejection_reason"),
        "revision_note": record.get("revision_note"),
    }
    out.update(_common(record))
    return out


def equipment_line(record):
    out = {
        "colocation_application_id": record["colocation_application_id"],
        "installed_amendment_id": record["installed_amendment_id"],
        "equipment_type": record["equipment_type"],
        "model_code": record["model_code"],
        "quantity": record["quantity"],
        "unit_weight_lbs": num(record["unit_weight_lbs"]),
        "wind_area_sqft": num(record["wind_area_sqft"]),
        "mount_elevation_ft": num(record["mount_elevation_ft"]),
        "load_units": num(record["load_units"]),
    }
    out.update(_common(record))
    return out


def analysis(record):
    out = {
        "colocation_application_id": record["colocation_application_id"],
        "variant": record["variant"],
        "base_load_units": num(record["base_load_units"]),
        "subject_load_units": num(record["subject_load_units"]),
        "pipeline_load_units": num(record["pipeline_load_units"]),
        "included_load_units": num(record["included_load_units"]),
        "projected_loading_pct": num(record["projected_loading_pct"]),
        "result": record["result"],
        "status": record["status"],
        "modification_construction_cost_cents": record["modification_construction_cost_cents"],
        "quoted_at": iso(record["quoted_at"]),
        "engineer_user_id": record["engineer_user_id"],
        "issued_at": iso(record["issued_at"]),
    }
    out.update(_common(record))
    return out


def amendment(record):
    out = {
        "master_lease_agreement_id": record["master_lease_agreement_id"],
        "tower_id": record["tower_id"],
        "colocation_application_id": record["colocation_application_id"],
        "supersedes_amendment_id": record["supersedes_amendment_id"],
        "execution_status": record["execution_status"],
        "billing_status": record["billing_status"],
        "base_monthly_rent_cents": record["base_monthly_rent_cents"],
        "escalator_pct": num(record["escalator_pct"]),
        "effective_date": _date(record, "effective_date"),
        "term_end_date": _date(record, "term_end_date"),
        "elevation_bottom_ft": num(record["elevation_bottom_ft"]),
        "elevation_top_ft": num(record["elevation_top_ft"]),
        "ground_space_sqft": num(record["ground_space_sqft"]),
        "reserved_load_units": num(record["reserved_load_units"]),
        "current_monthly_rent_cents": services.amendment_current_rent(record),
        "restoration_deposit_cents": record["restoration_deposit_cents"],
        "restoration_status": record["restoration_status"],
        "notice_given_at": iso(record["notice_given_at"]),
        "terminated_at": iso(record["terminated_at"]),
    }
    out.update(_common(record))
    return out


def project(record):
    out = {
        "tower_id": record["tower_id"],
        "originating_analysis_id": record["originating_analysis_id"],
        "construction_window_start_date": _date(record, "construction_window_start_date"),
        "construction_window_end_date": _date(record, "construction_window_end_date"),
        "status": record["status"],
        "base_construction_cost_cents": record["base_construction_cost_cents"],
        "volume_discount_pct": num(record["volume_discount_pct"]),
        "engineering_fee_cents": record["engineering_fee_cents"],
        "total_cost_cents": record["total_cost_cents"],
        "allocation_basis": record["allocation_basis"],
        "allocated_cents": services.project_allocated_cents(record),
        "proposing_engineer_user_id": record["proposing_engineer_user_id"],
        "certified_by_user_id": record["certified_by_user_id"],
        "funded_at": iso(record["funded_at"]),
        "added_capacity_load_units": num(record.get("added_capacity_load_units")),
        "cancellation_reason": record.get("cancellation_reason"),
    }
    out.update(_common(record))
    return out


def cost_share(record):
    out = {
        "modification_project_id": record["modification_project_id"],
        "tenant_id": record["tenant_id"],
        "site_amendment_id": record["site_amendment_id"],
        "basis_load_units": num(record["basis_load_units"]),
        "basis_created_at": iso(record["basis_created_at"]),
        "share_cents": record["share_cents"],
        "allocation_basis": record["allocation_basis"],
        "status": record["status"],
        "accepted_at": iso(record["accepted_at"]),
        "decline_reason": record.get("decline_reason"),
    }
    out.update(_common(record))
    return out


def audit(record):
    out = {
        "tower_id": record["tower_id"],
        "audit_date": _date(record, "audit_date"),
        "basis": record["basis"],
        "status": record["status"],
        "finding_count": len(services.audit_findings(record["id"])),
        "retroactive_billing_total_cents": services.audit_retro_total(record),
        "auditor_user_id": record["auditor_user_id"],
    }
    out.update(_common(record))
    return out


def finding(record):
    out = {
        "equipment_audit_id": record["equipment_audit_id"],
        "tenant_id": record["tenant_id"],
        "site_amendment_id": record["site_amendment_id"],
        "description": record["description"],
        "observed_load_units": num(record["observed_load_units"]),
        "installed_on_date": _date(record, "installed_on_date"),
        "mount_elevation_ft": num(record["mount_elevation_ft"]),
        "months_billable": record["months_billable"],
        "retroactive_billing_cents": record["retroactive_billing_cents"],
        "status": record["status"],
    }
    out.update(_common(record))
    return out
