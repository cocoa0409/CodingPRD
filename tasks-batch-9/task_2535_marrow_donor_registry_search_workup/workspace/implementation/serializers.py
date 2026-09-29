"""Row -> JSON projections.  Every declared field is emitted, computed fields
are re-derived at read time so a counter can never drift (PRD 2.10).
"""

from decimal import Decimal

import calc
from store import fmt_date, fmt_instant


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def common(row):
    return {
        "id": row["id"],
        "created_at": fmt_instant(row["created_at"]),
        "updated_at": fmt_instant(row["updated_at"]),
        "version": row["version"],
    }


def registry_dict(row):
    out = common(row)
    out.update({
        "code": row["code"],
        "name": row["name"],
        "country_code": row["country_code"],
        "currency_code": row["currency_code"],
        "fx_rate_to_usd": num(row["fx_rate_to_usd"]),
        "is_domestic": row["is_domestic"],
        "cooperation_status": row["cooperation_status"],
        "cooperation_tier": row["cooperation_tier"],
        "ct_response_deadline_hours": row["ct_response_deadline_hours"],
        "donor_count": calc.donor_count(row["id"]),
    })
    return out


def center_dict(row):
    out = common(row)
    out.update({
        "name": row["name"],
        "country_code": row["country_code"],
        "concurrent_collection_capacity": row["concurrent_collection_capacity"],
        "committed_slot_minutes": calc.committed_slot_minutes(row["id"]),
    })
    return out


def patient_dict(row):
    out = common(row)
    out.update({
        "mrn": row["mrn"],
        "transplant_center_code": row["transplant_center_code"],
        "country_code": row["country_code"],
        "diagnosis_code": row["diagnosis_code"],
        "urgency_tier": row["urgency_tier"],
        "weight_kg": num(row["weight_kg"]),
        "cmv_status": row["cmv_status"],
        "hla_typing": row["hla_typing"],
        "case_budget_cents": row["case_budget_cents"],
        "coordinating_user_id": row["coordinating_user_id"],
        "conditioning_status": row["conditioning_status"],
        "conditioning_start_date": fmt_date(row["conditioning_start_date"]),
        "committed_cost_cents": calc.committed_cost_cents(row["id"]),
        "conditioning_aborted_reason": row["conditioning_aborted_reason"],
    })
    return out


def search_dict(row):
    out = common(row)
    out.update({
        "patient_id": row["patient_id"],
        "search_scope": row["search_scope"],
        "min_preliminary_score": num(row["min_preliminary_score"]),
        "status": row["status"],
        "match_pool_size": calc.match_pool_size(row["id"]),
        "backup_candidate_count": calc.backup_candidate_count(row["id"]),
        "last_sweep_at": fmt_instant(row["last_sweep_at"]),
    })
    return out


def donor_dict(row):
    out = common(row)
    out.update({
        "registry_id": row["registry_id"],
        "donor_code": row["donor_code"],
        "age_years": row["age_years"],
        "sex": row["sex"],
        "weight_kg": num(row["weight_kg"]),
        "cmv_status": row["cmv_status"],
        "hla_typing_registry": row["hla_typing_registry"],
        "ambiguous_loci": list(row["ambiguous_loci"]),
        "consented_methods": list(row["consented_methods"]),
        "prior_donation_count": row["prior_donation_count"],
        "availability_status": row["availability_status"],
        "deferral_until": fmt_date(row["deferral_until"]),
        "blocked_day_count": calc.blocked_day_count(row["id"]),
        "adverse_event_count": calc.adverse_event_count(row["id"]),
        "last_followup_at": fmt_instant(row["last_followup_at"]),
    })
    return out


def candidate_dict(row):
    out = common(row)
    out.update({
        "search_request_id": row["search_request_id"],
        "donor_id": row["donor_id"],
        "preliminary_score": num(row["preliminary_score"]),
        "confirmed_score": num(row["confirmed_score"]),
        "confirmed_match_grade": row["confirmed_match_grade"],
        "rank_score": num(row["rank_score"]),
        "rank_position": row["rank_position"],
        "candidate_role": row["candidate_role"],
        "status": row["status"],
        "ct_attempt_count": row["ct_attempt_count"],
        "screening_outcome": row["screening_outcome"],
        "screening_deferral_type": row["screening_deferral_type"],
        "promoted_from_rank": row["promoted_from_rank"],
    })
    return out


def typing_request_dict(row):
    out = common(row)
    out.update({
        "match_candidate_id": row["match_candidate_id"],
        "attempt_number": row["attempt_number"],
        "priority_flag": row["priority_flag"],
        "requested_at": fmt_instant(row["requested_at"]),
        "deadline_at": fmt_instant(row["deadline_at"]),
        "status": row["status"],
        "responded_at": fmt_instant(row["responded_at"]),
        "reported_hla_typing": row["reported_hla_typing"],
        "reported_match_grade": row["reported_match_grade"],
        "donor_available_flag": row["donor_available_flag"],
        "expired_by_sweep_at": fmt_instant(row["expired_by_sweep_at"]),
    })
    return out


def workup_dict(row):
    out = common(row)
    out.update({
        "match_candidate_id": row["match_candidate_id"],
        "case_status": row["case_status"],
        "clearance_status": row["clearance_status"],
        "logistics_status": row["logistics_status"],
        "collection_method": row["collection_method"],
        "method_decided_by_user_id": row["method_decided_by_user_id"],
        "physical_cleared_by_user_id": row["physical_cleared_by_user_id"],
        "idm_resulted_at": fmt_instant(row["idm_resulted_at"]),
        "opened_by_user_id": row["opened_by_user_id"],
        "planned_window_days": row["planned_window_days"],
        "abort_reason": row["abort_reason"],
    })
    return out


def clearance_dict(row):
    out = common(row)
    out.update({
        "workup_case_id": row["workup_case_id"],
        "item_type": row["item_type"],
        "result": row["result"],
        "resulted_at": fmt_instant(row["resulted_at"]),
        "resulted_by_user_id": row["resulted_by_user_id"],
        "expires_at": fmt_instant(row["expires_at"]),
        "note": row["note"],
    })
    return out


def booking_dict(row):
    out = common(row)
    out.update({
        "workup_case_id": row["workup_case_id"],
        "collection_center_id": row["collection_center_id"],
        "method": row["method"],
        "start_at": fmt_instant(row["start_at"]),
        "end_at": fmt_instant(row["end_at"]),
        "duration_minutes": row["duration_minutes"],
        "collection_date": fmt_date(row["collection_date"]),
        "status": row["status"],
        "confirmed_at": fmt_instant(row["confirmed_at"]),
        "cancel_reason": row["cancel_reason"],
        "cancelled_after_confirmation": bool(
            row["status"] == "CANCELLED" and row["confirmed_at"] is not None),
    })
    return out


def window_dict(row):
    out = common(row)
    out.update({
        "donor_id": row["donor_id"],
        "source_booking_id": row["source_booking_id"],
        "date_from": fmt_date(row["date_from"]),
        "date_to": fmt_date(row["date_to"]),
        "reason": row["reason"],
        "day_count": row["day_count"],
        "status": row["status"],
        "released_at": fmt_instant(row["released_at"]),
    })
    return out


def shipment_dict(row):
    out = common(row)
    out.update({
        "collection_booking_id": row["collection_booking_id"],
        "collected_at": fmt_instant(row["collected_at"]),
        "collected_cd34_e6_per_kg": num(row["collected_cd34_e6_per_kg"]),
        "collected_volume_ml": num(row["collected_volume_ml"]),
        "courier_reference": row["courier_reference"],
        "must_infuse_by": fmt_instant(row["must_infuse_by"]),
        "dose_adequacy": row["dose_adequacy"],
        "status": row["status"],
        "departed_at": fmt_instant(row["departed_at"]),
        "delivered_at": fmt_instant(row["delivered_at"]),
        "transit_event_count": row["transit_event_count"],
    })
    return out


def followup_dict(row):
    """DonorFollowUp is append-only: id and created_at only (PRD 2.5)."""
    return {
        "id": row["id"],
        "created_at": fmt_instant(row["created_at"]),
        "donor_id": row["donor_id"],
        "event_type": row["event_type"],
        "severity_grade": row["severity_grade"],
        "description": row["description"],
        "reported_at": fmt_instant(row["reported_at"]),
        "triggered_permanent_deferral": row["triggered_permanent_deferral"],
    }


def claim_dict(row):
    out = common(row)
    out.update({
        "workup_case_id": row["workup_case_id"],
        "patient_id": row["patient_id"],
        "billing_registry_id": row["billing_registry_id"],
        "status": row["status"],
        "variant_applied": row["variant_applied"],
        "currency_code": row["currency_code"],
        "fx_rate_snapshot": num(row["fx_rate_snapshot"]),
        "line_items": [
            {"line_type": item["line_type"],
             "amount_usd_cents": item["amount_usd_cents"]}
            for item in row["line_items"]
        ],
        "subtotal_usd_cents": row["subtotal_usd_cents"],
        "volume_discount_pct": num(row["volume_discount_pct"]),
        "discount_usd_cents": row["discount_usd_cents"],
        "intl_coordination_fee_usd_cents": row["intl_coordination_fee_usd_cents"],
        "total_usd_cents": row["total_usd_cents"],
        "billed_amount_local_cents": row["billed_amount_local_cents"],
        "cancellation_fee_applied": row["cancellation_fee_applied"],
        "finalized_at": fmt_instant(row["finalized_at"]),
        "void_reason": row["void_reason"],
    })
    return out
