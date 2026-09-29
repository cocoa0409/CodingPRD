"""Declared edges, refused edges and terminal states.

Lifecycle preconditions, non-idempotent triggers, terminal-state lockdown, the
two independent dimensions a wave advances on, and the zero-quantity and
empty-pool branches that route a row somewhere other than the happy path.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACTIVATION_IN_FLIGHT,
    ERR_CAMPAIGN_NOT_ACTIVE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NO_TARGET_LEGISLATOR,
)
from test_helpers.assertions import (
    assert_absent_or_none,
    assert_count,
    assert_field,
    assert_page,
    assert_score,
    assert_version_is,
)
from test_helpers.test_users import (
    USER_MESSAGE_STRATEGIST,
    make_campaign_director_headers,
    make_field_organizer_headers,
    make_message_strategist_headers,
)
from test_helpers.types import (
    ACTION_MATCHED,
    ACTION_UNMATCHED,
    ACTION_VOIDED,
    APPROVAL_CLEARED,
    APPROVAL_PENDING,
    CAMPAIGN_ACTIVE,
    CAMPAIGN_CLOSED,
    CAMPAIGN_DRAFT,
    CHANNEL_EMAIL,
    DELIVERY_SCHEDULED,
    DELIVERY_SENDING,
    DISPUTE_OUTCOME_VOIDED,
    MEETING_DECISION_CONFIRM,
    MEETING_DECISION_DECLINE,
    MEETING_DECLINED,
    MEETING_NO_SHOW,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    TIER_MONITOR,
    VARIANT_DRAFT,
    VARIANT_IN_REVIEW,
    VARIANT_LOCKED,
)

MEETING_START = "2026-08-10T14:00:00Z"
MEETING_END = "2026-08-10T15:00:00Z"
AFTER_MEETING = "2026-08-10T16:00:00Z"


def test_launching_a_campaign_with_an_empty_target_list_is_refused(api):
    """The target list is the launch precondition, not a formality.

    PRD: "It has two preconditions: the campaign must currently be in `DRAFT`, and at least one legislator row must exist whose `campaign_id` names this campaign — a campaign with no target legislator is refused with `ERR_NO_TARGET_LEGISLATOR`."

    Design: Corner/state_machines/campaign_launch_with_no_legislator_returns_no_target_legislator
    """
    fx.park_clock(api)
    campaign = fx.create_draft_campaign(api)

    response = api.launch_campaign(campaign["id"],
                                   headers=make_campaign_director_headers())

    validate_error(response, ERR_NO_TARGET_LEGISLATOR, expected_status=409)
    reread = fx.read_campaign(api, campaign["id"])
    assert_field(reread, "status", CAMPAIGN_DRAFT)
    assert_version_is(reread, 1)


def test_a_second_launch_is_refused_rather_than_replayed(api):
    """Launch is a declared edge out of DRAFT only, so it never runs twice.

    PRD: "Launching a `DRAFT` campaign advances `status` from `DRAFT` to `ACTIVE`."
    PRD: "The requested transition is declared for the entity's current state, including terminal-state lockdown and cycle limits — otherwise `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/campaign_launch_applied_twice_returns_invalid_state_transition
    """
    world = fx.create_active_campaign(api)
    assert_field(world["campaign"], "status", CAMPAIGN_ACTIVE)
    assert_version_is(world["campaign"], 2)

    response = api.launch_campaign(world["campaign_id"],
                                   headers=make_campaign_director_headers())

    validate_error(response, ERR_INVALID_STATE_TRANSITION, expected_status=409)
    reread = fx.read_campaign(api, world["campaign_id"])
    assert_field(reread, "status", CAMPAIGN_ACTIVE)
    assert_version_is(reread, 2)


def test_a_closed_campaign_refuses_lifecycle_calls_and_writes_beneath_it(api):
    """Nothing reopens a closed campaign, and nothing new lands under it.

    PRD: "The requested transition is declared for the entity's current state, including terminal-state lockdown and cycle limits — otherwise `ERR_INVALID_STATE_TRANSITION`."
    PRD: "The owning campaign's `status` is `ACTIVE` — otherwise `ERR_CAMPAIGN_NOT_ACTIVE`."

    Design: Corner/state_machines/closed_campaign_refuses_every_further_lifecycle_call
    """
    world = fx.create_active_campaign(api)
    campaign_id = world["campaign_id"]
    closed = fx.close_campaign(api, campaign_id)
    assert_version_is(closed, 3)

    second_close = api.close_campaign(campaign_id,
                                      headers=make_campaign_director_headers())
    relaunch = api.launch_campaign(campaign_id,
                                   headers=make_campaign_director_headers())
    late_supporter = api.create_supporter(
        F.supporter_payload(campaign_id, full_name="Late Lou",
                            email="lou@example.org"),
        headers=make_field_organizer_headers())

    validate_error(second_close, ERR_INVALID_STATE_TRANSITION,
                   expected_status=409)
    validate_error(relaunch, ERR_INVALID_STATE_TRANSITION, expected_status=409)
    validate_error(late_supporter, ERR_CAMPAIGN_NOT_ACTIVE, expected_status=409)
    reread = fx.read_campaign(api, campaign_id)
    assert_field(reread, "status", CAMPAIGN_CLOSED)
    assert_field(reread, "posture", POSTURE_FROZEN)
    assert_version_is(reread, 3)
    listing = api.list_supporters(headers=make_field_organizer_headers(),
                                 params={"campaign_id": campaign_id})
    assert_page(listing, expected_total=0, expected_len=0)


def test_submitting_a_draft_stamps_the_submitter_and_leaves_the_round_alone(api):
    """The round counter advances on review outcomes, not on submission.

    PRD: "A new draft lands in `status` `DRAFT` with `revision_round` of 1 and its `required_endorsement_quorum` computed from the current coalition."
    PRD: "Either way the server records `submitted_by_user_id` as the `X-User-ID` of the submitting request and increments the variant's `version` by 1."

    Design: Corner/state_machines/variant_submit_from_draft_enters_review_and_stamps_submitter
    """
    world = fx.create_active_campaign(api)
    variant = fx.add_variant(api, world["campaign_id"])
    assert_field(variant, "status", VARIANT_DRAFT)
    assert_count(variant["revision_round"], 1)

    submitted = fx.submit_variant(api, variant["id"],
                                  submission_note="ready for review")

    assert_field(submitted, "status", VARIANT_IN_REVIEW)
    assert_field(submitted, "submitted_by_user_id", USER_MESSAGE_STRATEGIST)
    assert_absent_or_none(submitted, "reviewed_by_user_id")
    assert_count(submitted["revision_round"], 1)
    assert_version_is(submitted, 2)


def test_a_close_cannot_orphan_a_send_that_has_already_started(api):
    """A sending wave holds the close off, so no cascade hop fires.

    PRD: "A `CampaignDirector` closes an `ACTIVE` campaign under two preconditions — the campaign's `status` is `ACTIVE`, and no activation of the campaign is in delivery state `SENDING`, otherwise `ERR_ACTIVATION_IN_FLIGHT`."

    Design: Corner/state_machines/campaign_close_while_a_wave_is_sending_returns_activation_in_flight
    """
    world = fx.create_sendable_world(api, supporter_count=1,
                                     channel=CHANNEL_EMAIL)
    sending = fx.create_sending_wave(api, world["campaign_id"],
                                     world["segment_id"], world["variant_id"])

    response = api.close_campaign(world["campaign_id"],
                                  headers=make_campaign_director_headers())

    validate_error(response, ERR_ACTIVATION_IN_FLIGHT, expected_status=409)
    assert_field(fx.read_campaign(api, world["campaign_id"]), "status",
                 CAMPAIGN_ACTIVE)
    wave = fx.read_activation(api, sending["id"])
    assert_field(wave, "delivery_state", DELIVERY_SENDING)
    assert_field(wave, "approval_state", APPROVAL_CLEARED)
    supporter = fx.read_supporter(api, world["supporter_ids"][0])
    assert_count(supporter["touches_reserved"], 1)
    report = fx.read_outcome_report(api, world["campaign_id"])
    assert_field(report, "touch_ledger_balanced", True)


def test_clearance_moves_the_approval_dimension_and_nothing_else(api):
    """Approval and delivery are independent dimensions of one wave.

    PRD: "A `ComplianceOfficer` clears a wave with a `clearance_note`, moving `approval_state` from `PENDING` to `CLEARED`."
    PRD: "Those two dimensions advance on separate triggers and neither is derivable from the other."

    Design: Corner/state_machines/activation_clear_moves_approval_state_only_and_leaves_delivery_state_scheduled
    """
    world = fx.create_sendable_world(api, supporter_count=1,
                                     channel=CHANNEL_EMAIL)
    activation = fx.add_activation(api, world["campaign_id"],
                                   world["segment_id"], world["variant_id"],
                                   channel=CHANNEL_EMAIL, min_viable_reach=1)
    assert_field(activation, "approval_state", APPROVAL_PENDING)
    assert_field(activation, "delivery_state", DELIVERY_SCHEDULED)

    cleared = fx.clear_activation(api, activation["id"],
                                  clearance_note="consent evidence sampled")

    assert_field(cleared, "approval_state", APPROVAL_CLEARED)
    assert_field(cleared, "delivery_state", DELIVERY_SCHEDULED)
    assert_absent_or_none(cleared, "realized_reach")
    assert_count(cleared["projected_reach"], 1)
    supporter = fx.read_supporter(api, world["supporter_ids"][0])
    assert_count(supporter["touches_reserved"], 1)
    assert_count(supporter["touches_consumed"], 0)
    listing = api.list_activations(
        headers=make_campaign_director_headers(),
        params={"campaign_id": world["campaign_id"],
                "approval_state": APPROVAL_CLEARED,
                "delivery_state": DELIVERY_SCHEDULED})
    assert_page(listing, expected_total=1, expected_len=1)


def test_a_meeting_nobody_attended_lands_in_no_show_with_no_credit(api):
    """Zero attendees is a declared branch of complete, not a held meeting.

    PRD: "An `attendee_count` of exactly 0 instead moves the meeting to `NO_SHOW`: `attendee_count` is stored as 0, `pressure_credit` stays 0.00, and **no** legislator or supporter counter changes at all."

    Design: Corner/state_machines/meeting_completed_with_zero_attendees_routes_to_no_show_without_pressure_credit
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"])
    profile = fx.create_certified_spokesperson(api, supporter["id"])
    meeting = fx.add_meeting(api, world["campaign_id"], world["legislator_id"],
                             profile["id"], MEETING_START, MEETING_END)
    fx.respond_to_meeting(api, meeting["id"], MEETING_DECISION_CONFIRM)
    fx.park_clock(api, MEETING_END)

    completed = fx.complete_meeting(api, meeting["id"], 0)

    assert_field(completed, "status", MEETING_NO_SHOW)
    assert_count(completed["attendee_count"], 0)
    assert_score(completed["pressure_credit"], 0.00)
    legislator = fx.read_legislator(api, world["legislator_id"])
    assert_count(legislator["meeting_held_count"], 0)
    assert_score(legislator["contact_pressure_score"], 0.0)
    assert_field(legislator, "priority_tier", TIER_MONITOR)
    assert_field(fx.read_campaign(api, world["campaign_id"]), "posture",
                 POSTURE_OPEN)
    listing = api.list_meetings(headers=make_field_organizer_headers(),
                               params={"campaign_id": world["campaign_id"],
                                       "status": MEETING_NO_SHOW})
    assert_page(listing, expected_total=1, expected_len=1)


def test_a_declined_meeting_can_never_be_completed(api):
    """DECLINED is terminal, so the office's refusal is the end of the row.

    PRD: "Both edges require the meeting to be currently `CONFIRMED` and require the logical clock to be at or after the meeting's `window_end`, otherwise `ERR_INVALID_STATE_TRANSITION` — a meeting cannot be reported before it has ended."
    PRD: "`DECLINED`, `HELD` and `NO_SHOW` are all terminal."

    Design: Corner/state_machines/declined_meeting_cannot_be_completed_afterwards
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"])
    profile = fx.create_certified_spokesperson(api, supporter["id"])
    meeting = fx.add_meeting(api, world["campaign_id"], world["legislator_id"],
                             profile["id"], MEETING_START, MEETING_END)
    declined = fx.respond_to_meeting(api, meeting["id"],
                                     MEETING_DECISION_DECLINE,
                                     decline_reason="office calendar full")
    assert_version_is(declined, 2)
    fx.park_clock(api, AFTER_MEETING)

    response = api.complete_meeting(meeting["id"],
                                    F.meeting_complete_payload(4),
                                    headers=make_field_organizer_headers())

    validate_error(response, ERR_INVALID_STATE_TRANSITION, expected_status=409)
    reread = fx.read_meeting(api, meeting["id"])
    assert_field(reread, "status", MEETING_DECLINED)
    assert_field(reread, "decline_reason", "office calendar full")
    assert_absent_or_none(reread, "attendee_count")
    assert_version_is(reread, 2)
    assert_count(fx.read_legislator(api, world["legislator_id"])["meeting_held_count"], 0)


def test_thanking_a_record_that_was_never_acknowledged_is_refused(api):
    """The thank-you rung is declared out of ACKNOWLEDGED alone.

    PRD: "Five preconditions apply in order: the record's `status` is `ACKNOWLEDGED`, otherwise `ERR_INVALID_STATE_TRANSITION`; the campaign's posture is not `FROZEN`, otherwise `ERR_CAMPAIGN_FROZEN`; the supporter's `suppressed` flag is false, otherwise `ERR_SUPPORTER_SUPPRESSED`; the supporter's resolved consent state for `thank_channel` is `GRANTED`, otherwise `ERR_CONSENT_MISSING`; and the sum of the supporter's `touches_consumed` and `touches_reserved` is strictly below the base allowance of 3 touches, otherwise `ERR_FREQUENCY_CAP_EXHAUSTED`."

    Design: Corner/state_machines/thank_attempted_before_acknowledge_returns_invalid_state_transition
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"])
    record = fx.log_action(api, supporter["id"], channel=CHANNEL_EMAIL)
    assert_field(record, "status", ACTION_MATCHED)

    response = api.thank_action(record["id"], F.thank_payload(CHANNEL_EMAIL),
                               headers=make_field_organizer_headers())

    validate_error(response, ERR_INVALID_STATE_TRANSITION, expected_status=409)
    reread = fx.read_action_record(api, record["id"])
    assert_field(reread, "status", ACTION_MATCHED)
    assert_absent_or_none(reread, "thanked_at")
    assert_absent_or_none(reread, "thank_channel")
    after = fx.read_supporter(api, supporter["id"])
    assert_count(after["touches_consumed"], 0)
    assert_count(after["thanked_count"], 0)
    assert_score(fx.read_legislator(api, world["legislator_id"])["contact_pressure_score"],
                 12.00)


def test_a_dispute_resolved_as_voided_removes_the_record_for_good(api):
    """The voided row leaves every input set, permanently.

    PRD: "`VOIDED` instead makes the record terminally `VOIDED`, with the legislator, supporter and campaign counters recomputed with the record permanently excluded."
    PRD: "Start from the acquisition-source bonus for the supporter's `acquisition_source` (`PETITION` 1.0, `EVENT` 2.0, `DIGITAL_AD` 0.5, `REFERRAL` 1.5)."

    Design: Corner/state_machines/dispute_resolved_as_voided_permanently_removes_record_from_pressure
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"])
    record = fx.log_action(api, supporter["id"], channel=CHANNEL_EMAIL)
    assert_score(fx.read_legislator(api, world["legislator_id"])["contact_pressure_score"],
                 12.00)
    fx.dispute_action(api, record["id"],
                      dispute_reason="two field sheets for one call")

    resolved = fx.resolve_dispute(api, record["id"], DISPUTE_OUTCOME_VOIDED,
                                  resolution_note="confirmed duplicate")

    assert_field(resolved, "status", ACTION_VOIDED)
    legislator = fx.read_legislator(api, world["legislator_id"])
    assert_score(legislator["contact_pressure_score"], 10.00)
    assert_count(legislator["constituent_action_count"], 0)
    assert_field(legislator, "priority_tier", TIER_MONITOR)
    after = fx.read_supporter(api, supporter["id"])
    assert_score(after["engagement_score"], 1.00)
    assert_count(after["action_count"], 0)
    campaign = fx.read_campaign(api, world["campaign_id"])
    assert_count(campaign["total_actions_logged"], 0)
    listing = api.list_action_records(
        headers=make_field_organizer_headers(),
        params={"legislator_id": world["legislator_id"],
                "status": ACTION_VOIDED})
    assert_page(listing, expected_total=1, expected_len=1)


def test_an_action_from_a_district_with_no_office_lands_unmatched(api):
    """An empty candidate pool is an audit row, not a rejection.

    PRD: "If that pool is empty, the record's `status` becomes `UNMATCHED` and its `legislator_id` stays null — this is the selector's empty-pool fallback, the request still succeeds with a 201, and `UNMATCHED` is terminal."
    PRD: "An unmatched action changes nothing else at all: no pressure, engagement or campaign counter moves, because the row exists purely for audit."
    PRD: "If that set is empty, the record's `pressure_multiplier` is 1.0."

    Design: Corner/state_machines/action_record_with_no_legislator_in_the_district_becomes_unmatched
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(api, world["campaign_id"],
                                 district_code="HD-99")

    response = api.create_action_record(
        F.action_record_payload(supporter["id"], channel=CHANNEL_EMAIL),
        headers=make_field_organizer_headers())

    record = validate_success(response, expected_status=201)
    assert_field(record, "status", ACTION_UNMATCHED)
    assert_absent_or_none(record, "legislator_id")
    assert record["pressure_multiplier"] == 1.0
    legislator = fx.read_legislator(api, world["legislator_id"])
    assert_count(legislator["constituent_action_count"], 0)
    assert_count(fx.read_supporter(api, supporter["id"])["action_count"], 0)
    campaign = fx.read_campaign(api, world["campaign_id"])
    assert_count(campaign["total_actions_logged"], 0)
    listing = api.list_action_records(
        headers=make_field_organizer_headers(),
        params={"supporter_id": supporter["id"], "status": ACTION_UNMATCHED})
    assert_page(listing, expected_total=1, expected_len=1)


def test_a_locked_variant_cannot_be_reopened_under_a_live_send(api):
    """The in-flight guard keeps the copy frozen while the wave runs.

    PRD: "The operator-triggered form has three preconditions: the variant is currently `LOCKED`; `revision_round` has not reached the ceiling of 3, otherwise `ERR_REVISION_LIMIT_REACHED`; and no activation carrying this variant is in delivery state `SENDING`, otherwise `ERR_ACTIVATION_IN_FLIGHT`."

    Design: Corner/state_machines/locked_variant_reopen_while_a_wave_is_sending_returns_activation_in_flight
    """
    world = fx.create_sendable_world(api, supporter_count=1,
                                     channel=CHANNEL_EMAIL)
    sending = fx.create_sending_wave(api, world["campaign_id"],
                                     world["segment_id"], world["variant_id"])

    response = api.reopen_variant(
        world["variant_id"],
        F.variant_reopen_payload(reopen_reason="legal wants a softer ask"),
        headers=make_message_strategist_headers())

    validate_error(response, ERR_ACTIVATION_IN_FLIGHT, expected_status=409)
    variant = fx.read_variant(api, world["variant_id"])
    assert_field(variant, "status", VARIANT_LOCKED)
    assert_count(variant["revision_round"], 1)
    wave = fx.read_activation(api, sending["id"])
    assert_field(wave, "approval_state", APPROVAL_CLEARED)
    assert_field(wave, "delivery_state", DELIVERY_SENDING)
    campaign = fx.read_campaign(api, world["campaign_id"])
    assert_count(campaign["blocked_activation_count"], 0)
    assert_field(campaign, "posture", POSTURE_OPEN)
