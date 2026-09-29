"""The win-back contact cap is one aggregate send per subscriber per 30 days.

Two campaigns each hold a target for the same lapsed subscriber.  Once one campaign
has sent, the other is refused for as long as that send sits inside the trailing
thirty-day window — including on the day that is exactly thirty days later.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_target,
    api_client,
    assert_instant,
    complete_session,
    pay_invoice,
    read_subscriber,
    read_target,
    run_renewal,
    send_target,
    set_clock,
    setup_active_subscription,
    setup_launched_campaign,
    setup_reason_captured_session,
    validate_error,
    validate_success,
)

RETENTION = TEST_USERS["retention_specialist_headers"]

CAMPAIGN = {
    "min_days_since_lapse": 30,
    "max_days_since_lapse": 120,
    "send_window_days": 14,
    "suppression_days": 60,
}


def _one_lapsed_subscriber_targeted_by_two_campaigns():
    """Lapsed 2026-02-07 after paying one 6298/2620 invoice; two targets minted 2026-03-13."""
    world = setup_active_subscription(
        clock="2026-01-10",
        subscriber_overrides={"acquisition_channel": "SEARCH"},
        addons=[{"code": "MUG", "qty": 1}],
    )
    pay_invoice(world["invoice"]["id"])
    set_clock("2026-01-15")
    session = setup_reason_captured_session(world, reason_code="PRICE")
    complete_session(session["id"], world["subscriber_headers"])
    set_clock("2026-02-07")
    run_renewal(world["subscription"]["id"])

    first = setup_launched_campaign(offer_discount_pct=0.2000, **CAMPAIGN)
    second = setup_launched_campaign(offer_discount_pct=0.2500, **CAMPAIGN)
    set_clock("2026-03-13")
    world["first_campaign"] = first
    world["second_campaign"] = second
    world["first_target"] = add_target(first, world["subscriber"]["id"])
    world["second_target"] = add_target(second, world["subscriber"]["id"])
    return world


class TestWinBackContactCap:

    def test_a_send_by_one_campaign_blocks_the_other_across_the_closed_window(self):
        """The cap counts sends from every campaign, and 30 days later is still inside it.

        PRD §3.8: "then the contact cap: the number of this subscriber's targets whose
        `sent_at` lies inside the closed sliding window from 30 days before the clock
        up to the clock must be strictly below one. This is an aggregate capacity
        check, not a pairwise-overlap check, and exceeding it is rejected with
        `ERR_CONTACT_CAP_EXCEEDED` (422)."

        Design: Difficulty/resource_temporal_overlap/winback_contact_cap_aggregate_sliding_window
        """
        world = _one_lapsed_subscriber_targeted_by_two_campaigns()

        assert world["first_target"]["days_since_lapse_at_target"] == 34
        # 0.45 * (3678/20000) + 0.30 * (1 - 34/120) + 0.25 * 1.0 for a PRICE reason.
        assert world["first_target"]["priority_score"] == pytest.approx(0.5478, abs=5e-5)

        sent = send_target(world["first_target"]["id"])
        assert sent["state"] == "SENT"
        assert_instant(sent["sent_at"], "2026-03-13T00:00:00Z", "sent_at")
        assert_instant(read_subscriber(world["subscriber"]["id"])["last_contacted_at"],
                       "2026-03-13T00:00:00Z", "last_contacted_at")

        second_id = world["second_target"]["id"]

        set_clock("2026-03-20")
        validate_error(api_client.send_winback_target(second_id, RETENTION),
                       ApiErrorId.ERR_CONTACT_CAP_EXCEEDED, 422)

        # 2026-03-13 sits exactly on the closed lower bound of the window here.
        set_clock("2026-04-12")
        validate_error(api_client.send_winback_target(second_id, RETENTION),
                       ApiErrorId.ERR_CONTACT_CAP_EXCEEDED, 422)

        blocked = read_target(second_id)
        assert blocked["state"] == "ELIGIBLE"
        assert blocked["sent_at"] is None
        assert blocked["expires_at"] is None

    def test_the_day_the_window_slides_past_the_earlier_send_the_second_campaign_may_send(self):
        """On 2026-04-13 the earlier send falls out of the window and the send succeeds.

        PRD §3.8: "A successful send moves the target from `ELIGIBLE` to `SENT`, sets
        `sent_at` to the clock and `expires_at` to the clock plus the campaign's
        `send_window_days` days, sets the subscriber's `last_contacted_at` to the
        clock, and increments the campaign's `sent_count`."

        Design: Difficulty/resource_temporal_overlap/winback_contact_cap_aggregate_sliding_window
        """
        world = _one_lapsed_subscriber_targeted_by_two_campaigns()

        send_target(world["first_target"]["id"])

        set_clock("2026-04-13")
        response = api_client.send_winback_target(world["second_target"]["id"], RETENTION)
        sent = validate_success(response, 200)

        assert sent["state"] == "SENT"
        assert_instant(sent["sent_at"], "2026-04-13T00:00:00Z", "sent_at")
        assert_instant(sent["expires_at"], "2026-04-27T00:00:00Z", "expires_at")

        assert_instant(read_subscriber(world["subscriber"]["id"])["last_contacted_at"],
                       "2026-04-13T00:00:00Z", "last_contacted_at")
