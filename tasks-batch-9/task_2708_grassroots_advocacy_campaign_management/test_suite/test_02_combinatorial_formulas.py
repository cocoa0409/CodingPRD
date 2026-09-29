"""Two formulas whose several inputs interact rather than simply adding up.

The district pressure index folds five inputs through two nested caps and a
branch on stance, so its ceiling is load-bearing rather than decorative. The
coalition funding split has a pinned order of operations — floor each line, then
walk the leftover cents one at a time — because the plausible alternatives give
different answers.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_count,
    assert_field,
    assert_score,
)
from test_helpers.types import (
    ACTION_MATCHED,
    CHANNEL_PHONE,
    MILESTONE_FLOOR_VOTE,
    PARTNER_TIER_ALLY,
    PARTNER_TIER_ANCHOR,
    PARTNER_TIER_CORE,
    POSTURE_RESTRICTED,
    STANCE_LEAN_OPPOSE,
    TIER_PRIMARY,
)


# --------------------------------------------------------------------------
# The pressure index: nested caps and the stance branch
# --------------------------------------------------------------------------

def _legislator_already_clamped_at_the_action_cap(api):
    """A lean-oppose legislator whose five floor-vote phone actions max the cap.

    Five phone actions each stamped with a floor-vote multiplier weigh 30.0,
    which doubles past the action cap, so the action component is already
    pinned at its ceiling before the sixth action is logged.
    """
    world = fx.create_active_campaign(
        api,
        legislator_overrides={"full_name": "Rep. Bell",
                              "stance": STANCE_LEAN_OPPOSE})
    milestone = fx.add_milestone(api, world["campaign_id"],
                                 "2026-08-04T00:00:00Z", "2026-08-06T00:00:00Z",
                                 kind=MILESTONE_FLOOR_VOTE,
                                 label="House floor vote")
    supporter = fx.add_supporter(
        api, world["campaign_id"], channels=[CHANNEL_PHONE],
        full_name="Cal Caller", email="cal@example.org",
        phone="+15551230011", lawful_basis="VERBAL_RECORDED",
        consent_source_reference="phonebank-3")

    fx.park_clock(api, "2026-08-05T00:00:00Z")
    fx.log_actions(api, supporter["id"], 5, channel=CHANNEL_PHONE)

    world.update({
        "milestone_id": milestone["id"],
        "supporter_id": supporter["id"],
    })
    return world


def test_a_sixth_phone_action_raises_the_count_but_leaves_the_score_at_its_cap(api):
    """The action component is clamped, so more contacts stop moving the score.

    PRD: "Multiply that sum by the action pressure factor of 2.0, and take the
    lesser of the result and the action cap of 60.0; that is the action
    component."

    Design: Difficulty/combinatorial_formula/pressure_index_mode_a_nested_caps_clamp_and_stance_branch
    """
    world = _legislator_already_clamped_at_the_action_cap(api)

    fx.log_action(api, world["supporter_id"], channel=CHANNEL_PHONE)

    legislator = fx.read_legislator(api, world["legislator_id"])
    assert_count(legislator["constituent_action_count"], 6)
    assert_score(legislator["contact_pressure_score"], 64.00)


def test_the_lean_oppose_stance_bonus_is_the_only_thing_lifting_the_score_above_the_cap(api):
    """Four points of stance bonus sit on top of the clamped action component.

    PRD: "Add a stance bonus determined by the legislator's current `stance`:
    0.0 for `SUPPORT`, 10.0 for `LEAN_SUPPORT`, 10.0 for `UNDECIDED`, 4.0 for
    `LEAN_OPPOSE` and 0.0 for `OPPOSE` — the bonus is highest for the
    persuadable middle, which is exactly where a campaign should spend
    pressure."

    Design: Difficulty/combinatorial_formula/pressure_index_mode_a_nested_caps_clamp_and_stance_branch
    """
    world = _legislator_already_clamped_at_the_action_cap(api)

    fx.log_action(api, world["supporter_id"], channel=CHANNEL_PHONE)

    legislator = fx.read_legislator(api, world["legislator_id"])
    assert_score(legislator["contact_pressure_score"], 64.00)
    assert_field(legislator, "stance", STANCE_LEAN_OPPOSE)
    assert_field(legislator, "priority_tier", TIER_PRIMARY)


def test_the_new_action_carries_the_floor_vote_multiplier_and_matches_its_own_office(api):
    """The multiplier is stamped from the window containing the clock.

    PRD: "Otherwise the strongest window wins: sort the containing milestones by
    `pressure_multiplier` descending and then by `created_at` ascending, and take
    the first one's `pressure_multiplier` — 1.5 inside a `COMMITTEE_HEARING`, 2.0
    inside a `FLOOR_VOTE`, 0.5 inside a `RECESS`, 1.0 inside a `SIGNING`."

    Design: Difficulty/combinatorial_formula/pressure_index_mode_a_nested_caps_clamp_and_stance_branch
    """
    world = _legislator_already_clamped_at_the_action_cap(api)

    sixth = fx.log_action(api, world["supporter_id"], channel=CHANNEL_PHONE)

    assert_field(sixth, "status", ACTION_MATCHED)
    assert_field(sixth, "legislator_id", world["legislator_id"])
    assert sixth["pressure_multiplier"] == 2.0, (
        f"expected a floor-vote multiplier of 2.0, got {sixth['pressure_multiplier']}")


def test_a_primary_tier_legislator_leaning_against_the_bill_narrows_the_campaign(api):
    """One opposed primary office is enough to restrict the campaign's posture.

    PRD: "Otherwise, if `blocked_activation_count` is at least 1 or
    `opposed_priority_legislator_count` is at least 1, the posture is
    `RESTRICTED`."

    Design: Difficulty/combinatorial_formula/pressure_index_mode_a_nested_caps_clamp_and_stance_branch
    """
    world = _legislator_already_clamped_at_the_action_cap(api)

    fx.log_action(api, world["supporter_id"], channel=CHANNEL_PHONE)

    campaign = fx.read_campaign(api, world["campaign_id"])
    assert_count(campaign["opposed_priority_legislator_count"], 1)
    assert_field(campaign, "posture", POSTURE_RESTRICTED)


# --------------------------------------------------------------------------
# The coalition split: floor each line, then waterfall the leftover
# --------------------------------------------------------------------------

def _coalition_of_anchor_and_core(api):
    """A hundred-thousand-cent budget split across two partners so far."""
    world = fx.create_active_campaign(api)
    anchor = fx.add_partner(api, world["campaign_id"], tier=PARTNER_TIER_ANCHOR,
                            org_name="Anchor Housing Alliance",
                            branding_asset_ref="brand/anchor.svg")
    core = fx.add_partner(api, world["campaign_id"], tier=PARTNER_TIER_CORE,
                          org_name="Core Tenants Union",
                          branding_asset_ref="brand/core.svg")
    world.update({"anchor_id": anchor["id"], "core_id": core["id"]})
    return world


def test_the_three_tiers_carry_their_published_share_weights(api):
    """Weight is a pure function of tier, and admitting a partner re-splits.

    PRD: "Adding or removing a partner re-splits the whole budget, and the
    **order of operations in that split is pinned** because two plausible orders
    give different answers."

    Design: Difficulty/combinatorial_formula/coalition_share_mode_b_floor_then_single_cent_waterfall
    """
    world = _coalition_of_anchor_and_core(api)

    ally = fx.add_partner(api, world["campaign_id"], tier=PARTNER_TIER_ALLY,
                          org_name="Ally Faith Network",
                          branding_asset_ref="brand/ally.svg")

    assert_count(fx.read_partner(api, world["anchor_id"])["share_weight"], 5)
    assert_count(fx.read_partner(api, world["core_id"])["share_weight"], 3)
    assert_count(ally["share_weight"], 1)


def test_the_single_leftover_cent_goes_to_the_heaviest_share_not_to_rounding(api):
    """Each line floors, then the one remaining cent walks to the anchor.

    PRD: "Worked through: with `funded_total_cents` of 100,000 split across one
    `ANCHOR`, one `CORE` and one `ALLY`, the floored lines are 55,555 plus
    33,333 plus 11,111, totalling 99,999; the single leftover cent goes to the
    `ANCHOR` because it holds the highest `share_weight`, giving 55,556, 33,333
    and 11,111."

    Design: Difficulty/combinatorial_formula/coalition_share_mode_b_floor_then_single_cent_waterfall
    """
    world = _coalition_of_anchor_and_core(api)

    ally = fx.add_partner(api, world["campaign_id"], tier=PARTNER_TIER_ALLY,
                          org_name="Ally Faith Network",
                          branding_asset_ref="brand/ally.svg")

    assert_cents(fx.read_partner(api, world["anchor_id"])["committed_cents"], 55556)
    assert_cents(fx.read_partner(api, world["core_id"])["committed_cents"], 33333)
    assert_cents(ally["committed_cents"], 11111)


def test_the_committed_total_still_reconciles_exactly_with_the_funded_budget(api):
    """Conservation is the point of pinning the order: nothing is created or lost.

    PRD: "The campaign's `committed_share_total_cents` is then the sum of all
    active partners' `committed_cents`, and any partner whose `status` is
    `WITHDRAWN` has `committed_cents` forced to 0."

    Design: Difficulty/combinatorial_formula/coalition_share_mode_b_floor_then_single_cent_waterfall
    """
    world = _coalition_of_anchor_and_core(api)

    fx.add_partner(api, world["campaign_id"], tier=PARTNER_TIER_ALLY,
                   org_name="Ally Faith Network",
                   branding_asset_ref="brand/ally.svg")

    campaign = fx.read_campaign(api, world["campaign_id"])
    assert_cents(campaign["committed_share_total_cents"], 100000)
    assert_cents(campaign["funded_total_cents"], 100000)
