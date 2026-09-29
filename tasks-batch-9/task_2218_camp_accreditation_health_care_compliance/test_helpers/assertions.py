"""Shape checkers and conserved-quantity checkers for the accreditation domain."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    FROZEN_PENALTY_POINTS,
    LICENSE_PENALTY,
    PCT_TOLERANCE,
    RESTRICTED_PENALTY_POINTS,
    STAFFING_RANK,
)
from .types import CompliancePosture, DeficiencyStatus

COUNTED_DEFICIENCY_STATUSES = [
    DeficiencyStatus.OPEN,
    DeficiencyStatus.PLAN_SUBMITTED,
    DeficiencyStatus.ESCALATED,
]

COUNTED_SEAT_STATUSES = ["ASSIGNED", "COMPLETED"]


# --------------------------------------------------------------------------
# common properties
# --------------------------------------------------------------------------
def assert_common_fields(row: Dict[str, Any]) -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(row["id"]), f"id is not a bare UUID: {row['id']}"
    assert "-" in row["id"] and not row["id"].startswith(("cmp_", "cyc_", "std_"))
    assert is_iso8601_timestamp(row["created_at"])
    assert is_iso8601_timestamp(row["updated_at"])
    assert isinstance(row["version"], int)
    assert row["version"] >= 1


def assert_has_fields(row: Dict[str, Any], fields: Iterable[str]) -> None:
    missing = [field for field in fields if field not in row]
    assert not missing, f"missing fields: {missing}"


def assert_pct(value: Any, expected: float) -> None:
    """Percentages are carried to exactly two decimal places, rounded half up."""
    assert value is not None
    assert float(value) == pytest.approx(expected, abs=PCT_TOLERANCE)
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9)


# --------------------------------------------------------------------------
# per-entity shapes
# --------------------------------------------------------------------------
CAMP_FIELDS = [
    "name",
    "camp_type",
    "state_code",
    "population_served",
    "program_elements",
    "resident_census",
    "max_daily_census",
    "distance_to_hospital_km",
    "health_staffing_level",
    "required_health_staffing_level",
    "prior_accredited_cycle_count",
    "state_license_number",
    "state_license_status",
    "accreditation_status",
    "penalty_point_balance",
    "compliance_posture",
    "health_intake_status",
    "controlled_intake_units",
    "controlled_on_hand_units",
    "last_accredited_year",
    "risk_index",
    "risk_index_variant",
]


def assert_camp(camp: Dict[str, Any]) -> None:
    assert_common_fields(camp)
    assert_has_fields(camp, CAMP_FIELDS)
    assert camp["required_health_staffing_level"] in STAFFING_RANK
    assert camp["health_staffing_level"] in STAFFING_RANK
    assert 0.00 <= float(camp["risk_index"]) <= 100.00
    assert camp["controlled_on_hand_units"] >= 0


STANDARDS_SET_FIELDS = [
    "edition_code",
    "effective_year",
    "status",
    "published_at",
    "standard_count",
    "mandatory_count",
]


def assert_standards_set(edition: Dict[str, Any]) -> None:
    assert_common_fields(edition)
    assert_has_fields(edition, STANDARDS_SET_FIELDS)


STANDARD_FIELDS = [
    "standards_set_id",
    "code",
    "title",
    "domain",
    "mandatory",
    "scoring_weight",
    "written_plan_type_required",
    "applies_to_camp_types",
    "applies_to_populations",
    "requires_program_elements_any",
    "requires_state_licensed",
]


def assert_standard(standard: Dict[str, Any]) -> None:
    assert_common_fields(standard)
    assert_has_fields(standard, STANDARD_FIELDS)
    assert 1 <= standard["scoring_weight"] <= 5


CYCLE_FIELDS = [
    "camp_id",
    "standards_set_id",
    "cycle_year",
    "status",
    "applicable_standard_count",
    "applicable_mandatory_count",
    "self_assessment_submitted_at",
    "provisional_mandatory_pct",
    "final_mandatory_pct",
    "final_weighted_pct",
    "decision_level",
    "open_deficiency_count",
    "assessed_fee_cents",
    "correction_deadline_at",
    "decision_issued_at",
    "decision_issued_by_user_id",
]


def assert_cycle(cycle: Dict[str, Any]) -> None:
    assert_common_fields(cycle)
    assert_has_fields(cycle, CYCLE_FIELDS)


EVALUATION_FIELDS = [
    "cycle_id",
    "standard_id",
    "visit_id",
    "applicable",
    "mandatory",
    "scoring_weight",
    "self_score",
    "self_status",
    "written_plan_id",
    "note",
    "visitor_score",
    "score_source",
    "visit_status",
    "scored_by_visitor_id",
]


def assert_evaluation(evaluation: Dict[str, Any]) -> None:
    assert_common_fields(evaluation)
    assert_has_fields(evaluation, EVALUATION_FIELDS)


WRITTEN_PLAN_FIELDS = [
    "camp_id",
    "plan_type",
    "body_ref",
    "effective_date",
    "expires_at",
    "physician_reviewed",
    "status",
    "supersedes_plan_id",
    "verified_at",
    "reviewer_user_id",
    "verification_note",
]


def assert_written_plan(plan: Dict[str, Any]) -> None:
    assert_common_fields(plan)
    assert_has_fields(plan, WRITTEN_PLAN_FIELDS)


VISITOR_FIELDS = [
    "full_name",
    "home_state_code",
    "trained_through_year",
    "certifications",
    "employer_camp_id",
    "status",
    "committed_travel_days",
    "deactivated_reason",
]


def assert_visitor(visitor: Dict[str, Any]) -> None:
    assert_common_fields(visitor)
    assert_has_fields(visitor, VISITOR_FIELDS)
    assert visitor["committed_travel_days"] >= 0


VISIT_FIELDS = [
    "cycle_id",
    "window_start_date",
    "window_end_date",
    "status",
    "lead_visitor_id",
    "team_size",
    "required_specialist_domains",
    "mandatory_scored_count",
    "mandatory_met_count",
    "provisional_mandatory_pct",
    "scheduled_by_user_id",
    "scored_at",
]


def assert_visit(visit: Dict[str, Any]) -> None:
    assert_common_fields(visit)
    assert_has_fields(visit, VISIT_FIELDS)
    assert visit["team_size"] >= 0


ASSIGNMENT_FIELDS = [
    "visit_id",
    "visitor_id",
    "team_role",
    "travel_block_start_date",
    "travel_block_end_date",
    "travel_days",
    "status",
    "withdrawal_reason",
]


def assert_visit_assignment(seat: Dict[str, Any]) -> None:
    assert_common_fields(seat)
    assert_has_fields(seat, ASSIGNMENT_FIELDS)
    assert seat["travel_days"] >= 1


DEFICIENCY_FIELDS = [
    "visit_id",
    "standard_id",
    "severity",
    "base_points",
    "penalty_points",
    "correction_due_date",
    "status",
    "plan_revision_count",
    "correction_plan_text",
    "last_plan_submitted_at",
    "reviewer_user_id",
    "reviewer_note",
]


def assert_deficiency(deficiency: Dict[str, Any]) -> None:
    assert_common_fields(deficiency)
    assert_has_fields(deficiency, DEFICIENCY_FIELDS)


MED_RECORD_FIELDS = [
    "camp_id",
    "camper_reference",
    "medication_class",
    "dose_units",
    "administered_at",
    "administered_by_role",
    "second_signature_present",
    "record_status",
    "compliance_flag",
    "void_reason",
]


def assert_medication_record(record: Dict[str, Any]) -> None:
    assert_common_fields(record)
    assert_has_fields(record, MED_RECORD_FIELDS)
    assert record["dose_units"] >= 1


ANNUAL_REPORT_FIELDS = [
    "camp_id",
    "report_year",
    "due_date",
    "status",
    "declared_incident_count",
    "disclosed_incident_count",
    "reopen_count",
    "submitted_at",
    "attested_by_user_id",
    "reviewer_note",
]


def assert_annual_report(report: Dict[str, Any]) -> None:
    assert_common_fields(report)
    assert_has_fields(report, ANNUAL_REPORT_FIELDS)


DISCLOSURE_FIELDS = [
    "annual_report_id",
    "incident_type",
    "occurred_at",
    "disclosed_at",
    "severity_weight",
    "state_notification_required",
    "status",
]


def assert_incident_disclosure(disclosure: Dict[str, Any]) -> None:
    assert_common_fields(disclosure)
    assert_has_fields(disclosure, DISCLOSURE_FIELDS)


# --------------------------------------------------------------------------
# domain invariants
# --------------------------------------------------------------------------
def expected_posture(
    penalty_point_balance: int,
    state_license_status: str,
    health_staffing_level: str,
    required_health_staffing_level: str,
    has_escalated_deficiency: bool = False,
) -> str:
    """The compliance posture decided by the first matching clause."""
    if (
        penalty_point_balance >= FROZEN_PENALTY_POINTS
        or state_license_status == "SUSPENDED"
        or has_escalated_deficiency
    ):
        return CompliancePosture.FROZEN
    if (
        penalty_point_balance >= RESTRICTED_PENALTY_POINTS
        or state_license_status in ("PENDING", "PROBATION")
        or STAFFING_RANK[health_staffing_level] < STAFFING_RANK[required_health_staffing_level]
    ):
        return CompliancePosture.RESTRICTED
    return CompliancePosture.OPEN


def assert_posture_matches_axes(
    camp: Dict[str, Any], has_escalated_deficiency: bool = False
) -> None:
    assert camp["compliance_posture"] == expected_posture(
        camp["penalty_point_balance"],
        camp["state_license_status"],
        camp["health_staffing_level"],
        camp["required_health_staffing_level"],
        has_escalated_deficiency,
    )


def assert_penalty_balance_conserved(
    camp: Dict[str, Any], deficiencies: List[Dict[str, Any]]
) -> None:
    """penalty_point_balance is the sum of penalty_points over OPEN, PLAN_SUBMITTED
    and ESCALATED findings of the camp."""
    expected = sum(
        row["penalty_points"]
        for row in deficiencies
        if row["status"] in COUNTED_DEFICIENCY_STATUSES
    )
    assert camp["penalty_point_balance"] == expected


def assert_travel_days_conserved(
    visitor: Dict[str, Any], seats: List[Dict[str, Any]]
) -> None:
    """committed_travel_days is the sum of travel_days over ASSIGNED and COMPLETED seats."""
    expected = sum(
        seat["travel_days"] for seat in seats if seat["status"] in COUNTED_SEAT_STATUSES
    )
    assert visitor["committed_travel_days"] == expected


def assert_controlled_stock_conserved(
    camp: Dict[str, Any], records: List[Dict[str, Any]]
) -> None:
    """controlled_on_hand_units is controlled_intake_units minus the RECORDED
    CONTROLLED doses."""
    consumed = sum(
        record["dose_units"]
        for record in records
        if record["medication_class"] == "CONTROLLED" and record["record_status"] == "RECORDED"
    )
    assert camp["controlled_on_hand_units"] == camp["controlled_intake_units"] - consumed
    assert camp["controlled_on_hand_units"] >= 0


def assert_license_penalty(components: Dict[str, Any], state_license_status: str) -> None:
    assert components["license_penalty"] == LICENSE_PENALTY[state_license_status]


RISK_INDEX_COMPONENT_FIELDS = [
    "camp_id",
    "risk_index_variant",
    "incident_component",
    "program_component",
    "staffing_gap_penalty",
    "license_penalty",
    "compliance_component",
    "population_multiplier",
    "risk_index",
]


def assert_risk_index_breakdown(components: Dict[str, Any]) -> None:
    assert_has_fields(components, RISK_INDEX_COMPONENT_FIELDS)
    assert 0.00 <= float(components["risk_index"]) <= 100.00


COMPLIANCE_SUMMARY_FIELDS = [
    "cycle_id",
    "applicable_standard_count",
    "applicable_mandatory_count",
    "provisional_denominator",
    "provisional_numerator",
    "provisional_mandatory_pct",
    "final_denominator",
    "final_numerator",
    "final_mandatory_pct",
    "weighted_total",
    "weighted_met",
    "final_weighted_pct",
    "open_deficiency_count",
    "projected_decision_level",
]


def assert_compliance_summary(summary: Dict[str, Any]) -> None:
    assert_has_fields(summary, COMPLIANCE_SUMMARY_FIELDS)


def assert_no_type_prefix(identifier: str) -> None:
    assert is_valid_uuid(identifier)


def assert_optional_null(row: Dict[str, Any], fields: Iterable[str]) -> None:
    for field in fields:
        assert row[field] is None, f"expected {field} to be null, got {row[field]!r}"


def assert_meta_pagination(meta: Dict[str, Any], limit: int, offset: int) -> None:
    assert meta["limit"] == limit
    assert meta["offset"] == offset
    assert "total_count" in meta
    assert "has_more" in meta


def find_by(rows: Iterable[Dict[str, Any]], **predicates: Any) -> Optional[Dict[str, Any]]:
    for row in rows:
        if all(row.get(key) == value for key, value in predicates.items()):
            return row
    return None
