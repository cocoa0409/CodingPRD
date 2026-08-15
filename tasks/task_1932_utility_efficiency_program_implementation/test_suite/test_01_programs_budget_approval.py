"""Programs: creation shape, pagination, close guard, budget boundary,
program-active gating of project approval, and program-version OCC."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_program,
    create_active_program,
    create_program_payload,
    create_proposed_project,
    get_program,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProgramCreationAndListing:
    def test_program_create_returns_201_with_system_fields(self, api, pm_headers):
        """PRD 3.1: "New programs are born in `DRAFT`, with `committed_cents`,
        `paid_cents`, and `avoided_kwh_actual` all at zero."
        PRD 2.4: "`id`: a server-minted UUID, with no type prefix."

        Design: Corner/entities/program_create_returns_201_with_system_fields
        """
        resp = api.create_program(create_program_payload(code="P-C1"), pm_headers)
        data = validate_success(resp, expected_status=201)
        assert_program(data)
        assert data["status"] == "DRAFT"
        assert data["committed_cents"] == 0
        assert data["paid_cents"] == 0
        assert data["avoided_kwh_actual"] == 0

    def test_programs_list_pagination_defaults(self, api, pm_headers):
        """PRD 2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10, accepts a minimum of 1, and is capped at a maximum
        of 100. The `offset` parameter skips a number of items from the front
        of the result set and defaults to 0. Unless otherwise specified, every
        list endpoint returns its resources sorted by creation timestamp
        (`created_at`) in ascending order."

        Design: Corner/entities/programs_list_pagination_defaults
        """
        for code in ("P-L1", "P-L2", "P-L3"):
            resp = api.create_program(create_program_payload(code=code), pm_headers)
            validate_success(resp, expected_status=201)

        resp = api.list_programs(pm_headers)
        data, meta = validate_paginated(resp)
        assert len(data) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        created = [p["created_at"] for p in data]
        assert created == sorted(created), "list must be created_at ascending"

    def test_program_get_not_found(self, api, pm_headers):
        """PRD 2.6: "When the path-referenced resource does not exist, the
        request is rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/program_get_not_found
        """
        resp = api.get_program(NON_EXISTENT_UUID, pm_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestProgramCloseGuard:
    def test_program_close_with_open_projects_rejected(self, api, pm_headers):
        """PRD 3.1: "a program in `ACTIVE` or `SUSPENDED` may move to `CLOSED`,
        but only when none of its projects remains in flight — that is, when no
        project of the program sits in `PROPOSED`, `APPROVED`, `SCHEDULED`,
        `INSTALLED`, `INSPECTING`, or `REMEDIATION`. A close requested while
        such projects exist is rejected with `ERR_PROGRAM_HAS_OPEN_PROJECTS`."

        Design: Corner/validations/program_close_with_open_projects_rejected
        """
        ctx = create_proposed_project()
        resp = api.close_program(ctx["program"]["id"], pm_headers)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_HAS_OPEN_PROJECTS)


class TestApproveFromTerminalState:
    def test_approve_project_from_completed_returns_invalid_state(self, api, pm_headers):
        """PRD 3.4: "First the project must be `PROPOSED` (any other state
        draws `ERR_INVALID_STATE`)."
        The project here sits in `CANCELLED`, a terminal state.

        Design: Corner/state_machines/approve_project_from_completed_returns_invalid_state
        """
        set_clock()
        ctx = create_proposed_project()
        validate_success(api.cancel_project(ctx["project"]["id"], pm_headers), 200)
        version = get_program(ctx["program"]["id"])["version"]
        resp = api.approve_project(ctx["project"]["id"], version, pm_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestBudgetExactBoundary:
    def test_approve_succeeds_when_commitment_equals_budget(self, api, pm_headers):
        """PRD 3.4: "the program's `committed_cents` plus this project's
        provisional incentive must not exceed the program's `budget_cents`, or
        the approval dies with `ERR_BUDGET_EXCEEDED`."
        PRD 3.4: "the first 2,000 kWh of annual savings earns 25 cents per kWh,
        and any savings above 2,000 kWh earns 12 cents per kWh; the two portions
        are summed, the total is clamped so it never exceeds 80,000 cents, and
        the provisional figure is floored to whole cents."
        (100 kWh * 25 cents = 2500 == budget 2500: at equality it does not
        exceed, so approval succeeds.)

        Design: Difficulty/boundary_precision_check/budget_exact_boundary
        """
        set_clock()
        ctx = create_proposed_project(
            program_overrides={"budget_cents": 2500},
            lead_overrides={"estimated_annual_kwh_savings": 100},
            project_overrides={"estimated_annual_kwh_savings": 100},
        )
        version = get_program(ctx["program"]["id"])["version"]
        resp = api.approve_project(ctx["project"]["id"], version, pm_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "APPROVED"
        assert data["incentive_amount_provisional_cents"] == 2500

    def test_approve_rejected_one_cent_over_budget(self, api, pm_headers):
        """PRD 3.4: "the program's `committed_cents` plus this project's
        provisional incentive must not exceed the program's `budget_cents`, or
        the approval dies with `ERR_BUDGET_EXCEEDED`."
        (100 kWh * 25 cents = 2500 > budget 2499: exceeds by one cent.)

        Design: Difficulty/boundary_precision_check/budget_exact_boundary
        """
        set_clock()
        ctx = create_proposed_project(
            program_overrides={"budget_cents": 2499},
            lead_overrides={"estimated_annual_kwh_savings": 100},
            project_overrides={"estimated_annual_kwh_savings": 100},
        )
        version = get_program(ctx["program"]["id"])["version"]
        resp = api.approve_project(ctx["project"]["id"], version, pm_headers)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)


class TestStateVsFiscalOnApprove:
    def test_approve_cancelled_project_with_blown_budget_returns_invalid_state(self, api, pm_headers):
        """PRD 2.6: "Path-existence resolution follows, then body foreign-key
        resolution, then state-transition validity — a transition requested
        from a state that does not permit it is rejected with
        `ERR_INVALID_STATE` (HTTP 409)."
        PRD 2.6: "Business rules run last, in their documented priority"
        — the fiscal budget-headroom rule is one of those late business rules,
        so the earlier state check must mask it.
        PRD 3.4: "First the project must be `PROPOSED` (any other state draws
        `ERR_INVALID_STATE`)."
        The project is CANCELLED (terminal) AND the budget is blown; the state
        error must surface.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_approve
        """
        set_clock()
        ctx = create_proposed_project(
            program_overrides={"budget_cents": 1},
            lead_overrides={"estimated_annual_kwh_savings": 100},
            project_overrides={"estimated_annual_kwh_savings": 100},
        )
        cancel = api.cancel_project(ctx["project"]["id"], pm_headers)
        validate_success(cancel, expected_status=200)
        version = get_program(ctx["program"]["id"])["version"]
        resp = api.approve_project(ctx["project"]["id"], version, pm_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_approve_proposed_project_with_blown_budget_returns_budget_exceeded(self, api, pm_headers):
        """PRD 3.4: "Finally comes the fiscal check: the program's
        `committed_cents` plus this project's provisional incentive must not
        exceed the program's `budget_cents`, or the approval dies with
        `ERR_BUDGET_EXCEEDED`."
        With the project validly PROPOSED (state check passes), the fiscal
        rule is the one that fires.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_approve
        """
        set_clock()
        ctx = create_proposed_project(
            program_overrides={"budget_cents": 1},
            lead_overrides={"estimated_annual_kwh_savings": 100},
            project_overrides={"estimated_annual_kwh_savings": 100},
        )
        version = get_program(ctx["program"]["id"])["version"]
        resp = api.approve_project(ctx["project"]["id"], version, pm_headers)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)


class TestProjectApproveRequiresProgramActive:
    def test_approve_rejected_when_program_suspended(self, api, pm_headers):
        """PRD 3.1: "Any operation requiring an active program — creating a
        lead, distributing a lead, approving a project — is rejected with
        `ERR_PROGRAM_NOT_ACTIVE` whenever the program is not `ACTIVE`, whether
        it sits in `DRAFT`, `SUSPENDED`, or `CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/project_approve_requires_program_active
        """
        ctx = create_proposed_project()
        validate_success(api.suspend_program(ctx["program"]["id"], pm_headers), 200)
        version = get_program(ctx["program"]["id"])["version"]
        resp = api.approve_project(ctx["project"]["id"], version, pm_headers)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)
        project = validate_success(api.get_project(ctx["project"]["id"], pm_headers))
        assert project["status"] == "PROPOSED"

    def test_rejected_approval_leaves_no_budget_footprint(self, api, pm_headers):
        """PRD 3.1: "Any operation requiring an active program — creating a
        lead, distributing a lead, approving a project — is rejected with
        `ERR_PROGRAM_NOT_ACTIVE` whenever the program is not `ACTIVE`, whether
        it sits in `DRAFT`, `SUSPENDED`, or `CLOSED`."
        PRD 3.4: "The program's `committed_cents` grows by the incentive amount
        and the program's `version` increments." — those are effects of a
        successful approval only; a rejected approval must not commit budget.

        Design: Difficulty/cross_entity_state_dependency/project_approve_requires_program_active
        """
        ctx = create_proposed_project()
        validate_success(api.suspend_program(ctx["program"]["id"], pm_headers), 200)
        before = get_program(ctx["program"]["id"])
        version = before["version"]
        resp = api.approve_project(ctx["project"]["id"], version, pm_headers)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACTIVE)
        after = get_program(ctx["program"]["id"])
        assert after["committed_cents"] == 0
        assert after["version"] == before["version"]
        payments = validate_success(
            api.list_incentive_payments(pm_headers,
                                        params={"project_id": ctx["project"]["id"]}))
        assert payments == [], "no payment shell may be created by a rejected approval"


class TestStaleProgramVersionOcc:
    def test_approve_with_stale_program_version_rejected(self, api, pm_headers):
        """PRD 2.7: "`POST /efficiency/projects/{project_id}/approve` requires
        the request to carry `expected_program_version`, holding the target
        program's `version` as the client last observed it. When the program's
        current `version` differs — because, for instance, another approval has
        since committed budget against the same program and the client's view
        of `committed_cents` is stale — the request is rejected with
        `ERR_STALE_PROGRAM_VERSION` (HTTP 412), so a budget check is never
        evaluated against a baseline the client never saw."

        Design: Corner/errors/err_stale_program_version_triggered
        """
        set_clock()
        program = create_active_program()
        observed_version = program["version"]

        ctx1 = create_proposed_project(program_id=program["id"])
        first = api.approve_project(ctx1["project"]["id"], observed_version, pm_headers)
        validate_success(first, expected_status=200)

        ctx2 = create_proposed_project(program_id=program["id"])
        # The first approval advanced the program's version (PRD 3.4), so the
        # previously observed version is now stale.
        resp = api.approve_project(ctx2["project"]["id"], observed_version, pm_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_PROGRAM_VERSION)
