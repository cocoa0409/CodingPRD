"""Deal qualification thresholds, LOI negotiation cycle, precedence, capital conservation, and OCC."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, make_broker_headers, make_buyer_headers, make_seller_headers,
    create_loi_payload,
)
from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Design: Difficulty/boundary_precision_check/qualify_proof_of_funds_inclusive_boundary
# ---------------------------------------------------------------------------
class TestQualifyProofOfFundsBoundary:
    def test_proof_exactly_required_down_payment_qualifies(self, api):
        """PRD §3.4: "the buyer's `proof_of_funds_cents` must be at least the required down payment,
        which is ten percent of the listing's `asking_price_cents`, rounded half up; falling
        short is rejected with `ERR_INSUFFICIENT_FUNDS`."
        PRD §3.4: "All three comparisons are inclusive — meeting a threshold exactly is sufficient."

        Design: Difficulty/boundary_precision_check/qualify_proof_of_funds_inclusive_boundary
        """
        s = fx.setup_prospect_deal(
            api, buyer_proof_of_funds_cents=12_000_000, buyer_net_worth_cents=80_000_000
        )
        data = validate_success(api.qualify_deal(s["deal"]["id"], make_broker_headers(s["broker"]["id"])))
        assert data["status"] == "QUALIFIED"

    def test_proof_one_cent_below_required_rejected(self, api):
        """PRD §3.4: "the buyer's `proof_of_funds_cents` must be at least the required down payment,
        which is ten percent of the listing's `asking_price_cents`, rounded half up; falling
        short is rejected with `ERR_INSUFFICIENT_FUNDS`."

        Design: Difficulty/boundary_precision_check/qualify_proof_of_funds_inclusive_boundary
        """
        s = fx.setup_prospect_deal(
            api, buyer_proof_of_funds_cents=11_999_999, buyer_net_worth_cents=80_000_000
        )
        resp = api.qualify_deal(s["deal"]["id"], make_broker_headers(s["broker"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)


# ---------------------------------------------------------------------------
# Design: Difficulty/non_linear_state_machine/loi_negotiation_counter_revise_cycle
# ---------------------------------------------------------------------------
class TestLOINegotiationCycle:
    def test_counter_moves_to_countered_and_increments_round(self, api):
        """PRD §3.5: "A `Seller` **counters** an offer that is in `SUBMITTED`, recording a
        `counter_price_cents`, incrementing the `round_number` by one, and moving the offer to
        `COUNTERED`; a counter attempted from any other status is rejected with `ERR_LOI_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/loi_negotiation_counter_revise_cycle
        """
        s = fx.setup_submitted_loi(api, offer_price_cents=110_000_000, earnest_deposit_cents=5_000_000)
        data = validate_success(
            api.counter_loi(s["loi"]["id"], {"counter_price_cents": 118_000_000},
                            make_seller_headers(s["seller"]["id"]))
        )
        assert data["status"] == "COUNTERED"
        assert data["round_number"] == 2

    def test_revise_returns_to_submitted_and_increments_round(self, api):
        """PRD §3.5: "The buyer may then **revise** an offer that is in `COUNTERED`, supplying an
        updated `offer_price_cents` and `earnest_deposit_cents`; this clears the
        `counter_price_cents`, increments the `round_number` by one, and returns the offer to
        `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/loi_negotiation_counter_revise_cycle
        """
        s = fx.setup_submitted_loi(api, offer_price_cents=110_000_000, earnest_deposit_cents=5_000_000)
        validate_success(
            api.counter_loi(s["loi"]["id"], {"counter_price_cents": 118_000_000},
                            make_seller_headers(s["seller"]["id"]))
        )
        data = validate_success(
            api.revise_loi(s["loi"]["id"], {"offer_price_cents": 115_000_000, "earnest_deposit_cents": 5_000_000},
                           make_buyer_headers(s["buyer"]["id"]))
        )
        assert data["status"] == "SUBMITTED"
        assert data["round_number"] == 3


# ---------------------------------------------------------------------------
# Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_loi_submit
# ---------------------------------------------------------------------------
class TestStateBeatsFiscalOnLOISubmit:
    def _submit_on_prospect(self, api):
        s = fx.setup_prospect_deal(api, buyer_proof_of_funds_cents=3_000_000)
        resp = api.submit_loi(
            s["deal"]["id"],
            create_loi_payload(s["deal_version"], offer_price_cents=115_000_000, earnest_deposit_cents=5_000_000),
            make_buyer_headers(s["buyer"]["id"]),
        )
        return s, resp

    def test_prospect_deal_reports_not_qualified_over_insufficient_funds(self, api):
        """PRD §3.5: "Submission is admitted only when the deal is in `QUALIFIED`; otherwise it is
        rejected with `ERR_DEAL_NOT_QUALIFIED`."
        PRD §2.6: "When several checks could reject the same request, they are evaluated in a
        fixed priority order so that the returned error is deterministic."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_loi_submit
        """
        _s, resp = self._submit_on_prospect(api)
        validate_error(resp, ApiErrorId.ERR_DEAL_NOT_QUALIFIED.value)

    def test_rejected_submit_leaves_deal_in_prospect(self, api):
        """PRD §3.5: "Submission is admitted only when the deal is in `QUALIFIED`; otherwise it is
        rejected with `ERR_DEAL_NOT_QUALIFIED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_loi_submit
        """
        s, _resp = self._submit_on_prospect(api)
        deal = validate_success(api.get_deal(s["deal"]["id"], make_broker_headers(s["broker"]["id"])))
        assert deal["status"] == "PROSPECT"


# ---------------------------------------------------------------------------
# Design: Difficulty/compensating_invariant/buyer_capital_conserved_across_loi_submit_withdraw
# ---------------------------------------------------------------------------
class TestBuyerCapitalConservation:
    def test_loi_submit_encumbers_earnest(self, api):
        """PRD §3.5: "the new offer's earnest is added to the buyer's `committed_capital_cents`,
        and the deal's `version` increments by one."
        PRD §2.8: "the system derives a read-only `available_capital_cents`, defined as
        `proof_of_funds_cents` minus `committed_capital_cents` minus `escrowed_cents`."

        Design: Difficulty/compensating_invariant/buyer_capital_conserved_across_loi_submit_withdraw
        """
        s = fx.setup_qualified_deal(api, buyer_proof_of_funds_cents=50_000_000)
        validate_success(
            api.submit_loi(
                s["deal"]["id"],
                create_loi_payload(s["deal_version"], offer_price_cents=115_000_000, earnest_deposit_cents=5_000_000),
                make_buyer_headers(s["buyer"]["id"]),
            ),
            expected_status=201,
        )
        buyer = fx.get_buyer(api, s["buyer"]["id"])
        assert buyer["committed_capital_cents"] == 5_000_000
        assert buyer["available_capital_cents"] == 45_000_000

    def test_loi_withdraw_releases_earnest(self, api):
        """PRD §3.5: "a `Buyer` may **withdraw** their own offer while it is in `SUBMITTED` or
        `COUNTERED`, moving it to the terminal `WITHDRAWN` and likewise releasing the earnest
        from `committed_capital_cents`"

        Design: Difficulty/compensating_invariant/buyer_capital_conserved_across_loi_submit_withdraw
        """
        s = fx.setup_submitted_loi(api, buyer_proof_of_funds_cents=50_000_000, earnest_deposit_cents=5_000_000)
        loi = validate_success(api.withdraw_loi(s["loi"]["id"], make_buyer_headers(s["buyer"]["id"])))
        assert loi["status"] == "WITHDRAWN"
        buyer = fx.get_buyer(api, s["buyer"]["id"])
        assert buyer["committed_capital_cents"] == 0
        assert buyer["available_capital_cents"] == 50_000_000


def test_loi_submit_earnest_over_available_capital_rejected(api):
    """PRD §3.5: "the buyer's `available_capital_cents` must be at least the `earnest_deposit_cents`,
    or the submission is rejected with `ERR_INSUFFICIENT_FUNDS`."

    Design: Corner/validations/loi_submit_insufficient_available_capital_returns_402
    """
    s = fx.setup_qualified_deal(api, buyer_proof_of_funds_cents=12_000_000, buyer_net_worth_cents=80_000_000)
    resp = api.submit_loi(
        s["deal"]["id"],
        create_loi_payload(s["deal_version"], offer_price_cents=115_000_000, earnest_deposit_cents=15_000_000),
        make_buyer_headers(s["buyer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)


def test_second_loi_with_stale_deal_version_rejected(api):
    """PRD §2.11: "If that value does not match the deal's current `version` — because the deal
    has advanced since the buyer read it — the submission is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §2.11: "A successful offer submission itself increments the deal's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/loi_create_stale_deal_version_returns_412
    """
    s = fx.setup_qualified_deal(api)
    stale_version = s["deal_version"]
    validate_success(
        api.submit_loi(
            s["deal"]["id"],
            create_loi_payload(stale_version, offer_price_cents=110_000_000, earnest_deposit_cents=4_000_000),
            make_buyer_headers(s["buyer"]["id"]),
        ),
        expected_status=201,
    )
    # Second create still carries the now-stale pre-bump version.
    resp = api.submit_loi(
        s["deal"]["id"],
        create_loi_payload(stale_version, offer_price_cents=115_000_000, earnest_deposit_cents=5_000_000),
        make_buyer_headers(s["buyer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
