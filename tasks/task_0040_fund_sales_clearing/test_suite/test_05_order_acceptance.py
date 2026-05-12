"""PRD §3.3 / §2.10: Order submission, acceptance preconditions,
idempotency, and validation precedence pairs declared in PRD §2.10.

Validation order (PRD §2.10): auth -> RBAC -> path-not-found ->
idempotency-replay -> invalid-state -> SoD-shelf -> SoD-NAV -> SoD-recon
-> KYC -> suitability -> region -> conversion-target -> cancel-window ->
NAV-T+1 -> dividend-date -> order-limit -> fee-tiers-invalid ->
insufficient-cash -> insufficient-shares -> recon-invariant ->
fund-has-holders -> waive-not-allowed.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    assert_order,
    create_fund_payload,
    create_investor_payload,
    create_on_shelf_fund,
    create_kyc_approved_investor,
    create_investor_pending_kyc,
    create_subscribe_order_payload,
    create_redeem_order_payload,
    fee_tier,
    get_order_fresh,
    make_investor_headers,
    setup_basic_investor_and_fund,
    setup_investor_with_confirmed_subscribe,
    submit_subscribe_order,
    unique_idempotency_key,
    validate_error,
    validate_success,
)


# =====================================================================
# Happy path: SUBSCRIBE accepted
# =====================================================================
class TestSubscribeAccepted:
    def test_valid_subscribe_reaches_accepted(self, api):
        """PRD §3.3: "the order's `trade_date` is assigned by the
        acceptance-window rule, `confirm_date` is set to `trade_date`
        plus the fund's `confirmation_cycle_days` measured in calendar
        days, `status` becomes `ACCEPTED`."

        Claim: a SUBSCRIBE order passing all validations is created in
        ACCEPTED status with trade_date and confirm_date populated.
        """
        investor, fund = setup_basic_investor_and_fund()
        advance_clock_to("2026-05-04T10:00:00.000Z")
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=1_000
            ),
            make_investor_headers(investor["id"]),
        )
        order = validate_success(res, expected_status=201)
        assert_order(order)
        assert order["status"] == "ACCEPTED"
        assert order["trade_date"] is not None
        assert order["confirm_date"] is not None


# =====================================================================
# KYC precondition (PRD §3.3 / §2.10 priority 9)
# =====================================================================
class TestKycPrecondition:
    def test_pending_kyc_subscribe_rejected(self, api):
        """PRD §3.3: "the `Investor.kyc_status` equals `APPROVED`."

        PRD §2.10: "(9) investor KYC is approved before any order (else
        `ERR_KYC_NOT_APPROVED`)."

        Claim: a SUBSCRIBE order from a PENDING-KYC investor against an
        ON_SHELF fund yields ERR_KYC_NOT_APPROVED.
        """
        investor = create_investor_pending_kyc()
        fund = create_on_shelf_fund()
        # Credit cash so insufficient-cash isn't a confounding factor.
        from test_helpers import api_client, credit_cash_payload
        api_client.credit_cash(
            investor["id"], credit_cash_payload(10_000_000),
            TEST_USERS["platform_admin_headers"],
        )
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=1_000
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_KYC_NOT_APPROVED")


# =====================================================================
# Suitability (PRD §3.3 / §2.10 priority 10)
# =====================================================================
class TestSuitability:
    def test_low_tolerance_high_rating_rejected(self, api):
        """PRD §3.3: "the suitability index test holds (the investor's
        `risk_tolerance` index is at least the fund's `risk_rating`
        index, where `C1`<`C2`<`C3`<`C4`<`C5` and `R1`<`R2`<`R3`<`R4`<`R5`,
        so an `R3` fund admits a `C3`, `C4`, or `C5` investor but
        rejects a `C1` or `C2`)."

        Claim: C2 investor on an R5 fund yields ERR_SUITABILITY_MISMATCH.
        """
        investor = create_kyc_approved_investor(risk_tolerance="C2")
        fund = create_on_shelf_fund(risk_rating="R5")
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=1_000
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_SUITABILITY_MISMATCH")

    @pytest.mark.parametrize("tolerance,rating", [
        ("C3", "R3"),  # equal index
        ("C5", "R3"),  # tolerance > rating
    ])
    def test_admissible_pairs_accepted(self, api, tolerance, rating):
        """PRD §3.3: "an `R3` fund admits a `C3`, `C4`, or `C5` investor
        but rejects a `C1` or `C2`."

        Claim: C-index >= R-index passes the suitability gate.
        """
        investor = create_kyc_approved_investor(risk_tolerance=tolerance)
        fund = create_on_shelf_fund(risk_rating=rating)
        advance_clock_to("2026-06-01T10:00:00.000Z")
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=1_000
            ),
            make_investor_headers(investor["id"]),
        )
        order = validate_success(res, expected_status=201)
        assert order["status"] == "ACCEPTED"


# =====================================================================
# Region restriction (PRD §3.3 / §2.10 priority 11)
# =====================================================================
class TestRegionRestriction:
    def test_country_not_in_allowed_list_rejected(self, api):
        """PRD §3.3: "the fund's `allowed_country_codes` array either is
        empty or contains the investor's `country_code`."

        Claim: investor with country_code='US' against a fund whose
        allowed_country_codes=['CN'] yields ERR_REGION_RESTRICTED.
        """
        investor = create_kyc_approved_investor(country_code="US")
        fund = create_on_shelf_fund(allowed_country_codes=["CN"])
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=1_000
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_REGION_RESTRICTED")

    def test_empty_allowed_list_treated_as_unrestricted(self, api):
        """PRD §3.3: "the fund's `allowed_country_codes` array either is
        empty or contains the investor's `country_code`."

        Claim: an empty allowed_country_codes array admits any country.
        """
        investor = create_kyc_approved_investor(country_code="JP")
        fund = create_on_shelf_fund(allowed_country_codes=[])
        advance_clock_to("2026-06-15T10:00:00.000Z")
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=1_000
            ),
            make_investor_headers(investor["id"]),
        )
        order = validate_success(res, expected_status=201)
        assert order["status"] == "ACCEPTED"


# =====================================================================
# Order amount/share limits (PRD §3.3 / §2.10 priority 16)
# =====================================================================
class TestOrderLimits:
    def test_below_min_subscription_amount_rejected(self, api):
        """PRD §3.3: "for `SUBSCRIBE`, `gross_amount_cents` must lie in the
        inclusive range from `min_subscription_amount_cents` up to
        `max_subscription_amount_cents` (unlimited if that field is
        null)."

        Claim: gross_amount below min triggers ERR_ORDER_LIMIT_VIOLATED.
        """
        investor = create_kyc_approved_investor()
        fund = create_on_shelf_fund(min_subscription_amount_cents=50_000)
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=10_000
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_ORDER_LIMIT_VIOLATED")

    def test_above_max_subscription_amount_rejected(self, api):
        """PRD §3.3: "for `SUBSCRIBE`, `gross_amount_cents` must lie in the
        inclusive range from `min_subscription_amount_cents` up to
        `max_subscription_amount_cents` (unlimited if that field is
        null)."

        Claim: gross_amount above max triggers ERR_ORDER_LIMIT_VIOLATED.
        """
        investor = create_kyc_approved_investor()
        fund = create_on_shelf_fund(
            min_subscription_amount_cents=1,
            max_subscription_amount_cents=1_000,
        )
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=2_000
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_ORDER_LIMIT_VIOLATED")

    def test_redeem_below_min_shares_rejected(self, api):
        """PRD §3.3: "for `REDEEM`, `requested_shares` must be at least
        `min_redemption_shares`."

        Claim: requested_shares < min_redemption_shares yields
        ERR_ORDER_LIMIT_VIOLATED.
        """
        investor, fund, _, _ = setup_investor_with_confirmed_subscribe(
            gross_amount_cents=10_000,
            fund_overrides={"min_redemption_shares": 1_000_000},
        )
        # Investor now holds 1_000_000 shares, but min_redemption is set
        # higher. Try to redeem fewer than min.
        res = api.create_order(
            create_redeem_order_payload(
                fund_id=fund["id"], requested_shares=500_000
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_ORDER_LIMIT_VIOLATED")


# =====================================================================
# Insufficient cash / shares (PRD §3.3 / §2.10 priorities 18, 19)
# =====================================================================
class TestInsufficientFunds:
    def test_insufficient_cash_rejected(self, api):
        """PRD §3.3: "A `SUBSCRIBE` additionally requires that the
        investor's `cash_balance_cents` be at least the order's
        `gross_amount_cents` (the cash is conceptually reserved at
        acceptance)."

        Claim: cash_balance < gross_amount produces ERR_INSUFFICIENT_CASH.
        """
        investor = create_kyc_approved_investor(cash_cents=100)
        fund = create_on_shelf_fund()
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=10_000
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_INSUFFICIENT_CASH")

    def test_insufficient_shares_rejected(self, api):
        """PRD §3.3: "a `REDEEM` or `CONVERT` requires that the investor's
        `Holding.shares` for the source fund be at least
        `requested_shares`."

        Claim: requested_shares > holdings yields ERR_INSUFFICIENT_SHARES.
        """
        investor = create_kyc_approved_investor()
        fund = create_on_shelf_fund()
        # Investor has zero holdings on this fund.
        res = api.create_order(
            create_redeem_order_payload(
                fund_id=fund["id"], requested_shares=10_000
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_INSUFFICIENT_SHARES")


# =====================================================================
# Idempotency (PRD §3.3)
# =====================================================================
class TestIdempotency:
    def test_replay_with_identical_body_returns_original(self, api):
        """PRD §3.3: "A repeat submission with the identical key and an
        identical body returns the originally created `Order` with HTTP
        200."

        Claim: the second call with identical (investor_id,
        idempotency_key, body) returns HTTP 200 and the same Order.id.
        """
        investor, fund = setup_basic_investor_and_fund()
        advance_clock_to("2026-07-01T10:00:00.000Z")
        key = unique_idempotency_key("idem")
        first = validate_success(api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=1_000,
                idempotency_key=key,
            ),
            make_investor_headers(investor["id"]),
        ), expected_status=201)
        # Second submission with identical body.
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=1_000,
                idempotency_key=key,
            ),
            make_investor_headers(investor["id"]),
        )
        replay = validate_success(res, expected_status=200)
        assert replay["id"] == first["id"]
        assert replay["idempotency_key"] == key

    def test_replay_with_different_body_yields_409(self, api):
        """PRD §3.3: "a repeat submission with the same key but a
        different body yields `ERR_IDEMPOTENCY_REPLAY` with HTTP 409."

        Claim: same idempotency_key with different gross_amount yields
        ERR_IDEMPOTENCY_REPLAY.
        """
        investor, fund = setup_basic_investor_and_fund()
        advance_clock_to("2026-07-15T10:00:00.000Z")
        key = unique_idempotency_key("idem")
        validate_success(api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=1_000,
                idempotency_key=key,
            ),
            make_investor_headers(investor["id"]),
        ), expected_status=201)
        # Different body, same key.
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=2_000,
                idempotency_key=key,
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_IDEMPOTENCY_REPLAY")


# =====================================================================
# Validation precedence pairs (PRD §2.10)
# =====================================================================
class TestValidationPrecedence:
    def test_state_wins_over_kyc(self, api):
        """PRD §2.10 priority 5: "(5) target resource is in a valid state
        for the operation (else `ERR_INVALID_STATE`)" runs BEFORE
        priority 9: "(9) investor KYC is approved before any order".

        Claim: an investor with kyc_status=PENDING submitting an order
        against a Fund.status=DRAFT yields ERR_INVALID_STATE (state at
        priority 5 wins over KYC at priority 9).

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_kyc
        """
        investor = create_investor_pending_kyc()
        # Credit cash so insufficient-cash isn't a confound.
        from test_helpers import api_client as ac, credit_cash_payload
        ac.credit_cash(
            investor["id"], credit_cash_payload(10_000_000),
            TEST_USERS["platform_admin_headers"],
        )
        # Fund stays in DRAFT (never approved).
        fund_res = api.create_fund(
            create_fund_payload(),
            TEST_USERS["product_operator_headers"],
        )
        draft_fund = validate_success(fund_res, expected_status=201)
        assert draft_fund["status"] == "DRAFT"
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=draft_fund["id"], gross_amount_cents=1_000
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_suitability_wins_over_order_limit(self, api):
        """PRD §2.10 priority 10 ("(10) suitability match...") runs
        BEFORE priority 16 ("(16) order amount/share within fund
        min/max bounds (else `ERR_ORDER_LIMIT_VIOLATED`)").

        Claim: a C2 investor on R5 fund with gross_amount BELOW
        min_subscription_amount yields ERR_SUITABILITY_MISMATCH (10),
        not ERR_ORDER_LIMIT_VIOLATED (16).

        # difficulty: priority_pair_validation_conflict/business_safety_suitability_vs_business_constraint_amount
        """
        investor = create_kyc_approved_investor(risk_tolerance="C2")
        fund = create_on_shelf_fund(
            risk_rating="R5",
            min_subscription_amount_cents=50_000,
        )
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=10_000
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_SUITABILITY_MISMATCH")


# =====================================================================
# Cross-entity state dependency (PRD §3.3)
# =====================================================================
class TestCrossEntityState:
    def test_order_acceptance_requires_fund_on_shelf(self, api):
        """PRD §3.3: "the source `Fund.status` equals `ON_SHELF`."

        Claim: when fund is SUSPENDED, order submission yields
        ERR_INVALID_STATE.

        # difficulty: cross_entity_state_dependency/order_acceptance_requires_fund_on_shelf_and_investor_kyc
        """
        investor, fund = setup_basic_investor_and_fund()
        # Suspend the fund.
        validate_success(api.suspend_fund(
            fund["id"], TEST_USERS["compliance_reviewer_headers"]
        ))
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=1_000
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_order_acceptance_requires_investor_kyc_approved(self, api):
        """PRD §3.3: "the `Investor.kyc_status` equals `APPROVED`."

        Claim: when fund is ON_SHELF but investor.kyc_status=PENDING,
        order yields ERR_KYC_NOT_APPROVED.

        # difficulty: cross_entity_state_dependency/order_acceptance_requires_fund_on_shelf_and_investor_kyc
        """
        investor = create_investor_pending_kyc()
        from test_helpers import api_client as ac, credit_cash_payload
        ac.credit_cash(
            investor["id"], credit_cash_payload(10_000_000),
            TEST_USERS["platform_admin_headers"],
        )
        fund = create_on_shelf_fund()
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=1_000
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_KYC_NOT_APPROVED")
