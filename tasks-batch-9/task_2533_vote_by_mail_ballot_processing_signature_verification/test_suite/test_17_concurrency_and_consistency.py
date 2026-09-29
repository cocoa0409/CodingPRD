"""Optimistic concurrency on the two guarded creates, and the read-your-writes
visibility of the dispatch cascade.
"""
from datetime import datetime

from test_helpers import (
    ADMIN,
    CLERK,
    OBSERVER,
    SUPERVISOR,
    ApiErrorId,
    api_client,
    ballot_request_payload,
    create_ballot_request,
    create_trained_reviewer,
    create_voter,
    get_election,
    get_envelope,
    open_review,
    setup_election,
    setup_received_envelopes,
    setup_sealed_batch,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value):
    """Parse an emitted UTC instant so a stamp may be compared to the logical clock
    value regardless of how many fractional digits it carries."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestStaleVoterVersion:
    def test_optimistic_concurrency_stale_voter_version_blocks_a_second_request(self):
        """The first request bumps the voter, so replaying the client's original view is
        refused; re-reading the voter and retrying is accepted and supersedes the first.

        PRD: "If it does not equal that voter's current `version`, the create is rejected
        with `ERR_STALE_VOTER_VERSION` (HTTP 412)."
        Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_voter_version_blocks_a_second_request
        """
        election = setup_election(clock="2026-09-10T09:00:00Z")
        voter = create_voter()
        assert voter["version"] == 1

        first = create_ballot_request(voter, election, request_channel="ONLINE")
        assert first["status"] == "RECEIVED"

        stale_payload = ballot_request_payload(voter["id"], election["id"], 1,
                                               request_channel="PHONE")
        validate_error(api_client.create_ballot_request(stale_payload, CLERK),
                       ApiErrorId.ERR_STALE_VOTER_VERSION, 412)

        _, meta = validate_paginated(api_client.list_ballot_requests(
            CLERK, params={"voter_id": voter["id"]}))
        assert meta["total_count"] == 1, "the refused create minted no request"

        fresh = validate_success(api_client.get_voter(voter["id"], CLERK), 200)
        assert fresh["version"] == 2, "the accepted create incremented Voter.version"

        retried = validate_success(api_client.create_ballot_request(
            ballot_request_payload(voter["id"], election["id"], fresh["version"],
                                   request_channel="PHONE"), CLERK), 201)
        assert retried["status"] == "RECEIVED"
        assert retried["request_channel"] == "PHONE"

        superseded = validate_success(
            api_client.get_ballot_request(first["id"], CLERK), 200)
        assert superseded["status"] == "SUPERSEDED"

        _, after = validate_paginated(api_client.list_ballot_requests(
            CLERK, params={"voter_id": voter["id"]}))
        assert after["total_count"] == 2

        bumped = validate_success(api_client.get_voter(voter["id"], CLERK), 200)
        assert bumped["version"] == 3


class TestStaleEnvelopeVersion:
    def test_optimistic_concurrency_stale_envelope_version_blocks_a_remake(self):
        """A review round mutates the envelope, so a remake authorised against the
        pre-review view is refused until the supervisor re-reads the envelope.

        PRD: "A remake legitimately supersedes an earlier remake of the same envelope, so
        a client whose view of the envelope's signature, custody, or challenge dimension
        has been overtaken cannot authorise a new remake session."
        Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_envelope_version_blocks_a_remake
        """
        reviewer = create_trained_reviewer(full_name="Tess Ward", party_affiliation="NPP")
        member_a = create_trained_reviewer(full_name="Reid Vance",
                                           party_affiliation="REP")
        member_b = create_trained_reviewer(full_name="Dana Moss",
                                           party_affiliation="NPP")
        bundle = setup_received_envelopes(count=1)
        envelope_id = bundle["envelopes"][0]["id"]
        stale_version = bundle["envelopes"][0]["version"]
        assert stale_version == 1

        review = open_review(envelope_id)
        assert review["reviewer_id"] == reviewer["id"]

        def _payload(expected_version):
            return {
                "team_member_a_reviewer_id": member_a["id"],
                "team_member_b_reviewer_id": member_b["id"],
                "reason_code": "TORN_ENVELOPE",
                "session_start_at": "2026-11-03T13:00:00Z",
                "session_end_at": "2026-11-03T14:00:00Z",
                "expected_envelope_version": expected_version,
            }

        validate_error(api_client.create_remake(
            envelope_id, _payload(stale_version), SUPERVISOR),
            ApiErrorId.ERR_STALE_ENVELOPE_VERSION, 412)

        _, meta = validate_paginated(api_client.list_remake_records(
            SUPERVISOR, params={"original_envelope_id": envelope_id}))
        assert meta["total_count"] == 0, "the refused create opened no remake session"

        current = get_envelope(envelope_id)
        assert current["version"] == stale_version + 1, \
            "opening the review round was itself a mutation of the envelope"

        remake = validate_success(api_client.create_remake(
            envelope_id, _payload(current["version"]), SUPERVISOR), 201)
        assert remake["status"] == "OPEN"
        assert remake["original_envelope_id"] == envelope_id
        assert remake["remade_envelope_id"] is None
        assert remake["remade_serial"] is None
        assert remake["completed_at"] is None
        assert remake["voided_reason_code"] is None

        after = get_envelope(envelope_id)
        assert after["version"] == current["version"] + 1, \
            "a successful create increments ReturnEnvelope.version"
        assert after["custody_status"] == "SEALED"


class TestCascadeVisibility:
    def test_dispatch_cascade_is_visible_inside_the_same_response(self):
        """Dispatch applies all three links before it answers: the packet, its request,
        and the election's posture and counters are already settled on the next read.

        PRD: "Several operations in this domain mutate more than one record, and the
        service applies every link of the chain within the same request rather than
        deferring any of it."
        Design: Corner/consistency_model/dispatch_cascade_is_visible_inside_the_same_response
        """
        election = setup_election(clock="2026-09-10T09:00:00Z")
        bundle = setup_sealed_batch(election, weights=(28,),
                                   scheduled_send_date="2026-09-15")
        batch = bundle["batch"]
        packet_id = bundle["packets"][0]["id"]
        request_id = bundle["requests"][0]["id"]
        assert batch["status"] == "SEALED"
        assert batch["estimated_postage_cents"] == 141, "73 outbound + 68 prepaid return"
        assert get_election(election["id"])["posture"] == "PRE_MAIL"

        dispatched = validate_success(api_client.dispatch_batch(batch["id"], CLERK), 200)
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["estimated_postage_cents"] == 141
        assert dispatched["actual_postage_cents"] == 141, \
            "no packet was spoiled between seal and dispatch"
        assert _instant(dispatched["dispatched_at"]) == _instant("2026-09-10T09:00:00Z")

        packet = validate_success(api_client.get_ballot_packet(packet_id, CLERK), 200)
        assert packet["status"] == "MAILED"
        assert _instant(packet["mailed_at"]) == _instant("2026-09-10T09:00:00Z")

        request = validate_success(api_client.get_ballot_request(request_id, CLERK), 200)
        assert request["status"] == "MAILED"

        after = get_election(election["id"])
        assert after["posture"] == "MAILING", "the third link auto-advanced the posture"
        assert after["packets_mailed_count"] == 1
        assert after["outstanding_packet_count"] == 1
        assert after["postage_committed_cents"] == 141
        assert after["postage_actual_cents"] == 141

        report = validate_success(
            api_client.get_accountability(election["id"], OBSERVER), 200)
        assert report["packets_mailed_count"] == 1
        assert report["outstanding_packet_count"] == 1
        assert report["returned_packet_count"] == 0
        assert report["undeliverable_packet_count"] == 0
        assert report["accountability_delta"] == 0
        assert report["reconciliation_status"] == "IN_BALANCE"
        assert report["postage_committed_cents"] == 141
        assert report["postage_actual_cents"] == 141

        rows, meta = validate_paginated(api_client.list_transparency_log(
            ADMIN, params={"election_id": election["id"],
                           "event_type": "POSTURE_CHANGED"}))
        assert meta["total_count"] == 1
        assert rows[0]["actor_role"] == "system", \
            "an automatic advance records the system as its actor"

        _, dispatch_log = validate_paginated(api_client.list_transparency_log(
            ADMIN, params={"election_id": election["id"],
                           "event_type": "BATCH_DISPATCHED"}))
        assert dispatch_log["total_count"] == 1
