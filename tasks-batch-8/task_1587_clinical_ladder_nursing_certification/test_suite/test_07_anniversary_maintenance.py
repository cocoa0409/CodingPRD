"""Anniversary maintenance reviews: score boundary, demotion floor, the
parallel level/differential dimensions, and the demotion budget cascade
(PRD §3.5, §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_verified_points,
    advance_nurse_to_cn_iii,
    create_anniversary_review,
    create_budget_line,
    create_certification,
    create_criterion,
    create_nurse,
    get_budget_line,
    get_nurse,
    run_ops_cycle,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANALYST = TEST_USERS["retention_analyst_headers"]


class TestMaintenanceScoreBoundary:
    def _nurse_with_review(self, api, employee_code, hire_date):
        """CN_I nurse (level requirement NONE) with 5 verified points and one
        CURRENT BASIC certification, plus an OPEN review for 2026."""
        nurse = create_nurse(employee_code=employee_code, hire_date=hire_date,
                             home_unit="ICU-4W")
        add_verified_points(nurse["id"], 5, "2026-03-01T00:00:00Z")
        create_certification(
            nurse["id"], track="BASIC", exam_fee_cents=40000,
            obtained_on="2025-01-01T00:00:00Z", expires_on="2028-01-01T00:00:00Z",
        )
        review = create_anniversary_review(nurse["id"], 2026)
        return nurse, review

    def test_maintenance_score_exactly_60_sustains(self, api):
        """PRD §3.5: "The participation component doubles the live 24-month
        participation window at review close and caps at 40, so twenty verified
        points saturate it. The certification component depends on the nurse's
        own level requirement — the `required_certification_track` of the
        active criterion set for the nurse's current level, or `NONE` for
        `CN_I`, whose rung has no admission criterion: holding at least one
        `CURRENT` certification at or above that requirement earns 40, holding
        at least one `CURRENT` `BASIC` credential short of it earns 20, and
        holding neither earns 0. The tenure component doubles `tenure_years`
        and caps at 20, so ten years of service saturate it."
        PRD §3.5: "Closing with `SUSTAIN` requires the maintenance score to
        reach the threshold of 60 — 59 fails with
        `ERR_MAINTENANCE_SCORE_INSUFFICIENT` (HTTP 422), 60 passes..."

        Nurse A hired 2021-07-01 at clock 2026-08-01: tenure 5 -> 10 points;
        5 verified points -> 10; BASIC cert at-or-above NONE -> 40; total 60.

        Design: Difficulty/combinatorial_formula/maintenance_score_three_input_nonlinear_saturation
        """
        set_clock("2026-08-01T00:00:00Z")
        _, review = self._nurse_with_review(api, "RN-A", "2021-07-01T00:00:00Z")
        closed = validate_success(
            api.close_anniversary_review(review["id"], {"outcome": "SUSTAIN"}, ADMIN)
        )
        assert closed["outcome"] == "SUSTAIN"
        assert closed["maintenance_score"] == 60, (
            f"10 + 40 + 10 must total exactly the threshold 60, got {closed['maintenance_score']}"
        )

    def test_maintenance_score_58_rejects_sustain(self, api):
        """PRD §3.5: "Closing with `SUSTAIN` requires the maintenance score to
        reach the threshold of 60 — 59 fails with
        `ERR_MAINTENANCE_SCORE_INSUFFICIENT` (HTTP 422), 60 passes..."

        Nurse B hired 2021-08-01 at clock 2026-08-01: tenure 4 -> 8 points;
        5 verified points -> 10; BASIC cert -> 40; total 58.

        Design: Difficulty/combinatorial_formula/maintenance_score_three_input_nonlinear_saturation
        """
        set_clock("2026-08-01T00:00:00Z")
        _, review = self._nurse_with_review(api, "RN-B", "2021-08-01T00:00:00Z")
        resp = api.close_anniversary_review(review["id"], {"outcome": "SUSTAIN"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_MAINTENANCE_SCORE_INSUFFICIENT, 422)


class TestDemotionFloor:
    def test_demote_floor_cn1_rejected(self, api):
        """PRD §3.5: "Closing with `DEMOTE` requires a `resolution_reason` and
        drops the nurse one rung — `CN_IV` to `CN_III`, `CN_III` to `CN_II`,
        `CN_II` to `CN_I` — while a demotion requested for a nurse already at
        `CN_I` is rejected with `ERR_CANNOT_DEMOTE_FLOOR` (HTTP 422)."

        Design: Corner/validations/demote_floor_cn1_rejected
        """
        nurse = create_nurse(employee_code="RN-DF1", full_name="Df One")
        review = create_anniversary_review(nurse["id"], 2026)
        resp = api.close_anniversary_review(
            review["id"],
            {"outcome": "DEMOTE", "resolution_reason": "floor test"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CANNOT_DEMOTE_FLOOR, 422)


class TestParallelDimensions:
    def test_demote_drops_level_and_suspends_differential(self, api):
        """PRD §3.5: "Demotion flips `differential_status` to `SUSPENDED`,
        halting pay while leaving the level dimension to stand on its own, and
        fires the heaviest single increment to the nurse's retention risk; the
        unit budget commitment recomputes against the now-lower differential."
        PRD §3.1: "Two dimensions on the nurse evolve independently."

        Design: Difficulty/non_linear_state_machine/nurse_parallel_dimensions_level_vs_differential
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = advance_nurse_to_cn_iii(employee_code="RN-P")
        nurse = ctx["nurse"]
        assert nurse["current_level"] == "CN_III"
        assert nurse["differential_status"] == "ACTIVE"
        review = create_anniversary_review(nurse["id"], 2026)
        validate_success(
            api.close_anniversary_review(
                review["id"],
                {"outcome": "DEMOTE", "resolution_reason": "maintenance lapsed"},
                ADMIN,
            )
        )
        after = get_nurse(nurse["id"])
        assert after["current_level"] == "CN_II", (
            f"demotion must drop exactly one rung, got {after['current_level']}"
        )
        assert after["differential_status"] == "SUSPENDED", (
            f"pay must suspend on demotion, got {after['differential_status']}"
        )

    def test_lapse_terminates_differential_without_touching_level(self, api):
        """PRD §3.5: "When the ops-run sweep finds a review still `OPEN` past
        December 31 of its `review_year`, it closes the review as `LAPSE` —
        recording the rationale on the row — and sets `differential_status` to
        `TERMINATED`, killing the pay entirely rather than suspending it, then
        recomputes both the unit budget commitment and the nurse's retention
        risk."

        Design: Difficulty/non_linear_state_machine/nurse_parallel_dimensions_level_vs_differential
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = advance_nurse_to_cn_iii(employee_code="RN-PQ")
        nurse = ctx["nurse"]
        review1 = create_anniversary_review(nurse["id"], 2026)
        validate_success(
            api.close_anniversary_review(
                review1["id"],
                {"outcome": "DEMOTE", "resolution_reason": "maintenance lapsed"},
                ADMIN,
            )
        )
        create_anniversary_review(nurse["id"], 2027)
        set_clock("2028-01-15T00:00:00Z")
        run_ops_cycle()
        after = get_nurse(nurse["id"])
        assert after["current_level"] == "CN_II", (
            f"lapse must leave the level dimension untouched, got {after['current_level']}"
        )
        assert after["differential_status"] == "TERMINATED", (
            f"lapsed review must terminate pay entirely, got {after['differential_status']}"
        )


class TestDemotionBudgetCascade:
    def test_active_differential_annualizes_into_commitment(self, api):
        """PRD §3.6: "It annualizes the active differentials — twelve months
        of each unit nurse's level-keyed monthly differential, summed over
        nurses whose `differential_status` is `ACTIVE`..."

        CN_III criterion pays 50000/month; one ACTIVE nurse at CN_III commits
        12 * 50000 = 600000.

        Design: Difficulty/transitive_cascade/demote_cascade_level_to_differential_to_budget
        """
        set_clock("2026-08-01T00:00:00Z")
        line = create_budget_line("ICU-4W", 2027, 9000000)
        ctx = advance_nurse_to_cn_iii(employee_code="RN-D")
        assert ctx["nurse"]["current_level"] == "CN_III"
        assert ctx["nurse"]["differential_status"] == "ACTIVE"
        committed = get_budget_line(line["id"])["committed_cents"]
        assert committed == 600000, (
            f"annualized CN_III differential must commit 600000, got {committed}"
        )

    def test_demote_removes_differential_from_committed_pool(self, api):
        """PRD §3.5: "Demotion flips `differential_status` to `SUSPENDED`,
        halting pay while leaving the level dimension to stand on its own, and
        fires the heaviest single increment to the nurse's retention risk; the
        unit budget commitment recomputes against the now-lower differential."
        PRD §3.6: "...summed over nurses whose `differential_status` is
        `ACTIVE`..."

        Design: Difficulty/transitive_cascade/demote_cascade_level_to_differential_to_budget
        """
        set_clock("2026-08-01T00:00:00Z")
        line = create_budget_line("ICU-4W", 2027, 9000000)
        ctx = advance_nurse_to_cn_iii(employee_code="RN-D2")
        assert get_budget_line(line["id"])["committed_cents"] == 600000
        review = create_anniversary_review(ctx["nurse"]["id"], 2026)
        validate_success(
            api.close_anniversary_review(
                review["id"],
                {"outcome": "DEMOTE", "resolution_reason": "insufficient maintenance"},
                ADMIN,
            )
        )
        after = get_nurse(ctx["nurse"]["id"])
        assert after["current_level"] == "CN_II"
        assert after["differential_status"] == "SUSPENDED"
        committed = get_budget_line(line["id"])["committed_cents"]
        assert committed == 0, (
            "SUSPENDED differential must leave the committed pool for this "
            f"single-nurse unit, got {committed}"
        )


class TestAnalystReadOnly:
    def test_retention_analyst_read_only(self, api):
        """PRD §2.1: "`RetentionAnalyst` — a read-only analyst for retention
        snapshots and participation aggregates."
        PRD §2.1: "A request whose role is not permitted to invoke the endpoint
        is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/retention_analyst_read_only
        """
        from test_helpers import create_participation_event
        nurse = create_nurse(employee_code="RN-RA1", full_name="Ra One")
        event = create_participation_event(nurse["id"], points=5)
        review = create_anniversary_review(nurse["id"], 2026)
        resp_verify = api.verify_participation_event(event["id"], ANALYST)
        validate_error(resp_verify, ApiErrorId.ERR_UNAUTHORIZED, 403)
        resp_close = api.close_anniversary_review(
            review["id"], {"outcome": "SUSTAIN"}, ANALYST
        )
        validate_error(resp_close, ApiErrorId.ERR_UNAUTHORIZED, 403)
