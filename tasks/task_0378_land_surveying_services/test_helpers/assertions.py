"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the standard system fields (UUID id, ISO 8601
created_at, integer version) plus the entity's own fields. Domain invariant
helpers check monetary and counting invariants that must hold after any
operation.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_crew_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_type"] in {
        "COORDINATOR", "PLS", "TECH", "RESEARCHER", "DRAFTER", "BILLING_CLERK"
    }, f"unexpected role_type {data['role_type']!r}"
    assert isinstance(data["active"], bool)
    assert isinstance(data["open_assignment_count"], int) and data["open_assignment_count"] >= 0


def assert_instrument(data: dict):
    _assert_common(data)
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert data["instrument_type"] in {"TOTAL_STATION", "GPS_RTK", "LEVEL", "DRONE", "SCANNER"}
    assert data["status"] in {"AVAILABLE", "RESERVED", "MAINTENANCE"}


def assert_survey_order(data: dict):
    _assert_common(data)
    assert isinstance(data["client_name"], str) and data["client_name"]
    assert data["survey_type"] in {"BOUNDARY", "TOPO", "ALTA", "ELEVATION"}
    assert data["status"] in {
        "INTAKE", "RESEARCH", "FIELD_READY", "IN_FIELD", "DATA_READY",
        "DRAFTING", "SEALED", "DELIVERED", "CANCELLED"
    }
    assert isinstance(data["research_clear"], bool)
    for fee in ("base_fee_cents", "estimated_fee_cents", "final_fee_cents"):
        assert isinstance(data[fee], int) and data[fee] >= 0, f"{fee} must be a non-negative int"
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_research_packet(data: dict):
    _assert_common(data)
    assert data["status"] in {"OPEN", "IN_PROGRESS", "CLEARED", "TITLE_HOLD"}
    assert isinstance(data["encumbrance_count"], int) and data["encumbrance_count"] >= 0


def assert_field_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
    assert isinstance(data["window_minutes"], int) and data["window_minutes"] >= 0


def assert_instrument_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in {"HELD", "RELEASED"}


def assert_data_set(data: dict):
    _assert_common(data)
    assert data["status"] in {"RAW", "REDUCED", "ACCEPTED"}
    assert isinstance(data["point_count"], int) and data["point_count"] >= 0
    assert isinstance(data["closure_error_ppm"], int) and data["closure_error_ppm"] >= 0


def assert_plat_drawing(data: dict):
    _assert_common(data)
    assert data["status"] in {"DRAFTED", "UNDER_REVIEW", "SEALED", "IN_REVISION"}


def assert_revision_request(data: dict):
    _assert_common(data)
    assert data["reason"] in {"CLIENT_CHANGE", "FIELD_ERROR", "DEED_DISCREPANCY"}
    assert data["status"] in {"REQUESTED", "APPLIED", "REJECTED"}
    assert isinstance(data["reseal_fee_cents"], int) and data["reseal_fee_cents"] >= 0


def assert_deliverable(data: dict):
    _assert_common(data)
    assert data["format"] in {"PDF", "DWG", "PAPER"}
    assert data["status"] in {"ASSEMBLED", "RELEASED"}


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["lifecycle_status"] in {"DRAFT", "ISSUED", "CLOSED"}
    assert data["payment_status"] in {"UNPAID", "PARTIAL", "PAID"}
    for fee in ("subtotal_cents", "tax_cents", "total_cents",
                "amount_paid_cents", "balance_due_cents"):
        assert isinstance(data[fee], int), f"{fee} must be an integer (cents)"


def assert_invoice_balance_invariant(data: dict):
    """balance_due_cents must equal total_cents - amount_paid_cents (PRD §3.6)."""
    assert data["balance_due_cents"] == data["total_cents"] - data["amount_paid_cents"], (
        f"balance {data['balance_due_cents']} != total {data['total_cents']} "
        f"- paid {data['amount_paid_cents']}"
    )
