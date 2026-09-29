"""Entity representations.  Derived figures are recomputed at read time."""

from db import commit
from response import iso, iso_date
from services import calc
from services.domain import program_standing


def _common(row):
    # PRD 2.5: `version` "increases by exactly 1 on every mutation of the row"
    # and `updated_at` is "refreshed on every mutation".  The request's pending
    # bumps must land in the emitted body, so they are committed here — at the
    # moment a row is first read for serialisation — rather than after the
    # caller has already built the payload.  Refusals never reach this point,
    # so a rejected write still leaves the row untouched.
    commit()
    return {
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def volunteer(row):
    payload = {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "email": row["email"],
        "role_track": row["role_track"],
        "seniority_start_date": iso_date(row["seniority_start_date"]),
        "committee_seat": row["committee_seat"],
        "status": row["status"],
        "continuous_service_months": calc.continuous_service_months(row),
        "current_certification_count": calc.current_certification_count(row["id"]),
        "strike_count": row["strike_count"],
        "seniority_score": row["seniority_score"],
        "needs_core_renewal": calc.needs_core_renewal(row["id"]),
    }
    payload.update(_common(row))
    return payload


def certification(row):
    payload = {
        "id": row["id"],
        "volunteer_id": row["volunteer_id"],
        "cert_type": row["cert_type"],
        "status": row["status"],
        "exam_score": row["exam_score"],
        "attempt_count": row["attempt_count"],
        "issued_on": iso(row["issued_on"]),
        "expires_on": iso(row["expires_on"]),
        "last_attempt_at": iso(row["last_attempt_at"]),
        "revocation_reason": row["revocation_reason"],
    }
    payload.update(_common(row))
    return payload


def proposal(row):
    payload = {
        "id": row["id"],
        "proposer_volunteer_id": row["proposer_volunteer_id"],
        "title": row["title"],
        "format_code": row["format_code"],
        "language_code": row["language_code"],
        "requested_daypart": row["requested_daypart"],
        "requested_duration_minutes": row["requested_duration_minutes"],
        "diversity_tags": list(row["diversity_tags"]),
        "status": row["status"],
        "review_round": row["review_round"],
        "composite_score": row["composite_score"],
        "decline_majority": row["decline_majority"],
        "decided_at": iso(row["decided_at"]),
    }
    payload.update(_common(row))
    return payload


def committee_vote(row):
    return {
        "id": row["id"],
        "proposal_id": row["proposal_id"],
        "member_volunteer_id": row["member_volunteer_id"],
        "review_round": row["review_round"],
        "format_fit_score": row["format_fit_score"],
        "diversity_score": row["diversity_score"],
        "quality_score": row["quality_score"],
        "recommendation": row["recommendation"],
        "rationale": row["rationale"],
        "created_at": iso(row["created_at"]),
    }


def program(row):
    payload = {
        "id": row["id"],
        "proposal_id": row["proposal_id"],
        "host_volunteer_id": row["host_volunteer_id"],
        "title": row["title"],
        "format_code": row["format_code"],
        "programming_status": row["programming_status"],
        "compliance_standing": program_standing(row),
        "compliance_penalty_points": calc.program_penalty_points(row["id"]),
        "performance_score": row["performance_score"],
        "performance_score_method": row["performance_score_method"],
        "last_evaluated_at": iso(row["last_evaluated_at"]),
        "cancellation_reason": row["cancellation_reason"],
    }
    payload.update(_common(row))
    return payload


def grid(row):
    total, pct = calc.grid_figures(row)
    payload = {
        "id": row["id"],
        "season_code": row["season_code"],
        "effective_from": iso(row["effective_from"]),
        "effective_to": iso(row["effective_to"]),
        "status": row["status"],
        "total_assigned_minutes": total,
        "public_affairs_minutes_pct": pct,
        "published_at": iso(row["published_at"]),
    }
    payload.update(_common(row))
    return payload


def slot(row):
    payload = {
        "id": row["id"],
        "grid_id": row["grid_id"],
        "program_id": row["program_id"],
        "day_of_week": row["day_of_week"],
        "start_minute": row["start_minute"],
        "duration_minutes": row["duration_minutes"],
        "status": row["status"],
        "preempted_by_program_id": row["preempted_by_program_id"],
        "release_reason": row["release_reason"],
    }
    payload.update(_common(row))
    return payload


def episode(row):
    payload = {
        "id": row["id"],
        "program_id": row["program_id"],
        "slot_assignment_id": row["slot_assignment_id"],
        "board_operator_volunteer_id": row["board_operator_volunteer_id"],
        "scheduled_start_utc": iso(row["scheduled_start_utc"]),
        "air_status": row["air_status"],
        "log_status": row["log_status"],
        "needs_substitute": row["needs_substitute"],
        "featured_performance_count": row["featured_performance_count"],
        "local_featured_count": row["local_featured_count"],
        "provisional_royalty_cents": row["provisional_royalty_cents"],
        "final_royalty_cents": row["final_royalty_cents"],
        "log_due_at": iso(row["log_due_at"]),
    }
    payload.update(_common(row))
    return payload


def playlist_entry(row):
    return {
        "id": row["id"],
        "episode_id": row["episode_id"],
        "sequence_number": row["sequence_number"],
        "artist": row["artist"],
        "title": row["title"],
        "album": row["album"],
        "label": row["label"],
        "is_local_artist": row["is_local_artist"],
        "is_new_release": row["is_new_release"],
        "duration_seconds": row["duration_seconds"],
        "play_source": row["play_source"],
        "royalty_class": row["royalty_class"],
        "created_at": iso(row["created_at"]),
    }


def spot(row):
    payload = {
        "id": row["id"],
        "underwriter_name": row["underwriter_name"],
        "spot_class": row["spot_class"],
        "copy_text": row["copy_text"],
        "approved_copy_text": row["approved_copy_text"],
        "assigned_program_id": row["assigned_program_id"],
        "flight_start": iso(row["flight_start"]),
        "flight_end": iso(row["flight_end"]),
        "status": row["status"],
        "noncommercial_risk_score": row["noncommercial_risk_score"],
        "compliance_flags": list(row["compliance_flags"]),
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "public_file_status": row["public_file_status"],
        "public_file_due_at": iso(row["public_file_due_at"]),
        "public_file_posted_at": iso(row["public_file_posted_at"]),
        "public_file_reference": row["public_file_reference"],
    }
    payload.update(_common(row))
    return payload


def incident(row):
    payload = {
        "id": row["id"],
        "category": row["category"],
        "severity": row["severity"],
        "program_id": row["program_id"],
        "episode_id": row["episode_id"],
        "underwriting_spot_id": row["underwriting_spot_id"],
        "respondent_volunteer_id": row["respondent_volunteer_id"],
        "complainant_note": row["complainant_note"],
        "occurred_at": iso(row["occurred_at"]),
        "status": row["status"],
        "safe_harbor_violation": row["safe_harbor_violation"],
        "penalty_points": row["penalty_points"],
        "sanction": row["sanction"],
        "adjudicated_by_user_id": row["adjudicated_by_user_id"],
        "remediation_note": row["remediation_note"],
    }
    payload.update(_common(row))
    return payload


def drive(row):
    payload = {
        "id": row["id"],
        "name": row["name"],
        "goal_cents": row["goal_cents"],
        "start_at": iso(row["start_at"]),
        "end_at": iso(row["end_at"]),
        "phone_line_count": row["phone_line_count"],
        "status": row["status"],
    }
    payload.update(calc.drive_aggregates(row))
    payload.update(_common(row))
    return payload


def shift(row):
    payload = {
        "id": row["id"],
        "drive_id": row["drive_id"],
        "volunteer_id": row["volunteer_id"],
        "start_at": iso(row["start_at"]),
        "end_at": iso(row["end_at"]),
        "status": row["status"],
        "pledges_taken_count": row["pledges_taken_count"],
    }
    payload.update(_common(row))
    return payload


def premium(row):
    payload = {
        "id": row["id"],
        "sku": row["sku"],
        "name": row["name"],
        "tier_threshold_cents": row["tier_threshold_cents"],
        "fair_market_value_cents": row["fair_market_value_cents"],
        "units_received_qty": row["units_received_qty"],
        "on_hand_qty": row["on_hand_qty"],
        "reserved_qty": row["reserved_qty"],
        "shipped_qty": row["shipped_qty"],
        "status": calc.premium_status(row),
    }
    payload.update(_common(row))
    return payload


def pledge(row):
    payload = {
        "id": row["id"],
        "drive_id": row["drive_id"],
        "shift_id": row["shift_id"],
        "premium_item_id": row["premium_item_id"],
        "donor_name": row["donor_name"],
        "amount_cents": row["amount_cents"],
        "wants_premium": row["wants_premium"],
        "payment_status": row["payment_status"],
        "premium_status": row["premium_status"],
        "tax_deductible_cents": row["tax_deductible_cents"],
    }
    payload.update(_common(row))
    return payload
