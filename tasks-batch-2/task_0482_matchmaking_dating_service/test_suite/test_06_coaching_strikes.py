"""Coaching no-show strikes: suspension boundary and decay over time."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    fixtures as fx,
)

ADMIN = TEST_USERS["billing_admin_headers"]
MATCHMAKER = TEST_USERS["matchmaker_headers"]


def test_coaching_strike_two_does_not_suspend(api):
    """PRD §3.7: "the member's coaching_suspended flag becomes true. ... if the
    resulting count reaches at least 3, the member's coaching_suspended flag becomes
    true. ... Thus, two strikes do not suspend, three do".

    Design: Difficulty/boundary_precision_check/coaching_strike_limit_exactly_3_suspends
    """
    member_id, _ = fx.setup_member_with_no_shows(2, email="a9two@x.com")
    member = validate_success(api.get_member(member_id, MATCHMAKER), 200)
    assert member["no_show_strikes"] == 2, (
        f"two NO_SHOWs => 2 strikes, got {member['no_show_strikes']}"
    )
    assert member["coaching_suspended"] is False, (
        f"two strikes must NOT suspend, got coaching_suspended={member['coaching_suspended']}"
    )


def test_coaching_strike_limit_exactly_3_suspends(api):
    """PRD §3.7: "A `NO_SHOW` outcome moves the session to `NO_SHOW` and increments the member's `no_show_strikes` by one; if the resulting count reaches at least 3, the member's `coaching_suspended` flag becomes true." and "Thus, two strikes do not
    suspend, three do".

    Design: Difficulty/boundary_precision_check/coaching_strike_limit_exactly_3_suspends
    """
    member_id, _ = fx.setup_member_with_no_shows(3, email="a9three@x.com")
    member = validate_success(api.get_member(member_id, MATCHMAKER), 200)
    assert member["no_show_strikes"] == 3, (
        f"three NO_SHOWs => 3 strikes, got {member['no_show_strikes']}"
    )
    assert member["coaching_suspended"] is True, (
        f"three strikes must suspend, got coaching_suspended={member['coaching_suspended']}"
    )


def test_strike_decay_over_clean_window(api):
    """PRD §3.7: "it is the recorded strike count reduced by one for every full 30
    days elapsed since that most recent no-show instant, floored at 0. ... after 30
    clean days one strike decays away."

    Design: Corner/calculations/strike_decay_over_clean_window
    """
    # 3 NO_SHOWs recorded at 2026-06-02; outcome clock then advanced to 2026-07-03
    # (31 days after the last no-show start) -> exactly one strike decays.
    member_id, _ = fx.setup_member_with_no_shows(
        3, outcome_clock="2026-06-02T16:00:00Z", email="ca8@x.com"
    )
    fx.set_clock("2026-07-03T16:00:00Z")
    member = validate_success(api.get_member(member_id, MATCHMAKER), 200)
    assert member["no_show_strikes"] == 2, (
        f"after 31 clean days one strike decays: 3-1=2, got {member['no_show_strikes']}"
    )
    assert member["coaching_suspended"] is False, (
        f"2 effective strikes must not suspend, got {member['coaching_suspended']}"
    )
