"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    ApplicationStatus, CampaignStatus, ComplianceReportStatus,
    IncomeCertificationStatus, LotteryRunStatus, PreferenceClaimStatus,
    ProvisionalDetermination, PurgeRunStatus, RemovalReason, UnitOfferStatus,
    UnitStatus, WaitlistEntryStatus,
)


def assert_common_fields(data: dict):
    """PRD §2.4 system-managed fields present with the right types."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_property(data: dict):
    assert_common_fields(data)
    for field in ("units_total", "units_available_count", "units_reserved_count",
                  "units_leased_count", "units_out_of_service_count"):
        assert isinstance(data.get(field), int), f"{field} must be an integer"
    assert_property_bucket_conservation(data)


def assert_property_bucket_conservation(data: dict):
    """PRD §2.8: each status counter tallies units in the corresponding
    status, so the per-status buckets always sum to units_total."""
    bucket_sum = (data["units_available_count"] + data["units_reserved_count"]
                  + data["units_leased_count"]
                  + data["units_out_of_service_count"])
    assert bucket_sum == data["units_total"], (
        f"unit status buckets {bucket_sum} must equal "
        f"units_total {data['units_total']}"
    )


def assert_unit(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in UnitStatus]


def assert_occupancy_standard(data: dict):
    assert_common_fields(data)
    assert isinstance(data["min_occupants"], int)
    assert isinstance(data["max_occupants"], int)
    assert data["min_occupants"] <= data["max_occupants"]


def assert_ami_limit(data: dict):
    assert_common_fields(data)
    assert isinstance(data["household_size"], int)
    assert isinstance(data["annual_limit_cents"], int)


def assert_campaign(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in CampaignStatus]
    for field in ("applications_received_count", "waitlist_active_count",
                  "entries_leased_count", "reopen_count"):
        assert isinstance(data.get(field), int), f"{field} must be an integer"


def assert_applicant(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("email"), str)


def assert_application(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in ApplicationStatus]
    assert data["provisional_determination"] in [
        s.value for s in ProvisionalDetermination]


def assert_preference_claim(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in PreferenceClaimStatus]


def assert_income_certification(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in IncomeCertificationStatus]


def assert_lottery_run(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in LotteryRunStatus]


def assert_waitlist_entry(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in WaitlistEntryStatus]
    assert isinstance(data["base_rank"], int)
    assert isinstance(data["preference_tier"], int)
    assert isinstance(data["effective_rank"], int)
    assert isinstance(data["refusal_count"], int)
    if data["status"] == WaitlistEntryStatus.REMOVED.value:
        assert data["removal_reason"] in [r.value for r in RemovalReason]


def assert_unit_offer(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in UnitOfferStatus]


def assert_purge_run(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in PurgeRunStatus]


def assert_compliance_report(data: dict):
    assert_common_fields(data)
    assert data["status"] in [s.value for s in ComplianceReportStatus]
    for field in ("applications_received_count", "applications_verified_count",
                  "preference_claims_decided_count",
                  "preference_claims_verified_count",
                  "preference_verification_rate_bp",
                  "lottery_runs_executed_count", "offers_made_count",
                  "offers_accepted_count", "entries_removed_count",
                  "lease_up_rate_bp"):
        assert isinstance(data.get(field), int), f"{field} must be an integer"


def assert_entry_census(entries: list, expected_total: int):
    """Domain invariant: waitlist entries are conserved — offers and refusals
    move entries between status buckets but never create or destroy rows."""
    by_status = {}
    for e in entries:
        by_status[e["status"]] = by_status.get(e["status"], 0) + 1
    assert len(entries) == expected_total, (
        f"entry census {len(entries)} != expected {expected_total}: "
        f"{by_status}"
    )
    return by_status
