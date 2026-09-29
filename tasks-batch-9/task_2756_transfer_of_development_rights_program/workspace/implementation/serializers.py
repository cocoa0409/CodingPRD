"""Entity -> JSON projections."""

from core import fmt_dt, num


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def party(rec):
    out = {
        "kind": rec["kind"],
        "legal_name": rec["legal_name"],
        "contact_email": rec["contact_email"],
        "neighborhood_code": rec["neighborhood_code"],
        "cash_balance_cents": rec["cash_balance_cents"],
        "fee_revenue_cents": rec["fee_revenue_cents"],
        "units_held": rec["units_held"],
        "certificates_held_count": rec["certificates_held_count"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def sending_area(rec):
    out = {
        "code": rec["code"],
        "name": rec["name"],
        "neighborhood_code": rec["neighborhood_code"],
        "allocation_formula_version": rec["allocation_formula_version"],
        "base_rate_units_per_acre": num(rec["base_rate_units_per_acre"]),
        "gross_discount_factor": num(rec["gross_discount_factor"]),
        "equity_tier": rec["equity_tier"],
        "sending_cap_units": rec["sending_cap_units"],
        "severed_units_total": rec["severed_units_total"],
        "issued_certificate_count": rec["issued_certificate_count"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def receiving_area(rec):
    out = {
        "code": rec["code"],
        "name": rec["name"],
        "neighborhood_code": rec["neighborhood_code"],
        "base_density_units_per_acre": num(rec["base_density_units_per_acre"]),
        "max_bonus_pct": num(rec["max_bonus_pct"]),
        "absorption_cap_units": rec["absorption_cap_units"],
        "design_review_required": rec["design_review_required"],
        "eligible_sending_area_codes": list(rec["eligible_sending_area_codes"]),
        "absorbed_units": rec["absorbed_units"],
        "reserved_units": rec["reserved_units"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def appraisal_schedule(rec):
    out = {
        "neighborhood_code": rec["neighborhood_code"],
        "per_unit_value_cents": rec["per_unit_value_cents"],
        "equity_adjustment_bps": rec["equity_adjustment_bps"],
        "effective_from": fmt_dt(rec["effective_from"]),
        "effective_to": fmt_dt(rec["effective_to"]),
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def sending_parcel(rec):
    out = {
        "owner_party_id": rec["owner_party_id"],
        "sending_area_id": rec["sending_area_id"],
        "apn": rec["apn"],
        "gross_acres": num(rec["gross_acres"]),
        "constrained_acres": num(rec["constrained_acres"]),
        "soil_class": rec["soil_class"],
        "existing_dwelling_units": rec["existing_dwelling_units"],
        "baseline_allocation_units": rec["baseline_allocation_units"],
        "severed_units": rec["severed_units"],
        "remaining_units": rec["remaining_units"],
        "restricted_acres": num(rec["restricted_acres"]),
        "easement_status": rec["easement_status"],
        "parcel_status": rec["parcel_status"],
    }
    out.update(_common(rec))
    return out


def severance_application(rec):
    out = {
        "sending_parcel_id": rec["sending_parcel_id"],
        "applicant_party_id": rec["applicant_party_id"],
        "requested_units": rec["requested_units"],
        "status": rec["status"],
        "revision_round": rec["revision_round"],
        "screened_by_user_id": rec["screened_by_user_id"],
        "decided_by_user_id": rec["decided_by_user_id"],
        "certified_by_user_id": rec["certified_by_user_id"],
        "allocated_units": rec["allocated_units"],
        "applied_formula_version": rec["applied_formula_version"],
        "residual_units_retained": rec["residual_units_retained"],
        "decision_note": rec["decision_note"],
        "denial_reason": rec["denial_reason"],
    }
    out.update(_common(rec))
    return out


def conservation_easement(rec):
    out = {
        "sending_parcel_id": rec["sending_parcel_id"],
        "severance_application_id": rec["severance_application_id"],
        "recording_reference": rec["recording_reference"],
        "restricted_acres": num(rec["restricted_acres"]),
        "permitted_residual_units": rec["permitted_residual_units"],
        "units_issued_total": rec["units_issued_total"],
        "units_redeemed_confirmed": rec["units_redeemed_confirmed"],
        "units_retired": rec["units_retired"],
        "units_outstanding": rec["units_outstanding"],
        "amendment_count": rec["amendment_count"],
        "recording_status": rec["recording_status"],
        "compliance_status": rec["compliance_status"],
        "recorded_at": fmt_dt(rec["recorded_at"]),
        "last_inspection_at": fmt_dt(rec["last_inspection_at"]),
        "prior_violation_count": rec["prior_violation_count"],
        "cure_deadline": fmt_dt(rec["cure_deadline"]),
    }
    out.update(_common(rec))
    return out


def certificate(rec):
    out = {
        "conservation_easement_id": rec["conservation_easement_id"],
        "holder_party_id": rec["holder_party_id"],
        "parent_certificate_id": rec["parent_certificate_id"],
        "origin_sending_area_id": rec["origin_sending_area_id"],
        "serial_number": rec["serial_number"],
        "origin_neighborhood_code": rec["origin_neighborhood_code"],
        "generation": rec["generation"],
        "split_count": rec["split_count"],
        "units_face": rec["units_face"],
        "units_remaining": rec["units_remaining"],
        "units_split_out": rec["units_split_out"],
        "units_encumbered": rec["units_encumbered"],
        "units_redeemed": rec["units_redeemed"],
        "units_retired": rec["units_retired"],
        "lifecycle_status": rec["lifecycle_status"],
        "market_status": rec["market_status"],
        "issued_at": fmt_dt(rec["issued_at"]),
    }
    out.update(_common(rec))
    return out


def certificate_transfer(rec):
    # Append-only log: id and created_at only, no updated_at, no version.
    return {
        "id": rec["id"],
        "certificate_id": rec["certificate_id"],
        "from_party_id": rec["from_party_id"],
        "to_party_id": rec["to_party_id"],
        "market_transaction_id": rec["market_transaction_id"],
        "seq_no": rec["seq_no"],
        "transfer_type": rec["transfer_type"],
        "units": rec["units"],
        "price_cents": rec["price_cents"],
        "recorded_at": fmt_dt(rec["recorded_at"]),
        "created_at": fmt_dt(rec["created_at"]),
    }


def market_transaction(rec):
    out = {
        "certificate_id": rec["certificate_id"],
        "seller_party_id": rec["seller_party_id"],
        "buyer_party_id": rec["buyer_party_id"],
        "channel": rec["channel"],
        "units": rec["units"],
        "agreed_price_cents": rec["agreed_price_cents"],
        "applied_neighborhood_code": rec["applied_neighborhood_code"],
        "applied_per_unit_value_cents": rec["applied_per_unit_value_cents"],
        "appraised_reference_cents": rec["appraised_reference_cents"],
        "gross_price_cents": rec["gross_price_cents"],
        "price_deviation_bps": rec["price_deviation_bps"],
        "program_fee_cents": rec["program_fee_cents"],
        "equity_surcharge_cents": rec["equity_surcharge_cents"],
        "net_to_seller_cents": rec["net_to_seller_cents"],
        "status": rec["status"],
        "conveyance_mode": rec["conveyance_mode"],
        "conveyed_certificate_id": rec["conveyed_certificate_id"],
        "settled_at": fmt_dt(rec["settled_at"]),
        "reversed_at": fmt_dt(rec["reversed_at"]),
        "reversal_reason": rec["reversal_reason"],
    }
    out.update(_common(rec))
    return out


def receiving_site_application(rec):
    out = {
        "developer_party_id": rec["developer_party_id"],
        "receiving_area_id": rec["receiving_area_id"],
        "site_acres": num(rec["site_acres"]),
        "requested_bonus_units": rec["requested_bonus_units"],
        "base_units": rec["base_units"],
        "max_bonus_units": rec["max_bonus_units"],
        "required_backing_units": rec["required_backing_units"],
        "provisional_bonus_units": rec["provisional_bonus_units"],
        "allocated_bonus_units": rec["allocated_bonus_units"],
        "backed_units": rec["backed_units"],
        "pending_backed_units": rec["pending_backed_units"],
        "design_review_round": rec["design_review_round"],
        "design_reviewed_by_user_id": rec["design_reviewed_by_user_id"],
        "status": rec["status"],
        "finalized_at": fmt_dt(rec["finalized_at"]),
        "denial_reason": rec["denial_reason"],
    }
    out.update(_common(rec))
    return out


def certificate_redemption(rec):
    out = {
        "receiving_site_application_id": rec["receiving_site_application_id"],
        "certificate_id": rec["certificate_id"],
        "source_easement_id": rec["source_easement_id"],
        "units": rec["units"],
        "status": rec["status"],
        "allocated_at": fmt_dt(rec["allocated_at"]),
        "confirmed_at": fmt_dt(rec["confirmed_at"]),
        "released_at": fmt_dt(rec["released_at"]),
    }
    out.update(_common(rec))
    return out


def monitoring_inspection(rec):
    out = {
        "conservation_easement_id": rec["conservation_easement_id"],
        "inspector_user_id": rec["inspector_user_id"],
        "inspection_date": fmt_dt(rec["inspection_date"]),
        "finding": rec["finding"],
        "affected_acres": num(rec["affected_acres"]),
        "severity_score": num(rec["severity_score"]),
        "cure_deadline": fmt_dt(rec["cure_deadline"]),
        "status": rec["status"],
        "cure_verified_at": fmt_dt(rec["cure_verified_at"]),
        "cure_verified_by_user_id": rec["cure_verified_by_user_id"],
        "escalated_at": fmt_dt(rec["escalated_at"]),
        "note": rec["note"],
    }
    out.update(_common(rec))
    return out


def program_evaluation(rec):
    out = {
        "period_start": fmt_dt(rec["period_start"]),
        "period_end": fmt_dt(rec["period_end"]),
        "equity_weighting": rec["equity_weighting"],
        "preserved_acres": num(rec["preserved_acres"]),
        "easement_count": rec["easement_count"],
        "issued_units": rec["issued_units"],
        "redeemed_units": rec["redeemed_units"],
        "retired_units": rec["retired_units"],
        "absorption_pct": num(rec["absorption_pct"]),
        "equity_index": num(rec["equity_index"]),
        "outstanding_units": rec["outstanding_units"],
        "total_cash_cents": rec["total_cash_cents"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out
