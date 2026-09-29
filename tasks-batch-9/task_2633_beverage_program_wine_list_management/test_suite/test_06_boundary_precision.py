"""Boundary and precision edges in the corkage quote and the glass price.

Every rule in this file has an inclusive/exclusive edge that a naive
implementation gets wrong by one: the corkage waiver is a floor division whose
quotient is clamped by the bottles actually brought, the large-party break is
inclusive at exactly eight covers, and the by-the-glass effective pour count is
an integer floor that becomes a divisor -- so the pour size one step past the
last legal value is a refusal rather than a division by zero.  Each boundary is
pinned on both sides and at the exact point.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_POUR_SIZE_TOO_LARGE
from test_helpers.assertions import assert_decimal_equals, assert_fields_equal
from test_helpers.test_users import BEVERAGE_DIRECTOR_HEADERS, sommelier_headers

# The venue every recipe in this file uses: the six category targets are
# distinct so a mis-keyed lookup cannot pass by accident, and RED is 28.0.
_CATEGORY_TARGETS = f.cogs_targets(
    30.0, WHITE=25.0, ROSE=28.0, RED=28.0, DESSERT=32.0, FORTIFIED=35.0)


def _harbor_room(**overrides):
    """Venue HRB with the recipe's category targets and default corkage policy."""
    fx.set_clock("2026-09-01T12:00:00Z")
    return fx.create_venue(name="Harbor Room", venue_code="HRB",
                           cogs_target_pct_by_category=_CATEGORY_TARGETS,
                           priority_rank=1, **overrides)


def _quote(venue, **payload_overrides):
    """POST a corkage quote as the venue's sommelier and return the raw response."""
    venue_id = venue["id"]
    payload = f.corkage_payload(**payload_overrides)
    return api_client.quote_corkage(venue_id, payload, sommelier_headers(venue_id))


class TestCorkageWaiverRatioEdges:
    """The corkage waiver is floor(purchased / ratio) clamped by the bottles
    actually brought, and the large-party break is inclusive at eight covers.
    The venue keeps the PRD defaults: 3500 cents a bottle, a waiver ratio of 2
    and a BYO limit of 2."""

    def test_purchasing_exactly_the_waiver_ratio_earns_one_waiver(self):
        """A party buying exactly two bottles off the list waives exactly one of its own.

        "Divide `bottles_purchased_from_list` by the venue's `corkage_waiver_purchase_ratio`, discarding any remainder, to get how many waivers the party has earned; the waived bottles are the smaller of that figure and `byo_bottle_count`."

        Design: Difficulty/boundary_precision_check/corkage_waiver_ratio_floor_at_exact_multiple
        """
        venue = _harbor_room()
        quote = validate_success(_quote(venue, byo_bottle_count=2,
                                       bottles_purchased_from_list=2,
                                       party_size=4, byo_categories=["RED"]))
        assert_fields_equal(quote, {
            "waived_bottles": 1,
            "chargeable_bottles": 1,
            "corkage_total_cents": 3500,
            "large_party_discount_applied": False,
        }, name="corkage quote")

    def test_purchasing_one_bottle_below_the_ratio_earns_no_waiver(self):
        """One bottle short of the ratio the floor division yields zero waivers.

        "Because the division discards the remainder, one waiver is earned at exactly the ratio and not before."

        Design: Difficulty/boundary_precision_check/corkage_waiver_ratio_floor_at_exact_multiple
        """
        venue = _harbor_room()
        quote = validate_success(_quote(venue, byo_bottle_count=2,
                                       bottles_purchased_from_list=1,
                                       party_size=4, byo_categories=["RED"]))
        assert_fields_equal(quote, {
            "waived_bottles": 0,
            "chargeable_bottles": 2,
            "corkage_total_cents": 7000,
            "large_party_discount_applied": False,
        }, name="corkage quote")

    def test_more_waivers_than_bottles_brought_cannot_waive_what_was_not_brought(self):
        """Four purchased bottles earn two waivers, and the clamp stops the total at zero.

        "Divide `bottles_purchased_from_list` by the venue's `corkage_waiver_purchase_ratio`, discarding any remainder, to get how many waivers the party has earned; the waived bottles are the smaller of that figure and `byo_bottle_count`."

        Design: Difficulty/boundary_precision_check/corkage_waiver_ratio_floor_at_exact_multiple
        """
        venue = _harbor_room()
        quote = validate_success(_quote(venue, byo_bottle_count=2,
                                       bottles_purchased_from_list=4,
                                       party_size=4, byo_categories=["RED"]))
        assert_fields_equal(quote, {
            "waived_bottles": 2,
            "chargeable_bottles": 0,
            "corkage_total_cents": 0,
            "large_party_discount_applied": False,
        }, name="corkage quote")

    def test_a_party_of_exactly_eight_earns_the_large_party_reduction(self):
        """Eight covers is inclusive, and 3500 less a quarter lands exactly on 2625.

        "Finally, a large party earns a break: when `party_size` is at least 8, the total is reduced by 25.0 percent — multiplied by 100 less 25.0, divided by 100, rounded half up to whole cents — and a party of exactly 8 qualifies."

        Design: Difficulty/boundary_precision_check/corkage_waiver_ratio_floor_at_exact_multiple
        """
        venue = _harbor_room()
        before = fx.get_venue(venue)
        quote = validate_success(_quote(venue, byo_bottle_count=2,
                                       bottles_purchased_from_list=2,
                                       party_size=8, byo_categories=["RED"]))
        assert_fields_equal(quote, {
            "waived_bottles": 1,
            "chargeable_bottles": 1,
            "corkage_total_cents": 2625,
            "large_party_discount_applied": True,
        }, name="corkage quote")
        after = fx.get_venue(venue)
        assert after["version"] == before["version"], (
            "the corkage quote persists nothing, so the venue's version must not"
            " move: %r -> %r" % (before["version"], after["version"]))


def _draft_with_three_reds():
    """Venue HRB, three distinct 750 ml RED wines at 2400 cents, one DRAFT version."""
    venue = _harbor_room()
    wines = [
        fx.create_wine(producer="Ridge", cuvee=cuvee, vintage_year=2019,
                       category="RED", reference_cost_cents=2400,
                       bottle_size_ml=750, case_pack=6, is_allocated=False)
        for cuvee in ("Monte Bello", "Estate Cabernet", "Geyserville")
    ]
    chain = fx.setup_draft_version(venue)
    return venue, wines, chain["version"]


def _post_entry(version, wine, venue, sort_rank, pour_size_ml):
    """POST a by-the-glass entry and return the raw response (refusals included)."""
    version_id = version["id"]
    venue_id = venue["id"]
    expected = fx.current_version(api_client.get_list_version, version_id)
    payload = f.list_entry_payload(wine["id"], expected, sort_rank,
                                  by_the_glass=True, pour_size_ml=pour_size_ml,
                                  par_bottles=6, education_verified=False)
    return api_client.create_list_entry(version_id, payload,
                                        sommelier_headers(venue_id))


class TestGlassPriceEffectivePourFloor:
    """`effective_pours` is floor(bottle_size_ml / pour_size_ml) less one, and it
    then divides the glass price -- so the pour size at which the floor reaches
    zero is a refusal, not a division by zero.  All three entries sit on one
    750 ml RED wine at 2400 cents against a 28.0 category target."""

    def test_a_250_ml_pour_leaves_two_effective_pours_priced_at_4300_cents(self):
        """Three gross pours less the allowance leaves two, and the glass lifts to 4300.

        "The glass price then follows from the same category target: multiply the wine's `reference_cost_cents` by 100, divide by the venue's category target percentage, divide again by `effective_pours`, round that half up to whole cents, and finally raise the result to the next whole multiple of 25 cents."

        Design: Difficulty/boundary_precision_check/glass_price_effective_pour_floor_to_zero_pours
        """
        venue, wines, version = _draft_with_three_reds()
        entry = validate_success(_post_entry(version, wines[0], venue, 1, 250), 201)
        assert_fields_equal(entry, {
            "effective_pours": 2,
            "glass_price_cents": 4300,
            "bottle_price_cents": 8600,
            "price_band": "CORE",
        }, name="250 ml entry")

    def test_a_375_ml_pour_leaves_the_last_legal_single_effective_pour(self):
        """Two gross pours less the allowance leaves exactly one saleable glass at 8575.

        "Divide the wine's `bottle_size_ml` by the entry's `pour_size_ml` and discard any fraction to get the gross pour count, then subtract one pour as the spoilage allowance every open bottle concedes; the remainder is `effective_pours`."

        Design: Difficulty/boundary_precision_check/glass_price_effective_pour_floor_to_zero_pours
        """
        venue, wines, version = _draft_with_three_reds()
        entry = validate_success(_post_entry(version, wines[1], venue, 2, 375), 201)
        assert_fields_equal(entry, {
            "effective_pours": 1,
            "glass_price_cents": 8575,
            "bottle_price_cents": 8600,
            "price_band": "CORE",
        }, name="375 ml entry")

    def test_a_400_ml_pour_leaves_no_saleable_glass_and_is_refused(self):
        """One step past the last legal pour size the floor reaches zero and the entry is refused.

        "A pour size so large that this leaves fewer than one saleable glass is refused with `ERR_POUR_SIZE_TOO_LARGE` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/glass_price_effective_pour_floor_to_zero_pours
        """
        venue, wines, version = _draft_with_three_reds()
        version_id = version["id"]
        validate_success(_post_entry(version, wines[0], venue, 1, 250), 201)
        validate_success(_post_entry(version, wines[1], venue, 2, 375), 201)
        before = fx.current_version(api_client.get_list_version, version_id)
        assert before == 3, (
            "two accepted entries must have advanced the version's own version"
            " counter from 1 to 3, got %r" % (before,))

        validate_error(_post_entry(version, wines[2], venue, 3, 400),
                       ERR_POUR_SIZE_TOO_LARGE)

        rows, meta = validate_paginated(api_client.list_list_entries(
            BEVERAGE_DIRECTOR_HEADERS, params={"list_version_id": version_id}))
        assert meta["total_count"] == 2, (
            "the refused entry must leave no partial row: total_count %r"
            % (meta["total_count"],))
        assert len(rows) == 2, "expected exactly the two accepted entries"
        assert fx.current_version(api_client.get_list_version, version_id) == before, (
            "a refused entry must not advance the parent version's version counter")
        for row in rows:
            assert_decimal_equals(row["bottle_price_cents"], 8600,
                                  field="bottle_price_cents")
            assert row["price_band"] == "CORE"
