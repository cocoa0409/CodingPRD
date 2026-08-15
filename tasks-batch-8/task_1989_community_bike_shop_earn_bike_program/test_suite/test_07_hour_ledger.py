"""Earn-a-bike hour ledger: boundary hours (queue A), hour-void cascade
(queue A), OCC on participant (queue B), and hour corner cases (queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    make_participant, log_hours, approve_log, set_clock,
    TEST_USERS, make_participant_headers, make_coordinator_headers,
    make_director_headers,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestHoursExactThreshold:
    def test_below_threshold_stays_enrolled(self):
        """PRD §3.7: "When a recompute lifts an `ENROLLED` participant's
        `hours_earned` to at least their `required_hours` — equality triggers —
        the participant auto-advances `ENROLLED → HOURS_MET`."

        Design: Difficulty/boundary_precision_check/hours_exact_threshold_promotes
        """
        p = make_participant(full_name="P Adult", contact_email="pa@x.org",
                             age_group="ADULT")
        set_clock("2026-08-07T00:00:00Z")
        h1 = log_hours(p["id"], "2026-08-02", 6, "REFURB_WORK")
        h2 = log_hours(p["id"], "2026-08-03", 5, "SHOP_HELP")
        approve_log(h1["id"], p["id"])
        approve_log(h2["id"], p["id"])
        mid = validate_success(api_client.get_participant(p["id"], COORD))
        assert mid["hours_earned"] == 11
        assert mid["status"] == "ENROLLED"
        assert mid["required_hours"] == 12

    def test_exact_threshold_promotes_to_hours_met(self):
        """PRD §3.7: "When a recompute lifts an `ENROLLED` participant's
        `hours_earned` to at least their `required_hours` — equality triggers —
        the participant auto-advances `ENROLLED → HOURS_MET`."

        Design: Difficulty/boundary_precision_check/hours_exact_threshold_promotes
        """
        p = make_participant(full_name="P Adult", contact_email="pa@x.org",
                             age_group="ADULT")
        set_clock("2026-08-07T00:00:00Z")
        h1 = log_hours(p["id"], "2026-08-02", 6, "REFURB_WORK")
        h2 = log_hours(p["id"], "2026-08-03", 5, "SHOP_HELP")
        h3 = log_hours(p["id"], "2026-08-04", 1, "OUTREACH")
        approve_log(h1["id"], p["id"])
        approve_log(h2["id"], p["id"])
        approve_log(h3["id"], p["id"])
        end = validate_success(api_client.get_participant(p["id"], COORD))
        assert end["hours_earned"] == 12
        assert end["status"] == "HOURS_MET"
        assert end["required_hours"] == 12


class TestHourVoidDemotionCascade:
    def _setup_reserved_participant(self):
        """YOUTH participant (8 required) at HOURS_MET with a reserved bike."""
        from test_helpers import make_ready_bike
        p = make_participant(full_name="P Youth", contact_email="py@x.org",
                             age_group="YOUTH")
        set_clock("2026-08-07T00:00:00Z")
        h1 = log_hours(p["id"], "2026-08-02", 4, "REFURB_WORK")
        h2 = log_hours(p["id"], "2026-08-03", 4, "SHOP_HELP")
        approve_log(h1["id"], p["id"])
        approve_log(h2["id"], p["id"])
        donor_bike, _, _, _ = make_ready_bike(bike_type="ROAD", grade="B")
        validate_success(
            api_client.reserve_bike(p["id"], {"bike_id": donor_bike["id"]},
                                    make_participant_headers(p["id"]))
        )
        return p, h1, h2, donor_bike

    def test_void_recomputes_hours_and_demotes(self):
        """PRD §3.7: "A void flips the log to `VOIDED`, stamps
        `reviewed_by_user_id` and the optional `reason` as the log's
        `void_reason`, decrements `hours_earned` through the recompute, and
        bumps the participant's `version`. If the participant was `HOURS_MET`
        and the recompute drops them below their required hours, they demote
        `HOURS_MET → ENROLLED`".

        Design: Difficulty/transitive_cascade/hour_void_demotion_releases_bike
        """
        p, h1, h2, bike = self._setup_reserved_participant()
        voided = validate_success(
            api_client.void_hour_log(
                h2["id"], {"reason": "logged against wrong program"}, DIRECTOR
            )
        )
        assert voided["status"] == "VOIDED"
        after = validate_success(api_client.get_participant(p["id"], COORD))
        assert after["hours_earned"] == 4
        assert after["status"] == "ENROLLED"

    def test_void_demotion_force_releases_reserved_bike(self):
        """PRD §3.7: "if they were holding a reserved bike, that reservation is
        force-released: the bike returns `RESERVED_FOR_GRADUATE →
        READY_FOR_DISPOSITION` and `reserved_bike_id` clears to null, with both
        records' versions bumping."

        Design: Difficulty/transitive_cascade/hour_void_demotion_releases_bike
        """
        p, h1, h2, bike = self._setup_reserved_participant()
        validate_success(
            api_client.void_hour_log(h2["id"], {"reason": "wrong program"}, DIRECTOR)
        )
        after = validate_success(api_client.get_participant(p["id"], COORD))
        assert after["reserved_bike_id"] is None
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "READY_FOR_DISPOSITION"
        # sibling log untouched
        h1_after = validate_success(api_client.get_hour_log(h1["id"], COORD))
        assert h1_after["status"] == "APPROVED"


class TestHoursApproveVoidConservation:
    def test_approve_then_void_restores_hours(self):
        """PRD §3.7: "recomputes the participant's `hours_earned` as the sum of
        hours across all approved logs — pending, rejected, and voided rows
        never count".

        Design: Difficulty/compensating_invariant/hours_approve_void_conservation
        """
        p = make_participant(full_name="P HC", contact_email="phc@x.org",
                             age_group="YOUTH")
        set_clock("2026-08-07T00:00:00Z")
        h1 = log_hours(p["id"], "2026-08-02", 4, "REFURB_WORK")
        h2 = log_hours(p["id"], "2026-08-03", 4, "OUTREACH")
        approve_log(h1["id"], p["id"])
        approve_log(h2["id"], p["id"])
        mid = validate_success(api_client.get_participant(p["id"], COORD))
        assert mid["hours_earned"] == 8
        assert mid["status"] == "HOURS_MET"

        validate_success(api_client.void_hour_log(h2["id"], {"reason": "duplicate"}, DIRECTOR))
        end = validate_success(api_client.get_participant(p["id"], COORD))
        assert end["hours_earned"] == 4
        assert end["status"] == "ENROLLED"

    def test_log_statuses_after_void(self):
        """PRD §3.7: "Approval flips the log `PENDING → APPROVED`" and "A void
        flips the log to `VOIDED`".

        Design: Difficulty/compensating_invariant/hours_approve_void_conservation
        """
        p = make_participant(full_name="P HC2", contact_email="phc2@x.org",
                             age_group="YOUTH")
        set_clock("2026-08-07T00:00:00Z")
        h1 = log_hours(p["id"], "2026-08-02", 4, "REFURB_WORK")
        h2 = log_hours(p["id"], "2026-08-03", 4, "OUTREACH")
        approve_log(h1["id"], p["id"])
        approve_log(h2["id"], p["id"])
        validate_success(api_client.void_hour_log(h2["id"], {"reason": "duplicate"}, DIRECTOR))
        h1_after = validate_success(api_client.get_hour_log(h1["id"], COORD))
        h2_after = validate_success(api_client.get_hour_log(h2["id"], COORD))
        assert h1_after["status"] == "APPROVED"
        assert h2_after["status"] == "VOIDED"


class TestHourLogCorners:
    def test_double_approve_returns_invalid_state(self):
        """PRD §3.7: "Approval flips the log `PENDING → APPROVED`" — a log no
        longer PENDING cannot be approved again (PRD §2.7: `ERR_INVALID_STATE`
        when no more specific code applies).

        Design: Corner/state_machines/double_approve_hour_returns_invalid_state
        """
        p = make_participant(full_name="P DA", contact_email="pda@x.org",
                             age_group="YOUTH")
        set_clock("2026-08-07T00:00:00Z")
        h1 = log_hours(p["id"], "2026-08-02", 4, "SHOP_HELP")
        approve_log(h1["id"], p["id"])
        first = validate_success(api_client.get_participant(p["id"], COORD))
        assert first["hours_earned"] == 4

        # second approve with the current (fresh) version — log is no longer PENDING
        r = api_client.approve_hour_log(
            h1["id"],
            {"expected_participant_version": first["version"]},
            make_coordinator_headers("sc-approver-1"),
        )
        validate_error(r, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api_client.get_participant(p["id"], COORD))
        assert after["hours_earned"] == 4

    def test_hourlog_reject_is_terminal(self):
        """PRD §3.7: "Rejection flips the log `PENDING → REJECTED`" — REJECTED
        is terminal, so later approve and void fail (PRD §2.7:
        `ERR_INVALID_STATE` when no more specific code applies).

        Design: Corner/state_machines/hourlog_reject_is_terminal
        """
        p = make_participant(full_name="P RJ", contact_email="prj@x.org",
                             age_group="ADULT")
        set_clock("2026-08-07T00:00:00Z")
        h1 = log_hours(p["id"], "2026-08-02", 3, "OUTREACH")
        validate_success(
            api_client.reject_hour_log(
                h1["id"], {"reason": "unverifiable"},
                make_coordinator_headers("sc-reviewer-1"),
            )
        )
        cur = validate_success(api_client.get_participant(p["id"], COORD))
        r1 = api_client.approve_hour_log(
            h1["id"], {"expected_participant_version": cur["version"]},
            make_coordinator_headers("sc-reviewer-1"),
        )
        validate_error(r1, ApiErrorId.ERR_INVALID_STATE)
        r2 = api_client.void_hour_log(h1["id"], {"reason": "late"}, DIRECTOR)
        validate_error(r2, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api_client.get_participant(p["id"], COORD))
        assert after["hours_earned"] == 0

    def test_daily_hours_cap_aggregate_boundary(self):
        """PRD §3.7: "the daily cap: across a single `work_date`, the sum of
        `hours` over the participant's logs in `PENDING` or `APPROVED` status,
        including the new log, must not exceed 6, else
        `ERR_DAILY_HOURS_EXCEEDED`; rejected and voided rows free their hours."

        Design: Corner/validations/daily_hours_cap_aggregate_boundary
        """
        p = make_participant(full_name="P DC", contact_email="pdc@x.org",
                             age_group="ADULT")
        set_clock("2026-08-07T00:00:00Z")
        log_hours(p["id"], "2026-08-02", 4, "SHOP_HELP")
        r7 = api_client.create_hour_log(
            p["id"],
            {"work_date": "2026-08-02", "hours": 3, "activity_type": "SHOP_HELP"},
            make_participant_headers(p["id"]),
        )
        validate_error(r7, ApiErrorId.ERR_DAILY_HOURS_EXCEEDED)
        log_hours(p["id"], "2026-08-02", 2, "OUTREACH")
        r1 = api_client.create_hour_log(
            p["id"],
            {"work_date": "2026-08-02", "hours": 1, "activity_type": "OUTREACH"},
            make_participant_headers(p["id"]),
        )
        validate_error(r1, ApiErrorId.ERR_DAILY_HOURS_EXCEEDED)
        _, meta = validate_paginated(
            api_client.list_hour_logs(COORD, params={"participant_id": p["id"]})
        )
        assert meta["total_count"] == 2

    def test_work_date_window_enforced(self):
        """PRD §3.7: "The `work_date` must fall within the participation window
        — on or after the enrollment date and no later than the earlier of the
        current clock date and the deadline date — else
        `ERR_WORK_DATE_OUT_OF_WINDOW`."

        Design: Corner/validations/work_date_window_enforced
        """
        # enrolled at default clock 2026-08-01
        p = make_participant(full_name="P WD", contact_email="pwd@x.org",
                             age_group="ADULT")
        set_clock("2026-08-07T00:00:00Z")
        r_past = api_client.create_hour_log(
            p["id"],
            {"work_date": "2026-07-31", "hours": 2, "activity_type": "SHOP_HELP"},
            make_participant_headers(p["id"]),
        )
        validate_error(r_past, ApiErrorId.ERR_WORK_DATE_OUT_OF_WINDOW)
        r_future = api_client.create_hour_log(
            p["id"],
            {"work_date": "2026-08-09", "hours": 2, "activity_type": "SHOP_HELP"},
            make_participant_headers(p["id"]),
        )
        validate_error(r_future, ApiErrorId.ERR_WORK_DATE_OUT_OF_WINDOW)
        ok = validate_success(
            api_client.create_hour_log(
                p["id"],
                {"work_date": "2026-08-06", "hours": 2, "activity_type": "SHOP_HELP"},
                make_participant_headers(p["id"]),
            ),
            expected_status=201,
        )
        assert ok["status"] == "PENDING"

    def test_reviewer_is_logger_segregation(self):
        """PRD §2.9: "The reviewer of an hour log — approver, rejecter, or
        voider — must not be the person who created it; equality of the
        reviewer's `X-User-ID` with the log's `created_by_user_id` is rejected
        with `ERR_REVIEWER_IS_LOGGER`."

        Design: Corner/validations/reviewer_is_logger_segregation
        """
        p = make_participant(full_name="P SD", contact_email="psd@x.org",
                             age_group="ADULT")
        set_clock("2026-08-07T00:00:00Z")
        h1 = log_hours(p["id"], "2026-08-02", 2, "SHOP_HELP", as_user_id="sc-1")
        cur = validate_success(api_client.get_participant(p["id"], COORD))
        r = api_client.approve_hour_log(
            h1["id"], {"expected_participant_version": cur["version"]},
            make_coordinator_headers("sc-1"),
        )
        validate_error(r, ApiErrorId.ERR_REVIEWER_IS_LOGGER)
        ok = validate_success(
            api_client.approve_hour_log(
                h1["id"], {"expected_participant_version": cur["version"]},
                make_coordinator_headers("sc-2"),
            )
        )
        assert ok["status"] == "APPROVED"

    def test_coordinator_cannot_void_hourlog(self):
        """PRD §3.7: "Voiding is the director's compensating action against an
        `APPROVED` log" — the coordinator role is not authorized (PRD §2.1:
        rejected with `ERR_FORBIDDEN`).

        Design: Corner/rbac/coordinator_cannot_void_hourlog
        """
        p = make_participant(full_name="P VH", contact_email="pvh@x.org",
                             age_group="YOUTH")
        set_clock("2026-08-07T00:00:00Z")
        h1 = log_hours(p["id"], "2026-08-02", 2, "SHOP_HELP")
        approve_log(h1["id"], p["id"])
        r = api_client.void_hour_log(h1["id"], {"reason": "test"}, COORD)
        validate_error(r, ApiErrorId.ERR_FORBIDDEN)
        ok = validate_success(
            api_client.void_hour_log(h1["id"], {"reason": "test"}, DIRECTOR)
        )
        assert ok["status"] == "VOIDED"

    def test_participant_cannot_log_for_other_participant(self):
        """PRD §2.1: "When `X-User-Role` is `Participant`, `X-User-ID` is the
        `id` of the acting `EarnABikeParticipant`; a `Participant` may read only
        their own record and touch only their own hour logs, reservation, and
        withdrawal." and "A request whose authenticated role is not in the
        endpoint's authorized list, or whose entity-backed identity does not own
        the targeted resource, is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/participant_cannot_log_for_other_participant
        """
        pa = make_participant(full_name="P A", contact_email="pa@x.org", age_group="ADULT")
        pb = make_participant(full_name="P B", contact_email="pb@x.org", age_group="ADULT")
        set_clock("2026-08-07T00:00:00Z")
        r = api_client.create_hour_log(
            pb["id"],
            {"work_date": "2026-08-02", "hours": 2, "activity_type": "SHOP_HELP"},
            make_participant_headers(pa["id"]),
        )
        validate_error(r, ApiErrorId.ERR_FORBIDDEN)
        _, meta = validate_paginated(
            api_client.list_hour_logs(COORD, params={"participant_id": pb["id"]})
        )
        assert meta["total_count"] == 0

    def test_hourlog_shift_not_creditable(self):
        """PRD §3.7: "When `shift_id` is present it must reference a `COMPLETED`
        shift, else `ERR_SHIFT_NOT_CREDITABLE`."

        Design: Corner/validations/hourlog_shift_not_creditable
        """
        from test_helpers import make_volunteer, create_shift_payload
        p = make_participant(full_name="P SL", contact_email="psl@x.org",
                             age_group="ADULT")
        v = make_volunteer(full_name="V SL", email="vsl@x.org")
        sh = validate_success(
            api_client.create_shift(
                create_shift_payload(
                    v["id"], scheduled_start="2026-08-05T09:00:00Z",
                    scheduled_end="2026-08-05T10:00:00Z",
                ),
                COORD,
            ),
            expected_status=201,
        )
        set_clock("2026-08-07T00:00:00Z")
        r = api_client.create_hour_log(
            p["id"],
            {"work_date": "2026-08-05", "hours": 2, "activity_type": "SHOP_HELP",
             "shift_id": sh["id"]},
            make_participant_headers(p["id"]),
        )
        validate_error(r, ApiErrorId.ERR_SHIFT_NOT_CREDITABLE)
