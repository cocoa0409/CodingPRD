"""Activation: the training-compliance boundary and the order of the three gates."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_plan_metrics,
    assert_plan_state,
    assert_readiness,
    build_plan_activation,
    read_plan,
    setup_draft_plan,
    setup_five_pair_training_cohort,
    setup_screened_plan,
    setup_submitted_plan,
)


def _submitted_plan_on_cohort(api: ApiClient, completed: int):
    """A submitted front-desk plan on a five-pair training cohort."""
    ctx = setup_five_pair_training_cohort(api, completed=completed)
    ctx = setup_draft_plan(api, ctx)
    ctx = setup_screened_plan(api, ctx)
    return setup_submitted_plan(api, ctx)


class TestTrainingComplianceBoundary:
    """Four completions of five pairs is exactly the inclusive activation minimum."""

    def test_training_compliance_of_exactly_eighty_percent_activates_the_plan(
        self, api: ApiClient
    ) -> None:
        """Four of five completed pairs reads 80.00 and the site manager's activation succeeds.

        PRD: "Third, `training_compliance_pct` must be at least 80.00, an inclusive boundary where exactly 80.00 passes and 79.99 fails, or the request is refused with `ERR_TRAINING_COMPLIANCE_BELOW_THRESHOLD`."
        Design: Difficulty/boundary_precision_check/training_compliance_exactly_eighty_percent_permits_activation
        """
        ctx = _submitted_plan_on_cohort(api, completed=4)
        assert_plan_metrics(
            read_plan(api, ctx), hazard_coverage_pct=100.00, training_compliance_pct=80.00
        )

        activated = get_success_data(
            api.activate_prevention_plan(
                ctx["plan"]["id"],
                build_plan_activation(
                    activation_note="Coverage complete and training at the minimum; approved."
                ),
                ctx["headers"]["site_manager"],
            )
        )

        assert_plan_state(activated, status="ACTIVE", compliance_posture="OPEN")
        assert activated["activated_by_employee_id"] == ctx["sm2"]["id"]
        assert activated["activated_at"] == "2026-08-01T00:00:00Z"

    def test_activation_at_the_boundary_stamps_the_review_due_date_and_readiness(
        self, api: ApiClient
    ) -> None:
        """The boundary activation dates review a year out and scores 75.20 as inspection ready.

        PRD: "A successful activation writes `activated_by_employee_id` from the caller, `activated_at` from the logical clock, and `review_due_date` as `activated_at` advanced by `review_interval_days` — recomputed afresh on every activation."
        Design: Difficulty/boundary_precision_check/training_compliance_exactly_eighty_percent_permits_activation
        """
        ctx = _submitted_plan_on_cohort(api, completed=4)

        activated = get_success_data(
            api.activate_prevention_plan(
                ctx["plan"]["id"],
                build_plan_activation(
                    activation_note="Coverage complete and training at the minimum; approved."
                ),
                ctx["headers"]["site_manager"],
            )
        )

        assert activated["review_due_date"] == "2027-08-01T00:00:00Z"
        assert_readiness(
            activated,
            subtotal=80.00,
            penalty_band="ADEQUATE",
            penalty_points=4.80,
            score=75.20,
            inspection_ready=True,
        )
        last_completion = get_success_data(
            api.get_training_assignment(
                ctx["assignments"][3]["id"], ctx["headers"]["hr_partner"]
            )
        )
        assert last_completion["status"] == "COMPLETED"
        assert last_completion["score"] == 88
        assert last_completion["expires_at"] == "2027-08-01T00:00:00Z"


class TestGateOrderOnActivation:
    """Segregation of duties is checked before the training-compliance gate."""

    def test_self_approval_reports_segregation_of_duties_not_the_training_gate(
        self, api: ApiClient
    ) -> None:
        """The submitter activating her own plan is refused for segregation while training sits at 60.00.

        PRD: "First, the acting `X-User-ID` must differ from `submitted_by_employee_id`; a submitter attempting to activate their own submission is refused with `ERR_SEGREGATION_OF_DUTIES`."
        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_training_compliance_gate
        """
        ctx = _submitted_plan_on_cohort(api, completed=3)
        assert_plan_metrics(
            read_plan(api, ctx), hazard_coverage_pct=100.00, training_compliance_pct=60.00
        )

        response = api.activate_prevention_plan(
            ctx["plan"]["id"],
            build_plan_activation(activation_note="Self-approving my own submission."),
            ctx["headers"]["site_manager_self"],
        )

        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES, 409)
        assert (
            response.json()["data"]["error_id"]
            != ApiErrorId.TRAINING_COMPLIANCE_BELOW_THRESHOLD
        )
        plan = read_plan(api, ctx)
        assert_plan_state(plan, status="IN_REVIEW", compliance_posture="FROZEN", inspection_ready=False)
        assert plan["activated_by_employee_id"] is None
        assert plan["activated_at"] is None

    def test_independent_site_manager_then_surfaces_the_training_compliance_gate(
        self, api: ApiClient
    ) -> None:
        """With the segregation conflict removed the same plan fails on 60.00 percent training.

        PRD: "Third, `training_compliance_pct` must be at least 80.00, an inclusive boundary where exactly 80.00 passes and 79.99 fails, or the request is refused with `ERR_TRAINING_COMPLIANCE_BELOW_THRESHOLD`."
        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_training_compliance_gate
        """
        ctx = _submitted_plan_on_cohort(api, completed=3)
        validate_error(
            api.activate_prevention_plan(
                ctx["plan"]["id"],
                build_plan_activation(activation_note="Self-approving my own submission."),
                ctx["headers"]["site_manager_self"],
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            409,
        )

        response = api.activate_prevention_plan(
            ctx["plan"]["id"],
            build_plan_activation(
                activation_note="Independent review of the front desk plan."
            ),
            ctx["headers"]["site_manager"],
        )

        validate_error(response, ApiErrorId.TRAINING_COMPLIANCE_BELOW_THRESHOLD, 409)
        plan = read_plan(api, ctx)
        assert_plan_state(plan, status="IN_REVIEW", compliance_posture="FROZEN", inspection_ready=False)
        assert_plan_metrics(plan, training_compliance_pct=60.00)
