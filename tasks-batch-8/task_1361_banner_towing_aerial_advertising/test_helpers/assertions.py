"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Immutable evidentiary records (WeatherAssessment,
ProofOfFlight) are asserted to carry id + created_at only per PRD §2.4.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def _assert_immutable_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not carry updated_at (PRD §2.4)"
    assert "version" not in data, f"{entity} must not carry version (PRD §2.4)"


def assert_base(data: dict):
    _assert_common_fields(data, "Base")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_aircraft(data: dict):
    _assert_common_fields(data, "Aircraft")
    assert isinstance(data["tail_number"], str) and data["tail_number"]
    assert data["model"] in ("CITABRIA", "SUPER_CUB", "PAWNEE")
    assert isinstance(data["max_tow_weight_lbs"], int)
    assert isinstance(data["hourly_rate_cents"], int)
    assert data["status"] in ("ACTIVE", "MAINTENANCE", "RETIRED")
    assert data["season_hours_flown"] >= 0


def assert_pilot(data: dict):
    _assert_common_fields(data, "Pilot")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["certificate_number"], str) and data["certificate_number"]
    assert data["tow_endorsement_level"] in ("TRAINEE", "STANDARD", "STADIUM_QUALIFIED")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "INACTIVE")
    assert data["season_hours_flown"] >= 0
    assert isinstance(data["season_pickup_failure_count"], int)
    assert data["season_pickup_failure_count"] >= 0


def assert_route(data: dict):
    _assert_common_fields(data, "Route")
    assert isinstance(data["code"], str) and data["code"]
    assert data["kind"] in ("BEACH", "STADIUM", "FESTIVAL", "PARADE")
    assert data["min_banner_length_ft"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_client(data: dict):
    _assert_common_fields(data, "Client")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["billing_email"], str) and data["billing_email"]
    assert isinstance(data["credit_hold"], bool)
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_campaign(data: dict):
    _assert_common_fields(data, "Campaign")
    assert data["status"] in ("DRAFT", "BOOKED", "IN_FLIGHT", "COMPLETE", "CANCELLED")
    for counter in ("booked_flight_count", "flown_flight_count",
                    "cancelled_weather_count", "unapplied_make_good_cents"):
        assert isinstance(data[counter], int) and data[counter] >= 0, \
            f"Campaign.{counter} must be a non-negative integer"


def assert_airspace_approval(data: dict):
    _assert_common_fields(data, "AirspaceApproval")
    assert data["status"] in ("PENDING", "GRANTED", "DENIED", "REVOKED")
    assert isinstance(data["date_local"], str)
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert isinstance(data["stadium_tfr_waiver"], bool)


def assert_tfr_restriction(data: dict):
    _assert_common_fields(data, "TFRRestriction")
    assert data["status"] in ("PUBLISHED", "CANCELLED")
    assert is_iso8601_timestamp(data["starts_utc"])
    assert is_iso8601_timestamp(data["ends_utc"])


def assert_banner(data: dict):
    _assert_common_fields(data, "Banner")
    assert data["status"] in ("DRAFT", "IN_FABRICATION", "READY", "RETIRED")
    assert isinstance(data["banner_length_ft"], int)
    assert isinstance(data["banner_weight_lbs"], int)
    assert "current_revision_id" in data


def assert_banner_revision(data: dict):
    _assert_common_fields(data, "BannerRevision")
    assert data["status"] in ("PROPOSED", "APPROVED", "ACTIVE", "SUPERSEDED", "REJECTED")
    assert isinstance(data["revision_seq"], int) and data["revision_seq"] >= 1
    assert "supersedes_revision_id" in data


def assert_seasonal_capacity(data: dict):
    _assert_common_fields(data, "SeasonalCapacity")
    assert isinstance(data["aircraft_hour_quota"], int)
    assert isinstance(data["hours_committed"], int)
    assert isinstance(data["hours_remaining"], int)


def assert_flight_slot(data: dict):
    _assert_common_fields(data, "FlightSlot")
    assert data["status"] in ("DRAFT", "BOOKED", "SCHEDULED", "WEATHER_HOLD",
                              "FLOWN", "CANCELLED_CLIENT", "CANCELLED_WEATHER",
                              "CANCELLED_TFR")
    assert isinstance(data["planned_duration_hours"], int)
    assert 1 <= data["planned_duration_hours"] <= 8
    assert isinstance(data["weather_hold_count"], int)
    assert is_iso8601_timestamp(data["planned_start_utc"])


def assert_weather_assessment(data: dict):
    _assert_immutable_fields(data, "WeatherAssessment")
    assert data["verdict"] in ("GO", "MARGINAL", "NO_GO")
    assert isinstance(data["ceiling_ft"], int)
    assert isinstance(data["wind_kts"], int)
    assert is_iso8601_timestamp(data["assessed_at_utc"])


def assert_flight_log(data: dict):
    _assert_common_fields(data, "FlightLog")
    assert data["pickup_technique"] in ("GROUND_PICKUP", "AERIAL_PICKUP")
    assert data["pickup_outcome"] in ("CLEAN", "RETRIED", "FAILED")
    assert data["hobbs_in"] > data["hobbs_out"]
    assert is_iso8601_timestamp(data["filed_at_utc"])


def assert_make_good_credit(data: dict):
    _assert_common_fields(data, "MakeGoodCredit")
    assert data["status"] in ("OPEN", "PARTIALLY_APPLIED", "FULLY_APPLIED", "EXPIRED")
    assert isinstance(data["original_cents"], int) and data["original_cents"] >= 0
    assert isinstance(data["remaining_cents"], int) and data["remaining_cents"] >= 0
    assert data["remaining_cents"] <= data["original_cents"]


def assert_proof_of_flight(data: dict):
    _assert_immutable_fields(data, "ProofOfFlight")
    assert isinstance(data["pilot_attestation"], bool)
    assert isinstance(data["finalized"], bool)
    assert is_iso8601_timestamp(data["submitted_at_utc"])


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert data["status"] in ("ISSUED", "PAID", "VOID")
    for field in ("flight_subtotal_cents", "cancellation_penalty_cents",
                  "make_good_applied_cents", "total_cents", "balance_due_cents"):
        assert isinstance(data[field], int), f"Invoice.{field} must be integer cents"
    assert data["total_cents"] >= 0, "Invoice totals never go below zero (PRD §2.9)"


def assert_invoice_money_invariants(data: dict):
    """PRD §3.8: total = subtotal + penalty - credits, floored at zero."""
    expected = (data["flight_subtotal_cents"] + data["cancellation_penalty_cents"]
                - data["make_good_applied_cents"])
    assert data["total_cents"] == max(0, expected), (
        f"total_cents {data['total_cents']} != max(0, {expected})"
    )
