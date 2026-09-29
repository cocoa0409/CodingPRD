"""Compensating actions that must restore a conserved quantity exactly."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    NETWORK_MANAGER_HEADERS,
    assert_fields,
    assign_enrollee,
    build_prorated_july_roster,
    create_active_agreement,
    create_active_physician,
    create_enrollee,
    dispute_file,
    make_physician_user_headers,
    read_agreement,
    read_assignment,
    read_file,
    read_physician,
    read_remittance,
    set_clock,
    state_payload,
)

DISPUTE_REASON = (
    "The mid-month add on CM-0002 was prorated rather than paid in full"
)


class TestRemittanceDisputeRestoresAccruedCapitation:
    def test_reconciliation_accrues_the_expected_capitation(self, api):
        """PRD §3.5: "Reconciliation closes by accruing: the agreement's
        `accrued_capitation_cents` increases by the new remittance's
        `expected_capitation_cents` plus its `retro_adjustment_cents`."

        Design: Difficulty/compensating_invariant/remittance_dispute_restores_accrued_capitation_cents
        """
        built = build_prorated_july_roster(api)

        assert_fields(
            built["remittance"],
            {
                "status": "RECONCILED",
                "expected_capitation_cents": 86275,
                "retro_adjustment_cents": 0,
            },
        )
        assert (
            read_agreement(api, built["agreement"]["id"])["accrued_capitation_cents"]
            == 86275
        )

    def test_the_dispute_reverses_the_accrual_to_the_cent(self, api):
        """PRD §3.5: "This is the compensating action for reconciliation and the
        conserved quantity is the agreement's `accrued_capitation_cents`."

        Design: Difficulty/compensating_invariant/remittance_dispute_restores_accrued_capitation_cents
        """
        built = build_prorated_july_roster(api)
        dispute_file(api, built["file"]["id"], built["agreement"]["id"], DISPUTE_REASON)

        restored = read_agreement(api, built["agreement"]["id"])
        assert restored["accrued_capitation_cents"] == 0
        assert restored["accrued_capitation_cents"] != 86274
        assert restored["accrued_capitation_cents"] != 86276

    def test_the_dispute_moves_the_file_and_its_remittance(self, api):
        """PRD §3.5: "Four things happen: the file's `status` becomes `DISPUTED`;
        the file's remittance whose `status` is `RECONCILED` moves to `DISPUTED`,
        advancing that remittance's `version` by 1; the agreement's
        `accrued_capitation_cents` decreases by exactly that remittance's
        `expected_capitation_cents` plus its `retro_adjustment_cents`, precisely
        reversing the accrual; and the agreement's `capitation_posture` is
        re-derived, which — because a disputed remittance now exists — makes it
        read `WITHHELD`."

        Design: Difficulty/compensating_invariant/remittance_dispute_restores_accrued_capitation_cents
        """
        built = build_prorated_july_roster(api)
        remittance_before = built["remittance"]

        disputed = dispute_file(
            api, built["file"]["id"], built["agreement"]["id"], DISPUTE_REASON
        )
        assert disputed["status"] == "DISPUTED"
        assert read_file(api, built["file"]["id"])["status"] == "DISPUTED"

        remittance_after = read_remittance(api, remittance_before["id"])
        assert remittance_after["status"] == "DISPUTED"
        assert remittance_after["version"] == remittance_before["version"] + 1
        assert remittance_after["expected_capitation_cents"] == 86275

    def test_the_dispute_drives_the_posture_to_withheld(self, api):
        """PRD §3.1: "If any capitation remittance of the agreement has `status`
        `DISPUTED`, the posture is `WITHHELD`."

        Design: Difficulty/compensating_invariant/remittance_dispute_restores_accrued_capitation_cents
        """
        built = build_prorated_july_roster(api)
        assert (
            read_agreement(api, built["agreement"]["id"])["capitation_posture"]
            == "CURRENT"
        )

        dispute_file(api, built["file"]["id"], built["agreement"]["id"], DISPUTE_REASON)

        assert (
            read_agreement(api, built["agreement"]["id"])["capitation_posture"]
            == "WITHHELD"
        )

    def test_an_unposted_dispute_never_touched_the_withhold_balance(self, api):
        """PRD §3.1: "A newly created agreement begins in `status` `DRAFT` with
        `capitation_posture` `CURRENT` and every derived counter at zero:
        `accrued_capitation_cents`, `withheld_balance_cents`,
        `forfeited_withhold_cents` and `total_assigned_members` all start at 0."

        Design: Difficulty/compensating_invariant/remittance_dispute_restores_accrued_capitation_cents
        """
        built = build_prorated_july_roster(api)
        dispute_file(api, built["file"]["id"], built["agreement"]["id"], DISPUTE_REASON)

        agreement = read_agreement(api, built["agreement"]["id"])
        assert agreement["withheld_balance_cents"] == 0
        assert agreement["forfeited_withhold_cents"] == 0


def _member_awaiting_a_transfer_answer(api):
    """One member on the source panel, with a transfer proposed to a successor."""
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(api, max_panel_size=5)
    source = create_active_physician(api, agreement["id"], full_name="Rowan Adeyemi")
    successor = create_active_physician(api, agreement["id"], full_name="Imani Okonkwo")
    enrollee = create_enrollee(api, agreement["id"], external_member_id="CC-0001")
    assignment = assign_enrollee(api, enrollee["id"], source["id"])

    set_clock(api, "2026-08-01T00:00:00Z")
    return agreement, source, successor, enrollee, assignment


def _propose_transfer(api, assignment_id, to_physician_id):
    response = api.set_assignment_state(
        assignment_id,
        state_payload(
            "TRANSFER_PROPOSED",
            to_physician_id=to_physician_id,
            transfer_effective_date="2026-09-01T00:00:00Z",
        ),
        NETWORK_MANAGER_HEADERS,
    )
    return validate_success(response, 200)


def _reject_transfer(api, assignment_id, successor_id):
    response = api.set_assignment_state(
        assignment_id,
        state_payload("ACTIVE"),
        make_physician_user_headers(successor_id),
    )
    return validate_success(response, 200)


class TestTransferRejectionPreservesAssignedMemberCount:
    def test_the_proposal_takes_the_row_out_of_the_active_counts(self, api):
        """PRD §3.4: "Because the row has left `ACTIVE`, the source physician's
        `panel_size` is recomputed one lower and the agreement's
        `total_assigned_members` is recomputed one lower in the same request."

        Design: Difficulty/compensating_invariant/transfer_rejection_preserves_total_assigned_members_count
        """
        agreement, source, successor, _enrollee, assignment = (
            _member_awaiting_a_transfer_answer(api)
        )
        assert read_agreement(api, agreement["id"])["total_assigned_members"] == 1
        assert read_physician(api, source["id"])["panel_size"] == 1

        proposed = _propose_transfer(api, assignment["id"], successor["id"])
        assert_fields(
            proposed,
            {
                "status": "TRANSFER_PROPOSED",
                "pending_to_physician_id": successor["id"],
            },
        )
        assert read_agreement(api, agreement["id"])["total_assigned_members"] == 0
        assert read_physician(api, source["id"])["panel_size"] == 0
        assert read_physician(api, successor["id"])["panel_size"] == 0

    def test_the_proposal_marks_the_source_panel_transfer_pending(self, api):
        """PRD §3.4: "The proposal is admitted only when `status` is `ACTIVE`, when
        `to_physician_id` resolves to a physician under the same agreement as the
        assignment's current holder, when that target physician's
        `credential_status` is `ACTIVE`, when the target's `panel_size` is strictly
        less than the agreement's `max_panel_size`, and when
        `transfer_effective_date` is at or after the current logical clock
        instant."

        Design: Difficulty/compensating_invariant/transfer_rejection_preserves_total_assigned_members_count
        """
        _agreement, source, successor, _enrollee, assignment = (
            _member_awaiting_a_transfer_answer(api)
        )
        assert read_physician(api, source["id"])["panel_status"] == "OPEN"

        _propose_transfer(api, assignment["id"], successor["id"])

        assert read_physician(api, source["id"])["panel_status"] == "TRANSFER_PENDING"
        assert read_physician(api, successor["id"])["panel_status"] == "OPEN"

    def test_rejection_returns_the_row_to_active_with_no_pending_target(self, api):
        """PRD §3.4: "Rejection takes the assignment `TRANSFER_PROPOSED → ACTIVE`,
        permitted when `status` is `TRANSFER_PROPOSED`."

        Design: Difficulty/compensating_invariant/transfer_rejection_preserves_total_assigned_members_count
        """
        _agreement, _source, successor, _enrollee, assignment = (
            _member_awaiting_a_transfer_answer(api)
        )
        _propose_transfer(api, assignment["id"], successor["id"])

        rejected = _reject_transfer(api, assignment["id"], successor["id"])
        assert_fields(
            rejected,
            {
                "status": "ACTIVE",
                "pending_to_physician_id": None,
                "term_date": None,
            },
        )
        assert read_assignment(api, assignment["id"])["status"] == "ACTIVE"

    def test_rejection_restores_both_count_quantities_exactly(self, api):
        """PRD §3.4: "Rejection is the compensating action for the proposal and it
        restores the two count quantities exactly: the source physician's
        `panel_size` and the agreement's `total_assigned_members` return to
        precisely the values they held before the proposal was made."

        Design: Difficulty/compensating_invariant/transfer_rejection_preserves_total_assigned_members_count
        """
        agreement, source, successor, _enrollee, assignment = (
            _member_awaiting_a_transfer_answer(api)
        )
        _propose_transfer(api, assignment["id"], successor["id"])
        assert read_agreement(api, agreement["id"])["total_assigned_members"] == 0

        _reject_transfer(api, assignment["id"], successor["id"])

        assert read_agreement(api, agreement["id"])["total_assigned_members"] == 1
        assert read_physician(api, source["id"])["panel_size"] == 1
        assert read_physician(api, successor["id"])["panel_size"] == 0

    def test_rejection_does_not_reopen_the_source_panel(self, api):
        """PRD §3.4: "It clears `pending_to_physician_id` back to null and, when no
        other assignment of the source physician remains in `TRANSFER_PROPOSED` or
        `TRANSFER_ACCEPTED`, resolves that physician's `panel_status` to
        `CLOSED_TO_NEW` — pointedly not back to `OPEN`, even if `OPEN` is where it
        started."

        Design: Difficulty/compensating_invariant/transfer_rejection_preserves_total_assigned_members_count
        """
        _agreement, source, successor, _enrollee, assignment = (
            _member_awaiting_a_transfer_answer(api)
        )
        _propose_transfer(api, assignment["id"], successor["id"])
        _reject_transfer(api, assignment["id"], successor["id"])

        assert read_physician(api, source["id"])["panel_status"] == "CLOSED_TO_NEW"
        assert read_physician(api, successor["id"])["panel_status"] == "OPEN"
