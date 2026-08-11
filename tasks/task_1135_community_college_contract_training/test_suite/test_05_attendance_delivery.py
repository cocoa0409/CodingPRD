"""Attendance closure cascade, completion threshold boundary, credentialing."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_launched_cohort,
    setup_delivered_cohort,
    close_session_attendance,
    api_client,
    TEST_USERS,
    make_instructor_headers,
)

COORD = TEST_USERS["coordinator_headers"]
CRED = TEST_USERS["credential_officer_headers"]


class TestAttendanceCloseCascade:
    def test_close_attendance_cascades_to_delivery_and_completion(self, api):
        """PRD §3.6: "the cohort moves from `LAUNCHED` to `IN_PROGRESS` on its
        first `HELD` session; and when every session of the cohort sits in
        `HELD` or `CANCELLED` with at least one `HELD`, the cohort moves from
        `IN_PROGRESS` to `DELIVERED` and completion is evaluated." "A
        participant with zero attended hours becomes `NO_SHOW`; a participant
        whose rounded percentage is at least 80.00 — the boundary itself
        qualifies — becomes `COMPLETED`; anyone positive but below the
        threshold becomes `DROPPED`."

        Design: Difficulty/transitive_cascade/attendance_close_cascade_to_credentials
        """
        ctx = setup_launched_cohort(
            num_participants=2,
            min_enrollment=2,
            sessions=[("2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z"),
                      ("2026-06-16T09:00:00Z", "2026-06-16T11:00:00Z")],
            agreement_overrides={"pricing_model": "FLAT_COHORT",
                                 "est_participant_count": 2,
                                 "est_delivery_hours": 4},
            participant_prefix="K",
        )
        s1, s2 = ctx["session_ids"]
        p1, p2 = ctx["participants"]
        ins = ctx["instructor"]["id"]

        close_session_attendance(s1, ins, [
            {"external_employee_ref": "K01", "attended_hours": 2},
            {"external_employee_ref": "K02", "attended_hours": 2},
        ])
        mid = get_success_data(api_client.get_cohort(ctx["cohort"]["id"], COORD))
        assert mid["delivery_status"] == "IN_PROGRESS"

        close_session_attendance(s2, ins, [
            {"external_employee_ref": "K01", "attended_hours": 2},
            {"external_employee_ref": "K02", "attended_hours": 1},
        ])
        end = get_success_data(api_client.get_cohort(ctx["cohort"]["id"], COORD))
        assert end["delivery_status"] == "DELIVERED"
        assert end["completer_count"] == 1

        p1_after = get_success_data(api_client.get_participant(p1["id"], COORD))
        p2_after = get_success_data(api_client.get_participant(p2["id"], COORD))
        assert p1_after["completion_status"] == "COMPLETED"
        assert p1_after["attendance_pct"] == 100.00
        assert p2_after["completion_status"] == "DROPPED"
        assert p2_after["attendance_pct"] == 75.00

    def test_close_attendance_completes_assignment_and_releases_hours(self, api):
        """PRD §3.6: "The cascade continues outward: every `CONFIRMED`
        assignment on the session moves to `COMPLETED` and the instructor's
        `committed_hours` decreases by the session's `hours`".

        Design: Difficulty/transitive_cascade/attendance_close_cascade_to_credentials
        """
        ctx = setup_launched_cohort(num_participants=1, min_enrollment=1)
        sid = ctx["session_ids"][0]
        ins_id = ctx["instructor"]["id"]
        before = get_success_data(api_client.get_instructor(ins_id, COORD))
        assert before["committed_hours"] == 2

        close_session_attendance(sid, ins_id, [{"external_employee_ref": "P01",
                                                "attended_hours": 2}])
        assignments, _ = __import__("test_helpers").validate_paginated(
            api_client.list_session_instructor_assignments(sid, COORD)
        )
        assert len(assignments) == 1
        assert assignments[0]["status"] == "COMPLETED"
        after = get_success_data(api_client.get_instructor(ins_id, COORD))
        assert after["committed_hours"] == 0


class TestAttendanceThresholdBoundary:
    def _five_session_cohort(self, api):
        sessions = [("2026-06-%02dT09:00:00Z" % (15 + i),
                     "2026-06-%02dT11:00:00Z" % (15 + i)) for i in range(5)]
        return setup_launched_cohort(
            num_participants=2,
            min_enrollment=2,
            sessions=sessions,
            agreement_overrides={"pricing_model": "FLAT_COHORT",
                                 "est_participant_count": 2,
                                 "est_delivery_hours": 10},
            participant_prefix="P",
        )

    def test_exactly_80_pct_completes(self, api):
        """PRD §3.6: "a participant whose rounded percentage is at least
        80.00 — the boundary itself qualifies — becomes `COMPLETED`".

        Design: Difficulty/boundary_precision_check/attendance_threshold_exactly_80_pct
        """
        ctx = self._five_session_cohort(api)
        ins = ctx["instructor"]["id"]
        pa, pb = ctx["participants"]
        # PA: 2h on sessions 1-4, 0 on 5 -> 8.0/10.0 = 80.00
        # PB: 2h on 1-3, 1.99 on 4, 0 on 5 -> 7.99/10.0 = 79.90
        plan = [(2, 2), (2, 2), (2, 2), (2, 1.99), (None, None)]
        for sid, (ha, hb) in zip(ctx["session_ids"], plan):
            entries = []
            if ha is not None:
                entries.append({"external_employee_ref": "P01", "attended_hours": ha})
                entries.append({"external_employee_ref": "P02", "attended_hours": hb})
            close_session_attendance(sid, ins, entries)

        coh = get_success_data(api_client.get_cohort(ctx["cohort"]["id"], COORD))
        assert coh["delivery_status"] == "DELIVERED"
        pa_after = get_success_data(api_client.get_participant(pa["id"], COORD))
        assert pa_after["attendance_pct"] == 80.00
        assert pa_after["completion_status"] == "COMPLETED"

    def test_79_90_pct_drops(self, api):
        """PRD §3.6: "anyone positive but below the threshold becomes
        `DROPPED`"; threshold comparisons are made against the rounded value
        (PRD §2.7).

        Design: Difficulty/boundary_precision_check/attendance_threshold_exactly_80_pct
        """
        ctx = self._five_session_cohort(api)
        ins = ctx["instructor"]["id"]
        pb = ctx["participants"][1]
        plan = [(2, 2), (2, 2), (2, 2), (2, 1.99), (None, None)]
        for sid, (ha, hb) in zip(ctx["session_ids"], plan):
            entries = []
            if ha is not None:
                entries.append({"external_employee_ref": "P01", "attended_hours": ha})
                entries.append({"external_employee_ref": "P02", "attended_hours": hb})
            close_session_attendance(sid, ins, entries)

        pb_after = get_success_data(api_client.get_participant(pb["id"], COORD))
        assert pb_after["attendance_pct"] == 79.90
        assert pb_after["completion_status"] == "DROPPED"


class TestAttendanceAlreadyClosed:
    def test_second_close_rejected_and_no_double_count(self, api):
        """PRD §3.6: "invoking closure on a session already `HELD` returns the
        specialized `ERR_ATTENDANCE_ALREADY_CLOSED`".

        Design: Corner/errors/error_attendance_already_closed
        """
        ctx = setup_launched_cohort(
            num_participants=1,
            min_enrollment=1,
            sessions=[("2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z"),
                      ("2026-06-16T09:00:00Z", "2026-06-16T11:00:00Z")],
            agreement_overrides={"pricing_model": "FLAT_COHORT",
                                 "est_participant_count": 1,
                                 "est_delivery_hours": 4},
            participant_prefix="A",
        )
        s1 = ctx["session_ids"][0]
        p1 = ctx["participants"][0]
        ins = ctx["instructor"]["id"]
        close_session_attendance(s1, ins, [{"external_employee_ref": "A01",
                                            "attended_hours": 2}])
        resp = api_client.close_attendance(
            s1, {"attendance": [{"external_employee_ref": "A01", "attended_hours": 2}]},
            make_instructor_headers(ins),
        )
        validate_error(resp, ApiErrorId.ERR_ATTENDANCE_ALREADY_CLOSED)
        p1_after = get_success_data(api_client.get_participant(p1["id"], COORD))
        assert p1_after["attended_hours"] == 2


class TestNoCompletersBlocksCredentialing:
    def test_zero_hour_participant_yields_no_completers_error(self, api):
        """PRD §3.6: "A participant with zero attended hours becomes
        `NO_SHOW`". PRD §3.6: "a `completer_count` of zero is rejected with
        `ERR_NO_COMPLETERS`" on credential issue.

        Design: Corner/errors/error_no_completers_blocks_credentialing
        """
        ctx = setup_launched_cohort(
            num_participants=1, min_enrollment=1,
            sessions=[("2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")],
            participant_prefix="N",
        )
        close_session_attendance(ctx["session_ids"][0], ctx["instructor"]["id"], [])
        coh = get_success_data(api_client.get_cohort(ctx["cohort"]["id"], COORD))
        assert coh["delivery_status"] == "DELIVERED"
        assert coh["completer_count"] == 0
        p1 = get_success_data(api_client.get_participant(ctx["participants"][0]["id"], COORD))
        assert p1["completion_status"] == "NO_SHOW"
        resp = api_client.issue_credentials(ctx["cohort"]["id"], CRED)
        validate_error(resp, ApiErrorId.ERR_NO_COMPLETERS)
