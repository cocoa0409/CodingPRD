"""Cross-entity state dependency tests: an operation on one record is gated by a
state that lives on a different record — the grandparent election's posture, and
the assigned reviewer's training validity window.

Every test builds its own world from an empty database.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_posture,
    assert_confidence_precision,
    create_reviewer,
    get_election,
    get_envelope,
    make_signature_reviewer_headers,
    open_review,
    return_envelope_payload,
    set_clock,
    setup_mailed_packets,
    setup_received_envelopes,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["elections_admin_headers"]
CLERK = TEST_USERS["elections_clerk_headers"]


def _as_instant(value: str) -> datetime:
    """Parse a service-emitted ISO 8601 UTC instant, tolerating the trailing Z
    and any number of fractional-second digits."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestEnvelopeIntakeGatedByElectionPosture:
    """Whether a return envelope may be logged at all depends on the posture of
    the election two levels above it, not on any field of the envelope or packet."""

    def test_identical_intake_is_refused_once_the_election_locks_the_canvass(self, api):
        """Intake requires the election's posture to be `MAILING` or `RECEIVING`; once the posture reaches `CANVASS_LOCKED` intake is refused with `ERR_ELECTION_POSTURE_FORBIDS`.

        Design: Difficulty/cross_entity_state_dependency/envelope_intake_gated_by_election_posture
        """
        bundle = setup_mailed_packets(count=2, posture="RECEIVING",
                                     clock="2026-09-10T00:00:00Z")
        election_id = bundle["election"]["id"]
        packet_a, packet_b = bundle["packets"][0], bundle["packets"][1]
        set_clock("2026-11-03T12:00:00Z")
        assert get_election(election_id)["posture"] == "RECEIVING"

        first = validate_success(
            api.create_return_envelope(
                return_envelope_payload(packet_a["id"], "DROPBOX"), CLERK), 201)
        assert advance_posture(election_id, "CANVASS_LOCKED")["posture"] == "CANVASS_LOCKED"
        refused = api.create_return_envelope(
            return_envelope_payload(packet_b["id"], "DROPBOX"), CLERK)

        assert first["custody_status"] == "SEALED"
        validate_error(refused, ApiErrorId.ERR_ELECTION_POSTURE_FORBIDS, 409)

    def test_refused_intake_leaves_the_packet_and_the_counters_untouched(self, api):
        """The carrying packet moves `MAILED → RETURNED`.

        Design: Difficulty/cross_entity_state_dependency/envelope_intake_gated_by_election_posture
        """
        bundle = setup_mailed_packets(count=2, posture="RECEIVING",
                                     clock="2026-09-10T00:00:00Z")
        election_id = bundle["election"]["id"]
        packet_a, packet_b = bundle["packets"][0], bundle["packets"][1]
        set_clock("2026-11-03T12:00:00Z")
        validate_success(
            api.create_return_envelope(
                return_envelope_payload(packet_a["id"], "DROPBOX"), CLERK), 201)
        advance_posture(election_id, "CANVASS_LOCKED")

        validate_error(
            api.create_return_envelope(
                return_envelope_payload(packet_b["id"], "DROPBOX"), CLERK),
            ApiErrorId.ERR_ELECTION_POSTURE_FORBIDS, 409)

        rows, meta = validate_paginated(
            api.list_return_envelopes(CLERK, params={"ballot_packet_id": packet_b["id"]}))
        assert meta["total_count"] == 0 and rows == []
        blocked_packet = validate_success(api.get_ballot_packet(packet_b["id"], CLERK), 200)
        assert blocked_packet["status"] == "MAILED"
        election = get_election(election_id)
        assert election["envelopes_received_count"] == 1
        assert election["outstanding_packet_count"] == 1

    def test_control_intake_in_receiving_judges_a_dropbox_arrival_timely(self, api):
        """For the two channels that carry no carrier postmark — `DROPBOX` and `IN_PERSON` — both judgments are identical and there is no grace at all: the verdict is `TIMELY` when `received_at` is at or before `return_deadline_at`, and `UNTIMELY` otherwise.

        Design: Difficulty/cross_entity_state_dependency/envelope_intake_gated_by_election_posture
        """
        bundle = setup_mailed_packets(count=2, posture="RECEIVING",
                                     clock="2026-09-10T00:00:00Z")
        packet_a = bundle["packets"][0]
        set_clock("2026-11-03T12:00:00Z")

        envelope = validate_success(
            api.create_return_envelope(
                return_envelope_payload(packet_a["id"], "DROPBOX"), CLERK), 201)

        assert envelope["preliminary_timeliness"] == "TIMELY"
        assert envelope["signature_status"] == "UNVERIFIED"
        assert envelope["challenge_status"] == "NONE"
        assert _as_instant(envelope["received_at"]) == _as_instant("2026-11-03T12:00:00Z")
        carrying_packet = validate_success(api.get_ballot_packet(packet_a["id"], CLERK), 200)
        assert carrying_packet["status"] == "RETURNED"


def _setup_review_assigned_to_a_reviewer_whose_training_lapses() -> dict:
    """Exactly one reviewer in the county pool, TRAINED on 2025-09-01 so the
    validity window closes at 2026-09-01, holding an open round-one review that
    was assigned on 2026-08-25 while the window was still open."""
    reviewer = create_reviewer(full_name="Xan Ruiz", party_affiliation="NPP",
                              training_status="TRAINED",
                              training_completed_at="2025-09-01T00:00:00Z",
                              curriculum_version="2025.1")
    bundle = setup_received_envelopes(
        count=1,
        intake_at="2026-08-25T00:00:00Z",
        intake_channel="IN_PERSON",
        posture="RECEIVING",
        clock="2026-08-10T00:00:00Z",
        scheduled_send_date="2026-08-12",
    )
    envelope = bundle["envelopes"][0]
    review = open_review(envelope["id"])
    assert review["reviewer_id"] == reviewer["id"], \
        "the only candidate in the pool must take round one"
    return {"reviewer": reviewer, "envelope_id": envelope["id"], "review": review}


class TestSignatureDecisionGatedByReviewerTrainingValidity:
    """A review row that was legally assigned becomes unsubmittable once the
    logical clock passes the reviewer's training expiry, and a training
    completion recorded on the Reviewer unblocks the very same review row."""

    def test_training_expiry_is_derived_as_365_days_after_completion(self, api):
        """When `training_completed_at` — the instant the reviewer completed the signature-comparison curriculum — is supplied, the reviewer's `training_expires_at` is derived as that instant advanced by 365 whole days

        Design: Difficulty/cross_entity_state_dependency/signature_decision_gated_by_reviewer_training_validity
        """
        context = _setup_review_assigned_to_a_reviewer_whose_training_lapses()

        reviewer = validate_success(api.get_reviewer(context["reviewer"]["id"], ADMIN), 200)

        assert _as_instant(reviewer["training_expires_at"]) == \
            _as_instant("2026-09-01T00:00:00Z")
        assert reviewer["training_status"] == "TRAINED"
        assert reviewer["active_review_count"] == 1
        assert reviewer["completed_review_count"] == 0
        assert context["review"]["status"] == "ASSIGNED"

    def test_lapsed_training_blocks_the_decision_and_leaves_the_review_assigned(self, api):
        """The reviewer's `training_status` must be `TRAINED` or `CERTIFIED_LEAD` and their `training_expires_at` must be strictly later than the logical clock's current value — a null or already-passed expiry is rejected with `ERR_REVIEWER_TRAINING_INVALID`.

        Design: Difficulty/cross_entity_state_dependency/signature_decision_gated_by_reviewer_training_validity
        """
        context = _setup_review_assigned_to_a_reviewer_whose_training_lapses()
        reviewer_id = context["reviewer"]["id"]
        set_clock("2026-09-02T00:00:00Z")

        response = api.submit_signature_decision(
            context["review"]["id"], {"decision": "MATCH", "similarity_score": 80},
            make_signature_reviewer_headers(reviewer_id))

        validate_error(response, ApiErrorId.ERR_REVIEWER_TRAINING_INVALID, 422)
        review = validate_success(
            api.get_signature_review(context["review"]["id"], ADMIN), 200)
        assert review["status"] == "ASSIGNED"
        assert review["decision"] is None
        assert review["confidence_score"] is None
        reviewer = validate_success(api.get_reviewer(reviewer_id, ADMIN), 200)
        assert reviewer["active_review_count"] == 1
        assert reviewer["completed_review_count"] == 0
        assert get_envelope(context["envelope_id"])["signature_status"] == "PENDING_REVIEW"

    def test_recertifying_the_reviewer_unblocks_the_identical_decision(self, api):
        """recording it sets `training_completed_at` from `completed_at` and refreshes `training_expires_at` to that instant advanced by 365 days.

        Design: Difficulty/cross_entity_state_dependency/signature_decision_gated_by_reviewer_training_validity
        """
        context = _setup_review_assigned_to_a_reviewer_whose_training_lapses()
        reviewer_id = context["reviewer"]["id"]
        headers = make_signature_reviewer_headers(reviewer_id)
        decision_payload = {"decision": "MATCH", "similarity_score": 80}
        set_clock("2026-09-02T00:00:00Z")
        validate_error(
            api.submit_signature_decision(context["review"]["id"], decision_payload, headers),
            ApiErrorId.ERR_REVIEWER_TRAINING_INVALID, 422)

        recertified = validate_success(
            api.create_training_completion(
                reviewer_id,
                {"completed_at": "2026-09-02T00:00:00Z", "curriculum_version": "2026.2",
                 "training_status": "TRAINED"},
                ADMIN), 200)
        accepted = api.submit_signature_decision(
            context["review"]["id"], decision_payload, headers)

        assert _as_instant(recertified["training_expires_at"]) == \
            _as_instant("2027-09-02T00:00:00Z")
        review = validate_success(accepted, 200)
        assert review["status"] == "SUBMITTED"
        assert review["confidence_score"] == 0.8000
        assert_confidence_precision(review["confidence_score"])
        assert get_envelope(context["envelope_id"])["signature_status"] == "ACCEPTED"

    def test_successful_submission_moves_the_reviewer_workload_counters(self, api):
        """Submission stamps `submitted_at` from the logical clock, moves the review `ASSIGNED → SUBMITTED`, decrements the reviewer's `active_review_count` by one, increments their `completed_review_count` by one

        Design: Difficulty/cross_entity_state_dependency/signature_decision_gated_by_reviewer_training_validity
        """
        context = _setup_review_assigned_to_a_reviewer_whose_training_lapses()
        reviewer_id = context["reviewer"]["id"]
        headers = make_signature_reviewer_headers(reviewer_id)
        set_clock("2026-09-02T00:00:00Z")
        validate_error(
            api.submit_signature_decision(
                context["review"]["id"], {"decision": "MATCH", "similarity_score": 80},
                headers),
            ApiErrorId.ERR_REVIEWER_TRAINING_INVALID, 422)
        validate_success(
            api.create_training_completion(
                reviewer_id,
                {"completed_at": "2026-09-02T00:00:00Z", "curriculum_version": "2026.2",
                 "training_status": "TRAINED"},
                ADMIN), 200)

        validate_success(
            api.submit_signature_decision(
                context["review"]["id"], {"decision": "MATCH", "similarity_score": 80},
                headers), 200)

        reviewer = validate_success(api.get_reviewer(reviewer_id, ADMIN), 200)
        assert reviewer["active_review_count"] == 0
        assert reviewer["completed_review_count"] == 1
        envelope = get_envelope(context["envelope_id"])
        assert envelope["review_round_count"] == 1
        assert envelope["resolved_signature_confidence"] == 0.8000
