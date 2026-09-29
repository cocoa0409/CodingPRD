"""State-machine edges of the Vote-By-Mail Processing API.

Each test drives one declared transition — or one refused transition — from an
empty database, and checks both the record that moved and the records the PRD
says move with it.
"""
from datetime import datetime

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    address_result_payload,
    advance_posture_to,
    api_client,
    assert_accountability_identity,
    assert_mailing_batch,
    assert_remake_record,
    assert_voter,
    create_ballot_request,
    create_election,
    create_trained_reviewer,
    create_voter,
    cure_adjudication_payload,
    get_address_verification_for,
    get_envelope,
    mailing_batch_payload,
    make_observer_headers,
    observer_session_payload,
    open_remake,
    set_clock,
    setup_envelope_with_open_review,
    setup_issued_cure_notice,
    setup_mailed_packets,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["elections_admin_headers"]
CLERK = TEST_USERS["elections_clerk_headers"]
SUPERVISOR = TEST_USERS["canvass_supervisor_headers"]

VOTER_FIELDS = {
    "full_name": "Vera Ames",
    "party_affiliation": "DEM",
    "residence_address": "11 Ash St, Springfield",
    "last_signature_update_at": "2026-01-05T00:00:00Z",
}


def _instant(value):
    """Parse an ISO 8601 UTC instant so two spellings of one instant compare equal."""
    assert isinstance(value, str), f"expected an ISO 8601 UTC string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _log_total(election_id, event_type):
    """How many transparency entries of one event type this election carries."""
    _, meta = validate_paginated(
        api_client.list_transparency_log(
            ADMIN, params={"election_id": election_id, "event_type": event_type}))
    return meta["total_count"]


def _setup_open_remake_over_assigned_review():
    """An envelope in PENDING_REVIEW whose round-one review is still ASSIGNED, plus an
    OPEN remake session held by a bipartisan pair who reviewed nothing.

    The three reviewers are registered at distinct logical-clock instants so the
    selector's created-at tie-break is unambiguous and the round is assigned to the
    reviewer who is not on the remake team.
    """
    set_clock("2026-08-02T00:00:00Z")
    assigned_reviewer = create_trained_reviewer(full_name="Rosa Vidal",
                                               party_affiliation="DEM")
    set_clock("2026-08-03T00:00:00Z")
    member_a = create_trained_reviewer(full_name="Bo Reyes", party_affiliation="REP")
    set_clock("2026-08-04T00:00:00Z")
    member_b = create_trained_reviewer(full_name="Cass Dole", party_affiliation="DEM")

    bundle = setup_envelope_with_open_review(
        reviewers=[assigned_reviewer, member_a, member_b])
    review = bundle["review"]
    assert review["reviewer_id"] == assigned_reviewer["id"], \
        "the earliest-registered candidate takes round one"
    assert review["status"] == "ASSIGNED"

    envelope = get_envelope(bundle["envelope"]["id"])
    assert envelope["custody_status"] == "SEALED"
    assert envelope["signature_status"] == "PENDING_REVIEW"

    bundle["assigned_reviewer"] = assigned_reviewer
    bundle["team"] = (member_a, member_b)
    bundle["envelope"] = envelope
    bundle["remake"] = open_remake(envelope, member_a, member_b)
    return bundle


class TestAddressVerificationEdges:
    """The address branch that unblocks the mailing, and the approval gate ahead of it."""

    def test_address_result_match_same_clears_the_request_and_stamps_same_address(self):
        """A MATCH_SAME result clears the verification with evaluated_at read from the
        logical clock and, in the same request, drives the ballot request to
        ADDRESS_CLEARED with forwarding_class SAME_ADDRESS and its frozen snapshot intact.

        PRD: "On `MATCH_SAME` or `MATCH_FORWARDABLE` the verification moves `PENDING → CLEARED` and drives the request `RECEIVED → ADDRESS_CLEARED`."

        Design: Corner/state_machines/address_result_match_same_clears_the_request_and_stamps_same_address
        """
        set_clock("2026-09-10T09:00:00Z")
        election = create_election()
        voter = create_voter(**VOTER_FIELDS)
        request = create_ballot_request(voter, election)
        verification = get_address_verification_for(request["id"])
        assert verification["status"] == "PENDING"

        validate_success(
            api_client.submit_address_result(
                verification["id"], address_result_payload("MATCH_SAME"), CLERK),
            200)

        verification_after = validate_success(
            api_client.get_address_verification(verification["id"], CLERK), 200)
        assert verification_after["status"] == "CLEARED"
        assert verification_after["ncoa_result"] == "MATCH_SAME"
        assert _instant(verification_after["evaluated_at"]) == _instant("2026-09-10T09:00:00Z")

        request_after = validate_success(
            api_client.get_ballot_request(request["id"], CLERK), 200)
        assert request_after["status"] == "ADDRESS_CLEARED"
        assert request_after["forwarding_class"] == "SAME_ADDRESS"
        # Only MATCH_FORWARDABLE overwrites the snapshot, so it still holds the residence.
        assert request_after["mailing_address_snapshot"] == "11 Ash St, Springfield"

        voter_after = validate_success(api_client.get_voter(voter["id"], CLERK), 200)
        assert_voter(voter_after)
        assert voter_after["permanent_absentee_active"] is False

    def test_approve_from_received_returns_request_state_invalid(self):
        """Approval is declared only out of ADDRESS_CLEARED, so a request still in
        RECEIVED is refused, stays RECEIVED, keeps its PENDING verification and gains
        no permanent absentee enrollment.

        PRD: "It requires the request to be in `ADDRESS_CLEARED`, else `ERR_REQUEST_STATE_INVALID`"

        Design: Corner/state_machines/approve_from_received_returns_request_state_invalid
        """
        set_clock("2026-09-10T09:00:00Z")
        election = create_election()
        voter = create_voter(**VOTER_FIELDS)
        request = create_ballot_request(voter, election)
        verification = get_address_verification_for(request["id"])
        assert request["status"] == "RECEIVED"

        validate_error(api_client.approve_ballot_request(request["id"], CLERK),
                       ApiErrorId.ERR_REQUEST_STATE_INVALID, 409)

        request_after = validate_success(
            api_client.get_ballot_request(request["id"], CLERK), 200)
        assert request_after["status"] == "RECEIVED"

        _, enrollment_meta = validate_paginated(
            api_client.list_enrollments(CLERK, params={"voter_id": voter["id"]}))
        assert enrollment_meta["total_count"] == 0

        verification_after = validate_success(
            api_client.get_address_verification(verification["id"], CLERK), 200)
        assert verification_after["status"] == "PENDING"


class TestMailingBatchEdges:
    """Batch initial state, the packet-level undeliverable move, and re-dispatch."""

    @pytest.mark.parametrize("batch_type,expected_send_by", [
        ("DOMESTIC_INITIAL", "2026-10-05"),
        ("UOCAVA", "2026-09-19"),
        ("SUPPLEMENTAL", "2026-10-05"),
    ])
    def test_mailing_batch_starts_in_draft_with_derived_required_send_by_date(
            self, batch_type, expected_send_by):
        """A new batch opens in DRAFT with an empty packet count and no postage, and its
        statutory send-by date is derived from the batch type: the UOCAVA deadline for a
        UOCAVA batch and the domestic deadline for every other type.

        PRD: "Its `required_send_by_date` is derived, not supplied: it is the election's `uocava_send_deadline_date` when `batch_type` is `UOCAVA`, and the election's `domestic_send_deadline_date` for every other batch type."

        Design: Corner/state_machines/mailing_batch_starts_in_draft_with_derived_required_send_by_date
        """
        set_clock("2026-09-10T09:00:00Z")
        election = create_election()

        data = validate_success(
            api_client.create_mailing_batch(
                mailing_batch_payload(election["id"], batch_type=batch_type,
                                     scheduled_send_date="2026-09-25"),
                CLERK),
            201)

        assert_mailing_batch(data)
        assert data["status"] == "DRAFT"
        assert data["batch_type"] == batch_type
        assert data["required_send_by_date"] == expected_send_by
        assert data["packet_count"] == 0
        assert data["estimated_postage_cents"] == 0
        assert data["actual_postage_cents"] is None
        assert data["sealed_at"] is None
        assert data["dispatched_at"] is None
        assert data["cancellation_reason_code"] is None

        election_after = validate_success(
            api_client.get_election(election["id"], ADMIN), 200)
        assert election_after["postage_committed_cents"] == 0, \
            "opening a batch commits no postage"

    def test_packet_undeliverable_recomputes_election_accountability_counters(self):
        """A carrier return moves the packet MAILED to UNDELIVERABLE, shifts the election
        from one outstanding packet to one undeliverable one while packets_mailed_count
        holds at 1, keeps the reconciliation in balance, and appends one log entry.

        PRD: "The election's `undeliverable_packet_count` and `outstanding_packet_count` are recomputed, and a `PACKET_UNDELIVERABLE` entry is appended."

        Design: Corner/state_machines/packet_undeliverable_recomputes_election_accountability_counters
        """
        bundle = setup_mailed_packets(count=1, posture="MAILING",
                                    clock="2026-09-10T09:00:00Z")
        packet = bundle["packets"][0]
        election_id = bundle["election"]["id"]
        assert packet["status"] == "MAILED"

        validate_success(
            api_client.mark_packet_undeliverable(
                packet["id"], {"undeliverable_reason_code": "NO_SUCH_ADDRESS"}, CLERK),
            200)

        packet_after = validate_success(
            api_client.get_ballot_packet(packet["id"], CLERK), 200)
        assert packet_after["status"] == "UNDELIVERABLE"
        assert packet_after["undeliverable_reason_code"] == "NO_SUCH_ADDRESS"

        accountability = validate_success(
            api_client.get_accountability(election_id, ADMIN), 200)
        assert accountability["packets_mailed_count"] == 1
        assert accountability["undeliverable_packet_count"] == 1
        assert accountability["outstanding_packet_count"] == 0
        assert accountability["returned_packet_count"] == 0
        assert accountability["accountability_delta"] == 0
        assert accountability["reconciliation_status"] == "IN_BALANCE"
        assert_accountability_identity(accountability)

        assert _log_total(election_id, "PACKET_UNDELIVERABLE") == 1

        _, enrollment_meta = validate_paginated(
            api_client.list_enrollments(
                CLERK, params={"voter_id": bundle["voters"][0]["id"]}))
        assert enrollment_meta["total_count"] == 0, "no enrollment exists to suspend"

    def test_second_dispatch_of_the_same_batch_returns_batch_state_invalid(self):
        """Dispatch is declared only out of SEALED, so re-dispatching an already
        DISPATCHED batch is refused and the actual postage is never added twice: the
        batch keeps its 141-cent figure and so does the election.

        PRD: "Dispatching a batch requires it to be in `SEALED`, else `ERR_BATCH_STATE_INVALID`, and the logical clock's date must be on or before the batch's `required_send_by_date`."

        Design: Corner/state_machines/second_dispatch_of_the_same_batch_returns_batch_state_invalid
        """
        bundle = setup_mailed_packets(count=1, posture="MAILING",
                                    clock="2026-09-10T09:00:00Z")
        batch_id = bundle["batch"]["id"]
        election_id = bundle["election"]["id"]

        validate_error(api_client.dispatch_batch(batch_id, CLERK),
                       ApiErrorId.ERR_BATCH_STATE_INVALID, 409)

        batch_after = validate_success(
            api_client.get_mailing_batch(batch_id, CLERK), 200)
        assert batch_after["status"] == "DISPATCHED"
        # 28 g domestic packet on a SAME_ADDRESS request: 73 outbound plus 68 prepaid return.
        assert batch_after["actual_postage_cents"] == 141
        assert _instant(batch_after["dispatched_at"]) == _instant("2026-09-10T09:00:00Z")

        accountability = validate_success(
            api_client.get_accountability(election_id, ADMIN), 200)
        assert accountability["postage_actual_cents"] == 141
        assert accountability["packets_mailed_count"] == 1

        packet_after = validate_success(
            api_client.get_ballot_packet(bundle["packets"][0]["id"], CLERK), 200)
        assert packet_after["status"] == "MAILED"
        assert _instant(packet_after["mailed_at"]) == _instant("2026-09-10T09:00:00Z")


class TestElectionAndCureLockdownEdges:
    """The terminal posture, and adjudication attempted from the wrong notice status."""

    def test_certified_election_refuses_further_child_writes_and_further_advances(self):
        """An election with no children walks the whole posture ladder to CERTIFIED; from
        there both a new mailing batch and a repeat advance are refused, the posture stays
        CERTIFIED, and exactly four posture entries stand on the log.

        PRD: "Once the posture reaches `CERTIFIED`, no mutating child operation of that election is permitted at all."

        Design: Corner/state_machines/certified_election_refuses_further_child_writes_and_further_advances
        """
        set_clock("2026-09-10T09:00:00Z")
        election = create_election(name="Special Election 2026",
                                  postage_budget_cents=500_000)
        advance_posture_to(election["id"], "CERTIFIED")

        validate_error(
            api_client.create_mailing_batch(
                mailing_batch_payload(election["id"], batch_type="SUPPLEMENTAL",
                                     scheduled_send_date="2026-09-28"),
                CLERK),
            ApiErrorId.ERR_ELECTION_POSTURE_FORBIDS, 409)
        validate_error(
            api_client.advance_posture(election["id"], {"target_posture": "CERTIFIED"},
                                      ADMIN),
            ApiErrorId.ERR_ELECTION_POSTURE_FORBIDS, 409)

        election_after = validate_success(
            api_client.get_election(election["id"], ADMIN), 200)
        assert election_after["posture"] == "CERTIFIED"

        _, batch_meta = validate_paginated(
            api_client.list_mailing_batches(CLERK,
                                           params={"election_id": election["id"]}))
        assert batch_meta["total_count"] == 0

        # Four explicit advances happened; the two refused calls appended nothing.
        assert _log_total(election["id"], "POSTURE_CHANGED") == 4

    def test_cure_notice_adjudicate_from_issued_returns_cure_state_invalid(self):
        """Adjudication is declared only out of UNDER_EVIDENCE_REVIEW, so firing it on a
        notice still in ISSUED is refused: the notice keeps its counters and null
        resolution, the envelope stays CURE_REQUIRED and the open cure count holds at one.

        PRD: "The notice must be in `UNDER_EVIDENCE_REVIEW`, else `ERR_CURE_STATE_INVALID`"

        Design: Corner/state_machines/cure_notice_adjudicate_from_issued_returns_cure_state_invalid
        """
        bundle = setup_issued_cure_notice()
        notice = bundle["cure_notice"]
        election_id = bundle["election"]["id"]
        assert notice["status"] == "ISSUED"

        validate_error(
            api_client.adjudicate_cure_notice(notice["id"],
                                             cure_adjudication_payload("CURE"),
                                             SUPERVISOR),
            ApiErrorId.ERR_CURE_STATE_INVALID, 409)

        notice_after = validate_success(
            api_client.get_cure_notice(notice["id"], CLERK), 200)
        assert notice_after["status"] == "ISSUED"
        assert notice_after["evidence_submission_count"] == 0
        assert notice_after["deficiency_count"] == 0
        assert notice_after["resolved_at"] is None

        envelope_after = validate_success(
            api_client.get_return_envelope(bundle["envelope"]["id"], CLERK), 200)
        assert envelope_after["signature_status"] == "CURE_REQUIRED"

        election_after = validate_success(
            api_client.get_election(election_id, ADMIN), 200)
        assert election_after["open_cure_count"] == 1

        assert _log_total(election_id, "CURE_ADJUDICATED") == 0


class TestObserverSessionEdges:
    """Floor access activates only inside the booked half-open window."""

    def test_observer_check_in_before_the_window_opens_returns_window_not_active(self):
        """Check-in demands the logical clock to sit at or after window_start_at, so a
        clock two months short of the window is refused and the session stays SCHEDULED
        with no second access entry on the log.

        PRD: "the logical clock must lie inside the half-open window — at or after `window_start_at` and strictly before `window_end_at` — else `ERR_OBSERVER_WINDOW_NOT_ACTIVE`"

        Design: Corner/state_machines/observer_check_in_before_the_window_opens_returns_window_not_active
        """
        set_clock("2026-09-10T09:00:00Z")
        election = create_election()
        session = validate_success(
            api_client.create_observer_session(
                election["id"],
                observer_session_payload(
                    "obs-dem-1", observer_name="Dana Ortiz",
                    organization="County DEM Committee", party_affiliation="DEM",
                    station_area="INTAKE",
                    window_start_at="2026-11-03T14:00:00Z",
                    window_end_at="2026-11-03T16:00:00Z"),
                CLERK),
            201)
        assert session["status"] == "SCHEDULED"
        # Booking the session itself appends the only access entry that should exist.
        assert _log_total(election["id"], "OBSERVER_SESSION_OPENED") == 1

        validate_error(
            api_client.check_in_observer(session["id"],
                                        make_observer_headers("obs-dem-1")),
            ApiErrorId.ERR_OBSERVER_WINDOW_NOT_ACTIVE, 422)

        session_after = validate_success(
            api_client.get_observer_session(session["id"], ADMIN), 200)
        assert session_after["status"] == "SCHEDULED"
        assert _log_total(election["id"], "OBSERVER_SESSION_OPENED") == 1


class TestRemakeSessionEdges:
    """Completion supersedes the original and clears its pending review; a void from
    OPEN is a no-op on the ballot record."""

    def test_remake_completion_voids_the_assigned_review_and_supersedes_the_original(self):
        """Completing an OPEN remake stamps the record, mints a SEALED replacement,
        supersedes the original and voids the round-one review that was still ASSIGNED,
        releasing its reviewer's active workload without crediting a completed review.

        PRD: "Any signature review on the original envelope still in `ASSIGNED` transitions to `VOIDED`, and that reviewer's `active_review_count` decrements by one."

        Design: Corner/state_machines/remake_completion_voids_the_assigned_review_and_supersedes_the_original
        """
        bundle = _setup_open_remake_over_assigned_review()
        remake = bundle["remake"]
        original = bundle["envelope"]
        review = bundle["review"]
        reviewer = bundle["assigned_reviewer"]
        election_id = bundle["election"]["id"]

        before = validate_success(api_client.get_election(election_id, ADMIN), 200)
        assert before["attributable_ballot_count"] == 1

        record = validate_success(
            api_client.complete_remake(remake["id"], {"remade_serial": "RM-0001"},
                                      SUPERVISOR),
            200)
        assert_remake_record(record)
        assert record["status"] == "COMPLETED"
        assert record["remade_serial"] == "RM-0001"
        assert record["remade_envelope_id"] is not None
        assert _instant(record["completed_at"]) == _instant("2026-11-03T12:00:00Z")

        review_after = validate_success(
            api_client.get_signature_review(review["id"], CLERK), 200)
        assert review_after["status"] == "VOIDED"
        assert review_after["decision"] is None
        assert review_after["submitted_at"] is None

        reviewer_after = validate_success(
            api_client.get_reviewer(reviewer["id"], ADMIN), 200)
        assert reviewer_after["active_review_count"] == 0
        # A voided review is never credited as work completed.
        assert reviewer_after["completed_review_count"] == 0

        original_after = validate_success(
            api_client.get_return_envelope(original["id"], CLERK), 200)
        assert original_after["custody_status"] == "SUPERSEDED_BY_REMAKE"

        replacements, replacement_meta = validate_paginated(
            api_client.list_return_envelopes(
                CLERK, params={"remade_from_envelope_id": original["id"]}))
        assert replacement_meta["total_count"] == 1
        replacement = replacements[0]
        assert replacement["id"] == record["remade_envelope_id"]
        assert replacement["custody_status"] == "SEALED"
        assert replacement["signature_status"] == original["signature_status"]

        after = validate_success(api_client.get_election(election_id, ADMIN), 200)
        assert after["attributable_ballot_count"] == 1
        assert _log_total(election_id, "REMAKE_COMPLETED") == 1

    def test_remake_void_from_open_leaves_the_original_envelope_and_review_untouched(self):
        """Voiding straight out of OPEN never reached the compensating branch: no
        replacement was ever minted, the original keeps its SEALED custody and pending
        signature posture, and its ASSIGNED review is still live.

        PRD: "Voiding a remake is available from `OPEN` or from `COMPLETED` — those two and no others, else `ERR_REMAKE_STATE_INVALID` — records the `voided_reason_code`"

        Design: Corner/state_machines/remake_void_from_open_leaves_the_original_envelope_and_review_untouched
        """
        bundle = _setup_open_remake_over_assigned_review()
        remake = bundle["remake"]
        original = bundle["envelope"]
        review = bundle["review"]
        reviewer = bundle["assigned_reviewer"]
        election_id = bundle["election"]["id"]

        record = validate_success(
            api_client.void_remake(remake["id"], {"voided_reason_code": "TEAM_ERROR"},
                                  SUPERVISOR),
            200)
        assert_remake_record(record)
        assert record["status"] == "VOIDED"
        assert record["voided_reason_code"] == "TEAM_ERROR"
        assert record["remade_envelope_id"] is None
        assert record["completed_at"] is None

        original_after = validate_success(
            api_client.get_return_envelope(original["id"], CLERK), 200)
        assert original_after["custody_status"] == "SEALED"
        assert original_after["signature_status"] == "PENDING_REVIEW"

        review_after = validate_success(
            api_client.get_signature_review(review["id"], CLERK), 200)
        assert review_after["status"] == "ASSIGNED"
        reviewer_after = validate_success(
            api_client.get_reviewer(reviewer["id"], ADMIN), 200)
        assert reviewer_after["active_review_count"] == 1

        _, replacement_meta = validate_paginated(
            api_client.list_return_envelopes(
                CLERK, params={"remade_from_envelope_id": original["id"]}))
        assert replacement_meta["total_count"] == 0

        election_after = validate_success(
            api_client.get_election(election_id, ADMIN), 200)
        assert election_after["attributable_ballot_count"] == 1
        assert _log_total(election_id, "REMAKE_VOIDED") == 1
