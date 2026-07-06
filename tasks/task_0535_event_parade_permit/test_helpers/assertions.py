"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def assert_common_fields(data: dict):
    """id (UUID), created_at/updated_at (ISO 8601), version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer >= 1"


def assert_venue(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["venue_type"] in ("PARK", "PLAZA", "STADIUM", "STREET_CORRIDOR")
    assert isinstance(data["max_capacity"], int)
    assert isinstance(data["setup_buffer_minutes"], int)
    assert data["status"] in ("ACTIVE", "DECOMMISSIONED")


def assert_closure_schedule(data: dict):
    assert_common_fields(data)
    assert isinstance(data["corridor_name"], str) and len(data["corridor_name"]) > 0
    assert isinstance(data["min_gap_minutes"], int)
    assert data["status"] in ("OPEN", "SUSPENDED")


def assert_application(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED", "CONDITIONALLY_APPROVED",
        "ISSUED", "DENIED", "CANCELLED", "CLOSED",
    )
    assert data["permit_class"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["event_kind"] in ("PARADE", "FESTIVAL", "RACE", "RALLY")
    assert isinstance(data["expected_attendance"], int)
    assert_cost_precision(data["application_fee"])
    assert_cost_precision(data["deposit_required"])
    assert isinstance(data["required_coverage_min"], int)
    assert isinstance(data["coi_on_file"], bool)


def assert_route_segment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PLANNED", "ACTIVE", "RELEASED")
    assert isinstance(data["segment_label"], str)


def assert_department_review(data: dict):
    assert_common_fields(data)
    assert data["department"] in ("POLICE", "FIRE", "EMS", "PUBLIC_WORKS")
    assert data["status"] in ("PENDING", "APPROVED", "CHANGES_REQUESTED", "VETOED")


def assert_permit_condition(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PROPOSED", "ACKNOWLEDGED", "WAIVED")
    assert isinstance(data["mandatory"], bool)


def assert_insurance_certificate(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED")
    assert isinstance(data["coverage_amount"], int)


def assert_deposit(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("HELD", "FORFEITED_PARTIAL", "REFUNDED")
    assert_cost_precision(data["amount"])
    assert_cost_precision(data["forfeited_amount"])
    assert_cost_precision(data["refunded_amount"])


def assert_deposit_conserved(data: dict):
    """forfeited_amount + refunded_amount == amount (PRD §3.8 conservation)."""
    total = round(data["forfeited_amount"] + data["refunded_amount"], 2)
    assert total == round(data["amount"], 2), (
        f"forfeited {data['forfeited_amount']} + refunded {data['refunded_amount']} "
        f"must equal amount {data['amount']}"
    )


def assert_invoice(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "SETTLED")
    assert_cost_precision(data["fee_component"])
    assert_cost_precision(data["cost_recovery_estimate"])
    assert_cost_precision(data["cost_recovery_actual"])
    assert_cost_precision(data["balance_due"])


def assert_cleanup_debrief(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "FINALIZED")
