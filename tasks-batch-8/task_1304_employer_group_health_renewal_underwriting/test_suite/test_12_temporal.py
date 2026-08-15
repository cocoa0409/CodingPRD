"""Logical clock and quote expiry against the renewal effective date."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    api_client,
    setup_case_with_proposed_quote,
    make_broker_headers,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]


class TestQuoteExpiry:
    def test_quote_window_expires_at_effective_minus_30d(self):
        """PRD section 3.6: "any quote still sitting in `PROPOSED` or `COUNTERED`
        once the logical clock passes thirty days before the case's
        `effective_date` expires automatically to `EXPIRED`."
        PRD section 3.6: "Accepting a quote requires the quote to be `PROPOSED`
        (else `ERR_QUOTE_NOT_PROPOSED`)".

        Design: Difficulty/resource_temporal_overlap/quote_window_expires_at_effective_minus_30d
        """
        broker, case, plan, quote = setup_case_with_proposed_quote()
        # effective_date 2027-01-01 -> cutoff 2026-12-02; jump past it.
        validate_success(api_client.set_current_utc("2026-12-03T00:00:00Z", UW))
        quote = get_success_data(api_client.get_quote(quote["id"], UW))
        assert quote["status"] == "EXPIRED"
        resp = api_client.accept_quote(
            quote["id"], make_broker_headers(broker["id"])
        )
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_PROPOSED)
        case = get_success_data(api_client.get_case(case["id"], UW))
        assert case["status"] == "QUOTED"

    def test_quote_alive_before_expiry_window(self):
        """PRD section 3.6: "any quote still sitting in `PROPOSED` or `COUNTERED`
        once the logical clock passes thirty days before the case's
        `effective_date` expires automatically to `EXPIRED`."
        PRD section 2.8: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`."
        With the clock at the default 2026-08-01 the cutoff (2026-12-02) has not
        passed, so the quote is still PROPOSED and acceptable.

        Design: Difficulty/resource_temporal_overlap/quote_window_expires_at_effective_minus_30d
        """
        broker, case, plan, quote = setup_case_with_proposed_quote()
        quote = get_success_data(api_client.get_quote(quote["id"], UW))
        assert quote["status"] == "PROPOSED"
        data = validate_success(
            api_client.accept_quote(quote["id"], make_broker_headers(broker["id"]))
        )
        assert data["status"] == "ACCEPTED"


class TestLevelFundedSplitInvariant:
    def test_level_funded_split_conserves_total_pepm_after_cycle(self):
        """PRD section 3.5: "For a `LEVEL_FUNDED` quote that PEPM decomposes into
        three components that must sum back exactly to the whole:
        `claims_fund_cents` at 82 percent of the rate, `admin_fee_cents` at 12
        percent, and `stop_loss_premium_cents` at 6 percent".

        Design: Difficulty/compensating_invariant/level_funded_split_conserves_total_pepm
        """
        from test_helpers import (
            setup_case_with_proposed_quote,
            create_counter_payload,
            create_respond_payload,
        )
        broker, case, plan, quote = setup_case_with_proposed_quote(
            quote_funding_type="LEVEL_FUNDED", case_funding_type="LEVEL_FUNDED"
        )
        assert quote["pepm_rate_cents"] == 5338
        assert (
            quote["claims_fund_cents"]
            + quote["admin_fee_cents"]
            + quote["stop_loss_premium_cents"]
        ) == 5338

        broker_headers = make_broker_headers(broker["id"])
        validate_success(api_client.counter_quote(
            quote["id"], create_counter_payload(), broker_headers))
        validate_success(api_client.respond_quote(
            quote["id"], create_respond_payload(), UW))
        quote = get_success_data(api_client.get_quote(quote["id"], UW))
        assert quote["pepm_rate_cents"] == 5338
        assert (
            quote["claims_fund_cents"]
            + quote["admin_fee_cents"]
            + quote["stop_loss_premium_cents"]
        ) == 5338
        assert quote["annual_premium_cents"] == 25622400

    def test_level_funded_split_components_at_propose(self):
        """PRD section 3.5: "`claims_fund_cents` at 82 percent of the rate,
        `admin_fee_cents` at 12 percent, and `stop_loss_premium_cents` at 6
        percent; for a `FULLY_INSURED` quote these components do not apply."

        Design: Difficulty/compensating_invariant/level_funded_split_conserves_total_pepm
        """
        from test_helpers import setup_case_with_proposed_quote
        broker, case, plan, quote = setup_case_with_proposed_quote(
            quote_funding_type="LEVEL_FUNDED", case_funding_type="LEVEL_FUNDED"
        )
        pepm = quote["pepm_rate_cents"]
        assert quote["claims_fund_cents"] == round(pepm * 0.82)
        assert quote["admin_fee_cents"] == round(pepm * 0.12)
        assert quote["stop_loss_premium_cents"] == round(pepm * 0.06)
        assert (
            quote["claims_fund_cents"]
            + quote["admin_fee_cents"]
            + quote["stop_loss_premium_cents"]
        ) == pepm
