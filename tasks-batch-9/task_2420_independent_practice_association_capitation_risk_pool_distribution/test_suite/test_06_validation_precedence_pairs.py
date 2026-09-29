"""The two deliberately reachable validation-precedence conflict pairs."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ERR_ASSIGNMENT_BEFORE_COVERAGE,
    ERR_ASSIGNMENT_PERIOD_OVERLAP,
    ERR_PANEL_CAPACITY_EXCEEDED,
    ERR_PANEL_CLOSED_TO_NEW,
    ERR_PHYSICIAN_NOT_ACCEPTING_ASSIGNMENTS,
    NETWORK_MANAGER_HEADERS,
    assign_enrollee,
    assignment_payload,
    create_active_agreement,
    create_active_physician,
    create_enrollee,
    enrollee_version,
    give_exit_notice,
    read_agreement,
    read_assignment,
    read_physician,
    set_clock,
)


def _full_panel_under_notice(api):
    """A physician at capacity who has also given exit notice."""
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(
        api, reconciliation_method="ROSTER_SNAPSHOT", max_panel_size=1
    )
    physician = create_active_physician(api, agreement["id"])

    first = create_enrollee(api, agreement["id"], external_member_id="PC-0001")
    assign_enrollee(api, first["id"], physician["id"])
    give_exit_notice(api, physician["id"])

    second = create_enrollee(api, agreement["id"], external_member_id="PC-0002")
    return agreement, physician, second


class TestNoticeGivenBeatsPanelCapacity:
    def test_a_full_panel_under_notice_reports_the_credential_error(self, api):
        """PRD §2.10: "This is the first half of a deliberate conflict pair: a
        physician whose `credential_status` is `NOTICE_GIVEN` and whose
        `panel_size` already equals `max_panel_size` violates both this check and
        check 27, and this check wins — the response is
        `ERR_PHYSICIAN_NOT_ACCEPTING_ASSIGNMENTS` with HTTP 409, never the fiscal
        capacity error."

        Design: Difficulty/priority_pair_validation_conflict/physician_notice_given_wins_over_full_panel_capacity
        """
        agreement, physician, second = _full_panel_under_notice(api)
        loaded = read_physician(api, physician["id"])
        assert loaded["panel_size"] == agreement["max_panel_size"] == 1
        assert loaded["credential_status"] == "NOTICE_GIVEN"

        response = api.create_assignment(
            assignment_payload(
                second["id"], physician["id"], enrollee_version(api, second["id"])
            ),
            NETWORK_MANAGER_HEADERS,
        )
        validate_error(response, ERR_PHYSICIAN_NOT_ACCEPTING_ASSIGNMENTS, 409)

    def test_neither_the_capacity_nor_the_closed_panel_error_is_reported(self, api):
        """PRD §2.10: "The target physician's `panel_size`, counting only
        assignments whose `status` is `ACTIVE`, is strictly less than the
        agreement's `max_panel_size`."

        Design: Difficulty/priority_pair_validation_conflict/physician_notice_given_wins_over_full_panel_capacity
        """
        _agreement, physician, second = _full_panel_under_notice(api)
        assert read_physician(api, physician["id"])["panel_status"] == "CLOSED_TO_NEW"

        response = api.create_assignment(
            assignment_payload(
                second["id"], physician["id"], enrollee_version(api, second["id"])
            ),
            NETWORK_MANAGER_HEADERS,
        )
        error = validate_error(response, ERR_PHYSICIAN_NOT_ACCEPTING_ASSIGNMENTS, 409)
        assert error["error_id"] != ERR_PANEL_CAPACITY_EXCEEDED
        assert error["error_id"] != ERR_PANEL_CLOSED_TO_NEW

    def test_the_refused_create_leaves_the_panel_counters_untouched(self, api):
        """PRD §2.9: "`DelegationAgreement.total_assigned_members` is the count of
        `ACTIVE` assignments across every physician of the agreement."

        Design: Difficulty/priority_pair_validation_conflict/physician_notice_given_wins_over_full_panel_capacity
        """
        agreement, physician, second = _full_panel_under_notice(api)

        api.create_assignment(
            assignment_payload(
                second["id"], physician["id"], enrollee_version(api, second["id"])
            ),
            NETWORK_MANAGER_HEADERS,
        )

        assert read_agreement(api, agreement["id"])["total_assigned_members"] == 1
        assert read_physician(api, physician["id"])["panel_size"] == 1


def _member_with_an_incumbent_assignment(api):
    """A member covered from 1 March who already sits on an open panel."""
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(api, max_panel_size=10)
    physician = create_active_physician(api, agreement["id"])
    enrollee = create_enrollee(
        api,
        agreement["id"],
        external_member_id="PO-0001",
        coverage_start_date="2026-03-01T00:00:00Z",
    )
    incumbent = assign_enrollee(
        api, enrollee["id"], physician["id"], effective_date="2026-03-01T00:00:00Z"
    )
    return agreement, physician, enrollee, incumbent


class TestAssignmentBeforeCoverageBeatsPeriodOverlap:
    def test_an_out_of_coverage_effective_date_reports_the_coverage_error(self, api):
        """PRD §2.10: "This is the second deliberate conflict pair: an
        `effective_date` earlier than `coverage_start_date` that also opens an
        interval overlapping the enrollee's existing `ACTIVE` assignment violates
        both this check and check 18, and this check wins — the response is
        `ERR_ASSIGNMENT_BEFORE_COVERAGE` with HTTP 422, never
        `ERR_ASSIGNMENT_PERIOD_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/assignment_before_coverage_wins_over_period_overlap
        """
        _agreement, physician, enrollee, _incumbent = _member_with_an_incumbent_assignment(
            api
        )

        response = api.create_assignment(
            assignment_payload(
                enrollee["id"],
                physician["id"],
                enrollee_version(api, enrollee["id"]),
                effective_date="2026-02-01T00:00:00Z",
            ),
            NETWORK_MANAGER_HEADERS,
        )
        error = validate_error(response, ERR_ASSIGNMENT_BEFORE_COVERAGE, 422)
        assert error["error_id"] != ERR_ASSIGNMENT_PERIOD_OVERLAP

    def test_the_pair_is_reachable_with_the_target_active_and_open(self, api):
        """PRD §2.10: "The pair is reachable with the target physician in
        `credential_status` `ACTIVE` and `panel_status` `OPEN`, so no
        state-category check interferes."

        Design: Difficulty/priority_pair_validation_conflict/assignment_before_coverage_wins_over_period_overlap
        """
        _agreement, physician, enrollee, _incumbent = _member_with_an_incumbent_assignment(
            api
        )
        loaded = read_physician(api, physician["id"])
        assert loaded["credential_status"] == "ACTIVE"
        assert loaded["panel_status"] == "OPEN"

        response = api.create_assignment(
            assignment_payload(
                enrollee["id"],
                physician["id"],
                enrollee_version(api, enrollee["id"]),
                effective_date="2026-02-01T00:00:00Z",
            ),
            NETWORK_MANAGER_HEADERS,
        )
        validate_error(response, ERR_ASSIGNMENT_BEFORE_COVERAGE, 422)

    def test_the_incumbent_assignment_survives_the_refused_create(self, api):
        """PRD §2.10: "The system evaluates the following checks top to bottom,
        and the first check whose condition is violated determines the response;
        no lower-numbered check is skipped and no higher-numbered check is
        evaluated once a rejection has been determined."

        Design: Difficulty/priority_pair_validation_conflict/assignment_before_coverage_wins_over_period_overlap
        """
        _agreement, physician, enrollee, incumbent = _member_with_an_incumbent_assignment(
            api
        )

        api.create_assignment(
            assignment_payload(
                enrollee["id"],
                physician["id"],
                enrollee_version(api, enrollee["id"]),
                effective_date="2026-02-01T00:00:00Z",
            ),
            NETWORK_MANAGER_HEADERS,
        )

        survivor = read_assignment(api, incumbent["id"])
        assert survivor["status"] == "ACTIVE"
        assert survivor["term_date"] is None
        assert read_physician(api, physician["id"])["panel_size"] == 1
