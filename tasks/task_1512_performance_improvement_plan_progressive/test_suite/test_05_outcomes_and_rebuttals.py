"""Outcome-decision claims: approval cascade to closure, legal-review gating,
attainment boundary, proposal supersession, and rebuttal branching."""
import pytest

from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_cast,
    add_employee,
    setup_active_pip,
    setup_pip_ready_for_outcome,
    create_and_submit_legal_review,
    propose_outcome,
    approve_outcome,
    get_pip,
    get_employee,
    get_goals,
    set_clock,
    submit_and_adjudicate_evidence,
    hold_check_in,
    create_rebuttal_payload,
    make_hrbp_headers,
    make_director_headers,
    make_employee_headers,
)

LONG_REBUTTAL = (
    "I dispute the attainment computation: the final check-in evidence was not "
    "admitted despite being submitted before the deadline, and the incidents "
    "metric was mis-scoped to include team-wide events. I request an independent "
    "re-tabulation of the goal evidence and a review of the cadence violations "
    "that prevented two check-ins from being held."
)


def _setup_approved_termination(api, decision_clock="2026-09-01T00:00:00Z",
                                after_approve_clock="2026-09-03T00:00:00Z"):
    """ACTIVE PIP + legal PROCEED + APPROVED TERMINATION decision.

    Returns ctx with decision_id, proposer_id, director_id populated.
    """
    ctx = setup_active_pip(
        category="CONDUCT",
        goal_blueprints=[
            {"metric_key": "incidents", "target_value": 1, "unit": "count", "weight": 100},
        ],
    )
    proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
    director = add_employee(ctx["ou_id"], "Director", "d@x.com", job_level=9)
    ctx["proposer_id"] = proposer["id"]
    ctx["director_id"] = director["id"]
    create_and_submit_legal_review(
        ctx, hrbp_id=ctx["hrbp_id"],
        rationale="Documentation is complete; no protected-class, leave, whistleblower, or retaliation-window factors identified.",
    )
    set_clock(ctx["ou_id"], decision_clock)
    resp = propose_outcome(ctx, "TERMINATION", proposer_hrbp_id=proposer["id"],
                           rationale="No measurable improvement over the 30-day plan; conduct incidents continued.")
    decision = validate_success(resp, expected_status=201)
    ctx["decision_id"] = decision["id"]
    resp = approve_outcome(ctx, decision["id"], director_id=director["id"])
    validate_success(resp)
    if after_approve_clock:
        set_clock(ctx["ou_id"], after_approve_clock)
    return ctx


class TestTerminationCascade:
    def test_termination_approval_cascades_to_employee_and_links(self, api):
        """PRD §3.6: "An approved `TERMINATION` closes the plan `CLOSED_TERMINATED`
        after the rebuttal window resolves, cascading the employee's
        `employment_status` to `TERMINATED` and stamping `terminated_at`. Success
        and termination closures additionally clear the employee's `active_pip_id`,
        stamp `closed_at`, and write a rating-cycle outcome link for every rating
        cycle in the same org unit whose window — `window_start` inclusive to
        `window_end` exclusive — overlaps the plan's own window and whose status is
        `OPEN`, `CALIBRATION`, or `PUBLISHED`."

        Design: Difficulty/transitive_cascade/termination_approval_cascades_pip_close_employee_term_link_rows
        """
        ctx = setup_active_pip()
        hrbp_headers = make_hrbp_headers(ctx["hrbp_id"])
        # Rating cycle overlapping the plan window [2026-08-01, 2026-08-31).
        resp = api.create_rating_cycle(
            ctx["ou_id"],
            {"label": "2026-H2", "window_start": "2026-07-01T00:00:00Z",
             "window_end": "2026-12-31T00:00:00Z"},
            hrbp_headers,
        )
        cycle = validate_success(resp, expected_status=201)
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        create_and_submit_legal_review(ctx, hrbp_id=ctx["hrbp_id"],
                                       rationale="Documentation complete; no risk factors present.")
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        resp = propose_outcome(ctx, "TERMINATION", proposer_hrbp_id=proposer["id"],
                               rationale="No improvement over plan window; defect rate unchanged.")
        decision = validate_success(resp, expected_status=201)
        resp = approve_outcome(ctx, decision["id"])
        validate_success(resp)
        # No rebuttal filed; advance past the 5-day window so closure finalizes.
        set_clock(ctx["ou_id"], "2026-09-07T00:00:00Z")

        pip = get_pip(ctx)
        assert pip["status"] == "CLOSED_TERMINATED", (
            f"plan must be CLOSED_TERMINATED after window lapse, got {pip['status']}"
        )
        emp = get_employee(ctx)
        assert emp["employment_status"] == "TERMINATED"
        assert emp["terminated_at"] == "2026-09-07T00:00:00Z", (
            f"terminated_at must stamp the closure instant, got {emp.get('terminated_at')}"
        )
        assert emp.get("active_pip_id") is None
        links = get_success_data(api.list_rating_cycle_outcome_links(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], hrbp_headers
        ))
        assert len(links) == 1
        assert links[0]["rating_cycle_id"] == cycle["id"]
        assert links[0]["pip_outcome_at_link"] == "TERMINATION"


class TestTerminationLegalGate:
    def test_termination_propose_without_legal_review_rejected(self, api):
        """PRD §3.6: "Three guards attach at proposal time and again at approval:
        ... a `TERMINATION` requires a completed legal review — one in `SUBMITTED`
        or `OVERRIDDEN` — whose recommendation is not `REJECT`, unless that review
        was itself overridden (`ERR_LEGAL_REVIEW_REQUIRED`)."

        Design: Difficulty/cross_entity_state_dependency/outcome_approve_termination_requires_legal_review_submitted
        """
        ctx = setup_active_pip(
            category="CONDUCT",
            goal_blueprints=[
                {"metric_key": "incidents", "target_value": 1, "unit": "count", "weight": 100},
            ],
        )
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        resp = propose_outcome(ctx, "TERMINATION", proposer_hrbp_id=proposer["id"],
                               rationale="No improvement over the plan window; proceeding to termination.")
        validate_error(resp, ApiErrorId.ERR_LEGAL_REVIEW_REQUIRED)


class TestAttainmentThresholdBoundary:
    def test_success_proposal_at_exactly_080_accepted(self, api):
        """PRD §3.6: "a `SUCCESS` outcome requires a final attainment ratio of at
        least 0.80 (`ERR_ATTAINMENT_BELOW_THRESHOLD`)" — "at least 0.80" makes the
        0.80 boundary inclusive.

        Design: Difficulty/boundary_precision_check/attainment_threshold_080_inclusive_boundary
        """
        ctx = setup_active_pip(
            goal_blueprints=[
                {"metric_key": "defects", "target_value": 5, "unit": "count", "weight": 100},
            ],
        )
        goals = get_goals(ctx)
        submit_and_adjudicate_evidence(
            ctx, ctx["check_in_id"], goals[0]["id"], observed_value=4
        )
        hold_check_in(ctx, ctx["check_in_id"],
                      notes="Mid-plan trajectory review covering defect rate.")
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        resp = propose_outcome(
            ctx, "SUCCESS", proposer_hrbp_id=proposer["id"],
            rationale="Attainment at the 0.80 boundary; this proposal must be accepted because the threshold is inclusive.",
        )
        decision = validate_success(resp, expected_status=201)
        assert decision["final_attainment_ratio_at_decision"] == pytest.approx(0.80, abs=1e-9)
        assert decision["status"] == "PROPOSED"

    def test_success_proposal_below_080_rejected(self, api):
        """PRD §3.6: "a `SUCCESS` outcome requires a final attainment ratio of at
        least 0.80 (`ERR_ATTAINMENT_BELOW_THRESHOLD`)".

        Design: Difficulty/boundary_precision_check/attainment_threshold_080_inclusive_boundary
        """
        ctx = setup_active_pip(
            goal_blueprints=[
                {"metric_key": "defects", "target_value": 5, "unit": "count", "weight": 100},
            ],
        )
        goals = get_goals(ctx)
        # 3/5 = 0.6 < 0.80
        submit_and_adjudicate_evidence(
            ctx, ctx["check_in_id"], goals[0]["id"], observed_value=3
        )
        hold_check_in(ctx, ctx["check_in_id"],
                      notes="Mid-plan trajectory review covering defect rate.")
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        resp = propose_outcome(
            ctx, "SUCCESS", proposer_hrbp_id=proposer["id"],
            rationale="Attainment below the 0.80 threshold; must be rejected.",
        )
        validate_error(resp, ApiErrorId.ERR_ATTAINMENT_BELOW_THRESHOLD)


class TestOutcomeProposalSupersession:
    def test_new_proposal_supersedes_prior_proposed_decision(self, api):
        """PRD §3.6: "Proposing a new decision also supersedes any decision still
        standing `PROPOSED` on the same plan, and the new decision opens in
        `PROPOSED`."

        Design: Corner/state_machines/outcome_decision_superseded_on_new_proposal
        """
        ctx = setup_active_pip()
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        resp = propose_outcome(ctx, "EXTENSION", proposer_hrbp_id=proposer["id"],
                               rationale="Initial proposal: extend the plan by 15 days.")
        d1 = validate_success(resp, expected_status=201)
        resp = propose_outcome(ctx, "EXTENSION", proposer_hrbp_id=proposer["id"],
                               rationale="Revised proposal: shorter extension after re-tabulation.")
        d2 = validate_success(resp, expected_status=201)
        decisions = get_success_data(api.list_outcome_decisions(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            make_hrbp_headers(ctx["hrbp_id"]),
        ))
        by_id = {d["id"]: d for d in decisions}
        assert by_id[d1["id"]]["status"] == "SUPERSEDED"
        assert by_id[d2["id"]]["status"] == "PROPOSED"


class TestLegalRejectCascade:
    def test_legal_reject_supersedes_proposed_outcome(self, api):
        """PRD §3.5: "a `REJECT` recommendation cascades: any outcome decision
        still `PROPOSED` on the plan flips to `SUPERSEDED`."

        Design: Corner/cross_cutting_complexity_layers/cascade_legal_reject_supersedes_proposed_outcome
        """
        ctx = setup_active_pip(
            category="CONDUCT",
            goal_blueprints=[
                {"metric_key": "incidents", "target_value": 1, "unit": "count", "weight": 100},
            ],
        )
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        counsel = add_employee(ctx["ou_id"], "Counsel", "l@x.com", job_level=8)
        ctx["counsel_id"] = counsel["id"]
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        # EXTENSION (not TERMINATION): the §3.6 legal-review guard attaches at
        # proposal time, so a TERMINATION proposal without a completed review
        # would be rejected outright and no PROPOSED decision could stand.
        resp = propose_outcome(ctx, "EXTENSION", proposer_hrbp_id=proposer["id"],
                               rationale="Proposing an extension pending legal review.")
        decision = validate_success(resp, expected_status=201)
        # Request, claim, then submit a REJECT review.
        from test_helpers import create_legal_review_payload, submit_legal_review_payload, make_counsel_headers
        resp = api.create_legal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_legal_review_payload(counsel["id"]),
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        review = validate_success(resp, expected_status=201)
        validate_success(api.claim_legal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], review["id"],
            make_counsel_headers(counsel["id"]),
        ))
        resp = api.submit_legal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], review["id"],
            submit_legal_review_payload(
                risk_factors=["WHISTLEBLOWER_HISTORY", "RETALIATION_WINDOW"],
                recommendation="REJECT",
                rationale=("Employee filed a whistleblower complaint 6 weeks ago "
                           "and is within the retaliation-safe harbor window; "
                           "termination would create material legal exposure."),
            ),
            make_counsel_headers(counsel["id"]),
        )
        submitted = validate_success(resp)
        assert submitted["status"] == "SUBMITTED"
        decisions = get_success_data(api.list_outcome_decisions(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            make_hrbp_headers(ctx["hrbp_id"]),
        ))
        by_id = {d["id"]: d for d in decisions}
        assert by_id[decision["id"]]["status"] == "SUPERSEDED", (
            "REJECT recommendation must supersede the standing PROPOSED decision"
        )


class TestRebuttalBranching:
    def test_overruled_rebuttal_reverses_termination(self, api):
        """PRD §3.7: "Overruling an approved `TERMINATION` rescinds the
        termination: the plan closes `CLOSED_FAILED` and the employee's
        `employment_status` remains `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/rebuttal_branching_upheld_vs_overruled_paths_diverge
        """
        ctx = _setup_approved_termination(api)
        reviewer = add_employee(ctx["ou_id"], "Reviewer", "h2@x.com", job_level=7)
        resp = api.create_rebuttal(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_rebuttal_payload(ctx["decision_id"], body=LONG_REBUTTAL),
            make_employee_headers(ctx["emp_id"]),
        )
        rebuttal = validate_success(resp, expected_status=201)
        validate_success(api.start_rebuttal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], rebuttal["id"],
            make_hrbp_headers(reviewer["id"]),
        ))
        resp = api.resolve_rebuttal(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], rebuttal["id"],
            {"resolution": "OVERRULED",
             "resolution_rationale": ("Independent re-tabulation confirmed the "
                                      "admitted evidence does not support the "
                                      "attainment figure used at decision time; "
                                      "the termination outcome is reversed.")},
            make_hrbp_headers(reviewer["id"]),
        )
        resolved = validate_success(resp)
        assert resolved["status"] == "OVERRULED"
        pip = get_pip(ctx)
        assert pip["status"] == "CLOSED_FAILED", (
            f"overruled TERMINATION must close plan CLOSED_FAILED, got {pip['status']}"
        )
        emp = get_employee(ctx)
        assert emp["employment_status"] == "ACTIVE", (
            "termination rescinded: employee must remain ACTIVE"
        )

    def test_upheld_rebuttal_lets_success_close(self, api):
        """PRD §3.7: "Upholding an approved `SUCCESS` lets the plan proceed to
        `CLOSED_SUCCESS`."

        Design: Difficulty/non_linear_state_machine/rebuttal_branching_upheld_vs_overruled_paths_diverge
        """
        ctx = setup_active_pip()
        goals = get_goals(ctx)
        submit_and_adjudicate_evidence(
            ctx, ctx["check_in_id"], goals[0]["id"], observed_value=2
        )
        hold_check_in(ctx, ctx["check_in_id"], notes="Goal met; sustaining trajectory.")
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        director = add_employee(ctx["ou_id"], "Director", "d@x.com", job_level=9)
        reviewer = add_employee(ctx["ou_id"], "Reviewer", "h2@x.com", job_level=7)
        ctx["director_id"] = director["id"]
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        resp = propose_outcome(ctx, "SUCCESS", proposer_hrbp_id=proposer["id"],
                               rationale="Attainment at 1.0 across all goals on the plan.")
        decision = validate_success(resp, expected_status=201)
        validate_success(approve_outcome(ctx, decision["id"], director_id=director["id"]))
        set_clock(ctx["ou_id"], "2026-09-03T00:00:00Z")
        resp = api.create_rebuttal(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_rebuttal_payload(decision["id"], body=LONG_REBUTTAL),
            make_employee_headers(ctx["emp_id"]),
        )
        rebuttal = validate_success(resp, expected_status=201)
        validate_success(api.start_rebuttal_review(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], rebuttal["id"],
            make_hrbp_headers(reviewer["id"]),
        ))
        resp = api.resolve_rebuttal(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"], rebuttal["id"],
            {"resolution": "UPHELD",
             "resolution_rationale": ("Re-tabulation confirms the admitted evidence "
                                      "supports the attainment figure; the success "
                                      "outcome stands.")},
            make_hrbp_headers(reviewer["id"]),
        )
        resolved = validate_success(resp)
        assert resolved["status"] == "UPHELD"
        pip = get_pip(ctx)
        assert pip["status"] == "CLOSED_SUCCESS", (
            f"upheld SUCCESS must close plan CLOSED_SUCCESS, got {pip['status']}"
        )
