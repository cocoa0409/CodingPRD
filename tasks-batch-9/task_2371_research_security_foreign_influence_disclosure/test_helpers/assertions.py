"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    BLOCKER_ORDER,
    SCORE_MAX,
    SCORE_MIN,
)
from .types import (
    ActivationBlocker,
    AgencyCode,
    AppointmentType,
    AwardStatus,
    CompletenessTier,
    ControlledAreaPosture,
    CourseCode,
    Designation,
    DeviceRequirementTier,
    DisclosurePosture,
    DisclosureType,
    DocumentType,
    GrantStatus,
    GrantStatusReason,
    IncidentFinding,
    IncidentSeverity,
    IncidentStatus,
    IncidentType,
    ItemSource,
    ItemStatus,
    ItemType,
    OrgType,
    PersonnelRole,
    PersonnelStatus,
    PlanStatus,
    ReconcileVariant,
    ReconcileVerdict,
    ReviewStatus,
    ScreeningVariant,
    SecurityStatus,
    SecurityStatusReason,
    SensitivityLevel,
    StatementStatus,
    SubawardStatus,
    TrainingStatus,
    TravelPurpose,
    TravelStatus,
)


def _members(enum_cls) -> list:
    return [m.value for m in enum_cls]


def assert_common_fields(data: dict) -> None:
    """Every record carries a bare UUID id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1 or above, got {data['version']}"


def _assert_enum(data: dict, field: str, enum_cls) -> None:
    allowed = _members(enum_cls)
    assert data.get(field) in allowed, (
        f"{field} must be one of {allowed}, got {data.get(field)!r}"
    )


# --------------------------------------------------------------------------- #
# Per-entity assertions
# --------------------------------------------------------------------------- #

def assert_investigator(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"], "full_name required"
    assert isinstance(data["email"], str) and "@" in data["email"], "email required"
    assert isinstance(data["home_department"], str) and data["home_department"]
    _assert_enum(data, "appointment_type", AppointmentType)
    _assert_enum(data, "disclosure_posture", DisclosurePosture)
    assert 0 <= data["institutional_base_effort_pct"] <= 100
    assert SCORE_MIN <= data["risk_score"] <= SCORE_MAX, (
        f"risk_score must stay within {SCORE_MIN}..{SCORE_MAX}, got {data['risk_score']}"
    )
    assert isinstance(data["training_compliant"], bool)
    assert data["substantiated_incident_count"] >= 0
    assert data["material_discrepancy_count"] >= 0


def assert_foreign_organization(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    code = data["country_code"]
    assert isinstance(code, str) and len(code) == 2 and code.isupper(), (
        f"country_code must be two uppercase letters, got {code!r}"
    )
    _assert_enum(data, "org_type", OrgType)
    _assert_enum(data, "own_designation", Designation)
    _assert_enum(data, "effective_designation", Designation)
    assert data["effective_designation_depth"] >= 0
    assert 0 <= data["parent_ownership_pct"] <= 100


def assert_project(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    _assert_enum(data, "agency_code", AgencyCode)
    _assert_enum(data, "sensitivity_level", SensitivityLevel)
    _assert_enum(data, "award_status", AwardStatus)
    _assert_enum(data, "security_status", SecurityStatus)
    _assert_enum(data, "security_status_reason", SecurityStatusReason)
    _assert_enum(data, "controlled_area_posture", ControlledAreaPosture)
    assert data["award_amount_cents"] >= 0
    assert data["controlled_area_capacity"] >= 0
    assert data["active_grant_count"] >= 0
    assert data["open_incident_count"] >= 0
    assert isinstance(data["activation_blockers"], list)
    assert_activation_blockers_ordered(data["activation_blockers"])


def assert_project_personnel(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["investigator_id"])
    _assert_enum(data, "role_on_project", PersonnelRole)
    _assert_enum(data, "status", PersonnelStatus)
    assert 0 < data["committed_person_months"] <= 12


def assert_disclosure(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["investigator_id"])
    assert isinstance(data["cycle_label"], str) and data["cycle_label"]
    _assert_enum(data, "disclosure_type", DisclosureType)
    _assert_enum(data, "review_status", ReviewStatus)
    _assert_enum(data, "plan_status", PlanStatus)
    _assert_enum(data, "completeness_tier", CompletenessTier)
    assert 0 <= data["completeness_score"] <= 100
    assert data["revision_round"] >= 0
    assert data["item_count"] >= 0
    assert data["late_item_count"] >= 0
    assert data["undisclosed_item_count"] >= 0


def assert_disclosure_item(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["disclosure_id"])
    assert is_valid_uuid(data["foreign_organization_id"])
    _assert_enum(data, "item_type", ItemType)
    _assert_enum(data, "status", ItemStatus)
    _assert_enum(data, "source", ItemSource)
    assert 0 <= data["annual_effort_hours"] <= 2080
    assert data["compensation_usd_cents"] >= 0
    assert data["in_kind_value_cents"] >= 0
    assert isinstance(data["is_paid"], bool)
    assert data["item_risk_points"] >= 0


def assert_support_statement(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["investigator_id"])
    assert is_valid_uuid(data["project_id"])
    _assert_enum(data, "agency_code", AgencyCode)
    _assert_enum(data, "document_type", DocumentType)
    _assert_enum(data, "status", StatementStatus)
    assert data["declared_person_months"] >= 0
    assert data["declared_appointment_count"] >= 0
    assert data["declared_support_count"] >= 0
    if data.get("applied_variant") is not None:
        _assert_enum(data, "applied_variant", ReconcileVariant)
    if data.get("verdict") is not None:
        _assert_enum(data, "verdict", ReconcileVerdict)


def assert_travel_registration(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["investigator_id"])
    code = data["destination_country_code"]
    assert isinstance(code, str) and len(code) == 2 and code.isupper()
    _assert_enum(data, "purpose", TravelPurpose)
    _assert_enum(data, "status", TravelStatus)
    _assert_enum(data, "device_requirement_tier", DeviceRequirementTier)
    assert 0 <= data["risk_flag_count"] <= 4, (
        f"risk_flag_count must stay within 0..4, got {data['risk_flag_count']}"
    )
    assert isinstance(data["briefing_required"], bool)
    assert isinstance(data["carries_institutional_device"], bool)
    assert data["depart_on"] <= data["return_on"], "return_on must not precede depart_on"


def assert_access_grant(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["investigator_id"])
    _assert_enum(data, "status", GrantStatus)
    _assert_enum(data, "status_reason", GrantStatusReason)
    assert data["valid_until"] > data["valid_from"], (
        "valid_until must be strictly after valid_from"
    )
    assert data["peak_concurrency_at_request"] >= 0


def assert_security_incident(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["investigator_id"])
    _assert_enum(data, "incident_type", IncidentType)
    _assert_enum(data, "status", IncidentStatus)
    _assert_enum(data, "finding", IncidentFinding)
    assert isinstance(data["summary"], str) and data["summary"]
    if data.get("severity") is not None:
        _assert_enum(data, "severity", IncidentSeverity)
    if data.get("severity_points") is not None:
        assert data["severity_points"] >= 0
    assert isinstance(data["notified_late"], bool)


def assert_training_assignment(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["investigator_id"])
    _assert_enum(data, "course_code", CourseCode)
    _assert_enum(data, "status", TrainingStatus)
    assert is_iso8601_timestamp(data["assigned_on"])
    assert is_iso8601_timestamp(data["due_on"])


def assert_subaward(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["organization_id"])
    assert isinstance(data["scope"], str) and data["scope"]
    assert data["amount_cents"] > 0
    _assert_enum(data, "status", SubawardStatus)
    if data.get("applied_screening_variant") is not None:
        _assert_enum(data, "applied_screening_variant", ScreeningVariant)
    if data.get("screening_designation") is not None:
        _assert_enum(data, "screening_designation", Designation)


# --------------------------------------------------------------------------- #
# Domain invariant checkers
# --------------------------------------------------------------------------- #

def assert_activation_blockers_ordered(blockers: list) -> None:
    """Blockers are reported in the published fixed order, never discovery order."""
    for code in blockers:
        assert code in BLOCKER_ORDER, f"unknown activation blocker {code!r}"
    positions = [BLOCKER_ORDER.index(code) for code in blockers]
    assert positions == sorted(positions), (
        f"activation_blockers must follow {BLOCKER_ORDER}, got {blockers}"
    )
    assert len(set(blockers)) == len(blockers), f"duplicate blockers in {blockers}"


def assert_commitment_totals_consistent(investigator: dict) -> None:
    """total_commitment_pct is the sum of three already-rounded components."""
    expected = (
        investigator["institutional_base_effort_pct"]
        + investigator["committed_effort_pct"]
        + investigator["outside_effort_pct"]
    )
    assert abs(investigator["total_commitment_pct"] - expected) < 1e-9, (
        "total_commitment_pct must equal institutional_base_effort_pct + "
        f"committed_effort_pct + outside_effort_pct; expected {expected}, "
        f"got {investigator['total_commitment_pct']}"
    )
    expected_over = max(0.0, round(investigator["total_commitment_pct"] - 100, 2))
    assert abs(investigator["overcommitment_pct"] - expected_over) < 1e-9, (
        f"overcommitment_pct expected {expected_over}, "
        f"got {investigator['overcommitment_pct']}"
    )


def assert_two_decimal_places(value, label: str = "value") -> None:
    """Percentages and person-month figures are carried to two decimal places."""
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most two decimal places, got {value}"
    )


def assert_version_advanced(before: dict, after: dict, label: str = "record") -> None:
    """A mutation -- including a derived-field recomputation -- bumps version."""
    assert after["version"] > before["version"], (
        f"{label} version must advance past {before['version']}, got {after['version']}"
    )


def assert_version_unchanged(before: dict, after: dict, label: str = "record") -> None:
    assert after["version"] == before["version"], (
        f"{label} version must stay at {before['version']}, got {after['version']}"
    )


def assert_no_blockers(project: dict) -> None:
    assert project["activation_blockers"] == [], (
        f"expected an empty blocker list, got {project['activation_blockers']}"
    )


def assert_blocker_present(project: dict, blocker: str) -> None:
    assert blocker in project["activation_blockers"], (
        f"expected {blocker} in activation_blockers, "
        f"got {project['activation_blockers']}"
    )
    assert blocker in _members(ActivationBlocker)
