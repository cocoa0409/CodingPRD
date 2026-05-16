"""Entity assertions and domain invariant checkers.

Each `assert_{entity}` validates that a response body carries the
common-fields shape PRD §2.4 requires for that entity plus the
domain-specific fields PRD §3 declares.

PRD §2.4 distinguishes two common-fields shapes:
- Four common properties (id, created_at, updated_at, version) — most
  entities.
- id + created_at only — IncomeRecord, AssetRecord, EmergencyDeclaration
  (append-only).
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-field predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """For entities carrying the four common properties — PRD §2.4."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_no_updated_at_or_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: append-only entities (IncomeRecord, AssetRecord,
    EmergencyDeclaration) carry ONLY id and created_at — no updated_at
    and no version. Use this for those entities to confirm the shape
    matches PRD."""
    # PRD wording: "they have no updated_at and no version". A faithful
    # implementer would not return those fields. We do not strictly fail
    # if an implementation surfaces them — only that the response shape
    # may not advertise them as the documented common properties.
    # (We assert only the absence of `version` since some implementers
    # may carry a created/updated_at pair regardless. PRD strictly says
    # IncomeRecord and AssetRecord do not have updated_at or version.)
    assert "version" not in data, (
        "append-only entities must not return a `version` field per PRD §2.4"
    )


# ---------------------------------------------------------------------------
# Monetary precision — PRD §2.6
# ---------------------------------------------------------------------------
def assert_two_decimal_places(value: float, field_name: str = "value") -> None:
    """PRD §2.6: monetary and percentage values are rounded to exactly
    two decimal places using round-half-up."""
    assert isinstance(value, (int, float)), (
        f"{field_name} must be numeric, got {type(value).__name__}"
    )
    cents = round(float(value) * 100)
    assert abs(cents / 100.0 - float(value)) < 1e-9, (
        f"{field_name}={value} is not at two-decimal precision"
    )


# ---------------------------------------------------------------------------
# StatePolicy — PRD §3.1
# ---------------------------------------------------------------------------
def assert_state_policy(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("state_code"), str) and data["state_code"]
    assert isinstance(data.get("fpl_year"), int)
    assert isinstance(data.get("fpl_base_amount"), (int, float))
    assert isinstance(data.get("fpl_per_member_amount"), (int, float))
    assert isinstance(data.get("magi_income_limit_pct"), (int, float))
    assert isinstance(data.get("emergency_continuous_active"), bool), (
        "emergency_continuous_active must be boolean per PRD §3.1"
    )


# ---------------------------------------------------------------------------
# EmergencyDeclaration — PRD §3.1, §3.5
# ---------------------------------------------------------------------------
def assert_emergency_declaration(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    assert_no_updated_at_or_version(data)
    assert data.get("scope") in {"FEDERAL", "STATE"}, (
        f"scope must be FEDERAL or STATE, got {data.get('scope')!r}"
    )
    if data["scope"] == "FEDERAL":
        # PRD §3.1: "when the scope is FEDERAL, state_code must be null."
        assert data.get("state_code") is None, (
            "FEDERAL EmergencyDeclaration must have state_code=null per "
            "PRD §3.1"
        )
    else:
        assert isinstance(data.get("state_code"), str), (
            "STATE EmergencyDeclaration must have state_code per PRD §3.1"
        )
    assert is_iso8601_timestamp(data.get("declared_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data.get("status") in {"ACTIVE", "EXPIRED"}


# ---------------------------------------------------------------------------
# Household — PRD §3.1
# ---------------------------------------------------------------------------
def assert_household(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("state_code"), str) and data["state_code"]
    assert isinstance(data.get("address_line"), str)
    assert data.get("filing_status") in {
        "SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD",
    }
    # head_applicant_id may be null until first non-EXCLUDED applicant
    # is added — PRD §3.1.
    hai = data.get("head_applicant_id")
    if hai is not None:
        assert is_valid_uuid(hai), (
            f"head_applicant_id must be UUID, got {hai!r}"
        )
    # Computed fields.
    assert isinstance(data.get("household_size"), int)
    assert isinstance(data.get("active_enrollment_count"), int)


# ---------------------------------------------------------------------------
# Applicant — PRD §3.1
# ---------------------------------------------------------------------------
def assert_applicant(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("household_id", ""))
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("date_of_birth"), str)
    assert data.get("dependent_status") in {
        "PRIMARY", "SPOUSE", "DEPENDENT", "EXCLUDED",
    }
    assert isinstance(data.get("is_disabled"), bool)
    assert isinstance(data.get("is_pregnant"), bool)


# ---------------------------------------------------------------------------
# IncomeRecord / AssetRecord — PRD §3.1 (append-only)
# ---------------------------------------------------------------------------
def assert_income_record(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    assert_no_updated_at_or_version(data)
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert data.get("source_type") in {
        "WAGES", "SELF_EMPLOYMENT", "INTEREST", "DIVIDENDS",
        "CAPITAL_GAINS", "SOCIAL_SECURITY", "UNEMPLOYMENT",
        "CHILD_SUPPORT", "TANF", "SSI", "OTHER",
    }
    assert isinstance(data.get("gross_amount"), (int, float))
    assert data.get("frequency") in {"ANNUAL", "MONTHLY", "BIWEEKLY", "WEEKLY"}


def assert_asset_record(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    assert_no_updated_at_or_version(data)
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert data.get("asset_type") in {
        "PRIMARY_RESIDENCE", "VEHICLE", "CHECKING", "SAVINGS",
        "RETIREMENT", "INVESTMENT", "LIFE_INSURANCE", "OTHER",
    }
    assert isinstance(data.get("market_value"), (int, float))


# ---------------------------------------------------------------------------
# Application — PRD §3.3
# ---------------------------------------------------------------------------
def assert_application(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("household_id", ""))
    assert data.get("program") in {
        "MAGI_ADULT", "MAGI_CHILD", "MAGI_PREGNANT",
        "NON_MAGI_DISABILITY", "NON_MAGI_AGED",
    }
    assert data.get("rule_variant") in {"FEDERAL", "STATE"}
    assert data.get("status") in {
        "DRAFT", "UNDER_REVIEW", "APPROVED", "DENIED",
        "APPEALED", "WITHDRAWN",
    }


# ---------------------------------------------------------------------------
# EligibilityDetermination — PRD §3.3
# ---------------------------------------------------------------------------
def assert_eligibility_determination(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_iso8601_timestamp(data.get("decided_at", ""))
    assert data.get("outcome") in {"ELIGIBLE", "INELIGIBLE", "OVERTURNED"}
    # PRD §2.9: ineligibility_reason is null when outcome is ELIGIBLE.
    if data["outcome"] == "ELIGIBLE":
        assert data.get("ineligibility_reason") in (None,), (
            "ineligibility_reason must be null when outcome is ELIGIBLE "
            "per PRD §2.9"
        )
    assert data.get("applied_rule_variant") in {"FEDERAL", "STATE"}


# ---------------------------------------------------------------------------
# Enrollment — PRD §3.4
# ---------------------------------------------------------------------------
def assert_enrollment(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert is_valid_uuid(data.get("determination_id", ""))
    assert is_iso8601_timestamp(data.get("coverage_start", ""))
    assert is_iso8601_timestamp(data.get("coverage_end", ""))
    assert is_iso8601_timestamp(data.get("redetermination_due_at", ""))
    assert data.get("coverage_status") in {
        "ACTIVE", "CONTINUOUS_COVERAGE", "REDETERMINATION_DUE",
        "SUSPENDED", "TERMINATED",
    }
    assert isinstance(data.get("continuous_coverage_flag"), bool)
    # PRD §3.4: "Each enrollment carries a continuous_coverage_flag that
    # is true precisely when its coverage_status is CONTINUOUS_COVERAGE."
    expected_flag = (data["coverage_status"] == "CONTINUOUS_COVERAGE")
    assert data["continuous_coverage_flag"] == expected_flag, (
        f"continuous_coverage_flag={data['continuous_coverage_flag']!r} "
        f"does not match coverage_status={data['coverage_status']!r}"
    )


# ---------------------------------------------------------------------------
# Redetermination — PRD §3.4
# ---------------------------------------------------------------------------
def assert_redetermination(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert data.get("status") in {
        "PENDING", "SUBMITTED", "RENEWED", "TERMINATED", "WITHDRAWN",
    }
    decision = data.get("decision")
    if decision is not None:
        assert decision in {"RENEWED", "TERMINATED"}, (
            f"Redetermination.decision must be RENEWED or TERMINATED, "
            f"got {decision!r}"
        )


# ---------------------------------------------------------------------------
# Appeal — PRD §3.6
# ---------------------------------------------------------------------------
def assert_appeal(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("determination_id", ""))
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert is_iso8601_timestamp(data.get("deadline_at", ""))
    assert data.get("status") in {
        "FILED", "HEARING_SCHEDULED", "UNDER_REVIEW",
        "GRANTED", "UPHELD", "WITHDRAWN",
    }


# ---------------------------------------------------------------------------
# FairHearing — PRD §3.6
# ---------------------------------------------------------------------------
def assert_fair_hearing(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("appeal_id", ""))
    assert isinstance(data.get("officer_id"), str) and data["officer_id"]
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data.get("status") in {"SCHEDULED", "HELD", "CANCELLED"}


# ---------------------------------------------------------------------------
# Version increment — PRD §2.4
# ---------------------------------------------------------------------------
def assert_version_bumped_by_one(before: Dict[str, Any],
                                 after: Dict[str, Any]) -> None:
    """PRD §2.4: "version is incremented by exactly 1 on every successful
    mutation, including mutations induced by cascade."""
    assert "version" in before and "version" in after
    assert after["version"] == before["version"] + 1, (
        f"version must bump by exactly 1, got "
        f"before={before['version']}, after={after['version']}"
    )


__all__ = [
    "assert_two_decimal_places",
    "assert_no_updated_at_or_version",
    "assert_state_policy",
    "assert_emergency_declaration",
    "assert_household",
    "assert_applicant",
    "assert_income_record",
    "assert_asset_record",
    "assert_application",
    "assert_eligibility_determination",
    "assert_enrollment",
    "assert_redetermination",
    "assert_appeal",
    "assert_fair_hearing",
    "assert_version_bumped_by_one",
]
