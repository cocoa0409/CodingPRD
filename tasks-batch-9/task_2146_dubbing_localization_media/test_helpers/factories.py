"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def create_title_payload(**overrides) -> dict:
    payload = {
        "title_code": TEST_DEFAULTS["TITLE_CODE"],
        "source_language": TEST_DEFAULTS["SOURCE_LANGUAGE"],
        "runtime_seconds": TEST_DEFAULTS["RUNTIME_SECONDS"],
        "content_rating": "TEEN",
    }
    payload.update(overrides)
    return payload


def create_cut_payload(title_id: str, **overrides) -> dict:
    payload = {
        "title_id": title_id,
        "cut_code": "THEATRICAL",
        "loop_count": TEST_DEFAULTS["CUT_LOOP_COUNT"],
        "runtime_seconds": TEST_DEFAULTS["RUNTIME_SECONDS"],
    }
    payload.update(overrides)
    return payload


def derive_cut_payload(expected_parent_cut_version: int, **overrides) -> dict:
    payload = {
        "cut_code": "AIRLINE",
        "loop_count": 360,
        "runtime_seconds": 6900,
        "expected_parent_cut_version": expected_parent_cut_version,
    }
    payload.update(overrides)
    return payload


def create_character_payload(title_id: str, **overrides) -> dict:
    payload = {
        "title_id": title_id,
        "character_code": "HERO",
        "loop_count": 220,
        "screen_time_seconds": 3000,
        "is_principal": True,
    }
    payload.update(overrides)
    return payload


def create_platform_spec_payload(**overrides) -> dict:
    payload = {
        "platform_code": "STREAM_A",
        "loudness_target_lufs": -24.0,
        "stem_layout": "FIVE_ONE_ME",
        "max_lipsync_deviation_ms": 120,
        "min_fidelity_score": 0.65,
        "qc_pass_threshold": 0.9,
        "metadata_fields_required": ["title_local", "synopsis_local"],
    }
    payload.update(overrides)
    return payload


def create_voice_talent_payload(**overrides) -> dict:
    payload = {
        "full_name": "Anna Vogel",
        "language_code": TEST_DEFAULTS["TARGET_LANGUAGE"],
        "base_rate_cents_per_hour": TEST_DEFAULTS["TALENT_BASE_RATE_CENTS_PER_HOUR"],
        "licensed_territories": ["US", "DE", "JP"],
        "union_status": "NON_UNION",
        "max_daily_recorded_minutes": TEST_DEFAULTS["TALENT_MAX_DAILY_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_studio_payload(**overrides) -> dict:
    payload = {
        "name": "Booth 1",
        "territory": TEST_DEFAULTS["TERRITORY"],
        "hourly_rate_cents": TEST_DEFAULTS["STUDIO_HOURLY_RATE_CENTS"],
        "turnaround_buffer_minutes": TEST_DEFAULTS["STUDIO_BUFFER_MINUTES"],
        "daily_capacity_minutes": TEST_DEFAULTS["STUDIO_DAILY_CAPACITY_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_localization_order_payload(cut_id: str, platform_spec_id: str, **overrides) -> dict:
    payload = {
        "cut_id": cut_id,
        "platform_spec_id": platform_spec_id,
        "target_language": TEST_DEFAULTS["TARGET_LANGUAGE"],
        "territory": TEST_DEFAULTS["TERRITORY"],
        "budget_cap_cents": TEST_DEFAULTS["BUDGET_CAP_CENTS"],
        "priority_tier": TEST_DEFAULTS["PRIORITY_TIER"],
    }
    payload.update(overrides)
    return payload


def create_script_adaptation_payload(order_id: str, **overrides) -> dict:
    payload = {"order_id": order_id}
    payload.update(overrides)
    return payload


def adapt_payload(**overrides) -> dict:
    payload = {"declared_loop_count": TEST_DEFAULTS["DECLARED_LOOP_COUNT"]}
    payload.update(overrides)
    return payload


def submit_review_payload(**overrides) -> dict:
    payload = {
        "measured_sync_deviation_ms_total": TEST_DEFAULTS[
            "MEASURED_SYNC_DEVIATION_MS_TOTAL"
        ],
        "lines_over_deviation": TEST_DEFAULTS["LINES_OVER_DEVIATION"],
    }
    payload.update(overrides)
    return payload


def review_adaptation_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_casting_assignment_payload(
    order_id: str,
    character_id: str,
    talent_id: str,
    expected_order_version: int,
    **overrides,
) -> dict:
    payload = {
        "order_id": order_id,
        "character_id": character_id,
        "talent_id": talent_id,
        "usage_variant": "BUYOUT",
        "agreed_rate_cents_per_hour": TEST_DEFAULTS["CA1_RATE_CENTS_PER_HOUR"],
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


def create_recording_session_payload(
    order_id: str,
    studio_id: str,
    casting_assignment_id: str,
    start_utc: str,
    end_utc: str,
    **overrides,
) -> dict:
    payload = {
        "order_id": order_id,
        "studio_id": studio_id,
        "casting_assignment_id": casting_assignment_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "is_retake": False,
        "on_conflict": "REJECT",
    }
    payload.update(overrides)
    return payload


def create_mix_job_payload(order_id: str, **overrides) -> dict:
    payload = {
        "order_id": order_id,
        "stem_layout": "FIVE_ONE_ME",
        "me_stem_present": True,
    }
    payload.update(overrides)
    return payload


def mix_payload(**overrides) -> dict:
    payload = {"loudness_lufs": TEST_DEFAULTS["LOUDNESS_LUFS"]}
    payload.update(overrides)
    return payload


def create_quality_review_payload(order_id: str, mix_job_id: str, **overrides) -> dict:
    payload = {"order_id": order_id, "mix_job_id": mix_job_id}
    payload.update(overrides)
    return payload


def start_review_payload(**overrides) -> dict:
    payload = {"sampled_loop_count": TEST_DEFAULTS["SAMPLED_LOOP_COUNT"]}
    payload.update(overrides)
    return payload


def decide_pass_payload(defect_count: int = 20, **overrides) -> dict:
    payload = {"decision": "PASS", "defect_count": defect_count}
    payload.update(overrides)
    return payload


def decide_fail_payload(defects, defect_count: int = 30, **overrides) -> dict:
    payload = {"decision": "FAIL", "defect_count": defect_count, "defects": defects}
    payload.update(overrides)
    return payload


def defect_entry(
    casting_assignment_id: str,
    loop_ref: str = "L-0042",
    defect_category: str = "LIPSYNC",
    estimated_minutes: int = 20,
) -> dict:
    return {
        "casting_assignment_id": casting_assignment_id,
        "loop_ref": loop_ref,
        "defect_category": defect_category,
        "estimated_minutes": estimated_minutes,
    }


def create_talent_payment_payload(casting_assignment_id: str, territory_scope, **overrides) -> dict:
    payload = {
        "casting_assignment_id": casting_assignment_id,
        "territory_scope": list(territory_scope),
    }
    payload.update(overrides)
    return payload


def deliver_payload(metadata_locale_fields: dict) -> dict:
    return {"metadata_locale_fields": metadata_locale_fields}
