"""The two multi-hop cascades: contract wind-down and enrollment withdrawal."""

import pytest

from test_helpers import fixtures


class TestWindDownCascadeReachesFourHops:
    @pytest.fixture
    def executed_partnership_with_open_pipeline(self, api):
        """A LAUNCHED program with one course in FACULTY_REVIEW, one CONTACTED lead and one counselor."""
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)
        pg_id = program["id"]

        launch_course = fixtures.create_approved_course(api, ps_id, pg_id)
        in_flight = fixtures.add_course(
            api,
            ps_id,
            pg_id,
            course_code="MBA-502",
            title="Operations Strategy",
            design_cost_cents=900000,
            required_for_launch=False,
        )
        fixtures.start_course_design(api, ps_id, in_flight["id"])
        fixtures.submit_course_for_faculty_review(api, ps_id, in_flight["id"])
        fixtures.assign_service_scope(api, pg_id, "MARKETING")
        fixtures.submit_program(api, ps_id, pg_id)
        fixtures.approve_program(api, pg_id)
        fixtures.launch_program(api, ps_id, pg_id)

        counselor = fixtures.create_eligible_counselor(api, ps_id)
        lead = fixtures.create_lead(api, ps_id, pg_id, counselor["id"])
        fixtures.contact_lead(api, ps_id, lead["id"], 6)

        return {
            "ps_id": ps_id,
            "pg_id": pg_id,
            "c1_id": launch_course["id"],
            "c2_id": in_flight["id"],
            "co_id": counselor["id"],
            "ld_id": lead["id"],
        }

    def test_wind_down_drags_the_program_its_leads_and_its_in_flight_designs(
        self, api, executed_partnership_with_open_pipeline
    ):
        """Hops one and two: the program teaches out, its lead and its live design follow.

        PRD: "Its first hop transitions every program of that partnership whose `status` is
        `LAUNCHED` or `SUSPENDED` into `TEACH_OUT`, processing those programs in ascending
        `created_at` order and stamping each one's `teach_out_started_at` with the logical clock
        instant. Its second hop is caused by the first, not by the contract action: each program
        entering `TEACH_OUT` disqualifies its own leads in `NEW`, `CONTACTED` or `APPLIED` with
        `disqualification_reason` set to `PROGRAM_TEACH_OUT`, and suspends its own courses whose
        `design_status` is `IN_DESIGN` or `FACULTY_REVIEW` into `DESIGN_SUSPENDED`."
        PRD: "A `UniversityProvost` begins the exit from an `EXECUTED` partnership with
        `WIND_DOWN`, supplying a `wind_down_effective_date` that must be on or after the logical
        clock's date, and optionally a `wind_down_reason`. The supplied date is recorded on the
        partnership."

        Design: Difficulty/transitive_cascade/wind_down_chains_partnership_to_program_to_leads_and_courses_to_counselor_inactive
        """
        context = executed_partnership_with_open_pipeline
        partnership = fixtures.wind_down_partnership(api, context["ps_id"])

        assert partnership["status"] == "WIND_DOWN"
        assert partnership["wind_down_effective_date"] == "2026-08-15"

        program = fixtures.read_program(api, context["pg_id"])
        assert program["status"] == "TEACH_OUT"
        assert program["teach_out_started_at"] is not None

        lead = fixtures.read_lead(api, context["ld_id"])
        assert lead["status"] == "DISQUALIFIED"
        assert lead["disqualification_reason"] == "PROGRAM_TEACH_OUT"

        assert fixtures.read_course(api, context["c2_id"])["design_status"] == "DESIGN_SUSPENDED"
        assert fixtures.read_course(api, context["c1_id"])["design_status"] == "APPROVED"

    def test_emptied_pipeline_makes_the_counselor_inactive_without_touching_eligibility(
        self, api, executed_partnership_with_open_pipeline
    ):
        """Hop three: the recomputed pipeline reaches zero and only the performance side moves.

        PRD: "Its third hop is caused by the second: every counselor whose leads were
        disqualified in hop two recomputes `open_pipeline_count`, and any counselor whose
        recomputed count is zero moves `performance_status` to `INACTIVE_PENDING_REVIEW` while
        `incentive_eligibility` is left exactly as it was."

        Design: Difficulty/transitive_cascade/wind_down_chains_partnership_to_program_to_leads_and_courses_to_counselor_inactive
        """
        context = executed_partnership_with_open_pipeline
        before = fixtures.read_counselor(api, context["co_id"])
        assert before["open_pipeline_count"] == 1
        assert before["incentive_eligibility"] == "ELIGIBLE"

        fixtures.wind_down_partnership(api, context["ps_id"])

        counselor = fixtures.read_counselor(api, context["co_id"])
        assert counselor["open_pipeline_count"] == 0
        assert counselor["performance_status"] == "INACTIVE_PENDING_REVIEW"
        assert counselor["incentive_eligibility"] == "ELIGIBLE"


class TestWithdrawalCascadeChainsRefundToSuspension:
    @pytest.fixture
    def active_paid_enrollment(self, api):
        """One ACTIVE enrollment paid 562,500 cents in full, clock advanced to 2026-09-08."""
        return fixtures.build_paid_enrollment(api, final_clock=fixtures.CLOCK_SEP_8)

    def test_day_eight_withdrawal_refunds_the_half_band_and_reconciles_cash(
        self, api, active_paid_enrollment
    ):
        """Hop one: day 8 takes the 0.50 band and the compensating refund entry lands.

        PRD: "First, `days_elapsed_at_withdrawal` is the whole number of days from
        `term_start_date` to `withdrawal_date` counting the first day, so a withdrawal on the
        term's opening day is day 1."
        PRD: "The comparison is inclusive on `through_day`, which is why under the standard
        schedule a day-7 withdrawal takes the full-refund band while a day-8 withdrawal takes
        the half band."
        PRD: "**Hop 1** creates a tuition ledger entry with `entry_type` of `REFUND` and
        `generated_by` of `WITHDRAWAL_REFUND` for that refund amount, and recomputes the
        enrollment's `refunded_cents`, the program's `active_enrollment_count` (down by one,
        since the student is no longer active) and the partnership's `collected_tuition_cents`."

        Design: Difficulty/transitive_cascade/withdrawal_chains_refund_to_clawback_accrual_to_incentive_suspension
        """
        context = active_paid_enrollment
        enrollment = fixtures.withdraw_enrollment(
            api,
            context["en_id"],
            "2026-09-08",
            withdrawal_reason="Employer sponsorship withdrawn",
        )

        assert enrollment["status"] == "WITHDRAWN"
        assert enrollment["days_elapsed_at_withdrawal"] == 8
        assert enrollment["refund_pct_applied"] == pytest.approx(0.50, abs=0.0001)
        assert enrollment["refunded_cents"] == 281250
        assert enrollment["collected_cents"] == 562500

        partnership = fixtures.read_partnership(api, context["ps_id"])
        assert partnership["collected_tuition_cents"] == 281250

        program = fixtures.read_program(api, context["pg_id"])
        assert program["active_enrollment_count"] == 0

    def test_refund_accrues_the_clawback_which_then_suspends_the_incentive(
        self, api, active_paid_enrollment
    ):
        """Hops two and three: the accrual reaches the trigger exactly and only eligibility moves.

        PRD: "When `days_elapsed_at_withdrawal` is no greater than 45 — the clawback window, a
        month and a half into the term — that counselor's `clawback_pending_cents` increases by
        its `variable_component_cents` multiplied by the enrollment's `refund_pct_applied`,
        rounded half up to whole cents."
        PRD: "When the counselor's `clawback_pending_cents` has reached 50,000 cents — five
        hundred dollars of accumulated clawback — and its `incentive_eligibility` is `ELIGIBLE`,
        that dimension moves to `SUSPENDED`. The comparison is inclusive: exactly 50,000 cents
        trips it. `performance_status` is left unchanged, once again demonstrating the dimensions'
        independence."

        Design: Difficulty/transitive_cascade/withdrawal_chains_refund_to_clawback_accrual_to_incentive_suspension
        """
        context = active_paid_enrollment
        fixtures.withdraw_enrollment(
            api,
            context["en_id"],
            "2026-09-08",
            withdrawal_reason="Employer sponsorship withdrawn",
        )

        counselor = fixtures.read_counselor(api, context["co_id"])
        assert counselor["clawback_pending_cents"] == 50000
        assert counselor["incentive_eligibility"] == "SUSPENDED"
        assert counselor["performance_status"] == "NOT_RATED"
