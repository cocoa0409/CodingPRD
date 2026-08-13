"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULT_TOURNAMENT = {
    "game_title": "TacShooter",
    "region": "NA",
    "prize_pool_target_cents": 100000,
    "roster_size": 1,
    "max_roster_size": 2,
    "registration_opens_at": "2026-08-01T00:00:00Z",
    "registration_closes_at": "2026-08-10T00:00:00Z",
    "minor_curfew_local": "22:00",
}


def create_tournament_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_TOURNAMENT, name="Test Cup")
    defaults.update(overrides)
    return defaults


def create_player_payload(**overrides) -> dict:
    defaults = {
        "handle": "player-1",
        "date_of_birth": "2000-01-01",
        "region": "NA",
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(tournament_id, captain_player_id,
                                **overrides) -> dict:
    defaults = {
        "tournament_id": tournament_id,
        "team_name": "Alpha",
        "manager_contact_email": "manager@x.gg",
        "region_rank_points": 100,
        "prior_event_points": 0,
        "qualifier_wins": 0,
        "captain_player_id": captain_player_id,
    }
    defaults.update(overrides)
    return defaults


def create_roster_slot_payload(registration_id, player_id,
                               slot_role="STARTER", **overrides) -> dict:
    defaults = {
        "registration_id": registration_id,
        "player_id": player_id,
        "slot_role": slot_role,
    }
    defaults.update(overrides)
    return defaults


def create_server_payload(tournament_id, **overrides) -> dict:
    defaults = {
        "tournament_id": tournament_id,
        "label": "S1",
        "region": "NA",
    }
    defaults.update(overrides)
    return defaults


def schedule_match_payload(server_id, scheduled_start_at, duration_minutes,
                           assigned_referee_id, **overrides) -> dict:
    defaults = {
        "server_id": server_id,
        "scheduled_start_at": scheduled_start_at,
        "duration_minutes": duration_minutes,
        "assigned_referee_id": assigned_referee_id,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(match_id, registration_id, **overrides) -> dict:
    defaults = {
        "match_id": match_id,
        "registration_id": registration_id,
        "reason": "RULE_VIOLATION",
        "details": "evidence package attached",
    }
    defaults.update(overrides)
    return defaults


def create_integrity_case_payload(player_id, **overrides) -> dict:
    defaults = {
        "player_id": player_id,
        "evidence_summary": "anti-cheat export digest",
    }
    defaults.update(overrides)
    return defaults


def create_talent_payload(**overrides) -> dict:
    defaults = {
        "stage_name": "CasterOne",
        "home_region": "NA",
        "day_rate_cents": 80000,
    }
    defaults.update(overrides)
    return defaults


def create_talent_booking_payload(tournament_id, talent_id,
                                  **overrides) -> dict:
    defaults = {
        "tournament_id": tournament_id,
        "talent_id": talent_id,
        "stage_label": "MAIN",
        "shift_start_at": "2026-08-12T10:00:00Z",
        "shift_end_at": "2026-08-12T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_sponsor_deal_payload(tournament_id, **overrides) -> dict:
    defaults = {
        "tournament_id": tournament_id,
        "sponsor_name": "Acme",
        "contact_user_id": "sm-1",
        "rights_tier": "TITLE",
        "bonus_cents": 200000,
        "content_rights": ["VOD"],
    }
    defaults.update(overrides)
    return defaults
