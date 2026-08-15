"""Harassment reporting: the substantiation cascade and the appeal cycle."""
from test_helpers import (
    TEST_USERS,
    assert_notice_day_invariant,
    make_vessel_operator_headers,
    setup_harassment_under_review_scenario,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["program_coordinator_headers"]

RESOLUTION = {"resolution_notes": "Substantiated by interview"}


class TestSubstantiationCascade:
    def test_substantiation_terminates_at_sea_deployment(self, api, coordinator_headers):
        """PRD §3.7: "Substantiating a report — recording `resolution_notes` —
        fires a two-hop cascade. Hop one: if the linked deployment is still
        `AT_SEA`, it is terminated on the spot per §3.5's early-termination
        arithmetic, landing in `EARLY_TERMINATED` with the corresponding notice
        reconciliation. Hop two, executed only while `penalty_applied` is still
        false: the vessel's `selection_penalty_points` grows by 3 and its
        `substantiated_harassment_count` grows by 1, and `penalty_applied`
        flips to true — the flag that keeps a re-affirmation after appeal from
        punishing the vessel twice." PRD §3.5: "In that case the
        `actual_return_date` is set to the current clock date, and
        `actual_sea_days` is the inclusive count from
        `scheduled_departure_date` through that date, clamped to at least 1 day
        and at most `planned_sea_days`."

        Design: Difficulty/transitive_cascade/harassment_substantiation_cascade_terminates_at_sea_deployment
        """
        bundle = setup_harassment_under_review_scenario()
        report = validate_success(
            api.substantiate_harassment_report(
                bundle["report"]["id"], RESOLUTION, ADMIN
            )
        )
        assert report["status"] == "SUBSTANTIATED"
        assert report["penalty_applied"] is True

        deployment = validate_success(
            api.get_deployment(bundle["deployment"]["id"], coordinator_headers)
        )
        assert deployment["status"] == "EARLY_TERMINATED"
        assert deployment["early_termination_reason"] == "HARASSMENT"
        # Clock reads 2026-09-12; inclusive count from 2026-09-10 is 3 days.
        assert deployment["actual_sea_days"] == 3

        vessel = validate_success(api.get_vessel(bundle["vessel"]["id"], coordinator_headers))
        assert vessel["selection_penalty_points"] == 3
        assert vessel["substantiated_harassment_count"] == 1

    def test_substantiation_reconciles_notice_ledger(self, api, coordinator_headers):
        """PRD §3.5: "The notice reconciliation is identical to a normal
        return." PRD §2.9: "Recording a return — normal or early-terminated —
        converts the reservation into consumption: `reserved_sea_days` falls by
        `planned_sea_days`, `consumed_sea_days` rises by `actual_sea_days`, and
        `remaining_sea_days` is credited with the difference between planned
        and actual days."

        Design: Difficulty/transitive_cascade/harassment_substantiation_cascade_terminates_at_sea_deployment
        """
        bundle = setup_harassment_under_review_scenario()
        validate_success(
            api.substantiate_harassment_report(
                bundle["report"]["id"], RESOLUTION, ADMIN
            )
        )
        notice = validate_success(
            api.get_selection_notice(bundle["notice"]["id"], coordinator_headers)
        )
        # planned 10, actual 3: reserved 10 -> 0, consumed 0 -> 3,
        # remaining 20 -> 27.
        assert notice["reserved_sea_days"] == 0
        assert notice["consumed_sea_days"] == 3
        assert notice["remaining_sea_days"] == 27
        assert notice["allocated_sea_days"] == 30
        assert_notice_day_invariant(notice)


class TestAppealCycle:
    def test_appeal_reenters_review_and_dismissal_compensates(self, api, coordinator_headers):
        """PRD §3.7: "From `SUBSTANTIATED`, the vessel's operator may appeal —
        ownership of the report's vessel is checked — moving the report to
        `APPEALED` with `version` incremented, from which a fresh review can
        substantiate or dismiss it again." and "Dismissing a report from
        `UNDER_REVIEW` — again with `resolution_notes` — runs the mirror image
        only when `penalty_applied` is true, which is precisely the
        dismissal-after-appeal case: 3 points are refunded from
        `selection_penalty_points`, the `substantiated_harassment_count` is
        decremented by 1, and `penalty_applied` flips back to false; a
        dismissal with no penalty previously applied touches the vessel not at
        all."

        Design: Difficulty/non_linear_state_machine/harassment_report_appeal_cycle_reenters_under_review
        """
        bundle = setup_harassment_under_review_scenario()
        report_id = bundle["report"]["id"]
        validate_success(api.substantiate_harassment_report(report_id, RESOLUTION, ADMIN))
        appealed = validate_success(
            api.appeal_harassment_report(
                report_id, {}, make_vessel_operator_headers(bundle["operator"]["id"])
            )
        )
        assert appealed["status"] == "APPEALED"
        reopened = validate_success(api.start_harassment_review(report_id, {}, COORD))
        assert reopened["status"] == "UNDER_REVIEW", "the cycle re-enters UNDER_REVIEW"

        dismissed = validate_success(
            api.dismiss_harassment_report(
                report_id, {"resolution_notes": "Dismissed on re-review after appeal"},
                ADMIN,
            )
        )
        assert dismissed["status"] == "DISMISSED"
        assert dismissed["penalty_applied"] is False

        vessel = validate_success(api.get_vessel(bundle["vessel"]["id"], coordinator_headers))
        assert vessel["selection_penalty_points"] == 0
        assert vessel["substantiated_harassment_count"] == 0

    def test_early_termination_survives_post_appeal_dismissal(self, api, coordinator_headers):
        """PRD §3.7: "A coordinator opens review (`FILED` → `UNDER_REVIEW`, the
        report's `version` incrementing); the same action later reopens an
        `APPEALED` report for a second look (`APPEALED` → `UNDER_REVIEW`)." and
        "Hop one: if the linked deployment is still `AT_SEA`, it is terminated
        on the spot per §3.5's early-termination arithmetic, landing in
        `EARLY_TERMINATED` with the corresponding notice reconciliation."

        Design: Difficulty/non_linear_state_machine/harassment_report_appeal_cycle_reenters_under_review
        """
        bundle = setup_harassment_under_review_scenario()
        report_id = bundle["report"]["id"]
        validate_success(api.substantiate_harassment_report(report_id, RESOLUTION, ADMIN))
        validate_success(
            api.appeal_harassment_report(
                report_id, {}, make_vessel_operator_headers(bundle["operator"]["id"])
            )
        )
        reopened = validate_success(api.start_harassment_review(report_id, {}, COORD))
        assert reopened["status"] == "UNDER_REVIEW"
        validate_success(
            api.dismiss_harassment_report(
                report_id, {"resolution_notes": "Dismissed on re-review"}, ADMIN
            )
        )
        deployment = validate_success(
            api.get_deployment(bundle["deployment"]["id"], coordinator_headers)
        )
        # The cascade fired at substantiation and does not revert on dismissal.
        assert deployment["status"] == "EARLY_TERMINATED"
        assert deployment["actual_sea_days"] == 3
        assert deployment["early_termination_reason"] == "HARASSMENT"
