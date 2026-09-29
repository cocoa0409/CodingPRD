"""Entity assertions and the PRD's arithmetic restated as helpers.

The calculators here reproduce the rounding disciplines of PRD §2.8 exactly:
coverage rounds once on the final weighted sum, a risk score never pre-rounds
its base term, and a budget ask is rounded to whole cents per issue before the
waterfall spends anything.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    AUTOMATED_CREDIT_PER_CRITERION,
    AUTOMATED_ONLY_PROFILE_CAP,
    COVERAGE_WEIGHTS,
    DEBT_SEVERITY_POINTS,
    MANUAL_PROFILE_CAP,
    RISK_SEVERITY_POINTS,
    THRESHOLDS,
    TIER_PENALTY_RATE,
)


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------

def round_half_up(value, places: int = 2) -> float:
    """Round half-up to `places` decimal places (PRD §2.8)."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def round_half_up_cents(value) -> int:
    """Round half-up to whole cents (PRD §2.8)."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Shared shape helpers
# ---------------------------------------------------------------------------

def assert_common_fields(data: dict) -> None:
    """id + created_at + updated_at + version starting at 1 (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_immutable_config_fields(data: dict) -> None:
    """Success criteria carry only `id` and `created_at` (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "a success criterion has no updated_at field at all"
    assert "version" not in data, "a success criterion has no version field at all"


def assert_three_fractional_digits(value: str) -> None:
    """Instants render as ISO 8601 UTC with three fractional digits (PRD §2.4)."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    assert value.endswith("Z"), f"instant must be UTC and end with Z, got {value!r}"
    assert "." in value, f"instant must carry fractional digits, got {value!r}"
    fraction = value.split(".")[-1][:-1]
    assert len(fraction) == 3, f"instant must carry three fractional digits, got {value!r}"


def assert_two_decimal_places(value) -> None:
    assert float(value) == round_half_up(value, 2), (
        f"{value} must be stored to two decimal places"
    )


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------

def assert_standard(data: dict) -> None:
    assert_common_fields(data)
    assert data["code"] in ("WCAG_2_1", "WCAG_2_2", "EN_301_549", "SECTION_508_SW")
    assert isinstance(data["title"], str) and 1 <= len(data["title"]) <= 200
    assert data["surface_scope"] in ("WEB", "SOFTWARE", "BOTH")
    assert data["max_target_level"] in ("A", "AA", "AAA")
    assert isinstance(data["criteria_count"], int) and data["criteria_count"] >= 0


def assert_criterion(data: dict) -> None:
    assert_immutable_config_fields(data)
    assert is_valid_uuid(data["standard_id"])
    assert isinstance(data["criterion_number"], str) and data["criterion_number"]
    assert isinstance(data["title"], str) and 1 <= len(data["title"]) <= 200
    assert data["level"] in ("A", "AA", "AAA")
    assert data["disability_categories"], "disability_categories must be non-empty"
    assert len(set(data["disability_categories"])) == len(data["disability_categories"]), (
        "disability_categories must be duplicate-free"
    )
    for category in data["disability_categories"]:
        assert category in ("VISION", "HEARING", "MOTOR", "COGNITIVE")
    assert data["applies_to_surfaces"], "applies_to_surfaces must be non-empty"
    for surface in data["applies_to_surfaces"]:
        assert surface in ("WEB", "SOFTWARE")


def assert_product(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 160
    assert isinstance(data["version_label"], str) and 1 <= len(data["version_label"]) <= 40
    assert is_valid_uuid(data["standard_id"])
    assert data["target_level"] in ("A", "AA", "AAA")
    assert data["surface_type"] in ("WEB", "SOFTWARE", "BOTH")
    for counter in (
        "components_in_scope_count",
        "components_complete_count",
        "assessed_criteria_count",
        "stale_questionnaire_count",
        "correction_required_questionnaire_count",
        "overdue_committed_blocker_count",
        "accommodations_fulfilled_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer, got {data[counter]!r}"
        )
    assert_two_decimal_places(data["conformance_index_provisional"])
    assert data["assessment_readiness"] in ("NOT_READY", "READY")
    assert data["publication_posture"] in ("OPEN", "RESTRICTED", "FROZEN")


def assert_component(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 160
    assert data["component_type"] in (
        "WEB_UI",
        "DESKTOP_APP",
        "MOBILE_APP",
        "AUTHORING_TOOL",
        "DOCUMENTATION",
    )
    assert isinstance(data["in_scope"], bool)
    assert data["assessment_scope"] in ("FULL", "SAMPLED", "EXCLUDED")
    assert 1 <= int(data["applicable_criteria_count"]) <= 500
    assert 0 <= float(data["user_reach_pct"]) <= 100
    assert data["assessment_state"] in ("PLANNED", "IN_TESTING", "COMPLETE")
    assert data["design_review_state"] in (
        "NOT_REVIEWED",
        "REVIEWED_PASS",
        "REVIEWED_BLOCKED",
    )
    assert_two_decimal_places(data["coverage_pct"])
    assert isinstance(data["evidence_units_total"], int) and data["evidence_units_total"] >= 0
    assert isinstance(data["validated_disability_categories"], list)


def assert_environment(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["at_profile"] in ("SCREEN_READER", "KEYBOARD", "MAGNIFICATION")
    assert isinstance(data["at_product_name"], str) and data["at_product_name"]
    assert data["os_platform"] in ("WINDOWS", "MACOS", "LINUX", "ANDROID", "IOS")
    assert 0 <= int(data["reconfiguration_buffer_minutes"]) <= 240
    assert isinstance(data["scheduled_run_count"], int) and data["scheduled_run_count"] >= 0


def assert_run(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["component_id"])
    assert is_valid_uuid(data["environment_id"])
    assert data["method"] in ("AUTOMATED", "MANUAL")
    assert data["at_profile"] in ("SCREEN_READER", "KEYBOARD", "MAGNIFICATION")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "VOID")
    assert 1 <= int(data["criteria_exercised"]) <= 500
    assert data["disability_categories_validated"], (
        "disability_categories_validated must be non-empty"
    )


def assert_assessment(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["component_id"])
    assert is_valid_uuid(data["criterion_id"])
    assert data["support_level"] in (
        "SUPPORTS",
        "PARTIALLY_SUPPORTS",
        "DOES_NOT_SUPPORT",
        "NOT_APPLICABLE",
    )
    assert data["attestation_state"] in (
        "DRAFT",
        "ATTESTED",
        "NEEDS_REVALIDATION",
        "SUPERSEDED",
    )
    assert data["authored_by_user_id"], "authored_by_user_id records the acting X-User-ID"


def assert_report(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["standard_id"])
    assert isinstance(data["report_title"], str) and 1 <= len(data["report_title"]) <= 200
    assert data["state"] in (
        "DRAFT",
        "IN_REVIEW",
        "CHANGES_REQUESTED",
        "APPROVED",
        "PUBLISHED",
        "SUPERSEDED",
        "WITHDRAWN",
    )
    assert isinstance(data["pinned_assessment_ids"], list)
    assert isinstance(data["pinned_assessment_versions"], list)
    assert len(data["pinned_assessment_ids"]) == len(data["pinned_assessment_versions"]), (
        "pinned ids and pinned versions are index-aligned"
    )
    assert isinstance(data["criterion_support_snapshot"], list)
    assert isinstance(data["published_issue_count"], int)
    assert isinstance(data["change_request_count"], int)


def assert_release_train(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert 0 <= int(data["freeze_days"]) <= 60
    assert 1 <= int(data["effort_capacity_points"]) <= 1000
    assert 0 <= int(data["remediation_budget_cents"]) <= 100000000
    assert isinstance(data["committed_effort_points"], int)
    assert isinstance(data["unallocated_cents"], int)
    assert data["allocation_state"] in ("UNALLOCATED", "ALLOCATED")


def assert_known_issue(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["component_id"])
    assert is_valid_uuid(data["criterion_id"])
    assert data["severity"] in ("BLOCKER", "SERIOUS", "MODERATE", "MINOR")
    assert isinstance(data["summary"], str) and 10 <= len(data["summary"]) <= 1000
    assert 1 <= int(data["effort_points"]) <= 100
    assert data["publish_intent"] in ("INCLUDED", "EXCLUDED")
    assert data["state"] in (
        "OPEN",
        "TRIAGED",
        "DEFERRED",
        "COMMITTED",
        "PUBLISHED_COMMITTED",
        "RESOLVED",
    )
    assert data["funding_state"] in ("UNFUNDED", "PARTIALLY_FUNDED", "FULLY_FUNDED")
    assert data["risk_variant"] in ("INTAKE_ESTIMATE", "BOARD_REVIEW")
    assert isinstance(data["funded_cents"], int) and data["funded_cents"] >= 0
    assert isinstance(data["linked_complaint_count"], int)
    assert_two_decimal_places(data["risk_score"])


def assert_questionnaire(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["report_id"])
    assert isinstance(data["customer_name"], str) and 1 <= len(data["customer_name"]) <= 160
    assert data["questionnaire_kind"] in (
        "VPAT_ACR",
        "SECTION_508_CHECKLIST",
        "EN_301_549_ANNEX",
        "CUSTOM_RFP",
    )
    assert data["review_status"] in ("DRAFT", "SUBMITTED", "ATTESTED")
    assert data["accuracy_status"] in ("CURRENT", "STALE", "CORRECTION_REQUIRED")
    assert data["disclosure_tier"] in ("STANDARD", "ELEVATED", "CRITICAL")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert_two_decimal_places(data["disclosure_debt"])


def assert_complaint(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert data["channel"] in ("EMAIL", "PHONE", "WEB_FORM", "REGULATOR_REFERRAL")
    assert isinstance(data["description"], str) and 10 <= len(data["description"]) <= 2000
    assert data["disability_category"] in ("VISION", "HEARING", "MOTOR", "COGNITIVE")
    assert data["state"] in ("NEW", "TRIAGED", "LINKED", "ACCOMMODATED", "CLOSED")
    assert data["route"] in (None, "REMEDIATION", "ACCOMMODATION")


# ---------------------------------------------------------------------------
# Coverage arithmetic (PRD §3.4)
# ---------------------------------------------------------------------------

def expected_coverage_pct(
    applicable_criteria_count: int,
    completed_runs: Iterable[Dict[str, object]],
) -> float:
    """Weighted coverage over the three profiles, rounded exactly once.

    Each entry of `completed_runs` names a `method`, an `at_profile` and a
    `criteria_exercised` count, and stands for one COMPLETED run.
    """
    denominator = Decimal(applicable_criteria_count)
    weighted = Decimal(0)
    for profile, weight in COVERAGE_WEIGHTS.items():
        automated = sum(
            int(run["criteria_exercised"])
            for run in completed_runs
            if run["at_profile"] == profile and run["method"] == "AUTOMATED"
        )
        manual = sum(
            int(run["criteria_exercised"])
            for run in completed_runs
            if run["at_profile"] == profile and run["method"] == "MANUAL"
        )
        raw = (
            Decimal(str(AUTOMATED_CREDIT_PER_CRITERION)) * Decimal(automated) + Decimal(manual)
        ) / denominator
        raw = min(raw, Decimal(1))
        cap = Decimal(str(MANUAL_PROFILE_CAP if manual > 0 else AUTOMATED_ONLY_PROFILE_CAP))
        weighted += Decimal(str(weight)) * min(raw, cap)
    return round_half_up(weighted * Decimal(100), 2)


# ---------------------------------------------------------------------------
# Risk scoring (PRD §3.9)
# ---------------------------------------------------------------------------

def risk_base_term(severity: str, category_count: int, user_reach_pct) -> Decimal:
    """Severity points × breadth factor × reach factor, never pre-rounded."""
    severity_points = Decimal(RISK_SEVERITY_POINTS[severity])
    breadth = Decimal(1) + Decimal(str(THRESHOLDS["BREADTH_STEP_PER_EXTRA_CATEGORY"])) * (
        Decimal(category_count) - Decimal(1)
    )
    reach = Decimal(str(THRESHOLDS["REACH_BASE"])) + Decimal(
        str(THRESHOLDS["REACH_SLOPE"])
    ) * Decimal(str(user_reach_pct)) / Decimal(100)
    return severity_points * breadth * reach


def expected_intake_risk_score(severity: str, category_count: int, user_reach_pct) -> float:
    """INTAKE_ESTIMATE: the base term rounded half-up to two decimals."""
    return round_half_up(risk_base_term(severity, category_count, user_reach_pct), 2)


def expected_board_review_risk_score(
    severity: str,
    category_count: int,
    user_reach_pct,
    days_past_target: int = 0,
    linked_complaint_count: int = 0,
) -> float:
    """BOARD_REVIEW: base × aging × complaint multiplier, clamped then rounded."""
    base = risk_base_term(severity, category_count, user_reach_pct)
    overdue_days = max(0, min(int(days_past_target), THRESHOLDS["AGING_MAX_DAYS"]))
    aging = Decimal(1) + Decimal(str(THRESHOLDS["AGING_STEP_PER_DAY"])) * Decimal(overdue_days)
    complaints = min(int(linked_complaint_count), THRESHOLDS["COMPLAINT_CAP"])
    complaint = Decimal(1) + Decimal(str(THRESHOLDS["COMPLAINT_STEP"])) * Decimal(complaints)
    product = base * aging * complaint
    clamped = min(product, Decimal(str(THRESHOLDS["RISK_SCORE_CLAMP"])))
    return round_half_up(clamped, 2)


# ---------------------------------------------------------------------------
# Remediation budget waterfall (PRD §3.9)
# ---------------------------------------------------------------------------

def expected_budget_ask_cents(effort_points: int) -> int:
    """effort_points × 18750 cents × 1.0725, rounded half-up per issue."""
    raw = (
        Decimal(effort_points)
        * Decimal(THRESHOLDS["REMEDIATION_RATE_CENTS_PER_POINT"])
        * Decimal(str(THRESHOLDS["PROGRAMME_OVERHEAD_FACTOR"]))
    )
    return round_half_up_cents(raw)


def expected_waterfall_grants(budget_cents: int, effort_points_in_order: Sequence[int]) -> List[int]:
    """The per-issue grants a strict waterfall produces over the given order."""
    remaining = int(budget_cents)
    grants: List[int] = []
    for points in effort_points_in_order:
        ask = expected_budget_ask_cents(points)
        grant = min(remaining, ask)
        grants.append(grant)
        remaining -= grant
    return grants


def expected_funding_state(grant: int, ask: int) -> str:
    if grant == 0:
        return "UNFUNDED"
    if grant == ask:
        return "FULLY_FUNDED"
    return "PARTIALLY_FUNDED"


# ---------------------------------------------------------------------------
# Disclosure debt (PRD §3.10)
# ---------------------------------------------------------------------------

def expected_debt_base(contributing_issues: Iterable[Dict[str, object]]) -> int:
    """Base debt: severity points plus an overdue surcharge per issue."""
    total = 0
    for issue in contributing_issues:
        total += DEBT_SEVERITY_POINTS[str(issue["severity"])]
        if issue.get("overdue"):
            total += THRESHOLDS["DEBT_OVERDUE_SURCHARGE"]
    return total


def expected_debt_tier(base_debt: int) -> str:
    """The tier is keyed on the base debt and on nothing else."""
    if base_debt <= THRESHOLDS["DEBT_TIER_STANDARD_MAX"]:
        return "STANDARD"
    if base_debt <= THRESHOLDS["DEBT_TIER_ELEVATED_MAX"]:
        return "ELEVATED"
    return "CRITICAL"


def expected_disclosure_debt(base_debt: int, whole_days_since_reference: int) -> float:
    """base debt + staleness penalty, rounded half-up to two decimals."""
    tier = expected_debt_tier(base_debt)
    bucket = min(
        int(whole_days_since_reference) // THRESHOLDS["DEBT_STALENESS_BUCKET_DAYS"],
        THRESHOLDS["DEBT_STALENESS_BUCKET_CAP"],
    )
    penalty = Decimal(str(TIER_PENALTY_RATE[tier])) * Decimal(bucket)
    return round_half_up(Decimal(base_debt) + penalty, 2)


# ---------------------------------------------------------------------------
# Conformance index (PRD §3.6)
# ---------------------------------------------------------------------------

def expected_index(numerator, denominator: int) -> float:
    """100 × numerator / denominator, or 0.00 on an empty denominator."""
    if denominator == 0:
        return 0.00
    return round_half_up(Decimal(100) * Decimal(str(numerator)) / Decimal(denominator), 2)


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

def assert_budget_conservation(train: dict, funded_cents_total: int) -> None:
    """A train's budget equals its unallocated remainder plus its grants."""
    assert train["remediation_budget_cents"] == train["unallocated_cents"] + funded_cents_total, (
        "remediation_budget_cents must equal unallocated_cents plus the sum of funded_cents, "
        f"got {train['remediation_budget_cents']} vs "
        f"{train['unallocated_cents']} + {funded_cents_total}"
    )


def assert_evidence_conservation(component: dict, expected_units: int) -> None:
    """evidence_units_total is the sum of criteria_exercised over COMPLETED runs."""
    assert component["evidence_units_total"] == expected_units, (
        "evidence_units_total must equal the sum of criteria_exercised over the component's "
        f"COMPLETED runs, expected {expected_units}, got {component['evidence_units_total']}"
    )


def assert_posture(product: dict, expected: str) -> None:
    assert product["publication_posture"] == expected, (
        f"publication_posture must be {expected}, got {product['publication_posture']} "
        f"(overdue={product.get('overdue_committed_blocker_count')}, "
        f"correction_required={product.get('correction_required_questionnaire_count')}, "
        f"stale={product.get('stale_questionnaire_count')}, "
        f"assessed={product.get('assessed_criteria_count')}, "
        f"index={product.get('conformance_index_provisional')})"
    )
