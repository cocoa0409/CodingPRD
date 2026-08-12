"""Talent review calibration: sessions, entries, the challenge-revise loop."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_manager, setup_talent_manager, setup_report,
    setup_session, setup_in_progress_session, propose_entry, ratify_entry,
    make_talent_manager_headers, make_manager_headers,
)

ADMIN = TEST_USERS["admin_headers"]


class TestSessionCalendarOverlap:
    def test_overlapping_session_rejected(self, api):
        """PRD §2.11: "A new session conflicts with an existing session of the
        same `department_scope` whose status is `SCHEDULED` or `IN_PROGRESS`
        exactly when the new start is earlier than the existing end and the
        existing start is earlier than the new end."
        PRD §3.6: "the new window must not overlap any session of the same
        `department_scope` in `SCHEDULED` or `IN_PROGRESS` status, on pain of
        `ERR_SESSION_WINDOW_CONFLICT`, while back-to-back adjacency is
        permitted."

        Design: Difficulty/resource_temporal_overlap/session_calendar_half_open_adjacency
        """
        _, tm_headers = setup_talent_manager()
        setup_session(tm_headers, name="SALES-Q2-A", department_scope="SALES",
                      scheduled_start="2026-06-01T09:00:00Z",
                      scheduled_end="2026-06-01T12:00:00Z")

        resp = api.create_calibration_session({
            "name": "SALES-Q2-B", "department_scope": "SALES",
            "scheduled_start": "2026-06-01T11:00:00Z",
            "scheduled_end": "2026-06-01T13:00:00Z",
        }, tm_headers)
        validate_error(resp, ApiErrorId.ERR_SESSION_WINDOW_CONFLICT, 409)

    def test_adjacent_session_allowed(self, api):
        """PRD §2.11: "Adjacency is allowed: a session starting exactly at
        another session's `scheduled_end` — or ending exactly at another's
        `scheduled_start` — does not conflict."
        PRD §2.11: "A calibration session's window is the half-open interval
        spanning from `scheduled_start` up to but not including
        `scheduled_end`."

        Design: Difficulty/resource_temporal_overlap/session_calendar_half_open_adjacency
        """
        _, tm_headers = setup_talent_manager()
        first = setup_session(tm_headers, name="SALES-Q2-A", department_scope="SALES",
                              scheduled_start="2026-06-01T09:00:00Z",
                              scheduled_end="2026-06-01T12:00:00Z")

        adjacent = validate_success(api.create_calibration_session({
            "name": "SALES-Q2-C", "department_scope": "SALES",
            "scheduled_start": "2026-06-01T12:00:00Z",
            "scheduled_end": "2026-06-01T15:00:00Z",
        }, tm_headers), 201)
        assert adjacent["id"] != first["id"]
        assert adjacent["status"] == "SCHEDULED"

        sessions, meta = validate_paginated(api.list_calibration_sessions(
            tm_headers, params={"department_scope": "SALES"},
        ))
        assert meta["total_count"] == 2, (
            "the half-open calendar must hold both the 09-12 and 12-15 sessions"
        )


class TestFinalizeGates:
    def test_session_finalize_with_unratified_entry_returns_error(self, api):
        """PRD §3.6: "Finalization is the point of no return, and its gates run
        in a fixed order: the session must be `IN_PROGRESS` (otherwise
        `ERR_SESSION_INVALID_STATE`); it must contain at least one entry, i.e.
        `entry_count` of 1 or more (otherwise `ERR_SESSION_EMPTY`); and every
        entry must be ratified, i.e. `ratified_count` must equal `entry_count`
        (otherwise `ERR_UNRATIFIED_ENTRIES_REMAIN`)."

        Design: Corner/state_machines/session_finalize_with_unratified_entry_returns_error
        """
        _, tm_headers = setup_talent_manager()
        manager, _ = setup_manager()
        subject = setup_report(manager["id"], performance_rating="SOLID")
        session = setup_in_progress_session(tm_headers, name="CAL-56")
        propose_entry(session["id"], manager["id"], subject["id"],
                      proposed_rating="STRONG")

        resp = api.finalize_calibration_session(session["id"], tm_headers)
        validate_error(resp, ApiErrorId.ERR_UNRATIFIED_ENTRIES_REMAIN, 409)

        session = get_success_data(api.get_calibration_session(session["id"], tm_headers))
        assert session["status"] == "IN_PROGRESS"
        subject = get_success_data(api.get_employee(subject["id"], ADMIN))
        assert subject["performance_rating"] == "SOLID", (
            "a rejected finalize must not touch the employee's rating"
        )

    def test_session_finalize_empty_returns_session_empty(self, api):
        """PRD §3.6: "it must contain at least one entry, i.e. `entry_count`
        of 1 or more (otherwise `ERR_SESSION_EMPTY`); and every entry must be
        ratified, i.e. `ratified_count` must equal `entry_count` (otherwise
        `ERR_UNRATIFIED_ENTRIES_REMAIN`)."

        Design: Corner/state_machines/session_finalize_empty_returns_session_empty
        """
        _, tm_headers = setup_talent_manager()
        session = setup_in_progress_session(tm_headers, name="CAL-57",
                                            department_scope="HR")

        resp = api.finalize_calibration_session(session["id"], tm_headers)
        validate_error(resp, ApiErrorId.ERR_SESSION_EMPTY, 409)

        session = get_success_data(api.get_calibration_session(session["id"], tm_headers))
        assert session["status"] == "IN_PROGRESS"


class TestEntryStateGates:
    def test_entry_challenge_from_ratified_returns_invalid_state(self, api):
        """PRD §3.6: "A `TalentManager` challenges a `PROPOSED` entry — from
        any other status the attempt is rejected with
        `ERR_ENTRY_INVALID_STATE`, and the parent session must be
        `IN_PROGRESS` — moving it to `CHALLENGED` and incrementing
        `challenge_count` by one."

        Design: Corner/state_machines/entry_challenge_from_ratified_returns_invalid_state
        """
        _, tm_headers = setup_talent_manager()
        manager, _ = setup_manager()
        subject = setup_report(manager["id"], performance_rating="SOLID")
        session = setup_in_progress_session(tm_headers, name="CAL-58")
        entry = propose_entry(session["id"], manager["id"], subject["id"],
                              proposed_rating="STRONG")
        ratify_entry(entry["id"], tm_headers, "STRONG")

        resp = api.challenge_calibration_entry(entry["id"], tm_headers)
        validate_error(resp, ApiErrorId.ERR_ENTRY_INVALID_STATE, 409)
        after = get_success_data(api.get_calibration_entry(entry["id"], tm_headers))
        assert after["status"] == "RATIFIED"

    def test_entry_propose_before_session_start_returns_session_invalid_state(self, api):
        """PRD §3.6: "Proposal requires the parent session to be `IN_PROGRESS`
        (otherwise `ERR_SESSION_INVALID_STATE`), the caller to be the subject's
        `current_manager_id` (otherwise `ERR_NOT_REPORTING_MANAGER`), and the
        subject to have no other entry in this session (otherwise
        `ERR_DUPLICATE_SESSION_SUBJECT`)."

        Design: Corner/state_machines/entry_propose_before_session_start_returns_session_invalid_state
        """
        _, tm_headers = setup_talent_manager()
        manager, _ = setup_manager()
        subject = setup_report(manager["id"], performance_rating="SOLID")
        session = setup_session(tm_headers, name="CAL-59")
        assert session["status"] == "SCHEDULED"

        resp = api.create_calibration_entry(session["id"], {
            "employee_id": subject["id"], "proposed_rating": "STRONG",
        }, make_manager_headers(manager["id"]))
        validate_error(resp, ApiErrorId.ERR_SESSION_INVALID_STATE, 409)

        entries, meta = validate_paginated(api.list_calibration_entries(
            tm_headers, params={"session_id": session["id"]},
        ))
        assert meta["total_count"] == 0

    def test_duplicate_session_subject_returns_error(self, api):
        """PRD §3.6: "and the subject to have no other entry in this session
        (otherwise `ERR_DUPLICATE_SESSION_SUBJECT`)."
        PRD §3.6: "the session's `entry_count` recomputes."

        Design: Corner/validations/duplicate_session_subject_returns_error
        """
        _, tm_headers = setup_talent_manager()
        manager, _ = setup_manager()
        subject = setup_report(manager["id"], performance_rating="SOLID")
        session = setup_in_progress_session(tm_headers, name="CAL-96")
        propose_entry(session["id"], manager["id"], subject["id"],
                      proposed_rating="SOLID")

        resp = api.create_calibration_entry(session["id"], {
            "employee_id": subject["id"], "proposed_rating": "STRONG",
        }, make_manager_headers(manager["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SESSION_SUBJECT, 409)

        session = get_success_data(api.get_calibration_session(session["id"], tm_headers))
        assert session["entry_count"] == 1


class TestChallengeReviseLoop:
    def _setup_proposed_entry(self, api):
        _, tm_headers = setup_talent_manager()
        manager, _ = setup_manager()
        subject = setup_report(manager["id"], performance_rating="SOLID",
                               hire_date="2023-02-01")
        session = setup_in_progress_session(tm_headers, name="CAL-APR")
        entry = propose_entry(session["id"], manager["id"], subject["id"],
                              proposed_rating="SOLID")
        return tm_headers, manager, subject, session, entry

    def test_challenge_then_revise_returns_to_proposed(self, api):
        """PRD §3.6: "A `TalentManager` challenges a `PROPOSED` entry — from
        any other status the attempt is rejected with
        `ERR_ENTRY_INVALID_STATE`, and the parent session must be
        `IN_PROGRESS` — moving it to `CHALLENGED` and incrementing
        `challenge_count` by one."
        PRD §3.6: "Revision returns a `CHALLENGED` entry to `PROPOSED` with a
        replacement `proposed_rating`, and only the original proposer may
        revise: the caller must equal `proposed_by_manager_id`, otherwise
        `ERR_NOT_ENTRY_PROPOSER`."

        Design: Difficulty/non_linear_state_machine/calibration_entry_challenge_revise_loop
        """
        tm_headers, manager, _, session, entry = self._setup_proposed_entry(api)

        challenged = validate_success(
            api.challenge_calibration_entry(entry["id"], tm_headers), 200,
        )
        assert challenged["status"] == "CHALLENGED"
        assert challenged["challenge_count"] == 1

        revised = validate_success(api.revise_calibration_entry(
            entry["id"], {"proposed_rating": "STRONG"},
            make_manager_headers(manager["id"]),
        ), 200)
        assert revised["status"] == "PROPOSED", "the entry loops back to PROPOSED"
        assert revised["proposed_rating"] == "STRONG", "revise overwrote SOLID"

    def test_second_challenge_then_ratify_accumulates_count(self, api):
        """PRD §3.6: "Ratification fixes the outcome: a `TalentManager`
        ratifies an entry in `PROPOSED` or `CHALLENGED` — the state checks,
        including the parent session being `IN_PROGRESS`, are evaluated first —
        and segregation of duties then forbids the ratifier from being the
        entry's proposer (otherwise `ERR_SEGREGATION_OF_DUTIES`). Ratification
        fixes `calibrated_rating` from the supplied `final_rating`, moves the
        entry to `RATIFIED`, and recomputes the session's `ratified_count` —
        the count of entries in `RATIFIED` or `APPLIED`."

        Design: Difficulty/non_linear_state_machine/calibration_entry_challenge_revise_loop
        """
        tm_headers, manager, _, session, entry = self._setup_proposed_entry(api)

        api.challenge_calibration_entry(entry["id"], tm_headers)
        api.revise_calibration_entry(entry["id"], {"proposed_rating": "STRONG"},
                                     make_manager_headers(manager["id"]))
        challenged_again = validate_success(
            api.challenge_calibration_entry(entry["id"], tm_headers), 200,
        )
        assert challenged_again["challenge_count"] == 2, (
            "challenge_count accumulates across the revision cycle"
        )

        ratified = validate_success(api.ratify_calibration_entry(
            entry["id"], {"final_rating": "STRONG"}, tm_headers,
        ), 200)
        assert ratified["status"] == "RATIFIED"
        assert ratified["calibrated_rating"] == "STRONG"
        assert ratified["challenge_count"] == 2


class TestCalibrationSegregationAndAuthorship:
    def test_revise_by_non_proposer_returns_not_entry_proposer(self, api):
        """PRD §3.6: "Revision returns a `CHALLENGED` entry to `PROPOSED` with
        a replacement `proposed_rating`, and only the original proposer may
        revise: the caller must equal `proposed_by_manager_id`, otherwise
        `ERR_NOT_ENTRY_PROPOSER`."
        PRD §2.10: "Revision authorship requires `X-User-ID` to equal the
        entry's `proposed_by_manager_id` when a challenged rating is revised;
        violations are rejected with `ERR_NOT_ENTRY_PROPOSER` (HTTP 403)."

        Design: Corner/validations/revise_by_non_proposer_returns_not_entry_proposer
        """
        _, tm_headers = setup_talent_manager()
        manager, _ = setup_manager()
        other, _ = setup_manager()
        subject = setup_report(manager["id"], performance_rating="SOLID")
        session = setup_in_progress_session(tm_headers, name="CAL-106")
        entry = propose_entry(session["id"], manager["id"], subject["id"],
                              proposed_rating="SOLID")
        api.challenge_calibration_entry(entry["id"], tm_headers)

        resp = api.revise_calibration_entry(
            entry["id"], {"proposed_rating": "STRONG"},
            make_manager_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_ENTRY_PROPOSER, 403)
        after = get_success_data(api.get_calibration_entry(entry["id"], tm_headers))
        assert after["status"] == "CHALLENGED"
        assert after["proposed_rating"] == "SOLID"

    def test_ratify_by_proposer_returns_segregation_of_duties(self, api):
        """PRD §2.10: "In calibration, the facilitator ratifying an entry must
        not be the manager who proposed the rating. Either violation is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
        PRD §3.6: "a `TalentManager` ratifies an entry in `PROPOSED` or
        `CHALLENGED` — the state checks, including the parent session being
        `IN_PROGRESS`, are evaluated first — and segregation of duties then
        forbids the ratifier from being the entry's proposer (otherwise
        `ERR_SEGREGATION_OF_DUTIES`). Ratification fixes `calibrated_rating`
        from the supplied `final_rating`, moves the entry to `RATIFIED`, and
        recomputes the session's `ratified_count`"

        Design: Corner/rbac/ratify_by_proposer_returns_segregation_of_duties
        """
        _, tm_headers = setup_talent_manager()
        manager, _ = setup_manager()
        subject = setup_report(manager["id"], performance_rating="SOLID")
        session = setup_in_progress_session(tm_headers, name="CAL-124")
        entry = propose_entry(session["id"], manager["id"], subject["id"],
                              proposed_rating="SOLID")

        resp = api.ratify_calibration_entry(
            entry["id"], {"final_rating": "SOLID"},
            make_talent_manager_headers(manager["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 409)

        ratified = validate_success(api.ratify_calibration_entry(
            entry["id"], {"final_rating": "STRONG"}, tm_headers,
        ), 200)
        assert ratified["status"] == "RATIFIED"
        assert ratified["calibrated_rating"] == "STRONG", (
            "a different facilitator ratifies successfully"
        )
