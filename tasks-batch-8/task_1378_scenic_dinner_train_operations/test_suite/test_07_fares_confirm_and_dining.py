"""Fare quoting under surge, confirm-time response completeness, and the dining table
selector (PRD §2.6, §3.5)."""
import pytest

from test_helpers import (
    assert_booking,
    confirm_booking,
    create_held_booking,
    get_booking,
    setup_published_excursion,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import DINING_SPEC, LOCO_SPEC


class TestFareQuoteHolidaySurge:
    """fare_quote: class branch x surge multiplier x party size, rounding pinned to the
    unit fare. HOLIDAY surge 13333 on DINING base 15000: round_half_up(19999.5) = 20000."""

    def _setup_confirmed(self):
        scenario = setup_published_excursion(
            event_type="HOLIDAY", surge_multiplier_bp=13333,
            title="Holiday Express", car_specs=[LOCO_SPEC, DINING_SPEC])
        excursion = scenario["excursion"]
        held = create_held_booking(excursion["id"], "dana@x.com", "DINING", 2, "EARLY")
        return excursion, held

    def test_fare_quote_unit_rounded_half_up_before_multiplying(self, api, station_agent_headers):
        """PRD §2.6: "When a fare is quoted, the rounding order is pinned: the unit fare
        is computed first — the class base fare scaled by the excursion's surge multiplier
        — rounded half-up to a whole cent, and only then multiplied by the party size to
        produce the booking total. Rounding the product instead of the unit fare is a
        specification violation."
        PRD §2.6: "Base fares per passenger are fixed by class: 6000 cents for `COACH`,
        11000 cents for `FIRST_CLASS`, and 15000 cents for `DINING`."

        Design: Difficulty/combinatorial_formula/fare_quote_class_branch_surge_party_max (mode a)
        """
        _, held = self._setup_confirmed()
        confirmed = confirm_booking(held["id"])
        assert confirmed["unit_fare_cents"] == 20000, (
            "round_half_up(15000 * 13333 / 10000) = round_half_up(19999.5) = 20000")

    def test_fare_quote_total_paid_and_table_assignment(self, api, station_agent_headers):
        """PRD §2.6: "When a fare is quoted, the rounding order is pinned: the unit fare
        is computed first — the class base fare scaled by the excursion's surge multiplier
        — rounded half-up to a whole cent, and only then multiplied by the party size to
        produce the booking total."
        PRD §3.5: "With no rain-check, `paid_cents` equals the total."
        PRD §3.5: "The selector walks cars by ascending `position` and tables by ascending
        number, taking the first free table; because position and table number form a
        total order over distinct tables, no tie-break is ever needed."

        Design: Difficulty/combinatorial_formula/fare_quote_class_branch_surge_party_max (mode a)
        """
        _, held = self._setup_confirmed()
        confirmed = confirm_booking(held["id"])
        assert confirmed["unit_fare_cents"] == 20000
        assert confirmed["total_price_cents"] == 40000, "20000 x party of 2"
        assert confirmed["paid_cents"] == 40000, "standard payment branch: paid == total"
        assert confirmed["dining_table_number"] == 1, "selector takes the lowest free table"
        assert confirmed["dining_car_assignment_id"] is not None


def test_confirm_response_contains_final_computed_fields(api, station_agent_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    PRD §3.5: "Pricing follows the fare rule of §2.6 exactly. The `unit_fare_cents` is
    the class base fare scaled by the excursion's `surge_multiplier_bp`, rounded half-up
    to whole cents; the `total_price_cents` is that unit fare multiplied by `party_size`.
    With no rain-check, `paid_cents` equals the total."
    PRD §3.5: "On success the booking records `dining_table_number` and the chosen car in
    `dining_car_assignment_id`; both stay null for non-dining bookings."

    Design: Corner/consistency_model/confirm_response_contains_final_computed_fields
    """
    scenario = setup_published_excursion(car_specs=[LOCO_SPEC, DINING_SPEC])
    held = create_held_booking(scenario["excursion"]["id"], "imm@x.com", "DINING", 2, "EARLY")

    confirmed = confirm_booking(held["id"])
    assert_booking(confirmed)
    # Immediate consistency: the CONFIRM response itself carries the final computed
    # fields — no re-read required.
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["unit_fare_cents"] == 15000, "DINING base fare at REGULAR surge 10000"
    assert confirmed["total_price_cents"] == 30000, "15000 x party of 2"
    assert confirmed["paid_cents"] == 30000
    assert confirmed["dining_table_number"] == 1
    assert confirmed["dining_car_assignment_id"] == scenario["cars"]["DIN-1"]["assignment"]["id"]


def test_dining_selector_assigns_lowest_table_then_fails_full(api, station_agent_headers):
    """PRD §3.5: "The selector walks cars by ascending `position` and tables by ascending
    number, taking the first free table; because position and table number form a total
    order over distinct tables, no tie-break is ever needed. If the pool is empty,
    confirmation fails with `ERR_DINING_SERVICE_FULL`."

    Design: Corner/calculations/dining_selector_assigns_lowest_table_then_fails_full
    """
    scenario = setup_published_excursion(car_specs=[LOCO_SPEC, DINING_SPEC])  # 4 tables
    excursion_id = scenario["excursion"]["id"]
    dining_car_assignment_id = scenario["cars"]["DIN-1"]["assignment"]["id"]

    confirmed_tables = []
    for i in range(1, 5):
        held = create_held_booking(excursion_id, f"t{i}@x.com", "DINING", 1, "EARLY")
        confirmed = confirm_booking(held["id"])
        confirmed_tables.append(confirmed["dining_table_number"])
        assert confirmed["dining_car_assignment_id"] == dining_car_assignment_id
    assert confirmed_tables == [1, 2, 3, 4], "tables handed out in ascending order"

    fifth = create_held_booking(excursion_id, "t5@x.com", "DINING", 1, "EARLY")
    res = api.booking_event(fifth["id"], {"event_type": "CONFIRM"}, station_agent_headers)
    validate_error(res, ApiErrorId.ERR_DINING_SERVICE_FULL.value, expected_status=409)
    after = get_booking(fifth["id"])
    assert after["status"] == "HELD", "a failed confirmation leaves the booking HELD"
