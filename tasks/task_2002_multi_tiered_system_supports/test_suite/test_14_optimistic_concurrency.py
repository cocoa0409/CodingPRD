"""Optimistic concurrency control on student and plan writes (PRD §2.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_second_window_screening,
    convene_meeting,
    create_team_meeting,
    get_plan,
    get_student,
    pause_plan,
    propose_tier_movement_payload,
    record_weekly_probes,
    resume_plan,
    setup_active_plan,
    setup_student_with_ratified_tier,
    validate_error,
    validate_success,
)

LEAD = TEST_USERS["team_lead_headers"]


class TestStaleStudentVersionOnRatify:
    def test_ratify_with_stale_student_version_rejected(self, api):
        """PRD §2.9: "A ratification request must carry an
        `expected_student_version` matching the student's current `version`: if
        another writer has advanced the student's version since the client last
        read it — for example, by ratifying a different movement for the same
        student, which rewrites `current_tier` and bumps the student's `version`
        — the ratification is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the client from acting on a student record it has not
        observed."
        PRD §3.4: "Writing the proposal increments the student's `version` by
        one."

        The client reads the student, then proposes (which itself advances the
        student's version), then ratifies with the pre-proposal version.

        Design: Corner/errors/err_stale_version_triggerable_via_occ
        """
        ctx = setup_student_with_ratified_tier(api, target_tier="TIER_2",
                                               raw_score=80)
        d_id, s_id, st_id = (ctx["district"]["id"], ctx["school"]["id"],
                             ctx["student"]["id"])
        add_second_window_screening(api, ctx, raw_score=60)
        meeting = create_team_meeting(api, d_id, s_id, scheduled_on="2026-12-20")
        convene_meeting(api, d_id, s_id, meeting["id"])

        stale_version = get_student(api, d_id, s_id, st_id)["version"]
        # The proposal write advances the student's version (PRD §3.4); a
        # proposal creates a new movement resource, so 201 per PRD §4.
        proposed = validate_success(api.propose_tier_movement(
            d_id, s_id, st_id,
            propose_tier_movement_payload("TIER_3", "WINTER", stale_version),
            LEAD), 201)
        assert proposed["status"] == "PROPOSED"
        assert get_student(api, d_id, s_id, st_id)["version"] != stale_version

        resp = api.ratify_movement(
            d_id, s_id, meeting["id"],
            {"movement_id": proposed["id"],
             "expected_student_version": stale_version},
            LEAD)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


class TestStalePlanVersionOnExit:
    def test_exit_with_stale_plan_version_rejected(self, api):
        """PRD §2.9: "Pausing, resuming, exiting, or cancelling a plan requires
        `expected_plan_version`, the client's last observed `version` of the
        plan."
        PRD §2.9: "Likewise, a plan-exit request must carry an
        `expected_plan_version` matching the plan's current `version`: if a
        ratification cascade has already moved the plan to `EXIT_MOVED`,
        advancing the plan's `version`, the exit is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        The plan carries full EXIT_RESPONSIVE evidence (five responsive probes,
        the latest one RESPONSIVE) and is ACTIVE, so the version mismatch is the
        only failing precondition: the version captured at creation has since
        advanced through a pause/resume pair.

        Design: Corner/cross_cutting/optimistic_concurrency_on_plan_exit
        """
        ctx = setup_active_plan(api, tier="TIER_2", raw_score=100,
                                tier2_max_score=130, tier3_max_score=90,
                                probe_frequency="WEEKLY")
        d_id, s_id = ctx["district"]["id"], ctx["school"]["id"]
        st_id, plan_id = ctx["student"]["id"], ctx["plan"]["id"]
        stale_version = ctx["plan"]["version"]

        # Responsive evidence: scores outrun the rising aimline (104, 108, 111,
        # 115, 119) in every trailing window.
        probes = record_weekly_probes(api, ctx, [104, 110, 116, 122, 128],
                                      first_date="2026-08-12")
        assert probes[-1]["slope_decision"] == "RESPONSIVE"

        # Advance the plan's version while keeping it ACTIVE.
        pause_plan(api, ctx)
        resume_plan(api, ctx)
        plan = get_plan(api, d_id, s_id, st_id, plan_id)
        assert plan["status"] == "ACTIVE"
        assert plan["version"] != stale_version

        resp = api.exit_plan(
            d_id, s_id, st_id, plan_id,
            {"expected_plan_version": stale_version,
             "exit_kind": "EXIT_RESPONSIVE"},
            LEAD)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
