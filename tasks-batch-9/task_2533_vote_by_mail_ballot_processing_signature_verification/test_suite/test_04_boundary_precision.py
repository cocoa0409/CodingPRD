"""Boundary-precision tests: the four-decimal confidence score against the
auto-accept threshold, and the distinct-envelope cardinality of a separation run.

Every test builds its own world from an empty database.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_confidence_precision,
    create_trained_reviewer,
    get_election,
    get_envelope,
    list_transparency_log,
    make_signature_reviewer_headers,
    open_review,
    separation_run_payload,
    setup_accepted_envelope_pool,
    setup_received_envelopes,
    validate_error,
    validate_paginated,
    validate_success,
)

SUPERVISOR = TEST_USERS["canvass_supervisor_headers"]
CLERK = TEST_USERS["elections_clerk_headers"]

# The whole world these tests share: an election whose return deadline is
# 2026-11-03T20:00:00Z, intake at 2026-11-03T12:00:00Z through a DROPBOX, and a
# voter whose newest exemplar was captured on 2026-01-05 (302 days of signature
# age, far short of the 1460-day staleness trigger).
INTAKE_AT = "2026-11-03T12:00:00Z"
SETUP_CLOCK = "2026-09-10T00:00:00Z"
LAST_SIGNATURE_UPDATE_AT = "2026-01-05T00:00:00Z"


def _setup_envelope_awaiting_round_one(signature_on_file_count: int = 1) -> dict:
    """One election in RECEIVING holding exactly one TRAINED reviewer, one
    DROPBOX envelope for a voter with `signature_on_file_count` exemplars on
    file, and an open round-one review assigned to that single reviewer."""
    create_trained_reviewer()
    bundle = setup_received_envelopes(
        count=1,
        intake_at=INTAKE_AT,
        intake_channel="DROPBOX",
        posture="RECEIVING",
        clock=SETUP_CLOCK,
        voter_overrides={
            "signature_on_file_count": signature_on_file_count,
            "last_signature_update_at": LAST_SIGNATURE_UPDATE_AT,
        },
    )
    envelope = bundle["envelopes"][0]
    return {
        "election_id": bundle["election"]["id"],
        "envelope_id": envelope["id"],
        "review": open_review(envelope["id"]),
    }


def _submit_match(api, review: dict, similarity_score: int):
    """Submit a MATCH decision as the reviewer the round was assigned to."""
    return api.submit_signature_decision(
        review["id"],
        {"decision": "MATCH", "similarity_score": similarity_score},
        make_signature_reviewer_headers(review["reviewer_id"]),
    )


class TestConfidenceScoreThresholdEdges:
    """The auto-accept comparison is inclusive at 0.72, the on-file reward is
    clamped at 0.10, and the fourth decimal is produced by round-half-up."""

    @pytest.mark.parametrize(
        "similarity_score,signature_on_file_count,expected_confidence,expected_signature_status",
        [
            pytest.param(72, 1, 0.7200, "ACCEPTED", id="exactly-at-0.72-accepts"),
            pytest.param(71, 1, 0.7100, "ESCALATED", id="one-step-below-escalates"),
            pytest.param(65, 6, 0.7150, "ESCALATED", id="on-file-reward-clamped-at-0.10"),
            pytest.param(63, 4, 0.6773, "ESCALATED", id="fifth-decimal-5-rounds-half-up"),
        ],
    )
    def test_confidence_score_edges_drive_the_round_one_outcome(
        self, api, similarity_score, signature_on_file_count,
        expected_confidence, expected_signature_status,
    ):
        """A `MATCH` whose `confidence_score` is at or above 0.72 accepts the signature.

        Design: Difficulty/boundary_precision_check/confidence_score_auto_accept_threshold_cap_and_rounding_edges
        """
        context = _setup_envelope_awaiting_round_one(signature_on_file_count)

        response = _submit_match(api, context["review"], similarity_score)

        review = validate_success(response, 200)
        assert review["status"] == "SUBMITTED"
        assert review["confidence_score"] == expected_confidence, (
            f"similarity {similarity_score} with {signature_on_file_count} exemplars "
            f"on file must score {expected_confidence}, got {review['confidence_score']}"
        )
        assert_confidence_precision(review["confidence_score"])

        envelope = get_envelope(context["envelope_id"])
        assert envelope["signature_status"] == expected_signature_status
        assert envelope["review_round_count"] == 1

    def test_score_exactly_at_the_threshold_is_carried_onto_the_envelope(self, api):
        """An acceptance moves the envelope `PENDING_REVIEW → ACCEPTED` and sets `resolved_signature_confidence` to the submitted review's `confidence_score`.

        Design: Difficulty/boundary_precision_check/confidence_score_auto_accept_threshold_cap_and_rounding_edges
        """
        context = _setup_envelope_awaiting_round_one(signature_on_file_count=1)

        review = validate_success(_submit_match(api, context["review"], 72), 200)

        assert review["confidence_score"] == 0.7200
        envelope = get_envelope(context["envelope_id"])
        assert envelope["signature_status"] == "ACCEPTED"
        assert envelope["resolved_signature_confidence"] == 0.7200
        assert_confidence_precision(envelope["resolved_signature_confidence"])

    def test_on_file_reward_cap_keeps_a_six_exemplar_voter_below_the_threshold(self, api):
        """it is 0.025 for each exemplar beyond the first — that is, 0.025 multiplied by the voter's `signature_on_file_count` less one — capped at 0.10, so the reward stops growing once five exemplars are on file.

        Design: Difficulty/boundary_precision_check/confidence_score_auto_accept_threshold_cap_and_rounding_edges
        """
        context = _setup_envelope_awaiting_round_one(signature_on_file_count=6)

        review = validate_success(_submit_match(api, context["review"], 65), 200)

        # Six exemplars would earn 0.125 uncapped, which would score 0.7313 and
        # wrongly auto-accept; the cap holds the reward at 0.10 and 0.7150.
        assert review["confidence_score"] == 0.7150
        assert get_envelope(context["envelope_id"])["signature_status"] == "ESCALATED"

    def test_below_threshold_score_escalates_and_rejects_nothing(self, api):
        """A `MATCH` whose `confidence_score` is at or above 0.55 but strictly below 0.72 escalates.

        Design: Difficulty/boundary_precision_check/confidence_score_auto_accept_threshold_cap_and_rounding_edges
        """
        context = _setup_envelope_awaiting_round_one(signature_on_file_count=1)

        review = validate_success(_submit_match(api, context["review"], 71), 200)

        assert review["confidence_score"] == 0.7100
        envelope = get_envelope(context["envelope_id"])
        assert envelope["signature_status"] == "ESCALATED"
        election = get_election(context["election_id"])
        assert election["countable_envelope_count"] == 0
        assert election["rejected_envelope_count"] == 0


def _setup_three_accepted_envelopes() -> dict:
    """Three DROPBOX envelopes, each carried to ACCEPTED by one round-one MATCH
    at similarity 80, so each is signature ACCEPTED, custody SEALED, challenge NONE."""
    return setup_accepted_envelope_pool(
        count=3,
        similarity_score=80,
        intake_at=INTAKE_AT,
        intake_channel="DROPBOX",
        posture="RECEIVING",
        clock=SETUP_CLOCK,
    )


class TestSeparationRunSecrecyPoolCardinality:
    """The metric guarding a separation run is the count of DISTINCT envelope
    identifiers submitted, not the length of the submitted array."""

    @pytest.mark.parametrize(
        "pool_shape,expected_error,expected_status",
        [
            pytest.param("empty", ApiErrorId.ERR_SEPARATION_SET_EMPTY, 400,
                         id="cardinality-0-has-its-own-error"),
            pytest.param("two-distinct", ApiErrorId.ERR_BALLOT_SECRECY_POOL_TOO_SMALL, 422,
                         id="cardinality-2-is-one-below-the-minimum"),
            pytest.param("three-entries-two-distinct",
                         ApiErrorId.ERR_BALLOT_SECRECY_POOL_TOO_SMALL, 422,
                         id="array-of-three-holding-only-two-distinct-ids"),
        ],
    )
    def test_undersized_secrecy_pools_are_refused(
        self, api, pool_shape, expected_error, expected_status,
    ):
        """A non-empty run containing fewer than 3 distinct envelopes is rejected with `ERR_BALLOT_SECRECY_POOL_TOO_SMALL`, because a pool that small would let a separated ballot be re-associated with its voter.

        Design: Difficulty/boundary_precision_check/separation_run_secrecy_pool_cardinality_edges
        """
        bundle = _setup_three_accepted_envelopes()
        election_id = bundle["election"]["id"]
        ids = [envelope["id"] for envelope in bundle["envelopes"]]
        pools = {
            "empty": [],
            "two-distinct": [ids[0], ids[1]],
            "three-entries-two-distinct": [ids[0], ids[1], ids[1]],
        }

        response = api.create_separation_run(
            election_id, separation_run_payload(pools[pool_shape]), SUPERVISOR)

        validate_error(response, expected_error, expected_status)
        election = get_election(election_id)
        assert election["separation_run_sequence"] == 0
        assert election["countable_envelope_count"] == 0

    def test_run_of_exactly_three_distinct_envelopes_is_accepted(self, api):
        """An accepted run increments the election's `separation_run_sequence` by one and stamps that new value onto the `separation_run_sequence` field of every envelope in the run, so each ballot carries the identity of the batch it was anonymised in.

        Design: Difficulty/boundary_precision_check/separation_run_secrecy_pool_cardinality_edges
        """
        bundle = _setup_three_accepted_envelopes()
        election_id = bundle["election"]["id"]
        ids = [envelope["id"] for envelope in bundle["envelopes"]]

        response = api.create_separation_run(
            election_id, separation_run_payload(ids), SUPERVISOR)

        run = validate_success(response, 200)
        assert run["election_id"] == election_id
        assert run["run_sequence"] == 1
        assert run["separated_count"] == 3
        assert run["secrecy_pool_size"] == 3
        assert run["countable_envelope_count"] == 3

        separated, meta = validate_paginated(
            api.list_return_envelopes(CLERK, params={"custody_status": "SEPARATED"}))
        assert meta["total_count"] == 3
        assert len(separated) == 3
        for envelope in separated:
            assert envelope["custody_status"] == "SEPARATED"
            assert envelope["separation_run_sequence"] == 1

        assert get_election(election_id)["separation_run_sequence"] == 1

    def test_only_the_accepted_run_appends_a_transparency_entry(self, api):
        """Exactly one `SEPARATION_RUN` entry is appended for the whole run, with the election as its subject and `ballot_content_disclosed` false.

        Design: Difficulty/boundary_precision_check/separation_run_secrecy_pool_cardinality_edges
        """
        bundle = _setup_three_accepted_envelopes()
        election_id = bundle["election"]["id"]
        ids = [envelope["id"] for envelope in bundle["envelopes"]]

        validate_error(
            api.create_separation_run(election_id, separation_run_payload([]), SUPERVISOR),
            ApiErrorId.ERR_SEPARATION_SET_EMPTY, 400)
        validate_error(
            api.create_separation_run(election_id,
                                      separation_run_payload([ids[0], ids[1]]), SUPERVISOR),
            ApiErrorId.ERR_BALLOT_SECRECY_POOL_TOO_SMALL, 422)
        validate_error(
            api.create_separation_run(election_id,
                                      separation_run_payload([ids[0], ids[1], ids[1]]),
                                      SUPERVISOR),
            ApiErrorId.ERR_BALLOT_SECRECY_POOL_TOO_SMALL, 422)
        run = validate_success(
            api.create_separation_run(election_id, separation_run_payload(ids), SUPERVISOR),
            200)

        assert run["run_sequence"] == 1, "the three refused calls never advanced the counter"
        entries = list_transparency_log(election_id, event_type="SEPARATION_RUN")
        assert len(entries) == 1
        assert entries[0]["ballot_content_disclosed"] is False
        assert entries[0]["subject_entity"] == "Election"
