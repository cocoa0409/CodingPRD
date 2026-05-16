"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract. They are intentionally generous about server-minted
fields: a test that wants to pin a specific computed value asserts it
directly in test code.

PRD §2.4: every persisted resource carries id, created_at, updated_at,
version EXCEPT LateEnrollmentPenalty, DrugClaim, and StarRatingSnapshot
which are lean (id + created_at only).
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
    """PRD §2.4: 'version is an integer that starts at 1 and increments
    by exactly one on each mutation'."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Beneficiary — PRD §3.1
# ---------------------------------------------------------------------------
def assert_beneficiary(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("date_of_birth"), str)
    assert isinstance(data.get("medicare_id"), str)
    # PRD §3.1: 'exactly eleven uppercase-alphanumeric characters'.
    assert len(data["medicare_id"]) == 11, (
        f"medicare_id must be 11 chars, got {data['medicare_id']!r}"
    )
    assert data["medicare_id"].isalnum() and data["medicare_id"].isupper() \
        or data["medicare_id"].isdigit(), (
            f"medicare_id must be uppercase-alphanumeric, got "
            f"{data['medicare_id']!r}"
        )
    assert isinstance(data.get("has_esrd"), bool)
    assert isinstance(data.get("has_disability"), bool)
    assert isinstance(data.get("state_code"), str)
    # PRD §3.1: 'two-letter USPS abbreviation'.
    assert len(data["state_code"]) == 2 and data["state_code"].isupper(), (
        f"state_code must be 2 upper letters, got {data['state_code']!r}"
    )
    assert data.get("lifecycle_status") in {
        "PRE_ELIGIBLE", "IEP_OPEN", "IEP_CLOSED", "ENROLLED",
        "COVERAGE_GAP", "DECEASED",
    }
    assert isinstance(data.get("iep_start_date"), str)
    assert isinstance(data.get("iep_end_date"), str)
    assert isinstance(data.get("medicare_eligibility_date"), str)


# ---------------------------------------------------------------------------
# Plan — PRD §3.3
# ---------------------------------------------------------------------------
def assert_plan(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("plan_code"), str) and data["plan_code"]
    assert data.get("plan_type") in {
        "PART_A", "PART_B", "PART_C", "PART_D", "MEDIGAP",
    }
    assert isinstance(data.get("plan_year"), int)
    # PRD §3.3: '2020 and 2030 inclusive'.
    assert 2020 <= data["plan_year"] <= 2030
    assert isinstance(data.get("monthly_premium_cents"), int)
    assert data["monthly_premium_cents"] >= 0
    # PRD §3.3: 'in half-star increments from 1.0 to 5.0 inclusive'.
    assert isinstance(data.get("star_rating"), (int, float))
    assert 1.0 <= float(data["star_rating"]) <= 5.0
    half = float(data["star_rating"]) * 2
    assert abs(half - round(half)) < 1e-6, (
        f"star_rating must be in half-star increments, got "
        f"{data['star_rating']!r}"
    )
    assert isinstance(data.get("is_active"), bool)
    # Non-Part-D deductible/initial/catastrophic default to 0.
    for field in (
        "annual_deductible_cents",
        "initial_coverage_limit_cents",
        "catastrophic_threshold_cents",
    ):
        assert isinstance(data.get(field), int)
        assert data[field] >= 0


# ---------------------------------------------------------------------------
# EnrollmentPeriod — PRD §3.1 / §3.2
# ---------------------------------------------------------------------------
def assert_enrollment_period(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("beneficiary_id", ""))
    assert data.get("period_type") in {
        "IEP", "AEP", "GEP", "SEP_MOVE", "SEP_LOSS_OF_COVERAGE",
        "MEDIGAP_GI",
    }
    assert isinstance(data.get("window_start"), str)
    assert isinstance(data.get("window_end"), str)
    assert data.get("status") in {
        "SCHEDULED", "OPEN", "CLOSED", "CONSUMED",
    }


# ---------------------------------------------------------------------------
# Enrollment — PRD §3.4 / §3.9
# ---------------------------------------------------------------------------
def assert_enrollment(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("beneficiary_id", ""))
    assert is_valid_uuid(data.get("plan_id", ""))
    assert is_valid_uuid(data.get("enrollment_period_id", ""))
    assert data.get("part_covered") in {
        "PART_A", "PART_B", "PART_C", "PART_D",
    }
    assert data.get("status") in {
        "PENDING", "ACTIVE", "TERMINATED", "REJECTED",
    }
    assert isinstance(data.get("effective_date"), str)
    assert isinstance(data.get("months_late"), int)
    assert data["months_late"] >= 0


# ---------------------------------------------------------------------------
# LateEnrollmentPenalty — PRD §3.5; PRD §2.4 lean entity
# ---------------------------------------------------------------------------
def assert_late_enrollment_penalty(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: 'LateEnrollmentPenalty and DrugClaim carry only id and
    # created_at — they have no updated_at and no version'. So we
    # intentionally do NOT assert updated_at/version here.
    assert is_valid_uuid(data.get("beneficiary_id", ""))
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data.get("part") in {"PART_B", "PART_D"}
    assert isinstance(data.get("months_late"), int)
    assert data["months_late"] >= 0
    assert isinstance(data.get("penalty_rate_decimal"), (int, float))
    assert float(data["penalty_rate_decimal"]) >= 0
    assert isinstance(data.get("monthly_penalty_cents"), int)
    assert data["monthly_penalty_cents"] >= 0
    assert isinstance(data.get("snapshot_base_premium_cents"), int)
    assert data["snapshot_base_premium_cents"] >= 0


# ---------------------------------------------------------------------------
# MedigapPolicy — PRD §3.7
# ---------------------------------------------------------------------------
def assert_medigap_policy(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("beneficiary_id", ""))
    assert is_valid_uuid(data.get("plan_id", ""))
    assert data.get("status") in {
        "APPLIED", "GUARANTEED_ISSUED", "UNDERWRITING", "ISSUED",
        "DENIED", "CANCELLED",
    }
    assert isinstance(data.get("applied_at"), str)
    assert isinstance(
        data.get("underwriting_uplift_decimal"), (int, float),
    )


# ---------------------------------------------------------------------------
# DrugClaim — PRD §3.8; PRD §2.4 lean entity
# ---------------------------------------------------------------------------
def assert_drug_claim(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: lean entity — no updated_at, no version.
    assert is_valid_uuid(data.get("beneficiary_id", ""))
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data.get("ndc_code"), str)
    assert data.get("tier") in {
        "TIER_1", "TIER_2", "TIER_3", "TIER_4", "TIER_5",
    }
    assert isinstance(data.get("fill_date"), str)
    assert isinstance(data.get("gross_cost_cents"), int)
    assert data["gross_cost_cents"] >= 1
    assert data.get("status") in {"SUBMITTED", "ADJUDICATED", "REVERSED"}


# ---------------------------------------------------------------------------
# DrugPhaseLedger — PRD §3.4 / §3.8 / §2.10
# ---------------------------------------------------------------------------
def assert_drug_phase_ledger(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("beneficiary_id", ""))
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data.get("plan_year"), int)
    for field in (
        "deductible_paid_cents",
        "total_drug_spend_cents",
        "troop_cents",
    ):
        assert isinstance(data.get(field), int), (
            f"{field} must be integer cents, got {data.get(field)!r}"
        )
        assert data[field] >= 0
    assert data.get("current_phase") in {
        "DEDUCTIBLE", "INITIAL_COVERAGE", "COVERAGE_GAP", "CATASTROPHIC",
    }


# ---------------------------------------------------------------------------
# StarRatingSnapshot — PRD §3.3; PRD §2.4 lean entity
# ---------------------------------------------------------------------------
def assert_star_rating_snapshot(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: 'The StarRatingSnapshot is likewise lean: only id and
    # created_at accompany its measurement fields.'
    assert is_valid_uuid(data.get("plan_id", ""))
    assert isinstance(data.get("measurement_year"), int)
    assert 2020 <= data["measurement_year"] <= 2030
    for field in (
        "clinical_quality_score",
        "member_experience_score",
        "customer_service_score",
    ):
        assert isinstance(data.get(field), (int, float))
    # PRD §3.3: 'banded into a half-star weighted_star_rating'.
    wsr = data.get("weighted_star_rating")
    assert isinstance(wsr, (int, float))
    assert 1.0 <= float(wsr) <= 5.0
    half = float(wsr) * 2
    assert abs(half - round(half)) < 1e-6
    assert isinstance(data.get("published_at"), str)


# ---------------------------------------------------------------------------
# CostSummary response — PRD §3.6
# ---------------------------------------------------------------------------
def assert_cost_summary(data: Dict[str, Any]) -> None:
    """PRD §3.6: cost-summary returns
    {effective_premium_cents, base_premium_cents, lep_cents, variant}.
    """
    assert "variant" in data
    assert data["variant"] in {"provisional", "final"}, (
        f"variant must be 'provisional' or 'final', got "
        f"{data.get('variant')!r}"
    )
    for field in (
        "effective_premium_cents", "base_premium_cents", "lep_cents",
    ):
        assert isinstance(data.get(field), int), (
            f"{field} must be integer cents, got {data.get(field)!r}"
        )
        assert data[field] >= 0
    # PRD §3.6: 'effective_premium_cents is base_premium_cents plus
    # lep_cents'.
    assert (
        data["effective_premium_cents"]
        == data["base_premium_cents"] + data["lep_cents"]
    ), (
        f"effective_premium_cents must equal base_premium_cents + "
        f"lep_cents, got {data['effective_premium_cents']} != "
        f"{data['base_premium_cents']} + {data['lep_cents']}"
    )


# ---------------------------------------------------------------------------
# DrugCostEstimate forward variant — PRD §3.8
# ---------------------------------------------------------------------------
def assert_drug_cost_estimate(data: Dict[str, Any]) -> None:
    """PRD §3.8: 'The forward variant returns beneficiary_cost_cents,
    plan_cost_cents, and phase_at_adjudication'."""
    assert isinstance(data.get("beneficiary_cost_cents"), int)
    assert data["beneficiary_cost_cents"] >= 0
    assert isinstance(data.get("plan_cost_cents"), int)
    assert data["plan_cost_cents"] >= 0
    assert data.get("phase_at_adjudication") in {
        "DEDUCTIBLE", "INITIAL_COVERAGE", "COVERAGE_GAP", "CATASTROPHIC",
    }


# ---------------------------------------------------------------------------
# Clock — PRD §3.2
# ---------------------------------------------------------------------------
def assert_clock_advance(data: Dict[str, Any]) -> None:
    """PRD §3.2: 'returns the list of transitions actually applied,
    each carrying the entity type, entity id, and the from/to states'.
    """
    assert "now" in data
    assert is_iso8601_timestamp(data["now"]), (
        f"now must be ISO 8601 timestamp, got {data['now']!r}"
    )
    assert "transitions_applied" in data
    assert isinstance(data["transitions_applied"], list)
    for t in data["transitions_applied"]:
        assert "entity_type" in t
        assert "entity_id" in t
        assert "from" in t
        assert "to" in t


# ---------------------------------------------------------------------------
# Version-bump invariant — PRD §2.7
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.7: 'A successful mutation increments the row's version by
    one and refreshes updated_at to the current server time.'
    """
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Ledger compensating invariant — PRD §2.10
# ---------------------------------------------------------------------------
def assert_ledger_sums_equal_adjudicated(
    ledger: Dict[str, Any],
    adjudicated_claims: list,
) -> None:
    """PRD §2.10: 'at all times, the four counters must equal the
    chronological sum (oldest fill_date first; ties broken by
    DrugClaim.id ascending) of the contributions of every claim in
    ADJUDICATED status'.

    The four counters are deductible_paid_cents, total_drug_spend_cents,
    troop_cents, and (derived) current_phase. We check that
    total_drug_spend_cents equals the sum of gross_cost_cents across
    ADJUDICATED claims and troop_cents equals the sum of
    beneficiary_cost_cents (PRD §3.8: beneficiary_share is added to
    troop in every per-phase update).
    """
    total_gross = sum(c["gross_cost_cents"] for c in adjudicated_claims)
    total_bene = sum(c["beneficiary_cost_cents"]
                     for c in adjudicated_claims)
    assert ledger["total_drug_spend_cents"] == total_gross, (
        f"ledger.total_drug_spend_cents ({ledger['total_drug_spend_cents']}) "
        f"!= sum(gross_cost_cents over ADJUDICATED claims) ({total_gross})"
    )
    assert ledger["troop_cents"] == total_bene, (
        f"ledger.troop_cents ({ledger['troop_cents']}) != "
        f"sum(beneficiary_cost_cents over ADJUDICATED claims) "
        f"({total_bene})"
    )


__all__ = [
    "assert_beneficiary",
    "assert_plan",
    "assert_enrollment_period",
    "assert_enrollment",
    "assert_late_enrollment_penalty",
    "assert_medigap_policy",
    "assert_drug_claim",
    "assert_drug_phase_ledger",
    "assert_star_rating_snapshot",
    "assert_cost_summary",
    "assert_drug_cost_estimate",
    "assert_clock_advance",
    "assert_version_incremented_by_one",
    "assert_ledger_sums_equal_adjudicated",
]
