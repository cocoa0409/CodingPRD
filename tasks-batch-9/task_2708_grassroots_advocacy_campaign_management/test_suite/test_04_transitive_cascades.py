"""Cascades where each hop is caused by the hop before it, not by the trigger.

A partner walking out of a coalition ends up moving the campaign's posture five
steps later, and closing a campaign ends up rebasing a legislator's whip count
four steps later. Neither outcome is written into the triggering call.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_count,
    assert_field,
    assert_score,
)
from test_helpers.types import (
    ACTION_VOIDED,
    APPROVAL_BLOCKED,
    CAMPAIGN_CLOSED,
    CHANNEL_EMAIL,
    DELIVERY_ABORTED,
    DELIVERY_SCHEDULED,
    ENDORSEMENT_REVOKED,
    PARTNER_TIER_ANCHOR,
    PARTNER_TIER_CORE,
    PARTNER_WITHDRAWN,
    POSTURE_FROZEN,
    POSTURE_RESTRICTED,
    TIER_MONITOR,
    VARIANT_CHANGES_REQUESTED,
)


# --------------------------------------------------------------------------
# A partner withdrawal, five hops deep
# --------------------------------------------------------------------------

def _two_partner_coalition_with_a_scheduled_wave(api):
    """An anchor and a core partner, the anchor's endorsement holding the lock.

    Two active partners put the endorsement quorum at one, so the anchor's
    single endorsement is the only thing keeping the variant locked, and the
    only thing keeping the scheduled wave approvable.
    """
    world = fx.create_sendable_world(
        api, supporter_count=1, channel=CHANNEL_EMAIL,
        partner_tiers=[PARTNER_TIER_ANCHOR, PARTNER_TIER_CORE])
    activation = fx.add_activation(api, world["campaign_id"], world["segment_id"],
                                   world["variant_id"], channel=CHANNEL_EMAIL,
                                   min_viable_reach=1)
    world["activation_id"] = activation["id"]
    world["anchor_id"] = world["partner_ids"][0]
    world["core_id"] = world["partner_ids"][1]
    return world


def _withdraw_the_anchor(api, world):
    return fx.withdraw_partner(api, world["anchor_id"],
                               withdraw_reason="board vote to exit the coalition")


def test_withdrawal_zeroes_the_leaving_partner_and_re_splits_the_budget(api):
    """Hop zero: the withdrawal itself, with the split re-run behind it.

    PRD: "The partner must currently be `ACTIVE`; its `status` becomes
    `WITHDRAWN`, its `committed_cents` is zeroed, and the funding split re-runs
    over the remaining active partners so that `committed_share_total_cents`
    still equals `funded_total_cents`."

    Design: Difficulty/transitive_cascade/partner_withdrawal_five_hop_cascade_to_blocked_wave_and_posture
    """
    world = _two_partner_coalition_with_a_scheduled_wave(api)

    withdrawn = _withdraw_the_anchor(api, world)

    assert_field(withdrawn, "status", PARTNER_WITHDRAWN)
    assert_cents(withdrawn["committed_cents"], 0)
    assert_cents(fx.read_partner(api, world["core_id"])["committed_cents"], 100000)
    assert_cents(fx.read_campaign(api, world["campaign_id"])
                 ["committed_share_total_cents"], 100000)


def test_the_leaving_partners_endorsement_is_revoked_and_the_tally_falls(api):
    """Hops one and two: the endorsement goes, the variant's tally drops with it.

    PRD: "Second, because those endorsements were revoked, each affected message
    variant has its `endorsement_count` decremented and its
    `required_endorsement_quorum` recomputed against the now-smaller coalition."

    Design: Difficulty/transitive_cascade/partner_withdrawal_five_hop_cascade_to_blocked_wave_and_posture
    """
    world = _two_partner_coalition_with_a_scheduled_wave(api)

    _withdraw_the_anchor(api, world)

    assert_field(fx.read_endorsement(api, world["endorsement_id"]),
                 "status", ENDORSEMENT_REVOKED)
    variant = fx.read_variant(api, world["variant_id"])
    assert_count(variant["endorsement_count"], 0)
    assert_count(variant["required_endorsement_quorum"], 1)


def test_falling_below_quorum_unlocks_the_variant_without_anyone_asking(api):
    """Hop three: the shortfall itself drags the copy back out of lock.

    PRD: "Third, because `endorsement_count` fell below
    `required_endorsement_quorum` on a variant that was `LOCKED`, that variant
    moves from `LOCKED` to `CHANGES_REQUESTED`."

    Design: Difficulty/transitive_cascade/partner_withdrawal_five_hop_cascade_to_blocked_wave_and_posture
    """
    world = _two_partner_coalition_with_a_scheduled_wave(api)

    _withdraw_the_anchor(api, world)

    assert_field(fx.read_variant(api, world["variant_id"]),
                 "status", VARIANT_CHANGES_REQUESTED)


def test_the_unlocked_copy_blocks_its_scheduled_wave_on_the_approval_axis_only(api):
    """Hop four: approval is withdrawn while the delivery axis stays put.

    PRD: "Fourth, because the variant left `LOCKED`, every activation carrying it
    that is still in delivery state `SCHEDULED` has its `approval_state` set to
    `BLOCKED`."

    Design: Difficulty/transitive_cascade/partner_withdrawal_five_hop_cascade_to_blocked_wave_and_posture
    """
    world = _two_partner_coalition_with_a_scheduled_wave(api)

    _withdraw_the_anchor(api, world)

    activation = fx.read_activation(api, world["activation_id"])
    assert_field(activation, "approval_state", APPROVAL_BLOCKED)
    assert_field(activation, "delivery_state", DELIVERY_SCHEDULED)


def test_the_blocked_wave_finally_narrows_the_campaigns_posture(api):
    """Hop five: the posture derivation is the last thing the withdrawal touches.

    PRD: "Fifth, because waves became `BLOCKED`, the campaign's
    `blocked_activation_count` is recomputed and the posture derivation re-runs."

    Design: Difficulty/transitive_cascade/partner_withdrawal_five_hop_cascade_to_blocked_wave_and_posture
    """
    world = _two_partner_coalition_with_a_scheduled_wave(api)

    _withdraw_the_anchor(api, world)

    campaign = fx.read_campaign(api, world["campaign_id"])
    assert_count(campaign["blocked_activation_count"], 1)
    assert_field(campaign, "posture", POSTURE_RESTRICTED)


# --------------------------------------------------------------------------
# A campaign close, four hops deep
# --------------------------------------------------------------------------

def _scheduled_wave_with_one_attributed_action(api):
    """Two reserved supporters and one action credited to the pending wave.

    The wave holds one touch reservation per supporter, and the action logged
    against it is what lifts the district office above its stance-only floor.
    """
    world = fx.create_sendable_world(api, supporter_count=2, channel=CHANNEL_EMAIL)
    activation = fx.add_activation(api, world["campaign_id"], world["segment_id"],
                                   world["variant_id"], channel=CHANNEL_EMAIL,
                                   min_viable_reach=1)
    record = fx.log_action(api, world["supporter_ids"][0], channel=CHANNEL_EMAIL,
                           activation_id=activation["id"])
    world.update({"activation_id": activation["id"], "record_id": record["id"]})
    return world


def test_closing_the_campaign_aborts_the_scheduled_wave_it_still_holds(api):
    """Hop one: the close flushes anything still waiting to send.

    PRD: "On success `status` becomes `CLOSED` and a wide cascade fires."

    Design: Difficulty/transitive_cascade/campaign_close_four_hop_cascade_voids_actions_and_rebases_pressure
    """
    world = _scheduled_wave_with_one_attributed_action(api)

    closed = fx.close_campaign(api, world["campaign_id"])

    assert_field(closed, "status", CAMPAIGN_CLOSED)
    activation = fx.read_activation(api, world["activation_id"])
    assert_field(activation, "delivery_state", DELIVERY_ABORTED)
    assert_field(activation, "abort_reason", "CAMPAIGN_CLOSED")


def test_the_abort_releases_every_touch_reservation_the_wave_was_holding(api):
    """Hop two: leaving the scheduled state is what frees the ledger.

    PRD: "Because those activations left `SCHEDULED`, each supporter listed in
    their `target_supporter_ids` has `touches_reserved` decremented by 1 for each
    aborted activation they appeared in, and `active_activation_count` is
    decremented on each of their segments, bumping those segments' `version`."

    Design: Difficulty/transitive_cascade/campaign_close_four_hop_cascade_voids_actions_and_rebases_pressure
    """
    world = _scheduled_wave_with_one_attributed_action(api)

    fx.close_campaign(api, world["campaign_id"])

    for supporter_id in world["supporter_ids"]:
        assert_count(fx.read_supporter(api, supporter_id)["touches_reserved"], 0)


def test_the_abort_voids_the_action_that_the_wave_had_prompted(api):
    """Hop three: the wave's own attributed rows lose their standing.

    PRD: "Because those activations became `ABORTED`, every action record whose
    `activation_id` names one of them and whose `status` is `RECORDED`, `MATCHED`
    or `ACKNOWLEDGED` becomes `VOIDED`, while records already in `THANKED` are
    preserved."

    Design: Difficulty/transitive_cascade/campaign_close_four_hop_cascade_voids_actions_and_rebases_pressure
    """
    world = _scheduled_wave_with_one_attributed_action(api)

    fx.close_campaign(api, world["campaign_id"])

    assert_field(fx.read_action_record(api, world["record_id"]),
                 "status", ACTION_VOIDED)


def test_the_voided_action_rebases_the_whip_count_to_the_stance_bonus_alone(api):
    """Hop four: pressure is recomputed with the voided row excluded.

    PRD: "Because those action records became `VOIDED`,
    `contact_pressure_score` and `priority_tier` are recomputed for each affected
    legislator."

    Design: Difficulty/transitive_cascade/campaign_close_four_hop_cascade_voids_actions_and_rebases_pressure
    """
    world = _scheduled_wave_with_one_attributed_action(api)

    fx.close_campaign(api, world["campaign_id"])

    legislator = fx.read_legislator(api, world["legislator_id"])
    assert_count(legislator["constituent_action_count"], 0)
    assert_score(legislator["contact_pressure_score"], 10.00)
    assert_field(legislator, "priority_tier", TIER_MONITOR)


def test_the_close_writes_retention_over_the_surviving_rows_and_freezes_the_campaign(api):
    """The final score is written after the voiding, so it sees only what survived.

    PRD: "The campaign-final `retention_score` is then written for every
    supporter of the campaign."

    Design: Difficulty/transitive_cascade/campaign_close_four_hop_cascade_voids_actions_and_rebases_pressure
    """
    world = _scheduled_wave_with_one_attributed_action(api)

    fx.close_campaign(api, world["campaign_id"])

    assert_score(fx.read_supporter(api, world["supporter_ids"][0])["retention_score"],
                 1.00)
    assert_field(fx.read_campaign(api, world["campaign_id"]), "posture",
                 POSTURE_FROZEN)
