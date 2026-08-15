"""Inspections, citations, contest branching, and window arithmetic."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_citation,
    assert_inspection,
    assert_summary,
    create_citation,
    create_corrective_action,
    create_inspection,
    create_summary,
    get_corrective_action,
    get_success_data,
    set_clock,
    setup_org,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OFFICER


class TestInspectionClosure:
    def test_inspection_close_blocked_when_citations_exist(self, api):
        """PRD §3.8: "A `SafetyOfficer` may close an inspection without
        citations only while none exist — once any citation exists the close
        fails with `ERR_CITATIONS_EXIST` — and a successful close stamps
        `closed_on` and lands the inspection in the terminal
        `CLOSED_NO_CITATION` state. The first citation issued under an
        inspection automatically moves it to the terminal `CITATIONS_ISSUED`
        state."

        Design: Corner/state_machines/inspection_close_blocked_when_citations_exist
        """
        _, establishment, _ = setup_org(fein="34-0000012",
                                        site_name="Site IC")
        inspection = create_inspection(
            establishment["id"], opened_on="2026-08-01",
            inspection_type="PROGRAMMED", scope="PARTIAL")
        create_citation(inspection["id"],
                        standard_cited="29 CFR 1910.95",
                        proposed_penalty_usd=5000)

        resp = api.close_inspection(inspection["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_CITATIONS_EXIST)

        refreshed = get_success_data(
            api.get_inspection(inspection["id"], OFFICER))
        assert_inspection(refreshed)
        assert refreshed["status"] == "CITATIONS_ISSUED", (
            "The first citation auto-moves the inspection")


class TestContestResolution:
    def _contested_citation(self, api, fein, penalty=8000,
                            standard="29 CFR 1910.23"):
        _, establishment, _ = setup_org(fein=fein, site_name="Pen Site")
        set_clock("2026-08-03T10:00:00Z")
        inspection = create_inspection(
            establishment["id"], opened_on="2026-08-03",
            inspection_type="COMPLAINT", scope="PARTIAL")
        citation = create_citation(
            inspection["id"], standard_cited=standard,
            proposed_penalty_usd=penalty, abatement_due_date="2026-09-01")
        get_success_data(api.contest_citation(citation["id"], OFFICER))
        return establishment, citation

    def test_modified_contest_requires_explicit_penalty(self, api):
        """PRD §3.8: "`MODIFIED` also moves it to `FINAL_ORDER` but requires
        an explicit, non-negative `final_penalty_usd` in the payload — its
        absence, or a negative value, fails with `ERR_PENALTY_INVALID` — and
        starts the abatement clock from the resolution date."

        Design: Corner/validations/penalty_invalid_on_modified_contest_without_amount
        """
        _, citation = self._contested_citation(api, "06-0000025")
        resp = api.resolve_contest(citation["id"], {"outcome": "MODIFIED"},
                                   OFFICER)
        validate_error(resp, ApiErrorId.ERR_PENALTY_INVALID)

    def test_contest_modified_branch_overrides_penalty(self, api):
        """PRD §3.8: "`MODIFIED` also moves it to `FINAL_ORDER` but requires
        an explicit, non-negative `final_penalty_usd` in the payload"
        PRD §3.8: "Immediately after a citation reaches `FINAL_ORDER` with an
        `abatement_due_date` set, the system moves it on to
        `ABATEMENT_PENDING`."
        PRD §3.8: "A citation created on Monday 2026-08-03 therefore carries
        a contest deadline of Monday 2026-08-24 at 23:59:59Z"

        Design: Difficulty/non_linear_state_machine/citation_contest_branching_fork_join
        """
        _, citation = self._contested_citation(api, "55-7878787",
                                               penalty=14500,
                                               standard="29 CFR 1910.147")
        resp = api.resolve_contest(
            citation["id"],
            {"outcome": "MODIFIED", "final_penalty_usd": 9000},
            OFFICER)
        resolved = validate_success(resp, 200)
        assert_citation(resolved)
        assert resolved["status"] == "ABATEMENT_PENDING", (
            "FINAL_ORDER auto-advances to ABATEMENT_PENDING")
        assert resolved["final_penalty_usd"] == pytest.approx(9000), (
            "MODIFIED overrides the proposed 14500")
        assert resolved["contest_deadline"].startswith(
            "2026-08-24T23:59:59"), (
            "Fifteen working days from Monday 2026-08-03")

    def test_contest_vacated_branch_cancels_linked_actions(self, api):
        """PRD §3.8: "`VACATED` lands the citation in the terminal `VACATED`
        state, removes it from penalty totals, and automatically cancels any
        corrective actions linked to it."

        Design: Difficulty/non_linear_state_machine/citation_contest_branching_fork_join
        """
        _, establishment, _ = setup_org(fein="55-7878788",
                                        site_name="Plant 10")
        set_clock("2026-08-03T10:00:00Z")
        inspection = create_inspection(
            establishment["id"], opened_on="2026-08-03",
            inspection_type="COMPLAINT", scope="PARTIAL")
        citation = create_citation(
            inspection["id"], standard_cited="29 CFR 1910.134",
            violation_type="OTHER_THAN_SERIOUS", proposed_penalty_usd=2500,
            abatement_due_date="2026-09-01")
        action = create_corrective_action(
            establishment["id"], citation_id=citation["id"],
            description="Respirator program fix", assigned_to="op-fix-2",
            due_date="2026-08-30", priority="MEDIUM")

        get_success_data(api.contest_citation(citation["id"], OFFICER))
        resp = api.resolve_contest(citation["id"], {"outcome": "VACATED"},
                                   OFFICER)
        resolved = validate_success(resp, 200)
        assert resolved["status"] == "VACATED", (
            "VACATED is terminal; the abatement branch is never entered")

        refreshed = get_corrective_action(action["id"])
        assert refreshed["status"] == "CANCELLED", (
            "Auto-cancel fires on the VACATED branch")


class TestWindowArithmetic:
    def test_contest_deadline_weekend_rolls_to_monday(self, api):
        """PRD §3.8: "the system computes its `contest_deadline`: day zero is
        the citation's creation date itself — or the following Monday when
        creation falls on a weekend — and counting fifteen working days,
        Mondays through Fridays only, forward from day zero yields the
        deadline date, stamped at 23:59:59 UTC. A citation created on Monday
        2026-08-03 therefore carries a contest deadline of Monday 2026-08-24
        at 23:59:59Z, and one created on Saturday 2026-08-01 starts its count
        on that same Monday and lands on the same deadline."

        Design: Difficulty/resource_temporal_overlap/contest_window_working_day_vs_summary_fixed_calendar_window
        """
        _, establishment, _ = setup_org(fein="55-1231234",
                                        site_name="Dock 4")
        set_clock("2026-08-01T10:00:00Z")
        inspection = create_inspection(
            establishment["id"], opened_on="2026-08-01",
            inspection_type="REFERRAL", scope="RECORDS_ONLY")
        saturday = create_citation(
            inspection["id"], standard_cited="29 CFR 1904.7",
            violation_type="OTHER_THAN_SERIOUS", proposed_penalty_usd=1000)

        set_clock("2026-08-03T10:00:00Z")
        monday = create_citation(
            inspection["id"], standard_cited="29 CFR 1904.29",
            proposed_penalty_usd=7000)

        sat = get_success_data(api.get_citation(saturday["id"], OFFICER))
        mon = get_success_data(api.get_citation(monday["id"], OFFICER))
        assert sat["contest_deadline"].startswith("2026-08-24T23:59:59"), (
            "Saturday creation rolls day zero to Monday 2026-08-03")
        assert mon["contest_deadline"].startswith("2026-08-24T23:59:59")
        assert sat["contest_deadline"][:19] == mon["contest_deadline"][:19], (
            "Weekend and Monday creations land on the same deadline")

    def test_summary_posting_window_is_fixed_calendar(self, api):
        """PRD §3.7: "at creation the system fixes the posting window:
        `posting_window_open` at 00:00:00 UTC on February 1 of the following
        year, `posting_window_close` at 23:59:59 UTC on April 30 of that
        year."

        Design: Difficulty/resource_temporal_overlap/contest_window_working_day_vs_summary_fixed_calendar_window
        """
        _, establishment, _ = setup_org(fein="55-1231235",
                                        site_name="Dock 5")
        summary = create_summary(establishment["id"], 2026)
        assert_summary(summary)
        assert summary["posting_window_open"].startswith(
            "2027-02-01T00:00:00")
        assert summary["posting_window_close"].startswith(
            "2027-04-30T23:59:59")
