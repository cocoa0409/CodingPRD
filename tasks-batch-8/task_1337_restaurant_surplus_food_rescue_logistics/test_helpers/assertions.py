"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

DONOR_STATUSES = ["PENDING_REVIEW", "ACTIVE", "SUSPENDED", "DEACTIVATED"]
DRIVER_STATUSES = ["ONBOARDING", "ACTIVE", "SUSPENDED"]
WINDOW_STATUSES = ["OPEN", "BOOKED"]
COOLER_STATUSES = ["AVAILABLE", "RESERVED", "CHECKED_OUT", "CLEANING", "QUARANTINED"]
RESERVATION_STATUSES = ["RESERVED", "CHECKED_OUT", "RELEASED", "RETURNED", "QUARANTINED_HOLD"]
OFFER_STATUSES = [
    "DRAFT", "OPEN", "MATCHED", "SCHEDULED", "PICKED_UP",
    "DELIVERED", "CLOSED", "CANCELLED", "EXPIRED", "DISCARDED",
]
RUN_STATUSES = [
    "PROPOSED", "CONFIRMED", "PICKED_UP", "DELIVERED", "VERIFIED",
    "DECLINED", "FAILED_PICKUP", "FAILED_DELIVERY", "CANCELLED",
]
SAFETY_STATUSES = [
    "UNVERIFIED", "PROVISIONAL_COMPLIANT", "VERIFIED_COMPLIANT", "VERIFIED_VIOLATION",
]
STRIKE_STATUSES = ["FILED", "UPHELD", "WAIVED"]
RECEIPT_STATUSES = ["ISSUED", "AMENDED"]
FOOD_CATEGORIES = ["COLD_HELD", "HOT_HELD", "PRODUCE", "SHELF_STABLE"]


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def assert_donor_site(data: dict):
    _assert_common_fields(data, "donor_site")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["ein"], str) and data["ein"]
    assert data["status"] in DONOR_STATUSES
    for f in ("strike_count", "lifetime_weight_lbs", "pending_estimated_lbs",
              "lifetime_tax_value_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative integer"


def assert_recipient_agency(data: dict):
    _assert_common_fields(data, "recipient_agency")
    assert isinstance(data["name"], str) and data["name"]
    for c in data["accepts_categories"]:
        assert c in FOOD_CATEGORIES
    for f in ("capacity_cold_held_lbs", "capacity_hot_held_lbs",
              "capacity_produce_lbs", "capacity_shelf_stable_lbs",
              "committed_cold_held_lbs", "committed_hot_held_lbs",
              "committed_produce_lbs", "committed_shelf_stable_lbs",
              "received_total_lbs"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_volunteer_driver(data: dict):
    _assert_common_fields(data, "volunteer_driver")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in DRIVER_STATUSES
    assert isinstance(data["vehicle_capacity_lbs"], int)
    assert isinstance(data["cooler_slot_count"], int)
    assert 0 <= data["reliability_score"] <= 100, "reliability_score must be within 0..100"
    assert isinstance(data["completed_run_count"], int)
    assert isinstance(data["upheld_strike_count"], int)


def assert_availability_window(data: dict):
    _assert_common_fields(data, "availability_window")
    assert data["status"] in WINDOW_STATUSES
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])


def assert_cooler(data: dict):
    _assert_common_fields(data, "cooler")
    assert data["status"] in COOLER_STATUSES
    assert isinstance(data["capacity_liters"], int) and data["capacity_liters"] > 0
    if data["status"] in ("CLEANING", "QUARANTINED"):
        assert is_iso8601_timestamp(data["cleaning_ends_at"]), (
            "a holding-state cooler must carry cleaning_ends_at"
        )


def assert_cooler_reservation(data: dict):
    _assert_common_fields(data, "cooler_reservation")
    assert data["status"] in RESERVATION_STATUSES
    assert is_valid_uuid(data["cooler_id"])
    assert is_valid_uuid(data["rescue_run_id"])
    assert is_iso8601_timestamp(data["blocked_start"])
    assert is_iso8601_timestamp(data["blocked_end"])


def assert_donation_offer(data: dict):
    _assert_common_fields(data, "donation_offer")
    assert data["status"] in OFFER_STATUSES
    assert data["food_category"] in FOOD_CATEGORIES
    assert isinstance(data["requires_cold_chain"], bool)
    assert isinstance(data["estimated_weight_lbs"], int) and data["estimated_weight_lbs"] > 0
    assert isinstance(data["failed_attempts"], int) and data["failed_attempts"] >= 0


def assert_rescue_run(data: dict):
    _assert_common_fields(data, "rescue_run")
    assert data["run_status"] in RUN_STATUSES
    assert data["safety_status"] in SAFETY_STATUSES
    assert is_valid_uuid(data["offer_id"])
    assert isinstance(data["estimated_weight_snapshot"], int)


def assert_temperature_log(data: dict):
    """Temperature logs are immutable artifacts (PRD §2.5): id + created_at only.

    Both updated_at and version must be ABSENT from the payload.
    """
    assert is_valid_uuid(data.get("id", "")), "temperature_log.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "temperature_log.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "temperature logs must not carry updated_at"
    assert "version" not in data, "temperature logs must not carry version"
    assert data["point"] in ("PICKUP", "ARRIVAL")
    assert is_valid_uuid(data["rescue_run_id"])
    assert isinstance(data["temp_f"], (int, float))
    assert is_iso8601_timestamp(data["recorded_at"])
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]


def assert_strike_report(data: dict):
    _assert_common_fields(data, "strike_report")
    assert data["status"] in STRIKE_STATUSES
    assert data["reporter_role"] in ("DRIVER", "ADMIN", "SYSTEM")
    assert data["subject_type"] in ("DONOR_SITE", "DRIVER")
    if data["reporter_role"] == "SYSTEM":
        assert data["reporter_user_id"] is None, (
            "reporter_user_id is null exactly when reporter_role is SYSTEM"
        )


def assert_tax_receipt(data: dict):
    _assert_common_fields(data, "tax_receipt")
    assert data["status"] in RECEIPT_STATUSES
    assert isinstance(data["rate_card_version"], int) and data["rate_card_version"] >= 1
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert line["food_category"] in FOOD_CATEGORIES
        for f in ("weight_lbs", "fmv_cents_per_lb", "basis_cents_per_lb",
                  "standard_cents", "enhanced_cents"):
            assert isinstance(line[f], int), f"line.{f} must be an integer"
    for f in ("total_standard_value_cents", "total_enhanced_value_cents",
              "deductible_value_cents", "total_weight_lbs"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    # Roll-up invariant (PRD §3.8): totals are the sums of the lines.
    assert data["total_standard_value_cents"] == sum(l["standard_cents"] for l in data["lines"])
    assert data["total_enhanced_value_cents"] == sum(l["enhanced_cents"] for l in data["lines"])
    assert data["total_weight_lbs"] == sum(l["weight_lbs"] for l in data["lines"])
    # Variant selection rule (PRD §3.8).
    assert data["deductible_value_cents"] in (
        data["total_standard_value_cents"], data["total_enhanced_value_cents"],
    )


def assert_rate_card(data: dict):
    _assert_common_fields(data, "rate_card")
    assert isinstance(data["card_version"], int) and data["card_version"] >= 1
    assert is_iso8601_timestamp(data["effective_start"])
    assert is_iso8601_timestamp(data["effective_end"])
    for f in ("cold_held_fmv_cents_per_lb", "cold_held_basis_cents_per_lb",
              "hot_held_fmv_cents_per_lb", "hot_held_basis_cents_per_lb",
              "produce_fmv_cents_per_lb", "produce_basis_cents_per_lb",
              "shelf_stable_fmv_cents_per_lb", "shelf_stable_basis_cents_per_lb"):
        assert isinstance(data[f], int), f"{f} must be an integer"
