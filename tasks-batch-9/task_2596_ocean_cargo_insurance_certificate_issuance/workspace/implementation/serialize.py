"""Entity -> JSON body projections (PRD 2.4 common fields, SCAFFOLD 1.1 field order)."""
from clock import iso
from validation import num


def _common(row):
    return {
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def _dt(value):
    return iso(value) if value is not None else None


def open_policy(row):
    out = {
        "id": row["id"],
        "policy_number": row["policy_number"],
        "assured_name": row["assured_name"],
        "inception_at": _dt(row["inception_at"]),
        "expiry_at": _dt(row["expiry_at"]),
        "warehouse_to_warehouse": row["warehouse_to_warehouse"],
        "freight_basis": row["freight_basis"],
        "markup_pct": num(row["markup_pct"]),
        "per_certificate_limit_amount": num(row["per_certificate_limit_amount"]),
        "conveyance_limit_amount": num(row["conveyance_limit_amount"]),
        "annual_aggregate_limit_amount": num(row["annual_aggregate_limit_amount"]),
        "deductible_amount": num(row["deductible_amount"]),
        "premium_rate_per_mille": num(row["premium_rate_per_mille"]),
        "war_rate_per_mille": num(row["war_rate_per_mille"]),
        "strikes_rate_per_mille": num(row["strikes_rate_per_mille"]),
        "status": row["status"],
        "war_cover_status": row["war_cover_status"],
        "war_terminated_at": _dt(row["war_terminated_at"]),
        "war_termination_port_unlocode": row["war_termination_port_unlocode"],
        "reinstatement_rate_per_mille": num(row["reinstatement_rate_per_mille"]),
        "aggregate_insured_value_booked": num(row["aggregate_insured_value_booked"]),
        "aggregate_premium_booked": num(row["aggregate_premium_booked"]),
        "aggregate_return_premium": num(row["aggregate_return_premium"]),
        "security_deposit_held_amount": num(row["security_deposit_held_amount"]),
        "certificates_issued_count": row["certificates_issued_count"],
    }
    out.update(_common(row))
    return out


def commodity_class(row):
    out = {
        "id": row["id"],
        "code": row["code"],
        "description": row["description"],
        "susceptibility_rating": row["susceptibility_rating"],
        "required_packaging_code": row["required_packaging_code"],
        "rate_loading_pct": num(row["rate_loading_pct"]),
        "max_conveyance_share_pct": num(row["max_conveyance_share_pct"]),
        "survey_required_above_amount": num(row["survey_required_above_amount"]),
    }
    out.update(_common(row))
    return out


def vessel(row):
    out = {
        "id": row["id"],
        "name": row["name"],
        "imo_number": row["imo_number"],
        "year_built": row["year_built"],
        "classification_society": row["classification_society"],
        "flag_code": row["flag_code"],
        "vessel_accumulation_limit_amount": num(row["vessel_accumulation_limit_amount"]),
        "status": row["status"],
        "overage_surcharge_pct": num(row["overage_surcharge_pct"]),
        "accumulated_insured_value": num(row["accumulated_insured_value"]),
        "open_ga_event_count": row["open_ga_event_count"],
    }
    out.update(_common(row))
    return out


def port(row):
    out = {
        "id": row["id"],
        "unlocode": row["unlocode"],
        "name": row["name"],
        "country_code": row["country_code"],
        "port_accumulation_limit_amount": num(row["port_accumulation_limit_amount"]),
        "storage_free_days": row["storage_free_days"],
        "war_risk_tier": row["war_risk_tier"],
        "war_rate_multiplier": num(row["war_rate_multiplier"]),
        "accumulated_insured_value": num(row["accumulated_insured_value"]),
    }
    out.update(_common(row))
    return out


def surveyor(row):
    out = {
        "id": row["id"],
        "name": row["name"],
        "panel_code": row["panel_code"],
        "base_port_id": row["base_port_id"],
        "certified_commodity_ratings": list(row["certified_commodity_ratings"]),
        "travel_buffer_minutes": row["travel_buffer_minutes"],
        "status": row["status"],
        "booked_minutes_total": row["booked_minutes_total"],
    }
    out.update(_common(row))
    return out


def certificate(row):
    out = {
        "id": row["id"],
        "open_policy_id": row["open_policy_id"],
        "commodity_class_id": row["commodity_class_id"],
        "vessel_id": row["vessel_id"],
        "loading_port_id": row["loading_port_id"],
        "discharge_port_id": row["discharge_port_id"],
        "replaces_certificate_id": row["replaces_certificate_id"],
        "premium_declaration_id": row["premium_declaration_id"],
        "certificate_number": row["certificate_number"],
        "valuation_basis": row["valuation_basis"],
        "invoice_value": num(row["invoice_value"]),
        "freight_amount": num(row["freight_amount"]),
        "duty_amount": num(row["duty_amount"]),
        "declared_value": num(row["declared_value"]),
        "packaging_code": row["packaging_code"],
        "package_count": row["package_count"],
        "gross_weight_kg": num(row["gross_weight_kg"]),
        "sailing_date": _dt(row["sailing_date"]),
        "discharge_date": _dt(row["discharge_date"]),
        "war_cover_requested": row["war_cover_requested"],
        "strikes_cover_requested": row["strikes_cover_requested"],
        "insured_value": num(row["insured_value"]),
        "attachment_at": _dt(row["attachment_at"]),
        "transit_termination_at": _dt(row["transit_termination_at"]),
        "effective_rate_per_mille": num(row["effective_rate_per_mille"]),
        "base_premium_amount": num(row["base_premium_amount"]),
        "war_premium_amount": num(row["war_premium_amount"]),
        "strikes_premium_amount": num(row["strikes_premium_amount"]),
        "total_premium_amount": num(row["total_premium_amount"]),
        "reinstatement_premium_amount": num(row["reinstatement_premium_amount"]),
        "return_premium_amount": num(row["return_premium_amount"]),
        "deductible_amount": num(row["deductible_amount"]),
        "status": row["status"],
        "war_cover_status": row["war_cover_status"],
        "issued_by_user_id": row["issued_by_user_id"],
        "issued_at": _dt(row["issued_at"]),
        "ga_contribution_amount": num(row["ga_contribution_amount"]),
    }
    out.update(_common(row))
    return out


def accumulation_entry(row):
    out = {
        "id": row["id"],
        "certificate_id": row["certificate_id"],
        "vessel_id": row["vessel_id"],
        "port_id": row["port_id"],
        "scope_type": row["scope_type"],
        "amount": num(row["amount"]),
        "window_start_at": _dt(row["window_start_at"]),
        "window_end_at": _dt(row["window_end_at"]),
        "status": row["status"],
        "release_reason": row["release_reason"],
    }
    out.update(_common(row))
    return out


def premium_declaration(row):
    out = {
        "id": row["id"],
        "open_policy_id": row["open_policy_id"],
        "period_start": _dt(row["period_start"]),
        "period_end": _dt(row["period_end"]),
        "declared_premium_total": num(row["declared_premium_total"]),
        "computed_premium_total": num(row["computed_premium_total"]),
        "certificate_count": row["certificate_count"],
        "variance_amount": num(row["variance_amount"]),
        "variance_pct": num(row["variance_pct"]),
        "audit_adjustment_amount": num(row["audit_adjustment_amount"]),
        "submitted_by_user_id": row["submitted_by_user_id"],
        "auditor_user_id": row["auditor_user_id"],
        "submission_count": row["submission_count"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def claim_file(row):
    out = {
        "id": row["id"],
        "certificate_id": row["certificate_id"],
        "ga_event_id": row["ga_event_id"],
        "loss_type": row["loss_type"],
        "peril": row["peril"],
        "adjustment_basis": row["adjustment_basis"],
        "claimed_amount": num(row["claimed_amount"]),
        "loss_date": _dt(row["loss_date"]),
        "damage_percentage": num(row["damage_percentage"]),
        "sound_market_value": num(row["sound_market_value"]),
        "damaged_sale_proceeds": num(row["damaged_sale_proceeds"]),
        "carrier_name": row["carrier_name"],
        "adjusted_amount": num(row["adjusted_amount"]),
        "deductible_applied_amount": num(row["deductible_applied_amount"]),
        "settled_amount": num(row["settled_amount"]),
        "documentation_complete": row["documentation_complete"],
        "warranty_breach": row["warranty_breach"],
        "adjusted_by_user_id": row["adjusted_by_user_id"],
        "settled_by_user_id": row["settled_by_user_id"],
        "subrogation_status": row["subrogation_status"],
        "subrogation_notice_at": _dt(row["subrogation_notice_at"]),
        "time_bar_at": _dt(row["time_bar_at"]),
        "recovered_amount": num(row["recovered_amount"]),
        "net_loss_amount": num(row["net_loss_amount"]),
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def damage_document(row):
    # Append-only evidence log: id + created_at only, no updated_at and no version.
    return {
        "id": row["id"],
        "claim_file_id": row["claim_file_id"],
        "doc_type": row["doc_type"],
        "reference": row["reference"],
        "received_at": _dt(row["received_at"]),
        "origin": row["origin"],
        "created_at": iso(row["created_at"]),
    }


def survey_order(row):
    out = {
        "id": row["id"],
        "claim_file_id": row["claim_file_id"],
        "surveyor_id": row["surveyor_id"],
        "window_start_at": _dt(row["window_start_at"]),
        "window_end_at": _dt(row["window_end_at"]),
        "window_minutes": row["window_minutes"],
        "packaging_compliant": row["packaging_compliant"],
        "damage_percentage_found": num(row["damage_percentage_found"]),
        "report_reference": row["report_reference"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def ga_event(row):
    out = {
        "id": row["id"],
        "vessel_id": row["vessel_id"],
        "voyage_sailing_date": _dt(row["voyage_sailing_date"]),
        "declaration_date": _dt(row["declaration_date"]),
        "average_adjuster_name": row["average_adjuster_name"],
        "sacrifice_amount": num(row["sacrifice_amount"]),
        "salvage_award_amount": num(row["salvage_award_amount"]),
        "adjuster_fee_amount": num(row["adjuster_fee_amount"]),
        "total_allowance_amount": num(row["total_allowance_amount"]),
        "total_contributory_value": num(row["total_contributory_value"]),
        "contribution_rate": num(row["contribution_rate"]),
        "postings_required_count": row["postings_required_count"],
        "postings_posted_count": row["postings_posted_count"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def ga_posting(row):
    out = {
        "id": row["id"],
        "ga_event_id": row["ga_event_id"],
        "certificate_id": row["certificate_id"],
        "contributory_value": num(row["contributory_value"]),
        "contribution_amount": num(row["contribution_amount"]),
        "cash_deposit_required": row["cash_deposit_required"],
        "cash_deposit_expected_amount": num(row["cash_deposit_expected_amount"]),
        "guarantee_amount": num(row["guarantee_amount"]),
        "cash_deposit_amount": num(row["cash_deposit_amount"]),
        "status": row["status"],
    }
    out.update(_common(row))
    return out
