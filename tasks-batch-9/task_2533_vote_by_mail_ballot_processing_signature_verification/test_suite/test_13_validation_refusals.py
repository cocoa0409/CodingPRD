"""Refusals across the mail stream of the Vote-By-Mail Processing API.

Each test drives one lawful world to the edge of a single rule, fires the refused
call, and then re-reads the surrounding records to prove the refusal wrote nothing:
eligibility at request logging, batch/voter agreement at packeting, duplicate
intake, the two send-deadline codes, the frozen cure deadline, observer floor
capacity, the emptied reviewer candidate set, and the two remake guards.
"""
from datetime import datetime

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    approve_request,
    assert_ballot_packet,
    assert_ballot_request,
    assert_cure_notice,
    assert_mailing_batch,
    assert_observer_session,
    assert_remake_record,
    assert_return_envelope,
    ballot_request_payload,
    create_ballot_request,
    create_batch,
    create_election,
    create_trained_reviewer,
    create_voter,
    cure_evidence_payload,
    get_accountability,
    get_cure_notice,
    get_election,
    get_envelope,
    issue_cure_notice,
    make_signature_reviewer_headers,
    observer_session_payload,
    open_remake,
    packet_payload,
    remake_payload,
    resolve_address,
    return_envelope_payload,
    schedule_observer_session,
    seal_batch,
    set_clock,
    setup_approved_request,
    setup_election,
    setup_envelope_with_open_review,
    setup_received_envelopes,
    submit_decision,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["elections_admin_headers"]
CLERK = TEST_USERS["elections_clerk_headers"]
SUPERVISOR = TEST_USERS["canvass_supervisor_headers"]

CLOCK_SEP10 = "2026-09-10T09:00:00Z"
CLOCK_NOV3 = "2026-11-03T12:00:00Z"


def _instant(value):
    """Parse an emitted ISO 8601 UTC instant so instants compare as instants."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _page(response):
    """The rows and the pagination envelope of a list response."""
    rows, meta = validate_paginated(response)
    return rows, meta


def _total_count(response):
    return _page(response)[1]["total_count"]


def _log_count(election_id, event_type):
    return _total_count(api_client.list_transparency_log(
        ADMIN, params={"election_id": election_id, "event_type": event_type}))


def _submit_missing_signature(review, notes="no signature in the signature box"):
    """A MISSING_SIGNATURE decision carries no similarity_score at all, so this
    posts the bare payload the rule allows."""
    headers = make_signature_reviewer_headers(review["reviewer_id"])
    response = api_client.submit_signature_decision(
        review["id"], {"decision": "MISSING_SIGNATURE", "notes": notes}, headers)
    return validate_success(response, 200)


class TestBallotRequestEligibility:
    """The two eligibility rules that bite when a request is logged."""

    def test_inactive_voter_cannot_open_a_ballot_request(self):
        """A voter registered INACTIVE is refused at logging, and neither a request nor
        an address verification is written, nor is the voter's version bumped.

        the voter's `registration_status` must be `ACTIVE`, else `ERR_VOTER_REGISTRATION_INACTIVE`

        Design: Corner/validations/inactive_voter_cannot_open_a_ballot_request
        """
        election = setup_election(posture="PRE_MAIL", clock=CLOCK_SEP10)
        voter = create_voter(full_name="Ida Frost", party_affiliation="REP",
                            residence_address="55 Elm Way, Springfield",
                            last_signature_update_at="2026-01-20T00:00:00Z",
                            registration_status="INACTIVE")
        assert voter["registration_status"] == "INACTIVE"
        assert voter["version"] == 1

        response = api_client.create_ballot_request(
            ballot_request_payload(voter["id"], election["id"], voter["version"]), CLERK)

        validate_error(response, ApiErrorId.ERR_VOTER_REGISTRATION_INACTIVE, 422)
        assert _total_count(api_client.list_ballot_requests(
            CLERK, params={"voter_id": voter["id"]})) == 0
        assert _total_count(api_client.list_address_verifications(CLERK)) == 0
        unchanged = validate_success(api_client.get_voter(voter["id"], CLERK), 200)
        assert unchanged["version"] == 1

    def test_email_uocava_delivery_for_a_domestic_voter_is_not_eligible(self):
        """The identical payload shape is accepted for a MILITARY voter and refused for a
        domestic one, so the gate is the voter's configuration and nothing else.

        choosing `EMAIL_UOCAVA` requires the voter's `uocava_status` to be `MILITARY` or `OVERSEAS`, else `ERR_DELIVERY_METHOD_NOT_ELIGIBLE`

        Design: Corner/validations/email_uocava_delivery_for_a_domestic_voter_is_not_eligible
        """
        election = setup_election(posture="PRE_MAIL", clock=CLOCK_SEP10)
        domestic = create_voter(full_name="Vera Ames",
                                residence_address="11 Ash St, Springfield")
        military = create_voter(full_name="Milo Vance", party_affiliation="NPP",
                                residence_address="Unit 7, FPO AE 09501",
                                last_signature_update_at="2026-01-08T00:00:00Z",
                                uocava_status="MILITARY")
        assert domestic["uocava_status"] == "NONE"
        assert military["uocava_status"] == "MILITARY"

        accepted = validate_success(api_client.create_ballot_request(
            ballot_request_payload(military["id"], election["id"], military["version"],
                                   delivery_method="EMAIL_UOCAVA"), CLERK), 201)
        refused = api_client.create_ballot_request(
            ballot_request_payload(domestic["id"], election["id"], domestic["version"],
                                   delivery_method="EMAIL_UOCAVA"), CLERK)

        assert_ballot_request(accepted)
        assert accepted["delivery_method"] == "EMAIL_UOCAVA"
        assert accepted["status"] == "RECEIVED"
        validate_error(refused, ApiErrorId.ERR_DELIVERY_METHOD_NOT_ELIGIBLE, 422)
        assert _total_count(api_client.list_ballot_requests(
            CLERK, params={"voter_id": domestic["id"]})) == 0
        assert _total_count(api_client.list_ballot_requests(
            CLERK, params={"voter_id": military["id"]})) == 1


class TestPacketAgreementWithItsRequest:
    """Adding a packet joins three records — the batch, the request, and the voter
    reached through it — and each disagreement has its own code."""

    def test_uocava_batch_rejects_a_domestic_voters_packet(self):
        """The overseas batch takes the MILITARY voter's packet at 152 cents and refuses
        the domestic voter's, so the batch keeps exactly one packet.

        a `UOCAVA` batch accepts only voters whose `uocava_status` is `MILITARY` or `OVERSEAS`, a `DOMESTIC_INITIAL` batch accepts only voters whose `uocava_status` is `NONE`, and a `SUPPLEMENTAL` batch accepts either — a mismatch is reported as `ERR_UOCAVA_BATCH_MISMATCH`

        Design: Corner/validations/uocava_batch_rejects_a_domestic_voters_packet
        """
        election = setup_election(posture="PRE_MAIL", clock=CLOCK_SEP10)
        domestic = create_voter(full_name="Vera Ames",
                                residence_address="11 Ash St, Springfield")
        domestic_approved = setup_approved_request(election, domestic, "MATCH_SAME")
        military = create_voter(full_name="Milo Vance", party_affiliation="NPP",
                                residence_address="Unit 7, FPO AE 09501",
                                last_signature_update_at="2026-01-08T00:00:00Z",
                                uocava_status="MILITARY")
        military_request = create_ballot_request(military, election,
                                                delivery_method="EMAIL_UOCAVA")
        resolve_address(military_request["id"], "MATCH_SAME")
        military_approved = approve_request(military_request["id"])
        assert military_approved["status"] == "APPROVED"
        batch = create_batch(election, batch_type="UOCAVA",
                             scheduled_send_date="2026-09-14")

        accepted = validate_success(api_client.add_packet(
            batch["id"], packet_payload(military_approved["id"], 28), CLERK), 201)
        refused = api_client.add_packet(
            batch["id"], packet_payload(domestic_approved["request"]["id"], 28), CLERK)

        assert_ballot_packet(accepted)
        assert accepted["packet_postage_cents"] == 152
        validate_error(refused, ApiErrorId.ERR_UOCAVA_BATCH_MISMATCH, 422)
        after = validate_success(api_client.get_mailing_batch(batch["id"], CLERK), 200)
        assert_mailing_batch(after)
        assert after["packet_count"] == 1
        rows, meta = _page(api_client.list_ballot_packets(
            CLERK, params={"mailing_batch_id": batch["id"]}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == accepted["id"]

    def test_packet_whose_request_belongs_to_another_election_returns_mismatch(self):
        """A batch on the bond election refuses an approved request that belongs to the
        general election, and its own totals stay at zero.

        The request's election must be the batch's election, else `ERR_REQUEST_ELECTION_MISMATCH`

        Design: Corner/validations/packet_whose_request_belongs_to_another_election_returns_mismatch
        """
        general = setup_election(posture="PRE_MAIL", clock=CLOCK_SEP10)
        approved = setup_approved_request(
            general,
            create_voter(full_name="Vera Ames", residence_address="11 Ash St, Springfield"),
            "MATCH_SAME")
        bond = create_election(name="School Bond Election 2026",
                               postage_budget_cents=250000)
        assert bond["id"] != general["id"]
        other_batch = create_batch(bond, batch_type="DOMESTIC_INITIAL",
                                   scheduled_send_date="2026-09-26")

        response = api_client.add_packet(
            other_batch["id"], packet_payload(approved["request"]["id"], 28), CLERK)

        validate_error(response, ApiErrorId.ERR_REQUEST_ELECTION_MISMATCH, 422)
        after = validate_success(
            api_client.get_mailing_batch(other_batch["id"], CLERK), 200)
        assert after["packet_count"] == 0
        assert after["estimated_postage_cents"] == 0
        assert _total_count(api_client.list_ballot_packets(
            CLERK, params={"ballot_request_id": approved["request"]["id"]})) == 0
        assert get_election(bond["id"])["postage_committed_cents"] == 0


class TestSecondIntakeOfTheSamePacket:
    """The packet-state gate deliberately admits an already-RETURNED packet so that a
    re-scan surfaces as a duplicate instead."""

    def test_second_intake_of_the_same_packet_returns_duplicate_envelope(self):
        """Re-scanning a packet that already has an envelope is refused as a duplicate, and
        the ledger still shows exactly one received envelope.

        if a return envelope already exists for this `ballot_packet_id` and was not itself minted by a remake (that is, its `remade_from_envelope_id` is null), the intake is rejected with `ERR_DUPLICATE_ENVELOPE_FOR_PACKET`

        Design: Corner/validations/second_intake_of_the_same_packet_returns_duplicate_envelope
        """
        bundle = setup_received_envelopes(count=1, clock=CLOCK_SEP10,
                                         intake_at=CLOCK_NOV3)
        packet_id = bundle["packets"][0]["id"]
        first = bundle["envelopes"][0]
        assert first["remade_from_envelope_id"] is None

        response = api_client.create_return_envelope(
            return_envelope_payload(packet_id, "IN_PERSON"), CLERK)

        validate_error(response, ApiErrorId.ERR_DUPLICATE_ENVELOPE_FOR_PACKET, 409)
        rows, meta = _page(api_client.list_return_envelopes(
            CLERK, params={"ballot_packet_id": packet_id}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]
        ledger = get_accountability(bundle["election"]["id"])
        assert ledger["envelopes_received_count"] == 1
        assert ledger["returned_packet_count"] == 1
        packet = validate_success(api_client.get_ballot_packet(packet_id, CLERK), 200)
        assert packet["status"] == "RETURNED"


class TestSendDeadlineSelectedByBatchType:
    """One clock instant, two batches, two verdicts: the deadline a batch must meet is
    derived from its type."""

    def test_send_deadline_rule_selected_by_batch_type(self):
        """At 2026-09-20 the overseas batch is one day late and refused with its own code
        while the domestic batch, due 2026-10-05, dispatches and books its postage.

        a late `UOCAVA` batch is rejected with `ERR_UOCAVA_SEND_DEADLINE_PASSED`, and a late `DOMESTIC_INITIAL` or `SUPPLEMENTAL` batch with `ERR_DOMESTIC_SEND_DEADLINE_PASSED`

        Design: Corner/validations/send_deadline_rule_selected_by_batch_type
        """
        election = setup_election(posture="PRE_MAIL", clock=CLOCK_SEP10)
        military = create_voter(full_name="Milo Vance", party_affiliation="NPP",
                                residence_address="Unit 7, FPO AE 09501",
                                last_signature_update_at="2026-01-08T00:00:00Z",
                                uocava_status="MILITARY")
        military_request = create_ballot_request(military, election,
                                                delivery_method="EMAIL_UOCAVA")
        resolve_address(military_request["id"], "MATCH_SAME")
        military_approved = approve_request(military_request["id"])
        overseas_batch = create_batch(election, batch_type="UOCAVA",
                                      scheduled_send_date="2026-09-14")
        overseas_packet = validate_success(api_client.add_packet(
            overseas_batch["id"], packet_payload(military_approved["id"], 28), CLERK), 201)
        assert overseas_packet["packet_postage_cents"] == 152
        assert seal_batch(overseas_batch["id"])["estimated_postage_cents"] == 152
        domestic = create_voter(full_name="Vera Ames",
                                residence_address="11 Ash St, Springfield")
        domestic_approved = setup_approved_request(election, domestic, "MATCH_SAME")
        domestic_batch = create_batch(election, batch_type="DOMESTIC_INITIAL",
                                      scheduled_send_date="2026-09-25")
        domestic_packet = validate_success(api_client.add_packet(
            domestic_batch["id"],
            packet_payload(domestic_approved["request"]["id"], 28), CLERK), 201)
        assert domestic_packet["packet_postage_cents"] == 141
        assert seal_batch(domestic_batch["id"])["estimated_postage_cents"] == 141
        set_clock("2026-09-20T09:00:00Z")

        refused = api_client.dispatch_batch(overseas_batch["id"], CLERK)
        accepted = api_client.dispatch_batch(domestic_batch["id"], CLERK)

        validate_error(refused, ApiErrorId.ERR_UOCAVA_SEND_DEADLINE_PASSED, 422)
        dispatched = validate_success(accepted, 200)
        assert dispatched["status"] == "DISPATCHED"
        assert _instant(dispatched["dispatched_at"]) == _instant("2026-09-20T09:00:00Z")
        assert dispatched["actual_postage_cents"] == 141
        assert dispatched["required_send_by_date"] == "2026-10-05"
        still_sealed = validate_success(
            api_client.get_mailing_batch(overseas_batch["id"], CLERK), 200)
        assert still_sealed["status"] == "SEALED"
        assert still_sealed["actual_postage_cents"] is None
        assert still_sealed["required_send_by_date"] == "2026-09-19"
        after = get_election(election["id"])
        assert after["posture"] == "MAILING"
        assert after["postage_committed_cents"] == 293
        assert after["postage_actual_cents"] == 141
        unmailed = validate_success(
            api_client.get_ballot_packet(overseas_packet["id"], CLERK), 200)
        assert unmailed["status"] == "QUEUED"
        assert unmailed["mailed_at"] is None


class TestFrozenCureDeadline:
    """A notice freezes its deadline at issuance, and evidence one second late is
    outside it."""

    def test_cure_evidence_after_the_deadline_returns_deadline_passed(self):
        """The single open notice freezes 2026-11-19T20:00:00Z — the canvass lock less one
        day, which is earlier than the 21-day cure window — and evidence logged one second
        later writes nothing at all.

        requires the logical clock to be at or before the notice's frozen `cure_deadline_at`, else `ERR_CURE_DEADLINE_PASSED`

        Design: Corner/validations/cure_evidence_after_the_deadline_returns_deadline_passed
        """
        reviewer = create_trained_reviewer(full_name="Rosa Vidal",
                                          party_affiliation="DEM",
                                          training_completed_at="2026-06-01T00:00:00Z")
        bundle = setup_envelope_with_open_review(reviewers=[reviewer], clock=CLOCK_SEP10,
                                                intake_at=CLOCK_NOV3)
        _submit_missing_signature(bundle["review"])
        envelope = get_envelope(bundle["envelope"]["id"])
        assert envelope["signature_status"] == "CURE_REQUIRED"
        notice = issue_cure_notice(envelope["id"])
        assert_cure_notice(notice)
        assert notice["reason_code"] == "MISSING_SIGNATURE"
        assert notice["status"] == "ISSUED"
        assert notice["canvass_days_at_issue"] == 17
        assert notice["open_cure_count_at_issue"] == 1
        assert _instant(notice["cure_deadline_at"]) == _instant("2026-11-19T20:00:00Z")
        set_clock("2026-11-19T20:00:01Z")

        response = api_client.submit_cure_evidence(
            notice["id"],
            cure_evidence_payload(evidence_type="ID_COPY", submission_channel="PORTAL",
                                  affirmation_signed=True),
            CLERK)

        validate_error(response, ApiErrorId.ERR_CURE_DEADLINE_PASSED, 422)
        after = get_cure_notice(notice["id"])
        assert after["status"] == "ISSUED"
        assert after["evidence_submission_count"] == 0
        assert _instant(after["cure_deadline_at"]) == _instant("2026-11-19T20:00:00Z")
        assert _total_count(api_client.list_cure_evidence(
            CLERK, params={"cure_notice_id": notice["id"]})) == 0
        election = get_election(bundle["election"]["id"])
        assert election["open_cure_count"] == 1
        assert election["canvass_days"] == 17
        assert _instant(election["canvass_lock_at"]) == _instant("2026-11-20T20:00:00Z")


class TestObserverFloorCapacity:
    """Per-party slots and the floor total are separate constraints: four different
    parties can each hold a slot and still breach the floor."""

    def test_observer_floor_capacity_aggregates_across_all_parties(self):
        """Three overlapping intake sessions of three parties are lawful; the fourth, of a
        party with no session at all, is refused because the floor total would reach four.

        The floor constraint aggregates occupancy across all parties under the same geometry and requires it to stay at 3 or fewer at every instant of the new window; a booking that would push it past 3 is rejected with `ERR_OBSERVER_FLOOR_CAPACITY`

        Design: Corner/validations/observer_floor_capacity_aggregates_across_all_parties
        """
        election = setup_election(posture="PRE_MAIL", clock=CLOCK_SEP10)
        booked = []
        for user_id, name, organization, party, start, end in [
            ("obs-dem-1", "Dana Ortiz", "County DEM Committee", "DEM",
             "2026-11-03T14:00:00Z", "2026-11-03T16:00:00Z"),
            ("obs-rep-1", "Rex Alden", "County REP Committee", "REP",
             "2026-11-03T14:30:00Z", "2026-11-03T15:30:00Z"),
            ("obs-npp-1", "Nia Pike", "Voter Watch", "NPP",
             "2026-11-03T15:00:00Z", "2026-11-03T16:00:00Z"),
        ]:
            session = schedule_observer_session(
                election["id"], user_id, headers=CLERK, observer_name=name,
                organization=organization, party_affiliation=party,
                station_area="INTAKE", window_start_at=start, window_end_at=end)
            assert_observer_session(session)
            assert session["status"] == "SCHEDULED"
            assert session["station_area"] == "INTAKE"
            booked.append(session)

        response = api_client.create_observer_session(
            election["id"],
            observer_session_payload("obs-oth-1", observer_name="Otto Lin",
                                     organization="Press Pool",
                                     party_affiliation="OTHER", station_area="INTAKE",
                                     window_start_at="2026-11-03T14:45:00Z",
                                     window_end_at="2026-11-03T15:15:00Z"),
            CLERK)

        validate_error(response, ApiErrorId.ERR_OBSERVER_FLOOR_CAPACITY, 409)
        rows, meta = _page(api_client.list_observer_sessions(
            CLERK, params={"election_id": election["id"]}))
        assert meta["total_count"] == 3
        assert {row["id"] for row in rows} == {session["id"] for session in booked}
        assert _log_count(election["id"], "OBSERVER_SESSION_OPENED") == 3


class TestEmptiedReviewerCandidateSet:
    """Segregation of duties can empty the candidate set outright, and then the
    escalated round simply cannot be opened."""

    def test_escalation_round_two_with_a_single_reviewer_returns_no_eligible_reviewer(self):
        """The county's only trained reviewer already decided round one on this envelope, so
        round two is refused, no review row appears, and the envelope stays ESCALATED.

        If the candidate set is empty, the request is rejected with `ERR_NO_ELIGIBLE_REVIEWER`, no signature review row is created, and the envelope's `signature_status` is left exactly as it was.

        Design: Corner/validations/escalation_round_two_with_a_single_reviewer_returns_no_eligible_reviewer
        """
        only_reviewer = create_trained_reviewer(full_name="Rosa Vidal",
                                               party_affiliation="DEM",
                                               training_completed_at="2026-06-01T00:00:00Z")
        bundle = setup_envelope_with_open_review(reviewers=[only_reviewer],
                                                clock=CLOCK_SEP10, intake_at=CLOCK_NOV3)
        envelope_id = bundle["envelope"]["id"]
        assert bundle["review"]["reviewer_id"] == only_reviewer["id"]
        submit_decision(bundle["review"], "NO_MATCH", 60)
        escalated = get_envelope(envelope_id)
        assert escalated["signature_status"] == "ESCALATED"

        response = api_client.open_signature_review(envelope_id, CLERK)

        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_REVIEWER, 409)
        assert _total_count(api_client.list_signature_reviews(
            CLERK, params={"return_envelope_id": envelope_id})) == 1
        unchanged = get_envelope(envelope_id)
        assert unchanged["signature_status"] == "ESCALATED"
        assert unchanged["review_round_count"] == 1
        reviewer = validate_success(
            api_client.get_reviewer(only_reviewer["id"], CLERK), 200)
        assert reviewer["active_review_count"] == 0
        assert reviewer["completed_review_count"] == 1


class TestRemakeGuards:
    """Two guards on the remake table: who may sit on the team, and which serial the
    replacement may bear."""

    def test_remake_team_member_who_reviewed_the_envelope_violates_segregation(self):
        """The nominated pair is bipartisan, so only segregation can fire — and it does,
        because member A holds the signature review on this very envelope.

        Neither member may hold a signature review on the envelope being remade, else `ERR_SEGREGATION_OF_DUTIES`.

        Design: Corner/validations/remake_team_member_who_reviewed_the_envelope_violates_segregation
        """
        reviewer_a = create_trained_reviewer(full_name="Rosa Vidal",
                                            party_affiliation="DEM",
                                            training_completed_at="2026-06-01T00:00:00Z")
        reviewer_b = create_trained_reviewer(full_name="Bo Reyes",
                                            party_affiliation="REP",
                                            training_completed_at="2026-06-02T00:00:00Z")
        assert reviewer_a["party_affiliation"] != reviewer_b["party_affiliation"]
        bundle = setup_envelope_with_open_review(reviewers=[reviewer_a, reviewer_b],
                                                clock=CLOCK_SEP10, intake_at=CLOCK_NOV3)
        assert bundle["review"]["reviewer_id"] == reviewer_a["id"]
        submit_decision(bundle["review"], "MATCH", 80)
        envelope = get_envelope(bundle["envelope"]["id"])
        assert envelope["signature_status"] == "ACCEPTED"
        assert envelope["custody_status"] == "SEALED"

        response = api_client.create_remake(
            envelope["id"],
            remake_payload(reviewer_a["id"], reviewer_b["id"], envelope["version"],
                           reason_code="TORN_ENVELOPE",
                           session_start_at="2026-11-03T13:00:00Z",
                           session_end_at="2026-11-03T14:00:00Z"),
            SUPERVISOR)

        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)
        assert _total_count(api_client.list_remake_records(
            SUPERVISOR, params={"original_envelope_id": envelope["id"]})) == 0
        unchanged = get_envelope(envelope["id"])
        assert unchanged["version"] == envelope["version"]
        assert unchanged["custody_status"] == "SEALED"

    def test_duplicate_remade_serial_within_the_election_is_rejected(self):
        """Serial RM-0001 is taken by the first completed remake, so the second remake of a
        different envelope in the same election cannot reuse it and stays OPEN.

        A `remade_serial` must be present, and it must be unique among the completed remake records of the same election — a repeat is rejected with `ERR_DUPLICATE_REMAKE_SERIAL`.

        Design: Corner/validations/duplicate_remade_serial_within_the_election_is_rejected
        """
        member_a = create_trained_reviewer(full_name="Bo Reyes", party_affiliation="REP",
                                           training_completed_at="2026-06-02T00:00:00Z")
        member_b = create_trained_reviewer(full_name="Cass Dole", party_affiliation="DEM",
                                           training_completed_at="2026-06-03T00:00:00Z")
        bundle = setup_received_envelopes(count=2, weights=(28, 57), clock=CLOCK_SEP10,
                                         intake_at=CLOCK_NOV3)
        first_envelope, second_envelope = bundle["envelopes"]
        first_remake = open_remake(get_envelope(first_envelope["id"]), member_a, member_b,
                                   session_start_at="2026-11-03T13:00:00Z",
                                   session_end_at="2026-11-03T14:00:00Z")
        second_remake = open_remake(get_envelope(second_envelope["id"]), member_a,
                                    member_b, reason_code="UNREADABLE_MARKS",
                                    session_start_at="2026-11-03T14:16:00Z",
                                    session_end_at="2026-11-03T15:00:00Z")
        assert first_remake["status"] == "OPEN"
        assert second_remake["status"] == "OPEN"

        completed = validate_success(api_client.complete_remake(
            first_remake["id"], {"remade_serial": "RM-0001"}, SUPERVISOR), 200)
        refused = api_client.complete_remake(
            second_remake["id"], {"remade_serial": "RM-0001"}, SUPERVISOR)

        assert_remake_record(completed)
        assert completed["status"] == "COMPLETED"
        assert completed["remade_serial"] == "RM-0001"
        assert completed["remade_envelope_id"] is not None
        validate_error(refused, ApiErrorId.ERR_DUPLICATE_REMAKE_SERIAL, 409)
        still_open = validate_success(
            api_client.get_remake_record(second_remake["id"], SUPERVISOR), 200)
        assert still_open["status"] == "OPEN"
        assert still_open["remade_serial"] is None
        assert still_open["remade_envelope_id"] is None
        assert still_open["completed_at"] is None
        assert get_envelope(second_envelope["id"])["custody_status"] == "SEALED"
        assert _total_count(api_client.list_return_envelopes(
            CLERK, params={"remade_from_envelope_id": second_envelope["id"]})) == 0
        superseded = get_envelope(first_envelope["id"])
        assert superseded["custody_status"] == "SUPERSEDED_BY_REMAKE"
        assert_return_envelope(superseded)
