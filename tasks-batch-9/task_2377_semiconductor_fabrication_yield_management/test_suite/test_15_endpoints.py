"""Endpoint surface: the declared filters, the pagination bounds and the links.

Each scenario populates enough rows for a filter to have something to exclude,
then reads back through the query parameters the endpoint declares.
"""

from test_helpers import (
    LotSpec,
    build_line,
    fab_planner_headers,
    operator_headers_opaque,
    process_engineer_headers,
    single_step_spec,
    sorted_run,
    yield_engineer_headers,
)
from test_helpers.api_errors import ERR_VALIDATION
from test_helpers.assertions import (
    assert_fields,
    assert_hours,
    assert_nulls,
    assert_pagination_meta,
    assert_ratio,
    assert_timestamp_equals,
)
from test_helpers.factories import wafer_result
from prd_bench_local_runner.testing.validators import validate_error, validate_success


# --------------------------------------------------------------------------
# Two filters applied together on the tool roster
# --------------------------------------------------------------------------


class TestEquipmentListing:
    def test_tool_type_and_state_narrow_the_roster_together(self, fab):
        """Three tools, two LITHO and two IDLE, but only one that is both.

        PRD: "| GET | `/fab/equipment` | List tools, filterable by tool type and
        state | All roles |"

        Design: Corner/endpoints/equipment_list_filters_on_tool_type_and_state_together
        """
        idle_litho = fab.equipment("LITHO-1", "LITHO")
        maintained_litho = fab.equipment("LITHO-2", "LITHO")
        fab.equipment("ETCH-1", "ETCH")
        assert fab.pm_start(maintained_litho["id"])["state"] == "PM"

        response = fab.client.list_equipment(
            process_engineer_headers(), {"tool_type": "LITHO", "state": "IDLE"}
        )

        rows = validate_success(response, 200)
        assert response.json()["meta"]["total_count"] == 1
        assert rows[0]["id"] == idle_litho["id"]
        assert fab.count(
            fab.client.list_equipment(process_engineer_headers(), {"tool_type": "LITHO"})
        ) == 2
        assert fab.count(
            fab.client.list_equipment(process_engineer_headers(), {"state": "IDLE"})
        ) == 2


# --------------------------------------------------------------------------
# Pagination bounds on the lot roster
# --------------------------------------------------------------------------


class TestLotListingPagination:
    def test_a_limit_above_one_hundred_is_refused_while_one_hundred_is_served(self, fab):
        """Paging works inside the bounds and the upper bound itself is inclusive.

        PRD: "List endpoints are paginated through two query parameters. `limit`
        caps the number of rows returned; it defaults to 10, has a minimum of 1
        and a maximum of 100."

        PRD: "A `limit` outside the range 1 through 100, or a negative `offset`,
        is a request-shape failure and is rejected with `ERR_VALIDATION` (HTTP
        400)."

        Design: Corner/endpoints/lot_list_paginates_and_rejects_a_limit_above_one_hundred
        """
        env = build_line(
            fab,
            single_step_spec(
                planned_wafer_starts=30,
                lots=[
                    LotSpec("LOT-001", 3, release=False),
                    LotSpec("LOT-002", 3, release=False),
                    LotSpec("LOT-003", 3, release=False),
                ],
            ),
        )
        page = fab.client.list_lots(
            fab_planner_headers(),
            {"plan_id": env.plan["id"], "limit": 2, "offset": 1},
        )
        assert_pagination_meta(page.json()["meta"], 2, 1, 3, False)
        assert len(page.json()["data"]) == 2

        response = fab.client.list_lots(
            fab_planner_headers(), {"plan_id": env.plan["id"], "limit": 101}
        )

        body = validate_error(response, ERR_VALIDATION, 400)
        assert body["error_id"] == ERR_VALIDATION
        at_the_bound = fab.client.list_lots(
            fab_planner_headers(), {"plan_id": env.plan["id"], "limit": 100}
        )
        assert at_the_bound.status_code == 200
        assert fab.count(at_the_bound) == 3


# --------------------------------------------------------------------------
# Maintenance completion, read back off the tool row
# --------------------------------------------------------------------------


class TestPmCompleteEffects:
    def test_finishing_maintenance_resets_the_ledger_and_opens_the_purge_window(self, fab):
        """150 accrued hours are wiped, the ledger returns to 720.00 and a window opens.

        PRD: "The tool is driven `PM → IDLE`; `hours_since_pm` resets to 0.0;
        `available_capacity_hours` resets to 720.00; `purge_until` is set to the
        current logical instant plus `purge_buffer_hours`; every chamber of the
        tool whose `qual_state` is `DISQUALIFIED` is driven `DISQUALIFIED →
        UNQUALIFIED`, which is what closes the chamber cycle `QUALIFIED →
        DISQUALIFIED → UNQUALIFIED → QUALIFIED`; every lot on `QUAL_HOLD` whose
        `hold_excursion_id` names an excursion raised on a chamber of this tool is
        released back to `hold_state` `NONE` with its `hold_excursion_id` cleared
        to null; and the tool's `version` increments by 1."

        Design: Corner/endpoints/pm_complete_resets_the_ledger_and_opens_the_purge_window
        """
        fab.set_clock("2026-08-01T00:00:00Z")
        recipe = fab.recipe("LITHO-200", "LITHO", 50.0, 100)
        tool = fab.equipment("LITHO-1", "LITHO", 168.0, 24.0, 150.0)
        chamber = fab.chamber(tool["id"], recipe["id"], "CH_L1")
        fab.qualify_chamber(chamber["id"])

        assert_hours(tool["hours_since_pm"], 150.0, "hours_since_pm")
        assert_nulls(tool, "purge_until")
        started = fab.pm_start(tool["id"], "Scheduled 168-hour PM")
        assert started["state"] == "PM"
        assert_timestamp_equals(
            started["pm_started_at"], "2026-08-01T00:00:00Z", "pm_started_at"
        )

        completed = fab.pm_complete(tool["id"])

        assert completed["state"] == "IDLE"
        assert_hours(
            completed["available_capacity_hours"], 720.00, "available_capacity_hours"
        )
        assert_hours(completed["hours_since_pm"], 0.0, "hours_since_pm")
        # The instant of completion plus the 24-hour purge buffer.
        assert_timestamp_equals(
            completed["purge_until"], "2026-08-02T00:00:00Z", "purge_until"
        )
        assert fab.read_chamber(chamber["id"])["qual_state"] == "QUALIFIED"


# --------------------------------------------------------------------------
# The die-sort excursion and the pointers that find it
# --------------------------------------------------------------------------


class TestSortExcursionLinkage:
    def test_a_sort_excursion_is_reachable_from_its_run_and_from_its_lot(self, fab):
        """A 13.04 percent loss opens an excursion that both filters return.

        PRD: "When `yield_loss_ratio` reaches 0.10 or more, a `DIE_SORT` excursion
        is opened with `die_sort_run_id` pointing at this run, `lot_id` copied
        from the run, `trigger_value` set to `yield_loss_ratio`, and
        `failure_signature` copied from `dominant_signature`; for excursions from
        any other source, `failure_signature` stays `NONE`."

        Design: Corner/endpoints/a_sort_excursion_links_back_to_its_run_and_its_lot
        """
        env = build_line(fab, single_step_spec())

        sort_run = sorted_run(
            fab,
            env,
            [
                wafer_result(1, 100, 80, edge_ring_fails=20),
                wafer_result(2, 100, 80, edge_ring_fails=20),
                wafer_result(3, 100, 80, edge_ring_fails=20),
            ],
            gross_die_per_wafer=100,
            baseline_yield=0.92,
        )

        assert_ratio(sort_run["sort_yield"], 0.8000, "sort_yield")
        # (0.92 - 0.80) / 0.92 carried at full precision, then rounded.
        assert_ratio(sort_run["yield_loss_ratio"], 0.1304, "yield_loss_ratio")
        assert sort_run["dominant_signature"] == "EDGE_RING"
        assert sort_run["good_die_total"] == 240

        by_run = fab.client.list_excursions(
            yield_engineer_headers(), {"die_sort_run_id": sort_run["id"]}
        )
        assert fab.count(by_run) == 1
        assert fab.count(
            fab.client.list_excursions(
                yield_engineer_headers(), {"lot_id": env.lots[0]["id"]}
            )
        ) == 1

        excursion = by_run.json()["data"][0]
        assert_fields(
            excursion,
            source_type="DIE_SORT",
            failure_signature="EDGE_RING",
            severity_band="LOW",
            status="OPEN",
            severity_variant="PROVISIONAL",
        )
        assert_ratio(excursion["trigger_value"], 0.1304, "trigger_value")
        # 60.0 times 0.1304 / 0.25 plus 3.0 for the single affected lot.
        assert_hours(excursion["severity_score"], 34.30, "severity_score")


# --------------------------------------------------------------------------
# Step reads, scoped by flow and by rework target
# --------------------------------------------------------------------------


class TestProcessStepReads:
    def test_the_step_listing_is_scoped_by_flow_and_by_rework_target(self, fab):
        """A second flow's step is excluded, and the rework filter finds exactly one.

        PRD: "| GET | `/fab/process-steps` | List process steps, filterable by
        flow, recipe and rework target | All roles |"

        PRD: "| GET | `/fab/process-flows` | List process flows, filterable by
        product family, status and superseding flow | All roles |"

        Design: Corner/endpoints/process_step_reads_are_scoped_by_flow_and_by_rework_target
        """
        recipe = fab.recipe("LITHO-200", "LITHO", 100.0, 100)
        flow_a = fab.flow("FLOW-A", "LOGIC_N5")
        first = fab.step(flow_a["id"], recipe["id"], 10, "LITHO-1", 2.0)
        second = fab.step(
            flow_a["id"],
            recipe["id"],
            20,
            "LITHO-2",
            3.0,
            metrology_required=True,
            rework_target_step_id=first["id"],
        )
        third = fab.step(flow_a["id"], recipe["id"], 30, "LITHO-3", 2.0)
        released = fab.release_flow(flow_a["id"])
        assert released["step_count"] == 3
        assert_hours(released["total_standard_hours"], 7.0, "total_standard_hours")

        # A second flow, on another product family, that the filter must exclude.
        flow_b = fab.flow("FLOW-B", "MEMORY_D1")
        other = fab.step(flow_b["id"], recipe["id"], 10, "LITHO-1", 2.0)

        response = fab.client.list_process_steps(
            operator_headers_opaque(), {"flow_id": flow_a["id"]}
        )

        rows = validate_success(response, 200)
        assert response.json()["meta"]["total_count"] == 3
        returned = [row["id"] for row in rows]
        assert returned == [first["id"], second["id"], third["id"]]
        assert other["id"] not in returned
        assert fab.count(
            fab.client.list_process_steps(
                operator_headers_opaque(), {"flow_id": flow_b["id"]}
            )
        ) == 1
        assert fab.count(
            fab.client.list_process_steps(
                operator_headers_opaque(), {"rework_target_step_id": first["id"]}
            )
        ) == 1

        stored = fab.read_step(second["id"])
        assert_fields(
            stored,
            step_seq=20,
            metrology_required=True,
            rework_target_step_id=first["id"],
        )
        assert_hours(stored["standard_hours"], 3.0, "standard_hours")
        assert fab.count(
            fab.client.list_process_flows(
                process_engineer_headers(), {"product_family": "LOGIC_N5"}
            )
        ) == 1
