"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the shape and field types of a resource payload
against the PRD. Domain invariant checkers enforce the conserved-quantity
relationships stated in §2.6.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common_mutable(data: dict):
    """Common fields for mutable resources (§2.4): id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_provider(data: dict):
    _common_mutable(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["role_kind"] in ("INJECTOR", "MEDICAL_DIRECTOR")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["open_complication_count"], int)
    assert isinstance(data["resolved_complication_count"], int)
    assert isinstance(data["committed_session_count"], int)


def assert_membership_package(data: dict):
    _common_mutable(data)
    assert data["tier"] in ("BASIC", "PLUS", "VIP")
    assert isinstance(data["member_discount_pct"], (int, float))
    assert 0 <= data["member_discount_pct"] < 1
    assert data["loyalty_program"] in ("ALLE", "ASPIRE")
    assert isinstance(data["monthly_fee_cents"], int)


def assert_injectable_lot(data: dict):
    _common_mutable(data)
    assert data["product"] in ("BOTOX", "DYSPORT", "JUVEDERM", "RESTYLANE")
    assert isinstance(data["lot_number"], str)
    assert is_iso8601_timestamp(data["expiration_date"])
    assert isinstance(data["total_units"], int)
    assert isinstance(data["reserved_units"], int)
    assert isinstance(data["consumed_units"], int)
    assert isinstance(data["remaining_units"], int)
    assert data["status"] in ("AVAILABLE", "QUARANTINED")
    assert_lot_conserved(data)


def assert_patient(data: dict):
    _common_mutable(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_iso8601_timestamp(data["date_of_birth"])
    assert isinstance(data["photo_consent_on_file"], bool)


def assert_loyalty_account(data: dict):
    _common_mutable(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["program"] in ("ALLE", "ASPIRE")
    assert isinstance(data["points_earned"], int)
    assert isinstance(data["points_redeemed"], int)
    assert isinstance(data["points_balance"], int)
    assert_loyalty_conserved(data)


def assert_consultation(data: dict):
    _common_mutable(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["exam_provider_id"])
    assert data["status"] in ("DRAFT", "EXAM_COMPLETE", "VOID")


def assert_standing_order(data: dict):
    _common_mutable(data)
    assert is_valid_uuid(data["consultation_id"])
    assert is_valid_uuid(data["director_provider_id"])
    assert data["product"] in ("BOTOX", "DYSPORT", "JUVEDERM", "RESTYLANE")
    assert isinstance(data["max_units_authorized"], int)
    assert is_iso8601_timestamp(data["valid_until_utc"])
    assert data["status"] in ("SIGNED", "REVOKED")


def assert_treatment_plan(data: dict):
    _common_mutable(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["consultation_id"])
    assert data["product"] in ("BOTOX", "DYSPORT", "JUVEDERM", "RESTYLANE")
    assert isinstance(data["planned_sessions"], int)
    assert isinstance(data["planned_units_per_session"], int)
    assert isinstance(data["list_price_per_unit_cents"], int)
    assert isinstance(data["required_deposit_cents"], int)
    assert isinstance(data["deposit_paid_cents"], int)
    assert isinstance(data["provisional_series_cost_cents"], int)
    assert isinstance(data["finalized_series_cost_cents"], int)
    assert isinstance(data["sessions_committed"], int)
    assert data["status"] in ("PROPOSED", "ACTIVE", "COMPLETED", "CANCELLED")


def assert_deposit(data: dict):
    _common_mutable(data)
    assert is_valid_uuid(data["treatment_plan_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("POSTED", "REFUNDED")


def assert_treatment_session(data: dict):
    _common_mutable(data)
    assert is_valid_uuid(data["treatment_plan_id"])
    assert is_valid_uuid(data["standing_order_id"])
    assert is_valid_uuid(data["injector_provider_id"])
    assert isinstance(data["planned_units"], int)
    assert isinstance(data["final_charge_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["points_earned_cents_basis"], int)
    assert data["status"] in (
        "BOOKED", "COMMITTED", "RESOLVED", "COMPLICATION_OPEN", "CANCELLED", "NO_SHOW",
    )


def assert_complication_case(data: dict):
    _common_mutable(data)
    assert is_valid_uuid(data["treatment_session_id"])
    assert is_valid_uuid(data["injector_provider_id"])
    assert data["severity"] in ("MINOR", "MODERATE", "SEVERE")
    assert isinstance(data["touchup_rounds"], int)
    assert isinstance(data["refund_cents"], int)
    assert data["status"] in ("OPEN", "IN_TOUCHUP", "RESOLVED")


def assert_consent_photo(data: dict):
    """ConsentPhoto is immutable (§2.4): only id + created_at, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ConsentPhoto must NOT carry a version field (§2.4)"
    assert "updated_at" not in data, "ConsentPhoto must NOT carry an updated_at field (§2.4)"


# --------------------------------------------------------------------------
# Domain invariant checkers (§2.6 conserved quantities)
# --------------------------------------------------------------------------
def assert_lot_conserved(lot: dict):
    """§2.6: remaining_units == total_units - reserved_units - consumed_units."""
    expected = lot["total_units"] - lot["reserved_units"] - lot["consumed_units"]
    assert lot["remaining_units"] == expected, (
        f"Lot conservation violated: remaining={lot['remaining_units']} "
        f"but total-reserved-consumed={expected}"
    )


def assert_loyalty_conserved(account: dict):
    """§2.6: points_balance == points_earned - points_redeemed."""
    expected = account["points_earned"] - account["points_redeemed"]
    assert account["points_balance"] == expected, (
        f"Loyalty conservation violated: balance={account['points_balance']} "
        f"but earned-redeemed={expected}"
    )
