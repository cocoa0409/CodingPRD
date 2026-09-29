"""The evaluated price of one single bid, priced twice by two different rules.

The public opening prices every bid as read; the responsiveness determination
re-prices the very same row under the corrected rule, which loads the
unacknowledged non-material addenda onto the base price.
"""
from typing import Any, Dict

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions
from test_helpers import factories as fac
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import OFFICER_HEADERS

# The solicitation calendar this file works against.
BID_DUE_UTC = "2026-08-27T00:00:00Z"
QUESTION_DEADLINE_UTC = "2026-08-20T00:00:00Z"

# The single bid's as-read price, and the loading two unacknowledged
# non-material addenda put on top of it: 12000000 * 0.0025 * 2.
AS_READ_PRICE_CENTS = 12000000
LOADING_CENTS = 60000
CORRECTED_PRICE_CENTS = 12060000

BOND_REQUIREMENT = {
    "requirement_code": "REQ-BOND",
    "description": "five percent bid bond",
    "materiality": "MATERIAL",
    "is_waivable": False,
}


def _build_opened_solicitation_with_one_unacknowledging_bid() -> Dict[str, Any]:
    """One eligible vendor, one solicitation carrying a single original material
    requirement plus two acknowledgment-required addenda that introduce no
    requirements at all, and one bid that acknowledges neither of them, walked
    to BIDS_OPENED with the clock standing at the bid due instant."""
    fx.reset_clock()

    vendor = fx.create_vendor(
        legal_name="Ridgeline Paving LLC",
        tax_id="100000001",
        contact_email="v1@example.gov",
    )

    solicitation = fx.create_solicitation(
        solicitation_number="SOL-2238-DV1",
        title="Roadway Resurfacing District 4",
        issuing_agency_code="DOT",
        estimated_value_cents=100000000,
        original_bid_due_utc=BID_DUE_UTC,
        original_question_deadline_utc=QUESTION_DEADLINE_UTC,
        mandatory_requirements=[dict(BOND_REQUIREMENT)],
    )
    solicitation_id = solicitation["id"]
    fx.issue_solicitation(solicitation_id)

    for summary in ("clarifies striping color", "clarifies traffic control hours"):
        fx.add_addendum(
            solicitation_id,
            summary=summary,
            extends_bid_due_by_days=0,
            acknowledgment_required=True,
            new_requirement_codes=[],
        )

    version_before_bid = fx.read_solicitation(solicitation_id)["version"]
    bid = fx.submit_bid(
        solicitation_id,
        vendor["id"],
        total_price_cents=AS_READ_PRICE_CENTS,
        acknowledged_addendum_sequences=[],
        expected_solicitation_version=version_before_bid,
    )

    fx.set_clock(QUESTION_DEADLINE_UTC)
    fx.close_question_period(solicitation_id)
    fx.set_clock(BID_DUE_UTC)
    opened = fx.open_bids(solicitation_id)

    return {
        "vendor_id": vendor["id"],
        "solicitation_id": solicitation_id,
        "solicitation": opened,
        "bid_id": bid["id"],
    }


def _determine_responsive(bid_id: str) -> Dict[str, Any]:
    """Fire the responsiveness determination and return the updated bid."""
    response = api_client.determine_responsiveness(
        bid_id,
        fac.responsiveness_payload(determination="RESPONSIVE", reason_codes=[]),
        OFFICER_HEADERS,
    )
    return validate_success(response)


@pytest.fixture
def opened_state() -> Dict[str, Any]:
    return _build_opened_solicitation_with_one_unacknowledging_bid()


class TestBidEvaluatedPriceVariants:
    """The as-read pricing of the opening against the corrected pricing of the
    responsiveness determination, on one and the same bid row."""

    def test_as_read_pricing_at_opening_then_corrected_pricing_at_determination(
        self, opened_state
    ):
        """Opening stamps `bids_opened_at_utc` from the logical clock, which becomes the trigger event for one flavour of protest timeliness, and prices every non-withdrawn bid under the **as-read variant** of the evaluated-price rule: each such bid's `evaluated_price_cents` is set to exactly its `total_price_cents`, and its `informality_loading_cents` is set to 0.

        That count of unacknowledged non-material addenda is multiplied by the base price and by a loading rate of twenty-five hundredths of one percent — that is, 0.0025 — and the product is rounded half-up to a whole cent exactly once to give `informality_loading_cents`.

        The bid's `evaluated_price_cents` becomes the base price plus that loading.

        Design: Difficulty/dual_variant_calc/bid_evaluated_price_as_read_versus_corrected_variant_divergence
        """
        bid_id = opened_state["bid_id"]

        as_read = fx.read_bid(bid_id)
        assertions.assert_integer_cents(
            as_read["evaluated_price_cents"], "evaluated_price_cents"
        )
        assert as_read["evaluated_price_cents"] == AS_READ_PRICE_CENTS
        assert as_read["informality_loading_cents"] == 0

        corrected = _determine_responsive(bid_id)
        assertions.assert_integer_cents(
            corrected["informality_loading_cents"], "informality_loading_cents"
        )
        assert corrected["informality_loading_cents"] == LOADING_CENTS
        assert corrected["evaluated_price_cents"] == CORRECTED_PRICE_CENTS

        # The whole point of the two variants: the same row, priced twice, and
        # the gap between the two prices is the loading and nothing else.
        assert (
            corrected["evaluated_price_cents"] - as_read["evaluated_price_cents"]
            == LOADING_CENTS
        )
        assert (
            corrected["evaluated_price_cents"]
            == corrected["informality_loading_cents"] + AS_READ_PRICE_CENTS
        )

    def test_neither_variant_moves_the_stored_price_or_the_responsibility_dimension(
        self, opened_state
    ):
        """These two dimensions evolve independently of one another for the entire life of the bid, which is why a bid can be `RESPONSIVE` and still `NOT_REVIEWED`, or `RESPONSIVE` and `NONRESPONSIBLE`.

        The base price is the `corrected_total_price_cents` supplied on this request when one was supplied, and otherwise the bid's stored `total_price_cents`.

        Design: Difficulty/dual_variant_calc/bid_evaluated_price_as_read_versus_corrected_variant_divergence
        """
        bid_id = opened_state["bid_id"]

        as_read = fx.read_bid(bid_id)
        assert as_read["total_price_cents"] == AS_READ_PRICE_CENTS
        assert as_read["responsiveness_status"] == "UNREVIEWED"
        assert as_read["responsibility_status"] == "NOT_REVIEWED"

        corrected = _determine_responsive(bid_id)

        # The as-read figure the vendor tendered is an input and stays put,
        # however the evaluated figure is recomputed on top of it.
        assert corrected["total_price_cents"] == AS_READ_PRICE_CENTS

        # Only the responsiveness dimension moved; responsibility is untouched.
        assert corrected["responsiveness_status"] == "RESPONSIVE"
        assert corrected["responsibility_status"] == "NOT_REVIEWED"

        persisted = fx.read_bid(bid_id)
        assert persisted["total_price_cents"] == AS_READ_PRICE_CENTS
        assert persisted["evaluated_price_cents"] == CORRECTED_PRICE_CENTS
        assert persisted["informality_loading_cents"] == LOADING_CENTS
        assert persisted["responsibility_status"] == "NOT_REVIEWED"

    def test_determination_carries_the_solicitation_into_evaluation_on_the_corrected_price(
        self, opened_state
    ):
        """Each fires the solicitation's automatic `BIDS_OPENED → EVALUATION` transition when the solicitation is still `BIDS_OPENED`, inside the very same request; that auto-transition increments the solicitation's `version` by 1 and fires only on the first determination recorded on that solicitation, since afterwards the solicitation is no longer `BIDS_OPENED`.

        The lowest-ranked candidate's id becomes `apparent_low_bid_id`.

        Design: Difficulty/dual_variant_calc/bid_evaluated_price_as_read_versus_corrected_variant_divergence
        """
        bid_id = opened_state["bid_id"]
        solicitation_id = opened_state["solicitation_id"]

        assert opened_state["solicitation"]["status"] == "BIDS_OPENED"
        assert opened_state["solicitation"]["apparent_low_bid_id"] == bid_id

        _determine_responsive(bid_id)

        solicitation = fx.read_solicitation(solicitation_id)
        assert solicitation["status"] == "EVALUATION"
        assert solicitation["apparent_low_bid_id"] == bid_id
