"""Lifecycle transitions: the admissible ones and the refusals that guard them.

Each scenario drives one entity to a particular state, fires the transition
under test, and pins both the answer and the state the entity is left in.
"""

from test_helpers import (
    LotSpec,
    USER_QUALITY_MANAGER,
    build_line,
    equipment_engineer_headers,
    fab_planner_headers,
    make_operator_headers,
    metrology_step_spec,
    open_run,
    process_engineer_headers,
    quality_manager_headers,
    raise_spc_excursion,
    single_step_spec,
    yield_engineer_headers,
)
from test_helpers.api_errors import (
    ERR_CHAMBER_INVALID_QUAL_STATE,
    ERR_CHANGE_REQUEST_INVALID_STATE,
    ERR_EQUIPMENT_DOWN,
    ERR_EQUIPMENT_INVALID_STATE,
    ERR_EQUIPMENT_NOT_IN_PM,
    ERR_EXCURSION_INVALID_STATE,
    ERR_FLOW_HAS_NO_STEPS,
    ERR_FLOW_NOT_DRAFT,
    ERR_FLOW_NOT_RELEASED,
    ERR_PLAN_ALREADY_COMMITTED,
    ERR_STEP_RUN_NOT_OPEN,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_days,
    assert_fields,
    assert_hours,
    assert_lot_state,
    assert_nulls,
    assert_ratio,
    assert_timestamp_equals,
)
from test_helpers.factories import (
    abort_payload,
    disposition_payload,
    pm_start_payload,
    plan_payload,
    process_flow_payload,
    qualification_run_payload,
    request_revision_payload,
    wafer_result,
)
from prd_bench_local_runner.testing.validators import validate_error, validate_success


# --------------------------------------------------------------------------
# The process flow: DRAFT, RELEASED, OBSOLETE
# --------------------------------------------------------------------------


class TestProcessFlowLifecycle:
    def test_a_new_flow_opens_as_an_empty_draft(self, fab):
        """Nothing is pinned and nothing is released until a step arrives.

        PRD: "A newly drafted flow opens in `DRAFT` `status`, with `step_count`
        at 0, `total_standard_hours` at 0.0, `revision` at 1, `released_at` null
        and `superseded_by_flow_id` null."

        Design: Corner/state_machines/new_process_flow_starts_in_draft_with_zero_steps
        """
        fab.set_clock("2026-08-01T00:00:00Z")

        response = fab.client.create_process_flow(
            process_flow_payload("FLOW-A", "LOGIC_N5"), process_engineer_headers()
        )

        flow = validate_success(response, 201)
        assert_fields(flow, status="DRAFT", revision=1, step_count=0)
        assert_hours(flow["total_standard_hours"], 0.0, "total_standard_hours")
        assert_nulls(flow, "released_at", "superseded_by_flow_id")

    def test_releasing_a_draft_stamps_the_release_instant(self, fab):
        """Release pins the step count and records when the flow went live.

        PRD: "On success the server recomputes and pins `step_count` and
        `total_standard_hours`, sets `released_at` to the current logical instant,
        sets `status` to `RELEASED`, and increments the flow's `version` by 1."

        Design: Corner/state_machines/release_flow_moves_draft_to_released_and_stamps_released_at
        """
        recipe = fab.recipe("LITHO-200", "LITHO", 50.0, 100)
        flow = fab.flow("FLOW-A", "LOGIC_N5")
        fab.step(flow["id"], recipe["id"], 10, "LITHO-1", 2.0)

        response = fab.client.release_process_flow(
            flow["id"], process_engineer_headers(), {}
        )

        released = validate_success(response, 200)
        assert released["status"] == "RELEASED"
        assert_timestamp_equals(
            released["released_at"], "2026-08-01T00:00:00Z", "released_at"
        )
        assert released["step_count"] == 1
        assert_hours(released["total_standard_hours"], 2.0, "total_standard_hours")
        assert_nulls(released, "superseded_by_flow_id")

    def test_a_second_release_of_the_same_flow_is_refused(self, fab):
        """The first release instant survives, four days after the fact.

        PRD: "Flow is `DRAFT`, for step insertion and release —
        `ERR_FLOW_NOT_DRAFT`."

        Design: Corner/state_machines/releasing_an_already_released_flow_returns_flow_not_draft
        """
        recipe = fab.recipe("LITHO-200", "LITHO", 50.0, 100)
        flow = fab.flow("FLOW-A", "LOGIC_N5")
        fab.step(flow["id"], recipe["id"], 10, "LITHO-1", 2.0)
        fab.release_flow(flow["id"])
        fab.set_clock("2026-08-05T00:00:00Z")

        response = fab.client.release_process_flow(
            flow["id"], process_engineer_headers(), {}
        )

        body = validate_error(response, ERR_FLOW_NOT_DRAFT, 409)
        assert body["error_id"] == ERR_FLOW_NOT_DRAFT
        stored = fab.read_flow(flow["id"])
        assert stored["status"] == "RELEASED"
        assert_timestamp_equals(
            stored["released_at"], "2026-08-01T00:00:00Z", "released_at"
        )

    def test_a_flow_with_no_steps_cannot_be_released(self, fab):
        """An empty flow has nothing to pin, so it stays a draft.

        PRD: "Release requires the flow to be in `DRAFT`, to have at least one
        step, and for every one of its steps to resolve a recipe whose `status`
        is `QUALIFIED`; a flow with no steps, or with a step whose recipe is
        `RESTRICTED`, is rejected with `ERR_FLOW_HAS_NO_STEPS`."

        Design: Corner/state_machines/releasing_a_flow_with_no_steps_returns_flow_has_no_steps
        """
        flow = fab.flow("FLOW-EMPTY", "MEMORY_D1")
        assert flow["step_count"] == 0

        response = fab.client.release_process_flow(
            flow["id"], process_engineer_headers(), {}
        )

        body = validate_error(response, ERR_FLOW_HAS_NO_STEPS, 422)
        assert body["error_id"] == ERR_FLOW_HAS_NO_STEPS
        stored = fab.read_flow(flow["id"])
        assert stored["status"] == "DRAFT"
        assert_nulls(stored, "released_at")

    def test_no_plan_may_be_written_against_a_superseded_flow(self, fab):
        """Supersession makes the old flow OBSOLETE, and planning refuses it.

        PRD: "A `FabPlanner` drafts a weekly plan naming the `flow_id` of a
        `RELEASED` flow — a flow that is `DRAFT` or `OBSOLETE` is rejected with
        `ERR_FLOW_NOT_RELEASED` — plus the `product_family` being planned, which
        must equal the flow's own `product_family` or the request is rejected
        with `ERR_PRODUCT_FAMILY_MISMATCH`; a `week_start_date` giving the first
        instant of the planning week in ISO 8601 UTC; `planned_wafer_starts`, at
        least 1, being the wafers the plan authorises for release during the
        week; `capacity_budget_hours`, greater than zero, being the fab capacity
        allocated to the plan; and `cycle_time_target_days`, greater than zero,
        the target days from lot release to sort."

        Design: Corner/state_machines/plan_creation_against_a_superseded_flow_returns_flow_not_released
        """
        recipe = fab.recipe("LITHO-200", "LITHO", 50.0, 100)
        old = fab.flow("FLOW-A", "LOGIC_N5")
        fab.step(old["id"], recipe["id"], 10, "LITHO-1", 2.0)
        fab.release_flow(old["id"])
        new = fab.flow("FLOW-A2", "LOGIC_N5")
        fab.step(new["id"], recipe["id"], 10, "LITHO-1", 2.0)
        fab.release_flow(new["id"], supersedes_flow_id=old["id"])

        superseded = fab.read_flow(old["id"])
        assert superseded["status"] == "OBSOLETE"
        assert superseded["superseded_by_flow_id"] == new["id"]

        response = fab.client.create_plan(
            plan_payload(old["id"], "LOGIC_N5", "2026-08-03T00:00:00Z", 10, 100.0, 30.0),
            fab_planner_headers(),
        )

        body = validate_error(response, ERR_FLOW_NOT_RELEASED, 409)
        assert body["error_id"] == ERR_FLOW_NOT_RELEASED


# --------------------------------------------------------------------------
# The tool: IDLE, PRODUCTIVE, PM, DOWN
# --------------------------------------------------------------------------


class TestEquipmentLifecycle:
    def test_maintenance_cannot_be_completed_on_a_tool_that_never_started_it(self, fab):
        """An IDLE tool keeps its accrued hours and never gets a purge window.

        PRD: "Completing maintenance requires the tool to be in `PM`, otherwise
        `ERR_EQUIPMENT_NOT_IN_PM`, and does a great deal at once."

        Design: Corner/state_machines/pm_complete_on_an_idle_tool_returns_equipment_not_in_pm
        """
        tool = fab.equipment("LITHO-1", "LITHO", 168.0, 24.0, 40.0)
        assert tool["state"] == "IDLE"

        response = fab.client.pm_complete(tool["id"], equipment_engineer_headers())

        body = validate_error(response, ERR_EQUIPMENT_NOT_IN_PM, 409)
        assert body["error_id"] == ERR_EQUIPMENT_NOT_IN_PM
        stored = fab.read_equipment(tool["id"])
        assert_hours(stored["hours_since_pm"], 40.0, "hours_since_pm")
        assert_hours(
            stored["available_capacity_hours"], 720.0, "available_capacity_hours"
        )
        assert_nulls(stored, "purge_until")

    def test_maintenance_cannot_start_while_a_run_is_open_on_the_tool(self, fab):
        """The tool is PRODUCTIVE, so the open run has to be closed out first.

        PRD: "A maintenance start is admissible only from `IDLE` or `DOWN`; a
        `PRODUCTIVE` tool must track out or abort its open runs first, and a tool
        already in `PM` cannot restart maintenance, both rejected with
        `ERR_EQUIPMENT_INVALID_STATE`."

        Design: Corner/state_machines/pm_start_on_a_productive_tool_returns_equipment_invalid_state
        """
        env = build_line(fab, single_step_spec())
        run = open_run(fab, env, step_ix=0, lot_ix=0)
        assert_hours(run["reserved_hours"], 2.0, "reserved_hours")

        working = fab.read_equipment(env.equipments[0]["id"])
        assert working["state"] == "PRODUCTIVE"
        assert_hours(
            working["available_capacity_hours"], 718.00, "available_capacity_hours"
        )

        response = fab.client.pm_start(
            env.equipments[0]["id"],
            pm_start_payload("Scheduled 168-hour PM"),
            equipment_engineer_headers(),
        )

        body = validate_error(response, ERR_EQUIPMENT_INVALID_STATE, 409)
        assert body["error_id"] == ERR_EQUIPMENT_INVALID_STATE
        stored = fab.read_equipment(env.equipments[0]["id"])
        assert stored["state"] == "PRODUCTIVE"
        assert_nulls(stored, "pm_started_at")
        assert_hours(
            stored["available_capacity_hours"], 718.00, "available_capacity_hours"
        )
        assert fab.read_step_run(run["id"])["status"] == "OPEN"


# --------------------------------------------------------------------------
# The chamber: UNQUALIFIED, QUALIFIED, QUAL_EXPIRED, DISQUALIFIED
# --------------------------------------------------------------------------


def _qualified_etch_chamber(fab):
    """One ETCH chamber qualified at 2026-08-01 on a 100-day window."""
    fab.set_clock("2026-08-01T00:00:00Z")
    recipe = fab.recipe("ETCH-200", "ETCH", 100.0, 100)
    tool = fab.equipment("ETCH-1", "ETCH")
    chamber = fab.chamber(tool["id"], recipe["id"], "CH_E1")
    return recipe, tool, fab.qualify_chamber(chamber["id"])


class TestChamberQualificationLifecycle:
    def test_a_chamber_that_is_already_qualified_refuses_another_run(self, fab):
        """The standing qualification and its expiry are left exactly as they were.

        PRD: "A qualification run is accepted only while the chamber's
        `qual_state` is `UNQUALIFIED` or `QUAL_EXPIRED`; a chamber that is
        already `QUALIFIED` must lapse or be disqualified first, and a
        `DISQUALIFIED` chamber must be cleared through maintenance, both rejected
        with `ERR_CHAMBER_INVALID_QUAL_STATE`."

        Design: Corner/state_machines/qualification_run_on_an_already_qualified_chamber_returns_chamber_invalid_qual_state
        """
        _, _, chamber = _qualified_etch_chamber(fab)
        # 2026-08-01 plus one hundred days.
        assert_timestamp_equals(
            chamber["qual_expires_at"], "2026-11-09T00:00:00Z", "qual_expires_at"
        )
        fab.set_clock("2026-08-05T00:00:00Z")

        response = fab.client.create_qualification_run(
            chamber["id"], qualification_run_payload("PASS"), equipment_engineer_headers()
        )

        body = validate_error(response, ERR_CHAMBER_INVALID_QUAL_STATE, 409)
        assert body["error_id"] == ERR_CHAMBER_INVALID_QUAL_STATE
        stored = fab.read_chamber(chamber["id"])
        assert stored["qual_state"] == "QUALIFIED"
        assert_timestamp_equals(
            stored["qual_expires_at"], "2026-11-09T00:00:00Z", "qual_expires_at"
        )
        assert_timestamp_equals(
            stored["qualified_at"], "2026-08-01T00:00:00Z", "qualified_at"
        )

    def test_a_failed_qualification_run_is_recorded_but_drives_no_transition(self, fab):
        """The attempt costs the chamber a version but leaves it unqualified.

        PRD: "A `FAIL` run is recorded but drives no transition: the chamber
        keeps its current `qual_state`, `qualified_at` and `qual_expires_at`."

        Design: Corner/state_machines/failed_qualification_run_records_the_attempt_without_qualifying_the_chamber
        """
        recipe = fab.recipe("ETCH-200", "ETCH", 100.0, 100)
        tool = fab.equipment("ETCH-1", "ETCH")
        fresh = fab.chamber(tool["id"], recipe["id"], "CH_E1")
        assert fresh["qual_state"] == "UNQUALIFIED"
        assert_common_fields(fresh, expected_version=1)

        response = fab.client.create_qualification_run(
            fresh["id"], qualification_run_payload("FAIL"), equipment_engineer_headers()
        )

        attempted = validate_success(response, 200)
        assert attempted["qual_state"] == "UNQUALIFIED"
        # Either result increments the chamber's version by 1.
        assert_common_fields(attempted, expected_version=2)
        assert_nulls(attempted, "qualified_at", "qual_expires_at")
        assert attempted["occupancy_state"] == "FREE"

    def test_a_chamber_on_a_downed_tool_cannot_be_requalified(self, fab):
        """Equipment-scope containment takes the tool down and the chamber with it.

        PRD: "The parent tool's `state` must be neither `DOWN` nor `PM`,
        otherwise `ERR_EQUIPMENT_DOWN`."

        Design: Corner/state_machines/qualification_run_on_a_chamber_of_a_down_tool_returns_equipment_down
        """
        env = build_line(fab, metrology_step_spec())
        raised = raise_spc_excursion(fab, env, 112.0, step_ix=0, lot_ix=0)

        contained = fab.contain(
            raised.excursion["id"],
            "EQUIPMENT",
            chamber_id=env.chambers[0]["id"],
            user_id=USER_QUALITY_MANAGER,
        )
        assert_fields(
            contained,
            status="CONTAINED",
            containment_scope="EQUIPMENT",
            severity_variant="FINAL",
        )
        assert fab.read_equipment(env.equipments[0]["id"])["state"] == "DOWN"
        assert fab.read_chamber(env.chambers[0]["id"])["qual_state"] == "DISQUALIFIED"

        response = fab.client.create_qualification_run(
            env.chambers[0]["id"],
            qualification_run_payload("PASS"),
            equipment_engineer_headers(),
        )

        body = validate_error(response, ERR_EQUIPMENT_DOWN, 409)
        assert body["error_id"] == ERR_EQUIPMENT_DOWN
        assert fab.read_chamber(env.chambers[0]["id"])["qual_state"] == "DISQUALIFIED"
        assert fab.read_step_run(raised.run["id"])["status"] == "ABORTED"
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), hold_state="QUAL_HOLD")


# --------------------------------------------------------------------------
# The plan: DRAFT, COMMITTED, CLOSED
# --------------------------------------------------------------------------


class TestPlanLifecycle:
    def test_a_committed_plan_refuses_a_second_commit(self, fab):
        """The prices recorded by the first commit are not recomputed.

        PRD: "Commit requires the plan to be in `DRAFT` — a second commit is
        rejected with `ERR_PLAN_ALREADY_COMMITTED` — and requires the flow still
        to be `RELEASED` and the product families still to agree."

        Design: Corner/state_machines/committing_an_already_committed_plan_returns_plan_already_committed
        """
        env = build_line(fab, single_step_spec(lots=[]))
        # 10 starts by 2.0 hours is 20.00 base, a 0.2000 utilisation, so TIER_0.
        assert_fields(env.plan, status="COMMITTED", commitment_tier="TIER_0")
        assert_hours(env.plan["committed_hours"], 20.00, "committed_hours")

        response = fab.client.commit_plan(env.plan["id"], fab_planner_headers())

        body = validate_error(response, ERR_PLAN_ALREADY_COMMITTED, 409)
        assert body["error_id"] == ERR_PLAN_ALREADY_COMMITTED
        stored = fab.read_plan(env.plan["id"])
        assert stored["status"] == "COMMITTED"
        assert_hours(stored["committed_hours"], 20.00, "committed_hours")
        assert_hours(stored["surcharge_hours"], 0.00, "surcharge_hours")

    def test_a_release_that_fills_the_authorisation_closes_the_plan(self, fab):
        """Five wafers against five authorised starts exhausts the plan outright.

        PRD: "When the candidate total is exactly equal to
        `planned_wafer_starts`, the plan is additionally driven `COMMITTED →
        CLOSED`, with a further increment of the plan's `version`."

        Design: Corner/state_machines/plan_auto_closes_when_a_release_fills_the_planned_wafer_starts
        """
        env = build_line(
            fab,
            single_step_spec(
                planned_wafer_starts=5,
                lots=[LotSpec("LOT-001", 5, release=False)],
            ),
        )
        assert_lot_state(env.lots[0], flow_state="PLANNED")

        released = fab.release_lot(env.lots[0]["id"], env.plan["id"])

        assert_lot_state(released, flow_state="RELEASED", current_step_seq=0)
        assert_timestamp_equals(
            released["released_at"], "2026-08-01T00:00:00Z", "released_at"
        )
        plan = fab.read_plan(env.plan["id"])
        assert plan["released_wafer_starts"] == 5
        assert plan["status"] == "CLOSED"


# --------------------------------------------------------------------------
# The operator: two independent dimensions on one row
# --------------------------------------------------------------------------


class TestOperatorDimensions:
    def test_gowning_cycles_freely_while_certification_stands_apart(self, fab):
        """Three gowning moves leave cert_status alone, and a suspension leaves gowning alone.

        PRD: "Otherwise the two dimensions do not interfere: a suspension leaves
        the recorded `gown_state` and `gowned_at` exactly as they were, so an
        operator suspended while gowned is still recorded as `GOWNED` and is
        blocked from floor actions by the certification check alone."

        Design: Corner/state_machines/operator_cert_and_gown_dimensions_advance_independently
        """
        fab.set_clock("2026-08-01T00:00:00Z")
        operator = fab.operator("OP-001", "Ada Fabrizio", ["LITHO", "ETCH", "CMP"], gowned=False)
        assert_fields(operator, cert_status="ACTIVE", gown_state="STREET")
        assert_nulls(operator, "gowned_at")

        gowned = fab.gown(operator["id"], "GOWNED")
        assert_fields(gowned, gown_state="GOWNED", cert_status="ACTIVE")
        assert_timestamp_equals(
            gowned["gowned_at"], "2026-08-01T00:00:00Z", "gowned_at"
        )
        street = fab.gown(operator["id"], "STREET")
        assert_fields(street, gown_state="STREET", cert_status="ACTIVE")
        regowned = fab.gown(operator["id"], "GOWNED")
        assert_fields(regowned, gown_state="GOWNED", cert_status="ACTIVE")

        suspended = fab.set_cert_status(operator["id"], "SUSPENDED")

        assert_fields(suspended, cert_status="SUSPENDED", gown_state="GOWNED")
        assert suspended["certified_tool_types"] == ["LITHO", "ETCH", "CMP"]


# --------------------------------------------------------------------------
# The change notice: SUBMITTED, REVISION_REQUESTED, APPROVED, IMPLEMENTED
# --------------------------------------------------------------------------


class TestChangeRequestLifecycle:
    def test_an_approved_notice_cannot_be_sent_back_for_revision(self, fab):
        """Review is over once the notice is approved, and the recipe stays restricted.

        PRD: "Sending a notice back for revision requires a `reviewer_comment`
        and requires the notice to be `SUBMITTED`; an inadmissible `status` at
        any point in this workflow is `ERR_CHANGE_REQUEST_INVALID_STATE`."

        Design: Corner/state_machines/request_revision_on_an_approved_change_request_returns_change_request_invalid_state
        """
        recipe = fab.recipe("ETCH-200", "ETCH", 100.0, 100)
        notice = fab.change_request(
            recipe["id"], "MAJOR", 110.0, "Widen etch depth by ten percent"
        )
        approved = fab.approve_change_request(
            notice["id"], recipe["version"], approver_user_id=USER_QUALITY_MANAGER
        )
        assert approved["status"] == "APPROVED"
        assert approved["pinned_recipe_revision"] == 1

        response = fab.client.request_change_revision(
            notice["id"],
            request_revision_payload("Please re-run the DOE"),
            quality_manager_headers(),
        )

        body = validate_error(response, ERR_CHANGE_REQUEST_INVALID_STATE, 409)
        assert body["error_id"] == ERR_CHANGE_REQUEST_INVALID_STATE
        stored = fab.read_change_request(notice["id"])
        assert_fields(stored, status="APPROVED", revision_round=0)
        assert_fields(
            fab.read_recipe(recipe["id"]),
            status="RESTRICTED",
            restricted_reason="ECN_PENDING_IMPLEMENTATION",
        )


# --------------------------------------------------------------------------
# The step run: OPEN, COMPLETED, ABORTED
# --------------------------------------------------------------------------


class TestStepRunLifecycle:
    def test_a_completed_run_cannot_afterwards_be_aborted(self, fab):
        """COMPLETED is terminal, so the settled ledger is not disturbed.

        PRD: "Aborting closes the run without charging it. An operator-driven
        abort carries an `abort_reason`, requires the run to be `OPEN`, and
        requires `X-User-ID` to equal the run's `operator_id`; the same
        transition also fires as a cascade when the run's chamber leaves
        `QUALIFIED` through containment, or when the run's lot is scrapped."

        Design: Corner/state_machines/abort_after_track_out_returns_step_run_not_open
        """
        env = build_line(fab, single_step_spec())
        operator_id = env.operators[0]["id"]
        run = open_run(fab, env, step_ix=0, lot_ix=0)
        fab.set_clock("2026-08-01T02:00:00Z")
        closed = fab.track_out(run["id"], operator_id)

        assert closed["status"] == "COMPLETED"
        assert_hours(closed["actual_hours"], 2.00, "actual_hours")
        settled = fab.read_equipment(env.equipments[0]["id"])
        assert_hours(
            settled["available_capacity_hours"], 718.00, "available_capacity_hours"
        )
        assert_hours(settled["hours_since_pm"], 2.0, "hours_since_pm")
        assert settled["state"] == "IDLE"

        response = fab.client.abort_step_run(
            run["id"],
            abort_payload("Late scrap decision"),
            make_operator_headers(operator_id),
        )

        body = validate_error(response, ERR_STEP_RUN_NOT_OPEN, 409)
        assert body["error_id"] == ERR_STEP_RUN_NOT_OPEN
        assert_hours(
            fab.read_equipment(env.equipments[0]["id"])["available_capacity_hours"],
            718.00,
            "available_capacity_hours",
        )
        assert fab.read_step_run(run["id"])["status"] == "COMPLETED"
        assert_lot_state(
            fab.read_lot(env.lots[0]["id"]), flow_state="AT_SORT", current_step_seq=10
        )


# --------------------------------------------------------------------------
# The sort run and the excursion
# --------------------------------------------------------------------------


class TestSortAndExcursionLifecycle:
    def test_binning_the_sort_run_completes_the_lot(self, fab):
        """The waterfall distributes every good die and closes the lot out.

        PRD: "Binning drives the run `SORTED → BINNED`, which is terminal, and
        increments its `version` by 1. It also completes the lot: the lot is
        driven `AT_SORT → COMPLETED`, its `completed_at` is set to the current
        logical instant, its `actual_cycle_time_days` is pinned from the
        chronological variant of the cycle-time calculation described in §3.5,
        and its `version` increments by 1."

        Design: Corner/state_machines/die_sort_and_bin_drive_the_lot_from_at_sort_to_completed
        """
        env = build_line(fab, single_step_spec())
        operator_id = env.operators[0]["id"]
        run = open_run(fab, env, step_ix=0, lot_ix=0)
        fab.set_clock("2026-08-01T02:00:00Z")
        assert fab.track_out(run["id"], operator_id)["status"] == "COMPLETED"

        sort_run = fab.die_sort(
            env.lots[0]["id"],
            [
                wafer_result(1, 100, 90, edge_ring_fails=10),
                wafer_result(2, 100, 90, edge_ring_fails=10),
                wafer_result(3, 100, 90, edge_ring_fails=10),
            ],
            gross_die_per_wafer=100,
            baseline_yield=0.92,
        )
        # Each wafer yields 0.9000, and 0.02 / 0.92 is a 0.0217 loss ratio.
        assert_ratio(sort_run["sort_yield"], 0.9000, "sort_yield")
        assert sort_run["good_die_total"] == 270
        assert_ratio(sort_run["yield_loss_ratio"], 0.0217, "yield_loss_ratio")
        assert sort_run["dominant_signature"] == "EDGE_RING"
        assert sort_run["status"] == "SORTED"

        binned = fab.bin_sort_run(sort_run["id"], 50, 60)

        assert_fields(
            binned, premium_die=50, standard_die=60, value_die=160, status="BINNED"
        )
        lot = fab.read_lot(env.lots[0]["id"])
        assert_lot_state(lot, flow_state="COMPLETED")
        assert_timestamp_equals(
            lot["completed_at"], "2026-08-01T02:00:00Z", "completed_at"
        )
        # Two hours out of a 24-hour day.
        assert_days(lot["actual_cycle_time_days"], 0.083, "actual_cycle_time_days")
        # A 0.0217 loss ratio is far below the 0.10 excursion threshold.
        assert fab.count(
            fab.client.list_excursions(
                yield_engineer_headers(), {"lot_id": env.lots[0]["id"]}
            )
        ) == 0

    def test_an_uncontained_excursion_cannot_be_dispositioned(self, fab):
        """Disposition is the second half of a two-person decision, so OPEN is too early.

        PRD: "It requires the excursion to be `CONTAINED`, and carries a
        `disposition` of `CONTINUE`, `REWORK` or `SCRAP` together with a
        `root_cause_note` recording the failure analysis."

        Design: Corner/state_machines/disposition_before_containment_returns_excursion_invalid_state
        """
        env = build_line(fab, metrology_step_spec())
        raised = raise_spc_excursion(fab, env, 112.0, step_ix=0, lot_ix=0)

        assert raised.measurement["classification"] == "OUT_OF_SPEC"
        assert_ratio(raised.measurement["deviation_sigma"], 6.0000, "deviation_sigma")
        # 60.0 at the capped deviation ratio, 3.0 for the one lot, 10.0 out of spec.
        assert_fields(
            raised.excursion,
            status="OPEN",
            severity_variant="PROVISIONAL",
            severity_band="HIGH",
            affected_lot_count=1,
        )
        assert_hours(raised.excursion["severity_score"], 73.00, "severity_score")

        response = fab.client.disposition_excursion(
            raised.excursion["id"],
            disposition_payload("CONTINUE", "Looks like a metrology artefact"),
            yield_engineer_headers(),
        )

        body = validate_error(response, ERR_EXCURSION_INVALID_STATE, 409)
        assert body["error_id"] == ERR_EXCURSION_INVALID_STATE
        stored = fab.read_excursion(raised.excursion["id"])
        assert_fields(
            stored, status="OPEN", disposition="NONE", containment_scope="NONE"
        )
        assert_nulls(stored, "dispositioned_by_user_id")
        assert fab.read_chart(env.charts[0]["id"])["status"] == "MONITORING"
