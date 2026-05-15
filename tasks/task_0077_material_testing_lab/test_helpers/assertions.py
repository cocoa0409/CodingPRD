"""Entity assertions and domain invariant checkers.

These helpers verify shape and PRD-mandated invariants over the response
payloads returned by ApiClient methods. They are PRD-exact; field names
follow PRD §3.
"""
from __future__ import annotations
from typing import Any, Dict, List

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common envelope helpers
# ---------------------------------------------------------------------------
def _assert_common_versioned(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'Every persisted resource carries an id ... plus a
    created_at timestamp. Most resources additionally carry an updated_at
    timestamp and an integer version that starts at 1.'"""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be positive integer, got {data.get('version')!r}"


def _assert_common_append_only(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'InstrumentBooking and DataModification carry only id
    and created_at.' AuditEvent is also append-only."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_client(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("contact_email"), str)
    # contract_id is optional
    assert "contract_id" in data, "Client must surface contract_id"
    assert isinstance(data.get("deposit_balance_cents"), int)
    assert isinstance(data.get("outstanding_balance_cents"), int)
    assert data["deposit_balance_cents"] >= 0
    assert data["outstanding_balance_cents"] >= 0


def assert_tester(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("qualifications"), list)
    for q in data["qualifications"]:
        assert "material_category" in q
        assert "valid_from" in q
        assert "valid_to" in q
    assert isinstance(data.get("max_concurrent_tasks"), int)
    assert isinstance(data.get("active_task_count"), int)
    assert data["active_task_count"] >= 0
    assert data.get("qualification_posture") in {
        "QUALIFIED", "EXPIRING_SOON", "LAPSED",
    }


def assert_reviewer(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("scope_categories"), list)


def assert_signatory(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("signature_certificate_id"), str)
    assert isinstance(data.get("scope_categories"), list)


def assert_instrument(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data)
    assert isinstance(data.get("asset_code"), str)
    assert isinstance(data.get("capabilities"), list)
    assert is_iso8601_timestamp(data.get("calibration_valid_from", ""))
    assert is_iso8601_timestamp(data.get("calibration_valid_to", ""))
    assert data.get("status") in {
        "AVAILABLE", "CALIBRATION_DUE", "OUT_OF_SERVICE", "RETIRED",
    }
    assert isinstance(data.get("usage_minutes_total"), int)
    assert data["usage_minutes_total"] >= 0


def assert_sample(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data)
    assert isinstance(data.get("client_id"), str)
    assert isinstance(data.get("source_project"), str)
    assert data.get("material_category") in {
        "CONCRETE", "STEEL_REBAR", "SOIL", "ASPHALT", "CEMENT",
    }
    assert isinstance(data.get("specification"), str)
    assert isinstance(data.get("witness_sampled"), bool)
    assert isinstance(data.get("sample_code"), str) and data["sample_code"]
    assert isinstance(data.get("storage_location"), str) and \
        data["storage_location"]
    assert data.get("status") in {
        "REGISTERED", "IN_TESTING", "RETESTING", "TESTED", "DISPOSED",
    }
    # handover_record shape
    handover = data.get("handover_record") or {}
    assert isinstance(handover, dict)
    assert handover.get("delivered_by")
    assert handover.get("received_by")
    assert is_iso8601_timestamp(handover.get("handover_at", ""))


def assert_test_task(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data)
    assert isinstance(data.get("sample_id"), str)
    assert data.get("test_method") in {
        "COMPRESSION_STRENGTH", "TENSILE_STRENGTH", "COMPACTION_DENSITY",
        "MARSHALL_STABILITY", "SETTING_TIME",
    }
    assert isinstance(data.get("urgent"), bool)
    assert data.get("status") in {
        "PENDING_ASSIGNMENT", "ASSIGNED", "IN_PROGRESS",
        "AWAITING_RETEST", "COMPLETED", "CANCELLED",
    }
    assert isinstance(data.get("retest_count"), int)
    assert data["retest_count"] >= 0
    assert isinstance(data.get("priority_seq"), int)


def assert_instrument_booking(data: Dict[str, Any]) -> None:
    _assert_common_append_only(data)
    assert isinstance(data.get("instrument_id"), str)
    assert isinstance(data.get("task_id"), str)
    assert is_iso8601_timestamp(data.get("slot_start", ""))
    assert is_iso8601_timestamp(data.get("slot_end", ""))
    assert data.get("status") in {"RESERVED", "COMPLETED", "CANCELLED"}
    # PRD §2.4: 'InstrumentBooking and DataModification carry only id
    # and created_at.'  No updated_at / version on the envelope.


def assert_test_record(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data)
    assert isinstance(data.get("task_id"), str)
    assert isinstance(data.get("tester_id"), str)
    assert isinstance(data.get("raw_data"), dict)
    assert isinstance(data.get("calculated_result"), (int, float))
    assert isinstance(data.get("abnormal_flag"), bool)
    assert data.get("status") in {"DRAFT", "SUBMITTED", "SUPERSEDED"}


def assert_data_modification(data: Dict[str, Any]) -> None:
    _assert_common_append_only(data)
    assert isinstance(data.get("record_id"), str)
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert isinstance(data.get("field_path"), str) and data["field_path"]
    # previous_value / new_value are JSON-serialised strings per PRD §3.8
    assert "previous_value" in data
    assert "new_value" in data
    assert isinstance(data.get("reason"), str) and data["reason"]


def assert_report(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data)
    assert isinstance(data.get("task_id"), str)
    assert isinstance(data.get("template_code"), str) and data["template_code"]
    assert data.get("status") in {
        "DRAFTED", "UNDER_REVIEW", "SIGNED", "ISSUED", "ARCHIVED", "RECALLED",
    }


def assert_invoice(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data)
    assert isinstance(data.get("client_id"), str)
    assert isinstance(data.get("line_items"), list)
    for line in data["line_items"]:
        assert isinstance(line.get("task_id"), str)
        assert isinstance(line.get("base_fee_cents"), int)
        assert isinstance(line.get("surcharge_cents"), int)
        assert isinstance(line.get("refund_cents"), int)
    assert isinstance(data.get("subtotal_cents"), int)
    assert isinstance(data.get("surcharge_total_cents"), int)
    assert isinstance(data.get("refund_total_cents"), int)
    assert isinstance(data.get("package_discount_cents"), int)
    assert isinstance(data.get("deposit_applied_cents"), int)
    assert isinstance(data.get("total_due_cents"), int)
    assert data["total_due_cents"] >= 0
    assert data["deposit_applied_cents"] >= 0
    assert data.get("status") in {"ISSUED", "PAID", "VOIDED"}


def assert_audit_event(data: Dict[str, Any]) -> None:
    _assert_common_append_only(data)
    assert data.get("event_type") in {
        "REPORT_ISSUED", "REPORT_RECALLED", "DATA_MODIFIED",
        "EXTERNAL_INSPECTION_RESPONDED", "INTERNAL_AUDIT_RUN",
        "QUALIFICATION_LAPSED", "INSTRUMENT_CALIBRATION_LAPSED",
    }
    assert isinstance(data.get("subject_type"), str)
    assert isinstance(data.get("subject_id"), str)
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_invoice_total_invariant(invoice: Dict[str, Any]) -> None:
    """PRD §3.10 evaluation order:
       gross = subtotal + surcharge_total - refund_total
       pre_deposit_total = gross - package_discount
       total_due = pre_deposit_total - deposit_applied
    """
    gross = (
        invoice["subtotal_cents"]
        + invoice["surcharge_total_cents"]
        - invoice["refund_total_cents"]
    )
    pre_deposit = gross - invoice["package_discount_cents"]
    expected_total = pre_deposit - invoice["deposit_applied_cents"]
    assert invoice["total_due_cents"] == expected_total, (
        f"total_due_cents={invoice['total_due_cents']} but "
        f"subtotal+surcharge-refund-discount-deposit={expected_total}"
    )


def assert_sample_code_format(sample: Dict[str, Any]) -> None:
    """PRD §3.2: '{MATERIAL3}-{YYYYMMDD}-{SEQ4}, where MATERIAL3 is the
    first three letters of material_category ... and SEQ4 is a four-digit
    zero-padded sequence.'"""
    code = sample["sample_code"]
    parts = code.split("-")
    assert len(parts) == 3, f"sample_code must have three dash-separated parts: {code}"
    material3, date_str, seq = parts
    assert len(material3) == 3, f"MATERIAL3 must be 3 chars: {material3}"
    assert len(date_str) == 8 and date_str.isdigit(), \
        f"YYYYMMDD segment malformed: {date_str}"
    assert len(seq) == 4 and seq.isdigit(), f"SEQ4 malformed: {seq}"


def assert_storage_location_format(sample: Dict[str, Any]) -> None:
    """PRD §3.2: 'BIN-{material_category}-{NN}'."""
    loc = sample["storage_location"]
    assert loc.startswith("BIN-"), f"storage_location must start with 'BIN-': {loc}"
    parts = loc.split("-")
    assert len(parts) >= 3, f"storage_location malformed: {loc}"
    # third segment must be the material category and exist in the
    # supported enumeration
    assert parts[1] in {"CONCRETE", "STEEL_REBAR", "SOIL", "ASPHALT", "CEMENT"}, \
        f"storage_location material segment unexpected: {parts[1]}"


__all__ = [
    "assert_client",
    "assert_tester",
    "assert_reviewer",
    "assert_signatory",
    "assert_instrument",
    "assert_sample",
    "assert_test_task",
    "assert_instrument_booking",
    "assert_test_record",
    "assert_data_modification",
    "assert_report",
    "assert_invoice",
    "assert_audit_event",
    "assert_invoice_total_invariant",
    "assert_sample_code_format",
    "assert_storage_location_format",
]
