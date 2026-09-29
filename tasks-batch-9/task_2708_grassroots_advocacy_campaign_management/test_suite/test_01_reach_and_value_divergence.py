"""Two calculations that answer the same question twice and disagree on purpose.

A send wave states reach twice — forward-looking at scheduling time and
chronological at completion — and a supporter carries value twice, as a rolling
engagement score and as a campaign-final retention score. Both pairs are
supposed to diverge over identical rows.
"""

import pytest

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_count,
    assert_field,
    assert_score,
)
from test_helpers.types import (
    ACTION_ACKNOWLEDGED,
    ACTION_MATCHED,
    CAMPAIGN_CLOSED,
    CHANNEL_EMAIL,
    CHANNEL_PHONE,
    CONSENT_REVOKED,
    DELIVERY_SENT,
    DISPUTE_OUTCOME_REINSTATED,
    POSTURE_FROZEN,
)


# --------------------------------------------------------------------------
# Activation: projected reach against realized reach
# --------------------------------------------------------------------------

def _wave_sending_with_a_mid_flight_revocation(api):
    """Four EMAIL supporters, a wave under way, one supporter opting out.

    The wave is scheduled over a segment holding all four supporters and is
    already delivering when supporter two revokes EMAIL consent, so the two
    reach figures are forced apart before the vendor tally lands.
    """
    world = fx.create_sendable_world(api, supporter_count=4, channel=CHANNEL_EMAIL)
    activation = fx.add_activation(api, world["campaign_id"], world["segment_id"],
                                   world["variant_id"], channel=CHANNEL_EMAIL,
                                   min_viable_reach=1)
    fx.clear_activation(api, activation["id"])
    fx.park_clock(api, "2026-08-05T10:00:00Z")
    fx.start_send(api, activation["id"])
    fx.revoke_consent(api, world["supporter_ids"][1], CHANNEL_EMAIL,
                      source_reference="unsubscribe-link-2")
    world["activation_id"] = activation["id"]
    world["projected_at_create"] = activation["projected_reach"]
    return world


def test_realized_reach_drops_the_supporter_who_revoked_while_the_wave_was_in_flight(api):
    """Completion recounts consent, so realized reach lands one below projected.

    PRD: "Identical wave data therefore yields a `projected_reach` of 4 and a
    `realized_reach` of 3 when one targeted supporter revokes the channel
    between send start and completion."

    Design: Difficulty/dual_variant_calc/activation_projected_versus_realized_reach_diverge
    """
    world = _wave_sending_with_a_mid_flight_revocation(api)

    completed = fx.complete_activation(api, world["activation_id"],
                                       delivered_count=4, bounced_count=0)

    assert_count(completed["projected_reach"], 4)
    assert_count(completed["realized_reach"], 3)
    assert_field(completed, "delivery_state", DELIVERY_SENT)


def test_the_gap_between_delivered_and_lawful_touches_is_reported_as_suppressed_by_consent(api):
    """The arithmetic difference of the two figures is published in its own field.

    PRD: "The difference between `delivered_count` and `realized_reach` is
    written to `suppressed_by_consent_count`."

    Design: Difficulty/dual_variant_calc/activation_projected_versus_realized_reach_diverge
    """
    world = _wave_sending_with_a_mid_flight_revocation(api)

    completed = fx.complete_activation(api, world["activation_id"],
                                       delivered_count=4, bounced_count=0)

    assert_count(completed["suppressed_by_consent_count"], 1)

    revoker = fx.read_supporter(api, world["supporter_ids"][1])
    assert_field(revoker, "email_consent_state", CONSENT_REVOKED)
    assert_field(revoker, "suppressed", False)


def test_send_cost_bills_every_delivered_touch_even_the_one_that_stopped_being_lawful(api):
    """Cost follows the vendor's delivered tally while reach follows consent.

    PRD: "`send_cost_cents` is the channel's unit cost multiplied by
    `delivered_count`, where the unit cost is 2 cents for `EMAIL`, 15 cents for
    `SMS` and 60 cents for `PHONE` — note that the vendor bills for what it
    delivered, not for what was lawful, so cost uses `delivered_count` while
    reach does not."

    Design: Difficulty/dual_variant_calc/activation_projected_versus_realized_reach_diverge
    """
    world = _wave_sending_with_a_mid_flight_revocation(api)

    completed = fx.complete_activation(api, world["activation_id"],
                                       delivered_count=4, bounced_count=0)

    assert_cents(completed["send_cost_cents"], 8)


def test_the_variant_rollup_sums_the_lawful_reach_and_the_billed_cost_separately(api):
    """The carrying variant's totals inherit the divergence, field by field.

    PRD: "`realized_reach_total` is the sum of those waves' `realized_reach`."

    Design: Difficulty/dual_variant_calc/activation_projected_versus_realized_reach_diverge
    """
    world = _wave_sending_with_a_mid_flight_revocation(api)

    fx.complete_activation(api, world["activation_id"],
                           delivered_count=4, bounced_count=0)

    variant = fx.read_variant(api, world["variant_id"])
    assert_count(variant["realized_reach_total"], 3)
    assert_cents(variant["send_cost_total_cents"], 8)


# --------------------------------------------------------------------------
# Supporter: rolling engagement against campaign-final retention
# --------------------------------------------------------------------------

def _supporter_with_two_forty_six_day_old_actions(api):
    """One event-sourced supporter whose only two actions have aged 46 days.

    The two actions are logged while the clock sits at the campaign's opening
    instant, then the clock jumps 46 days so that both fall in the oldest decay
    bucket, and the phone action is acknowledged at the later clock.

    Moving the clock does not by itself re-score the supporter: the PRD says a
    clock call changes "the decay bucket that the rolling engagement variant of
    supporter scoring will use on its next evaluation", so the fixture also
    drives a declared evaluation trigger at the later clock. Disputing the email
    action and resolving that dispute `REINSTATED` is the trigger that leaves the
    counted rows exactly as they were -- "the supporter's `action_count`,
    `engagement_score` and `retention_score` are recomputed" on both edges, and
    the record returns to `MATCHED`.
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(
        api, world["campaign_id"],
        channels=[CHANNEL_EMAIL, CHANNEL_PHONE],
        full_name="Eva Storyteller", email="eva@example.org",
        phone="+15551230001", acquisition_source="EVENT",
        lawful_basis="EVENT_CARD", consent_source_reference="event-signin-7")
    phone_record = fx.log_action(api, supporter["id"], channel=CHANNEL_PHONE)
    email_record = fx.log_action(api, supporter["id"], channel=CHANNEL_EMAIL)

    fx.park_clock(api, "2026-09-16T00:00:00Z")
    fx.acknowledge_action(api, phone_record["id"],
                          acknowledgement_note="office confirmed receipt")
    fx.dispute_action(api, email_record["id"],
                      dispute_reason="supporter asked us to double-check it")
    fx.resolve_dispute(api, email_record["id"], DISPUTE_OUTCOME_REINSTATED,
                       resolution_note="the contact log confirms the email")

    world.update({
        "supporter_id": supporter["id"],
        "phone_record_id": phone_record["id"],
        "email_record_id": email_record["id"],
    })
    return world


def test_the_rolling_engagement_score_halves_the_weight_of_forty_six_day_old_actions(api):
    """Age decay is what makes the rolling variant read lower than the final one.

    PRD: "Worked through against the rolling variant: an `EVENT`-sourced
    supporter with one `PHONE` action and one `EMAIL` action, both aged 46 days,
    with no story training, no thank-yous and no meetings, has an
    `engagement_score` of 2.0 plus 3.0 times 0.50 plus 1.0 times 0.50, which is
    4.00, while their `retention_score` is 2.0 plus 3.0 plus 1.0, which is 6.00."

    Design: Difficulty/dual_variant_calc/supporter_engagement_versus_retention_score_diverge
    """
    world = _supporter_with_two_forty_six_day_old_actions(api)

    fx.close_campaign(api, world["campaign_id"])

    supporter = fx.read_supporter(api, world["supporter_id"])
    assert_score(supporter["engagement_score"], 4.00)


def test_the_campaign_final_retention_score_drops_decay_over_the_very_same_rows(api):
    """Retention counts every action at full weight however old it is.

    PRD: "Then, for each of that supporter's action records whose `status` is
    `MATCHED`, `ACKNOWLEDGED` or `THANKED`, add the channel pressure weight of
    that record's `channel` — 1.0 for `EMAIL`, 1.5 for `SMS`, 3.0 for `PHONE` —
    with **no** age decay at all: every action counts at full weight regardless
    of how old it is."

    Design: Difficulty/dual_variant_calc/supporter_engagement_versus_retention_score_diverge
    """
    world = _supporter_with_two_forty_six_day_old_actions(api)

    fx.close_campaign(api, world["campaign_id"])

    supporter = fx.read_supporter(api, world["supporter_id"])
    assert_score(supporter["retention_score"], 6.00)

    assert_field(fx.read_action_record(api, world["phone_record_id"]),
                 "status", ACTION_ACKNOWLEDGED)
    assert_field(fx.read_action_record(api, world["email_record_id"]),
                 "status", ACTION_MATCHED)


def test_closing_the_campaign_is_what_writes_retention_and_freezes_the_posture(api):
    """The final score is computed once, at close, and the close freezes the campaign.

    PRD: "Finally the campaign's `posture` is set to `FROZEN` — a `CLOSED`
    campaign is `FROZEN` even when `posture_override` is `FORCE_OPEN` — and the
    campaign's `version` increments by 1."

    Design: Difficulty/dual_variant_calc/supporter_engagement_versus_retention_score_diverge
    """
    world = _supporter_with_two_forty_six_day_old_actions(api)

    closed = fx.close_campaign(api, world["campaign_id"])

    assert_field(closed, "status", CAMPAIGN_CLOSED)
    assert_field(closed, "posture", POSTURE_FROZEN)
