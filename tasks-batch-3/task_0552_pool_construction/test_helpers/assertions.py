"""Entity assertions and domain-invariant checkers for the Pool Construction API.

Uses the framework's generic format validators internally. Every entity in this
contract carries id/created_at/updated_at/version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_pool_project(data: dict):
    _assert_common(data)
    assert data["construction_status"] in (
        "NOT_STARTED", "IN_CONSTRUCTION", "STARTUP_READY", "ORIENTED", "CLOSED")
    assert data["posture"] in ("OPEN", "HOLD", "STOP_WORK")
    assert data["design_status"] in ("NO_DESIGN", "IN_DESIGN", "DESIGN_APPROVED", "PERMITTED")
    assert data["current_phase"] in (
        "NONE", "EXCAVATION", "STEEL", "PLUMBING", "GUNITE", "PLASTER", "STARTUP")
    for f in ("contract_amount_cents", "amount_disbursed_cents",
              "retainage_held_cents", "amount_remaining_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer number of cents"


def assert_ledger_conservation(data: dict):
    """PRD §2.8 conservation: amount_remaining == contract_amount - disbursed - retainage_held."""
    expected = (data["contract_amount_cents"]
                - data["amount_disbursed_cents"]
                - data["retainage_held_cents"])
    assert data["amount_remaining_cents"] == expected, (
        f"ledger not conserved: remaining {data['amount_remaining_cents']} != "
        f"contract {data['contract_amount_cents']} - disbursed {data['amount_disbursed_cents']} "
        f"- held {data['retainage_held_cents']}")


def assert_design_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "RENDERED_3D", "OWNER_APPROVED")
    assert data["permit_status"] in ("NONE", "SUBMITTED", "ISSUED", "REJECTED")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_phase_gate(data: dict):
    _assert_common(data)
    assert data["phase"] in ("EXCAVATION", "STEEL", "PLUMBING", "GUNITE", "PLASTER")
    assert data["status"] in ("PENDING", "IN_PROGRESS", "INSPECTION_PENDING", "PASSED", "FAILED")
    assert isinstance(data["sequence_index"], int) and 1 <= data["sequence_index"] <= 5
    assert isinstance(data["inspection_attempts"], int) and data["inspection_attempts"] >= 0
    assert isinstance(data["budget_cents"], int)


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED", "CANCELLED")


def assert_subcontractor(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["committed_crew_hours"], (int, float))
    assert 0 <= data["reliability_projected"] <= 100
    assert 0 <= data["reliability_realized"] <= 100


def assert_crew_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert isinstance(data["duration_hours"], (int, float))


def assert_change_order(data: dict):
    _assert_common(data)
    assert data["category"] in ("PUMP", "HEATER", "LIGHTING", "WATER_FEATURE", "CLEANER", "SCOPE")
    assert data["status"] in ("PROPOSED", "APPROVED", "REJECTED", "APPLIED", "REVERSED")
    assert isinstance(data["price_delta_cents"], int)
    assert isinstance(data["applied_delta_cents"], int)


def assert_draw_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "FUNDED")
    for f in ("requested_cents", "provisional_eligible_cents", "eligible_cents",
              "retainage_cents", "net_disbursed_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer number of cents"
    assert isinstance(data["retainage_released"], bool)


def assert_punch_item(data: dict):
    _assert_common(data)
    assert data["severity"] in ("MINOR", "MAJOR", "SAFETY")
    assert data["status"] in ("OPEN", "RESOLVED", "WAIVED")
