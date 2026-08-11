"""Entitlement record-position basis variants (PRD §3.4).

Covers the dual TRADE_DATE_BASIS / SETTLED_BASIS projection and the
claim-compensation EVENT_TERMS / MARKET_VALUE variant pair.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_security, make_account, make_lot, make_event_source,
    make_scrubbed_event, make_confirmed_event, set_clock,
    make_missed_entitlement_context, file_claim, get_entitlement_for,
    make_account_holder_headers, make_examiner_headers,
    split_terms,
)
from test_helpers.fixtures import ADMIN, VENDOR, ANALYST_1, ANALYST_2, OPS
from test_helpers import api_client


def _setup_divergence_scenario():
    """ACME; A1 holds 1000 sh (acq 2026-04-01) + 250 sh (acq 2026-05-14);
    SPLIT 2:1, record 2026-05-15, CONFIRMED."""
    sec = make_security(ticker="ACME", cusip="CUSP000001")
    acct = make_account(account_number="A-1", holder_name="Holder One")
    make_lot(acct["id"], sec["id"], quantity=1000,
             acquisition_date="2026-04-01", cost_basis_total_cents=10000000)
    make_lot(acct["id"], sec["id"], quantity=250,
             acquisition_date="2026-05-14", cost_basis_total_cents=2500000)
    terms = split_terms(ratio_num=2, ratio_den=1, price_per_share_cents=3333,
                        fractional_policy="ROUND_HALF_UP")
    event, _, _ = make_confirmed_event(
        sec["id"], "SPLIT", terms, record_date="2026-05-15",
        payable_date="2026-05-29")
    return sec, acct, event


class TestEntitlementBasisDivergence:
    def test_projected_trade_date_basis_includes_unsettled_lot(self, api):
        """PRD §3.4: "Under `TRADE_DATE_BASIS` — used for projections at confirm and amendment time — a lot is included when its `acquisition_date` falls on or before the record date, even if the trade would not have settled by then."

        Design: Difficulty/dual_variant_calc/entitlement_basis_divergence_trade_vs_settled
        """
        _, acct, event = _setup_divergence_scenario()
        ent = get_entitlement_for(event["id"], acct["id"])
        assert ent["record_position_quantity"] == 1250
        assert ent["entitled_shares"] == 2500
        assert ent["calculation_basis"] == "TRADE_DATE_BASIS"

    def test_capture_settled_basis_excludes_unsettled_lot(self, api):
        """PRD §3.4: "Under `SETTLED_BASIS` — used when positions are firmed up at the record date — a lot is included only when its `acquisition_date` falls on or before two days before the record date, mirroring the market's settlement lag."
        PRD §3.6: "Capture recomputes every `PROJECTED` entitlement in place under `SETTLED_BASIS` — `record_position_quantity`, `entitled_shares`, `fractional_shares`, `cash_in_lieu_cents`, and `cash_amount_cents` are all overwritten with the settled-basis figures, `calculation_basis` becomes `SETTLED_BASIS`, and the entitlement moves `PROJECTED` → `FIRM` with its `version` incremented."

        Design: Difficulty/dual_variant_calc/entitlement_basis_divergence_trade_vs_settled
        """
        _, acct, event = _setup_divergence_scenario()
        projected = get_entitlement_for(event["id"], acct["id"])
        assert projected["entitled_shares"] == 2500
        set_clock("2026-05-15T00:00:00Z")
        validate_success(api.capture_record_position(event["id"], OPS))
        firm = get_success_data(api.get_entitlement(projected["id"], OPS))
        assert firm["record_position_quantity"] == 1000
        assert firm["entitled_shares"] == 2000
        assert firm["calculation_basis"] == "SETTLED_BASIS"
        assert firm["status"] == "FIRM"
        assert firm["entitled_shares"] != projected["entitled_shares"]


class TestClaimCompensationBasisVariants:
    def _setup_pair(self):
        """Two securities; identical 5-share accounts; SPLIT 2:1 price 5000 on
        each; EVENT_TERMS on one, MARKET_VALUE on the other; both accounts
        FROZEN before booking so both entitlements go MISSED."""
        ctx_t = make_missed_entitlement_context(
            price_per_share_cents=5000, compensation_pool_cents=100000,
            claim_basis="EVENT_TERMS", account_shares=5)
        ctx_m = make_missed_entitlement_context(
            price_per_share_cents=5000, compensation_pool_cents=100000,
            claim_basis="MARKET_VALUE", account_shares=5)
        return ctx_t, ctx_m

    def test_event_terms_basis_uses_terms_price(self, api):
        """PRD §3.8: "Under the `EVENT_TERMS` variant, compensation is the entitlement's `cash_amount_cents`, plus its `entitled_shares` valued at the event terms' `price_per_share_cents` — zero when the terms carry no per-share price — plus its `cash_in_lieu_cents`."

        Design: Difficulty/dual_variant_calc/claim_compensation_event_terms_vs_market_value
        """
        ctx_t, _ = self._setup_pair()
        assert ctx_t["entitlement"]["status"] == "MISSED"
        claim = file_claim(ctx_t["event"]["id"], ctx_t["entitlement"]["id"],
                           ctx_t["account"]["id"], claimed_amount_cents=50000)
        decided = validate_success(api.decide_claim(
            claim["id"], {"decision": "APPROVED"}, make_examiner_headers("examiner-1")))
        # 5 sh x 2 = 10 entitled shares x 5000 = 50000
        assert decided["compensation_cents"] == 50000

    def test_market_value_basis_uses_filing_price(self, api):
        """PRD §3.8: "Under the `MARKET_VALUE` variant, the same three components apply but the shares are valued at the claim's `market_price_cents` supplied at filing, which is why that field is required when the event's basis is `MARKET_VALUE`. The same entitlement therefore yields different compensation when the terms price and the filing-time market price differ."

        Design: Difficulty/dual_variant_calc/claim_compensation_event_terms_vs_market_value
        """
        _, ctx_m = self._setup_pair()
        claim = file_claim(ctx_m["event"]["id"], ctx_m["entitlement"]["id"],
                           ctx_m["account"]["id"], claimed_amount_cents=56000,
                           market_price_cents=5600)
        decided = validate_success(api.decide_claim(
            claim["id"], {"decision": "APPROVED"}, make_examiner_headers("examiner-1")))
        # 10 entitled shares x 5600 market = 56000
        assert decided["compensation_cents"] == 56000
