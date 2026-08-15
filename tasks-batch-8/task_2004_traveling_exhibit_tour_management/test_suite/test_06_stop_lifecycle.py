"""Stop lifecycle: branching REOPEN, terminal states, attendance and supervision
gates (PRD §3.2, §3.8)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_and_open_booking,
    create_venue,
    book_stop,
    setup_contracted_stop,
    setup_install_ready_stop,
    setup_stop_in_teardown,
    setup_closed_stop,
    setup_received_shipment,
    accept_unpack_reports_and_clear,
    file_submit_accept_report,
    transition_stop,
)

TM = TEST_USERS["tour_manager_headers"]
VR = TEST_USERS["venue_registrar_headers"]


class TestTeardownReopenBranching:
    def test_reopen_from_teardown_returns_to_open(self, api):
        """PRD §3.8: "Should the venue need the exhibit back, `REOPEN` returns
        the stop `TEARDOWN` → `OPEN` — but only while the participation contract
        is not yet `FINALIZED`; once the contract has been finalized, the stop's
        commercial outcome is sealed and teardown cannot be aborted."

        Design: Difficulty/non_linear_state_machine/tourstop_teardown_reopen_branching
        """
        tour, crates, venue, stop, contract, shipment = setup_stop_in_teardown(
            venue_overrides={"name": "Tech Museum", "city": "Austin"},
            stop_overrides={
                "install_start": "2026-09-01T00:00:00Z",
                "open_date": "2026-09-03T00:00:00Z",
                "close_date": "2026-10-03T00:00:00Z",
                "teardown_end": "2026-10-05T00:00:00Z",
                "projected_attendance": 9000,
            },
            contract_overrides={"base_fee_cents": 500000, "sponsorship_credit_cents": 0},
            title="Coders",
            exhibit_code="CODE-2026",
            refurbishment_gap_days=1,
        )
        res = api.transition_stop(tour["id"], stop["id"], {"action": "REOPEN"}, TM)
        reopened = validate_success(res, 200)
        assert reopened["status"] == "OPEN"

    def test_reopen_leaves_contract_signed_not_finalized(self, api):
        """PRD §3.8: "`REOPEN` returns the stop `TEARDOWN` → `OPEN` — but only
        while the participation contract is not yet `FINALIZED`; once the
        contract has been finalized, the stop's commercial outcome is sealed and
        teardown cannot be aborted."
        PRD §3.3: "Finalization is always system-performed, never a client act.
        Closing a stop finalizes its `SIGNED` contract with the FINAL variant."

        Design: Difficulty/non_linear_state_machine/tourstop_teardown_reopen_branching
        """
        tour, crates, venue, stop, contract, shipment = setup_stop_in_teardown(
            contract_overrides={"base_fee_cents": 500000, "sponsorship_credit_cents": 0},
        )
        validate_success(
            api.transition_stop(tour["id"], stop["id"], {"action": "REOPEN"}, TM), 200
        )
        contracts = validate_success(api.get_contract(tour["id"], stop["id"], TM), 200)
        live = [c for c in contracts if c["id"] == contract["id"]][0]
        assert live["status"] == "SIGNED"
        assert live["final_fee_cents"] is None


class TestClosedStopTerminal:
    def _setup_closed(self, api):
        return setup_closed_stop(
            actual_attendance=100,
            venue_overrides={"name": "Cycle Hall"},
            contract_overrides={"base_fee_cents": 100000, "sponsorship_credit_cents": 0},
            title="Bikes",
            exhibit_code="BIKE-2026",
        )

    @pytest.mark.parametrize(
        "action",
        ["REOPEN", "BEGIN_TEARDOWN", "OPEN_TO_PUBLIC", "BEGIN_INSTALL", "CANCEL"],
    )
    def test_closed_stop_rejects_further_transitions(self, api, action):
        """PRD §3.8: "`CLOSED` and `CANCELLED` are the stop's terminal states."
        PRD §2.8: "then transition state validity — a transition attempted from a
        state that does not permit it fails with `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/closed_stop_is_terminal
        """
        tour, crates, venue, stop, contract, shipment = self._setup_closed(api)
        res = api.transition_stop(tour["id"], stop["id"], {"action": action}, TM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestTentativeStopCannotInstall:
    def test_begin_install_from_tentative_rejected(self, api):
        """PRD §3.8: "a `TourManager` begins install (`action` `BEGIN_INSTALL`),
        taking the stop `CONTRACTED` → `INSTALLING`."
        PRD §2.8: "then transition state validity — a transition attempted from a
        state that does not permit it fails with `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/tentative_stop_cannot_begin_install
        """
        tour, _ = create_and_open_booking()
        venue = create_venue(name="Kite Field")
        stop = book_stop(tour["id"], venue["id"], projected_attendance=100)
        assert stop["status"] == "TENTATIVE"
        res = api.transition_stop(tour["id"], stop["id"], {"action": "BEGIN_INSTALL"}, TM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestCloseStopAttendanceGate:
    def test_close_without_attendance_rejected(self, api):
        """PRD §3.8: "And the stop's `actual_attendance` must have been reported;
        closing without it fails with `ERR_ATTENDANCE_MISSING`."

        Design: Corner/state_machines/close_stop_without_attendance_rejected
        """
        tour, crates, venue, stop, contract, shipment = setup_stop_in_teardown(
            venue_overrides={"name": "Doll House"},
            contract_overrides={"base_fee_cents": 100000, "sponsorship_credit_cents": 0},
            title="Dolls",
            exhibit_code="DOLL-2026",
        )
        # PACK reports accepted but actual_attendance never reported.
        for crate in crates:
            file_submit_accept_report(
                tour["id"], shipment["id"], crate["id"], phase="PACK"
            )
        res = api.transition_stop(tour["id"], stop["id"], {"action": "CLOSE_STOP"}, TM)
        validate_error(res, ApiErrorId.ERR_ATTENDANCE_MISSING)


class TestSupervisorGate:
    def test_begin_install_without_supervisor_rejected(self, api):
        """PRD §3.8: "Supervision comes second: when the stop's
        `supervision_required` flag is true, a supervisor must already be
        assigned (§3.2), or the attempt fails with `ERR_SUPERVISOR_REQUIRED`."

        Design: Corner/validations/supervisor_required_gate_enforced
        """
        tour, crates, venue, stop, contract, shipment = setup_install_ready_stop(
            venue_overrides={"name": "Barn", "climate_controlled": False},
            contract_overrides={"base_fee_cents": 100000, "sponsorship_credit_cents": 0},
            title="Wood",
            exhibit_code="WOOD-2026",
            declared_value_cents=100000,
        )
        # Stop at a non-climate-controlled venue computes supervision_required.
        assert stop["supervision_required"] is True
        res = api.transition_stop(tour["id"], stop["id"], {"action": "BEGIN_INSTALL"}, TM)
        validate_error(res, ApiErrorId.ERR_SUPERVISOR_REQUIRED)

    def test_assigning_supervisor_satisfies_gate(self, api):
        """PRD §3.2: "When `supervision_required` is true, a `TourManager` assigns
        an on-site installation supervisor through a dedicated assignment
        capability that records a `supervisor_user_id` — a registrar operator's
        id — against the stop and returns that `supervisor_user_id` together
        with the `tour_stop_id` it was attached to. This single act is what
        satisfies the supervision gate at installation time."

        Design: Corner/validations/supervisor_required_gate_enforced
        """
        tour, crates, venue, stop, contract, shipment = setup_install_ready_stop(
            venue_overrides={"name": "Barn", "climate_controlled": False},
            title="Wood",
            exhibit_code="WOOD-2026",
            declared_value_cents=100000,
        )
        assignment = validate_success(
            api.assign_supervisor(
                tour["id"], stop["id"], {"supervisor_user_id": "reg-operator-7"}, TM
            ),
            201,
        )
        assert assignment["supervisor_user_id"] == "reg-operator-7"
        assert assignment["tour_stop_id"] == stop["id"]
        res = api.transition_stop(tour["id"], stop["id"], {"action": "BEGIN_INSTALL"}, TM)
        installing = validate_success(res, 200)
        assert installing["status"] == "INSTALLING"
