"""The competition-result fork, the protest loop and the record-claim gate."""
from test_helpers import (
    ApiErrorId,
    api_client,
    REGISTRATION_OFFICER_USER_ID,
    RECORDS_RATIFIER_USER_ID,
    age_group_record_payload,
    file_record_claim,
    get_event,
    get_record,
    make_athlete_headers,
    make_records_ratifier_headers,
    make_registration_officer_headers,
    setup_pending_record_claim,
    setup_submitted_result,
    validate_error,
    validate_paginated,
    validate_success,
    verify_result,
)

OFFICER = make_registration_officer_headers(REGISTRATION_OFFICER_USER_ID)
RATIFIER = make_records_ratifier_headers(RECORDS_RATIFIER_USER_ID)


def test_verification_forks_to_record_pending_when_no_record_yet_stands():
    """PRD §3.7: "A `RegistrationOfficer` verifies the mark, and the service compares it
    against the standing age-group record of the event: the record branch applies when
    the event's `current_record_id` is null, so that no record yet stands, or when the
    mark is better than the `mark_value` of the record named by `current_record_id`
    judged by the sport's `mark_direction` — smaller is better where the direction is
    `LOWER_IS_BETTER`, larger is better where it is `HIGHER_IS_BETTER`."
    PRD §3.7: "On that branch the mark moves `SUBMITTED` → `RECORD_PENDING`, which makes
    it eligible for a record claim but explicitly does not publish it."
    PRD §3.7: "Both branches stamp `verified_by_user_id` with the verifying caller's
    `X-User-ID` and both settle `national_qualifying`."
    PRD §3.7: "When that standard is null the event has no national pathway and
    `national_qualifying` is false."

    The record branch applies when the event's `current_record_id` is null, so
    a first mark on a fresh event moves `SUBMITTED` → `RECORD_PENDING` rather
    than to `VERIFIED`.  That branch confers record eligibility and explicitly
    does not publish.  `verified_by_user_id` is stamped with the verifying caller
    and `national_qualifying` is settled false, the event having no national
    standard.

    Design: Difficulty/non_linear_state_machine/competition_result_verify_fork_then_protest_remeasure_join
    """
    ctx = setup_submitted_result()
    assert ctx["event"]["current_record_id"] is None
    assert ctx["result"]["status"] == "SUBMITTED"

    verified = validate_success(
        api_client.verify_competition_result(ctx["result"]["id"], OFFICER)
    )

    assert verified["status"] == "RECORD_PENDING"
    assert verified["verified_by_user_id"] == REGISTRATION_OFFICER_USER_ID
    assert verified["national_qualifying"] is False


def test_the_record_arm_joins_at_published_only_once_a_claim_has_been_filed():
    """PRD §3.7: "The record branch is stricter: a `RECORD_PENDING` mark may only move
    `RECORD_PENDING` → `PUBLISHED` when a record claim citing it exists in
    `PENDING_RATIFICATION` or `RATIFIED`, so a record-beating mark cannot appear in the
    published results until the record paperwork has at least been filed."
    PRD §3.7: "The service derives the rest of the row rather than trusting the client:
    `holder_athlete_id` from the athlete behind the cited mark's entry, `age_group_code`
    copied from the event, `mark_value` copied from the cited mark, and
    `superseded_record_id` set to whatever record the event's `current_record_id`
    currently names — the record this claim would displace — or null when no record yet
    stands."
    PRD §3.7: "The claim starts `PENDING_RATIFICATION` with `ratified_by_user_id` null."

    The two arms converge at publication, but the record arm is stricter: a
    `RECORD_PENDING` mark may only be published once a claim citing it exists in
    `PENDING_RATIFICATION`.  The filed claim opens in `PENDING_RATIFICATION`
    copying the mark and the event's band, with no superseded record.

    Design: Difficulty/non_linear_state_machine/competition_result_verify_fork_then_protest_remeasure_join
    """
    ctx = setup_pending_record_claim()
    assert ctx["record"]["status"] == "PENDING_RATIFICATION"
    assert float(ctx["record"]["mark_value"]) == 15.2
    assert ctx["record"]["age_group_code"] == "60-64"
    assert ctx["record"]["superseded_record_id"] is None

    published = validate_success(
        api_client.publish_competition_result(ctx["result"]["id"], OFFICER)
    )

    assert published["status"] == "PUBLISHED"


def test_protesting_a_published_mark_pulls_down_the_pending_claim():
    """PRD §3.7: "A `PUBLISHED` mark moves `PUBLISHED` → `PROTESTED` and additionally pulls
    down the paperwork built on it: every record claim citing that mark which is still
    `PENDING_RATIFICATION` moves to `REJECTED`."
    PRD §3.7: "The athlete supplies the `grounds` for the dispute, and the service
    refuses the protest unless the caller's `X-User-ID` is the `athlete_id` of the entry
    behind the mark."

    A published mark moves `PUBLISHED` → `PROTESTED` on the athlete's own
    protest, and the paperwork built on it comes down with it: every claim citing
    the mark that is still `PENDING_RATIFICATION` moves to `REJECTED`.

    Design: Difficulty/non_linear_state_machine/competition_result_verify_fork_then_protest_remeasure_join
    """
    ctx = setup_pending_record_claim()
    validate_success(api_client.publish_competition_result(ctx["result"]["id"], OFFICER))

    protested = validate_success(
        api_client.protest_competition_result(
            ctx["result"]["id"],
            {"grounds": "Finish-line timing gate misfired on lane 4."},
            make_athlete_headers(ctx["athlete"]["id"]),
        )
    )

    assert protested["status"] == "PROTESTED"
    assert get_record(ctx["record"]["id"])["status"] == "REJECTED"


def test_a_remeasure_returns_the_mark_to_submitted_and_clears_the_verification():
    """PRD §3.7: "A decision of `REMEASURE` accepts a corrected `mark_value` and
    `placement`, rewrites both onto the result, returns it `PROTESTED` → `SUBMITTED`,
    resets `verified_by_user_id` to null and `national_qualifying` to false so the mark
    must be verified again from scratch, and increments `protest_round` by one."
    PRD §3.7: "That closes the loop from `SUBMITTED` through verification and protest
    back to `SUBMITTED`, and because the protest gate demands a `protest_round` of zero,
    the loop can be travelled at most once."

    Resolving the protest by `REMEASURE` rewrites `mark_value` and
    `placement`, returns the mark `PROTESTED` → `SUBMITTED`, resets
    `verified_by_user_id` to null and `national_qualifying` to false so the mark
    must be verified again from scratch, and increments `protest_round` to 1 —
    closing the loop, which the protest gate allows to be travelled only once.

    Design: Difficulty/non_linear_state_machine/competition_result_verify_fork_then_protest_remeasure_join
    """
    ctx = setup_pending_record_claim()
    validate_success(api_client.publish_competition_result(ctx["result"]["id"], OFFICER))
    validate_success(
        api_client.protest_competition_result(
            ctx["result"]["id"],
            {"grounds": "Finish-line timing gate misfired on lane 4."},
            make_athlete_headers(ctx["athlete"]["id"]),
        )
    )

    resolved = validate_success(
        api_client.resolve_protest(
            ctx["result"]["id"],
            {"decision": "REMEASURE", "mark_value": 15.4, "placement": 2},
            OFFICER,
        )
    )

    assert resolved["status"] == "SUBMITTED"
    assert float(resolved["mark_value"]) == 15.4
    assert resolved["placement"] == 2
    assert resolved["protest_round"] == 1
    assert resolved["verified_by_user_id"] is None
    assert resolved["national_qualifying"] is False


def test_a_claim_on_a_merely_submitted_mark_is_refused():
    """PRD §3.7: "The cited mark must be `RECORD_PENDING` or `PUBLISHED`, and citing
    anything else is refused with `ERR_RESULT_NOT_RECORD_ELIGIBLE`."
    PRD §3.7: "The claim names its `sport_event_id`, the `competition_result_id` it
    cites, the `claimed_by_user_id` of the person filing it, and an
    `expected_sport_event_version` that must match the event's current `version` — a
    mismatch is `ERR_STALE_SPORT_EVENT_VERSION`, and a successful filing increments that
    event's `version`."
    PRD §3.7: "On success the claim moves `PENDING_RATIFICATION` → `RATIFIED`,
    `ratified_by_user_id` is stamped with the acting caller, the event's
    `current_record_id` is repointed at this claim, and the prior record named by this
    claim's `superseded_record_id`, where that pointer is not null, moves `RATIFIED` →
    `SUPERSEDED`."

    The claim's version guard is satisfied — the expected version is read from
    the event immediately beforehand — yet the claim is refused because the cited
    mark is only `SUBMITTED` and record eligibility demands `RECORD_PENDING` or
    `PUBLISHED`.  No claim row is written and the event's `current_record_id`
    stays null.

    Design: Difficulty/cross_entity_state_dependency/record_claim_requires_result_record_eligible_dimension
    """
    ctx = setup_submitted_result()
    event = get_event(ctx["event"]["id"])
    assert ctx["result"]["status"] == "SUBMITTED"
    assert event["current_record_id"] is None

    response = api_client.create_age_group_record(
        age_group_record_payload(
            event["id"], ctx["result"]["id"], RECORDS_RATIFIER_USER_ID, event["version"]
        ),
        RATIFIER,
    )

    validate_error(response, ApiErrorId.ERR_RESULT_NOT_RECORD_ELIGIBLE.value, expected_status=409)
    rows, _meta = validate_paginated(
        api_client.list_age_group_records(RATIFIER, {"limit": 100, "offset": 0})
    )
    assert rows == []
    assert get_event(ctx["event"]["id"])["current_record_id"] is None


def test_the_identical_claim_succeeds_once_the_mark_is_record_eligible():
    """PRD §3.7: "The cited mark must be `RECORD_PENDING` or `PUBLISHED`, and citing
    anything else is refused with `ERR_RESULT_NOT_RECORD_ELIGIBLE`."
    PRD §3.7: "On that branch the mark moves `SUBMITTED` → `RECORD_PENDING`, which makes
    it eligible for a record claim but explicitly does not publish it."
    PRD §3.7: "The service derives the rest of the row rather than trusting the client:
    `holder_athlete_id` from the athlete behind the cited mark's entry, `age_group_code`
    copied from the event, `mark_value` copied from the cited mark, and
    `superseded_record_id` set to whatever record the event's `current_record_id`
    currently names — the record this claim would displace — or null when no record yet
    stands."
    PRD §3.7: "On success the claim moves `PENDING_RATIFICATION` → `RATIFIED`,
    `ratified_by_user_id` is stamped with the acting caller, the event's
    `current_record_id` is repointed at this claim, and the prior record named by this
    claim's `superseded_record_id`, where that pointer is not null, moves `RATIFIED` →
    `SUPERSEDED`."

    Verifying the mark changes nothing on the claim side, yet the same claim
    now succeeds: the mark's move to `RECORD_PENDING` is the whole difference.
    The new claim derives its holder, band and mark from the cited rows, and the
    event's `current_record_id` remains null because only ratification sets it.

    Design: Difficulty/cross_entity_state_dependency/record_claim_requires_result_record_eligible_dimension
    """
    ctx = setup_submitted_result()
    verified = verify_result(ctx["result"]["id"])
    assert verified["status"] == "RECORD_PENDING"

    record = file_record_claim(
        ctx["event"]["id"], ctx["result"]["id"], RECORDS_RATIFIER_USER_ID
    )

    assert record["status"] == "PENDING_RATIFICATION"
    assert float(record["mark_value"]) == 15.2
    assert record["age_group_code"] == "60-64"
    assert record["holder_athlete_id"] == ctx["athlete"]["id"]
    assert record["superseded_record_id"] is None
    assert get_event(ctx["event"]["id"])["current_record_id"] is None
