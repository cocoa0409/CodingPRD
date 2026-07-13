"""Fuel-economy reporting: the segment snapshot taken at authorization and the two
economy methods offered by the vehicle economy endpoint."""
import pytest

from test_helpers import (
    MERCHANT,
    assert_transaction,
    authorize_transaction_payload,
    setup_authorized_fills,
    setup_fueling_scenario,
    validate_success,
)

# Two fills whose per-fill economy differs, so SEGMENT and ROLLING must diverge:
#   fill A: odometer 10600 from a 10000 start -> 600 miles on 100 gallons
#   fill B: odometer 11200                    -> 600 miles on  80 gallons
_MPG_FILLS = [
    {"gallons": 100, "unit_price_cents": 400, "odometer": 10600},
    {"gallons": 80, "unit_price_cents": 400, "odometer": 11200},
]
_MPG_VEHICLE = {
    "tank_capacity_gallons": 5000, "expected_mpg_min": 3,
    "expected_mpg_max": 12, "starting_odometer": 10000,
}


def _mpg_scenario(api):
    return setup_authorized_fills(
        api, _MPG_FILLS,
        account_overrides={"company_name": "Mpg Fleet"},
        vehicle_overrides=_MPG_VEHICLE,
        card_overrides={"last4": "2222"},
    )


def test_segment_economy_uses_only_the_latest_fill(api):
    """PRD §3.8: "Both methods draw on the vehicle's window of `AUTHORIZED`-or-later,
    non-`VOIDED` transactions, ordered by `purchased_at` ascending with ties broken by
    `created_at` ascending."
    PRD §3.8: "The `SEGMENT` method uses only the most recent such transaction: its
    `mpg` is that transaction's `segment_miles` divided by its `gallons`, rounded half
    up to one decimal place."

    The latest fill covered 600 miles on 80 gallons: 7.5 mpg.

    Design: Difficulty/dual_variant_calc/vehicle_mpg_segment_vs_rolling_diverges
    """
    scenario = _mpg_scenario(api)

    data = validate_success(
        api.get_vehicle_mpg(scenario["vehicle"]["id"], scenario["fm"],
                            params={"method": "SEGMENT"})
    )

    assert data["method"] == "SEGMENT"
    assert data["mpg"] == pytest.approx(7.5, abs=0.001), "600 miles / 80 gallons"
    assert data["exception"] is False, "7.5 sits inside the vehicle's 3..12 band"


def test_rolling_economy_diverges_from_segment_across_the_window(api):
    """PRD §3.8: "The `ROLLING` method uses the whole window: total miles is the
    latest transaction's `odometer` minus the earliest window transaction's odometer,
    total gallons is the sum of `gallons` across the window, and `mpg` is total miles
    divided by total gallons, rounded half up to one decimal place."
    PRD §3.8: "The two methods diverge whenever per-fill economy varies across the
    window."

    Rolling miles are 11200 - 10600 = 600 over 180 gallons of window fuel, so
    round_half_up(3.333.., 1) == 3.3 — a different figure from the 7.5 the SEGMENT
    method reports on the same history.

    Design: Difficulty/dual_variant_calc/vehicle_mpg_segment_vs_rolling_diverges
    """
    scenario = _mpg_scenario(api)

    rolling = validate_success(
        api.get_vehicle_mpg(scenario["vehicle"]["id"], scenario["fm"],
                            params={"method": "ROLLING"})
    )
    segment = validate_success(
        api.get_vehicle_mpg(scenario["vehicle"]["id"], scenario["fm"],
                            params={"method": "SEGMENT"})
    )

    assert rolling["method"] == "ROLLING"
    assert rolling["mpg"] == pytest.approx(3.3, abs=0.001), "600 miles / 180 gallons"
    assert rolling["mpg"] != segment["mpg"], (
        "the two methods must diverge when per-fill economy varies"
    )


def test_mpg_exception_flagged_below_the_expected_band(api):
    """PRD §3.4: "The segment economy `mpg_snapshot` is `segment_miles` divided by
    `gallons`, rounded half up to one decimal place. The boolean `mpg_exception` is
    true when `mpg_snapshot` is below the vehicle's `expected_mpg_min` or above its
    `expected_mpg_max`."
    PRD §3.4: "The system also computes the fuel-economy snapshot: `segment_miles` is
    this `odometer` minus the previous transaction's `odometer` on the same vehicle
    (or the vehicle's `starting_odometer` if this is the vehicle's first transaction),
    where "previous" is by `purchased_at` ascending, ties broken by `created_at`
    ascending."

    Design: Corner/calculations/mpg_exception_flag_below_band
    """
    scenario = setup_fueling_scenario(
        api,
        account_overrides={"company_name": "Exc Co"},
        vehicle_overrides={"tank_capacity_gallons": 5000, "expected_mpg_min": 3,
                           "expected_mpg_max": 12, "starting_odometer": 0},
        card_overrides={"last4": "0601"},
    )

    payload = authorize_transaction_payload(
        scenario["card"]["id"], gallons=100, unit_price_cents=400, odometer=100,
    )
    txn = validate_success(api.authorize_transaction(payload, MERCHANT), 201)

    assert_transaction(txn)
    assert txn["mpg_snapshot"] == pytest.approx(1.0, abs=0.001), "100 miles / 100 gallons"
    assert txn["mpg_exception"] is True, "1.0 is below the vehicle's expected_mpg_min of 3"
