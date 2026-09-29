"""Who may do what, and the one rule that compares identities rather than roles.

Presenting an offer belongs to the retention operator alone, accepting one belongs to the
subscriber alone, holding the right role is not the same as owning the resource, and the
officer who signs off a floor breach may not be the operator who offered it.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    accept_grant,
    assert_margin_exception_consistency,
    create_cancellation_session_payload,
    create_cohort_snapshot_payload,
    create_modification_payload,
    get_success_data,
    make_compliance_officer_headers,
    make_retention_specialist_headers,
    make_subscriber_headers,
    margin_exception_payload,
    modifications_for,
    new_payment_method,
    new_plan,
    new_subscriber,
    new_template,
    read_grant,
    read_modification,
    read_session,
    read_subscription,
    reverse_modification_payload,
    setup_active_subscription,
    setup_presented_grant,
    setup_reason_captured_session,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_operator_headers"]

PRICE_OFFER = {"offer_type": "DISCOUNT", "discount_pct": 0.1000, "discount_cycles": 1,
               "priority_rank": 10, "eligible_reason_codes": ["PRICE"]}


class TestOfferPresentationIsExclusive:

    def test_the_subscriber_who_owns_the_session_may_not_present_the_offer(self):
        """A denied call is not a step, so the cancellation budget is untouched.

        PRD §2.1: "`RetentionSpecialist` is the retention operator: the only role that may
        present a save offer, and the role that runs win-back campaigns and reverses
        modifications."

        Design: Corner/rbac/subscriber_cannot_present_save_offers
        """
        new_template(code="T_PRICE", **PRICE_OFFER)
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        session = setup_reason_captured_session(world, reason_code="PRICE")

        validate_error(
            api_client.present_offers(session["id"], world["subscriber_headers"]),
            ApiErrorId.ERR_UNAUTHORIZED, 403)

        held = read_session(session["id"])
        assert held["state"] == "REASON_CAPTURED"
        assert held["offers_presented_count"] == 0
        assert held["step_count"] == 2
        assert held["presented_by_user_id"] is None

        _, meta = validate_paginated(api_client.list_save_offer_grants(
            ADMIN, params={"cancellation_session_id": session["id"]}))
        assert meta["total_count"] == 0


class TestAcceptanceIsTheSubscribersConsent:

    def test_a_billing_operator_may_not_accept_an_offer_for_the_subscriber(self):
        """Consent cannot be given on the subscriber's behalf, so no discount lands.

        PRD §4: "| POST | `/save-offer-grants/{id}/accept` | Accept a presented save offer |
        Subscriber |"

        Design: Corner/rbac/billing_operator_cannot_accept_a_save_offer
        """
        new_template(code="T_PRICE", **PRICE_OFFER)
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        grant = setup_presented_grant(world, reason_code="PRICE", as_user_id="rs_43")

        validate_error(api_client.accept_grant(grant["id"], BILLING),
                       ApiErrorId.ERR_UNAUTHORIZED, 403)

        held = read_grant(grant["id"])
        assert held["state"] == "PRESENTED"
        assert held["accepted_at"] is None
        assert read_session(world["session"]["id"])["state"] == "OFFERS_PRESENTED"

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["committed_price_cents"] == 4999
        assert subscription["active_discount_pct"] == pytest.approx(0.0000, abs=5e-5)
        assert subscription["version"] == 1


class TestOwnershipBeatsRoleMembership:

    def test_one_subscriber_may_not_open_a_session_on_anothers_subscription(self):
        """The role is on the endpoint's list, but the identity does not match the chain.

        PRD §2.1: "A `Subscriber` acting on another subscriber's resource chain is rejected
        with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/subscriber_cannot_open_a_session_on_another_subscribers_subscription
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        stranger = new_subscriber(acquisition_channel="SEARCH")
        new_payment_method(stranger["id"])

        payload = create_cancellation_session_payload(world["subscription"]["id"])
        validate_error(api_client.create_cancellation_session(
            payload, make_subscriber_headers(stranger["id"])),
            ApiErrorId.ERR_UNAUTHORIZED, 403)

        _, meta = validate_paginated(api_client.list_cancellation_sessions(
            ADMIN, params={"subscription_id": world["subscription"]["id"]}))
        assert meta["total_count"] == 0

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["lifecycle_state"] == "ACTIVE"
        assert subscription["version"] == 1


class TestSegregationOfDuties:

    def test_the_officer_who_presented_the_offer_may_not_approve_its_breach(self):
        """The same identifier on both sides is refused; a different officer unlocks the accept.

        PRD §2.1: "Because `RetentionSpecialist` and `ComplianceOfficer` identifiers are both
        opaque strings drawn from the same space, the segregation-of-duties rule is expressed
        as a direct string comparison: the `X-User-ID` of the `ComplianceOfficer` deciding a
        grant's margin-floor exception must differ from that grant's `presented_by_user_id`."

        Design: Corner/rbac/the_presenting_user_may_not_decide_that_grants_margin_exception
        """
        deep_plan = new_plan(code="BOUND", monthly_price_cents=5000, unit_cogs_cents=2500,
                            margin_floor_pct=0.4048, allowed_frequency_weeks=[4],
                            is_negative_option=False)
        new_template(code="T_DEEP", offer_type="DISCOUNT", discount_pct=0.4500,
                     discount_cycles=2, priority_rank=10, eligible_reason_codes=["PRICE"])
        world = setup_active_subscription(
            clock="2026-01-10", plan=deep_plan,
            subscriber_overrides={"acquisition_channel": "SEARCH"})
        grant = setup_presented_grant(world, reason_code="PRICE", as_user_id="rs_9")
        assert grant["presented_by_user_id"] == "rs_9"

        validate_error(api_client.decide_margin_exception(
            grant["id"], margin_exception_payload("APPROVE",
                                                  justification="self approval attempt"),
            make_compliance_officer_headers("rs_9")),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        undecided = read_grant(grant["id"])
        assert undecided["margin_exception_state"] == "PENDING"
        assert undecided["decided_by_user_id"] is None

        decided = validate_success(api_client.decide_margin_exception(
            grant["id"], margin_exception_payload(
                "APPROVE", justification="retention value justifies the floor breach"),
            make_compliance_officer_headers("co_1")), 200)

        assert decided["margin_exception_required"] is True
        # 2750 a cycle for two cycles then 5000 for three: 8000 of margin on 20500.
        assert decided["per_cycle_margin_pct"] == pytest.approx(0.0909, abs=5e-5)
        assert decided["blended_term_margin_pct"] == pytest.approx(0.3902, abs=5e-5)
        assert decided["retention_value_cents"] == 8000
        assert decided["margin_exception_state"] == "APPROVED"
        assert decided["decided_by_user_id"] == "co_1"
        assert_margin_exception_consistency(decided)

        accepted = accept_grant(grant["id"], world["subscriber_headers"])
        assert accepted["state"] == "ACCEPTED"

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["committed_price_cents"] == 2750
        assert subscription["active_discount_pct"] == pytest.approx(0.4500, abs=5e-5)
        assert subscription["discount_remaining_cycles"] == 2
        assert read_session(world["session"]["id"])["state"] == "OFFER_ACCEPTED"


class TestRetentionSpecialistSharedOperations:

    def test_the_specialist_can_modify_reverse_and_snapshot_without_the_subscriber(self):
        """Three shared operations in a row, ending with the cadence restored at version 3.

        PRD §4: "| POST | `/subscriptions/{id}/modifications` | Request a subscription
        modification | Subscriber, RetentionSpecialist |"

        Design: Corner/rbac/retention_specialist_shared_operations_all_succeed
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})
        specialist = make_retention_specialist_headers("rs_44")

        payload = create_modification_payload("FREQUENCY_CHANGE",
                                              world["subscription"]["version"],
                                              frequency_weeks=2)
        applied = validate_success(api_client.create_modification(
            world["subscription"]["id"], payload, specialist), 201)

        get_success_data(api_client.reverse_modification(
            applied["id"], specialist,
            reverse_modification_payload(reason_note="subscriber changed their mind")))

        assert read_modification(applied["id"])["state"] == "REVERSED"
        compensating = [row for row in modifications_for(world["subscription"]["id"])
                        if row["reverses_modification_id"] == applied["id"]]
        assert len(compensating) == 1
        assert compensating[0]["prior_snapshot"]["frequency_weeks"] == 2
        assert compensating[0]["delta_price_cents"] == 0

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["frequency_weeks"] == 4
        assert subscription["committed_price_cents"] == 4999
        assert subscription["version"] == 3

        snapshot = validate_success(api_client.create_cohort_snapshot(
            create_cohort_snapshot_payload("2026-01", "REALIZED"), specialist), 201)
        assert snapshot["member_count"] == 1
        assert snapshot["retained_count"] == 1
