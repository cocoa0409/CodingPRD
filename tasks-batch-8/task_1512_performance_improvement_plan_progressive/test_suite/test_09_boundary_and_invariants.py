"""Second-coverage tests for difficulty instances, plus derived-field
reconciliation reads at each lifecycle hop."""
import pytest

from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_cast,
    add_employee,
    create_employee,
    create_coaching_entries,
    create_and_submit_concern,
    create_and_accept_concern,
    create_and_publish_template,
    create_draft_pip,
    create_and_issue_pip,
    setup_concern_and_template,
    setup_issued_pip,
    setup_active_pip,
    create_check_in_payload,
    create_mark_held_payload,
    create_evidence_payload,
    create_legal_review_payload,
    submit_legal_review_payload,
    create_and_submit_legal_review,
    propose_outcome,
    approve_outcome,
    get_pip,
    get_employee,
    get_goals,
    set_clock,
    make_hrbp_headers,
    make_manager_headers,
    make_counsel_headers,
    make_director_headers,
    make_employee_headers,
)


class TestDerivedFieldReconciliation:
    def test_active_pip_id_reconciled_at_each_transition(self, api):
        """PRD §3.1: "A computed `active_pip_id` points at the employee's single
        in-flight plan, or is null when none exists; the server reconciles it
        whenever a plan enters or leaves its in-flight states."
        PRD §3.3: "the employee's `active_pip_id` is set to the plan" (issuance)
        and withdrawal "clears the employee's `active_pip_id`".

        Design: Corner/cross_cutting_complexity_layers/derived_field_employee_active_pip_id_reconciled_on_close
        """
        cast = setup_cast()
        concern, template = setup_concern_and_template(cast)
        pip = create_and_issue_pip(cast, concern["id"], template["id"])
        emp_after_issue = get_employee({**cast, "pip_id": pip["id"]})
        assert emp_after_issue["active_pip_id"] == pip["id"]
        validate_success(api.withdraw_pip(
            cast["ou_id"], cast["emp_id"], pip["id"],
            make_hrbp_headers(cast["hrbp_id"]),
        ))
        emp_after_withdraw = get_employee(cast)
        assert emp_after_withdraw.get("active_pip_id") is None, (
            "active_pip_id must be reconciled to null immediately on close"
        )


class TestIssuanceCascadeSecondAngle:
    def test_issue_bumps_pip_version(self, api):
        """PRD §3.3: "Issuance cascades outward: the concern flips to
        `SUPERSEDED_BY_PIP`, the employee's `active_pip_id` is set to the plan, and
        the plan's `version` increments."

        Design: Difficulty/transitive_cascade/concern_accept_cascades_coaching_entries_escalate_pip_issue_supersedes_concern
        """
        cast = setup_cast()
        concern, template = setup_concern_and_template(cast)
        pip = create_draft_pip(cast, concern["id"], template["id"])
        version_at_create = pip["version"]
        resp = api.issue_pip(
            cast["ou_id"], cast["emp_id"], pip["id"],
            {"expected_pip_version": version_at_create},
            make_hrbp_headers(cast["hrbp_id"]),
        )
        issued = validate_success(resp)
        assert issued["version"] == version_at_create + 1, (
            f"issuance must increment the plan version, got "
            f"{version_at_create} -> {issued['version']}"
        )


class TestTerminationCascadeSecondAngle:
    def test_termination_close_stamps_closed_at(self, api):
        """PRD §3.6: "An approved `TERMINATION` closes the plan `CLOSED_TERMINATED`
        after the rebuttal window resolves" and "Success and termination closures
        additionally clear the employee's `active_pip_id`, stamp `closed_at`".

        Design: Difficulty/transitive_cascade/termination_approval_cascades_pip_close_employee_term_link_rows
        """
        ctx = setup_active_pip(
            category="CONDUCT",
            goal_blueprints=[
                {"metric_key": "incidents", "target_value": 1, "unit": "count", "weight": 100},
            ],
        )
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        director = add_employee(ctx["ou_id"], "Director", "d@x.com", job_level=9)
        ctx["director_id"] = director["id"]
        create_and_submit_legal_review(
            ctx, hrbp_id=ctx["hrbp_id"],
            rationale="Documentation is complete; no elevated legal risk.",
        )
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        resp = propose_outcome(ctx, "TERMINATION", proposer_hrbp_id=proposer["id"],
                               rationale="No improvement observed over the full plan window.")
        decision = validate_success(resp, expected_status=201)
        validate_success(approve_outcome(ctx, decision["id"], director_id=director["id"]))
        set_clock(ctx["ou_id"], "2026-09-07T00:00:00Z")
        pip = get_pip(ctx)
        assert pip["status"] == "CLOSED_TERMINATED"
        assert pip.get("closed_at") == "2026-09-07T00:00:00Z", (
            f"closed_at must stamp the closure instant, got {pip.get('closed_at')}"
        )


class TestProvisionalFinalSecondAngle:
    def test_provisional_zero_when_only_evidence_excluded(self, api):
        """PRD §3.4: "only goals backed by admissible evidence contribute their
        measured value, and goals without admissible evidence contribute zero
        attainment — although their weight still counts in the denominator."

        Design: Difficulty/dual_variant_calc/pip_attainment_provisional_vs_final_diverge_on_admissibility
        """
        ctx = setup_active_pip(
            goal_blueprints=[
                {"metric_key": "defects_per_kloc", "target_value": 2, "unit": "count", "weight": 50},
                {"metric_key": "story_points", "target_value": 20, "unit": "points", "weight": 50},
            ],
        )
        hrbp_headers = make_hrbp_headers(ctx["hrbp_id"])
        # Manager submits (PRD §3.4: "A manager or an HRBP submits an item") so
        # the issuing HRBP may adjudicate without a segregation-of-duties clash.
        mgr_headers = make_manager_headers(ctx["mgr_id"])
        goals = {g["metric_key"]: g for g in get_goals(ctx)}
        # Submit two evidence items; exclude BOTH -> provisional must be 0.
        for metric, value in (("defects_per_kloc", 1), ("story_points", 20)):
            resp = api.submit_evidence(
                ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"],
                create_evidence_payload(goals[metric]["id"], observed_value=value,
                                        source="SELF_REPORT"),
                mgr_headers,
            )
            ev = validate_success(resp, expected_status=201)["id"]
            validate_success(api.exclude_evidence(
                ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"], ev,
                hrbp_headers,
            ))
        validate_success(api.mark_check_in_held(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["check_in_id"],
            create_mark_held_payload(notes="Reviewed both goals; no evidence admitted."),
            hrbp_headers,
        ))
        pip = get_pip(ctx)
        assert pip["provisional_attainment_ratio"] == pytest.approx(0.0, abs=1e-9), (
            "with no admissible evidence the provisional ratio must be 0"
        )


class TestLegalRiskScoreSecondAngles:
    def _setup_claimed_review(self, api):
        ctx = setup_issued_pip()
        counsel = add_employee(ctx["ou_id"], "Counsel", "l@x.com", job_level=8)
        ctx["counsel_id"] = counsel["id"]
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

    def test_documentation_gap_doubles_sub_threshold_base(self, api):
        """PRD §3.5: "If a documentation gap is among the factors, the base is
        doubled — a multiplicative interaction floored to a whole number."

        Design: Difficulty/dual_variant_calc/legal_risk_score_baseline_vs_documentation_gap_multiplier
        """
        ctx = self._setup_claimed_review(api)
        resp = api.submit_legal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["review_id"],
            submit_legal_review_payload(
                risk_factors=["PROTECTED_CLASS", "DOCUMENTATION_GAP"],
                recommendation="PROCEED_WITH_CAUTION",
                rationale=("Protected-class factor present with a documentation "
                           "gap; the doubled base stays below the compound "
                           "trigger threshold."),
            ),
            make_counsel_headers(ctx["counsel_id"]),
        )
        review = validate_success(resp)
        # (20 + 0) * 2 = 40; no whistleblower bonus; no clamp.
        assert review["risk_score"] == 40
        assert review["status"] == "SUBMITTED"

    def test_whistleblower_compound_bonus_applies_at_threshold(self, api):
        """PRD §3.5: "If the resulting base is at least 50 and whistleblower
        history is present, a further 10 points are added as a compound trigger."

        Design: Difficulty/combinatorial_formula/legal_risk_score_three_input_nonlinear_mode_a
        """
        ctx = self._setup_claimed_review(api)
        resp = api.submit_legal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], ctx["review_id"],
            submit_legal_review_payload(
                risk_factors=["WHISTLEBLOWER_HISTORY", "RETALIATION_WINDOW"],
                recommendation="HOLD",
                rationale=("Whistleblower history within the retaliation window "
                           "pushes the base to the compound trigger threshold."),
            ),
            make_counsel_headers(ctx["counsel_id"]),
        )
        review = validate_success(resp)
        # 30 + 25 = 55 >= 50 with whistleblower present -> +10 -> 65.
        assert review["risk_score"] == 65
        assert review["status"] == "SUBMITTED"


class TestNestedRoundingSecondAngle:
    def test_attainment_rounds_half_up_at_four_decimals(self, api):
        """PRD §2.9: "rounded half-up to exactly 4 decimal places, with rounding
        applied once at the end of each computation and never to intermediate
        per-goal values."

        Design: Difficulty/combinatorial_formula/pip_attainment_nested_rounding_mode_b
        """
        ctx = setup_issued_pip(
            goal_blueprints=[
                {"metric_key": "epics_closed", "target_value": 6, "unit": "count", "weight": 50},
                {"metric_key": "story_points", "target_value": 4, "unit": "points", "weight": 50},
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
        goals = {g["metric_key"]: g for g in get_goals(ctx)}
        for metric, value in (("epics_closed", 1), ("story_points", 1)):
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
            create_mark_held_payload(notes="Trajectory review on both goals."),
            hrbp_headers,
        ))
        pip = get_pip(ctx)
        # ((1/6)*50 + (1/4)*50)/100 = (8.333... + 12.5)/100 = 0.208333...
        # half-up at 4dp = 0.2083.
        assert pip["provisional_attainment_ratio"] == pytest.approx(0.2083, abs=1e-9), (
            f"expected 0.2083, got {pip['provisional_attainment_ratio']}"
        )


class TestWithdrawalInvariantsSecondAngle:
    def test_withdraw_cancels_scheduled_checkins(self, api):
        """PRD §3.3: "Withdrawal closes the plan as `CLOSED_WITHDRAWN`, stamps
        `closed_at`, clears the employee's `active_pip_id`, and flips every
        still-`SCHEDULED` check-in to `CANCELLED`."

        Design: Difficulty/compensating_invariant/pip_goal_weight_sum_conserved_across_create_withdraw
        """
        ctx = setup_active_pip()
        validate_success(api.withdraw_pip(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            make_hrbp_headers(ctx["hrbp_id"]),
        ))
        checkins = get_success_data(api.list_check_ins(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            make_hrbp_headers(ctx["hrbp_id"]),
        ))
        assert len(checkins) == 1
        assert checkins[0]["status"] == "CANCELLED", (
            f"scheduled check-in must be cancelled on withdrawal, got "
            f"{checkins[0]['status']}"
        )
        # The goal rows survive the close (weights still sum to 100).
        goals = get_goals(ctx)
        assert sum(g["weight"] for g in goals) == 100


class TestActivePipIdConservedSecondAngle:
    def test_active_pip_id_cleared_on_terminal_close(self, api):
        """PRD §3.1: "A computed `active_pip_id` points at the employee's single
        in-flight plan, or is null when none exists; the server reconciles it
        whenever a plan enters or leaves its in-flight states."
        PRD §3.6: "Success and termination closures additionally clear the
        employee's `active_pip_id`".

        Design: Difficulty/compensating_invariant/employee_active_pip_id_conserved_across_issue_then_close
        """
        ctx = setup_active_pip()
        goals = get_goals(ctx)
        from test_helpers import submit_and_adjudicate_evidence, hold_check_in
        submit_and_adjudicate_evidence(
            ctx, ctx["check_in_id"], goals[0]["id"], observed_value=2
        )
        hold_check_in(ctx, ctx["check_in_id"], notes="Goal met; sustaining trajectory.")
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        director = add_employee(ctx["ou_id"], "Director", "d@x.com", job_level=9)
        ctx["director_id"] = director["id"]
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        resp = propose_outcome(ctx, "SUCCESS", proposer_hrbp_id=proposer["id"],
                               rationale="Attainment at 1.0 across all goals on the plan.")
        decision = validate_success(resp, expected_status=201)
        validate_success(approve_outcome(ctx, decision["id"], director_id=director["id"]))
        # While the rebuttal window is open the plan still holds the in-flight id.
        emp_mid = get_employee(ctx)
        assert emp_mid["active_pip_id"] == ctx["pip_id"]
        set_clock(ctx["ou_id"], "2026-09-07T00:00:00Z")  # window lapses -> close
        emp_post = get_employee(ctx)
        assert emp_post.get("active_pip_id") is None, (
            "active_pip_id must return to null after terminal close"
        )
        pip = get_pip(ctx)
        assert pip["status"] == "CLOSED_SUCCESS"


class TestRebuttalWindowBoundarySecondAngle:
    def test_rebuttal_one_second_before_close_accepted(self, api):
        """PRD §3.7: "Filing must land inside the window: the clock reading at or
        before five days after the decision's `decided_at`, failing which the
        submission is rejected with `ERR_REBUTTAL_WINDOW_CLOSED`."

        Design: Difficulty/boundary_precision_check/rebuttal_window_close_at_exactly_plus_5_days
        """
        ctx = setup_active_pip(
            category="CONDUCT",
            goal_blueprints=[
                {"metric_key": "incidents", "target_value": 1, "unit": "count", "weight": 100},
            ],
        )
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        director = add_employee(ctx["ou_id"], "Director", "d@x.com", job_level=9)
        ctx["director_id"] = director["id"]
        create_and_submit_legal_review(
            ctx, hrbp_id=ctx["hrbp_id"],
            rationale="Documentation is complete; no elevated legal risk.",
        )
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        resp = propose_outcome(ctx, "TERMINATION", proposer_hrbp_id=proposer["id"],
                               rationale="No improvement observed over the full plan window.")
        decision = validate_success(resp, expected_status=201)
        validate_success(approve_outcome(ctx, decision["id"], director_id=director["id"]))
        # One second inside the window edge: 2026-09-05T23:59:59Z <= +5 days.
        set_clock(ctx["ou_id"], "2026-09-05T23:59:59Z")
        from test_helpers import create_rebuttal_payload
        body = (
            "Filed one second inside the window close. The attainment figure "
            "rested on evidence that was still pending review at decision time; "
            "I request re-tabulation before closure finalizes."
        )
        resp = api.create_rebuttal(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_rebuttal_payload(decision["id"], body=body),
            make_employee_headers(ctx["emp_id"]),
        )
        rebuttal = validate_success(resp, expected_status=201)
        assert rebuttal["status"] == "SUBMITTED"


class TestPriorityPairSecondAngles:
    def test_state_check_wins_even_with_valid_actor(self, api):
        """PRD §2.6: "then target-state validity (`ERR_INVALID_STATE`), then
        segregation of duties (`ERR_SEGREGATION_OF_DUTIES`)".
        PRD §3.2: "Acceptance moves the concern `SUBMITTED` → `ACCEPTED`" — a
        DRAFT concern cannot be accepted regardless of who asks.

        Design: Difficulty/priority_pair_validation_conflict/state_invalid_vs_sod_segregation_state_wins
        """
        cast = setup_cast()
        entry_ids = create_coaching_entries(cast)
        resp = api.create_concern(
            cast["ou_id"], cast["emp_id"],
            {"category": "QUALITY", "summary": "Quality below bar for level",
             "coaching_log_entry_ids": entry_ids},
            make_manager_headers(cast["mgr_id"]),
        )
        concern = validate_success(resp, expected_status=201)
        # A legitimate, unrelated HRBP (no SoD conflict) still gets INVALID_STATE
        # because the concern is DRAFT.
        resp = api.accept_concern(
            cast["ou_id"], cast["emp_id"], concern["id"],
            make_hrbp_headers(cast["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_attainment_guard_fires_when_no_segregation_conflict(self, api):
        """PRD §3.6: "a `SUCCESS` outcome requires a final attainment ratio of at
        least 0.80 (`ERR_ATTAINMENT_BELOW_THRESHOLD`)" and "the director must not
        be the proposer (`ERR_SEGREGATION_OF_DUTIES`)" — with a distinct director
        the segregation check passes and the attainment guard surfaces.

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_attainment_threshold_sod_wins
        """
        ctx = setup_active_pip()
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        director = add_employee(ctx["ou_id"], "Director", "d@x.com", job_level=9)
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        # No evidence admitted -> final attainment 0.
        resp = propose_outcome(ctx, "SUCCESS", proposer_hrbp_id=proposer["id"],
                               rationale="Proposing success despite empty evidence record.")
        validate_error(resp, ApiErrorId.ERR_ATTAINMENT_BELOW_THRESHOLD)
