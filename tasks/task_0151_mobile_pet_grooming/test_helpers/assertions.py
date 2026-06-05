"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape of a returned resource against the
PRD's field contract. Domain invariant checkers verify cross-field rules that
must hold after any operation.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_COAT_TYPES = ["SMOOTH", "DOUBLE", "CURLY", "WIRE", "HAIRLESS"]
_SIZE_CLASSES = ["TOY", "SMALL", "MEDIUM", "LARGE", "GIANT"]
_TIER_CODES = ["BATH_ONLY", "FULL_GROOM", "SHOW_CUT"]
_ADDON_CODES = ["DESHED", "NAIL_TRIM", "TEETH_CLEAN"]
_COAT_CONDITIONS = ["NORMAL", "MATTED"]
_BEHAVIORAL_FLAGS = ["CALM", "NERVOUS", "AGGRESSIVE"]
_VAX_STATUS = ["VALID", "EXPIRED"]
_ACCOUNT_STATUS = ["ACTIVE", "SUSPENDED"]
_VACCINE_TYPES = ["RABIES", "BORDETELLA", "DISTEMPER"]
_SKILL_LEVELS = ["JUNIOR", "SENIOR"]
_GROOMER_STATUS = ["AVAILABLE", "OFF_DUTY"]
_ROUTEDAY_STATUS = ["OPEN", "LOCKED", "CLOSED"]
_ROUTESTOP_STATUS = ["RESERVED", "SERVICED", "NO_SHOW", "VOIDED"]
_APPT_STATUS = ["REQUESTED", "QUOTED", "SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED"]
_PLAN_STATUS = ["ACTIVE", "PAUSED", "CANCELLED"]
_FEE_TYPES = ["NO_SHOW", "LATE_CANCEL"]
_SETTLEMENT_STATUS = ["PENDING", "SETTLED", "WAIVED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_breed(data: dict):
    _assert_versioned(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["coat_type"] in _COAT_TYPES
    assert data["size_class"] in _SIZE_CLASSES
    assert isinstance(data["base_service_minutes"], int)
    assert 15 <= data["base_service_minutes"] <= 240


def assert_service_tier(data: dict):
    _assert_versioned(data)
    assert data["code"] in _TIER_CODES
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert float(data["duration_multiplier"]) >= 1.0


def assert_add_on(data: dict):
    _assert_versioned(data)
    assert data["code"] in _ADDON_CODES
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["duration_minutes"], int) and 0 <= data["duration_minutes"] <= 60
    assert isinstance(data["requires_calm"], bool)


def assert_customer(data: dict):
    _assert_versioned(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["service_zip"], str) and len(data["service_zip"]) == 5
    assert isinstance(data["no_show_strikes"], int)
    assert data["account_status"] in _ACCOUNT_STATUS
    assert isinstance(data["outstanding_fee_cents"], int)


def assert_pet(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["breed_id"])
    assert isinstance(data["name"], str)
    assert float(data["weight_lbs"]) > 0
    assert data["coat_condition"] in _COAT_CONDITIONS
    assert data["behavioral_flag"] in _BEHAVIORAL_FLAGS
    assert isinstance(data["muzzle_required"], bool)
    assert data["vaccination_status"] in _VAX_STATUS


def assert_vaccination_record(data: dict):
    # common_fields:false — id + created_at only; must NOT carry version/updated_at.
    _assert_common(data)
    assert is_valid_uuid(data["pet_id"])
    assert data["vaccine_type"] in _VACCINE_TYPES
    assert is_iso8601_timestamp(data["issued_on"])
    assert is_iso8601_timestamp(data["expires_on"])
    assert "version" not in data, "VaccinationRecord is immutable; must not expose version"
    assert "updated_at" not in data, "VaccinationRecord is immutable; must not expose updated_at"


def assert_groomer(data: dict):
    _assert_versioned(data)
    assert isinstance(data["email"], str) and data["email"]
    assert data["skill_level"] in _SKILL_LEVELS
    assert isinstance(data["handles_aggressive"], bool)
    assert data["status"] in _GROOMER_STATUS


def assert_van(data: dict):
    _assert_versioned(data)
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["max_stops"], int) and 1 <= data["max_stops"] <= 20
    assert isinstance(data["has_show_equipment"], bool)


def assert_route_day(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["van_id"])
    assert isinstance(data["coverage_zip"], str) and len(data["coverage_zip"]) == 5
    assert data["status"] in _ROUTEDAY_STATUS
    assert isinstance(data["booked_minutes"], int) and data["booked_minutes"] >= 0


def assert_route_stop(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["route_day_id"])
    assert is_iso8601_timestamp(data["slot_start"])
    assert isinstance(data["scheduled_minutes"], int)
    assert data["status"] in _ROUTESTOP_STATUS


def assert_appointment(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["pet_id"])
    assert is_valid_uuid(data["service_tier_id"])
    assert data["status"] in _APPT_STATUS
    assert isinstance(data["estimated_minutes"], int)
    assert isinstance(data["quoted_price_cents"], int)
    assert isinstance(data["final_price_cents"], int)
    assert isinstance(data["quote_round"], int)


def assert_appointment_add_on(data: dict):
    # common_fields:false — id + created_at only.
    _assert_common(data)
    assert is_valid_uuid(data["appointment_id"])
    assert is_valid_uuid(data["add_on_id"])
    assert isinstance(data["price_cents_snapshot"], int)
    assert "version" not in data, "AppointmentAddOn link is immutable; must not expose version"
    assert "updated_at" not in data, "AppointmentAddOn link is immutable; must not expose updated_at"


def assert_recurring_plan(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["pet_id"])
    assert is_valid_uuid(data["service_tier_id"])
    assert data["cadence_days"] in (28, 42, 56)
    assert 0 <= float(data["discount_pct"]) <= 0.20
    assert data["status"] in _PLAN_STATUS


def assert_fee_charge(data: dict):
    _assert_versioned(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["appointment_id"])
    assert data["fee_type"] in _FEE_TYPES
    assert isinstance(data["amount_cents"], int)
    assert data["settlement_status"] in _SETTLEMENT_STATUS


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_outstanding_matches_pending(customer: dict, pending_fees: list):
    """PRD §3.9 invariant: outstanding_fee_cents == sum of PENDING fee amounts."""
    expected = sum(f["amount_cents"] for f in pending_fees if f["settlement_status"] == "PENDING")
    assert customer["outstanding_fee_cents"] == expected, (
        f"outstanding_fee_cents {customer['outstanding_fee_cents']} != "
        f"sum of PENDING fees {expected}"
    )
