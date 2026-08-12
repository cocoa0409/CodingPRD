"""Burn-day gates: briefing preconditions, weather freshness/prescription, go/no-go
evaluation, scheduling windows, and clock sweeps (PRD §2.5, §3.6, §3.7)."""
from test_helpers import (
    ANY_READER_HEADERS,
    TEST_USERS,
    ApiErrorId,
    create_ignition_plan_payload,
    create_smoke_approval_payload,
    create_weather_observation_payload,
    ctx_add_contingency,
    ctx_add_execution,
    ctx_add_ignition,
    ctx_add_order,
    ctx_add_permit,
    ctx_add_smoke,
    ctx_author,
    ctx_brief,
    ctx_go_no_go,
    ctx_reviewer,
    ctx_set_burn_day,
    go_no_go_payload,
    set_clock_payload,
    setup_approved_plan_ctx,
    setup_burn_ready_ctx,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
BURN_DAY = "2026-05-12"
BURN_TS = "2026-05-12T07:30:00Z"


def _ready_execution(api, smoke=True, smoke_date=BURN_DAY, fill="full"):
    """Burn-ready execution SCHEDULED for 2026-05-12 (smoke/permit/order per flags)."""
    ctx = setup_approved_plan_ctx()
    ctx_add_contingency(ctx)
    ctx_add_ignition(ctx)
    ctx_add_permit(ctx, notifications_required=1)
    if smoke:
        ctx_add_smoke(ctx, date=smoke_date)
    ctx_add_order(ctx, fill=fill)
    ctx_add_execution(ctx, date=BURN_DAY)
    return ctx


class TestWeatherPrescriptionBoundary:
    def test_wind_speed_exactly_at_max_passes(self, api):
        """PRD §3.6: "Every bound is inclusive — a reading exactly equal to its bound
        passes."

        Design: Difficulty/boundary_precision_check/wind_speed_exactly_at_max_passes
        """
        ctx = setup_burn_ready_ctx()
        obs = ctx_set_burn_day(ctx, obs_overrides={"wind_mph": 15})  # == max_wind_mph 15
        assert obs["in_prescription"] is True
        ctx_brief(ctx)
        checklist = ctx_go_no_go(ctx)
        assert checklist["verdict"] == "GO"
        assert ctx["execution"]["phase"] == "TEST_FIRE"

    def test_wind_speed_one_over_max_out_of_prescription(self, api):
        """PRD §3.6: "The system computes `in_prescription` against the plan's
        prescription: sustained wind no greater than `max_wind_mph`"
        PRD §3.6: "That latest observation must be in prescription
        (`ERR_WEATHER_OUT_OF_PRESCRIPTION`)."

        Design: Difficulty/boundary_precision_check/wind_speed_exactly_at_max_passes
        """
        ctx = setup_burn_ready_ctx()
        obs = ctx_set_burn_day(ctx, obs_overrides={"wind_mph": 16})  # one over the max
        assert obs["in_prescription"] is False
        ctx_brief(ctx)
        validate_error(api.submit_go_no_go(
            ctx["execution"]["id"], go_no_go_payload(), ctx_author(ctx)),
            ApiErrorId.ERR_WEATHER_OUT_OF_PRESCRIPTION)


class TestBriefSmokeGate:
    def test_brief_requires_smoke_approval_valid(self, api):
        """PRD §3.6: "A smoke approval in `APPROVED` or `CONDITIONALLY_APPROVED` must
        exist for the plan whose `requested_burn_date` equals the `scheduled_date`
        (`ERR_SMOKE_APPROVAL_NOT_VALID`)."

        Design: Difficulty/cross_entity_state_dependency/brief_requires_smoke_approval_valid
        """
        ctx = _ready_execution(api, smoke=False)  # smoke approval never requested
        ctx_set_burn_day(ctx)
        validate_error(api.brief_execution(ctx["execution"]["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_SMOKE_APPROVAL_NOT_VALID)
        after = validate_success(api.get_execution(ctx["execution"]["id"], ANY_READER_HEADERS), 200)
        assert after["phase"] == "SCHEDULED"

    def test_brief_rejected_when_smoke_date_mismatched(self, api):
        """PRD §3.6: "A smoke approval in `APPROVED` or `CONDITIONALLY_APPROVED` must
        exist for the plan whose `requested_burn_date` equals the `scheduled_date`
        (`ERR_SMOKE_APPROVAL_NOT_VALID`)."

        Design: Difficulty/cross_entity_state_dependency/brief_requires_smoke_approval_valid
        """
        ctx = _ready_execution(api, smoke=True, smoke_date="2026-05-13")
        ctx_set_burn_day(ctx)
        validate_error(api.brief_execution(ctx["execution"]["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_SMOKE_APPROVAL_NOT_VALID)


class TestVersionPinAtBrief:
    def _replace_ignition_after_scheduling(self, api, ctx):
        """Re-file the ignition plan (advancing the plan version the execution pinned)."""
        plan = validate_success(api.get_burn_plan(ctx["plan"]["id"], ANY_READER_HEADERS), 200)
        ign2 = validate_success(api.create_ignition_plan(
            plan["id"], create_ignition_plan_payload(
                plan["version"], ignition_method="AERIAL", test_fire_required=False,
                steps=[{"step_index": 1, "zone_label": "south", "technique": "sphere"}]),
            ctx_author(ctx)), 201)
        validate_success(api.accept_ignition_plan(ign2["id"], ctx_reviewer(ctx)), 200)

    def test_version_pin_blocks_brief_after_plan_mutation(self, api):
        """PRD §3.6: "The pinned `plan_version_at_schedule` must still equal the plan's
        current `version` — a plan edited since scheduling is rejected with
        `ERR_STALE_PLAN_VERSION`, forcing re-scheduling against the plan as it now
        stands."

        Design: Corner/cross_cutting_layers/version_pin_blocks_brief_after_plan_mutation
        """
        ctx = setup_burn_ready_ctx()
        pin = ctx["execution"]["plan_version_at_schedule"]
        self._replace_ignition_after_scheduling(api, ctx)
        plan = validate_success(api.get_burn_plan(ctx["plan"]["id"], ANY_READER_HEADERS), 200)
        assert plan["version"] != pin  # the ignition re-file advanced the plan
        ctx_set_burn_day(ctx)
        validate_error(api.brief_execution(ctx["execution"]["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_STALE_PLAN_VERSION)

    def test_brief_succeeds_after_reschedule_repins(self, api):
        """PRD §3.6: "a plan edited since scheduling is rejected with
        `ERR_STALE_PLAN_VERSION`, forcing re-scheduling against the plan as it now
        stands."
        PRD §3.6: "A successful briefing moves the execution to `BRIEFED`."

        Design: Corner/cross_cutting_layers/version_pin_blocks_brief_after_plan_mutation
        """
        ctx = setup_burn_ready_ctx()
        self._replace_ignition_after_scheduling(api, ctx)
        ctx_set_burn_day(ctx)
        validate_error(api.brief_execution(ctx["execution"]["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_STALE_PLAN_VERSION)
        # Cancel the stale execution and reschedule: the new execution pins the
        # current plan version, so every brief gate now passes.
        validate_success(api.cancel_execution(ctx["execution"]["id"], ctx_author(ctx)), 200)
        ctx_add_execution(ctx, date=BURN_DAY)
        briefed = validate_success(api.brief_execution(ctx["execution"]["id"], ctx_author(ctx)), 200)
        assert briefed["phase"] == "BRIEFED"


class TestGoNoGoEvaluation:
    def test_observation_stale_at_61_minutes_rejected(self, api):
        """PRD §3.6: "Weather must be fresh: the latest observation — chosen by greatest
        `observed_at`, ties broken by `created_at` ascending so the later-created row wins
        — must exist and be no more than 60 minutes old against the current clock, an
        observation exactly 60 minutes old passing (`ERR_WEATHER_OBSERVATION_STALE`)."
        PRD §3.6: "A rejected evaluation records no checklist."

        Design: Corner/calculations/observation_stale_at_61_minutes_rejected
        """
        ctx = setup_burn_ready_ctx()
        validate_success(api.set_clock(set_clock_payload("2026-05-12T08:30:00Z"), ADMIN), 200)
        validate_success(api.create_weather_observation(
            ctx["execution"]["id"],
            create_weather_observation_payload(observed_at="2026-05-12T07:29:00Z"),
            ctx_author(ctx)), 201)  # 61 minutes old at the 08:30 evaluation
        ctx_brief(ctx)
        validate_error(api.submit_go_no_go(
            ctx["execution"]["id"], go_no_go_payload(), ctx_author(ctx)),
            ApiErrorId.ERR_WEATHER_OBSERVATION_STALE)
        data, meta = validate_paginated(
            api.list_checklists(ctx["execution"]["id"], ANY_READER_HEADERS))
        assert meta["total_count"] == 0
        after = validate_success(api.get_execution(ctx["execution"]["id"], ANY_READER_HEADERS), 200)
        assert after["phase"] == "BRIEFED"

    def test_gonogo_out_of_prescription_rejected(self, api):
        """PRD §3.6: "That latest observation must be in prescription
        (`ERR_WEATHER_OUT_OF_PRESCRIPTION`)."
        PRD §3.6: "A rejected evaluation records no checklist."

        Design: Corner/errors/gonogo_out_of_prescription_rejected
        """
        ctx = setup_burn_ready_ctx()
        obs = ctx_set_burn_day(ctx, obs_overrides={"wind_mph": 99})
        assert obs["in_prescription"] is False
        ctx_brief(ctx)
        validate_error(api.submit_go_no_go(
            ctx["execution"]["id"], go_no_go_payload(), ctx_author(ctx)),
            ApiErrorId.ERR_WEATHER_OUT_OF_PRESCRIPTION)
        _data, meta = validate_paginated(
            api.list_checklists(ctx["execution"]["id"], ANY_READER_HEADERS))
        assert meta["total_count"] == 0

    def test_gonogo_rejected_on_incomplete_checklist(self, api):
        """PRD §3.6: "The author submits `checklist_answers` covering exactly the six
        required items — `permit_verified`, `crew_briefed`, `communications_check`,
        `escape_routes_reviewed`, `weather_within_prescription`, `holding_resources_ready`
        — each answered `PASS` or `FAIL`; missing items or invalid result values are
        rejected with `ERR_INCOMPLETE_CHECKLIST`."

        Design: Corner/errors/gonogo_rejected_on_incomplete_checklist
        """
        ctx = setup_burn_ready_ctx()
        ctx_set_burn_day(ctx)
        ctx_brief(ctx)
        five_items = ["permit_verified", "crew_briefed", "communications_check",
                      "escape_routes_reviewed", "weather_within_prescription"]
        validate_error(api.submit_go_no_go(
            ctx["execution"]["id"], go_no_go_payload(items=five_items), ctx_author(ctx)),
            ApiErrorId.ERR_INCOMPLETE_CHECKLIST)
        after = validate_success(api.get_execution(ctx["execution"]["id"], ANY_READER_HEADERS), 200)
        assert after["phase"] == "BRIEFED"

    def test_gonogo_fail_answer_stands_down_execution(self, api):
        """PRD §3.6: "If any answer is `FAIL`, the checklist is recorded with verdict
        `NO_GO` and the execution moves to `STOOD_DOWN`."
        PRD §3.6: "the system records a `GoNoGoChecklist` — capturing the
        `burn_execution_id`, a `weather_observation_id` snapshot of the observation the
        verdict rested on"

        Design: Corner/state_machines/gonogo_fail_answer_stands_down_execution
        """
        ctx = setup_burn_ready_ctx()
        obs = ctx_set_burn_day(ctx)
        ctx_brief(ctx)
        checklist = validate_success(api.submit_go_no_go(
            ctx["execution"]["id"],
            go_no_go_payload(results={"holding_resources_ready": "FAIL"}),
            ctx_author(ctx)), 200)
        assert checklist["verdict"] == "NO_GO"
        assert checklist["weather_observation_id"] == obs["id"]
        after = validate_success(api.get_execution(ctx["execution"]["id"], ANY_READER_HEADERS), 200)
        assert after["phase"] == "STOOD_DOWN"


class TestBriefGatesAndScheduling:
    def test_brief_rejected_on_wrong_day(self, api):
        """PRD §3.6: "The current clock date must be exactly the `scheduled_date`
        (`ERR_WRONG_BURN_DAY`)."

        Design: Corner/errors/brief_rejected_on_wrong_day
        """
        ctx = setup_burn_ready_ctx()
        validate_success(api.set_clock(set_clock_payload("2026-05-11T08:00:00Z"), ADMIN), 200)
        validate_error(api.brief_execution(ctx["execution"]["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_WRONG_BURN_DAY)
        after = validate_success(api.get_execution(ctx["execution"]["id"], ANY_READER_HEADERS), 200)
        assert after["phase"] == "SCHEDULED"

    def test_brief_rejected_when_order_not_filled(self, api):
        """PRD §3.6: "The plan's resource order must be `FILLED`
        (`ERR_HOLDING_FORCE_INADEQUATE`)."

        Design: Corner/errors/brief_rejected_when_order_not_filled
        """
        ctx = _ready_execution(api, fill="engines_only")
        assert ctx["order"]["status"] == "PARTIALLY_FILLED"
        ctx_set_burn_day(ctx)
        validate_error(api.brief_execution(ctx["execution"]["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_HOLDING_FORCE_INADEQUATE)

    def test_schedule_rejected_outside_plan_window(self, api):
        """PRD §3.6: "the author schedules the burn by naming a `scheduled_date`, which
        must fall inside the plan's prescription window — on or after
        `planned_window_start` and on or after no later than `planned_window_end`, both
        ends inclusive, else `ERR_SCHEDULED_DATE_OUTSIDE_WINDOW`."

        Design: Corner/errors/schedule_rejected_outside_plan_window
        """
        ctx = setup_approved_plan_ctx()
        validate_error(api.create_execution(
            ctx["plan"]["id"], {"scheduled_date": "2026-05-25"}, ctx_author(ctx)),
            ApiErrorId.ERR_SCHEDULED_DATE_OUTSIDE_WINDOW)

    def test_declare_escape_from_briefed_rejected(self, api):
        """PRD §3.7: "From `TEST_FIRE`, `IGNITION`, `HOLDING`, or `PATROL` — and only
        those, else `ERR_EXECUTION_NOT_ESCAPABLE` — the author may declare an escape"

        Design: Corner/state_machines/declare_escape_from_briefed_rejected
        """
        ctx = setup_burn_ready_ctx()
        ctx_set_burn_day(ctx)
        ctx_brief(ctx)
        validate_error(api.declare_escape(ctx["execution"]["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_EXECUTION_NOT_ESCAPABLE)
        after = validate_success(api.get_execution(ctx["execution"]["id"], ANY_READER_HEADERS), 200)
        assert after["phase"] == "BRIEFED"


class TestClockSweeps:
    def test_clock_sweep_lapses_scheduled_execution(self, api):
        """PRD §2.5: "A `SCHEDULED` execution whose `scheduled_date` has passed moves to
        `LAPSED`."

        Design: Corner/cross_cutting_layers/clock_sweep_lapses_scheduled_execution
        """
        ctx = setup_approved_plan_ctx()
        ctx_add_execution(ctx, date=BURN_DAY)
        validate_success(api.set_clock(set_clock_payload("2026-05-13T00:00:00Z"), ADMIN), 200)
        execution = validate_success(
            api.get_execution(ctx["execution"]["id"], ANY_READER_HEADERS), 200)
        assert execution["phase"] == "LAPSED"
        plan = validate_success(api.get_burn_plan(ctx["plan"]["id"], ANY_READER_HEADERS), 200)
        assert plan["status"] == "APPROVED"  # window runs to 2026-05-20

    def test_clock_sweep_expires_plan_and_permit(self, api):
        """PRD §2.5: "An `APPROVED` burn plan whose `planned_window_end` has passed and
        for which no execution ever reached `CLOSED` or `WILDFIRE_RESPONSE` moves to
        `EXPIRED`, and its `ISSUED` permit moves to `EXPIRED` with it"

        Design: Corner/cross_cutting_layers/clock_sweep_expires_plan_and_permit
        """
        ctx = setup_approved_plan_ctx()
        ctx_add_contingency(ctx)
        permit = ctx_add_permit(ctx, notifications_required=0)
        assert permit["status"] == "ISSUED"
        validate_success(api.set_clock(set_clock_payload("2026-05-21T00:00:00Z"), ADMIN), 200)
        plan = validate_success(api.get_burn_plan(ctx["plan"]["id"], ANY_READER_HEADERS), 200)
        assert plan["status"] == "EXPIRED"
        permit = validate_success(api.get_permit(permit["id"], ANY_READER_HEADERS), 200)
        assert permit["status"] == "EXPIRED"


class TestStateBeatsSafetyPriority:
    def test_start_ignition_state_error_beats_weather_safety(self, api):
        """PRD §2.7: "seventh the lifecycle-state precondition of the attempted
        transition; eighth burn-day safety conditions (weather within prescription,
        holding-force coverage, accepted safety documents)"
        PRD §3.7: "starting primary ignition requires the execution to be in `TEST_FIRE`
        (`ERR_EXECUTION_NOT_IN_TEST_FIRE`)"

        Design: Difficulty/priority_pair_validation_conflict/ignition_state_error_beats_weather_safety
        """
        ctx = setup_burn_ready_ctx()
        obs = ctx_set_burn_day(ctx, obs_overrides={"wind_mph": 99})
        assert obs["in_prescription"] is False  # the safety failure is real
        ctx_brief(ctx)  # BRIEFED, never passed go/no-go into TEST_FIRE
        validate_error(api.start_ignition(ctx["execution"]["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_EXECUTION_NOT_IN_TEST_FIRE)
        after = validate_success(api.get_execution(ctx["execution"]["id"], ANY_READER_HEADERS), 200)
        assert after["phase"] == "BRIEFED"

    def test_start_ignition_from_briefed_with_good_weather_still_state_error(self, api):
        """PRD §3.7: "starting primary ignition requires the execution to be in
        `TEST_FIRE` (`ERR_EXECUTION_NOT_IN_TEST_FIRE`) with weather still fresh — the
        latest observation no more than 60 minutes old (`ERR_WEATHER_OBSERVATION_STALE`) —
        and still in prescription (`ERR_WEATHER_OUT_OF_PRESCRIPTION`); the execution moves
        to `IGNITION`."

        Design: Difficulty/priority_pair_validation_conflict/ignition_state_error_beats_weather_safety
        """
        ctx = setup_burn_ready_ctx()
        obs = ctx_set_burn_day(ctx)  # fresh and in-prescription
        assert obs["in_prescription"] is True
        ctx_brief(ctx)
        # Weather passes, but the lifecycle-state precondition fires alone
        validate_error(api.start_ignition(ctx["execution"]["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_EXECUTION_NOT_IN_TEST_FIRE)
