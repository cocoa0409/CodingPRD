"""Entity assertions and domain invariant checkers.

Each ``assert_{entity}`` validates the structural shape of a resource using the
framework's generic format validators. Append-only records (weigh-ins, messages)
are checked to carry only ``id`` + ``created_at`` and no ``updated_at`` /
``version`` fields.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    """id + created_at + updated_at + version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def _assert_append_only(data: dict):
    """id + created_at present; updated_at and version MUST be absent."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_iso8601_timestamp(data["current_utc"]), "current_utc must be ISO 8601"
    assert isinstance(data["coach_max_active_members"], int)


def assert_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("COACHING", "RX", "MEAL")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["enrollment_fee_cents"], int) and data["enrollment_fee_cents"] >= 0
    assert isinstance(data["requires_rx"], bool)
    assert isinstance(data["active"], bool)


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["status"] in ("REGISTERED", "INTAKE_PENDING", "ENROLLED", "GRADUATED", "WITHDRAWN")
    assert isinstance(data["account_balance_cents"], int)


def assert_coach(data: dict):
    _assert_common(data)
    assert data["specialty"] in ("GENERAL", "DIETITIAN", "CLINICAL")
    assert isinstance(data["active_member_count"], int) and data["active_member_count"] >= 0
    assert isinstance(data["accepting"], bool)


def assert_intake(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_REVISION", "APPROVED", "REJECTED",
    )
    assert isinstance(data["revision_round"], int)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["clinical_status"] in ("PENDING_CLINICAL", "ACTIVE", "GRADUATED", "WITHDRAWN")
    assert data["billing_status"] in ("UNBILLED", "CURRENT", "PAST_DUE", "CLOSED")
    assert isinstance(data["cycles_billed"], int)
    assert isinstance(data["graduation_eligible"], bool)


def assert_goal(data: dict):
    _assert_common(data)
    assert data["kind"] in ("PRIMARY", "SECONDARY")
    assert data["status"] in ("OPEN", "ACHIEVED", "CLOSED")


def assert_milestone(data: dict):
    _assert_common(data)
    assert data["threshold_pct"] in (25, 50, 75, 100)
    assert data["status"] in ("PENDING", "ACHIEVED", "VOIDED")


def assert_coach_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "ENDED")


def assert_message_thread(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "ARCHIVED")
    assert isinstance(data["message_count"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "PAID", "VOID")
    assert isinstance(data["cycle_index"], int)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["line_items"], list)


def assert_eligibility(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "APPROVED", "DENIED")
    assert isinstance(data["hsa_fsa_eligible"], bool)


def assert_rx(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "ISSUED", "DENIED", "REVOKED")


def assert_weighin(data: dict):
    _assert_append_only(data)
    assert isinstance(data["weight_kg"], (int, float))
    assert isinstance(data["counts"], bool)


def assert_message(data: dict):
    _assert_append_only(data)
    assert data["sender_role"] in ("MEMBER", "COACH")
    assert isinstance(data["body"], str)


def find_line_item(invoice: dict, code: str):
    """Return the first line_item dict with the given code, or None."""
    for line in invoice.get("line_items", []):
        if line.get("code") == code:
            return line
    return None
