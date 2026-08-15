"""Trade-ally network: enrollment defaults, state machine (including the
ACTIVE↔SUSPENDED cycle), termination guards, uniqueness, and the
performance-score standing boundary."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_trade_ally,
    build_submitted_application,
    create_active_ally,
    create_ally,
    create_open_program,
    create_trade_ally_payload,
    drive_inspection_history,
    get_trade_ally,
    validate_error,
    validate_success,
)


class TestTradeAllyEnrollment:
    def test_creation_assigns_default_score_and_tier(self, api, admin_headers):
        """PRD §3.2: "A new ally starts with `enroll_status` `PENDING`,
        `performance_score` 100, `standing_tier` `STANDARD`, and `version` 1."

        Design: Corner/entities/trade_ally_creation_assigns_default_score_and_tier
        """
        res = api.create_trade_ally(
            create_trade_ally_payload(ally_name="Acme", license_number="LIC-001"),
            admin_headers,
        )
        ally = validate_success(res, 201)
        assert_trade_ally(ally)
        assert ally["enroll_status"] == "PENDING"
        assert ally["performance_score"] == 100
        assert ally["standing_tier"] == "STANDARD"
        assert ally["version"] == 1

    def test_initial_state_is_pending(self, api, admin_headers):
        """PRD §3.2: "A new ally starts with `enroll_status` `PENDING`,
        `performance_score` 100, `standing_tier` `STANDARD`, and `version` 1."

        Design: Corner/state_machines/trade_ally_initial_state_is_pending
        """
        ally = create_ally()
        assert ally["enroll_status"] == "PENDING"

    def test_not_found_returns_404(self, api, admin_headers):
        """PRD §2.9: "Third, every identifier in the request path must resolve
        to an existing resource of the appropriate type, yielding the
        resource-specific not-found error: `ERR_PROGRAM_YEAR_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_ALLY_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`"
        PRD §2.9: "(all HTTP 404)"

        Design: Corner/entities/trade_ally_not_found_returns_404
        """
        res = api.get_trade_ally(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_ALLY_NOT_FOUND, expected_status=404)

    def test_duplicate_license_number_returns_error(self, api, admin_headers):
        """PRD §3.2: "Contractors join the network when a `ProgramAdministrator`
        enrolls them with an `ally_name` and a state-issued `license_number`
        (unique across the network; duplicates yield
        `ERR_DUPLICATE_UNIQUE_FIELD`)."

        Design: Corner/validations/trade_ally_duplicate_license_number_returns_error
        """
        create_ally(license_number="LIC-001")
        res = api.create_trade_ally(
            create_trade_ally_payload(ally_name="AcmeClone", license_number="LIC-001"),
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_UNIQUE_FIELD, expected_status=409)


class TestTradeAllyStateMachine:
    def test_terminate_from_pending_returns_invalid_state(self, api, admin_headers):
        """PRD §3.2: "Each of these transitions requires the matching current
        state — a mismatched call yields `ERR_INVALID_STATE` — and increments
        the ally's `version`. Termination from `ACTIVE` carries one further
        guard, evaluated after the state check"
        PRD §3.2: "Termination from `SUSPENDED` requires only the state
        precondition."

        Design: Corner/state_machines/trade_ally_terminate_from_pending_returns_invalid_state
        """
        ally = create_ally()
        assert ally["enroll_status"] == "PENDING"
        res = api.terminate_trade_ally(ally["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_terminated_is_terminal(self, api, admin_headers):
        """PRD §3.2: "termination is the terminal `TERMINATED` state. Each of
        these transitions requires the matching current state — a mismatched
        call yields `ERR_INVALID_STATE` — and increments the ally's `version`."

        Design: Corner/state_machines/trade_ally_terminated_is_terminal
        """
        ally = create_active_ally()
        ally = validate_success(api.terminate_trade_ally(ally["id"], admin_headers), 200)
        assert ally["enroll_status"] == "TERMINATED"

        for trigger in (
            api.activate_trade_ally,
            api.suspend_trade_ally,
            api.reinstate_trade_ally,
            api.terminate_trade_ally,
        ):
            res = trigger(ally["id"], admin_headers)
            validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_terminate_with_open_applications_returns_error(self, api, admin_headers):
        """PRD §3.2: "Termination from `ACTIVE` carries one further guard,
        evaluated after the state check: it is refused with
        `ERR_ALLY_HAS_OPEN_APPLICATIONS` (HTTP 409) while the ally still has any
        application in `DRAFT`, `SUBMITTED`, `PRE_INSPECTION`,
        `POST_INSPECTION`, or `VERIFIED`."

        Design: Corner/validations/terminate_ally_with_open_applications_returns_error
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        build_submitted_application(py, ally, measures[0])

        res = api.terminate_trade_ally(ally["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_ALLY_HAS_OPEN_APPLICATIONS, expected_status=409)


class TestTradeAllySuspendReinstateCycle:
    def test_two_suspend_reinstate_loops_return_to_active(self, api, admin_headers):
        """PRD §3.2: "suspension moves `ACTIVE` → `SUSPENDED`; reinstatement
        returns `SUSPENDED` → `ACTIVE`"

        Design: Difficulty/non_linear_state_machine/trade_ally_suspend_reinstate_cycle
        """
        ally = create_active_ally()
        for _ in range(2):
            ally = validate_success(api.suspend_trade_ally(ally["id"], admin_headers), 200)
            assert ally["enroll_status"] == "SUSPENDED"
            ally = validate_success(api.reinstate_trade_ally(ally["id"], admin_headers), 200)
            assert ally["enroll_status"] == "ACTIVE"

        final = get_trade_ally(ally["id"])
        assert final["enroll_status"] == "ACTIVE"

    def test_each_transition_increments_version(self, api, admin_headers):
        """PRD §3.2: "Activation moves `PENDING` → `ACTIVE`; suspension moves
        `ACTIVE` → `SUSPENDED`; reinstatement returns `SUSPENDED` → `ACTIVE`;
        termination is the terminal `TERMINATED` state. Each of these
        transitions requires the matching current state — a mismatched call
        yields `ERR_INVALID_STATE` — and increments the ally's `version`."

        Design: Difficulty/non_linear_state_machine/trade_ally_suspend_reinstate_cycle
        """
        ally = create_ally()
        assert ally["version"] == 1

        ally = validate_success(api.activate_trade_ally(ally["id"], admin_headers), 200)
        assert ally["version"] == 2
        ally = validate_success(api.suspend_trade_ally(ally["id"], admin_headers), 200)
        assert ally["version"] == 3
        ally = validate_success(api.reinstate_trade_ally(ally["id"], admin_headers), 200)
        assert ally["version"] == 4
        ally = validate_success(api.suspend_trade_ally(ally["id"], admin_headers), 200)
        assert ally["version"] == 5
        ally = validate_success(api.reinstate_trade_ally(ally["id"], admin_headers), 200)
        assert ally["version"] == 6
        assert ally["enroll_status"] == "ACTIVE"


class TestTradeAllyPerformanceBoundary:
    def test_exactly_90_is_preferred(self, api, admin_headers):
        """PRD §3.2: "Whenever an inspection is completed — pass or fail, pre-
        or post-installation — the installing ally's `performance_score` is
        recomputed across every completed inspection belonging to that ally's
        applications, in any program year: one hundred times the number of
        `PASSED` inspections divided by the number of completed inspections
        (those `PASSED` or `FAILED`), rounded half-up to a whole number."
        PRD §3.2: "`PREFERRED` at ninety or above, `STANDARD` at seventy or
        above, and `PROBATION` below seventy."

        Design: Difficulty/boundary_precision_check/ally_performance_tier_exact_90_preferred
        """
        py, measures = create_open_program(
            budget_cap_cents=1_000_000_000,
            measure_specs=[{"base_rate_cents": 100, "deemed_kwh_per_unit": 10_001}],
        )
        ally = create_active_ally()
        drive_inspection_history(
            py, ally, measures[0], ["PASSED"] * 9 + ["FAILED"]
        )

        ally = get_trade_ally(ally["id"])
        # 9 PASSED of 10 completed -> round_half_up(90.0) == 90 -> PREFERRED.
        assert ally["performance_score"] == 90
        assert ally["standing_tier"] == "PREFERRED"

    def test_89_is_standard_not_preferred(self, api, admin_headers):
        """PRD §3.2: "one hundred times the number of `PASSED` inspections
        divided by the number of completed inspections (those `PASSED` or
        `FAILED`), rounded half-up to a whole number."
        PRD §3.2: "`PREFERRED` at ninety or above, `STANDARD` at seventy or
        above, and `PROBATION` below seventy."

        Design: Difficulty/boundary_precision_check/ally_performance_tier_exact_90_preferred
        """
        py, measures = create_open_program(
            budget_cap_cents=1_000_000_000,
            measure_specs=[{"base_rate_cents": 100, "deemed_kwh_per_unit": 10_001}],
        )
        ally = create_active_ally()
        drive_inspection_history(
            py, ally, measures[0], ["PASSED"] * 8 + ["FAILED"]
        )

        ally = get_trade_ally(ally["id"])
        # 8 PASSED of 9 completed -> round_half_up(88.88..) == 89 -> STANDARD.
        assert ally["performance_score"] == 89
        assert ally["standing_tier"] == "STANDARD"
