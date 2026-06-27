"""Entity assertions and domain invariant checkers for the Climbing Gym Belay API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, versioned: bool = True):
    """id + created_at always; updated_at + version only on versioned resources."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            "version must be an int >= 1"


def assert_member(data: dict):
    _assert_common(data, versioned=True)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["is_youth"], bool)
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents is never negative"
    assert data["status"] in ("ACTIVE", "DEACTIVATED")


def assert_waiver(data: dict):
    # Waiver is common_fields:false — id + created_at only, no updated_at/version.
    _assert_common(data, versioned=False)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be valid UUID"
    assert data["status"] in ("VALID", "EXPIRED")
    assert "version" not in data, "Waiver must not carry a version field"
    assert "updated_at" not in data, "Waiver must not carry an updated_at field"


def assert_membership(data: dict):
    _assert_common(data, versioned=True)
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["plan_tier"] in ("BASIC", "YOUTH_TEAM")
    assert isinstance(data["monthly_fee_cents"], int)
    assert data["billing_status"] in ("CURRENT", "PAST_DUE", "CANCELLED")
    assert data["access_status"] in ("ACTIVE", "FROZEN", "SUSPENDED", "TERMINATED")


def assert_certification(data: dict):
    _assert_common(data, versioned=True)
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["discipline"] in ("BELAY", "LEAD")
    assert data["status"] in ("REGISTERED", "PASSED", "FAILED", "EXPIRED", "REVOKED")


def assert_facility(data: dict):
    _assert_common(data, versioned=True)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["floor_capacity"], int) and data["floor_capacity"] >= 1
    assert isinstance(data["occupancy"], int) and data["occupancy"] >= 0
    assert isinstance(data["requires_belay_cert"], bool)


def assert_route(data: dict):
    _assert_common(data, versioned=True)
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["grade"], int) and 0 <= data["grade"] <= 10
    assert data["style"] in ("SLAB", "OVERHANG", "ROOF")
    assert isinstance(data["difficulty_points"], int)
    assert data["status"] in ("OPEN", "STRIPPED")


def assert_checkin(data: dict):
    _assert_common(data, versioned=True)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["entry_kind"] in ("MEMBERSHIP", "DAY_PASS")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert data["status"] in ("ON_FLOOR", "CHECKED_OUT")


def assert_clinic(data: dict):
    _assert_common(data, versioned=True)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_enrollment(data: dict):
    # Enrollment is common_fields:false — id + created_at only, no updated_at/version.
    _assert_common(data, versioned=False)
    assert is_valid_uuid(data.get("clinic_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["status"] in ("ENROLLED", "WITHDRAWN")
    assert "version" not in data, "Enrollment must not carry a version field"
    assert "updated_at" not in data, "Enrollment must not carry an updated_at field"


def assert_rental(data: dict):
    _assert_common(data, versioned=True)
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["item_kind"] in ("HARNESS", "SHOES", "ROPE")
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0
    assert data["status"] in ("OUT", "RETURNED", "LOST")


def assert_incident(data: dict):
    _assert_common(data, versioned=True)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["severity"] in ("MINOR", "SERIOUS")
    assert data["status"] in ("OPEN", "RESOLVED")


def assert_deposit_conservation(rental: dict):
    """Conserved-quantity invariant: late_fee + refund == deposit, to the cent."""
    assert rental["late_fee_cents"] + rental["refund_cents"] == rental["deposit_cents"], (
        f"deposit conservation violated: "
        f"{rental['late_fee_cents']} + {rental['refund_cents']} "
        f"!= {rental['deposit_cents']}"
    )
