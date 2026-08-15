"""Marketing kit production cost boundaries (PRD §3.4)."""
import pytest
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    create_and_open_booking,
    create_venue,
    book_stop,
    create_marketing_kit_payload,
)

TM = TEST_USERS["tour_manager_headers"]


class TestBulkDiscountBoundary:
    def _produce_kit(self, api, tour_id, stop_id, language_count, logo_slots=0):
        kit = get_success_data(
            api.create_marketing_kit(
                tour_id,
                stop_id,
                create_marketing_kit_payload(
                    language_count=language_count, sponsor_logo_slots=logo_slots
                ),
                TM,
            )
        )
        return validate_success(
            api.transition_marketing_kit(
                tour_id, stop_id, {"action": "PRODUCE"}, TM
            ),
            200,
        )

    def test_three_languages_no_discount(self, api):
        """PRD §3.4: "The cost builds in layers: a fixed base of $1,500.00; plus
        $450.00 per language edition — and when `language_count` strictly
        exceeds three, the language portion alone earns a fifteen percent bulk
        discount, rounded half-up to whole cents at the moment the discount is
        applied; plus $200.00 per sponsor logo slot."

        Design: Difficulty/boundary_precision_check/marketing_kit_bulk_discount_boundary_3_vs_4
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="V1")
        stop = book_stop(tour["id"], venue["id"], projected_attendance=1000)
        kit = self._produce_kit(api, tour["id"], stop["id"], language_count=3)
        # 150000 + 3*45000 = 285000; strictly-exceeds-3 false at 3 -> no discount.
        assert kit["production_cost_cents"] == 285000

    def test_four_languages_earn_bulk_discount(self, api):
        """PRD §3.4: "when `language_count` strictly exceeds three, the language
        portion alone earns a fifteen percent bulk discount, rounded half-up to
        whole cents at the moment the discount is applied".

        Design: Difficulty/boundary_precision_check/marketing_kit_bulk_discount_boundary_3_vs_4
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="V2")
        stop = book_stop(tour["id"], venue["id"], projected_attendance=1000)
        kit = self._produce_kit(api, tour["id"], stop["id"], language_count=4)
        # 150000 + round_half_up(4*45000*0.85) = 150000 + 153000 = 303000.
        assert kit["production_cost_cents"] == 303000
