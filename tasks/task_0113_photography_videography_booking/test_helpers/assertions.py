"""Entity assertions and domain invariant checkers for the
Photography & Videography Booking API.

Field-presence and -type checks follow PRD §2.4 (every entity except ProofSelection
carries id/created_at/updated_at/version; ProofSelection carries only id + created_at).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_mutable(data: dict):
    """id + created_at + updated_at + version for mutable entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be int >= 1, got {data.get('version')!r}"
    )


def _assert_common_immutable(data: dict):
    """id + created_at ONLY for immutable entities (PRD §2.4): no version, no updated_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable resource must NOT carry a version field"
    assert "updated_at" not in data, "immutable resource must NOT carry an updated_at field"


def assert_client(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["status"] in {"ACTIVE", "ARCHIVED"}


def assert_photographer(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["skills"], list) and len(data["skills"]) > 0
    for skill in data["skills"]:
        assert skill in {"PHOTO", "VIDEO", "DRONE", "EDITING"}
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert data["status"] in {"ACTIVE", "INACTIVE"}


def assert_session_package(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["name"], str)
    assert data["session_type"] in {"PORTRAIT", "WEDDING", "EVENT", "COMMERCIAL", "PRODUCT"}
    assert data["tier"] in {"BASIC", "STANDARD", "PREMIUM"}
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] > 0
    assert data["included_shoot_hours"] > 0
    assert isinstance(data["overage_hourly_rate_cents"], int) and data["overage_hourly_rate_cents"] >= 0
    assert isinstance(data["included_edited_images"], int) and data["included_edited_images"] >= 0
    assert 0 < data["deposit_pct"] <= 1
    assert isinstance(data["requires_model_release"], bool)
    assert isinstance(data["active"], bool)


def assert_booking(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["package_id"])
    assert is_valid_uuid(data["lead_photographer_id"])
    assert data["requested_shoot_hours"] > 0
    assert data["workflow_status"] in {
        "DRAFT", "CONFIRMED", "SHOT", "DELIVERED", "CLOSED", "CANCELLED",
    }
    assert data["payment_status"] in {"UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUND_PENDING"}
    assert isinstance(data["total_fee_cents"], int)
    assert isinstance(data["deposit_due_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["cancellation_fee_cents"], int)


def assert_booking_money_invariants(data: dict):
    """Money invariants that must hold on any booking (PRD §3.2):
    balance_due is total - amount_paid floored at 0, and every monetary field is
    a whole-cent integer."""
    for field in (
        "total_fee_cents", "deposit_due_cents", "amount_paid_cents",
        "balance_due_cents", "cancellation_fee_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["balance_due_cents"] >= 0, "balance_due_cents floors at 0"
    expected_balance = max(0, data["total_fee_cents"] - data["amount_paid_cents"])
    assert data["balance_due_cents"] == expected_balance, (
        f"balance_due_cents should be max(0, total-paid)={expected_balance}, "
        f"got {data['balance_due_cents']}"
    )


def assert_payment(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["booking_id"])
    assert data["kind"] in {"DEPOSIT", "BALANCE", "REFUND"}
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in {"PENDING", "SETTLED", "FAILED"}


def assert_contract(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["booking_id"])
    assert isinstance(data["includes_model_release"], bool)
    assert data["status"] in {"DRAFT", "SENT", "SIGNED", "VOID"}


def assert_shoot_schedule(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["booking_id"])
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert data["status"] in {"SCHEDULED", "RESCHEDULED", "COMPLETED", "CANCELLED"}
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0
    if data.get("reschedule_reason") is not None:
        assert data["reschedule_reason"] in {"WEATHER", "CLIENT_REQUEST", "PHOTOGRAPHER_REQUEST"}


def assert_second_shooter_assignment(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["shoot_schedule_id"])
    assert is_valid_uuid(data["photographer_id"])
    assert data["billable_hours"] >= 0
    assert isinstance(data["assignment_fee_cents"], int) and data["assignment_fee_cents"] >= 0
    assert data["status"] in {"ASSIGNED", "RELEASED"}


def assert_gallery(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["booking_id"])
    assert isinstance(data["delivered_image_count"], int) and data["delivered_image_count"] >= 0
    assert data["status"] in {"PENDING_UPLOAD", "PROOFING", "REVISION_REQUESTED", "FINALIZED"}
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_proof_selection(data: dict):
    """ProofSelection is immutable: id + created_at only (PRD §2.4)."""
    _assert_common_immutable(data)
    assert is_valid_uuid(data["gallery_id"])
    assert isinstance(data["selected_image_count"], int) and data["selected_image_count"] >= 1
    assert isinstance(data["round_index"], int) and data["round_index"] >= 0


def assert_add_on_order(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["booking_id"])
    assert data["line_kind"] in {"PRINT", "ALBUM"}
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["line_total_cents"], int)
    assert data["status"] in {"ORDERED", "CANCELLED"}


def assert_license_grant(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["booking_id"])
    assert data["usage_scope"] in {"PERSONAL", "COMMERCIAL", "EDITORIAL", "EXCLUSIVE"}
    assert data["territory"] in {"LOCAL", "NATIONAL", "WORLDWIDE"}
    assert isinstance(data["term_months"], int) and data["term_months"] >= 0
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in {"ACTIVE", "REVOKED"}
