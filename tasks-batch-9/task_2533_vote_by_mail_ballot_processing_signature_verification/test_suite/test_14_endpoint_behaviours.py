"""Endpoint behaviours: soft deletes, the canvass checkpoint, the accountability
read, the address re-check gate, rejection side effects, and challenge sustain.

Every test builds its own world from an empty database through the public API.
"""
from datetime import datetime

from test_helpers import (
    ADMIN,
    CLERK,
    OBSERVER,
    SUPERVISOR,
    ApiErrorId,
    api_client,
    check_in_observer,
    create_ballot_request,
    create_enrollment,
    create_voter,
    get_address_verification_for,
    get_election,
    get_envelope,
    get_success_data,
    intake_envelope,
    issue_cure_notice,
    make_observer_headers,
    make_signature_reviewer_headers,
    mark_packet_undeliverable,
    schedule_observer_session,
    set_clock,
    setup_accepted_envelope,
    setup_election,
    setup_envelope_with_open_review,
    setup_mailed_packets,
    submit_address_result,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value):
    """Parse an emitted UTC instant so a stamp may be compared to the logical
    clock value regardless of how many fractional digits it carries."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _decide_missing_signature(review, notes="no signature in the signature box"):
    """Submit a MISSING_SIGNATURE decision, which carries no similarity_score."""
    headers = make_signature_reviewer_headers(review["reviewer_id"])
    return get_success_data(api_client.submit_signature_decision(
        review["id"], {"decision": "MISSING_SIGNATURE", "notes": notes}, headers))


class TestEnrollmentRemoval:
    def test_enrollment_delete_marks_removed_and_clears_the_voter_flag(self):
        """Removing a voter from the permanent absentee list is a soft state change:
        the enrollment row survives at REMOVED and the voter's derived flag drops.

        PRD: "Removal is permitted from either `ACTIVE` or `SUSPENDED`, else
        `ERR_ENROLLMENT_NOT_SUSPENDED`; it sets the status to the terminal `REMOVED`
        and clears the voter's `permanent_absentee_active` to false."
        Design: Corner/endpoints/enrollment_delete_marks_removed_and_clears_the_voter_flag
        """
        set_clock("2026-09-10T09:00:00Z")
        voter = create_voter()
        enrollment = create_enrollment(voter["id"])
        assert enrollment["status"] == "ACTIVE"
        enrolled_voter = validate_success(api_client.get_voter(voter["id"], CLERK), 200)
        assert enrolled_voter["permanent_absentee_active"] is True

        removed = validate_success(
            api_client.delete_enrollment(enrollment["id"], CLERK), 200)
        assert removed["status"] == "REMOVED"

        reread = validate_success(api_client.get_enrollment(enrollment["id"], CLERK), 200)
        assert reread["status"] == "REMOVED", "the removed enrollment is retained for audit"

        after = validate_success(api_client.get_voter(voter["id"], CLERK), 200)
        assert after["permanent_absentee_active"] is False

        rows, meta = validate_paginated(
            api_client.list_enrollments(CLERK, params={"voter_id": voter["id"]}))
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "REMOVED"


class TestCanvassCheckpoint:
    def test_canvass_sweep_expires_the_overdue_cure_and_reports_its_own_counters(self):
        """One sweep taken a second past the frozen cure deadline expires the notice,
        drives the three-link rejection cascade, and reports only its own deltas.

        PRD: "Each expiry then drives the three-link rejection cascade: the envelope's
        signature dimension moves `CURE_REQUIRED → REJECTED` and the election's
        `rejected_envelope_count` is recomputed; caused by that, the envelope's custody
        dimension moves `SEALED → SEQUESTERED`; and caused by the rejection, the voter's
        `provisional_ballot_eligible` is set to true, the election's
        `provisional_referral_count` increments by one, and a `PROVISIONAL_REFERRAL`
        entry naming the voter as its subject is appended."
        Design: Corner/endpoints/canvass_sweep_expires_the_overdue_cure_and_reports_its_own_counters
        """
        bundle = setup_envelope_with_open_review()
        election_id = bundle["election"]["id"]
        envelope_id = bundle["envelope"]["id"]
        voter_id = bundle["voters"][0]["id"]

        _decide_missing_signature(bundle["review"])
        notice = issue_cure_notice(envelope_id)
        assert _instant(notice["cure_deadline_at"]) == _instant("2026-11-19T20:00:00Z"), \
            "the notice freezes the canvass lock less one whole day"

        set_clock("2026-11-19T20:00:01Z")
        sweep = validate_success(
            api_client.run_canvass_sweep(election_id, {}, ADMIN), 200)

        assert sweep["canvass_sweep_index"] == 1
        assert sweep["expired_cure_count"] == 1
        assert sweep["finalized_envelope_count"] == 1
        assert sweep["sequestered_envelope_count"] == 1
        assert sweep["rejected_envelope_count"] == 1
        assert sweep["closed_observer_session_count"] == 0
        assert sweep["reconciliation_status"] == "IN_BALANCE"

        expired = validate_success(api_client.get_cure_notice(notice["id"], CLERK), 200)
        assert expired["status"] == "EXPIRED"
        assert _instant(expired["resolved_at"]) == _instant("2026-11-19T20:00:01Z")

        envelope = get_envelope(envelope_id)
        assert envelope["signature_status"] == "REJECTED"
        assert envelope["custody_status"] == "SEQUESTERED"
        assert envelope["final_timeliness"] == "TIMELY"

        voter = validate_success(api_client.get_voter(voter_id, CLERK), 200)
        assert voter["provisional_ballot_eligible"] is True

        election = get_election(election_id)
        assert election["open_cure_count"] == 0
        assert election["rejected_envelope_count"] == 1
        assert election["provisional_referral_count"] == 1
        assert election["canvass_sweep_index"] == 1

        _, meta = validate_paginated(api_client.list_transparency_log(
            ADMIN, params={"election_id": election_id,
                           "event_type": "PROVISIONAL_REFERRAL"}))
        assert meta["total_count"] == 1


class TestAccountabilityRead:
    def test_accountability_read_matches_the_mailing_and_intake_ledger(self):
        """Three mailed packets, one returned and one undeliverable, reconcile to a
        zero delta, and the money figures are the sum of the per-packet charges.

        PRD: "`packets_mailed_count` is the number of those packets whose status is
        `MAILED`, `RETURNED`, or `UNDELIVERABLE`."
        Design: Corner/endpoints/accountability_read_matches_the_mailing_and_intake_ledger
        """
        bundle = setup_mailed_packets(count=3, weights=(28, 57, 85), posture="MAILING",
                                     clock="2026-09-10T09:00:00Z")
        election_id = bundle["election"]["id"]

        set_clock("2026-11-03T12:00:00Z")
        intake_envelope(bundle["packets"][0]["id"], "DROPBOX")
        mark_packet_undeliverable(bundle["packets"][2]["id"], "MOVED_NO_FORWARD")

        report = validate_success(
            api_client.get_accountability(election_id, OBSERVER), 200)

        assert report["election_id"] == election_id
        assert report["packets_mailed_count"] == 3
        assert report["returned_packet_count"] == 1
        assert report["undeliverable_packet_count"] == 1
        assert report["outstanding_packet_count"] == 1
        assert report["envelopes_received_count"] == 1
        assert report["accountability_delta"] == 0
        assert report["reconciliation_status"] == "IN_BALANCE"
        assert report["countable_envelope_count"] == 0, \
            "an UNVERIFIED, still-sealed envelope is not countable"
        assert report["attributable_ballot_count"] == 1
        assert report["postage_committed_cents"] == 591, "141 + 197 + 253"
        assert report["postage_actual_cents"] == 591


class TestAddressRecheck:
    def test_address_recheck_is_allowed_only_from_address_hold(self):
        """A request held by a non-forwardable result may be re-checked once; after
        the re-check clears it the same call is refused.

        PRD: "The clerk may re-open address verification for it, which creates a fresh
        verification in `PENDING` for that request and requires the request's status to
        be exactly `ADDRESS_HOLD`, else `ERR_REQUEST_STATE_INVALID`."
        Design: Corner/endpoints/address_recheck_is_allowed_only_from_address_hold
        """
        election = setup_election(clock="2026-09-10T09:00:00Z")
        voter = create_voter()
        request = create_ballot_request(voter, election)
        first = get_address_verification_for(request["id"])
        submit_address_result(first["id"], "MATCH_NON_FORWARDABLE")

        held = validate_success(api_client.get_ballot_request(request["id"], CLERK), 200)
        assert held["status"] == "ADDRESS_HOLD"
        assert held["forwarding_class"] == "NON_FORWARDABLE"

        reopened = validate_success(api_client.address_recheck(request["id"], CLERK), 201)
        assert reopened["status"] == "PENDING"
        assert reopened["ncoa_result"] is None
        assert reopened["evaluated_at"] is None
        assert reopened["ballot_request_id"] == request["id"]
        assert reopened["id"] != first["id"]

        _, meta = validate_paginated(api_client.list_address_verifications(
            CLERK, params={"ballot_request_id": request["id"]}))
        assert meta["total_count"] == 2

        submit_address_result(reopened["id"], "MATCH_FORWARDABLE",
                             verified_mailing_address="77 Birch Ln, Springfield",
                             forwardable=True)
        cleared = validate_success(api_client.get_ballot_request(request["id"], CLERK), 200)
        assert cleared["status"] == "ADDRESS_CLEARED"
        assert cleared["forwarding_class"] == "FORWARDABLE"

        validate_error(api_client.address_recheck(request["id"], CLERK),
                       ApiErrorId.ERR_REQUEST_STATE_INVALID, 409)

        _, meta_after = validate_paginated(api_client.list_address_verifications(
            CLERK, params={"ballot_request_id": request["id"]}))
        assert meta_after["total_count"] == 2, "the refused re-check minted nothing"


class TestRequestRejection:
    def test_request_reject_fails_the_pending_address_verification(self):
        """Rejecting a request in the same response drives its still-pending address
        verification to FAILED, and the rejected request can no longer be approved.

        PRD: "Rejection from any of the three also sets every linked address
        verification still in `PENDING` to `FAILED`."
        Design: Corner/endpoints/request_reject_fails_the_pending_address_verification
        """
        election = setup_election(clock="2026-09-10T09:00:00Z")
        voter = create_voter()
        request = create_ballot_request(voter, election)
        verification = get_address_verification_for(request["id"])
        assert request["status"] == "RECEIVED"
        assert verification["status"] == "PENDING"

        rejected = validate_success(api_client.reject_ballot_request(
            request["id"], {"rejection_reason_code": "VOTER_WITHDREW"}, CLERK), 200)
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason_code"] == "VOTER_WITHDREW"

        failed = validate_success(
            api_client.get_address_verification(verification["id"], CLERK), 200)
        assert failed["status"] == "FAILED"

        validate_error(api_client.approve_ballot_request(request["id"], CLERK),
                       ApiErrorId.ERR_REQUEST_STATE_INVALID, 409)

        unmoved = validate_success(api_client.get_ballot_request(request["id"], CLERK), 200)
        assert unmoved["status"] == "REJECTED"


class TestChallengeAdjudication:
    def test_sustained_challenge_sequesters_the_envelope_and_refers_the_voter(self):
        """A checked-in observer's challenge sequesters an accepted envelope, and
        sustaining it rejects the signature and refers the voter to the provisional
        process rather than returning the ballot to the countable pool.

        PRD: "Sustaining a challenge moves the challenge dimension
        `CHALLENGED → SUSTAINED`, sets the envelope's `signature_status` to `REJECTED`
        while leaving its custody dimension at `SEQUESTERED`, sets the voter's
        `provisional_ballot_eligible` to true, increments the election's
        `provisional_referral_count` by one, and appends a `PROVISIONAL_REFERRAL` entry
        whose subject is the voter."
        Design: Corner/endpoints/sustained_challenge_sequesters_the_envelope_and_refers_the_voter
        """
        bundle = setup_accepted_envelope(similarity_score=80)
        election_id = bundle["election"]["id"]
        envelope_id = bundle["envelope"]["id"]
        voter_id = bundle["voters"][0]["id"]
        assert bundle["envelope"]["signature_status"] == "ACCEPTED"
        assert bundle["envelope"]["custody_status"] == "SEALED"

        session = schedule_observer_session(
            election_id, "obs-dem-1", headers=CLERK, party_affiliation="DEM",
            station_area="INTAKE", window_start_at="2026-11-03T14:00:00Z",
            window_end_at="2026-11-03T16:00:00Z")
        set_clock("2026-11-03T14:30:00Z")
        check_in_observer(session)
        observer = make_observer_headers("obs-dem-1")

        challenged = validate_success(api_client.file_challenge(
            envelope_id, {"challenge_reason_code": "IDENTITY_DISPUTE"}, observer), 200)
        assert challenged["challenge_status"] == "CHALLENGED"
        assert challenged["custody_status"] == "SEQUESTERED"

        findings = "Identity could not be established from the affirmation."
        sustained = validate_success(api_client.adjudicate_challenge(
            envelope_id, {"outcome": "SUSTAIN", "challenge_findings": findings},
            SUPERVISOR), 200)
        assert sustained["challenge_status"] == "SUSTAINED"
        assert sustained["custody_status"] == "SEQUESTERED"
        assert sustained["signature_status"] == "REJECTED"
        assert sustained["challenge_findings"] == findings

        voter = validate_success(api_client.get_voter(voter_id, CLERK), 200)
        assert voter["provisional_ballot_eligible"] is True

        election = get_election(election_id)
        assert election["provisional_referral_count"] == 1

        report = validate_success(
            api_client.get_accountability(election_id, SUPERVISOR), 200)
        assert report["countable_envelope_count"] == 0, \
            "a SUSTAINED challenge is never countable"
        assert report["attributable_ballot_count"] == 0, \
            "a SEQUESTERED envelope whose signature is REJECTED is not attributable"

        rows, meta = validate_paginated(api_client.list_transparency_log(
            ADMIN, params={"election_id": election_id,
                           "event_type": "CHALLENGE_FILED"}))
        assert meta["total_count"] == 1
        assert rows[0]["actor_role"] == "Observer"
