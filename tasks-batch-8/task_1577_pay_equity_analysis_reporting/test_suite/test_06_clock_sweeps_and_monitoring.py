"""Logical-clock sweeps, monitoring cycles, and the study closure loop
(PRD §2.4, §2.9, §3.4, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_proposed_adjustments,
    approve_all_adjustments,
    create_monitoring_cycle_payload,
    create_plan_payload,
    create_study,
    get_adjustment,
    get_finding,
    get_plan,
    get_study,
    setup_monitoring_study,
    setup_remediation_open,
    submit_and_approve_plan,
    sweep_clock,
    two_eng_member_specs,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["comp_analyst_headers"]
COUNSEL = TEST_USERS["legal_counsel_headers"]


class TestClockEffectivationCascade:
    def test_clock_sweep_makes_approved_adjustments_effective(self, api):
        """PRD §2.4: "Every clock set triggers a scheduled-transition sweep in a pinned order. First, every `APPROVED` adjustment whose `effective_date` falls on or before the new UTC calendar date becomes `EFFECTIVE`; ties are processed by `effective_date` ascending and then by `created_at` ascending."
        PRD §3.4: "Whenever a recompute brings `committed_cents` exactly equal to `total_budget_cents`, the plan moves automatically from `EXECUTING` to `FULLY_COMMITTED`."

        Design: Difficulty/transitive_cascade/clock_effectivation_cascade_to_monitoring
        """
        ctx = _setup_fully_committed_scenario(api)
        # Precondition: all three approvals exactly exhausted the envelope.
        assert get_plan(ctx["plan"]["id"])["status"] == "FULLY_COMMITTED"

        sweep_clock("2026-09-01T00:00:00Z")
        # Link 1: the boundary date itself is eligible for effectivation.
        for adjustment in ctx["adjustments"]:
            assert get_adjustment(adjustment["id"])["status"] == "EFFECTIVE"

    def test_cascade_resolves_finding_completes_plan_monitors_study(self, api):
        """PRD §3.4: "The resolution re-check moves a `TARGETED` finding to `RESOLVED` automatically when no adjustment referencing it remains in `PROPOSED` or `APPROVED` and at least one referencing adjustment is `EFFECTIVE`; the check is re-evaluated on every adjustment transition into `EFFECTIVE`, `REJECTED`, or `REVERSED`."
        PRD §3.4: "A plan completes automatically — from either `EXECUTING` or `FULLY_COMMITTED` — when no adjustment of the plan remains in `PROPOSED` or `APPROVED` and at least one adjustment is `EFFECTIVE`, moving it to the terminal `COMPLETED` status."
        PRD §3.4: "When a resolution brings the study's unresolved count to zero and the plan is `FULLY_COMMITTED` or `COMPLETED`, the study moves automatically from `REMEDIATION_OPEN` to `MONITORING`."

        Design: Difficulty/transitive_cascade/clock_effectivation_cascade_to_monitoring
        """
        ctx = _setup_fully_committed_scenario(api)
        sweep_clock("2026-09-01T00:00:00Z")
        # Link 2: no PROPOSED/APPROVED adjustments remain and all three are
        # EFFECTIVE, so the TARGETED finding resolves.
        assert get_finding(ctx["finding"]["id"])["status"] == "RESOLVED"
        # Link 2b: all adjustments terminal with >= 1 EFFECTIVE completes the plan.
        assert get_plan(ctx["plan"]["id"])["status"] == "COMPLETED"
        # Link 3: zero unresolved findings + plan COMPLETED auto-opens monitoring.
        assert get_study(ctx["study"]["id"])["status"] == "MONITORING"


class TestMonitoringWindowOverlap:
    def test_touching_half_open_windows_allowed(self, api):
        """PRD §2.9: "A monitoring cycle's observation window, by contrast, is a **half-open interval**: the window includes `window_start` and excludes `window_end`. Because the end date is excluded, two windows whose boundaries merely touch — one ending exactly where another begins — do not overlap and are permitted."
        PRD §3.7: "A new cycle begins in `SCHEDULED` with `retest_result` null and receives a `cycle_index` equal to the count of the study's prior cycles plus one; the study's `monitor_cadence_days` serves as the informational baseline for spacing these due dates."

        Design: Difficulty/resource_temporal_overlap/monitor_window_half_open_touching_allowed
        """
        ctx = setup_monitoring_study(name="StudyM")
        assert ctx["study"]["status"] == "MONITORING"
        cycle1 = validate_success(
            api.create_monitoring_cycle(
                create_monitoring_cycle_payload(
                    ctx["study"]["id"],
                    window_start="2026-09-02", window_end="2026-12-01",
                    due_date="2026-12-15",
                ),
                ANALYST,
            ),
            201,
        )
        assert cycle1["cycle_index"] == 1
        assert cycle1["status"] == "SCHEDULED"
        # window_start 2026-12-01 equals cycle 1's window_end: the half-open
        # boundary touch is permitted.
        cycle2 = validate_success(
            api.create_monitoring_cycle(
                create_monitoring_cycle_payload(
                    ctx["study"]["id"],
                    window_start="2026-12-01", window_end="2027-03-01",
                    due_date="2027-03-15",
                ),
                ANALYST,
            ),
            201,
        )
        assert cycle2["cycle_index"] == 2

    def test_genuinely_overlapping_window_rejected(self, api):
        """PRD §3.7: "The window must not overlap any existing cycle of the same study under the half-open semantics of §2.9 — touching boundaries are allowed — and a genuine overlap is rejected with `ERR_MONITOR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/monitor_window_half_open_touching_allowed
        """
        ctx = setup_monitoring_study(name="StudyM")
        validate_success(
            api.create_monitoring_cycle(
                create_monitoring_cycle_payload(
                    ctx["study"]["id"],
                    window_start="2026-09-02", window_end="2026-12-01",
                    due_date="2026-12-15",
                ),
                ANALYST,
            ),
            201,
        )
        # 2026-11-30 < 2026-12-01 genuinely intersects cycle 1's window.
        res = api.create_monitoring_cycle(
            create_monitoring_cycle_payload(
                ctx["study"]["id"],
                window_start="2026-11-30", window_end="2027-02-01",
                due_date="2027-02-15",
            ),
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_MONITOR_WINDOW_OVERLAP)


class TestCycleLifecycle:
    def test_cycle_guards_and_full_flow_to_study_close(self, api):
        """PRD §3.7: "A `CompAnalyst` schedules a monitoring cycle for a study in `MONITORING` (otherwise `ERR_STUDY_NOT_MONITORING`), supplying the half-open observation window `window_start` to `window_end` — an end that is not strictly after the start is rejected with `ERR_INVALID_WINDOW` — and a `due_date` for the re-test that must fall no earlier than `window_end` (otherwise `ERR_INVALID_DUE_DATE`)."
        PRD §3.7: "A `CompAnalyst` then starts the re-test, moving the cycle from `DUE` to `RE_TESTING` (from any other state, `ERR_CYCLE_INVALID_STATE`)."
        PRD §2.4: "Fifth, every `SCHEDULED` monitoring cycle whose `due_date` falls on or before the new UTC calendar date becomes `DUE`."
        PRD §3.7: "a `LegalCounsel` closes a study from `MONITORING` (from any other state except `PRIVILEGED_FINAL`, where §3.3's clean-study path applies, the attempt is rejected with `ERR_STUDY_INVALID_STATE`) only when the latest `COMPLETED` cycle by `cycle_index` recorded a `retest_result` of `GAPS_CLOSED`; otherwise the closure is rejected with `ERR_GAPS_NOT_CLOSED`."

        Design: Corner/state_machines/cycle_guards_and_full_flow_to_study_close
        """
        ctx = setup_monitoring_study(
            name="MC", member_specs=two_eng_member_specs(), min_group_size=2,
            significance_threshold=0.1, budget=100000,
            adjustment_specs=((1, 100000),),
        )
        assert ctx["study"]["status"] == "MONITORING"

        # window_end equal to window_start is not strictly after it.
        res_w = api.create_monitoring_cycle(
            create_monitoring_cycle_payload(
                ctx["study"]["id"],
                window_start="2026-12-01", window_end="2026-12-01",
                due_date="2026-12-15",
            ),
            ANALYST,
        )
        validate_error(res_w, ApiErrorId.ERR_INVALID_WINDOW)
        # due_date before window_end is rejected.
        res_d = api.create_monitoring_cycle(
            create_monitoring_cycle_payload(
                ctx["study"]["id"],
                window_start="2026-09-02", window_end="2026-12-01",
                due_date="2026-11-30",
            ),
            ANALYST,
        )
        validate_error(res_d, ApiErrorId.ERR_INVALID_DUE_DATE)

        cycle = validate_success(
            api.create_monitoring_cycle(
                create_monitoring_cycle_payload(
                    ctx["study"]["id"],
                    window_start="2026-09-02", window_end="2026-12-01",
                    due_date="2026-12-15",
                ),
                ANALYST,
            ),
            201,
        )
        assert cycle["cycle_index"] == 1
        assert cycle["status"] == "SCHEDULED"
        # A SCHEDULED cycle cannot start; it becomes DUE only via the clock.
        res_early = api.start_cycle(cycle["id"], ANALYST)
        validate_error(res_early, ApiErrorId.ERR_CYCLE_INVALID_STATE)
        # The due sweep at the boundary date (inclusive) flips it DUE.
        sweep_clock("2026-12-15T00:00:00Z")
        due = validate_success(api.get_monitoring_cycle(cycle["id"], ANALYST))
        assert due["status"] == "DUE"
        started = validate_success(api.start_cycle(cycle["id"], ANALYST))
        assert started["status"] == "RE_TESTING"
        completed = validate_success(
            api.complete_cycle(cycle["id"], {"retest_result": "GAPS_CLOSED"}, ANALYST)
        )
        assert completed["status"] == "COMPLETED"
        # The latest COMPLETED cycle recorded GAPS_CLOSED: counsel closes the study.
        closed = validate_success(api.close_study(ctx["study"]["id"], COUNSEL))
        assert closed["status"] == "CLOSED"

    def test_cycle_create_requires_monitoring_study(self, api):
        """PRD §3.7: "A `CompAnalyst` schedules a monitoring cycle for a study in `MONITORING` (otherwise `ERR_STUDY_NOT_MONITORING`), supplying the half-open observation window `window_start` to `window_end` — an end that is not strictly after the start is rejected with `ERR_INVALID_WINDOW` — and a `due_date` for the re-test that must fall no earlier than `window_end` (otherwise `ERR_INVALID_DUE_DATE`)."

        Design: Corner/validations/cycle_create_requires_monitoring_study
        """
        study = create_study(
            name="CY", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31",
        )
        res = api.create_monitoring_cycle(
            create_monitoring_cycle_payload(
                study["id"],
                window_start="2026-09-02", window_end="2026-12-01",
                due_date="2026-12-15",
            ),
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_STUDY_NOT_MONITORING)

    def test_gaps_persist_reopens_remediation(self, api):
        """PRD §3.7: "When a cycle completes with `GAPS_PERSIST` while its study is `MONITORING`, the study automatically returns to `REMEDIATION_OPEN` — remediation reopens — and because the prior plan is by then `COMPLETED`, it does not block the creation of a fresh remediation plan under the one-live-plan rule of §3.4."
        PRD §3.7: "Completing the re-test requires the cycle to be `RE_TESTING` (otherwise `ERR_CYCLE_INVALID_STATE`) and a `retest_result` of `GAPS_CLOSED`, `GAPS_PERSIST`, or `INCONCLUSIVE`; a missing or invalid value is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/gaps_persist_reopens_remediation
        """
        ctx = setup_monitoring_study(
            name="MP", member_specs=two_eng_member_specs(), min_group_size=2,
            significance_threshold=0.1, budget=100000,
            adjustment_specs=((1, 100000),),
        )
        # The plan reached COMPLETED through the effectivation cascade.
        assert ctx["plan"]["status"] == "COMPLETED"
        cycle = validate_success(
            api.create_monitoring_cycle(
                create_monitoring_cycle_payload(
                    ctx["study"]["id"],
                    window_start="2026-09-02", window_end="2026-12-01",
                    due_date="2026-12-15",
                ),
                ANALYST,
            ),
            201,
        )
        sweep_clock("2026-12-15T00:00:00Z")
        validate_success(api.start_cycle(cycle["id"], ANALYST))
        completed = validate_success(
            api.complete_cycle(cycle["id"], {"retest_result": "GAPS_PERSIST"}, ANALYST)
        )
        assert completed["status"] == "COMPLETED"
        assert completed["retest_result"] == "GAPS_PERSIST"
        # The re-test failure reopens remediation.
        study = get_study(ctx["study"]["id"])
        assert study["status"] == "REMEDIATION_OPEN"
        # The COMPLETED prior plan does not block a fresh plan.
        new_plan = validate_success(
            api.create_plan(
                create_plan_payload(ctx["study"]["id"], total_budget_cents=500000),
                ANALYST,
            ),
            201,
        )
        assert new_plan["status"] == "DRAFT"
        assert new_plan["study_id"] == ctx["study"]["id"]


def _setup_fully_committed_scenario(api):
    """Remediation-open study whose plan (budget 2700000) is APPROVED with
    three APPROVED adjustments 950000/900000/850000 (committed == total, plan
    FULLY_COMMITTED) and effective_date 2026-09-01; clock untouched."""
    ctx = setup_remediation_open(name="StudyC", budget=2700000)
    add_proposed_adjustments(ctx, [(3, 950000), (4, 900000), (5, 850000)])
    submit_and_approve_plan(ctx)
    approve_all_adjustments(ctx)
    return ctx
