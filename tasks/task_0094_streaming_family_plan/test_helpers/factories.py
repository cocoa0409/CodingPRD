"""Payload factories — one per writable entity, input fields only.

Each factory provides sensible defaults and accepts **overrides so a test can
control exactly the field under assertion. Only source:input fields appear here;
system/computed fields (id, status, version, size_mb, ad_breaks_served, ...) are
never sent.
"""


# --- Plan tier presets (PRD §3.1) ---
# AD_SUPPORTED -> ad_free false; AD_FREE / PREMIUM -> ad_free true;
# hd_offline_allowed true only on PREMIUM.

def create_plan_payload(**overrides) -> dict:
    """Default: a PREMIUM plan (ad-free, HD allowed, generous caps)."""
    defaults = {
        "tier": "PREMIUM",
        "monthly_fee_cents": 1000,
        "max_profiles": 6,
        "concurrent_stream_cap": 4,
        "max_registered_devices": 8,
        "download_quota_per_profile": 10,
        "ad_free": True,
        "hd_offline_allowed": True,
    }
    defaults.update(overrides)
    return defaults


def ad_supported_plan_payload(**overrides) -> dict:
    """An AD_SUPPORTED plan: ad_free false, no HD offline."""
    defaults = create_plan_payload(
        tier="AD_SUPPORTED",
        monthly_fee_cents=500,
        max_profiles=4,
        concurrent_stream_cap=2,
        max_registered_devices=4,
        download_quota_per_profile=3,
        ad_free=False,
        hd_offline_allowed=False,
    )
    defaults.update(overrides)
    return defaults


def ad_free_plan_payload(**overrides) -> dict:
    """An AD_FREE plan: ad_free true, HD offline NOT allowed (PREMIUM-only)."""
    defaults = create_plan_payload(
        tier="AD_FREE",
        monthly_fee_cents=800,
        max_profiles=4,
        concurrent_stream_cap=2,
        max_registered_devices=4,
        download_quota_per_profile=3,
        ad_free=True,
        hd_offline_allowed=False,
    )
    defaults.update(overrides)
    return defaults


def create_title_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Title",
        "maturity_rating": "PG",
        "runtime_minutes": 60,
        "downloadable": True,
        "license_size_mb": 300,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "owner_email": "owner@example.com",
        "billing_anchor_day": 1,
        "initial_credit_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_profile_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "display_name": "Test Profile",
        "kind": "ADULT",
    }
    defaults.update(overrides)
    return defaults


def create_parental_control_payload(**overrides) -> dict:
    defaults = {
        "max_rating": "PG13",
        "daily_watch_limit_minutes": 0,
        "curfew_start_min": 0,
        "curfew_end_min": 0,
    }
    defaults.update(overrides)
    return defaults


def create_invite_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "invitee_email": "invitee@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "device_label": "Test Device",
        "platform": "TV",
        "supports_hd": True,
    }
    defaults.update(overrides)
    return defaults


def create_stream_session_payload(profile_id, device_id, title_id, **overrides) -> dict:
    defaults = {
        "profile_id": profile_id,
        "device_id": device_id,
        "title_id": title_id,
    }
    defaults.update(overrides)
    return defaults


def create_download_payload(profile_id, device_id, title_id, **overrides) -> dict:
    defaults = {
        "profile_id": profile_id,
        "device_id": device_id,
        "title_id": title_id,
        "quality": "SD",
    }
    defaults.update(overrides)
    return defaults


def create_watch_progress_payload(profile_id, title_id, last_device_id, position_min=0, **overrides) -> dict:
    defaults = {
        "profile_id": profile_id,
        "title_id": title_id,
        "position_min": position_min,
        "last_device_id": last_device_id,
    }
    defaults.update(overrides)
    return defaults


def clock_advance_payload(to_iso8601, run_sweeps=False) -> dict:
    return {"to_iso8601": to_iso8601, "run_sweeps": run_sweeps}
