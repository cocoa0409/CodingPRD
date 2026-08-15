"""Entity serializers — exact field sets per SCAFFOLD 1.1 / PRD 2.4.
Internal keys (prefixed with "_") are never emitted. Derived readings
(claims_posture, reinsurance_posture) are computed live at serialization.
"""

from __future__ import annotations

from services.core import derive_claims_posture, reinsurance_posture


def carrier_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "carrier_code": c["carrier_code"],
        "legal_name": c["legal_name"],
        "current_utc": c["current_utc"],
        "reinsurance_treaty_attachment_cents": c["reinsurance_treaty_attachment_cents"],
        "reinsurance_posture": reinsurance_posture(c),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def grower_view(g: dict) -> dict:
    return {
        "id": g["id"],
        "carrier_id": g["carrier_id"],
        "full_name": g["full_name"],
        "tax_id_last4": g["tax_id_last4"],
        "email": g["email"],
        "county_code": g["county_code"],
        "state_code": g["state_code"],
        "continuous_coverage_since": g["continuous_coverage_since"],
        "prior_claims_count": g["prior_claims_count"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def adjuster_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "carrier_id": a["carrier_id"],
        "full_name": a["full_name"],
        "license_number": a["license_number"],
        "county_codes": a["county_codes"],
        "species_qualified": a["species_qualified"],
        "capacity_max_open_claims": a["capacity_max_open_claims"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def rate_table_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "carrier_id": r["carrier_id"],
        "rating_kind": r["rating_kind"],
        "county_code": r["county_code"],
        "crop_code": r["crop_code"],
        "species": r["species"],
        "value_band_floor_cents": r["value_band_floor_cents"],
        "value_band_ceiling_cents": r["value_band_ceiling_cents"],
        "rate_per_100_cents_of_liability": r["rate_per_100_cents_of_liability"],
        "effective_from": r["effective_from"],
        "effective_to": r["effective_to"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def federal_view(f: dict) -> dict:
    return {
        "id": f["id"],
        "carrier_id": f["carrier_id"],
        "grower_id": f["grower_id"],
        "fci_policy_number": f["fci_policy_number"],
        "coverage_level_pct": f["coverage_level_pct"],
        "crop_code": f["crop_code"],
        "county_code": f["county_code"],
        "effective_date": f["effective_date"],
        "expiration_date": f["expiration_date"],
        "liability_cents": f["liability_cents"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def policy_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "carrier_id": p["carrier_id"],
        "grower_id": p["grower_id"],
        "policy_kind": p["policy_kind"],
        "policy_number": p["policy_number"],
        "effective_date": p["effective_date"],
        "expiration_date": p["expiration_date"],
        "acreage_report_deadline": p["acreage_report_deadline"],
        "harvest_report_deadline": p["harvest_report_deadline"],
        "head_report_deadline": p["head_report_deadline"],
        "premium_cents": p["premium_cents"],
        "premium_paid_cents": p["premium_paid_cents"],
        "premium_reserve_cents": p["premium_reserve_cents"],
        "continuous_coverage_carryover_credit_cents": p["continuous_coverage_carryover_credit_cents"],
        "high_risk_surcharge_pct": p["high_risk_surcharge_pct"],
        "lifecycle_state": p["lifecycle_state"],
        "billing_state": p["billing_state"],
        "claims_posture": derive_claims_posture(p),
        "prior_policy_id": p["prior_policy_id"],
        "dual_coverage_link_id": p["dual_coverage_link_id"],
        "version_note": p["version_note"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def coverage_unit_view(u: dict) -> dict:
    return {
        "id": u["id"],
        "policy_id": u["policy_id"],
        "unit_kind": u["unit_kind"],
        "county_code": u["county_code"],
        "crop_code": u["crop_code"],
        "declared_acres": u["declared_acres"],
        "species": u["species"],
        "declared_head_count": u["declared_head_count"],
        "per_head_value_cents": u["per_head_value_cents"],
        "liability_cents": u["liability_cents"],
        "premium_cents": u["premium_cents"],
        "status": u["status"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


def acreage_report_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "coverage_unit_id": r["coverage_unit_id"],
        "report_kind": r["report_kind"],
        "reported_acres": r["reported_acres"],
        "submitted_at": r["submitted_at"],
        "is_timely": r["is_timely"],
        "lateness_days": r["lateness_days"],
        "coverage_reduction_pct": r["coverage_reduction_pct"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def head_report_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "coverage_unit_id": r["coverage_unit_id"],
        "report_kind": r["report_kind"],
        "reported_head_count": r["reported_head_count"],
        "submitted_at": r["submitted_at"],
        "is_timely": r["is_timely"],
        "lateness_days": r["lateness_days"],
        "coverage_reduction_pct": r["coverage_reduction_pct"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def claim_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "policy_id": c["policy_id"],
        "coverage_unit_id": c["coverage_unit_id"],
        "claim_kind": c["claim_kind"],
        "loss_date": c["loss_date"],
        "reported_at": c["reported_at"],
        "reported_within_window": c["reported_within_window"],
        "late_notification_penalty_pct": c["late_notification_penalty_pct"],
        "percent_damage_estimate_pct": c["percent_damage_estimate_pct"],
        "appraisal_value_cents": c["appraisal_value_cents"],
        "deceased_head_count": c["deceased_head_count"],
        "adjuster_id": c["adjuster_id"],
        "provisional_indemnity_cents": c["provisional_indemnity_cents"],
        "final_indemnity_cents": c["final_indemnity_cents"],
        "claim_state": c["claim_state"],
        "doc_posture": c["doc_posture"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def field_inspection_view(i: dict) -> dict:
    return {
        "id": i["id"],
        "claim_id": i["claim_id"],
        "adjuster_id": i["adjuster_id"],
        "scheduled_for": i["scheduled_for"],
        "inspected_at": i["inspected_at"],
        "within_inspection_window": i["within_inspection_window"],
        "observed_percent_damage_pct": i["observed_percent_damage_pct"],
        "observed_appraisal_cents": i["observed_appraisal_cents"],
        "observed_deceased_count": i["observed_deceased_count"],
        "provisional_indemnity_cents": i["provisional_indemnity_cents"],
        "notes": i["notes"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def vet_report_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "claim_id": r["claim_id"],
        "veterinarian_license": r["veterinarian_license"],
        "report_kind": r["report_kind"],
        "cause_of_death": r["cause_of_death"],
        "necropsy_performed": r["necropsy_performed"],
        "death_date": r["death_date"],
        "submitted_at": r["submitted_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def determination_view(d: dict) -> dict:
    return {
        "id": d["id"],
        "claim_id": d["claim_id"],
        "reviewer_id": d["reviewer_id"],
        "decision": d["decision"],
        "approved_indemnity_cents": d["approved_indemnity_cents"],
        "applied_coverage_reduction_pct": d["applied_coverage_reduction_pct"],
        "applied_late_notification_penalty_pct": d["applied_late_notification_penalty_pct"],
        "applied_dual_coverage_offset_cents": d["applied_dual_coverage_offset_cents"],
        "final_indemnity_cents": d["final_indemnity_cents"],
        "denial_reason_code": d["denial_reason_code"],
        "decided_at": d["decided_at"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def indemnity_payment_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "claim_id": p["claim_id"],
        "amount_cents": p["amount_cents"],
        "issued_at": p["issued_at"],
        "payment_method": p["payment_method"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def dual_link_view(l: dict) -> dict:
    return {
        "id": l["id"],
        "policy_id": l["policy_id"],
        "federal_crop_policy_id": l["federal_crop_policy_id"],
        "offset_pct_of_federal_liability": l["offset_pct_of_federal_liability"],
        "established_at": l["established_at"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def renewal_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "policy_id": r["policy_id"],
        "prior_policy_id": r["prior_policy_id"],
        "continuity_gap_days": r["continuity_gap_days"],
        "carryover_credit_cents": r["carryover_credit_cents"],
        "decision": r["decision"],
        "decided_at": r["decided_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def premium_payment_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "policy_id": p["policy_id"],
        "amount_cents": p["amount_cents"],
        "posted_at": p["posted_at"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }
