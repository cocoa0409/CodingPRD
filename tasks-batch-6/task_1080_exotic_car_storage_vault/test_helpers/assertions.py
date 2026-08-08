"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7, §3.9)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')}"


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["total_units"], int)
    for f in ("units_available", "units_reserved", "units_occupied", "units_out_of_service"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be non-negative int"


def assert_facility_counter_invariant(data: dict, expected_total_units_created: int):
    """§2.7: the four counters always sum to the total number of units under the facility."""
    total = (data["units_available"] + data["units_reserved"]
             + data["units_occupied"] + data["units_out_of_service"])
    assert total == expected_total_units_created, (
        f"unit counters must sum to {expected_total_units_created} units created, got {total}"
    )


def assert_storage_unit(data: dict):
    _assert_common(data)
    assert data["unit_class"] in ("STANDARD", "CLIMATE", "SHOWCASE")
    assert data["status"] in ("AVAILABLE", "RESERVED", "OCCUPIED", "OUT_OF_SERVICE")
    assert isinstance(data["climate_controlled"], bool)
    assert isinstance(data["monthly_rate_cents"], int) and data["monthly_rate_cents"] >= 0


def assert_member(data: dict):
    _assert_common(data)
    assert data["membership_tier"] in ("BRONZE", "SILVER", "GOLD", "PLATINUM")
    assert data["billing_status"] in ("CURRENT", "PAST_DUE", "SUSPENDED")
    for f in ("charged_cents", "paid_cents", "held_cents", "account_balance_cents"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["account_balance_cents"] == data["charged_cents"] - data["paid_cents"], (
        "account_balance_cents must equal charged_cents - paid_cents"
    )


def assert_vehicle(data: dict):
    _assert_common(data)
    assert data["fuel_type"] in ("ICE", "HYBRID", "EV")
    assert data["condition_status"] in ("INTAKE_PENDING", "DOCUMENTED", "DAMAGE_HOLD")
    assert data["insurance_status"] in ("NONE", "ACTIVE", "LAPSED")
    assert isinstance(data["declared_value_cents"], int) and data["declared_value_cents"] >= 0


def assert_coi(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")
    assert isinstance(data["coverage_amount_cents"], int) and data["coverage_amount_cents"] >= 0


def assert_agreement(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "IN_STORAGE", "CHECKED_OUT", "CLOSED", "CANCELLED")
    assert isinstance(data["monthly_rate_cents"], int)


def assert_monitoring(data: dict):
    _assert_common(data)
    assert data["monitor_type"] in ("BATTERY_TENDER", "CLIMATE", "BOTH")
    assert data["status"] in ("ACTIVE", "CANCELLED")
    assert isinstance(data["low_battery_alert"], bool)


def assert_service_order(data: dict):
    _assert_common(data)
    assert data["service_type"] in ("DETAIL", "START_ENGINE", "CHECKOUT", "CHECKIN", "FUEL")
    assert data["status"] in (
        "REQUESTED", "APPROVED", "REJECTED", "IN_PROGRESS", "ON_HOLD", "COMPLETED", "CANCELLED"
    )


def assert_transporter(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0


def assert_delivery_job(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "OUT_FOR_EVENT", "RETURNED", "CANCELLED")


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert data["status"] in ("WAITING", "OFFERED", "CLAIMED", "EXPIRED", "CANCELLED")
    assert data["desired_unit_class"] in ("STANDARD", "CLIMATE", "SHOWCASE")


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["inspection_type"] in ("INTAKE", "PERIODIC", "CHECKOUT")
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID")
    assert data["proration_mode"] in ("FULL_MONTH", "PRORATED")
    assert isinstance(data["line_items"], list)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"] + data["tax_cents"], (
        "total_cents must equal subtotal_cents + tax_cents"
    )
