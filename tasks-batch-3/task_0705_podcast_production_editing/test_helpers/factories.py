"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional fields (those with a declared default in
the PRD) are omitted from defaults unless a test overrides them.
"""


def create_show_payload(**overrides) -> dict:
    """Required: title, format, billing_model. Optional: target_loudness_lufs."""
    payload = {
        "title": "Test Show",
        "format": "SOLO",
        "billing_model": "PER_EPISODE",
    }
    payload.update(overrides)
    return payload


def create_contract_payload(show_id, **overrides) -> dict:
    """Required: show_id, tier, engagement_type.
    Optional: monthly_included_episodes, loyalty_discount_pct."""
    payload = {
        "show_id": show_id,
        "tier": "STANDARD",
        "engagement_type": "PER_EPISODE",
    }
    payload.update(overrides)
    return payload


def create_retainer_cycle_payload(contract_id, cycle_start_utc, cycle_end_utc, **overrides) -> dict:
    """Required: contract_id, cycle_start_utc, cycle_end_utc."""
    payload = {
        "contract_id": contract_id,
        "cycle_start_utc": cycle_start_utc,
        "cycle_end_utc": cycle_end_utc,
    }
    payload.update(overrides)
    return payload


def create_engineer_payload(**overrides) -> dict:
    """Required: name. Optional: remote_buffer_minutes, active."""
    payload = {"name": "Test Engineer"}
    payload.update(overrides)
    return payload


def create_episode_payload(show_id, contract_id, **overrides) -> dict:
    """Required: show_id, contract_id, title, planned_track_count.
    Optional: transcript_requested."""
    payload = {
        "show_id": show_id,
        "contract_id": contract_id,
        "title": "Test Episode",
        "planned_track_count": 1,
    }
    payload.update(overrides)
    return payload


def create_session_payload(episode_id, engineer_id, scheduled_start_utc,
                           scheduled_end_utc, **overrides) -> dict:
    """Required: episode_id, engineer_id, capture_mode, scheduled_start_utc,
    scheduled_end_utc."""
    payload = {
        "episode_id": episode_id,
        "engineer_id": engineer_id,
        "capture_mode": "STUDIO",
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
    }
    payload.update(overrides)
    return payload


def create_deliverable_payload(episode_id, kind, **overrides) -> dict:
    """Required: episode_id, kind."""
    payload = {"episode_id": episode_id, "kind": kind}
    payload.update(overrides)
    return payload


def create_asset_version_payload(deliverable_id, **overrides) -> dict:
    """Required: deliverable_id. Optional: supersedes_version_id,
    integrated_loudness_lufs."""
    payload = {"deliverable_id": deliverable_id}
    payload.update(overrides)
    return payload


def create_ad_campaign_payload(show_id, **overrides) -> dict:
    """Required: show_id, sponsor_name. Optional: platform_fee_pct."""
    payload = {"show_id": show_id, "sponsor_name": "Test Sponsor"}
    payload.update(overrides)
    return payload


def create_ad_slot_payload(campaign_id, episode_id, gross_cents, **overrides) -> dict:
    """Required: campaign_id, episode_id, placement, gross_cents."""
    payload = {
        "campaign_id": campaign_id,
        "episode_id": episode_id,
        "placement": "MID_ROLL",
        "gross_cents": gross_cents,
    }
    payload.update(overrides)
    return payload
