"""Requests that break two rules at once, where only the lower rung answers.

The ladder is global, so a state problem outranks a fiscal one and a safety
problem outranks a temporal one, no matter which violation looks worse.
"""

from test_helpers import (
    SPONSOR,
    api_client,
    create_subscription_payload,
    mark_exchange_file_expired,
    read_exchange_file,
    read_investor,
    read_offering,
    read_subscription,
    read_trust,
    set_clock,
    setup_funding_with_investor_a,
    setup_reserved_subscription_a,
    validate_error,
    validate_paginated,
)


class TestExchangeFileStateBeatsMinimumInvestment:
    def test_the_expired_file_answers_before_the_undersized_request(self):
        """Rung 21 is reached before rung 54 on the same request.

        PRD: "When a request violates more than one rule, exactly one error comes
        back: the violation with the lowest priority number in the ladder below."

        Design: Difficulty/priority_pair_validation_conflict/state_exchange_file_expired_beats_fiscal_below_minimum
        """
        deal = setup_funding_with_investor_a()
        set_clock("2027-02-02T00:00:00Z")
        expired = mark_exchange_file_expired(deal["exchange_file_a"]["id"])
        assert expired["status"] == "EXPIRED"

        response = api_client.create_subscription(
            create_subscription_payload(
                deal["offering"]["id"],
                deal["investor_a"]["id"],
                deal["exchange_file_a"]["id"],
                5,
                deal["offering_version"],
            ),
            SPONSOR,
        )

        error = validate_error(response, "ERR_EXCHANGE_FILE_INVALID_STATE", 409)
        assert error["error_id"] != "ERR_BELOW_MINIMUM_INVESTMENT"

    def test_the_undersized_request_is_five_units_against_a_minimum_of_fifteen(self):
        """The fiscal violation is real and still does not surface.

        PRD: "Units requested meet the offering minimum, on subscription creation:
        `ERR_BELOW_MINIMUM_INVESTMENT`."

        Design: Difficulty/priority_pair_validation_conflict/state_exchange_file_expired_beats_fiscal_below_minimum
        """
        deal = setup_funding_with_investor_a()
        assert deal["offering"]["min_units_per_investor"] == 15
        set_clock("2027-02-02T00:00:00Z")
        mark_exchange_file_expired(deal["exchange_file_a"]["id"])

        response = api_client.create_subscription(
            create_subscription_payload(
                deal["offering"]["id"],
                deal["investor_a"]["id"],
                deal["exchange_file_a"]["id"],
                5,
                deal["offering_version"],
            ),
            SPONSOR,
        )
        validate_error(response, "ERR_EXCHANGE_FILE_INVALID_STATE")

    def test_the_rejected_request_leaves_no_trace_on_the_offering(self):
        """Evaluation stops at the rung and no side effect is applied.

        PRD: "Evaluation stops there, and none of the request's side effects are
        applied."

        Design: Difficulty/priority_pair_validation_conflict/state_exchange_file_expired_beats_fiscal_below_minimum
        """
        deal = setup_funding_with_investor_a()
        version_before = read_offering(deal["offering"]["id"])["version"]
        set_clock("2027-02-02T00:00:00Z")
        mark_exchange_file_expired(deal["exchange_file_a"]["id"])

        api_client.create_subscription(
            create_subscription_payload(
                deal["offering"]["id"],
                deal["investor_a"]["id"],
                deal["exchange_file_a"]["id"],
                5,
                deal["offering_version"],
            ),
            SPONSOR,
        )

        response = api_client.list_subscriptions(
            SPONSOR, params={"offering_id": deal["offering"]["id"]}
        )
        _, meta = validate_paginated(response)
        assert meta["total_count"] == 0

        offering = read_offering(deal["offering"]["id"])
        assert offering["units_committed"] == 0
        assert offering["equity_committed_cents"] == 0
        assert offering["version"] == version_before


class TestAccreditationExpiryBeatsExchangeDeadline:
    def test_the_lapsed_verification_answers_before_the_dead_exchange_clock(self):
        """Rung 29 is reached before rung 39 on the closing request.

        PRD: "Reading it top to bottom is the only way to predict which of two
        competing errors a request will produce."

        Design: Difficulty/priority_pair_validation_conflict/safety_accreditation_expired_beats_temporal_exchange_deadline
        """
        deal = setup_reserved_subscription_a(300)
        set_clock("2027-02-07T00:00:00Z")

        response = api_client.close_subscription(
            deal["subscription_a"]["id"], SPONSOR
        )

        error = validate_error(response, "ERR_ACCREDITATION_EXPIRED", 422)
        assert error["error_id"] != "ERR_EXCHANGE_DEADLINE_PASSED"

    def test_both_deadlines_really_are_in_the_past(self):
        """The temporal violation is live and still outranked.

        PRD: "The logical clock is at or before the file's `exchange_deadline`, on
        subscription creation and closing: `ERR_EXCHANGE_DEADLINE_PASSED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_accreditation_expired_beats_temporal_exchange_deadline
        """
        deal = setup_reserved_subscription_a(300)
        set_clock("2027-02-07T00:00:00Z")

        investor = read_investor(deal["investor_a"]["id"])
        exchange_file = read_exchange_file(deal["exchange_file_a"]["id"])
        assert investor["accreditation_expires_at"] == "2026-11-18T00:00:00.000Z"
        assert exchange_file["exchange_deadline"] == "2027-02-01T23:59:59.999Z"

        response = api_client.close_subscription(
            deal["subscription_a"]["id"], SPONSOR
        )
        validate_error(response, "ERR_ACCREDITATION_EXPIRED")

    def test_the_refused_close_leaves_the_subscription_and_trust_untouched(self):
        """A refused close books nothing and assigns no ordinal.

        PRD: "Evaluation stops there, and none of the request's side effects are
        applied."

        Design: Difficulty/priority_pair_validation_conflict/safety_accreditation_expired_beats_temporal_exchange_deadline
        """
        deal = setup_reserved_subscription_a(300)
        set_clock("2027-02-07T00:00:00Z")

        api_client.close_subscription(deal["subscription_a"]["id"], SPONSOR)

        subscription = read_subscription(deal["subscription_a"]["id"])
        assert subscription["status"] == "RESERVED"
        assert subscription["closing_sequence_no"] is None
        trust = read_trust(deal["trust"]["id"])
        assert trust["status"] == "FUNDING"
        assert trust["units_issued"] == 0
