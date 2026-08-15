"""Entity assertions and domain invariant checkers."""
import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AmendmentKind,
    AmendmentStatus,
    ArbitrationStatus,
    AssessmentMethod,
    AssessmentStatus,
    ContactKind,
    DeliveryMethod,
    ExerciseNoticeStatus,
    LeaseStatus,
    LedgerEntryKind,
    OptionStatus,
    OptionType,
    PortfolioPosture,
    RateDetermination,
    ReminderStatus,
    ReminderTier,
)


def assert_portfolio(data: dict):
    """Validate Portfolio response structure against the PRD contract."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["region"], str) and len(data["region"]) > 0
    assert isinstance(data["laddering_max_pct_per_year"], int)
    assert 0 <= data["laddering_max_pct_per_year"] <= 100
    assert isinstance(data["total_active_square_feet"], int)
    assert data["total_active_square_feet"] >= 0
    assert data["posture"] in [p.value for p in PortfolioPosture]
    assert data.get("posture_year") is None or isinstance(data["posture_year"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_lease(data: dict):
    """Validate Lease response structure against the PRD contract."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("portfolio_id", "")), "portfolio_id must be a UUID"
    assert isinstance(data["premises_label"], str) and len(data["premises_label"]) > 0
    assert isinstance(data["rentable_square_feet"], int)
    assert data["rentable_square_feet"] > 0
    assert isinstance(data["base_rent_cents_per_rsf_year"], int)
    assert data["base_rent_cents_per_rsf_year"] > 0
    assert is_iso8601_timestamp(data.get("commencement_date", ""))
    assert is_iso8601_timestamp(data.get("expiration_date", ""))
    assert isinstance(data["holdover_tier1_pct"], int)
    assert isinstance(data["holdover_tier2_pct"], int)
    assert isinstance(data["holdover_tier1_days"], int)
    assert data["status"] in [s.value for s in LeaseStatus]
    assert data.get("holdover_entered_at") is None or is_iso8601_timestamp(
        data["holdover_entered_at"])
    assert isinstance(data["accrued_holdover_rent_cents"], int)
    assert data.get("active_amendment_id") is None or is_valid_uuid(
        data["active_amendment_id"])
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_contact(data: dict):
    """Validate Contact response structure against the PRD contract."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("portfolio_id", "")), "portfolio_id must be a UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["contact_kind"] in [k.value for k in ContactKind]
    assert isinstance(data["is_active"], bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_option(data: dict):
    """Validate Option response structure against the PRD contract."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("lease_id", "")), "lease_id must be a UUID"
    assert data["option_type"] in [t.value for t in OptionType]
    assert is_iso8601_timestamp(data.get("notice_window_open_date", ""))
    assert is_iso8601_timestamp(data.get("notice_window_close_date", ""))
    assert is_iso8601_timestamp(data.get("target_commencement_date", ""))
    assert data.get("extension_years") is None or isinstance(data["extension_years"], int)
    assert data["rate_determination"] in [r.value for r in RateDetermination]
    assert data.get("fixed_rent_cents_per_rsf_year") is None or isinstance(
        data["fixed_rent_cents_per_rsf_year"], int)
    assert isinstance(data["exercise_fee_cents"], int)
    assert isinstance(data["missed_option_penalty_cents"], int)
    assert data["status"] in [s.value for s in OptionStatus]
    assert data.get("exercised_at") is None or is_iso8601_timestamp(data["exercised_at"])
    assert data.get("lapsed_at") is None or is_iso8601_timestamp(data["lapsed_at"])
    assert data.get("determined_rent_cents_per_rsf_year") is None or isinstance(
        data["determined_rent_cents_per_rsf_year"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_assessment(data: dict):
    """Validate MarketRateAssessment response structure against the PRD contract."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("option_id", "")), "option_id must be a UUID"
    assert data["method"] in [m.value for m in AssessmentMethod]
    assert data.get("comparable_rents_cents") is None or isinstance(
        data["comparable_rents_cents"], list)
    assert data.get("regression_base_cents") is None or isinstance(
        data["regression_base_cents"], int)
    assert data.get("regression_adjustments") is None or isinstance(
        data["regression_adjustments"], list)
    assert data["status"] in [s.value for s in AssessmentStatus]
    assert isinstance(data["provisional_rent_cents"], int)
    assert data.get("determined_rent_cents") is None or isinstance(
        data["determined_rent_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_arbitration_case(data: dict):
    """Validate ArbitrationCase response structure against the PRD contract."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("assessment_id", "")), "assessment_id must be a UUID"
    assert isinstance(data["landlord_rent_cents"], int)
    assert isinstance(data["tenant_rent_cents"], int)
    assert is_iso8601_timestamp(data.get("submission_close_date", ""))
    assert data["status"] in [s.value for s in ArbitrationStatus]
    assert data.get("award_rent_cents") is None or isinstance(data["award_rent_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_exercise_notice(data: dict):
    """Validate ExerciseNotice response structure against the PRD contract."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("option_id", "")), "option_id must be a UUID"
    assert data["delivery_method"] in [m.value for m in DeliveryMethod]
    assert is_iso8601_timestamp(data.get("sent_at", ""))
    assert data.get("delivered_at") is None or is_iso8601_timestamp(data["delivered_at"])
    assert data.get("acknowledged_at") is None or is_iso8601_timestamp(
        data["acknowledged_at"])
    assert data["status"] in [s.value for s in ExerciseNoticeStatus]
    assert data.get("rejection_reason") is None or isinstance(
        data["rejection_reason"], str)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_reminder(data: dict):
    """Validate Reminder response structure against the PRD contract."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("option_id", "")), "option_id must be a UUID"
    assert is_valid_uuid(data.get("contact_id", "")), "contact_id must be a UUID"
    assert data["tier"] in [t.value for t in ReminderTier]
    assert is_iso8601_timestamp(data.get("scheduled_for", ""))
    assert data["status"] in [s.value for s in ReminderStatus]
    assert data.get("sent_at") is None or is_iso8601_timestamp(data["sent_at"])
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_amendment(data: dict):
    """Validate Amendment response structure against the PRD contract."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("lease_id", "")), "lease_id must be a UUID"
    assert data.get("supersedes_amendment_id") is None or is_valid_uuid(
        data["supersedes_amendment_id"])
    assert data["kind"] in [k.value for k in AmendmentKind]
    assert is_iso8601_timestamp(data.get("new_expiration_date", ""))
    assert isinstance(data["new_base_rent_cents_per_rsf_year"], int)
    assert data["new_base_rent_cents_per_rsf_year"] > 0
    assert data["status"] in [s.value for s in AmendmentStatus]
    assert data.get("negotiation_opened_at") is None or is_iso8601_timestamp(
        data["negotiation_opened_at"])
    assert data.get("executed_at") is None or is_iso8601_timestamp(data["executed_at"])
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_ledger_entry(data: dict):
    """Validate LedgerEntry response structure.

    LedgerEntry is append-only: it exposes id and created_at only; no
    updated_at, no version.
    """
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "LedgerEntry is append-only; no updated_at"
    assert "version" not in data, "LedgerEntry is append-only; no version"
    assert is_valid_uuid(data.get("lease_id", "")), "lease_id must be a UUID"
    assert data["entry_kind"] in [k.value for k in LedgerEntryKind]
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data.get("effective_date", ""))
    assert data.get("source_option_id") is None or is_valid_uuid(data["source_option_id"])
    assert data.get("source_assessment_id") is None or is_valid_uuid(
        data["source_assessment_id"])


def assert_clock_event(data: dict):
    """Validate ClockEvent response structure.

    ClockEvent is append-only: it exposes id and created_at only.
    """
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "ClockEvent is append-only; no updated_at"
    assert "version" not in data, "ClockEvent is append-only; no version"
    assert is_iso8601_timestamp(data.get("set_to", ""))
    assert isinstance(data["fired_reminder_ids"], list)
    assert isinstance(data["lapsed_option_ids"], list)
    assert isinstance(data["holdover_lease_ids"], list)
