"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates response shape against the PRD contract using the
framework's generic format checkers. The invariant helpers encode cross-field
identities the PRD guarantees after any operation.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id/created_at/updated_at/version quartet (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_farm(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["operational_status"] in ("OPEN", "WEATHER_HOLD", "CLOSED")
    assert isinstance(data["parking_fee_cents"], int) and data["parking_fee_cents"] >= 0
    assert isinstance(data["window_buffer_minutes"], int) and data["window_buffer_minutes"] >= 0
    assert isinstance(data["refunds_issued_cents"], int) and data["refunds_issued_cents"] >= 0


def assert_weather_event(data: dict):
    """WeatherEvent is append-only: id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ("HOLD", "CLEARED", "CLOSURE")
    assert "updated_at" not in data, "WeatherEvent must not carry updated_at"
    assert "version" not in data, "WeatherEvent must not carry version"


def assert_pricing_policy(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")
    for f in ("adult_admission_cents", "child_admission_cents", "hayride_pass_cents",
              "maze_pass_cents", "upick_pass_cents", "pumpkin_per_lb_cents",
              "pumpkin_flat_each_cents", "season_pass_price_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be int >= 0"


def assert_admission_window(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "SOLD_OUT", "CANCELLED")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    for f in ("seats_held", "seats_committed", "seats_available"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be int >= 0"
    assert_window_seat_invariant(data)


def assert_visitor(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0


def assert_season_pass(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")
    assert isinstance(data["purchase_price_cents"], int) and data["purchase_price_cents"] >= 0
    assert isinstance(data["visits_used"], int) and data["visits_used"] >= 0


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "CONFIRMED", "CHECKED_IN", "SETTLED",
                              "CANCELLED", "NO_SHOW")
    assert data["participant_count"] == data["adult_count"] + data["child_count"]
    assert isinstance(data["admission_charge_cents"], int) and data["admission_charge_cents"] >= 0


def assert_activity_pass(data: dict):
    _assert_common(data)
    assert data["activity"] in ("HAYRIDE", "MAZE", "UPICK")
    assert data["status"] in ("ACTIVE", "REVOKED")
    assert data["line_total_cents"] == data["quantity"] * data["unit_price_cents"]


def assert_waiver(data: dict):
    _assert_common(data)
    assert data["status"] in ("SIGNED", "VOID")
    assert isinstance(data["participant_name"], str) and len(data["participant_name"]) > 0


def assert_pumpkin_purchase(data: dict):
    _assert_common(data)
    assert data["status"] in ("ESTIMATED", "WEIGHED", "VOID")
    assert isinstance(data["charge_cents"], int) and data["charge_cents"] >= 0


def assert_concession_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("PAID", "REFUNDED")
    assert data["total_cents"] == data["food_cents"] + data["parking_cents"]


def assert_group_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUOTED", "REVISING", "CONFIRMED", "CANCELLED")
    assert data["headcount"] == data["adult_count"] + data["child_count"]
    assert data["kind"] in ("FIELD_TRIP", "SCHOOL", "CORPORATE")


# --- Domain invariants ------------------------------------------------------

def assert_window_seat_invariant(window: dict):
    """PRD §3.3: available seats are capacity less held less committed, floored
    at 0, and never negative."""
    assert window["seats_available"] >= 0, "seats_available must never be negative"
    expected = max(0, window["capacity"] - window["seats_held"] - window["seats_committed"])
    assert window["seats_available"] == expected, (
        f"seats_available {window['seats_available']} != "
        f"max(0, capacity {window['capacity']} - held {window['seats_held']} "
        f"- committed {window['seats_committed']}) = {expected}"
    )
