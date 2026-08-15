"""Renewal efforts: manual firing, pricing per effort position, the renewal
window gate, and declining an event."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    assert_renewal_event,
    create_publication,
    create_issue,
    create_subscriber,
    create_active_subscription,
    create_default_renewal_series,
    get_subscription,
    setup_active_subscription_with_pending_renewal_event,
    set_clock,
    CM,
)

CM_H = TEST_USERS["circulation_manager_headers"]


class TestFireNextEffort:
    def test_fire_next_effort_creates_first_event_with_first_price(self, api):
        """With the renewal window open, firing the next effort creates effort
        number 1 at the first configured price, PENDING, with the series code
        denormalized onto the event; the subscription carries the default
        series' code.

        PRD §3.6: "When an effort fires for a subscription, the created **RenewalEvent** takes the next `effort_number` — one greater than the subscription's current `renewal_effort_number` — records `sent_at`, and sets its `offered_price_cents` to the entry of `effort_pricing_cents` at that effort's position: the first effort uses the first price, the second the second, and no event fires once the effort number would exceed `max_efforts`. The event's `series_code` is denormalized onto it for audit, its `response` starts `PENDING`, and `responded_at` remains unset until the subscriber answers."
        PRD §3.2: "Finally, when the publication has a default renewal series, the subscription adopts that series' code as its `renewal_series_code` and its first renewal effort is scheduled; the `renewal_effort_number` counter starts at zero, meaning no effort has yet been sent."

        Design: Difficulty/resource_temporal_overlap/renewal_effort_window_half_open
        """
        ctx = setup_active_subscription_with_pending_renewal_event(
            series_offsets=(-30, -7), series_pricing=(999, 1199)
        )
        event = ctx["renewal_event"]
        series = ctx["renewal_series"]
        assert_renewal_event(event)
        assert event["effort_number"] == 1, (
            f"no effort had been sent, so the fired effort is number 1, got {event['effort_number']}"
        )
        assert event["offered_price_cents"] == 999, (
            f"the first effort uses the first price, got {event['offered_price_cents']}"
        )
        assert event["response"] == "PENDING"
        assert event.get("responded_at") is None
        assert event["series_code"] == series["series_code"]

        sub = get_subscription(ctx["publication"]["id"], ctx["subscription"]["id"])
        assert sub["renewal_series_code"] == series["series_code"]

    def test_fire_next_effort_before_window_open_rejected(self, api):
        """Firing an effort whose offset window has not opened — here the
        logical clock sits eleven-plus months before any plausible term expiry
        while the first window opens ninety days before expiry — is rejected
        with ERR_RENEWAL_WINDOW_NOT_OPEN.

        PRD §3.6: "An effort may fire only when the logical clock has crossed the effort's configured offset window ahead of expiry; a `CirculationManager` may fire the next effort manually, but doing so before its window has opened is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`."

        Design: Difficulty/resource_temporal_overlap/renewal_effort_window_half_open
        """
        set_clock()  # 2026-08-01; the 12-issue term cannot plausibly expire before 2027.
        pub = create_publication()
        issue = create_issue(pub["id"])
        create_default_renewal_series(pub["id"], offsets=(-90, -60, -30), pricing=(999, 1099, 1199))
        subscriber = create_subscriber()
        sub = create_active_subscription(pub["id"], subscriber["id"], issue["id"])

        resp = api.fire_next_renewal_event(pub["id"], sub["id"], CM_H)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN, 409)


class TestDeclineEvent:
    def test_decline_marks_event_and_increments_effort_number(self, api):
        """Declining a PENDING event marks it DECLINED and advances the
        subscription's renewal_effort_number by exactly one.

        PRD §3.6: "From `PENDING`, an event resolves one of three ways: a successful renewal matching the effort marks it `ACCEPTED`; a `CirculationManager` may mark it `DECLINED`, which also increments the subscription's `renewal_effort_number`; and the event lapses to `EXPIRED` when the next effort fires or when the subscription cancels or expires."

        Design: Corner/state_machines/subscription_renewal_event_decline_side_effect
        """
        ctx = setup_active_subscription_with_pending_renewal_event()
        pub_id = ctx["publication"]["id"]
        sub = ctx["subscription"]
        event = ctx["renewal_event"]

        effort_before = get_subscription(pub_id, sub["id"])["renewal_effort_number"]

        declined = validate_success(api.decline_renewal_event(pub_id, sub["id"], event["id"], CM_H))
        assert declined["response"] == "DECLINED", (
            f"declined event must read DECLINED, got {declined['response']}"
        )

        effort_after = get_subscription(pub_id, sub["id"])["renewal_effort_number"]
        assert effort_after == effort_before + 1, (
            f"declining must increment renewal_effort_number by one: {effort_before} -> {effort_after}"
        )
