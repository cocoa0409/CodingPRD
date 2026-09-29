"""Non-linear state machines and depth-three transitive cascades.

The return envelope carries three dimensions that advance independently, the cure
notice cycles back on itself while its deadline stays frozen, and two different
triggers each drive a three-link chain in which every link is caused by the one
before it.
"""
from datetime import datetime

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_ballot_request,
    create_enrollment,
    create_trained_reviewer,
    create_voter,
    get_accountability,
    get_address_verification_for,
    get_cure_notice,
    get_election,
    get_envelope,
    get_success_data,
    issue_cure_notice,
    list_transparency_log,
    make_signature_reviewer_headers,
    open_review,
    set_clock,
    setup_accepted_envelope,
    setup_checked_in_observer,
    setup_cure_required_envelope,
    setup_election,
    setup_received_envelopes,
    setup_sealed_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

CLERK = TEST_USERS["elections_clerk_headers"]
SUPERVISOR = TEST_USERS["canvass_supervisor_headers"]

OVERRULE_FINDINGS = "Registration photo matches the envelope affidavit; challenge not sustained."


def _instant(value):
    """Parse an emitted ISO 8601 UTC instant, tolerating the fractional digits."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _decide_missing_signature(review):
    """Submit MISSING_SIGNATURE, which carries no similarity_score at all."""
    headers = make_signature_reviewer_headers(review["reviewer_id"])
    return get_success_data(
        api_client.submit_signature_decision(review["id"],
                                             {"decision": "MISSING_SIGNATURE"}, headers))


class TestReturnEnvelopeParallelDimensions:
    """signature_status, custody_status and challenge_status advance on one row
    without either of them dragging the others along."""

    def test_challenge_moves_custody_twice_without_touching_the_signature_dimension(self):
        """A filed challenge sequesters the ballot and an overrule hands it back, while
        the accepted signature verdict stays exactly where the reviewer left it.

        "Overruling moves the challenge dimension `CHALLENGED → OVERRULED` and returns the envelope to the separable pool by moving its custody dimension `SEQUESTERED → SEALED`, but **only** when nothing else disqualifies it — that is, only when its `signature_status` is `ACCEPTED` and its `final_timeliness` is anything other than `UNTIMELY`."

        Design: Difficulty/non_linear_state_machine/return_envelope_three_parallel_state_dimensions
        """
        bundle = setup_accepted_envelope(similarity_score=80)
        envelope = bundle["envelope"]
        assert bundle["review"]["confidence_score"] == pytest.approx(0.8, abs=0.0001)
        assert envelope["signature_status"] == "ACCEPTED"
        assert envelope["custody_status"] == "SEALED"
        assert envelope["challenge_status"] == "NONE"

        access = setup_checked_in_observer(bundle["election"], observer_user_id="obs-dem-1",
                                          station_area="INTAKE",
                                          window_start_at="2026-11-03T00:00:00Z",
                                          window_end_at="2026-11-04T00:00:00Z")

        challenged = validate_success(
            api_client.file_challenge(envelope["id"],
                                     {"challenge_reason_code": "IDENTITY_DISPUTE"},
                                     access["headers"]), 200)
        assert challenged["challenge_status"] == "CHALLENGED"
        assert challenged["custody_status"] == "SEQUESTERED"
        assert challenged["signature_status"] == "ACCEPTED"

        overruled = validate_success(
            api_client.adjudicate_challenge(envelope["id"],
                                          {"outcome": "OVERRULE",
                                           "challenge_findings": OVERRULE_FINDINGS},
                                          SUPERVISOR), 200)
        assert overruled["challenge_status"] == "OVERRULED"
        assert overruled["custody_status"] == "SEALED"
        assert overruled["signature_status"] == "ACCEPTED"

        after = get_envelope(envelope["id"])
        assert after["challenge_findings"] == OVERRULE_FINDINGS
        assert after["review_round_count"] == 1
        assert get_election(bundle["election"]["id"])["provisional_referral_count"] == 0

    def test_sustained_challenge_rejects_the_signature_dimension_and_holds_custody(self):
        """Sustaining drives all three dimensions at once: the challenge terminates, the
        signature is rejected, and custody stays sequestered.

        "Sustaining a challenge moves the challenge dimension `CHALLENGED → SUSTAINED`, sets the envelope's `signature_status` to `REJECTED` while leaving its custody dimension at `SEQUESTERED`, sets the voter's `provisional_ballot_eligible` to true, increments the election's `provisional_referral_count` by one, and appends a `PROVISIONAL_REFERRAL` entry whose subject is the voter."

        Design: Difficulty/non_linear_state_machine/return_envelope_three_parallel_state_dimensions
        """
        bundle = setup_accepted_envelope(similarity_score=80)
        envelope = bundle["envelope"]
        access = setup_checked_in_observer(bundle["election"], observer_user_id="obs-dem-1",
                                          station_area="INTAKE",
                                          window_start_at="2026-11-03T00:00:00Z",
                                          window_end_at="2026-11-04T00:00:00Z")
        validate_success(
            api_client.file_challenge(envelope["id"],
                                     {"challenge_reason_code": "ENVELOPE_TAMPERING"},
                                     access["headers"]), 200)

        sustained = validate_success(
            api_client.adjudicate_challenge(envelope["id"],
                                          {"outcome": "SUSTAIN",
                                           "challenge_findings": "Seal was broken in transit."},
                                          SUPERVISOR), 200)
        assert sustained["challenge_status"] == "SUSTAINED"
        assert sustained["signature_status"] == "REJECTED"
        assert sustained["custody_status"] == "SEQUESTERED"

        voter = get_success_data(api_client.get_voter(bundle["voters"][0]["id"], CLERK))
        assert voter["provisional_ballot_eligible"] is True
        assert get_election(bundle["election"]["id"])["provisional_referral_count"] == 1

    def test_overruled_challenge_leaves_custody_sequestered_when_signature_is_not_accepted(
            self):
        """The custody round trip is conditional on the parallel signature dimension, so
        a cure-required envelope stays sequestered even after the challenge is overruled.

        "If either of those fails, the envelope stays `SEQUESTERED` even though the challenge was overruled."

        Design: Difficulty/non_linear_state_machine/return_envelope_three_parallel_state_dimensions
        """
        bundle = setup_cure_required_envelope()
        envelope = bundle["envelope"]
        assert envelope["signature_status"] == "CURE_REQUIRED"
        assert envelope["custody_status"] == "SEALED"

        access = setup_checked_in_observer(bundle["election"], observer_user_id="obs-dem-1",
                                          station_area="SIGNATURE_REVIEW",
                                          window_start_at="2026-11-03T00:00:00Z",
                                          window_end_at="2026-11-04T00:00:00Z")
        challenged = validate_success(
            api_client.file_challenge(envelope["id"],
                                     {"challenge_reason_code": "SIGNATURE_DISPUTE"},
                                     access["headers"]), 200)
        assert challenged["custody_status"] == "SEQUESTERED"
        assert challenged["signature_status"] == "CURE_REQUIRED"

        overruled = validate_success(
            api_client.adjudicate_challenge(envelope["id"],
                                          {"outcome": "OVERRULE",
                                           "challenge_findings": OVERRULE_FINDINGS},
                                          SUPERVISOR), 200)
        assert overruled["challenge_status"] == "OVERRULED"
        assert overruled["custody_status"] == "SEQUESTERED"
        assert overruled["signature_status"] == "CURE_REQUIRED"


def _setup_missing_signature_notice():
    """One DROPBOX envelope carried to CURE_REQUIRED by a MISSING_SIGNATURE round-one
    review, with one ISSUED cure notice on it and the clock at 2026-11-04T00:00:00Z."""
    create_trained_reviewer(full_name="Rae Lin", party_affiliation="NPP")
    bundle = setup_received_envelopes(count=1, intake_at="2026-11-03T12:00:00Z",
                                      intake_channel="DROPBOX")
    envelope = bundle["envelopes"][0]
    _decide_missing_signature(open_review(envelope["id"]))
    set_clock("2026-11-04T00:00:00Z")
    bundle["envelope"] = get_envelope(envelope["id"])
    bundle["cure_notice"] = issue_cure_notice(envelope["id"])
    return bundle


def _submit_evidence(notice_id, evidence_type, submission_channel, affirmation_signed):
    return validate_success(
        api_client.submit_cure_evidence(notice_id,
                                       {"evidence_type": evidence_type,
                                        "submission_channel": submission_channel,
                                        "affirmation_signed": affirmation_signed},
                                       CLERK), 201)


def _adjudicate_deficient(notice_id, deficiency_reason_code):
    return validate_success(
        api_client.adjudicate_cure_notice(notice_id,
                                         {"outcome": "DEFICIENT",
                                          "deficiency_reason_code": deficiency_reason_code},
                                         SUPERVISOR), 200)


class TestCureNoticeEvidenceDeficiencyCycle:
    """ISSUED -> UNDER_EVIDENCE_REVIEW -> ISSUED is traversable repeatedly, and the
    frozen deadline is the only thing that ends the loop."""

    def test_loop_closes_twice_before_a_cure_and_the_deadline_never_moves(self):
        """Two deficient rounds return the notice to ISSUED and are counted, and the
        third submission cures it against the same frozen deadline.

        "`cure_deadline_at` is emphatically **not** extended by a deficient round: the `ISSUED → UNDER_EVIDENCE_REVIEW → ISSUED` cycle may repeat any number of times against the same frozen deadline, and `deficiency_count` records how many times it has."

        Design: Difficulty/non_linear_state_machine/cure_notice_evidence_deficiency_cycle
        """
        bundle = _setup_missing_signature_notice()
        notice = bundle["cure_notice"]
        assert notice["status"] == "ISSUED"
        assert notice["reason_code"] == "MISSING_SIGNATURE"
        assert notice["evidence_submission_count"] == 0
        assert notice["deficiency_count"] == 0
        frozen_deadline = notice["cure_deadline_at"]

        first_evidence = _submit_evidence(notice["id"], "SIGNED_AFFIDAVIT", "MAIL", False)
        under_review = get_cure_notice(notice["id"])
        assert under_review["status"] == "UNDER_EVIDENCE_REVIEW"
        assert under_review["evidence_submission_count"] == 1

        after_first = _adjudicate_deficient(notice["id"], "AFFIRMATION_UNSIGNED")
        assert after_first["status"] == "ISSUED"
        assert after_first["deficiency_count"] == 1

        _submit_evidence(notice["id"], "ID_COPY", "PORTAL", False)
        after_second = _adjudicate_deficient(notice["id"], "WRONG_EVIDENCE_TYPE")
        assert after_second["status"] == "ISSUED"
        assert after_second["deficiency_count"] == 2

        third_evidence = _submit_evidence(notice["id"], "SIGNED_AFFIDAVIT", "IN_PERSON", True)
        cured = validate_success(
            api_client.adjudicate_cure_notice(notice["id"], {"outcome": "CURE"},
                                             SUPERVISOR), 200)
        assert cured["status"] == "CURED"
        assert cured["evidence_submission_count"] == 3
        assert cured["deficiency_count"] == 2
        assert _instant(cured["cure_deadline_at"]) == _instant(frozen_deadline)

        assert get_envelope(bundle["envelope"]["id"])["signature_status"] == "ACCEPTED"
        assert get_election(bundle["election"]["id"])["open_cure_count"] == 0

        rows, meta = validate_paginated(
            api_client.list_cure_evidence(CLERK, params={"cure_notice_id": notice["id"]}))
        assert meta["total_count"] == 3
        by_id = {row["id"]: row for row in rows}
        assert by_id[first_evidence["id"]]["accepted"] is False
        assert by_id[first_evidence["id"]]["deficiency_reason_code"] == "AFFIRMATION_UNSIGNED"
        assert by_id[third_evidence["id"]]["accepted"] is True

    def test_looping_cannot_outlive_the_frozen_deadline(self):
        """The loop terminator is the frozen deadline, so a submission after it is refused
        no matter how many deficient rounds preceded it.

        "Submission requires the notice to be in `ISSUED`, else `ERR_CURE_STATE_INVALID`, requires the logical clock to be at or before the notice's frozen `cure_deadline_at`, else `ERR_CURE_DEADLINE_PASSED`, and requires the election's posture to be anything other than `CERTIFIED`."

        Design: Difficulty/non_linear_state_machine/cure_notice_evidence_deficiency_cycle
        """
        bundle = _setup_missing_signature_notice()
        notice = bundle["cure_notice"]
        frozen_deadline = notice["cure_deadline_at"]

        _submit_evidence(notice["id"], "SIGNED_AFFIDAVIT", "MAIL", False)
        _adjudicate_deficient(notice["id"], "AFFIRMATION_UNSIGNED")
        _submit_evidence(notice["id"], "ID_COPY", "EMAIL", False)
        after_second = _adjudicate_deficient(notice["id"], "ILLEGIBLE")
        assert after_second["status"] == "ISSUED"
        assert after_second["deficiency_count"] == 2

        set_clock("2026-11-20T00:00:00Z")
        validate_error(
            api_client.submit_cure_evidence(notice["id"],
                                           {"evidence_type": "SIGNED_AFFIDAVIT",
                                            "submission_channel": "MAIL",
                                            "affirmation_signed": True},
                                           CLERK),
            ApiErrorId.ERR_CURE_DEADLINE_PASSED, 422)

        unchanged = get_cure_notice(notice["id"])
        assert unchanged["status"] == "ISSUED"
        assert unchanged["evidence_submission_count"] == 2
        assert _instant(unchanged["cure_deadline_at"]) == _instant(frozen_deadline)

    def test_adjudication_is_refused_while_the_notice_sits_back_in_issued(self):
        """The cycle only admits an adjudication from the evidence-review leg, so the leg
        the loop returns to cannot be adjudicated again.

        "A `CanvassSupervisor` adjudicates. The notice must be in `UNDER_EVIDENCE_REVIEW`, else `ERR_CURE_STATE_INVALID`, and the adjudication names an `outcome` of either `CURE` or `DEFICIENT`, optionally with a `deficiency_reason_code` drawn from `AFFIRMATION_UNSIGNED`, `WRONG_EVIDENCE_TYPE`, and `ILLEGIBLE`."

        Design: Difficulty/non_linear_state_machine/cure_notice_evidence_deficiency_cycle
        """
        bundle = _setup_missing_signature_notice()
        notice = bundle["cure_notice"]

        _submit_evidence(notice["id"], "SIGNED_AFFIDAVIT", "MAIL", True)
        back_to_issued = _adjudicate_deficient(notice["id"], "ILLEGIBLE")
        assert back_to_issued["status"] == "ISSUED"

        validate_error(
            api_client.adjudicate_cure_notice(notice["id"], {"outcome": "CURE"}, SUPERVISOR),
            ApiErrorId.ERR_CURE_STATE_INVALID, 409)

        still_open = get_cure_notice(notice["id"])
        assert still_open["status"] == "ISSUED"
        assert still_open["deficiency_count"] == 1
        assert get_election(bundle["election"]["id"])["open_cure_count"] == 1


def _get_request(request_id):
    return get_success_data(api_client.get_ballot_request(request_id, CLERK))


def _get_packet(packet_id):
    return get_success_data(api_client.get_ballot_packet(packet_id, CLERK))


class TestBatchDispatchCascade:
    """Dispatch is a depth-three chain: packets mail, their requests follow, and the
    election's counters and posture move because the requests reached MAILED."""

    def test_dispatch_drives_packet_request_and_election_in_one_call(self):
        """A single dispatch on a PRE_MAIL election mails the packet, carries its request
        to MAILED, recomputes the counters and auto-advances the posture.

        "Third link, caused by the requests reaching `MAILED`: the election's `packets_mailed_count` and `outstanding_packet_count` are recomputed, and the election auto-advances `PRE_MAIL → MAILING` if it is still in `PRE_MAIL`."

        Design: Difficulty/transitive_cascade/batch_dispatch_packet_request_election_chain
        """
        election = setup_election(clock="2026-09-10T00:00:00Z")
        assert election["posture"] == "PRE_MAIL"
        bundle = setup_sealed_batch(election, weights=(28,))

        dispatched = validate_success(
            api_client.dispatch_batch(bundle["batch"]["id"], CLERK), 200)
        assert dispatched["status"] == "DISPATCHED"
        assert _instant(dispatched["dispatched_at"]) == _instant("2026-09-10T00:00:00Z")

        packet = _get_packet(bundle["packets"][0]["id"])
        assert packet["status"] == "MAILED"
        assert _instant(packet["mailed_at"]) == _instant("2026-09-10T00:00:00Z")

        assert _get_request(bundle["requests"][0]["id"])["status"] == "MAILED"

        after = get_election(election["id"])
        assert after["posture"] == "MAILING"
        assert after["packets_mailed_count"] == 1
        assert after["outstanding_packet_count"] == 1

        accountability = get_accountability(election["id"])
        assert accountability["accountability_delta"] == 0
        assert accountability["reconciliation_status"] == "IN_BALANCE"

    def test_auto_advanced_posture_entry_is_attributed_to_the_system(self):
        """The posture link fired without an admin asking for it, so its single log entry
        names the system as actor and points at the election.

        "When either fires automatically the appended transparency entry records `actor_role` as `system`; when taken explicitly it records the acting admin."

        Design: Difficulty/transitive_cascade/batch_dispatch_packet_request_election_chain
        """
        election = setup_election(clock="2026-09-10T00:00:00Z")
        bundle = setup_sealed_batch(election, weights=(28,))
        validate_success(api_client.dispatch_batch(bundle["batch"]["id"], CLERK), 200)

        posture_entries = [entry for entry in list_transparency_log(election["id"])
                           if entry["event_type"] == "POSTURE_CHANGED"]
        assert len(posture_entries) == 1
        entry = posture_entries[0]
        assert entry["actor_role"] == "system"
        assert entry["actor_user_id"] is None
        assert entry["subject_entity"] == "Election"
        assert entry["subject_id"] == election["id"]
        assert entry["ballot_content_disclosed"] is False

    def test_every_link_fires_once_per_packet_in_a_two_packet_batch(self):
        """Both packets mail and both requests follow, and the counters land on the
        recomputed population rather than on a single increment.

        "First link: every packet in the batch still in `QUEUED` moves `QUEUED → MAILED` with `mailed_at` stamped from the logical clock."

        Design: Difficulty/transitive_cascade/batch_dispatch_packet_request_election_chain
        """
        election = setup_election(clock="2026-09-10T00:00:00Z")
        bundle = setup_sealed_batch(election, weights=(28, 57))

        validate_success(api_client.dispatch_batch(bundle["batch"]["id"], CLERK), 200)

        for packet in bundle["packets"]:
            assert _get_packet(packet["id"])["status"] == "MAILED"
        for request in bundle["requests"]:
            assert _get_request(request["id"])["status"] == "MAILED"

        after = get_election(election["id"])
        assert after["posture"] == "MAILING"
        assert after["packets_mailed_count"] == 2
        assert after["outstanding_packet_count"] == 2

        dispatch_entries = [entry for entry in list_transparency_log(election["id"])
                            if entry["event_type"] == "BATCH_DISPATCHED"]
        assert len(dispatch_entries) == 1

    def test_an_already_mailing_election_records_the_admin_not_the_system(self):
        """When the posture step was taken by hand before any dispatch, the third link has
        nothing left to advance and the sole posture entry names the admin.

        "The advance `PRE_MAIL → MAILING` fires automatically the first time a mailing batch of this election dispatches, and it can also be taken explicitly before any dispatch has occurred; it requires the current posture to be `PRE_MAIL`, and it recomputes `packets_mailed_count` and `outstanding_packet_count`."

        Design: Difficulty/transitive_cascade/batch_dispatch_packet_request_election_chain
        """
        election = setup_election(posture="MAILING", clock="2026-09-10T00:00:00Z")
        bundle = setup_sealed_batch(election, weights=(28,))

        validate_success(api_client.dispatch_batch(bundle["batch"]["id"], CLERK), 200)

        after = get_election(election["id"])
        assert after["posture"] == "MAILING"
        assert after["packets_mailed_count"] == 1
        assert _get_request(bundle["requests"][0]["id"])["status"] == "MAILED"

        posture_entries = [entry for entry in list_transparency_log(election["id"])
                           if entry["event_type"] == "POSTURE_CHANGED"]
        assert len(posture_entries) == 1
        assert posture_entries[0]["actor_role"] == "ElectionsAdmin"


def _get_voter(voter_id):
    return get_success_data(api_client.get_voter(voter_id, CLERK))


def _get_enrollment(enrollment_id):
    return get_success_data(api_client.get_enrollment(enrollment_id, CLERK))


def _log_request_and_fail_address(voter_id, election, ncoa_result):
    """Log a fresh request for a voter, threading the voter's current version, and
    record one change-of-address outcome against its pending verification."""
    voter = _get_voter(voter_id)
    request = create_ballot_request(voter, election)
    verification = get_address_verification_for(request["id"])
    resolved = get_success_data(
        api_client.submit_address_result(verification["id"],
                                        {"ncoa_result": ncoa_result}, CLERK))
    return {"request": request, "verification": resolved}


def _setup_enrolled_voter():
    """An election on 2026-09-10 plus one voter holding an ACTIVE enrollment."""
    election = setup_election(clock="2026-09-10T00:00:00Z")
    voter = create_voter(full_name="Gil Pratt", residence_address="12 Larch St")
    enrollment = create_enrollment(voter["id"])
    assert enrollment["status"] == "ACTIVE"
    assert enrollment["consecutive_undeliverable_count"] == 0
    assert _get_voter(voter["id"])["permanent_absentee_active"] is True
    return {"election": election, "voter": voter, "enrollment": enrollment}


class TestAddressFailureSuspensionCascade:
    """A non-forwardable change-of-address result holds the request, the hold drives the
    enrollment counter to its threshold, and the suspension clears the voter's flag."""

    def test_second_non_forwardable_result_suspends_and_clears_the_voter_flag(self):
        """Two consecutive non-forwardable results reach the threshold, so the enrollment
        suspends and the third link flips the voter's flag and logs the suspension.

        "The third link follows from that suspension: the voter's `permanent_absentee_active` is set to false and an `ENROLLMENT_SUSPENDED` entry naming the enrollment as its subject is appended."

        Design: Difficulty/transitive_cascade/address_failure_enrollment_suspension_voter_flag_chain
        """
        base = _setup_enrolled_voter()
        first = _log_request_and_fail_address(base["voter"]["id"], base["election"],
                                              "MATCH_NON_FORWARDABLE")
        after_first = _get_enrollment(base["enrollment"]["id"])
        assert after_first["consecutive_undeliverable_count"] == 1
        assert after_first["status"] == "ACTIVE"

        second = _log_request_and_fail_address(base["voter"]["id"], base["election"],
                                               "MATCH_NON_FORWARDABLE")
        assert second["verification"]["status"] == "FAILED"

        held = _get_request(second["request"]["id"])
        assert held["status"] == "ADDRESS_HOLD"
        assert held["forwarding_class"] == "NON_FORWARDABLE"

        suspended = _get_enrollment(base["enrollment"]["id"])
        assert suspended["consecutive_undeliverable_count"] == 2
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason_code"] == "ADDRESS_NON_FORWARDABLE"

        assert _get_voter(base["voter"]["id"])["permanent_absentee_active"] is False

        entries = [entry for entry in list_transparency_log(base["election"]["id"])
                   if entry["event_type"] == "ENROLLMENT_SUSPENDED"]
        assert len(entries) == 1
        assert entries[0]["subject_entity"] == "PermanentAbsenteeEnrollment"
        assert entries[0]["subject_id"] == base["enrollment"]["id"]

        assert _get_request(first["request"]["id"])["status"] == "SUPERSEDED"

    def test_one_non_forwardable_result_stops_at_the_first_link(self):
        """A single failure holds the request and counts once, but the chain stops short of
        the suspension so the voter's flag is untouched.

        "Its second link reaches the voter's permanent absentee enrollment: if that enrollment's status is `ACTIVE`, its `consecutive_undeliverable_count` increments by one, and when the new value reaches two or more the enrollment transitions `ACTIVE → SUSPENDED` with `suspension_reason_code` set to `ADDRESS_NON_FORWARDABLE`."

        Design: Difficulty/transitive_cascade/address_failure_enrollment_suspension_voter_flag_chain
        """
        base = _setup_enrolled_voter()
        outcome = _log_request_and_fail_address(base["voter"]["id"], base["election"],
                                                "MATCH_NON_FORWARDABLE")
        assert outcome["verification"]["status"] == "FAILED"

        held = _get_request(outcome["request"]["id"])
        assert held["status"] == "ADDRESS_HOLD"
        assert held["forwarding_class"] == "NON_FORWARDABLE"

        enrollment = _get_enrollment(base["enrollment"]["id"])
        assert enrollment["consecutive_undeliverable_count"] == 1
        assert enrollment["status"] == "ACTIVE"
        assert enrollment["suspension_reason_code"] is None

        assert _get_voter(base["voter"]["id"])["permanent_absentee_active"] is True

        entries = [entry for entry in list_transparency_log(base["election"]["id"])
                   if entry["event_type"] == "ENROLLMENT_SUSPENDED"]
        assert entries == []

    def test_no_match_holds_the_request_without_entering_the_cascade(self):
        """A no-match result also fails the verification and holds the request, but it is
        not the non-forwardable head, so the enrollment counter never moves.

        "`forwarding_class` becomes `NON_FORWARDABLE` when the result was `MATCH_NON_FORWARDABLE` and is left at `UNKNOWN` when it was `NO_MATCH`."

        Design: Difficulty/transitive_cascade/address_failure_enrollment_suspension_voter_flag_chain
        """
        base = _setup_enrolled_voter()
        for _ in range(2):
            outcome = _log_request_and_fail_address(base["voter"]["id"], base["election"],
                                                    "NO_MATCH")
            assert outcome["verification"]["status"] == "FAILED"
            held = _get_request(outcome["request"]["id"])
            assert held["status"] == "ADDRESS_HOLD"
            assert held["forwarding_class"] == "UNKNOWN"

        enrollment = _get_enrollment(base["enrollment"]["id"])
        assert enrollment["consecutive_undeliverable_count"] == 0
        assert enrollment["status"] == "ACTIVE"
        assert _get_voter(base["voter"]["id"])["permanent_absentee_active"] is True
