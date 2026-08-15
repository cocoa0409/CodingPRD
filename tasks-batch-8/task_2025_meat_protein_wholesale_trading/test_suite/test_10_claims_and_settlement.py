"""Claims: filing gates, provisional vs final settlement variants, the bounded
offer/counter cycle, the freight allowance, OCC on offers, and the
accept-time credit cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_claim,
    api_client,
    assert_claim,
    claim_offer_payload,
    counter_claim,
    create_claim_payload,
    get_claim,
    get_customer,
    make_customer_rep_headers,
    post_offer,
    setup_delivered_shipment,
    setup_filed_claim,
    setup_staging_shipment,
    validate_error,
    validate_success,
)

ADJUSTER = TEST_USERS["claims_adjuster_headers"]


class TestProvisionalVsFinalSettlement:
    def test_filing_computes_provisional_credit(self):
        """PRD §3.8: "Filing immediately computes a provisional credit,
        `provisional_credit_cents`: the smaller of the `claimed_amount_cents`
        and a claim-type percentage of the shipment's value."
        PRD §3.8: "The percentage is sixty percent for `TEMPERATURE_ABUSE`,
        fifty percent for `SPEC_NONCONFORMANCE`, one hundred percent for
        `WEIGHT_SHORTAGE`, and forty percent for `QUALITY_DEFECT`; the
        percentage of shipped value is rounded half-up to whole cents before
        the minimum against the claimed amount is taken."
        PRD §3.8: "A filed claim starts in `FILED` status with `offer_round`
        at zero, `current_offer_cents` null, and `final_settlement_cents`
        null."

        Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_settlement
        """
        ctx = setup_filed_claim(shipped_lbs=500, lot_weight=1000,
                                price_per_lb_cents=700,
                                claim_type="QUALITY_DEFECT",
                                claimed_amount_cents=200_000)
        claim = ctx["claim"]
        assert_claim(claim)
        assert claim["status"] == "FILED"
        assert claim["offer_round"] == 0
        assert claim["current_offer_cents"] is None
        assert claim["final_settlement_cents"] is None
        # min(200000, 350000 x 0.40) = min(200000, 140000)
        assert claim["provisional_credit_cents"] == 140_000, (
            f"provisional credit must be the 40%% provisional of shipped "
            f"value, got {claim['provisional_credit_cents']}"
        )

    def test_acceptance_computes_final_settlement_under_liability_cap(self):
        """PRD §3.8: "the liability cap is eighty percent of that value,
        rounded half-up to whole cents; the base settlement is the smaller of
        `current_offer_cents` and the liability cap; and a flat freight
        allowance of 15000 cents is added only when the claim's `claim_type`
        is `TEMPERATURE_ABUSE` and the shipment's `temp_compliance` is
        `BREACHED`, with the allowance otherwise zero."
        PRD §2.10: "Its value is an aggregation: sum, over the customer's
        allocations in `CONFIRMED` or `SHIPPED` status, each allocation's
        `allocated_lbs` multiplied by its `unit_price_cents`; then subtract
        the `final_settlement_cents` of the customer's claims in `SETTLED_PAID`
        status."

        Design: Difficulty/dual_variant_calc/claim_provisional_vs_final_settlement
        """
        ctx = setup_filed_claim(shipped_lbs=500, lot_weight=1000,
                                price_per_lb_cents=700,
                                claim_type="QUALITY_DEFECT",
                                claimed_amount_cents=200_000)
        claim = ctx["claim"]
        customer = ctx["customer"]
        post_offer(claim["id"], 160_000, claim["version"])

        accepted = accept_claim(claim["id"], customer)
        assert accepted["status"] == "SETTLED_PAID"
        # min(160000, round(350000 x 0.80)) + 0
        assert accepted["final_settlement_cents"] == 160_000
        assert (accepted["provisional_credit_cents"]
                != accepted["final_settlement_cents"])
        # Exposure moves from 350000 to 350000 - 160000.
        assert get_customer(customer["id"])["outstanding_exposure_cents"] == 190_000


class TestOfferCounterCycleBounded:
    def _setup_claim(self):
        return setup_filed_claim(shipped_lbs=500, lot_weight=1000,
                                 price_per_lb_cents=700,
                                 claim_type="QUALITY_DEFECT",
                                 claimed_amount_cents=200_000)

    def test_three_round_cycle_then_counter_rejected_then_accept(self):
        """PRD §3.8: "The customer answers from `OFFER_MADE`. A counter,
        carrying `counter_amount_cents`, moves the claim to `COUNTERED` and
        increments its `version`; it is permitted only while `offer_round`
        remains below three, else `ERR_CLAIM_OFFER_LIMIT_EXCEEDED`"
        PRD §3.8: "Acceptance by the owning `CustomerRep` requires
        `OFFER_MADE`, else `ERR_CLAIM_STATE_INVALID`, and moves the claim to
        `SETTLED_PAID`, computing `final_settlement_cents` at that moment"

        Design: Difficulty/non_linear_state_machine/claim_offer_counter_cycle_bounded
        """
        ctx = self._setup_claim()
        claim = ctx["claim"]
        customer = ctx["customer"]
        cid = claim["id"]

        c = post_offer(cid, 100_000, claim["version"])
        c = counter_claim(cid, customer, 180_000)
        assert c["status"] == "COUNTERED"
        c = post_offer(cid, 150_000, c["version"])
        c = counter_claim(cid, customer, 175_000)
        c = post_offer(cid, 170_000, c["version"])
        assert c["offer_round"] == 3
        assert c["current_offer_cents"] == 170_000
        assert c["status"] == "OFFER_MADE"

        resp = api_client.counter_claim(cid, {"counter_amount_cents": 179_000},
                                        make_customer_rep_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_CLAIM_OFFER_LIMIT_EXCEEDED)

        accepted = accept_claim(cid, customer)
        assert accepted["status"] == "SETTLED_PAID"
        # min(170000, round(350000 x 0.80) = 280000) + 0
        assert accepted["final_settlement_cents"] == 170_000

    def test_fourth_offer_rejected_after_round_cap(self):
        """PRD §3.8: "once `offer_round` has reached three a further offer is
        rejected with `ERR_CLAIM_OFFER_LIMIT_EXCEEDED` (HTTP 422)."

        Design: Difficulty/non_linear_state_machine/claim_offer_counter_cycle_bounded
        """
        ctx = self._setup_claim()
        claim = ctx["claim"]
        customer = ctx["customer"]
        cid = claim["id"]

        c = post_offer(cid, 100_000, claim["version"])
        c = counter_claim(cid, customer, 180_000)
        c = post_offer(cid, 150_000, c["version"])
        c = counter_claim(cid, customer, 175_000)
        c = post_offer(cid, 170_000, c["version"])
        assert c["offer_round"] == 3

        resp = api_client.post_claim_offer(
            cid, claim_offer_payload(165_000, c["version"]), ADJUSTER,
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_OFFER_LIMIT_EXCEEDED)
        after = get_claim(cid)
        assert after["offer_round"] == 3
        assert after["current_offer_cents"] == 170_000


class TestClaimAcceptCreditCascade:
    def _setup(self):
        """Customer on CREDIT_HOLD (exposure 350000 > limit 200000) with a
        DELIVERED shipment and a FILED claim; one 160000-cent offer posted."""
        ctx = setup_filed_claim(credit_limit_cents=200_000, shipped_lbs=500,
                                lot_weight=1000, price_per_lb_cents=700,
                                claim_type="QUALITY_DEFECT",
                                claimed_amount_cents=200_000)
        assert get_customer(ctx["customer"]["id"])["status"] == "CREDIT_HOLD", \
            "Setup failed: the 350000-cent grant must force CREDIT_HOLD"
        post_offer(ctx["claim"]["id"], 160_000, ctx["claim"]["version"])
        return ctx

    def test_accept_settles_and_reduces_exposure(self):
        """PRD §3.8: "Acceptance then fires a two-link cascade: the customer's
        `outstanding_exposure_cents` is reduced by `final_settlement_cents`
        through the §2.10 recompute, and the credit-hold auto-release is
        re-evaluated from the lowered exposure."

        Design: Difficulty/transitive_cascade/claim_accept_credit_cascade
        """
        ctx = self._setup()
        accepted = accept_claim(ctx["claim"]["id"], ctx["customer"])
        assert accepted["status"] == "SETTLED_PAID"
        assert accepted["final_settlement_cents"] == 160_000
        assert get_customer(ctx["customer"]["id"])[
            "outstanding_exposure_cents"] == 190_000, \
            "link 1: exposure drops by the settlement (350000 - 160000)"

    def test_accept_auto_releases_credit_hold(self):
        """PRD §3.8: "Acceptance then fires a two-link cascade: the customer's
        `outstanding_exposure_cents` is reduced by `final_settlement_cents`
        through the §2.10 recompute, and the credit-hold auto-release is
        re-evaluated from the lowered exposure."
        PRD §2.10: "a customer on `CREDIT_HOLD` whose exposure falls to the
        limit or below transitions back to `ACTIVE`."

        Design: Difficulty/transitive_cascade/claim_accept_credit_cascade
        """
        ctx = self._setup()
        accept_claim(ctx["claim"]["id"], ctx["customer"])
        after = get_customer(ctx["customer"]["id"])
        assert after["outstanding_exposure_cents"] == 190_000
        assert after["status"] == "ACTIVE", \
            "link 2: the threshold crossing must release the hold"


class TestFreightAllowance:
    def test_freight_allowance_only_when_breached(self):
        """PRD §3.8: "the liability cap is eighty percent of that value,
        rounded half-up to whole cents; the base settlement is the smaller of
        `current_offer_cents` and the liability cap; and a flat freight
        allowance of 15000 cents is added only when the claim's `claim_type`
        is `TEMPERATURE_ABUSE` and the shipment's `temp_compliance` is
        `BREACHED`, with the allowance otherwise zero."

        Design: Corner/calculations/claim_freight_allowance_only_when_breached
        """
        ctx = setup_filed_claim(shipped_lbs=500, lot_weight=1000,
                                price_per_lb_cents=700, breach=True,
                                claim_type="TEMPERATURE_ABUSE",
                                claimed_amount_cents=100_000)
        claim = ctx["claim"]
        # Provisional: min(100000, round(350000 x 0.60) = 210000)
        assert claim["provisional_credit_cents"] == 100_000

        post_offer(claim["id"], 90_000, claim["version"])
        accepted = accept_claim(claim["id"], ctx["customer"])
        # min(90000, 280000) + 15000 freight allowance
        assert accepted["final_settlement_cents"] == 105_000, (
            f"breached temp-abuse settlement must add the freight allowance, "
            f"got {accepted['final_settlement_cents']}"
        )


class TestClaimFilingGates:
    def test_temperature_claim_requires_breach(self):
        """PRD §3.8: "A `TEMPERATURE_ABUSE` claim additionally requires the
        shipment's `temp_compliance` axis to be `BREACHED`, else
        `ERR_CLAIM_TYPE_NOT_SUPPORTED` (HTTP 422)."
        PRD §3.8: "A filed claim starts in `FILED` status with `offer_round`
        at zero, `current_offer_cents` null, and `final_settlement_cents`
        null."

        Design: Corner/validations/temperature_claim_requires_breach
        """
        ctx = setup_delivered_shipment(shipped_lbs=100, lot_weight=500,
                                       breach=False)
        rep = make_customer_rep_headers(ctx["customer"]["id"])

        bad = api_client.create_claim(
            create_claim_payload(ctx["shipment"]["id"], "TEMPERATURE_ABUSE",
                                 5_000),
            rep,
        )
        validate_error(bad, ApiErrorId.ERR_CLAIM_TYPE_NOT_SUPPORTED)

        ok = api_client.create_claim(
            create_claim_payload(ctx["shipment"]["id"], "QUALITY_DEFECT",
                                 5_000),
            rep,
        )
        assert validate_success(ok, expected_status=201)["status"] == "FILED"

    def test_claim_on_staging_shipment_returns_409(self):
        """PRD §3.8: "The shipment must be `DELIVERED` or
        `REJECTED_AT_RECEIVING`, else `ERR_SHIPMENT_NOT_CLAIMABLE`."

        Design: Corner/validations/claim_on_staging_shipment_returns_409
        """
        ctx = setup_staging_shipment(shipped_lbs=100, lot_weight=500)
        resp = api_client.create_claim(
            create_claim_payload(ctx["shipment"]["id"], "QUALITY_DEFECT",
                                 5_000),
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_CLAIMABLE)

    def test_claim_accept_without_offer_returns_409(self):
        """PRD §3.8: "Acceptance by the owning `CustomerRep` requires
        `OFFER_MADE`, else `ERR_CLAIM_STATE_INVALID`"

        Design: Corner/validations/claim_accept_without_offer_returns_409
        """
        ctx = setup_filed_claim(shipped_lbs=100, lot_weight=500,
                                claim_type="SPEC_NONCONFORMANCE",
                                claimed_amount_cents=9_000)
        resp = api_client.accept_claim(
            ctx["claim"]["id"],
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_STATE_INVALID)
        assert get_claim(ctx["claim"]["id"])["status"] == "FILED"


class TestClaimOfferOcc:
    def test_occ_claim_offer_stale_version(self, claims_adjuster_headers):
        """PRD §2.9: "Posting a settlement offer against a claim requires the
        request to carry `expected_claim_version` equal to the claim's current
        `version`. A new offer legitimately supersedes the previous offer
        without changing the claim's status, so a second sequential offer
        carrying a stale `expected_claim_version` sees identical business state
        and would otherwise succeed; the version check is the only thing that
        rejects it. A mismatch is rejected with `ERR_STALE_CLAIM_VERSION`
        (HTTP 412)."
        PRD §3.8: "Each posted offer increments `offer_round` by one, sets
        `current_offer_cents` to the payload's `offer_cents` — superseding any
        prior offer — moves the claim to `OFFER_MADE`, and increments the
        claim's `version`."

        Design: Corner/cross_cutting/occ_claim_offer_stale_version
        """
        ctx = setup_filed_claim(shipped_lbs=100, lot_weight=500,
                                claim_type="QUALITY_DEFECT",
                                claimed_amount_cents=5_000)
        claim = ctx["claim"]
        cid = claim["id"]
        v1 = claim["version"]

        first = api_client.post_claim_offer(
            cid, {"offer_cents": 4_000, "expected_claim_version": v1},
            claims_adjuster_headers,
        )
        offered = validate_success(first)
        assert offered["version"] == v1 + 1
        assert offered["status"] == "OFFER_MADE"

        stale = api_client.post_claim_offer(
            cid, {"offer_cents": 4_500, "expected_claim_version": v1},
            claims_adjuster_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_CLAIM_VERSION)

        ok = api_client.post_claim_offer(
            cid,
            {"offer_cents": 4_500,
             "expected_claim_version": offered["version"]},
            claims_adjuster_headers,
        )
        revised = validate_success(ok)
        assert revised["version"] == v1 + 2
        assert revised["current_offer_cents"] == 4_500, \
            "the offer with the current version supersedes the prior offer"
