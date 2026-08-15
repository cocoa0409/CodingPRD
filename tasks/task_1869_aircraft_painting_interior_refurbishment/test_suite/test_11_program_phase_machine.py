"""Program phase machine: advances, cancels, cascades (PRD §3.1, §3.5)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    advance_program,
    create_engagement,
    get_program,
    set_logical_clock,
    setup_booked_program,
    setup_inducted_program,
    validate_error,
    validate_success,
)

_PM = TEST_USERS["program_manager_headers"]
_ADMIN = TEST_USERS["center_admin_headers"]


class TestInductionCascade:
    def test_aircraft_enters_refurb_on_induction(self, api):
        """PRD §3.5: "Induction is the moment the aircraft physically enters
        the center's custody, so the aircraft cascades from `IN_SERVICE` or
        `RETURNED` to `IN_REFURB`."

        Design: Corner/state_machines/aircraft_cascade_on_induction
        """
        ctx = setup_booked_program()
        validate_success(api.activate_hangar_slot(ctx["slot"]["id"], _PM))
        advance_program(ctx["program"]["id"], "INDUCTED")

        aircraft = validate_success(api.get_aircraft(ctx["aircraft"]["id"], _PM))
        assert aircraft["status"] == "IN_REFURB"


class TestProgramCancel:
    def test_cancel_cascades_to_booked_slots(self, api):
        """PRD §3.1: "cancellation cascades downward, cancelling every `BOOKED`
        or `ACTIVE` hangar slot of the program (from `QUOTED`, only `BOOKED`
        slots exist to cancel), and cancelling from `INDUCTED` additionally
        returns the aircraft to `RETURNED`."

        Design: Corner/state_machines/program_cancel_cascades_to_slots
        """
        ctx = setup_booked_program()
        cancelled = validate_success(api.cancel_program(ctx["program"]["id"], _PM))
        assert cancelled["status"] == "CANCELLED"

        slot = validate_success(api.get_hangar_slot(ctx["slot"]["id"], _PM))
        assert slot["status"] == "CANCELLED"

    def test_cancelled_program_is_terminal(self, api):
        """PRD §3.1: "From `QUOTED`, `BOOKED`, or `INDUCTED` a program may be
        cancelled outright". PRD §2.10: "**State validity** — the entity is in a
        valid from-state for the requested transition, including terminal
        lockdown (`ERR_INVALID_STATE`, 409)".

        Design: Corner/state_machines/cancelled_program_is_terminal
        """
        ctx = create_engagement()
        cancelled = validate_success(api.cancel_program(ctx["program"]["id"], _PM))
        assert cancelled["status"] == "CANCELLED"

        resp = api.advance_program(ctx["program"]["id"], {"to_phase": "BOOKED"}, _PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSurfaceReviewGate:
    def test_surface_review_requires_assessment(self, api, program_manager_headers):
        """PRD §3.5: "From `INDUCTED` to `SURFACE_REVIEW`: a surface assessment
        for the program must exist in `PENDING` or `DECIDED` status
        (`ERR_ASSESSMENT_REQUIRED`)."

        Design: Corner/errors/surface_review_requires_assessment
        """
        ctx = setup_inducted_program()  # no assessment created
        resp = api.advance_program(
            ctx["program"]["id"], {"to_phase": "SURFACE_REVIEW"}, program_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_REQUIRED)


class TestAdvanceExistenceAndPriority:
    def test_advance_nonexistent_program_returns_not_found(self, api,
                                                           program_manager_headers):
        """PRD §2.8: "When an endpoint path contains resource identifiers, the
        system validates the existence of each identifier in sequential,
        left-to-right order, rejecting with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not correspond to an existing resource." —
        path existence (§2.10 item 4) precedes state validity (item 7).

        Design: Corner/validations/existence_precedes_state_on_advance
        """
        resp = api.advance_program(
            NON_EXISTENT_UUID, {"to_phase": "BOOKED"}, program_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_state_error_precedes_credit_hold_on_advance(self, api, program_manager_headers):
        """PRD §2.10: "Incoming requests are validated in a fixed priority
        order, so that the error a caller receives is always the
        highest-priority failure present rather than an arbitrary one." —
        state validity (item 7, `ERR_INVALID_STATE`) precedes fiscal rules
        (item 12, `ERR_CREDIT_HOLD`). PRD §3.5 declares no QUOTED -> IN_WORK
        edge; the nearest gates are stated per advance.

        Design: Difficulty/priority_pair_validation_conflict/advance_state_vs_fiscal_conflict
        """
        ctx = create_engagement()
        validate_success(
            api.set_customer_credit_status(
                ctx["customer"]["id"], {"credit_status": "CREDIT_HOLD"}, _ADMIN
            )
        )
        resp = api.advance_program(
            ctx["program"]["id"], {"to_phase": "IN_WORK"}, program_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_advance_leaves_program_phase_unchanged(self, api,
                                                             program_manager_headers):
        """PRD §2.7: "All mutations and their cascades are atomic within the
        request: the system never persists a partial application." The rejected
        QUOTED -> IN_WORK advance (state error outranking the fiscal hold per
        §2.10) must leave the program untouched.

        Design: Difficulty/priority_pair_validation_conflict/advance_state_vs_fiscal_conflict
        """
        ctx = create_engagement()
        validate_success(
            api.set_customer_credit_status(
                ctx["customer"]["id"], {"credit_status": "CREDIT_HOLD"}, _ADMIN
            )
        )
        v0 = get_program(ctx["program"]["id"])["version"]
        resp = api.advance_program(
            ctx["program"]["id"], {"to_phase": "IN_WORK"}, program_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        program = get_program(ctx["program"]["id"])
        assert program["status"] == "QUOTED"
        assert program["version"] == v0
