"""The error catalogue: identity refusal and one not-found code per entity.

Each scenario names an identifier that resolves to nothing, or omits identity
altogether, and pins the machine-readable code and the HTTP status that carry it.
"""

from test_helpers import (
    UNKNOWN_CHAMBER_ID,
    UNKNOWN_CHANGE_REQUEST_ID,
    UNKNOWN_DIE_SORT_RUN_ID,
    UNKNOWN_EXCURSION_ID,
    UNKNOWN_LOT_ID,
    UNKNOWN_OPERATOR_ID,
    UNKNOWN_PLAN_ID,
    UNKNOWN_SPC_CHART_ID,
    UNKNOWN_STEP_ID,
    UNKNOWN_STEP_RUN_ID,
    equipment_engineer_headers,
    fab_planner_headers,
    process_engineer_headers,
    quality_manager_headers,
    yield_engineer_headers,
)
from test_helpers.api_errors import (
    ERR_CHAMBER_NOT_FOUND,
    ERR_CHANGE_REQUEST_NOT_FOUND,
    ERR_EXCURSION_NOT_FOUND,
    ERR_LOT_NOT_FOUND,
    ERR_OPERATOR_NOT_FOUND,
    ERR_PLAN_NOT_FOUND,
    ERR_PROCESS_STEP_NOT_FOUND,
    ERR_SORT_RUN_NOT_FOUND,
    ERR_SPC_CHART_NOT_FOUND,
    ERR_STEP_RUN_NOT_FOUND,
    ERR_UNAUTHENTICATED,
)
from test_helpers.constants import API_PREFIX
from test_helpers.factories import spc_chart_payload
from prd_bench_local_runner.testing.validators import validate_error


# --------------------------------------------------------------------------
# Identity headers
# --------------------------------------------------------------------------


class TestIdentityRefusal:
    def test_a_request_carrying_no_identity_headers_is_refused(self, fab):
        """Without both headers the server never reaches the roster at all.

        PRD: "A request missing either header, or carrying an `X-User-Role` value
        that is not one of those six, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        PRD: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/a_request_with_no_identity_headers_is_unauthenticated
        """
        response = fab.client.request_without_headers("GET", API_PREFIX + "/lots")

        body = validate_error(response, ERR_UNAUTHENTICATED, 401)
        assert body["error_id"] == ERR_UNAUTHENTICATED
        envelope = response.json()
        assert set(envelope["meta"].keys()) == {
            "api_request_id",
            "api_request_timestamp",
        }
        assert not isinstance(envelope["data"], list), (
            "an error response carries no data rows"
        )


# --------------------------------------------------------------------------
# One not-found code per entity
# --------------------------------------------------------------------------


class TestNotFoundCatalogue:
    def test_a_chart_named_on_an_unknown_step_reports_the_step_code(self, fab):
        """The body foreign key is resolved first, so no chart is ever written.

        PRD: "The same catalogue serves foreign keys supplied in a request body:
        an unresolvable `plan_id` yields `ERR_PLAN_NOT_FOUND`, an unresolvable
        `qualified_recipe_id` yields `ERR_RECIPE_NOT_FOUND`, and so on."

        Design: Corner/errors/spc_chart_on_an_unknown_step_returns_process_step_not_found
        """
        response = fab.client.create_spc_chart(
            spc_chart_payload(UNKNOWN_STEP_ID, "CD", 100.0, 2.0, 110.0, 90.0, 106.0, 94.0),
            process_engineer_headers(),
        )

        body = validate_error(response, ERR_PROCESS_STEP_NOT_FOUND, 404)
        assert body["error_id"] == ERR_PROCESS_STEP_NOT_FOUND
        assert fab.count(fab.client.list_spc_charts(process_engineer_headers())) == 0

    def test_an_unknown_change_notice_reports_the_change_request_code(self, fab):
        """A notice that was never filed answers with its own code.

        PRD: "Each entity has its own not-found code:
        `ERR_PROCESS_FLOW_NOT_FOUND`, `ERR_PROCESS_STEP_NOT_FOUND`,
        `ERR_RECIPE_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`,
        `ERR_EQUIPMENT_NOT_FOUND`, `ERR_CHAMBER_NOT_FOUND`,
        `ERR_OPERATOR_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_STEP_RUN_NOT_FOUND`, `ERR_SPC_CHART_NOT_FOUND`,
        `ERR_EXCURSION_NOT_FOUND` and `ERR_SORT_RUN_NOT_FOUND`, all HTTP 404."

        Design: Corner/errors/reading_an_unknown_change_request_returns_change_request_not_found
        """
        response = fab.client.get_change_request(
            UNKNOWN_CHANGE_REQUEST_ID, process_engineer_headers()
        )

        body = validate_error(response, ERR_CHANGE_REQUEST_NOT_FOUND, 404)
        assert body["error_id"] == ERR_CHANGE_REQUEST_NOT_FOUND

    def test_an_unknown_chamber_reports_the_chamber_code_even_beside_a_real_tool(self, fab):
        """A commissioned tool with no chambers still answers for the chamber.

        PRD: "When a path carries an identifier, the server resolves it before it
        evaluates any business rule."

        Design: Corner/errors/reading_an_unknown_chamber_returns_chamber_not_found
        """
        tool = fab.equipment("LITHO-1", "LITHO")

        response = fab.client.get_chamber(
            UNKNOWN_CHAMBER_ID, equipment_engineer_headers()
        )

        body = validate_error(response, ERR_CHAMBER_NOT_FOUND, 404)
        assert body["error_id"] == ERR_CHAMBER_NOT_FOUND
        assert fab.count(
            fab.client.list_chambers(
                equipment_engineer_headers(), {"equipment_id": tool["id"]}
            )
        ) == 0

    def test_an_unknown_operator_reports_the_operator_code(self, fab):
        """An unregistered badge resolves to nothing, and says so precisely.

        PRD: "Each entity has its own not-found code:
        `ERR_PROCESS_FLOW_NOT_FOUND`, `ERR_PROCESS_STEP_NOT_FOUND`,
        `ERR_RECIPE_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`,
        `ERR_EQUIPMENT_NOT_FOUND`, `ERR_CHAMBER_NOT_FOUND`,
        `ERR_OPERATOR_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_STEP_RUN_NOT_FOUND`, `ERR_SPC_CHART_NOT_FOUND`,
        `ERR_EXCURSION_NOT_FOUND` and `ERR_SORT_RUN_NOT_FOUND`, all HTTP 404."

        Design: Corner/errors/reading_an_unknown_operator_returns_operator_not_found
        """
        response = fab.client.get_operator(
            UNKNOWN_OPERATOR_ID, quality_manager_headers()
        )

        body = validate_error(response, ERR_OPERATOR_NOT_FOUND, 404)
        assert body["error_id"] == ERR_OPERATOR_NOT_FOUND

    def test_an_unknown_wafer_start_plan_reports_the_plan_code(self, fab):
        """The planner's own entity has its own code, distinct from the lot's.

        PRD: "Each entity has its own not-found code:
        `ERR_PROCESS_FLOW_NOT_FOUND`, `ERR_PROCESS_STEP_NOT_FOUND`,
        `ERR_RECIPE_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`,
        `ERR_EQUIPMENT_NOT_FOUND`, `ERR_CHAMBER_NOT_FOUND`,
        `ERR_OPERATOR_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_STEP_RUN_NOT_FOUND`, `ERR_SPC_CHART_NOT_FOUND`,
        `ERR_EXCURSION_NOT_FOUND` and `ERR_SORT_RUN_NOT_FOUND`, all HTTP 404."

        Design: Corner/errors/reading_an_unknown_wafer_start_plan_returns_plan_not_found
        """
        response = fab.client.get_plan(UNKNOWN_PLAN_ID, fab_planner_headers())

        body = validate_error(response, ERR_PLAN_NOT_FOUND, 404)
        assert body["error_id"] == ERR_PLAN_NOT_FOUND

    def test_an_unknown_lot_reports_the_lot_code_while_the_roster_reads_empty(self, fab):
        """The listing succeeds with nothing in it; only the point read fails.

        PRD: "Each entity has its own not-found code:
        `ERR_PROCESS_FLOW_NOT_FOUND`, `ERR_PROCESS_STEP_NOT_FOUND`,
        `ERR_RECIPE_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`,
        `ERR_EQUIPMENT_NOT_FOUND`, `ERR_CHAMBER_NOT_FOUND`,
        `ERR_OPERATOR_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_STEP_RUN_NOT_FOUND`, `ERR_SPC_CHART_NOT_FOUND`,
        `ERR_EXCURSION_NOT_FOUND` and `ERR_SORT_RUN_NOT_FOUND`, all HTTP 404."

        Design: Corner/errors/reading_an_unknown_lot_returns_lot_not_found
        """
        response = fab.client.get_lot(UNKNOWN_LOT_ID, fab_planner_headers())

        body = validate_error(response, ERR_LOT_NOT_FOUND, 404)
        assert body["error_id"] == ERR_LOT_NOT_FOUND
        roster = fab.client.list_lots(fab_planner_headers())
        assert roster.status_code == 200
        assert fab.count(roster) == 0

    def test_an_unknown_step_run_reports_the_step_run_code(self, fab):
        """A run identifier that was never minted answers with its own code.

        PRD: "Each entity has its own not-found code:
        `ERR_PROCESS_FLOW_NOT_FOUND`, `ERR_PROCESS_STEP_NOT_FOUND`,
        `ERR_RECIPE_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`,
        `ERR_EQUIPMENT_NOT_FOUND`, `ERR_CHAMBER_NOT_FOUND`,
        `ERR_OPERATOR_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_STEP_RUN_NOT_FOUND`, `ERR_SPC_CHART_NOT_FOUND`,
        `ERR_EXCURSION_NOT_FOUND` and `ERR_SORT_RUN_NOT_FOUND`, all HTTP 404."

        Design: Corner/errors/reading_an_unknown_step_run_returns_step_run_not_found
        """
        response = fab.client.get_step_run(
            UNKNOWN_STEP_RUN_ID, process_engineer_headers()
        )

        body = validate_error(response, ERR_STEP_RUN_NOT_FOUND, 404)
        assert body["error_id"] == ERR_STEP_RUN_NOT_FOUND

    def test_an_unknown_spc_chart_reports_the_spc_chart_code(self, fab):
        """The chart catalogue answers for itself and not for its step.

        PRD: "Each entity has its own not-found code:
        `ERR_PROCESS_FLOW_NOT_FOUND`, `ERR_PROCESS_STEP_NOT_FOUND`,
        `ERR_RECIPE_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`,
        `ERR_EQUIPMENT_NOT_FOUND`, `ERR_CHAMBER_NOT_FOUND`,
        `ERR_OPERATOR_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_STEP_RUN_NOT_FOUND`, `ERR_SPC_CHART_NOT_FOUND`,
        `ERR_EXCURSION_NOT_FOUND` and `ERR_SORT_RUN_NOT_FOUND`, all HTTP 404."

        Design: Corner/errors/reading_an_unknown_spc_chart_returns_spc_chart_not_found
        """
        response = fab.client.get_spc_chart(
            UNKNOWN_SPC_CHART_ID, process_engineer_headers()
        )

        body = validate_error(response, ERR_SPC_CHART_NOT_FOUND, 404)
        assert body["error_id"] == ERR_SPC_CHART_NOT_FOUND

    def test_an_unknown_excursion_reports_the_excursion_code(self, fab):
        """Quality's own entity carries its own code.

        PRD: "Each entity has its own not-found code:
        `ERR_PROCESS_FLOW_NOT_FOUND`, `ERR_PROCESS_STEP_NOT_FOUND`,
        `ERR_RECIPE_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`,
        `ERR_EQUIPMENT_NOT_FOUND`, `ERR_CHAMBER_NOT_FOUND`,
        `ERR_OPERATOR_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_STEP_RUN_NOT_FOUND`, `ERR_SPC_CHART_NOT_FOUND`,
        `ERR_EXCURSION_NOT_FOUND` and `ERR_SORT_RUN_NOT_FOUND`, all HTTP 404."

        Design: Corner/errors/reading_an_unknown_excursion_returns_excursion_not_found
        """
        response = fab.client.get_excursion(
            UNKNOWN_EXCURSION_ID, quality_manager_headers()
        )

        body = validate_error(response, ERR_EXCURSION_NOT_FOUND, 404)
        assert body["error_id"] == ERR_EXCURSION_NOT_FOUND

    def test_an_unknown_die_sort_run_reports_the_sort_run_code(self, fab):
        """The sort run's code is spelled ERR_SORT_RUN_NOT_FOUND, not after its path.

        PRD: "Each entity has its own not-found code:
        `ERR_PROCESS_FLOW_NOT_FOUND`, `ERR_PROCESS_STEP_NOT_FOUND`,
        `ERR_RECIPE_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`,
        `ERR_EQUIPMENT_NOT_FOUND`, `ERR_CHAMBER_NOT_FOUND`,
        `ERR_OPERATOR_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_STEP_RUN_NOT_FOUND`, `ERR_SPC_CHART_NOT_FOUND`,
        `ERR_EXCURSION_NOT_FOUND` and `ERR_SORT_RUN_NOT_FOUND`, all HTTP 404."

        Design: Corner/errors/reading_an_unknown_die_sort_run_returns_sort_run_not_found
        """
        response = fab.client.get_die_sort_run(
            UNKNOWN_DIE_SORT_RUN_ID, yield_engineer_headers()
        )

        body = validate_error(response, ERR_SORT_RUN_NOT_FOUND, 404)
        assert body["error_id"] == ERR_SORT_RUN_NOT_FOUND
