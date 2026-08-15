"""Entity assertions and domain invariant checkers.

Ledger-style resources (Payment, FlightLog, WeatherAdvisory) must NOT carry
updated_at or version — PRD section "Common Resource Properties" states both
are absent from these three resources.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def _assert_ledger_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{label} is ledger-style: updated_at must be absent"
    assert "version" not in data, f"{label} is ledger-style: version must be absent"


def assert_aircraft_owner(data: dict):
    _assert_common_fields(data, "AircraftOwner")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["revenue_share_pct"], (int, float))
    assert 0 <= data["revenue_share_pct"] <= 100
    assert isinstance(data["guarantee_cents_per_block_min"], int)
    assert data["guarantee_cents_per_block_min"] >= 0


def assert_aircraft(data: dict):
    _assert_common_fields(data, "Aircraft")
    assert isinstance(data["tail_number"], str) and data["tail_number"]
    assert data["category"] in ("TURBOPROP", "LIGHT_JET", "MIDSIZE_JET", "HEAVY_JET")
    assert isinstance(data["seats"], int) and data["seats"] > 0
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["on_ops_spec"], bool)
    assert isinstance(data["initial_airframe_minutes"], int)
    assert isinstance(data["total_airframe_minutes"], int)
    assert isinstance(data["next_check_due_minutes"], int)
    assert data["status"] in ("AVAILABLE", "IN_TRIP", "MAINTENANCE_HOLD", "GROUNDED")


def assert_crew_member(data: dict):
    _assert_common_fields(data, "CrewMember")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["qualified_categories"], list)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_trip_request(data: dict):
    _assert_common_fields(data, "TripRequest")
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert data["requested_category"] in ("TURBOPROP", "LIGHT_JET", "MIDSIZE_JET", "HEAVY_JET")
    assert isinstance(data["passenger_count"], int)
    assert isinstance(data["international"], bool)
    assert data["status"] in ("QUOTE_DRAFT", "QUOTED", "BOOKED", "DISPATCHED",
                              "COMPLETED", "CANCELLED", "EXPIRED")
    assert data["payment_posture"] in ("UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL",
                                       "REFUNDED_PARTIAL", "REFUNDED_FULL")
    for nullable in ("quoted_total_cents", "deposit_required_cents", "quote_valid_until",
                     "final_total_cents", "cancellation_reason",
                     "cancellation_fee_cents", "refund_cents"):
        assert nullable in data, f"TripRequest.{nullable} key must be present (may be null)"
    assert isinstance(data["collected_cents"], int)


def assert_quote_leg(data: dict):
    _assert_common_fields(data, "QuoteLeg")
    assert isinstance(data["seq_no"], int)
    assert data["leg_type"] in ("REVENUE", "POSITIONING")
    assert isinstance(data["block_minutes"], int) and data["block_minutes"] > 0
    assert isinstance(data["fuel_stop"], bool)


def assert_aircraft_assignment(data: dict):
    _assert_common_fields(data, "AircraftAssignment")
    assert data["status"] in ("TENTATIVE", "CONFIRMED", "RELEASED")
    assert isinstance(data["trip_request_id"], str)
    assert isinstance(data["aircraft_id"], str)


def assert_crew_assignment(data: dict):
    _assert_common_fields(data, "CrewAssignment")
    assert data["duty_role"] in ("PIC", "SIC")
    assert data["status"] in ("PROPOSED", "VETTED", "FLAGGED_ILLEGAL", "RELEASED")
    for nullable in ("duty_legal", "rest_legal", "vetted_at"):
        assert nullable in data, f"CrewAssignment.{nullable} key must be present (may be null)"


def assert_maintenance_window(data: dict):
    _assert_common_fields(data, "MaintenanceWindow")
    assert data["window_type"] in ("INSPECTION_100H", "ANNUAL", "AOG_REPAIR")
    assert data["status"] in ("PLANNED", "ACTIVE", "COMPLETED", "CANCELLED")
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])


def assert_passenger(data: dict):
    _assert_common_fields(data, "Passenger")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["tsa_status"] in ("PENDING", "CLEARED", "DENIED", "EXPIRED")
    assert "screened_at" in data, "Passenger.screened_at key must be present (may be null)"


def assert_overflight_permit(data: dict):
    _assert_common_fields(data, "OverflightPermit")
    assert data["permit_type"] in ("OVERFLIGHT", "LANDING")
    assert isinstance(data["required"], bool)
    assert data["status"] in ("REQUESTED", "GRANTED", "DENIED", "EXPIRED")
    assert "decided_at" in data, "OverflightPermit.decided_at key must be present (may be null)"


def assert_payment(data: dict):
    _assert_ledger_fields(data, "Payment")
    assert data["payment_type"] in ("DEPOSIT", "BALANCE", "REFUND")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] == "POSTED"


def assert_flight_log(data: dict):
    _assert_ledger_fields(data, "FlightLog")
    assert isinstance(data["actual_block_minutes"], int) and data["actual_block_minutes"] > 0
    assert is_iso8601_timestamp(data["departed_at"])
    assert is_iso8601_timestamp(data["arrived_at"])


def assert_owner_statement(data: dict):
    _assert_common_fields(data, "OwnerStatement")
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["standard_share_cents"], int)
    assert isinstance(data["guarantee_floor_cents"], int)
    assert isinstance(data["owner_share_cents"], int)
    assert isinstance(data["operator_retained_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED")
    assert "issued_at" in data, "OwnerStatement.issued_at key must be present (may be null)"


def assert_compliance_finding(data: dict):
    _assert_common_fields(data, "ComplianceFinding")
    assert data["subject_type"] in ("AIRCRAFT", "CREW_MEMBER", "TRIP_REQUEST")
    assert isinstance(data["subject_id"], str) and data["subject_id"]
    assert isinstance(data["finding_code"], str) and data["finding_code"]
    assert isinstance(data["grounding"], bool)
    assert data["status"] in ("OPEN", "RESOLVED")
    assert "resolved_at" in data, "ComplianceFinding.resolved_at key must be present (may be null)"


def assert_weather_advisory(data: dict):
    _assert_ledger_fields(data, "WeatherAdvisory")
    assert data["severity"] in ("SIGMET", "CONVECTIVE", "WINTER", "OTHER")
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])


def assert_statement_conservation(data: dict):
    """Owner statement split invariant (PRD: 'Conservation holds always: owner
    share plus operator retained equals the gross')."""
    assert data["owner_share_cents"] + data["operator_retained_cents"] == data["gross_cents"], (
        f"owner_share {data['owner_share_cents']} + operator_retained "
        f"{data['operator_retained_cents']} != gross {data['gross_cents']}")


def assert_trip_money_invariants(data: dict):
    """Trip money invariants that must hold after any operation."""
    assert isinstance(data["collected_cents"], int)
    if data["status"] != "CANCELLED":
        assert data["collected_cents"] >= 0
    if data["quoted_total_cents"] is not None and data["status"] not in ("CANCELLED", "EXPIRED"):
        if data["payment_posture"] == "PAID_IN_FULL":
            assert data["collected_cents"] >= data["quoted_total_cents"]
