"""Domain services: view serializers, logical-clock helpers, computed-field
reconciliation, and the scheduled sweeps (PRD §2.9, §3).
"""
from db import store
from calculations import (
    parse_iso_to_dt, minute_of_day, utc_day_ordinal,
    rating_ceiling, INVITE_SEAT_HOLD_CENTS,
)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def current_dt():
    """Aware UTC datetime of the logical clock (store.current_utc)."""
    return parse_iso_to_dt(store.current_utc)


def current_minute_of_day() -> int:
    return minute_of_day(current_dt())


# ---------------------------------------------------------------------------
# Computed-field reconciliation
# ---------------------------------------------------------------------------
def profile_active_downloads_count(profile_id: str) -> int:
    """Count of {DOWNLOADING, READY} downloads owned by a profile."""
    n = 0
    for d in store.downloads.values():
        if d["profile_id"] == profile_id and d["status"] in ("DOWNLOADING", "READY"):
            n += 1
    return n


def non_archived_profile_count(account_id: str) -> int:
    n = 0
    for p in store.profiles.values():
        if p["account_id"] == account_id and p["status"] != "ARCHIVED":
            n += 1
    return n


def parental_control_for_profile(profile_id: str):
    for pc in store.parental_controls.values():
        if pc["profile_id"] == profile_id:
            return pc
    return None


def recompute_profile_max_rating(profile: dict):
    """Recompute max_rating_allowed from kind tightened by ParentalControl."""
    pc = parental_control_for_profile(profile["id"])
    control_max = pc["max_rating"] if pc else None
    profile["max_rating_allowed"] = rating_ceiling(profile["kind"], control_max)


# ---------------------------------------------------------------------------
# View serializers — present exactly the entity fields, with computed fields
# kept current at read time.
# ---------------------------------------------------------------------------
def plan_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "tier": p["tier"],
        "monthly_fee_cents": p["monthly_fee_cents"],
        "max_profiles": p["max_profiles"],
        "concurrent_stream_cap": p["concurrent_stream_cap"],
        "max_registered_devices": p["max_registered_devices"],
        "download_quota_per_profile": p["download_quota_per_profile"],
        "ad_free": p["ad_free"],
        "hd_offline_allowed": p["hd_offline_allowed"],
    }


def title_view(t: dict) -> dict:
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "name": t["name"],
        "maturity_rating": t["maturity_rating"],
        "runtime_minutes": t["runtime_minutes"],
        "downloadable": t["downloadable"],
        "license_size_mb": t["license_size_mb"],
    }


def account_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "plan_id": a["plan_id"],
        "owner_email": a["owner_email"],
        "status": a["status"],
        "billing_anchor_day": a["billing_anchor_day"],
        "wallet_credit_cents": a["wallet_credit_cents"],
        "billing_status": a["billing_status"],
        "period_charge_cents": a["period_charge_cents"],
        "proration_adjustment_cents": a["proration_adjustment_cents"],
        "active_stream_count": a["active_stream_count"],
        "registered_device_count": a["registered_device_count"],
    }


def profile_view(p: dict) -> dict:
    # max_rating_allowed is computed; refresh on read (PRD §2.8).
    recompute_profile_max_rating(p)
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "account_id": p["account_id"],
        "display_name": p["display_name"],
        "kind": p["kind"],
        "status": p["status"],
        "max_rating_allowed": p["max_rating_allowed"],
        "daily_watch_minutes_used": p["daily_watch_minutes_used"],
    }


def parental_control_view(pc: dict) -> dict:
    return {
        "id": pc["id"],
        "created_at": pc["created_at"],
        "updated_at": pc["updated_at"],
        "version": pc["version"],
        "profile_id": pc["profile_id"],
        "max_rating": pc["max_rating"],
        "daily_watch_limit_minutes": pc["daily_watch_limit_minutes"],
        "curfew_start_min": pc["curfew_start_min"],
        "curfew_end_min": pc["curfew_end_min"],
    }


def invite_view(i: dict) -> dict:
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
        "account_id": i["account_id"],
        "invitee_email": i["invitee_email"],
        "token": i["token"],
        "status": i["status"],
        "expires_at": i["expires_at"],
        "created_profile_id": i["created_profile_id"],
        "hold_amount_cents": i["hold_amount_cents"],
    }


def device_view(d: dict) -> dict:
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "account_id": d["account_id"],
        "device_label": d["device_label"],
        "platform": d["platform"],
        "status": d["status"],
        "supports_hd": d["supports_hd"],
    }


def stream_session_view(s: dict) -> dict:
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "profile_id": s["profile_id"],
        "device_id": s["device_id"],
        "title_id": s["title_id"],
        "status": s["status"],
        "started_at_min": s["started_at_min"],
        "minutes_watched": s["minutes_watched"],
        "ad_breaks_served": s["ad_breaks_served"],
    }


def download_view(d: dict) -> dict:
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "profile_id": d["profile_id"],
        "device_id": d["device_id"],
        "title_id": d["title_id"],
        "status": d["status"],
        "quality": d["quality"],
        "license_expires_at": d["license_expires_at"],
        "size_mb": d["size_mb"],
    }


def watch_progress_view(w: dict) -> dict:
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
        "profile_id": w["profile_id"],
        "title_id": w["title_id"],
        "position_min": w["position_min"],
        "last_device_id": w["last_device_id"],
        "completed": w["completed"],
    }


def plan_change_view(pc: dict) -> dict:
    return {
        "id": pc["id"],
        "created_at": pc["created_at"],
        "account_id": pc["account_id"],
        "to_plan_id": pc["to_plan_id"],
        "from_plan_id": pc["from_plan_id"],
        "direction": pc["direction"],
    }
