"""Payload factories — one per resource, carrying only caller-supplied input fields."""

from .constants import TEST_DEFAULTS


def create_client_payload(**overrides) -> dict:
    payload = {
        "name": "Acme Retail",
        "industry": "RETAIL",
        "billing_email": "ap@acme.test",
    }
    payload.update(overrides)
    return payload


def create_rate_card_payload(**overrides) -> dict:
    payload = {
        "name": "Standard 2026",
        "rate_junior_cents_per_hour": TEST_DEFAULTS["RATE_JUNIOR_CENTS_PER_HOUR"],
        "rate_senior_cents_per_hour": TEST_DEFAULTS["RATE_SENIOR_CENTS_PER_HOUR"],
        "rate_director_cents_per_hour": TEST_DEFAULTS["RATE_DIRECTOR_CENTS_PER_HOUR"],
    }
    payload.update(overrides)
    return payload


def create_staff_member_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dana Lee",
        "grade": "SENIOR",
        "standard_daily_capacity_minutes": TEST_DEFAULTS["STANDARD_DAILY_CAPACITY_MINUTES"],
        "cost_rate_cents_per_hour": TEST_DEFAULTS["COST_RATE_SENIOR"],
    }
    payload.update(overrides)
    return payload


def create_media_placement_payload(**overrides) -> dict:
    payload = {
        "publisher_name": "StreamCo",
        "channel": "VIDEO",
        "min_dark_days": 0,
    }
    payload.update(overrides)
    return payload


def create_retainer_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "initial_funding_cents": 5_000_000,
        "period_start": "2026-06-01",
        "period_end": "2026-09-01",
    }
    payload.update(overrides)
    return payload


def create_sow_payload(client_id, rate_card_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "rate_card_id": rate_card_id,
        "title": "Q3 Retainer SOW",
        "labor_cap_cents": TEST_DEFAULTS["LABOR_CAP_CENTS"],
        "markup_pct": TEST_DEFAULTS["MARKUP_PCT"],
        "effective_start": TEST_DEFAULTS["SOW_EFFECTIVE_START"],
        "effective_end": TEST_DEFAULTS["SOW_EFFECTIVE_END"],
    }
    payload.update(overrides)
    return payload


def create_campaign_payload(client_id, sow_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "sow_id": sow_id,
        "name": "Summer Push",
        "brief_summary": "Drive summer awareness",
        "objective": "AWARENESS",
    }
    payload.update(overrides)
    return payload


def create_deliverable_payload(campaign_id, **overrides) -> dict:
    payload = {"campaign_id": campaign_id, "title": "Hero film 30s cut"}
    payload.update(overrides)
    return payload


def create_time_entry_payload(campaign_id, staff_id, started_at, ended_at, **overrides) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "staff_id": staff_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "billable": True,
    }
    payload.update(overrides)
    return payload


def create_vendor_cost_payload(campaign_id, **overrides) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "vendor_name": "Freelance Editor",
        "vendor_type": "FREELANCER",
        "estimated_amount_cents": 100_000,
        "incurred_on": "2026-06-03",
    }
    payload.update(overrides)
    return payload


def create_media_plan_payload(campaign_id, **overrides) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "approved_budget_cents": 10_000_000,
        "allowed_channels": ["VIDEO"],
    }
    payload.update(overrides)
    return payload


def create_insertion_order_payload(
    media_plan_id, placement_id, expected_media_plan_version, **overrides
) -> dict:
    payload = {
        "media_plan_id": media_plan_id,
        "placement_id": placement_id,
        "flight_start": "2026-06-05",
        "flight_end": "2026-06-20",
        "gross_cents": 1_000_000,
        "expected_media_plan_version": expected_media_plan_version,
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(client_id, campaign_id, retainer_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "campaign_id": campaign_id,
        "retainer_id": retainer_id,
        "billing_mode": "FINAL",
        "period_start": TEST_DEFAULTS["PERIOD_START"],
        "period_end": TEST_DEFAULTS["PERIOD_END"],
    }
    payload.update(overrides)
    return payload
