"""A win-back target walks the non-linear cycle ELIGIBLE, SENT, EXPIRED, ELIGIBLE.

The subscriber lapsed voluntarily on a price complaint, so their priority score is
driven by all three weighted terms.  After the send window closes the target expires,
and it only returns to eligibility once the campaign's suppression window has run out.
"""

import pytest

from test_helpers import (
    add_target,
    assert_instant,
    assert_winback_target,
    complete_session,
    pay_invoice,
    read_campaign,
    read_subscriber,
    read_target,
    reevaluate_target,
    run_renewal,
    send_target,
    set_clock,
    setup_active_subscription,
    setup_launched_campaign,
    setup_reason_captured_session,
)

CAMPAIGN = {
    "min_days_since_lapse": 30,
    "max_days_since_lapse": 120,
    "send_window_days": 14,
    "suppression_days": 60,
    "offer_discount_pct": 0.2000,
}


def _voluntarily_lapsed_subscriber_targeted_on_april_first():
    """Paid one 6298/2620 invoice, cancelled voluntarily on a PRICE reason, lapsed 2026-02-07."""
    world = setup_active_subscription(
        clock="2026-01-10",
        subscriber_overrides={"acquisition_channel": "SEARCH"},
        addons=[{"code": "MUG", "qty": 1}],
    )
    pay_invoice(world["invoice"]["id"])
    set_clock("2026-01-15")
    session = setup_reason_captured_session(world, reason_code="PRICE",
                                           entry_channel="APP_SELF_SERVE")
    complete_session(session["id"], world["subscriber_headers"])
    set_clock("2026-02-07")
    run_renewal(world["subscription"]["id"])

    campaign = setup_launched_campaign(**CAMPAIGN)
    set_clock("2026-04-01")
    world["campaign"] = campaign
    world["target"] = add_target(campaign, world["subscriber"]["id"])
    return world


class TestWinBackTargetCycle:

    def test_send_stamps_the_window_and_the_score_reflects_recency_and_reason(self):
        """A target 53 days past lapse scores 0.5003 and its send opens a 14-day window.

        PRD §3.8: "A successful send moves the target from `ELIGIBLE` to `SENT`, sets
        `sent_at` to the clock and `expires_at` to the clock plus the campaign's
        `send_window_days` days, sets the subscriber's `last_contacted_at` to the
        clock, and increments the campaign's `sent_count`."

        Design: Difficulty/non_linear_state_machine/winback_target_cycles_back_to_eligible_and_resends
        """
        world = _voluntarily_lapsed_subscriber_targeted_on_april_first()
        target = world["target"]

        assert_winback_target(target)
        assert target["state"] == "ELIGIBLE"
        assert target["suppression_reason"] == "NONE"
        # 2026-02-07 to 2026-04-01 is 53 whole days.
        assert target["days_since_lapse_at_target"] == 53
        # 0.45 * (3678/20000) + 0.30 * (1 - 53/120) + 0.25 * 1.0 for a PRICE reason.
        assert target["priority_score"] == pytest.approx(0.5003, abs=5e-5)

        sent = send_target(target["id"])
        assert sent["state"] == "SENT"
        assert_instant(sent["sent_at"], "2026-04-01T00:00:00Z", "sent_at")
        assert_instant(sent["expires_at"], "2026-04-15T00:00:00Z", "expires_at")

        subscriber = read_subscriber(world["subscriber"]["id"])
        assert subscriber["churn_type"] == "VOLUNTARY"
        assert_instant(subscriber["lapsed_at"], "2026-02-07T00:00:00Z", "lapsed_at")
        assert_instant(subscriber["last_contacted_at"], "2026-04-01T00:00:00Z",
                       "last_contacted_at")

        assert read_campaign(world["campaign"]["id"])["sent_count"] == 1

    def test_expired_target_returns_to_eligible_only_after_the_suppression_window(self):
        """Expiry keeps sent_at; re-eligibility waits for sent_at plus 60 days.

        PRD §3.8: "A target in `SENT` whose `expires_at` the clock has reached moves
        to `EXPIRED`, and `sent_at` is deliberately left intact so that the contact cap
        keeps counting it. A target in `EXPIRED` moves back to `ELIGIBLE` when the
        clock has reached `sent_at` plus the campaign's `suppression_days` days and no
        suppression predicate holds; `expires_at` is cleared to null and
        `suppression_reason` set to `NONE`, closing the cycle so the target may be sent
        again."

        Design: Difficulty/non_linear_state_machine/winback_target_cycles_back_to_eligible_and_resends
        """
        world = _voluntarily_lapsed_subscriber_targeted_on_april_first()
        target_id = world["target"]["id"]

        send_target(target_id)

        set_clock("2026-04-15")
        expired = reevaluate_target(target_id)
        assert expired["state"] == "EXPIRED"
        assert_instant(expired["sent_at"], "2026-04-01T00:00:00Z", "sent_at")

        # sent_at plus suppression_days is 2026-05-31, so one day earlier nothing moves.
        set_clock("2026-05-30")
        unchanged = reevaluate_target(target_id)
        assert unchanged["state"] == "EXPIRED"
        assert_instant(unchanged["sent_at"], "2026-04-01T00:00:00Z", "sent_at")

        set_clock("2026-05-31")
        reopened = reevaluate_target(target_id)
        assert reopened["state"] == "ELIGIBLE"
        assert reopened["expires_at"] is None
        assert reopened["suppression_reason"] == "NONE"
        assert_instant(reopened["sent_at"], "2026-04-01T00:00:00Z", "sent_at")

        assert read_target(target_id)["state"] == "ELIGIBLE"
