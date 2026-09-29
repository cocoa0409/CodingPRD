"""Ordered validation precedence where one call breaks two rules at once.

Each scenario builds a request that violates two rules from different categories,
proves the lower-numbered category is the one reported, and then isolates the
losing rule on its own so that it is demonstrably still live.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_packet,
    api_client,
    create_batch,
    create_trained_reviewer,
    create_voter,
    get_election,
    get_envelope,
    get_success_data,
    remake_payload,
    setup_approved_request,
    setup_election,
    setup_received_envelopes,
    setup_sealed_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

CLERK = TEST_USERS["elections_clerk_headers"]
SUPERVISOR = TEST_USERS["canvass_supervisor_headers"]


def _instant(value):
    """Parse an emitted ISO 8601 UTC instant, tolerating the fractional digits."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _get_batch(batch_id):
    return get_success_data(api_client.get_mailing_batch(batch_id, CLERK))


def _setup_two_batches_on_a_200_cent_authority():
    """An election whose whole postage authority is 200 cents, one SEALED batch holding
    a single 141-cent packet, and a second DRAFT batch holding another one."""
    election = setup_election(clock="2026-09-10T00:00:00Z", postage_budget_cents=200)
    sealed = setup_sealed_batch(election, weights=(28,))

    draft = create_batch(election, batch_type="SUPPLEMENTAL",
                        scheduled_send_date="2026-09-16")
    second = setup_approved_request(election,
                                    create_voter(full_name="Ivan Koss",
                                                 residence_address="14 Nutmeg St"))
    draft_packet = add_packet(draft["id"], second["request"]["id"], 28)
    return {"election": election, "sealed_batch": sealed["batch"],
            "sealed_packet": sealed["packets"][0], "draft_batch": draft,
            "draft_packet": draft_packet}


class TestSealStateBeatsPostageBudget:
    """Re-sealing a SEALED batch breaks the state gate and the postage authority in the
    same call, and the state gate is the one reported."""

    def test_reseal_reports_the_state_error_and_never_the_budget_error(self):
        """Both rules are violated — the batch is already SEALED, and counting its frozen
        141 cents twice would overrun the 200-cent authority — yet the state gate wins.

        "When a single request violates more than one rule, the service reports the violation with the lowest precedence number below."

        Design: Difficulty/priority_pair_validation_conflict/batch_state_beats_postage_budget_on_second_seal
        """
        bundle = _setup_two_batches_on_a_200_cent_authority()
        assert bundle["sealed_packet"]["packet_postage_cents"] == 141
        assert bundle["sealed_batch"]["status"] == "SEALED"
        assert bundle["sealed_batch"]["estimated_postage_cents"] == 141
        assert get_election(bundle["election"]["id"])["postage_committed_cents"] == 141

        validate_error(api_client.seal_batch(bundle["sealed_batch"]["id"], CLERK),
                       ApiErrorId.ERR_BATCH_STATE_INVALID, 409)

    def test_the_losing_budget_rule_still_fires_on_a_draft_batch(self):
        """With the state gate satisfied the only remaining violation is fiscal, so the
        second seal is refused for breaching the authority.

        "The postage authority check runs before the commitment lands: the election's current `postage_committed_cents` plus this batch's estimated total must be at most the election's `postage_budget_cents`, and a seal that would breach the authority is rejected with `ERR_POSTAGE_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/batch_state_beats_postage_budget_on_second_seal
        """
        bundle = _setup_two_batches_on_a_200_cent_authority()
        assert bundle["draft_batch"]["status"] == "DRAFT"
        assert bundle["draft_packet"]["packet_postage_cents"] == 141

        validate_error(api_client.seal_batch(bundle["draft_batch"]["id"], CLERK),
                       ApiErrorId.ERR_POSTAGE_BUDGET_EXCEEDED, 402)

    def test_neither_rejected_seal_moves_money_or_the_frozen_seal_instant(self):
        """The rejected pair and the rejected fiscal control both leave the accumulators,
        the first batch's seal instant, and the second batch's estimate untouched.

        "`postage_actual_cents` is untouched by both seal and cancel and remains at its pre-seal value; it accumulates only at dispatch, as the sum of `actual_postage_cents` over dispatched batches."

        Design: Difficulty/priority_pair_validation_conflict/batch_state_beats_postage_budget_on_second_seal
        """
        bundle = _setup_two_batches_on_a_200_cent_authority()
        sealed_at = bundle["sealed_batch"]["sealed_at"]

        validate_error(api_client.seal_batch(bundle["sealed_batch"]["id"], CLERK),
                       ApiErrorId.ERR_BATCH_STATE_INVALID, 409)
        validate_error(api_client.seal_batch(bundle["draft_batch"]["id"], CLERK),
                       ApiErrorId.ERR_POSTAGE_BUDGET_EXCEEDED, 402)

        election = get_election(bundle["election"]["id"])
        assert election["postage_committed_cents"] == 141
        assert election["postage_actual_cents"] == 0

        first = _get_batch(bundle["sealed_batch"]["id"])
        assert first["status"] == "SEALED"
        assert _instant(first["sealed_at"]) == _instant(sealed_at)

        second = _get_batch(bundle["draft_batch"]["id"])
        assert second["status"] == "DRAFT"
        assert second["estimated_postage_cents"] == 0
        assert second["sealed_at"] is None


def _setup_remake_conflict():
    """Four trained reviewers, two intake-logged envelopes, and one OPEN remake session
    on the first envelope held by reviewers A and B from 13:00 to 14:00."""
    reviewers = {
        "a": create_trained_reviewer(full_name="Ada Vance", party_affiliation="DEM"),
        "b": create_trained_reviewer(full_name="Bo Reyes", party_affiliation="REP"),
        "c": create_trained_reviewer(full_name="Cy Marsh", party_affiliation="DEM"),
        "d": create_trained_reviewer(full_name="Dot Peck", party_affiliation="REP"),
    }
    bundle = setup_received_envelopes(count=2, intake_at="2026-11-03T12:00:00Z",
                                     intake_channel="DROPBOX")
    occupied, target = bundle["envelopes"]

    held = validate_success(
        api_client.create_remake(
            occupied["id"],
            remake_payload(reviewers["a"]["id"], reviewers["b"]["id"],
                          get_envelope(occupied["id"])["version"],
                          reason_code="DAMAGED",
                          session_start_at="2026-11-05T13:00:00Z",
                          session_end_at="2026-11-05T14:00:00Z"),
            SUPERVISOR), 201)
    assert held["status"] == "OPEN"

    target = get_envelope(target["id"])
    assert target["custody_status"] == "SEALED"
    assert target["signature_status"] == "UNVERIFIED"
    return {"reviewers": reviewers, "held_remake": held, "target": target,
            "election": bundle["election"]}


def _attempt_remake(target, member_a, member_b, expected_version):
    """Propose a 14:10-to-15:00 session on `target`, ten minutes after the held one
    ends and therefore inside the fifteen-minute changeover buffer."""
    return api_client.create_remake(
        target["id"],
        remake_payload(member_a["id"], member_b["id"], expected_version,
                      reason_code="TORN_ENVELOPE",
                      session_start_at="2026-11-05T14:10:00Z",
                      session_end_at="2026-11-05T15:00:00Z"),
        SUPERVISOR)


def _remakes_for(envelope_id):
    return validate_paginated(
        api_client.list_remake_records(SUPERVISOR,
                                      params={"original_envelope_id": envelope_id}))


class TestBipartisanSafetyBeatsDoubleBooking:
    """A same-party team that also overlaps an existing session breaks a safety rule and
    a capacity rule at once, and the safety rule is the one reported."""

    def test_same_party_overlapping_team_reports_the_bipartisan_failure(self):
        """Reviewers A and C are both DEM and A already sits on the held session, so both
        rules fire, and the composition rule is reported rather than the collision.

        "The team must be bipartisan — the two nominated identifiers must not be the same reviewer and the two reviewers' `party_affiliation` values must differ — else `ERR_REMAKE_TEAM_NOT_BIPARTISAN`."

        Design: Difficulty/priority_pair_validation_conflict/bipartisan_safety_beats_double_booking_constraint_on_remake
        """
        bundle = _setup_remake_conflict()
        reviewers = bundle["reviewers"]
        assert reviewers["a"]["party_affiliation"] == reviewers["c"]["party_affiliation"]

        validate_error(
            _attempt_remake(bundle["target"], reviewers["a"], reviewers["c"],
                            bundle["target"]["version"]),
            ApiErrorId.ERR_REMAKE_TEAM_NOT_BIPARTISAN, 422)

    def test_the_losing_double_booking_rule_still_fires_on_a_bipartisan_team(self):
        """Reviewers B and C are of different parties, so the composition gate is passed and
        B's ten-minute gap from the held session is refused on its own.

        "For either team member, the proposed session collides with any remake record in `OPEN` or `COMPLETED` on which that reviewer already sits when the proposed `session_start_at` reduced by fifteen minutes is at or before the existing session's `session_end_at` **and** the existing session's `session_start_at` is at or before the proposed `session_end_at` increased by fifteen minutes."

        Design: Difficulty/priority_pair_validation_conflict/bipartisan_safety_beats_double_booking_constraint_on_remake
        """
        bundle = _setup_remake_conflict()
        reviewers = bundle["reviewers"]
        assert reviewers["b"]["party_affiliation"] != reviewers["c"]["party_affiliation"]

        validate_error(
            _attempt_remake(bundle["target"], reviewers["b"], reviewers["c"],
                            bundle["target"]["version"]),
            ApiErrorId.ERR_REMAKE_TEAM_DOUBLE_BOOKED, 409)

    def test_a_free_bipartisan_team_takes_the_identical_window(self):
        """Reviewers C and D are of different parties and sit on nothing, so the very window
        that was refused twice is accepted for them.

        "The record opens in `OPEN` with `original_envelope_id` pointing at the envelope under remake, and `remade_envelope_id`, `completed_at`, and `voided_reason_code` all null."

        Design: Difficulty/priority_pair_validation_conflict/bipartisan_safety_beats_double_booking_constraint_on_remake
        """
        bundle = _setup_remake_conflict()
        reviewers = bundle["reviewers"]

        opened = validate_success(
            _attempt_remake(bundle["target"], reviewers["c"], reviewers["d"],
                            bundle["target"]["version"]), 201)
        assert opened["status"] == "OPEN"
        assert opened["original_envelope_id"] == bundle["target"]["id"]
        assert opened["remade_envelope_id"] is None
        assert opened["completed_at"] is None
        assert opened["voided_reason_code"] is None

        rows, meta = _remakes_for(bundle["target"]["id"])
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [opened["id"]]

    def test_both_rejected_proposals_leave_no_record_and_no_version_bump(self):
        """Neither refusal mints a remake record, and because only a successful create
        touches the envelope, its version and custody dimension stay where they were.

        "A successful create increments `ReturnEnvelope.version` by one."

        Design: Difficulty/priority_pair_validation_conflict/bipartisan_safety_beats_double_booking_constraint_on_remake
        """
        bundle = _setup_remake_conflict()
        reviewers = bundle["reviewers"]
        target = bundle["target"]

        validate_error(
            _attempt_remake(target, reviewers["a"], reviewers["c"], target["version"]),
            ApiErrorId.ERR_REMAKE_TEAM_NOT_BIPARTISAN, 422)
        validate_error(
            _attempt_remake(target, reviewers["b"], reviewers["c"], target["version"]),
            ApiErrorId.ERR_REMAKE_TEAM_DOUBLE_BOOKED, 409)

        rows, meta = _remakes_for(target["id"])
        assert meta["total_count"] == 0
        assert rows == []

        after = get_envelope(target["id"])
        assert after["version"] == target["version"]
        assert after["custody_status"] == "SEALED"

        opened = validate_success(
            _attempt_remake(target, reviewers["c"], reviewers["d"], target["version"]), 201)
        assert opened["status"] == "OPEN"
        assert get_envelope(target["id"])["version"] == target["version"] + 1
