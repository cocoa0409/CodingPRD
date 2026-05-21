"""Transaction settlement, eligible-item resolution, decline reasons, and reversal.

Covers PRD §3.5 (eligibility resolution and settlement order), §3.4
(card suspended/active gating), §2.10 (reversal window).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    NON_EXISTENT_UUID,
    ERR_CARD_NOT_ACTIVE, ERR_MERCHANT_NOT_AUTHORIZED,
    ERR_ALL_ITEMS_INELIGIBLE, ERR_INSUFFICIENT_FUNDS,
    ERR_INVALID_STATE, ERR_FORBIDDEN, ERR_REVERSAL_WINDOW_EXPIRED,
    TEST_USERS, make_merchant_headers,
    assert_transaction,
    create_transaction_payload,
    setup_full_purchase_scene, setup_approved_household_with_active_card,
    setup_authorized_merchant,
    iso_past, iso_future,
)


CASEWORKER = TEST_USERS["caseworker_headers"]


# Helper: build merchant-role headers for the given merchant id.
def _m_headers(merchant_id):
    return make_merchant_headers(merchant_id)


class TestTransactionApproval:
    def test_purchase_approved_against_active_card_authorized_merchant(self, api):
        """PRD §3.5: "Otherwise the transaction is approved: `status` becomes
        `APPROVED`, `posted_at` is set to `Clock.now`, a `PURCHASE`
        `BenefitLedger` entry with `amount_cents` equal to the negation of
        `eligible_amount_cents` is posted."

        Claim: a valid purchase yields status=APPROVED with eligible_amount.
        """
        ctx = setup_full_purchase_scene(size=1, age=30)
        merchant_id = ctx["merchant"]["id"]
        m_headers = _m_headers(merchant_id)
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"],
            merchant_id=merchant_id,
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 500, "quantity": 1}],
        )
        resp = api.create_transaction(payload, m_headers)
        data = validate_success(resp, expected_status=201)
        assert_transaction(data)
        assert data["status"] == "APPROVED"
        assert data["eligible_amount_cents"] == 500
        assert data["ineligible_amount_cents"] == 0
        assert data["posted_at"] is not None

    def test_purchase_decrements_card_balance(self, api):
        """PRD §3.5: "a `PURCHASE` `BenefitLedger` entry with `amount_cents`
        equal to the negation of `eligible_amount_cents` is posted to the
        current `benefit_month` (derived from `Clock.now`), and the card's
        `balance_cents` is recomputed."

        Claim: after a purchase of N cents, card.balance_cents drops by N.
        """
        ctx = setup_full_purchase_scene(size=1, age=30)
        merchant_id = ctx["merchant"]["id"]
        m_headers = _m_headers(merchant_id)
        pre = validate_success(api.get_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER))
        balance_pre = pre["balance_cents"]
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=merchant_id,
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 1000, "quantity": 1}],
        )
        validate_success(api.create_transaction(payload, m_headers), expected_status=201)
        post = validate_success(api.get_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER))
        assert post["balance_cents"] == balance_pre - 1000


class TestTransactionDeclineOrdering:
    def test_card_not_active_beats_balance_check(self, api):
        """PRD §3.5: "If the `EbtCard.status` is not `ACTIVE`, the transaction
        is declined with `decline_reason` = `CARD_NOT_ACTIVE` and the response
        is `ERR_CARD_NOT_ACTIVE`."
        PRD §2.12: "the all-items-ineligible check fires **before** the
        insufficient-funds check on a purchase."

        Claim (priority): SUSPENDED card + high requested amount yields
        ERR_CARD_NOT_ACTIVE, not ERR_INSUFFICIENT_FUNDS.
        """
        # difficulty: priority_pair_validation_conflict/state_beats_fiscal_on_transaction
        ctx = setup_full_purchase_scene(size=1, age=30)
        validate_success(api.suspend_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER))
        merchant_id = ctx["merchant"]["id"]
        m_headers = _m_headers(merchant_id)
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=merchant_id,
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 1000000, "quantity": 1}],
        )
        resp = api.create_transaction(payload, m_headers)
        validate_error(resp, ERR_CARD_NOT_ACTIVE)

    def test_merchant_not_authorized_yields_error(self, api):
        """PRD §3.5: "If the merchant's `snap_authorization_status` is not
        `AUTHORIZED`, or `authorization_expires_at` is at or before `Clock.now`,
        the transaction is declined with `decline_reason` = `MERCHANT_NOT_AUTHORIZED`
        and the response is `ERR_MERCHANT_NOT_AUTHORIZED`."

        Claim: a merchant with snap_authorization_status=SUSPENDED yields
        ERR_MERCHANT_NOT_AUTHORIZED.
        """
        ctx = setup_approved_household_with_active_card(size=1, age=30)
        merchant = setup_authorized_merchant()
        # Suspend the merchant
        from test_helpers import TEST_USERS
        validate_success(api.update_merchant(
            merchant["id"], {"snap_authorization_status": "SUSPENDED"},
            TEST_USERS["state_admin_headers"],
        ))
        m_headers = _m_headers(merchant["id"])
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=merchant["id"],
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 100, "quantity": 1}],
        )
        resp = api.create_transaction(payload, m_headers)
        validate_error(resp, ERR_MERCHANT_NOT_AUTHORIZED)

    def test_all_items_ineligible_beats_insufficient_funds(self, api):
        """PRD §3.5: "This zero-eligible check **precedes** the balance check,
        so a cart of only `NON_FOOD` items against a zero-balance card returns
        `ERR_ALL_ITEMS_INELIGIBLE`, not `ERR_INSUFFICIENT_FUNDS`."

        Claim (priority): cart of only ALCOHOL+TOBACCO yields
        ERR_ALL_ITEMS_INELIGIBLE even when balance is also too low.
        """
        # difficulty: boundary_precision_check/zero_eligible_amount_beats_zero_balance
        ctx = setup_full_purchase_scene(size=1, age=30)
        merchant_id = ctx["merchant"]["id"]
        m_headers = _m_headers(merchant_id)
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=merchant_id,
            line_items=[
                {"item_category": "ALCOHOL", "unit_price_cents": 1000, "quantity": 1},
                {"item_category": "TOBACCO", "unit_price_cents": 1000, "quantity": 1},
            ],
            requested_amount_cents=2000,
        )
        resp = api.create_transaction(payload, m_headers)
        validate_error(resp, ERR_ALL_ITEMS_INELIGIBLE)

    def test_insufficient_funds_when_eligible_exceeds_balance(self, api):
        """PRD §3.5: "If `eligible_amount_cents` is greater than the card's
        current `balance_cents`, the transaction is declined with
        `decline_reason` = `INSUFFICIENT_FUNDS` and the response is
        `ERR_INSUFFICIENT_FUNDS`."

        Claim: an eligible cart whose total exceeds card.balance_cents yields
        ERR_INSUFFICIENT_FUNDS.
        """
        ctx = setup_full_purchase_scene(size=1, age=30)
        # Current balance equals monthly_allotment_cents = 2300 (minimum benefit
        # for size 1 with zero income); we attempt 1,000,000 cents -> fails.
        merchant_id = ctx["merchant"]["id"]
        m_headers = _m_headers(merchant_id)
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=merchant_id,
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 1000000, "quantity": 1}],
        )
        resp = api.create_transaction(payload, m_headers)
        validate_error(resp, ERR_INSUFFICIENT_FUNDS)


class TestEligibleAmountResolution:
    def test_non_food_excluded_from_eligible(self, api):
        """PRD §3.5: "Any line whose `item_category` is `NON_FOOD`, `ALCOHOL`,
        or `TOBACCO` is filtered out — these are never SNAP-eligible regardless
        of merchant or household."

        Claim: NON_FOOD lines are excluded from eligible_amount_cents.
        """
        ctx = setup_full_purchase_scene(size=1, age=30)
        merchant_id = ctx["merchant"]["id"]
        m_headers = _m_headers(merchant_id)
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=merchant_id,
            line_items=[
                {"item_category": "STAPLE", "unit_price_cents": 500, "quantity": 1},
                {"item_category": "NON_FOOD", "unit_price_cents": 1000, "quantity": 1},
            ],
            requested_amount_cents=1500,
        )
        resp = api.create_transaction(payload, m_headers)
        data = validate_success(resp, expected_status=201)
        assert data["eligible_amount_cents"] == 500
        assert data["ineligible_amount_cents"] == 1000

    def test_hot_prepared_excluded_when_no_pilot(self, api):
        """PRD §3.5: "Lines whose `item_category` is `HOT_PREPARED` or
        `COLD_PREPARED` are eligible **only** when the merchant's
        `hot_food_pilot` is true **and** the household's
        `has_elderly_or_disabled` is true."

        Claim (standard household path): non-pilot merchant + non-elderly
        household: HOT_PREPARED counts as ineligible.
        """
        # difficulty: dual_variant_calc/eligible_amount_standard_vs_restaurant_meals
        ctx = setup_full_purchase_scene(size=1, age=30, hot_food_pilot=False)
        merchant_id = ctx["merchant"]["id"]
        m_headers = _m_headers(merchant_id)
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=merchant_id,
            line_items=[
                {"item_category": "STAPLE", "unit_price_cents": 500, "quantity": 3},
                {"item_category": "HOT_PREPARED", "unit_price_cents": 1200, "quantity": 2},
            ],
            requested_amount_cents=1500 + 2400,
        )
        resp = api.create_transaction(payload, m_headers)
        # Card balance only has 2300 cents minimum benefit; eligible would be
        # 1500 only if HOT_PREPARED is excluded; 1500 < 2300, so APPROVED.
        data = validate_success(resp, expected_status=201)
        assert data["eligible_amount_cents"] == 1500

    def test_hot_prepared_eligible_for_elderly_at_pilot_merchant(self, api):
        """PRD §3.5: "When either condition fails, both `HOT_PREPARED` and
        `COLD_PREPARED` lines are treated as ineligible alongside the
        categorical exclusions in step 1."

        Claim (restaurant meals): elderly household + pilot merchant counts
        HOT_PREPARED as eligible.
        """
        # difficulty: dual_variant_calc/eligible_amount_standard_vs_restaurant_meals
        # Build a size=1 elderly household with sufficient balance.
        from test_helpers import setup_basic_household, create_draft_application
        from test_helpers import walk_to_interview_done, approve_application, activate_card
        from test_helpers import dob_for_age
        # We need an APPROVED household with high balance. Standard path uses
        # MINIMUM_BENEFIT_CENTS=2300 for size 1 — not enough for a cart of
        # 1500+2400=3900 eligible. Use elderly path which raises allotment.
        from test_helpers import api_client as _api2
        hh = _api2.create_household({"state_code": "CA", "address_zip": "94110"}, CASEWORKER)
        from test_helpers import get_success_data
        hh = get_success_data(hh)
        _api2.create_member(hh["id"],
                            {"full_name": "E", "date_of_birth": dob_for_age(65),
                             "is_disabled": True},
                            CASEWORKER)
        app = get_success_data(_api2.create_application(hh["id"], CASEWORKER))
        walk_to_interview_done(hh["id"], app["id"])
        issued = get_success_data(_api2.create_card(hh["id"], CASEWORKER))
        approve_application(hh["id"], app["id"])
        # Activate the card so it can transact (PRD: card must be ACTIVE).
        activate_card(hh["id"], issued["id"])
        # Refresh
        hh = get_success_data(_api2.get_household(hh["id"], CASEWORKER))
        card = get_success_data(_api2.get_card(hh["id"], issued["id"], CASEWORKER))
        merchant = setup_authorized_merchant(hot_food_pilot=True)
        m_headers = _m_headers(merchant["id"])
        payload = create_transaction_payload(
            card_id=card["id"], merchant_id=merchant["id"],
            line_items=[
                {"item_category": "STAPLE", "unit_price_cents": 100, "quantity": 1},
                {"item_category": "HOT_PREPARED", "unit_price_cents": 100, "quantity": 1},
            ],
            requested_amount_cents=200,
        )
        resp = api.create_transaction(payload, m_headers)
        data = validate_success(resp, expected_status=201)
        # Both lines should be eligible
        assert data["eligible_amount_cents"] == 200


class TestTransactionReversal:
    def test_reverse_within_window_succeeds(self, api):
        """PRD §3.5: "A `Merchant` may reverse an `APPROVED` transaction within
        24 hours, transitioning it from `APPROVED` to `REVERSED`."

        Claim: reversing an APPROVED transaction immediately succeeds and
        sets status=REVERSED.
        """
        ctx = setup_full_purchase_scene(size=1, age=30)
        merchant_id = ctx["merchant"]["id"]
        m_headers = _m_headers(merchant_id)
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=merchant_id,
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 500, "quantity": 1}],
        )
        tx = validate_success(api.create_transaction(payload, m_headers), expected_status=201)
        resp = api.reverse_transaction(tx["id"], m_headers)
        data = validate_success(resp)
        assert data["status"] == "REVERSED"

    def test_reverse_restores_card_balance(self, api):
        """PRD §3.5: "On a successful reversal a `REFUND` ledger entry with
        `amount_cents` equal to the positive of the original
        `eligible_amount_cents` is posted, and the card's `balance_cents` is
        recomputed accordingly."

        Claim: after purchase + reverse, card.balance_cents == pre-purchase balance.
        """
        # difficulty: compensating_invariant/purchase_then_reverse_leaves_card_balance_unchanged
        ctx = setup_full_purchase_scene(size=1, age=30)
        merchant_id = ctx["merchant"]["id"]
        m_headers = _m_headers(merchant_id)
        pre = validate_success(api.get_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER))
        balance_before = pre["balance_cents"]
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=merchant_id,
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 500, "quantity": 1}],
        )
        tx = validate_success(api.create_transaction(payload, m_headers), expected_status=201)
        # Sanity: balance dropped by 500
        mid = validate_success(api.get_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER))
        assert mid["balance_cents"] == balance_before - 500
        # Reverse
        validate_success(api.reverse_transaction(tx["id"], m_headers))
        post = validate_success(api.get_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER))
        assert post["balance_cents"] == balance_before, (
            f"Card balance should return to {balance_before}, got {post['balance_cents']}"
        )

    def test_reverse_on_non_approved_yields_invalid_state(self, api):
        """PRD §3.5: "A `Merchant` may reverse an `APPROVED` transaction."

        Claim: reversing an already-REVERSED transaction yields ERR_INVALID_STATE.
        """
        ctx = setup_full_purchase_scene(size=1, age=30)
        merchant_id = ctx["merchant"]["id"]
        m_headers = _m_headers(merchant_id)
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=merchant_id,
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 500, "quantity": 1}],
        )
        tx = validate_success(api.create_transaction(payload, m_headers), expected_status=201)
        validate_success(api.reverse_transaction(tx["id"], m_headers))
        # Second reverse
        resp = api.reverse_transaction(tx["id"], m_headers)
        validate_error(resp, ERR_INVALID_STATE)
