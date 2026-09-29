"""Entity assertions and domain invariant checkers."""
import re
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    ActivityCode,
    AnalysisStatus,
    CertificateStatus,
    CertificateType,
    CompliancePosture,
    ComplianceStatus,
    CrsCycleStatus,
    Datum,
    DeterminationCaseStatus,
    DeterminationMethod,
    DeterminationOutcome,
    DeterminationTriggerSource,
    DeterminationType,
    DocumentationStatus,
    FirmPanelStatus,
    FloodZone,
    InspectionStatus,
    LossAreaStatus,
    OrderStatus,
    OutreachStatus,
    PermitStatus,
    ProjectType,
    RecordSource,
    RecordType,
    RepetitiveLossStatus,
    Severity,
    StructureUse,
    SubstantialStatus,
    ViolationStatus,
    ViolationType,
)

_ISO_UTC_MILLIS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# --------------------------------------------------------------------------
# Generic shape helpers
# --------------------------------------------------------------------------

def assert_identity_fields(data: dict, entity_name: str = "resource") -> None:
    """Every persisted resource carries a server-minted UUID id and created_at."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a UUID with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 timestamp, got {data.get('created_at')!r}"
    )


def assert_audit_fields(data: dict, entity_name: str = "resource",
                        expected_version: int = None) -> None:
    """Resources other than the ledger carry updated_at and version too."""
    assert_identity_fields(data, entity_name)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity_name}.version must be an integer, got {data.get('version')!r}"
    )
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected {entity_name}.version {expected_version}, got {data['version']}"
        )


def assert_utc_millis_timestamp(value: str, label: str = "timestamp") -> None:
    """ISO 8601 UTC timestamp with three fractional digits."""
    assert isinstance(value, str) and _ISO_UTC_MILLIS.match(value), (
        f"{label} must be an ISO 8601 UTC timestamp with three fractional digits, got {value!r}"
    )


def assert_one_decimal_place(value, label: str = "elevation") -> None:
    """Derived elevations are rounded to exactly 1 decimal place."""
    assert value is not None, f"{label} must not be null"
    assert round(float(value), 1) == float(value), (
        f"{label} must carry at most 1 decimal place, got {value!r}"
    )


def assert_two_decimal_places(value, label: str = "ratio") -> None:
    """Ratios and percentages are rounded to exactly 2 decimal places."""
    assert value is not None, f"{label} must not be null"
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most 2 decimal places, got {value!r}"
    )


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant the API emitted."""
    assert isinstance(value, str), f"Expected an ISO 8601 string, got {value!r}"
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_days_after(later: str, earlier: str, days: int, label: str = "deadline") -> None:
    """`later` must be exactly `days` days after `earlier` (exact day arithmetic)."""
    delta = parse_instant(later) - parse_instant(earlier)
    assert delta == timedelta(days=days), (
        f"{label}: expected exactly {days} days after {earlier}, got {later} (delta {delta})"
    )


def assert_calendar_years_after(later: str, earlier: str, years: int,
                                label: str = "deadline") -> None:
    """`later` must be `years` calendar years after `earlier`, 29 February
    clamping to 28 February when the target year has no leap day."""
    start = parse_instant(earlier)
    month, day = start.month, start.day
    if month == 2 and day == 29:
        target_year = start.year + years
        is_leap = (target_year % 4 == 0 and target_year % 100 != 0) or target_year % 400 == 0
        if not is_leap:
            day = 28
    expected = start.replace(year=start.year + years, month=month, day=day)
    actual = parse_instant(later)
    assert actual == expected, (
        f"{label}: expected {years} calendar years after {earlier} "
        f"({expected.isoformat()}), got {later}"
    )


# --------------------------------------------------------------------------
# Entity assertions
# --------------------------------------------------------------------------

def assert_community(data: dict) -> None:
    assert_audit_fields(data, "Community")
    assert isinstance(data["name"], str) and data["name"]
    assert re.fullmatch(r"[A-Z]{2}", data["state_code"]), (
        f"state_code must be exactly two uppercase letters, got {data['state_code']!r}"
    )
    assert isinstance(data["cid_number"], str) and data["cid_number"]
    assert 0.0 <= float(data["freeboard_ft"]) <= 6.0, (
        f"freeboard_ft must lie between 0.0 and 6.0 inclusive, got {data['freeboard_ft']}"
    )
    assert 0 <= int(data["cumulative_period_years"]) <= 25
    assert is_iso8601_timestamp(data["standards_adopted_at"])
    assert isinstance(data["sanction_risk_points"], int) and data["sanction_risk_points"] >= 0
    assert data["compliance_posture"] in [e.value for e in CompliancePosture]
    assert isinstance(data["crs_credit_points_claimed"], int)
    assert isinstance(data["crs_credit_points_verified"], int)
    assert isinstance(data["crs_class"], int) and 1 <= data["crs_class"] <= 10


def assert_firm_panel(data: dict) -> None:
    assert_audit_fields(data, "FirmPanel")
    assert isinstance(data["community_id"], str)
    assert isinstance(data["panel_number"], str) and data["panel_number"]
    assert isinstance(data["suffix"], str) and data["suffix"]
    assert data["flood_zone"] in [e.value for e in FloodZone]
    assert data["status"] in [e.value for e in FirmPanelStatus]
    assert "base_flood_elevation_ft" in data
    assert "effective_date" in data
    assert "supersedes_panel_id" in data


def assert_property(data: dict) -> None:
    assert_audit_fields(data, "Property")
    assert isinstance(data["community_id"], str)
    assert isinstance(data["firm_panel_id"], str)
    assert isinstance(data["parcel_id"], str) and data["parcel_id"]
    assert isinstance(data["mapped_area_code"], str)
    assert isinstance(data["owner_name"], str)
    assert isinstance(data["owner_email"], str)
    assert "repetitive_loss_area_id" in data
    assert isinstance(data["qualifying_claim_count"], int)
    assert isinstance(data["max_window_claim_count"], int)
    assert float(data["cumulative_claim_paid_usd"]) >= 0
    assert data["repetitive_loss_status"] in [e.value for e in RepetitiveLossStatus]


def assert_structure(data: dict) -> None:
    assert_audit_fields(data, "Structure")
    assert isinstance(data["property_id"], str)
    assert data["structure_use"] in [e.value for e in StructureUse]
    assert isinstance(data["pre_firm"], bool)
    assert isinstance(data["construction_year"], int)
    assert float(data["market_value_usd"]) > 0, "market_value_usd must be strictly greater than 0"
    assert data["highest_adjacent_grade_ft"] is not None
    assert "lowest_floor_elevation_ft" in data
    assert data["compliance_status"] in [e.value for e in ComplianceStatus]
    assert data["substantial_status"] in [e.value for e in SubstantialStatus]
    assert "anchor_record_id" in data
    assert float(data["cumulative_counted_cost_usd"]) >= 0
    assert_two_decimal_places(data["cumulative_improvement_pct"], "cumulative_improvement_pct")
    assert_two_decimal_places(data["single_event_improvement_pct"], "single_event_improvement_pct")


def assert_permit(data: dict) -> None:
    assert_audit_fields(data, "DevelopmentPermit")
    assert isinstance(data["property_id"], str)
    assert isinstance(data["structure_id"], str)
    assert data["project_type"] in [e.value for e in ProjectType]
    assert float(data["declared_project_cost_usd"]) >= 0
    assert data["proposed_lowest_floor_elevation_ft"] is not None
    assert isinstance(data["floodproofing_requested"], bool)
    assert data["status"] in [e.value for e in PermitStatus]
    assert isinstance(data["revision_round"], int) and 0 <= data["revision_round"] <= 3
    assert "determined_zone" in data
    assert "determined_bfe_ft" in data
    assert "freeboard_applied_ft" in data
    assert "required_lowest_floor_elevation_ft" in data
    assert "si_determination_case_id" in data
    if data.get("required_lowest_floor_elevation_ft") is not None:
        assert_one_decimal_place(
            data["required_lowest_floor_elevation_ft"], "required_lowest_floor_elevation_ft"
        )


def assert_certificate(data: dict) -> None:
    assert_audit_fields(data, "ElevationCertificate")
    assert isinstance(data["permit_id"], str)
    assert isinstance(data["structure_id"], str)
    assert data["certificate_type"] in [e.value for e in CertificateType]
    assert data["datum"] in [e.value for e in Datum]
    assert data["measured_lowest_floor_ft"] is not None
    assert data["measured_bfe_ft"] is not None
    assert_one_decimal_place(data["normalized_lowest_floor_ft"], "normalized_lowest_floor_ft")
    assert_one_decimal_place(data["freeboard_margin_ft"], "freeboard_margin_ft")
    assert data["status"] in [e.value for e in CertificateStatus]
    assert isinstance(data["deficiency_codes"], list)


def assert_improvement_record(data: dict) -> None:
    """An ImprovementRecord is append-only: it carries id and created_at only,
    with no updated_at and no version field at all."""
    assert_identity_fields(data, "ImprovementRecord")
    assert "updated_at" not in data, "ImprovementRecord must not carry updated_at"
    assert "version" not in data, "ImprovementRecord must not carry a version field"
    assert isinstance(data["structure_id"], str)
    assert data["record_type"] in [e.value for e in RecordType]
    assert data["source"] in [e.value for e in RecordSource]
    assert "permit_id" in data
    assert "inspection_id" in data
    assert "event_date" in data
    assert float(data["cost_usd"]) >= 0
    assert data["market_value_at_event_usd"] is not None
    assert float(data["claim_paid_amount_usd"]) >= 0
    assert isinstance(data["is_code_compliance_only"], bool)
    assert isinstance(data["counted_in_cumulative"], bool)
    assert isinstance(data["reversed"], bool)
    assert_cost_precision(float(data["cost_usd"]))


def assert_determination_case(data: dict) -> None:
    assert_audit_fields(data, "DeterminationCase")
    assert isinstance(data["structure_id"], str)
    assert "anchor_record_id" in data
    assert data["method"] in [e.value for e in DeterminationMethod]
    assert data["trigger_source"] in [e.value for e in DeterminationTriggerSource]
    assert data["determination_type"] in [e.value for e in DeterminationType]
    assert float(data["threshold_pct"]) == 50.00
    assert data["status"] in [e.value for e in DeterminationCaseStatus]
    if data.get("outcome") is not None:
        assert data["outcome"] in [e.value for e in DeterminationOutcome]
    if data.get("computed_ratio_pct") is not None:
        assert_two_decimal_places(data["computed_ratio_pct"], "computed_ratio_pct")


def assert_inspection(data: dict) -> None:
    assert_audit_fields(data, "PostDisasterInspection")
    assert isinstance(data["structure_id"], str)
    assert isinstance(data["declaration_code"], str)
    assert data["disaster_event_date"] is not None
    assert data["deadline_at"] is not None
    assert data["status"] in [e.value for e in InspectionStatus]
    if data.get("damage_ratio_pct") is not None:
        assert_two_decimal_places(data["damage_ratio_pct"], "damage_ratio_pct")


def assert_violation(data: dict) -> None:
    assert_audit_fields(data, "Violation")
    assert isinstance(data["property_id"], str)
    assert "structure_id" in data
    assert "permit_id" in data
    assert data["violation_type"] in [e.value for e in ViolationType]
    assert data["severity"] in [e.value for e in Severity]
    assert data["status"] in [e.value for e in ViolationStatus]
    assert isinstance(data["sanction_points_contributed"], int)
    assert is_iso8601_timestamp(data["opened_at"])


def assert_remediation_order(data: dict) -> None:
    assert_audit_fields(data, "RemediationOrder")
    assert isinstance(data["violation_id"], str)
    assert isinstance(data["required_action"], str)
    assert data["deadline_at"] is not None
    assert isinstance(data["extension_count"], int) and 0 <= data["extension_count"] <= 2
    assert data["status"] in [e.value for e in OrderStatus]


def assert_loss_area(data: dict) -> None:
    assert_audit_fields(data, "RepetitiveLossArea")
    assert isinstance(data["community_id"], str)
    assert isinstance(data["area_code"], str)
    assert isinstance(data["boundary_description"], str)
    assert data["status"] in [e.value for e in LossAreaStatus]
    assert data["analysis_status"] in [e.value for e in AnalysisStatus]
    assert data["outreach_status"] in [e.value for e in OutreachStatus]
    assert isinstance(data["property_count"], int)
    assert isinstance(data["rl_property_count"], int)
    assert isinstance(data["target_property_count"], int)
    assert isinstance(data["delivered_count"], int)
    assert_two_decimal_places(data["coverage_pct"], "coverage_pct")


def assert_higher_standard(data: dict) -> None:
    assert_audit_fields(data, "HigherStandard")
    assert isinstance(data["community_id"], str)
    assert data["activity_code"] in [e.value for e in ActivityCode]
    assert isinstance(data["documentation_cycle_year"], int)
    assert isinstance(data["claimed_points"], int) and data["claimed_points"] >= 1
    assert isinstance(data["max_points_allowed"], int)
    assert isinstance(data["verified_points"], int)
    assert data["documentation_status"] in [e.value for e in DocumentationStatus]


def assert_crs_cycle(data: dict) -> None:
    assert_audit_fields(data, "CrsCycle")
    assert isinstance(data["community_id"], str)
    assert isinstance(data["cycle_year"], int)
    assert data["cycle_start_date"] is not None
    assert data["cycle_end_date"] is not None
    assert data["due_at"] is not None
    assert data["status"] in [e.value for e in CrsCycleStatus]
    assert isinstance(data["verification_visit_required"], bool)
    assert isinstance(data["total_claimed_points"], int)
    assert isinstance(data["total_verified_points"], int)


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------

def assert_ledger_aggregates(structure: dict, anchor_record_id, counted_cost_usd,
                             cumulative_pct, single_event_pct) -> None:
    """The four ledger aggregates the server recomputes from scratch."""
    assert structure["anchor_record_id"] == anchor_record_id, (
        f"Expected anchor_record_id {anchor_record_id}, got {structure['anchor_record_id']}"
    )
    assert float(structure["cumulative_counted_cost_usd"]) == counted_cost_usd, (
        f"Expected cumulative_counted_cost_usd {counted_cost_usd}, "
        f"got {structure['cumulative_counted_cost_usd']}"
    )
    assert float(structure["cumulative_improvement_pct"]) == cumulative_pct, (
        f"Expected cumulative_improvement_pct {cumulative_pct}, "
        f"got {structure['cumulative_improvement_pct']}"
    )
    assert float(structure["single_event_improvement_pct"]) == single_event_pct, (
        f"Expected single_event_improvement_pct {single_event_pct}, "
        f"got {structure['single_event_improvement_pct']}"
    )


def assert_sanction_state(community: dict, points: int, posture: str) -> None:
    """sanction_risk_points is the raw score minus the credit, floored at 0, and
    compliance_posture is the tier of that final value."""
    assert int(community["sanction_risk_points"]) == points, (
        f"Expected sanction_risk_points {points}, got {community['sanction_risk_points']}"
    )
    assert community["compliance_posture"] == posture, (
        f"Expected compliance_posture {posture}, got {community['compliance_posture']}"
    )


def assert_no_ledger_mutation(record_before: dict, record_after: dict) -> None:
    """A ledger record is never edited; only the derived `reversed` marker flips."""
    for field in ("id", "structure_id", "record_type", "source", "event_date",
                  "cost_usd", "market_value_at_event_usd", "claim_paid_amount_usd",
                  "is_code_compliance_only", "counted_in_cumulative", "created_at"):
        assert record_before.get(field) == record_after.get(field), (
            f"ImprovementRecord.{field} must not be rewritten: "
            f"{record_before.get(field)!r} -> {record_after.get(field)!r}"
        )
