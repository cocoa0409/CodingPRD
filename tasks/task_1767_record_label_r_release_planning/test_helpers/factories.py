"""Payload factories — one per entity, input fields only."""


def create_label_payload(**overrides) -> dict:
    defaults = {"name": "Test Label"}
    defaults.update(overrides)
    return defaults


def create_artist_payload(label_id, **overrides) -> dict:
    defaults = {
        "label_id": label_id,
        "stage_name": "Test Act",
        "genre": "POP",
        "birth_date": "1995-04-12",
        "monthly_streams": 600_000,
        "social_followers": 800_000,
        "engagement_rate": 0.5,
        "live_draw_avg": 1_000,
    }
    defaults.update(overrides)
    return defaults


def create_deal_memo_payload(**overrides) -> dict:
    defaults = {
        "advance_cents": 0,
        "base_royalty_rate_bps": 2_000,
        "recoupment_scope": "MASTER_ONLY",
        "promo_costs_recoupable": False,
        "options_total": 0,
        "option_term_months": 12,
        "option_escalation_bps": 0,
        "term_months": 12,
        "valid_until_date": "2028-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_recording_project_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Project",
        "project_type": "SINGLE",
        "budget_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_milestone_payload(**overrides) -> dict:
    defaults = {
        "name": "Milestone 1",
        "sequence": 1,
        "due_date": "2026-09-01",
        "payment_cents": 1_000,
    }
    defaults.update(overrides)
    return defaults


def create_track_payload(**overrides) -> dict:
    defaults = {
        "title": "Track 1",
        "duration_seconds": 200,
        "isrc": "USRC10000001",
    }
    defaults.update(overrides)
    return defaults


def create_release_payload(project_id, track_ids, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "title": "Test Release",
        "release_type": "SINGLE",
        "release_date": "2026-09-01",
        "track_ids": list(track_ids),
    }
    defaults.update(overrides)
    return defaults


def create_distributor_payload(label_id, **overrides) -> dict:
    defaults = {
        "label_id": label_id,
        "name": "Distributor 1",
        "channel_type": "DSP",
    }
    defaults.update(overrides)
    return defaults


def create_beat_payload(**overrides) -> dict:
    defaults = {
        "beat_type": "TEASER",
        "channel": "PLAYLIST",
        "start_date": "2026-08-01",
        "end_date": "2026-08-08",
        "budget_cents": 5_000,
    }
    defaults.update(overrides)
    return defaults


def create_promo_campaign_payload(**overrides) -> dict:
    defaults = {
        "channel": "PLAYLIST",
        "start_date": "2026-08-05",
        "end_date": "2026-08-10",
        "spend_cap_cents": 50_000,
    }
    defaults.update(overrides)
    return defaults


def create_tour_support_payload(**overrides) -> dict:
    defaults = {
        "tour_name": "Test Tour",
        "requested_amount_cents": 24_000,
    }
    defaults.update(overrides)
    return defaults


def create_tour_expense_payload(**overrides) -> dict:
    defaults = {
        "category": "TRAVEL",
        "amount_cents": 1_000,
        "expense_date": "2026-09-10",
    }
    defaults.update(overrides)
    return defaults


def create_revenue_report_payload(label_id, distributor_id, release_id, **overrides) -> dict:
    defaults = {
        "label_id": label_id,
        "distributor_id": distributor_id,
        "release_id": release_id,
        "period": "2026-Q3",
        "channel": "STREAMING",
        "units": 100,
        "gross_revenue_cents": 1_000,
    }
    defaults.update(overrides)
    return defaults


def create_royalty_run_payload(label_id, period="2026-Q3", **overrides) -> dict:
    defaults = {
        "label_id": label_id,
        "period": period,
    }
    defaults.update(overrides)
    return defaults
