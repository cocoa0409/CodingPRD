"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the system-managed identity fields and the
field shapes the PRD promises. Domain invariant checkers verify cross-field
rules that must hold after any operation.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id/created_at/updated_at/version for full first-class entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_shop_location(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_state_tint_regulation(data: dict):
    """StateTintRegulation carries ONLY id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["state_code"], str)
    assert isinstance(data["front_side_min_vlt_pct"], int)
    assert isinstance(data["medical_exemption_allowed"], bool)


def assert_film_material(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str)
    assert data["category"] in ("TINT_FILM", "PPF_FILM", "WRAP_VINYL", "CERAMIC_COATING")
    assert isinstance(data["cure_hours"], int)
    assert isinstance(data["price_multiplier_bps"], int)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_service_package(data: dict):
    _assert_common(data)
    assert data["service_type"] in ("TINT", "PPF", "WRAP", "CERAMIC")
    assert isinstance(data["base_rate_cents"], int)
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert isinstance(data["cure_buffer_minutes"], int)
    assert isinstance(data["warranty_days"], int)
    assert isinstance(data["requires_proof"], bool)


def assert_vehicle_profile(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_user_id"], str)
    assert isinstance(data["vin"], str)
    assert data["size_class"] in ("SEDAN", "SUV", "TRUCK")
    assert isinstance(data["size_surcharge_cents"], int)


def assert_fleet_account(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str)
    assert isinstance(data["fleet_manager_user_id"], str)
    assert isinstance(data["discount_bps"], int)
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["held_credit_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_quote(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PRICED", "ACCEPTED", "CONVERTED", "EXPIRED", "VOIDED")
    for f in ("subtotal_cents", "discount_cents", "net_cents", "rush_fee_cents",
              "total_due_cents", "deposit_required_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_quote_line(data: dict):
    _assert_common(data)
    assert data["coverage"] in ("FULL", "PARTIAL", "ACCENT")
    assert data["window_position"] in (
        "FRONT_SIDE", "REAR_SIDE", "REAR_WINDOW", "WINDSHIELD", "BODY_PANEL")
    assert data["status"] in ("INCLUDED", "REMOVED")
    assert isinstance(data["line_total_cents"], int)


def assert_medical_exemption(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED", "REVOKED")
    assert isinstance(data["exempt_min_vlt_pct"], int)


def assert_bay(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str)
    assert isinstance(data["reserved_minutes"], int)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_installer(data: dict):
    _assert_common(data)
    assert isinstance(data["certified_service_types"], list)
    assert data["status"] in ("AVAILABLE", "OFF_DUTY")


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["install_status"] in (
        "SCHEDULED", "IN_PROGRESS", "CURING", "COMPLETED", "CANCELLED")
    assert data["payment_status"] in (
        "DEPOSIT_DUE", "DEPOSIT_PAID", "INVOICED", "SETTLED")
    assert data["primary_service_type"] in ("TINT", "PPF", "WRAP", "CERAMIC")
    assert isinstance(data["total_due_cents"], int)
    assert isinstance(data["duration_minutes"], int)
    assert isinstance(data["cure_buffer_minutes"], int)


def assert_wrap_proof(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PROOF_SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "REJECTED")
    assert isinstance(data["revision_round"], int)


def assert_callback_ticket(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "RESOLVED", "CLOSED")
    assert data["reason"] in ("BUBBLING", "PEELING", "COLOR_MISMATCH", "MEASUREMENT_ERROR")
