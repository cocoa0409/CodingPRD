"""Refusals on the shop floor: the operator gate, the run gate and change control.

Every scenario stands a working line up, breaks exactly one admissibility
condition, and then proves nothing at all was written.
"""

from test_helpers import (
    ChartSpec,
    OperatorSpec,
    StepSpec,
    build_line,
    make_operator_headers,
    metrology_step_spec,
    open_run,
    process_engineer_headers,
    single_step_spec,
)
from test_helpers.api_errors import (
    ERR_CHAMBER_QUAL_EXPIRED,
    ERR_CHART_STEP_MISMATCH,
    ERR_DUPLICATE_CODE,
    ERR_EQUIPMENT_CAPACITY_EXHAUSTED,
    ERR_METROLOGY_MISSING,
    ERR_METROLOGY_NOT_REQUIRED,
    ERR_OPERATOR_CERT_INACTIVE,
    ERR_OPERATOR_IDENTITY_MISMATCH,
    ERR_OPERATOR_NOT_CERTIFIED,
    ERR_OPERATOR_NOT_GOWNED,
    ERR_PINNED_REVISION_STALE,
    ERR_STEP_FLOW_MISMATCH,
)
from test_helpers.assertions import (
    assert_fields,
    assert_hours,
    assert_lot_state,
    assert_nulls,
    assert_timestamp_equals,
)
from test_helpers.factories import (
    measurement_payload,
    recipe_payload,
    step_run_payload,
)
from prd_bench_local_runner.testing.validators import validate_error


# --------------------------------------------------------------------------
# The two independent operator dimensions
# --------------------------------------------------------------------------


class TestOperatorGate:
    def test_an_ungowned_operator_cannot_open_a_run(self, fab):
        """Certification is fine but the operator never gowned, so the floor is shut.

        PRD: "Opening a run, tracking out and recording a measurement all require
        `cert_status` of `ACTIVE` — otherwise `ERR_OPERATOR_CERT_INACTIVE` (HTTP
        403) — and all require `gown_state` of `GOWNED` — otherwise
        `ERR_OPERATOR_NOT_GOWNED` (HTTP 403)."

        Design: Corner/validations/track_in_by_an_ungowned_operator_returns_operator_not_gowned
        """
        env = build_line(
            fab,
            single_step_spec(
                operators=[OperatorSpec("OP-001", "Ada Fabrizio", gowned=False)]
            ),
        )
        assert_fields(env.operators[0], gown_state="STREET", cert_status="ACTIVE")

        response = fab.client.create_step_run(
            step_run_payload(
                env.lots[0]["id"], env.steps[0]["id"], env.operators[0]["id"]
            ),
            make_operator_headers(env.operators[0]["id"]),
        )

        body = validate_error(response, ERR_OPERATOR_NOT_GOWNED, 403)
        assert body["error_id"] == ERR_OPERATOR_NOT_GOWNED
        assert fab.read_chamber(env.chambers[0]["id"])["occupancy_state"] == "FREE"
        tool = fab.read_equipment(env.equipments[0]["id"])
        assert tool["state"] == "IDLE"
        assert_hours(
            tool["available_capacity_hours"], 720.00, "available_capacity_hours"
        )
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), flow_state="RELEASED")

    def test_a_suspended_operator_cannot_open_a_run_even_while_gowned(self, fab):
        """Suspending certification leaves the gowning dimension untouched.

        PRD: "The cleanroom protocol has two independent dimensions on an
        operator, and both are enforced before any floor action."

        PRD: "Opening a run, tracking out and recording a measurement all require
        `cert_status` of `ACTIVE` — otherwise `ERR_OPERATOR_CERT_INACTIVE` (HTTP
        403) — and all require `gown_state` of `GOWNED` — otherwise
        `ERR_OPERATOR_NOT_GOWNED` (HTTP 403)."

        Design: Corner/validations/track_in_by_a_suspended_operator_returns_operator_cert_inactive
        """
        env = build_line(fab, single_step_spec())
        suspended = fab.set_cert_status(env.operators[0]["id"], "SUSPENDED")
        assert_fields(suspended, cert_status="SUSPENDED", gown_state="GOWNED")

        response = fab.client.create_step_run(
            step_run_payload(
                env.lots[0]["id"], env.steps[0]["id"], env.operators[0]["id"]
            ),
            make_operator_headers(env.operators[0]["id"]),
        )

        body = validate_error(response, ERR_OPERATOR_CERT_INACTIVE, 403)
        assert body["error_id"] == ERR_OPERATOR_CERT_INACTIVE
        assert fab.read_operator(env.operators[0]["id"])["gown_state"] == "GOWNED"
        assert fab.read_chamber(env.chambers[0]["id"])["occupancy_state"] == "FREE"
        assert fab.read_equipment(env.equipments[0]["id"])["state"] == "IDLE"

    def test_an_operator_uncertified_for_the_tool_class_cannot_open_a_run(self, fab):
        """A CMP-only badge cannot work a step whose recipe is a LITHO program.

        PRD: "The step's recipe `tool_type` must appear in the operator's
        `certified_tool_types`, otherwise `ERR_OPERATOR_NOT_CERTIFIED`."

        Design: Corner/validations/track_in_on_an_uncertified_tool_type_returns_operator_not_certified
        """
        env = build_line(
            fab,
            single_step_spec(
                operators=[OperatorSpec("OP-002", "Colin Polisher", ["CMP"])]
            ),
        )
        assert env.operators[0]["gown_state"] == "GOWNED"
        assert "LITHO" not in env.operators[0]["certified_tool_types"]
        assert env.recipes[0]["tool_type"] == "LITHO"

        response = fab.client.create_step_run(
            step_run_payload(
                env.lots[0]["id"], env.steps[0]["id"], env.operators[0]["id"]
            ),
            make_operator_headers(env.operators[0]["id"]),
        )

        body = validate_error(response, ERR_OPERATOR_NOT_CERTIFIED, 403)
        assert body["error_id"] == ERR_OPERATOR_NOT_CERTIFIED
        assert fab.read_chamber(env.chambers[0]["id"])["occupancy_state"] == "FREE"
        assert fab.read_equipment(env.equipments[0]["id"])["state"] == "IDLE"

    def test_nobody_may_open_a_run_on_another_operators_behalf(self, fab):
        """Both badges are perfectly qualified; only the identity match is missing.

        PRD: "Concretely, an `Operator` may only open a step run whose
        `operator_id` equals their own `X-User-ID`, may only track out, abort or
        record measurements against a run whose `operator_id` equals their
        `X-User-ID`, and may only patch the `Operator` row whose `id` equals their
        `X-User-ID`."

        PRD: "A violation of any of these is rejected with
        `ERR_OPERATOR_IDENTITY_MISMATCH` (HTTP 403)."

        Design: Corner/validations/track_in_on_behalf_of_another_operator_returns_identity_mismatch
        """
        env = build_line(
            fab,
            single_step_spec(
                operators=[
                    OperatorSpec("OP-001", "Ada Fabrizio"),
                    OperatorSpec("OP-002", "Grace Litho"),
                ]
            ),
        )

        response = fab.client.create_step_run(
            step_run_payload(
                env.lots[0]["id"], env.steps[0]["id"], env.operators[1]["id"]
            ),
            make_operator_headers(env.operators[0]["id"]),
        )

        body = validate_error(response, ERR_OPERATOR_IDENTITY_MISMATCH, 403)
        assert body["error_id"] == ERR_OPERATOR_IDENTITY_MISMATCH
        assert fab.count(
            fab.client.list_step_runs(
                process_engineer_headers(), {"lot_id": env.lots[0]["id"]}
            )
        ) == 0
        assert fab.read_chamber(env.chambers[0]["id"])["occupancy_state"] == "FREE"
        assert_hours(
            fab.read_equipment(env.equipments[0]["id"])["available_capacity_hours"],
            720.00,
            "available_capacity_hours",
        )


# --------------------------------------------------------------------------
# The run gate: routing, qualification windows and capacity
# --------------------------------------------------------------------------


class TestRunAdmissibility:
    def test_a_step_belonging_to_another_flow_cannot_be_opened(self, fab):
        """The step is real and identically shaped, but it is not on the lot's route.

        PRD: "The step must belong to the lot's flow, otherwise
        `ERR_STEP_FLOW_MISMATCH`."

        Design: Corner/validations/track_in_with_a_step_from_another_flow_returns_step_flow_mismatch
        """
        env = build_line(fab, single_step_spec())
        other_flow = fab.flow("FLOW-B", "LOGIC_N5")
        foreign_step = fab.step(
            other_flow["id"], env.recipes[0]["id"], 10, "LITHO-1", 2.0
        )
        fab.release_flow(other_flow["id"])

        response = fab.client.create_step_run(
            step_run_payload(
                env.lots[0]["id"], foreign_step["id"], env.operators[0]["id"]
            ),
            make_operator_headers(env.operators[0]["id"]),
        )

        body = validate_error(response, ERR_STEP_FLOW_MISMATCH, 422)
        assert body["error_id"] == ERR_STEP_FLOW_MISMATCH
        assert fab.count(
            fab.client.list_step_runs(
                process_engineer_headers(), {"lot_id": env.lots[0]["id"]}
            )
        ) == 0
        assert_lot_state(
            fab.read_lot(env.lots[0]["id"]),
            flow_state="RELEASED",
            current_step_seq=0,
        )

    def test_a_lapsed_qualification_window_closes_the_only_chamber(self, fab):
        """One day past expiry the chamber lapses on evaluation and dispatch fails.

        PRD: "Whenever a chamber is evaluated as a dispatch candidate and the
        current logical instant is at or after its `qual_expires_at`, the chamber
        is first driven `QUALIFIED → QUAL_EXPIRED` and then excluded from the
        candidate set, with its `version` incremented."

        PRD: "If the candidate set is empty because every otherwise-eligible
        chamber's qualification has lapsed, the rejection is
        `ERR_CHAMBER_QUAL_EXPIRED`; if it is empty for any other reason, the
        rejection is `ERR_NO_QUALIFIED_CHAMBER`, and in either case no run is
        created."

        Design: Corner/validations/track_in_after_the_chamber_qualification_lapses_returns_chamber_qual_expired
        """
        env = build_line(fab, single_step_spec())
        assert env.chambers[0]["qual_state"] == "QUALIFIED"
        # 100 qualification days counted from 2026-08-01.
        assert_timestamp_equals(
            env.chambers[0]["qual_expires_at"],
            "2026-11-09T00:00:00Z",
            "qual_expires_at",
        )
        fab.set_clock("2026-11-10T00:00:00Z")

        response = fab.client.create_step_run(
            step_run_payload(
                env.lots[0]["id"], env.steps[0]["id"], env.operators[0]["id"]
            ),
            make_operator_headers(env.operators[0]["id"]),
        )

        body = validate_error(response, ERR_CHAMBER_QUAL_EXPIRED, 409)
        assert body["error_id"] == ERR_CHAMBER_QUAL_EXPIRED
        lapsed = fab.read_chamber(env.chambers[0]["id"])
        assert_fields(lapsed, qual_state="QUAL_EXPIRED", occupancy_state="FREE")
        assert_hours(
            fab.read_equipment(env.equipments[0]["id"])["available_capacity_hours"],
            720.00,
            "available_capacity_hours",
        )
        assert fab.count(
            fab.client.list_step_runs(
                process_engineer_headers(), {"lot_id": env.lots[0]["id"]}
            )
        ) == 0

    def test_a_step_costing_more_hours_than_the_tool_holds_is_refused(self, fab):
        """800 standard hours against a 720.00 ledger cannot be reserved.

        PRD: "One fiscal check remains: the winning chamber's tool must have
        `available_capacity_hours` greater than or equal to the step's
        `standard_hours`, otherwise `ERR_EQUIPMENT_CAPACITY_EXHAUSTED`."

        Design: Corner/validations/track_in_needing_more_hours_than_the_tool_has_returns_equipment_capacity_exhausted
        """
        env = build_line(
            fab,
            single_step_spec(
                steps=[StepSpec(10, "LITHO-1", 800.0)],
                planned_wafer_starts=10,
                capacity_budget_hours=20000.0,
            ),
        )
        assert_hours(
            fab.read_equipment(env.equipments[0]["id"])["available_capacity_hours"],
            720.0,
            "available_capacity_hours",
        )
        assert env.chambers[0]["qual_state"] == "QUALIFIED"
        # 10 starts times 800.0 hours is 8000.00 against a 20000.0 budget.
        assert_hours(env.plan["committed_hours"], 8000.00, "committed_hours")
        assert env.plan["commitment_tier"] == "TIER_0"

        response = fab.client.create_step_run(
            step_run_payload(
                env.lots[0]["id"], env.steps[0]["id"], env.operators[0]["id"]
            ),
            make_operator_headers(env.operators[0]["id"]),
        )

        body = validate_error(response, ERR_EQUIPMENT_CAPACITY_EXHAUSTED, 409)
        assert body["error_id"] == ERR_EQUIPMENT_CAPACITY_EXHAUSTED
        tool = fab.read_equipment(env.equipments[0]["id"])
        assert_hours(
            tool["available_capacity_hours"], 720.00, "available_capacity_hours"
        )
        assert tool["state"] == "IDLE"
        assert fab.read_chamber(env.chambers[0]["id"])["occupancy_state"] == "FREE"
        assert_lot_state(
            fab.read_lot(env.lots[0]["id"]),
            flow_state="RELEASED",
            current_step_seq=0,
        )

    def test_a_metrology_step_cannot_be_tracked_out_unmeasured(self, fab):
        """The run stays open and the reservation stays outstanding.

        PRD: "Tracking out closes the run. It requires the run's `status` to be
        `OPEN`, otherwise `ERR_STEP_RUN_NOT_OPEN`; requires the caller's
        `X-User-ID` to equal the run's `operator_id`; requires the operator to be
        `ACTIVE` and `GOWNED`; and, when the step's `metrology_required` is true,
        requires at least one measurement to exist against the run, otherwise
        `ERR_METROLOGY_MISSING`."

        Design: Corner/validations/track_out_without_a_measurement_returns_metrology_missing
        """
        env = build_line(fab, metrology_step_spec())
        run = open_run(fab, env, step_ix=0, lot_ix=0)

        response = fab.client.track_out(
            run["id"], make_operator_headers(env.operators[0]["id"])
        )

        body = validate_error(response, ERR_METROLOGY_MISSING, 409)
        assert body["error_id"] == ERR_METROLOGY_MISSING
        still_open = fab.read_step_run(run["id"])
        assert still_open["status"] == "OPEN"
        assert_nulls(still_open, "actual_hours", "tracked_out_at")
        assert fab.read_chamber(env.chambers[0]["id"])["occupancy_state"] == "OCCUPIED"
        tool = fab.read_equipment(env.equipments[0]["id"])
        assert_hours(
            tool["available_capacity_hours"], 718.00, "available_capacity_hours"
        )
        assert_hours(tool["hours_since_pm"], 0.0, "hours_since_pm")
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), current_step_seq=0)


# --------------------------------------------------------------------------
# Measurement admissibility
# --------------------------------------------------------------------------


class TestMeasurementAdmissibility:
    def test_a_reading_on_a_step_that_declares_no_metrology_is_refused(self, fab):
        """The chart exists on the step, but the step never asked for metrology.

        PRD: "The step must actually have `metrology_required` true, otherwise
        `ERR_METROLOGY_NOT_REQUIRED`."

        Design: Corner/validations/measurement_on_a_non_metrology_step_returns_metrology_not_required
        """
        env = build_line(
            fab, single_step_spec(charts=[ChartSpec(step_ix=0, param_name="CD")])
        )
        assert env.steps[0]["metrology_required"] is False
        run = open_run(fab, env, step_ix=0, lot_ix=0)

        response = fab.client.create_measurement(
            measurement_payload(run["id"], env.charts[0]["id"], 100.0),
            make_operator_headers(env.operators[0]["id"]),
        )

        body = validate_error(response, ERR_METROLOGY_NOT_REQUIRED, 422)
        assert body["error_id"] == ERR_METROLOGY_NOT_REQUIRED
        assert fab.count(
            fab.client.list_measurements(
                process_engineer_headers(), {"step_run_id": run["id"]}
            )
        ) == 0
        assert fab.read_step_run(run["id"])["status"] == "OPEN"

    def test_a_chart_belonging_to_a_later_step_cannot_classify_this_run(self, fab):
        """The run sits on step 10 while the chart monitors step 20.

        PRD: "The chart's `step_id` must equal the run's `step_id`, otherwise
        `ERR_CHART_STEP_MISMATCH`."

        Design: Corner/validations/measurement_against_another_steps_chart_returns_chart_step_mismatch
        """
        env = build_line(
            fab,
            single_step_spec(
                steps=[
                    StepSpec(10, "LITHO-1", 2.0, metrology_required=True),
                    StepSpec(20, "LITHO-2", 2.0, metrology_required=True),
                ],
                charts=[ChartSpec(step_ix=1, param_name="CD-20")],
            ),
        )
        run = open_run(fab, env, step_ix=0, lot_ix=0)
        assert run["step_id"] == env.steps[0]["id"]
        assert env.charts[0]["step_id"] == env.steps[1]["id"]

        response = fab.client.create_measurement(
            measurement_payload(run["id"], env.charts[0]["id"], 100.0),
            make_operator_headers(env.operators[0]["id"]),
        )

        body = validate_error(response, ERR_CHART_STEP_MISMATCH, 422)
        assert body["error_id"] == ERR_CHART_STEP_MISMATCH
        assert fab.count(
            fab.client.list_measurements(
                process_engineer_headers(), {"spc_chart_id": env.charts[0]["id"]}
            )
        ) == 0
        assert fab.read_chart(env.charts[0]["id"])["violation_count"] == 0
        assert fab.read_step_run(run["id"])["status"] == "OPEN"


# --------------------------------------------------------------------------
# Recipe identity and change control
# --------------------------------------------------------------------------


class TestRecipeIdentity:
    def test_a_second_recipe_cannot_reuse_a_live_recipe_code(self, fab):
        """Business-key uniqueness is global, so the tool class cannot rescue it.

        PRD: "A duplicate `recipe_code` is `ERR_DUPLICATE_CODE`."

        Design: Corner/validations/reusing_a_recipe_code_returns_duplicate_code
        """
        first = fab.recipe("LITHO-100", "LITHO", 50.0)
        assert first["recipe_code"] == "LITHO-100"

        response = fab.client.create_recipe(
            recipe_payload("LITHO-100", "ETCH", 100.0, drop=["qual_expiry_days"]),
            process_engineer_headers(),
        )

        body = validate_error(response, ERR_DUPLICATE_CODE, 409)
        assert body["error_id"] == ERR_DUPLICATE_CODE
        assert fab.count(fab.client.list_recipes(process_engineer_headers())) == 1
        stored = fab.read_recipe(first["id"])
        assert stored["tool_type"] == "LITHO"
        assert_hours(stored["target_value"], 50.00, "target_value")


class TestChangeControlStaleness:
    def test_the_second_notice_cannot_implement_on_a_moved_revision(self, fab):
        """Two notices pin revision 1; the first implementation invalidates the second.

        PRD: "A `ProcessEngineer` implements an `APPROVED` notice, and the server
        first checks that the recipe's `revision` still equals the notice's
        `pinned_recipe_revision`; if a sibling notice has been implemented in the
        meantime and moved the revision, the request is rejected with
        `ERR_PINNED_REVISION_STALE`."

        Design: Corner/validations/implementing_the_second_ecn_after_the_first_returns_pinned_revision_stale
        """
        recipe = fab.recipe("LITHO-100", "LITHO", 100.0)
        assert recipe["revision"] == 1
        first = fab.change_request(recipe["id"], "MINOR", 100.5)
        second = fab.change_request(recipe["id"], "MINOR", 101.0)
        # A half-unit move on a 100.00 target is a twentieth of the saturating
        # ten-percent move, so 10.0 plus 25.0 times 0.05 is 11.25.
        assert_hours(first["risk_score"], 11.25, "risk_score")
        assert first["impact_lot_count"] == 0
        # A full unit move doubles the second term to 2.50.
        assert_hours(second["risk_score"], 12.50, "risk_score")

        approved_first = fab.approve_change_request(first["id"], recipe["version"])
        approved_second = fab.approve_change_request(
            second["id"], fab.read_recipe(recipe["id"])["version"]
        )
        assert approved_first["pinned_recipe_revision"] == 1
        assert approved_second["pinned_recipe_revision"] == 1
        assert fab.read_recipe(recipe["id"])["status"] == "RESTRICTED"
        implemented = fab.implement_change_request(first["id"])
        assert implemented["status"] == "IMPLEMENTED"
        assert fab.read_change_request(second["id"])["status"] == "APPROVED"

        response = fab.client.implement_change_request(
            second["id"], process_engineer_headers()
        )

        body = validate_error(response, ERR_PINNED_REVISION_STALE, 409)
        assert body["error_id"] == ERR_PINNED_REVISION_STALE
        stored = fab.read_recipe(recipe["id"])
        assert_fields(
            stored, revision=2, status="QUALIFIED", restricted_reason="NONE"
        )
        assert_hours(stored["target_value"], 100.50, "target_value")
        assert fab.read_change_request(second["id"])["status"] == "APPROVED"
