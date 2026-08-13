"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"
    else:
        assert "updated_at" not in data, "append-only record must not carry updated_at"
        assert "version" not in data, "append-only record must not carry version"


def assert_program(data: dict):
    _assert_common(data)
    assert data["program_posture"] in ("ACTIVE", "SUSPENDED", "WINDING_DOWN", "CLOSED")
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert 1 <= data["contract_year_start_month"] <= 12
    assert isinstance(data["peak_day_calendar"], list)


def assert_aircraft_class(data: dict):
    _assert_common(data)
    assert data["hourly_rate_cents"] > 0
    assert data["monthly_fee_base_cents"] > 0
    assert data["interchange_upgrade_multiplier_bp"] >= 10000
    assert data["seats"] > 0


def assert_aircraft(data: dict):
    _assert_common(data)
    assert data["aircraft_status"] in ("IN_SERVICE", "IN_MAINTENANCE", "GROUNDED")
    assert isinstance(data["tail_number"], str) and data["tail_number"]


def assert_owner(data: dict):
    _assert_common(data)
    assert data["owner_standing"] in ("GOOD", "DELINQUENT", "SUSPENDED", "EXITED")
    assert data["deposit_balance_cents"] >= 0, "deposit ledger may never hold a negative balance"


def assert_share(data: dict):
    _assert_common(data)
    assert data["share_status"] in ("PENDING_ACTIVATION", "ACTIVE", "LISTED", "IN_EXIT", "CLOSED")
    assert data["fraction_denominator"] in (4, 8, 16, 32)
    assert 1 <= data["fraction_numerator"] <= data["fraction_denominator"]
    assert data["purchase_price_cents"] > 0


def assert_booking(data: dict):
    _assert_common(data)
    assert data["booking_status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED", "EXPIRED")
    assert data["billing_status"] in ("UNBILLED", "PROVISIONALLY_BILLED", "FINALLY_BILLED")
    assert data["interchange_direction"] in ("NONE", "UPGRADE", "DOWNGRADE")


def assert_flight_leg(data: dict):
    """FlightLeg is append-only: id + created_at only (PRD §2.5)."""
    _assert_common(data, with_version=False)
    assert data["actual_block_hours"] > 0
    assert isinstance(data["peak_day_flag"], bool)


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["invoice_status"] in (
        "OPEN", "ISSUED", "PAID", "PAST_DUE", "DISPUTED", "SETTLED_AFTER_DISPUTE"
    )


def assert_invoice_line(data: dict):
    """InvoiceLine is append-only: id + created_at only (PRD §2.5)."""
    _assert_common(data, with_version=False)
    assert data["line_kind"] in (
        "MANAGEMENT_FEE", "OCCUPIED_HOURS", "PEAK_SURCHARGE",
        "INTERCHANGE_ADJUSTMENT", "MAINTENANCE_ALLOCATION", "DEPRECIATION_PASSTHROUGH",
    )
    assert isinstance(data["amount_cents"], int)


def assert_transfer_listing(data: dict):
    _assert_common(data)
    assert data["listing_status"] in ("LISTED", "UNDER_OFFER", "SOLD", "WITHDRAWN", "EXPIRED")
    assert data["asking_price_cents"] > 0


def assert_maintenance_event(data: dict):
    _assert_common(data)
    assert data["event_status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["cost_cents"] >= 0


def assert_depreciation_schedule(data: dict):
    """DepreciationSchedule is append-only: id + created_at only (PRD §2.5)."""
    _assert_common(data, with_version=False)
    assert data["schedule_method"] in ("STRAIGHT_LINE", "DOUBLE_DECLINING")
    assert data["recovery_years"] in (5, 7)
    assert data["basis_cents"] > 0
    assert data["accumulated_depreciation_cents"] >= 0


def assert_exit_request(data: dict):
    _assert_common(data)
    assert data["exit_status"] in ("SUBMITTED", "VALUED", "APPROVED", "SETTLED", "REJECTED", "WITHDRAWN")
