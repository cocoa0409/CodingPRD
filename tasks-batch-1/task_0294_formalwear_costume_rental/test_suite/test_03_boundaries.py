"""Boundary-precision tests: the late-day boundary at the exact window end, and
the size-chart lower bound."""
from test_helpers import (
    validate_success,
    set_clock, create_customer,
    create_picked_up_reservation, return_reservation,
)
from test_helpers import api_client
from test_helpers import TEST_USERS
from test_helpers.factories import create_measurement_profile_payload

CAT = {
    "daily_rate_cents": 5000, "deposit_cents": 20000, "replacement_value_cents": 80000,
    "waiver_daily_rate_cents": 1200, "cleaning_buffer_days": 2, "late_fee_daily_rate_cents": 2000,
}
RESV = {
    "event_date_iso": "2026-09-04T00:00:00Z",
    "pickup_window_start_iso": "2026-09-01T09:00:00Z",
    "return_window_end_iso": "2026-09-03T17:00:00Z",
}


def test_return_exactly_at_window_end_is_on_time(api):
    """PRD §3.7: "The `late_days` is the number of whole calendar days the `returned_at_iso` falls strictly after the `return_window_end_iso`, taking the ceiling of the day difference, and is 0 when the return is on or before the window end".
    PRD §3.7: "If the `returned_at_iso` is on or before the reservation's `return_window_end_iso`, the reservation follows the on-time branch from `PICKED_UP` to `RETURNED`."

    Design: Difficulty/boundary_precision_check/late_fee_exact_window_end_is_zero_days
    """
    _, _, _, resv = create_picked_up_reservation(
        catalog_overrides={**CAT, "style_name": "Tux K"}, reservation_overrides=RESV)
    settlement = return_reservation(resv["id"], "2026-09-03T17:00:00Z", "CLEAN")

    assert settlement["late_days"] == 0, "exactly at window end -> on time"
    assert settlement["late_fee_cents"] == 0
    after = validate_success(api_client.get_reservation(resv["id"], TEST_USERS["clerk_headers"]), 200)
    assert after["status"] == "RETURNED", "on-time branch -> RETURNED"


def test_late_fee_two_days_routes_overdue(api):
    """PRD §3.7: "The `late_fee_cents` is `late_days` multiplied by the catalog's `late_fee_daily_rate_cents`, and is therefore 0 on the on-time branch and positive only on the late branch."
    PRD §3.7: "If the `returned_at_iso` is after the `return_window_end_iso`, the reservation follows the late branch".

    Design: Difficulty/non_linear_state_machine/reservation_branching_fork_join_pickedup_to_returned_or_overdue
    """
    _, _, _, resv = create_picked_up_reservation(
        catalog_overrides={**CAT, "style_name": "Tux E"}, reservation_overrides=RESV)
    settlement = return_reservation(resv["id"], "2026-09-05T17:00:00Z", "CLEAN")

    # 09-05T17:00 vs window end 09-03T17:00 -> exactly 2 whole days.
    assert settlement["late_days"] == 2
    assert settlement["late_fee_cents"] == 4000, "2 * 2000"
    after = validate_success(api_client.get_reservation(resv["id"], TEST_USERS["clerk_headers"]), 200)
    assert after["status"] == "OVERDUE", "late branch -> OVERDUE"


def test_recommended_size_chest_106_is_L(api):
    """PRD §3.2: "from 106 cm up to but not including 116 cm recommends `L".

    Design: Difficulty/boundary_precision_check/recommended_size_chest_106_boundary_is_L
    """
    set_clock()
    customer = create_customer()
    res = api_client.create_measurement_profile(
        customer["id"], create_measurement_profile_payload(chest_cm=106, waist_cm=90, inseam_cm=82),
        TEST_USERS["clerk_headers"])
    profile = validate_success(res, 201)
    assert profile["recommended_size_code"] == "L", \
        f"106 is inclusive lower bound of [106,116); got {profile['recommended_size_code']}"


def test_recommended_size_chest_105_is_M(api):
    """PRD §3.2: "from 96 cm up to but not including 106 cm recommends `M".

    Design: Difficulty/boundary_precision_check/recommended_size_chest_106_boundary_is_L
    """
    set_clock()
    customer = create_customer()
    res = api_client.create_measurement_profile(
        customer["id"], create_measurement_profile_payload(chest_cm=105, waist_cm=90, inseam_cm=82),
        TEST_USERS["clerk_headers"])
    profile = validate_success(res, 201)
    assert profile["recommended_size_code"] == "M", \
        f"105 is below the L lower bound; got {profile['recommended_size_code']}"
