"""Inclusive thresholds and the empty-divisor edge, one hundredth and one enrollment apart."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    make_partner_account_lead_headers,
    make_provost_headers,
)

MSN_PROGRAM_OVERRIDES = {
    "program_name": "MSN Online",
    "cip_code": "52.0801",
    "required_service_domains": [],
}
MSN_COURSE_OVERRIDES = {
    "course_code": "MSN-501",
    "title": "Population Health Foundations",
    "design_cost_cents": 900000,
    "required_for_launch": False,
}


class TestConfirmedScoreApprovalThresholdIsInclusive:
    @pytest.fixture
    def two_submitted_programs(self, api):
        """Two SUBMITTED programs differing only in prior-year inquiry volume, 1750 against 1740."""
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]

        at_threshold = fixtures.create_program(api, ps_id)
        fixtures.create_approved_course(api, ps_id, at_threshold["id"])
        fixtures.assign_service_scope(api, at_threshold["id"], "MARKETING")
        fixtures.submit_program(api, ps_id, at_threshold["id"])

        below_threshold = fixtures.create_program(
            api, ps_id, prior_year_inquiry_volume=1740, **MSN_PROGRAM_OVERRIDES
        )
        fixtures.add_course(api, ps_id, below_threshold["id"], **MSN_COURSE_OVERRIDES)
        fixtures.submit_program(api, ps_id, below_threshold["id"])

        return {"ps_id": ps_id, "pg_id": at_threshold["id"], "pgB_id": below_threshold["id"]}

    def test_confirmed_score_of_exactly_sixty_two_is_admitted(self, api, two_submitted_programs):
        """An inquiry volume of 1750 lands the confirmed score on the threshold itself.

        PRD: "and the freshly recomputed `demand_score_confirmed` to be at least 62.00, failing
        which the refusal is `ERR_DEMAND_SCORE_BELOW_APPROVAL_THRESHOLD`. That comparison is
        inclusive too: exactly 62.00 passes."
        PRD: "The **confirmed** variant takes the effective projection to be the smaller of
        `projected_annual_enrollments` and the observed funnel converted at a yield of one inquiry
        in ten — that is, `prior_year_inquiry_volume` multiplied by 0.10 and rounded half up to a
        whole number — and writes its result to `demand_score_confirmed`."

        Design: Difficulty/boundary_precision_check/confirmed_demand_score_exactly_at_approval_threshold_is_inclusive
        """
        program = fixtures.approve_program(api, two_submitted_programs["pg_id"])

        assert program["demand_score_confirmed"] == pytest.approx(62.00, abs=0.01)
        assert program["status"] == "APPROVED"

    def test_confirmed_score_one_hundredth_below_is_refused(self, api, two_submitted_programs):
        """An inquiry volume of 1740 lands on 61.90 and the approval is refused.

        PRD: "the freshly recomputed `demand_score_confirmed` to be at least 62.00, failing
        which the refusal is `ERR_DEMAND_SCORE_BELOW_APPROVAL_THRESHOLD`."
        PRD: "The product is rounded half up to 2 decimal places."
        PRD: "Any lifecycle action that does not match a legal transition out of the program's
        current `status` is refused with `ERR_PROGRAM_INVALID_STATE`."

        Design: Difficulty/boundary_precision_check/confirmed_demand_score_exactly_at_approval_threshold_is_inclusive
        """
        context = two_submitted_programs
        fixtures.approve_program(api, context["pg_id"])

        response = api.post_program_lifecycle_action(
            context["pgB_id"], factories.lifecycle_action_payload("APPROVE"), headers=make_provost_headers()
        )
        validate_error(response, ApiErrorId.DEMAND_SCORE_BELOW_APPROVAL_THRESHOLD.value, 422)

        refused = fixtures.read_program(api, context["pgB_id"])
        assert refused["demand_score_confirmed"] == pytest.approx(61.90, abs=0.01)
        assert refused["status"] == "SUBMITTED"


class TestBlendedCacAtTheEmptyDivisorEdge:
    @pytest.fixture
    def two_launched_programs_one_with_a_student(self, api):
        """Two LAUNCHED programs under one contract; only the second has converted a student."""
        context = fixtures.build_launched_program(api)
        ps_id, co_id = context["ps_id"], context["co_id"]

        with_student = fixtures.create_program(api, ps_id, **MSN_PROGRAM_OVERRIDES)
        pgB_id = with_student["id"]
        fixtures.add_course(api, ps_id, pgB_id, **MSN_COURSE_OVERRIDES)
        fixtures.submit_program(api, ps_id, pgB_id)
        fixtures.approve_program(api, pgB_id)
        fixtures.launch_program(api, ps_id, pgB_id)

        lead = fixtures.create_applied_lead(
            api, ps_id, pgB_id, co_id, prospect_external_id="P-1101"
        )
        fixtures.enroll_lead(api, lead["id"], student_external_id="S-2101")

        context["pgB_id"] = pgB_id
        return context

    def test_identical_spend_gives_null_cac_at_zero_enrollments_and_an_integer_at_one(
        self, api, two_launched_programs_one_with_a_student
    ):
        """The same 300,000-cent spend reports null on one program and 300,000 on the other.

        PRD: "A program's `blended_cac_cents` is its `marketing_spend_net_cents` divided by its
        `total_enrollment_count`, rounded half up to whole cents. When `total_enrollment_count` is
        zero the value is null — never 0 — because dividing spend by no enrollments has no
        meaning, and the distinction between "no students yet" and "free students" must survive
        into the response."
        PRD: "For one program, `marketing_spend_net_cents` is the sum of `amount_cents` over
        that program's media ledger entries whose `entry_type` is `SPEND`, less the sum over
        those whose `entry_type` is `CREDIT_MEMO`."

        Design: Difficulty/boundary_precision_check/blended_cac_is_null_at_zero_enrollments_and_exact_at_first_enrollment
        """
        context = two_launched_programs_one_with_a_student
        ps_id = context["ps_id"]
        fixtures.post_marketing_entry(
            api, ps_id, context["pg_id"], amount_cents=300000, spend_date="2026-08-01"
        )
        fixtures.post_marketing_entry(
            api, ps_id, context["pgB_id"], amount_cents=300000, spend_date="2026-08-01"
        )

        empty = fixtures.read_program(api, context["pg_id"])
        assert empty["total_enrollment_count"] == 0
        assert empty["marketing_spend_net_cents"] == 300000
        assert empty["blended_cac_cents"] is None

        served = fixtures.read_program(api, context["pgB_id"])
        assert served["total_enrollment_count"] == 1
        assert served["marketing_spend_net_cents"] == 300000
        assert served["blended_cac_cents"] == 300000

    def test_both_postings_draw_down_one_shared_envelope(
        self, api, two_launched_programs_one_with_a_student
    ):
        """The envelope is a partnership-level figure summed across its programs.

        PRD: "Summing that net figure over every program of the partnership gives the
        partnership's posted net spend. `marketing_budget_remaining_cents` is
        `marketing_budget_cents` less that posted net, and `unrecouped_marketing_spend_cents` is
        that posted net less the sum of `marketing_recoupment_cents` over the partnership's
        statements whose `status` is `REMITTED`."

        Design: Difficulty/boundary_precision_check/blended_cac_is_null_at_zero_enrollments_and_exact_at_first_enrollment
        """
        context = two_launched_programs_one_with_a_student
        ps_id = context["ps_id"]
        fixtures.post_marketing_entry(
            api, ps_id, context["pg_id"], amount_cents=300000, spend_date="2026-08-01"
        )
        last = api.create_marketing_spend_entry(
            context["pgB_id"],
            factories.marketing_spend_payload(amount_cents=300000, spend_date="2026-08-01"),
            headers=make_partner_account_lead_headers(ps_id),
        )
        validate_success(last, 201)

        partnership = fixtures.read_partnership(api, ps_id)
        assert partnership["marketing_budget_remaining_cents"] == 3400000
        assert partnership["unrecouped_marketing_spend_cents"] == 600000
