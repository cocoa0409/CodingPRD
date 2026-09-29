"""Two machines that loop rather than run forward, and how each loop ends.

A message variant genuinely re-enters review, and only the revision ceiling
stops it going round again. An action record forks on match and then cycles
through dispute and back, and the return leg has to restore the whip count
exactly as it stood.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_REVISION_LIMIT_REACHED
from test_helpers.assertions import assert_count, assert_field, assert_score
from test_helpers.factories import (
    dispute_payload,
    dispute_resolution_payload,
    variant_submit_payload,
)
from test_helpers.test_users import (
    USER_MESSAGE_STRATEGIST,
    make_campaign_director_headers,
    make_compliance_officer_headers,
    make_message_strategist_headers,
)
from test_helpers.types import (
    ACTION_MATCHED,
    CHANNEL_PHONE,
    DISPUTE_OUTCOME_REINSTATED,
    POSTURE_OPEN,
    REVIEW_DECISION_REQUEST_CHANGES,
    TIER_MONITOR,
    VARIANT_CHANGES_REQUESTED,
)


# --------------------------------------------------------------------------
# The review cycle and its terminating condition
# --------------------------------------------------------------------------

def _variant_sent_back_for_changes_twice(api):
    """A variant that has been round the review loop until it sits at the ceiling.

    Each request for changes walks the revision counter up by one, so two of
    them leave the variant waiting for edits with no further round available.
    """
    world = fx.create_active_campaign(api)
    variant = fx.add_variant(api, world["campaign_id"])

    fx.submit_variant(api, variant["id"], submission_note="round one")
    fx.review_variant(api, variant["id"], REVIEW_DECISION_REQUEST_CHANGES,
                      review_note="soften the ask")
    fx.submit_variant(api, variant["id"], submission_note="round two")
    fx.review_variant(api, variant["id"], REVIEW_DECISION_REQUEST_CHANGES,
                      review_note="still off message")

    world["variant_id"] = variant["id"]
    return world


def test_a_further_submission_is_refused_once_the_revision_ceiling_is_reached(api):
    """The ceiling, not a state, is what terminates the review loop.

    PRD: "The resubmission edge additionally requires that `revision_round` has
    not yet reached the ceiling of 3 revision rounds; a fourth attempt is refused
    with `ERR_REVISION_LIMIT_REACHED`, and that ceiling is what terminates the
    cycle."

    Design: Difficulty/non_linear_state_machine/message_variant_revision_cycle_terminates_at_third_round
    """
    world = _variant_sent_back_for_changes_twice(api)

    response = api.submit_variant(
        world["variant_id"], variant_submit_payload(submission_note="round three"),
        headers=make_message_strategist_headers())

    validate_error(response, ERR_REVISION_LIMIT_REACHED, expected_status=409)


def test_the_refused_variant_stays_waiting_for_changes_at_the_third_round(api):
    """A refusal leaves the loop where it was, in a state a line could not re-enter.

    PRD: "`REQUEST_CHANGES` moves it from `IN_REVIEW` to `CHANGES_REQUESTED` and
    increments `revision_round` by 1 — which is what walks the variant towards
    the ceiling."

    Design: Difficulty/non_linear_state_machine/message_variant_revision_cycle_terminates_at_third_round
    """
    world = _variant_sent_back_for_changes_twice(api)

    api.submit_variant(
        world["variant_id"], variant_submit_payload(submission_note="round three"),
        headers=make_message_strategist_headers())

    variant = fx.read_variant(api, world["variant_id"])
    assert_field(variant, "status", VARIANT_CHANGES_REQUESTED)
    assert_count(variant["revision_round"], 3)


def test_the_submitter_recorded_on_the_variant_is_the_one_from_the_last_accepted_submit(api):
    """The refused attempt does not overwrite the stored submitter.

    PRD: "Either way the server records `submitted_by_user_id` as the
    `X-User-ID` of the submitting request and increments the variant's `version`
    by 1."

    Design: Difficulty/non_linear_state_machine/message_variant_revision_cycle_terminates_at_third_round
    """
    world = _variant_sent_back_for_changes_twice(api)

    api.submit_variant(
        world["variant_id"], variant_submit_payload(submission_note="round three"),
        headers=make_message_strategist_headers())

    variant = fx.read_variant(api, world["variant_id"])
    assert_field(variant, "submitted_by_user_id", USER_MESSAGE_STRATEGIST)


# --------------------------------------------------------------------------
# The dispute cycle and pressure conservation
# --------------------------------------------------------------------------

def _matched_phone_action_currently_under_dispute(api):
    """One phone action matched to the district office, then disputed.

    No milestone exists, so the action carries the neutral multiplier, and the
    dispute has already pulled the row out of the whip count.
    """
    world = fx.create_active_campaign(api)
    supporter = fx.add_supporter(
        api, world["campaign_id"], channels=[CHANNEL_PHONE],
        full_name="Cal Caller", email="cal@example.org",
        phone="+15551230011", lawful_basis="VERBAL_RECORDED",
        consent_source_reference="phonebank-3")
    record = fx.log_action(api, supporter["id"], channel=CHANNEL_PHONE)

    api.dispute_action(record["id"],
                       dispute_payload(dispute_reason="possible duplicate call log"),
                       headers=make_compliance_officer_headers())

    world.update({"supporter_id": supporter["id"], "record_id": record["id"]})
    return world


def _reinstate(api, record_id):
    """Settle the dispute in the constituent's favour, as the campaign director."""
    return api.resolve_dispute(
        record_id,
        dispute_resolution_payload(
            DISPUTE_OUTCOME_REINSTATED,
            resolution_note="call log verified against phonebank sheet"),
        headers=make_campaign_director_headers())


def test_reinstating_a_disputed_action_returns_it_to_matched_with_its_stamp_intact(api):
    """The return leg of the loop closes without losing the original stamp.

    PRD: "`REINSTATED` returns the record from `DISPUTED` to `MATCHED`, closing
    the cycle: the original `pressure_multiplier` and `legislator_id` are intact,
    `acknowledged_at` (if any) is preserved even though the record returns to
    `MATCHED` rather than to `ACKNOWLEDGED`, the row re-enters the pressure input
    set so the legislator's counters and `contact_pressure_score` are recomputed
    to exactly their pre-dispute values and `priority_tier` is re-derived, and
    the supporter's `action_count`, `engagement_score` and `retention_score` are
    recomputed."

    Design: Difficulty/non_linear_state_machine/action_record_dispute_reinstate_cycle_returns_to_matched
    """
    world = _matched_phone_action_currently_under_dispute(api)

    _reinstate(api, world["record_id"])

    record = fx.read_action_record(api, world["record_id"])
    assert_field(record, "status", ACTION_MATCHED)
    assert_field(record, "legislator_id", world["legislator_id"])
    assert record["pressure_multiplier"] == 1.0, (
        f"expected the neutral multiplier 1.0, got {record['pressure_multiplier']}")


def test_the_round_trip_restores_the_whip_count_to_its_pre_dispute_value(api):
    """Pressure conservation is what makes the cycle safe to run.

    PRD: "The `MATCHED` to `DISPUTED` to `MATCHED` round trip must leave
    `contact_pressure_score` bit-identical — that is the pressure-conservation
    invariant."

    Design: Difficulty/non_linear_state_machine/action_record_dispute_reinstate_cycle_returns_to_matched
    """
    world = _matched_phone_action_currently_under_dispute(api)

    _reinstate(api, world["record_id"])

    legislator = fx.read_legislator(api, world["legislator_id"])
    assert_score(legislator["contact_pressure_score"], 16.00)
    assert_count(legislator["constituent_action_count"], 1)
    assert_field(legislator, "priority_tier", TIER_MONITOR)


def test_a_reinstated_action_leaves_the_campaign_posture_unnarrowed(api):
    """A monitor-tier office feeds nothing into the posture derivation.

    PRD: "`opposed_priority_legislator_count` is the number of the campaign's
    legislators whose `priority_tier` is `PRIMARY` **and** whose `stance` is
    either `LEAN_OPPOSE` or `OPPOSE`."

    Design: Difficulty/non_linear_state_machine/action_record_dispute_reinstate_cycle_returns_to_matched
    """
    world = _matched_phone_action_currently_under_dispute(api)

    _reinstate(api, world["record_id"])

    campaign = fx.read_campaign(api, world["campaign_id"])
    assert_field(campaign, "posture", POSTURE_OPEN)
