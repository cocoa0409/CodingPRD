"""Quantities the system promises to conserve across a compensating call.

Two ledgers are read before the trigger and again afterwards. The touch ledger
must land back on zero equals zero after an abort releases three reservations,
and the funded budget must still total exactly what was funded after a partner
walks out and the whole split re-runs.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_cents, assert_count, assert_field, assert_page
from test_helpers.test_users import make_campaign_director_headers
from test_helpers.types import (
    CHANNEL_EMAIL,
    DELIVERY_ABORTED,
    PARTNER_ACTIVE,
    PARTNER_TIER_ALLY,
    PARTNER_TIER_ANCHOR,
    PARTNER_TIER_CORE,
    PARTNER_WITHDRAWN,
)


# --------------------------------------------------------------------------
# The touch-reservation ledger across an abort
# --------------------------------------------------------------------------

def _scheduled_wave_holding_one_reservation_per_supporter(api):
    """A wave over three consenting supporters, none of it delivered yet.

    The wave's projected reach and the sum of the three supporters'
    reservations are the two sides of the ledger the abort has to rebalance.
    """
    world = fx.create_sendable_world(api, supporter_count=3, channel=CHANNEL_EMAIL)
    activation = fx.add_activation(api, world["campaign_id"],
                                   world["segment_id"], world["variant_id"],
                                   channel=CHANNEL_EMAIL, min_viable_reach=1)
    world["activation_id"] = activation["id"]
    return world


def test_the_ledger_balances_at_three_before_the_abort(api):
    """Three reservations against three units of open projected reach.

    PRD: "`touch_reservation_total` is the sum of `touches_reserved` across the campaign's supporters, `open_wave_projected_reach_total` is the sum of `projected_reach` across the campaign's activations whose delivery state is `SCHEDULED` or `SENDING`, and `touch_ledger_balanced` is the exact equality of those two integers."

    Design: Difficulty/compensating_invariant/touch_reservation_ledger_conserved_across_wave_abort
    """
    world = _scheduled_wave_holding_one_reservation_per_supporter(api)

    report = fx.read_outcome_report(api, world["campaign_id"])
    assert_count(report["touch_reservation_total"], 3)
    assert_count(report["open_wave_projected_reach_total"], 3)
    assert_field(report, "touch_ledger_balanced", True)


def test_the_abort_records_its_reason_and_keeps_the_reach_it_had_projected(api):
    """The audit snapshot survives the abort; only the live ledger moves.

    PRD: "Aborting a wave carries an `abort_reason` and is legal from either `SCHEDULED` or `SENDING`."

    Design: Difficulty/compensating_invariant/touch_reservation_ledger_conserved_across_wave_abort
    """
    world = _scheduled_wave_holding_one_reservation_per_supporter(api)

    aborted = fx.abort_activation(api, world["activation_id"],
                                  abort_reason="budget pulled")

    assert_field(aborted, "delivery_state", DELIVERY_ABORTED)
    assert_field(aborted, "abort_reason", "budget pulled")
    assert_count(aborted["projected_reach"], 3)


def test_every_reservation_is_released_and_none_becomes_a_consumed_touch(api):
    """The compensation is exact: three released, zero delivered.

    PRD: "From `SCHEDULED` the compensation is simple: `delivery_state` becomes `ABORTED`, the `abort_reason` is stored, every supporter listed in `target_supporter_ids` has `touches_reserved` decremented by 1 — the exact compensating action of the reservations taken at creation — and the segment's `active_activation_count` is decremented by 1, bumping the segment's `version`."

    Design: Difficulty/compensating_invariant/touch_reservation_ledger_conserved_across_wave_abort
    """
    world = _scheduled_wave_holding_one_reservation_per_supporter(api)

    fx.abort_activation(api, world["activation_id"], abort_reason="budget pulled")

    for supporter_id in world["supporter_ids"]:
        supporter = fx.read_supporter(api, supporter_id)
        assert_count(supporter["touches_reserved"], 0)
        assert_count(supporter["touches_consumed"], 0)
    assert_count(fx.read_segment(api, world["segment_id"])
                 ["active_activation_count"], 0)


def test_the_ledger_lands_back_on_zero_equals_zero(api):
    """Balanced before at three each, balanced after at zero each.

    PRD: "Both reconciliation flags are exact integer equality checks, never tolerances."

    Design: Difficulty/compensating_invariant/touch_reservation_ledger_conserved_across_wave_abort
    """
    world = _scheduled_wave_holding_one_reservation_per_supporter(api)

    fx.abort_activation(api, world["activation_id"], abort_reason="budget pulled")

    report = fx.read_outcome_report(api, world["campaign_id"])
    assert_count(report["touch_reservation_total"], 0)
    assert_count(report["open_wave_projected_reach_total"], 0)
    assert_field(report, "touch_ledger_balanced", True)


# --------------------------------------------------------------------------
# The funded budget across a partner withdrawal
# --------------------------------------------------------------------------

def _three_way_coalition_with_a_leftover_cent(api):
    """An anchor, a core and an ally splitting one thousand dollars.

    The three-way split leaves one cent over that the waterfall hands to the
    anchor, and there are no variants at all, so the withdrawal cascade can only
    touch the funding split.
    """
    world = fx.create_active_campaign(api)
    partners = fx.add_partners(api, world["campaign_id"],
                               [PARTNER_TIER_ANCHOR, PARTNER_TIER_CORE,
                                PARTNER_TIER_ALLY])
    world.update({"partners": partners,
                  "anchor_id": partners[0]["id"],
                  "core_id": partners[1]["id"],
                  "ally_id": partners[2]["id"]})
    return world


def test_the_funding_ledger_balances_before_the_withdrawal(api):
    """The whole funded total is committed, leftover cent included.

    PRD: "`committed_share_total_cents` and `funded_total_cents` are reported side by side, and `coalition_funding_balanced` is the exact equality of those two integers."

    Design: Difficulty/compensating_invariant/coalition_funding_total_conserved_across_partner_withdrawal
    """
    world = _three_way_coalition_with_a_leftover_cent(api)

    report = fx.read_outcome_report(api, world["campaign_id"])
    assert_cents(report["committed_share_total_cents"], 100000)
    assert_cents(report["funded_total_cents"], 100000)
    assert_field(report, "coalition_funding_balanced", True)


def test_the_leaving_anchor_is_zeroed_and_the_other_two_absorb_its_share(api):
    """Every line changes, and the two-way split has no leftover at all.

    PRD: "Worked through: with `funded_total_cents` of 100,000 split across one `ANCHOR`, one `CORE` and one `ALLY`, the floored lines are 55,555 plus 33,333 plus 11,111, totalling 99,999; the single leftover cent goes to the `ANCHOR` because it holds the highest `share_weight`, giving 55,556, 33,333 and 11,111."

    Design: Difficulty/compensating_invariant/coalition_funding_total_conserved_across_partner_withdrawal
    """
    world = _three_way_coalition_with_a_leftover_cent(api)

    withdrawn = fx.withdraw_partner(api, world["anchor_id"],
                                    withdraw_reason="board vote to exit the coalition")

    assert_field(withdrawn, "status", PARTNER_WITHDRAWN)
    assert_cents(withdrawn["committed_cents"], 0)
    assert_cents(fx.read_partner(api, world["core_id"])["committed_cents"], 75000)
    assert_cents(fx.read_partner(api, world["ally_id"])["committed_cents"], 25000)


def test_the_funded_total_is_invariant_across_the_re_split(api):
    """Both splits sum to exactly the funded total, never one cent either side.

    PRD: "After the `ANCHOR` withdraws, the remaining two split 75,000 and 25,000 with no leftover."

    Design: Difficulty/compensating_invariant/coalition_funding_total_conserved_across_partner_withdrawal
    """
    world = _three_way_coalition_with_a_leftover_cent(api)

    fx.withdraw_partner(api, world["anchor_id"],
                        withdraw_reason="board vote to exit the coalition")

    campaign = fx.read_campaign(api, world["campaign_id"])
    assert_cents(campaign["committed_share_total_cents"], 100000)
    assert_cents(campaign["funded_total_cents"], 100000)
    report = fx.read_outcome_report(api, world["campaign_id"])
    assert_field(report, "coalition_funding_balanced", True)


def test_two_partners_remain_active_after_the_withdrawal(api):
    """The withdrawn organisation leaves the active roster, not the record.

    PRD: "Collect the campaign's partners whose `status` is `ACTIVE`, ordered by `created_at` ascending, and total their `share_weight` values."

    Design: Difficulty/compensating_invariant/coalition_funding_total_conserved_across_partner_withdrawal
    """
    world = _three_way_coalition_with_a_leftover_cent(api)

    fx.withdraw_partner(api, world["anchor_id"],
                        withdraw_reason="board vote to exit the coalition")

    assert_page(api.list_campaign_partners(
        world["campaign_id"], headers=make_campaign_director_headers(),
        params={"status": PARTNER_ACTIVE}), expected_total=2)
