"""Program-year lifecycle: creation defaults, retrieval, pagination, catalog
gate at open, terminal REPORTED lockdown, optimistic concurrency."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_program_ledger_invariants,
    assert_program_year,
    build_reported_program,
    build_submitted_application,
    create_active_ally,
    create_open_program,
    create_program_year,
    create_program_year_payload,
    get_program_year,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProgramYearCreation:
    def test_creation_assigns_defaults(self, api, admin_headers):
        """PRD §3.1: "The year starts in `DRAFT` with every derived counter at
        zero and `version` 1."

        Design: Corner/entities/program_year_creation_assigns_defaults
        """
        res = api.create_program_year(
            create_program_year_payload(
                program_code="RES-2026", budget_cap_cents=5_000_000,
                savings_goal_kwh=100_000,
            ),
            admin_headers,
        )
        py = validate_success(res, 201)
        assert_program_year(py)
        assert py["status"] == "DRAFT"
        assert py["committed_cents"] == 0
        assert py["paid_cents"] == 0
        assert py["reported_kwh"] == 0
        assert py["adjusted_kwh"] == 0
        assert py["goal_attainment_pct"] == 0
        assert py["version"] == 1
        assert_program_ledger_invariants(py)

    def test_get_by_id_returns_stored_entity(self, api, admin_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/entities/program_year_get_by_id_returns_stored_entity
        """
        py = create_program_year(
            program_code="RES-2026", budget_cap_cents=5_000_000,
            savings_goal_kwh=100_000,
        )
        res = api.get_program_year(py["id"], admin_headers)
        fetched = validate_success(res, 200)
        assert_program_year(fetched)
        assert fetched["id"] == py["id"]
        assert fetched["program_code"] == "RES-2026"
        assert fetched["budget_cap_cents"] == 5_000_000

    def test_not_found_returns_404(self, api, admin_headers):
        """PRD §2.9: "Third, every identifier in the request path must resolve
        to an existing resource of the appropriate type, yielding the
        resource-specific not-found error: `ERR_PROGRAM_YEAR_NOT_FOUND`"
        PRD §2.9: "(all HTTP 404)"

        Design: Corner/entities/program_year_not_found_returns_404
        """
        res = api.get_program_year(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_PROGRAM_YEAR_NOT_FOUND, expected_status=404)

    def test_list_pagination(self, api, admin_headers):
        """PRD §2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/program_year_list_pagination
        """
        for _ in range(3):
            create_program_year()

        data, meta = validate_paginated(
            api.list_program_years(admin_headers, params={"limit": 2, "offset": 0})
        )
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["has_more"] is True

        data, meta = validate_paginated(
            api.list_program_years(admin_headers, params={"limit": 2, "offset": 2})
        )
        assert len(data) == 1
        assert meta["has_more"] is False

    def test_missing_required_field_returns_400(self, api, admin_headers):
        """PRD §2.9: "Independent of this ordering, a structurally malformed
        request — a missing required field, a wrong-typed value, or an
        out-of-range scalar — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/program_year_missing_required_field_returns_400
        """
        payload = create_program_year_payload(program_code="P1")
        del payload["budget_cap_cents"]
        res = api.create_program_year(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_duplicate_program_code_returns_error(self, api, admin_headers):
        """PRD §3.1: "A duplicate `program_code` is refused with
        `ERR_DUPLICATE_UNIQUE_FIELD` (HTTP 409)."

        Design: Corner/validations/program_year_duplicate_program_code_returns_error
        """
        create_program_year(program_code="P1")
        res = api.create_program_year(
            create_program_year_payload(program_code="P1"), admin_headers
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_UNIQUE_FIELD, expected_status=409)


class TestProgramYearOpenCloseReport:
    def test_open_with_no_active_measures_returns_error(self, api, admin_headers):
        """PRD §3.1: "Opening the year — the `DRAFT` → `OPEN` transition,
        performed by a `ProgramAdministrator` — requires a non-empty active
        catalog, and its checks run in a fixed order: the state check first (a
        year not in `DRAFT` yields `ERR_INVALID_STATE`), then the catalog check
        (no active measure yields `ERR_NO_ACTIVE_MEASURES`, HTTP 422)."

        Design: Corner/validations/open_program_with_no_active_measures_returns_error
        """
        py = create_program_year()
        res = api.open_program_year(py["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_MEASURES, expected_status=422)

    def test_open_twice_returns_invalid_state(self, api, admin_headers):
        """PRD §3.1: "Opening the year — the `DRAFT` → `OPEN` transition,
        performed by a `ProgramAdministrator` — requires a non-empty active
        catalog, and its checks run in a fixed order: the state check first (a
        year not in `DRAFT` yields `ERR_INVALID_STATE`), then the catalog check
        (no active measure yields `ERR_NO_ACTIVE_MEASURES`, HTTP 422)."

        Design: Corner/state_machines/program_year_open_twice_returns_invalid_state
        """
        py, _measures = create_open_program()
        assert py["status"] == "OPEN"
        res = api.open_program_year(py["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_reported_is_terminal(self, api, admin_headers):
        """PRD §3.7: "`REPORTED` is terminal, and the year's counters thereafter
        stand as the regulatory record."
        PRD §3.7: "Closing requires the `OPEN` state — the state check runs
        first — and a quiet pipeline: no application of the year may remain in
        `SUBMITTED`, `PRE_INSPECTION`, `POST_INSPECTION`, or `VERIFIED`, or the
        close is refused with `ERR_OPEN_APPLICATIONS_REMAIN` (HTTP 409)."

        Design: Corner/state_machines/program_year_reported_is_terminal
        """
        py, _adj, _app = build_reported_program()
        assert py["status"] == "REPORTED"
        res = api.close_program_year(py["id"], admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestProgramYearOptimisticConcurrency:
    def test_stale_version_rejected_after_config_edit(self, api, admin_headers):
        """PRD §2.8: "If the server-side `version` has since advanced, whether
        by a prior configuration edit or by any of the ledger cascades described
        in §2.6, the update is rejected as stale with `ERR_STALE_VERSION` (HTTP
        412), preventing the client from overwriting a configuration it has not
        observed."

        Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_version_rejected
        """
        py = create_program_year(budget_cap_cents=1_000_000)
        observed_version = py["version"]
        assert observed_version == 1

        first = validate_success(
            api.update_program_year(
                py["id"],
                {"expected_program_year_version": observed_version,
                 "budget_cap_cents": 2_000_000},
                admin_headers,
            ),
            200,
        )
        assert first["version"] == 2
        assert first["budget_cap_cents"] == 2_000_000

        res = api.update_program_year(
            py["id"],
            {"expected_program_year_version": observed_version,
             "savings_goal_kwh": 9999},
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        # Failed update must not have taken effect.
        after = get_program_year(py["id"])
        assert after["savings_goal_kwh"] != 9999

    def test_stale_version_rejected_after_ledger_cascade(self, api, admin_headers):
        """PRD §2.6: "Cascades that touch these counters are first-class
        mutations of the program-year resource: each one refreshes `updated_at`
        and increments the program year's `version` by one. A client holding a
        previously observed version will therefore be refused a configuration
        update (§2.8) even when the version advanced because of activity on a
        child application rather than a direct edit."

        Design: Corner/cross_cutting_layers/optimistic_concurrency_stale_version_rejected
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        # open bumped the year to version 2; capture it, then let a child
        # application submission cascade the version further.
        py_now = get_program_year(py["id"])
        cascade_base_version = py_now["version"]
        build_submitted_application(py, ally, measures[0])

        res = api.update_program_year(
            py["id"],
            {"expected_program_year_version": cascade_base_version,
             "budget_cap_cents": 999_999_999},
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
