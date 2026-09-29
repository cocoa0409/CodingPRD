"""Entity -> JSON projections.  Computed fields are derived at read time."""

from db import store
from services import calc, domain


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def athlete(rec):
    out = _common(rec)
    out.update(
        {
            "full_name": rec["full_name"],
            "date_of_birth": rec["date_of_birth"],
            "sport": rec["sport"],
            "position": rec["position"],
            "guardian_email": rec["guardian_email"],
            "maturity_offset_months": rec["maturity_offset_months"],
            "team_contract_id": rec["team_contract_id"],
            "membership_status": rec["membership_status"],
            "training_clearance": rec["training_clearance"],
            "injury_risk_score": calc.as_float(rec["injury_risk_score"]),
            "screen_count": rec["screen_count"],
            "age_years": domain.athlete_age_years(rec),
            "last_composite_percentile": calc.as_float(rec["last_composite_percentile"]),
            "last_performance_test_at": rec["last_performance_test_at"],
            "next_test_due_on": rec["next_test_due_on"],
            "attended_count": rec["attended_count"],
            "no_show_count": rec["no_show_count"],
            "no_show_strikes": rec["no_show_strikes"],
            "readiness_index": calc.as_float(domain.athlete_readiness(rec)),
        }
    )
    return out


def injury_record(rec):
    out = _common(rec)
    out.update(
        {
            "athlete_id": rec["athlete_id"],
            "body_region": rec["body_region"],
            "severity": rec["severity"],
            "occurred_on": rec["occurred_on"],
            "rts_required": rec["rts_required"],
            "status": rec["status"],
        }
    )
    return out


def test_session(rec):
    out = _common(rec)
    percentiles = rec["metric_percentiles"]
    if percentiles is not None:
        percentiles = [
            {
                "metric_code": row["metric_code"],
                "percentile": calc.as_float(row["percentile"]),
                "norm_band_matched": row["norm_band_matched"],
            }
            for row in percentiles
        ]
    out.update(
        {
            "athlete_id": rec["athlete_id"],
            "battery_type": rec["battery_type"],
            "administered_by_staff_id": rec["administered_by_staff_id"],
            "rts_plan_id": rec["rts_plan_id"],
            "results": [dict(row) for row in rec["results"]],
            "result_count": rec["result_count"],
            "status": rec["status"],
            "age_years_at_test": rec["age_years_at_test"],
            "effective_age_years": rec["effective_age_years"],
            "metric_percentiles": percentiles,
            "composite_percentile": calc.as_float(rec["composite_percentile"]),
            "risk_score": calc.as_float(rec["risk_score"]),
            "asymmetry_points": rec["asymmetry_points"],
            "variant_applied": rec["variant_applied"],
            "finalized_at": rec["finalized_at"],
        }
    )
    return out


def training_program(rec):
    blocks = program_blocks_of(rec["id"])
    out = _common(rec)
    out.update(
        {
            "athlete_id": rec["athlete_id"],
            "sport": rec["sport"],
            "position": rec["position"],
            "competition_start_date": rec["competition_start_date"],
            "competition_end_date": rec["competition_end_date"],
            "status": rec["status"],
            "block_count": len(blocks),
            "total_weeks": calc.program_total_weeks(blocks),
            "planned_load_units": calc.as_float(rec["planned_load_units"]),
            "pinned_block_versions": rec["pinned_block_versions"],
            "activated_at": rec["activated_at"],
        }
    )
    return out


def program_blocks_of(training_program_id):
    blocks = [
        b for b in store.program_blocks.values() if b["training_program_id"] == training_program_id
    ]
    blocks.sort(key=lambda b: (b["sequence_index"], b["created_at"], b["_seq"]))
    return blocks


def program_block(rec):
    out = _common(rec)
    out.update(
        {
            "training_program_id": rec["training_program_id"],
            "predecessor_block_id": rec["predecessor_block_id"],
            "phase": rec["phase"],
            "start_week": rec["start_week"],
            "end_week": rec["end_week"],
            "target_intensity_pct": rec["target_intensity_pct"],
            "weekly_volume_units": rec["weekly_volume_units"],
            "status": rec["status"],
            "sequence_index": rec["sequence_index"],
        }
    )
    return out


def group_session(rec):
    derived = domain.session_derived(rec)
    out = _common(rec)
    out.update(
        {
            "start_at": rec["start_at"],
            "end_at": rec["end_at"],
            "site_code": rec["site_code"],
            "offsite_location": rec["offsite_location"],
            "station_count": rec["station_count"],
            "phase_focus": rec["phase_focus"],
            "max_athletes": rec["max_athletes"],
            "team_contract_id": rec["team_contract_id"],
            "assigned_staff": [dict(row) for row in rec["assigned_staff"]],
            "compliant_coach_count": derived["compliant_coach_count"],
            "athlete_units": calc.as_float(derived["athlete_units"]),
            "required_coach_count": derived["required_coach_count"],
            "reserved_count": derived["reserved_count"],
            "waitlisted_count": derived["waitlisted_count"],
            "attended_count": derived["attended_count"],
            "no_show_count": derived["no_show_count"],
            "session_status": rec["session_status"],
            "staffing_status": derived["staffing_status"],
            "billed_rate_cents": rec["billed_rate_cents"],
            "rate_tier_applied": rec["rate_tier_applied"],
            "delivered_slots_at_completion": rec["delivered_slots_at_completion"],
            "cancel_reason": rec["cancel_reason"],
        }
    )
    return out


def enrollment(rec):
    out = _common(rec)
    out.update(
        {
            "athlete_id": rec["athlete_id"],
            "group_session_id": rec["group_session_id"],
            "funding_preference": rec["funding_preference"],
            "funding_source": rec["funding_source"],
            "membership_package_id": rec["membership_package_id"],
            "charge_cents": rec["charge_cents"],
            "status": rec["status"],
            "cancel_reason": rec["cancel_reason"],
            "station_number": rec["station_number"],
            "no_show_fee_cents": rec["no_show_fee_cents"],
            "strike_index_at_no_show": rec["strike_index_at_no_show"],
            "promoted_from_waitlist": rec["promoted_from_waitlist"],
        }
    )
    return out


def staff_member(rec):
    out = _common(rec)
    out.update(
        {
            "full_name": rec["full_name"],
            "role_title": rec["role_title"],
            "liability_insurance_expires_on": rec["liability_insurance_expires_on"],
            "credential_status": rec["credential_status"],
            "valid_certification_count": rec["valid_certification_count"],
            "lapsed_certification_count": rec["lapsed_certification_count"],
            "ceu_credits_earned_total": rec["ceu_credits_earned_total"],
            "last_credential_review_at": rec["last_credential_review_at"],
        }
    )
    return out


def certification(rec):
    out = _common(rec)
    out.update(
        {
            "staff_member_id": rec["staff_member_id"],
            "cert_code": rec["cert_code"],
            "issued_on": rec["issued_on"],
            "expires_on": rec["expires_on"],
            "ceu_credits_required": rec["ceu_credits_required"],
            "ceu_credits_earned": rec["ceu_credits_earned"],
            "status": rec["status"],
            "renewal_count": rec["renewal_count"],
        }
    )
    return out


def membership_package(rec):
    out = _common(rec)
    out.update(
        {
            "athlete_id": rec["athlete_id"],
            "sessions_purchased": rec["sessions_purchased"],
            "price_cents": rec["price_cents"],
            "expires_on": rec["expires_on"],
            "frozen_days_total": rec["frozen_days_total"],
            "frozen_at": rec["frozen_at"],
            "effective_expires_on": rec["effective_expires_on"],
            "sessions_remaining": rec["sessions_remaining"],
            "sessions_reserved": rec["sessions_reserved"],
            "sessions_consumed": rec["sessions_consumed"],
            "sessions_forfeited": rec["sessions_forfeited"],
            "status": rec["status"],
        }
    )
    return out


def team_contract(rec):
    out = _common(rec)
    out.update(
        {
            "organization_name": rec["organization_name"],
            "organization_type": rec["organization_type"],
            "contracted_sessions": rec["contracted_sessions"],
            "base_rate_cents": rec["base_rate_cents"],
            "offsite_allowance": rec["offsite_allowance"],
            "term_start": rec["term_start"],
            "term_end": rec["term_end"],
            "sessions_available": rec["sessions_available"],
            "sessions_reserved": rec["sessions_reserved"],
            "sessions_delivered": rec["sessions_delivered"],
            "offsite_sessions_used": rec["offsite_sessions_used"],
            "billed_amount_cents": rec["billed_amount_cents"],
            "rate_tier": calc.rate_tier_for(rec["sessions_delivered"]),
            "status": rec["status"],
        }
    )
    return out


def rts_plan(rec):
    out = _common(rec)
    out.update(
        {
            "athlete_id": rec["athlete_id"],
            "injury_record_id": rec["injury_record_id"],
            "target_stage_count": rec["target_stage_count"],
            "current_stage": rec["current_stage"],
            "stage_attempts": rec["stage_attempts"],
            "total_failed_attempts": rec["total_failed_attempts"],
            "active_stage_test_id": rec["active_stage_test_id"],
            "status": rec["status"],
            "cleared_at": rec["cleared_at"],
        }
    )
    return out


def clearance_document(rec):
    out = _common(rec)
    out.update(
        {
            "athlete_id": rec["athlete_id"],
            "rts_plan_id": rec["rts_plan_id"],
            "document_type": rec["document_type"],
            "stage_number": rec["stage_number"],
            "expires_on": rec["expires_on"],
            "provider_license_id": rec["provider_license_id"],
            "signed_at": rec["signed_at"],
            "status": rec["status"],
        }
    )
    return out
