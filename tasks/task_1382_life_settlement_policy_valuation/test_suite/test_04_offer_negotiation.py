"""Offer lifecycle: marketing gate, negotiation rounds, expiry, withdraw and
reunderwrite loops (PRD §3.2, §3.3)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_broker_headers,
    setup_case_marketed, create_offer, set_clock,
    order_and_deliver_le,
)

ADMIN = TEST_USERS["admin_headers"]
CM = TEST_USERS["case_manager_headers"]
UW = TEST_USERS["underwriter_headers"]


class TestNegotiationCycle:
    def test_offer_negotiation_cycle_rounds(self, api):
        """PRD §3.3: "A successful counter sets the offer's `counter_amount_cents`,
        increments `round_number` by 1, moves the offer from `PENDING` to
        `COUNTERED`, and increments the offer's `version`."
        PRD §3.3: "`RE_OFFER` replaces the offer's `amount_cents` with a supplied
        payload amount that must be strictly greater than the previous
        `amount_cents` and no greater than the outstanding `counter_amount_cents` —
        an amount outside that band is rejected with `ERR_INVALID_REQUEST` — clears
        `counter_amount_cents` back to unset, increments `round_number` (the same
        round ceiling applies, with a fourth-round attempt rejected as
        `ERR_MAX_NEGOTIATION_ROUNDS_REACHED`), and returns the offer to `PENDING`."
        PRD §3.3: "Countering requires the case to be `MARKETED`
        (`ERR_CASE_NOT_MARKETED`), the caller to own the case
        (`ERR_NOT_CASE_OWNER`), the supplied version to match
        (`ERR_STALE_VERSION`), the round ceiling to hold — `round_number` must be
        below 4, so at most four rounds of pricing are ever negotiated, with a
        fourth-round attempt rejected as `ERR_MAX_NEGOTIATION_ROUNDS_REACHED`
        (HTTP 409) — and the counter to clear a minimum increment:
        `counter_amount_cents` must be at least the offer's `amount_cents`
        multiplied by 101 and divided by 100, rounded half-up — a one-percent
        minimum bump — with anything less rejected as
        `ERR_COUNTER_INCREMENT_TOO_SMALL` (HTTP 422)."

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_rounds
        """
        ctx = setup_case_marketed(with_disclosures=True, with_offer=False)
        case, broker = ctx["case"], ctx["broker"]
        bh = make_broker_headers(broker["id"])
        offer = create_offer(case, 6000000)
        assert offer["round_number"] == 1

        countered = validate_success(api.counter_offer(
            offer["id"], {"counter_amount_cents": 6100000,
                          "expected_offer_version": offer["version"]}, bh))
        assert countered["status"] == "COUNTERED"
        assert countered["round_number"] == 2

        reoffered = validate_success(api.respond_to_offer(
            offer["id"], {"action": "RE_OFFER", "amount_cents": 6050000}, UW))
        assert reoffered["status"] == "PENDING"
        assert reoffered["round_number"] == 3
        assert reoffered["amount_cents"] == 6050000
        assert reoffered["counter_amount_cents"] is None

        # round_half_up(6050000 * 101 / 100) == 6110500 passes the increment exactly.
        countered2 = validate_success(api.counter_offer(
            offer["id"], {"counter_amount_cents": 6110500,
                          "expected_offer_version": reoffered["version"]}, bh))
        assert countered2["status"] == "COUNTERED"
        assert countered2["round_number"] == 4

        resp = api.respond_to_offer(offer["id"], {"action": "RE_OFFER", "amount_cents": 6060000}, UW)
        validate_error(resp, ApiErrorId.ERR_MAX_NEGOTIATION_ROUNDS_REACHED)

        accepted = validate_success(api.respond_to_offer(
            offer["id"], {"action": "ACCEPT_COUNTER"}, UW))
        assert accepted["effective_price_cents"] == 6110500
        assert accepted["round_number"] == 4
        case_after = validate_success(api.get_case(case["id"], CM))
        assert case_after["status"] == "IN_CLOSING"

    def test_offer_negotiation_cycle_reoffer_band(self, api):
        """PRD §3.3: "`RE_OFFER` replaces the offer's `amount_cents` with a
        supplied payload amount that must be strictly greater than the previous
        `amount_cents` and no greater than the outstanding `counter_amount_cents`
        — an amount outside that band is rejected with `ERR_INVALID_REQUEST` —
        clears `counter_amount_cents` back to unset, increments `round_number` (the
        same round ceiling applies, with a fourth-round attempt rejected as
        `ERR_MAX_NEGOTIATION_ROUNDS_REACHED`), and returns the offer to `PENDING`."
        PRD §3.3: "`ACCEPT_COUNTER` accepts the broker's counter: it runs the full
        acceptance cascade described below, using `counter_amount_cents` as the
        price, and captures the case's `broker_commission_bps` from the response
        payload's optional `broker_commission_bps`, defaulting to 0 when omitted."

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycle_rounds
        """
        ctx = setup_case_marketed(with_disclosures=True, with_offer=False)
        case, broker = ctx["case"], ctx["broker"]
        bh = make_broker_headers(broker["id"])
        offer = create_offer(case, 6000000)

        countered = validate_success(api.counter_offer(
            offer["id"], {"counter_amount_cents": 6100000,
                          "expected_offer_version": offer["version"]}, bh))
        assert countered["round_number"] == 2

        # Band violation: equal to the previous amount is not strictly greater.
        resp_low = api.respond_to_offer(
            offer["id"], {"action": "RE_OFFER", "amount_cents": 6000000}, UW)
        validate_error(resp_low, ApiErrorId.ERR_INVALID_REQUEST)
        # Band violation: above the outstanding counter.
        resp_high = api.respond_to_offer(
            offer["id"], {"action": "RE_OFFER", "amount_cents": 6100001}, UW)
        validate_error(resp_high, ApiErrorId.ERR_INVALID_REQUEST)

        # The ceiling of the band is allowed: exactly the counter amount.
        at_counter = validate_success(api.respond_to_offer(
            offer["id"], {"action": "RE_OFFER", "amount_cents": 6100000}, UW))
        assert at_counter["status"] == "PENDING"
        assert at_counter["amount_cents"] == 6100000
        assert at_counter["counter_amount_cents"] is None
        assert at_counter["round_number"] == 3

    def test_counter_increment_exact_one_percent(self, api):
        """PRD §3.3: "the counter to clear a minimum increment:
        `counter_amount_cents` must be at least the offer's `amount_cents`
        multiplied by 101 and divided by 100, rounded half-up — a one-percent
        minimum bump — with anything less rejected as
        `ERR_COUNTER_INCREMENT_TOO_SMALL` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/counter_increment_exact_one_percent
        """
        ctx1 = setup_case_marketed(with_disclosures=True, with_offer=False)
        offer1 = create_offer(ctx1["case"], 6100000)
        bh1 = make_broker_headers(ctx1["broker"]["id"])

        ctx2 = setup_case_marketed(with_disclosures=True, with_offer=False,
                                   with_license=False,
                                   broker_overrides={"license_number": "BR-2"},
                                   policy_overrides={"policy_number": "P-2"})
        offer2 = create_offer(ctx2["case"], 6100000)
        bh2 = make_broker_headers(ctx2["broker"]["id"])

        ok = validate_success(api.counter_offer(
            offer1["id"], {"counter_amount_cents": 6161000,
                           "expected_offer_version": offer1["version"]}, bh1))
        assert ok["status"] == "COUNTERED", "counter at exactly 6161000 passes (>= inclusive)"

        resp = api.counter_offer(
            offer2["id"], {"counter_amount_cents": 6160999,
                           "expected_offer_version": offer2["version"]}, bh2)
        validate_error(resp, ApiErrorId.ERR_COUNTER_INCREMENT_TOO_SMALL)
        offer2_after = validate_success(api.get_offer(offer2["id"], CM))
        assert offer2_after["status"] == "PENDING"
        assert offer2_after["round_number"] == 1

    def test_counter_increment_rounds_half_up(self, api):
        """PRD §3.3: "the counter to clear a minimum increment:
        `counter_amount_cents` must be at least the offer's `amount_cents`
        multiplied by 101 and divided by 100, rounded half-up — a one-percent
        minimum bump — with anything less rejected as
        `ERR_COUNTER_INCREMENT_TOO_SMALL` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/counter_increment_exact_one_percent
        """
        # amount 6050055: 6050055 * 101 / 100 = 6110555.55 -> round_half_up 6110556.
        ctx = setup_case_marketed(with_disclosures=True, with_offer=False,
                                  broker_overrides={"license_number": "BR-3"},
                                  policy_overrides={"policy_number": "P-3"})
        offer = create_offer(ctx["case"], 6050055)
        bh = make_broker_headers(ctx["broker"]["id"])

        resp = api.counter_offer(
            offer["id"], {"counter_amount_cents": 6110555,
                          "expected_offer_version": offer["version"]}, bh)
        validate_error(resp, ApiErrorId.ERR_COUNTER_INCREMENT_TOO_SMALL)

        ok = validate_success(api.counter_offer(
            offer["id"], {"counter_amount_cents": 6110556,
                          "expected_offer_version": offer["version"]}, bh))
        assert ok["status"] == "COUNTERED"
        assert ok["counter_amount_cents"] == 6110556

    def test_terminal_offer_counter_rejected_before_increment_check(self, api):
        """PRD §2.7: "Terminal-state guard on the target resource: an action aimed
        at a resource already in a terminal state — countering an `EXPIRED` offer,
        paying a `PAID` payment, approving a `CLOSED` package — is rejected with
        `ERR_ALREADY_TERMINAL` (HTTP 409)."
        PRD §2.7: "Across all rules attached to an endpoint, evaluation follows a
        fixed priority order, and the first failure determines the response"

        Design: Difficulty/priority_pair_validation_conflict/terminal_offer_counter_rejected_before_increment_check
        """
        ctx = setup_case_marketed(with_disclosures=True, with_offer=False)
        offer = create_offer(ctx["case"], 6000000)  # default clock 2026-08-01, +10d
        bh = make_broker_headers(ctx["broker"]["id"])

        set_clock("2026-08-12T00:00:00Z")
        offer_after = validate_success(api.get_offer(offer["id"], CM))
        assert offer_after["status"] == "EXPIRED"

        resp = api.counter_offer(
            offer["id"], {"counter_amount_cents": 100,
                          "expected_offer_version": offer["version"]}, bh)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

    def test_terminal_offer_reject_and_withdraw_rejected(self, api):
        """PRD §2.7: "Terminal-state guard on the target resource: an action aimed
        at a resource already in a terminal state — countering an `EXPIRED` offer,
        paying a `PAID` payment, approving a `CLOSED` package — is rejected with
        `ERR_ALREADY_TERMINAL` (HTTP 409)."
        PRD §3.3: "A `PENDING` or `COUNTERED` offer whose `expires_at` passes
        becomes `EXPIRED` automatically."

        Design: Difficulty/priority_pair_validation_conflict/terminal_offer_counter_rejected_before_increment_check
        """
        ctx = setup_case_marketed(with_disclosures=True, with_offer=False,
                                  broker_overrides={"license_number": "BR-4"},
                                  policy_overrides={"policy_number": "P-4"})
        broker = ctx["broker"]
        bh = make_broker_headers(broker["id"])
        offer = create_offer(ctx["case"], 6000000)

        set_clock("2026-08-12T00:00:00Z")
        assert validate_success(api.get_offer(offer["id"], CM))["status"] == "EXPIRED"

        # Broker-side action on the terminal offer.
        resp_reject = api.reject_offer(offer["id"], bh)
        validate_error(resp_reject, ApiErrorId.ERR_ALREADY_TERMINAL)
        # Underwriter-side action on the terminal offer.
        resp_withdraw = api.withdraw_offer(offer["id"], UW)
        validate_error(resp_withdraw, ApiErrorId.ERR_ALREADY_TERMINAL)
        # Counter with a perfectly valid increment is still terminal-guarded.
        resp_counter = api.counter_offer(
            offer["id"], {"counter_amount_cents": 6060000,
                          "expected_offer_version": offer["version"]}, bh)
        validate_error(resp_counter, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestOfferExpiryAndDeadline:
    def test_offer_expiry_boundary_at_clock(self, api):
        """PRD §3.3: "Its `expires_at` is the creation clock plus `expires_in_days`
        — defaulting to 10 days when omitted, and capped at 30 days; a request
        above 30 is rejected with `ERR_INVALID_REQUEST`."
        PRD §2.4: "a `PENDING` or `COUNTERED` offer whose `expires_at` is earlier
        than the new clock becomes `EXPIRED`"

        Design: Corner/state_machines/offer_expiry_boundary_at_clock
        """
        ctx = setup_case_marketed(with_disclosures=False, with_offer=False)
        offer = create_offer(ctx["case"], 6000000)
        assert offer["expires_at"] == "2026-08-11T00:00:00Z"

        set_clock("2026-08-11T00:00:00Z")
        at = validate_success(api.get_offer(offer["id"], CM))
        assert at["status"] == "PENDING", "clock == expires_at is not yet expired (strictly earlier rule)"

        set_clock("2026-08-11T00:00:01Z")
        after = validate_success(api.get_offer(offer["id"], CM))
        assert after["status"] == "EXPIRED"

    def test_marketing_deadline_auto_expire(self, api):
        """PRD §3.2: "An approved case moves from `UNDERWRITING` to `MARKETED`; the
        system stamps `marketed_at` with the clock and sets `marketing_deadline` to
        `marketed_at` plus 90 days."
        PRD §2.4: "a `MARKETED` case whose `marketing_deadline` has passed with no
        `PENDING` or `COUNTERED` offers on it becomes `EXPIRED`."
        PRD §3.3: "the underwriter may withdraw a `PENDING` or `COUNTERED` offer"

        Design: Corner/state_machines/marketing_deadline_auto_expire
        """
        ctx = setup_case_marketed(with_disclosures=False, with_offer=False)
        case = ctx["case"]
        assert case["marketing_deadline"] == "2026-10-30T00:00:00Z"
        offer = create_offer(case, 6000000)
        validate_success(api.withdraw_offer(offer["id"], UW))

        set_clock("2026-10-30T00:00:01Z")
        case_after = validate_success(api.get_case(case["id"], CM))
        assert case_after["status"] == "EXPIRED"


class TestWithdrawAndReunderwrite:
    def test_withdraw_cascades_offers(self, api):
        """PRD §3.1: "Withdrawal cascades: withdrawing from `UNDERWRITING`
        supersedes any `ORDERED` life-expectancy reports, and withdrawing from
        `MARKETED` withdraws every `PENDING` or `COUNTERED` offer on the case."

        Design: Corner/state_machines/withdraw_cascades_offers
        """
        ctx = setup_case_marketed(with_disclosures=False, with_offer=True)
        case, offer, broker = ctx["case"], ctx["offer"], ctx["broker"]
        withdrawn = validate_success(api.withdraw_case(case["id"],
                                                       make_broker_headers(broker["id"])))
        assert withdrawn["status"] == "WITHDRAWN"
        offer_after = validate_success(api.get_offer(offer["id"], CM))
        assert offer_after["status"] == "WITHDRAWN"

    def test_reunderwrite_rejected_with_live_offer(self, api):
        """PRD §3.2: "an underwriter may send the case from `MARKETED` back to
        `UNDERWRITING` through reunderwriting — but only while no offer on the case
        is `PENDING` or `COUNTERED`; with live offers the attempt is rejected with
        `ERR_INVALID_STATE_TRANSITION`. Reunderwriting clears `blended_le_months`,
        `reserve_price_cents`, `marketed_at`, and `marketing_deadline` back to
        unset."

        Design: Corner/state_machines/reunderwrite_rejected_with_live_offer
        """
        ctx = setup_case_marketed(with_disclosures=False, with_offer=True)
        case, offer = ctx["case"], ctx["offer"]
        resp = api.reunderwrite_case(case["id"], UW)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        validate_success(api.withdraw_offer(offer["id"], UW))
        back = validate_success(api.reunderwrite_case(case["id"], UW))
        assert back["status"] == "UNDERWRITING"
        assert back["blended_le_months"] is None
        assert back["reserve_price_cents"] is None
        assert back["marketed_at"] is None
        assert back["marketing_deadline"] is None
