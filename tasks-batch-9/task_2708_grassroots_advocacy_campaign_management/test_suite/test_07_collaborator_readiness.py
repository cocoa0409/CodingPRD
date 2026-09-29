"""Calls refused for something another entity has not done yet.

In both cases the payload never changes between the failing attempt and the
succeeding one. What changes is a write on the collaborator: a variant reaching
LOCKED, and a spokesperson reaching CERTIFIED.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_SPOKESPERSON_NOT_CERTIFIED,
    ERR_VARIANT_NOT_LOCKED,
)
from test_helpers.assertions import assert_count, assert_field, assert_page, assert_score
from test_helpers.test_users import (
    make_campaign_director_headers,
    make_field_organizer_headers,
)
from test_helpers.types import (
    APPROVAL_PENDING,
    CHANNEL_EMAIL,
    CHANNEL_PHONE,
    DELIVERY_SCHEDULED,
    LAWFUL_BASIS_EVENT_CARD,
    ACQUISITION_EVENT,
    MEETING_REQUESTED,
    PUBLICATION_CONSENT_PUBLIC,
    TRAINING_CERTIFIED,
    TRAINING_TRAINED,
    VARIANT_LOCKED,
)


# --------------------------------------------------------------------------
# An activation waits on its variant reaching LOCKED
# --------------------------------------------------------------------------

def _approved_but_unlocked_variant_with_quorum_already_met(api):
    """Copy sitting in APPROVED with its one required endorsement in hand.

    Everything the wave needs is in place except the lock itself, so the only
    reason a create can fail is the variant's own state.
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"],
                                 channels=[CHANNEL_EMAIL])
    segment = fx.add_segment(api, world["campaign_id"],
                             rule_required_channel=CHANNEL_EMAIL)
    partner = fx.add_partner(api, world["campaign_id"])
    variant = fx.create_approved_variant(api, world["campaign_id"],
                                         channel_scope=[CHANNEL_EMAIL])
    fx.endorse_variant(api, partner["id"], variant["id"])
    world.update({"supporter_id": supporter["id"],
                  "segment_id": segment["id"],
                  "partner_id": partner["id"],
                  "variant_id": variant["id"]})
    return world


def _attempt_wave(api, world):
    payload = F.activation_payload(
        world["campaign_id"], world["segment_id"], world["variant_id"],
        "2026-08-05T09:00:00Z", "2026-08-05T17:00:00Z",
        fx.read_segment(api, world["segment_id"])["version"],
        channel=CHANNEL_EMAIL, min_viable_reach=1)
    return api.create_activation(payload,
                                 headers=make_campaign_director_headers())


def test_a_wave_naming_approved_copy_is_refused_and_reserves_nothing(api):
    """Approved is not lockable copy, and the refusal happens before reservation.

    PRD: "Once `LOCKED`, the copy may not be edited, and — critically — only a `LOCKED` variant may be named by an activation."

    Design: Difficulty/cross_entity_state_dependency/activation_create_blocked_until_message_variant_reaches_locked
    """
    world = _approved_but_unlocked_variant_with_quorum_already_met(api)

    response = _attempt_wave(api, world)

    validate_error(response, ERR_VARIANT_NOT_LOCKED, expected_status=409)
    assert_count(fx.read_supporter(api, world["supporter_id"])
                 ["touches_reserved"], 0)


def test_the_single_endorsement_already_satisfies_the_lock_quorum(api):
    """A one-partner coalition needs one endorsement, and locking then succeeds.

    PRD: "An `APPROVED` variant moves to `LOCKED` on the single business precondition that its `endorsement_count` is greater than or equal to its `required_endorsement_quorum`; falling short is `ERR_ENDORSEMENT_QUORUM_NOT_MET`."

    Design: Difficulty/cross_entity_state_dependency/activation_create_blocked_until_message_variant_reaches_locked
    """
    world = _approved_but_unlocked_variant_with_quorum_already_met(api)
    _attempt_wave(api, world)

    locked = fx.lock_variant(api, world["variant_id"])

    assert_count(locked["required_endorsement_quorum"], 1)
    assert_count(locked["endorsement_count"], 1)
    assert_field(locked, "status", VARIANT_LOCKED)


def test_the_identical_payload_succeeds_once_the_copy_is_locked(api):
    """Nothing about the wave changed; the collaborator did.

    PRD: "Creating a wave also increments the segment's `active_activation_count` (bumping the segment's `version`) and lands the wave on both of its independent state dimensions: `approval_state` `PENDING` and `delivery_state` `SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/activation_create_blocked_until_message_variant_reaches_locked
    """
    world = _approved_but_unlocked_variant_with_quorum_already_met(api)
    _attempt_wave(api, world)
    fx.lock_variant(api, world["variant_id"])

    activation = validate_success(_attempt_wave(api, world), expected_status=201)

    assert_count(activation["projected_reach"], 1)
    assert_field(activation, "approval_state", APPROVAL_PENDING)
    assert_field(activation, "delivery_state", DELIVERY_SCHEDULED)
    assert_count(fx.read_supporter(api, world["supporter_id"])
                 ["touches_reserved"], 1)


# --------------------------------------------------------------------------
# A district meeting waits on its spokesperson reaching CERTIFIED
# --------------------------------------------------------------------------

def _trained_but_uncertified_spokesperson(api):
    """A story cleared for publication, its teller one rung short of certified.

    Publication consent is already PUBLIC, so the only thing standing between
    the profile and certification is the second training session.
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(
        api, world["campaign_id"], channels=[CHANNEL_EMAIL, CHANNEL_PHONE],
        full_name="Tess Teller", email="tess@example.org",
        phone="+15551230022", acquisition_source=ACQUISITION_EVENT,
        lawful_basis=LAWFUL_BASIS_EVENT_CARD,
        consent_source_reference="townhall-card-7")
    profile = fx.add_spokesperson(
        api, supporter["id"],
        story_summary="Lost her lease after a 40 percent rent increase.",
        publication_consent=PUBLICATION_CONSENT_PUBLIC)
    fx.advance_training(api, profile["id"], TRAINING_TRAINED)
    world.update({"supporter_id": supporter["id"],
                  "spokesperson_id": profile["id"]})
    return world


def _attempt_meeting(api, world):
    payload = F.meeting_payload(world["campaign_id"], world["legislator_id"],
                               world["spokesperson_id"],
                               "2026-08-10T14:00:00Z", "2026-08-10T15:00:00Z")
    return api.create_meeting(payload, headers=make_field_organizer_headers())


def test_a_trained_profile_is_not_yet_media_ready(api):
    """Media readiness needs certification, not merely training.

    PRD: "`media_ready` is true exactly when `training_state` is `CERTIFIED` **and** `publication_consent` is `PUBLIC`."

    Design: Difficulty/cross_entity_state_dependency/district_meeting_request_blocked_until_spokesperson_reaches_certified
    """
    world = _trained_but_uncertified_spokesperson(api)

    profile = fx.read_spokesperson(api, world["spokesperson_id"])
    assert_field(profile, "training_state", TRAINING_TRAINED)
    assert_field(profile, "media_ready", False)


def test_a_meeting_led_by_a_merely_trained_spokesperson_is_refused(api):
    """The readiness rung reads the collaborator's state, not the payload.

    PRD: "The lead spokesperson must already be `CERTIFIED`, otherwise `ERR_SPOKESPERSON_NOT_CERTIFIED`, and the request is contactability-gated on the supporter's `EMAIL` channel."

    Design: Difficulty/cross_entity_state_dependency/district_meeting_request_blocked_until_spokesperson_reaches_certified
    """
    world = _trained_but_uncertified_spokesperson(api)

    response = _attempt_meeting(api, world)

    validate_error(response, ERR_SPOKESPERSON_NOT_CERTIFIED,
                   expected_status=409)


def test_the_second_session_certifies_the_teller_and_marks_the_story_publishable(api):
    """The write that unblocks the meeting lands on the spokesperson row.

    PRD: "On success `training_state` becomes `CERTIFIED`, `training_sessions_completed` increments by 1, `media_ready` becomes true, the supporter's `engagement_score` and `retention_score` are recomputed because the story bonus rises from 1.0 to 3.0, affected segments are recomputed (bumping their `version`), and the profile's `version` increments by 1."

    Design: Difficulty/cross_entity_state_dependency/district_meeting_request_blocked_until_spokesperson_reaches_certified
    """
    world = _trained_but_uncertified_spokesperson(api)
    _attempt_meeting(api, world)

    certified = fx.advance_training(api, world["spokesperson_id"],
                                    TRAINING_CERTIFIED)

    assert_field(certified, "training_state", TRAINING_CERTIFIED)
    assert_count(certified["training_sessions_completed"], 2)
    assert_field(certified, "media_ready", True)


def test_the_identical_meeting_request_succeeds_once_the_teller_is_certified(api):
    """Only one meeting exists afterwards: the refused attempt left no row.

    PRD: "A new meeting lands in `status` `REQUESTED` with `pressure_credit` of 0.00 and `decline_reason` null."

    Design: Difficulty/cross_entity_state_dependency/district_meeting_request_blocked_until_spokesperson_reaches_certified
    """
    world = _trained_but_uncertified_spokesperson(api)
    _attempt_meeting(api, world)
    fx.advance_training(api, world["spokesperson_id"], TRAINING_CERTIFIED)

    meeting = validate_success(_attempt_meeting(api, world), expected_status=201)

    assert_field(meeting, "status", MEETING_REQUESTED)
    assert_score(meeting["pressure_credit"], 0.00)
    assert_page(api.list_meetings(headers=make_field_organizer_headers(),
                                  params={"campaign_id": world["campaign_id"]}),
                expected_total=1)
    assert_count(fx.read_legislator(api, world["legislator_id"])
                 ["meeting_held_count"], 0)
