"""Entity assertions, instant comparison and conservation-invariant checkers."""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --------------------------------------------------------------------------
# Instant handling
# --------------------------------------------------------------------------
def parse_instant(value):
    """Parse an ISO 8601 UTC instant into an aware datetime.

    Accepts both the plain `...Z` rendering a caller supplies and the
    three-fractional-digit `...mmmZ` rendering the server mints, because
    comparisons between such instants are made on the instants they denote,
    not on their strings.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected, label="instant"):
    """Compare two ISO 8601 instants semantically, never as strings."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected the instant {expected!r}, got {actual!r}"
    )


def assert_common_fields(data, expect_version=True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if expect_version:
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be a positive integer, got {data.get('version')!r}"
        )
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )


def assert_append_only_fields(data):
    """For the two entities that carry only id and created_at."""
    assert_common_fields(data, expect_version=False)
    assert "version" not in data, "this resource carries no version field"
    assert "updated_at" not in data, "this resource carries no updated_at field"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_participant(data):
    assert_common_fields(data)
    assert data["status"] in ("INTAKE", "ACTIVE", "INACTIVE", "EXITED")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["household_id"], str)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert data["income_band"] in ("BAND_A", "BAND_B", "BAND_C", "BAND_D")
    assert isinstance(data["weight_kg"], int) and data["weight_kg"] >= 1
    assert data["mobility_profile"] in ("WHEELCHAIR", "AMBULATORY")
    assert data["guardianship_status"] in ("SELF", "GUARDIAN_REQUIRED", "CONSERVATORSHIP")
    assert isinstance(data["age_years"], int) and data["age_years"] >= 0
    assert data["effective_support_tier"] in (
        None, "INDEPENDENT", "INTERMITTENT", "SUBSTANTIAL", "ONE_TO_ONE",
    )


def assert_program_session(data):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "OPEN", "STAFFING_LOCKED", "DELIVERED", "CANCELLED")
    for field in (
        "slot_capacity", "slots_committed", "slots_available",
        "one_to_one_pool_size", "one_to_one_committed", "one_to_one_available",
        "one_to_one_staffed", "assigned_group_staff_count",
        "required_group_staff_planned", "staffing_gap", "unlock_count",
        "sequence_number",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must not be negative"
    assert data["required_group_staff_delivered"] is None or isinstance(
        data["required_group_staff_delivered"], int
    )


def assert_enrollment(data):
    assert_common_fields(data)
    assert data["enrollment_status"] in (
        "REQUESTED", "WAITLISTED", "CONFIRMED", "DENIED", "WITHDRAWN", "ATTENDED", "NO_SHOW",
    )
    assert data["funding_status"] in (
        "QUOTED", "ENCUMBERED", "DISBURSED", "RELEASED", "UNFUNDED",
    )
    assert isinstance(data["waitlist_score"], int)


def assert_enrollment_charge(data):
    assert_common_fields(data)
    assert data["status"] in ("QUOTED", "OUTSTANDING", "SETTLED", "VOIDED")
    for field in (
        "program_fee_cents", "scholarship_applied_cents", "copay_cents",
        "transport_fee_cents", "sibling_discount_bp", "family_responsibility_cents",
        "amount_paid_cents", "balance_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be whole integer cents"
        assert data[field] >= 0, f"{field} must never fall below 0"


def assert_fee_scale_band(data):
    assert_append_only_fields(data)
    assert data["income_band"] in ("BAND_A", "BAND_B", "BAND_C", "BAND_D")


def assert_goal_rating(data):
    assert_append_only_fields(data)
    assert isinstance(data["score"], int) and 1 <= data["score"] <= 5


def assert_equipment_item(data):
    assert_common_fields(data)
    assert data["item_kind"] in ("SERIALIZED", "POOLED")
    assert data["condition_status"] in (
        "SERVICEABLE", "INSPECTION_DUE", "OUT_OF_SERVICE", "RETIRED",
    )


def assert_transport_run(data):
    assert_common_fields(data)
    assert data["status"] in ("PLANNED", "BOARDING_FULL", "CANCELLED")


def assert_funding_source(data):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "EXHAUSTED", "CLOSED")


def assert_scholarship_award(data):
    assert_common_fields(data)
    assert data["status"] in (
        "PROPOSED", "ENCUMBERED", "PARTIALLY_DISBURSED", "DISBURSED",
        "RELEASED", "LAPSED_NO_FUNDS",
    )


# --------------------------------------------------------------------------
# Conservation invariants (PRD 2.11)
# --------------------------------------------------------------------------
def assert_slot_conservation(session):
    assert session["slot_capacity"] == session["slots_committed"] + session["slots_available"], (
        f"slot_capacity {session['slot_capacity']} must equal slots_committed "
        f"{session['slots_committed']} plus slots_available {session['slots_available']}"
    )


def assert_one_to_one_conservation(session):
    assert session["one_to_one_pool_size"] == (
        session["one_to_one_committed"] + session["one_to_one_available"]
    ), (
        f"one_to_one_pool_size {session['one_to_one_pool_size']} must equal "
        f"one_to_one_committed {session['one_to_one_committed']} plus "
        f"one_to_one_available {session['one_to_one_available']}"
    )


def assert_funding_ledger_conservation(source):
    total = source["available_cents"] + source["encumbered_cents"] + source["disbursed_cents"]
    assert source["total_budget_cents"] == total, (
        f"total_budget_cents {source['total_budget_cents']} must equal available "
        f"{source['available_cents']} + encumbered {source['encumbered_cents']} + "
        f"disbursed {source['disbursed_cents']} (got {total})"
    )


def assert_position_pool_conservation(run):
    assert run["accessible_positions"] == (
        run["accessible_committed"] + run["accessible_available"]
    ), "accessible_positions must equal accessible_committed plus accessible_available"
    assert run["ambulatory_seats"] == (
        run["ambulatory_committed"] + run["ambulatory_available"]
    ), "ambulatory_seats must equal ambulatory_committed plus ambulatory_available"


def assert_equipment_unit_conservation(item):
    total = item["pooled_available"] + item["pooled_held"] + item["pooled_checked_out"]
    assert item["pooled_total"] == total, (
        f"pooled_total {item['pooled_total']} must equal pooled_available "
        f"{item['pooled_available']} + pooled_held {item['pooled_held']} + "
        f"pooled_checked_out {item['pooled_checked_out']} (got {total})"
    )
