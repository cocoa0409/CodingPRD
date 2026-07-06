"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_venue(data: dict):
    assert is_valid_uuid(data.get("id", "")), "venue id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["venue_type"] in {"DOME", "THEATER", "GALLERY", "CLASSROOM", "RENTAL_HALL"}
    assert isinstance(data["seated_capacity"], int) and data["seated_capacity"] >= 1
    assert isinstance(data["turnover_buffer_minutes"], int) and data["turnover_buffer_minutes"] >= 0
    assert isinstance(data["accessible_seats"], int) and data["accessible_seats"] >= 0
    assert data["accessible_seats"] <= data["seated_capacity"]
    assert data["status"] == "ACTIVE"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_membership(data: dict):
    assert is_valid_uuid(data.get("id", "")), "membership id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["tier"] in {"INDIVIDUAL", "FAMILY", "PATRON"}
    assert isinstance(data["astc_eligible"], bool)
    assert data["status"] in {"PENDING", "ACTIVE", "EXPIRED", "CANCELLED"}
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["dues_paid_cents"], int) and data["dues_paid_cents"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_show_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "show id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["feature_surcharge_cents"], int) and data["feature_surcharge_cents"] >= 0
    assert isinstance(data["seats_sold"], int) and data["seats_sold"] >= 0
    assert data["status"] in {"SCHEDULED", "OPEN", "SOLD_OUT", "CANCELLED", "COMPLETED"}
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_show_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "booking id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["gross_price_cents"], int) and data["gross_price_cents"] >= 0
    assert isinstance(data["member_discount_cents"], int) and data["member_discount_cents"] >= 0
    assert isinstance(data["net_price_cents"], int)
    assert data["net_price_cents"] == data["gross_price_cents"] - data["member_discount_cents"]
    assert data["status"] in {"HELD", "CONFIRMED", "CANCELLED", "REFUNDED"}


def assert_group_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "group booking id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["student_count"], int) and data["student_count"] >= 1
    assert isinstance(data["chaperone_count"], int) and data["chaperone_count"] >= 0
    assert isinstance(data["total_seats"], int) and data["total_seats"] >= 1
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["status"] in {"REQUESTED", "DEPOSIT_PAID", "CONFIRMED", "CANCELLED"}


def assert_program_session(data: dict):
    assert is_valid_uuid(data.get("id", "")), "program id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["program_kind"] in {"CAMP", "CLASS"}
    assert isinstance(data["min_age"], int) and data["min_age"] >= 0
    assert isinstance(data["max_age"], int) and data["max_age"] >= data["min_age"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["tuition_cents"], int) and data["tuition_cents"] >= 0
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert data["status"] in {"ENROLLING", "FULL", "STARTED", "CANCELLED"}
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_registration(data: dict):
    assert is_valid_uuid(data.get("id", "")), "registration id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["participant_name"], str) and len(data["participant_name"]) > 0
    assert isinstance(data["participant_age"], int) and data["participant_age"] >= 0
    assert data["status"] in {"ENROLLED", "WAITLISTED", "CANCELLED"}


def assert_rental_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "rental id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["guest_count"], int) and data["guest_count"] >= 1
    assert isinstance(data["base_rental_cents"], int) and data["base_rental_cents"] >= 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["status"] in {"INQUIRY", "HELD", "CONFIRMED", "CANCELLED"}


def assert_sponsor(data: dict):
    assert is_valid_uuid(data.get("id", "")), "sponsor id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["pledged_cents"], int) and data["pledged_cents"] >= 0
    assert isinstance(data["received_cents"], int) and data["received_cents"] >= 0
    assert isinstance(data["fulfillment_ratio"], (int, float))
    assert data["status"] in {"PLEDGED", "PARTIALLY_FULFILLED", "FULFILLED", "LAPSED"}
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_contribution(data: dict):
    """Contribution is append-only: id + created_at only, status always RECEIVED.
    It carries no version field of its own."""
    assert is_valid_uuid(data.get("id", "")), "contribution id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] == "RECEIVED"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1


def assert_accommodation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "accommodation id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["subject_type"] in {"SHOW_BOOKING", "REGISTRATION", "RENTAL"}
    assert data["accommodation_kind"] in {
        "WHEELCHAIR", "ASL_INTERPRETER", "SENSORY_FRIENDLY", "ASSISTIVE_LISTENING"
    }
    assert data["status"] in {"SUBMITTED", "APPROVED", "DENIED", "FULFILLED"}
