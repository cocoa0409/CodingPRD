"""Changeover lifecycle and the run-start gate stack: cleaning cycles,
validation, staleness, segregation of duties, posture derivation, and the
safety-before-temporal error ordering."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    clean_and_validate_changeover,
    create_line,
    create_plain_product,
    get_line,
    get_success_data,
    make_line_operator_headers,
    make_quality_tech_headers,
    schedule_run,
    set_clock,
    setup_required_changeover,
    start_run,
    validate_error,
)

PM = TEST_USERS["plant_manager_headers"]


class TestRunStartConsumesValidatedChangeover:
    def test_start_without_validated_changeover_rejected(self, api):
        """PRD §3.4: "If no such changeover exists the start is rejected with
        `ERR_ALLERGEN_CHANGEOVER_REQUIRED`; if a matching one exists but its
        `validated_at` is more than 48 hours old the rejection is
        `ERR_CLEANING_VALIDATION_STALE`."

        Design: Difficulty/cross_entity_state_dependency/run_start_consumes_validated_changeover
        """
        ctx = setup_required_changeover()
        set_clock("2026-08-02T12:00:00Z")
        # the auto-created changeover is still REQUIRED (never validated)
        resp = api.start_run(ctx["run2"]["id"], make_line_operator_headers("op-1"))
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_CHANGEOVER_REQUIRED, 422)
        run2 = get_success_data(api.get_run(ctx["run2"]["id"], PM))
        assert run2["execution_status"] == "SCHEDULED"
        changeover = get_success_data(
            api.get_changeover(ctx["changeover"]["id"], PM))
        assert changeover["status"] == "REQUIRED"
        assert changeover["consumed_by_run_id"] is None

    def test_start_consumes_changeover_atomically(self, api):
        """PRD §3.3: "The first run start whose allergen gate is satisfied by
        this changeover — the line matches, the run's product equals the
        changeover's `to_product_id`, and the validation is still fresh —
        consumes it, moving it to `APPLIED` and recording the run in
        `consumed_by_run_id`."
        PRD §3.4: "A successful start stamps `started_at`, consumes the
        satisfying changeover (`VALIDATED` to `APPLIED`) when one was used,
        pins the cost basis, computes the standard margin described in §3.6"

        Design: Difficulty/cross_entity_state_dependency/run_start_consumes_validated_changeover
        """
        ctx = setup_required_changeover()
        clean_and_validate_changeover(ctx["changeover"]["id"],
                                      cleaner_id="op-1", validator_id="qt-1")
        set_clock("2026-08-02T12:00:00Z")
        run2 = start_run(ctx["run2"]["id"], operator_id="op-2")
        assert run2["execution_status"] == "RUNNING"
        changeover = get_success_data(
            api.get_changeover(ctx["changeover"]["id"], PM))
        assert changeover["status"] == "APPLIED"
        assert changeover["consumed_by_run_id"] == ctx["run2"]["id"]


class TestSwabFailCleaningCycle:
    def test_fail_loops_back_then_pass_validates_and_applies(self, api):
        """PRD §3.3: "A `FAIL` loops the machine back into `CLEANING`: the
        attempt is counted, the line stays in `CLEANING` posture and continues
        to gate run starts, and `swab_result` is reset to null for the next
        cleaning cycle. Every recorded swab, pass or fail, increments
        `swab_attempts` by one"
        PRD §3.3: "consumes it, moving it to `APPLIED` and recording the run in
        `consumed_by_run_id`."

        Design: Difficulty/non_linear_state_machine/changeover_swab_fail_cleaning_cycle
        """
        ctx = setup_required_changeover()
        co_id = ctx["changeover"]["id"]
        get_success_data(api.begin_cleaning(co_id, make_line_operator_headers("op-1")))
        get_success_data(api.record_swab(co_id, "FAIL", make_quality_tech_headers("qt-1")))
        get_success_data(api.record_swab(co_id, "PASS", make_quality_tech_headers("qt-1")))
        get_success_data(api.validate_changeover(co_id, make_quality_tech_headers("qt-1")))
        set_clock("2026-08-02T12:00:00Z")
        run2 = start_run(ctx["run2"]["id"], operator_id="op-2")
        assert run2["execution_status"] == "RUNNING"
        changeover = get_success_data(api.get_changeover(co_id, PM))
        assert changeover["status"] == "APPLIED"
        assert changeover["consumed_by_run_id"] == ctx["run2"]["id"]
        assert changeover["swab_attempts"] == 2, "the FAIL loop must count"
        assert changeover["cleaned_by_user_id"] == "op-1"
        assert changeover["validated_by_user_id"] == "qt-1"

    def test_fail_swab_resets_result_and_stays_in_cleaning(self, api):
        """PRD §3.3: "A `PASS` advances the changeover to `SWAB_PENDING` with
        `swab_result` set to `PASS`. A `FAIL` loops the machine back into
        `CLEANING`: the attempt is counted, the line stays in `CLEANING`
        posture and continues to gate run starts, and `swab_result` is reset to
        null for the next cleaning cycle."

        Design: Difficulty/non_linear_state_machine/changeover_swab_fail_cleaning_cycle
        """
        ctx = setup_required_changeover()
        co_id = ctx["changeover"]["id"]
        get_success_data(api.begin_cleaning(co_id, make_line_operator_headers("op-1")))
        after_fail = get_success_data(
            api.record_swab(co_id, "FAIL", make_quality_tech_headers("qt-1")))
        assert after_fail["status"] == "CLEANING"
        assert after_fail["swab_attempts"] == 1
        assert after_fail["swab_result"] is None, (
            "a FAIL resets swab_result to null for the next cleaning cycle"
        )
        after_pass = get_success_data(
            api.record_swab(co_id, "PASS", make_quality_tech_headers("qt-1")))
        assert after_pass["status"] == "SWAB_PENDING"
        assert after_pass["swab_attempts"] == 2
        assert after_pass["swab_result"] == "PASS"


class TestChangeoverGateErrors:
    def test_changeover_validate_from_required_rejected(self, api):
        """PRD §3.3: "A `QualityTechnician` validates a changeover in
        `SWAB_PENDING` whose `swab_result` is `PASS`, moving it to
        `VALIDATED`"
        PRD §2.9: "the target entity occupies a from-state of the invoked
        transition, terminal entities reject all further transitions with
        `ERR_ALREADY_TERMINAL`, non-terminal mismatches yield
        `ERR_INVALID_STATE`"

        Design: Corner/state_machines/changeover_validate_from_required_rejected
        """
        ctx = setup_required_changeover()
        resp = api.validate_changeover(
            ctx["changeover"]["id"], make_quality_tech_headers("qt-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        changeover = get_success_data(
            api.get_changeover(ctx["changeover"]["id"], PM))
        assert changeover["status"] == "REQUIRED"

    def test_cleaning_validation_stale_after_48h(self, api):
        """PRD §3.3: "Freshness expires 48 hours after `validated_at`; a
        changeover whose validation is more than 48 hours old at run start is
        stale."
        PRD §3.4: "if a matching one exists but its `validated_at` is more than
        48 hours old the rejection is `ERR_CLEANING_VALIDATION_STALE`."

        Design: Corner/validations/cleaning_validation_stale_after_48h
        """
        ctx = setup_required_changeover()
        co_id = ctx["changeover"]["id"]
        get_success_data(api.begin_cleaning(co_id, make_line_operator_headers("op-1")))
        set_clock("2026-08-02T12:00:00Z")  # validated_at will be 12:00
        get_success_data(api.record_swab(co_id, "PASS", make_quality_tech_headers("qt-1")))
        validated = get_success_data(
            api.validate_changeover(co_id, make_quality_tech_headers("qt-1")))
        assert validated["status"] == "VALIDATED"
        set_clock("2026-08-04T13:00:00Z")  # 49 hours after validation
        resp = api.start_run(ctx["run2"]["id"], make_line_operator_headers("op-2"))
        validate_error(resp, ApiErrorId.ERR_CLEANING_VALIDATION_STALE, 422)
        changeover = get_success_data(api.get_changeover(co_id, PM))
        assert changeover["status"] == "VALIDATED"
        assert changeover["consumed_by_run_id"] is None
        run2 = get_success_data(api.get_run(ctx["run2"]["id"], PM))
        assert run2["execution_status"] == "SCHEDULED"

    def test_start_before_scheduled_window_rejected(self, api):
        """PRD §3.4: "Finally, the logical clock must have reached
        `scheduled_start`; an early start is rejected with
        `ERR_START_BEFORE_WINDOW`."

        Design: Corner/validations/start_before_scheduled_window_rejected
        """
        product = create_plain_product()
        line = create_line()
        run = schedule_run(line["id"], product["id"],
                           start="2026-08-02T08:00:00Z",
                           end="2026-08-02T10:00:00Z")
        # clock left at the startup default 2026-08-01T00:00:00Z: requirement
        # NONE on a fresh line, so only the clock gate can fire
        resp = api.start_run(run["id"], make_line_operator_headers("op-1"))
        validate_error(resp, ApiErrorId.ERR_START_BEFORE_WINDOW, 422)
        run = get_success_data(api.get_run(run["id"], PM))
        assert run["execution_status"] == "SCHEDULED"


class TestSegregationOfDuties:
    def test_sod_cleaner_cannot_validate_own_cleaning(self, api):
        """PRD §3.3: "the validating user's `X-User-ID` must differ from
        `cleaned_by_user_id`, and a self-validation is rejected with
        `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/validations/sod_cleaner_cannot_validate_own_cleaning
        """
        ctx = setup_required_changeover()
        co_id = ctx["changeover"]["id"]
        get_success_data(
            api.begin_cleaning(co_id, make_line_operator_headers("shared-1")))
        get_success_data(
            api.record_swab(co_id, "PASS", make_quality_tech_headers("qt-9")))
        # the same human, now wearing the QualityTechnician role, cannot
        # validate the cleaning they performed
        resp = api.validate_changeover(co_id, make_quality_tech_headers("shared-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 403)
        changeover = get_success_data(api.get_changeover(co_id, PM))
        assert changeover["status"] == "SWAB_PENDING"


class TestQualityRoleExclusivity:
    def test_line_operator_cannot_record_swab(self, api):
        """PRD §2.1: "A `QualityTechnician` is the quality gatekeeper: swab
        recording, changeover validation, weight checks, hold release, and
        quality disposition."
        PRD §2.1: "A request whose role is not among the roles authorized for
        the targeted endpoint is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/line_operator_cannot_record_swab
        """
        ctx = setup_required_changeover()
        co_id = ctx["changeover"]["id"]
        get_success_data(api.begin_cleaning(co_id, make_line_operator_headers("op-1")))
        resp = api.record_swab(co_id, "PASS", make_line_operator_headers("op-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        changeover = get_success_data(api.get_changeover(co_id, PM))
        assert changeover["status"] == "CLEANING"
        assert changeover["swab_attempts"] == 0

    def test_plant_manager_cannot_validate_changeover(self, api):
        """PRD §2.1: "Plant administration rights do not subsume quality duties
        — a `PlantManager` cannot record swabs, validate changeovers, record
        weight checks, or release holds."

        Design: Corner/rbac/plant_manager_cannot_validate_changeover
        """
        ctx = setup_required_changeover()
        co_id = ctx["changeover"]["id"]
        get_success_data(api.begin_cleaning(co_id, make_line_operator_headers("op-1")))
        get_success_data(
            api.record_swab(co_id, "PASS", make_quality_tech_headers("qt-1")))
        resp = api.validate_changeover(co_id, PM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        changeover = get_success_data(api.get_changeover(co_id, PM))
        assert changeover["status"] == "SWAB_PENDING"


class TestLinePosture:
    def test_line_posture_recomputes_across_changeover_lifecycle(self, api):
        """PRD §2.8: "The precedence order is strict: `RUNNING` if any
        ProductionRun on the line has `execution_status` equal to `RUNNING`;
        otherwise `CLEANING` if any Changeover on the line has `status` in
        `REQUIRED`, `CLEANING`, or `SWAB_PENDING`; otherwise `BLOCKED` if the
        line's FryerOil `state` is `QUALITY_HOLD` or `DRAINING`; otherwise
        `IDLE`."
        PRD §3.3: "Validation lifts the cleaning gate, so the line's posture is
        recomputed and may leave `CLEANING`."

        Design: Corner/entities/line_posture_recomputes_across_changeover_lifecycle
        """
        ctx = setup_required_changeover()
        line_id = ctx["line"]["id"]
        # run1 completed: completed runs do not hold the posture
        assert ctx["line"]["posture"] == "IDLE"
        # the auto-created changeover sits in REQUIRED
        assert get_line(line_id)["posture"] == "CLEANING"
        clean_and_validate_changeover(ctx["changeover"]["id"],
                                      cleaner_id="op-1", validator_id="qt-1")
        # VALIDATED is no longer in the cleaning set: posture derives back down
        assert get_line(line_id)["posture"] == "IDLE"


class TestSafetyBeatsTemporal:
    def test_dual_violation_reports_allergen_gate_not_clock(self, api):
        """PRD §2.9: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order so that the surfaced
        error is deterministic:" with "7. Safety and segregation of duties: the
        allergen changeover gate and oil state gate on run start" listed before
        "8. Temporal rules: start-not-before-window, schedule overlap with
        cleaning buffer"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_run_start
        """
        ctx = setup_required_changeover()
        # clock 11:00 is before run2's scheduled_start (12:00) AND the
        # FULL_WASH changeover is unvalidated: safety must outrank temporal
        set_clock("2026-08-02T11:00:00Z")
        resp = api.start_run(ctx["run2"]["id"], make_line_operator_headers("op-1"))
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_CHANGEOVER_REQUIRED, 422)
        run2 = get_success_data(api.get_run(ctx["run2"]["id"], PM))
        assert run2["execution_status"] == "SCHEDULED"

    def test_safety_gate_fires_alone_once_clock_reaches_window(self, api):
        """PRD §3.4: "The allergen safety gate follows: starting is permitted
        when the changeover matrix computed against the line's current profile
        yields `NONE`, or when a matching changeover exists on the line — aimed
        at the run's product, in `VALIDATED` status, with `consumed_by_run_id`
        still null, and validated within the last 48 hours."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_run_start
        """
        ctx = setup_required_changeover()
        set_clock("2026-08-02T11:00:00Z")
        resp = api.start_run(ctx["run2"]["id"], make_line_operator_headers("op-1"))
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_CHANGEOVER_REQUIRED, 422)
        # advancing the clock into the schedule window cures the temporal
        # violation; the allergen gate alone still rejects the start
        set_clock("2026-08-02T12:00:00Z")
        resp = api.start_run(ctx["run2"]["id"], make_line_operator_headers("op-1"))
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_CHANGEOVER_REQUIRED, 422)
        run2 = get_success_data(api.get_run(ctx["run2"]["id"], PM))
        assert run2["execution_status"] == "SCHEDULED"
