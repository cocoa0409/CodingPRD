"""Entity assertions and domain invariant checkers for the feedback panel API."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_ts(value):
    return datetime.fromisoformat(
        str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_timestamp_eq(actual, expected_iso):
    """PRD stamps fields like `sent_at`/`last_contacted_at`/`lapsed_at`/
    `breached_at`/`last_reminder_at` "with the current time" — the instant is
    pinned, the string serialization is not, so compare instants."""
    assert actual is not None, f"expected a timestamp equal to {expected_iso}, got None"
    assert _parse_ts(actual) == _parse_ts(expected_iso), (
        f"timestamp mismatch: {actual!r} != {expected_iso!r}")


def assert_common_spine(data: dict, entity_label: str = "resource"):
    """Every PRD resource carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity_label}.version must be a positive int"


def assert_panel_cell(data: dict):
    assert_common_spine(data, "PanelCell")
    assert data["age_band"] in ["AGE_18_29", "AGE_30_44", "AGE_45_64", "AGE_65_PLUS"]
    assert isinstance(data["district"], str) and data["district"]
    assert data["tenure_bucket"] in ["RENTER", "OWNER"]
    assert isinstance(data["target_size"], int) and data["target_size"] >= 0
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert isinstance(data["active_count"], int) and data["active_count"] >= 0
    assert data["status"] in ["OPEN", "SATURATED"]


def assert_panelist(data: dict):
    assert_common_spine(data, "Panelist")
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["age_band"] in ["AGE_18_29", "AGE_30_44", "AGE_45_64", "AGE_65_PLUS"]
    assert isinstance(data["district"], str) and data["district"]
    assert data["tenure_bucket"] in ["RENTER", "OWNER"]
    assert isinstance(data["preferred_locale"], str) and data["preferred_locale"]
    assert data["status"] in ["APPLICANT", "ACTIVE", "LAPSED", "SUSPENDED", "ATTRITED", "WITHDRAWN"]
    assert isinstance(data["missed_streak"], int) and data["missed_streak"] >= 0


def assert_instrument(data: dict):
    assert_common_spine(data, "Instrument")
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["question_count"], int) and data["question_count"] >= 1
    assert isinstance(data["required_locales"], list) and len(data["required_locales"]) >= 1
    assert isinstance(data["base_locale"], str) and data["base_locale"]
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in ["DRAFT", "IN_REVIEW", "APPROVED", "LOCKED"]


def assert_translation(data: dict):
    assert_common_spine(data, "Translation")
    assert is_valid_uuid(data.get("instrument_id", "")), "Translation.instrument_id must be a UUID"
    assert isinstance(data["locale"], str) and data["locale"]
    assert isinstance(data["translator_ref"], str) and data["translator_ref"]
    assert isinstance(data["instrument_revision"], int) and data["instrument_revision"] >= 1
    assert data["status"] in ["SUBMITTED", "CERTIFIED", "REJECTED", "STALE"]


def assert_survey_wave(data: dict):
    assert_common_spine(data, "SurveyWave")
    assert isinstance(data["wave_code"], str) and data["wave_code"]
    assert is_valid_uuid(data.get("instrument_id", "")), "SurveyWave.instrument_id must be a UUID"
    assert is_iso8601_timestamp(data.get("opens_at", ""))
    assert is_iso8601_timestamp(data.get("closes_at", ""))
    assert 0 < data["min_response_rate"] <= 1
    for f in ("incentive_pool_total_cents", "base_incentive_cents",
              "incentive_pool_available_cents", "incentive_pool_reserved_cents",
              "incentive_pool_paid_cents", "invited_count", "completed_count"):
        assert isinstance(data[f], int) and data[f] >= 0, f"SurveyWave.{f} must be a non-negative int"
    assert data["status"] in ["DRAFT", "ARMED", "FIELDING", "CLOSED", "WEIGHTED", "PUBLISHED", "CANCELLED"]


def assert_invitation(data: dict):
    assert_common_spine(data, "Invitation")
    assert is_valid_uuid(data.get("wave_id", "")), "Invitation.wave_id must be a UUID"
    assert is_valid_uuid(data.get("panelist_id", "")), "Invitation.panelist_id must be a UUID"
    assert is_iso8601_timestamp(data.get("sent_at", ""))
    assert isinstance(data["reminder_count"], int) and data["reminder_count"] >= 0
    assert data["status"] in ["SENT", "COMPLETED", "DECLINED", "EXPIRED", "SUPPRESSED"]


def assert_response(data: dict):
    assert_common_spine(data, "Response")
    assert is_valid_uuid(data.get("invitation_id", "")), "Response.invitation_id must be a UUID"
    assert 0 <= data["completeness_pct"] <= 100
    assert isinstance(data["completion_seconds"], int) and data["completion_seconds"] >= 0
    assert isinstance(data["speeder_flag"], bool)
    assert isinstance(data["low_effort_flag"], bool)
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "QUARANTINED", "DISCARDED"]


def assert_incentive_award(data: dict):
    assert_common_spine(data, "IncentiveAward")
    assert is_valid_uuid(data.get("response_id", "")), "IncentiveAward.response_id must be a UUID"
    assert is_valid_uuid(data.get("wave_id", "")), "IncentiveAward.wave_id must be a UUID"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["eligibility_status"] in ["PENDING", "ELIGIBLE", "INELIGIBLE"]
    assert data["payout_status"] in ["UNPAID", "AUTHORIZED", "PAID", "FORFEITED"]


def assert_weight_snapshot(data: dict):
    assert_common_spine(data, "WeightSnapshot")
    assert is_valid_uuid(data.get("wave_id", "")), "WeightSnapshot.wave_id must be a UUID"
    assert data["method"] in ["RIM", "POST_STRAT"]
    assert isinstance(data["accepted_count"], int) and data["accepted_count"] >= 0
    assert isinstance(data["weighted_cell_shares"], dict)
    assert data["status"] in ["PROVISIONAL", "FINALIZED", "SUPERSEDED"]


def assert_publication(data: dict):
    assert_common_spine(data, "Publication")
    assert is_valid_uuid(data.get("wave_id", "")), "Publication.wave_id must be a UUID"
    assert is_valid_uuid(data.get("weight_snapshot_id", "")), "Publication.weight_snapshot_id must be a UUID"
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["k_threshold"], int) and data["k_threshold"] >= 1
    assert isinstance(data["breakdown_cells"], list)
    assert data["status"] in ["DRAFT", "PUBLISHED", "RETRACTED"]


def assert_commitment(data: dict):
    assert_common_spine(data, "FollowUpCommitment")
    assert is_valid_uuid(data.get("publication_id", "")), "FollowUpCommitment.publication_id must be a UUID"
    assert isinstance(data["department_name"], str) and data["department_name"]
    assert isinstance(data["summary"], str)
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert data["status"] in ["COMMITTED", "IN_PROGRESS", "FULFILLED", "BREACHED", "SUSPENDED"]


def assert_privacy_hold(data: dict):
    assert_common_spine(data, "PrivacyHold")
    assert is_valid_uuid(data.get("panelist_id", "")), "PrivacyHold.panelist_id must be a UUID"
    assert data["scope"] in ["NO_CONTACT", "FULL_SUPPRESS"]
    assert isinstance(data["reason"], str)
    assert data["status"] in ["ACTIVE", "RELEASED"]


def assert_refresh_run(data: dict):
    assert_common_spine(data, "RefreshRun")
    assert isinstance(data["run_label"], str) and data["run_label"]
    assert isinstance(data["attrition_grace_days"], int) and data["attrition_grace_days"] >= 0
    assert isinstance(data["planned_attrition_count"], int) and data["planned_attrition_count"] >= 0
    assert data["status"] in ["OPEN", "APPLIED", "ABORTED"]


def assert_pool_conservation(wave: dict):
    """The wave's three pool buckets always sum to the pool total."""
    total = wave["incentive_pool_total_cents"]
    s = (wave["incentive_pool_available_cents"]
         + wave["incentive_pool_reserved_cents"]
         + wave["incentive_pool_paid_cents"])
    assert s == total, (
        f"Pool buckets must sum to total {total}: "
        f"available={wave['incentive_pool_available_cents']} "
        f"reserved={wave['incentive_pool_reserved_cents']} "
        f"paid={wave['incentive_pool_paid_cents']}"
    )
