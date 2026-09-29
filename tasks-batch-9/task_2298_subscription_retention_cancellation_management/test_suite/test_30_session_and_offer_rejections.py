"""Guards around the one retention conversation a subscription is allowed at a time.

Only one live session may exist per subscription; a template whose yearly allowance is
spent is still the selected candidate and is refused on quota rather than on emptiness; a
reason nobody wrote an offer for empties the pool; and an offer that never breached the
floor has nothing for a compliance officer to decide.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_grant,
    api_client,
    assert_margin_exception_consistency,
    create_cancellation_session_payload,
    make_compliance_officer_headers,
    make_retention_specialist_headers,
    margin_exception_payload,
    new_template,
    present_offers,
    read_grant,
    read_session,
    read_subscriber,
    setup_active_subscription,
    setup_presented_grant,
    setup_reason_captured_session,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestOneLiveSessionPerSubscription:

    def test_a_second_session_is_refused_while_the_first_is_still_open(self):
        """The live session is in REASON_CAPTURED, which is one of the blocking states.

        PRD §3.5: "Two guards apply in order: the subscription's `lifecycle_state` must be
        `ACTIVE` or `PAUSED`, otherwise `ERR_SUBSCRIPTION_NOT_MODIFIABLE` (409); and no other
        session on the same subscription may be in `STARTED`, `REASON_CAPTURED` or
        `OFFERS_PRESENTED`, otherwise `ERR_SESSION_ALREADY_OPEN` (409)."

        Design: Corner/errors/second_open_cancellation_session_on_one_subscription_is_rejected
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        live_session = setup_reason_captured_session(world, reason_code="PRICE")

        payload = create_cancellation_session_payload(world["subscription"]["id"],
                                                     entry_channel="AGENT_ASSISTED")
        validate_error(
            api_client.create_cancellation_session(payload, world["subscriber_headers"]),
            ApiErrorId.ERR_SESSION_ALREADY_OPEN, 409)

        _, meta = validate_paginated(api_client.list_cancellation_sessions(
            ADMIN, params={"subscription_id": world["subscription"]["id"]}))
        assert meta["total_count"] == 1

        held = read_session(live_session["id"])
        assert held["state"] == "REASON_CAPTURED"
        assert held["step_count"] == 2


class TestYearlyOfferAllowance:

    def test_a_template_whose_allowance_is_spent_is_refused_on_quota(self):
        """The exhausted template is still selected, so the answer names the quota.

        PRD §3.6: "Second, if the grants of the *selected* template for this subscriber
        inside the trailing 365 days have already reached that template's
        `max_per_subscriber_per_365d`, the round is rejected with `ERR_OFFER_QUOTA_EXCEEDED`
        (422); the count must be strictly below the cap for the round to proceed."

        Design: Corner/errors/presenting_an_exhausted_template_a_second_time_is_rejected_on_quota
        """
        only_template = new_template(
            code="T_Q", offer_type="DISCOUNT", discount_pct=0.1000, discount_cycles=1,
            priority_rank=10, eligible_reason_codes=["PRICE"], max_per_subscriber_per_365d=1)
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})

        first_session = setup_reason_captured_session(world, reason_code="PRICE")
        first_grant = present_offers(first_session["id"])
        accept_grant(first_grant["id"], world["subscriber_headers"])

        second_session = setup_reason_captured_session(world, reason_code="PRICE")
        validate_error(
            api_client.present_offers(second_session["id"],
                                      make_retention_specialist_headers("rs_40")),
            ApiErrorId.ERR_OFFER_QUOTA_EXCEEDED, 422)

        _, meta = validate_paginated(api_client.list_save_offer_grants(
            ADMIN, params={"save_offer_template_id": only_template["id"]}))
        assert meta["total_count"] == 1
        assert read_grant(first_grant["id"])["state"] == "ACCEPTED"

        held = read_session(second_session["id"])
        assert held["state"] == "REASON_CAPTURED"
        assert held["offers_presented_count"] == 0
        assert held["step_count"] == 2
        assert read_subscriber(
            world["subscriber"]["id"])["save_offer_grants_365d_count"] == 1


class TestEmptyCandidatePool:

    def test_a_reason_no_template_lists_empties_the_pool_without_blaming_tenure(self):
        """The only template lists PRICE, so an OTHER session has no candidate at all.

        PRD §3.6: "Third, if the eligibility filter yields no candidate for any reason other
        than tenure — no template lists the `reason_code` at all, the `offer_type`'s
        structural precondition fails, or every match is `RETIRED` — the round is rejected
        with `ERR_NO_ELIGIBLE_SAVE_OFFER` (422)."

        Design: Corner/errors/reason_with_no_matching_template_returns_no_eligible_save_offer
        """
        new_template(code="T_PRICE", offer_type="DISCOUNT", discount_pct=0.1000,
                     discount_cycles=1, priority_rank=10, eligible_reason_codes=["PRICE"],
                     min_tenure_days=0)
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        session = setup_reason_captured_session(world, reason_code="OTHER")

        validate_error(
            api_client.present_offers(session["id"],
                                      make_retention_specialist_headers("rs_41")),
            ApiErrorId.ERR_NO_ELIGIBLE_SAVE_OFFER, 422)

        held = read_session(session["id"])
        assert held["state"] == "REASON_CAPTURED"
        assert held["offers_presented_count"] == 0
        assert held["step_count"] == 2
        assert held["presented_by_user_id"] is None

        _, meta = validate_paginated(api_client.list_save_offer_grants(
            ADMIN, params={"cancellation_session_id": session["id"]}))
        assert meta["total_count"] == 0


class TestExceptionDecisionPrecondition:

    def test_an_offer_that_cleared_the_floor_has_no_exception_to_decide(self):
        """A shallow single-cycle discount blends to 0.5691 against a 0.4200 floor.

        PRD §3.6: "Its guards run in this order: the segregation-of-duties comparison of
        §2.1, whose violation is `ERR_SEGREGATION_OF_DUTIES` (403); then
        `margin_exception_state` must be `PENDING`, a decision on any other value being
        rejected with `ERR_MARGIN_EXCEPTION_NOT_REQUIRED` (409)."

        Design: Corner/errors/deciding_an_exception_that_was_never_required_is_rejected
        """
        new_template(code="T_SHALLOW", offer_type="DISCOUNT", discount_pct=0.1000,
                     discount_cycles=1, priority_rank=10, eligible_reason_codes=["PRICE"])
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        grant = setup_presented_grant(world, reason_code="PRICE", as_user_id="rs_42")

        validate_error(api_client.decide_margin_exception(
            grant["id"], margin_exception_payload("APPROVE", justification="looks fine"),
            make_compliance_officer_headers("co_2")),
            ApiErrorId.ERR_MARGIN_EXCEPTION_NOT_REQUIRED, 409)

        held = read_grant(grant["id"])
        assert held["blended_term_margin_pct"] == pytest.approx(0.5691, abs=5e-5)
        assert held["margin_exception_required"] is False
        assert held["margin_exception_state"] == "NOT_REQUIRED"
        assert held["decided_by_user_id"] is None
        assert held["version"] == 1
        assert_margin_exception_consistency(held)
