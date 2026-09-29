"""Requests that break two rules at once, and which rung wins.

The rejection ladder is numbered, and the number is the contract: a wave that is
both frozen out and under its reach floor reports the freeze, and a wave that is
both in a recess blackout and third in a saturated window reports the blackout.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_BLACKOUT_WINDOW,
    ERR_CAMPAIGN_FROZEN,
)
from test_helpers.assertions import assert_count, assert_field, assert_page
from test_helpers.test_users import make_campaign_director_headers
from test_helpers.types import (
    CHANNEL_EMAIL,
    MILESTONE_RECESS,
    POSTURE_OVERRIDE_FORCE_FROZEN,
)


# --------------------------------------------------------------------------
# Rung 9 (frozen posture) against rung 24 (reach floor)
# --------------------------------------------------------------------------

def _frozen_campaign_ready_to_schedule_one_email_wave(api):
    """A sendable world whose director has just frozen it by hand.

    The single consenting supporter means any wave asking for five is also under
    its reach floor, so one create violates two rungs at once.
    """
    world = fx.create_sendable_world(api, supporter_count=1, channel=CHANNEL_EMAIL)
    fx.override_posture(api, world["campaign_id"],
                        POSTURE_OVERRIDE_FORCE_FROZEN,
                        override_reason="regulator inquiry opened")
    return world


def _attempt_wave_needing_five_supporters(api, world):
    payload = F.activation_payload(
        world["campaign_id"], world["segment_id"], world["variant_id"],
        "2026-08-05T09:00:00Z", "2026-08-05T17:00:00Z",
        fx.read_segment(api, world["segment_id"])["version"],
        channel=CHANNEL_EMAIL, min_viable_reach=5)
    return api.create_activation(payload,
                                 headers=make_campaign_director_headers())


def test_the_freeze_is_reported_and_the_reach_floor_is_not(api):
    """Rung 9 outranks rung 24, so the frozen posture is the answer.

    PRD: "When a single request violates several rules at once, the response always carries the `error_id` of the **lowest-numbered** rung below."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_state_error_beats_fiscal_reach_floor
    """
    world = _frozen_campaign_ready_to_schedule_one_email_wave(api)

    response = _attempt_wave_needing_five_supporters(api, world)

    validate_error(response, ERR_CAMPAIGN_FROZEN, expected_status=409)


def test_the_refused_wave_leaves_no_row_and_takes_no_reservation(api):
    """A rejection at rung 9 happens before the wave or its reservations exist.

    PRD: "The owning campaign's derived `posture` is not `FROZEN` — otherwise `ERR_CAMPAIGN_FROZEN`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_state_error_beats_fiscal_reach_floor
    """
    world = _frozen_campaign_ready_to_schedule_one_email_wave(api)

    _attempt_wave_needing_five_supporters(api, world)

    assert_page(api.list_activations(headers=make_campaign_director_headers(),
                                     params={"campaign_id": world["campaign_id"]}),
                expected_total=0)
    assert_count(fx.read_segment(api, world["segment_id"])["member_count"], 1)
    assert_count(fx.read_supporter(api, world["supporter_ids"][0])
                 ["touches_reserved"], 0)


# --------------------------------------------------------------------------
# Rung 17 (blackout) against rung 19 (channel saturation)
# --------------------------------------------------------------------------

def _two_scheduled_waves_and_a_recess_two_days_out(api):
    """A saturated email window plus an August recess the next wave runs into.

    Two overlapping scheduled waves already sit on the campaign-and-channel
    pairing, and neither of them touches the recess, so only the third wave can
    break both rules.
    """
    world = fx.create_sendable_world(api, supporter_count=1, channel=CHANNEL_EMAIL)
    recess = fx.add_milestone(api, world["campaign_id"],
                              "2026-08-10T00:00:00Z", "2026-08-12T00:00:00Z",
                              kind=MILESTONE_RECESS, label="August recess")
    fx.add_activation(api, world["campaign_id"], world["segment_id"],
                      world["variant_id"], "2026-08-08T00:00:00Z",
                      "2026-08-09T23:00:00Z", channel=CHANNEL_EMAIL)
    fx.add_activation(api, world["campaign_id"], world["segment_id"],
                      world["variant_id"], "2026-08-09T09:00:00Z",
                      "2026-08-09T23:00:00Z", channel=CHANNEL_EMAIL)
    world["recess_id"] = recess["id"]
    return world


def _attempt_third_wave_running_into_the_recess(api, world):
    payload = F.activation_payload(
        world["campaign_id"], world["segment_id"], world["variant_id"],
        "2026-08-09T12:00:00Z", "2026-08-10T12:00:00Z",
        fx.read_segment(api, world["segment_id"])["version"],
        channel=CHANNEL_EMAIL, min_viable_reach=1)
    return api.create_activation(payload,
                                 headers=make_campaign_director_headers())


def test_the_blackout_is_reported_and_the_saturation_is_not(api):
    """Rung 17 outranks rung 19, so the recess overlap is the answer.

    PRD: "The send window does not intersect any milestone of kind `RECESS` belonging to the same campaign — otherwise `ERR_BLACKOUT_WINDOW`."

    Design: Difficulty/priority_pair_validation_conflict/blackout_temporal_error_beats_channel_saturation_constraint
    """
    world = _two_scheduled_waves_and_a_recess_two_days_out(api)

    response = _attempt_third_wave_running_into_the_recess(api, world)

    validate_error(response, ERR_BLACKOUT_WINDOW, expected_status=409)


def test_the_two_earlier_waves_keep_their_reservations_and_the_recess_is_a_blackout(api):
    """Only the third wave is refused; the ledger still reads two reservations.

    PRD: "`is_blackout` is true exactly when `kind` is `RECESS`, and blackout windows forbid overlapping activation send windows."

    Design: Difficulty/priority_pair_validation_conflict/blackout_temporal_error_beats_channel_saturation_constraint
    """
    world = _two_scheduled_waves_and_a_recess_two_days_out(api)

    _attempt_third_wave_running_into_the_recess(api, world)

    assert_page(api.list_activations(headers=make_campaign_director_headers(),
                                     params={"campaign_id": world["campaign_id"]}),
                expected_total=2)
    assert_count(fx.read_supporter(api, world["supporter_ids"][0])
                 ["touches_reserved"], 2)
    assert_field(fx.read_milestone(api, world["recess_id"]), "is_blackout", True)
