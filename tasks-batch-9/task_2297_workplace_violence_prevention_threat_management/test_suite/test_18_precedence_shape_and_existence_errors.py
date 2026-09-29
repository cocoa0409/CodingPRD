"""Authentication ahead of existence, pagination bounds, the two existence tiers and a terminal replay."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    COMPLIANCE_AUDITOR_HEADERS,
    HEADERS_WITHOUT_ROLE,
    PROGRAM_ADMIN_HEADERS,
    UNRECOGNISED_ROLE_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_plan_metrics,
    assert_readiness,
    assert_total_count,
    build_drill,
    build_drill_execution,
    build_separation,
    read_employee,
    read_plan,
    setup_active_plan,
    setup_programme,
)

#: A recognised role that still omits the identifier only Anonymous may leave out.
SAFETY_OFFICER_HEADERS_WITHOUT_USER_ID = {
    "X-User-Role": "SafetyOfficer",
    "Content-Type": "application/json",
}


class TestUnauthenticatedOutranksExistence:
    """The header check is the first gate, so it answers even for identifiers that do not exist."""

    def test_three_broken_header_sets_all_answer_before_the_path_is_resolved(
        self, api: ApiClient
    ) -> None:
        """A missing role, an invented role and a missing identifier all return 401, never a 404.

        PRD: "A request that omits either header, or whose `X-User-Role` is not one of those ten strings, is rejected with `ERR_UNAUTHENTICATED` (401)."
        Design: Corner/errors/missing_x_user_role_header_returns_unauthenticated
        """
        ctx = setup_programme(api)
        before = get_success_data(
            api.get_worksite(ctx["worksite"]["id"], PROGRAM_ADMIN_HEADERS)
        )

        roleless = api.get_worksite(NON_EXISTENT_UUID, HEADERS_WITHOUT_ROLE)

        validate_error(roleless, ApiErrorId.UNAUTHENTICATED, 401)
        assert roleless.json()["data"]["error_id"] != ApiErrorId.WORKSITE_NOT_FOUND

        invented = api.get_worksite(NON_EXISTENT_UUID, UNRECOGNISED_ROLE_HEADERS)

        validate_error(invented, ApiErrorId.UNAUTHENTICATED, 401)
        assert invented.json()["data"]["error_id"] != ApiErrorId.WORKSITE_NOT_FOUND

        nameless = api.get_worksite(
            ctx["worksite"]["id"], SAFETY_OFFICER_HEADERS_WITHOUT_USER_ID
        )

        validate_error(nameless, ApiErrorId.UNAUTHENTICATED, 401)
        assert nameless.json()["data"]["error_id"] != ApiErrorId.UNAUTHORIZED
        assert_total_count(api.list_worksites(PROGRAM_ADMIN_HEADERS), 1)
        assert_total_count(
            api.list_employees(
                PROGRAM_ADMIN_HEADERS, {"worksite_id": ctx["worksite"]["id"]}
            ),
            11,
        )
        after = get_success_data(
            api.get_worksite(ctx["worksite"]["id"], PROGRAM_ADMIN_HEADERS)
        )
        assert after["version"] == before["version"]


class TestPaginationBounds:
    """Pagination is shape validation, so the bounds are checked without touching a row."""

    def test_the_three_out_of_range_pages_fail_and_the_inclusive_maximum_is_accepted(
        self, api: ApiClient
    ) -> None:
        """A limit of 101, a negative offset and a limit of 0 are all 400, while 100 returns everyone.

        PRD: "A `limit` outside the range 1 through 100, or a negative `offset`, is a request-shape error and is rejected with `ERR_INVALID_REQUEST` (400)."
        Design: Corner/errors/pagination_limit_above_one_hundred_returns_invalid_request
        """
        ctx = setup_programme(api)
        worksite_id = ctx["worksite"]["id"]

        validate_error(
            api.list_employees(PROGRAM_ADMIN_HEADERS, {"worksite_id": worksite_id, "limit": 101}),
            ApiErrorId.INVALID_REQUEST,
            400,
        )
        validate_error(
            api.list_employees(
                PROGRAM_ADMIN_HEADERS, {"worksite_id": worksite_id, "limit": 10, "offset": -1}
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )
        validate_error(
            api.list_employees(PROGRAM_ADMIN_HEADERS, {"worksite_id": worksite_id, "limit": 0}),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

        everyone, full_meta = validate_paginated(
            api.list_employees(PROGRAM_ADMIN_HEADERS, {"worksite_id": worksite_id, "limit": 100})
        )

        assert len(everyone) == 11
        assert full_meta["total_count"] == 11
        assert full_meta["limit"] == 100
        assert full_meta["offset"] == 0
        assert full_meta["has_more"] is False

        first_page, page_meta = validate_paginated(
            api.list_employees(PROGRAM_ADMIN_HEADERS, {"worksite_id": worksite_id})
        )

        assert len(first_page) == 10
        assert page_meta["total_count"] == 11
        assert page_meta["limit"] == 10
        assert page_meta["has_more"] is True


class TestTwoExistenceTiers:
    """A path identifier and a body foreign key report different codes on the same family."""

    def test_an_unknown_drill_in_the_path_and_an_unknown_plan_in_the_body_differ(
        self, api: ApiClient
    ) -> None:
        """Execute and read both answer for the drill, while the create answers for the plan it names.

        PRD: "Every templated identifier in the path resolves to an existing row, validated left to right — one of the thirteen not-found codes (404) listed in §2.6."
        Design: Corner/errors/unknown_drill_id_returns_drill_not_found
        """
        ctx = setup_active_plan(api)
        officer = ctx["headers"]["safety_officer"]

        validate_error(
            api.execute_drill(
                NON_EXISTENT_UUID, build_drill_execution(12, findings_count=1), officer
            ),
            ApiErrorId.DRILL_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_drill(
                build_drill(
                    NON_EXISTENT_UUID,
                    scenario_type="LOCKDOWN",
                    scheduled_at="2026-08-10T00:00:00Z",
                ),
                officer,
            ),
            ApiErrorId.PREVENTION_PLAN_NOT_FOUND,
            404,
        )
        validate_error(
            api.get_drill(NON_EXISTENT_UUID, COMPLIANCE_AUDITOR_HEADERS),
            ApiErrorId.DRILL_NOT_FOUND,
            404,
        )

        assert_total_count(api.list_drills(officer, {"plan_id": ctx["plan"]["id"]}), 0)
        plan = read_plan(api, ctx)
        assert_plan_metrics(plan, drills_completed_12mo=0)
        assert_readiness(plan, score=79.90, inspection_ready=True)


class TestSeparationIsTerminal:
    """The replayed offboarding is refused rather than absorbed, so the unwinding runs once."""

    def test_separating_the_same_worker_twice_reports_the_state_and_moves_nothing(
        self, api: ApiClient
    ) -> None:
        """The second call answers with the employee state code, not a not-found, and bumps no version.

        PRD: "An `HRPartner` separates a worker by supplying a `separation_reason`, moving `employment_status` from `ACTIVE` to `SEPARATED` and recording `separated_at` from the logical clock; separating someone already `SEPARATED` is rejected with `ERR_EMPLOYEE_INVALID_STATE`."
        Design: Corner/errors/separating_an_already_separated_employee_returns_employee_invalid_state
        """
        ctx = setup_programme(api)
        leaver_id = ctx["subj"]["id"]
        assert ctx["subj"]["employment_status"] == "ACTIVE"

        separated = get_success_data(
            api.separate_employee(
                leaver_id,
                build_separation(
                    separation_reason="Terminated following the threat assessment."
                ),
                ctx["headers"]["hr_partner"],
            )
        )

        assert separated["employment_status"] == "SEPARATED"
        assert separated["separated_at"] == "2026-08-01T00:00:00Z"

        replay = api.separate_employee(
            leaver_id,
            build_separation(separation_reason="Duplicate offboarding ticket."),
            ctx["headers"]["hr_partner"],
        )

        validate_error(replay, ApiErrorId.EMPLOYEE_INVALID_STATE, 409)
        assert replay.json()["data"]["error_id"] != ApiErrorId.EMPLOYEE_NOT_FOUND
        final = read_employee(api, leaver_id)
        assert final["version"] == separated["version"]
        assert final["employment_status"] == "SEPARATED"
        assert final["escort_committed_minutes"] == 0
        assert final["active_restriction_count"] == 0
