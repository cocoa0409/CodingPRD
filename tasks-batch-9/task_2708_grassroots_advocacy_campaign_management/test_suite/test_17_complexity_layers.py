"""Optimistic concurrency, the version counter, and counter reconciliation.

Two audience-pinning guards fire because the accepted write moved the parent
underneath the client, the `version` field is shown to be a write counter that
no read ever touches, and the campaign and legislator aggregates are read three
times across a dispute and its voiding to show the deduction happens once.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_STALE_SEGMENT_VERSION,
    ERR_STALE_VARIANT_VERSION,
)
from test_helpers.assertions import (
    assert_count,
    assert_field,
    assert_score,
    assert_version_is,
)
from test_helpers.test_users import (
    make_campaign_director_headers,
    make_compliance_officer_headers,
    make_message_strategist_headers,
    make_partner_delegate_headers,
)
from test_helpers.types import (
    ACQUISITION_EVENT,
    ACTION_MATCHED,
    ACTION_VOIDED,
    APPROVAL_PENDING,
    CAMPAIGN_ACTIVE,
    CHANNEL_EMAIL,
    DISPUTE_OUTCOME_VOIDED,
    ENDORSEMENT_ACTIVE,
    PARTNER_TIER_ANCHOR,
    PARTNER_TIER_CORE,
    POSTURE_FROZEN,
    POSTURE_OVERRIDE_FORCE_FROZEN,
    REVIEW_DECISION_APPROVE,
    TIER_MONITOR,
    VARIANT_APPROVED,
)

SECOND_WINDOW_START = "2026-09-10T09:00:00Z"
SECOND_WINDOW_END = "2026-09-10T17:00:00Z"


def test_a_stale_segment_pin_blocks_the_second_wave_until_the_client_re_reads(api):
    """The first wave moved the segment, so replaying its pin is refused with 412.

    PRD: "If that value does not equal the segment's current `version`, the create is rejected with `ERR_STALE_SEGMENT_VERSION` (HTTP 412)."

    PRD: "The product deliberately permits many waves against one segment, so a second create is legitimate on its own terms; what the guard catches is that the audience snapshot the client sized its wave against — `member_supporter_ids`, `member_count` and `active_activation_count` — is no longer the audience the server holds."

    PRD: "Creating a wave also increments the segment's `active_activation_count` (bumping the segment's `version`) and lands the wave on both of its independent state dimensions: `approval_state` `PENDING` and `delivery_state` `SCHEDULED`."

    PRD: "The surviving identifiers become `target_supporter_ids` in that same order, `projected_reach` is the length of that list, and every one of those supporters has `touches_reserved` incremented by 1, taking the reservation that later paths must compensate."

    Design: Corner/cross-cutting complexity layers/stale_segment_version_blocks_a_second_wave_until_the_client_re_reads
    """
    world = fx.create_sendable_world(api, supporter_count=1)
    campaign_id = world["campaign_id"]
    segment_id = world["segment_id"]
    variant_id = world["variant_id"]
    before = fx.read_segment(api, segment_id)
    assert_count(before["active_activation_count"], 0)
    first_pin = before["version"]

    first_wave = fx.add_activation(api, campaign_id, segment_id, variant_id,
                                  segment_version=first_pin)

    replay = F.activation_payload(campaign_id, segment_id, variant_id,
                                  SECOND_WINDOW_START, SECOND_WINDOW_END,
                                  first_pin, channel=CHANNEL_EMAIL,
                                  min_viable_reach=1)
    validate_error(
        api.create_activation(replay, headers=make_campaign_director_headers()),
        ERR_STALE_SEGMENT_VERSION, expected_status=412)

    moved = fx.read_segment(api, segment_id)
    assert_count(moved["active_activation_count"], 1)
    assert moved["version"] != first_pin, (
        f"the accepted wave must move the segment off {first_pin}")

    retry = dict(replay, expected_segment_version=moved["version"])
    second_wave = validate_success(
        api.create_activation(retry, headers=make_campaign_director_headers()),
        expected_status=201)
    assert_count(second_wave["projected_reach"], 1)

    assert_field(fx.read_activation(api, first_wave["id"]), "approval_state",
                 APPROVAL_PENDING)
    assert_field(fx.read_activation(api, second_wave["id"]), "approval_state",
                 APPROVAL_PENDING)
    assert_count(fx.read_segment(api, segment_id)["active_activation_count"], 2)
    supporter = fx.read_supporter(api, world["supporter_ids"][0])
    assert_count(supporter["touches_reserved"], 2)


def test_an_endorsement_pins_the_reviewed_revision_and_rejects_the_stale_one(api):
    """Partner A's endorsement moves the copy, so partner B must read it again.

    PRD: "If that value does not equal the variant's current `version`, the create is rejected with `ERR_STALE_VARIANT_VERSION` (HTTP 412)."

    PRD: "Every coalition partner may legitimately endorse the same variant, so a later endorsement is a normal product operation; the guard exists because the copy under endorsement may have changed — a review decision, a lock, a reopen or another partner's endorsement all bump the variant's `version` — and message discipline requires a partner to endorse the exact revision it reviewed."

    PRD: "A message variant's `required_endorsement_quorum` is the greater of 1 and the count of the campaign's `ACTIVE` partners multiplied by one half and rounded **up** to a whole number."

    Design: Corner/cross-cutting complexity layers/endorsement_pins_the_reviewed_revision_and_rejects_the_stale_one
    """
    world = fx.create_active_campaign(api)
    campaign_id = world["campaign_id"]
    partners = fx.add_partners(api, campaign_id,
                              [PARTNER_TIER_ANCHOR, PARTNER_TIER_CORE])
    variant = fx.create_approved_variant(api, campaign_id)
    variant_id = variant["id"]
    shared_read = fx.read_variant(api, variant_id)
    first_pin = shared_read["version"]
    assert_count(shared_read["required_endorsement_quorum"], 1)

    endorsement_a = validate_success(
        api.create_endorsement(
            F.endorsement_payload(partners[0]["id"], variant_id, first_pin),
            headers=make_partner_delegate_headers(partners[0]["id"])),
        expected_status=201)
    assert_count(endorsement_a["endorsed_variant_version"], first_pin)

    validate_error(
        api.create_endorsement(
            F.endorsement_payload(partners[1]["id"], variant_id, first_pin),
            headers=make_partner_delegate_headers(partners[1]["id"])),
        ERR_STALE_VARIANT_VERSION, expected_status=412)

    re_read = validate_success(api.get_variant(
        variant_id,
        headers=make_partner_delegate_headers(partners[1]["id"])))
    assert_count(re_read["endorsement_count"], 1)
    second_pin = re_read["version"]
    assert second_pin != first_pin, (
        f"partner A's endorsement must move the variant off {first_pin}")

    endorsement_b = validate_success(
        api.create_endorsement(
            F.endorsement_payload(partners[1]["id"], variant_id, second_pin),
            headers=make_partner_delegate_headers(partners[1]["id"])),
        expected_status=201)
    assert_count(endorsement_b["endorsed_variant_version"], second_pin)
    assert (endorsement_b["endorsed_variant_version"]
            != endorsement_a["endorsed_variant_version"]), (
        "the two partners pin two different revisions of the same copy")

    assert_field(fx.read_endorsement(api, endorsement_a["id"]), "status",
                 ENDORSEMENT_ACTIVE)
    assert_field(fx.read_endorsement(api, endorsement_b["id"]), "status",
                 ENDORSEMENT_ACTIVE)
    assert_count(fx.read_variant(api, variant_id)["endorsement_count"], 2)


def test_every_accepted_write_climbs_one_version_and_no_read_ever_does(api):
    """Two aggregates each climb 1, 2, 3 while three interleaved reads change nothing.

    PRD: "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of that row, and `version`, an integer that begins at 1 on creation and increments by exactly 1 on every mutation of that row — including mutations the caller did not ask for directly, such as a counter recomputed as a cascade hop of some other entity's transition."

    PRD: "On success the campaign's `posture` is recomputed and the campaign's `version` increments by 1."

    PRD: "Latching `FORCE_FROZEN` drives the posture from `OPEN` to `FROZEN` with no preconditions at all."

    PRD: "Either way the server records `submitted_by_user_id` as the `X-User-ID` of the submitting request and increments the variant's `version` by 1."

    PRD: "In both cases `reviewed_by_user_id` is set to the reviewing `X-User-ID` and the variant's `version` increments by 1."

    Design: Corner/cross-cutting complexity layers/every_write_increments_version_by_one_and_no_read_ever_does
    """
    fx.park_clock(api)
    campaign = fx.create_draft_campaign(api)
    campaign_id = campaign["id"]
    assert_version_is(campaign, 1)
    assert_version_is(fx.read_campaign(api, campaign_id), 1)

    fx.add_legislator(api, campaign_id)
    launched = fx.launch_campaign(api, campaign_id)
    assert_version_is(launched, 2)
    assert_field(launched, "status", CAMPAIGN_ACTIVE)

    frozen = validate_success(api.override_posture(
        campaign_id,
        F.posture_override_payload(
            POSTURE_OVERRIDE_FORCE_FROZEN,
            override_reason="hold all outbound during the audit"),
        headers=make_campaign_director_headers()))
    assert_version_is(frozen, 3)
    assert_field(frozen, "posture", POSTURE_FROZEN)
    read_back = validate_success(api.get_campaign(
        campaign_id, headers=make_compliance_officer_headers()))
    assert_version_is(read_back, 3)

    variant = validate_success(
        api.create_variant(
            F.variant_payload(campaign_id,
                              headline="Vote yes on HB-1420",
                              body="Ask your representative to vote yes on HB-1420.",
                              channel_scope=[CHANNEL_EMAIL]),
            headers=make_message_strategist_headers()),
        expected_status=201)
    variant_id = variant["id"]
    assert_version_is(variant, 1)

    submitted = fx.submit_variant(api, variant_id,
                                 submission_note="ready for review")
    assert_version_is(submitted, 2)
    mid_read = validate_success(api.get_variant(
        variant_id, headers=make_compliance_officer_headers()))
    assert_version_is(mid_read, 2)

    reviewed = fx.review_variant(api, variant_id, REVIEW_DECISION_APPROVE,
                                review_note="copy is compliant")
    assert_version_is(reviewed, 3)
    assert_field(fx.read_variant(api, variant_id), "status", VARIANT_APPROVED)


def test_the_dispute_deducts_the_counters_once_and_the_voiding_adds_nothing(api):
    """Three readings of the same aggregates: 2, then 1, then still 1.

    PRD: "The same request also refreshes two campaign totals as part of this pass: `total_actions_logged`, the number of the campaign's action records whose `status` is `MATCHED`, `ACKNOWLEDGED` or `THANKED`; and `distinct_acting_supporter_count`, the number of distinct supporters appearing on those same rows."

    PRD: "Both edges carry identical consequences: the row leaves the counted input set, so the legislator's `constituent_action_count` and `contact_pressure_score` are recomputed and `priority_tier` re-derived; the supporter's `action_count`, `engagement_score` and `retention_score` are recomputed; the campaign counters are recomputed and the posture derivation re-runs; and the record's `version` increments by 1."

    PRD: "`VOIDED` instead makes the record terminally `VOIDED`, with the legislator, supporter and campaign counters recomputed with the record permanently excluded."

    PRD: "Start by collecting the action records pointing at this legislator whose `status` is `MATCHED`, `ACKNOWLEDGED` or `THANKED`; `UNMATCHED`, `DISPUTED` and `VOIDED` rows are excluded entirely."

    PRD: "If that set is empty, the record's `pressure_multiplier` is 1.0."

    Design: Corner/cross-cutting complexity layers/campaign_and_legislator_counters_reconcile_after_a_disputed_action_is_voided
    """
    world = fx.create_active_campaign(api)
    campaign_id = world["campaign_id"]
    legislator_id = world["legislator_id"]
    supporter_one = fx.add_supporter(api, campaign_id)
    supporter_two = fx.add_supporter(api, campaign_id, full_name="Sup Two",
                                    email="s2@example.org",
                                    acquisition_source=ACQUISITION_EVENT)
    first = fx.log_action(api, supporter_one["id"])
    second = fx.log_action(api, supporter_two["id"])
    assert_score(second["pressure_multiplier"], 1.0)

    created = fx.read_campaign(api, campaign_id)
    assert_count(created["total_actions_logged"], 2)
    assert_count(created["distinct_acting_supporter_count"], 2)
    pressured = fx.read_legislator(api, legislator_id)
    assert_score(pressured["contact_pressure_score"], 14.00)
    assert_count(pressured["constituent_action_count"], 2)

    validate_success(api.dispute_action(
        second["id"],
        F.dispute_payload(
            dispute_reason="the supporter says they never sent this message"),
        headers=make_compliance_officer_headers()))

    disputed = fx.read_campaign(api, campaign_id)
    assert_count(disputed["total_actions_logged"], 1)
    assert_count(disputed["distinct_acting_supporter_count"], 1)
    after_dispute = fx.read_legislator(api, legislator_id)
    assert_score(after_dispute["contact_pressure_score"], 12.00)
    assert_field(after_dispute, "priority_tier", TIER_MONITOR)

    resolved = validate_success(api.resolve_dispute(
        second["id"],
        F.dispute_resolution_payload(
            DISPUTE_OUTCOME_VOIDED,
            resolution_note="no delivery evidence in the wave log"),
        headers=make_campaign_director_headers()))
    assert_field(resolved, "status", ACTION_VOIDED)

    voided = fx.read_campaign(api, campaign_id)
    assert_count(voided["total_actions_logged"], 1)
    assert_count(voided["distinct_acting_supporter_count"], 1)
    final = fx.read_legislator(api, legislator_id)
    assert_score(final["contact_pressure_score"], 12.00)
    assert_count(final["constituent_action_count"], 1)
    assert_field(fx.read_action_record(api, first["id"]), "status", ACTION_MATCHED)
    assert_score(fx.read_supporter(api, supporter_one["id"])["engagement_score"],
                 2.00)
    kept = fx.read_supporter(api, supporter_two["id"])
    assert_score(kept["engagement_score"], 2.00)
    assert_count(kept["action_count"], 0)
