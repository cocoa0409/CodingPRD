"""Derived-value edges of the Vote-By-Mail Processing API.

Every test builds its own world from an empty database and reads only values the
PRD derives uniquely: the postage tier schedule, the postmark grace window, the
round-two escalation resolution, the countable/attributable membership rules, and
the reviewer selector policy.
"""
from datetime import datetime

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_ballot_packet,
    assert_cure_notice,
    assert_return_envelope,
    assert_reviewer,
    assert_whole_cents,
    create_batch,
    create_trained_reviewer,
    create_voter,
    get_accountability,
    get_election,
    get_envelope,
    intake_envelope,
    issue_cure_notice,
    open_review,
    packet_payload,
    return_envelope_payload,
    separation_run_payload,
    set_clock,
    setup_accepted_envelope_pool,
    setup_approved_request,
    setup_election,
    setup_envelope_with_open_review,
    setup_mailed_packets,
    setup_received_envelopes,
    setup_sealed_batch,
    submit_decision,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["elections_admin_headers"]
CLERK = TEST_USERS["elections_clerk_headers"]
SUPERVISOR = TEST_USERS["canvass_supervisor_headers"]

CLOCK_SEP10 = "2026-09-10T09:00:00Z"
CLOCK_NOV3 = "2026-11-03T12:00:00Z"


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


class TestPostageTierBoundaries:
    """The outbound charge at each declared weight edge and the batch total built
    from the already-rounded per-packet figures."""

    @pytest.mark.parametrize("packet_weight_grams,expected_cents", [
        (28, 141),
        (57, 197),
        (85, 253),
        (86, 309),
    ])
    def test_packet_postage_at_each_tier_boundary(self, packet_weight_grams,
                                                  expected_cents):
        """A domestic SAME_ADDRESS packet pays only the outbound charge plus the flat
        prepaid return postage, so the three tier edges and the first overweight step
        land on 141, 197, 253 and 309 cents.

        a packet weighing at most 28 grams costs 73 cents; a heavier packet weighing at most 57 grams costs 129 cents; a heavier packet weighing at most 85 grams costs 185 cents; and a packet over 85 grams costs 185 cents plus 56 cents for each additional 28-gram step needed to cover the excess

        Design: Corner/calculations/postage_tier_boundaries_at_28_57_85_and_86_grams
        """
        election = setup_election(posture="PRE_MAIL", clock=CLOCK_SEP10)
        voter = create_voter(full_name="Vera Ames",
                             residence_address="11 Ash St, Springfield")
        approved = setup_approved_request(election, voter, "MATCH_SAME")
        assert approved["request"]["forwarding_class"] == "SAME_ADDRESS"
        batch = create_batch(election, batch_type="DOMESTIC_INITIAL",
                             scheduled_send_date="2026-09-25")

        response = api_client.add_packet(
            batch["id"],
            packet_payload(approved["request"]["id"], packet_weight_grams),
            CLERK)

        packet = validate_success(response, 201)
        assert_ballot_packet(packet)
        assert packet["packet_weight_grams"] == packet_weight_grams
        assert packet["packet_postage_cents"] == expected_cents
        assert_whole_cents(packet["packet_postage_cents"])
        assert packet["status"] == "QUEUED"

    def test_sealed_batch_total_is_the_sum_of_the_four_packet_figures(self):
        """Four packets at 28 g, 57 g, 85 g and 86 g freeze an estimate of 900 cents,
        which is committed against the election's postage authority while the actual
        figure stays at zero until dispatch.

        a batch total is the sum of already-rounded per-packet figures

        Design: Corner/calculations/postage_tier_boundaries_at_28_57_85_and_86_grams
        """
        election = setup_election(posture="PRE_MAIL", clock=CLOCK_SEP10)

        bundle = setup_sealed_batch(election, weights=(28, 57, 85, 86))

        assert [packet["packet_postage_cents"] for packet in bundle["packets"]] == \
            [141, 197, 253, 309]
        batch = bundle["batch"]
        assert batch["status"] == "SEALED"
        assert batch["packet_count"] == 4
        assert batch["estimated_postage_cents"] == 900
        assert_whole_cents(batch["estimated_postage_cents"])
        after = get_election(election["id"])
        assert after["postage_committed_cents"] == 900
        assert after["postage_actual_cents"] == 0


class TestUspsGraceWindowBoundaries:
    """The postmark grace window is closed at both ends: arrival exactly at the
    return deadline is timely and arrival exactly at the grace limit is still inside
    the window, while one second later is not."""

    @pytest.mark.parametrize("received_at,postmark_date,expected_preliminary", [
        ("2026-11-03T20:00:00Z", "2026-11-01", "TIMELY"),
        ("2026-11-10T20:00:00Z", "2026-11-02", "PROVISIONAL_TIMELY_POSTMARK"),
        ("2026-11-10T20:00:01Z", "2026-11-03", "UNTIMELY"),
    ])
    def test_preliminary_verdict_at_the_two_boundaries_and_one_second_past(
            self, received_at, postmark_date, expected_preliminary):
        """With a return deadline of 2026-11-03T20:00:00Z and seven grace days the
        grace limit is 2026-11-10T20:00:00Z, so a USPS envelope logged at the deadline
        is TIMELY, one logged at the grace limit is PROVISIONAL_TIMELY_POSTMARK, and
        one logged a second later is UNTIMELY.

        Otherwise, if `received_at` is strictly after the grace limit, the verdict is `UNTIMELY` in both variants; arrival exactly at the grace limit is still inside the window.

        Design: Corner/calculations/usps_grace_window_boundaries_at_deadline_and_at_grace_limit
        """
        bundle = setup_mailed_packets(count=1, posture="MAILING", clock=CLOCK_SEP10)
        election = bundle["election"]
        assert election["postmark_grace_days"] == 7
        assert _instant(election["return_deadline_at"]) == _instant("2026-11-03T20:00:00Z")
        set_clock(received_at)

        response = api_client.create_return_envelope(
            return_envelope_payload(bundle["packets"][0]["id"], "USPS",
                                    postmark_date=postmark_date,
                                    postmark_legible=True),
            CLERK)

        envelope = validate_success(response, 201)
        assert_return_envelope(envelope)
        assert _instant(envelope["received_at"]) == _instant(received_at)
        assert envelope["preliminary_timeliness"] == expected_preliminary
        assert envelope["final_timeliness"] is None

    def test_canvass_sweep_writes_the_final_variant_and_sequesters_only_the_late_one(self):
        """One sweep over the same three envelopes writes TIMELY, TIMELY_BY_POSTMARK and
        UNTIMELY, and only the envelope past the grace limit leaves the sealed pool.

        every envelope whose freshly written `final_timeliness` is `UNTIMELY` moves its custody dimension `SEALED → SEQUESTERED`

        Design: Corner/calculations/usps_grace_window_boundaries_at_deadline_and_at_grace_limit
        """
        bundle = setup_mailed_packets(count=3, posture="MAILING", clock=CLOCK_SEP10)
        election_id = bundle["election"]["id"]
        arrivals = [
            ("2026-11-03T20:00:00Z", "2026-11-01"),
            ("2026-11-10T20:00:00Z", "2026-11-02"),
            ("2026-11-10T20:00:01Z", "2026-11-03"),
        ]
        envelopes = []
        for packet, (received_at, postmark_date) in zip(bundle["packets"], arrivals):
            set_clock(received_at)
            envelopes.append(intake_envelope(packet["id"], "USPS",
                                             postmark_date=postmark_date,
                                             postmark_legible=True))
        assert [envelope["preliminary_timeliness"] for envelope in envelopes] == \
            ["TIMELY", "PROVISIONAL_TIMELY_POSTMARK", "UNTIMELY"]

        response = api_client.run_canvass_sweep(election_id, {}, ADMIN)

        sweep = validate_success(response, 200)
        assert sweep["canvass_sweep_index"] == 1
        assert sweep["expired_cure_count"] == 0
        assert sweep["finalized_envelope_count"] == 3
        assert sweep["sequestered_envelope_count"] == 1
        finalized = [get_envelope(envelope["id"]) for envelope in envelopes]
        assert [envelope["final_timeliness"] for envelope in finalized] == \
            ["TIMELY", "TIMELY_BY_POSTMARK", "UNTIMELY"]
        assert [envelope["custody_status"] for envelope in finalized] == \
            ["SEALED", "SEALED", "SEQUESTERED"]


class TestTwoNoMatchRoundsResolveToCureRequired:
    """Round one escalates on a NO_MATCH regardless of confidence; round two with a
    second NO_MATCH is dispositive and names the mismatch reason."""

    def test_round_one_escalates_and_round_two_resolves_to_cure_required(self):
        """A round-one NO_MATCH at similarity 60 scores 0.6000 and escalates; a second
        reviewer's round-two NO_MATCH at similarity 58 scores 0.5800, drives the envelope
        to CURE_REQUIRED with that confidence resolved, and the notice issued afterwards
        carries SIGNATURE_MISMATCH.

        Two `NO_MATCH` decisions produce a cure requirement with a reason of `SIGNATURE_MISMATCH`.

        Design: Corner/calculations/two_no_match_rounds_resolve_to_cure_required_with_mismatch_reason
        """
        first = create_trained_reviewer(full_name="Rosa Vidal", party_affiliation="DEM",
                                        training_completed_at="2026-06-01T00:00:00Z")
        second = create_trained_reviewer(full_name="Bo Reyes", party_affiliation="REP",
                                         training_completed_at="2026-06-02T00:00:00Z")
        bundle = setup_envelope_with_open_review(reviewers=[first, second],
                                                 clock=CLOCK_SEP10,
                                                 intake_at=CLOCK_NOV3)
        envelope_id = bundle["envelope"]["id"]
        assert bundle["review"]["reviewer_id"] == first["id"]

        round_one = submit_decision(bundle["review"], "NO_MATCH", 60,
                                    notes="slant and letter forms differ")

        assert round_one["status"] == "SUBMITTED"
        assert round_one["confidence_score"] == pytest.approx(0.6, abs=1e-9)
        escalated = get_envelope(envelope_id)
        assert escalated["signature_status"] == "ESCALATED"
        assert escalated["review_round_count"] == 1

        round_two_open = open_review(envelope_id)
        assert round_two_open["reviewer_id"] == second["id"]
        assert round_two_open["review_round"] == 2
        round_two = submit_decision(round_two_open, "NO_MATCH", 58,
                                    notes="second reader agrees")

        assert round_two["confidence_score"] == pytest.approx(0.58, abs=1e-9)
        resolved = get_envelope(envelope_id)
        assert resolved["signature_status"] == "CURE_REQUIRED"
        assert resolved["review_round_count"] == 2
        assert resolved["resolved_signature_confidence"] == pytest.approx(0.58, abs=1e-9)

        notice = issue_cure_notice(envelope_id)
        assert_cure_notice(notice)
        assert notice["reason_code"] == "SIGNATURE_MISMATCH"
        assert notice["status"] == "ISSUED"
        assert _log_count(bundle["election"]["id"], "SIGNATURE_ESCALATION") == 1


class TestCountableAndAttributableMembership:
    """The two ballot populations differ on the custody dimension: countability starts
    at separation, attributability starts at the sealed envelope."""

    def test_countable_starts_at_separation_while_attributable_spans_sealed_too(self):
        """Three accepted envelopes contribute 0 to countable_envelope_count while sealed,
        3 once separated and still 3 after one is counted, while attributable_ballot_count
        is 3 at every step.

        `countable_envelope_count` is the number of the election's return envelopes whose `signature_status` is `ACCEPTED`, whose `custody_status` is either `SEPARATED` or `COUNTED`, and whose `challenge_status` is anything other than `SUSTAINED`.

        Design: Corner/calculations/countable_and_attributable_sets_include_only_accepted_and_separated_envelopes
        """
        reviewer = create_trained_reviewer(full_name="Rosa Vidal",
                                          party_affiliation="DEM",
                                          training_completed_at="2026-06-01T00:00:00Z")
        bundle = setup_accepted_envelope_pool(count=3, similarity_score=80,
                                              reviewers=[reviewer],
                                              weights=(28, 57, 85),
                                              clock=CLOCK_SEP10,
                                              intake_at=CLOCK_NOV3)
        election_id = bundle["election"]["id"]
        envelope_ids = [envelope["id"] for envelope in bundle["envelopes"]]
        assert all(envelope["signature_status"] == "ACCEPTED"
                   for envelope in bundle["envelopes"])
        assert all(envelope["custody_status"] == "SEALED"
                   for envelope in bundle["envelopes"])

        before = get_accountability(election_id, SUPERVISOR)
        assert before["countable_envelope_count"] == 0
        assert before["attributable_ballot_count"] == 3

        response = api_client.create_separation_run(
            election_id, separation_run_payload(envelope_ids), SUPERVISOR)

        run = validate_success(response, 200)
        assert run["run_sequence"] == 1
        assert run["separated_count"] == 3
        assert run["secrecy_pool_size"] == 3
        assert run["countable_envelope_count"] == 3
        assert run["attributable_ballot_count"] == 3
        separated = [get_envelope(envelope_id) for envelope_id in envelope_ids]
        assert all(envelope["custody_status"] == "SEPARATED" for envelope in separated)
        assert all(envelope["separation_run_sequence"] == 1 for envelope in separated)

        validate_success(api_client.run_canvass_sweep(election_id, {}, ADMIN), 200)
        counted = validate_success(
            api_client.count_envelope(envelope_ids[0], SUPERVISOR, {}), 200)

        assert counted["custody_status"] == "COUNTED"
        final = get_accountability(election_id, SUPERVISOR)
        assert final["countable_envelope_count"] == 3
        assert final["attributable_ballot_count"] == 3
        assert final["envelopes_received_count"] == 3
        assert final["returned_packet_count"] == 3
        assert final["outstanding_packet_count"] == 0
        assert final["packets_mailed_count"] == 3
        assert final["accountability_delta"] == 0
        assert final["reconciliation_status"] == "IN_BALANCE"
        assert final["postage_committed_cents"] == 591
        assert final["postage_actual_cents"] == 591


class TestReviewerSelectorPolicy:
    """Who the server picks: the untrained and the lapsed reviewer are filtered out of
    the candidate set entirely, and the survivors are ordered by open workload."""

    def test_three_openings_alternate_by_open_load_and_never_reach_the_ineligible_two(self):
        """Rosa (trained, created first), Bo (trained), Uma (untrained) and Eli (training
        lapsed on 2026-01-01) sit in one pool; three round-one openings go to Rosa, Bo and
        Rosa again, leaving Uma and Eli with no reviews at all.

        Candidates are ranked by `active_review_count` ascending, then by `completed_review_count` ascending, then by `created_at` ascending as the deterministic final tie-break

        Design: Corner/calculations/reviewer_selection_filters_untrained_and_expired_then_ranks_by_open_load
        """
        set_clock("2026-08-01T01:00:00Z")
        rosa = create_trained_reviewer(full_name="Rosa Vidal", party_affiliation="DEM",
                                       training_completed_at="2026-06-01T00:00:00Z")
        set_clock("2026-08-01T02:00:00Z")
        bo = create_trained_reviewer(full_name="Bo Reyes", party_affiliation="REP",
                                     training_completed_at="2026-06-02T00:00:00Z")
        assert _instant(rosa["created_at"]) < _instant(bo["created_at"])
        uma = validate_success(api_client.create_reviewer(
            {"full_name": "Uma Novak", "party_affiliation": "NPP"}, ADMIN), 201)
        assert_reviewer(uma)
        assert uma["training_status"] == "UNTRAINED"
        assert uma["training_expires_at"] is None
        eli = create_trained_reviewer(full_name="Eli Prado", party_affiliation="REP",
                                      training_completed_at="2025-01-01T00:00:00Z",
                                      curriculum_version="SV-2025.1")
        assert _instant(eli["training_expires_at"]) == _instant("2026-01-01T00:00:00Z")
        bundle = setup_received_envelopes(count=3, weights=(28, 57, 85),
                                          clock=CLOCK_SEP10, intake_at=CLOCK_NOV3)
        envelope_ids = [envelope["id"] for envelope in bundle["envelopes"]]

        assignments = [open_review(envelope_id) for envelope_id in envelope_ids]

        assert [review["reviewer_id"] for review in assignments] == \
            [rosa["id"], bo["id"], rosa["id"]]
        assert all(review["review_round"] == 1 for review in assignments)
        assert all(review["status"] == "ASSIGNED" for review in assignments)
        rosa_after = validate_success(api_client.get_reviewer(rosa["id"], CLERK), 200)
        bo_after = validate_success(api_client.get_reviewer(bo["id"], CLERK), 200)
        assert rosa_after["active_review_count"] == 2
        assert rosa_after["completed_review_count"] == 0
        assert bo_after["active_review_count"] == 1
        assert bo_after["completed_review_count"] == 0
        for ineligible in (uma, eli):
            assert _total_count(api_client.list_signature_reviews(
                CLERK, params={"reviewer_id": ineligible["id"]})) == 0
            still_idle = validate_success(
                api_client.get_reviewer(ineligible["id"], CLERK), 200)
            assert still_idle["active_review_count"] == 0
