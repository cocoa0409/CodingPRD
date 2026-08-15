"""Corrective-plan resubmission cycle and the school's parallel standing
dimensions (PRD §3.3, §3.5)."""
import pytest

from test_helpers import (
    validate_success, create_open_school, create_issued_notice,
    submit_corrective_plan, add_monitoring_report, accept_report,
    make_staff_headers, make_school_operator_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


def _plan_context():
    """Open school + ISSUED PROBATION notice (staff_a) + SUBMITTED plan."""
    ctx = create_open_school(school_name="NL Plan Academy", applicant_id="applicant_nl1")
    notice = create_issued_notice(ctx["school"]["id"], level="PROBATION",
                                  domain="ACADEMIC",
                                  reason="Math proficiency below floor",
                                  issuer_id="staff_a")
    plan = submit_corrective_plan(notice["id"], ctx["school"]["id"],
                                  plan_text="Hire math coach; weekly tutoring",
                                  expected_intervention_version=notice["version"])
    return ctx, notice, plan


class TestCorrectivePlanReturnResubmitCycle:
    def test_return_then_resubmit_refreshes_plan_fields(self, api):
        """PRD §3.5: "Resubmission replaces `plan_text`, refreshes
        `submitted_at` from the clock, and clears `reviewed_by_user_id` for the
        next review."
        PRD §3.5: "`RETURNED` requires non-empty `review_notes` (missing notes
        are `ERR_INVALID_REQUEST`) and sends the plan back for rework."

        Design: Difficulty/non_linear_state_machine/corrective_plan_return_resubmit_cycle
        """
        _ctx, _notice, plan = _plan_context()
        returned = validate_success(
            api.review_corrective_plan(
                plan["id"], {"outcome": "RETURNED",
                             "review_notes": "Add measurable milestones"},
                make_staff_headers("staff_rev1")), 200)
        assert returned["status"] == "RETURNED"
        assert returned["review_notes"] == "Add measurable milestones"
        assert returned["reviewed_by_user_id"] == "staff_rev1"

        resubmitted = validate_success(
            api.resubmit_corrective_plan(
                plan["id"],
                {"plan_text": "Hire math coach; weekly tutoring; quarterly benchmarks"},
                make_school_operator_headers(_ctx["school"]["id"])), 200)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["plan_text"] == (
            "Hire math coach; weekly tutoring; quarterly benchmarks")
        assert resubmitted["reviewed_by_user_id"] is None

    def test_full_cycle_reaches_accepted_on_same_entity(self, api):
        """PRD §3.5: "A returned plan can be resubmitted by the owning
        `SchoolOperator`, cycling `RETURNED` → `SUBMITTED`: the plan must be
        `RETURNED` (`ERR_PLAN_INVALID_STATE`), ownership is verified, and the
        due date still binds (`ERR_CORRECTIVE_PLAN_OVERDUE`)."
        PRD §3.5: "`ACCEPTED` closes the loop"

        Design: Difficulty/non_linear_state_machine/corrective_plan_return_resubmit_cycle
        """
        _ctx, _notice, plan = _plan_context()
        validate_success(
            api.review_corrective_plan(
                plan["id"], {"outcome": "RETURNED",
                             "review_notes": "Add measurable milestones"},
                make_staff_headers("staff_rev1")), 200)
        validate_success(
            api.resubmit_corrective_plan(
                plan["id"],
                {"plan_text": "Hire math coach; weekly tutoring; quarterly benchmarks"},
                make_school_operator_headers(_ctx["school"]["id"])), 200)
        accepted = validate_success(
            api.review_corrective_plan(plan["id"], {"outcome": "ACCEPTED"},
                                       make_staff_headers("staff_rev2")), 200)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["id"] == plan["id"]
        assert accepted["reviewed_by_user_id"] == "staff_rev2"


class TestSchoolParallelStandingIndependence:
    def _standing_context(self):
        ctx = create_open_school(school_name="NL Standing Academy",
                                 applicant_id="applicant_nl2")
        report = add_monitoring_report(ctx["school"]["id"], fiscal_year=2028,
                                       academic_score=45, financial_score=90,
                                       operational_score=70)
        return ctx, report

    def test_standings_move_independently_of_each_other_and_status(self, api):
        """PRD §3.3: "Each domain score is mapped to a standing band: a score
        of eighty or above lands `GOOD`, sixty-five up to but not including
        eighty lands `NOTICE`, fifty up to but not including sixty-five lands
        `PROBATION`, and below fifty lands `CRITICAL`; boundaries are inclusive
        at the lower edge of each band, so exactly 80.0 is `GOOD`."
        PRD §3.3: "These standings are parallel dimensions: they evolve
        independently of each other and of the school's `status`."

        Design: Difficulty/non_linear_state_machine/school_parallel_standing_independence
        """
        ctx, report = self._standing_context()
        accept_report(report["id"])
        school = validate_success(api.get_school(ctx["school"]["id"], STAFF), 200)
        assert school["academic_standing"] == "CRITICAL"      # 45 < 50
        assert school["financial_standing"] == "GOOD"         # 90 >= 80
        assert school["operational_standing"] == "NOTICE"     # 65 <= 70 < 80
        assert school["status"] == "OPEN"

    def test_failing_domain_reweights_compliance_index(self, api):
        """PRD §3.3: "The base weights are one-half for the academic score and
        one-quarter each for the financial and operational scores; any domain
        whose score falls below sixty has its weight doubled, and the index is
        the weighted sum of the three scores divided by the sum of the
        (possibly doubled) weights, rounded half-up to one decimal place."

        Design: Difficulty/non_linear_state_machine/school_parallel_standing_independence
        """
        ctx, report = self._standing_context()
        # academic 45 < 60 doubles: (1.0*45 + 0.25*90 + 0.25*70) / 1.5 = 56.7
        assert report["compliance_index"] == pytest.approx(56.7, abs=0.001)
        accepted = accept_report(report["id"])
        assert accepted["compliance_index"] == pytest.approx(56.7, abs=0.001)
