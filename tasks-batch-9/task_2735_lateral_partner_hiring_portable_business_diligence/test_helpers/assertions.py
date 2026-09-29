"""Entity assertions, money/timestamp helpers and conserved-quantity checkers."""

from datetime import datetime, timezone
from decimal import Decimal

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

# ----------------------------------------------------------------------
# Money and ratio helpers
# ----------------------------------------------------------------------

MONEY_TOLERANCE = 0.005
RATIO_TOLERANCE = 0.00005


def money(value) -> float:
    """Coerce a monetary field to float, accepting int, float, Decimal or str."""
    if value is None:
        raise AssertionError("Expected a monetary value, got None")
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        return float(value)
    return float(value)


def assert_money_equals(actual, expected, label="amount"):
    a = money(actual)
    assert abs(a - float(expected)) < MONEY_TOLERANCE, (
        f"Expected {label} == {expected}, got {actual}"
    )


def assert_ratio_equals(actual, expected, label="ratio"):
    a = money(actual)
    assert abs(a - float(expected)) < RATIO_TOLERANCE, (
        f"Expected {label} == {expected}, got {actual}"
    )


def assert_two_decimal_places(value, label="amount"):
    """A monetary amount must carry no more than two decimal places."""
    q = Decimal(str(money(value))).normalize()
    exponent = -q.as_tuple().exponent
    assert exponent <= 2, f"Expected {label} to carry at most 2 decimals, got {value}"


# ----------------------------------------------------------------------
# Timestamp helpers — canonicalise before comparing
# ----------------------------------------------------------------------


def parse_instant(value) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a timezone-aware datetime.

    Accepts any sub-second width (including none) and either a trailing ``Z`` or
    an explicit offset, so comparisons never turn into string-width mismatches.
    """
    assert isinstance(value, str) and value, f"Expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual, expected, label="timestamp"):
    """Compare two ISO 8601 instants by value, not by textual representation."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"Expected {label} == {expected}, got {actual}"
    )


def assert_instant_is_null(value, label="timestamp"):
    assert value is None, f"Expected {label} to be null, got {value!r}"


def assert_three_fractional_digits(value, label="timestamp"):
    """PRD requires ISO 8601 UTC timestamps with exactly three fractional digits."""
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601: {value!r}"
    assert "." in value, f"{label} must carry fractional seconds: {value!r}"
    fraction = value.split(".")[1]
    digits = "".join(ch for ch in fraction if ch.isdigit())
    assert len(digits) == 3, (
        f"{label} must carry exactly three fractional digits, got {value!r}"
    )


def days_after(instant: str, days: int) -> str:
    """Return ``instant`` advanced by ``days`` days in the canonical wire format."""
    from datetime import timedelta

    moved = parse_instant(instant) + timedelta(days=days)
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moved.microsecond // 1000:03d}Z"


# ----------------------------------------------------------------------
# Common-field assertions
# ----------------------------------------------------------------------


def assert_common_fields(data: dict, entity_label="resource"):
    """id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer at least 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict, entity_label="record"):
    """id + created_at only — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ----------------------------------------------------------------------
# Per-entity assertions
# ----------------------------------------------------------------------


def assert_practice_group(data: dict):
    assert_common_fields(data, "PracticeGroup")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["status"] in ("OPEN", "HIRING_FROZEN")
    for field in (
        "guarantee_budget_total_usd",
        "available_guarantee_budget_usd",
        "reserved_guarantee_budget_usd",
        "committed_guarantee_total_usd",
        "leverage_ratio",
        "target_standard_rate_usd",
    ):
        money(data[field])
    assert isinstance(data["onboarding_capacity"], int) and data["onboarding_capacity"] >= 1
    assert isinstance(data["active_onboarding_count"], int)
    assert_guarantee_budget_identity(data)


def assert_search_firm(data: dict):
    assert_common_fields(data, "SearchFirm")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    money(data["max_fee_pct"])
    assert isinstance(data["max_concurrent_engagements"], int)
    assert data["max_concurrent_engagements"] >= 1
    assert isinstance(data["engagement_count"], int) and data["engagement_count"] >= 0


def assert_search_firm_engagement(data: dict):
    assert_common_fields(data, "SearchFirmEngagement")
    assert is_valid_uuid(data["search_firm_id"])
    assert is_valid_uuid(data["practice_group_id"])
    assert data["status"] in ("ACTIVE", "TERMINATED", "EXPIRED")
    assert data["fee_status"] in ("NOT_DUE", "FEE_DUE", "FEE_WAIVED")
    assert data["fee_basis"] in ("NONE", "DIRECT_PLACEMENT", "TAIL_OFF_CLAIM")
    money(data["fee_pct"])
    money(data["fee_cap_usd"])
    money(data["fee_amount_usd"])
    assert isinstance(data["tail_off_days"], int) and 0 <= data["tail_off_days"] <= 365
    assert is_iso8601_timestamp(data["exclusivity_start_date"])
    assert is_iso8601_timestamp(data["exclusivity_end_date"])


def assert_candidate(data: dict):
    assert_common_fields(data, "Candidate")
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert isinstance(data["prior_firm_name"], str)
    assert is_valid_uuid(data["target_practice_group_id"])
    assert is_valid_uuid(data["sourcing_engagement_id"])
    assert isinstance(data["sponsor_user_id"], str) and 1 <= len(data["sponsor_user_id"]) <= 64
    money(data["current_standard_rate_usd"])
    assert isinstance(data["notice_period_days"], int)
    assert 0 <= data["notice_period_days"] <= 365
    assert isinstance(data["non_solicit_days"], int)
    assert 0 <= data["non_solicit_days"] <= 730
    assert data["pipeline_status"] in (
        "SOURCED",
        "APPROACHED",
        "DILIGENCE",
        "OFFER_OUT",
        "HIRED",
        "DECLINED",
        "WITHDRAWN",
    )
    assert data["clearance_status"] in (
        "NOT_STARTED",
        "IN_PROGRESS",
        "CLEARED",
        "BLOCKED",
    )


def assert_questionnaire(data: dict):
    assert_common_fields(data, "LateralQuestionnaire")
    assert is_valid_uuid(data["candidate_id"])
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "REVISION_REQUESTED",
        "ACCEPTED",
        "ABANDONED",
    )
    money(data["declared_prior_year_billings_usd"])
    money(data["declared_prior_year_collections_usd"])
    money(data["declared_realization_rate"])
    assert isinstance(data["primary_matter_types"], list)
    assert 1 <= len(data["primary_matter_types"]) <= 10
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert isinstance(data["entry_count"], int) and data["entry_count"] >= 0


def assert_client_book_entry(data: dict):
    assert_common_fields(data, "ClientBookEntry")
    assert is_valid_uuid(data["questionnaire_id"])
    assert isinstance(data["client_name"], str) and 1 <= len(data["client_name"]) <= 120
    assert data["relationship_role"] in (
        "BILLING_ATTORNEY",
        "RELATIONSHIP_PARTNER",
        "SERVICE_PARTNER",
    )
    assert data["client_consent_status"] in ("CONSENT_PENDING", "CONSENT_CONFIRMED")
    money(data["claimed_annual_billings_usd"])
    money(data["claimed_portability_pct"])
    money(data["claimed_realization_rate"])
    assert isinstance(data["matter_types"], list) and 1 <= len(data["matter_types"]) <= 6
    assert data["status"] in ("ACTIVE", "WITHDRAWN")
    assert data["portable_status"] in ("UNVALIDATED", "VALIDATED", "DECLINED")
    money(data["baseline_portable_amount_usd"])
    money(data["validated_portable_amount_usd"])
    assert isinstance(data["verified_record_count"], int)


def assert_collection_record(data: dict):
    """A CollectionRecord carries only id and created_at from the common fields."""
    assert_append_only_fields(data, "CollectionRecord")
    assert is_valid_uuid(data["candidate_id"])
    assert data["record_type"] in ("HISTORICAL", "POST_HIRE")
    assert data["status"] in ("UNVERIFIED", "VERIFIED")
    assert data["source"] in (
        "PRIOR_FIRM_STATEMENT",
        "CANDIDATE_ATTESTATION",
        "FIRM_LEDGER",
    )
    money(data["amount_usd"])
    assert is_iso8601_timestamp(data["period_end_date"])


def assert_collection_record_has_no_mutable_fields(data: dict):
    """The append-only contract: neither updated_at nor version is present."""
    assert "updated_at" not in data, (
        "CollectionRecord must not expose updated_at; it is never modified"
    )
    assert "version" not in data, (
        "CollectionRecord must not expose version; it is never modified"
    )


def assert_portability_assessment(data: dict):
    assert_common_fields(data, "PortabilityAssessment")
    assert is_valid_uuid(data["questionnaire_id"])
    assert data["status"] in ("CURRENT", "STALE", "SUPERSEDED")
    assert data["governing_basis"] in ("SELF_REPORTED", "VALIDATED")
    assert data["concentration_grade"] in ("HIGH", "MEDIUM", "LOW")
    assert is_iso8601_timestamp(data["baseline_date"])
    assert is_iso8601_timestamp(data["lookback_start_date"])
    for field in (
        "gross_baseline_total_usd",
        "validated_portable_total_usd",
        "declined_portable_total_usd",
        "self_reported_total_usd",
        "variance_pct",
        "top_client_share",
        "top3_client_share",
        "concentration_haircut_pct",
        "adjusted_portable_total_usd",
    ):
        money(data[field])
    assert isinstance(data["entry_count_in_scope"], int)
    assert_portable_book_identity(data)


def assert_conflict_check(data: dict):
    assert_common_fields(data, "ConflictCheck")
    assert is_valid_uuid(data["client_book_entry_id"])
    assert isinstance(data["adverse_party_name"], str)
    assert isinstance(data["affected_matter_types"], list)
    assert 1 <= len(data["affected_matter_types"]) <= 6
    assert data["severity"] in ("DIRECT_ADVERSE", "POSITIONAL", "IMPUTED")
    assert data["status"] in ("PENDING", "WAIVER_PENDING", "CLEAR", "BLOCKED")


def assert_conflict_waiver(data: dict):
    assert_common_fields(data, "ConflictWaiver")
    assert is_valid_uuid(data["conflict_check_id"])
    assert data["waiver_strategy"] in (
        "ADVANCE_CONSENT",
        "ETHICAL_WALL",
        "MATTER_CARVE_OUT",
    )
    assert isinstance(data["requested_from_client"], str)
    assert is_iso8601_timestamp(data["response_deadline_date"])
    assert data["status"] in ("REQUESTED", "GRANTED", "REFUSED", "EXPIRED")


def assert_matter_declination(data: dict):
    assert_common_fields(data, "MatterDeclination")
    assert is_valid_uuid(data["conflict_check_id"])
    assert is_valid_uuid(data["client_book_entry_id"])
    assert isinstance(data["matter_type"], str) and data["matter_type"]
    money(data["foregone_annual_revenue_usd"])
    assert data["status"] in ("ACTIVE", "RESCINDED")


def assert_compensation_offer(data: dict):
    assert_common_fields(data, "CompensationOffer")
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["portability_assessment_id"])
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data["status"] in (
        "DRAFTED",
        "COMMITTEE_REVIEW",
        "APPROVED",
        "REJECTED",
        "COUNTER_REQUESTED",
        "REPRICE_REQUIRED",
        "ACCEPTED",
        "LAPSED",
    )
    for field in (
        "guaranteed_comp_usd",
        "signing_bonus_usd",
        "adjusted_portable_total_snapshot_usd",
        "expected_contribution_usd",
        "total_first_year_comp_usd",
        "search_fee_amount_usd",
        "integration_cost_total_usd",
        "net_first_year_economics_usd",
        "guarantee_true_up_amount_usd",
    ):
        money(data[field])
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    for field in ("votes_cast_total", "active_vote_count", "voided_vote_count"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert_vote_ledger_identity(data)


def assert_committee_vote(data: dict):
    assert_common_fields(data, "CommitteeVote")
    assert is_valid_uuid(data["offer_id"])
    assert isinstance(data["voter_user_id"], str) and data["voter_user_id"]
    assert data["decision"] in ("APPROVE", "REJECT", "ABSTAIN")
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["status"] in ("ACTIVE", "VOIDED")


def assert_integration_plan(data: dict):
    assert_common_fields(data, "IntegrationPlan")
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["practice_group_id"])
    assert is_valid_uuid(data["offer_id"])
    assert data["status"] in ("DRAFT", "ACTIVE", "COMPLETED", "ABANDONED")
    assert is_iso8601_timestamp(data["onboarding_start_date"])
    assert is_iso8601_timestamp(data["onboarding_end_date"])
    money(data["planned_standard_rate_usd"])
    assert isinstance(data["cross_sell_target_count"], int)
    assert 0 <= data["cross_sell_target_count"] <= 50
    assert isinstance(data["introduction_count"], int)
    assert isinstance(data["completed_introduction_count"], int)


def assert_cross_sell_introduction(data: dict):
    assert_common_fields(data, "CrossSellIntroduction")
    assert is_valid_uuid(data["integration_plan_id"])
    assert isinstance(data["target_client_name"], str)
    assert isinstance(data["introducing_partner_name"], str)
    assert is_iso8601_timestamp(data["slot_start_at"])
    assert is_iso8601_timestamp(data["slot_end_at"])
    assert data["status"] in ("PROPOSED", "COMPLETED", "CANCELLED")


def assert_performance_review(data: dict):
    assert_common_fields(data, "PerformanceReview")
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["integration_plan_id"])
    assert is_iso8601_timestamp(data["period_start_date"])
    assert is_iso8601_timestamp(data["period_end_date"])
    assert isinstance(data["period_days"], int) and data["period_days"] >= 1
    assert data["variance_basis"] in ("PLAN_BASIS", "RATE_ADJUSTED_BASIS")
    assert data["performance_flag"] in ("ON_PLAN", "WATCH", "BELOW_PLAN")
    for field in (
        "realized_standard_rate_usd",
        "actual_collections_usd",
        "plan_target_usd",
        "plan_target_adjusted_usd",
        "variance_usd",
        "attainment_pct",
    ):
        money(data[field])
    assert isinstance(data["cross_sell_credit_count"], int)


# ----------------------------------------------------------------------
# Conserved quantities
# ----------------------------------------------------------------------


def assert_guarantee_budget_identity(practice_group: dict):
    """total == available + reserved + committed, on every PracticeGroup."""
    total = money(practice_group["guarantee_budget_total_usd"])
    available = money(practice_group["available_guarantee_budget_usd"])
    reserved = money(practice_group["reserved_guarantee_budget_usd"])
    committed = money(practice_group["committed_guarantee_total_usd"])
    assert abs(total - (available + reserved + committed)) < MONEY_TOLERANCE, (
        "Guarantee budget identity broken: "
        f"total={total} available={available} reserved={reserved} committed={committed}"
    )


def assert_portable_book_identity(assessment: dict):
    """validated + declined == gross, exactly, on every PortabilityAssessment."""
    gross = money(assessment["gross_baseline_total_usd"])
    validated = money(assessment["validated_portable_total_usd"])
    declined = money(assessment["declined_portable_total_usd"])
    assert abs(gross - (validated + declined)) < MONEY_TOLERANCE, (
        "Portable book identity broken: "
        f"gross={gross} validated={validated} declined={declined}"
    )


def assert_vote_ledger_identity(offer: dict):
    """votes_cast_total == active_vote_count + voided_vote_count."""
    total = offer["votes_cast_total"]
    active = offer["active_vote_count"]
    voided = offer["voided_vote_count"]
    assert total == active + voided, (
        "Vote ledger identity broken: "
        f"votes_cast_total={total} active={active} voided={voided}"
    )
