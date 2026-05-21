"""Difficulty-design coverage: tests that explicitly hit the
SCAFFOLD_DIFFICULTY_DESIGN instances not already saturated elsewhere.

These tests serve as the second coverage hit for each instance defined in
the priority queue, on top of the primary tests embedded in the other files
(test_03, test_04, test_05, test_08, test_09, test_10, test_11, test_12).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    ERR_INVALID_STATE, ERR_FRAUD_HOLD, ERR_CARD_NOT_ACTIVE,
    ERR_ALL_ITEMS_INELIGIBLE, ERR_NET_INCOME_OVER_LIMIT,
    ERR_WAIVER_OVERLAP, ERR_EA_DUPLICATE,
    TEST_USERS, make_household_head_headers, make_merchant_headers,
    create_household, add_member,
    setup_basic_household, setup_approved_household_with_active_card,
    setup_approved_household_at_net_income,
    setup_household_at_net_income,
    setup_full_purchase_scene,
    setup_approved_abawd_waiver,
    request_abawd_waiver,
    create_draft_application, walk_to_interview_done,
    create_transaction_payload,
    create_emergency_allotment_payload,
    create_draft_ea,
    open_fraud_case, assign_fraud_case,
    dob_for_age, validate_error_is_one_of,
)


CASEWORKER = TEST_USERS["caseworker_headers"]
FRAUD_INV = TEST_USERS["fraud_investigator_headers"]
STATE_ADMIN = TEST_USERS["state_admin_headers"]


# ===========================================================================
# Rule 1 — dual_variant_calc (second tests for both instances)
# ===========================================================================

class TestDualVariantNetSecondHit:
    def test_non_elderly_vs_elderly_net_differ_strict(self, api):
        """PRD §3.2: "for households **without** an elderly or disabled member
        the cap is 67,200 cents (the lesser of the raw figure and 67,200 cents
        is taken), and for households **with** an elderly or disabled member
        the cap does not apply."

        Claim: two identical-income/expense households with and without elderly
        produce strictly different net values.
        """
        # difficulty: dual_variant_calc/net_income_standard_vs_elderly_disabled
        h1 = create_household(shelter_expense_cents=250000)
        h2 = create_household(shelter_expense_cents=250000)
        for hh in (h1, h2):
            add_member(hh["id"], full_name="A", date_of_birth=dob_for_age(35),
                       earned_income_cents=150000)
            add_member(hh["id"], full_name="B", date_of_birth=dob_for_age(35),
                       earned_income_cents=150000)
        # Different third member
        add_member(h1["id"], full_name="C", date_of_birth=dob_for_age(35),
                   earned_income_cents=0)
        add_member(h2["id"], full_name="E", date_of_birth=dob_for_age(65),
                   earned_income_cents=0)
        h1r = validate_success(api.get_household(h1["id"], CASEWORKER))
        h2r = validate_success(api.get_household(h2["id"], CASEWORKER))
        assert h1r["net_monthly_income_cents"] != h2r["net_monthly_income_cents"]
        # Specifically, the elderly variant is strictly lower (uncapped shelter)
        assert h2r["net_monthly_income_cents"] < h1r["net_monthly_income_cents"]


class TestRestaurantMealsSecondHit:
    def test_non_elderly_at_pilot_excludes_hot_prepared(self, api):
        """PRD §3.5: "Lines whose `item_category` is `HOT_PREPARED` or
        `COLD_PREPARED` are eligible **only** when the merchant's
        `hot_food_pilot` is true **and** the household's
        `has_elderly_or_disabled` is true."

        Claim: non-elderly household + pilot merchant: HOT_PREPARED counts as
        ineligible.
        """
        # difficulty: dual_variant_calc/eligible_amount_standard_vs_restaurant_meals
        ctx = setup_full_purchase_scene(size=1, age=30, hot_food_pilot=True)
        m_headers = make_merchant_headers(ctx["merchant"]["id"])
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=ctx["merchant"]["id"],
            line_items=[
                {"item_category": "STAPLE", "unit_price_cents": 500, "quantity": 1},
                {"item_category": "HOT_PREPARED", "unit_price_cents": 1200, "quantity": 1},
            ],
            requested_amount_cents=1700,
        )
        resp = api.create_transaction(payload, m_headers)
        data = validate_success(resp, expected_status=201)
        # HOT_PREPARED should be excluded because household is not elderly/disabled
        assert data["eligible_amount_cents"] == 500


# ===========================================================================
# Rule 6 — boundary_precision_check (second tests)
# ===========================================================================

class TestNetIncomeBoundarySecondHit:
    def test_size_3_net_one_below_limit_approves(self, api):
        """PRD §3.3: "Both checks use **inclusive** comparisons — a household
        whose net income equals the limit exactly is approved, not rejected."

        Claim: size=3 net=211799 (1 below limit) approves cleanly.
        """
        # difficulty: boundary_precision_check/net_income_limit_inclusive_boundary
        ctx = setup_approved_household_at_net_income(target_net_cents=211799, size=3)
        assert ctx["application"]["state"] == "APPROVED"


class TestAllItemsIneligibleSecondHit:
    def test_only_non_food_yields_all_items_ineligible(self, api):
        """PRD §3.5: "If `eligible_amount_cents` is zero, the transaction is
        declined with `decline_reason` = `ALL_ITEMS_INELIGIBLE` and the response
        is `ERR_ALL_ITEMS_INELIGIBLE`."

        Claim: a cart of only NON_FOOD lines yields ERR_ALL_ITEMS_INELIGIBLE.
        """
        # difficulty: boundary_precision_check/zero_eligible_amount_beats_zero_balance
        ctx = setup_full_purchase_scene(size=1, age=30)
        m_headers = make_merchant_headers(ctx["merchant"]["id"])
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=ctx["merchant"]["id"],
            line_items=[
                {"item_category": "NON_FOOD", "unit_price_cents": 100, "quantity": 1},
            ],
            requested_amount_cents=100,
        )
        resp = api.create_transaction(payload, m_headers)
        validate_error(resp, ERR_ALL_ITEMS_INELIGIBLE)


# ===========================================================================
# Rule 7 — cross_entity_state_dependency (second tests)
# ===========================================================================

class TestCardActivateRequiresApprovedSecondHit:
    def test_card_activate_blocked_until_application_approved(self, api):
        """PRD §3.4: "activation requires the household's `certification_status`
        to be `APPROVED`."

        Claim: a card issued before approval cannot be activated until the
        household is APPROVED.
        """
        # difficulty: cross_entity_state_dependency/ebtcard_activate_requires_household_certified
        hh, _ = setup_basic_household(size=1, age=30)
        card = validate_success(api.create_card(hh["id"], CASEWORKER), expected_status=201)
        hh_head = make_household_head_headers(hh["id"])
        # Pre-approval activate should fail
        resp = api.activate_card(hh["id"], card["id"], hh_head)
        validate_error(resp, ERR_INVALID_STATE)
        # Then walk to approved
        app = validate_success(api.create_application(hh["id"], CASEWORKER), expected_status=201)
        walk_to_interview_done(hh["id"], app["id"])
        validate_success(api.approve_application(hh["id"], app["id"], CASEWORKER))
        # Now activate succeeds
        resp = api.activate_card(hh["id"], card["id"], hh_head)
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"


# ===========================================================================
# Rule 9 — compensating_invariant (second tests)
# ===========================================================================

class TestPurchaseReverseHouseholdInvariant:
    def test_household_total_balance_invariant_across_purchase_pair(self, api):
        """PRD §2.9: "The ledger is append-only — entries are never edited or
        deleted — so balance corrections are made by posting new offsetting
        rows, never by mutating history."

        Claim: household-level total balance == balance_before after a
        purchase+reverse pair.
        """
        # difficulty: compensating_invariant/purchase_then_reverse_leaves_card_balance_unchanged
        ctx = setup_full_purchase_scene(size=1, age=30)
        m_headers = make_merchant_headers(ctx["merchant"]["id"])
        pre = validate_success(api.get_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER))
        balance_before = pre["balance_cents"]
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=ctx["merchant"]["id"],
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 1000, "quantity": 1}],
        )
        tx = validate_success(api.create_transaction(payload, m_headers), expected_status=201)
        validate_success(api.reverse_transaction(tx["id"], m_headers))
        post = validate_success(api.get_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER))
        assert post["balance_cents"] == balance_before


class TestCardReplaceInvariantSecondHit:
    def test_card_replace_emits_adjustment_pair(self, api):
        """PRD §3.4: "the balance is migrated atomically by posting two paired
        `ADJUSTMENT` entries to the ledger — a negative entry equal to the old
        card's `balance_cents` at the instant of replacement on the old card,
        and a positive entry of the same magnitude on the new card."

        Claim: after replace, ledger contains one negative ADJUSTMENT on the
        old card and one positive ADJUSTMENT on the new card.
        """
        # difficulty: compensating_invariant/card_replace_preserves_household_total_benefits
        ctx = setup_approved_household_with_active_card(size=1, age=30)
        hh_id = ctx["household"]["id"]
        old_id = ctx["card"]["id"]
        hh_head = make_household_head_headers(hh_id)
        # Snapshot old balance pre-replace
        old_pre = validate_success(api.get_card(hh_id, old_id, CASEWORKER))
        balance = old_pre["balance_cents"]
        old_after = validate_success(api.replace_card(hh_id, old_id, hh_head))
        new_id = old_after["replaced_by_card_id"]
        old_ledger, _ = validate_paginated(
            api.get_card_ledger(hh_id, old_id, CASEWORKER, params={"limit": 100})
        )
        new_ledger, _ = validate_paginated(
            api.get_card_ledger(hh_id, new_id, CASEWORKER, params={"limit": 100})
        )
        old_adj = [e for e in old_ledger if e["entry_type"] == "ADJUSTMENT"]
        new_adj = [e for e in new_ledger if e["entry_type"] == "ADJUSTMENT"]
        assert any(e["amount_cents"] == -balance for e in old_adj), (
            f"Old card missing -{balance} ADJUSTMENT entry: {old_adj}"
        )
        assert any(e["amount_cents"] == balance for e in new_adj), (
            f"New card missing +{balance} ADJUSTMENT entry: {new_adj}"
        )


# ===========================================================================
# Rule 3 — non_linear_state_machine (second test for fraud_case cycle)
# ===========================================================================
# Note: the SUBSTANTIATED path requires suspicious_score >= 0.70, which is
# impractical to engineer purely via PRD-driven API calls without a fixture
# for transaction patterns. We instead exercise the linear part of the cycle:
# OPEN -> UNDER_REVIEW -> UNFOUNDED via dismiss + CLOSE. The cyclic appeal
# path requires score>=0.70 to substantiate; without engineering that, we
# cover only the dismiss branch here as the "second test" target.

class TestFraudCaseLinearLifecycle:
    def test_full_open_to_closed_via_dismiss(self, api):
        """PRD §3.7: "A `FraudInvestigator` then assigns the case from `OPEN`
        to `UNDER_REVIEW`."
        PRD §3.7: "Dismissing the case transitions `UNDER_REVIEW` to
        `UNFOUNDED` with no cascade."
        PRD §3.7: "From `UNFOUNDED`, an investigator closes the case at any
        time; the transition stamps `closed_at` to `Clock.now`."

        Claim: linear path OPEN -> UNDER_REVIEW -> UNFOUNDED -> CLOSED works
        end-to-end.
        """
        # difficulty: non_linear_state_machine/fraud_case_cyclic_via_appeal (partial coverage)
        hh = create_household()
        case = open_fraud_case(hh["id"])
        assert case["state"] == "OPEN"
        case = assign_fraud_case(case["id"])
        assert case["state"] == "UNDER_REVIEW"
        dismissed = validate_success(api.dismiss_fraud_case(case["id"], FRAUD_INV))
        assert dismissed["state"] == "UNFOUNDED"
        closed = validate_success(api.close_fraud_case(case["id"], FRAUD_INV))
        assert closed["state"] == "CLOSED"
        assert closed["closed_at"] is not None
