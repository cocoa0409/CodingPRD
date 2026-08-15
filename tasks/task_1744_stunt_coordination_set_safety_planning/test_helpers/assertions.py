"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_mutable(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer starting at 1"
    )


def _assert_common_immutable(data: dict, entity_label: str):
    """Immutable records (Certification, Inspection) carry only id + created_at
    of the common fields — neither updated_at nor version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity_label} must not carry updated_at"
    assert "version" not in data, f"{entity_label} must not carry version"


def assert_production(data: dict):
    _assert_common_mutable(data, "Production")
    assert data["posture"] in ["SETUP", "ACTIVE", "STOPPED", "WRAPPED"]
    assert data["insurance_status"] in ["UNFILED", "FILED", "ACKNOWLEDGED"]
    assert isinstance(data["total_budget_cents"], int)
    assert isinstance(data["committed_pay_cents"], int)


def assert_sequence(data: dict):
    _assert_common_mutable(data, "StuntSequence")
    assert data["status"] in [
        "DRAFT", "DESIGN_LOCKED", "READY", "SAFETY_HOLD", "EXECUTED", "REVIEWED", "CANCELLED",
    ]
    assert data["hazard_class"] in ["FIRE", "HEIGHT", "VEHICLE", "WATER", "PYRO", "AERIAL", "FIGHT"]
    assert data["risk_category"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert isinstance(data["design_revision"], int) and data["design_revision"] >= 1
    assert isinstance(data["completed_rehearsal_count"], int)
    assert isinstance(data["completed_rehearsal_minutes"], int)


def assert_risk_assessment(data: dict):
    _assert_common_mutable(data, "RiskAssessment")
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"]
    assert 1 <= data["severity_rating"] <= 5
    assert 1 <= data["likelihood_rating"] <= 5
    assert isinstance(data["screening_score"], int)


def assert_performer(data: dict):
    _assert_common_mutable(data, "StuntPerformer")
    assert data["status"] in ["REGISTERED", "QUALIFIED", "SUSPENDED"]
    assert data["union_status"] in ["SAG_AFTRA", "NON_UNION"]
    assert isinstance(data["completed_rehearsal_minutes"], int)


def assert_certification(data: dict):
    _assert_common_immutable(data, "Certification")
    assert data["discipline"] in ["FIRE", "HEIGHT", "VEHICLE", "WATER", "PYRO", "AERIAL", "FIGHT"]
    assert data["level"] in ["BASIC", "ADVANCED", "MASTER"]
    assert data["revoked"] in (True, False)


def assert_rehearsal(data: dict):
    _assert_common_mutable(data, "Rehearsal")
    assert data["status"] in ["SCHEDULED", "COMPLETED", "MISSED", "CANCELLED", "VOIDED"]
    assert isinstance(data["duration_minutes"], int)


def assert_safety_meeting(data: dict):
    _assert_common_mutable(data, "SafetyMeeting")
    assert data["status"] in ["SCHEDULED", "IN_SESSION", "COMPLETED", "ADJOURNED"]
    assert isinstance(data["design_revision"], int) and data["design_revision"] >= 1


def assert_signoff(data: dict):
    _assert_common_mutable(data, "DepartmentSignoff")
    assert data["status"] in ["PENDING", "SIGNED", "SIGNED_WITH_CONDITIONS", "REFUSED"]
    assert data["department"] in ["CAMERA", "ELECTRIC", "GRIP", "STUNTS", "MEDIC", "FIRE_SAFETY"]


def assert_equipment(data: dict):
    _assert_common_mutable(data, "EquipmentItem")
    assert data["status"] in ["IN_SERVICE", "QUARANTINED", "RETIRED"]
    assert data["equipment_type"] in ["RIGGING", "PYRO_DEVICE", "VEHICLE", "HARNESS", "AIRBAG", "CRANE"]
    assert data["inspection_current"] in (True, False)


def assert_inspection(data: dict):
    _assert_common_immutable(data, "Inspection")
    assert data["outcome"] in ["PASSED", "CONDITIONAL", "FAILED"]
    assert is_iso8601_timestamp(data.get("inspected_at", "")), "inspected_at must be ISO 8601"


def assert_permit(data: dict):
    _assert_common_mutable(data, "Permit")
    assert data["status"] in ["APPLIED", "GRANTED", "DENIED", "REVOKED"]
    assert data["permit_type"] in [
        "PYROTECHNICS", "CRANE_OPERATION", "AERIAL_WORK", "FIRE_EFFECTS", "WATER_WORK",
    ]


def assert_pay_adjustment(data: dict):
    _assert_common_mutable(data, "PayAdjustment")
    assert data["status"] in ["PROPOSED", "COUNTERED", "AGREED", "WITHDRAWN", "EXPIRED", "VOIDED"]
    assert data["adjustment_type"] in ["HAZARD_BUMP", "STUNT_DOUBLE"]
    assert data["proposer_by"] in ["PERFORMER", "COORDINATOR"]
    assert data["last_offer_by"] in ["PERFORMER", "COORDINATOR"]
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    assert isinstance(data["provisional_estimate_cents"], int)


def assert_incident(data: dict):
    _assert_common_mutable(data, "Incident")
    assert data["status"] in ["REPORTED", "UNDER_INVESTIGATION", "CLOSED"]
    assert data["severity"] in ["NEAR_MISS", "MINOR", "SERIOUS", "CRITICAL"]


def assert_execution(data: dict):
    _assert_common_mutable(data, "StuntExecution")
    assert data["status"] in ["ATTEMPTED", "COMPLETED", "ABORTED"]
    assert isinstance(data["take_number"], int) and data["take_number"] >= 1


def assert_review(data: dict):
    _assert_common_mutable(data, "PostStuntReview")
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_committed_pay_invariant(production: dict, agreed_adjustments: list):
    """Invariant I1 (PRD §3.7): committed_pay_cents equals the sum of
    final_amount_cents over exactly the production's AGREED pay adjustments."""
    expected = sum(a["final_amount_cents"] for a in agreed_adjustments if a["status"] == "AGREED")
    assert production["committed_pay_cents"] == expected, (
        f"committed_pay_cents {production['committed_pay_cents']} != sum of AGREED finals {expected}"
    )
