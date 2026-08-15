"""Calculation claims: attainment ratio variants, nested rounding, goal-status
boundaries, and the legal risk score formula."""
import pytest

from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_cast,
    add_employee,
    setup_issued_pip,
    setup_active_pip,
    get_pip,
    get_goals,
    set_clock,
    create_check_in_payload,
    create_mark_held_payload,
    create_evidence_payload,
    create_legal_review_payload,
    submit_legal_review_payload,
    create_and_submit_legal_review,
    propose_outcome,
    make_hrbp_headers,
    make_manager_headers,
    make_counsel_headers,
)


def _goals_by_metric(ctx):
    goals = get_goals(ctx)
    return {g["metric_key"]: g for g in goals}


class TestProvisionalVsFinalAttainment:
    def test_variants_diverge_on_excluded_evidence(self, api):
        """PRD §3.4: "While the plan runs, the figure is provisional: only goals
        backed by admissible evidence contribute their measured value, and goals
        without admissible evidence contribute zero attainment — although their
        weight still counts in the denominator."
        PRD §3.6: "Proposal freezes the final attainment figure: the plan's
        `final_attainment_ratio` — null until this moment — is computed and
        snapshot into the decision's `final_attainment_ratio_at_decision`."

        Design: Difficulty/dual_variant_calc/pip_attainment_provisional_vs_final_diverge_on_admissibility
        """
        ctx = setup_issued_pip(
            goal_blueprints=[
                {"metric_key": "defects_per_kloc", "target_value": 2, "unit": "count", "weight": 50},
                {"metric_key": "story_points", "target_value": 20, "unit": "points", "weight": 50},
            ],
        )
        hrbp_headers = make_hrbp_headers(ctx["hrbp_id"])
        # Manager submits evidence so the issuing HRBP may adjudicate it
        # (PRD §3.4 segregation of duties).
        mgr_headers = make_manager_headers(ctx["mgr_id"])
        resp = api.create_check_in(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_check_in_payload(scheduled_for="2026-08-11T00:00:00Z"),
            hrbp_headers,
        )
        ck_id = validate_success(resp, expected_status=201)["id"]
        goals = _goals_by_metric(ctx)
        # Admitted evidence on goal 1 (attainment 0.5); excluded on goal 2.
        resp = api.submit_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ck_id,
            create_evidence_payload(goals["defects_per_kloc"]["id"], observed_value=1,
                                    source="SYSTEM_REPORT"),
            mgr_headers,
        )
        ev_a = validate_success(resp, expected_status=201)["id"]
        resp = api.submit_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ck_id,
            create_evidence_payload(goals["story_points"]["id"], observed_value=20,
                                    source="SELF_REPORT"),
            mgr_headers,
        )
        ev_b = validate_success(resp, expected_status=201)["id"]
        validate_success(api.admit_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ck_id, ev_a, hrbp_headers))
        validate_success(api.exclude_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ck_id, ev_b, hrbp_headers))
        set_clock(ctx["ou_id"], "2026-08-11T10:00:00Z")
        validate_success(api.mark_check_in_held(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ck_id,
            create_mark_held_payload(
                notes="Reviewed current trajectory against both goals in depth."),
            hrbp_headers,
        ))

        pip = get_pip(ctx)
        # PROVISIONAL: the excluded goal contributes 0 but its weight still
        # divides — (0.5*50 + 0*50)/100 = 0.25.
        assert pip["provisional_attainment_ratio"] == pytest.approx(0.25, abs=1e-9), (
            f"provisional ratio must be 0.25, got {pip['provisional_attainment_ratio']}"
        )
        # The final figure stays null until a proposal freezes it (§3.6).
        assert pip["final_attainment_ratio"] is None

        proposer = add_employee(ctx["ou_id"], "Proposer HRBP", "h1.alt@x.com",
                                job_level=7)
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")  # past end_date
        resp = propose_outcome(
            ctx, "EXTENSION", proposer_hrbp_id=proposer["id"],
            rationale="Provisional attainment below the success bar; extend the plan.",
        )
        decision = validate_success(resp, expected_status=201)
        pip_after = get_pip(ctx)
        assert pip_after["final_attainment_ratio"] is not None
        assert decision["final_attainment_ratio_at_decision"] == pytest.approx(
            pip_after["final_attainment_ratio"], abs=1e-9
        ), "the decision must snapshot the plan's frozen final attainment ratio"


class TestNestedRounding:
    def test_attainment_rounds_once_at_the_end(self, api):
        """PRD §3.4: "Rounding happens exactly once, half-up to 4 decimal places,
        after the weighted sum is formed."
        PRD §2.9: "rounded half-up to exactly 4 decimal places, with rounding
        applied once at the end of each computation and never to intermediate
        per-goal values."

        Design: Difficulty/combinatorial_formula/pip_attainment_nested_rounding_mode_b
        """
        ctx = setup_issued_pip(
            goal_blueprints=[
                {"metric_key": "epics_closed", "target_value": 3, "unit": "count", "weight": 50},
                {"metric_key": "story_points", "target_value": 7, "unit": "points", "weight": 50},
            ],
        )
        hrbp_headers = make_hrbp_headers(ctx["hrbp_id"])
        # Manager submits evidence so the issuing HRBP may adjudicate (§3.4 SoD).
        mgr_headers = make_manager_headers(ctx["mgr_id"])
        resp = api.create_check_in(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_check_in_payload(scheduled_for="2026-08-11T00:00:00Z"),
            hrbp_headers,
        )
        ck_id = validate_success(resp, expected_status=201)["id"]
        goals = _goals_by_metric(ctx)
        for metric, value in (("epics_closed", 1), ("story_points", 2)):
            resp = api.submit_evidence(
                ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ck_id,
                create_evidence_payload(goals[metric]["id"], observed_value=value,
                                        source="SYSTEM_REPORT"),
                mgr_headers,
            )
            ev = validate_success(resp, expected_status=201)["id"]
            validate_success(api.admit_evidence(
                ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ck_id, ev, hrbp_headers))
        set_clock(ctx["ou_id"], "2026-08-11T10:00:00Z")
        validate_success(api.mark_check_in_held(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ck_id,
            create_mark_held_payload(notes="Trajectory discussion on both velocity goals."),
            hrbp_headers,
        ))
        pip = get_pip(ctx)
        # ((1/3)*50 + (2/7)*50)/100 = 0.3095238..., half-up at 4dp = 0.3095.
        assert pip["provisional_attainment_ratio"] == pytest.approx(0.3095, abs=1e-9), (
            f"round-at-end must yield 0.3095, got {pip['provisional_attainment_ratio']}"
        )


class TestGoalStatusBoundary:
    def test_goal_at_exactly_070_is_on_track(self, api):
        """PRD §3.4: "at least 70 percent of target is `ON_TRACK` — the boundary is
        inclusive, so exactly 0.70 maps to `ON_TRACK` while 0.6999 maps to
        `AT_RISK`".

        Design: Corner/calculations/goal_status_rule_boundary_070_inclusive_on_track
        """
        ctx = setup_issued_pip(
            category="VELOCITY",
            goal_blueprints=[
                {"metric_key": "story_points", "target_value": 1000, "unit": "points", "weight": 100},
            ],
        )
        hrbp_headers = make_hrbp_headers(ctx["hrbp_id"])
        # Manager submits evidence so the issuing HRBP may adjudicate (§3.4 SoD).
        mgr_headers = make_manager_headers(ctx["mgr_id"])
        resp = api.create_check_in(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_check_in_payload(scheduled_for="2026-08-11T00:00:00Z"),
            hrbp_headers,
        )
        ck_id = validate_success(resp, expected_status=201)["id"]
        goals = get_goals(ctx)
        resp = api.submit_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ck_id,
            create_evidence_payload(goals[0]["id"], observed_value=700,
                                    source="SYSTEM_REPORT"),
            mgr_headers,
        )
        ev = validate_success(resp, expected_status=201)["id"]
        validate_success(api.admit_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ck_id, ev, hrbp_headers))
        set_clock(ctx["ou_id"], "2026-08-11T10:00:00Z")
        validate_success(api.mark_check_in_held(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ck_id,
            create_mark_held_payload(notes="Velocity review at the 0.70 boundary."),
            hrbp_headers,
        ))
        goals = get_goals(ctx)
        assert goals[0]["current_value"] == 700
        assert goals[0]["goal_status"] == "ON_TRACK", (
            f"0.70 is inclusive for ON_TRACK, got {goals[0]['goal_status']}"
        )


class TestSingleGoalFullAttainment:
    def test_met_goal_yields_ratio_one(self, api):
        """PRD §3.4: "A goal whose `current_value` reaches at least its full
        `target_value` is `MET`".
        PRD §3.4: "The ratio is the sum of every goal's attainment multiplied by
        its `weight`, divided by the summed weights of the non-waived goals only".

        Design: Corner/calculations/pip_attainment_waived_goal_contributes_full_credit
        """
        ctx = setup_active_pip()
        hrbp_headers = make_hrbp_headers(ctx["hrbp_id"])
        # Manager submits evidence so the issuing HRBP may adjudicate (§3.4 SoD).
        mgr_headers = make_manager_headers(ctx["mgr_id"])
        goals = get_goals(ctx)
        resp = api.submit_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"],
            create_evidence_payload(goals[0]["id"], observed_value=2,
                                    source="SYSTEM_REPORT"),
            mgr_headers,
        )
        ev = validate_success(resp, expected_status=201)["id"]
        validate_success(api.admit_evidence(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"], ev,
            hrbp_headers))
        validate_success(api.mark_check_in_held(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"],
            create_mark_held_payload(notes="Single-goal attainment verification."),
            hrbp_headers,
        ))
        goals = get_goals(ctx)
        assert goals[0]["goal_status"] == "MET"
        pip = get_pip(ctx)
        assert pip["provisional_attainment_ratio"] == pytest.approx(1.0, abs=1e-9)


class TestLegalRiskScore:
    def _setup_claimed_review(self, api, duration_days=30, cadence=10,
                              category="QUALITY", concern_severity="DOCUMENTED"):
        """ACTIVE PIP + claimed legal review. Returns ctx with counsel_id set."""
        ctx = setup_cast()
        counsel = add_employee(ctx["ou_id"], "Counsel L1", "l@x.com", job_level=8)
        ctx["counsel_id"] = counsel["id"]
        from test_helpers import (
            create_coaching_entries, create_and_accept_concern,
            create_and_publish_template, create_and_issue_pip,
        )
        entry_ids = create_coaching_entries(ctx, count=2, severity=concern_severity,
                                            category=category)
        concern = create_and_accept_concern(ctx, entry_ids, category=category)
        template = create_and_publish_template(
            ctx, category=category, duration_days=duration_days,
            check_in_cadence_days=cadence,
        )
        pip = create_and_issue_pip(ctx, concern["id"], template["id"])
        ctx["pip"] = pip
        ctx["pip_id"] = pip["id"]
        resp = api.create_check_in(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_check_in_payload(scheduled_for="2026-08-11T00:00:00Z"),
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        ctx["check_in_id"] = validate_success(resp, expected_status=201)["id"]
        resp = api.create_legal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_legal_review_payload(counsel["id"]),
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        ctx["review_id"] = validate_success(resp, expected_status=201)["id"]
        validate_success(api.claim_legal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["review_id"],
            make_counsel_headers(counsel["id"]),
        ))
        return ctx

    def test_documentation_gap_multiplier_and_compound_bonus(self, api):
        """PRD §3.5: "If a documentation gap is among the factors, the base is
        doubled — a multiplicative interaction floored to a whole number. If the
        resulting base is at least 50 and whistleblower history is present, a
        further 10 points are added as a compound trigger. The final score is
        clamped so it never falls below 0 or rises above 100."

        Design: Difficulty/dual_variant_calc/legal_risk_score_baseline_vs_documentation_gap_multiplier
        """
        ctx = self._setup_claimed_review(api)
        set_clock(ctx["ou_id"], "2026-08-15T00:00:00Z")
        resp = api.submit_legal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["review_id"],
            submit_legal_review_payload(
                risk_factors=["PROTECTED_CLASS", "WHISTLEBLOWER_HISTORY",
                              "DOCUMENTATION_GAP"],
                recommendation="PROCEED_WITH_CAUTION",
                rationale=("Elevated risk due to protected-class interplay with "
                           "prior whistleblower activity and a thin documentary record."),
            ),
            make_counsel_headers(ctx["counsel_id"]),
        )
        review = validate_success(resp)
        # (20 + 30 + 0) * 2 = 100, +10 compound -> 110, clamped to 100.
        assert review["risk_score"] == 100
        assert review["status"] == "SUBMITTED"

    def test_three_factor_additive_score(self, api):
        """PRD §3.5: "Each factor contributes a fixed weight: 20 for
        `PROTECTED_CLASS`, 15 for `RECENT_LEAVE`, 30 for `WHISTLEBLOWER_HISTORY`,
        10 for `PRIOR_COMPLAINT`, 25 for `RETALIATION_WINDOW`, and 0 for
        `DOCUMENTATION_GAP`. The base score is the sum of the listed factors'
        weights."

        Design: Difficulty/combinatorial_formula/legal_risk_score_three_input_nonlinear_mode_a
        """
        ctx = self._setup_claimed_review(api)
        resp = api.submit_legal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["review_id"],
            submit_legal_review_payload(
                risk_factors=["PROTECTED_CLASS", "RECENT_LEAVE", "PRIOR_COMPLAINT"],
                recommendation="PROCEED",
                rationale=("Multiple compounding factors but none rise to "
                           "documentation-gap or whistleblower level."),
            ),
            make_counsel_headers(ctx["counsel_id"]),
        )
        review = validate_success(resp)
        # 20 + 15 + 10 = 45; no doubling, no compound bonus, no clamp.
        assert review["risk_score"] == 45
        assert review["status"] == "SUBMITTED"

    def test_empty_factors_clamped_at_zero(self, api):
        """PRD §3.5: "The base score is the sum of the listed factors' weights. ...
        The final score is clamped so it never falls below 0 or rises above 100."

        Design: Corner/calculations/legal_risk_score_clamped_at_zero_when_no_factors
        """
        ctx = self._setup_claimed_review(api)
        resp = api.submit_legal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["review_id"],
            submit_legal_review_payload(
                risk_factors=[],
                recommendation="PROCEED",
                rationale=("No legal risk factors identified; documentation "
                           "complete and consistent."),
            ),
            make_counsel_headers(ctx["counsel_id"]),
        )
        review = validate_success(resp)
        assert review["risk_score"] == 0
