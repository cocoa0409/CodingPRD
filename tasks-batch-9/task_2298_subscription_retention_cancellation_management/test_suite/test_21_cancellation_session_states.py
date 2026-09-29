"""The cancellation conversation: where it starts, what it refuses, and what it does.

The create call is itself the first recorded step; completion refuses to run before a
reason exists; a terminal session refuses everything; and the completion that does run
performs all four of its declared effects at once.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_cancellation_session,
    assert_instant,
    complete_cancellation_payload,
    capture_reason_payload,
    complete_session,
    notice_of_type,
    open_session,
    present_offers,
    read_grant,
    read_session,
    read_subscriber,
    read_subscription,
    setup_reason_captured_session,
    setup_active_subscription,
    new_template,
    validate_error,
)

PRICE_OFFER = {"offer_type": "DISCOUNT", "discount_pct": 0.1000, "discount_cycles": 1,
               "priority_rank": 10, "eligible_reason_codes": ["PRICE"]}


def _active_subscription():
    return setup_active_subscription(
        clock="2026-01-10", subscriber_overrides={"acquisition_channel": "SEARCH"})


class TestSessionInitialState:

    def test_opening_a_session_records_the_create_call_as_step_one(self):
        """STARTED, one step already spent, no reason and no presenter yet.

        PRD §3.5: "A new session records `state` `STARTED`, `step_count` 1,
        `offers_presented_count` 0, and `started_at` at the clock, with `reason_code`,
        `reason_detail`, `completed_at` and `presented_by_user_id` all null."

        Design: Corner/state_machines/cancellation_session_starts_in_started_with_step_count_one
        """
        world = _active_subscription()
        session = open_session(world, entry_channel="WEB_SELF_SERVE")

        assert_cancellation_session(session)
        assert session["state"] == "STARTED"
        assert session["step_count"] == 1
        assert session["offers_presented_count"] == 0
        assert session["reason_code"] is None
        assert session["reason_detail"] is None
        assert session["presented_by_user_id"] is None
        assert session["completed_at"] is None
        assert_instant(session["started_at"], "2026-01-10T00:00:00Z", "started_at")

        assert read_subscription(world["subscription"]["id"])["lifecycle_state"] == "ACTIVE"


class TestCompletionPreconditions:

    def test_completing_before_a_reason_is_captured_is_refused(self):
        """The step budget exempts completion, but the reason gate does not.

        PRD §3.5: "Its guards are, in order: session not terminal
        (`ERR_SESSION_ALREADY_TERMINAL`, 409), then `reason_code` must not be null
        (`ERR_REASON_NOT_CAPTURED`, 409) — a subscriber cannot complete a cancellation
        whose reason was never captured."

        Design: Corner/state_machines/session_complete_before_reason_capture_returns_reason_not_captured
        """
        world = _active_subscription()
        session = open_session(world)

        validate_error(
            api_client.complete_cancellation(session["id"], complete_cancellation_payload(True),
                                             world["subscriber_headers"]),
            ApiErrorId.ERR_REASON_NOT_CAPTURED, 409)

        unchanged = read_session(session["id"])
        assert unchanged["state"] == "STARTED"
        assert unchanged["step_count"] == 1
        assert unchanged["completed_at"] is None

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["lifecycle_state"] == "ACTIVE"
        assert subscription["cancel_effective_at"] is None


class TestTerminalSessionLockdown:

    def test_revising_the_reason_after_completion_is_refused_and_keeps_the_old_reason(self):
        """COMPLETED_CANCELLED is terminal, and the terminal check runs before the budget.

        PRD §3.5: "Any state-advancing call against a session already in one of the three
        terminal states is rejected with `ERR_SESSION_ALREADY_TERMINAL` (409), and that
        check is the first domain guard on reason capture, offer presentation and
        completion alike."

        Design: Corner/state_machines/reason_revision_after_completion_returns_session_already_terminal
        """
        world = _active_subscription()
        session = setup_reason_captured_session(world, reason_code="PRICE")
        complete_session(session["id"], world["subscriber_headers"])

        validate_error(
            api_client.capture_reason(session["id"],
                                      capture_reason_payload("OTHER",
                                                             reason_detail="changed my mind"),
                                      world["subscriber_headers"]),
            ApiErrorId.ERR_SESSION_ALREADY_TERMINAL, 409)

        locked = read_session(session["id"])
        assert locked["state"] == "COMPLETED_CANCELLED"
        assert locked["reason_code"] == "PRICE"
        assert locked["reason_detail"] is None
        # Create, reason capture and completion: three recorded steps and no more.
        assert locked["step_count"] == 3


class TestCompletionSideEffects:

    def test_one_completion_call_fires_all_four_declared_effects(self):
        """Session terminal, subscription pending, grant expired and a confirmation sent.

        PRD §3.5: "Completion has identical consequences from either origin state: the
        subscription moves from `ACTIVE` or `PAUSED` to `PENDING_CANCEL` with
        `cancel_effective_at` set to `next_renewal_at`, and the subscription's `version`
        increments. Every `SaveOfferGrant` on the session still in `PRESENTED` moves to
        `EXPIRED`, which recomputes the subscriber's `save_offer_grants_365d_count`. A
        `CANCELLATION_CONFIRMATION` notice is created already `SENT` with `sent_at` at the
        clock."

        Design: Corner/state_machines/session_completion_executes_every_declared_side_effect
        """
        new_template(code="T_PRICE", **PRICE_OFFER)
        world = _active_subscription()
        session = setup_reason_captured_session(world, reason_code="PRICE")
        grant = present_offers(session["id"], as_user_id="rs_1")

        completed = complete_session(session["id"], world["subscriber_headers"])
        assert completed["state"] == "COMPLETED_CANCELLED"
        assert completed["step_count"] == 4
        assert_instant(completed["completed_at"], "2026-01-10T00:00:00Z", "completed_at")

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["lifecycle_state"] == "PENDING_CANCEL"
        assert_instant(subscription["cancel_effective_at"], "2026-02-07T00:00:00Z",
                       "cancel_effective_at")
        assert subscription["version"] == 2

        assert read_grant(grant["id"])["state"] == "EXPIRED"

        notice = notice_of_type(world["subscription"]["id"], "CANCELLATION_CONFIRMATION")
        assert notice["state"] == "SENT"
        assert_instant(notice["sent_at"], "2026-01-10T00:00:00Z", "sent_at")

        subscriber = read_subscriber(world["subscriber"]["id"])
        # The expired grant left the trailing window, and access continues through the term.
        assert subscriber["save_offer_grants_365d_count"] == 0
        assert subscriber["churn_type"] == "NONE"
