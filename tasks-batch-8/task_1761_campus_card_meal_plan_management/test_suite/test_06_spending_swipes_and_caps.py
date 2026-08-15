"""Card spending: meal swipes, declining-balance purchases, and the provisional
daily cap."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_term_week,
    create_and_publish_plan,
    create_holder,
    create_provisional_card,
    create_term,
    create_verified_card,
    enroll_holder,
    get_success_data,
    make_cardholder_headers,
    open_term,
    post_pos_transaction,
    report_card_lost,
    set_clock,
    setup_enrolled_holder_with_card,
    setup_funded_campus_cash,
    setup_open_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)

POS = TEST_USERS["pos_headers"]
BURSAR = TEST_USERS["bursar_headers"]
DINING = TEST_USERS["dining_manager_headers"]


class TestSwipeAdmission:
    def test_swipe_exhaustion_and_weekly_reset_boundary(self, api):
        """PRD §3.5: "unlimited plans always admit; otherwise the swipe is
        admitted only while `swipes_used_this_week` is strictly below the
        snapshotted `weekly_swipe_allowance` — a swipe attempted when the used
        count already equals the allowance is rejected with
        `ERR_SWIPES_EXHAUSTED`"
        PRD §3.4: "second, every `ACTIVE` enrollment of the term has its
        `swipes_used_this_week` reset to 0"

        Design: Corner/calculations/swipe_exhaustion_and_weekly_reset_boundary
        """
        set_clock("2026-08-24T09:00:00Z")
        holder, term, plan, enrollment, card = setup_enrolled_holder_with_card(
            {"term_code": "T-SWP"},
            {"plan_code": "P-SWP", "weekly_swipe_allowance": 5,
             "dining_dollar_allocation_cents": 0, "price_cents": 50000,
             "eligible_holder_types": ["STUDENT_RESIDENT"]},
            {"university_id": "U91001", "full_name": "Ula Swipe",
             "email": "ula@x.edu", "holder_type": "STUDENT_RESIDENT",
             "housing_status": "ON_CAMPUS"})
        for i in range(1, 5):
            post_pos_transaction(card["id"], "MEAL_SWIPE", 0, key=f"sw-{i}")

        fifth = api.create_transaction(
            {"card_id": card["id"], "tender_type": "MEAL_SWIPE", "amount_cents": 0,
             "idempotency_key": "sw-5"}, POS)
        assert validate_success(fifth, 201)["status"] == "SETTLED"

        sixth = api.create_transaction(
            {"card_id": card["id"], "tender_type": "MEAL_SWIPE", "amount_cents": 0,
             "idempotency_key": "sw-6"}, POS)
        validate_error(sixth, ApiErrorId.ERR_SWIPES_EXHAUSTED)

        advance_term_week(term["id"])
        seventh = api.create_transaction(
            {"card_id": card["id"], "tender_type": "MEAL_SWIPE", "amount_cents": 0,
             "idempotency_key": "sw-7"}, POS)
        assert validate_success(seventh, 201)["status"] == "SETTLED"
        after = get_success_data(api.get_enrollment(enrollment["id"], DINING))
        assert after["swipes_used_this_week"] == 1

    def test_unlimited_plan_bypasses_swipe_count(self, api):
        """PRD §3.5: "unlimited plans always admit"
        PRD §3.4: "Activation also snapshots the plan's `weekly_swipe_allowance`
        and `is_unlimited_swipes` onto the enrollment (later plan edits do not
        disturb live enrollments)"

        Design: Corner/calculations/unlimited_plan_bypasses_swipe_count
        """
        set_clock("2026-08-24T09:00:00Z")
        holder, term, plan, enrollment, card = setup_enrolled_holder_with_card(
            {"term_code": "T-UNL"},
            {"plan_code": "P-UNL", "weekly_swipe_allowance": 0,
             "is_unlimited_swipes": True, "dining_dollar_allocation_cents": 25000,
             "price_cents": 220000, "requires_on_campus_housing": True,
             "eligible_holder_types": ["STUDENT_RESIDENT"]},
            {"university_id": "U91002", "full_name": "Vic Unl",
             "email": "vic@x.edu", "holder_type": "STUDENT_RESIDENT",
             "housing_status": "ON_CAMPUS"})
        assert enrollment["is_unlimited_swipes"] is True

        for i in range(1, 7):
            resp = api.create_transaction(
                {"card_id": card["id"], "tender_type": "MEAL_SWIPE",
                 "amount_cents": 0, "idempotency_key": f"un-{i}"}, POS)
            assert validate_success(resp, 201)["status"] == "SETTLED", (
                f"swipe {i} on an unlimited plan must be admitted")

    def test_swipe_without_active_enrollment_rejected(self, api):
        """PRD §3.5: "For a swipe, the resolved enrollment must be `ACTIVE`
        (`ERR_ENROLLMENT_NOT_ACTIVE`)"

        Design: Corner/validations/swipe_without_active_enrollment_rejected
        """
        set_clock("2026-08-24T09:00:00Z")
        term = create_term(term_code="T-NSW")
        open_term(term["id"])
        holder = create_holder(university_id="U92012", full_name="Val NoEnr",
                               email="val@x.edu", holder_type="STUDENT_RESIDENT",
                               housing_status="ON_CAMPUS")
        card = create_verified_card(holder["id"])

        resp = api.create_transaction(
            {"card_id": card["id"], "tender_type": "MEAL_SWIPE", "amount_cents": 0,
             "idempotency_key": "val-sw"}, POS)
        validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)

    def test_swipe_with_nonzero_amount_returns_validation_error(self, api):
        """PRD §3.5: "an `amount_cents` that must be exactly 0 for a swipe and
        strictly positive for either declining-balance tender (`ERR_VALIDATION`
        otherwise)"
        PRD §2.10: "When a request violates several rules at once, the error that
        surfaces is determined by a fixed priority order, evaluated from first to
        last" — body well-formedness (item 4) precedes path and body-reference
        existence (items 5-6).

        Design: Corner/validations/swipe_with_nonzero_amount_returns_validation_error
        """
        resp = api.create_transaction(
            {"card_id": str(NON_EXISTENT_UUID), "tender_type": "MEAL_SWIPE",
             "amount_cents": 100, "idempotency_key": "bad-swipe"}, POS)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestProvisionalDailyCap:
    def test_provisional_daily_cap_inclusive_boundary(self, api):
        """PRD §3.5: "the sum of `amount_cents` over the card's `PURCHASE` ledger
        entries — across both account types — whose `created_at` falls on the same
        UTC calendar date as the logical clock, plus the new amount, must not
        exceed the provisional daily cap of 2500 cents. A purchase that lands
        exactly on the cap is admitted; one that would push the day's total above
        it is rejected with `ERR_PROVISIONAL_DAILY_CAP` (HTTP 422)."

        Design: Corner/calculations/provisional_daily_cap_inclusive_boundary
        """
        set_clock("2026-08-25T09:00:00Z")
        holder, card, account = _setup_provisional_funded(api, 10000)
        post_pos_transaction(card["id"], "CAMPUS_CASH", 2000, key="wes-1")

        at_cap = api.create_transaction(
            {"card_id": card["id"], "tender_type": "CAMPUS_CASH",
             "amount_cents": 500, "idempotency_key": "wes-2"}, POS)
        assert validate_success(at_cap, 201)["status"] == "SETTLED"

        over = api.create_transaction(
            {"card_id": card["id"], "tender_type": "CAMPUS_CASH",
             "amount_cents": 1, "idempotency_key": "wes-3"}, POS)
        validate_error(over, ApiErrorId.ERR_PROVISIONAL_DAILY_CAP)

        after = get_success_data(api.get_account(account["id"], BURSAR))
        assert after["balance_cents"] == 7500


class TestPurchaseBalanceBoundary:
    def test_purchase_at_exact_balance_boundary(self, api):
        """PRD §3.5: "the amount must not exceed the account's `balance_cents` —
        a purchase exactly equal to the balance is admitted, anything larger is
        rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 402)"
        PRD §3.5: "on-campus postings settle immediately and are born `SETTLED`"

        Design: Difficulty/boundary_precision_check/purchase_at_exact_balance_boundary
        """
        set_clock("2026-08-25T09:00:00Z")
        holder, card, account = setup_funded_campus_cash(
            amount_cents=5000, university_id="U7001", full_name="Mia Resident",
            email="mia@x.edu", holder_type="STUDENT_RESIDENT",
            housing_status="ON_CAMPUS")
        resp = api.create_transaction(
            {"card_id": card["id"], "tender_type": "CAMPUS_CASH",
             "amount_cents": 5000, "idempotency_key": "mia-t1"}, POS)
        assert validate_success(resp, 201)["status"] == "SETTLED"
        after = get_success_data(api.get_account(account["id"], BURSAR))
        assert after["balance_cents"] == 0

    def test_purchase_one_cent_over_zero_balance_rejected(self, api):
        """PRD §3.5: "the amount must not exceed the account's `balance_cents` —
        a purchase exactly equal to the balance is admitted, anything larger is
        rejected with `ERR_INSUFFICIENT_FUNDS` (HTTP 402)"

        Design: Difficulty/boundary_precision_check/purchase_at_exact_balance_boundary
        """
        set_clock("2026-08-25T09:00:00Z")
        holder, card, account = setup_funded_campus_cash(
            amount_cents=5000, university_id="U7001", full_name="Mia Resident",
            email="mia@x.edu", holder_type="STUDENT_RESIDENT",
            housing_status="ON_CAMPUS")
        post_pos_transaction(card["id"], "CAMPUS_CASH", 5000, key="mia-t1")

        over = api.create_transaction(
            {"card_id": card["id"], "tender_type": "CAMPUS_CASH",
             "amount_cents": 1, "idempotency_key": "mia-t2"}, POS)
        validate_error(over, ApiErrorId.ERR_INSUFFICIENT_FUNDS)
        after = get_success_data(api.get_account(account["id"], BURSAR))
        assert after["balance_cents"] == 0


class TestFrozenCardPurchasePrecedence:
    def test_frozen_card_state_beats_insufficient_funds(self, api):
        """PRD §2.10: "When a request violates several rules at once, the error
        that surfaces is determined by a fixed priority order, evaluated from first
        to last" — item 10 "card active or frozen (`ERR_CARD_NOT_ACTIVE`,
        `ERR_CARD_FROZEN`)" precedes item 14 "purchase amounts covered by the
        account balance (`ERR_INSUFFICIENT_FUNDS`, 402)".
        PRD §3.5: "a card in `LOST_FROZEN` or `STOLEN_FROZEN` is rejected with
        `ERR_CARD_FROZEN`"

        Design: Difficulty/priority_pair_validation_conflict/frozen_card_state_beats_insufficient_funds
        """
        holder, card, account = _setup_lost_card_with_small_balance(api)
        resp = api.create_transaction(
            {"card_id": card["id"], "tender_type": "CAMPUS_CASH",
             "amount_cents": 9999, "idempotency_key": "kim-t1"}, POS)
        validate_error(resp, ApiErrorId.ERR_CARD_FROZEN)

    def test_frozen_card_rejection_posts_nothing(self, api):
        """PRD §3.5: "an admitted purchase posts a `PURCHASE` entry carrying the
        transaction's `reference_transaction_id`, recomputes the balance, and bumps
        the account's `version`." — a rejected purchase admits none of these.
        PRD §3.5: "a card in `LOST_FROZEN` or `STOLEN_FROZEN` is rejected with
        `ERR_CARD_FROZEN`"

        Design: Difficulty/priority_pair_validation_conflict/frozen_card_state_beats_insufficient_funds
        """
        holder, card, account = _setup_lost_card_with_small_balance(api)
        api.create_transaction(
            {"card_id": card["id"], "tender_type": "CAMPUS_CASH",
             "amount_cents": 9999, "idempotency_key": "kim-t1"}, POS)
        after = get_success_data(api.get_account(account["id"], BURSAR))
        assert after["balance_cents"] == 100
        transactions, _ = validate_paginated(
            api.list_transactions(BURSAR, {"card_id": card["id"]}))
        assert transactions == []


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _setup_provisional_funded(api, amount_cents):
    from test_helpers import fund_account, open_account
    holder = create_holder(university_id="U91003", full_name="Wes Prov",
                           email="wes@x.edu", holder_type="STUDENT_RESIDENT",
                           housing_status="ON_CAMPUS")
    card = create_provisional_card(holder["id"])
    account = open_account(holder["id"], "CAMPUS_CASH")
    fund_account(account["id"], amount_cents)
    return holder, card, account


def _setup_lost_card_with_small_balance(api):
    set_clock("2026-08-25T09:00:00Z")
    holder, card, account = setup_funded_campus_cash(
        amount_cents=100, university_id="U6001", full_name="Kim Commuter",
        email="kim@x.edu", holder_type="STUDENT_COMMUTER",
        housing_status="COMMUTER")
    report_card_lost(card["id"], holder["id"])
    return holder, card, account
