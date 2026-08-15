"""Entity assertions and domain invariant checkers (PRD sections 2.2-2.4, 3.x)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ChangeOrderStatus,
    CommentSeverity,
    CommentStatus,
    ContractorStatus,
    DrawStatus,
    EngagementStatus,
    InvoiceStatus,
    LeaseSpaceStatus,
    LeaseStatus,
    MilestoneStatus,
    MilestoneWorkType,
    PunchItemStatus,
    PunchSeverity,
    TIProjectPosture,
    TIProjectStatus,
    WaiverStatus,
    WaiverType,
    WorkDelineation,
    WorkLetterStatus,
    PlanSubmissionStatus,
    AbatementBasis,
    DelayResponsibility,
)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating 'Z' vs '+00:00' rendering."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_enum(value, enum_cls, field):
    members = [m.value for m in enum_cls]
    assert value in members, f"{field} must be one of {members}, got {value!r}"


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address"], str) and data["address"]
    cap = data["max_concurrent_construction_projects"]
    assert isinstance(cap, int) and cap >= 1, f"capacity cap must be an integer >= 1, got {cap!r}"


def assert_lease_space(data: dict):
    _assert_common(data)
    assert isinstance(data["property_id"], str) and data["property_id"]
    assert isinstance(data["suite_number"], str) and data["suite_number"]
    assert isinstance(data["floor"], int)
    assert isinstance(data["rentable_sqft"], int) and data["rentable_sqft"] > 0
    _assert_enum(data["status"], LeaseSpaceStatus, "status")


def assert_tenant(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["tax_id"], str) and data["tax_id"]


def assert_lease(data: dict):
    _assert_common(data)
    assert isinstance(data["space_id"], str) and data["space_id"]
    assert isinstance(data["tenant_id"], str) and data["tenant_id"]
    assert isinstance(data["base_rent_annual_cents"], int) and data["base_rent_annual_cents"] > 0
    assert is_iso8601_timestamp(data["scheduled_rent_commencement_date"])
    _assert_enum(data["abatement_basis"], AbatementBasis, "abatement_basis")
    _assert_enum(data["delay_responsibility"], DelayResponsibility, "delay_responsibility")
    assert isinstance(data["rent_abatement_credit_cents"], int)
    assert isinstance(data["lease_term_months"], int) and data["lease_term_months"] > 0
    _assert_enum(data["status"], LeaseStatus, "status")


def assert_ti_project(data: dict):
    _assert_common(data)
    assert isinstance(data["lease_id"], str) and data["lease_id"]
    assert isinstance(data["project_name"], str) and data["project_name"]
    assert isinstance(data["base_contract_cents"], int) and data["base_contract_cents"] >= 0
    assert isinstance(data["allowance_total_cents"], int)
    _assert_enum(data["status"], TIProjectStatus, "status")
    _assert_enum(data["posture"], TIProjectPosture, "posture")
    for field in (
        "total_cost_cents",
        "allowance_consumed_cents",
        "provisional_allowance_consumed_cents",
        "allowance_remaining_cents",
        "overage_cents",
        "retainage_held_cents",
        "retainage_released_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents, got {data.get(field)!r}"


def assert_work_letter(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert isinstance(data["scope_description"], str)
    assert isinstance(data["allowance_offer_cents"], int) and data["allowance_offer_cents"] >= 0
    _assert_enum(data["work_delineation"], WorkDelineation, "work_delineation")
    assert isinstance(data["round_number"], int) and data["round_number"] >= 0
    _assert_enum(data["status"], WorkLetterStatus, "status")


def assert_plan_submission(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert isinstance(data["drawing_set_ref"], str) and data["drawing_set_ref"]
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0
    assert is_iso8601_timestamp(data["submitted_at"])
    _assert_enum(data["status"], PlanSubmissionStatus, "status")


def assert_review_comment(data: dict):
    _assert_common(data)
    assert isinstance(data["submission_id"], str) and data["submission_id"]
    assert isinstance(data["comment_text"], str)
    _assert_enum(data["severity"], CommentSeverity, "severity")
    _assert_enum(data["status"], CommentStatus, "status")


def assert_contractor(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert is_iso8601_timestamp(data["insurance_expiry_date"])
    _assert_enum(data["qualification_status"], ContractorStatus, "qualification_status")


def assert_engagement(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["contractor_id"], str) and data["contractor_id"]
    assert isinstance(data["building_rules_acknowledged"], bool)
    _assert_enum(data["status"], EngagementStatus, "status")


def assert_milestone(data: dict):
    _assert_common(data)
    assert isinstance(data["engagement_id"], str) and data["engagement_id"]
    assert isinstance(data["milestone_name"], str) and data["milestone_name"]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    _assert_enum(data["work_type"], MilestoneWorkType, "work_type")
    _assert_enum(data["status"], MilestoneStatus, "status")


def assert_change_order(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["co_number"], int) and data["co_number"] >= 1
    assert isinstance(data["description"], str)
    assert isinstance(data["lines"], list)
    _assert_enum(data["status"], ChangeOrderStatus, "status")


def assert_draw(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["draw_number"], int) and data["draw_number"] >= 1
    assert is_iso8601_timestamp(data["period_end_date"])
    assert isinstance(data["requested_amount_cents"], int) and data["requested_amount_cents"] > 0
    assert isinstance(data["is_final_draw"], bool)
    _assert_enum(data["status"], DrawStatus, "status")


def assert_lien_waiver(data: dict):
    _assert_common(data)
    assert isinstance(data["disbursement_id"], str) and data["disbursement_id"]
    assert isinstance(data["contractor_id"], str) and data["contractor_id"]
    _assert_enum(data["waiver_type"], WaiverType, "waiver_type")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    _assert_enum(data["status"], WaiverStatus, "status")


def assert_punch_item(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["assigned_engagement_id"], str) and data["assigned_engagement_id"]
    assert isinstance(data["description"], str)
    assert isinstance(data["location"], str)
    _assert_enum(data["severity"], PunchSeverity, "severity")
    _assert_enum(data["status"], PunchItemStatus, "status")


def assert_overage_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str) and data["project_id"]
    assert isinstance(data["invoice_number"], int) and data["invoice_number"] >= 1
    assert isinstance(data["line_total_cents"], int)
    _assert_enum(data["status"], InvoiceStatus, "status")


def assert_project_allowance_invariants(project: dict):
    """PRD 3.6: the allowance pool split is conserved — consumed + remaining == total."""
    total = project["allowance_total_cents"]
    assert project["allowance_consumed_cents"] + project["allowance_remaining_cents"] == total, (
        f"consumed {project['allowance_consumed_cents']} + remaining "
        f"{project['allowance_remaining_cents']} != total {total}"
    )
    assert project["allowance_remaining_cents"] >= 0
    # Posture derivation per PRD 3.6.
    if total > 0 and project["allowance_consumed_cents"] >= total:
        assert project["posture"] == "ALLOWANCE_EXHAUSTED"


def assert_project_retainage_invariants(project: dict):
    """PRD 3.6: retainage escrow is never negative and released only via final draw pay."""
    assert project["retainage_held_cents"] >= 0
    assert project["retainage_released_cents"] >= 0


def assert_project_overage_invariants(project: dict):
    """PRD 3.5: overage is the amount total cost exceeds the allowance, never below zero."""
    expected = max(0, project["total_cost_cents"] - project["allowance_total_cents"])
    assert project["overage_cents"] == expected, (
        f"overage_cents {project['overage_cents']} != max(0, total_cost "
        f"{project['total_cost_cents']} - allowance {project['allowance_total_cents']})"
    )
