"""Derived values: replay, membership predicates, constants and precision.

Per-channel consent replay, the suppression conjunction, the five-condition
membership predicate, the ceiled endorsement quorum, write-once multiplier
snapshots, the decay bucket boundary, the surge grant, the no-action sentinel,
the guarded thank-loop ratio and the pressure-spreading match selector.
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
)
from test_helpers.test_users import (
    make_campaign_director_headers,
    make_compliance_officer_headers,
    make_field_organizer_headers,
    make_message_strategist_headers,
)
from test_helpers.types import (
    ACQUISITION_EVENT,
    ACQUISITION_PETITION,
    ACQUISITION_REFERRAL,
    ACTION_MATCHED,
    APPROVAL_PENDING,
    CHANNEL_ALL,
    CHANNEL_EMAIL,
    CHANNEL_PHONE,
    CHANNEL_SMS,
    CONSENT_GRANTED,
    CONSENT_NONE,
    CONSENT_REVOKED,
    DELIVERY_SCHEDULED,
    DELIVERY_SENT,
    MILESTONE_COMMITTEE_HEARING,
    MILESTONE_RECESS,
    PARTNER_ACTIVE,
    PARTNER_TIER_ALLY,
    PARTNER_TIER_ANCHOR,
    PARTNER_TIER_CORE,
    TIER_MONITOR,
)


def test_a_channel_grant_after_an_all_revoke_regrants_only_that_channel(api):
    """Replay is per channel, so the wildcard revoke keeps governing the rest.

    PRD: "One consequence of per-channel replay deserves stating plainly: a channel-scoped `GRANT` recorded after an `ALL`-scoped `REVOKE` re-grants that one channel, because the per-channel event is the later event *for that channel*."

    Design: Corner/calculations/consent_replay_channel_grant_after_all_revoke_regrants_only_that_channel
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(
        api, world["campaign_id"],
        channels=[CHANNEL_EMAIL, CHANNEL_SMS, CHANNEL_PHONE])
    assert_count(supporter["consent_event_count"], 3)
    revoke = fx.revoke_consent(api, supporter["id"], CHANNEL_ALL,
                               source_reference="unsubscribe-link-1")
    assert_count(revoke["sequence_no"], 4)

    response = api.create_consent_event(
        F.grant_payload(supporter["id"], CHANNEL_EMAIL,
                        source_reference="resubscribe-form-2"),
        headers=make_compliance_officer_headers())

    event = validate_success(response, expected_status=201)
    assert_count(event["sequence_no"], 5)
    after = fx.read_supporter(api, supporter["id"])
    assert_field(after, "email_consent_state", CONSENT_GRANTED)
    assert_field(after, "sms_consent_state", CONSENT_REVOKED)
    assert_field(after, "phone_consent_state", CONSENT_REVOKED)
    assert_field(after, "suppressed", False)
    assert_count(after["consent_event_count"], 5)


def test_a_wildcard_revoke_suppresses_the_supporter_and_empties_the_segment(api):
    """Suppression is the conjunction over all three channels.

    PRD: "A supporter's `suppressed` flag is true exactly when all three of `email_consent_state`, `sms_consent_state` and `phone_consent_state` are `REVOKED`."
    PRD: "A supporter whose consent state on the required channel is `NONE` or `REVOKED` is excluded."

    Design: Corner/calculations/all_channel_revoke_sets_suppressed_true_and_empties_every_segment
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(
        api, world["campaign_id"],
        channels=[CHANNEL_EMAIL, CHANNEL_SMS, CHANNEL_PHONE])
    segment = fx.add_segment(api, world["campaign_id"],
                             rule_required_channel=CHANNEL_EMAIL)
    assert_count(segment["member_count"], 1)

    response = api.create_consent_event(
        F.revoke_payload(supporter["id"], CHANNEL_ALL,
                         source_reference="unsubscribe-link-1"),
        headers=make_compliance_officer_headers())

    validate_success(response, expected_status=201)
    after = fx.read_supporter(api, supporter["id"])
    assert_field(after, "suppressed", True)
    assert_field(after, "email_consent_state", CONSENT_REVOKED)
    assert_field(after, "sms_consent_state", CONSENT_REVOKED)
    assert_field(after, "phone_consent_state", CONSENT_REVOKED)
    reread = fx.read_segment(api, segment["id"])
    assert_count(reread["member_count"], 0)
    assert reread["member_supporter_ids"] == []


def test_membership_admits_only_the_supporter_passing_every_rule(api):
    """Four supporters differ on one dimension each; one survives.

    PRD: "A supporter of the same campaign is a member exactly when all five conditions hold: their resolved consent state for the segment's `rule_required_channel` is `GRANTED`; their `suppressed` flag is false; either `rule_district_codes` is empty or their `district_code` appears in it; their `engagement_score` is at least `rule_min_engagement_score`; and either `rule_sources` is empty or their `acquisition_source` appears in it."

    Design: Corner/calculations/segment_membership_filters_on_channel_consent_engagement_and_source
    """
    world = fx.create_active_campaign(api)
    campaign_id = world["campaign_id"]
    warm = fx.add_supporter(api, campaign_id, channels=[CHANNEL_SMS],
                            full_name="Ada Event", email="ada@example.org",
                            phone="+15550100011",
                            acquisition_source=ACQUISITION_EVENT,
                            consent_source_reference="event-card-1")
    petition = fx.add_supporter(api, campaign_id, channels=[CHANNEL_SMS],
                                full_name="Ben Petition",
                                email="ben@example.org",
                                phone="+15550100012",
                                acquisition_source=ACQUISITION_PETITION,
                                consent_source_reference="petition-sheet-1")
    email_only = fx.add_supporter(api, campaign_id, channels=[CHANNEL_EMAIL],
                                  full_name="Cleo Event",
                                  email="cleo@example.org",
                                  acquisition_source=ACQUISITION_EVENT,
                                  consent_source_reference="event-card-2")
    referral = fx.add_supporter(api, campaign_id, channels=[CHANNEL_SMS],
                                full_name="Dov Referral",
                                email="dov@example.org",
                                phone="+15550100014",
                                acquisition_source=ACQUISITION_REFERRAL,
                                consent_source_reference="referral-note-1")
    assert_score(warm["engagement_score"], 2.00)
    assert_score(petition["engagement_score"], 1.00)
    assert_field(email_only, "sms_consent_state", CONSENT_NONE)
    assert_score(referral["engagement_score"], 1.50)

    response = api.create_segment(
        F.segment_payload(campaign_id, name="Warm SMS event crowd",
                          rule_required_channel=CHANNEL_SMS,
                          rule_min_engagement_score=2.0,
                          rule_sources=[ACQUISITION_EVENT]),
        headers=make_message_strategist_headers())

    segment = validate_success(response, expected_status=201)
    assert_count(segment["member_count"], 1)
    assert segment["member_supporter_ids"] == [warm["id"]]
    assert_score(segment["rule_min_engagement_score"], 2.0)
    assert_absent_or_none(segment, "last_refreshed_at")
    assert_count(segment["active_activation_count"], 0)


def test_the_endorsement_quorum_ceils_half_of_three_active_partners(api):
    """Half of three is two, and the quorum is re-derived on every read.

    PRD: "A message variant's `required_endorsement_quorum` is the greater of 1 and the count of the campaign's `ACTIVE` partners multiplied by one half and rounded **up** to a whole number."
    PRD: "The quorum is recomputed whenever a partner is added, whenever a partner withdraws, and on every read of a message variant, so it never goes stale."

    Design: Corner/calculations/endorsement_quorum_ceils_half_of_three_active_partners_to_two
    """
    world = fx.create_active_campaign(api)
    campaign_id = world["campaign_id"]
    variant = fx.create_approved_variant(api, campaign_id)
    assert_count(fx.read_variant(api, variant["id"])["required_endorsement_quorum"], 1)
    fx.add_partner(api, campaign_id, tier=PARTNER_TIER_ANCHOR,
                   org_name="Anchor Housing Alliance")
    assert_count(fx.read_variant(api, variant["id"])["required_endorsement_quorum"], 1)
    fx.add_partner(api, campaign_id, tier=PARTNER_TIER_CORE,
                   org_name="Core Tenants Union")
    assert_count(fx.read_variant(api, variant["id"])["required_endorsement_quorum"], 1)

    response = api.create_partner(
        F.partner_payload(campaign_id, org_name="Ally Faith Network",
                          tier=PARTNER_TIER_ALLY),
        headers=make_campaign_director_headers())

    ally = validate_success(response, expected_status=201)
    assert_field(ally, "status", PARTNER_ACTIVE)
    reread = fx.read_variant(api, variant["id"])
    assert_count(reread["required_endorsement_quorum"], 2)
    assert_count(reread["endorsement_count"], 0)


def test_a_recess_action_is_halved_and_a_later_reschedule_never_rescores_it(api):
    """The multiplier is a write-once snapshot taken while the window held.

    PRD: "Otherwise the strongest window wins: sort the containing milestones by `pressure_multiplier` descending and then by `created_at` ascending, and take the first one's `pressure_multiplier` — 1.5 inside a `COMMITTEE_HEARING`, 2.0 inside a `FLOOR_VOTE`, 0.5 inside a `RECESS`, 1.0 inside a `SIGNING`."
    PRD: "The snapshot is written once and never recomputed, so a later reschedule does not retroactively rescore existing actions."

    Design: Corner/calculations/recess_milestone_stamps_half_multiplier_and_a_reschedule_never_rescores_it
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"])
    milestone = fx.add_milestone(api, world["campaign_id"],
                                 "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z",
                                 kind=MILESTONE_RECESS,
                                 label="Legislative recess")
    assert_score(milestone["pressure_multiplier"], 0.5)
    assert_field(milestone, "is_blackout", True)
    fx.park_clock(api, "2026-08-12T00:00:00Z")
    record = fx.log_action(api, supporter["id"], channel=CHANNEL_EMAIL)
    assert_score(record["pressure_multiplier"], 0.5)

    moved = validate_success(api.reschedule_milestone(
        milestone["id"],
        F.milestone_reschedule_payload("2026-09-01T00:00:00Z",
                                       "2026-09-10T00:00:00Z"),
        headers=make_campaign_director_headers()))

    assert_count(moved["reschedule_count"], 1)
    assert moved["window_start"].startswith("2026-09-01T00:00:00")
    reread = fx.read_action_record(api, record["id"])
    assert_field(reread, "status", ACTION_MATCHED)
    assert_score(reread["pressure_multiplier"], 0.5)
    legislator = fx.read_legislator(api, world["legislator_id"])
    assert_score(legislator["contact_pressure_score"], 11.00)
    assert_field(legislator, "priority_tier", TIER_MONITOR)
    assert_score(fx.read_supporter(api, supporter["id"])["engagement_score"], 2.00)


def test_the_decay_bucket_holds_at_seven_days_and_drops_at_eight(api):
    """The bucket is chosen by an integer day count with an inclusive bound.

    PRD: "An action aged at most 7 days keeps a factor of 1.00; one aged more than 7 days but at most 30 days takes 0.75; anything older takes 0.50."
    PRD: "Because the decay factor is selected by an integer day count, an action aged exactly 7 days still keeps 1.00 while one aged 8 days drops to 0.75, and moving the logical clock alone is enough to change the score on its next evaluation."

    Design: Corner/calculations/engagement_decay_holds_at_seven_days_and_drops_to_three_quarters_at_eight
    """
    world = fx.create_active_campaign(api)
    campaign_id = world["campaign_id"]
    seven = fx.add_supporter(api, campaign_id,
                             channels=[CHANNEL_EMAIL, CHANNEL_PHONE],
                             full_name="Seven Sun", email="seven@example.org",
                             phone="+15550100021",
                             consent_source_reference="petition-sheet-7")
    eight = fx.add_supporter(api, campaign_id,
                             channels=[CHANNEL_EMAIL, CHANNEL_PHONE],
                             full_name="Eight Eve", email="eight@example.org",
                             phone="+15550100022",
                             consent_source_reference="petition-sheet-8")
    fx.log_action(api, seven["id"], channel=CHANNEL_PHONE)
    fx.log_action(api, eight["id"], channel=CHANNEL_PHONE)
    assert_score(fx.read_supporter(api, seven["id"])["engagement_score"], 4.00)
    assert_score(fx.read_supporter(api, eight["id"])["engagement_score"], 4.00)

    fx.park_clock(api, "2026-08-08T00:00:00Z")
    fx.log_action(api, seven["id"], channel=CHANNEL_EMAIL)
    fx.park_clock(api, "2026-08-09T00:00:00Z")
    fx.log_action(api, eight["id"], channel=CHANNEL_EMAIL)

    aged_seven = fx.read_supporter(api, seven["id"])
    assert_score(aged_seven["engagement_score"], 5.00)
    assert_count(aged_seven["action_count"], 2)
    aged_eight = fx.read_supporter(api, eight["id"])
    assert_score(aged_eight["engagement_score"], 4.25)
    assert_count(aged_eight["action_count"], 2)


def test_only_the_milestone_anchored_wave_earns_the_surge_grant(api):
    """The grant needs the right kind, full containment and an open posture.

    PRD: "It is 2 when a `milestone_id` was supplied, that milestone's `kind` is `COMMITTEE_HEARING` or `FLOOR_VOTE`, the milestone's `window_start` is at or before the wave's `window_start`, the wave's `window_end` is at or before the milestone's `window_end`, and the pre-request posture was `OPEN`."
    PRD: "**Step three**: `effective_touch_cap` is the base allowance of 3 touches per supporter plus that surge grant, and it is persisted on the wave as an audit snapshot."

    Design: Corner/calculations/surge_grant_lifts_touch_cap_to_five_only_for_a_milestone_anchored_wave
    """
    world = fx.create_sendable_world(api, supporter_count=1,
                                     channel=CHANNEL_EMAIL)
    campaign_id = world["campaign_id"]
    milestone = fx.add_milestone(api, campaign_id, "2026-09-01T00:00:00Z",
                                 "2026-09-30T00:00:00Z",
                                 kind=MILESTONE_COMMITTEE_HEARING,
                                 label="Committee hearing")
    assert_score(milestone["pressure_multiplier"], 1.5)
    plain = fx.add_activation(api, campaign_id, world["segment_id"],
                              world["variant_id"], channel=CHANNEL_EMAIL,
                              min_viable_reach=1)
    assert_count(plain["effective_touch_cap"], 3)
    assert_count(plain["projected_reach"], 1)

    response = api.create_activation(
        F.activation_payload(campaign_id, world["segment_id"],
                             world["variant_id"], "2026-09-10T09:00:00Z",
                             "2026-09-10T17:00:00Z",
                             fx.read_segment(api, world["segment_id"])["version"],
                             channel=CHANNEL_EMAIL, min_viable_reach=1,
                             milestone_id=milestone["id"]),
        headers=make_campaign_director_headers())

    surge = validate_success(response, expected_status=201)
    assert_count(surge["effective_touch_cap"], 5)
    assert_field(surge, "milestone_id", milestone["id"])
    assert_count(surge["projected_reach"], 1)
    assert_field(surge, "delivery_state", DELIVERY_SCHEDULED)
    assert_field(surge, "approval_state", APPROVAL_PENDING)
    supporter = fx.read_supporter(api, world["supporter_ids"][0])
    assert_count(supporter["touches_reserved"], 2)
    assert_count(supporter["touches_consumed"], 0)
    assert_count(fx.read_segment(api, world["segment_id"])["active_activation_count"], 2)


def test_a_delivered_wave_with_no_attributed_action_uses_the_sentinel(api):
    """The undefined division is replaced by a sentinel, never by a null.

    PRD: "`cost_per_action_cents` is the sentinel value 999999 when `attributed_action_count` is 0; otherwise it is `send_cost_total_cents` divided by `attributed_action_count` with any fraction discarded — floored, never rounded."
    PRD: "`send_cost_cents` is the channel's unit cost multiplied by `delivered_count`, where the unit cost is 2 cents for `EMAIL`, 15 cents for `SMS` and 60 cents for `PHONE` — note that the vendor bills for what it delivered, not for what was lawful, so cost uses `delivered_count` while reach does not."

    Design: Corner/calculations/variant_metrics_use_the_sentinel_and_zero_bps_when_no_action_is_attributed
    """
    world = fx.create_sendable_world(api, supporter_count=1,
                                     channel=CHANNEL_EMAIL)
    sending = fx.create_sending_wave(api, world["campaign_id"],
                                     world["segment_id"], world["variant_id"])
    assert_count(sending["projected_reach"], 1)

    response = api.complete_activation(
        sending["id"], F.activation_complete_payload(1, 0),
        headers=make_campaign_director_headers())

    completed = validate_success(response)
    assert_count(completed["realized_reach"], 1)
    assert_cents(completed["send_cost_cents"], 2)
    assert_field(completed, "delivery_state", DELIVERY_SENT)
    assert_count(completed["suppressed_by_consent_count"], 0)
    variant = fx.read_variant(api, world["variant_id"])
    assert_count(variant["realized_reach_total"], 1)
    assert_cents(variant["send_cost_total_cents"], 2)
    assert_count(variant["attributed_action_count"], 0)
    assert_bps(variant["response_rate_bps"], 0)
    assert_cents(variant["cost_per_action_cents"], 999999)
    supporter = fx.read_supporter(api, world["supporter_ids"][0])
    assert_count(supporter["touches_reserved"], 0)
    assert_count(supporter["touches_consumed"], 1)


def test_the_outcome_report_guards_the_thank_loop_ratio_at_zero_actions(api):
    """No action yet, so the ratio is guarded and both ledgers reconcile.

    PRD: "`thank_loop_closure_bps` is 0 when `action_total` is 0, and otherwise `thanked_total` multiplied by 10,000, divided by `action_total`, rounded half up to a whole number of basis points."
    PRD: "`committed_share_total_cents` and `funded_total_cents` are reported side by side, and `coalition_funding_balanced` is the exact equality of those two integers."
    PRD: "`touch_reservation_total` is the sum of `touches_reserved` across the campaign's supporters, `open_wave_projected_reach_total` is the sum of `projected_reach` across the campaign's activations whose delivery state is `SCHEDULED` or `SENDING`, and `touch_ledger_balanced` is the exact equality of those two integers."

    Design: Corner/calculations/outcome_report_reports_zero_thank_loop_bps_before_any_action_exists
    """
    world = fx.create_active_campaign(api)
    fx.add_supporter(api, world["campaign_id"])
    partner = fx.add_partner(api, world["campaign_id"],
                             tier=PARTNER_TIER_ANCHOR)
    assert_cents(partner["committed_cents"], 100000)

    response = api.get_outcome_report(world["campaign_id"],
                                      headers=make_campaign_director_headers())

    report = validate_success(response)
    assert_count(report["supporter_total"], 1)
    assert_count(report["consented_reachable_total"], 1)
    assert_count(report["action_total"], 0)
    assert_count(report["thanked_total"], 0)
    assert_bps(report["thank_loop_closure_bps"], 0)
    assert_count(report["primary_flip_count"], 0)
    assert_count(report["retained_supporter_count"], 0)
    assert_cents(report["committed_share_total_cents"], 100000)
    assert_cents(report["funded_total_cents"], 100000)
    assert_field(report, "coalition_funding_balanced", True)
    assert_count(report["touch_reservation_total"], 0)
    assert_count(report["open_wave_projected_reach_total"], 0)
    assert_field(report, "touch_ledger_balanced", True)


def test_the_selector_routes_the_second_action_to_the_quieter_office(api):
    """Pressure score ascending outranks the created_at tie-break.

    PRD: "A new legislator starts with `contact_pressure_score` of 0.00, `priority_tier` `MONITOR`, `constituent_action_count` of 0 and `meeting_held_count` of 0."
    PRD: "The second key is the candidate's current `contact_pressure_score`, **ascending** — the selector deliberately spreads pressure by preferring the least-contacted office."
    PRD: "The third key is `created_at` ascending, and it is the final tie-break; ties are never broken on `id`."

    Design: Corner/calculations/match_selector_spreads_pressure_to_the_lowest_scoring_legislator_after_a_created_at_tie
    """
    world = fx.create_active_campaign(api)
    first_office = world["legislator_id"]
    second_office = fx.add_legislator(api, world["campaign_id"],
                                      full_name="Rep. Brandt")["id"]
    assert_score(fx.read_legislator(api, first_office)["contact_pressure_score"],
                 0.00)
    assert_score(fx.read_legislator(api, second_office)["contact_pressure_score"],
                 0.00)
    supporter = fx.add_supporter(api, world["campaign_id"])
    first_record = fx.log_action(api, supporter["id"], channel=CHANNEL_EMAIL)
    assert_field(first_record, "legislator_id", first_office)

    response = api.create_action_record(
        F.action_record_payload(supporter["id"], channel=CHANNEL_EMAIL),
        headers=make_field_organizer_headers())

    second_record = validate_success(response, expected_status=201)
    assert_field(second_record, "legislator_id", second_office)
    for office in (first_office, second_office):
        legislator = fx.read_legislator(api, office)
        assert_score(legislator["contact_pressure_score"], 12.00)
        assert_count(legislator["constituent_action_count"], 1)
    campaign = fx.read_campaign(api, world["campaign_id"])
    assert_count(campaign["total_actions_logged"], 2)
    assert_count(campaign["distinct_acting_supporter_count"], 1)
    assert_score(fx.read_supporter(api, supporter["id"])["engagement_score"], 3.00)
