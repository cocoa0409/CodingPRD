"""Two non-linear machines: the counselor's parallel dimensions and the statement fork-join."""

import pytest

from test_helpers import (
    COMPLIANCE_AUDITOR_USER_ID,
    SECOND_COMPLIANCE_AUDITOR_USER_ID,
    fixtures,
)


class TestCounselorParallelDimensions:
    @pytest.fixture
    def rated_pipeline(self, api):
        """One counselor with four rated leads, two of them past the 24-hour SLA."""
        context = fixtures.build_launched_program(
            api, service_domains=("MARKETING", "ENROLLMENT_COUNSELING")
        )
        ps_id, pg_id, co_id = context["ps_id"], context["pg_id"], context["co_id"]

        converted = fixtures.create_applied_lead(api, ps_id, pg_id, co_id)
        fixtures.enroll_lead(api, converted["id"])

        late_one = fixtures.create_lead(
            api, ps_id, pg_id, co_id, prospect_external_id="P-1002", source_channel="PAID_SOCIAL"
        )
        fixtures.contact_lead(api, ps_id, late_one["id"], 30)
        late_two = fixtures.create_lead(
            api, ps_id, pg_id, co_id, prospect_external_id="P-1003", source_channel="ORGANIC"
        )
        fixtures.contact_lead(api, ps_id, late_two["id"], 40)
        prompt = fixtures.create_lead(
            api,
            ps_id,
            pg_id,
            co_id,
            prospect_external_id="P-1004",
            source_channel="EMPLOYER_REFERRAL",
        )
        fixtures.contact_lead(api, ps_id, prompt["id"], 9)
        return context

    def test_performance_run_rates_the_window_and_leaves_incentive_eligibility_alone(
        self, api, rated_pipeline
    ):
        """A breach ratio above 0.3000 downgrades one step and touches nothing else.

        PRD: "Otherwise `conversion_rate` is `enrolled_lead_count` divided by `rated_lead_count`,
        rounded half up to 4 decimal places, and a base rating is chosen from it —
        `MEETS_STANDARD` when the rate is at least 0.2500, otherwise `WATCH` when the rate is at
        least 0.1500, otherwise `PROBATION`."
        PRD: "when that ratio is strictly greater than 0.3000 — the comparison is exclusive, so a
        ratio of exactly 0.3000 triggers nothing — the counselor is moved one step down the ladder
        from the base rating, `MEETS_STANDARD` becoming `WATCH` and `WATCH` becoming `PROBATION`,
        with `PROBATION` absorbing the downgrade and staying where it is."
        PRD: "A performance run never touches incentive eligibility, and a compliance decision
        never touches performance status."

        Design: Difficulty/non_linear_state_machine/counselor_parallel_dimensions_advance_independently
        """
        ps_id, co_id = rated_pipeline["ps_id"], rated_pipeline["co_id"]
        fixtures.run_performance_evaluation(api, ps_id)

        counselor = fixtures.read_counselor(api, co_id)
        assert counselor["rated_lead_count"] == 4
        assert counselor["enrolled_lead_count"] == 1
        assert counselor["sla_breach_count"] == 2
        assert counselor["conversion_rate"] == pytest.approx(0.2500, abs=0.0001)
        assert counselor["performance_status"] == "WATCH"
        assert counselor["incentive_eligibility"] == "ELIGIBLE"

    def test_compliance_suspension_moves_only_the_incentive_dimension(self, api, rated_pipeline):
        """A later compliance SUSPEND leaves the performance rating exactly where it was.

        PRD: "No transition on either dimension reads or writes the other: a performance run
        leaves `incentive_eligibility` exactly as it found it, a compliance decision leaves
        `performance_status` exactly as it found it, and the teach-out cascade that drives a
        counselor to `INACTIVE_PENDING_REVIEW` leaves the incentive dimension alone."
        PRD: "A `decision` of `SUSPEND` takes either `PENDING_COMPLIANCE_REVIEW` or `ELIGIBLE`
        to `SUSPENDED`."
        PRD: "Every decision records the acting `X-User-ID` as `last_review_user_id`."

        Design: Difficulty/non_linear_state_machine/counselor_parallel_dimensions_advance_independently
        """
        ps_id, co_id = rated_pipeline["ps_id"], rated_pipeline["co_id"]
        fixtures.run_performance_evaluation(api, ps_id)

        counselor = fixtures.review_counselor(
            api,
            co_id,
            "SUSPEND",
            reviewer_user_id=SECOND_COMPLIANCE_AUDITOR_USER_ID,
            reviewer_note="Plan documentation withdrawn pending re-file.",
        )

        assert counselor["incentive_eligibility"] == "SUSPENDED"
        assert counselor["performance_status"] == "WATCH"
        assert counselor["last_review_user_id"] == SECOND_COMPLIANCE_AUDITOR_USER_ID
        assert counselor["last_review_user_id"] != COMPLIANCE_AUDITOR_USER_ID


class TestStatementDisputeBranchRejoinsBeforeRemit:
    @pytest.fixture
    def disputed_then_resolved(self, api):
        """September statement taken down the dispute branch and restated on the milestone basis."""
        context = fixtures.build_september_statement(api)
        fixtures.dispute_statement(
            api,
            context["ps_id"],
            context["st_id"],
            "Milestone basis contractually applies for the first term.",
        )
        fixtures.resolve_statement(
            api,
            context["st_id"],
            recognition_method_override="MILESTONE_CHRONOLOGICAL",
            adjustment_note="Agreed restatement on the milestone basis.",
        )
        return context

    def test_resolved_branch_rejoins_at_university_approved_and_exits_at_remitted(
        self, api, disputed_then_resolved
    ):
        """The dispute branch is approved exactly as the straight branch is, then remits once.

        PRD: "The two branches then **join**: a `RESOLVED_ADJUSTED` statement is approved by a
        `UniversityProvost` exactly as a `CALCULATED` one is, taking `RESOLVED_ADJUSTED →
        UNIVERSITY_APPROVED`, subject to the same segregation-of-duties check against
        `authored_by_user_id` and recording the same `approved_by_user_id`."
        PRD: "From the join there is one exit. A `UniversityBursar` remits with a mandatory
        `remittance_reference`, taking `UNIVERSITY_APPROVED → REMITTED`, which requires
        `net_payable_cents` to be strictly greater than zero — remitting nothing, or a negative
        balance, is refused with `ERR_NOTHING_TO_REMIT`."

        Design: Difficulty/non_linear_state_machine/statement_dispute_branch_rejoins_at_university_approved_before_remit
        """
        st_id = disputed_then_resolved["st_id"]
        approved = fixtures.approve_statement(api, st_id)
        assert approved["status"] == "UNIVERSITY_APPROVED"

        remitted = fixtures.remit_statement(api, st_id)
        assert remitted["status"] == "REMITTED"
        assert remitted["resolved_by_user_id"] == "bursar-1"
        assert remitted["approved_by_user_id"] == "provost-1"
        assert remitted["adjustment_delta_cents"] == 13141
        assert remitted["net_payable_cents"] == 87060

    def test_remittance_posts_the_restated_figures_onto_the_partnership_ledger(
        self, api, disputed_then_resolved
    ):
        """Remittance moves net payable, holdback and recoupment onto the partnership.

        PRD: "Remittance stamps `remitted_at` with the logical clock instant, adds
        `net_payable_cents` to the partnership's `remitted_to_partner_cents`, adds
        `holdback_cents` to the partnership's `holdback_balance_cents`, and subtracts
        `marketing_recoupment_cents` from the partnership's
        `unrecouped_marketing_spend_cents`."

        Design: Difficulty/non_linear_state_machine/statement_dispute_branch_rejoins_at_university_approved_before_remit
        """
        ps_id, st_id = disputed_then_resolved["ps_id"], disputed_then_resolved["st_id"]
        fixtures.approve_statement(api, st_id)
        fixtures.remit_statement(api, st_id)

        partnership = fixtures.read_partnership(api, ps_id)
        assert partnership["remitted_to_partner_cents"] == 87060
        assert partnership["holdback_balance_cents"] == 4582
        assert partnership["unrecouped_marketing_spend_cents"] == 283829
