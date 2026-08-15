"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    """The twelve primary resources share id/created_at/updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_project(data: dict):
    _assert_common_fields(data, "Project")
    assert isinstance(data["project_name"], str) and data["project_name"]
    assert data["posture"] in ["SETUP", "ACTIVE", "SUSPENDED", "CLOSEOUT", "CLOSED"]
    for field in (
        "rfi_response_days",
        "ack_required_days",
        "mobilization_buffer_days",
        "long_lead_threshold_days",
        "expedite_window_days",
        "initial_contingency_cents",
        "contingency_reserved_cents",
        "contingency_spent_cents",
        "contingency_available_cents",
        "gc_tier_threshold_cents",
        "ops_scan_index",
    ):
        assert isinstance(data[field], int), f"Project.{field} must be an integer"
    assert isinstance(data["holiday_dates"], list), "Project.holiday_dates must be a list"


def assert_spec_section(data: dict):
    _assert_common_fields(data, "SpecSection")
    assert isinstance(data["section_number"], str) and data["section_number"]
    assert data["status"] in ["DRAFT", "ACTIVE", "LOCKED"]
    assert data["required_discipline"] in ["ARCH", "STRUCT", "MEP", "CIVIL"]
    assert isinstance(data["required_submittal_kinds"], list)


def assert_subcontractor(data: dict):
    _assert_common_fields(data, "Subcontractor")
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert data["standing"] in ["GOOD", "WATCH", "SUSPENDED"]
    assert isinstance(data["late_ack_count"], int) and data["late_ack_count"] >= 0


def assert_reviewer(data: dict):
    _assert_common_fields(data, "Reviewer")
    assert data["discipline"] in ["ARCH", "STRUCT", "MEP", "CIVIL"]
    assert data["reviewer_status"] in ["ACTIVE", "INACTIVE"]
    assert isinstance(data["open_review_count"], int) and data["open_review_count"] >= 0
    assert isinstance(data["review_capacity"], int) and data["review_capacity"] >= 1


def assert_submittal(data: dict):
    _assert_common_fields(data, "Submittal")
    assert data["submittal_kind"] in [
        "PRODUCT_DATA",
        "SHOP_DRAWINGS",
        "SAMPLES",
        "MOCKUP",
        "CERTIFICATES",
        "O_AND_M_MANUALS",
    ]
    assert isinstance(data["item_number"], str) and data["item_number"]
    assert data["review_status"] in [
        "REGISTERED",
        "IN_REVIEW",
        "RETURNED_NEEDS_RESUBMIT",
        "APPROVED",
        "RELEASED",
        "DISTRIBUTED",
        "CLOSED",
        "VOID",
    ]
    assert data["expediting_status"] in [
        "NOT_REQUIRED",
        "MONITORING",
        "EXPEDITING",
        "ESCALATED",
        "CLEAR",
    ]
    assert data["deferral_status"] in ["NONE", "DEFERRAL_REQUESTED", "DEFERRED_APPROVED"]
    assert isinstance(data["is_long_lead"], bool)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_revision(data: dict):
    _assert_common_fields(data, "SubmittalRevision")
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "RETURNED", "SUPERSEDED"]
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 0
    if data.get("action_code") is not None:
        assert data["action_code"] in ["A", "B", "C", "D"]


def assert_long_lead_item(data: dict):
    _assert_common_fields(data, "LongLeadItem")
    assert data["status"] in [
        "IDENTIFIED",
        "QUOTED",
        "PO_ISSUED",
        "IN_PRODUCTION",
        "SHIPPED",
        "DELIVERED",
        "CANCELLED",
    ]
    assert data["criticality"] in ["CRITICAL", "HIGH", "STANDARD"]
    assert isinstance(data["days_late"], int) and data["days_late"] >= 0
    assert data["escalation_level"] in [0, 1, 2, 3]
    assert isinstance(data["priority_score"], int)
    assert 0 <= data["priority_score"] <= 100, "priority_score is clamped to [0, 100]"


def assert_rfi(data: dict):
    _assert_common_fields(data, "RFI")
    assert data["status"] in ["OPEN", "ROUTED", "ANSWERED", "CLOSED", "VOID"]
    assert data["priority"] in ["LOW", "NORMAL", "HIGH", "CRITICAL"]
    assert data["required_discipline"] in ["ARCH", "STRUCT", "MEP", "CIVIL"]
    assert isinstance(data["rfi_number"], str) and data["rfi_number"].startswith("RFI-")
    assert isinstance(data["cycle_count"], int) and data["cycle_count"] >= 0
    assert isinstance(data["is_overdue"], bool)
    assert isinstance(data["is_late_answer"], bool)


def assert_impact_assessment(data: dict):
    _assert_common_fields(data, "ImpactAssessment")
    assert data["status"] in ["ESTIMATED", "PRICED", "ACCEPTED", "DISPUTED", "WAIVED"]
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["provisional_delta_cents"], int)
    assert isinstance(data["price_cycle"], int) and data["price_cycle"] >= 0
    if data.get("final_delta_cents") is not None:
        assert isinstance(data["final_delta_cents"], int)
    if data.get("gc_markup_tier") is not None:
        assert data["gc_markup_tier"] in [1, 2]


def assert_distribution_record(data: dict):
    _assert_common_fields(data, "DistributionRecord")
    assert data["status"] in ["QUEUED", "SENT", "ACKNOWLEDGED"]
    assert data["source_type"] in ["RFI", "SUBMITTAL"]
    assert isinstance(data["is_overdue"], bool)


def assert_installation_activity(data: dict):
    _assert_common_fields(data, "InstallationActivity")
    assert data["status"] in ["PLANNED", "RELEASED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["shift_applied_days"], int) and data["shift_applied_days"] >= 0


def assert_owner_report(data: dict):
    _assert_common_fields(data, "OwnerReport")
    assert data["status"] in ["DRAFT", "PUBLISHED", "SUPERSEDED"]


def assert_escalation_event(data: dict):
    """Append-only log entries carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "EscalationEvent.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "EscalationEvent.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "EscalationEvent must not carry updated_at"
    assert "version" not in data, "EscalationEvent must not carry version"
    assert data["event_type"] in [
        "RFI_OVERDUE",
        "LLI_ESCALATION_RAISED",
        "LLI_ESCALATION_CLEARED",
        "DIST_ACK_OVERDUE",
        "SUBCONTRACTOR_WATCH",
        "SUBCONTRACTOR_SUSPENDED",
    ]
    assert data["source_type"] in [
        "RFI",
        "LONG_LEAD_ITEM",
        "DISTRIBUTION_RECORD",
        "SUBCONTRACTOR",
    ]


def assert_contingency_conserved(project: dict):
    """PRD §2.7: available + reserved + spent == initial at all times."""
    total = (
        project["contingency_available_cents"]
        + project["contingency_reserved_cents"]
        + project["contingency_spent_cents"]
    )
    assert total == project["initial_contingency_cents"], (
        f"Contingency conservation violated: "
        f"{project['contingency_available_cents']} + "
        f"{project['contingency_reserved_cents']} + "
        f"{project['contingency_spent_cents']} != "
        f"{project['initial_contingency_cents']}"
    )
