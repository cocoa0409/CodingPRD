"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    assert_timestamp_format,
    is_valid_uuid,
)


def _assert_common(data: dict):
    """Every resource carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID without prefix: {data.get('id')!r}"
    assert_timestamp_format(data.get("created_at", ""))
    assert_timestamp_format(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_lab(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["department"], str)
    assert isinstance(data["building"], str)
    assert isinstance(data["room"], str)
    pi = data.get("pi_worker_id")
    assert pi is None or isinstance(pi, str), "pi_worker_id must be null or a worker id"
    assert data["status"] in ("ACTIVE", "CLOSING", "DECOMMISSIONED")
    assert data["posture"] in ("NORMAL", "RESTRICTED", "FROZEN")
    assert isinstance(data["hazard_totals_physical"], dict), "hazard_totals_physical exposed on lab"
    assert isinstance(data["hazard_totals_regulatory"], dict), "hazard_totals_regulatory exposed on lab"
    assert isinstance(data["permit_report_required"], bool)


def assert_worker(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_in_lab"] in ("PI", "RESEARCHER", "STUDENT")


def assert_container(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_id"], str)
    assert isinstance(data["barcode"], str) and data["barcode"]
    assert isinstance(data["chemical_name"], str)
    assert data["hazard_class"] in (
        "FLAMMABLE", "OXIDIZER", "CORROSIVE", "TOXIC",
        "CONTROLLED_SUBSTANCE", "SELECT_AGENT",
    )
    assert isinstance(data["quantity_value"], (int, float))
    assert data["quantity_value"] > 0
    assert data["quantity_unit"] in ("GAL", "L", "KG", "LB")
    assert data["state"] in ("IN_USE", "WASTE_TAGGED", "PICKED_UP")
    assert data.get("accumulation_area_id") is None or isinstance(data["accumulation_area_id"], str)
    assert data.get("pickup_request_id") is None or isinstance(data["pickup_request_id"], str)
    assert data.get("tagged_at") is None or isinstance(data["tagged_at"], str)
    if "access_blocked" in data:
        assert isinstance(data["access_blocked"], bool)


def assert_area(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert data["area_type"] in ("SAA", "CAA")
    assert isinstance(data["capacity_containers"], int)
    assert data["capacity_containers"] > 0
    assert isinstance(data["current_container_count"], int)
    assert data["current_container_count"] >= 0
    assert isinstance(data["has_overstay_containers"], bool)


def assert_pickup_request(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_id"], str)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "REJECTED", "SCHEDULED", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["estimated_quantity_total"], (int, float))
    assert isinstance(data["estimated_cost"], (int, float))
    assert_cost_precision(float(data["estimated_cost"]))
    assert data.get("dock_id") is None or isinstance(data["dock_id"], str)
    assert data.get("window_start") is None or isinstance(data["window_start"], str)
    assert data.get("window_end") is None or isinstance(data["window_end"], str)
    assert data.get("rejection_reason") is None or isinstance(data["rejection_reason"], str)


def assert_inspection(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_id"], str)
    assert isinstance(data["inspector_id"], str)
    assert isinstance(data["scheduled_start"], str)
    assert isinstance(data["scheduled_end"], str)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    if data.get("findings") is not None:
        assert isinstance(data["findings"], list)
        for f in data["findings"]:
            assert f["severity"] in ("MAJOR", "MINOR")
            assert isinstance(f["description"], str)
    assert data.get("score_weighted") is None or isinstance(data["score_weighted"], (int, float))
    assert data.get("score_flat") is None or isinstance(data["score_flat"], (int, float))
    assert data.get("outcome") in (None, "PASS", "FAIL")
    assert data.get("completed_by_inspector_id") is None or isinstance(
        data["completed_by_inspector_id"], str
    )
    assert data.get("completed_at") is None or isinstance(data["completed_at"], str)


def assert_corrective_action(data: dict):
    _assert_common(data)
    assert isinstance(data["inspection_id"], str)
    assert isinstance(data["lab_id"], str)
    assert isinstance(data["description"], str)
    assert data["severity"] in ("MAJOR", "MINOR")
    assert data["status"] in ("OPEN", "SUBMITTED", "REOPENED", "VERIFIED")
    assert isinstance(data["due_date"], str)
    assert data.get("resolution_note") is None or isinstance(data["resolution_note"], str)
    assert data.get("verified_by") is None or isinstance(data["verified_by"], str)


def assert_training_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_id"], str)
    assert isinstance(data["worker_id"], str)
    assert data["hazard_class"] in (
        "FLAMMABLE", "OXIDIZER", "CORROSIVE", "TOXIC",
        "CONTROLLED_SUBSTANCE", "SELECT_AGENT",
    )
    assert data["status"] in ("ASSIGNED", "COMPLETED", "EXPIRED")
    assert isinstance(data["due_date"], str)
    assert data.get("completed_at") is None or isinstance(data["completed_at"], str)


def assert_incident(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_id"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["description"], str)
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data["near_miss"], bool)
    assert data["status"] in ("REPORTED", "CLOSED")
    assert isinstance(data["reported_by"], str)
    assert data.get("resolution") is None or isinstance(data["resolution"], str)


def assert_registration(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_id"], str)
    assert data["material_type"] in ("CONTROLLED_SUBSTANCE", "SELECT_AGENT")
    assert isinstance(data["registration_number"], str) and data["registration_number"]
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "SURRENDERED", "SUPERSEDED")
