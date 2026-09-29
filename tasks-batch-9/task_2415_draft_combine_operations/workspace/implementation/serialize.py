"""Entity -> JSON projections. Derived fields are recomputed on every read."""

from decimal import Decimal

import derive
from timeutil import fmt_iso


def num(value):
    """Render a Decimal (or plain number) as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(rec, out):
    out["id"] = rec["id"]
    out["created_at"] = fmt_iso(rec["created_at"])
    out["updated_at"] = fmt_iso(rec["updated_at"])
    out["version"] = rec["version"]
    return out


def draft_cycle(rec):
    count, points = derive.pick_inventory(rec["id"])
    out = {
        "season_year": rec["season_year"],
        "declaration_deadline_at": fmt_iso(rec["declaration_deadline_at"]),
        "combine_week_start_at": fmt_iso(rec["combine_week_start_at"]),
        "combine_week_end_at": fmt_iso(rec["combine_week_end_at"]),
        "draft_start_at": fmt_iso(rec["draft_start_at"]),
        "rounds_count": rec["rounds_count"],
        "compressed_final_day": rec["compressed_final_day"],
        "status": rec["status"],
        "club_count": derive.club_count(rec["id"]),
        "lottery_completed": rec["lottery_completed"],
        "lottery_slot_club_ids": list(rec["lottery_slot_club_ids"]),
        "order_finalized_at": fmt_iso(rec["order_finalized_at"]),
        "current_overall_number": derive.current_overall_number(rec["id"]),
        "udfa_window_close_at": fmt_iso(rec["udfa_window_close_at"]),
        "posture": derive.cycle_posture(rec),
        "pick_inventory_chart_points": num(points),
        "pick_inventory_count": count,
    }
    return _common(rec, out)


def club(rec):
    capital = derive.draft_capital_points(rec)
    out = {
        "draft_cycle_id": rec["draft_cycle_id"],
        "club_code": rec["club_code"],
        "market_name": rec["market_name"],
        "registration_status": rec["registration_status"],
        "playoff_qualified": rec["playoff_qualified"],
        "playoff_exit_round": rec["playoff_exit_round"],
        "prior_season_win_pct": num(rec["prior_season_win_pct"]),
        "strength_of_schedule": num(rec["strength_of_schedule"]),
        "head_to_head_rank": rec["head_to_head_rank"],
        "lottery_combinations": rec["lottery_combinations"],
        "forfeited_round_numbers": list(rec["forfeited_round_numbers"]),
        "pre_lottery_rank": rec["pre_lottery_rank"],
        "draft_order_index": rec["draft_order_index"],
        "rookie_pool_total_cents": rec["rookie_pool_total_cents"],
        "rookie_pool_remaining_cents": derive.rookie_pool_remaining(rec),
        "draft_capital_points": num(capital),
        "trade_authorization_tier": derive.club_tier(rec),
        "timeouts_remaining": rec["timeouts_remaining"],
        "udfa_pool_total_cents": rec["udfa_pool_total_cents"],
        "udfa_pool_remaining_cents": derive.udfa_pool_remaining(rec),
    }
    return _common(rec, out)


def prospect(rec):
    out = {
        "draft_cycle_id": rec["draft_cycle_id"],
        "full_name": rec["full_name"],
        "position_group": rec["position_group"],
        "school_code": rec["school_code"],
        "seasons_played": rec["seasons_played"],
        "scouting_grade": num(rec["scouting_grade"]),
        "position_group_scarcity_rank": rec["position_group_scarcity_rank"],
        "declaration_status": rec["declaration_status"],
        "declared_at": fmt_iso(rec["declared_at"]),
        "late_declaration_waived": rec["late_declaration_waived"],
        "early_entry_waived": rec["early_entry_waived"],
        "eligibility_status": rec["eligibility_status"],
        "invitation_status": rec["invitation_status"],
        "consent_status": rec["consent_status"],
        "consent_scope": rec["consent_scope"],
        "consent_expires_at": fmt_iso(rec["consent_expires_at"]),
        "medical_clearance_status": rec["medical_clearance_status"],
        "drafted_pick_overall_number": rec["drafted_pick_overall_number"],
        "signing_status": rec["signing_status"],
    }
    return _common(rec, out)


def eligibility_waiver(rec):
    out = {
        "prospect_id": rec["prospect_id"],
        "waiver_type": rec["waiver_type"],
        "rationale": rec["rationale"],
        "status": rec["status"],
        "info_request_count": rec["info_request_count"],
        "submitted_by_user_id": rec["submitted_by_user_id"],
        "opened_by_user_id": rec["opened_by_user_id"],
        "decided_by_user_id": rec["decided_by_user_id"],
        "decision_note": rec["decision_note"],
        "decided_at": fmt_iso(rec["decided_at"]),
    }
    return _common(rec, out)


def medical_station(rec):
    out = {
        "station_code": rec["station_code"],
        "exam_type": rec["exam_type"],
        "turnaround_buffer_minutes": rec["turnaround_buffer_minutes"],
        "status": rec["status"],
    }
    return _common(rec, out)


def interview_room(rec):
    out = {
        "room_code": rec["room_code"],
        "concurrent_capacity": rec["concurrent_capacity"],
        "status": rec["status"],
    }
    return _common(rec, out)


def combine_booking(rec):
    out = {
        "prospect_id": rec["prospect_id"],
        "booking_type": rec["booking_type"],
        "medical_station_id": rec["medical_station_id"],
        "interview_room_id": rec["interview_room_id"],
        "club_id": rec["club_id"],
        "starts_at": fmt_iso(rec["starts_at"]),
        "ends_at": fmt_iso(rec["ends_at"]),
        "status": rec["status"],
        "duration_minutes": rec["duration_minutes"],
    }
    return _common(rec, out)


def medical_evaluation(rec):
    out = {
        "combine_booking_id": rec["combine_booking_id"],
        "prospect_id": rec["prospect_id"],
        "filed_by_user_id": rec["filed_by_user_id"],
        "findings_code": rec["findings_code"],
        "medical_grade": rec["medical_grade"],
        "confidentiality_tier": rec["confidentiality_tier"],
        "disclosure_state": rec["disclosure_state"],
        "active_share_count": derive.active_share_count(rec["id"]),
    }
    return _common(rec, out)


def medical_record_share(rec):
    out = {
        "medical_evaluation_id": rec["medical_evaluation_id"],
        "club_id": rec["club_id"],
        "requested_by_user_id": rec["requested_by_user_id"],
        "requested_by_role": rec["requested_by_role"],
        "scope": rec["scope"],
        "status": rec["status"],
        "granted_at": fmt_iso(rec["granted_at"]),
        "expires_at": fmt_iso(rec["expires_at"]),
        "effective_access": derive.effective_access(rec),
        "denial_reason": rec["denial_reason"],
    }
    return _common(rec, out)


def draft_pick(rec):
    out = {
        "draft_cycle_id": rec["draft_cycle_id"],
        "owning_club_id": rec["owning_club_id"],
        "original_club_id": rec["original_club_id"],
        "round_number": rec["round_number"],
        "pick_in_round": rec["pick_in_round"],
        "overall_number": rec["overall_number"],
        "is_compensatory": rec["is_compensatory"],
        "compensatory_sequence": rec["compensatory_sequence"],
        "status": rec["status"],
        "chart_value_points": num(rec["chart_value_points"]),
        "slot_total_value_cents": rec["slot_total_value_cents"],
        "slot_signing_bonus_cents": rec["slot_signing_bonus_cents"],
        "slot_first_year_cap_charge_cents": rec["slot_first_year_cap_charge_cents"],
        "slot_total_cap_commitment_cents": rec["slot_total_cap_commitment_cents"],
        "on_clock_started_at": fmt_iso(rec["on_clock_started_at"]),
        "deadline_at": fmt_iso(rec["deadline_at"]),
        "timeouts_used": rec["timeouts_used"],
        "out_of_order_authorized": rec["out_of_order_authorized"],
        "selected_prospect_id": rec["selected_prospect_id"],
        "selection_source": rec["selection_source"],
        "pass_reason": rec["pass_reason"],
    }
    return _common(rec, out)


def pick_trade(rec):
    out = {
        "draft_cycle_id": rec["draft_cycle_id"],
        "proposing_club_id": rec["proposing_club_id"],
        "receiving_club_id": rec["receiving_club_id"],
        "offered_pick_ids": list(rec["offered_pick_ids"]),
        "requested_pick_ids": list(rec["requested_pick_ids"]),
        "round_index": rec["round_index"],
        "status": rec["status"],
        "last_actor_club_id": rec["last_actor_club_id"],
        "chart_balance_points": num(rec["chart_balance_points"]),
        "imbalance_ratio": num(rec["imbalance_ratio"]),
        "surplus_balance_points": num(rec["surplus_balance_points"]),
        "conditional_round_number": rec["conditional_round_number"],
        "conditional_condition_code": rec["conditional_condition_code"],
        "conditional_probability_tier": rec["conditional_probability_tier"],
        "conditional_status": rec["conditional_status"],
        "conditional_conveyed_overall_number": rec[
            "conditional_conveyed_overall_number"
        ],
    }
    return _common(rec, out)


def compensatory_claim(rec):
    out = {
        "draft_cycle_id": rec["draft_cycle_id"],
        "club_id": rec["club_id"],
        "claim_type": rec["claim_type"],
        "player_name": rec["player_name"],
        "departed_apy_cents": rec["departed_apy_cents"],
        "snap_pct": num(rec["snap_pct"]),
        "postseason_honor": rec["postseason_honor"],
        "status": rec["status"],
        "claim_score": num(rec["claim_score"]),
        "advisory_snap_adjusted_score": num(rec["advisory_snap_adjusted_score"]),
        "qualifies": rec["qualifies"],
        "awarded_round": rec["awarded_round"],
        "awarded_sequence": rec["awarded_sequence"],
    }
    return _common(rec, out)


def player_contract(rec):
    out = {
        "prospect_id": rec["prospect_id"],
        "club_id": rec["club_id"],
        "draft_pick_id": rec["draft_pick_id"],
        "origin": rec["origin"],
        "status": rec["status"],
        "contract_years": rec["contract_years"],
        "total_value_cents": rec["total_value_cents"],
        "signing_bonus_cents": rec["signing_bonus_cents"],
        "first_year_cap_charge_cents": rec["first_year_cap_charge_cents"],
        "total_cap_commitment_cents": rec["total_cap_commitment_cents"],
        "signed_at": fmt_iso(rec["signed_at"]),
    }
    return _common(rec, out)


SERIALIZERS = {
    "DraftCycle": draft_cycle,
    "Club": club,
    "Prospect": prospect,
    "EligibilityWaiver": eligibility_waiver,
    "MedicalStation": medical_station,
    "InterviewRoom": interview_room,
    "CombineBooking": combine_booking,
    "MedicalEvaluation": medical_evaluation,
    "MedicalRecordShare": medical_record_share,
    "DraftPick": draft_pick,
    "PickTrade": pick_trade,
    "CompensatoryClaim": compensatory_claim,
    "PlayerContract": player_contract,
}


def serialize(rec):
    return SERIALIZERS[rec["_kind"]](rec)


def serialize_many(records):
    return [serialize(r) for r in records]
