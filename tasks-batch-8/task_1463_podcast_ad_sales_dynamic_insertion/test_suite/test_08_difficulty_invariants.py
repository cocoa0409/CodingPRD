"""Difficulty queue A — compensating_invariant (2 instances, 4 tests)."""

from test_helpers import (
    add_line_item,
    get_episode,
    get_show,
    setup_selling_scenario,
    transition_line_item,
)


def _setup_pool_invariant():
    """Show avg 10000 with one episode in horizon (forecast 9500); ACTIVE
    campaign; DRAFT run-of-show line item reserving 4000."""
    ctx = setup_selling_scenario(
        advertiser_name="PoolCo", category="AUTOMOTIVE", content_category="NEWS",
        show_avg=10000, booked_impressions=4000, cpm_cents=1000,
        episode_publish_at="2026-08-05T00:00:00Z",
    )
    ctx["line_item"] = add_line_item(ctx, target="show", position="MID_ROLL",
                                     reserved_impressions=4000, priority=10,
                                     activate=False)
    return ctx


def _setup_slot_invariant():
    """Episode slot_capacity 2 (publish 2026-08-01, clock inside the flight);
    ACTIVE campaign; DRAFT episode-targeted line item."""
    ctx = setup_selling_scenario(
        advertiser_name="SlotCo", category="TECHNOLOGY", content_category="SPORTS",
        show_avg=10000, booked_impressions=10, cpm_cents=1000,
        episode_publish_at="2026-08-01T00:00:00Z",
        episode_overrides={"measurement_window_days": 30, "slot_capacity": 2},
    )
    ctx["line_item"] = add_line_item(ctx, target="episode", position="MID_ROLL",
                                     reserved_impressions=10, priority=10,
                                     activate=False)
    return ctx


# =========================================================================
# show_impression_pool_reserve_release_invariant
# =========================================================================

def test_activate_debits_reserved_and_available_conserves_forecast(api):
    """PRD §3.4: "A successful activation debits the pool it sells against: a run-of-show item adds its `reserved_impressions` to the show's `reserved_impressions` and recomputes `available_impressions`"
    PRD §3.1: "`reserved_impressions` is the sum of `reserved_impressions` over the show's `ACTIVE` run-of-show line items, and `available_impressions` is the difference"

    Design: Difficulty/compensating_invariant/show_impression_pool_reserve_release_invariant
    """
    ctx = _setup_pool_invariant()
    show = get_show(ctx["show"]["id"])
    assert show["forecast_impressions"] == 9500
    assert show["reserved_impressions"] == 0
    assert show["available_impressions"] == 9500
    transition_line_item(ctx["line_item"]["id"], "ACTIVATE")
    show = get_show(ctx["show"]["id"])
    assert show["reserved_impressions"] == 4000
    assert show["available_impressions"] == 5500
    assert show["reserved_impressions"] + show["available_impressions"] == 9500


def test_pause_releases_reservation_restoring_the_conserved_total(api):
    """PRD §3.4: "Pausing an `ACTIVE` line item — manually by `AdOps`, or by the system when its show is suspended, its advertiser is suspended, or its ad copy is revoked — releases what it holds: a run-of-show item subtracts its `reserved_impressions` back out of the show's `reserved_impressions` and recomputes `available_impressions`, and an episode-targeted item's `slots_in_use` is recomputed."

    Design: Difficulty/compensating_invariant/show_impression_pool_reserve_release_invariant
    """
    ctx = _setup_pool_invariant()
    transition_line_item(ctx["line_item"]["id"], "ACTIVATE")
    show = get_show(ctx["show"]["id"])
    assert show["reserved_impressions"] == 4000
    transition_line_item(ctx["line_item"]["id"], "PAUSE")
    show = get_show(ctx["show"]["id"])
    assert show["reserved_impressions"] == 0, (
        f"Compensating PAUSE must release the reservation, got "
        f"{show['reserved_impressions']}"
    )
    assert show["available_impressions"] == 9500
    assert show["reserved_impressions"] + show["available_impressions"] == 9500


# =========================================================================
# episode_slot_occupancy_activate_end_invariant
# =========================================================================

def test_episode_activate_occupies_one_slot(api):
    """PRD §3.4: "an episode-targeted item triggers recomputation of the episode's `slots_in_use`, defined as the count of `ACTIVE` episode-targeted line items whose campaign flight contains the current logical-clock instant (`slots_free`, the capacity minus that count, is what remains sellable)."

    Design: Difficulty/compensating_invariant/episode_slot_occupancy_activate_end_invariant
    """
    ctx = _setup_slot_invariant()
    episode = get_episode(ctx["episode"]["id"])
    assert episode["slot_capacity"] == 2
    assert episode["slots_in_use"] == 0
    transition_line_item(ctx["line_item"]["id"], "ACTIVATE")
    episode = get_episode(ctx["episode"]["id"])
    assert episode["slots_in_use"] == 1, (
        f"Activation must occupy one slot, got {episode['slots_in_use']}"
    )


def test_episode_end_releases_the_slot(api):
    """PRD §3.4: "Ending a line item — from `ACTIVE` or `PAUSED`, manually or because the campaign ended — moves it to terminal `ENDED` and releases the reservation or slot exactly as a pause does."

    Design: Difficulty/compensating_invariant/episode_slot_occupancy_activate_end_invariant
    """
    ctx = _setup_slot_invariant()
    transition_line_item(ctx["line_item"]["id"], "ACTIVATE")
    assert get_episode(ctx["episode"]["id"])["slots_in_use"] == 1
    transition_line_item(ctx["line_item"]["id"], "END")
    episode = get_episode(ctx["episode"]["id"])
    assert episode["slots_in_use"] == 0, (
        f"Compensating END must release the slot, got {episode['slots_in_use']}"
    )
