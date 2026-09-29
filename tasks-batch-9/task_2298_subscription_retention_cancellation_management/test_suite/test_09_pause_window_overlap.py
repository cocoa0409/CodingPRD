"""Half-open pause windows: true overlap is refused, exact adjacency is allowed.

One pause is already applied over [2026-01-10, 2026-02-07).  A second window starting
inside it is rejected, while a window starting exactly on its excluded upper bound is
accepted — and because the rejection changes nothing, the version the client already
held is still good for the second attempt.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant,
    assert_price_conserved,
    create_modification_payload,
    instant,
    modifications_for,
    pause_subscription,
    read_subscription,
    setup_active_subscription,
    validate_error,
    validate_success,
)


def _subscription_with_one_applied_pause():
    """Pause [2026-01-10, 2026-02-07) applied immediately; one cycle of a three-cycle budget."""
    world = setup_active_subscription(
        clock="2026-01-10",
        subscriber_overrides={"acquisition_channel": "REFERRAL"},
    )
    world["first_pause"] = pause_subscription(world, "2026-01-10", "2026-02-07")
    world["version_after_pause"] = read_subscription(world["subscription"]["id"])["version"]
    return world


def _pause_payload(expected_version, start, end):
    return create_modification_payload(
        "PAUSE", expected_version,
        pause_start_at=instant(start), pause_end_at=instant(end), effective_at=instant(start))


class TestPauseWindowOverlap:

    def test_a_window_starting_inside_the_applied_pause_is_rejected(self):
        """[2026-02-01, 2026-02-28) overlaps [2026-01-10, 2026-02-07) and changes nothing.

        PRD §3.3: "The requested window may not overlap the window of any existing
        pause modification whose `state` is `APPLIED` or `SCHEDULED`; because the
        semantics are half-open, a new window that starts exactly where a prior window
        ended is permitted, while any true overlap is rejected with
        `ERR_PAUSE_WINDOW_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/pause_windows_reject_overlap_but_allow_adjacency
        """
        world = _subscription_with_one_applied_pause()
        assert world["first_pause"]["state"] == "APPLIED"

        response = api_client.create_modification(
            world["subscription"]["id"],
            _pause_payload(world["version_after_pause"], "2026-02-01", "2026-02-28"),
            world["subscriber_headers"])
        validate_error(response, ApiErrorId.ERR_PAUSE_WINDOW_OVERLAP, 409)

        subscription = read_subscription(world["subscription"]["id"])
        assert subscription["version"] == world["version_after_pause"]
        assert subscription["lifecycle_state"] == "PAUSED"
        assert subscription["pause_cycles_used"] == 1
        assert len(modifications_for(subscription["id"])) == 1

    def test_a_window_starting_on_the_excluded_upper_bound_is_accepted_as_scheduled(self):
        """[2026-02-07, 2026-03-07) is adjacent, not overlapping, and defers its effect.

        PRD §3.3: "A row that settles into `SCHEDULED` mutates nothing on the
        subscription except its `version`." and PRD §2.9: "Rows in `SCHEDULED` or
        `CANCELLED` are excluded from that sum and always carry `delta_price_cents` of
        0."

        Design: Difficulty/resource_temporal_overlap/pause_windows_reject_overlap_but_allow_adjacency
        """
        world = _subscription_with_one_applied_pause()

        # The rejected attempt above left the version untouched, so the same expected
        # version is still current here.
        api_client.create_modification(
            world["subscription"]["id"],
            _pause_payload(world["version_after_pause"], "2026-02-01", "2026-02-28"),
            world["subscriber_headers"])

        response = api_client.create_modification(
            world["subscription"]["id"],
            _pause_payload(world["version_after_pause"], "2026-02-07", "2026-03-07"),
            world["subscriber_headers"])
        adjacent = validate_success(response, 201)

        assert adjacent["mod_type"] == "PAUSE"
        assert adjacent["state"] == "SCHEDULED"
        assert adjacent["delta_price_cents"] == 0
        assert adjacent["applied_at"] is None
        assert_instant(adjacent["pause_start_at"], "2026-02-07T00:00:00Z", "pause_start_at")

        subscription = read_subscription(world["subscription"]["id"])
        # The applied pause still owns the lifecycle axis and the cycle budget.
        assert subscription["lifecycle_state"] == "PAUSED"
        assert_instant(subscription["paused_until"], "2026-02-07T00:00:00Z", "paused_until")
        assert subscription["pause_cycles_used"] == 1
        assert_price_conserved(subscription, modifications_for(subscription["id"]))
