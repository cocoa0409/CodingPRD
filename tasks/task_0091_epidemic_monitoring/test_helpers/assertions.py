"""Entity assertions and domain invariant checkers.

Per PRD §2.4: most resources carry id/created_at/updated_at/version.
ContactEvent, DailyHealthReport, RiskTierDecision, Dispatch, AuditLog
are append-only — only id + created_at.
"""
from __future__ import annotations

from typing import Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-field assertion helpers
# ---------------------------------------------------------------------------
def _assert_mutable_common(data: dict, label: str) -> None:
    """id/created_at/updated_at/version (PRD §2.4 mutable resources)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{label}.version must be int, got {type(data.get('version'))}"
    )
    assert data["version"] >= 1, (
        f"{label}.version must be >= 1, got {data['version']}"
    )


def _assert_append_only_common(data: dict, label: str) -> None:
    """id + created_at only (PRD §2.4 append-only entities)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# ReportingInstitution
# ---------------------------------------------------------------------------
def assert_institution(data: dict) -> None:
    _assert_mutable_common(data, "ReportingInstitution")
    assert isinstance(data["institution_code"], str) and data["institution_code"]
    assert data["institution_type"] in {
        "HOSPITAL", "LAB", "CDC", "VENUE", "TRANSIT",
    }
    assert isinstance(data["district_code"], str) and data["district_code"]
    assert data["status"] in {"ACTIVE", "SUSPENDED", "ARCHIVED"}


# ---------------------------------------------------------------------------
# Region
# ---------------------------------------------------------------------------
def assert_region(data: dict) -> None:
    _assert_mutable_common(data, "Region")
    assert isinstance(data["district_code"], str) and data["district_code"]
    assert isinstance(data["population"], int) and data["population"] > 0
    assert data["current_risk_tier"] in {"LOW", "MEDIUM", "HIGH"}
    assert data["provisional_risk_tier"] in {"LOW", "MEDIUM", "HIGH"}


# ---------------------------------------------------------------------------
# Person
# ---------------------------------------------------------------------------
def assert_person(data: dict) -> None:
    _assert_mutable_common(data, "Person")
    assert isinstance(data["person_hash"], str)
    assert len(data["person_hash"]) == 16
    assert all(c in "0123456789abcdef" for c in data["person_hash"]), (
        f"person_hash must be lowercase hex, got {data['person_hash']!r}"
    )
    assert isinstance(data["demographics"], dict)
    assert isinstance(data["district_code"], str)
    assert data["isolation_status"] in {
        "NONE", "ACTIVE", "RELEASED", "VIOLATED_TERMINATED",
    }


# ---------------------------------------------------------------------------
# IsolationFacility
# ---------------------------------------------------------------------------
def assert_facility(data: dict) -> None:
    _assert_mutable_common(data, "IsolationFacility")
    assert isinstance(data["facility_code"], str) and data["facility_code"]
    assert isinstance(data["district_code"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["occupied"], int) and data["occupied"] >= 0
    assert data["occupied"] <= data["capacity"], (
        f"occupied={data['occupied']} > capacity={data['capacity']} violates "
        "PRD §3.1 facility capacity invariant"
    )
    assert data["status"] in {"OPEN", "FULL", "CLOSED"}


# ---------------------------------------------------------------------------
# Case
# ---------------------------------------------------------------------------
def assert_case(data: dict) -> None:
    _assert_mutable_common(data, "Case")
    assert isinstance(data["person_id"], str) and data["person_id"]
    assert isinstance(data["reporting_institution_id"], str)
    assert data["case_type"] in {"SUSPECTED", "CONFIRMED", "ASYMPTOMATIC"}
    assert is_iso8601_timestamp(data["onset_date"])
    assert is_iso8601_timestamp(data["reported_at"])
    assert is_iso8601_timestamp(data["report_deadline_at"])
    assert isinstance(data["is_late_report"], bool)
    assert isinstance(data["symptoms"], list)
    assert data["status"] in {
        "REPORTED", "UNDER_TRACING", "CONFIRMED", "RECOVERED", "DEDUPLICATED",
    }


# ---------------------------------------------------------------------------
# ContactEvent (append-only)
# ---------------------------------------------------------------------------
def assert_contact_event(data: dict) -> None:
    _assert_append_only_common(data, "ContactEvent")
    assert "updated_at" not in data, (
        "PRD §2.4: ContactEvent is append-only and MUST NOT carry updated_at"
    )
    assert "version" not in data, (
        "PRD §2.4: ContactEvent is append-only and MUST NOT carry version"
    )
    assert isinstance(data["source_person_id"], str)
    assert isinstance(data["target_person_id"], str)
    assert data["event_type"] in {"TRANSIT", "VENUE", "COWORKER", "HOUSEHOLD"}
    assert is_iso8601_timestamp(data["event_time"])
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 0
    assert isinstance(data["distance_meters"], (int, float))
    assert float(data["distance_meters"]) >= 0
    assert data["tier"] in {"CLOSE", "SUB_CLOSE"}
    assert data["ingested_from"] in {
        "HIS", "LIS", "TRANSIT_CODE", "VENUE_CODE", "MANUAL",
    }


# ---------------------------------------------------------------------------
# TracingTask
# ---------------------------------------------------------------------------
def assert_tracing_task(data: dict) -> None:
    _assert_mutable_common(data, "TracingTask")
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert isinstance(data["assigned_cdc_id"], str)
    assert data["status"] in {
        "DISPATCHED", "IN_PROGRESS", "NEEDS_REVISION", "COMPLETED", "CLOSED",
    }
    assert is_iso8601_timestamp(data["due_at"])
    assert is_iso8601_timestamp(data["dispatched_at"])
    assert isinstance(data["discovered_contact_count"], int)
    assert data["discovered_contact_count"] >= 0


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------
def assert_isolation(data: dict) -> None:
    _assert_mutable_common(data, "Isolation")
    assert isinstance(data["person_id"], str)
    assert data["mode"] in {"CENTRALIZED", "HOME", "MEDICAL_OBSERVATION"}
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["planned_end_date"])
    assert data["status"] in {
        "ACTIVE", "EXTENDED", "RELEASED", "VIOLATED_TERMINATED",
    }
    assert isinstance(data["extension_count"], int)
    assert isinstance(data["daily_reports_received"], int)
    assert isinstance(data["violations_count"], int)
    if data["mode"] == "CENTRALIZED":
        assert data.get("facility_id"), (
            "PRD §3.4: CENTRALIZED Isolation requires facility_id"
        )


# ---------------------------------------------------------------------------
# DailyHealthReport (append-only)
# ---------------------------------------------------------------------------
def assert_daily_report(data: dict) -> None:
    _assert_append_only_common(data, "DailyHealthReport")
    assert "updated_at" not in data, (
        "PRD §2.4: DailyHealthReport is append-only and MUST NOT carry updated_at"
    )
    assert "version" not in data, (
        "PRD §2.4: DailyHealthReport is append-only and MUST NOT carry version"
    )
    assert isinstance(data["isolation_id"], str)
    assert is_iso8601_timestamp(data["report_date"])
    assert isinstance(data["temperature_c"], (int, float))
    assert isinstance(data["symptoms"], list)
    assert isinstance(data["is_abnormal"], bool)


# ---------------------------------------------------------------------------
# TestOrder
# ---------------------------------------------------------------------------
def assert_test_order(data: dict) -> None:
    _assert_mutable_common(data, "TestOrder")
    assert isinstance(data["person_id"], str)
    assert isinstance(data["ordering_institution_id"], str)
    assert data["test_type"] in {"PCR", "ANTIGEN", "ANTIBODY"}
    assert data["result"] in {"PENDING", "POSITIVE", "NEGATIVE", "INVALID"}
    assert data["status"] in {
        "ORDERED", "COLLECTED", "RESULTED", "FOLLOW_UP", "CLOSED", "VOID",
    }
    assert isinstance(data["chain_of_custody"], list)


# ---------------------------------------------------------------------------
# RiskTierDecision (append-only — PRD §2.4)
# ---------------------------------------------------------------------------
def assert_risk_decision(data: dict) -> None:
    _assert_append_only_common(data, "RiskTierDecision")
    assert "updated_at" not in data, (
        "PRD §2.4: RiskTierDecision is append-only and MUST NOT carry updated_at"
    )
    assert "version" not in data, (
        "PRD §2.4: RiskTierDecision is append-only and MUST NOT carry version"
    )
    assert isinstance(data["region_id"], str)
    assert data["status"] in {
        "PROVISIONAL", "UNDER_REVIEW", "APPROVED", "PUBLISHED", "REJECTED",
    }
    assert data["provisional_tier"] in {"LOW", "MEDIUM", "HIGH"}


# ---------------------------------------------------------------------------
# SupplyItem
# ---------------------------------------------------------------------------
def assert_supply_item(data: dict) -> None:
    _assert_mutable_common(data, "SupplyItem")
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in {"PPE", "TEST_KIT", "MEDICATION", "VACCINE"}
    assert isinstance(data["reserve_quantity"], int)
    assert data["reserve_quantity"] >= 0
    assert isinstance(data["allocated_quantity"], int)
    assert data["allocated_quantity"] >= 0
    assert data["allocated_quantity"] <= data["reserve_quantity"], (
        f"PRD §3.7 invariant: allocated_quantity ({data['allocated_quantity']}) "
        f"must not exceed reserve_quantity ({data['reserve_quantity']})"
    )


# ---------------------------------------------------------------------------
# SupplyRequest
# ---------------------------------------------------------------------------
def assert_supply_request(data: dict) -> None:
    _assert_mutable_common(data, "SupplyRequest")
    assert isinstance(data["sku"], str)
    assert isinstance(data["requesting_institution_id"], str)
    assert isinstance(data["requested_quantity"], int)
    assert data["requested_quantity"] > 0
    assert isinstance(data["priority_score"], int)
    assert isinstance(data["allocated_quantity"], int)
    assert data["allocated_quantity"] >= 0
    assert isinstance(data["dispatched_quantity"], int)
    assert data["dispatched_quantity"] >= 0
    assert isinstance(data["consumed_quantity"], int)
    assert data["consumed_quantity"] >= 0
    assert data["status"] in {
        "PENDING", "ALLOCATED", "DISPATCHED", "DELIVERED",
        "CONSUMED", "CANCELLED",
    }


# ---------------------------------------------------------------------------
# Dispatch (append-only — PRD §2.4)
# ---------------------------------------------------------------------------
def assert_dispatch(data: dict) -> None:
    _assert_append_only_common(data, "Dispatch")
    assert "updated_at" not in data, (
        "PRD §2.4: Dispatch is append-only and MUST NOT carry updated_at"
    )
    assert "version" not in data, (
        "PRD §2.4: Dispatch is append-only and MUST NOT carry version"
    )
    assert isinstance(data["request_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["status"] in {"IN_TRANSIT", "DELIVERED"}


# ---------------------------------------------------------------------------
# Bulletin
# ---------------------------------------------------------------------------
def assert_bulletin(data: dict) -> None:
    _assert_mutable_common(data, "Bulletin")
    assert is_iso8601_timestamp(data["bulletin_date"])
    assert isinstance(data["total_new_cases"], int)
    assert data["total_new_cases"] >= 0
    assert isinstance(data["tier_summary"], dict)
    assert data["status"] in {"DRAFT", "PUBLISHED", "RETRACTED", "ARCHIVED"}
    assert isinstance(data["channels"], list)
    assert isinstance(data["rumor_corrections"], list)


# ---------------------------------------------------------------------------
# AuditLog (append-only — PRD §2.10)
# ---------------------------------------------------------------------------
def assert_audit_log(data: dict) -> None:
    _assert_append_only_common(data, "AuditLog")
    assert "updated_at" not in data, (
        "PRD §2.10: AuditLog is append-only (no version, no updated_at)"
    )
    assert "version" not in data, (
        "PRD §2.10: AuditLog is append-only (no version, no updated_at)"
    )
    assert data["entity_type"] in {
        "Case", "RiskTierDecision", "Isolation", "TestOrder",
    }
    assert isinstance(data["entity_id"], str)
    assert isinstance(data["from_state"], str)
    assert isinstance(data["to_state"], str)
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)
    assert is_iso8601_timestamp(data["at"])


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_facility_occupancy_invariant(facility: dict) -> None:
    """PRD §3.1: facility.occupied is bounded by capacity; status FULL
    iff occupied == capacity, status OPEN iff occupied < capacity (for
    facilities not administratively CLOSED)."""
    assert facility["occupied"] <= facility["capacity"]
    if facility["status"] != "CLOSED":
        if facility["occupied"] >= facility["capacity"]:
            assert facility["status"] == "FULL", (
                f"facility occupied={facility['occupied']} == capacity but "
                f"status={facility['status']} (expected FULL per PRD §3.1)"
            )
        else:
            assert facility["status"] == "OPEN", (
                f"facility occupied={facility['occupied']} < capacity but "
                f"status={facility['status']} (expected OPEN per PRD §3.1)"
            )


def assert_supply_item_invariant(item: dict) -> None:
    """PRD §3.7: allocated_quantity <= reserve_quantity at all times."""
    assert item["allocated_quantity"] <= item["reserve_quantity"]
    assert item["allocated_quantity"] >= 0
    assert item["reserve_quantity"] >= 0


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------
def find_row(rows: Iterable[dict], **kwargs) -> Optional[dict]:
    """Return the first row whose fields match all kwargs, or None."""
    for r in rows:
        if all(r.get(k) == v for k, v in kwargs.items()):
            return r
    return None


def select_rows(rows: Iterable[dict], **kwargs) -> list:
    return [r for r in rows if all(r.get(k) == v for k, v in kwargs.items())]


__all__ = [
    "assert_institution",
    "assert_region",
    "assert_person",
    "assert_facility",
    "assert_case",
    "assert_contact_event",
    "assert_tracing_task",
    "assert_isolation",
    "assert_daily_report",
    "assert_test_order",
    "assert_risk_decision",
    "assert_supply_item",
    "assert_supply_request",
    "assert_dispatch",
    "assert_bulletin",
    "assert_audit_log",
    "assert_facility_occupancy_invariant",
    "assert_supply_item_invariant",
    "find_row",
    "select_rows",
]
