"""Entity serializers: fixed field lists with per-field output formatting."""

from decimal import Decimal

from store import iso, iso_date, out_num

COMMON = (("id", "str"), ("created_at", "dt"), ("updated_at", "dt"), ("version", "int"))

SPECS = {
    "district": (
        ("name", "str"), ("state_code", "str"), ("max_age_rating", "str"),
        ("academic_standing_basis", "str"), ("min_gpa", "n3"), ("probation_gpa_floor", "n3"),
        ("dispute_window_hours", "int"), ("subsidy_pct", "n3"), ("subsidy_pool_cents", "int"),
        ("subsidy_pool_initial_cents", "int"), ("recruiting_dead_period_start", "dt"),
        ("recruiting_dead_period_end", "dt"), ("recruiting_contact_cap_per_window", "int"),
        ("recruiting_window_days", "int"), ("broadcast_buffer_minutes", "int"),
    ),
    "school": (
        ("district_id", "str"), ("name", "str"), ("nces_code", "str"),
        ("enrollment_verified_through", "date"), ("concurrent_broadcast_capacity", "int"),
        ("status", "str"),
    ),
    "coach": (
        ("school_id", "str"), ("full_name", "str"), ("email", "str"),
        ("certification_status", "str"), ("background_check_expires_on", "date"),
        ("certified_at", "dt"),
    ),
    "student": (
        ("school_id", "str"), ("full_name", "str"), ("birthdate", "date"),
        ("grade_level", "int"), ("enrollment_status", "str"), ("credits_completed", "num"),
        ("latest_term_label", "str"), ("latest_term_gpa", "n3"), ("latest_term_credits", "num"),
        ("prior_term_gpa", "n3"), ("prior_term_credits", "num"), ("effective_gpa", "n3"),
        ("academic_standing", "str"), ("standing_basis_applied", "str"),
        ("fair_play_status", "str"), ("showcase_status", "str"), ("nominating_team_id", "str"),
        ("award_tier", "str"), ("provisional_award_cents", "int"),
        ("scholarship_award_cents", "int"), ("scholarship_award_state", "str"),
        ("recruiting_contact_log", "log"),
    ),
    "title": (
        ("name", "str"), ("publisher", "str"), ("age_rating", "str"),
        ("min_player_age", "int"), ("server_pool_id", "str"),
        ("server_pool_capacity", "int"), ("match_duration_minutes", "int"),
    ),
    "title_approval": (
        ("district_id", "str"), ("title_id", "str"), ("requested_by_school_id", "str"),
        ("status", "str"), ("decided_by_user_id", "str"), ("decided_at", "dt"),
        ("decision_note", "str"),
    ),
    "season": (
        ("title_id", "str"), ("name", "str"), ("division", "str"),
        ("registration_opens_at", "dt"), ("registration_closes_at", "dt"),
        ("roster_lock_at", "dt"), ("regular_season_end_at", "dt"),
        ("age_cutoff_date", "date"), ("max_age", "int"), ("min_starters", "int"),
        ("max_starters", "int"), ("base_entry_fee_cents", "int"),
        ("per_starter_fee_cents", "int"), ("seeding_basis", "str"),
        ("seeding_basis_applied", "str"), ("playoff_slots", "int"), ("status", "str"),
        ("seeding_state", "str"), ("seed_order", "raw"), ("registered_team_count", "int"),
        ("match_point_pool", "int"),
    ),
    "team": (
        ("season_id", "str"), ("school_id", "str"), ("title_id", "str"), ("coach_id", "str"),
        ("name", "str"), ("status", "str"), ("registered_at", "dt"),
        ("roster_locked_at", "dt"), ("starter_slots_used", "int"),
        ("starter_slots_available", "int"), ("active_starter_count", "int"),
        ("entry_fee_cents", "int"), ("subsidy_granted_cents", "int"),
        ("net_fee_due_cents", "int"), ("match_points", "int"), ("wins", "int"),
        ("losses", "int"), ("draws", "int"), ("forfeits_charged", "int"),
        ("forfeit_wins", "int"), ("games_won", "int"), ("games_lost", "int"),
        ("game_differential", "int"), ("seed_points", "n4"), ("seed_position", "int"),
        ("seed_stale", "bool"), ("integrity_score", "n2"), ("suspension_reason", "str"),
    ),
    "roster_slot": (
        ("team_id", "str"), ("student_id", "str"), ("slot_role", "str"),
        ("verification_status", "str"), ("academic_status", "str"),
        ("participation_status", "str"), ("enrollment_verified_by_user_id", "str"),
        ("academics_verified_by_user_id", "str"), ("enrollment_document_ref", "str"),
        ("verified_birthdate", "date"), ("age_at_cutoff", "int"),
        ("standing_at_verification", "str"), ("effective_gpa_at_verification", "n3"),
        ("released_at", "dt"), ("ineligibility_reason", "str"),
    ),
    "match": (
        ("season_id", "str"), ("home_team_id", "str"), ("away_team_id", "str"),
        ("scheduled_start_at", "dt"), ("scheduled_end_at", "dt"), ("server_pool_id", "str"),
        ("region_code", "str"), ("patch_version", "str"), ("play_status", "str"),
        ("result_status", "str"), ("dispute_status", "str"), ("broadcast_status", "str"),
        ("broadcast_school_id", "str"), ("broadcast_start_at", "dt"),
        ("broadcast_end_at", "dt"), ("spectator_strikes", "int"),
        ("home_reported_home_games_won", "int"), ("home_reported_away_games_won", "int"),
        ("away_reported_home_games_won", "int"), ("away_reported_away_games_won", "int"),
        ("home_games_won", "int"), ("away_games_won", "int"),
        ("result_confirmed_at", "dt"), ("dispute_deadline_at", "dt"),
        ("dispute_filed_by_team_id", "str"), ("dispute_reason_code", "str"),
        ("winner_team_id", "str"), ("forfeiting_team_id", "str"),
        ("home_points_awarded", "int"), ("away_points_awarded", "int"),
    ),
    "fair_play_case": (
        ("team_id", "str"), ("subject_type", "str"), ("subject_student_id", "str"),
        ("subject_match_id", "str"), ("case_type", "str"), ("evidence_ref", "str"),
        ("severity", "str"), ("status", "str"), ("reported_by_user_id", "str"),
        ("investigator_user_id", "str"), ("decider_user_id", "str"),
        ("appeal_decider_user_id", "str"), ("severity_weight", "n2"),
        ("repeat_index", "int"), ("applied_penalty", "n2"), ("sanction_type", "str"),
        ("appeal_grounds", "str"), ("decided_at", "dt"),
    ),
}


def _emit(kind_of, value):
    if value is None:
        return None
    if kind_of == "dt":
        return iso(value)
    if kind_of == "date":
        return iso_date(value)
    if kind_of == "int":
        return int(value)
    if kind_of == "bool":
        return bool(value)
    if kind_of == "n3":
        return out_num(value, 3)
    if kind_of == "n4":
        return out_num(value, 4)
    if kind_of == "n2":
        return out_num(value, 2)
    if kind_of == "num":
        if isinstance(value, Decimal):
            return float(value) if value != value.to_integral_value() else int(value)
        return value
    if kind_of == "log":
        return [
            {
                "contacted_at": iso(entry["contacted_at"]),
                "org_code": entry["org_code"],
                "channel": entry["channel"],
                "purpose": entry["purpose"],
            }
            for entry in value
        ]
    if kind_of == "raw":
        return list(value) if isinstance(value, (list, tuple)) else value
    return value


def dump(rec):
    """Serialize a record using the field spec for its kind."""
    if rec is None:
        return None
    spec = SPECS[rec["_kind"]]
    out = {}
    for name, kind_of in COMMON:
        out[name] = _emit(kind_of, rec.get(name))
    for name, kind_of in spec:
        out[name] = _emit(kind_of, rec.get(name))
    return out


def dumper(kind):
    return dump
