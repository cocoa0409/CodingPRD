"""Corner coverage: phase lifecycle edges (invalid transitions, terminal
lockdown, sequencing), closing double-transition rejection, and the budget
revision loop."""
from test_helpers import (
    api_client,
    activate_payload,
    close_lots_with_owners,
    create_active_agreement,
    create_active_community,
    create_and_close_lot,
    create_community,
    create_draft_agreement,
    create_executed_agreement,
    create_lot,
    create_offered_lot,
    create_open_phase,
    create_phase,
    create_builder,
    create_proposed_budget,
    setup_active_agreement_scenario,
    set_clock,
    get_success_data,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]
DIRECTOR = TEST_USERS["association_director_headers"]


class TestPhaseInvalidTransitionsAndTerminalLockdown:
    def test_closeout_from_planned_and_cancelled_terminal_lockdown(self):
        """PRD §3.2: "Closing out a `DELIVERING` phase requires that every lot in the phase be in `CLOSED` or `WITHDRAWN` and that every agreement drawing on the phase be in `COMPLETED`, `DEFAULTED`, or `TERMINATED`; either shortfall is rejected with `ERR_CLOSEOUT_BLOCKED`." (close-out is defined only
        from DELIVERING).
        PRD §2.9 rung 5: "State — the target must be in a valid from-state for
        the requested transition (ERR_INVALID_STATE, HTTP 409)".
        PRD §3.2: "A `PLANNED` or `SALES_OPEN` phase may instead be cancelled, but only while no closing in `PENDING` or `CLOSED` references any of its lots (again `ERR_CLOSEOUT_BLOCKED`).".

        Design: Corner/state_machines/phase_invalid_transitions_and_terminal_lockdown
        """
        community = create_active_community("Lockdown Lane", 10)
        phase = create_phase(community["id"], "P1", 1, 5)
        assert phase["status"] == "PLANNED"

        resp_closeout = api_client.close_out_phase(phase["id"], EXEC)
        validate_error(resp_closeout, ApiErrorId.ERR_INVALID_STATE)

        cancelled = get_success_data(api_client.cancel_phase(phase["id"], EXEC))
        assert cancelled["status"] == "CANCELLED"

        resp_again = api_client.cancel_phase(phase["id"], EXEC)
        validate_error(resp_again, ApiErrorId.ERR_INVALID_STATE)

        resp_open = api_client.open_sales(phase["id"], EXEC)
        validate_error(resp_open, ApiErrorId.ERR_INVALID_STATE)


class TestClosingDoubleTransitionRejected:
    def test_second_close_and_cancel_after_close_rejected(self):
        """PRD §3.4: "Recording the close — `PENDING` → `CLOSED`, again by a `DeclarantController`, again gated on the agreement being `ACTIVE` and the lot being `UNDER_CONTRACT` (`ERR_LOT_NOT_UNDER_CONTRACT`) — is the system's central transaction, and its effects land in a fixed order." and
        "Cancelling a PENDING closing returns the lot to OFFERED" — both are
        defined only from PENDING.
        PRD §2.9 rung 5: "State — the target must be in a valid from-state for
        the requested transition (ERR_INVALID_STATE, HTTP 409)".

        Design: Corner/state_machines/closing_double_transition_rejected
        """
        scenario = setup_active_agreement_scenario(
            total_planned_units=10, planned_lot_count=5, total_lots_committed=1,
            tranches=[("2026-06-30T00:00:00Z", 1)], community_name="Double Close",
            earnest_money_cents=1000000,
        )
        lot = create_offered_lot(scenario["phase"]["id"], "L1")
        set_clock("2026-06-01T00:00:00Z")
        closing = create_and_close_lot(scenario["agreement"]["id"], lot["id"])
        assert closing["status"] == "CLOSED"

        lot_read = get_success_data(api_client.get_lot(lot["id"], EXEC))
        assert lot_read["status"] == "CLOSED"

        resp_close2 = api_client.close_closing(closing["id"], CTRL)
        validate_error(resp_close2, ApiErrorId.ERR_INVALID_STATE)

        resp_cancel = api_client.cancel_closing(closing["id"], CTRL)
        validate_error(resp_cancel, ApiErrorId.ERR_INVALID_STATE)


class TestBudgetRevisionCycle:
    def test_rejected_budget_returns_to_draft_and_reproposes(self):
        """PRD §3.5: "Rejection is available to an `AssociationDirector` from either `PROPOSED` or `PENDING_RATIFICATION`, and a `REJECTED` budget returns to `DRAFT` through the controller's revise action — a full revision loop."

        Design: Corner/state_machines/budget_revision_cycle
        """
        community = create_active_community("Revision Ranch", 10)
        budget = create_proposed_budget(
            community["id"], 2027, [("INSURANCE", 300000)]
        )
        rejected = get_success_data(api_client.reject_budget(budget["id"], DIRECTOR))
        assert rejected["status"] == "REJECTED"

        draft = get_success_data(api_client.revise_budget(budget["id"], CTRL))
        assert draft["status"] == "DRAFT"

        reproposed = get_success_data(api_client.propose_budget(budget["id"], CTRL))
        assert reproposed["status"] == "PROPOSED"


class TestPhaseSequenceBlockedUntilPredecessorDelivers:
    def test_open_sales_gated_on_predecessor_and_unique_sequence(self):
        """PRD §3.2: "Opening sales moves the phase from `PLANNED` to `SALES_OPEN` and is gated twice: the community must be `ACTIVE` (otherwise `ERR_COMMUNITY_NOT_ACTIVE`), and the phase with the immediately preceding `sequence_no` in the same community, when one exists, must already be `DELIVERING` or `CLOSED_OUT` (otherwise `ERR_PHASE_SEQUENCE_BLOCKED`; the same error fires when the `sequence_no` itself is already used in the community)."

        Design: Corner/state_machines/phase_sequence_blocked_until_predecessor_delivers
        """
        community = create_active_community("Sequence Springs", 10)
        phase1 = create_phase(community["id"], "P1", 1, 5)
        phase2 = create_phase(community["id"], "P2", 2, 5)

        resp_dup = api_client.create_phase(
            {
                "community_id": community["id"], "phase_name": "P1-dup",
                "sequence_no": 1, "planned_lot_count": 3,
            },
            EXEC,
        )
        validate_error(resp_dup, ApiErrorId.ERR_PHASE_SEQUENCE_BLOCKED)

        resp_seq = api_client.open_sales(phase2["id"], EXEC)
        validate_error(resp_seq, ApiErrorId.ERR_PHASE_SEQUENCE_BLOCKED)

        opened = get_success_data(api_client.open_sales(phase1["id"], EXEC))
        assert opened["status"] == "SALES_OPEN"

        resp_seq2 = api_client.open_sales(phase2["id"], EXEC)
        validate_error(resp_seq2, ApiErrorId.ERR_PHASE_SEQUENCE_BLOCKED)


class TestCommunityAndPhaseStateGates:
    def test_open_sales_requires_active_community_and_open_phase_gates(self):
        """PRD §3.2: "Opening sales moves the phase from `PLANNED` to `SALES_OPEN` and is gated twice: the community must be `ACTIVE` (otherwise `ERR_COMMUNITY_NOT_ACTIVE`), and the phase with the immediately preceding `sequence_no` in the same community, when one exists, must already be `DELIVERING` or `CLOSED_OUT` (otherwise `ERR_PHASE_SEQUENCE_BLOCKED`; the same error fires when the `sequence_no` itself is already used in the community).".
        PRD §3.3: "Execution moves the agreement from `DRAFT` to `EXECUTED` under a `DeclarantExecutive` and enforces four gates: the community must be `ACTIVE` (`ERR_COMMUNITY_NOT_ACTIVE`), the builder must be in `GOOD_STANDING` (`ERR_BUILDER_NOT_IN_GOOD_STANDING`), the phase must be `SALES_OPEN` or `DELIVERING` (`ERR_PHASE_NOT_OPEN_FOR_SALES`), and the tranche schedule must exactly cover the commitment — the sum of `lot_count_due` across the agreement's tranches must equal `total_lots_committed` (`ERR_TRANCHE_COVERAGE_MISMATCH`).".
        PRD §3.4: "A new lot is `PLATTED`; offering it moves it to `OFFERED` and requires the phase to be `SALES_OPEN` or `DELIVERING` (`ERR_PHASE_NOT_OPEN_FOR_SALES`); an `OFFERED` lot may be pulled back to `WITHDRAWN`.".

        Design: Corner/state_machines/community_and_phase_state_gates
        """
        community = create_community("Gate Gardens", 10)
        phase = create_phase(community["id"], "P1", 1, 5)
        builder = create_builder(community["id"], "Gate Builders", "A")
        agreement, _ = create_draft_agreement(
            community["id"], builder["id"], phase["id"], 1,
            [("2026-06-30T00:00:00Z", 1)],
        )
        lot = create_lot(phase["id"], "G1")

        resp_community = api_client.open_sales(phase["id"], EXEC)
        validate_error(resp_community, ApiErrorId.ERR_COMMUNITY_NOT_ACTIVE)

        get_success_data(api_client.activate_community(community["id"], activate_payload(), EXEC))

        resp_execute = api_client.execute_agreement(agreement["id"], EXEC)
        validate_error(resp_execute, ApiErrorId.ERR_PHASE_NOT_OPEN_FOR_SALES)

        resp_offer = api_client.offer_lot(lot["id"], EXEC)
        validate_error(resp_offer, ApiErrorId.ERR_PHASE_NOT_OPEN_FOR_SALES)
