"""Refusals: which rung of the ladder answers, and what it answers with.

Contactability before consent, the conditional lawful basis, window sanity and
containment, the two uniqueness pairings, collaborator readiness, scope
agreement, the four capacity sub-checks in their declared order, and the two
ladder-ordering contrasts that separate a missing row from a malformed body.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CAMPAIGN_NOT_FOUND,
    ERR_CAMPAIGN_RESTRICTED,
    ERR_CHANNEL_NOT_IN_VARIANT_SCOPE,
    ERR_CONSENT_MISSING,
    ERR_DELIVERY_TALLY_MISMATCH,
    ERR_DISTRICT_MISMATCH,
    ERR_DUPLICATE_ENDORSEMENT,
    ERR_DUPLICATE_SPOKESPERSON,
    ERR_ENDORSEMENT_QUORUM_NOT_MET,
    ERR_FREQUENCY_CAP_EXHAUSTED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WINDOW,
    ERR_LAWFUL_BASIS_INVALID,
    ERR_NO_ELIGIBLE_VARIANT,
    ERR_OUTSIDE_SEND_WINDOW,
    ERR_PARTNER_WITHDRAWN,
    ERR_REACH_BELOW_MINIMUM,
    ERR_SEGMENT_EMPTY,
    ERR_STORY_CONSENT_REQUIRED,
    ERR_SUPPORTER_SUPPRESSED,
    ERR_WINDOW_OUTSIDE_CAMPAIGN,
)
from test_helpers.assertions import (
    assert_absent_or_none,
    assert_cents,
    assert_count,
    assert_field,
    assert_page,
    assert_score,
    assert_version_is,
)
from test_helpers.test_users import (
    make_campaign_director_headers,
    make_compliance_officer_headers,
    make_field_organizer_headers,
    make_message_strategist_headers,
    make_partner_delegate_headers,
)
from test_helpers.types import (
    ACTION_ACKNOWLEDGED,
    ALL_CHANNELS,
    APPROVAL_BLOCKED,
    APPROVAL_CLEARED,
    CAMPAIGN_DRAFT,
    CHANNEL_ALL,
    CHANNEL_EMAIL,
    CHANNEL_PHONE,
    CHANNEL_SMS,
    CONSENT_ACTION_GRANT,
    CONSENT_GRANTED,
    CONSENT_NONE,
    CONSENT_REVOKED,
    DELIVERY_SCHEDULED,
    DELIVERY_SENDING,
    ENDORSEMENT_ACTIVE,
    ENDORSEMENT_REVOKED,
    LAWFUL_BASIS_OPT_IN_FORM,
    MILESTONE_FLOOR_VOTE,
    MILESTONE_SCHEDULED,
    MILESTONE_SIGNING,
    PARTNER_TIER_ALLY,
    PARTNER_TIER_ANCHOR,
    PARTNER_TIER_CORE,
    PARTNER_WITHDRAWN,
    POSTURE_RESTRICTED,
    PUBLICATION_CONSENT_INTERNAL,
    PUBLICATION_CONSENT_PUBLIC,
    PUBLICATION_CONSENT_WITHHELD,
    TEST_CELL_ECONOMIC_FRAME,
    TIER_MONITOR,
    TRAINING_CERTIFIED,
    TRAINING_TRAINED,
    TRAINING_UNTRAINED,
    VARIANT_APPROVED,
    VARIANT_CHANGES_REQUESTED,
    VARIANT_LOCKED,
)


def test_a_phone_action_for_an_email_only_supporter_is_refused_on_that_channel(api):
    """The addressed channel is the record's own channel, not any granted one.

    PRD: "The addressed channel is the action record's `channel` when logging a constituent action, `thank_channel` on the thank-you touch, and `EMAIL` on a district-meeting request; the channel-less spokesperson intake instead requires at least one of `EMAIL`, `SMS` or `PHONE` to be `GRANTED`."

    PRD: "That distinction drives which of two error codes a caller sees: a supporter with all three channels revoked yields `ERR_SUPPORTER_SUPPRESSED`, while a supporter whose addressed channel is `NONE` or `REVOKED` but who still has at least one other channel `GRANTED` yields `ERR_CONSENT_MISSING`."

    PRD: "A new legislator starts with `contact_pressure_score` of 0.00, `priority_tier` `MONITOR`, `constituent_action_count` of 0 and `meeting_held_count` of 0."

    Design: Corner/validations/phone_action_for_an_email_only_supporter_returns_consent_missing
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"],
                                 channels=[CHANNEL_EMAIL], with_phone=True)
    assert_field(supporter, "email_consent_state", CONSENT_GRANTED)
    assert_field(supporter, "phone_consent_state", CONSENT_NONE)

    response = api.create_action_record(
        F.action_record_payload(supporter["id"], channel=CHANNEL_PHONE),
        headers=make_field_organizer_headers())
    validate_error(response, ERR_CONSENT_MISSING, expected_status=422)

    listing = api.list_action_records(
        headers=make_field_organizer_headers(),
        params={"supporter_id": supporter["id"]})
    assert_page(listing, expected_total=0, expected_len=0)
    legislator = fx.read_legislator(api, world["legislator_id"])
    assert_score(legislator["contact_pressure_score"], 0.00)
    assert_count(legislator["constituent_action_count"], 0)
    assert_field(legislator, "priority_tier", TIER_MONITOR)
    after = fx.read_supporter(api, supporter["id"])
    assert_count(after["action_count"], 0)
    assert_score(after["engagement_score"], 1.00)


def test_the_suppression_flag_answers_before_the_channel_consent_state(api):
    """A fully revoked supporter is suppressed, not merely unconsented.

    PRD: "This rung has a strict internal order of its own: first the suppression flag, so a supporter whose `suppressed` value is true is rejected with `ERR_SUPPORTER_SUPPRESSED`; only then the resolved consent state of the addressed channel, which must be `GRANTED` or the rejection is `ERR_CONSENT_MISSING`."

    PRD: "A supporter's `suppressed` flag is true exactly when all three of `email_consent_state`, `sms_consent_state` and `phone_consent_state` are `REVOKED`."

    Design: Corner/validations/suppression_flag_is_checked_before_channel_consent_at_priority_thirteen
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"],
                                 channels=ALL_CHANNELS)
    assert_count(supporter["consent_event_count"], 3)
    wildcard = fx.revoke_consent(api, supporter["id"], CHANNEL_ALL,
                                 source_reference="unsubscribe-link-1")
    assert_count(wildcard["sequence_no"], 4)

    response = api.create_action_record(
        F.action_record_payload(supporter["id"], channel=CHANNEL_EMAIL),
        headers=make_field_organizer_headers())
    validate_error(response, ERR_SUPPORTER_SUPPRESSED, expected_status=422)

    after = fx.read_supporter(api, supporter["id"])
    assert after["suppressed"] is True, "the wildcard revoke suppresses"
    assert_count(after["action_count"], 0)
    legislator = fx.read_legislator(api, world["legislator_id"])
    assert_count(legislator["constituent_action_count"], 0)
    listing = api.list_action_records(
        headers=make_field_organizer_headers(),
        params={"supporter_id": supporter["id"]})
    assert_page(listing, expected_total=0, expected_len=0)


def test_a_lawful_basis_is_required_on_a_grant_and_forbidden_on_a_revoke(api):
    """The rung is conditional on the event's action, in both directions.

    PRD: "14. **Lawful basis.** A consent event whose `action` is `GRANT` supplies a `lawful_basis` drawn from `EXPRESS_WRITTEN`, `OPT_IN_FORM`, `EVENT_CARD` or `VERBAL_RECORDED`, and a `REVOKE` event supplies no `lawful_basis` at all — otherwise `ERR_LAWFUL_BASIS_INVALID`."

    PRD: "The winning event's `action` decides the outcome: `GRANT` resolves to `GRANTED`, `REVOKE` resolves to `REVOKED`."

    Design: Corner/validations/lawful_basis_is_required_on_grant_and_forbidden_on_revoke
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"],
                                 channels=[CHANNEL_EMAIL], with_phone=True)

    grant_without_basis = {
        "supporter_id": supporter["id"],
        "channel": CHANNEL_SMS,
        "action": CONSENT_ACTION_GRANT,
        "source_reference": "sms-optin-1",
    }
    validate_error(
        api.create_consent_event(grant_without_basis,
                                 headers=make_compliance_officer_headers()),
        ERR_LAWFUL_BASIS_INVALID, expected_status=422)

    validate_error(
        api.create_consent_event(
            F.revoke_payload(supporter["id"], CHANNEL_EMAIL,
                             lawful_basis=LAWFUL_BASIS_OPT_IN_FORM,
                             source_reference="unsubscribe-link-1"),
            headers=make_compliance_officer_headers()),
        ERR_LAWFUL_BASIS_INVALID, expected_status=422)

    accepted = validate_success(
        api.create_consent_event(
            F.revoke_payload(supporter["id"], CHANNEL_EMAIL,
                             source_reference="unsubscribe-link-1"),
            headers=make_compliance_officer_headers()),
        expected_status=201)
    assert_count(accepted["sequence_no"], 2)
    assert_absent_or_none(accepted, "lawful_basis")

    after = fx.read_supporter(api, supporter["id"])
    assert_field(after, "email_consent_state", CONSENT_REVOKED)
    assert_field(after, "sms_consent_state", CONSENT_NONE)
    assert after["suppressed"] is False, "one revoked channel is not suppression"
    assert_count(after["consent_event_count"], 2)


def test_an_inverted_window_and_a_window_carrying_seconds_are_both_invalid(api):
    """Rung 15 owns both defects, and rung 5 lets a parseable pair through.

    PRD: "15. **Window sanity.** `window_start` is strictly before `window_end` and both bounds are aligned to a whole minute — otherwise `ERR_INVALID_WINDOW`."

    PRD: "The *order* of two parseable window bounds is deliberately **not** checked here: a well-typed but inverted window passes this rung and is caught at rung 15, so it surfaces as `ERR_INVALID_WINDOW`, never as `ERR_INVALID_REQUEST`."

    PRD: "`pressure_multiplier` is taken verbatim from the calendar-weight table: a `COMMITTEE_HEARING` window is worth 1.5, a `FLOOR_VOTE` window 2.0, a `RECESS` window 0.5, and a `SIGNING` window 1.0."

    Design: Corner/validations/milestone_window_must_be_ordered_and_minute_aligned
    """
    fx.park_clock(api)
    campaign = fx.create_draft_campaign(api)
    assert_field(campaign, "status", CAMPAIGN_DRAFT)
    campaign_id = campaign["id"]

    validate_error(
        api.create_milestone(
            F.milestone_payload(campaign_id, "2026-09-10T00:00:00Z",
                                "2026-09-01T00:00:00Z",
                                kind=MILESTONE_FLOOR_VOTE,
                                label="Inverted window"),
            headers=make_campaign_director_headers()),
        ERR_INVALID_WINDOW, expected_status=422)

    validate_error(
        api.create_milestone(
            F.milestone_payload(campaign_id, "2026-09-01T00:00:30Z",
                                "2026-09-10T00:00:00Z",
                                kind=MILESTONE_FLOOR_VOTE,
                                label="Unaligned window"),
            headers=make_campaign_director_headers()),
        ERR_INVALID_WINDOW, expected_status=422)

    accepted = validate_success(
        api.create_milestone(
            F.milestone_payload(campaign_id, "2026-09-01T00:00:00Z",
                                "2026-09-10T00:00:00Z",
                                kind=MILESTONE_FLOOR_VOTE,
                                label="Floor vote"),
            headers=make_campaign_director_headers()),
        expected_status=201)
    assert_field(accepted, "status", MILESTONE_SCHEDULED)
    assert accepted["pressure_multiplier"] == 2.0, "a floor vote is worth 2.0"
    assert accepted["is_blackout"] is False, "only a recess is a blackout"
    assert_count(accepted["reschedule_count"], 0)

    listing = api.list_milestones(headers=make_campaign_director_headers(),
                                  params={"campaign_id": campaign_id})
    assert_page(listing, expected_total=1, expected_len=1)


def test_a_january_window_on_a_campaign_ending_in_december_is_uncontained(api):
    """Containment is a separate rung from ordering and answers separately.

    PRD: "16. **Window containment.** The window falls entirely inside the owning campaign's span from `start_date` to `end_date` inclusive — otherwise `ERR_WINDOW_OUTSIDE_CAMPAIGN`."

    Design: Corner/validations/milestone_window_beyond_campaign_end_returns_window_outside_campaign
    """
    fx.park_clock(api)
    campaign = fx.create_draft_campaign(api)
    campaign_id = campaign["id"]
    assert campaign["end_date"].startswith("2026-12-31T00:00:00"), (
        f"the campaign span ends in December, got {campaign['end_date']}")

    response = api.create_milestone(
        F.milestone_payload(campaign_id, "2027-01-05T00:00:00Z",
                            "2027-01-06T00:00:00Z",
                            kind=MILESTONE_SIGNING, label="Bill signing"),
        headers=make_campaign_director_headers())
    validate_error(response, ERR_WINDOW_OUTSIDE_CAMPAIGN, expected_status=422)

    listing = api.list_milestones(headers=make_campaign_director_headers(),
                                  params={"campaign_id": campaign_id})
    assert_page(listing, expected_total=0, expected_len=0)


def test_a_partners_second_endorsement_of_one_variant_is_a_duplicate(api):
    """Uniqueness is over the pairing, and a current pin does not excuse it.

    PRD: "20. **Uniqueness.** At most one `ACTIVE` endorsement exists per partner-and-variant pairing, and at most one spokesperson profile exists per supporter-and-campaign pairing — otherwise `ERR_DUPLICATE_ENDORSEMENT` or `ERR_DUPLICATE_SPOKESPERSON` respectively."

    PRD: "A message variant's `required_endorsement_quorum` is the greater of 1 and the count of the campaign's `ACTIVE` partners multiplied by one half and rounded **up** to a whole number."

    Design: Corner/validations/second_endorsement_by_the_same_partner_returns_duplicate_endorsement
    """
    world = fx.create_active_campaign(api)
    variant = fx.create_approved_variant(api, world["campaign_id"])
    partner = fx.add_partner(api, world["campaign_id"])
    endorsement = fx.endorse_variant(api, partner["id"], variant["id"])
    assert_field(endorsement, "status", ENDORSEMENT_ACTIVE)

    seen = validate_success(api.get_variant(
        variant["id"], headers=make_partner_delegate_headers(partner["id"])))
    response = api.create_endorsement(
        F.endorsement_payload(partner["id"], variant["id"], seen["version"]),
        headers=make_partner_delegate_headers(partner["id"]))
    validate_error(response, ERR_DUPLICATE_ENDORSEMENT, expected_status=409)

    after = fx.read_variant(api, variant["id"])
    assert_count(after["endorsement_count"], 1)
    assert_count(after["required_endorsement_quorum"], 1)
    assert_field(after, "status", VARIANT_APPROVED)
    assert_count(fx.read_partner(api, partner["id"])["active_endorsement_count"], 1)
    assert_field(fx.read_endorsement(api, endorsement["id"]), "status",
                 ENDORSEMENT_ACTIVE)
    listing = api.list_endorsements(
        headers=make_message_strategist_headers(),
        params={"message_variant_id": variant["id"]})
    assert_page(listing, expected_total=1, expected_len=1)


def test_a_second_spokesperson_profile_for_one_supporter_is_a_duplicate(api):
    """A different story and a wider consent do not make a second intake new.

    PRD: "Only one profile may exist per supporter-and-campaign pairing; a second is `ERR_DUPLICATE_SPOKESPERSON`."

    PRD: "A new profile starts `UNTRAINED`, with `training_sessions_completed` at 0 and `media_ready` false."

    PRD: "Opening a spokesperson profile takes `supporter_id` and a `story_summary` of at most 1,000 characters — the collected personal story used in media work and legislator meetings — plus an optional `publication_consent` stating how far the story may travel, drawn from `WITHHELD`, `INTERNAL` and `PUBLIC` and defaulting to `WITHHELD`."

    Design: Corner/validations/second_spokesperson_profile_for_one_supporter_returns_duplicate_spokesperson
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"])
    profile = fx.add_spokesperson(api, supporter["id"])
    assert_field(profile, "publication_consent", PUBLICATION_CONSENT_WITHHELD)
    assert_field(profile, "training_state", TRAINING_UNTRAINED)

    response = api.create_spokesperson(
        F.spokesperson_payload(
            supporter["id"],
            story_summary="A second version of the same story.",
            publication_consent=PUBLICATION_CONSENT_PUBLIC),
        headers=make_field_organizer_headers())
    validate_error(response, ERR_DUPLICATE_SPOKESPERSON, expected_status=409)

    after = fx.read_spokesperson(api, profile["id"])
    assert_field(after, "publication_consent", PUBLICATION_CONSENT_WITHHELD)
    assert_count(after["training_sessions_completed"], 0)
    assert after["media_ready"] is False, "an untrained profile is not ready"
    listing = api.list_spokespersons(headers=make_field_organizer_headers(),
                                     params={"supporter_id": supporter["id"]})
    assert_page(listing, expected_total=1, expected_len=1)


def test_certification_needs_public_story_consent_and_internal_is_not_enough(api):
    """The certification rung reads the consent field, not just the ladder rung.

    PRD: "Advancing to `CERTIFIED` requires the profile to be currently `TRAINED`, otherwise `ERR_INVALID_STATE_TRANSITION`, and additionally requires `publication_consent` to be exactly `PUBLIC`, otherwise `ERR_STORY_CONSENT_REQUIRED` — a campaign may not certify a spokesperson whose story it is not allowed to publish."

    PRD: "`media_ready` is true exactly when `training_state` is `CERTIFIED` **and** `publication_consent` is `PUBLIC`."

    Design: Corner/validations/certification_without_public_story_consent_returns_story_consent_required
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"])
    profile = fx.add_spokesperson(
        api, supporter["id"],
        publication_consent=PUBLICATION_CONSENT_INTERNAL)
    trained = fx.advance_training(api, profile["id"], TRAINING_TRAINED)
    assert_field(trained, "training_state", TRAINING_TRAINED)

    response = api.advance_training(
        profile["id"],
        F.training_advancement_payload(
            TRAINING_CERTIFIED, session_reference="certification-2026-08"),
        headers=make_field_organizer_headers())
    validate_error(response, ERR_STORY_CONSENT_REQUIRED, expected_status=422)

    after = fx.read_spokesperson(api, profile["id"])
    assert_field(after, "training_state", TRAINING_TRAINED)
    assert_count(after["training_sessions_completed"], 1)
    assert after["media_ready"] is False, "an uncertified profile is not ready"
    assert_score(fx.read_supporter(api, supporter["id"])["engagement_score"],
                 2.00)


def test_a_meeting_booked_in_the_wrong_district_is_refused_after_readiness(api):
    """A certified spokesperson does not rescue a mis-districted booking.

    PRD: "23. **Scope agreement.** Co-referenced rows agree: all foreign keys in one request resolve to the same campaign or the rejection is `ERR_CAMPAIGN_MISMATCH`; the activation `channel` appears in the variant's `channel_scope` or the rejection is `ERR_CHANNEL_NOT_IN_VARIANT_SCOPE`; and a meeting's lead spokesperson's supporter lives in the addressed legislator's district or the rejection is `ERR_DISTRICT_MISMATCH`."

    PRD: "Two agreement rules also bite: `location_district_code` must equal the legislator's `district_code`, and the lead spokesperson's supporter must live in that same district, with either mismatch reported as `ERR_DISTRICT_MISMATCH`."

    Design: Corner/validations/meeting_location_outside_the_legislator_district_returns_district_mismatch
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"])
    profile = fx.create_certified_spokesperson(api, supporter["id"])
    assert_field(profile, "training_state", TRAINING_CERTIFIED)
    assert profile["media_ready"] is True, "a public certified story is ready"

    response = api.create_meeting(
        F.meeting_payload(world["campaign_id"], world["legislator_id"],
                          profile["id"], "2026-08-20T15:00:00Z",
                          "2026-08-20T16:00:00Z",
                          location_district_code="HD-77"),
        headers=make_field_organizer_headers())
    validate_error(response, ERR_DISTRICT_MISMATCH, expected_status=422)

    listing = api.list_meetings(headers=make_field_organizer_headers(),
                                params={"campaign_id": world["campaign_id"]})
    assert_page(listing, expected_total=0, expected_len=0)
    assert_count(fx.read_legislator(api, world["legislator_id"])["meeting_held_count"], 0)
    assert_score(fx.read_supporter(api, supporter["id"])["engagement_score"],
                 4.00)


def test_an_sms_wave_on_an_email_only_variant_is_out_of_scope(api):
    """Scope agreement answers before any capacity arithmetic is attempted.

    PRD: "23. **Scope agreement.** Co-referenced rows agree: all foreign keys in one request resolve to the same campaign or the rejection is `ERR_CAMPAIGN_MISMATCH`; the activation `channel` appears in the variant's `channel_scope` or the rejection is `ERR_CHANNEL_NOT_IN_VARIANT_SCOPE`; and a meeting's lead spokesperson's supporter lives in the addressed legislator's district or the rejection is `ERR_DISTRICT_MISMATCH`."

    Design: Corner/validations/sms_wave_on_an_email_only_variant_returns_channel_not_in_variant_scope
    """
    world = fx.create_sendable_world(
        api, supporter_count=1, channels=[CHANNEL_EMAIL, CHANNEL_SMS],
        channel=CHANNEL_SMS,
        variant_overrides={"channel_scope": [CHANNEL_EMAIL]})
    segment = fx.read_segment(api, world["segment_id"])
    assert_count(segment["member_count"], 1)
    segment_version = segment["version"]
    assert_field(fx.read_variant(api, world["variant_id"]), "status",
                 VARIANT_LOCKED)

    response = api.create_activation(
        F.activation_payload(world["campaign_id"], world["segment_id"],
                             world["variant_id"], "2026-08-05T09:00:00Z",
                             "2026-08-05T17:00:00Z", segment_version,
                             channel=CHANNEL_SMS, min_viable_reach=1),
        headers=make_campaign_director_headers())
    validate_error(response, ERR_CHANNEL_NOT_IN_VARIANT_SCOPE,
                   expected_status=422)

    listing = api.list_activations(
        headers=make_campaign_director_headers(),
        params={"campaign_id": world["campaign_id"]})
    assert_page(listing, expected_total=0, expected_len=0)
    assert_count(fx.read_supporter(api, world["supporter_ids"][0])["touches_reserved"], 0)
    after = fx.read_segment(api, world["segment_id"])
    assert_count(after["active_activation_count"], 0)
    assert_version_is(after, segment_version)


def test_a_wave_over_an_empty_segment_stops_at_the_first_capacity_sub_check(api):
    """An empty membership snapshot answers before any reach arithmetic.

    PRD: "24. **Capacity, reach and budget.** Last of all, capacity floors, again with a strict internal order: an activation targeting a segment whose `member_count` is 0 is refused with `ERR_SEGMENT_EMPTY`; a `projected_reach` that evaluates to 0 because every member already sits at or above the wave's `effective_touch_cap` is refused with `ERR_FREQUENCY_CAP_EXHAUSTED`; a `projected_reach` greater than 0 but strictly below `min_viable_reach` is refused with `ERR_REACH_BELOW_MINIMUM`; and a `delivered_count` reported at completion that exceeds `projected_reach` is refused with `ERR_DELIVERY_TALLY_MISMATCH`."

    Design: Corner/validations/wave_over_an_empty_segment_returns_segment_empty_before_any_reach_check
    """
    world = fx.create_sendable_world(
        api, supporter_count=1, channels=[CHANNEL_EMAIL],
        channel=CHANNEL_SMS,
        variant_overrides={"channel_scope": [CHANNEL_EMAIL, CHANNEL_SMS]})
    segment = fx.read_segment(api, world["segment_id"])
    assert_count(segment["member_count"], 0)

    response = api.create_activation(
        F.activation_payload(world["campaign_id"], world["segment_id"],
                             world["variant_id"], "2026-08-05T09:00:00Z",
                             "2026-08-05T17:00:00Z", segment["version"],
                             channel=CHANNEL_SMS, min_viable_reach=1),
        headers=make_campaign_director_headers())
    validate_error(response, ERR_SEGMENT_EMPTY, expected_status=409)

    listing = api.list_activations(
        headers=make_campaign_director_headers(),
        params={"campaign_id": world["campaign_id"]})
    assert_page(listing, expected_total=0, expected_len=0)
    after = fx.read_segment(api, world["segment_id"])
    assert_count(after["member_count"], 0)
    assert_count(after["active_activation_count"], 0)
    assert_count(fx.read_supporter(api, world["supporter_ids"][0])["touches_reserved"], 0)


def test_a_reach_of_one_under_a_minimum_of_two_is_below_the_floor(api):
    """The floor comparison is strict, and the refusal leaves no reservation.

    PRD: "24. **Capacity, reach and budget.** Last of all, capacity floors, again with a strict internal order: an activation targeting a segment whose `member_count` is 0 is refused with `ERR_SEGMENT_EMPTY`; a `projected_reach` that evaluates to 0 because every member already sits at or above the wave's `effective_touch_cap` is refused with `ERR_FREQUENCY_CAP_EXHAUSTED`; a `projected_reach` greater than 0 but strictly below `min_viable_reach` is refused with `ERR_REACH_BELOW_MINIMUM`; and a `delivered_count` reported at completion that exceeds `projected_reach` is refused with `ERR_DELIVERY_TALLY_MISMATCH`."

    PRD: "The surviving identifiers become `target_supporter_ids` in that same order, `projected_reach` is the length of that list, and every one of those supporters has `touches_reserved` incremented by 1, taking the reservation that later paths must compensate."

    Design: Corner/validations/projected_reach_of_one_under_a_minimum_of_two_returns_reach_below_minimum
    """
    world = fx.create_sendable_world(api, supporter_count=1)
    segment = fx.read_segment(api, world["segment_id"])
    assert_count(segment["member_count"], 1)
    segment_version = segment["version"]

    response = api.create_activation(
        F.activation_payload(world["campaign_id"], world["segment_id"],
                             world["variant_id"], "2026-08-05T09:00:00Z",
                             "2026-08-05T17:00:00Z", segment_version,
                             channel=CHANNEL_EMAIL, min_viable_reach=2),
        headers=make_campaign_director_headers())
    validate_error(response, ERR_REACH_BELOW_MINIMUM, expected_status=409)

    listing = api.list_activations(
        headers=make_campaign_director_headers(),
        params={"campaign_id": world["campaign_id"]})
    assert_page(listing, expected_total=0, expected_len=0)
    assert_count(fx.read_supporter(api, world["supporter_ids"][0])["touches_reserved"], 0)
    after = fx.read_segment(api, world["segment_id"])
    assert_count(after["active_activation_count"], 0)
    assert_version_is(after, segment_version)


def test_a_cleared_wave_refuses_to_start_early_and_starts_on_the_lower_bound(api):
    """The send window is closed on both ends against the logical clock.

    PRD: "Starting a send moves `delivery_state` from `SCHEDULED` to `SENDING` and has five preconditions: the wave is currently `SCHEDULED`; its `approval_state` is `CLEARED`, otherwise `ERR_INVALID_STATE_TRANSITION`; the campaign's posture is not `FROZEN`, otherwise `ERR_CAMPAIGN_FROZEN`; the campaign's posture is not `RESTRICTED` when the wave's `channel` is `SMS` or `PHONE`, otherwise `ERR_CAMPAIGN_RESTRICTED`; and the logical clock sits inside the wave's closed send window, at or after `window_start` and at or before `window_end`, otherwise `ERR_OUTSIDE_SEND_WINDOW`."

    Design: Corner/validations/start_send_before_the_window_opens_returns_outside_send_window
    """
    world = fx.create_sendable_world(api, supporter_count=1)
    activation = fx.add_activation(api, world["campaign_id"],
                                   world["segment_id"], world["variant_id"])
    cleared = fx.clear_activation(api, activation["id"])
    assert_field(cleared, "approval_state", APPROVAL_CLEARED)
    assert_field(cleared, "delivery_state", DELIVERY_SCHEDULED)

    early = api.start_send(activation["id"],
                           headers=make_campaign_director_headers())
    validate_error(early, ERR_OUTSIDE_SEND_WINDOW, expected_status=409)

    fx.park_clock(api, "2026-08-05T09:00:00Z")
    started = validate_success(
        api.start_send(activation["id"],
                       headers=make_campaign_director_headers()))
    assert_field(started, "delivery_state", DELIVERY_SENDING)

    after = fx.read_activation(api, activation["id"])
    assert_count(after["projected_reach"], 1)
    supporter = fx.read_supporter(api, world["supporter_ids"][0])
    assert_count(supporter["touches_reserved"], 1)
    assert_count(supporter["touches_consumed"], 0)


def test_a_withdrawn_partner_cannot_endorse_even_with_a_current_pin(api):
    """Readiness of the named partner is checked, not just the version pin.

    PRD: "22. **Collaborator readiness.** The cross-entity collaborator named in the request is ready: an activation's variant must be `LOCKED` or the rejection is `ERR_VARIANT_NOT_LOCKED`; a district meeting's lead spokesperson must be `CERTIFIED` or the rejection is `ERR_SPOKESPERSON_NOT_CERTIFIED`; a variant lock requires at least the variant's `required_endorsement_quorum` in `ACTIVE` endorsements or the rejection is `ERR_ENDORSEMENT_QUORUM_NOT_MET`; and both endorsement creation and endorsement revocation require the named coalition partner to still be `ACTIVE` or the rejection is `ERR_PARTNER_WITHDRAWN`."

    PRD: "The partner must currently be `ACTIVE`; its `status` becomes `WITHDRAWN`, its `committed_cents` is zeroed, and the funding split re-runs over the remaining active partners so that `committed_share_total_cents` still equals `funded_total_cents`."

    Design: Corner/validations/endorsement_by_a_withdrawn_partner_returns_partner_withdrawn
    """
    world = fx.create_active_campaign(api)
    variant = fx.create_approved_variant(api, world["campaign_id"])
    partners = fx.add_partners(api, world["campaign_id"],
                               [PARTNER_TIER_ANCHOR, PARTNER_TIER_CORE])
    anchor, core = partners[0], partners[1]
    withdrawn = fx.withdraw_partner(api, anchor["id"])
    assert_field(withdrawn, "status", PARTNER_WITHDRAWN)
    assert_cents(withdrawn["committed_cents"], 0)

    pinned = fx.read_variant(api, variant["id"])
    response = api.create_endorsement(
        F.endorsement_payload(anchor["id"], variant["id"], pinned["version"]),
        headers=make_partner_delegate_headers(anchor["id"]))
    validate_error(response, ERR_PARTNER_WITHDRAWN, expected_status=409)

    after = fx.read_variant(api, variant["id"])
    assert_count(after["endorsement_count"], 0)
    assert_count(after["required_endorsement_quorum"], 1)
    assert_cents(fx.read_partner(api, core["id"])["committed_cents"], 100000)
    campaign = fx.read_campaign(api, world["campaign_id"])
    assert_cents(campaign["committed_share_total_cents"], 100000)
    listing = api.list_endorsements(
        headers=make_message_strategist_headers(),
        params={"message_variant_id": variant["id"]})
    assert_page(listing, expected_total=0, expected_len=0)


def test_one_endorsement_under_a_quorum_of_two_cannot_lock_the_copy(api):
    """The quorum is an aggregate over active partners, not a per-partner nod.

    PRD: "Locking is the point at which message discipline becomes enforceable. An `APPROVED` variant moves to `LOCKED` on the single business precondition that its `endorsement_count` is greater than or equal to its `required_endorsement_quorum`; falling short is `ERR_ENDORSEMENT_QUORUM_NOT_MET`."

    PRD: "So a campaign with three active partners requires 2 endorsements, and a campaign with four active partners also requires 2."

    Design: Corner/validations/lock_with_one_endorsement_under_a_quorum_of_two_returns_quorum_not_met
    """
    world = fx.create_active_campaign(api)
    variant = fx.create_approved_variant(api, world["campaign_id"])
    partners = fx.add_partners(
        api, world["campaign_id"],
        [PARTNER_TIER_ANCHOR, PARTNER_TIER_CORE, PARTNER_TIER_ALLY])
    fx.endorse_variant(api, partners[0]["id"], variant["id"])
    before = fx.read_variant(api, variant["id"])
    assert_count(before["required_endorsement_quorum"], 2)
    assert_count(before["endorsement_count"], 1)

    refused = api.lock_variant(variant["id"],
                               headers=make_message_strategist_headers())
    validate_error(refused, ERR_ENDORSEMENT_QUORUM_NOT_MET,
                   expected_status=409)

    fx.endorse_variant(api, partners[1]["id"], variant["id"])
    locked = validate_success(
        api.lock_variant(variant["id"],
                         headers=make_message_strategist_headers()))
    assert_field(locked, "status", VARIANT_LOCKED)

    after = fx.read_variant(api, variant["id"])
    assert_count(after["endorsement_count"], 2)
    assert_count(after["required_endorsement_quorum"], 2)
    assert_count(fx.read_partner(api, partners[2]["id"])["active_endorsement_count"], 0)


def test_resolving_a_test_cell_whose_only_variant_never_locked_finds_no_winner(api):
    """Eligibility to win a test is locked copy, not merely approved copy.

    PRD: "If no variant in the named `test_cell` is `LOCKED`, or if the named winner does not belong to that `test_cell`, the resolution is refused with `ERR_NO_ELIGIBLE_VARIANT`."

    PRD: "`realized_reach_total` is the sum of those waves' `realized_reach`."

    PRD: "`cost_per_action_cents` is the sentinel value 999999 when `attributed_action_count` is 0; otherwise it is `send_cost_total_cents` divided by `attributed_action_count` with any fraction discarded — floored, never rounded."

    Design: Corner/validations/message_test_resolution_naming_an_unlocked_cell_returns_no_eligible_variant
    """
    world = fx.create_active_campaign(api)
    variant = fx.create_approved_variant(api, world["campaign_id"],
                                         test_cell=TEST_CELL_ECONOMIC_FRAME)
    assert_field(variant, "status", VARIANT_APPROVED)

    response = api.resolve_message_test(
        world["campaign_id"],
        F.message_test_resolution_payload(TEST_CELL_ECONOMIC_FRAME,
                                          variant["id"]),
        headers=make_message_strategist_headers())
    validate_error(response, ERR_NO_ELIGIBLE_VARIANT, expected_status=409)

    after = fx.read_variant(api, variant["id"])
    assert_field(after, "status", VARIANT_APPROVED)
    assert_count(after["realized_reach_total"], 0)
    assert_cents(after["cost_per_action_cents"], 999999)


def test_the_fourth_thank_you_touch_exhausts_the_base_allowance(api):
    """A thank-you is a governed touch measured against the base cap of three.

    PRD: "Five preconditions apply in order: the record's `status` is `ACKNOWLEDGED`, otherwise `ERR_INVALID_STATE_TRANSITION`; the campaign's posture is not `FROZEN`, otherwise `ERR_CAMPAIGN_FROZEN`; the supporter's `suppressed` flag is false, otherwise `ERR_SUPPORTER_SUPPRESSED`; the supporter's resolved consent state for `thank_channel` is `GRANTED`, otherwise `ERR_CONSENT_MISSING`; and the sum of the supporter's `touches_consumed` and `touches_reserved` is strictly below the base allowance of 3 touches, otherwise `ERR_FREQUENCY_CAP_EXHAUSTED`."

    PRD: "Note that the thank-you touch is measured against the *base* allowance, never against any wave's surged `effective_touch_cap`."

    PRD: "Multiply that sum by the action pressure factor of 2.0, and take the lesser of the result and the action cap of 60.0; that is the action component."

    Design: Corner/validations/fourth_thank_you_touch_returns_frequency_cap_exhausted
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"])
    records = fx.log_actions(api, supporter["id"], 4)
    for record in records:
        fx.acknowledge_action(api, record["id"])
    for record in records[:3]:
        fx.thank_action(api, record["id"])

    before = fx.read_supporter(api, supporter["id"])
    assert_count(before["touches_consumed"], 3)
    fourth = fx.read_action_record(api, records[3]["id"])
    assert_field(fourth, "status", ACTION_ACKNOWLEDGED)

    response = api.thank_action(records[3]["id"],
                               F.thank_payload(CHANNEL_EMAIL),
                               headers=make_field_organizer_headers())
    validate_error(response, ERR_FREQUENCY_CAP_EXHAUSTED, expected_status=409)

    after_record = fx.read_action_record(api, records[3]["id"])
    assert_field(after_record, "status", ACTION_ACKNOWLEDGED)
    assert_absent_or_none(after_record, "thanked_at")
    after = fx.read_supporter(api, supporter["id"])
    assert_count(after["touches_consumed"], 3)
    assert_count(after["touches_reserved"], 0)
    assert_count(after["thanked_count"], 3)
    legislator = fx.read_legislator(api, world["legislator_id"])
    assert_count(legislator["constituent_action_count"], 4)
    assert_score(legislator["contact_pressure_score"], 18.00)


def test_a_vendor_tally_above_the_target_list_refuses_the_completion(api):
    """The tally must reconcile with the frozen target list, exactly.

    PRD: "Both edges out of `SENDING` share one arithmetic precondition: `delivered_count` plus `bounced_count` must equal the length of `target_supporter_ids`, otherwise `ERR_DELIVERY_TALLY_MISMATCH`."

    PRD: "24. **Capacity, reach and budget.** Last of all, capacity floors, again with a strict internal order: an activation targeting a segment whose `member_count` is 0 is refused with `ERR_SEGMENT_EMPTY`; a `projected_reach` that evaluates to 0 because every member already sits at or above the wave's `effective_touch_cap` is refused with `ERR_FREQUENCY_CAP_EXHAUSTED`; a `projected_reach` greater than 0 but strictly below `min_viable_reach` is refused with `ERR_REACH_BELOW_MINIMUM`; and a `delivered_count` reported at completion that exceeds `projected_reach` is refused with `ERR_DELIVERY_TALLY_MISMATCH`."

    PRD: "`realized_reach_total` is the sum of those waves' `realized_reach`."

    Design: Corner/validations/completion_tally_above_projected_reach_returns_delivery_tally_mismatch
    """
    world = fx.create_sendable_world(api, supporter_count=1)
    sending = fx.create_sending_wave(api, world["campaign_id"],
                                     world["segment_id"], world["variant_id"],
                                     inside_window="2026-08-05T10:00:00Z")
    assert_count(sending["projected_reach"], 1)

    response = api.complete_activation(
        sending["id"], F.activation_complete_payload(2, 0),
        headers=make_campaign_director_headers())
    validate_error(response, ERR_DELIVERY_TALLY_MISMATCH, expected_status=409)

    after = fx.read_activation(api, sending["id"])
    assert_field(after, "delivery_state", DELIVERY_SENDING)
    assert_absent_or_none(after, "realized_reach")
    supporter = fx.read_supporter(api, world["supporter_ids"][0])
    assert_count(supporter["touches_reserved"], 1)
    assert_count(supporter["touches_consumed"], 0)
    assert_count(fx.read_variant(api, world["variant_id"])["realized_reach_total"], 0)


def test_an_unknown_body_foreign_key_answers_before_the_unknown_field(api):
    """Rung 4 answers first, and the same body against a real row shows rung 5.

    PRD: "4. **Body foreign-key existence.** Every foreign key supplied in the request body resolves, checked in the field order the endpoint declares — otherwise the matching not-found code."

    PRD: "5. **Request shape.** The body is well formed: no unknown fields, every required field present, every enum value inside its declared set, integers non-negative where declared non-negative, cent amounts integral, and timestamps parseable as ISO 8601 UTC — otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/validations/unknown_body_fk_returns_404_before_a_malformed_body_returns_invalid_request
    """
    fx.park_clock(api)
    campaign = fx.create_draft_campaign(api)

    ghost = api.create_legislator(
        F.legislator_payload(C.UNKNOWN_UUID, full_name="Rep. Ghost",
                             seniority_rank=3),
        headers=make_campaign_director_headers())
    validate_error(ghost, ERR_CAMPAIGN_NOT_FOUND, expected_status=404)

    malformed = api.create_legislator(
        F.legislator_payload(campaign["id"], seniority_rank=3),
        headers=make_campaign_director_headers())
    validate_error(malformed, ERR_INVALID_REQUEST, expected_status=422)

    listing = api.list_legislators(headers=make_campaign_director_headers(),
                                   params={"campaign_id": campaign["id"]})
    assert_page(listing, expected_total=0, expected_len=0)
    assert_field(fx.read_campaign(api, campaign["id"]), "status",
                 CAMPAIGN_DRAFT)


def test_one_blocked_wave_restricts_the_campaign_and_closes_the_sms_lane(api):
    """A single blocked wave narrows the posture, and rung 10 answers first.

    PRD: "10. **Restricted posture.** When the owning campaign's `posture` is `RESTRICTED`, only `EMAIL` waves remain open: creating, clearing or starting an `SMS` or `PHONE` activation is refused with `ERR_CAMPAIGN_RESTRICTED` while `EMAIL` waves proceed normally."

    PRD: "5. Otherwise, if `blocked_activation_count` is at least 1 or `opposed_priority_legislator_count` is at least 1, the posture is `RESTRICTED`."

    PRD: "Then four hops: the variant's `endorsement_count` is decremented, bumping the variant's `version`; because `endorsement_count` fell below `required_endorsement_quorum` while the variant was `LOCKED`, the variant moves from `LOCKED` to `CHANGES_REQUESTED`; because the variant left `LOCKED`, every activation carrying it in delivery state `SCHEDULED` has its `approval_state` set to `BLOCKED`; and because waves became `BLOCKED`, the campaign's `blocked_activation_count` is recomputed and the posture derivation re-runs."

    Design: Corner/validations/sms_wave_while_one_blocked_wave_holds_the_campaign_restricted
    """
    world = fx.create_sendable_world(
        api, supporter_count=1, channels=[CHANNEL_EMAIL, CHANNEL_SMS],
        channel=CHANNEL_EMAIL,
        variant_overrides={"channel_scope": [CHANNEL_EMAIL, CHANNEL_SMS]})
    campaign_id = world["campaign_id"]
    sms_segment = fx.add_segment(api, campaign_id, name="SMS crowd",
                                 rule_required_channel=CHANNEL_SMS)
    assert_count(sms_segment["member_count"], 1)
    email_wave = fx.add_activation(api, campaign_id, world["segment_id"],
                                   world["variant_id"], channel=CHANNEL_EMAIL)

    revoked = validate_success(api.revoke_endorsement(
        world["endorsement_id"],
        {"revoked_reason": "the board reversed its vote"},
        headers=make_partner_delegate_headers(world["partner_ids"][0])))
    assert_field(revoked, "status", ENDORSEMENT_REVOKED)
    campaign = fx.read_campaign(api, campaign_id)
    assert_field(campaign, "posture", POSTURE_RESTRICTED)
    assert_count(campaign["blocked_activation_count"], 1)

    pinned = fx.read_segment(api, sms_segment["id"])
    response = api.create_activation(
        F.activation_payload(campaign_id, sms_segment["id"],
                             world["variant_id"], "2026-08-06T09:00:00Z",
                             "2026-08-06T17:00:00Z", pinned["version"],
                             channel=CHANNEL_SMS, min_viable_reach=1),
        headers=make_campaign_director_headers())
    validate_error(response, ERR_CAMPAIGN_RESTRICTED, expected_status=409)

    held = fx.read_activation(api, email_wave["id"])
    assert_field(held, "approval_state", APPROVAL_BLOCKED)
    assert_field(held, "delivery_state", DELIVERY_SCHEDULED)
    variant = fx.read_variant(api, world["variant_id"])
    assert_field(variant, "status", VARIANT_CHANGES_REQUESTED)
    assert_count(variant["endorsement_count"], 0)
    listing = api.list_activations(
        headers=make_campaign_director_headers(),
        params={"campaign_id": campaign_id, "channel": CHANNEL_SMS})
    assert_page(listing, expected_total=0, expected_len=0)
    assert_count(fx.read_supporter(api, world["supporter_ids"][0])["touches_reserved"], 1)
