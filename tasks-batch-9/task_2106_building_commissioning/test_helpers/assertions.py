"""Entity assertions and domain invariant checkers."""

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import RETAINAGE_CAP_FRACTION


def assert_common_fields(data: dict, entity_name: str = "resource") -> None:
    """Every stored resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a bare UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1, "
        f"got {data.get('version')!r}"
    )


def assert_cx_project(data: dict) -> None:
    assert_common_fields(data, "CxProject")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["building_name"], str) and data["building_name"]
    assert data["project_type"] in ("NEW_CONSTRUCTION", "RETRO_COMMISSIONING")
    assert data["certification_target"] in ("NONE", "STANDARD", "ENHANCED")
    assert isinstance(data["contract_value_cents"], int)
    assert data["contract_value_cents"] >= 1
    assert isinstance(data["witness_capacity"], int) and data["witness_capacity"] >= 1
    assert data["delivery_phase"] in (
        "PLANNING",
        "DESIGN",
        "CONSTRUCTION",
        "FUNCTIONAL_TESTING",
        "ACCEPTANCE",
        "WARRANTY",
        "CLOSED",
    )
    assert data["readiness_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert data["acceptance_kind"] in (None, "SUBSTANTIAL", "FINAL")
    assert_project_rollup_invariants(data)


def assert_project_rollup_invariants(data: dict) -> None:
    """Roll-ups the engagement row must always satisfy."""
    assert data["issue_severity_index"] >= 0
    assert data["issue_severity_index"] <= 100.00, (
        "issue_severity_index is capped at 100.00, "
        f"got {data['issue_severity_index']}"
    )
    assert data["retainage_withheld_cents"] >= 0
    assert_whole_cents(data["retainage_withheld_cents"], "retainage_withheld_cents")
    assert data["verified_prefunctional_units"] >= 0
    assert data["open_blocking_issue_count"] >= 0
    assert 0 <= data["acceptance_completion_score"] <= 100.00
    assert data["withdrawn_credit_count"] >= 0
    assert data["total_awarded_points"] >= 0


def assert_whole_cents(value, field_name: str = "amount") -> None:
    """Monetary quantities are held as whole cents, never as fractional currency."""
    assert isinstance(value, (int, float)) and float(value).is_integer(), (
        f"{field_name} must be a whole number of cents, got {value!r}"
    )


def retainage_cap_cents(contract_value_cents: int) -> int:
    """contract_value_cents * 0.10 with any fractional cent discarded."""
    return int(contract_value_cents * RETAINAGE_CAP_FRACTION)


def assert_owner_requirement(data: dict) -> None:
    assert_common_fields(data, "OwnerRequirement")
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["metric_key"], str) and data["metric_key"]
    assert data["target_value"] >= 0
    assert 0 <= data["tolerance_pct"] <= 100
    assert data["criticality"] in ("LIFE_SAFETY", "CRITICAL", "STANDARD")
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in ("DRAFT", "APPROVED", "SUPERSEDED")


def assert_cx_plan(data: dict) -> None:
    assert_common_fields(data, "CxPlan")
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in ("DRAFT", "APPROVED", "SUPERSEDED")
    assert isinstance(data["pinned_requirement_ids"], list)
    assert data["pinned_requirement_count"] == len(data["pinned_requirement_ids"]), (
        "pinned_requirement_count must equal the length of pinned_requirement_ids"
    )
    assert isinstance(data["pin_stale"], bool)


def assert_submittal(data: dict) -> None:
    assert_common_fields(data, "Submittal")
    assert is_valid_uuid(data["project_id"])
    assert data["submittal_kind"] in (
        "DESIGN_DOCUMENT",
        "PRODUCT_DATA",
        "SHOP_DRAWING",
        "OM_DATA",
    )
    assert data["status"] in (
        "RECEIVED",
        "APPROVED",
        "APPROVED_AS_NOTED",
        "REVISE_AND_RESUBMIT",
    )
    assert isinstance(data["review_round"], int) and 1 <= data["review_round"] <= 3
    assert data["last_decision"] in (
        None,
        "APPROVED",
        "APPROVED_AS_NOTED",
        "REVISE_AND_RESUBMIT",
    )


def assert_equipment_unit(data: dict) -> None:
    assert_common_fields(data, "EquipmentUnit")
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["tag"], str) and data["tag"]
    assert data["system_type"] in (
        "AHU",
        "CHILLER",
        "BOILER",
        "LIGHTING",
        "FIRE_ALARM",
        "ELEVATOR",
        "BAS",
    )
    assert data["criticality"] in ("LIFE_SAFETY", "CRITICAL", "STANDARD")
    assert data["contract_value_cents"] >= 1
    assert data["weight_units"] >= 1
    assert data["install_status"] in (
        "NOT_INSTALLED",
        "INSTALLED",
        "STARTED_UP",
        "REMOVED",
    )
    assert data["verification_status"] in (
        "UNVERIFIED",
        "PREFUNCTIONAL_VERIFIED",
        "FUNCTIONAL_ACCEPTED",
        "CONDITIONALLY_ACCEPTED",
    )
    assert data["blocking_issue_count"] >= 0


def assert_prefunctional_checklist(data: dict) -> None:
    assert_common_fields(data, "PrefunctionalChecklist")
    assert is_valid_uuid(data["equipment_id"])
    assert data["status"] in ("DRAFT", "EXECUTED", "VERIFIED", "REWORK")
    assert isinstance(data["items"], list)
    assert data["item_count"] == len(data["items"]), (
        "item_count must equal the length of items"
    )
    passed = sum(1 for item in data["items"] if item["result"] in ("PASS", "NA"))
    failed = sum(1 for item in data["items"] if item["result"] == "FAIL")
    assert data["passed_item_count"] == passed, (
        "passed_item_count counts items whose result is PASS or NA"
    )
    assert data["failed_item_count"] == failed, (
        "failed_item_count counts items whose result is FAIL"
    )
    assert data["rework_cycle_count"] >= 0
    for item in data["items"]:
        assert_checklist_item(item)


def assert_checklist_item(item: dict) -> None:
    """Embedded checklist items carry no id, no version and no updated_at."""
    assert isinstance(item["item_code"], str) and item["item_code"]
    assert isinstance(item["description"], str)
    assert isinstance(item["is_safety_critical"], bool)
    assert item["result"] in ("PENDING", "PASS", "FAIL", "NA")
    assert "id" not in item, "checklist items have no id of their own"
    assert "version" not in item, "checklist items have no version of their own"


def assert_functional_test(data: dict) -> None:
    assert_common_fields(data, "FunctionalTest")
    assert is_valid_uuid(data["equipment_id"])
    assert is_valid_uuid(data["requirement_id"])
    assert isinstance(data["script_code"], str) and data["script_code"]
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["scheduled_end"] > data["scheduled_start"]
    assert data["status"] in (
        "SCHEDULED",
        "IN_PROGRESS",
        "PASSED",
        "PASSED_WITH_EXCEPTIONS",
        "FAILED",
        "CANCELLED",
    )


def assert_issue(data: dict) -> None:
    assert_common_fields(data, "Issue")
    assert is_valid_uuid(data["project_id"])
    assert data["origin"] in (
        "DESIGN_REVIEW",
        "SUBMITTAL",
        "PREFUNCTIONAL",
        "FUNCTIONAL",
        "SEASONAL",
        "RETRO_CX",
    )
    assert data["severity"] in ("S1", "S2", "S3", "S4")
    assert data["status"] in (
        "OPEN",
        "IN_REVIEW",
        "VERIFIED_CLOSED",
        "DEFERRED",
        "VOID",
    )
    assert data["blocks_acceptance"] is (data["severity"] in ("S1", "S2")), (
        "blocks_acceptance is true exactly when severity is S1 or S2"
    )
    assert is_iso8601_timestamp(data["opened_at"])
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    assert_whole_cents(data["retainage_hold_cents"], "retainage_hold_cents")
    assert data["retainage_hold_cents"] >= 0
    assert data["reopen_count"] >= 0


def assert_deferred_test(data: dict) -> None:
    assert_common_fields(data, "DeferredTest")
    assert is_valid_uuid(data["equipment_id"])
    assert is_valid_uuid(data["requirement_id"])
    assert data["season"] in ("HEATING", "COOLING", "SHOULDER")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["window_end"] > data["window_start"]
    assert data["status"] in (
        "PLANNED",
        "BLOCKED",
        "EXECUTED_PASS",
        "EXECUTED_FAIL",
        "MISSED",
    )


def assert_closeout_deliverable(data: dict) -> None:
    assert_common_fields(data, "CloseoutDeliverable")
    assert is_valid_uuid(data["project_id"])
    assert data["deliverable_kind"] in (
        "TRAINING_SESSION",
        "SYSTEMS_MANUAL_SECTION",
        "OM_DATA_PACKAGE",
    )
    assert isinstance(data["title"], str) and data["title"]
    assert data["required_attendee_count"] >= 0
    assert data["attendee_count"] >= 0
    assert data["duration_minutes"] >= 0
    assert data["status"] in ("PLANNED", "DELIVERED", "ACCEPTED", "RETURNED")
    assert 0 <= data["coverage_ratio"] <= 1.0, (
        f"coverage_ratio is capped at 1.0, got {data['coverage_ratio']}"
    )


def assert_certification_credit(data: dict) -> None:
    assert_common_fields(data, "CertificationCredit")
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["credit_code"], str) and data["credit_code"]
    assert data["required_evidence_count"] >= 0
    assert data["max_points"] >= 0
    assert data["status"] in (
        "NOT_STARTED",
        "IN_PREPARATION",
        "SUBMITTED",
        "AWARDED",
        "DENIED",
        "WITHDRAWN",
    )
    assert data["evidence_count"] == (
        data["fresh_evidence_count"] + data["stale_evidence_count"]
    ), "evidence_count must equal fresh_evidence_count + stale_evidence_count"
    assert 0 <= data["completeness_ratio"] <= 1.0
    assert data["provisional_tier"] in ("NONE", "BRONZE", "SILVER", "GOLD")
    assert data["final_tier"] in ("NONE", "BRONZE", "SILVER", "GOLD")
    assert data["documentation_score"] >= 0.0
    assert data["awarded_points"] >= 0


def assert_credit_evidence(data: dict) -> None:
    assert_common_fields(data, "CreditEvidence")
    assert is_valid_uuid(data["credit_id"])
    assert data["evidence_type"] in (
        "EQUIPMENT_VERIFICATION",
        "FUNCTIONAL_TEST",
        "CHECKLIST",
        "TRAINING",
        "MANUAL_SECTION",
        "ENERGY_BASELINE",
    )
    assert isinstance(data["is_stale"], bool)


def assert_energy_baseline(data: dict) -> None:
    assert_common_fields(data, "EnergyBaseline")
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["measure_code"], str) and data["measure_code"]
    assert data["baseline_kwh"] > 0
    assert data["baseline_hdd"] > 0
    assert data["stipulated_kwh_per_hour"] >= 0
    assert data["operating_hours"] >= 0
    assert data["status"] in ("BASELINE_SET", "POST_PERIOD_RECORDED", "CERTIFIED")
    assert data["certified_variant"] in (None, "DEEMED", "MEASURED")


def assert_readiness(data: dict) -> None:
    """The computed readiness read exposes both score variants side by side."""
    for field in (
        "readiness_posture",
        "issue_severity_index",
        "acceptance_completion_score_provisional",
        "acceptance_completion_score_final",
        "open_blocking_issue_count",
        "retainage_withheld_cents",
        "retainage_cap_cents",
        "verified_prefunctional_units",
        "total_weight_units",
        "withdrawn_credit_count",
        "total_awarded_points",
    ):
        assert field in data, f"readiness read must expose {field}"
    assert data["readiness_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert 0 <= data["acceptance_completion_score_provisional"] <= 100.00
    assert 0 <= data["acceptance_completion_score_final"] <= 100.00


def assert_rounded_to(value: float, places: int = 2) -> None:
    """Derived numbers are rounded half up to a fixed number of decimal places."""
    assert round(value, places) == pytest.approx(value), (
        f"{value} carries more than {places} decimal places"
    )
