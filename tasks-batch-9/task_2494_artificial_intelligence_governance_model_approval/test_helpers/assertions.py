"""Per-entity shape assertions, domain invariant checkers, and the arithmetic
the PRD mandates, re-implemented so tests can cross-check a computed field
against an independently derived expectation.

The rounding helpers matter: PRD §2.7 mandates round-half-up, which is *not*
Python's built-in banker's rounding, and mandates that control debt be rounded
per gate before summing rather than summed and rounded once.
"""

import math
import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional

import pytest
from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ACTIVE_BINDING_STATUSES,
    ADEQUACY_SCORE_CAP,
    CONDITION_DEBT_DIVISOR,
    CONSERVATIVE_RETENTION_DAYS,
    CONTROL_CREDIT_CAP,
    CREDIT_PER_CLEARED_GATE,
    CREDIT_PER_PASSED_EVAL,
    DATA_SENSITIVITY_POINTS,
    DEBT_BEARING_GATE_STATUSES,
    DEBT_TOLERANCE,
    DECISION_AUTONOMY_POINTS,
    GATE_WEIGHTS,
    GRADE_BAND_A,
    GRADE_BAND_B,
    GRADE_BAND_C,
    HIGH_SCRUTINY_JURISDICTIONS,
    INCIDENT_BASE_HOURS,
    INDIVIDUAL_IMPACT_POINTS,
    METRIC_TOLERANCE,
    NO_OPT_OUT_POINTS,
    OUTPUT_RIGHTS_POINTS,
    OVERRIDE_CAPABILITY_POINTS,
    POINTS_PER_HIGH_SCRUTINY_JURISDICTION,
    PROVENANCE_POINTS,
    REACH_BANDS,
    REACH_POINTS_BELOW_LOWEST_BAND,
    RETENTION_BANDS,
    RETENTION_POINTS_ABOVE_HIGHEST_BAND,
    REVIEW_MODE_BASE,
    RISK_SCORE_MAX,
    RISK_SCORE_MIN,
    SAMPLE_COMPONENT_CAP,
    SAMPLE_COMPONENT_FACTOR,
    SHADOW_BASE_GRACE_DAYS,
    SLA_COMPONENT_BASE,
    SLA_COMPONENT_HOURS_PER_POINT,
    TIER_BAND_HIGH,
    TIER_BAND_LIMITED,
    TIER_BAND_PROHIBITED,
    TIER_DEBT_MULTIPLIERS,
    TIER_SPEED_FACTOR,
    UNDISCLOSED_PROVENANCE_SURCHARGE,
    UNDISCLOSED_SUBPROCESSORS_POINTS,
    UNRESOLVED_INCIDENT_STATUSES,
    VENDOR_PENALTY_BY_GRADE,
    VENDOR_PENALTY_FIRST_PARTY,
)

# ─── Rounding (PRD §2.7) ───────────────────────────────────────────────────


def round_half_up(value: float, places: int = 0) -> float:
    """Round half away from zero, which is what the PRD means by 'half up'."""
    quantum = Decimal(1).scaleb(-places)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return float(rounded) if places > 0 else float(int(rounded))


def round_half_up_int(value: float) -> int:
    """Round half up to a whole number."""
    return int(round_half_up(value, 0))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ─── Risk classification arithmetic (PRD §3.2) ─────────────────────────────


def expected_reach_points(deployed_headcount_reach: int) -> int:
    for floor_value, points in REACH_BANDS:
        if deployed_headcount_reach >= floor_value:
            return points
    return REACH_POINTS_BELOW_LOWEST_BAND


def expected_jurisdiction_points(jurisdictions: Iterable[str]) -> int:
    high_scrutiny = [j for j in jurisdictions if j in HIGH_SCRUTINY_JURISDICTIONS]
    return len(high_scrutiny) * POINTS_PER_HIGH_SCRUTINY_JURISDICTION


def expected_base_score(payload: dict[str, Any]) -> int:
    """The additive risk score of an intake, before any approval-time credit."""
    return (
        INDIVIDUAL_IMPACT_POINTS[payload["individual_impact"]]
        + DECISION_AUTONOMY_POINTS[payload["decision_autonomy"]]
        + DATA_SENSITIVITY_POINTS[payload["data_sensitivity"]]
        + expected_reach_points(payload["deployed_headcount_reach"])
        + expected_jurisdiction_points(payload.get("jurisdictions") or [])
    )


def tier_for_score(score: int) -> str:
    if score >= TIER_BAND_PROHIBITED:
        return "PROHIBITED"
    if score >= TIER_BAND_HIGH:
        return "HIGH"
    if score >= TIER_BAND_LIMITED:
        return "LIMITED"
    return "MINIMAL"


def is_forced_prohibited(payload: dict[str, Any]) -> bool:
    """All four legs of the prohibited conjunction must hold (PRD §3.2)."""
    return (
        payload.get("affects_individuals") is True
        and payload.get("individual_impact") == "CONSEQUENTIAL"
        and payload.get("decision_autonomy") == "FULLY_AUTOMATED"
        and payload.get("data_sensitivity") == "SPECIAL_CATEGORY"
    )


# ─── Control debt arithmetic (PRD §3.3, §2.7) ──────────────────────────────


def expected_gate_debt(gate_type: str, open_condition_count: int, tier: str) -> float:
    """One gate's debt, rounded half up to two decimals in isolation."""
    raw = (
        GATE_WEIGHTS[gate_type]
        * (open_condition_count / CONDITION_DEBT_DIVISOR)
        * TIER_DEBT_MULTIPLIERS[tier]
    )
    return round_half_up(raw, 2)


def expected_debt_total(gate_conditions: dict[str, int], tier: str) -> float:
    """The portfolio total: each gate rounded first, then the rounded values summed."""
    return round_half_up(
        sum(
            expected_gate_debt(gate_type, count, tier)
            for gate_type, count in gate_conditions.items()
        ),
        2,
    )


# ─── Vendor terms grading (PRD §3.1) ───────────────────────────────────────


def expected_retention_points(effective_retention_days: int) -> int:
    for ceiling, points in RETENTION_BANDS:
        if effective_retention_days <= ceiling:
            return points
    return RETENTION_POINTS_ABOVE_HIGHEST_BAND


def expected_effective_retention_days(payload: dict[str, Any], variant: str) -> int:
    """The conservative variant substitutes a decade whenever terms are unclear."""
    if variant == "CONSERVATIVE_LEGAL":
        if payload.get("retention_days") is None or payload.get("retention_opt_out") is False:
            return CONSERVATIVE_RETENTION_DAYS
    return int(payload["retention_days"])


def expected_terms_risk_points(payload: dict[str, Any], variant: str) -> int:
    provenance = payload["training_data_provenance"]
    points = PROVENANCE_POINTS[provenance]
    if provenance == "UNDISCLOSED" and variant == "CONSERVATIVE_LEGAL":
        points += UNDISCLOSED_PROVENANCE_SURCHARGE
    points += OUTPUT_RIGHTS_POINTS[payload["output_rights"]]
    points += expected_retention_points(
        expected_effective_retention_days(payload, variant)
    )
    if payload.get("retention_opt_out") is False:
        points += NO_OPT_OUT_POINTS
    if payload.get("subprocessors_disclosed") is False:
        points += UNDISCLOSED_SUBPROCESSORS_POINTS
    return points


def grade_for_points(points: int) -> str:
    if points <= GRADE_BAND_A:
        return "A"
    if points <= GRADE_BAND_B:
        return "B"
    if points <= GRADE_BAND_C:
        return "C"
    return "D"


# ─── Oversight adequacy (PRD §3.5) ─────────────────────────────────────────


def expected_adequacy_score(payload: dict[str, Any]) -> int:
    base = REVIEW_MODE_BASE[payload["review_mode"]]
    sample_component = 0
    if payload["review_mode"] == "SAMPLED":
        sample_component = min(
            SAMPLE_COMPONENT_CAP,
            math.floor(payload["sample_pct"] * SAMPLE_COMPONENT_FACTOR),
        )
    sla_component = max(
        0,
        SLA_COMPONENT_BASE
        - math.floor(payload["escalation_sla_hours"] / SLA_COMPONENT_HOURS_PER_POINT),
    )
    override = OVERRIDE_CAPABILITY_POINTS if payload["override_capability"] else 0
    return min(ADEQUACY_SCORE_CAP, base + sample_component + sla_component + override)


# ─── Approval arithmetic (PRD §3.7) ────────────────────────────────────────


def expected_control_credit(cleared_gate_count: int, passed_eval_count: int) -> int:
    raw = (
        cleared_gate_count * CREDIT_PER_CLEARED_GATE
        + passed_eval_count * CREDIT_PER_PASSED_EVAL
    )
    return min(CONTROL_CREDIT_CAP, raw)


def expected_vendor_penalty(is_third_party: bool, terms_grade: Optional[str]) -> int:
    if not is_third_party:
        return VENDOR_PENALTY_FIRST_PARTY
    return VENDOR_PENALTY_BY_GRADE[terms_grade]


def expected_final_score(
    base_score: int, vendor_penalty: int, control_credit: int
) -> int:
    raw = base_score + vendor_penalty - control_credit
    return int(clamp(round_half_up_int(raw), RISK_SCORE_MIN, RISK_SCORE_MAX))


# ─── Incident containment (PRD §3.8) ───────────────────────────────────────


def expected_containment_hours(severity: str, effective_tier: str) -> int:
    """Base hours scaled by the tier speed factor, rounded UP."""
    raw = INCIDENT_BASE_HOURS[severity] * TIER_SPEED_FACTOR[effective_tier]
    return math.ceil(raw)


def expected_posture(incident_statuses_and_severities: Iterable[tuple]) -> str:
    """Posture from the (status, severity) pairs of a use case's incidents."""
    unresolved = [
        (status, severity)
        for status, severity in incident_statuses_and_severities
        if status in UNRESOLVED_INCIDENT_STATUSES
    ]
    if any(severity == "SEV1" for _, severity in unresolved):
        return "IMPAIRED"
    if unresolved:
        return "WATCH"
    return "HEALTHY"


# ─── Shadow grace (PRD §3.9) ───────────────────────────────────────────────


def expected_grace_days(environment: str, grace_days_granted: int = 0) -> int:
    """Base grace for the environment plus the single granted extension."""
    return SHADOW_BASE_GRACE_DAYS[environment] + grace_days_granted


# ─── Envelope-level shape helpers ──────────────────────────────────────────


def assert_common_fields(record: dict[str, Any]) -> None:
    """Assert the identity, audit and concurrency fields every mutable record has."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record.get('id')!r}"
    assert_timestamp_format(record["created_at"])
    assert_timestamp_format(record["updated_at"])
    assert isinstance(record["version"], int), "version must be an integer"
    assert record["version"] >= 1, f"version must start at 1, got {record['version']}"


def assert_append_only_fields(record: dict[str, Any], stamp_field: str) -> None:
    """Assert the reduced field set of an append-only record.

    PRD §2.4 gives these records only ``id`` and ``created_at`` beside their own
    stamped instant, so the mutable-record fields must be absent outright.
    """
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record.get('id')!r}"
    assert_timestamp_format(record["created_at"])
    assert_timestamp_format(record[stamp_field])
    assert "updated_at" not in record, (
        "an append-only record must not expose updated_at"
    )
    assert "version" not in record, "an append-only record must not expose version"


# ─── Per-entity assertions ─────────────────────────────────────────────────


def assert_use_case(use_case: dict[str, Any], **expected: Any) -> None:
    assert_common_fields(use_case)
    assert isinstance(use_case["status"], str)
    assert isinstance(use_case["jurisdictions"], list)
    assert isinstance(use_case["deployed_headcount_reach"], int)
    assert isinstance(use_case["open_conditions_count"], int)
    assert isinstance(use_case["cleared_gate_count"], int)
    _assert_expected(use_case, expected, "use case")


def assert_classification_snapshot(snapshot: dict[str, Any], **expected: Any) -> None:
    assert_append_only_fields(snapshot, "computed_at")
    assert snapshot["variant"] in ("INTAKE_PROVISIONAL", "DEPLOYMENT_FINAL")
    assert isinstance(snapshot["risk_score"], int)
    _assert_expected(snapshot, expected, "classification snapshot")


def assert_review_gate(gate: dict[str, Any], **expected: Any) -> None:
    assert_common_fields(gate)
    assert gate["gate_type"] in GATE_WEIGHTS
    assert isinstance(gate["open_condition_count"], int)
    assert isinstance(gate["control_debt_index"], (int, float))
    _assert_expected(gate, expected, "review gate")


def assert_model_asset(asset: dict[str, Any], **expected: Any) -> None:
    assert_common_fields(asset)
    assert asset["status"] in ("REGISTERED", "APPROVED_FOR_USE", "RESTRICTED")
    assert isinstance(asset["active_binding_count"], int)
    assert isinstance(asset["enforced_shadow_count"], int)
    _assert_expected(asset, expected, "model asset")


def assert_model_binding(binding: dict[str, Any], **expected: Any) -> None:
    assert_common_fields(binding)
    assert binding["status"] in ("PINNED", "STALE", "RETIRED")
    assert isinstance(binding["pinned_model_version"], int)
    _assert_expected(binding, expected, "model binding")


def assert_vendor_assessment(assessment: dict[str, Any], **expected: Any) -> None:
    assert_common_fields(assessment)
    assert assessment["terms_grade"] in ("A", "B", "C", "D")
    assert isinstance(assessment["terms_risk_points"], int)
    _assert_expected(assessment, expected, "vendor assessment")


def assert_test_evaluation(evaluation: dict[str, Any], **expected: Any) -> None:
    assert_common_fields(evaluation)
    assert evaluation["status"] in ("PLANNED", "PASSED", "FAILED", "VOIDED")
    assert_timestamp_format(evaluation["window_start_at"])
    assert_timestamp_format(evaluation["window_end_at"])
    _assert_expected(evaluation, expected, "test evaluation")


def assert_oversight_design(design: dict[str, Any], **expected: Any) -> None:
    assert_common_fields(design)
    assert design["status"] in ("DRAFT", "APPROVED", "REJECTED")
    assert isinstance(design["adequacy_score"], int)
    assert isinstance(design["required_adequacy_score"], int)
    _assert_expected(design, expected, "oversight design")


def assert_disclosure_notice(notice: dict[str, Any], **expected: Any) -> None:
    assert_common_fields(notice)
    assert notice["status"] in ("PUBLISHED", "WITHDRAWN")
    assert_timestamp_format(notice["effective_from"])
    assert_timestamp_format(notice["effective_to"])
    _assert_expected(notice, expected, "disclosure notice")


def assert_monitoring_incident(incident: dict[str, Any], **expected: Any) -> None:
    assert_common_fields(incident)
    assert incident["status"] in ("OPEN", "CONTAINED", "ESCALATED", "RESOLVED")
    assert incident["severity"] in ("SEV1", "SEV2", "SEV3")
    assert_timestamp_format(incident["containment_deadline_at"])
    _assert_expected(incident, expected, "monitoring incident")


def assert_shadow_deployment(shadow: dict[str, Any], **expected: Any) -> None:
    assert_common_fields(shadow)
    assert shadow["status"] in (
        "DISCOVERED",
        "LINKED",
        "GRACE_GRANTED",
        "RETIRED",
        "ENFORCED_BLOCK",
    )
    assert_timestamp_format(shadow["grace_deadline_at"])
    _assert_expected(shadow, expected, "shadow deployment")


def assert_ledger_entry(entry: dict[str, Any], **expected: Any) -> None:
    assert_append_only_fields(entry, "recorded_at")
    assert isinstance(entry["reach_delta"], int)
    assert isinstance(entry["debt_delta"], (int, float))
    assert isinstance(entry["actor_user_id"], str)
    _assert_expected(entry, expected, "ledger entry")


_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def _looks_like_instant(value: Any) -> bool:
    return isinstance(value, str) and bool(_INSTANT_RE.match(value.strip()))


def _assert_expected(record: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    """Compare each named expectation, tolerating float imprecision."""
    for field, want in expected.items():
        assert field in record, f"{label} is missing field {field!r}"
        got = record[field]
        if isinstance(want, float):
            assert got == pytest.approx(want, abs=DEBT_TOLERANCE), (
                f"{label}.{field}: expected {want}, got {got}"
            )
        elif _looks_like_instant(want) and _looks_like_instant(got):
            # Instants are compared on the parsed value, not the rendering: the
            # PRD pins the instant, not the number of fractional digits shown.
            assert parse_instant(got) == parse_instant(want), (
                f"{label}.{field}: expected {want!r}, got {got!r}"
            )
        else:
            assert got == want, f"{label}.{field}: expected {want!r}, got {got!r}"


# ─── Domain invariant checkers ─────────────────────────────────────────────


def assert_metric_value(observed: float, expected: float) -> None:
    """Metrics are compared at four decimal places with no rounding (PRD §2.7)."""
    assert observed == pytest.approx(expected, abs=METRIC_TOLERANCE), (
        f"metric value: expected {expected}, got {observed}"
    )


def assert_debt_equals(observed: float, expected: float) -> None:
    """Control debt is a two-decimal quantity; assert it to the cent."""
    assert observed == pytest.approx(expected, abs=DEBT_TOLERANCE), (
        f"control debt: expected {expected}, got {observed}"
    )


def assert_gate_order(gates: list[dict[str, Any]], expected_types: list[str]) -> None:
    """Gates are listed in creation order, which is the canonical gate order."""
    assert [gate["gate_type"] for gate in gates] == expected_types, (
        f"expected gate order {expected_types}, "
        f"got {[gate['gate_type'] for gate in gates]}"
    )


def assert_created_at_ascending(records: list[dict[str, Any]]) -> None:
    stamps = [record["created_at"] for record in records]
    assert stamps == sorted(stamps), f"records are not in created_at order: {stamps}"


def assert_reach_conserved(summary: dict[str, Any]) -> None:
    """The ledger's reach balance must equal the live portfolio reach."""
    assert summary["ledger_reach_balance"] == summary["portfolio_approved_reach"], (
        f"reach not conserved: ledger {summary['ledger_reach_balance']} "
        f"vs portfolio {summary['portfolio_approved_reach']}"
    )


def assert_debt_conserved(summary: dict[str, Any], expected_balance: float) -> None:
    """The ledger's debt balance must equal the sum of booked debt deltas."""
    assert_debt_equals(summary["ledger_debt_balance"], expected_balance)


def assert_ledger_reach_balance(entries: list[dict[str, Any]], expected: int) -> None:
    total = sum(entry["reach_delta"] for entry in entries)
    assert total == expected, (
        f"ledger reach deltas sum to {total}, expected {expected}"
    )


def assert_ledger_debt_balance(entries: list[dict[str, Any]], expected: float) -> None:
    total = sum(entry["debt_delta"] for entry in entries)
    assert_debt_equals(total, expected)


def entry_types(entries: list[dict[str, Any]]) -> list[str]:
    return [entry["entry_type"] for entry in entries]


def assert_no_ledger_entries(entries: list[dict[str, Any]]) -> None:
    assert entries == [], f"expected an empty ledger, got {entry_types(entries)}"


def assert_active_binding_count(asset: dict[str, Any], bindings: list[dict[str, Any]]) -> None:
    """The asset's counter must equal the number of bindings still holding it."""
    live = [b for b in bindings if b["status"] in ACTIVE_BINDING_STATUSES]
    assert asset["active_binding_count"] == len(live), (
        f"asset.active_binding_count is {asset['active_binding_count']} "
        f"but {len(live)} bindings are PINNED or STALE"
    )


def assert_debt_total_matches_gates(
    summary: dict[str, Any], gates: list[dict[str, Any]]
) -> None:
    """The reported total must be the sum over non-voided gates."""
    expected = round_half_up(
        sum(
            gate["control_debt_index"]
            for gate in gates
            if gate["status"] in DEBT_BEARING_GATE_STATUSES
        ),
        2,
    )
    assert_debt_equals(summary["control_debt_index_total"], expected)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating either 0 or 3 fractional digits.

    PRD §2.5 says instant comparisons are "exact to the second in UTC", and PRD
    §2.4 renders stamps with three fractional digits, so `...T06:00:00Z` and
    `...T06:00:00.000Z` denote the very same instant. Comparing the raw strings
    would test a rendering choice the PRD does not pin down, so every instant
    expectation is compared on the parsed value.
    """
    assert isinstance(value, str), f"not an instant string: {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_iso_instant(value: str, expected: str) -> None:
    """Assert an exact instant, having first checked it is a well-formed stamp."""
    assert is_iso8601_timestamp(value), f"not an ISO 8601 timestamp: {value!r}"
    assert parse_instant(value) == parse_instant(expected), (
        f"expected instant {expected}, got {value}"
    )
