"""Concurrency tests — race conditions on per-card and per-application writes.

Covers PRD §3.5 (per-card transaction serialization, balance race),
§3.7 (application approve/deny race), §3.4 (card issuance race).
"""
import pytest

from test_helpers import (
    validate_success, validate_error_is_one_of, get_success_data,
    run_race, assert_exactly_one_succeeds, assert_at_least_one_succeeds,
    ERR_CARD_ALREADY_EXISTS, ERR_INVALID_STATE,
    ERR_INSUFFICIENT_FUNDS,
    TEST_USERS, make_merchant_headers,
    setup_basic_household, setup_full_purchase_scene,
    create_draft_application, walk_to_interview_done,
    create_transaction_payload,
)


CASEWORKER = TEST_USERS["caseworker_headers"]
CASEWORKER2 = TEST_USERS["caseworker2_headers"]


class TestCardIssuanceRace:
    def test_two_parallel_issuances_exactly_one_wins(self, api):
        """PRD §3.4: "The same uniqueness rule also defends against two
        parallel issuance calls racing — the first writer wins and the loser
        receives `ERR_CARD_ALREADY_EXISTS`."

        Claim: two parallel POST /cards on the same household: exactly one
        succeeds, the other fails with ERR_CARD_ALREADY_EXISTS.
        """
        hh, _ = setup_basic_household(size=1, age=30)
        results = run_race(
            lambda: api.create_card(hh["id"], CASEWORKER),
            lambda: api.create_card(hh["id"], CASEWORKER2),
        )
        outcome = assert_exactly_one_succeeds(*results)
        # The failure should be ERR_CARD_ALREADY_EXISTS
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, [ERR_CARD_ALREADY_EXISTS])


class TestPurchaseFundsRace:
    def test_two_purchases_each_for_full_balance(self, api):
        """PRD §3.5: "When two purchase attempts race for the same card and
        the combined eligible amounts exceed the available balance, the system
        serializes them per-card: the first writer's ledger insertion wins and
        is `APPROVED`, while the second writer's balance check fails on the
        now-reduced balance and is `DECLINED` with `decline_reason` =
        `INSUFFICIENT_FUNDS` and response `ERR_INSUFFICIENT_FUNDS`."

        Claim: two concurrent purchases each demanding the full balance —
        exactly one is APPROVED, the other DECLINED with ERR_INSUFFICIENT_FUNDS.
        """
        ctx = setup_full_purchase_scene(size=1, age=30)
        m_headers = make_merchant_headers(ctx["merchant"]["id"])
        # Each call attempts to spend the FULL current card balance, so at
        # most one can succeed: the second writer sees a now-reduced balance
        # below the eligible_amount and is DECLINED with ERR_INSUFFICIENT_FUNDS.
        full_balance = int(ctx["card"]["balance_cents"])
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=ctx["merchant"]["id"],
            line_items=[{"item_category": "STAPLE", "unit_price_cents": full_balance, "quantity": 1}],
        )
        results = run_race(
            lambda: api.create_transaction(payload, m_headers),
            lambda: api.create_transaction(payload, m_headers),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, [ERR_INSUFFICIENT_FUNDS])


class TestApplicationApproveDenyRace:
    def test_concurrent_approve_and_deny_one_wins(self, api):
        """PRD §3.7 / §3.3: "Caseworker approves Application while another
        caseworker denies the same Application" — "Exactly one transition
        succeeds; the loser gets ERR_INVALID_STATE because the application is
        no longer in INTERVIEW_DONE."

        Claim: concurrent approve + deny: exactly one succeeds, loser receives
        ERR_INVALID_STATE.
        """
        # Use a small, definitely-eligible household
        hh, _ = setup_basic_household(size=1, age=30, earned_each_cents=0)
        app = create_draft_application(hh["id"])
        walk_to_interview_done(hh["id"], app["id"])

        results = run_race(
            lambda: api.approve_application(hh["id"], app["id"], CASEWORKER),
            lambda: api.deny_application(hh["id"], app["id"], {"denial_reason": "OTHER"}, CASEWORKER2),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, [ERR_INVALID_STATE])
