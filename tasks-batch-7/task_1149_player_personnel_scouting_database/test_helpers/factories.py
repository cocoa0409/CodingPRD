"""Payload factories — one per entity, input fields only.

Every factory takes **overrides so tests can pin the values they care about.
Defaults are chosen to be valid against the PRD's declared constraints.
"""


def create_scout_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Scout",
        "level": "AREA",
    }
    defaults.update(overrides)
    return defaults


def create_prospect_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Prospect",
        "position": "QB",
        "college": "State U",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "raw_grade": 7.00,
        "scheme_fit": 1.00,
    }
    defaults.update(overrides)
    return defaults


def create_video_tag_payload(**overrides) -> dict:
    defaults = {
        "clip_url": "https://video.example/clip-1",
        "start_sec": 10,
        "end_sec": 42,
        "tag": "SCHEME",
    }
    defaults.update(overrides)
    return defaults


def create_flag_payload(**overrides) -> dict:
    defaults = {
        "flag_type": "CHARACTER",
        "severity": "LOW",
        "detail": "test flag detail",
    }
    defaults.update(overrides)
    return defaults


def create_draft_board_payload(**overrides) -> dict:
    defaults = {
        "season_year": 2026,
    }
    defaults.update(overrides)
    return defaults


def create_board_entry_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_reorder_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_roster_need_payload(**overrides) -> dict:
    defaults = {
        "season_year": 2026,
        "position": "QB",
        "priority_tier": "P2",
    }
    defaults.update(overrides)
    return defaults


def create_free_agent_target_payload(**overrides) -> dict:
    defaults = {
        "player_name": "Test Vet",
        "position": "QB",
        "season_year": 2026,
        "base_salary_cents": 1000000,
        "signing_bonus_cents": 0,
        "contract_years": 1,
    }
    defaults.update(overrides)
    return defaults


def create_budget_payload(**overrides) -> dict:
    defaults = {
        "season_year": 2026,
        "base_cap_cents": 100000000,
        "rollover_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(**overrides) -> dict:
    defaults = {
        "rollover_delta_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_interview_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-06-01T10:00:00Z",
        "end_at": "2026-06-01T11:00:00Z",
        "location": "Combine",
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": "Interview Room A",
        "capacity": 6,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-06-01T10:00:00Z",
        "end_at": "2026-06-01T11:00:00Z",
        "purpose": "formal interview",
    }
    defaults.update(overrides)
    return defaults


def create_outcome_payload(**overrides) -> dict:
    defaults = {
        "season_year": 2026,
        "games_started": 8,
        "pro_bowl": False,
        "outcome_percentile": 50,
    }
    defaults.update(overrides)
    return defaults
