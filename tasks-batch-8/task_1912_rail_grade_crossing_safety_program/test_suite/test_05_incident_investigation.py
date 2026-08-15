"""Incident reporting, investigation fork/join, five-year window, and FRA
submission gates (PRD §3.1, §3.3)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_incident_report,
    create_eligible_project,
    create_incident,
    create_incident_in_status,
    create_incident_report_payload,
    create_locality,
    create_program,
    create_project,
    get_success_data,
    issue_findings,
    make_local_authority_headers,
    setup_locality_and_crossing,
    transition_incident,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
RAILROAD = TEST_USERS["railroad_headers"]


class TestInvestigationForkJoin:
    def test_field_fork_sets_review_due_desk_fork_does_not(self, api, admin_headers):
        """PRD §3.3: "moving to `FIELD_INVESTIGATION` records
        `investigation_track` as `FIELD_INVESTIGATION` and, as a branch side
        effect, flips the crossing's `diagnostic_review_due` to `true`; moving to
        `DESK_REVIEW` records the `DESK_REVIEW` track with no such side effect."

        Design: Difficulty/non_linear_state_machine/incident_investigation_fork_join
        """
        locality, crossing = setup_locality_and_crossing(
            {
                "dot_crossing_number": "DOT-400101",
                "annual_train_count": 365,
                "aadt": 5000,
                "school_bus_count": 0,
                "sight_distance_rating": 3,
                "warning_device_class": "GATES",
            }
        )
        # Exposure 5.00 is below the review threshold, so the flag starts false.
        assert crossing["diagnostic_review_due"] is False

        inc1 = create_incident(
            crossing["id"],
            occurred_at="2026-06-15T14:30:00Z",
            severity="CASUALTY",
            fatalities=1,
            property_damage_cents=2_000_000,
        )
        inc2 = create_incident(
            crossing["id"],
            occurred_at="2026-07-01T09:00:00Z",
            severity="PROPERTY_DAMAGE",
            property_damage_cents=500_000,
        )
        transition_incident(inc1["id"], "SCREENED")
        transition_incident(inc2["id"], "SCREENED")

        inc1_field = transition_incident(inc1["id"], "FIELD_INVESTIGATION")
        assert inc1_field["investigation_track"] == "FIELD_INVESTIGATION"
        cx_after_field = get_success_data(api.get_crossing(crossing["id"], ADMIN))
        assert cx_after_field["diagnostic_review_due"] is True, (
            "the FIELD fork flips diagnostic_review_due to true"
        )

        inc2_desk = transition_incident(inc2["id"], "DESK_REVIEW")
        assert inc2_desk["investigation_track"] == "DESK_REVIEW"

    def test_both_branches_join_at_findings_issued_and_recompute_crossing(
        self, api, admin_headers
    ):
        """PRD §3.3: "From either `FIELD_INVESTIGATION` or `DESK_REVIEW`, the
        officer supplies the `findings_summary` text and the
        `warning_devices_functioning` flag, moving the report to
        `FINDINGS_ISSUED`." PRD §3.3: "Link 1: the crossing's
        `incident_count_5yr` is recomputed over the trailing five-year window and
        its `hazard_score` is recomputed with the new incident term".

        Design: Difficulty/non_linear_state_machine/incident_investigation_fork_join
        """
        locality, crossing = setup_locality_and_crossing(
            {
                "dot_crossing_number": "DOT-400102",
                "annual_train_count": 365,
                "aadt": 5000,
                "school_bus_count": 0,
                "sight_distance_rating": 3,
                "warning_device_class": "GATES",
            }
        )
        inc1 = create_incident(
            crossing["id"],
            occurred_at="2026-06-15T14:30:00Z",
            severity="CASUALTY",
            fatalities=1,
            property_damage_cents=2_000_000,
        )
        inc2 = create_incident(
            crossing["id"],
            occurred_at="2026-07-01T09:00:00Z",
            severity="PROPERTY_DAMAGE",
            property_damage_cents=500_000,
        )
        assert inc1["fra_reportable"] is True  # fatality
        transition_incident(inc1["id"], "SCREENED")
        transition_incident(inc2["id"], "SCREENED")
        transition_incident(inc1["id"], "FIELD_INVESTIGATION")
        transition_incident(inc2["id"], "DESK_REVIEW")

        issue_findings(inc1["id"], "gate arm failed to descend", False)
        inc2_final = issue_findings(
            inc2["id"], "driver error; devices functioned", True
        )
        assert inc2_final["status"] == "FINDINGS_ISSUED"
        assert_incident_report(inc2_final)

        cx = get_success_data(api.get_crossing(crossing["id"], ADMIN))
        assert cx["incident_count_5yr"] == 2
        # (5.00*1.10 + 2*8 + 0) * 1.00 * 1.00 = 21.50
        assert cx["hazard_score"] == pytest.approx(21.50, abs=1e-9)


class TestFiveYearWindowBoundary:
    def test_incident_at_exactly_five_years_counts_one_second_earlier_does_not(
        self, api, admin_headers
    ):
        """PRD §3.1: "incident reports of this crossing whose status is
        `FINDINGS_ISSUED`, `FRA_SUBMITTED`, or `CLOSED` and whose `occurred_at`
        falls within the trailing five-year window — from five years before the
        logical clock through the logical clock, both bounds inclusive."
        PRD §2.5: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`".

        Design: Corner/calculations/incident_five_year_window_boundary
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-030001"}
        )
        ia = create_incident(
            crossing["id"],
            occurred_at="2021-08-01T00:00:00Z",
            severity="PROPERTY_DAMAGE",
            property_damage_cents=500_000,
        )
        transition_incident(ia["id"], "SCREENED")
        transition_incident(ia["id"], "DESK_REVIEW")
        issue_findings(ia["id"], "A at inclusive bound", True)

        ib = create_incident(
            crossing["id"],
            occurred_at="2021-07-31T23:59:59Z",
            severity="PROPERTY_DAMAGE",
            property_damage_cents=500_000,
        )
        transition_incident(ib["id"], "SCREENED")
        transition_incident(ib["id"], "DESK_REVIEW")
        issue_findings(ib["id"], "B one second outside", True)

        cx = get_success_data(api.get_crossing(crossing["id"], ADMIN))
        assert cx["incident_count_5yr"] == 1, (
            "A at the inclusive lower bound counts; B one second earlier does not"
        )
        # (5.00*1.10 + 8) * 1.00 * 1.00 = 13.50
        assert cx["hazard_score"] == pytest.approx(13.50, abs=1e-9)

    def test_reported_incident_excluded_from_count(self, api, admin_headers):
        """PRD §3.1: "Reports still in `REPORTED`, `SCREENED`,
        `FIELD_INVESTIGATION`, or `DESK_REVIEW`, and reports that were `REJECTED`,
        never count."

        Design: Corner/calculations/uninvestigated_incidents_excluded_from_counts
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-030011"}
        )
        hazard_before = crossing["hazard_score"]
        create_incident(
            crossing["id"],
            occurred_at="2026-05-01T10:00:00Z",
            severity="NEAR_MISS",
        )  # left in REPORTED
        cx = get_success_data(api.get_crossing(crossing["id"], ADMIN))
        assert cx["incident_count_5yr"] == 0
        assert cx["hazard_score"] == pytest.approx(hazard_before, abs=1e-9)


class TestFraReportabilityThreshold:
    def test_damage_at_threshold_is_reportable_and_submittable(
        self, api, officer_headers
    ):
        """PRD §3.3: "the report is FRA-reportable when it records any fatality,
        any injury, or property damage of at least 1,100,000 cents — the damage
        threshold is inclusive, so damage of exactly 1,100,000 cents qualifies."
        PRD §3.3: "the officer moves it to `FRA_SUBMITTED`, which stamps
        `fra_submitted_at`".

        Design: Corner/state_machines/fra_reportability_threshold
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-020081"}
        )
        i1 = create_incident(
            crossing["id"],
            occurred_at="2026-03-01T10:00:00Z",
            severity="PROPERTY_DAMAGE",
            property_damage_cents=1_100_000,
        )
        assert i1["fra_reportable"] is True
        transition_incident(i1["id"], "SCREENED")
        transition_incident(i1["id"], "DESK_REVIEW")
        issue_findings(i1["id"], "threshold case", True)

        submitted = transition_incident(i1["id"], "FRA_SUBMITTED")
        assert submitted["status"] == "FRA_SUBMITTED"
        assert submitted["fra_submitted_at"] is not None

    def test_damage_below_threshold_not_reportable_and_closes_directly(
        self, api, officer_headers
    ):
        """PRD §3.3: "Attempting the FRA-submission move on a non-reportable
        incident is rejected with `ERR_FRA_NOT_REPORTABLE`. Conversely, a
        non-reportable report moves directly from `FINDINGS_ISSUED` to `CLOSED`;
        attempting to close a reportable one without the FRA submission is
        rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/fra_reportability_threshold
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-020082"}
        )
        i2 = create_incident(
            crossing["id"],
            occurred_at="2026-04-01T10:00:00Z",
            severity="PROPERTY_DAMAGE",
            property_damage_cents=1_099_999,
        )
        assert i2["fra_reportable"] is False
        transition_incident(i2["id"], "SCREENED")
        transition_incident(i2["id"], "DESK_REVIEW")
        issue_findings(i2["id"], "sub-threshold case", True)

        resp = api.transition_incident_report(
            i2["id"], {"to_status": "FRA_SUBMITTED"}, officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_FRA_NOT_REPORTABLE, expected_status=409)

        closed = transition_incident(i2["id"], "CLOSED")
        assert closed["status"] == "CLOSED"


class TestIncidentTerminalAndSeverityRules:
    def test_rejected_incident_is_terminal(self, api, officer_headers):
        """PRD §3.3: "`CLOSED` and `REJECTED` are terminal." and PRD §3.3:
        "A `RailSafetyOfficer` moves a `REPORTED` report to `SCREENED` to open it,
        or straight to `REJECTED` when the report does not warrant investigation;
        both moves require the `REPORTED` from-state, else
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/incident_rejected_terminal_lockdown
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-020031"}
        )
        inc = get_success_data(
            api.create_incident_report(
                create_incident_report_payload(
                    crossing_id=crossing["id"],
                    occurred_at="2026-06-01T10:00:00Z",
                    severity="NEAR_MISS",
                ),
                RAILROAD,
            )
        )
        rejected = transition_incident(inc["id"], "REJECTED")
        assert rejected["status"] == "REJECTED"

        resp = api.transition_incident_report(
            inc["id"], {"to_status": "CLOSED"}, officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
        after = get_success_data(api.get_incident_report(inc["id"], ADMIN))
        assert after["status"] == "REJECTED"

    def test_casualty_cannot_be_desk_reviewed(self, api, officer_headers):
        """PRD §3.3: "A `CASUALTY` incident may never be desk-reviewed —
        attempting the `SCREENED` → `DESK_REVIEW` move on one is rejected with
        `ERR_SEVERITY_REQUIRES_FIELD_INVESTIGATION`."

        Design: Corner/validations/casualty_requires_field_investigation
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-040081"}
        )
        inc = create_incident(
            crossing["id"],
            occurred_at="2026-05-10T10:00:00Z",
            severity="CASUALTY",
            fatalities=1,
        )
        transition_incident(inc["id"], "SCREENED")

        resp = api.transition_incident_report(
            inc["id"], {"to_status": "DESK_REVIEW"}, officer_headers
        )
        validate_error(
            resp,
            ApiErrorId.ERR_SEVERITY_REQUIRES_FIELD_INVESTIGATION,
            expected_status=422,
        )
        after = get_success_data(api.get_incident_report(inc["id"], ADMIN))
        assert after["status"] == "SCREENED"

    def test_future_incident_rejected(self, api, officer_headers):
        """PRD §3.3: "A report whose `occurred_at` is after the logical clock is
        rejected with `ERR_INCIDENT_IN_FUTURE`." PRD §2.5: "At server startup the
        logical clock reads exactly `2026-08-01T00:00:00Z`".

        Design: Corner/validations/incident_in_future_rejected
        """
        locality, crossing = setup_locality_and_crossing(
            {"dot_crossing_number": "DOT-040121"}
        )
        resp = api.create_incident_report(
            create_incident_report_payload(
                crossing_id=crossing["id"],
                occurred_at="2026-08-02T00:00:00Z",
                severity="NEAR_MISS",
            ),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INCIDENT_IN_FUTURE, expected_status=422)


class TestFindingsCascadeToProgramDemand:
    def test_findings_revert_eligible_project_and_recompute_demand(
        self, api, admin_headers
    ):
        """PRD §3.3: "Link 2: because the crossing's live `hazard_score` has
        changed, every upgrade project of this crossing currently in `ELIGIBLE`
        reverts `ELIGIBLE` → `PROPOSED` with its `score_stale` flag set to `true`
        — its pinned `priority_score` no longer matches the live hazard. Link 3:
        because those projects left `ELIGIBLE`, each affected funding program's
        `eligible_demand_cents` is recomputed, decreasing by each reverted
        project's `estimated_cost_cents`."

        Design: Difficulty/transitive_cascade/incident_findings_cascade_to_program_demand
        """
        locality, crossing = setup_locality_and_crossing(
            {
                "dot_crossing_number": "DOT-400201",
                "annual_train_count": 730,
                "aadt": 5000,
                "school_bus_count": 0,
                "sight_distance_rating": 3,
                "warning_device_class": "GATES",
            }
        )
        # Exposure 10.00 -> hazard (10.00*1.20) * 1.00 = 12.00
        assert crossing["hazard_score"] == pytest.approx(12.00, abs=1e-9)
        prog = create_program(
            fiscal_year=2028,
            apportionment_cents=1_000_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        pj = create_eligible_project(crossing["id"], prog["id"], estimated_cost_cents=300_000)
        assert pj["priority_score"] == pytest.approx(12.00, abs=1e-9)
        assert pj["score_stale"] is False
        prog_mid = get_success_data(api.get_funding_program(prog["id"], ADMIN))
        assert prog_mid["eligible_demand_cents"] == 300_000

        inc = create_incident(
            crossing["id"],
            occurred_at="2025-01-10T08:00:00Z",
            severity="PROPERTY_DAMAGE",
            property_damage_cents=500_000,
        )
        transition_incident(inc["id"], "SCREENED")
        transition_incident(inc["id"], "DESK_REVIEW")
        issue_findings(inc["id"], "crossbuck obscured by vegetation", True)

        # Link 1: crossing recomputed
        cx = get_success_data(api.get_crossing(crossing["id"], ADMIN))
        assert cx["incident_count_5yr"] == 1
        # (10.00*1.20 + 8) * 1.00 * 1.00 = 20.00
        assert cx["hazard_score"] == pytest.approx(20.00, abs=1e-9)
        # Link 2: ELIGIBLE project reverted with score_stale set
        pj_after = get_success_data(api.get_upgrade_project(pj["id"], ADMIN))
        assert pj_after["status"] == "PROPOSED"
        assert pj_after["score_stale"] is True
        assert pj_after["priority_score"] == pytest.approx(12.00, abs=1e-9), (
            "pinned priority_score survives the revert"
        )
        # Link 3: program demand recomputed
        prog_after = get_success_data(api.get_funding_program(prog["id"], ADMIN))
        assert prog_after["eligible_demand_cents"] == 0

    def test_desk_branch_findings_run_the_same_cascade(self, api, admin_headers):
        """PRD §3.3: "Issuing findings is the pivotal act. From either
        `FIELD_INVESTIGATION` or `DESK_REVIEW`, the officer supplies the
        `findings_summary` text and the `warning_devices_functioning` flag, moving
        the report to `FINDINGS_ISSUED`. That single move fires a three-link
        cascade." PRD §3.4: "`eligible_demand_cents` tracks the sum of
        `estimated_cost_cents` over the program's projects currently in
        `ELIGIBLE`, recomputed on every project status change."

        Design: Difficulty/transitive_cascade/incident_findings_cascade_to_program_demand
        """
        locality, crossing = setup_locality_and_crossing(
            {
                "dot_crossing_number": "DOT-400202",
                "annual_train_count": 730,
                "aadt": 5000,
                "school_bus_count": 0,
                "sight_distance_rating": 3,
                "warning_device_class": "GATES",
            }
        )
        prog = create_program(fiscal_year=2029, apportionment_cents=1_000_000)
        pj = create_eligible_project(crossing["id"], prog["id"], estimated_cost_cents=300_000)

        inc = create_incident(
            crossing["id"],
            occurred_at="2025-03-10T08:00:00Z",
            severity="PROPERTY_DAMAGE",
            property_damage_cents=500_000,
        )
        transition_incident(inc["id"], "SCREENED")
        transition_incident(inc["id"], "DESK_REVIEW")  # desk branch
        issue_findings(inc["id"], "desk-reviewed findings", True)

        pj_after = get_success_data(api.get_upgrade_project(pj["id"], ADMIN))
        assert pj_after["status"] == "PROPOSED"
        assert pj_after["score_stale"] is True
        prog_after = get_success_data(api.get_funding_program(prog["id"], ADMIN))
        assert prog_after["eligible_demand_cents"] == 0
