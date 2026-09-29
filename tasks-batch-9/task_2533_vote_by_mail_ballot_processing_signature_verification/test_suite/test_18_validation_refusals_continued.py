"""Refusals of the Vote-By-Mail Processing API, continued.

Each test drives one guarded operation to its documented refusal and then proves
the refusal changed nothing: the state the PRD names is read back, the counters it
names are read back, and the transparency log is checked for the entry that must
not have been appended.
"""
from datetime import datetime

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    address_result_payload,
    api_client,
    assert_address_verification,
    assert_ballot_packet,
    assert_enrollment,
    assert_mailing_batch,
    assert_observer_session,
    assert_return_envelope,
    assert_signature_review,
    assert_voter,
    assert_whole_cents,
    challenge_payload,
    create_ballot_request,
    create_batch,
    create_enrollment,
    create_trained_reviewer,
    create_voter,
    get_accountability,
    get_address_verification_for,
    get_election,
    get_envelope,
    make_observer_headers,
    make_signature_reviewer_headers,
    packet_payload,
    schedule_observer_session,
    separation_run_payload,
    set_clock,
    setup_accepted_envelope,
    setup_approved_request,
    setup_election,
    setup_envelope_with_open_review,
    setup_received_envelopes,
    signature_decision_payload,
    submit_address_result,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["elections_admin_headers"]
CLERK = TEST_USERS["elections_clerk_headers"]
SUPERVISOR = TEST_USERS["canvass_supervisor_headers"]

CLOCK_SEP10 = "2026-09-10T09:00:00Z"
CLOCK_NOV3 = "2026-11-03T12:00:00Z"
MISSING_ID = "00000000-0000-0000-0000-0000000000ff"


def _instant(value):
    """Parse an emitted ISO 8601 UTC instant, tolerating the Z suffix and any
    fractional-second digits, so instants are compared as instants."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _total_count(response):
    """The total_count a list endpoint reports before its page window is applied."""
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def _log_count(election_id, event_type):
    return _total_count(api_client.list_transparency_log(
        ADMIN, params={"election_id": election_id, "event_type": event_type}))


def _get_reviewer(reviewer_id):
    return validate_success(api_client.get_reviewer(reviewer_id, CLERK), 200)


def _get_review(review_id):
    return validate_success(api_client.get_signature_review(review_id, CLERK), 200)


class TestForwardOnlyClock:
    """The logical clock is a ratchet: neither a rewind nor a no-op reset is a legal
    move, and the instant the refusals report stays available for a real step."""

    def test_rewind_and_same_instant_are_both_refused_while_one_second_forward_lands(self):
        """From 2026-11-03T12:00:00Z, a step back to 11:59:59Z and a step to the very same
        instant are both refused, and the clock is still exactly where it was, so a step to
        12:00:01Z succeeds.

        The clock may only move forward: a `to_iso8601` that is not strictly greater than the current logical clock value is rejected with `ERR_CLOCK_REWIND_FORBIDDEN`.

        Design: Corner/validations/clock_cannot_be_rewound_or_reset_to_the_same_instant
        """
        set_clock(CLOCK_SEP10)
        started = set_clock(CLOCK_NOV3)
        assert _instant(started["current_utc"]) == _instant(CLOCK_NOV3)

        rewind = api_client.set_clock("2026-11-03T11:59:59Z", ADMIN)
        same = api_client.set_clock("2026-11-03T12:00:00Z", ADMIN)

        validate_error(rewind, ApiErrorId.ERR_CLOCK_REWIND_FORBIDDEN, 422)
        validate_error(same, ApiErrorId.ERR_CLOCK_REWIND_FORBIDDEN, 422)
        forward = validate_success(api_client.set_clock("2026-11-03T12:00:01Z", ADMIN), 200)
        assert _instant(forward["current_utc"]) == _instant("2026-11-03T12:00:01Z")


class TestReinstatementRequiresSuspension:
    """Reinstatement is a recovery from suspension, so an enrollment that never left
    ACTIVE has nothing to recover from and its counters must not move."""

    def test_reinstating_an_active_enrollment_is_refused_and_leaves_the_counters_alone(self):
        """A freshly opened ACTIVE enrollment refuses a SIGNED_CONFIRMATION_CARD
        reinstatement, keeps reinstated_count at 0 and its original last_confirmation_at,
        and appends no reinstatement entry.

        it requires the enrollment's status to be exactly `SUSPENDED`, else `ERR_ENROLLMENT_NOT_SUSPENDED`

        Design: Corner/validations/reinstating_an_active_enrollment_returns_enrollment_not_suspended
        """
        election = setup_election(posture="PRE_MAIL", clock=CLOCK_SEP10)
        voter = create_voter(full_name="Vera Ames",
                            residence_address="11 Ash St, Springfield")
        enrollment = create_enrollment(voter["id"])
        assert_enrollment(enrollment)
        assert enrollment["status"] == "ACTIVE"
        assert enrollment["reinstated_count"] == 0
        assert enrollment["consecutive_undeliverable_count"] == 0
        assert _instant(enrollment["last_confirmation_at"]) == _instant(CLOCK_SEP10)

        response = api_client.reinstate_enrollment(
            enrollment["id"],
            {"confirmation_evidence_type": "SIGNED_CONFIRMATION_CARD"},
            CLERK)

        validate_error(response, ApiErrorId.ERR_ENROLLMENT_NOT_SUSPENDED, 409)
        after = validate_success(api_client.get_enrollment(enrollment["id"], CLERK), 200)
        assert after["status"] == "ACTIVE"
        assert after["reinstated_count"] == 0
        assert after["consecutive_undeliverable_count"] == 0
        assert after["suspension_reason_code"] is None
        assert _instant(after["last_confirmation_at"]) == _instant(CLOCK_SEP10)
        assert after["version"] == enrollment["version"]
        voter_after = validate_success(api_client.get_voter(voter["id"], CLERK), 200)
        assert_voter(voter_after)
        assert voter_after["permanent_absentee_active"] is True
        assert _log_count(election["id"], "ENROLLMENT_REINSTATED") == 0


class TestOnlyTheAssigneeMayDecide:
    """A signature review is owned by the reviewer it was assigned to; a colleague in
    the same pool cannot post its decision."""

    def test_decision_by_a_reviewer_other_than_the_assignee_is_refused(self):
        """The review opens to Rosa, so a MATCH at similarity 90 posted under Bo's identity
        is refused, the review stays ASSIGNED with no decision recorded, and Bo's workload
        counters never move.

        The acting `X-User-ID` must equal the review's `reviewer_id`, else `ERR_NOT_ASSIGNED_REVIEWER`

        Design: Corner/validations/decision_by_a_reviewer_other_than_the_assignee_is_refused
        """
        set_clock("2026-08-01T01:00:00Z")
        assignee = create_trained_reviewer(full_name="Rosa Vidal", party_affiliation="DEM",
                                          training_completed_at="2026-06-01T00:00:00Z")
        set_clock("2026-08-01T02:00:00Z")
        bystander = create_trained_reviewer(full_name="Bo Reyes", party_affiliation="REP",
                                           training_completed_at="2026-06-02T00:00:00Z")
        bundle = setup_envelope_with_open_review(reviewers=[assignee, bystander],
                                                 clock=CLOCK_SEP10,
                                                 intake_at=CLOCK_NOV3)
        review = bundle["review"]
        assert review["reviewer_id"] == assignee["id"]
        assert review["status"] == "ASSIGNED"

        response = api_client.submit_signature_decision(
            review["id"],
            signature_decision_payload("MATCH", 90),
            make_signature_reviewer_headers(bystander["id"]))

        validate_error(response, ApiErrorId.ERR_NOT_ASSIGNED_REVIEWER, 403)
        after = _get_review(review["id"])
        assert_signature_review(after)
        assert after["status"] == "ASSIGNED"
        assert after["reviewer_id"] == assignee["id"]
        assert after["decision"] is None
        assert after["similarity_score"] is None
        assert after["confidence_score"] is None
        assert after["submitted_at"] is None
        envelope = get_envelope(bundle["envelope"]["id"])
        assert envelope["signature_status"] == "PENDING_REVIEW"
        assert envelope["review_round_count"] == 0
        bystander_after = _get_reviewer(bystander["id"])
        assert bystander_after["active_review_count"] == 0
        assert bystander_after["completed_review_count"] == 0
        assignee_after = _get_reviewer(assignee["id"])
        assert assignee_after["active_review_count"] == 1
        assert assignee_after["completed_review_count"] == 0


class TestChallengeNeedsAnActiveSession:
    """A booked session is not floor access: the challenge power turns on a session
    that is CHECKED_IN with the clock inside its window."""

    def test_observer_challenge_with_only_a_scheduled_session_is_refused(self):
        """The observer holds a DEM INTAKE session for 14:00–16:00Z that is still merely
        SCHEDULED at 12:00Z, so the filing is refused, the envelope keeps its untouched
        dimensions and version, and no challenge entry is appended.

        Any failure of that access test is reported as `ERR_OBSERVER_SESSION_REQUIRED`.

        Design: Corner/validations/observer_challenge_with_only_a_scheduled_session_is_refused
        """
        bundle = setup_received_envelopes(count=1, clock=CLOCK_SEP10,
                                          intake_at=CLOCK_NOV3)
        election_id = bundle["election"]["id"]
        envelope = bundle["envelopes"][0]
        assert_return_envelope(envelope)
        assert envelope["challenge_status"] == "NONE"
        assert envelope["custody_status"] == "SEALED"
        session = schedule_observer_session(
            election_id, "obs-dem-1", headers=CLERK,
            observer_name="Dana Ortiz", organization="County DEM Committee",
            party_affiliation="DEM", station_area="INTAKE",
            window_start_at="2026-11-03T14:00:00Z",
            window_end_at="2026-11-03T16:00:00Z")
        assert_observer_session(session)
        assert session["status"] == "SCHEDULED"

        response = api_client.file_challenge(
            envelope["id"], challenge_payload("SIGNATURE_DISPUTE"),
            make_observer_headers("obs-dem-1"))

        validate_error(response, ApiErrorId.ERR_OBSERVER_SESSION_REQUIRED, 403)
        session_after = validate_success(
            api_client.get_observer_session(session["id"], CLERK), 200)
        assert session_after["status"] == "SCHEDULED"
        envelope_after = get_envelope(envelope["id"])
        assert envelope_after["challenge_status"] == "NONE"
        assert envelope_after["challenge_reason_code"] is None
        assert envelope_after["custody_status"] == "SEALED"
        assert envelope_after["version"] == envelope["version"]
        assert _log_count(election_id, "CHALLENGE_FILED") == 0


class TestAddressVerificationResolvesOnce:
    """A verification carries one result. The second submission cannot rewrite the
    first, so the request keeps the forwarding class the first result earned it."""

    def test_second_address_result_returns_verification_already_resolved(self):
        """A MATCH_SAME result clears the verification and the request; a following
        MATCH_NON_FORWARDABLE on the same verification is refused, leaving the CLEARED
        verification, the SAME_ADDRESS request, and the voter's enrolment flag untouched.

        The verification must still be `PENDING`, else `ERR_VERIFICATION_ALREADY_RESOLVED`

        Design: Corner/validations/second_address_result_returns_verification_already_resolved
        """
        election = setup_election(posture="PRE_MAIL", clock=CLOCK_SEP10)
        voter = create_voter(full_name="Vera Ames",
                            residence_address="11 Ash St, Springfield")
        request = create_ballot_request(voter, election)
        verification = get_address_verification_for(request["id"])
        assert verification["status"] == "PENDING"

        first = submit_address_result(verification["id"], "MATCH_SAME")
        assert first["status"] == "CLEARED"

        response = api_client.submit_address_result(
            verification["id"], address_result_payload("MATCH_NON_FORWARDABLE"), CLERK)

        validate_error(response, ApiErrorId.ERR_VERIFICATION_ALREADY_RESOLVED, 409)
        after = validate_success(
            api_client.get_address_verification(verification["id"], CLERK), 200)
        assert_address_verification(after)
        assert after["status"] == "CLEARED"
        assert after["ncoa_result"] == "MATCH_SAME"
        request_after = validate_success(
            api_client.get_ballot_request(request["id"], CLERK), 200)
        assert request_after["status"] == "ADDRESS_CLEARED"
        assert request_after["forwarding_class"] == "SAME_ADDRESS"
        voter_after = validate_success(api_client.get_voter(voter["id"], CLERK), 200)
        assert voter_after["permanent_absentee_active"] is False


class TestCountingNeedsSeparation:
    """Counting is the last custody act and it starts from SEPARATED; an accepted
    envelope still sealed in its pool is not countable yet."""

    def test_counting_an_unseparated_envelope_returns_custody_state_invalid(self):
        """An ACCEPTED envelope whose custody dimension is still SEALED refuses the count,
        keeps its null separation_run_sequence, and never enters the countable population.

        It requires the envelope's `custody_status` to be `SEPARATED`, else `ERR_ENVELOPE_CUSTODY_STATE_INVALID`

        Design: Corner/validations/counting_an_unseparated_envelope_returns_custody_state_invalid
        """
        reviewer = create_trained_reviewer(full_name="Rosa Vidal",
                                         party_affiliation="DEM",
                                         training_completed_at="2026-06-01T00:00:00Z")
        bundle = setup_accepted_envelope(similarity_score=80, reviewers=[reviewer],
                                         clock=CLOCK_SEP10, intake_at=CLOCK_NOV3)
        envelope = bundle["envelope"]
        assert envelope["signature_status"] == "ACCEPTED"
        assert envelope["custody_status"] == "SEALED"
        assert envelope["challenge_status"] == "NONE"
        assert envelope["separation_run_sequence"] is None

        response = api_client.count_envelope(envelope["id"], SUPERVISOR, {})

        validate_error(response, ApiErrorId.ERR_ENVELOPE_CUSTODY_STATE_INVALID, 409)
        after = get_envelope(envelope["id"])
        assert after["custody_status"] == "SEALED"
        assert after["separation_run_sequence"] is None
        accountability = get_accountability(bundle["election"]["id"], SUPERVISOR)
        assert accountability["countable_envelope_count"] == 0
        assert accountability["attributable_ballot_count"] == 1


class TestAdjudicationNeedsAChallenge:
    """Adjudication answers a filed challenge. With nothing filed there is no finding
    to record and no provisional referral to make."""

    def test_adjudicating_an_unchallenged_envelope_returns_challenge_state_invalid(self):
        """A SUSTAIN with findings against an envelope whose challenge dimension is NONE is
        refused, the findings are not written, and neither the voter's provisional
        eligibility nor the election's referral counter moves.

        Adjudication belongs to the `CanvassSupervisor` and requires the envelope's `challenge_status` to be `CHALLENGED`, else `ERR_CHALLENGE_STATE_INVALID`.

        Design: Corner/validations/adjudicating_an_unchallenged_envelope_returns_challenge_state_invalid
        """
        bundle = setup_received_envelopes(count=1, clock=CLOCK_SEP10,
                                          intake_at=CLOCK_NOV3)
        envelope = bundle["envelopes"][0]
        voter = bundle["voters"][0]
        assert envelope["challenge_status"] == "NONE"

        response = api_client.adjudicate_challenge(
            envelope["id"],
            {"outcome": "SUSTAIN",
             "challenge_findings": "Signature does not match the registration exemplar."},
            SUPERVISOR)

        validate_error(response, ApiErrorId.ERR_CHALLENGE_STATE_INVALID, 409)
        after = get_envelope(envelope["id"])
        assert after["challenge_status"] == "NONE"
        assert after["challenge_findings"] is None
        assert after["custody_status"] == "SEALED"
        assert after["signature_status"] == "UNVERIFIED"
        voter_after = validate_success(api_client.get_voter(voter["id"], CLERK), 200)
        assert voter_after["provisional_ballot_eligible"] is False
        election_after = get_election(bundle["election"]["id"])
        assert election_after["provisional_referral_count"] == 0
        assert _log_count(election_after["id"], "CHALLENGE_ADJUDICATED") == 0


class TestSimilarityScoreRange:
    """The similarity judgment is a percentage; 101 is not a percentage, so the
    decision never reaches the confidence formula."""

    def test_similarity_score_above_one_hundred_returns_invalid_request(self):
        """A MATCH carrying similarity_score 101 is refused as a malformed request, the
        review stays ASSIGNED with no score of any kind, and the envelope stays at round 0.

        A `similarity_score` is the reviewer's visual similarity judgment as a whole number from 0 through 100 inclusive

        Design: Corner/validations/similarity_score_above_one_hundred_returns_invalid_request
        """
        bundle = setup_envelope_with_open_review(clock=CLOCK_SEP10, intake_at=CLOCK_NOV3)
        review = bundle["review"]

        response = api_client.submit_signature_decision(
            review["id"], {"decision": "MATCH", "similarity_score": 101},
            make_signature_reviewer_headers(review["reviewer_id"]))

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
        after = _get_review(review["id"])
        assert after["status"] == "ASSIGNED"
        assert after["decision"] is None
        assert after["similarity_score"] is None
        assert after["confidence_score"] is None
        assert after["submitted_at"] is None
        envelope = get_envelope(bundle["envelope"]["id"])
        assert envelope["signature_status"] == "PENDING_REVIEW"
        assert envelope["review_round_count"] == 0
        assert envelope["resolved_signature_confidence"] is None


class TestSeparationRunNeedsEnvelopes:
    """A separation run anonymises a pool of ballots; an empty array is not a pool
    and must not advance the run sequence."""

    def test_empty_separation_run_returns_separation_set_empty(self):
        """An empty return_envelope_ids array is refused, the election's
        separation_run_sequence stays at 0, and no separation entry is appended.

        An empty `return_envelope_ids` array is rejected with `ERR_SEPARATION_SET_EMPTY`

        Design: Corner/validations/empty_separation_run_returns_separation_set_empty
        """
        bundle = setup_received_envelopes(count=1, clock=CLOCK_SEP10,
                                          intake_at=CLOCK_NOV3)
        election_id = bundle["election"]["id"]
        assert bundle["election"]["posture"] == "RECEIVING"
        assert bundle["election"]["separation_run_sequence"] == 0

        response = api_client.create_separation_run(
            election_id, separation_run_payload([]), SUPERVISOR)

        validate_error(response, ApiErrorId.ERR_SEPARATION_SET_EMPTY, 400)
        after = get_election(election_id)
        assert after["separation_run_sequence"] == 0
        assert _log_count(election_id, "SEPARATION_RUN") == 0
        accountability = get_accountability(election_id, SUPERVISOR)
        assert accountability["countable_envelope_count"] == 0


class TestSealInsideThePostageAuthority:
    """The authority check is a ceiling, not a toll: a seal that fits under the budget
    goes through and commits exactly the estimate it froze."""

    def test_seal_inside_the_postage_budget_commits_the_estimated_total(self):
        """A one-packet 28 g batch freezes 141 cents against a 1,000,000-cent authority, so
        the seal succeeds, the election commits 141 cents, the actual side stays at zero, and
        the packet is still QUEUED awaiting dispatch.

        the election's current `postage_committed_cents` plus this batch's estimated total must be at most the election's `postage_budget_cents`

        Design: Corner/validations/seal_inside_the_postage_budget_commits_the_estimated_total
        """
        election = setup_election(posture="PRE_MAIL", clock=CLOCK_SEP10)
        assert election["postage_budget_cents"] == 1000000
        assert election["postage_committed_cents"] == 0
        voter = create_voter(full_name="Vera Ames",
                            residence_address="11 Ash St, Springfield")
        approved = setup_approved_request(election, voter, "MATCH_SAME")
        batch = create_batch(election, batch_type="DOMESTIC_INITIAL",
                             scheduled_send_date="2026-09-25")
        packet = validate_success(api_client.add_packet(
            batch["id"], packet_payload(approved["request"]["id"], 28), CLERK), 201)
        assert_ballot_packet(packet)
        assert packet["packet_postage_cents"] == 141

        response = api_client.seal_batch(batch["id"], CLERK)

        sealed = validate_success(response, 200)
        assert_mailing_batch(sealed)
        assert sealed["status"] == "SEALED"
        assert sealed["packet_count"] == 1
        assert sealed["estimated_postage_cents"] == 141
        assert_whole_cents(sealed["estimated_postage_cents"])
        assert sealed["actual_postage_cents"] is None
        assert _instant(sealed["sealed_at"]) == _instant(CLOCK_SEP10)
        accountability = get_accountability(election["id"], SUPERVISOR)
        assert accountability["postage_committed_cents"] == 141
        assert accountability["postage_actual_cents"] == 0
        packet_after = validate_success(
            api_client.get_ballot_packet(packet["id"], CLERK), 200)
        assert packet_after["status"] == "QUEUED"


class TestRoleCheckPrecedesExistence:
    """Precedence is observable: an unauthorised role never learns whether the
    identifier it asked about exists."""

    def test_role_check_precedes_existence_check_on_a_voter_read(self):
        """An Observer reading a voter id that does not exist is refused on the role, while
        the same missing id read by a clerk reports the missing record, and the one real
        voter in the roll is untouched by either read.

        When a single request violates more than one rule, the service reports the violation with the lowest precedence number below.

        Design: Corner/validations/role_check_precedes_existence_check_on_a_voter_read
        """
        setup_election(posture="PRE_MAIL", clock=CLOCK_SEP10)
        voter = create_voter(full_name="Vera Ames",
                            residence_address="11 Ash St, Springfield")

        observer_read = api_client.get_voter(MISSING_ID, make_observer_headers("obs-dem-1"))
        clerk_read = api_client.get_voter(MISSING_ID, CLERK)

        validate_error(observer_read, ApiErrorId.ERR_ROLE_FORBIDDEN, 403)
        validate_error(clerk_read, ApiErrorId.ERR_VOTER_NOT_FOUND, 404)
        assert _total_count(api_client.list_voters(CLERK, params={"limit": 100})) == 1
        real = validate_success(api_client.get_voter(voter["id"], CLERK), 200)
        assert_voter(real)
        assert real["registration_status"] == "ACTIVE"
