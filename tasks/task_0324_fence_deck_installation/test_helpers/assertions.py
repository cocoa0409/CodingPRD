"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the system-managed field shape and the
declared field domains. Domain invariant checkers verify cross-field
identities that must hold after any operation.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def _assert_common_mutable(data: dict):
    """id + created_at + updated_at + version for mutable resources."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    """Customer is an immutable identity record: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str)
    assert isinstance(data["hoa_governed"], bool)


def assert_project(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in [
        "DRAFT", "ESTIMATED", "MEASURED", "APPROVED", "SCHEDULED",
        "IN_PROGRESS", "COMPLETED", "CANCELLED",
    ], f"unexpected project status {data['status']!r}"
    assert data["job_type"] in ["FENCE", "DECK", "FENCE_AND_DECK"]
    assert data["permit_clearance"] in ["PENDING", "CLEARED", "BLOCKED"]
    assert_cost_precision(data["contract_total"])
    assert_cost_precision(data["draws_paid_total"])
    assert_cost_precision(data["balance_due"])
    assert isinstance(data["customer_id"], str)


def assert_project_money_invariants(data: dict):
    """balance_due == contract_total - draws_paid_total (PRD §3.8)."""
    expected = round(data["contract_total"] - data["draws_paid_total"], 2)
    assert abs(data["balance_due"] - expected) < 0.005, (
        f"balance_due {data['balance_due']} != contract_total - draws_paid_total "
        f"({data['contract_total']} - {data['draws_paid_total']} = {expected})"
    )
    assert_cost_precision(data["balance_due"])


def assert_estimate(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in ["DRAFT", "PRICED", "ACCEPTED", "SUPERSEDED"]
    assert isinstance(data["project_id"], str)


def assert_line_item(data: dict):
    _assert_common_mutable(data)
    assert data["work_type"] in ["FENCE", "DECK"]
    assert data["material"] in ["CEDAR", "VINYL", "COMPOSITE", "PT_PINE", "ALUMINUM"]
    assert data["style"] in ["PRIVACY", "PICKET", "DECK_STANDARD", "ORNAMENTAL"]
    assert data["accessory"] in ["NONE", "SINGLE_GATE", "DOUBLE_GATE", "STAIR_SET"]
    assert isinstance(data["estimate_id"], str)


def assert_site_measure(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in ["RECORDED", "APPROVED"]
    assert isinstance(data["setback_ok"], bool)
    assert isinstance(data["property_line_note"], str)


def assert_permit(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "RETURNED", "ISSUED", "DENIED"]
    assert data["permit_type"] in ["FENCE_PERMIT", "DECK_PERMIT", "ZONING_VARIANCE"]


def assert_hoa_approval(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED"]


def assert_material_order(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in ["PLACED", "CONFIRMED", "DELIVERED", "CANCELLED"]
    assert isinstance(data["dock_id"], str)


def assert_crew_booking(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in ["HELD", "CONFIRMED", "CANCELLED"]
    assert isinstance(data["crew_id"], str)


def assert_change_order(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in ["DRAFT", "APPLIED", "REJECTED", "WITHDRAWN"]
    assert isinstance(data["line_item_id"], str)


def assert_draw(data: dict):
    _assert_common_mutable(data)
    assert data["milestone"] in ["DEPOSIT", "DELIVERY", "FRAMING", "FINAL"]
    assert data["status"] in ["SCHEDULED", "INVOICED", "PAID", "VOIDED"]
    assert_cost_precision(data["amount"])


def assert_warranty(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in ["ISSUED", "CLAIMED", "EXPIRED", "VOIDED"]
    assert isinstance(data["coverage_years"], int)
    assert isinstance(data["workmanship_only"], bool)


def find_draw_by_milestone(draws: list, milestone: str) -> dict:
    """Return the single draw row with the given milestone from a draw list."""
    matches = [d for d in draws if d["milestone"] == milestone]
    assert len(matches) == 1, f"expected exactly one {milestone} draw, got {len(matches)}"
    return matches[0]
