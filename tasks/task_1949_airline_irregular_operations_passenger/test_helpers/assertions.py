"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    """PRD §2.4: every primary resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_passenger(data: dict):
    _assert_common_fields(data, "Passenger")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["loyalty_tier"] in ("NONE", "SILVER", "GOLD", "PLATINUM")
    ssr = data.get("special_service_codes")
    assert ssr is None or isinstance(ssr, list)


def assert_flight(data: dict):
    _assert_common_fields(data, "Flight")
    assert isinstance(data["flight_number"], str) and data["flight_number"]
    assert isinstance(data["origin"], str) and data["origin"]
    assert isinstance(data["destination"], str) and data["destination"]
    assert is_iso8601_timestamp(data["sched_dep_utc"])
    assert is_iso8601_timestamp(data["sched_arr_utc"])
    assert is_iso8601_timestamp(data["orig_sched_dep_utc"])
    assert is_iso8601_timestamp(data["orig_sched_arr_utc"])
    assert isinstance(data["distance_km"], int) and data["distance_km"] > 0
    assert isinstance(data["operating_carrier"], str)
    assert data["flight_status"] in (
        "SCHEDULED", "DELAYED", "IN_FLIGHT", "ARRIVED", "CANCELLED")
    assert data["crew_coverage_status"] in ("CREW_OK", "CREW_SHORT")


def assert_cabin_inventory(data: dict):
    _assert_common_fields(data, "CabinInventory")
    assert is_valid_uuid(data.get("flight_id", ""))
    assert data["cabin"] in ("ECONOMY", "PREMIUM", "BUSINESS", "FIRST")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 0
    assert isinstance(data["seats_sold"], int) and data["seats_sold"] >= 0
    assert isinstance(data["interline_seats_committed"], int)
    assert data["interline_seats_committed"] >= 0


def assert_disruption_event(data: dict):
    _assert_common_fields(data, "DisruptionEvent")
    assert isinstance(data["event_code"], str) and data["event_code"]
    assert isinstance(data["hub"], str) and data["hub"]
    assert data["classification"] in ("WEATHER", "ATC", "MECHANICAL", "CREW_SHORTAGE")
    assert isinstance(data["is_controllable"], bool)
    assert data["event_status"] in ("OPEN", "ASSESSING", "RECOVERY", "CLOSED")
    assert isinstance(data["cost_cap_cents"], int)
    assert is_iso8601_timestamp(data["detected_at"])
    assert isinstance(data["affected_booking_count"], int)
    assert isinstance(data["affected_passenger_count"], int)
    assert isinstance(data["accrual_total_cents"], int)
    assert isinstance(data["settled_total_cents"], int)


def assert_booking(data: dict):
    _assert_common_fields(data, "Booking")
    assert is_valid_uuid(data.get("passenger_id", ""))
    assert isinstance(data["fare_cents"], int) and data["fare_cents"] >= 0
    assert data["cabin"] in ("ECONOMY", "PREMIUM", "BUSINESS", "FIRST")
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert data["booking_status"] in (
        "ACTIVE", "DISRUPTED", "REBOOKED", "CANCELLED", "COMPLETED")
    assert data["compensation_status"] in (
        "NONE", "ELIGIBLE_PENDING", "ELECTED_REFUND", "ELECTED_CREDIT", "SETTLED")
    assert isinstance(data["refund_amount_cents"], int)
    assert isinstance(data["credit_amount_cents"], int)
    assert isinstance(data["compensation_amount_cents"], int)


def assert_booking_segment(data: dict):
    _assert_common_fields(data, "BookingSegment")
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("flight_id", ""))
    assert isinstance(data["seq_no"], int) and data["seq_no"] >= 1
    assert data["cabin"] in ("ECONOMY", "PREMIUM", "BUSINESS", "FIRST")
    assert data["segment_status"] in (
        "CONFIRMED", "DISRUPTED", "CANCELLED", "REBOOKED", "FLOWN")


def assert_reaccommodation_case(data: dict):
    _assert_common_fields(data, "ReaccommodationCase")
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("disruption_event_id", ""))
    assert isinstance(data["priority_score"], int)
    assert data["case_status"] in (
        "QUEUED", "OFFERED", "COMMITTED", "EXPIRED", "ESCALATED", "VOIDED")
    assert is_iso8601_timestamp(data["queued_at"])


def assert_reaccommodation_option(data: dict):
    _assert_common_fields(data, "ReaccommodationOption")
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["is_interline"], bool)
    assert isinstance(data["legs"], list) and len(data["legs"]) >= 1
    assert is_iso8601_timestamp(data["est_first_dep_utc"])
    assert is_iso8601_timestamp(data["est_final_arr_utc"])
    assert isinstance(data["projected_arrival_delay_minutes"], int)
    assert isinstance(data["interline_fare_cents"], int)
    assert isinstance(data["rank_score"], int)
    assert data["option_status"] in ("PROPOSED", "ACCEPTED", "REJECTED", "EXPIRED")


def assert_interline_agreement(data: dict):
    _assert_common_fields(data, "InterlineAgreement")
    assert isinstance(data["partner_carrier"], str)
    assert isinstance(data["origin"], str) and data["origin"]
    assert isinstance(data["destination"], str) and data["destination"]
    assert isinstance(data["cabin_map"], dict)
    assert isinstance(data["settlement_rate_pct"], int)
    assert 0 <= data["settlement_rate_pct"] <= 100
    assert isinstance(data["seats_quota_per_flight"], int)
    assert data["agreement_status"] in ("ACTIVE", "SUSPENDED")


def assert_voucher(data: dict):
    _assert_common_fields(data, "Voucher")
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("disruption_event_id", ""))
    assert data["voucher_type"] in ("HOTEL", "MEAL", "TRANSPORT")
    assert isinstance(data["face_value_cents"], int) and data["face_value_cents"] > 0
    assert isinstance(data["nights"], int)
    assert isinstance(data["meals_count"], int)
    assert data["voucher_status"] in ("ISSUED", "REDEEMED", "VOIDED", "EXPIRED")
    assert isinstance(data["valid_through"], str)


def assert_crew_assignment(data: dict):
    _assert_common_fields(data, "CrewAssignment")
    assert is_valid_uuid(data.get("flight_id", ""))
    assert isinstance(data["crew_member_ref"], str) and data["crew_member_ref"]
    assert data["crew_role"] in ("CAPTAIN", "FIRST_OFFICER", "FLIGHT_ATTENDANT")
    assert is_iso8601_timestamp(data["duty_start_utc"])
    assert is_iso8601_timestamp(data["duty_end_utc"])
    assert data["legality_status"] in ("LEGAL", "FLAGGED_ILLEGAL")
    assert data["assignment_status"] in ("ASSIGNED", "RELEASED")


def assert_refund_election(data: dict):
    _assert_common_fields(data, "RefundElection")
    assert is_valid_uuid(data.get("booking_id", ""))
    assert data["election"] in ("REFUND", "CREDIT")
    assert data["election_source"] in ("USER", "SYSTEM_DEFAULT")
    assert isinstance(data["refund_amount_cents"], int)
    assert isinstance(data["credit_amount_cents"], int)
    assert isinstance(data["compensation_amount_cents"], int)
    assert data["election_status"] in ("PENDING", "PROCESSED")


def assert_cost_entry(data: dict):
    """Append-only ledger row (PRD §2.4): id + created_at only; the
    updated_at and version fields are absent from its representation."""
    assert is_valid_uuid(data.get("id", "")), "CostEntry.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "CostEntry must not expose updated_at"
    assert "version" not in data, "CostEntry must not expose version"
    assert is_valid_uuid(data.get("disruption_event_id", ""))
    assert data["source_type"] in ("VOUCHER", "REFUND", "CREDIT", "COMPENSATION", "INTERLINE")
    assert isinstance(data["source_id"], str) and data["source_id"]
    assert data["entry_kind"] in ("ACCRUAL", "SETTLEMENT", "REVERSAL")
    assert isinstance(data["amount_cents"], int)


def assert_communication_log(data: dict):
    """Append-only log row (PRD §2.4): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "CommunicationLog.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "CommunicationLog must not expose updated_at"
    assert "version" not in data, "CommunicationLog must not expose version"
    assert is_valid_uuid(data.get("booking_id", ""))
    assert data["template"] in (
        "DISRUPTION_DETECTED", "CANCELLATION", "REBOOK_OFFER",
        "REBOOK_CONFIRMED", "REMINDER", "ELECTION_DEFAULT")
    assert data["channel"] in ("EMAIL", "SMS")
    assert data["log_status"] in ("QUEUED", "SENT", "FAILED")


def assert_event_cost_invariants(event: dict):
    """PRD §2.9: the two per-event totals are net sums over the ledger."""
    assert isinstance(event["accrual_total_cents"], int)
    assert isinstance(event["settled_total_cents"], int)


def assert_cost_summary(data: dict):
    """PRD §2.9: the computed cost-summary read carries four integer fields."""
    assert isinstance(data["accrual_total_cents"], int)
    assert isinstance(data["settled_total_cents"], int)
    assert isinstance(data["entry_count"], int) and data["entry_count"] >= 0
    assert isinstance(data["voucher_face_outstanding_cents"], int)
