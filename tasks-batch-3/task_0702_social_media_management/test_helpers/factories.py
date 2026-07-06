"""Payload factories — one per entity, input fields only."""


def create_client_payload(**overrides) -> dict:
    defaults = {"name": "Test Client", "account_manager_id": "am-1"}
    defaults.update(overrides)
    return defaults


def create_retainer_package_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "tier": "GROWTH",
        "monthly_retainer_fee_cents": 300000,
        "monthly_boost_budget_cents": 1000000,
        "monthly_post_quota": 10,
        "included_channels": 3,
    }
    defaults.update(overrides)
    return defaults


def create_channel_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "platform": "INSTAGRAM",
        "handle": "@test",
    }
    defaults.update(overrides)
    return defaults


def create_content_item_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "author_id": "cc-1",
        "title": "Test Title",
        "body": "Test body",
    }
    defaults.update(overrides)
    return defaults


def create_content_target_payload(content_item_id, channel_id, **overrides) -> dict:
    defaults = {"content_item_id": content_item_id, "channel_id": channel_id}
    defaults.update(overrides)
    return defaults


def schedule_payload(channel_id, slot_start_utc, **overrides) -> dict:
    defaults = {"channel_id": channel_id, "slot_start_utc": slot_start_utc, "duration_minutes": 15}
    defaults.update(overrides)
    return defaults


def create_boost_campaign_payload(client_id, content_item_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "content_item_id": content_item_id,
        "requested_budget_cents": 100000,
        "daily_cap_cents": 50000,
        "duration_days": 2,
    }
    defaults.update(overrides)
    return defaults


def reserve_payload(expected_client_version, **overrides) -> dict:
    defaults = {"expected_client_version": expected_client_version}
    defaults.update(overrides)
    return defaults


def record_spend_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_conversation_payload(channel_id, **overrides) -> dict:
    defaults = {"channel_id": channel_id, "kind": "DM", "external_author_handle": "@fan"}
    defaults.update(overrides)
    return defaults


def create_message_payload(conversation_id, **overrides) -> dict:
    defaults = {"conversation_id": conversation_id, "direction": "INBOUND", "body": "hi"}
    defaults.update(overrides)
    return defaults


def create_influencer_collab_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "influencer_handle": "@influencer",
        "offer_fee_cents": 100000,
        "deliverable_count": 2,
    }
    defaults.update(overrides)
    return defaults


def counter_payload(counter_fee_cents, **overrides) -> dict:
    defaults = {"counter_fee_cents": counter_fee_cents}
    defaults.update(overrides)
    return defaults


def create_ugc_asset_payload(collab_id, **overrides) -> dict:
    defaults = {"collab_id": collab_id, "asset_url": "http://u/1"}
    defaults.update(overrides)
    return defaults


def analytics_snapshot_payload(total_impressions, total_engagements, **overrides) -> dict:
    defaults = {"total_impressions": total_impressions, "total_engagements": total_engagements}
    defaults.update(overrides)
    return defaults
