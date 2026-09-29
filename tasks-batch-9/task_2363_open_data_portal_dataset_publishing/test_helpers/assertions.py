"""
Domain assertion helpers for the Open Data Portal API.

These wrap the generic structural assertions and add the invariants the PRD states
about this domain: the four system-managed properties, the credit-conservation
invariant, 2-decimal money, and the derived-field pairings.
"""

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

MONEY_TOLERANCE = 0.005


# ─── Structural ───────────────────────────────────────────────────────


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every persisted resource carries `id`, `created_at`, `updated_at`, `version`."""
    assert is_valid_uuid(entity.get("id", "")), f"id must be a UUID with no type prefix: {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC timestamp: {entity.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(entity.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC timestamp: {entity.get('updated_at')!r}"
    )
    assert isinstance(entity.get("version"), int), f"version must be an integer: {entity.get('version')!r}"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"Expected version {expected_version}, got {entity['version']}"
        )


def assert_envelope_object(body: Dict[str, Any]) -> None:
    """A single-resource response answers with `response_type` \"object\"."""
    assert body.get("response_type") == "object", (
        f"Expected response_type 'object', got {body.get('response_type')!r}"
    )
    meta = body.get("meta", {})
    assert str(meta.get("api_request_id", "")).startswith("req_"), (
        f"api_request_id must start with 'req_': {meta.get('api_request_id')!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        f"api_request_timestamp must be ISO 8601: {meta.get('api_request_timestamp')!r}"
    )


def assert_money(actual: Any, expected: float, label: str = "amount") -> None:
    """A 2-decimal credit quantity equals `expected`."""
    assert actual is not None, f"{label} must be present"
    assert float(actual) == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"Expected {label} {expected:.2f}, got {actual}"
    )


def assert_two_decimals(value: Any, label: str = "value") -> None:
    """A derived numeric is carried to at most 2 decimal places."""
    assert value is not None, f"{label} must be present"
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"{label} must be carried to 2 decimal places, got {value}"
    )


# ─── Dataset ──────────────────────────────────────────────────────────


def assert_dataset_states(
    dataset: Dict[str, Any],
    publication_status: Optional[str] = None,
    currency_status: Optional[str] = None,
) -> None:
    """The dataset's two independent state dimensions."""
    if publication_status is not None:
        assert dataset.get("publication_status") == publication_status, (
            f"Expected publication_status {publication_status}, got {dataset.get('publication_status')}"
        )
    if currency_status is not None:
        assert dataset.get("currency_status") == currency_status, (
            f"Expected currency_status {currency_status}, got {dataset.get('currency_status')}"
        )


def assert_priority(
    dataset: Dict[str, Any],
    priority_score: Optional[float] = None,
    priority_score_variant: Optional[str] = None,
    priority_tier: Optional[str] = None,
) -> None:
    """`priority_score` with the variant that produced it and the tier that follows."""
    if priority_score is not None:
        assert_money(dataset.get("priority_score"), priority_score, "priority_score")
    if priority_score_variant is not None:
        assert dataset.get("priority_score_variant") == priority_score_variant, (
            f"Expected priority_score_variant {priority_score_variant}, "
            f"got {dataset.get('priority_score_variant')}"
        )
    if priority_tier is not None:
        assert dataset.get("priority_tier") == priority_tier, (
            f"Expected priority_tier {priority_tier}, got {dataset.get('priority_tier')}"
        )


# ─── Credits ──────────────────────────────────────────────────────────


def assert_credit_buckets(
    department: Dict[str, Any],
    issued: Optional[float] = None,
    balance: Optional[float] = None,
    escrowed: Optional[float] = None,
    consumed: Optional[float] = None,
) -> None:
    """Assert the four departmental credit buckets."""
    if issued is not None:
        assert_money(department.get("credits_issued_units"), issued, "credits_issued_units")
    if balance is not None:
        assert_money(department.get("credit_balance_units"), balance, "credit_balance_units")
    if escrowed is not None:
        assert_money(department.get("credits_escrowed_units"), escrowed, "credits_escrowed_units")
    if consumed is not None:
        assert_money(department.get("credits_consumed_units"), consumed, "credits_consumed_units")


def assert_credit_conservation(department: Dict[str, Any]) -> None:
    """`credit_balance_units` + `credits_escrowed_units` + `credits_consumed_units`
    equals `credits_issued_units` — the invariant that must hold after every request."""
    balance = float(department["credit_balance_units"])
    escrowed = float(department["credits_escrowed_units"])
    consumed = float(department["credits_consumed_units"])
    issued = float(department["credits_issued_units"])
    assert balance + escrowed + consumed == pytest.approx(issued, abs=MONEY_TOLERANCE), (
        f"Credit conservation broken: {balance} + {escrowed} + {consumed} != {issued}"
    )


def assert_scorecard_balanced(scorecard: Dict[str, Any]) -> None:
    """The scorecard's own `credit_ledger_balanced` flag and the arithmetic agree."""
    assert scorecard.get("credit_ledger_balanced") is True, (
        f"credit_ledger_balanced must be true, got {scorecard.get('credit_ledger_balanced')!r}"
    )
    assert_credit_conservation(scorecard)


def assert_posture(
    department: Dict[str, Any],
    risk_points: Optional[int] = None,
    compliance_posture: Optional[str] = None,
    breached: Optional[int] = None,
    stale: Optional[int] = None,
    remediation: Optional[int] = None,
    overdue_corrections: Optional[int] = None,
) -> None:
    """Assert the posture arithmetic of a department or its scorecard."""
    if breached is not None:
        assert department.get("breached_dataset_count") == breached, (
            f"Expected breached_dataset_count {breached}, got {department.get('breached_dataset_count')}"
        )
    if stale is not None:
        assert department.get("stale_dataset_count") == stale, (
            f"Expected stale_dataset_count {stale}, got {department.get('stale_dataset_count')}"
        )
    if remediation is not None:
        assert department.get("remediation_dataset_count") == remediation, (
            f"Expected remediation_dataset_count {remediation}, "
            f"got {department.get('remediation_dataset_count')}"
        )
    if overdue_corrections is not None:
        assert department.get("overdue_correction_count") == overdue_corrections, (
            f"Expected overdue_correction_count {overdue_corrections}, "
            f"got {department.get('overdue_correction_count')}"
        )
    if risk_points is not None:
        assert department.get("risk_points") == risk_points, (
            f"Expected risk_points {risk_points}, got {department.get('risk_points')}"
        )
    if compliance_posture is not None:
        assert department.get("compliance_posture") == compliance_posture, (
            f"Expected compliance_posture {compliance_posture}, got {department.get('compliance_posture')}"
        )


# ─── Metadata and privacy ─────────────────────────────────────────────


def assert_component_contributions(record: Dict[str, Any], expected: List[float]) -> None:
    """The six rounded weighted contributions, in declaration order:
    dictionary, provenance, contact, frequency, licence, attribution."""
    contributions = record.get("component_contributions")
    assert isinstance(contributions, list), (
        f"component_contributions must be a list, got {contributions!r}"
    )
    assert len(contributions) == len(expected), (
        f"Expected {len(expected)} component contributions, got {len(contributions)}: {contributions}"
    )
    for index, (actual_value, expected_value) in enumerate(zip(contributions, expected)):
        assert float(actual_value) == pytest.approx(expected_value, abs=MONEY_TOLERANCE), (
            f"component_contributions[{index}]: expected {expected_value:.2f}, got {actual_value}"
        )


def assert_assessment_derived(
    assessment: Dict[str, Any],
    risk_score: Optional[float] = None,
    k_anonymity_k: Optional[int] = None,
    aggregation_required: Optional[bool] = None,
    min_aggregation_geography: Optional[str] = None,
) -> None:
    """The three fields that hang off whichever risk score is current."""
    if risk_score is not None:
        assert_money(assessment.get("risk_score"), risk_score, "risk_score")
    if k_anonymity_k is not None:
        assert assessment.get("k_anonymity_k") == k_anonymity_k, (
            f"Expected k_anonymity_k {k_anonymity_k}, got {assessment.get('k_anonymity_k')}"
        )
    if aggregation_required is not None:
        assert assessment.get("aggregation_required") is aggregation_required, (
            f"Expected aggregation_required {aggregation_required}, "
            f"got {assessment.get('aggregation_required')!r}"
        )
    if min_aggregation_geography is not None:
        assert assessment.get("min_aggregation_geography") == min_aggregation_geography, (
            f"Expected min_aggregation_geography {min_aggregation_geography}, "
            f"got {assessment.get('min_aggregation_geography')}"
        )


# ─── Run settlement ───────────────────────────────────────────────────


def assert_settlement(
    run: Dict[str, Any],
    compute_credits: Optional[float] = None,
    alert_credits: Optional[float] = None,
    subtotal_credits: Optional[float] = None,
    reliability_discount_pct: Optional[float] = None,
    discount_credits: Optional[float] = None,
    total_charge_credits: Optional[float] = None,
    escrow_drawn_units: Optional[float] = None,
    balance_drawn_units: Optional[float] = None,
) -> None:
    """Assert the six-step settlement calculation and the two-bucket waterfall."""
    if compute_credits is not None:
        assert_money(run.get("compute_credits"), compute_credits, "compute_credits")
    if alert_credits is not None:
        assert_money(run.get("alert_credits"), alert_credits, "alert_credits")
    if subtotal_credits is not None:
        assert_money(run.get("subtotal_credits"), subtotal_credits, "subtotal_credits")
    if reliability_discount_pct is not None:
        assert float(run.get("reliability_discount_pct")) == pytest.approx(
            reliability_discount_pct, abs=1e-6
        ), (
            f"Expected reliability_discount_pct {reliability_discount_pct}, "
            f"got {run.get('reliability_discount_pct')}"
        )
    if discount_credits is not None:
        assert_money(run.get("discount_credits"), discount_credits, "discount_credits")
    if total_charge_credits is not None:
        assert_money(run.get("total_charge_credits"), total_charge_credits, "total_charge_credits")
    if escrow_drawn_units is not None:
        assert_money(run.get("escrow_drawn_units"), escrow_drawn_units, "escrow_drawn_units")
    if balance_drawn_units is not None:
        assert_money(run.get("balance_drawn_units"), balance_drawn_units, "balance_drawn_units")


# ─── Versions ─────────────────────────────────────────────────────────


def assert_exactly_one_live_version(versions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A dataset published at least once and never fully retracted has exactly one
    version in `LIVE`. Returns that version."""
    live = [version for version in versions if version.get("status") == "LIVE"]
    assert len(live) == 1, (
        f"Expected exactly one LIVE version, got {len(live)}: "
        f"{[(v.get('version_index'), v.get('status')) for v in versions]}"
    )
    return live[0]


def find_version_by_index(versions: List[Dict[str, Any]], version_index: int) -> Dict[str, Any]:
    """Locate a version by its `version_index` within a listing."""
    matches = [version for version in versions if version.get("version_index") == version_index]
    assert len(matches) == 1, (
        f"Expected exactly one version with version_index {version_index}, got {len(matches)}"
    )
    return matches[0]


def find_showcase_app(dataset: Dict[str, Any], label: str) -> Dict[str, Any]:
    """Locate an inline showcase entry by its `label`."""
    matches = [app for app in dataset.get("showcase_apps", []) if app.get("label") == label]
    assert len(matches) == 1, f"Expected exactly one showcase entry labelled {label!r}, got {len(matches)}"
    return matches[0]
