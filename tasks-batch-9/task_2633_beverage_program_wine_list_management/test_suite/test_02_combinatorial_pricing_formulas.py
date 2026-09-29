"""Combinatorial formulas: multi-step arithmetic whose step order is pinned.

Two computations in this API are built out of several dependent steps and would
give a different answer if the steps were reordered.  The allocation waterfall
floors every proportional share *before* anything is summed and only then hands
the remainder out in a pinned order, and wine-dinner pricing reads its volume
tier once from the provisional gross and never re-derives it from the final
ticket price.  Both are asserted against literals taken from the design index.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions, factories as f, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import BEVERAGE_DIRECTOR_HEADERS, sommelier_headers

CLOCK = "2026-09-01T12:00:00Z"

_TARGETS = f.cogs_targets(SPARKLING=30.0, WHITE=25.0, ROSE=28.0, RED=28.0,
                          DESSERT=32.0, FORTIFIED=35.0)


def _assert_instant(actual, expected_prefix, field="timestamp"):
    """Compare a server-minted instant against a whole-second literal."""
    assert actual is not None, "%s must not be null" % field
    assert str(actual).startswith(expected_prefix), (
        "%s expected the instant %sZ, got %r" % (field, expected_prefix, actual))


def _venue(priority_rank, name):
    return fx.create_venue(name=name,
                           cogs_target_pct_by_category=dict(_TARGETS),
                           event_cogs_target_pct=28.0,
                           priority_rank=priority_rank)


def _claim(claim_id):
    return get_success_data(
        api_client.get_allocation_claim(claim_id, BEVERAGE_DIRECTOR_HEADERS))


def _ten_bottle_offer_with_four_equal_claims(rank_order=(1, 2, 3, 4)):
    """Four venues each claiming 3 bottles of a 10-bottle pool.

    ``rank_order`` is the sequence of ``priority_rank`` values in the order the
    claims are filed, so a caller can file the claims in an order that differs
    from the priority order.
    """
    fx.set_clock(CLOCK)
    venues = {rank: _venue(rank, "Venue Rank %d" % rank)
              for rank in sorted(rank_order)}
    distributor = fx.create_cleared_distributor(
        name="Coastal Selections", license_number="LIC-88120",
        allocation_tier="A", on_time_delivery_pct=96.5)
    wine = fx.create_wine(producer="Domaine Leflaive", cuvee="Puligny",
                          vintage_year=2021, category="RED",
                          reference_cost_cents=4500, bottle_size_ml=750,
                          case_pack=6, is_allocated=True)
    offer = fx.create_offer(distributor, wine, offered_bottles=10,
                            unit_cost_cents=4500,
                            response_deadline="2026-09-30T00:00:00Z")
    claims = {}
    for rank in rank_order:
        # file_claim re-reads the offer's live version for the OCC guard, which
        # every claim after the first one needs.
        claims[rank] = fx.file_claim(offer, venues[rank], 3)
    return {"venues": venues, "offer": offer, "wine": wine, "claims": claims}


class TestAllocationWaterfall:
    """A 10-bottle pool against four 3-bottle claims: every raw share is exactly
    2.5000, so the floor-then-remainder order decides the whole award vector."""

    def test_flooring_before_summing_awards_ten_bottles_and_never_twelve(self):
        """Base awards of 2 plus a 2-bottle remainder give 3, 3, 2, 2 — not 3, 3, 3, 3.

        "Rounding each proportional share half up and then summing the results is explicitly **not** the rule; it produces a different award vector whenever a discarded fraction is exactly one half."

        Design: Difficulty/combinatorial_formula/allocation_waterfall_floor_then_remainder_priority_tiebreak
        """
        setup = _ten_bottle_offer_with_four_equal_claims()

        allocated = fx.allocate(setup["offer"])

        awards = {rank: _claim(claim["id"])["granted_bottles"]
                  for rank, claim in setup["claims"].items()}
        assert awards == {1: 3, 2: 3, 3: 2, 4: 2}, (
            "expected the floor-then-remainder vector 3,3,2,2, got %r" % (awards,))
        assert sum(awards.values()) == 10, (
            "the four awards must exhaust exactly the 10-bottle pool, got %d"
            % sum(awards.values()))
        assert allocated["unallocated_bottles"] == 0
        assert allocated["fulfillment_state"] == "ALLOCATED"
        assert allocated["compliance_state"] == "CLEARED"
        assert allocated["claim_count"] == 4
        _assert_instant(allocated["allocated_at"], "2026-09-01T12:00:00",
                        "allocated_at")

    def test_remainder_bottles_go_to_the_two_highest_priority_venues(self):
        """With every discarded fraction tied at one half, ranks 1 and 2 take the
        two spare bottles and land GRANTED while ranks 3 and 4 stay short.

        "The bottles left over, being the pool less the sum of those whole-number parts, are then handed out one bottle at a time to claims ordered by the discarded fraction descending, then by the claiming venue's `priority_rank` ascending so that rank 1 outranks rank 5, then by the claim's `created_at` ascending; identifiers are never used as a tie-break."

        Design: Difficulty/combinatorial_formula/allocation_waterfall_floor_then_remainder_priority_tiebreak
        """
        setup = _ten_bottle_offer_with_four_equal_claims()

        fx.allocate(setup["offer"])

        rows = {rank: _claim(claim["id"])
                for rank, claim in setup["claims"].items()}
        assert rows[1]["remainder_awarded"] is True
        assert rows[2]["remainder_awarded"] is True
        assert rows[3]["remainder_awarded"] is False
        assert rows[4]["remainder_awarded"] is False
        assert rows[1]["state"] == "GRANTED"
        assert rows[2]["state"] == "GRANTED"
        assert rows[3]["state"] == "PARTIALLY_GRANTED"
        assert rows[4]["state"] == "PARTIALLY_GRANTED"

    def test_priority_rank_outranks_claim_creation_order_for_the_remainder(self):
        """Filing the claims in reverse rank order does not move the remainder:
        the rank-1 and rank-2 venues still take the two spare bottles.

        "The bottles left over, being the pool less the sum of those whole-number parts, are then handed out one bottle at a time to claims ordered by the discarded fraction descending, then by the claiming venue's `priority_rank` ascending so that rank 1 outranks rank 5, then by the claim's `created_at` ascending; identifiers are never used as a tie-break."

        Design: Difficulty/combinatorial_formula/allocation_waterfall_floor_then_remainder_priority_tiebreak
        """
        setup = _ten_bottle_offer_with_four_equal_claims(rank_order=(4, 3, 2, 1))

        fx.allocate(setup["offer"])

        rows = {rank: _claim(claim["id"])
                for rank, claim in setup["claims"].items()}
        awards = {rank: row["granted_bottles"] for rank, row in rows.items()}
        assert awards == {1: 3, 2: 3, 3: 2, 4: 2}, (
            "priority_rank must outrank created_at, got %r" % (awards,))
        assert rows[1]["remainder_awarded"] is True
        assert rows[2]["remainder_awarded"] is True
        assert rows[3]["remainder_awarded"] is False
        assert rows[4]["remainder_awarded"] is False

    def test_raw_share_records_the_unrounded_share_to_four_decimals(self):
        """Every claim's audit share is 2.5000, the exact rational 10 x 3 / 12.

        "Third, one field is carried to four decimal places for audit purposes: `raw_share` on an allocation claim, which records a claim's unrounded proportional share of an offer, is persisted rounded half up to four decimals while the awarding arithmetic itself uses the exact rational value."

        Design: Difficulty/combinatorial_formula/allocation_waterfall_floor_then_remainder_priority_tiebreak
        """
        setup = _ten_bottle_offer_with_four_equal_claims()

        fx.allocate(setup["offer"])

        for rank, claim in setup["claims"].items():
            row = _claim(claim["id"])
            assertions.assert_decimal_equals(
                row["raw_share"], 2.5000, "claim rank %d raw_share" % rank)


def _planned_eighty_seat_dinner():
    """An 80-seat PLANNED dinner: 2 pours of a 2400-cent RED plus 1 pour of a
    6000-cent WHITE, in a venue whose event_cogs_target_pct is 28.0."""
    fx.set_clock(CLOCK)
    venue = _venue(1, "Harbor Room")
    bin_ = fx.create_bin(venue, bin_code="A1", zone="CELLAR",
                         capacity_bottles=48, temperature_controlled=True)
    red = fx.create_wine(producer="Ridge", cuvee="Monte Bello",
                         vintage_year=2019, category="RED",
                         reference_cost_cents=2400, bottle_size_ml=750,
                         case_pack=6, is_allocated=False)
    white = fx.create_wine(producer="Kistler", cuvee="Les Noisetiers",
                           vintage_year=2022, category="WHITE",
                           reference_cost_cents=6000, bottle_size_ml=750,
                           case_pack=6, is_allocated=False)
    fx.create_lot(venue, red, bin_, bottles_received=6, unit_cost_cents=2400,
                  received_at="2026-08-10T00:00:00Z")
    fx.create_lot(venue, white, bin_, bottles_received=6, unit_cost_cents=6000,
                  received_at="2026-08-10T00:00:00Z")
    draft = fx.setup_draft_version(venue)
    red_entry = fx.add_entry(draft["version"], red, venue, sort_rank=1,
                             by_the_glass=False, par_bottles=6,
                             education_verified=True)
    white_entry = fx.add_entry(draft["version"], white, venue, sort_rank=2,
                               by_the_glass=False, par_bottles=6,
                               education_verified=True)
    version = fx.publish_version(draft["version"], venue)
    event = fx.create_event(venue, version,
                            [f.pour_plan_line(red_entry["id"], 2),
                             f.pour_plan_line(white_entry["id"], 1)],
                            name="Grand Tasting",
                            starts_at="2026-10-10T18:00:00Z",
                            ends_at="2026-10-10T21:00:00Z",
                            seat_count=80)
    return {"venue": venue, "version": version, "red_entry": red_entry,
            "white_entry": white_entry, "event": event}


def _price(setup):
    return validate_success(
        api_client.price_event(setup["event"]["id"],
                               sommelier_headers(setup["venue"]["id"])))


class TestWineDinnerTicketPricing:
    """Pricing an 80-seat dinner whose provisional revenue sits just over the
    500000-cent tier break while its final revenue sits below it."""

    def test_volume_tier_is_read_once_from_the_provisional_gross(self):
        """The 7.0 percent tier comes from 6500 x 80 = 520000 and yields 6100, not 6300.

        "The apparent circularity here is resolved by fiat: the tier is read once from the provisional revenue in step three and is **never** re-derived from the final ticket price multiplied by the seat count."

        Design: Difficulty/combinatorial_formula/wine_dinner_tier_keyed_on_provisional_gross_single_pass
        """
        setup = _planned_eighty_seat_dinner()

        priced = _price(setup)

        assert priced["beverage_cost_per_seat_cents"] == 1800
        assert priced["provisional_gross_cents"] == 6500
        assertions.assert_decimal_equals(priced["tier_discount_pct"], 7.0,
                                        "tier_discount_pct")
        assert priced["final_ticket_price_cents"] == 6100
        assert priced["final_ticket_price_cents"] != 6300, (
            "6300 is the second-pass answer: the tier must not be re-read from "
            "the final ticket revenue of 488000 cents")
        assert priced["state"] == "PRICED"
        assert priced["pinned_version_no"] == 1

    def test_projection_divides_total_beverage_cost_by_the_final_gross(self):
        """144000 cents of beverage cost over 488000 of ticket revenue is 29.51 percent.

        "**Step five and six**, the projection: multiply `beverage_cost_per_seat_cents` by `seat_count` to get the event's total beverage cost, then express it as a percentage of gross ticket revenue — total beverage cost multiplied by 100, divided by `final_ticket_price_cents` multiplied by `seat_count`, rounded half up to two decimals; that is `projected_pour_cost_pct`."

        Design: Difficulty/combinatorial_formula/wine_dinner_tier_keyed_on_provisional_gross_single_pass
        """
        setup = _planned_eighty_seat_dinner()

        priced = _price(setup)

        assert priced["beverage_cost_per_seat_cents"] == 1800
        assert priced["final_ticket_price_cents"] == 6100
        assertions.assert_decimal_equals(priced["projected_pour_cost_pct"],
                                        29.51, "projected_pour_cost_pct")
        assertions.assert_two_decimal_places(priced["projected_pour_cost_pct"],
                                            "projected_pour_cost_pct")

    def test_repricing_unchanged_inputs_leaves_every_figure_alone(self):
        """A second pricing call reproduces the 7.0 tier and the 6100 ticket.

        "Because the tier is keyed on the provisional gross, re-pricing unchanged inputs is idempotent."

        Design: Difficulty/combinatorial_formula/wine_dinner_tier_keyed_on_provisional_gross_single_pass
        """
        setup = _planned_eighty_seat_dinner()
        first = _price(setup)

        second = _price(setup)

        assert second["state"] == "PRICED"
        assertions.assert_decimal_equals(second["tier_discount_pct"], 7.0,
                                        "tier_discount_pct")
        assert second["final_ticket_price_cents"] == 6100
        assert second["provisional_gross_cents"] == 6500
        assert second["beverage_cost_per_seat_cents"] == 1800
        assertions.assert_decimal_equals(second["projected_pour_cost_pct"],
                                        29.51, "projected_pour_cost_pct")
        assert (second["final_ticket_price_cents"]
                == first["final_ticket_price_cents"])

    def test_frozen_list_prices_are_not_inputs_to_the_ticket(self):
        """The two entries print at 8600 and 24000 cents, neither of which feeds
        the 6100-cent ticket.

        "Neither `bottle_price_cents` nor `glass_price_cents` is an input to any of this."

        Design: Difficulty/combinatorial_formula/wine_dinner_tier_keyed_on_provisional_gross_single_pass
        """
        setup = _planned_eighty_seat_dinner()

        priced = _price(setup)

        assert setup["red_entry"]["bottle_price_cents"] == 8600
        assert setup["red_entry"]["price_band"] == "CORE"
        assert setup["white_entry"]["bottle_price_cents"] == 24000
        assert setup["white_entry"]["price_band"] == "PREMIUM"
        assert priced["final_ticket_price_cents"] == 6100
