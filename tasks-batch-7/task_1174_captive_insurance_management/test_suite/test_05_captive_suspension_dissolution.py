"""Captive suspension cascades and dissolution terminal lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_captive,
    get_captive,
    setup_active_captive_with_program,
    setup_dissolved_captive,
    setup_suspendable_captive_with_active_program,
    validate_error,
    validate_success,
    GOVERNANCE_SUSPENSION_THRESHOLD,
)


class TestSuspensionCascade:

    def test_suspension_cascades_to_programs_and_fronting(
        self, api, domicile_regulator_headers, underwriter_headers
    ):
        """PRD §3.2: "Suspension transitions the captive `ACTIVE → SUSPENDED`,
        cascades every `IN_FORCE` program to `RUN_OFF`, and cascades every
        `ACTIVE` `FrontingArrangement` to `TERMINATED`."
        PRD §3.2: "A `DomicileRegulator` may suspend an `ACTIVE` captive when
        either its `solvency_status` is `BREACH` or its `governance_score` has
        fallen below `40`." — here the governance ground is established through
        five tax-position challenges (PRD §2.9: "a tax-position challenge
        decrements it by `15`"), taking the score from 100 to 25.

        Design: Difficulty/transitive_cascade/captive_suspension_cascades_to_programs_and_fronting
        """
        ctx = setup_suspendable_captive_with_active_program(fronting_required=True)
        captive = ctx["captive"]
        program = ctx["program"]
        fronting = ctx["fronting"]
        assert program["program_status"] == "IN_FORCE"
        assert fronting["status"] == "ACTIVE"
        assert captive["governance_score"] < GOVERNANCE_SUSPENSION_THRESHOLD

        suspended = validate_success(
            api.suspend_captive(captive["id"], domicile_regulator_headers)
        )
        assert_captive(suspended)
        assert suspended["status"] == "SUSPENDED"

        program_after = validate_success(
            api.get_program(captive["id"], program["id"], underwriter_headers)
        )
        assert program_after["program_status"] == "RUN_OFF", (
            f"IN_FORCE program must cascade to RUN_OFF on suspension, "
            f"got {program_after['program_status']}"
        )
        fronting_after = validate_success(
            api.get_fronting(captive["id"], program["id"], fronting["id"], underwriter_headers)
        )
        assert fronting_after["status"] == "TERMINATED", (
            f"ACTIVE fronting arrangement must cascade to TERMINATED on suspension, "
            f"got {fronting_after['status']}"
        )

    def test_suspension_without_grounds_rejected(
        self, api, domicile_regulator_headers
    ):
        """PRD §3.2: "Suspension from any other state is rejected with
        `ERR_CAPTIVE_NOT_ACTIVE`, and suspension without either ground is rejected
        with `ERR_NO_SUSPENSION_GROUNDS` (HTTP 400)." — a freshly activated
        captive kept its `governance_score` of 100 and had no solvency breach at
        activation time, so neither ground exists.

        Design: Difficulty/transitive_cascade/captive_suspension_cascades_to_programs_and_fronting
        """
        captive, program, _fronting = setup_active_captive_with_program()
        assert captive["status"] == "ACTIVE"
        assert get_captive(captive["id"])["governance_score"] == 100
        resp = api.suspend_captive(captive["id"], domicile_regulator_headers)
        validate_error(resp, ApiErrorId.ERR_NO_SUSPENSION_GROUNDS)


class TestDissolutionTerminalState:

    def test_captive_terminal_dissolved_no_transitions(self, api, captive_manager_headers):
        """PRD §3.2: "Both branches transition the captive to `DISSOLVED`, cascade
        all remaining programs to `CLOSED`, and cascade all collateral postings to
        `RELEASED`."
        PRD §3.2: "Activation transitions the captive `CAPITALIZED → ACTIVE`;
        attempting it while the captive is not `CAPITALIZED` is rejected with
        `ERR_CAPTIVE_NOT_CAPITALIZED`" — a dissolved captive is not `CAPITALIZED`,
        so re-activation is rejected.

        Design: Corner/state_machines/captive_terminal_dissolved_no_transitions
        """
        captive = setup_dissolved_captive()
        assert captive["status"] == "DISSOLVED"
        resp = api.activate_captive(captive["id"], captive_manager_headers)
        validate_error(resp, ApiErrorId.ERR_CAPTIVE_NOT_CAPITALIZED)
