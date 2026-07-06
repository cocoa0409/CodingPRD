"""Payload factories — one per entity, input fields only."""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix: str = "journo") -> str:
    """Generate a process-unique email (journalist email must be unique)."""
    return f"{prefix}{next(_email_counter)}@example.com"


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Client",
        "industry": "TECH",
        "monthly_retainer_cents": 300000,
        "monthly_hours_cap": 20,
        "overage_rate_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_outlet_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Outlet",
        "tier": "TRADE",
        "monthly_unique_visitors": 100000,
        "domain_authority": 40,
    }
    defaults.update(overrides)
    return defaults


def create_journalist_payload(outlet_id: str, **overrides) -> dict:
    defaults = {
        "outlet_id": outlet_id,
        "full_name": "Test Journalist",
        "email": unique_email(),
        "beat": "TECH",
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "title": "Test Campaign",
        "objective": "LAUNCH",
        "budget_cents": 800000,
        "target_beat": "TECH",
    }
    defaults.update(overrides)
    return defaults


def create_retainer_period_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "period_month": "2026-03",
    }
    defaults.update(overrides)
    return defaults


def create_time_entry_payload(retainer_period_id: str, **overrides) -> dict:
    defaults = {
        "retainer_period_id": retainer_period_id,
        "staff_id": "staff-1",
        "work_type": "STRATEGY",
        "billable_hours": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_spokesperson_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "full_name": "Test Spokesperson",
        "title": "CEO",
    }
    defaults.update(overrides)
    return defaults


def create_media_list_payload(campaign_id: str, journalist_ids: list,
                              expected_campaign_version, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "name": "Test List",
        "journalist_ids": list(journalist_ids),
        "expected_campaign_version": expected_campaign_version,
    }
    defaults.update(overrides)
    return defaults


def create_pitch_payload(campaign_id: str, media_list_id: str, journalist_id: str, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "media_list_id": media_list_id,
        "journalist_id": journalist_id,
        "angle": "Test angle",
    }
    defaults.update(overrides)
    return defaults


def create_press_release_payload(campaign_id: str, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "headline": "Test Headline",
        "embargo_until": "2026-03-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_distribution_payload(press_release_id: str, journalist_id: str, **overrides) -> dict:
    defaults = {
        "press_release_id": press_release_id,
        "journalist_id": journalist_id,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_payload(campaign_id: str, journalist_id: str, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "journalist_id": journalist_id,
        "headline": "Test Clip",
        "published_at": "2026-03-02T00:00:00Z",
        "sentiment": "POSITIVE",
        "prominence": "FEATURE",
    }
    defaults.update(overrides)
    return defaults


def create_interview_payload(campaign_id: str, spokesperson_id: str, journalist_id: str,
                             starts_at: str, ends_at: str, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "spokesperson_id": spokesperson_id,
        "journalist_id": journalist_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def create_crisis_event_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "summary": "Test crisis",
        "severity": "HIGH",
    }
    defaults.update(overrides)
    return defaults
