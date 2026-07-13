"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    """Common bookkeeping fields on every versioned resource (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def _assert_reference(data: dict):
    """Lightweight reference resources carry only id + created_at (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_participant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["gender"] in ["FEMALE", "MALE", "OTHER", "DECLINED"]
    assert data["ethnicity"] in ["HISPANIC", "NON_HISPANIC", "DECLINED"]
    assert data["race"] in ["WHITE", "BLACK", "ASIAN", "NATIVE", "PACIFIC", "MULTI", "DECLINED"]
    assert data["poverty_status"] in ["BELOW", "AT_OR_ABOVE", "DECLINED"]
    assert isinstance(data["lives_alone"], bool)
    assert isinstance(data["rural"], bool)
    assert isinstance(data["veteran"], bool)
    assert isinstance(data["disability_count"], int) and data["disability_count"] >= 0
    assert data["status"] in ["ACTIVE", "INACTIVE"]
    assert isinstance(data["funded_cents"], int)


def assert_grant_award(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["oaa_title"] in ["IIIB", "IIIC1", "IIIC2", "IIID", "IIIE"]
    assert data["category"] in ["CONGREGATE_MEAL", "TRANSPORTATION", "WELLNESS", "ACTIVITY"]
    assert isinstance(data["authorized_cents"], int) and data["authorized_cents"] > 0
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["available_cents"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED"]


def assert_donation(data: dict):
    _assert_common(data)
    assert isinstance(data["donor_name"], str) and len(data["donor_name"]) > 0
    assert data["category"] in [
        "CONGREGATE_MEAL", "TRANSPORTATION", "WELLNESS", "ACTIVITY", "UNRESTRICTED"
    ]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["remaining_cents"], int) and data["remaining_cents"] >= 0
    assert isinstance(data["restricted"], bool)


def assert_funded_service(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["participant_id"])
    assert data["category"] in ["CONGREGATE_MEAL", "TRANSPORTATION", "WELLNESS", "ACTIVITY"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert is_valid_uuid(data["grant_award_id"])
    assert isinstance(data["billable_cents"], int) and data["billable_cents"] >= 0
    assert isinstance(data["grant_amount_cents"], int) and data["grant_amount_cents"] >= 0
    assert isinstance(data["donation_amount_cents"], int) and data["donation_amount_cents"] >= 0
    assert isinstance(data["unfunded_amount_cents"], int) and data["unfunded_amount_cents"] >= 0
    assert data["funding_status"] in ["FUNDED", "PARTIALLY_FUNDED", "UNFUNDED"]
    assert data["status"] in ["APPLIED", "REVERSED"]


def assert_activity_session(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["category"] in ["ACTIVITY", "WELLNESS"]
    assert is_valid_uuid(data["room_id"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert data["status"] in ["SCHEDULED", "CANCELLED"]


def assert_activity_signup(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["participant_id"])
    assert data["status"] in ["CONFIRMED", "CANCELLED"]


def assert_transportation_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["participant_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["linked_session_id"])
    assert data["eligibility_status"] in ["PENDING", "APPROVED"]
    assert data["trip_status"] in ["SCHEDULED", "COMPLETED"]


def assert_meal_service_day(data: dict):
    _assert_common(data)
    assert isinstance(data["site_name"], str) and len(data["site_name"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert isinstance(data["available_seats"], int)
    assert isinstance(data["served_count"], int) and data["served_count"] >= 0
    assert isinstance(data["provisional_reimbursable_units"], int)
    assert isinstance(data["final_reimbursable_units"], int)
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_meal_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_day_id"])
    assert is_valid_uuid(data["participant_id"])
    assert isinstance(data["suggested_contribution_cents"], int)
    assert data["status"] in ["CONFIRMED", "CANCELLED", "CHECKED_IN"]


def assert_wellness_program(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["model"] in ["CDSMP", "DPP", "ENHANCE_FITNESS", "MATTER_OF_BALANCE"]
    assert isinstance(data["total_sessions"], int) and data["total_sessions"] >= 1
    assert isinstance(data["fidelity_min_sessions"], int) and data["fidelity_min_sessions"] >= 1
    assert data["fidelity_min_sessions"] <= data["total_sessions"]


def assert_wellness_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["participant_id"])
    assert isinstance(data["sessions_attended"], int) and data["sessions_attended"] >= 0
    assert isinstance(data["consecutive_absences"], int) and data["consecutive_absences"] >= 0
    assert isinstance(data["absences_total"], int) and data["absences_total"] >= 0
    assert data["projected_graduation_status"] in ["WILL_GRADUATE", "AT_RISK"]
    assert data["status"] in ["ACTIVE", "LAPSED", "GRADUATED", "WITHDRAWN"]


def assert_volunteer_shift(data: dict):
    _assert_common(data)
    assert isinstance(data["volunteer_name"], str) and len(data["volunteer_name"]) > 0
    assert isinstance(data["role"], str) and len(data["role"]) > 0
    assert float(data["hours"]) > 0


def assert_room(data: dict):
    _assert_reference(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_vehicle(data: dict):
    _assert_reference(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1


# --- Domain invariant checkers ---
def assert_grant_conservation(grant: dict):
    """PRD 2.7: authorized_cents == committed_cents + available_cents at all times."""
    assert (
        grant["authorized_cents"] == grant["committed_cents"] + grant["available_cents"]
    ), (
        f"grant conservation broken: authorized {grant['authorized_cents']} != "
        f"committed {grant['committed_cents']} + available {grant['available_cents']}"
    )


def assert_meal_seat_conservation(day: dict):
    """PRD 3.6: available_seats is always capacity minus reserved_count."""
    assert (
        day["available_seats"] == day["capacity"] - day["reserved_count"]
    ), (
        f"meal seat conservation broken: available_seats {day['available_seats']} != "
        f"capacity {day['capacity']} - reserved_count {day['reserved_count']}"
    )


def assert_donation_remaining_within_amount(donation: dict):
    """PRD 2.7: a donation's remaining_cents never exceeds its original amount_cents."""
    assert (
        0 <= donation["remaining_cents"] <= donation["amount_cents"]
    ), (
        f"donation remaining_cents {donation['remaining_cents']} out of bounds "
        f"[0, {donation['amount_cents']}]"
    )
