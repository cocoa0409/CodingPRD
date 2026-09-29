"""Conservation across compensating actions.

Two quantities must come back to their exact prior value after a forward
action is undone: the election's `attributable_ballot_count` across a remake
completion followed by a void, and the election's `postage_committed_cents`
across a batch seal followed by a cancellation. Both are checked against the
value observed immediately before the forward action, never against a figure
recomputed over the surviving rows.
"""
from datetime import datetime

from test_helpers import (
    TEST_USERS,
    add_packet,
    assert_accountability_identity,
    cancel_batch,
    complete_remake,
    create_ballot_request,
    create_batch,
    create_trained_reviewer,
    create_voter,
    get_accountability,
    get_election,
    get_envelope,
    open_remake,
    open_review,
    seal_batch,
    setup_approved_request,
    setup_election,
    setup_received_envelopes,
    submit_decision,
    validate_paginated,
    validate_success,
    void_remake,
)

ADMIN = TEST_USERS["elections_admin_headers"]
CLERK = TEST_USERS["elections_clerk_headers"]
SUPERVISOR = TEST_USERS["canvass_supervisor_headers"]

INTAKE_AT = "2026-11-03T12:00:00Z"
SETUP_CLOCK = "2026-09-10T00:00:00Z"
SESSION_START_AT = "2026-11-05T13:00:00Z"
SESSION_END_AT = "2026-11-05T14:00:00Z"

# One 28 g domestic packet to an unchanged address: 73 cents outbound plus the
# 68-cent prepaid return, with no forwarding endorsement.
DOMESTIC_PACKET_CENTS = 141


def _as_instant(value: str) -> datetime:
    """Parse an emitted UTC instant so the comparison ignores fractional-digit width."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _setup_open_remake_on_an_accepted_envelope() -> dict:
    """An election in RECEIVING holding two custody-SEALED envelopes — one
    ACCEPTED at round one, one still UNVERIFIED — and an OPEN remake on the
    accepted one worked by a bipartisan pair that never touched its review.

    The three reviewers are registered before any review is opened so the
    round-one assignment lands on the first of them, leaving the other two free
    of a segregation-of-duties conflict with the remake team.
    """
    create_trained_reviewer(full_name="Sam Ober", party_affiliation="NPP")
    member_a = create_trained_reviewer(full_name="Ada Vance", party_affiliation="DEM")
    member_b = create_trained_reviewer(full_name="Bo Reyes", party_affiliation="REP")

    bundle = setup_received_envelopes(count=2, intake_at=INTAKE_AT,
                                      intake_channel="DROPBOX",
                                      posture="RECEIVING", clock=SETUP_CLOCK)
    original, untouched = bundle["envelopes"]

    review = open_review(original["id"])
    submit_decision(review, decision="MATCH", similarity_score=80)
    original = get_envelope(original["id"])
    assert original["signature_status"] == "ACCEPTED", \
        "a round-one match at similarity 80 clears the auto-accept threshold"
    assert original["custody_status"] == "SEALED"

    remake = open_remake(original, member_a, member_b, reason_code="DAMAGED",
                         session_start_at=SESSION_START_AT,
                         session_end_at=SESSION_END_AT)
    assert remake["status"] == "OPEN"
    return {
        "election": bundle["election"],
        "original": get_envelope(original["id"]),
        "untouched": untouched,
        "remake": remake,
    }


class TestAttributableBallotCountConservedAcrossRemake:
    """Completing a remake swaps the original out of the attributable set and the
    minted replacement in; voiding that completion swaps them back. The count
    must read identically at all three checkpoints."""

    def test_attributable_ballot_count_survives_completion_and_the_void_unchanged(self, api):
        """Any drift at all in `attributable_ballot_count` across that pair of operations is a defect.

        Design: Difficulty/compensating_invariant/attributable_ballot_count_conserved_across_remake_complete_then_void
        """
        context = _setup_open_remake_on_an_accepted_envelope()
        election_id = context["election"]["id"]

        before = get_accountability(election_id)
        assert before["attributable_ballot_count"] == 2, \
            "one ACCEPTED and one UNVERIFIED envelope, both custody SEALED, are both attributable"
        assert before["countable_envelope_count"] == 0, \
            "neither envelope has been separated, so neither is countable yet"

        completed = complete_remake(context["remake"]["id"], remade_serial="R-0001")
        assert completed["status"] == "COMPLETED"
        assert completed["remade_envelope_id"] is not None, \
            "completion mints the replacement envelope and points the record at it"
        assert _as_instant(completed["completed_at"]) == _as_instant(INTAKE_AT), \
            "completed_at is stamped from the logical clock"
        after_completion = get_accountability(election_id)
        assert after_completion["attributable_ballot_count"] == \
            before["attributable_ballot_count"]

        voided = void_remake(context["remake"]["id"],
                             voided_reason_code="WRONG_BALLOT_STYLE_PULLED")
        assert voided["status"] == "VOIDED"
        after_void = get_accountability(election_id)
        assert after_void["attributable_ballot_count"] == \
            before["attributable_ballot_count"], \
            "the compensating action must restore the exact pre-completion count"

    def test_envelopes_received_count_is_deliberately_not_conserved(self, api):
        """`envelopes_received_count`, by contrast, is deliberately **not** conserved: it increases by exactly one for every completed remake, because the replacement row is retained forever as an audit artifact.

        Design: Difficulty/compensating_invariant/attributable_ballot_count_conserved_across_remake_complete_then_void
        """
        context = _setup_open_remake_on_an_accepted_envelope()
        election_id = context["election"]["id"]

        assert get_accountability(election_id)["envelopes_received_count"] == 2

        complete_remake(context["remake"]["id"], remade_serial="R-0001")
        assert get_accountability(election_id)["envelopes_received_count"] == 3, \
            "the minted replacement is itself a received envelope"

        void_remake(context["remake"]["id"],
                    voided_reason_code="WRONG_BALLOT_STYLE_PULLED")
        assert get_accountability(election_id)["envelopes_received_count"] == 3, \
            "voiding does not delete the replacement row"

    def test_void_restores_the_original_and_withdraws_the_replacement(self, api):
        """The obligation is the compensating action: the replacement envelope's `signature_status` is set to `REJECTED` and its `custody_status` to `SEQUESTERED`, removing it from the countable pool, and the original envelope returns `SUPERSEDED_BY_REMAKE → SEALED` carrying its pre-remake `signature_status`.

        Design: Difficulty/compensating_invariant/attributable_ballot_count_conserved_across_remake_complete_then_void
        """
        context = _setup_open_remake_on_an_accepted_envelope()
        original_id = context["original"]["id"]

        completed = complete_remake(context["remake"]["id"], remade_serial="R-0001")
        replacement_id = completed["remade_envelope_id"]
        assert get_envelope(original_id)["custody_status"] == "SUPERSEDED_BY_REMAKE"
        replacement = get_envelope(replacement_id)
        assert replacement["remade_from_envelope_id"] == original_id
        assert replacement["custody_status"] == "SEALED"
        assert replacement["signature_status"] == "ACCEPTED", \
            "the replacement opens carrying the original's signature verdict"

        void_remake(context["remake"]["id"],
                    voided_reason_code="WRONG_BALLOT_STYLE_PULLED")

        original = get_envelope(original_id)
        assert original["custody_status"] == "SEALED"
        assert original["signature_status"] == "ACCEPTED", \
            "the original recovers its exact pre-remake signature dimension"
        replacement = get_envelope(replacement_id)
        assert replacement["custody_status"] == "SEQUESTERED"
        assert replacement["signature_status"] == "REJECTED"

    def test_reconciliation_stays_in_balance_at_every_checkpoint(self, api):
        """The election's `attributable_ballot_count` must land back on its exact pre-completion value; `envelopes_received_count`, as §2.11 says, does not come back down, because the replacement row is retained forever.

        Design: Difficulty/compensating_invariant/attributable_ballot_count_conserved_across_remake_complete_then_void
        """
        context = _setup_open_remake_on_an_accepted_envelope()
        election_id = context["election"]["id"]

        before = get_accountability(election_id)
        assert_accountability_identity(before)
        assert before["accountability_delta"] == 0, \
            "two mailed packets both came back as envelopes, so nothing is unaccounted for"

        complete_remake(context["remake"]["id"], remade_serial="R-0001")
        mid = get_accountability(election_id)
        assert_accountability_identity(mid)
        assert mid["accountability_delta"] == 0

        void_remake(context["remake"]["id"],
                    voided_reason_code="WRONG_BALLOT_STYLE_PULLED")
        after = get_accountability(election_id)
        assert_accountability_identity(after)
        assert after["accountability_delta"] == 0
        assert after["countable_envelope_count"] == before["countable_envelope_count"]
        assert get_election(election_id)["reconciliation_status"] == "IN_BALANCE"


def _setup_sealed_baseline_and_draft_supplement() -> dict:
    """An election carrying a committed baseline plus an uncommitted supplement:
    batch X is SEALED over one 141-cent packet, batch Y is still DRAFT over two.
    The baseline commitment is the value that must survive the whole exercise.
    """
    election = setup_election(posture="PRE_MAIL", clock=SETUP_CLOCK)

    baseline = create_batch(election, batch_type="DOMESTIC_INITIAL",
                            scheduled_send_date="2026-09-15")
    first = setup_approved_request(
        election, create_voter(full_name="Tia Lowe", party_affiliation="DEM",
                               residence_address="29 Dill St"))
    baseline_packet = add_packet(baseline["id"], first["request"]["id"], 28)
    baseline = seal_batch(baseline["id"])

    supplement = create_batch(election, batch_type="SUPPLEMENTAL",
                              scheduled_send_date="2026-09-16")
    second = setup_approved_request(
        election, create_voter(full_name="Uri Nash", party_affiliation="REP",
                               residence_address="30 Elder St"))
    third = setup_approved_request(
        election, create_voter(full_name="Wes Ortiz", party_affiliation="NPP",
                               residence_address="31 Fennel St"))
    packet_b = add_packet(supplement["id"], second["request"]["id"], 28)
    packet_c = add_packet(supplement["id"], third["request"]["id"], 28)

    return {
        "election": election,
        "baseline": baseline,
        "baseline_packet": baseline_packet,
        "supplement": supplement,
        "supplement_packets": [packet_b, packet_c],
        "superseding_voter": second["voter"],
    }


def _supersede(api, election: dict, voter: dict) -> dict:
    """Log a second ballot request for one voter, which supersedes the first and
    spoils its still-queued packet. The voter is re-read so the stale-view guard
    carries the current version."""
    current = validate_success(api.get_voter(voter["id"], CLERK), 200)
    return create_ballot_request(current, election, request_channel="PHONE")


class TestPostageCommittedCentsConservedAcrossSealThenCancel:
    """Sealing adds a frozen estimate to the election's commitment and cancelling
    releases that same frozen figure — not a fresh estimate over whatever packets
    are left once a request has been superseded in between."""

    def test_seal_commits_the_frozen_estimate_and_cancel_releases_it_in_full(self, api):
        """After that batch is cancelled it equals the prior value exactly — the frozen estimate is released in full, never a fresh estimate recomputed over the now-spoiled packets.

        Design: Difficulty/compensating_invariant/postage_committed_cents_conserved_across_seal_then_cancel
        """
        context = _setup_sealed_baseline_and_draft_supplement()
        election_id = context["election"]["id"]

        assert context["baseline"]["estimated_postage_cents"] == DOMESTIC_PACKET_CENTS
        before = get_accountability(election_id)
        assert before["postage_committed_cents"] == DOMESTIC_PACKET_CENTS
        assert before["postage_actual_cents"] == 0, "nothing has been dispatched"

        sealed = seal_batch(context["supplement"]["id"])
        assert sealed["estimated_postage_cents"] == 2 * DOMESTIC_PACKET_CENTS, \
            "two 141-cent packets, each rounded before summation"
        assert get_accountability(election_id)["postage_committed_cents"] == 423

        _supersede(api, context["election"], context["superseding_voter"])
        cancel_batch(context["supplement"]["id"],
                     cancellation_reason_code="OPERATOR_ERROR")

        after = get_accountability(election_id)
        assert after["postage_committed_cents"] == before["postage_committed_cents"], \
            "the full frozen 282 is released, not the 141 recomputed over the survivor"
        assert after["postage_committed_cents"] == DOMESTIC_PACKET_CENTS

    def test_supersession_between_seal_and_cancel_does_not_shrink_the_commitment(self, api):
        """The **estimated** variant of the postage assessment is computed over the batch's packets whose status is `QUEUED` at that instant, written to `estimated_postage_cents`, and frozen there permanently.

        Design: Difficulty/compensating_invariant/postage_committed_cents_conserved_across_seal_then_cancel
        """
        context = _setup_sealed_baseline_and_draft_supplement()
        election_id = context["election"]["id"]
        spoiled_packet = context["supplement_packets"][0]

        seal_batch(context["supplement"]["id"])
        assert get_accountability(election_id)["postage_committed_cents"] == 423

        _supersede(api, context["election"], context["superseding_voter"])

        assert validate_success(
            api.get_ballot_packet(spoiled_packet["id"], CLERK), 200)["status"] == "SPOILED"
        assert get_accountability(election_id)["postage_committed_cents"] == 423, \
            "spoiling a packet must not retroactively shrink an already frozen estimate"
        assert validate_success(
            api.get_mailing_batch(context["supplement"]["id"], CLERK),
            200)["estimated_postage_cents"] == 282

    def test_cancelled_batch_keeps_its_frozen_estimate_and_actual_postage_is_untouched(self, api):
        """`postage_actual_cents` is untouched by both seal and cancel and remains at its pre-seal value; it accumulates only at dispatch, as the sum of `actual_postage_cents` over dispatched batches.

        Design: Difficulty/compensating_invariant/postage_committed_cents_conserved_across_seal_then_cancel
        """
        context = _setup_sealed_baseline_and_draft_supplement()
        election_id = context["election"]["id"]

        seal_batch(context["supplement"]["id"])
        _supersede(api, context["election"], context["superseding_voter"])
        cancelled = cancel_batch(context["supplement"]["id"],
                                 cancellation_reason_code="OPERATOR_ERROR")

        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason_code"] == "OPERATOR_ERROR"
        assert cancelled["estimated_postage_cents"] == 282, \
            "the frozen estimate stays on the cancelled batch as an audit record"
        assert get_accountability(election_id)["postage_actual_cents"] == 0

        baseline = validate_success(
            api.get_mailing_batch(context["baseline"]["id"], CLERK), 200)
        assert baseline["status"] == "SEALED", "cancelling one batch leaves the other alone"
        assert baseline["estimated_postage_cents"] == DOMESTIC_PACKET_CENTS

    def test_cancel_from_sealed_spoils_every_queued_packet_and_restores_the_election(self, api):
        """Cancelling from `SEALED` additionally performs the compensating action: the batch's frozen `estimated_postage_cents` is subtracted from the election's `postage_committed_cents`, restoring the exact pre-seal value as required by §2.11.

        Design: Difficulty/compensating_invariant/postage_committed_cents_conserved_across_seal_then_cancel
        """
        context = _setup_sealed_baseline_and_draft_supplement()
        election_id = context["election"]["id"]
        supplement_id = context["supplement"]["id"]

        pre_seal = get_election(election_id)["postage_committed_cents"]
        seal_batch(supplement_id)
        cancel_batch(supplement_id, cancellation_reason_code="OPERATOR_ERROR")

        election = get_election(election_id)
        assert election["postage_committed_cents"] == pre_seal == DOMESTIC_PACKET_CENTS
        assert election["postage_committed_cents"] == \
            get_accountability(election_id)["postage_committed_cents"], \
            "the election read and the accountability read report one figure"

        rows, meta = validate_paginated(
            api.list_ballot_packets(CLERK, params={"mailing_batch_id": supplement_id}))
        assert meta["total_count"] == 2
        assert {row["status"] for row in rows} == {"SPOILED"}
