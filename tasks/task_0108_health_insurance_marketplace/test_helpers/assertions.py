"""Entity assertions and domain invariant checkers.

Each assertion validates the response shape and domain invariants
required by the PRD contract. They are intentionally generous about
optional fields: a test that wants to pin a specific computed value
asserts it directly in test code.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    """PRD §2.4: every persisted resource carries an id which is a
    server-minted UUID with no type prefix, and a created_at timestamp
    in ISO 8601 UTC with three fractional digits.
    """
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: "Resources whose data evolves after creation — Application,
    HouseholdMember, Plan, SEPEvent, Enrollment — also carry an
    updated_at timestamp ... and an integer version field that begins at
    1 and increments by exactly 1 on every successful mutation."
    """
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


# ===========================================================================
# Application — PRD §3.1, §3.3
# ===========================================================================
def assert_application(data: Dict[str, Any]) -> None:
    """Validate Application response shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("applicant_id"), str) and data["applicant_id"]
    assert isinstance(data.get("coverage_year"), int)
    assert data.get("status") in {
        "DRAFT", "SUBMITTED", "ELIGIBILITY_DETERMINED", "APPROVED", "DENIED",
    }
    assert isinstance(data.get("filing_state"), str)
    assert len(data["filing_state"]) == 2
    assert data.get("enrollment_window") in {"OEP", "SEP", "CLOSED"}
    # household_size always an integer ≥ 0 once computed.
    if data.get("household_size") is not None:
        assert isinstance(data["household_size"], int)
        assert data["household_size"] >= 0
    # PRD §2.7: monetary fields are integer cents.
    if data.get("total_magi_cents") is not None:
        assert isinstance(data["total_magi_cents"], int)
    if data.get("aptc_estimated_cents") is not None:
        assert isinstance(data["aptc_estimated_cents"], int)
        assert data["aptc_estimated_cents"] >= 0
    if data.get("aptc_reconciled_cents") is not None:
        assert isinstance(data["aptc_reconciled_cents"], int)
        assert data["aptc_reconciled_cents"] >= 0
    assert data.get("csr_eligibility") in {
        "NONE", "CSR_73", "CSR_87", "CSR_94", "CSR_PLUS",
    } if data.get("csr_eligibility") is not None else True
    # PRD §2.7: fpl_percentage rounded half-up to one decimal place.
    if data.get("fpl_percentage") is not None:
        assert isinstance(data["fpl_percentage"], (int, float))


# ===========================================================================
# HouseholdMember — PRD §3.1
# ===========================================================================
def assert_household_member(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert data.get("filer_type") in {
        "PRIMARY_FILER", "SPOUSE", "DEPENDENT",
    }
    assert isinstance(data.get("date_of_birth"), str)
    assert isinstance(data.get("include_in_household"), bool)
    assert isinstance(data.get("include_in_magi"), bool)
    assert isinstance(data.get("is_tobacco_user"), bool)


# ===========================================================================
# IncomeRecord — PRD §3.1; PRD §2.4 append-only entity
# ===========================================================================
def assert_income_record(data: Dict[str, Any]) -> None:
    """PRD §2.4: "Append-only resources — IncomeRecord, Insurer,
    PlanVariant, PremiumInvoice — carry only id and created_at; they
    have no updated_at field and no version field."
    """
    _assert_id_and_created_at(data)
    # Do NOT assert updated_at/version — append-only.
    assert is_valid_uuid(data.get("member_id", ""))
    assert data.get("source_type") in {
        "WAGES", "SELF_EMPLOYMENT", "SOCIAL_SECURITY",
        "INTEREST_DIVIDEND", "RETIREMENT", "RENTAL", "OTHER",
    }
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("effective_date"), str)


# ===========================================================================
# Insurer — PRD §3.5; PRD §2.4 append-only entity
# ===========================================================================
def assert_insurer(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # Do NOT assert updated_at/version — append-only.
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("filing_states"), list)
    for state in data["filing_states"]:
        assert isinstance(state, str) and len(state) == 2
    assert isinstance(data.get("contact_phone"), str)


# ===========================================================================
# Plan — PRD §3.5
# ===========================================================================
def assert_plan(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("insurer_id", ""))
    assert isinstance(data.get("coverage_year"), int)
    assert isinstance(data.get("filing_state"), str)
    assert data.get("tier") in {"BRONZE", "SILVER", "GOLD", "PLATINUM"}
    assert isinstance(data.get("base_monthly_premium_cents"), int)
    assert data["base_monthly_premium_cents"] >= 0
    assert isinstance(data.get("is_benchmark_silver"), bool)
    assert data.get("status") in {"ACTIVE", "WITHDRAWN"}
    assert isinstance(data.get("catalog_version"), int)
    assert data["catalog_version"] >= 1


# ===========================================================================
# PlanVariant — PRD §3.5; PRD §2.4 append-only entity
# ===========================================================================
def assert_plan_variant(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # Do NOT assert updated_at/version — append-only.
    assert is_valid_uuid(data.get("plan_id", ""))
    assert data.get("csr_level") in {
        "STANDARD", "CSR_73", "CSR_87", "CSR_94", "CSR_PLUS",
    }
    assert isinstance(data.get("actuarial_value"), (int, float))
    assert isinstance(data.get("out_of_pocket_max_cents"), int)
    assert data["out_of_pocket_max_cents"] >= 0


# ===========================================================================
# SEPEvent — PRD §3.4
# ===========================================================================
def assert_sep_event(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert data.get("event_type") in {
        "LOSS_OF_COVERAGE", "MARRIAGE", "BIRTH_ADOPTION", "MOVE",
        "INCOME_CHANGE", "MEDICAID_LOSS", "GAINED_CITIZENSHIP",
    }
    assert isinstance(data.get("event_date"), str)
    assert is_iso8601_timestamp(data.get("reported_at", ""))
    assert data.get("status") in {
        "SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED",
    }


# ===========================================================================
# Enrollment — PRD §3.6, §3.7
# ===========================================================================
def assert_enrollment(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("plan_variant_id", ""))
    assert isinstance(data.get("pinned_plan_catalog_version"), int)
    assert data.get("coverage_status") in {
        "PENDING_PAYMENT", "ACTIVE", "GRACE_PERIOD", "TERMINATED",
    }
    assert data.get("payment_status") in {
        "AWAITING_BINDER", "CURRENT",
        "DELINQUENT_M1", "DELINQUENT_M2", "DELINQUENT_M3",
    }
    assert isinstance(data.get("coverage_start_date"), str)
    # PRD §2.7: monetary fields are integer cents.
    for field in (
        "monthly_premium_gross_cents",
        "monthly_aptc_applied_cents",
        "monthly_net_premium_cents",
    ):
        assert isinstance(data.get(field), int), (
            f"{field} must be an integer, got {data.get(field)!r}"
        )
        assert data[field] >= 0
    # PRD §3.6: monthly_net_premium_cents == gross minus APTC applied.
    assert data["monthly_net_premium_cents"] == (
        data["monthly_premium_gross_cents"]
        - data["monthly_aptc_applied_cents"]
    ), (
        "PRD §3.6: monthly_net_premium_cents must equal "
        "monthly_premium_gross_cents minus monthly_aptc_applied_cents"
    )
    # PRD §3.6: APTC applied capped at gross.
    assert (
        data["monthly_aptc_applied_cents"]
        <= data["monthly_premium_gross_cents"]
    ), (
        "PRD §3.6: monthly_aptc_applied_cents has a ceiling at the "
        "gross premium"
    )
    # Terminated reason only after termination.
    if data["coverage_status"] == "TERMINATED":
        assert data.get("terminated_reason") in {
            "NON_PAYMENT", "APPLICANT_CANCELLED", "SEP_REVOKED",
            "COVERAGE_YEAR_ENDED",
        }


# ===========================================================================
# PremiumInvoice — PRD §3.7; PRD §2.4 append-only entity
# ===========================================================================
def assert_premium_invoice(data: Dict[str, Any]) -> None:
    """PRD §2.4: "Append-only resources — IncomeRecord, Insurer,
    PlanVariant, PremiumInvoice — carry only id and created_at."
    """
    _assert_id_and_created_at(data)
    # Do NOT assert updated_at/version — append-only.
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data.get("billing_month"), str)
    # PRD §3.7: billing_month is YYYY-MM.
    assert len(data["billing_month"]) == 7
    for field in (
        "gross_amount_cents", "aptc_amount_cents", "net_amount_cents",
    ):
        assert isinstance(data.get(field), int), (
            f"{field} must be an integer, got {data.get(field)!r}"
        )
    # PRD §3.7: "net_amount_cents to the difference" between gross and
    # aptc.
    assert data["net_amount_cents"] == (
        data["gross_amount_cents"] - data["aptc_amount_cents"]
    ), (
        "PRD §3.7: invoice net_amount_cents must equal "
        "gross_amount_cents minus aptc_amount_cents"
    )
    assert isinstance(data.get("due_date"), str)
    assert data.get("status") in {"ISSUED", "PAID", "WAIVED", "VOIDED"}


# ===========================================================================
# Version-bump invariant — PRD §2.4 / §2.6
# ===========================================================================
def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.4: "an integer version field that begins at 1 and
    increments by exactly 1 on every successful mutation."
    """
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, got {after['version']}"
    )


__all__ = [
    "assert_application",
    "assert_household_member",
    "assert_income_record",
    "assert_insurer",
    "assert_plan",
    "assert_plan_variant",
    "assert_sep_event",
    "assert_enrollment",
    "assert_premium_invoice",
    "assert_version_incremented_by_one",
]
