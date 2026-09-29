"""Per-resource shape assertions, instant comparison helpers and domain invariants."""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BASE_SUPPORT_CENTS_PER_MONTH,
    BROADBAND_UPLIFT_CENTS_PER_MONTH,
    FPG_BASE_ANNUAL_CENTS,
    FPG_PER_ADDITIONAL_CENTS,
    INCOME_MULTIPLIER_STANDARD,
    INCOME_MULTIPLIER_TRIBAL,
    MINIMUM_THRESHOLD_CENTS,
    PENALTY_RATE_HIGH,
    PENALTY_RATE_LOW,
    PENALTY_RATE_MID,
    PENALTY_TIER_1_CENTS,
    PENALTY_TIER_2_CENTS,
    PROGRAM_INCOME_CEILING_CENTS,
    RISK_DEVICE_COUNT_CAP,
    RISK_SCORE_CEILING,
    RISK_WEIGHT_DUPLICATE_ADDRESS,
    RISK_WEIGHT_NON_USAGE,
    RISK_WEIGHT_PER_DEVICE,
    RISK_WEIGHT_RECERT_LAPSE,
    RISK_WEIGHT_TRANSFERRED,
    TRIBAL_ENHANCEMENT_CENTS_PER_MONTH,
)

# ------------------------------------------------------------------ instants


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant regardless of how many fractional digits it carries."""
    assert isinstance(value, str) and value, f"expected an instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def instants_equal(left: str, right: str) -> bool:
    """True when two ISO 8601 strings name the same instant."""
    return parse_instant(left) == parse_instant(right)


def assert_instant(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two instants by value so fractional-digit width never matters."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert instants_equal(actual, expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instant_null(actual: Any, label: str = "instant") -> None:
    assert actual is None, f"{label}: expected null, got {actual}"


def assert_date_component(actual: Any, expected_date: str, label: str = "date") -> None:
    """Compare only the calendar date of a stored instant."""
    assert actual is not None, f"{label}: expected {expected_date}, got null"
    got = parse_instant(actual).date().isoformat()
    assert got == expected_date, f"{label}: expected date {expected_date}, got {actual}"


def iso_z(moment: datetime) -> str:
    """Render a datetime as an ISO 8601 UTC instant with millisecond precision."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def shift_instant(value: str, **delta: Any) -> str:
    """An instant offset from another instant, preserving time of day."""
    return iso_z(parse_instant(value) + timedelta(**delta))


def day_start_after(value: str, days: int) -> str:
    """Add days to the calendar date of an instant and stamp 00:00:00.000Z."""
    base = parse_instant(value).date() + timedelta(days=days)
    return f"{base.isoformat()}T00:00:00.000Z"


def day_end_after(value: str, days: int) -> str:
    """Add days to the calendar date of an instant and stamp 23:59:59.999Z."""
    base = parse_instant(value).date() + timedelta(days=days)
    return f"{base.isoformat()}T23:59:59.999Z"


# ------------------------------------------------------------------- money math


def round_half_up(value: Any) -> int:
    """Round a rational or float to the nearest whole cent, halves away from zero."""
    if isinstance(value, Fraction):
        quantised = Decimal(value.numerator) / Decimal(value.denominator)
    else:
        quantised = Decimal(str(value))
    return int(quantised.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def expected_income_threshold(household_size: int, tribal_lands_flag: bool) -> int:
    """The program income threshold in cents for a household."""
    guideline = FPG_BASE_ANNUAL_CENTS + FPG_PER_ADDITIONAL_CENTS * (household_size - 1)
    multiplier = (
        INCOME_MULTIPLIER_TRIBAL if tribal_lands_flag else INCOME_MULTIPLIER_STANDARD
    )
    product = round_half_up(Decimal(guideline) * Decimal(str(multiplier)))
    product = min(product, PROGRAM_INCOME_CEILING_CENTS)
    return max(product, MINIMUM_THRESHOLD_CENTS)


def monthly_support_rate(service_type: str, tribal_lands_flag: bool) -> int:
    """The monthly support rate in cents for one benefit."""
    rate = BASE_SUPPORT_CENTS_PER_MONTH
    if tribal_lands_flag:
        rate += TRIBAL_ENHANCEMENT_CENTS_PER_MONTH
    if service_type in ("BROADBAND", "BUNDLED"):
        rate += BROADBAND_UPLIFT_CENTS_PER_MONTH
    return rate


def expected_support_line(rate_cents: int, support_days: int, days_in_month: int) -> int:
    """One per-enrollment support line, rounded before it joins any sum."""
    return round_half_up(Fraction(rate_cents * support_days, days_in_month))


def expected_recoupment(
    final_amount_cents: int, failed_sample_count: int, audit_sample_count: int
) -> Dict[str, int]:
    """The extrapolation, penalty, recoupment and net payable figures for a failed audit."""
    rate = Fraction(failed_sample_count, audit_sample_count)
    extrapolated = round_half_up(Fraction(final_amount_cents) * rate)
    if extrapolated < PENALTY_TIER_1_CENTS:
        penalty_rate = PENALTY_RATE_LOW
    elif extrapolated < PENALTY_TIER_2_CENTS:
        penalty_rate = PENALTY_RATE_MID
    else:
        penalty_rate = PENALTY_RATE_HIGH
    penalty = round_half_up(Decimal(extrapolated) * Decimal(str(penalty_rate)))
    recoupment = extrapolated + penalty
    return {
        "extrapolated_cents": extrapolated,
        "penalty_rate": penalty_rate,
        "penalty_cents": penalty,
        "recoupment_amount_cents": recoupment,
        "net_payable_cents": final_amount_cents - recoupment,
    }


def expected_risk_score(
    address_duplicate_flagged: bool = False,
    usage_lapsed: bool = False,
    recert_lapsed: bool = False,
    device_issuance_count: int = 0,
    transfer_count: int = 0,
) -> int:
    """The audit risk score for one benefit, clamped last."""
    total = 0
    if address_duplicate_flagged:
        total += RISK_WEIGHT_DUPLICATE_ADDRESS
    if usage_lapsed:
        total += RISK_WEIGHT_NON_USAGE
    if recert_lapsed:
        total += RISK_WEIGHT_RECERT_LAPSE
    total += RISK_WEIGHT_PER_DEVICE * min(device_issuance_count, RISK_DEVICE_COUNT_CAP)
    if transfer_count >= 1:
        total += RISK_WEIGHT_TRANSFERRED
    return min(total, RISK_SCORE_CEILING)


def address_hash_for(
    address_line1: str,
    unit_designator: Optional[str],
    city: str,
    state_code: str,
    postal_code: str,
) -> str:
    """The canonical duplicate-detection hash for a dwelling."""

    def normalise(part: Optional[str]) -> str:
        text = (part or "").upper()
        return "".join(ch for ch in text if ch.isalnum() and ch.isascii())

    postal5 = (postal_code or "")[:5]
    return "|".join(
        [
            normalise(address_line1),
            normalise(unit_designator),
            normalise(city),
            normalise(state_code),
            normalise(postal5),
        ]
    )


# --------------------------------------------------------------- common shapes


def assert_common_fields(row: Dict[str, Any], label: str = "row") -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(row.get("id")), f"{label}.id must be a bare UUID, got {row.get('id')!r}"
    assert is_iso8601_timestamp(row.get("created_at")), (
        f"{label}.created_at must be an ISO 8601 instant, got {row.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(row.get("updated_at")), (
        f"{label}.updated_at must be an ISO 8601 instant, got {row.get('updated_at')!r}"
    )
    assert isinstance(row.get("version"), int) and row["version"] >= 1, (
        f"{label}.version must be an integer of at least 1, got {row.get('version')!r}"
    )


def assert_meta_envelope(meta: Dict[str, Any]) -> None:
    """Response metadata carries a prefixed request id and a UTC timestamp."""
    assert isinstance(meta.get("api_request_id"), str), "meta.api_request_id must be a string"
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must carry the req_ prefix, got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), (
        f"meta.api_request_timestamp must be an ISO 8601 instant, got {meta.get('api_request_timestamp')!r}"
    )


# -------------------------------------------------------------- resource shapes


def assert_provider(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "Provider")
    for field in (
        "name",
        "spin_id",
        "study_area_code",
        "licensed_state_codes",
        "status",
        "enrollment_cap",
        "active_enrollment_count",
        "devices_total_count",
        "devices_in_stock_count",
        "devices_issued_count",
        "devices_reclaim_pending_count",
        "devices_retired_count",
        "open_claim_count",
        "claim_gross_cents",
        "recouped_cents",
        "net_reimbursed_cents",
        "audit_hold_flag",
    ):
        assert field in row, f"Provider is missing {field}"
    assert row["status"] in ("ACTIVE", "SUSPENDED"), f"unexpected Provider status {row['status']!r}"
    assert isinstance(row["licensed_state_codes"], list) and row["licensed_state_codes"], (
        "Provider.licensed_state_codes must be a non-empty array"
    )
    assert isinstance(row["audit_hold_flag"], bool), "Provider.audit_hold_flag must be a boolean"
    for money in ("claim_gross_cents", "recouped_cents", "net_reimbursed_cents"):
        assert isinstance(row[money], int) and not isinstance(row[money], bool), (
            f"Provider.{money} must be an integer number of cents, got {row[money]!r}"
        )
    assert_device_partition_conserved(row)
    assert_provider_ledger_consistent(row)


def assert_household_address(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "HouseholdAddress")
    for field in (
        "address_line1",
        "unit_designator",
        "city",
        "state_code",
        "postal_code",
        "address_hash",
        "status",
        "declared_household_count",
        "independent_household_worksheet_ref",
        "max_permitted_benefit_slots",
        "occupied_benefit_slots",
        "cohort_address_count",
    ):
        assert field in row, f"HouseholdAddress is missing {field}"
    assert row["status"] in (
        "UNVERIFIED",
        "DUPLICATE_FLAGGED",
        "RESOLVED_MULTI_HOUSEHOLD",
        "RESOLVED_SINGLE_HOUSEHOLD",
    ), f"unexpected HouseholdAddress status {row['status']!r}"
    assert row["cohort_address_count"] >= 1, (
        "a dwelling always counts itself in its cohort"
    )


def assert_subscriber(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "Subscriber")
    for field in (
        "address_id",
        "full_name",
        "date_of_birth",
        "last4_ssn",
        "household_size",
        "annual_income_cents",
        "last_3mo_income_cents",
        "qualifying_benefit",
        "tribal_lands_flag",
        "identity_key",
        "status",
        "eligibility_basis",
        "income_threshold_cents",
        "de_enrollment_count",
    ):
        assert field in row, f"Subscriber is missing {field}"
    assert isinstance(row["annual_income_cents"], int), (
        f"Subscriber.annual_income_cents must be an integer, got {row['annual_income_cents']!r}"
    )
    assert isinstance(row["income_threshold_cents"], int), (
        f"Subscriber.income_threshold_cents must be an integer, got {row['income_threshold_cents']!r}"
    )
    assert row["income_threshold_cents"] == expected_income_threshold(
        row["household_size"], bool(row["tribal_lands_flag"])
    ), (
        "Subscriber.income_threshold_cents does not match the household size and tribal flag"
    )


def assert_eligibility_check(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "EligibilityCheck")
    for field in (
        "subscriber_id",
        "claimed_basis",
        "proof_document_ref",
        "income_variant",
        "evaluated_income_cents",
        "income_threshold_cents",
        "status",
        "verifier_outcome",
        "verifier_reason_code",
        "matched_benefit",
        "confirmed_at",
        "expires_at",
        "resubmission_count",
    ):
        assert field in row, f"EligibilityCheck is missing {field}"
    assert row["claimed_basis"] in ("INCOME", "BENEFIT"), (
        f"unexpected claimed_basis {row['claimed_basis']!r}"
    )
    assert row["status"] in (
        "PENDING_VERIFIER",
        "DOCUMENTATION_REQUIRED",
        "ELIGIBLE_CONFIRMED",
        "INELIGIBLE",
    ), f"unexpected EligibilityCheck status {row['status']!r}"


def assert_enrollment(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "Enrollment")
    for field in (
        "subscriber_id",
        "provider_id",
        "eligibility_check_id",
        "certified_address_id",
        "service_type",
        "one_per_household_attested",
        "benefit_status",
        "usage_status",
        "recert_status",
        "device_status",
        "benefit_start_date",
        "benefit_end_date",
        "port_freeze_until",
        "last_usage_at",
        "non_usage_flagged_at",
        "cure_deadline_at",
        "recert_due_date",
        "recert_notice_sent_at",
        "recert_response_deadline_at",
        "recert_last_responded_at",
        "recert_evaluated_income_cents",
        "recert_income_threshold_cents",
        "de_enrollment_reason",
        "de_enrolled_at",
        "de_enrolled_by_ref",
        "appeal_deadline_at",
        "last_device_issued_at",
        "device_issuance_count",
        "transfer_count",
        "reinstatement_count",
        "audit_risk_score",
    ):
        assert field in row, f"Enrollment is missing {field}"
    assert row["benefit_status"] in ("ACTIVE", "DE_ENROLLED")
    assert row["usage_status"] in (
        "PENDING_FIRST_USE",
        "USING",
        "NON_USAGE_FLAGGED",
        "CURE_EXPIRED",
    )
    assert row["recert_status"] in (
        "NOT_DUE",
        "NOTICED",
        "NON_RESPONSIVE",
        "RESPONDED_INELIGIBLE",
    )
    assert row["device_status"] in ("AWAITING_DEVICE", "DEVICE_ISSUED", "RECLAIM_PENDING")
    assert 0 <= row["audit_risk_score"] <= RISK_SCORE_CEILING, (
        f"audit_risk_score must be clamped to {RISK_SCORE_CEILING}, got {row['audit_risk_score']}"
    )


def assert_device(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "Device")
    for field in (
        "provider_id",
        "imei",
        "model_tier",
        "unit_cost_cents",
        "status",
        "issued_enrollment_id",
        "issued_at",
        "returned_at",
        "return_condition",
    ):
        assert field in row, f"Device is missing {field}"
    assert row["model_tier"] in ("BASIC", "STANDARD", "SMART")
    assert row["status"] in ("IN_STOCK", "ISSUED", "RECLAIM_PENDING", "RETIRED", "LOST")
    assert isinstance(row["unit_cost_cents"], int), (
        f"Device.unit_cost_cents must be an integer, got {row['unit_cost_cents']!r}"
    )


def assert_service_transfer(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "ServiceTransfer")
    for field in (
        "enrollment_id",
        "target_provider_id",
        "source_provider_id",
        "subscriber_consent_ref",
        "status",
        "rejection_reason",
        "requested_at",
        "completed_at",
        "port_freeze_until_snapshot",
    ):
        assert field in row, f"ServiceTransfer is missing {field}"
    assert row["status"] in ("REQUESTED", "ACCEPTED_COMPLETED", "REJECTED", "SUPERSEDED")


def assert_reimbursement_claim(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "ReimbursementClaim")
    for field in (
        "provider_id",
        "service_month",
        "status",
        "provisional_amount_cents",
        "final_amount_cents",
        "variance_cents",
        "covered_enrollment_count",
        "certifying_officer_ref",
        "filed_at",
        "audit_sample_count",
        "failed_sample_count",
        "sample_drawn_by_ref",
        "recoupment_amount_cents",
        "penalty_cents",
        "net_payable_cents",
    ):
        assert field in row, f"ReimbursementClaim is missing {field}"
    assert row["status"] in (
        "DRAFT",
        "FILED",
        "HELD",
        "UNDER_AUDIT",
        "AUDIT_PASSED",
        "AUDIT_FAILED",
        "SUPERSEDED",
    )
    for money in (
        "provisional_amount_cents",
        "final_amount_cents",
        "variance_cents",
        "recoupment_amount_cents",
        "penalty_cents",
        "net_payable_cents",
    ):
        assert isinstance(row[money], int) and not isinstance(row[money], bool), (
            f"ReimbursementClaim.{money} must be an integer number of cents, got {row[money]!r}"
        )


def assert_audit_sample(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "AuditSample")
    for field in (
        "claim_id",
        "enrollment_id",
        "selection_rank",
        "risk_score_at_draw",
        "claimed_line_cents",
        "drawn_by_ref",
        "status",
        "finding",
        "finding_note",
        "adjudicated_by_ref",
        "disallowed_support_cents",
    ):
        assert field in row, f"AuditSample is missing {field}"
    assert row["status"] in ("DRAWN", "ADJUDICATED_PASS", "ADJUDICATED_FAIL")
    assert row["selection_rank"] >= 1, "selection_rank is one-based"


def assert_subscriber_case(row: Dict[str, Any]) -> None:
    assert_common_fields(row, "SubscriberCase")
    for field in (
        "subscriber_id",
        "enrollment_id",
        "case_type",
        "narrative",
        "status",
        "reviewer_ref",
        "review_round",
        "decision",
        "decision_rationale",
        "decided_at",
        "decided_by_ref",
        "reinstated_enrollment_flag",
    ):
        assert field in row, f"SubscriberCase is missing {field}"
    assert row["case_type"] in ("SERVICE_COMPLAINT", "DE_ENROLLMENT_APPEAL")
    assert row["status"] in (
        "SUBMITTED",
        "UNDER_REVIEW",
        "REMANDED",
        "GRANTED",
        "DENIED",
        "RESOLVED",
    )
    assert isinstance(row["reinstated_enrollment_flag"], bool)


# ----------------------------------------------------------------- invariants


def assert_device_partition_conserved(provider: Dict[str, Any]) -> None:
    """The handset inventory partition must always add up to the total."""
    partition = (
        provider["devices_in_stock_count"]
        + provider["devices_issued_count"]
        + provider["devices_reclaim_pending_count"]
        + provider["devices_retired_count"]
    )
    assert provider["devices_total_count"] == partition, (
        "devices_total_count "
        f"{provider['devices_total_count']} != in_stock {provider['devices_in_stock_count']}"
        f" + issued {provider['devices_issued_count']}"
        f" + reclaim_pending {provider['devices_reclaim_pending_count']}"
        f" + retired {provider['devices_retired_count']}"
    )


def assert_provider_ledger_consistent(provider: Dict[str, Any]) -> None:
    """net_reimbursed_cents is always the gross less what has been recouped."""
    assert (
        provider["net_reimbursed_cents"]
        == provider["claim_gross_cents"] - provider["recouped_cents"]
    ), (
        "net_reimbursed_cents "
        f"{provider['net_reimbursed_cents']} != claim_gross_cents {provider['claim_gross_cents']}"
        f" - recouped_cents {provider['recouped_cents']}"
    )


def assert_device_counters(
    provider: Dict[str, Any],
    total: int,
    in_stock: int,
    issued: int,
    reclaim_pending: int,
    retired: int,
) -> None:
    """Pin the whole five-field inventory tuple in one assertion."""
    actual = (
        provider["devices_total_count"],
        provider["devices_in_stock_count"],
        provider["devices_issued_count"],
        provider["devices_reclaim_pending_count"],
        provider["devices_retired_count"],
    )
    assert actual == (total, in_stock, issued, reclaim_pending, retired), (
        f"expected inventory tuple {(total, in_stock, issued, reclaim_pending, retired)}, got {actual}"
    )
    assert_device_partition_conserved(provider)


def assert_ledger_tuple(
    provider: Dict[str, Any],
    claim_gross_cents: int,
    recouped_cents: int,
    net_reimbursed_cents: int,
    audit_hold_flag: bool,
) -> None:
    """Pin the reimbursement ledger triple plus the hold flag."""
    actual = (
        provider["claim_gross_cents"],
        provider["recouped_cents"],
        provider["net_reimbursed_cents"],
        provider["audit_hold_flag"],
    )
    expected = (claim_gross_cents, recouped_cents, net_reimbursed_cents, audit_hold_flag)
    assert actual == expected, f"expected ledger {expected}, got {actual}"
    assert_provider_ledger_consistent(provider)


def assert_de_enrollment_cascade(
    enrollment: Dict[str, Any], reason: str, de_enrolled_at: str, by_ref: str
) -> None:
    """The fields every de-enrollment route writes onto the benefit."""
    assert enrollment["benefit_status"] == "DE_ENROLLED", (
        f"expected benefit_status DE_ENROLLED, got {enrollment['benefit_status']}"
    )
    assert enrollment["de_enrollment_reason"] == reason, (
        f"expected de_enrollment_reason {reason}, got {enrollment['de_enrollment_reason']}"
    )
    assert_instant(enrollment["de_enrolled_at"], de_enrolled_at, "de_enrolled_at")
    assert_instant(enrollment["benefit_end_date"], de_enrolled_at, "benefit_end_date")
    assert enrollment["de_enrolled_by_ref"] == by_ref, (
        f"expected de_enrolled_by_ref {by_ref}, got {enrollment['de_enrolled_by_ref']}"
    )
    assert_instant(
        enrollment["appeal_deadline_at"],
        day_end_after(de_enrolled_at, 30),
        "appeal_deadline_at",
    )
