"""Quote lifecycle, dual-variant pricing, tax rounding, expiry, and OCC."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, make_customer_headers,
    assert_quote, assert_priced_quote,
    set_clock, make_customer, make_quote, price_quote, accept_quote,
)


def _price(customer_id, **quote_overrides):
    quote = make_quote(customer_id, **quote_overrides)
    return price_quote(quote["id"])


class TestQuoteLifecycle:
    def test_quote_initial_state_is_draft(self, api, quote_agent_headers):
        """PRD §3.3: "The quote is born in `DRAFT`."

        Design: Corner/state_machines/quote_initial_state_is_draft
        """
        set_clock()
        customer = make_customer(company_name="Init Test")
        res = api.create_quote(
            {"customer_id": customer["id"], "trip_date": "2026-09-01T08:00:00Z",
             "return_date": "2026-09-01T16:00:00Z", "origin": "Dallas TX",
             "destination": "Austin TX", "passenger_count": 40,
             "estimated_miles": 300, "estimated_hours": 5,
             "vehicle_class_requested": "STANDARD"},
            quote_agent_headers)
        quote = validate_success(res, 201)
        assert_quote(quote)
        assert quote["status"] == "DRAFT"

    def test_quote_cancel_from_accepted_returns_invalid_state(self, api):
        """PRD §3.3: "Either the customer or a quote agent may cancel a quote from
        `DRAFT` or from `QUOTED`, moving it to `CANCELLED`." PRD §2.8: "4. State
        validity: the target entity is in a state from which the requested
        transition exists per Section 3, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/quote_cancel_from_accepted_returns_invalid_state
        """
        set_clock()
        customer = make_customer(company_name="Cancel Test")
        quote = _price(customer["id"])
        accept_quote(quote["id"], customer["id"])
        res = api.cancel_quote(quote["id"], make_customer_headers(customer["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_expired_quote_accept_rejected(self, api):
        """PRD §3.4: "the quote must still be inside its seventy-two-hour window —
        a lapsed quote rejects with `ERR_QUOTE_EXPIRED`". PRD §3.3: pricing
        "stamps `quote_expiry` seventy-two hours after creation".

        Design: Corner/validations/error_quote_expired_on_accept
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(company_name="Expired Test")
        quote = _price(customer["id"])
        set_clock("2026-08-05T00:00:00Z")
        res = api.accept_quote(quote["id"],
                               {"expected_quote_version": quote["version"]},
                               make_customer_headers(customer["id"]))
        validate_error(res, ApiErrorId.ERR_QUOTE_EXPIRED)

    def test_check_expiry_transitions_expired_quote(self, api, quote_agent_headers):
        """PRD §2.6: "A quote still in `QUOTED` once the logical clock reaches its
        `quote_expiry` transitions to `EXPIRED` when the quote is read; a
        `QuoteAgent` or `DispatchManager` may also force the check through the
        quote expiry-check capability."

        Design: Corner/endpoints/quote_check_expiry_endpoint_transitions_expired_quote
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(company_name="Expiry Co")
        quote = _price(customer["id"])
        set_clock("2026-08-05T00:00:00Z")
        res = api.check_quote_expiry(quote["id"], quote_agent_headers)
        quote_after = validate_success(res)
        assert quote_after["status"] == "EXPIRED"

    def test_stale_version_on_quote_accept(self, api):
        """PRD §2.7: "If the quote's current `version` has advanced since that
        read — because the quote was repriced or otherwise mutated in the
        meantime — acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412),
        and no order is created."

        Design: Corner/errors/error_stale_version_on_quote_accept
        """
        set_clock()
        customer = make_customer(company_name="Stale Co")
        quote = _price(customer["id"])
        stale_version = quote["version"] - 1
        res = api.accept_quote(quote["id"],
                               {"expected_quote_version": stale_version},
                               make_customer_headers(customer["id"]))
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestDualVariantPricing:
    def test_mileage_primary_variant_for_highway_trip(self, api, quote_agent_headers):
        """PRD §3.3: "When `estimated_miles` divided by `estimated_hours` is at
        least 55.0 — a highway-dominated trip averaging fifty-five miles per hour
        or better — the quote prices under `MILEAGE_PRIMARY`". PRD §3.3: "A
        `STANDARD` coach bills at 250 cents per mile and 15,000 cents per hour"
        and "Under `MILEAGE_PRIMARY`, the base charge is the full
        `estimated_miles` multiplied by the mileage rate, and only the estimated
        hours beyond the included five are billed additionally — at one half of
        the hourly rate, rounded half-up to integer cents."

        600 mi / 8 h = 75.0 >= 55.0 -> MILEAGE_PRIMARY; subtotal =
        600*250 + round((8-5)*15000*0.5) = 150000 + 22500 = 172500.

        Design: Difficulty/dual_variant_calc/quote_pricing_mileage_vs_hourly_variant
        """
        set_clock()
        customer = make_customer(company_name="Acme Corp")
        quote = _price(customer["id"], trip_date="2026-09-01T08:00:00Z",
                       return_date="2026-09-01T16:00:00Z",
                       estimated_miles=600, estimated_hours=8)
        assert_priced_quote(quote)
        assert quote["pricing_variant"] == "MILEAGE_PRIMARY"
        assert quote["subtotal_cents"] == 172500
        assert quote["tax_cents"] == 14231
        assert quote["total_cents"] == 186731

    def test_hourly_primary_variant_for_local_trip(self, api, quote_agent_headers):
        """PRD §3.3: "below that ratio it prices under `HOURLY_PRIMARY`, and the
        selection is recorded in `pricing_variant`." PRD §3.3: "Under
        `HOURLY_PRIMARY`, the base charge is the `estimated_hours` multiplied by
        the hourly rate, rounded half-up to integer cents, and only the estimated
        miles beyond the included one hundred are billed additionally".

        80 mi / 12 h = 6.67 < 55 -> HOURLY_PRIMARY; subtotal = 12*15000 (base)
        + 25000 (one overnight night) + 45000 (relief driver) = 250000.

        Design: Difficulty/dual_variant_calc/quote_pricing_mileage_vs_hourly_variant
        """
        set_clock()
        customer = make_customer(company_name="Local Trips Inc")
        quote = _price(customer["id"], trip_date="2026-09-05T08:00:00Z",
                       return_date="2026-09-05T20:00:00Z",
                       estimated_miles=80, estimated_hours=12)
        assert_priced_quote(quote)
        assert quote["pricing_variant"] == "HOURLY_PRIMARY"
        assert quote["subtotal_cents"] == 250000
        assert quote["tax_cents"] == 20625
        assert quote["total_cents"] == 270625


class TestMultiInputTieredPricing:
    def test_overnight_and_relief_requirements_add_fees(self, api, quote_agent_headers):
        """PRD §3.3: "`requires_overnight` is set when `estimated_hours` exceeds
        10 or when the itinerary between `trip_date` and `return_date` crosses
        midnight." and "the number of nights is `estimated_hours` divided by 24
        and rounded up to the next whole night, each night billed at a flat
        25,000 cents, recorded in `overnight_fee_cents`. A relief requirement
        adds a flat 45,000 cents in `relief_driver_fee_cents`."

        14-hour trip: overnight (14 > 10, one night = 25000) and relief
        (14 h exceeds the 11 h single-driver limit = 45000) both apply.

        Design: Difficulty/combinatorial_formula/quote_pricing_multi_input_tiered_rates
        """
        set_clock()
        customer = make_customer(company_name="Exec Travel")
        quote = _price(customer["id"], trip_date="2026-09-10T06:00:00Z",
                       return_date="2026-09-10T20:00:00Z",
                       estimated_miles=400, estimated_hours=14,
                       ada_required=True, vehicle_class_requested="EXECUTIVE")
        assert_priced_quote(quote)
        assert quote["requires_overnight"] is True
        assert quote["requires_relief_driver"] is True
        assert quote["overnight_fee_cents"] == 25000
        assert quote["relief_driver_fee_cents"] == 45000

    def test_executive_rates_variant_and_ada_surcharge(self, api, quote_agent_headers):
        """PRD §3.3: "`EXECUTIVE` bills at 500 cents per mile and 30,000 cents per
        hour". PRD §3.3: "When `ada_required` is set, a surcharge of five percent
        of the combined base and supplementary charges — rounded half-up to
        integer cents — is added."

        400 mi / 14 h = 28.57 < 55 -> HOURLY_PRIMARY: base round(14*30000) =
        420000; supplementary (400-100) mi at half of 500 = 75000; ADA surcharge
        round(0.05 * 495000) = 24750; subtotal = 495000 + 25000 + 45000 + 24750
        = 589750.

        Design: Difficulty/combinatorial_formula/quote_pricing_multi_input_tiered_rates
        """
        set_clock()
        customer = make_customer(company_name="Exec Travel 2")
        quote = _price(customer["id"], trip_date="2026-09-10T06:00:00Z",
                       return_date="2026-09-10T20:00:00Z",
                       estimated_miles=400, estimated_hours=14,
                       ada_required=True, vehicle_class_requested="EXECUTIVE")
        assert quote["mileage_rate_cents"] == 500
        assert quote["hourly_rate_cents"] == 30000
        assert quote["pricing_variant"] == "HOURLY_PRIMARY"
        assert quote["subtotal_cents"] == 589750


class TestTaxRoundingOrder:
    def test_tax_computed_on_summed_subtotal(self, api, quote_agent_headers):
        """PRD §3.3: "The quote's `subtotal_cents` then sums the base charge, the
        supplementary charge, the overnight fee, the relief fee, and the ADA
        surcharge. `tax_cents` is 8.25 percent of the subtotal, rounded half-up
        to integer cents". PRD §3.3: "`total_cents` is the sum of subtotal and
        tax."

        600 mi / 8 h STANDARD: subtotal 172500; tax = round(172500 * 0.0825) =
        14231; total = 186731.

        Design: Difficulty/combinatorial_formula/quote_tax_rounding_order_sum_then_round
        """
        set_clock()
        customer = make_customer(company_name="Round Test Co")
        quote = _price(customer["id"], trip_date="2026-09-15T08:00:00Z",
                       return_date="2026-09-15T16:00:00Z",
                       estimated_miles=600, estimated_hours=8)
        assert quote["subtotal_cents"] == 172500
        assert quote["tax_cents"] == 14231
        assert quote["total_cents"] == 186731
        assert quote["total_cents"] == quote["subtotal_cents"] + quote["tax_cents"]

    def test_tax_exempt_customer_pays_zero_tax(self, api, quote_agent_headers):
        """PRD §3.3: "`tax_cents` is 8.25 percent of the subtotal, rounded half-up
        to integer cents — and is zero for a tax-exempt customer."

        Design: Difficulty/combinatorial_formula/quote_tax_rounding_order_sum_then_round
        """
        set_clock()
        customer = make_customer(company_name="Exempt Org", tax_exempt=True)
        quote = _price(customer["id"], trip_date="2026-09-15T08:00:00Z",
                       return_date="2026-09-15T16:00:00Z",
                       estimated_miles=600, estimated_hours=8)
        assert quote["subtotal_cents"] == 172500
        assert quote["tax_cents"] == 0
        assert quote["total_cents"] == 172500
