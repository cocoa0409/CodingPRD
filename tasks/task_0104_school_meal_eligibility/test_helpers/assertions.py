"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the PRD
contract. They are intentionally generous about server-minted fields
(e.g., computed counters): a test that wants to pin a specific computed
value asserts it directly in test code.
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
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: id, created_at, updated_at, and version comprise the
    standard set of system-managed fields on every primary, top-level
    resource (i.e., NOT AllergyProfileEntry or PaidLedgerEntry)."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# District
# ---------------------------------------------------------------------------
def assert_district(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("name"), str) and data["name"], (
        "name must be a non-empty string"
    )
    assert "school_year_start" in data
    assert is_iso8601_timestamp(data["school_year_start"]) or (
        # Some implementations may serialise as YYYY-MM-DD only; tolerate.
        isinstance(data["school_year_start"], str)
        and len(data["school_year_start"]) >= 10
    ), f"school_year_start must be ISO 8601, got {data['school_year_start']!r}"
    assert isinstance(data.get("usda_reimbursement_total_cents"), int)
    assert data["usda_reimbursement_total_cents"] >= 0
    assert isinstance(data.get("top_up_outstanding_cents"), int)


# ---------------------------------------------------------------------------
# ParentAccount
# ---------------------------------------------------------------------------
def assert_parent_account(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("district_id", ""))
    assert isinstance(data.get("parent_email"), str) and data["parent_email"]
    assert isinstance(data.get("prepaid_balance_cents"), int)
    # PRD §3.1 / §3.6: prepaid_balance_cents is never negative.
    assert data["prepaid_balance_cents"] >= 0, (
        f"prepaid_balance_cents must be >= 0, got "
        f"{data['prepaid_balance_cents']}"
    )


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------
def assert_student(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("district_id", ""))
    assert is_valid_uuid(data.get("parent_account_id", ""))
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("grade_level"), int)
    # PRD §3.1: grade_level is an integer from 0 through 12 inclusive.
    assert 0 <= data["grade_level"] <= 12, (
        f"grade_level must be in [0, 12], got {data['grade_level']}"
    )
    # PRD §3.1: eligibility_tier is FREE | REDUCED | PAID; new students
    # start at PAID.
    assert data.get("eligibility_tier") in {"FREE", "REDUCED", "PAID"}, (
        f"eligibility_tier must be FREE|REDUCED|PAID, got "
        f"{data.get('eligibility_tier')!r}"
    )
    # PRD §3.1: eligibility_application_id may be null (paid tier with no
    # application).
    eai = data.get("eligibility_application_id")
    assert eai is None or is_valid_uuid(eai), (
        f"eligibility_application_id must be null or UUID, got {eai!r}"
    )
    assert isinstance(data.get("allergy_block_active"), bool)
    assert isinstance(data.get("meals_served_today_count"), int)
    assert data["meals_served_today_count"] >= 0


# ---------------------------------------------------------------------------
# FrlApplication
# ---------------------------------------------------------------------------
def assert_frl_application(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("district_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    assert isinstance(data.get("household_size"), int)
    assert isinstance(data.get("declared_annual_income_cents"), int)
    assert data["declared_annual_income_cents"] >= 0
    assert isinstance(data.get("documents_attached_count"), int)
    assert data["documents_attached_count"] >= 0
    assert data.get("status") in {
        "DRAFT", "SUBMITTED", "INFO_REQUESTED",
        "APPROVED", "DENIED", "RENEWED_FROM_PRIOR",
    }
    # PRD §3.4: decided_tier is FREE|REDUCED|DENIED_PAID once decided;
    # null otherwise.
    dt = data.get("decided_tier")
    assert dt is None or dt in {"FREE", "REDUCED", "DENIED_PAID"}, (
        f"decided_tier must be null or one of FREE|REDUCED|DENIED_PAID, "
        f"got {dt!r}"
    )


# ---------------------------------------------------------------------------
# MenuItem
# ---------------------------------------------------------------------------
def assert_menu_item(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("district_id", ""))
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("contains_allergens"), list)
    for a in data["contains_allergens"]:
        assert a in {
            "PEANUT", "TREE_NUT", "DAIRY", "EGG",
            "SOY", "WHEAT", "FISH", "SHELLFISH",
        }, f"unknown allergen {a!r}"
    # PRD §3.3: calories and sodium_mg are non-negative integers.
    assert isinstance(data.get("calories"), int) and data["calories"] >= 0
    assert isinstance(data.get("sodium_mg"), int) and data["sodium_mg"] >= 0
    assert isinstance(data.get("full_price_cents"), int)
    assert data["full_price_cents"] >= 0
    assert isinstance(data.get("reimbursable"), bool)
    assert data.get("status") in {"ACTIVE", "RETIRED"}


# ---------------------------------------------------------------------------
# MealServingRecord
# ---------------------------------------------------------------------------
def assert_meal_serving_record(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("district_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("menu_item_id", ""))
    assert "serving_date" in data
    assert data.get("status") in {"SERVED", "VOIDED"}
    assert data.get("tier_at_serving") in {"FREE", "REDUCED", "PAID"}
    assert isinstance(data.get("charged_cents"), int)
    assert data["charged_cents"] >= 0
    assert isinstance(data.get("provisional_reimbursement_cents"), int)
    assert data["provisional_reimbursement_cents"] >= 0


# ---------------------------------------------------------------------------
# UsdaReimbursementClaim
# ---------------------------------------------------------------------------
def assert_usda_claim(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("district_id", ""))
    assert "period_start" in data and "period_end" in data
    assert data.get("status") in {
        "DRAFT", "SUBMITTED", "FINALIZED", "REJECTED",
    }
    assert isinstance(data.get("serving_record_ids"), list)
    for rid in data["serving_record_ids"]:
        assert is_valid_uuid(rid), (
            f"serving_record_ids entries must be UUIDs, got {rid!r}"
        )
    assert isinstance(data.get("final_reimbursement_cents"), int)
    assert data["final_reimbursement_cents"] >= 0
    assert isinstance(data.get("provisional_total_cents"), int)
    assert data["provisional_total_cents"] >= 0


# ---------------------------------------------------------------------------
# AllergyProfileEntry — append-only, ONLY id + created_at per PRD §2.4.
# ---------------------------------------------------------------------------
def assert_allergy_profile_entry(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: AllergyProfileEntry does NOT carry updated_at or version.
    assert is_valid_uuid(data.get("student_id", ""))
    assert data.get("allergen") in {
        "PEANUT", "TREE_NUT", "DAIRY", "EGG",
        "SOY", "WHEAT", "FISH", "SHELLFISH",
    }
    assert data.get("severity") in {"MILD", "MODERATE", "SEVERE"}
    assert data.get("status") in {"ACTIVE", "REVOKED"}
    assert isinstance(data.get("doctor_note_attached"), bool)


# ---------------------------------------------------------------------------
# PaidLedgerEntry — append-only, ONLY id + created_at per PRD §2.4.
# ---------------------------------------------------------------------------
def assert_paid_ledger_entry(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: PaidLedgerEntry does NOT carry updated_at or version.
    assert is_valid_uuid(data.get("parent_account_id", ""))
    assert data.get("type") in {"TOP_UP", "CHARGE", "REFUND"}
    # PRD §3.6: "amount_cents (always positive — sign meaning is encoded
    # by type)".
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] > 0, (
        f"amount_cents must be strictly positive, got {data['amount_cents']}"
    )
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    # PRD §3.6: "serving_record_id linking back to the causing serving
    # (null on TOP_UP)".
    if data["type"] == "TOP_UP":
        assert data.get("serving_record_id") in (None, ""), (
            "TOP_UP entries must have null serving_record_id"
        )
    else:
        srid = data.get("serving_record_id")
        if srid is not None and srid != "":
            assert is_valid_uuid(srid)


# ---------------------------------------------------------------------------
# Nutrition label — PRD §3.3.
# ---------------------------------------------------------------------------
def assert_nutrition_label(data: Dict[str, Any]) -> None:
    """PRD §3.3: "The label is a synthesised object containing four
    fields: calories_per_serving (the menu item's calories),
    sodium_per_serving_mg (the menu item's sodium_mg), allergens (the
    unique entries from contains_allergens, deduplicated and returned in
    lexicographic ascending order), and high_sodium_flag."
    """
    assert isinstance(data.get("calories_per_serving"), int)
    assert data["calories_per_serving"] >= 0
    assert isinstance(data.get("sodium_per_serving_mg"), int)
    assert data["sodium_per_serving_mg"] >= 0
    assert isinstance(data.get("allergens"), list)
    # PRD §3.3: allergens are deduplicated and returned in lexicographic
    # ascending order.
    assert data["allergens"] == sorted(set(data["allergens"])), (
        f"allergens must be deduplicated and sorted ascending, got "
        f"{data['allergens']!r}"
    )
    assert isinstance(data.get("high_sodium_flag"), bool)


# ---------------------------------------------------------------------------
# Version bump invariant — PRD §2.4.
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.4: "A monotonically increasing integer, starting at 1 on
    creation and incremented by exactly one on every persisted mutation
    of the owning resource."
    """
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, got {after['version']}"
    )


__all__ = [
    "assert_district",
    "assert_parent_account",
    "assert_student",
    "assert_frl_application",
    "assert_menu_item",
    "assert_meal_serving_record",
    "assert_usda_claim",
    "assert_allergy_profile_entry",
    "assert_paid_ledger_entry",
    "assert_nutrition_label",
    "assert_version_incremented_by_one",
]
