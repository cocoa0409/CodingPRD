"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid

from .constants import TEST_DEFAULTS


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def create_title_payload(**overrides) -> dict:
    defaults = {
        "title_code": f"T-{_suffix()}",
        "name": "Test Title",
        "platform_codes": ["PS5"],
        "target_launch_date": TEST_DEFAULTS["TARGET_LAUNCH_DATE"],
        "cert_budget_total_cents": TEST_DEFAULTS["TITLE_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "name": f"Vendor-{_suffix()}",
        "weekly_capacity_hours": TEST_DEFAULTS["VENDOR_CAPACITY_HOURS"],
        "cost_rate_cents_per_hour": TEST_DEFAULTS["VENDOR_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_test_plan_payload(title_id, platform_code="PS5", **overrides) -> dict:
    defaults = {"title_id": title_id, "platform_code": platform_code}
    defaults.update(overrides)
    return defaults


def create_plan_entry_payload(feature_area="COMBAT", platform_layer="GAME",
                              is_cert_blocker=True, required_coverage_hours=10,
                              **overrides) -> dict:
    defaults = {
        "feature_area": feature_area,
        "platform_layer": platform_layer,
        "is_cert_blocker": is_cert_blocker,
        "required_coverage_hours": required_coverage_hours,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(vendor_id, plan_id, feature_area="COMBAT",
                              week_start_date=TEST_DEFAULTS["WEEK_START"],
                              reserved_hours=10, **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "plan_id": plan_id,
        "feature_area": feature_area,
        "week_start_date": week_start_date,
        "reserved_hours": reserved_hours,
    }
    defaults.update(overrides)
    return defaults


def create_build_payload(title_id, platform_code="PS5", version_string=None,
                         **overrides) -> dict:
    defaults = {
        "title_id": title_id,
        "platform_code": platform_code,
        "version_string": version_string or f"1.0.0-{_suffix()}",
    }
    defaults.update(overrides)
    return defaults


def create_bug_payload(title_id, build_id, severity="MAJOR", category="GAMEPLAY",
                       **overrides) -> dict:
    defaults = {
        "title_id": title_id,
        "build_id": build_id,
        "severity": severity,
        "category": category,
    }
    defaults.update(overrides)
    return defaults


def create_submission_package_payload(platform_code, build_id, test_plan_id,
                                      expected_title_version, **overrides) -> dict:
    defaults = {
        "platform_code": platform_code,
        "build_id": build_id,
        "test_plan_id": test_plan_id,
        "expected_title_version": expected_title_version,
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(severity="CATEGORY_A", requirement_code="TRC-PS-02",
                           description="cert finding", **overrides) -> dict:
    defaults = {
        "severity": severity,
        "requirement_code": requirement_code,
        "description": description,
    }
    defaults.update(overrides)
    return defaults


def create_age_rating_payload(title_id, territory="ESRB",
                              content_descriptors=None, **overrides) -> dict:
    defaults = {
        "title_id": title_id,
        "territory": territory,
        "content_descriptors": content_descriptors or ["MILD_VIOLENCE"],
    }
    defaults.update(overrides)
    return defaults


def create_localization_pack_payload(title_id, locale=None, is_required=True,
                                     text_asset_total=100, audio_asset_total=50,
                                     **overrides) -> dict:
    defaults = {
        "title_id": title_id,
        "locale": locale or f"fr-{_suffix()[:4]}",
        "is_required": is_required,
        "text_asset_total": text_asset_total,
        "audio_asset_total": audio_asset_total,
    }
    defaults.update(overrides)
    return defaults


def create_release_window_payload(title_id, platform_code="PS5", kind="LAUNCH",
                                  start_utc="2026-08-10T09:00:00Z",
                                  end_utc="2026-08-10T17:00:00Z",
                                  **overrides) -> dict:
    defaults = {
        "title_id": title_id,
        "platform_code": platform_code,
        "kind": kind,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    defaults.update(overrides)
    return defaults


def create_blackout_window_payload(platform_code="PS5",
                                   start_utc="2026-08-10T00:00:00Z",
                                   end_utc="2026-08-12T00:00:00Z",
                                   buffer_hours=24, reason="platform cert freeze",
                                   **overrides) -> dict:
    defaults = {
        "platform_code": platform_code,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "buffer_hours": buffer_hours,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_hotfix_payload(title_id, platform_code="PS5", build_id=None,
                          severity="S1", incident_summary="post-launch incident",
                          **overrides) -> dict:
    defaults = {
        "title_id": title_id,
        "platform_code": platform_code,
        "build_id": build_id,
        "severity": severity,
        "incident_summary": incident_summary,
    }
    defaults.update(overrides)
    return defaults
