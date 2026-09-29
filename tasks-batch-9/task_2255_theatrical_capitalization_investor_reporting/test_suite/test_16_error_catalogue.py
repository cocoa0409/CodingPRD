"""
The error catalogue: one code per entity, one code per gate.

The point of these is discrimination. A refusal must name the entity or the gate
it came from, not fall back on a shared generic code, and the earliest gate in
the fixed order must win even when several rules would have refused the request.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
)

from test_helpers import (
    COMPTROLLER_HEADERS,
    COMPTROLLER_USER_ID,
    COUNSEL_HEADERS,
    GM_HEADERS,
    PRODUCER_HEADERS,
    UNKNOWN_UUID,
    ApiClient,
    ApiErrorId,
    assert_envelope,
    assert_no_write,
    factories,
    fixtures,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
)


class TestRepeatedTerminalActions:
    """Six repeat actions, six sibling 409s, each naming its own entity."""

    def test_each_already_settled_row_reports_its_own_invalid_state_code(
        self, api: ApiClient
    ):
        """Income, distribution, budget, line, wrap and notice answer for themselves.

        "Beyond the production file, the system carries a state field on the
        offering document (`DRAFT`, `EFFECTIVE`, `EXPIRED`, `WITHDRAWN`, with
        `EXPIRED` and `WITHDRAWN` terminal), the investor's accreditation
        determination (`UNVERIFIED`, `ACCREDITED`, `NON_ACCREDITED`, freely
        re-determinable in either direction), the subscription (`SUBMITTED`,
        `RETURNED_FOR_CURE`, `ACCEPTED`, `REJECTED`, `RESCINDED`, with `REJECTED`
        and `RESCINDED` terminal), the operating budget (`DRAFT`, `ACTIVE`,
        `SUPERSEDED`, with `SUPERSEDED` terminal), the budget line's commitment
        (`PLANNED`, `COMMITTED`, `SPENT`, with `SPENT` terminal), the royalty
        participation (`ACTIVE`, `TERMINATED`, cyclable in both directions), the
        weekly wrap (`DRAFT`, `SUBMITTED`, `CERTIFIED`, `DISPUTED`, `AMENDED`,
        `VOID`, with `VOID` terminal), the royalty allocation (`ALLOCATED`,
        `REVERSED`, with `REVERSED` terminal), licensing income (`RECORDED`,
        `ALLOCATED`, with `ALLOCATED` terminal), the distribution (`DECLARED`,
        `PAID`, with `PAID` terminal), and the closing notice (`ISSUED`,
        `WITHDRAWN`, `SETTLED`, with both `WITHDRAWN` and `SETTLED` terminal)."

        "A rejected request increments nothing and refreshes no `updated_at`."

        Design: Corner/errors/second_action_on_a_settled_row_reports_that_rows_invalid_state
        """
        world = fixtures.capitalized_world(api)
        get_success_data(api.approve_budget(world.production_id, PRODUCER_HEADERS), 200)

        line_id = get_success_data(
            api.create_budget_line(
                factories.budget_line_payload(
                    world.production_id, 40_000_000, world.production_version()
                ),
                GM_HEADERS,
            ),
            201,
        )["id"]
        get_success_data(api.commit_budget_line(line_id, GM_HEADERS), 200)

        income = fixtures.with_recorded_income(world, gross_income_cents=10_000_000)
        get_success_data(
            api.allocate_subsidiary_rights_income(income["id"], COMPTROLLER_HEADERS), 200
        )

        distribution = get_success_data(
            fixtures.declare_distribution(world, 1_000_000), 201
        )
        get_success_data(
            api.pay_investor_distribution(distribution["id"], COMPTROLLER_HEADERS), 200
        )

        fixtures.advance_operating_status(world, "REHEARSAL", "PREVIEWS", "RUNNING")
        fixtures.with_submitted_standard_week(world)
        fixtures.with_issued_closing_notice(
            world,
            notice_date="2026-09-07",
            final_performance_date="2026-09-27",
        )
        get_success_data(
            api.withdraw_closing_notice(
                world.closing_notice_id or "",
                factories.withdrawal_payload("Extension booked"),
                PRODUCER_HEADERS,
            ),
            200,
        )

        before = world.production()
        assert before["operating_status"] == "RUNNING"

        validate_error(
            api.allocate_subsidiary_rights_income(income["id"], COMPTROLLER_HEADERS),
            ApiErrorId.INVALID_INCOME_STATE,
        )
        validate_error(
            api.pay_investor_distribution(distribution["id"], COMPTROLLER_HEADERS),
            ApiErrorId.INVALID_DISTRIBUTION_STATE,
        )
        validate_error(
            api.activate_operating_budget(
                world.operating_budget_id or "", COMPTROLLER_HEADERS
            ),
            ApiErrorId.INVALID_OPERATING_BUDGET_STATE,
        )
        validate_error(
            api.commit_budget_line(line_id, GM_HEADERS),
            ApiErrorId.INVALID_BUDGET_LINE_STATE,
        )
        validate_error(
            api.submit_weekly_wrap(world.wrap_id or "", GM_HEADERS),
            ApiErrorId.INVALID_WRAP_STATE,
        )
        validate_error(
            api.withdraw_closing_notice(
                world.closing_notice_id or "",
                factories.withdrawal_payload("Second thoughts"),
                PRODUCER_HEADERS,
            ),
            ApiErrorId.INVALID_CLOSING_NOTICE_STATE,
        )

        after = world.production()
        assert after["operating_status"] == "RUNNING"
        assert_no_write(before, after)


class TestNotFoundCatalogue:
    """One unknown identifier probed against thirteen readers, thirteen codes."""

    def test_every_reader_reports_the_not_found_code_of_its_own_entity(
        self, api: ApiClient
    ):
        """No reader falls back on a shared generic not-found code.

        "Path identifiers are resolved left to right, and the first identifier
        that does not resolve determines the rejection:
        `ERR_THEATRE_NOT_FOUND`, `ERR_PRODUCTION_NOT_FOUND`,
        `ERR_THEATRE_ENGAGEMENT_NOT_FOUND`, `ERR_BUDGET_LINE_NOT_FOUND`,
        `ERR_OPERATING_BUDGET_NOT_FOUND`, `ERR_OFFERING_DOCUMENT_NOT_FOUND`,
        `ERR_INVESTOR_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`,
        `ERR_INVESTOR_ACCOUNT_NOT_FOUND`, `ERR_ROYALTY_PARTICIPANT_NOT_FOUND`,
        `ERR_WEEKLY_WRAP_NOT_FOUND`, `ERR_ROYALTY_ALLOCATION_NOT_FOUND`,
        `ERR_SUBSIDIARY_RIGHTS_INCOME_NOT_FOUND`,
        `ERR_INVESTOR_DISTRIBUTION_NOT_FOUND`, or
        `ERR_CLOSING_NOTICE_NOT_FOUND` — each HTTP 404."

        Design: Corner/errors/every_remaining_entity_lookup_reports_its_own_not_found_id
        """
        fixtures.base_world(api)

        probes = (
            (
                api.get_theatre_engagement(UNKNOWN_UUID, GM_HEADERS),
                ApiErrorId.THEATRE_ENGAGEMENT_NOT_FOUND,
            ),
            (
                api.get_budget_line(UNKNOWN_UUID, GM_HEADERS),
                ApiErrorId.BUDGET_LINE_NOT_FOUND,
            ),
            (
                api.get_operating_budget(UNKNOWN_UUID, GM_HEADERS),
                ApiErrorId.OPERATING_BUDGET_NOT_FOUND,
            ),
            (
                api.get_offering_document(UNKNOWN_UUID, COUNSEL_HEADERS),
                ApiErrorId.OFFERING_DOCUMENT_NOT_FOUND,
            ),
            (
                api.get_investor(UNKNOWN_UUID, COUNSEL_HEADERS),
                ApiErrorId.INVESTOR_NOT_FOUND,
            ),
            (
                api.get_subscription(UNKNOWN_UUID, COUNSEL_HEADERS),
                ApiErrorId.SUBSCRIPTION_NOT_FOUND,
            ),
            (
                api.get_investor_account(UNKNOWN_UUID, COMPTROLLER_HEADERS),
                ApiErrorId.INVESTOR_ACCOUNT_NOT_FOUND,
            ),
            (
                api.get_royalty_participant(UNKNOWN_UUID, GM_HEADERS),
                ApiErrorId.ROYALTY_PARTICIPANT_NOT_FOUND,
            ),
            (
                api.get_weekly_wrap(UNKNOWN_UUID, GM_HEADERS),
                ApiErrorId.WEEKLY_WRAP_NOT_FOUND,
            ),
            (
                api.get_royalty_allocation(UNKNOWN_UUID, COMPTROLLER_HEADERS),
                ApiErrorId.ROYALTY_ALLOCATION_NOT_FOUND,
            ),
            (
                api.get_subsidiary_rights_income(UNKNOWN_UUID, GM_HEADERS),
                ApiErrorId.SUBSIDIARY_RIGHTS_INCOME_NOT_FOUND,
            ),
            (
                api.get_investor_distribution(UNKNOWN_UUID, COMPTROLLER_HEADERS),
                ApiErrorId.INVESTOR_DISTRIBUTION_NOT_FOUND,
            ),
            (
                api.get_closing_notice(UNKNOWN_UUID, PRODUCER_HEADERS),
                ApiErrorId.CLOSING_NOTICE_NOT_FOUND,
            ),
        )
        for response, expected_error_id in probes:
            validate_error(response, expected_error_id, 404)
            assert_envelope(response.json(), "error")


class TestAuthenticationIsTheFirstGate:
    """A missing or unrecognised identity is refused before anything else runs."""

    def test_absent_headers_and_an_undeclared_role_are_all_unauthenticated(
        self, api: ApiClient
    ):
        """401 wins over the unknown path id and over the forbidden role alike.

        "**Authentication.** Both headers present and `X-User-Role` one of the
        five declared roles, else `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/errors/request_missing_x_user_role_header_rejected
        """
        world = fixtures.base_world(api)

        validate_error(
            api.get_production(world.production_id, headers_without_role()),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.get_production(world.production_id, headers_without_user_id()),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )
        # The path id resolves to nothing and the role would have been wrong
        # anyway; authentication still decides the answer.
        validate_error(
            api.capitalize(
                UNKNOWN_UUID, headers_without_role(COMPTROLLER_USER_ID)
            ),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.get_production(world.production_id, headers_with_undeclared_role()),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )
