"""Domain shape and invariant assertions."""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CATEGORY_WEIGHT,
    CREDIT_TOLERANCE,
    MEASURE_TOLERANCE,
    ONE_DECIMAL_TOLERANCE,
    TWO_DECIMAL_TOLERANCE,
)


# ---------------------------------------------------------------------------
# Common record properties (PRD 2.5)
# ---------------------------------------------------------------------------
def assert_common_record(record: Dict[str, Any]) -> None:
    """Every record carries id, created_at, updated_at and version."""
    assert is_valid_uuid(record["id"]), f"id must be a UUID: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"])
    assert is_iso8601_timestamp(record["updated_at"])
    assert isinstance(record["version"], int)
    assert record["version"] >= 1


def assert_audit_record(record: Dict[str, Any]) -> None:
    """Append-only rows carry only id and created_at: no updated_at, no version."""
    assert is_valid_uuid(record["id"]), f"id must be a UUID: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"])
    assert "updated_at" not in record, (
        "append-only audit rows must not expose updated_at"
    )
    assert "version" not in record, "append-only audit rows must not expose version"


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------
def assert_carrier(carrier: Dict[str, Any]) -> None:
    assert_common_record(carrier)
    for field in (
        "dot_number",
        "legal_name",
        "average_power_units",
        "annual_vmt",
        "carrier_segment",
        "utilization_factor",
        "safety_fitness_status",
        "intervention_status",
        "open_alert_count",
        "iss_pre_credit_value",
        "data_quality_credit_pct",
        "iss_value",
        "selection_band",
        "challenge_quota_used",
        "challenge_quota_limit",
    ):
        assert field in carrier, f"carrier missing {field}"
    assert carrier["carrier_segment"] in ("SMALL", "MEDIUM", "LARGE")
    assert carrier["selection_band"] in ("PASS", "OPTIONAL", "INSPECT")
    assert carrier["intervention_status"] in ("NONE", "WARNING_LETTER", "INVESTIGATION")


def assert_driver(driver: Dict[str, Any]) -> None:
    assert_common_record(driver)
    for field in (
        "carrier_id",
        "cdl_number",
        "full_name",
        "employment_status",
        "attributed_violation_count",
        "strict_attribution_score",
        "adjudicated_attribution_score",
        "coaching_required",
    ):
        assert field in driver, f"driver missing {field}"
    assert driver["employment_status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")


def assert_violation_code(code: Dict[str, Any]) -> None:
    assert_common_record(code)
    for field in (
        "code",
        "description",
        "basic_category",
        "severity_weight",
        "oos_add_on",
        "driver_attributable",
    ):
        assert field in code, f"violation code missing {field}"
    assert 1 <= code["severity_weight"] <= 10
    assert 0 <= code["oos_add_on"] <= 5


def assert_intervention_threshold(threshold: Dict[str, Any]) -> None:
    assert_common_record(threshold)
    assert (
        threshold["measure_at_p50"]
        < threshold["measure_at_p65"]
        < threshold["measure_at_p80"]
    ), "reference measures must be strictly increasing"
    assert (
        threshold["monitor_percentile"]
        < threshold["intervention_percentile"]
        <= threshold["investigation_percentile"]
    )


def assert_inspection_report(report: Dict[str, Any]) -> None:
    assert_common_record(report)
    for field in (
        "report_number",
        "inspection_state",
        "inspection_level",
        "inspection_start",
        "inspection_end",
        "vehicle_vin",
        "attributed_carrier_id",
        "selection_source",
        "status",
        "active_violation_count",
        "total_time_weighted_severity",
    ):
        assert field in report, f"report missing {field}"
    assert report["status"] in (
        "RECEIVED",
        "VALIDATED",
        "SCORED",
        "AMENDED",
        "RESCINDED",
    )
    assert 1 <= report["inspection_level"] <= 6
    assert report["inspection_end"] > report["inspection_start"]


def assert_violation(violation: Dict[str, Any]) -> None:
    assert_common_record(violation)
    for field in (
        "report_id",
        "violation_code_id",
        "effective_violation_code_id",
        "basic_category",
        "attributed_carrier_id",
        "out_of_service",
        "unit_type",
        "status",
        "under_challenge",
        "time_weight",
        "time_weighted_severity",
    ):
        assert field in violation, f"violation missing {field}"
    assert violation["status"] in ("ACTIVE", "RECODED", "REMOVED")
    assert violation["unit_type"] in ("VEHICLE", "DRIVER")
    assert violation["time_weight"] in (0, 1, 2, 3)


def assert_report_amendment(amendment: Dict[str, Any]) -> None:
    assert_audit_record(amendment)
    for field in (
        "report_id",
        "amendment_type",
        "rationale",
        "applied_at",
        "report_version_before",
        "report_version_after",
    ):
        assert field in amendment, f"amendment missing {field}"
    assert amendment["report_version_after"] > amendment["report_version_before"]


def assert_data_challenge(challenge: Dict[str, Any]) -> None:
    assert_common_record(challenge)
    for field in (
        "report_id",
        "carrier_id",
        "challenge_type",
        "narrative",
        "status",
        "info_request_count",
        "evidence_count",
    ):
        assert field in challenge, f"challenge missing {field}"
    assert challenge["status"] in (
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "INFO_REQUESTED",
        "RESOLVED_ACCEPTED",
        "RESOLVED_REJECTED",
        "WITHDRAWN",
    )
    assert 0 <= challenge["info_request_count"] <= 3


def assert_challenge_evidence(evidence: Dict[str, Any]) -> None:
    assert_audit_record(evidence)
    for field in ("challenge_id", "evidence_type", "document_uri", "submitted_round"):
        assert field in evidence, f"evidence missing {field}"


def assert_citation_adjudication(adj: Dict[str, Any]) -> None:
    assert_common_record(adj)
    for field in (
        "violation_id",
        "citation_number",
        "court_date",
        "court_status",
        "record_update_status",
        "severity_factor",
        "superseded",
    ):
        assert field in adj, f"adjudication missing {field}"
    assert adj["court_status"] in (
        "PENDING",
        "CONVICTED",
        "DISMISSED",
        "REDUCED",
        "NOT_GUILTY",
    )
    assert adj["record_update_status"] in ("NOT_APPLIED", "APPLIED", "NOT_APPLICABLE")


def assert_basic_score(score: Dict[str, Any]) -> None:
    assert_common_record(score)
    for field in (
        "carrier_id",
        "basic_category",
        "snapshot_utc",
        "total_time_weighted_severity",
        "challenged_time_weighted_severity",
        "included_violation_count",
        "relevant_inspection_count",
        "denominator_value",
        "provisional_measure",
        "certified_measure",
        "alert_status",
    ):
        assert field in score, f"basic score missing {field}"
    assert score["alert_status"] in ("CLEAR", "MONITOR", "ALERT", "NOT_ENOUGH_DATA")
    assert score["denominator_value"] >= 1.0, "denominators are floored at 1.0"
    assert score["certified_measure"] <= score["provisional_measure"] + MEASURE_TOLERANCE


def assert_coaching_assignment(assignment: Dict[str, Any]) -> None:
    assert_common_record(assignment)
    for field in (
        "carrier_id",
        "driver_id",
        "violation_id",
        "curriculum_code",
        "session_start",
        "session_end",
        "due_at",
        "status",
    ):
        assert field in assignment, f"coaching assignment missing {field}"
    assert assignment["status"] in (
        "ASSIGNED",
        "IN_PROGRESS",
        "COMPLETED",
        "OVERDUE",
        "WAIVED",
        "ESCALATED",
    )
    assert assignment["session_end"] > assignment["session_start"]


def assert_corrective_action_plan(cap: Dict[str, Any]) -> None:
    assert_common_record(cap)
    for field in (
        "carrier_id",
        "narrative",
        "status",
        "triggering_fitness_status",
        "item_count",
        "committed_item_count",
        "verified_item_count",
        "completion_pct",
    ):
        assert field in cap, f"CAP missing {field}"
    assert cap["status"] in (
        "DRAFT",
        "SUBMITTED",
        "IN_REVIEW",
        "PENDING_DECISION",
        "ACCEPTED",
        "RETURNED",
        "SUPERSEDED",
    )
    assert cap["triggering_fitness_status"] in ("CONDITIONAL", "UNSATISFACTORY")


def assert_cap_action_item(item: Dict[str, Any]) -> None:
    assert_common_record(item)
    for field in ("cap_id", "basic_category", "description", "target_completion_date",
                  "status"):
        assert field in item, f"CAP action item missing {field}"
    assert item["status"] in (
        "PROPOSED",
        "COMMITTED",
        "IMPLEMENTED",
        "VERIFIED",
        "REJECTED_ITEM",
    )


def assert_scoring_run(run: Dict[str, Any]) -> None:
    assert_common_record(run)
    for field in (
        "snapshot_utc",
        "carriers_scored",
        "scores_updated",
        "challenges_expired",
        "coaching_marked_overdue",
        "coaching_waived",
        "status",
    ):
        assert field in run, f"scoring run missing {field}"


# ---------------------------------------------------------------------------
# Precision helpers (PRD 2.7)
# ---------------------------------------------------------------------------
def assert_measure(actual: Optional[float], expected: float) -> None:
    """Measures carry three decimals, rounded half-up."""
    assert actual is not None, "expected a measure, got null"
    assert actual == pytest.approx(expected, abs=MEASURE_TOLERANCE), (
        f"measure {actual} != {expected}"
    )


def assert_one_decimal(actual: Optional[float], expected: float) -> None:
    """Percentiles, ISS values and completion percentages carry one decimal."""
    assert actual is not None, "expected a one-decimal value, got null"
    assert actual == pytest.approx(expected, abs=ONE_DECIMAL_TOLERANCE), (
        f"{actual} != {expected}"
    )


def assert_two_decimals(actual: Optional[float], expected: float) -> None:
    """Contributions and attribution scores carry two decimals."""
    assert actual is not None, "expected a two-decimal value, got null"
    assert actual == pytest.approx(expected, abs=TWO_DECIMAL_TOLERANCE), (
        f"{actual} != {expected}"
    )


def assert_credit_pct(actual: Optional[float], expected: float) -> None:
    """The data-quality credit carries four decimals."""
    assert actual is not None, "expected a credit percentage, got null"
    assert actual == pytest.approx(expected, abs=CREDIT_TOLERANCE), (
        f"credit {actual} != {expected}"
    )


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_time_weighted_severity(
    violation: Dict[str, Any], expected: float
) -> None:
    """time_weighted_severity == (code_weight_snapshot + oos_add_on_snapshot) * time_weight."""
    assert violation["time_weighted_severity"] == pytest.approx(expected, abs=0.01)
    if violation["status"] != "REMOVED":
        recomputed = (
            violation["code_weight_snapshot"] + violation["oos_add_on_snapshot"]
        ) * violation["time_weight"]
        assert violation["time_weighted_severity"] == pytest.approx(
            float(recomputed), abs=0.01
        ), "severity must equal (weight + oos add-on) x time weight"


def find_score(scores: List[Dict[str, Any]], category: str) -> Dict[str, Any]:
    """Pick one BASIC score row out of a listing by category."""
    matches = [s for s in scores if s["basic_category"] == category]
    assert len(matches) == 1, (
        f"expected exactly one {category} score row, found {len(matches)}"
    )
    return matches[0]


def contribution_for(risk: Dict[str, Any], category: str) -> float:
    """Read one per-category contribution out of the screening-risk read."""
    rows = risk["category_contributions"]
    if isinstance(rows, dict):
        assert category in rows, f"no contribution for {category}"
        return float(rows[category])
    matches = [
        r for r in rows if r.get("basic_category") == category or r.get("category") == category
    ]
    assert len(matches) == 1, f"expected one contribution row for {category}"
    row = matches[0]
    for key in ("contribution", "value", "amount"):
        if key in row:
            return float(row[key])
    raise AssertionError(f"contribution row for {category} carries no value: {row}")


def assert_contributions_sum_to_raw(risk: Dict[str, Any]) -> None:
    """PRD 3.5: the pre-credit value is the sum of the already-rounded contributions
    plus the out-of-service adder, capped at 100 and rounded to one decimal."""
    total = sum(contribution_for(risk, k) for k in CATEGORY_WEIGHT)
    expected = min(100.0, total + float(risk["oos_adder"]))
    assert risk["iss_pre_credit_value"] == pytest.approx(
        expected, abs=ONE_DECIMAL_TOLERANCE
    ), (
        f"iss_pre_credit_value {risk['iss_pre_credit_value']} does not equal the sum of "
        f"the rounded contributions {total} plus the OOS adder {risk['oos_adder']}"
    )


def assert_no_version_field(record: Dict[str, Any]) -> None:
    assert "version" not in record, "record must not expose a version"


def assert_selection_band(iss_value: float, band: str) -> None:
    """PRD 3.5 band cut-offs."""
    if iss_value >= 75.0:
        assert band == "INSPECT"
    elif iss_value >= 50.0:
        assert band == "OPTIONAL"
    else:
        assert band == "PASS"
