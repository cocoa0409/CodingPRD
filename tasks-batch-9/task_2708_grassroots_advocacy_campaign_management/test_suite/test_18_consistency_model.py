"""Nothing lags: the completion response already carries every recomputed field.

The vendor's tally is applied inside the completing request, so the response
itself states the realized reach and the cost, and the very next reads of the
carrying variant, the touched supporter and the segment agree with it without
any refresh call.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_count,
    assert_field,
)
from test_helpers.test_users import (
    make_campaign_director_headers,
    make_field_organizer_headers,
    make_message_strategist_headers,
)
from test_helpers.types import (
    DELIVERY_SENDING,
    DELIVERY_SENT,
)


def test_completing_a_wave_exposes_every_recomputed_field_in_the_same_request(api):
    """One delivered EMAIL touch, read back three ways with no retry anywhere.

    PRD: "When `bounced_count` is 0 **and** `delivered_count` equals the length of `target_supporter_ids`, `delivery_state` becomes `SENT`."

    PRD: "Take the first `delivered_count` entries of `target_supporter_ids` in the stored `created_at` ascending order — that ordered prefix is the delivered set — and count how many of those supporters still have `GRANTED` consent on the wave's `channel` and a `suppressed` flag of false at the moment of completion."

    PRD: "`send_cost_cents` is the channel's unit cost multiplied by `delivered_count`, where the unit cost is 2 cents for `EMAIL`, 15 cents for `SMS` and 60 cents for `PHONE` — note that the vendor bills for what it delivered, not for what was lawful, so cost uses `delivered_count` while reach does not."

    PRD: "For each of the first `delivered_count` supporters of `target_supporter_ids` in `created_at` ascending order, `touches_consumed` is incremented by 1 and `touches_reserved` is decremented by 1 — the reservation converts into consumption."

    PRD: "The segment's `active_activation_count` is decremented by 1, bumping the segment's `version`."

    PRD: "Finally the carrying variant's `realized_reach_total`, `send_cost_total_cents`, `response_rate_bps` and `cost_per_action_cents` are recomputed, and the wave's `version` increments by 1."

    Design: Corner/consistency model/completing_a_wave_exposes_every_recomputed_field_in_the_same_request
    """
    world = fx.create_sendable_world(api, supporter_count=1)
    supporter_id = world["supporter_ids"][0]
    variant_id = world["variant_id"]
    fresh = fx.read_variant(api, variant_id)
    assert_count(fresh["realized_reach_total"], 0)
    assert_cents(fresh["send_cost_total_cents"], 0)

    sending = fx.create_sending_wave(api, world["campaign_id"],
                                    world["segment_id"], variant_id)
    assert_field(sending, "delivery_state", DELIVERY_SENDING)
    assert_count(fx.read_supporter(api, supporter_id)["touches_reserved"], 1)

    completed = validate_success(api.complete_activation(
        sending["id"], F.activation_complete_payload(1, 0),
        headers=make_campaign_director_headers()))
    assert_count(completed["realized_reach"], 1)
    assert_cents(completed["send_cost_cents"], 2)
    assert_field(completed, "delivery_state", DELIVERY_SENT)

    variant = validate_success(api.get_variant(
        variant_id, headers=make_message_strategist_headers()))
    assert_count(variant["realized_reach_total"], 1)
    assert_cents(variant["send_cost_total_cents"], 2)

    supporter = validate_success(api.get_supporter(
        supporter_id, headers=make_field_organizer_headers()))
    assert_count(supporter["touches_reserved"], 0)
    assert_count(supporter["touches_consumed"], 1)

    assert_count(fx.read_segment(api, world["segment_id"])["active_activation_count"],
                 0)
