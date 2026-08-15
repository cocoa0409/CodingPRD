"""Entity assertions and domain invariant checkers."""
import re
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# PRD: created_at / updated_at are "ISO 8601 UTC timestamp[s] with three
# fractional digits".
_THREE_FRACTIONAL_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    created = data.get("created_at", "")
    updated = data.get("updated_at", "")
    assert isinstance(created, str) and _THREE_FRACTIONAL_RE.match(created), (
        f"created_at must be ISO 8601 UTC with three fractional digits, got {created!r}")
    assert isinstance(updated, str) and _THREE_FRACTIONAL_RE.match(updated), (
        f"updated_at must be ISO 8601 UTC with three fractional digits, got {updated!r}")
    assert isinstance(data.get("version"), int) and not isinstance(data.get("version"), bool), (
        f"version must be an integer, got {data.get('version')!r}")


def _assert_int(data: dict, field: str):
    assert isinstance(data.get(field), int) and not isinstance(data.get(field), bool), (
        f"{field} must be an integer, got {data.get(field)!r}")


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional digits.

    Clock-stamped domain datetimes (posted_at, received_at, cleared_at,
    expires_at, debriefed_at, barred_until) are pinned by the PRD to the
    logical clock's instant; the fractional-digit rendering is not pinned for
    these fields, so compare instants, not strings.
    """
    assert isinstance(value, str) and value, f"expected a non-empty ISO instant, got {value!r}"
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected_iso: str, label: str = "instant"):
    """Assert two ISO 8601 instants denote the same point in time."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}")


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("ministry_year"), str) and data["ministry_year"]
    assert data.get("status") in ("OPEN", "CLOSED")
    for field in ("scholarship_fund_total_cents", "scholarship_reserved_cents",
                  "scholarship_disbursed_cents", "scholarship_available_cents",
                  "max_award_pct_bp", "per_registration_cap_cents",
                  "default_chaperone_ratio"):
        _assert_int(data, field)
    assert isinstance(data.get("code_of_conduct_text"), str)
    assert isinstance(data.get("discipline_policy_text"), str)


def assert_fund_conserved(program: dict):
    """The scholarship fund triple is conserved after every mutation."""
    total = program["scholarship_reserved_cents"] + \
        program["scholarship_disbursed_cents"] + \
        program["scholarship_available_cents"]
    assert total == program["scholarship_fund_total_cents"], (
        f"fund triple {total} != fund total "
        f"{program['scholarship_fund_total_cents']}")


def assert_trip(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("destination_type") in ("IN_STATE", "OUT_OF_STATE",
                                            "INTERNATIONAL")
    assert data.get("required_insurance_tier") in ("NONE", "DOMESTIC",
                                                   "INTERNATIONAL")
    assert data.get("status") in (
        "DRAFT", "REGISTRATION_OPEN", "REGISTRATION_CLOSED", "ROSTER_LOCKED",
        "IN_PROGRESS", "DEBRIEFED", "CANCELLED")
    for field in ("capacity_youth", "base_cost_cents", "deposit_cents",
                  "chaperone_ratio", "seats_taken", "confirmed_youth_count",
                  "cleared_chaperone_count", "required_cleared_chaperones",
                  "lodging_cost_total_cents",
                  "debrief_actual_participant_count", "debrief_incident_count"):
        _assert_int(data, field)
    assert isinstance(data.get("ratio_compliant"), bool)
    assert isinstance(data.get("emergency_protocol_text"), str)


def assert_participant(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data.get("family_key"), str)
    assert isinstance(data.get("guardian_user_id"), str) and data["guardian_user_id"]
    assert isinstance(data.get("first_name"), str)
    assert isinstance(data.get("last_name"), str)
    _assert_int(data, "grade")
    assert 6 <= data["grade"] <= 12
    assert data.get("annual_income_bracket") in (
        "BAND_A", "BAND_B", "BAND_C", "BAND_D", "UNDISCLOSED")
    _assert_int(data, "household_size")
    assert data["household_size"] >= 1
    assert isinstance(data.get("barred_until"), str)


def assert_registration(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("trip_id", ""))
    assert is_valid_uuid(data.get("participant_id", ""))
    assert isinstance(data.get("guardian_user_id"), str) and data["guardian_user_id"]
    assert data.get("registration_status") in (
        "DRAFT", "SUBMITTED", "APPROVED", "WAITLISTED", "REJECTED", "CONFIRMED",
        "WITHDRAWN", "DISMISSED", "CANCELLED", "COMPLETED")
    assert data.get("payment_status") in (
        "PENDING_DEPOSIT", "PARTIALLY_PAID", "PAID_IN_FULL", "DELINQUENT",
        "REFUNDED")
    assert data.get("insurance_tier") in ("NONE", "DOMESTIC", "INTERNATIONAL")
    for field in ("provisional_cost_share_cents", "final_cost_share_cents",
                  "late_fees_total_cents", "covered_cents", "amount_due_cents",
                  "fundraising_credit_applied_cents", "scholarship_awarded_cents"):
        _assert_int(data, field)
    assert data["amount_due_cents"] >= 0, "amount_due_cents is floored at zero"
    for field in ("conduct_acknowledged", "deposit_late_fee_assessed",
                  "final_late_fee_assessed"):
        assert isinstance(data.get(field), bool), f"{field} must be boolean"


def assert_consent_form(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("registration_id", ""))
    assert data.get("form_type") in ("PARENTAL_CONSENT", "MEDICAL_RELEASE",
                                     "MEDIA_RELEASE", "CONDUCT_AGREEMENT")
    assert data.get("status") in ("SUBMITTED", "VERIFIED", "REJECTED", "VOIDED")
    assert isinstance(data.get("signed_by_name"), str)
    assert is_iso8601_timestamp(data.get("signed_at", ""))
    assert isinstance(data.get("medical_notes"), str)
    assert isinstance(data.get("reviewed_by_user_id"), str)
    assert isinstance(data.get("rejection_reason"), str)


def assert_fundraising_account(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("registration_id", ""))
    assert data.get("status") in ("OPEN", "CLOSED")
    for field in ("goal_cents", "raised_gross_cents", "fee_total_cents",
                  "raised_net_cents", "credit_applied_cents",
                  "available_credit_cents"):
        _assert_int(data, field)
    assert data["raised_net_cents"] == data["raised_gross_cents"] - data["fee_total_cents"]
    assert data["available_credit_cents"] == data["raised_net_cents"] - data["credit_applied_cents"]
    assert isinstance(data.get("goal_met"), bool)


def assert_donation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("fundraising_account_id", ""))
    assert isinstance(data.get("donor_name"), str)
    _assert_int(data, "amount_cents")
    assert data["amount_cents"] > 0
    assert data.get("channel") in ("CASH", "CHECK", "CARD_ONLINE")
    _assert_int(data, "fee_cents")
    assert data.get("status") in ("RECEIVED", "APPLIED", "REFUNDED")
    assert is_iso8601_timestamp(data.get("received_at", ""))


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("registration_id", ""))
    _assert_int(data, "amount_cents")
    assert data["amount_cents"] > 0
    assert data.get("method") in ("CASH", "CHECK", "CARD_ONLINE")
    assert data.get("status") in ("POSTED", "REFUNDED")
    assert is_iso8601_timestamp(data.get("posted_at", ""))


def assert_scholarship_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("registration_id", ""))
    _assert_int(data, "requested_cents")
    assert data["requested_cents"] > 0
    _assert_int(data, "need_score")
    assert 0 <= data["need_score"] <= 100
    _assert_int(data, "award_cents")
    assert data["award_cents"] >= 0
    assert data.get("status") in ("UNDER_REVIEW", "APPROVED", "DENIED",
                                  "DISBURSED", "RESCINDED", "RETURNED",
                                  "WITHDRAWN")
    assert isinstance(data.get("approved_by_user_id"), str)
    assert isinstance(data.get("disbursed_by_user_id"), str)
    assert isinstance(data.get("decision_reason"), str)


def assert_chaperone(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data.get("first_name"), str)
    assert isinstance(data.get("last_name"), str)
    assert isinstance(data.get("email"), str)
    assert isinstance(data.get("phone"), str)
    assert isinstance(data.get("current_screening_expires_at"), str)


def assert_background_check(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("chaperone_id", ""))
    assert data.get("status") in ("INITIATED", "SCREENING", "CLEARED",
                                  "FLAGGED", "EXPIRED")
    assert isinstance(data.get("vendor_reference"), str)
    assert isinstance(data.get("cleared_at"), str)
    assert isinstance(data.get("expires_at"), str)


def assert_chaperone_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("trip_id", ""))
    assert is_valid_uuid(data.get("chaperone_id", ""))
    assert data.get("role") in ("LEAD", "SUPPORT")
    assert data.get("status") in ("PROPOSED", "CONFIRMED", "DECLINED",
                                  "REMOVED")
    assert isinstance(data.get("removal_reason"), str)


def assert_itinerary_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("trip_id", ""))
    assert data.get("segment_type") in ("TRAVEL", "LODGING", "SERVICE",
                                        "MEAL", "FREE")
    assert isinstance(data.get("title"), str)
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data.get("location"), str)
    assert isinstance(data.get("vehicle_code"), str)


def assert_lodging_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("trip_id", ""))
    assert isinstance(data.get("site_name"), str)
    assert isinstance(data.get("room_code"), str)
    assert isinstance(data.get("check_in_date"), str)
    assert isinstance(data.get("check_out_date"), str)
    _assert_int(data, "room_capacity")
    assert data["room_capacity"] >= 1
    _assert_int(data, "cost_cents")
    assert data["cost_cents"] >= 0
    assert data.get("status") in ("CONFIRMED", "CANCELLED")
