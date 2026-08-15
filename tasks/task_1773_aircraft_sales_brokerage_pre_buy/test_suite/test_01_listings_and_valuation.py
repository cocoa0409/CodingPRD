"""Listing creation, comparable sales, and market-comparables valuation."""
import pytest

from test_helpers import (
    EXPECTED_FINAL_VALUE,
    EXPECTED_FINAL_VALUE_FOUR_COMPS,
    EXPECTED_FINAL_VALUE_MEAN_THEN_ROUND,
    EXPECTED_PROVISIONAL_VALUE,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_comparable_sale,
    assert_listing,
    assert_money,
    create_comparable_sale,
    create_comparable_sale_payload,
    create_draft_listing,
    create_listing_payload,
    get_success_data,
    run_valuation,
    setup_active_listing,
    setup_canonical_comps,
    validate_error,
    validate_success,
)

LISTING_AGENT = TEST_USERS["listing_agent_headers"]
BUYER_AGENT = TEST_USERS["buyer_agent_headers"]


class TestListingCreation:
    def test_listing_create_then_get_shows_defaults(self, api):
        """PRD §3.2: "A new listing starts in `DRAFT` status with
        `valuation_status` set to `NONE` and `market_value_estimate_usd` null,
        since no valuation has yet been computed."

        Design: Corner/entities/listing_create_then_get_shows_defaults
        """
        resp = api.create_listing(create_listing_payload(tail_number="N1001GS"),
                                  LISTING_AGENT)
        listing = validate_success(resp, 201)
        assert_listing(listing)
        assert listing["status"] == "DRAFT", "A new listing starts in DRAFT"
        assert listing["valuation_status"] == "NONE"
        assert listing["market_value_estimate_usd"] is None
        assert listing["tail_number"] == "N1001GS"

        fetched = validate_success(api.get_listing(listing["id"], BUYER_AGENT))
        assert fetched["status"] == "DRAFT"
        assert fetched["valuation_status"] == "NONE"
        assert fetched["market_value_estimate_usd"] is None
        assert fetched["tail_number"] == "N1001GS"

    def test_create_listing_missing_tail_number_returns_invalid_request(self, api):
        """PRD §2.8: "Request schema — required body fields are present, types
        are valid, and enum values are in range; failures return
        `ERR_VALIDATION` (HTTP 400)."
        PRD §3.2: "A `ListingAgent` brings an aircraft to market by creating a
        listing with its `tail_number`, `make`, `model`, `year`,
        `total_time_hours` (the airframe's total time in whole hours), its
        advertised `asking_price_usd`, and the `seller_name` shown to buyers"

        Design: Corner/entities/create_listing_missing_tail_number_returns_invalid_request
        """
        create_comparable_sale(
            make="Gulfstream", model="G550", year=2014, sale_price_usd=4123456.05,
            sale_date="2026-01-20", total_time_hours=3001, comp_status="VERIFIED")
        payload = create_listing_payload()
        del payload["tail_number"]
        resp = api.create_listing(payload, LISTING_AGENT)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_get_listing_not_found_returns_404(self, api):
        """PRD §2.9: "Wherever a path carries identifiers, the system validates
        their existence sequentially from left to right and rejects the request
        with the not-found error corresponding to the first identifier that does
        not resolve: `ERR_LISTING_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`,
        `ERR_COMPARABLE_SALE_NOT_FOUND`, `ERR_LOI_NOT_FOUND`,
        `ERR_TRANSACTION_NOT_FOUND`, `ERR_ESCROW_DEPOSIT_NOT_FOUND`,
        `ERR_INSPECTION_FACILITY_NOT_FOUND`, `ERR_INSPECTION_BOOKING_NOT_FOUND`,
        or `ERR_DISCREPANCY_ITEM_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/get_listing_not_found_returns_404
        """
        create_draft_listing()
        resp = api.get_listing(NON_EXISTENT_UUID, LISTING_AGENT)
        validate_error(resp, ApiErrorId.ERR_LISTING_NOT_FOUND)


class TestComparableSales:
    def test_comparable_sale_comp_status_defaults_unverified(self, api):
        """PRD §3.2: "plus an optional `comp_status` of `VERIFIED` or
        `UNVERIFIED` that defaults to `UNVERIFIED` when omitted"
        PRD §3.2: "Only `VERIFIED` comparables ever enter a valuation's input
        set."

        Design: Corner/entities/comparable_sale_comp_status_defaults_unverified
        """
        resp = api.create_comparable_sale(
            create_comparable_sale_payload(make="Gulfstream", model="G550"),
            LISTING_AGENT)
        comp = validate_success(resp, 201)
        assert_comparable_sale(comp)
        assert comp["comp_status"] == "UNVERIFIED", (
            "Omitting comp_status stores UNVERIFIED, keeping the comp out of "
            "valuation input sets")

        fetched = validate_success(api.get_comparable_sale(comp["id"], LISTING_AGENT))
        assert fetched["comp_status"] == "UNVERIFIED"

    def test_get_comparable_sale_not_found_returns_404(self, api):
        """PRD §2.9: "Wherever a path carries identifiers, the system validates
        their existence sequentially from left to right and rejects the request
        with the not-found error corresponding to the first identifier that does
        not resolve: `ERR_LISTING_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`,
        `ERR_COMPARABLE_SALE_NOT_FOUND`, `ERR_LOI_NOT_FOUND`,
        `ERR_TRANSACTION_NOT_FOUND`, `ERR_ESCROW_DEPOSIT_NOT_FOUND`,
        `ERR_INSPECTION_FACILITY_NOT_FOUND`, `ERR_INSPECTION_BOOKING_NOT_FOUND`,
        or `ERR_DISCREPANCY_ITEM_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/get_comparable_sale_not_found_returns_404
        """
        create_comparable_sale(make="Gulfstream", model="G550")
        resp = api.get_comparable_sale(NON_EXISTENT_UUID, LISTING_AGENT)
        validate_error(resp, ApiErrorId.ERR_COMPARABLE_SALE_NOT_FOUND)


class TestValuationVariants:
    def test_valuation_provisional_variant_returns_raw_mean(self, api):
        """PRD §3.2: "The `PROVISIONAL` variant is the broker's quick draft
        estimate, usable at any time: it takes the plain arithmetic mean of the
        input set — the comparables' `sale_price_usd` values are summed, the sum
        is divided by the number of comparables, and the result is rounded half
        up to two decimal places, with no per-hour adjustment applied."
        PRD §3.2: "Either run persists its result onto the listing:
        `market_value_estimate_usd` is set to the computed value,
        `valuation_status` is set to the requested `variant`, and the listing's
        `version` increments by one."

        Design: Difficulty/dual_variant_calc/valuation_provisional_vs_final_diverge
        """
        listing = create_draft_listing(tail_number="N1773GS", total_time_hours=2900)
        setup_canonical_comps()
        result = validate_success(
            api.run_valuation(listing["id"], {"variant": "PROVISIONAL"}, LISTING_AGENT))
        # (4123456.05 + 4350000.00 + 3980000.55) / 3 = 4151152.20
        assert_money(result["market_value_estimate_usd"], EXPECTED_PROVISIONAL_VALUE,
                     "PROVISIONAL market_value_estimate_usd")
        assert result["valuation_status"] == "PROVISIONAL"

    def test_valuation_final_variant_diverges_from_provisional(self, api):
        """PRD §3.2: "Because the per-comparable rounding happens before
        averaging, the FINAL variant provably diverges from the PROVISIONAL mean
        on the same input set."
        PRD §3.2: "Either run persists its result onto the listing:
        `market_value_estimate_usd` is set to the computed value,
        `valuation_status` is set to the requested `variant`, and the listing's
        `version` increments by one."

        Design: Difficulty/dual_variant_calc/valuation_provisional_vs_final_diverge
        """
        listing = create_draft_listing(tail_number="N1773GS", total_time_hours=2900)
        setup_canonical_comps()
        provisional = validate_success(
            api.run_valuation(listing["id"], {"variant": "PROVISIONAL"}, LISTING_AGENT))
        final = validate_success(
            api.run_valuation(listing["id"], {"variant": "FINAL"}, LISTING_AGENT))
        assert_money(provisional["market_value_estimate_usd"],
                     EXPECTED_PROVISIONAL_VALUE, "PROVISIONAL value")
        # Per-comp rounding of the time-adjusted prices before averaging.
        assert_money(final["market_value_estimate_usd"], EXPECTED_FINAL_VALUE,
                     "FINAL market_value_estimate_usd")
        assert final["valuation_status"] == "FINAL"
        assert float(final["market_value_estimate_usd"]) != pytest.approx(
            float(provisional["market_value_estimate_usd"]), abs=0.005), (
            "FINAL must diverge from PROVISIONAL on the identical comp set")


class TestFinalRoundingOrder:
    def test_final_valuation_rounds_each_comp_before_averaging(self, api):
        """PRD §3.2: "Each comparable's adjusted price is its `sale_price_usd`
        multiplied by its own adjustment factor, and that per-comparable product
        is rounded half up to two decimal places first, before any aggregation.
        The valuation is then the sum of those already-rounded adjusted prices
        divided by the number of comparables, with the final quotient itself
        rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/valuation_final_rounds_per_comp_before_averaging
        """
        listing = create_draft_listing(tail_number="N1773GS", total_time_hours=2900)
        setup_canonical_comps()
        result = validate_success(
            api.run_valuation(listing["id"], {"variant": "FINAL"}, LISTING_AGENT))
        # 4106797.29 + 4358700.00 + 3948160.55 = 12413657.84; / 3 = 4137885.95
        assert_money(result["market_value_estimate_usd"], EXPECTED_FINAL_VALUE,
                     "FINAL market_value_estimate_usd")
        assert result["valuation_status"] == "FINAL"

    def test_final_valuation_is_not_the_mean_then_round_alternative(self, api):
        """PRD §3.2: "Each comparable's adjusted price is its `sale_price_usd`
        multiplied by its own adjustment factor, and that per-comparable product
        is rounded half up to two decimal places first, before any aggregation."
        PRD §3.2: "Because the per-comparable rounding happens before averaging,
        the FINAL variant provably diverges from the PROVISIONAL mean on the
        same input set."

        Design: Difficulty/combinatorial_formula/valuation_final_rounds_per_comp_before_averaging
        """
        listing = create_draft_listing(tail_number="N1773GS", total_time_hours=2900)
        setup_canonical_comps()
        result = validate_success(
            api.run_valuation(listing["id"], {"variant": "FINAL"}, LISTING_AGENT))
        assert_money(result["market_value_estimate_usd"], EXPECTED_FINAL_VALUE,
                     "FINAL market_value_estimate_usd")
        assert float(result["market_value_estimate_usd"]) != pytest.approx(
            EXPECTED_FINAL_VALUE_MEAN_THEN_ROUND, abs=0.005), (
            "Averaging unrounded adjustments (4137885.94) violates the pinned "
            "per-comparable rounding order")
        # The result persists on the listing.
        fetched = validate_success(api.get_listing(listing["id"], LISTING_AGENT))
        assert_money(fetched["market_value_estimate_usd"], EXPECTED_FINAL_VALUE,
                     "persisted market_value_estimate_usd")
        assert fetched["valuation_status"] == "FINAL"


class TestMinimumComparablesBoundary:
    def test_valuation_with_two_verified_comps_rejected(self, api):
        """PRD §3.2: "If that set contains fewer than three comparables, the
        valuation is rejected with `ERR_INSUFFICIENT_COMPARABLES` (HTTP 422);
        three or more are always required."
        PRD §3.2: "Only `VERIFIED` comparables ever enter a valuation's input
        set."

        Design: Difficulty/boundary_precision_check/valuation_minimum_three_verified_comps_boundary
        """
        listing = create_draft_listing(tail_number="N1773GS", total_time_hours=2900)
        create_comparable_sale(make="Gulfstream", model="G550", year=2014,
                               sale_price_usd=4123456.05, sale_date="2026-01-20",
                               total_time_hours=3001, comp_status="VERIFIED")
        create_comparable_sale(make="Gulfstream", model="G550", year=2016,
                               sale_price_usd=4350000.00, sale_date="2026-02-11",
                               total_time_hours=2850, comp_status="VERIFIED")
        create_comparable_sale(make="Gulfstream", model="G550", year=2013,
                               sale_price_usd=3980000.55, sale_date="2026-03-02",
                               total_time_hours=3100, comp_status="UNVERIFIED")
        resp = api.run_valuation(listing["id"], {"variant": "FINAL"}, LISTING_AGENT)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COMPARABLES)

    def test_valuation_with_third_verified_comp_succeeds(self, api):
        """PRD §3.2: "If that set contains fewer than three comparables, the
        valuation is rejected with `ERR_INSUFFICIENT_COMPARABLES` (HTTP 422);
        three or more are always required."
        PRD §3.2: "The valuation is then the sum of those already-rounded
        adjusted prices divided by the number of comparables, with the final
        quotient itself rounded half up to two decimal places."

        Design: Difficulty/boundary_precision_check/valuation_minimum_three_verified_comps_boundary
        """
        listing = create_draft_listing(tail_number="N1773GS", total_time_hours=2900)
        create_comparable_sale(make="Gulfstream", model="G550", year=2014,
                               sale_price_usd=4123456.05, sale_date="2026-01-20",
                               total_time_hours=3001, comp_status="VERIFIED")
        create_comparable_sale(make="Gulfstream", model="G550", year=2016,
                               sale_price_usd=4350000.00, sale_date="2026-02-11",
                               total_time_hours=2850, comp_status="VERIFIED")
        create_comparable_sale(make="Gulfstream", model="G550", year=2013,
                               sale_price_usd=3980000.55, sale_date="2026-03-02",
                               total_time_hours=3100, comp_status="UNVERIFIED")
        resp = api.run_valuation(listing["id"], {"variant": "FINAL"}, LISTING_AGENT)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COMPARABLES)
        # A third VERIFIED comp (3900000.00 @ exactly the listing's 2900 hours,
        # adjustment factor 1) reaches the minimum count.
        create_comparable_sale(make="Gulfstream", model="G550", year=2015,
                               sale_price_usd=3900000.00, sale_date="2026-04-01",
                               total_time_hours=2900, comp_status="VERIFIED")
        result = validate_success(
            api.run_valuation(listing["id"], {"variant": "FINAL"}, LISTING_AGENT))
        # Only VERIFIED comps enter the input set, so the UNVERIFIED 3980000.55
        # comp stays excluded: (4106797.29 + 4358700.00 + 3900000.00) / 3 =
        # 4121832.43.
        assert_money(result["market_value_estimate_usd"],
                     EXPECTED_FINAL_VALUE_FOUR_COMPS,
                     "FINAL value over the three-VERIFIED-comp input set")
        assert result["valuation_status"] == "FINAL"


class TestValuationInputSetFiltering:
    def test_valuation_input_set_excludes_non_matching_and_unverified(self, api):
        """PRD §3.2: "The input set for both variants is the collection of
        `VERIFIED` comparable sales whose `make` and `model` exactly equal the
        listing's `make` and `model` — an exact string match, not a fuzzy one."
        PRD §3.2: "Only `VERIFIED` comparables ever enter a valuation's input
        set."

        Design: Corner/calculations/valuation_input_set_excludes_non_matching_and_unverified
        """
        listing = create_draft_listing(tail_number="N1773GS", total_time_hours=2900)
        setup_canonical_comps()
        # Polluting rows: an UNVERIFIED G550 comp priced at 100.00 and a
        # VERIFIED comp of a different make/model.
        create_comparable_sale(make="Gulfstream", model="G550", year=2012,
                               sale_price_usd=100.00, sale_date="2026-01-05",
                               total_time_hours=9000, comp_status="UNVERIFIED")
        create_comparable_sale(make="Cessna", model="Citation X", year=2015,
                               sale_price_usd=9000000.00, sale_date="2026-02-01",
                               total_time_hours=2500, comp_status="VERIFIED")
        result = validate_success(
            api.run_valuation(listing["id"], {"variant": "PROVISIONAL"}, LISTING_AGENT))
        assert_money(result["market_value_estimate_usd"], EXPECTED_PROVISIONAL_VALUE,
                     "PROVISIONAL value over the unpolluted input set")


class TestActivationGate:
    def test_activate_with_provisional_only_returns_valuation_required(self, api):
        """PRD §3.2: "a `ListingAgent` may activate a `DRAFT` listing only when
        its `valuation_status` is `FINAL`, moving it to `ACTIVE`; attempting
        activation without a FINAL-variant valuation on record is rejected with
        `ERR_VALUATION_REQUIRED` (HTTP 409), and a successful activation
        increments the listing's `version`."

        Design: Corner/state_machines/activate_with_provisional_only_returns_valuation_required
        """
        listing = create_draft_listing()
        setup_canonical_comps()
        run_valuation(listing["id"], "PROVISIONAL")
        resp = api.activate_listing(listing["id"], LISTING_AGENT)
        validate_error(resp, ApiErrorId.ERR_VALUATION_REQUIRED)
        fetched = validate_success(api.get_listing(listing["id"], LISTING_AGENT))
        assert fetched["status"] == "DRAFT", "Rejected activation leaves the listing DRAFT"

    def test_activate_with_final_valuation_succeeds(self, api):
        """PRD §3.2: "a `ListingAgent` may activate a `DRAFT` listing only when
        its `valuation_status` is `FINAL`, moving it to `ACTIVE`; attempting
        activation without a FINAL-variant valuation on record is rejected with
        `ERR_VALUATION_REQUIRED` (HTTP 409), and a successful activation
        increments the listing's `version`."

        Design: Corner/state_machines/activate_with_provisional_only_returns_valuation_required
        """
        listing = setup_active_listing(tail_number="N1001GS")
        assert listing["status"] == "ACTIVE"
        assert listing["valuation_status"] == "FINAL"
        assert_money(listing["market_value_estimate_usd"], EXPECTED_FINAL_VALUE,
                     "FINAL valuation persisted before activation")
