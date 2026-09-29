"""Computed reads, reconciliation actions and multi-effect action endpoints.

The outcome report derived from a live action history, an idempotent segment
refresh that only moves its stamp, the override that masks a blocker without
resolving it, and the test resolution that crowns one winner and retires the
co-locked loser in a single call.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_absent_or_none,
    assert_bps,
    assert_cents,
    assert_count,
    assert_field,
    assert_score,
    assert_version_is,
)
from test_helpers.test_users import (
    make_campaign_director_headers,
    make_message_strategist_headers,
    make_partner_delegate_headers,
)
from test_helpers.types import (
    ACTION_MATCHED,
    ACTION_THANKED,
    APPROVAL_BLOCKED,
    CHANNEL_ALL,
    CHANNEL_EMAIL,
    CHANNEL_SMS,
    DELIVERY_SCHEDULED,
    ENDORSEMENT_REVOKED,
    POSTURE_OPEN,
    POSTURE_OVERRIDE_FORCE_OPEN,
    POSTURE_RESTRICTED,
    TEST_CELL_ECONOMIC_FRAME,
    VARIANT_CHANGES_REQUESTED,
    VARIANT_LOCKED,
    VARIANT_RETIRED,
)


def test_the_outcome_report_derives_thank_loop_closure_without_storing_it(api):
    """Half the counted actions were thanked, and the read mutates nothing.

    PRD: "`thank_loop_closure_bps` is 0 when `action_total` is 0, and otherwise `thanked_total` multiplied by 10,000, divided by `action_total`, rounded half up to a whole number of basis points."

    PRD: "`action_total` is the number of the campaign's action records whose `status` is `MATCHED`, `ACKNOWLEDGED` or `THANKED`; `UNMATCHED`, `DISPUTED` and `VOIDED` rows are excluded."

    PRD: "The outcome report is a computed read available to a `CampaignDirector` or a `ComplianceOfficer`, and it is also recomputed as part of the close."

    PRD: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of that row, and `version`, an integer that begins at 1 on creation and increments by exactly 1 on every mutation of that row — including mutations the caller did not ask for directly, such as a counter recomputed as a cascade hop of some other entity's transition."

    Design: Corner/endpoints/outcome_report_computes_thank_loop_closure_from_real_action_history
    """
    world = fx.create_active_campaign(api)
    campaign_id = world["campaign_id"]
    fx.add_partner(api, campaign_id)
    supporter = fx.add_supporter(api, campaign_id)
    records = fx.log_actions(api, supporter["id"], 2)
    fx.acknowledge_action(api, records[0]["id"])
    thanked = fx.thank_action(api, records[0]["id"])
    assert_field(thanked, "status", ACTION_THANKED)
    assert_field(fx.read_action_record(api, records[1]["id"]), "status",
                 ACTION_MATCHED)
    before = fx.read_campaign(api, campaign_id)

    report = validate_success(api.get_outcome_report(
        campaign_id, headers=make_campaign_director_headers()))
    assert_count(report["supporter_total"], 1)
    assert_count(report["consented_reachable_total"], 1)
    assert_count(report["action_total"], 2)
    assert_count(report["thanked_total"], 1)
    assert_bps(report["thank_loop_closure_bps"], 5000)
    assert_count(report["primary_flip_count"], 0)
    assert_count(report["retained_supporter_count"], 0)
    assert_cents(report["committed_share_total_cents"], 100000)
    assert_cents(report["funded_total_cents"], 100000)
    assert report["coalition_funding_balanced"] is True, "funding reconciles"
    assert_count(report["touch_reservation_total"], 0)
    assert_count(report["open_wave_projected_reach_total"], 0)
    assert report["touch_ledger_balanced"] is True, "the touch ledger reconciles"

    after = fx.read_campaign(api, campaign_id)
    assert_version_is(after, before["version"])
    legislator = fx.read_legislator(api, world["legislator_id"])
    assert_score(legislator["contact_pressure_score"], 14.00)
    assert_count(fx.read_supporter(api, supporter["id"])["touches_consumed"], 1)


def test_an_explicit_segment_refresh_only_moves_the_stamp_it_owns(api):
    """The consent cascade already emptied the segment, so the refresh is a no-op.

    PRD: "Refreshing a segment re-materialises `member_supporter_ids` and `member_count` against current consent and engagement data, stamps `last_refreshed_at` from the logical clock, and increments the segment's `version`."

    PRD: "A segment also publishes `active_activation_count`, the number of activations referencing it whose delivery state is `SCHEDULED` or `SENDING`, and `last_refreshed_at`, which is null until the segment is first refreshed and thereafter holds the logical-clock instant of the most recent refresh."

    PRD: "Membership is recomputed on segment creation, on an explicit refresh, and as a cascade hop of any mutation that changes a supporter's consent states, `engagement_score`, `suppressed` flag or spokesperson training level."

    Design: Corner/endpoints/segment_refresh_is_idempotent_and_only_stamps_last_refreshed_at
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"])
    segment = fx.add_segment(api, world["campaign_id"])
    assert_count(segment["member_count"], 1)
    assert_absent_or_none(segment, "last_refreshed_at")

    fx.revoke_consent(api, supporter["id"], CHANNEL_ALL,
                      source_reference="unsubscribe-link-1")
    emptied = fx.read_segment(api, segment["id"])
    assert_count(emptied["member_count"], 0)

    fx.park_clock(api, "2026-08-03T00:00:00Z")
    refreshed = validate_success(api.refresh_segment(
        segment["id"], headers=make_message_strategist_headers()))
    assert_count(refreshed["member_count"], 0)
    assert refreshed["last_refreshed_at"].startswith("2026-08-03T00:00:00"), (
        f"the stamp comes from the logical clock, got "
        f"{refreshed['last_refreshed_at']}")

    after = fx.read_segment(api, segment["id"])
    assert after["member_supporter_ids"] == [], (
        f"no member survives the revocation, got {after['member_supporter_ids']}")
    assert_count(after["active_activation_count"], 0)
    assert fx.read_supporter(api, supporter["id"])["suppressed"] is True, (
        "the wildcard revoke suppresses the only member")


def test_forcing_a_posture_open_masks_the_blocked_wave_without_clearing_it(api):
    """The override branch outranks the counters it does not reset.

    PRD: "3. Otherwise, if `posture_override` is `FORCE_OPEN`, the posture is `OPEN`."

    PRD: "`FORCE_OPEN` is the one branch that can mask real blockers — it forces `posture` to `OPEN` irrespective of `blocked_activation_count` and `opposed_priority_legislator_count`, and it does **not** clear `blocked_activation_count`, nor does it un-block the blocked waves, which stay `BLOCKED`."

    PRD: "5. Otherwise, if `blocked_activation_count` is at least 1 or `opposed_priority_legislator_count` is at least 1, the posture is `RESTRICTED`."

    Design: Corner/endpoints/force_open_override_masks_a_blocked_wave_without_clearing_it
    """
    world = fx.create_sendable_world(
        api, supporter_count=1, channels=[CHANNEL_EMAIL, CHANNEL_SMS],
        channel=CHANNEL_EMAIL,
        variant_overrides={"channel_scope": [CHANNEL_EMAIL, CHANNEL_SMS]})
    campaign_id = world["campaign_id"]
    wave = fx.add_activation(api, campaign_id, world["segment_id"],
                             world["variant_id"], channel=CHANNEL_EMAIL)
    revoked = validate_success(api.revoke_endorsement(
        world["endorsement_id"],
        {"revoked_reason": "the board reversed its vote"},
        headers=make_partner_delegate_headers(world["partner_ids"][0])))
    assert_field(revoked, "status", ENDORSEMENT_REVOKED)
    before = fx.read_campaign(api, campaign_id)
    assert_field(before, "posture", POSTURE_RESTRICTED)
    assert_count(before["blocked_activation_count"], 1)

    forced = validate_success(api.override_posture(
        campaign_id,
        F.posture_override_payload(
            POSTURE_OVERRIDE_FORCE_OPEN,
            override_reason="leadership accepts the risk for the hearing week"),
        headers=make_campaign_director_headers()))
    assert_field(forced, "posture", POSTURE_OPEN)
    assert_field(forced, "posture_override", POSTURE_OVERRIDE_FORCE_OPEN)

    after = fx.read_campaign(api, campaign_id)
    assert_count(after["blocked_activation_count"], 1)
    held = fx.read_activation(api, wave["id"])
    assert_field(held, "approval_state", APPROVAL_BLOCKED)
    assert_field(held, "delivery_state", DELIVERY_SCHEDULED)
    assert_field(fx.read_variant(api, world["variant_id"]), "status",
                 VARIANT_CHANGES_REQUESTED)
    assert_count(fx.read_supporter(api, world["supporter_ids"][0])["touches_reserved"], 1)


def test_resolving_a_test_crowns_the_winner_and_retires_the_co_locked_loser(api):
    """One call writes the winner flag, the retirement and both metric sets.

    PRD: "On success the test metrics are recomputed for every variant in the cell, `test_winner` becomes true on the winner and false on every other variant of the cell, and every losing variant whose `status` was `APPROVED` or `LOCKED` is `RETIRED`."

    PRD: "The named winner must be `LOCKED` and must carry a `realized_reach_total` of at least the minimum test reach of 3; falling short of that reach floor is `ERR_REACH_BELOW_MINIMUM`."

    PRD: "`send_cost_cents` is the channel's unit cost multiplied by `delivered_count`, where the unit cost is 2 cents for `EMAIL`, 15 cents for `SMS` and 60 cents for `PHONE` — note that the vendor bills for what it delivered, not for what was lawful, so cost uses `delivered_count` while reach does not."

    PRD: "`cost_per_action_cents` is the sentinel value 999999 when `attributed_action_count` is 0; otherwise it is `send_cost_total_cents` divided by `attributed_action_count` with any fraction discarded — floored, never rounded."

    Design: Corner/endpoints/message_test_resolution_crowns_one_winner_and_retires_the_loser
    """
    world = fx.create_sendable_world(api, supporter_count=3)
    campaign_id = world["campaign_id"]
    assert_count(fx.read_segment(api, world["segment_id"])["member_count"], 3)
    loser = fx.create_locked_variant(
        api, campaign_id, partner_id=world["partner_ids"][0],
        test_cell=TEST_CELL_ECONOMIC_FRAME,
        headline="Stand with renters on HB-1420",
        body="Tell your representative that renters are watching HB-1420.")
    assert_field(loser["variant"], "status", VARIANT_LOCKED)

    sent = fx.create_sent_wave(api, campaign_id, world["segment_id"],
                               world["variant_id"], delivered_count=3)
    assert_count(sent["projected_reach"], 3)
    assert_count(sent["realized_reach"], 3)
    assert_cents(sent["send_cost_cents"], 6)

    validate_success(api.resolve_message_test(
        campaign_id,
        F.message_test_resolution_payload(TEST_CELL_ECONOMIC_FRAME,
                                          world["variant_id"]),
        headers=make_message_strategist_headers()))

    winner = fx.read_variant(api, world["variant_id"])
    assert winner["test_winner"] is True, "the named winner carries the flag"
    assert_field(winner, "status", VARIANT_LOCKED)
    assert_count(winner["realized_reach_total"], 3)
    assert_cents(winner["send_cost_total_cents"], 6)
    assert_count(winner["attributed_action_count"], 0)
    assert_bps(winner["response_rate_bps"], 0)
    assert_cents(winner["cost_per_action_cents"], 999999)

    retired = fx.read_variant(api, loser["variant_id"])
    assert retired["test_winner"] is False, "every other variant loses the cell"
    assert_field(retired, "status", VARIANT_RETIRED)
    assert_count(retired["realized_reach_total"], 0)

    for supporter_id in world["supporter_ids"]:
        supporter = fx.read_supporter(api, supporter_id)
        assert_count(supporter["touches_consumed"], 1)
        assert_count(supporter["touches_reserved"], 0)
