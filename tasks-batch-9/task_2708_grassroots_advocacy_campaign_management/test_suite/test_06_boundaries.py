"""Thresholds that land exactly on the boundary, and divisions that do not.

Sixty is inclusive, so the action that lands a whip count on exactly 60.00 must
promote the office. Cents floor while basis points round half up, so one
completion response carries two different rounding rules at once.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_bps,
    assert_cents,
    assert_count,
    assert_field,
    assert_score,
)
from test_helpers.types import (
    CHANNEL_EMAIL,
    CHANNEL_PHONE,
    DELIVERY_SENT,
    LAWFUL_BASIS_VERBAL_RECORDED,
    MILESTONE_FLOOR_VOTE,
    POSTURE_OPEN,
    TIER_PRIMARY,
    TIER_SECONDARY,
)


# --------------------------------------------------------------------------
# The primary-tier threshold of 60.00
# --------------------------------------------------------------------------

def _whip_count_parked_two_points_below_primary(api):
    """Four floor-vote phone calls, leaving the office on exactly 58.00.

    The clock is then moved clear of every milestone window, so the next action
    logged is stamped with the bare multiplier rather than the floor-vote one.
    """
    world = fx.create_active_campaign(api, legislator_overrides={
        "full_name": "Rep. Cruz"})
    fx.add_milestone(api, world["campaign_id"],
                     "2026-08-04T00:00:00Z", "2026-08-06T00:00:00Z",
                     kind=MILESTONE_FLOOR_VOTE, label="House floor vote")
    supporter = fx.add_supporter(
        api, world["campaign_id"], channels=[CHANNEL_EMAIL, CHANNEL_PHONE],
        full_name="Cal Caller", email="cal@example.org", phone="+15551230011",
        lawful_basis=LAWFUL_BASIS_VERBAL_RECORDED,
        consent_source_reference="phonebank-3")
    fx.park_clock(api, "2026-08-05T00:00:00Z")
    fx.log_actions(api, supporter["id"], 4, channel=CHANNEL_PHONE)
    fx.park_clock(api, "2026-08-07T00:00:00Z")
    world["supporter_id"] = supporter["id"]
    return world


def test_four_floor_vote_calls_leave_the_office_at_fifty_eight_and_secondary(api):
    """The starting point of the boundary: one step below promotion.

    PRD: "Remove the `EMAIL` action and the score is 58.00, which is `SECONDARY`."

    Design: Difficulty/boundary_precision_check/pressure_tier_promotes_at_exactly_sixty_inclusive
    """
    world = _whip_count_parked_two_points_below_primary(api)

    legislator = fx.read_legislator(api, world["legislator_id"])
    assert_score(legislator["contact_pressure_score"], 58.00)
    assert_field(legislator, "priority_tier", TIER_SECONDARY)


def test_an_action_logged_outside_every_window_is_stamped_with_the_bare_multiplier(api):
    """The fifth action is stamped 1.0 because no window contains the clock.

    PRD: "If that set is empty, the record's `pressure_multiplier` is 1.0."

    Design: Difficulty/boundary_precision_check/pressure_tier_promotes_at_exactly_sixty_inclusive
    """
    world = _whip_count_parked_two_points_below_primary(api)

    record = fx.log_action(api, world["supporter_id"], channel=CHANNEL_EMAIL)

    assert_score(record["pressure_multiplier"], 1.0)


def test_landing_on_exactly_sixty_promotes_the_office_to_primary(api):
    """Sixty is inclusive, so the boundary itself is a promotion.

    PRD: "Worked through: a legislator whose `stance` is `UNDECIDED` with four `PHONE` actions each stamped with a `FLOOR_VOTE` multiplier of 2.0 and one `EMAIL` action stamped 1.0 has a weighted sum of 25.0, an action component of 50.0 (below the 60.0 cap), no meeting component, and a stance bonus of 10.0 — a score of exactly 60.00, which lands on `PRIMARY`."

    Design: Difficulty/boundary_precision_check/pressure_tier_promotes_at_exactly_sixty_inclusive
    """
    world = _whip_count_parked_two_points_below_primary(api)

    fx.log_action(api, world["supporter_id"], channel=CHANNEL_EMAIL)

    legislator = fx.read_legislator(api, world["legislator_id"])
    assert_score(legislator["contact_pressure_score"], 60.00)
    assert_field(legislator, "priority_tier", TIER_PRIMARY)
    assert_count(legislator["constituent_action_count"], 5)


def test_a_promotion_on_a_persuadable_office_leaves_the_posture_open(api):
    """An undecided office reaching PRIMARY is not an opposed priority office.

    PRD: "`opposed_priority_legislator_count` is the number of the campaign's legislators whose `priority_tier` is `PRIMARY` **and** whose `stance` is either `LEAN_OPPOSE` or `OPPOSE`."

    Design: Difficulty/boundary_precision_check/pressure_tier_promotes_at_exactly_sixty_inclusive
    """
    world = _whip_count_parked_two_points_below_primary(api)

    fx.log_action(api, world["supporter_id"], channel=CHANNEL_EMAIL)

    campaign = fx.read_campaign(api, world["campaign_id"])
    assert_count(campaign["opposed_priority_legislator_count"], 0)
    assert_field(campaign, "posture", POSTURE_OPEN)


# --------------------------------------------------------------------------
# Cents floor while basis points round
# --------------------------------------------------------------------------

def _sending_wave_with_four_attributed_actions(api):
    """Three targeted supporters mid-flight, four actions credited to the wave.

    Two of the four actions come from the same supporter, so the attributed
    action count exceeds the reach and the cost division comes out fractional.
    """
    world = fx.create_sendable_world(api, supporter_count=3, channel=CHANNEL_EMAIL)
    sending = fx.create_sending_wave(api, world["campaign_id"],
                                     world["segment_id"], world["variant_id"])
    activation_id = sending["id"]
    supporter_ids = world["supporter_ids"]
    fx.log_action(api, supporter_ids[0], channel=CHANNEL_EMAIL,
                  activation_id=activation_id)
    fx.log_action(api, supporter_ids[0], channel=CHANNEL_EMAIL,
                  activation_id=activation_id)
    fx.log_action(api, supporter_ids[1], channel=CHANNEL_EMAIL,
                  activation_id=activation_id)
    fx.log_action(api, supporter_ids[2], channel=CHANNEL_EMAIL,
                  activation_id=activation_id)
    world["activation_id"] = activation_id
    return world


def test_completion_bills_two_cents_a_head_for_three_delivered_emails(api):
    """The cost side of the division: 3 delivered emails at 2 cents each.

    PRD: "`send_cost_cents` is the channel's unit cost multiplied by `delivered_count`, where the unit cost is 2 cents for `EMAIL`, 15 cents for `SMS` and 60 cents for `PHONE` — note that the vendor bills for what it delivered, not for what was lawful, so cost uses `delivered_count` while reach does not."

    Design: Difficulty/boundary_precision_check/cost_per_action_floors_instead_of_rounding_at_one_cent
    """
    world = _sending_wave_with_four_attributed_actions(api)

    completed = fx.complete_activation(api, world["activation_id"], 3)

    assert_field(completed, "delivery_state", DELIVERY_SENT)
    assert_count(completed["realized_reach"], 3)
    assert_cents(completed["send_cost_cents"], 6)


def test_cost_per_action_floors_one_and_a_half_cents_down_to_one(api):
    """Six cents over four actions is 1, not 2: the fraction is discarded.

    PRD: "`cost_per_action_cents` is the sentinel value 999999 when `attributed_action_count` is 0; otherwise it is `send_cost_total_cents` divided by `attributed_action_count` with any fraction discarded — floored, never rounded."

    Design: Difficulty/boundary_precision_check/cost_per_action_floors_instead_of_rounding_at_one_cent
    """
    world = _sending_wave_with_four_attributed_actions(api)

    fx.complete_activation(api, world["activation_id"], 3)

    variant = fx.read_variant(api, world["variant_id"])
    assert_count(variant["realized_reach_total"], 3)
    assert_cents(variant["send_cost_total_cents"], 6)
    assert_count(variant["attributed_action_count"], 4)
    assert_cents(variant["cost_per_action_cents"], 1)


def test_response_rate_rounds_half_up_on_the_same_response_that_floored(api):
    """Four over three in basis points rounds up, while the cents floored.

    PRD: "`response_rate_bps` is 0 when `realized_reach_total` is 0; otherwise it is `attributed_action_count` multiplied by 10,000, divided by `realized_reach_total`, and rounded half up to a whole number of basis points."

    Design: Difficulty/boundary_precision_check/cost_per_action_floors_instead_of_rounding_at_one_cent
    """
    world = _sending_wave_with_four_attributed_actions(api)

    fx.complete_activation(api, world["activation_id"], 3)

    assert_bps(fx.read_variant(api, world["variant_id"])["response_rate_bps"],
               13333)
