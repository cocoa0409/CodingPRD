"""Financial-education pairings (caseload, completion, follow-up gating) and
retention checkpoints (creation on OPENED, epoch evaluation, early closure)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_institution_officer_headers,
    make_financial_coach_headers,
    MAX_ACTIVE_PAIRINGS_PER_COACH,
    create_participant, create_pairing, complete_pairing,
    setup_opened_account, setup_submitted_application,
    setup_declined_chex_case, propose_case, accept_case, decide_application,
    set_clock, run_ops_epoch,
)

ADMIN = TEST_USERS["coalition_admin_headers"]
NAV = TEST_USERS["agency_navigator_headers"]


class TestCoachCaseload:
    def test_fourth_active_pairing_rejected(self, api):
        """PRD §3.8: "A coach may hold at most three `ACTIVE` pairings: creation requires the coach's count of `ACTIVE` pairings to be strictly below three, and a create at the limit is rejected with `ERR_COACH_CASELOAD_FULL`."

        Design: Corner/calculations/coach_caseload_boundary
        """
        participants = [
            create_participant(full_name=f"P {i}", date_of_birth=f"1990-01-0{i + 1}")
            for i in range(4)
        ]
        for p in participants[:3]:
            create_pairing(p["id"], coach_id="coach-1")

        resp = api.create_education_pairing(
            {"participant_id": participants[3]["id"], "coach_id": "coach-1",
             "course_code": "FOUNDATIONS"},
            make_financial_coach_headers("coach-1"),
        )
        validate_error(resp, ApiErrorId.ERR_COACH_CASELOAD_FULL)

        _, meta = validate_paginated(
            api.list_education_pairings(
                ADMIN, params={"coach_id": "coach-1", "status": "ACTIVE"}
            )
        )
        assert meta["total_count"] == MAX_ACTIVE_PAIRINGS_PER_COACH


class TestFollowUpGating:
    def test_log_follow_up_gated_until_due(self, api):
        """PRD §3.8: "Completion stamps `completed_at` with the current logical-clock reading and computes `follow_up_due_at` as `completed_at` plus 30 days."
        PRD §3.8: "Logging the follow-up — again restricted to the pairing's own coach — is allowed only from `FOLLOW_UP_DUE`: attempting it while the pairing is `COMPLETED` but not yet due is rejected with `ERR_FOLLOW_UP_NOT_DUE`, and attempting it from any other status is rejected with `ERR_INVALID_STATE`."
        PRD §3.8: "From there the ops epoch moves the pairing from `COMPLETED` to `FOLLOW_UP_DUE` once the logical clock reaches `follow_up_due_at`."

        Design: Corner/state_machines/follow_up_gating_by_clock
        """
        p = create_participant()
        pairing = create_pairing(p["id"], coach_id="coach-1")
        complete_pairing(pairing["id"], coach_id="coach-1")  # completed 2026-05-01, due 2026-05-31

        set_clock("2026-05-15T00:00:00Z")
        resp = api.log_follow_up(pairing["id"], make_financial_coach_headers("coach-1"))
        validate_error(resp, ApiErrorId.ERR_FOLLOW_UP_NOT_DUE)

        set_clock("2026-06-01T00:00:00Z")
        run_ops_epoch()
        data = validate_success(
            api.log_follow_up(pairing["id"], make_financial_coach_headers("coach-1")), 200
        )
        assert data["status"] == "FOLLOW_UP_DONE"


class TestCheckpointCreation:
    def test_approval_creates_m6_m12_pair(self, api):
        """PRD §3.6: "creates two `RetentionCheckpoint` rows for the application, both `PENDING`: an `M6` checkpoint whose `due_date` is the date of `opened_at` plus 183 days, and an `M12` checkpoint whose `due_date` is the date of `opened_at` plus 365 days; each checkpoint's `window_end` is its `due_date` plus 30 days."
        PRD §2.5: "At startup the logical clock reads exactly `2026-05-01T00:00:00Z`; before any explicit set call it never falls back to wall-clock time."

        Design: Corner/entities/checkpoint_pair_created_on_opened
        """
        ctx = setup_opened_account()  # approved at the startup clock 2026-05-01
        rows, meta = validate_paginated(
            api.list_retention_checkpoints(
                ADMIN, params={"application_id": ctx["application"]["id"]}
            )
        )
        assert meta["total_count"] == 2, "exactly two checkpoints per OPENED"
        by_kind = {c["kind"]: c for c in rows}
        assert set(by_kind) == {"M6", "M12"}
        assert all(c["status"] == "PENDING" for c in rows)
        assert by_kind["M6"]["due_date"] == "2026-10-31"   # 2026-05-01 + 183d
        assert by_kind["M6"]["window_end"] == "2026-11-30"  # due + 30d
        assert by_kind["M12"]["due_date"] == "2027-05-01"  # 2026-05-01 + 365d
        assert by_kind["M12"]["window_end"] == "2027-05-31"


class TestCheckpointEvaluation:
    def test_early_closure_resolves_m6_not_retained(self, api):
        """PRD §3.7: "It resolves to `EVALUATED_NOT_RETAINED` when the application is `CLOSED_EARLY` with a `closed_at` date on or before the `due_date`."
        PRD §3.6: "Pending retention checkpoints are not resolved at closure time; they remain `PENDING` until the ops epoch evaluates them."
        PRD §2.5: "The epoch returns a summary object with integer counts `checkpoints_evaluated`, `certifications_lapsed`, `events_completed`, and `follow_ups_due`."

        Design: Corner/state_machines/checkpoint_not_retained_on_early_closure
        """
        ctx = setup_opened_account()  # OPENED 2026-05-01; M6 due 2026-10-31
        app_id = ctx["application"]["id"]
        officer = make_institution_officer_headers(ctx["institution"]["id"])
        data = validate_success(
            api.report_application_closure(app_id, {"closed_at": "2026-08-01T00:00:00Z"},
                                           officer), 200
        )
        assert data["status"] == "CLOSED_EARLY"

        set_clock("2026-11-10T00:00:00Z")
        summary = run_ops_epoch()
        assert summary["checkpoints_evaluated"] == 1, "only M6 is due by 2026-11-10"

        rows, _ = validate_paginated(
            api.list_retention_checkpoints(ADMIN, params={"application_id": app_id})
        )
        by_kind = {c["kind"]: c for c in rows}
        assert by_kind["M6"]["status"] == "EVALUATED_NOT_RETAINED", (
            "closed_at 2026-08-01 is on or before due_date 2026-10-31"
        )
        assert by_kind["M12"]["status"] == "PENDING", "M12 due 2027-05-01 not reached"


class TestReinstatedApplication:
    def test_reinstated_application_can_open(self, api):
        """PRD §3.6: "A reinstated application may be decided again; a fresh CHEX decline on it opens a new barrier case."
        PRD §3.6: "The decision endpoint accepts applications in `SUBMITTED` or `REINSTATED`; deciding from any other status is rejected with `ERR_INVALID_STATE`."
        PRD §3.6: "creates two `RetentionCheckpoint` rows for the application, both `PENDING`"

        Design: Corner/state_machines/reinstated_application_can_open
        """
        ctx = setup_declined_chex_case()
        inst_id = ctx["institution"]["id"]
        propose_case(ctx["case"]["id"], inst_id, 15000)
        accept_case(ctx["case"]["id"], ctx["participant"]["id"])  # -> REINSTATED

        data = decide_application(ctx["application"]["id"], inst_id, "APPROVE")
        assert data["status"] == "OPENED"
        assert data.get("account_number"), "account_number minted at the eventual OPENED"

        rows, meta = validate_paginated(
            api.list_retention_checkpoints(
                ADMIN, params={"application_id": ctx["application"]["id"]}
            )
        )
        assert meta["total_count"] == 2, "checkpoint pair created exactly once"
        referral = get_success_data(api.get_referral(ctx["referral"]["id"], NAV))
        assert referral["status"] == "CLOSED_CONVERTED"
        participant = get_success_data(api.get_participant(ctx["participant"]["id"], NAV))
        assert participant["pipeline_stage"] == "ACCOUNT_OPENED"
