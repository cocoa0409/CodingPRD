"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_property(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["owner_user_id"], str) and data["owner_user_id"]
    assert isinstance(data["address_line"], str) and data["address_line"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data.get("has_existing_shaft"), bool)


def assert_survey(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert is_valid_uuid(data.get("property_id", ""))
    assert is_valid_uuid(data.get("surveyor_technician_id", ""))
    if data["status"] == "COMPLETED":
        assert data["feasibility_verdict"] in ("FEASIBLE", "CONDITIONAL", "INFEASIBLE")


def assert_product_model(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert data["drive_type"] in ("HYDRAULIC", "TRACTION", "PNEUMATIC", "PLATFORM_LIFT")
    assert_cost_precision(data["base_price"])
    assert_cost_precision(data["install_labor_price"])


def assert_technician(data: dict):
    _assert_common_fields(data)
    assert data["certification"] in ("CET", "QEI", "CET_AND_QEI")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_contractor(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_project(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "QUOTED", "PERMIT_IN_PROGRESS", "PERMIT_APPROVED",
        "STRUCTURAL_IN_PROGRESS", "READY_FOR_INSTALL", "INSTALL_SCHEDULED",
        "INSTALL_COMPLETE", "AWAITING_REGISTRATION", "REGISTERED",
        "CLOSED", "CANCELLED",
    )
    assert data["project_type"] in ("NEW_INSTALLATION", "MODERNIZATION")
    if data["status"] in ("QUOTED", "PERMIT_IN_PROGRESS", "PERMIT_APPROVED",
                          "STRUCTURAL_IN_PROGRESS", "READY_FOR_INSTALL",
                          "INSTALL_SCHEDULED", "INSTALL_COMPLETE",
                          "AWAITING_REGISTRATION", "REGISTERED", "CLOSED"):
        assert_cost_precision(data["contract_price"])


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "UNDER_REVIEW", "CORRECTIONS_REQUIRED", "APPROVED",
        "DENIED", "EXPIRED", "CANCELLED",
    )
    assert_cost_precision(data["fee"])
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "RELEASED", "WORK_COMPLETE", "VERIFIED", "CANCELLED")
    assert_cost_precision(data["estimated_cost"])


def assert_unit(data: dict):
    _assert_common_fields(data)
    assert data["equipment_status"] in (
        "INSTALLED", "IN_SERVICE", "OUT_OF_SERVICE",
        "UNDER_MODERNIZATION", "DECOMMISSIONED",
    )
    assert data["registration_status"] in (
        "UNREGISTERED", "REGISTERED", "LAPSED", "SUSPENDED",
    )
    assert isinstance(data["serial_number"], str) and data["serial_number"]


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED", "CANCELLED")
    assert data["inspection_type"] in (
        "ACCEPTANCE", "ANNUAL", "REINSPECTION", "MODERNIZATION_ACCEPTANCE",
    )


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "PENDING_ISSUANCE", "ACTIVE", "RENEWAL_DUE",
        "EXPIRED", "REVOKED", "SUPERSEDED",
    )
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0


def assert_service_contract(data: dict):
    _assert_common_fields(data)
    assert data["tier"] in ("BASIC", "STANDARD", "PREMIUM")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert_cost_precision(data["annual_fee"])
    assert isinstance(data["included_visits"], int)
    assert isinstance(data["visits_consumed"], int)
    assert isinstance(data["entrapment_sla_minutes"], int)


def assert_service_call(data: dict):
    _assert_common_fields(data)
    assert data["call_type"] in ("MAINTENANCE_VISIT", "REPAIR", "ENTRAPMENT")
    assert data["status"] in ("OPEN", "DISPATCHED", "ON_SITE", "RESOLVED", "CANCELLED")


def assert_grant_program(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "PAUSED", "EXHAUSTED", "CLOSED")
    assert_cost_precision(data["total_pool"])
    assert_cost_precision(data["remaining_pool"])


def assert_grant_application(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "SUBMITTED", "APPROVED", "DENIED", "DISBURSED", "WITHDRAWN", "CLAWED_BACK",
    )
    assert_cost_precision(data["provisional_award"])


def assert_change_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PROPOSED", "APPROVED", "REJECTED")
    assert_cost_precision(data["amount"])


def assert_grant_pool_invariant(program: dict, approved_or_disbursed_awards):
    """Pool conservation: remaining_pool == total_pool - sum(final_award)."""
    expected = round(program["total_pool"] - sum(approved_or_disbursed_awards), 2)
    assert program["remaining_pool"] == expected, (
        f"pool conservation violated: remaining {program['remaining_pool']} != {expected}"
    )


def assert_visit_conservation(contract: dict):
    """visits_consumed + visits_remaining == included_visits."""
    assert 0 <= contract["visits_consumed"] <= contract["included_visits"]
