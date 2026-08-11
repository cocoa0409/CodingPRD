"""Event posture gating, violation cascades, and clock-driven expiry
(PRD §2.6, §2.9, §3.4)."""
from test_helpers import (
    ED,
    ApiErrorId,
    TEST_USERS,
    add_cleared_person,
    add_person,
    create_event,
    get_event,
    open_registration,
    add_milestone,
    make_team_lead_headers,
    register_and_confirm_team,
    set_clock,
    setup_confirmed_teams,
    setup_event_registration_open,
    setup_matches_running,
    validate_error,
    validate_success,
    api_client,
)

HEAD_REFEREE = TEST_USERS["head_referee_headers"]
LEAD_INSPECTOR = TEST_USERS["lead_inspector_headers"]


def _open_critical(event_id, team_id, opener_person_id, n=1):
    for i in range(n):
        validate_success(
            api_client.create_violation(
                event_id, team_id,
                {
                    "source_kind": "FIELD_SAFETY",
                    "severity": "CRITICAL",
                    "description": f"critical violation {i}",
                    "opened_by_person_id": opener_person_id,
                },
                HEAD_REFEREE,
            ),
            expected_status=201,
        )


class TestPostureComputation:
    def test_posture_open_when_no_violations(self):
        """PRD §2.6: "Otherwise, if `critical_open` is greater than zero or
        `uncleared_mentors` is greater than zero, posture becomes `RESTRICTED`.
        Otherwise posture is `OPEN`."

        Design: Corner/calculations/event_posture_open_when_no_violations
        """
        event = setup_event_registration_open()
        assert event["posture"] == "OPEN"
        ctx_team = register_and_confirm_team(event["id"], 6001)
        event = get_event(event["id"])
        assert event["posture"] == "OPEN"
        assert event["registered_team_count"] == 1
        assert event["cleared_mentor_count"] == 1

    def test_three_critical_violations_freeze_posture(self):
        """PRD §2.6: "If `critical_open` is at least
        `CRITICAL_FREEZE_THRESHOLD` = 3, posture becomes `FROZEN`." and "Any
        write attempted while posture is `FROZEN` is rejected with
        `ERR_EVENT_FROZEN` (HTTP 409)."

        Design: Difficulty/transitive_cascade/critical_violation_cascade_to_frozen_posture
        """
        ctx = setup_confirmed_teams(num_teams=1)
        event = ctx["event"]
        team = ctx["teams"][0]["team"]
        opener = ctx["teams"][0]["mentor"]
        _open_critical(event["id"], team["id"], opener["id"], n=3)
        event = get_event(event["id"])
        assert event["posture"] == "FROZEN"
        # Any write is now blocked — even opening another violation.
        resp = api_client.create_violation(
            event["id"], team["id"],
            {
                "source_kind": "FIELD_SAFETY",
                "severity": "MINOR",
                "description": "blocked write",
                "opened_by_person_id": opener["id"],
            },
            HEAD_REFEREE,
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_FROZEN)

    def test_two_critical_violations_restrict_but_do_not_freeze(self):
        """PRD §2.6: "If `critical_open` is at least
        `CRITICAL_FREEZE_THRESHOLD` = 3, posture becomes `FROZEN`. Otherwise,
        if `critical_open` is greater than zero ... posture becomes
        `RESTRICTED`."

        Design: Difficulty/transitive_cascade/critical_violation_cascade_to_frozen_posture
        """
        ctx = setup_confirmed_teams(num_teams=1)
        event = ctx["event"]
        team = ctx["teams"][0]["team"]
        opener = ctx["teams"][0]["mentor"]
        _open_critical(event["id"], team["id"], opener["id"], n=2)
        event = get_event(event["id"])
        assert event["posture"] == "RESTRICTED"
        assert event["outstanding_violation_count"] == 2


class TestMentorExpiryCascade:
    def test_last_mentor_expiry_flips_posture_to_restricted(self):
        """PRD §2.9: "Advancing the clock triggers the `screening_expiry`
        calculation, which transitions every `Person` whose `screening_status`
        is `CLEARED` and whose `screening_expires_at` has been reached or
        passed into `EXPIRED`. That expiry, in turn, can leave a confirmed team
        without a cleared mentor, which triggers a posture recomputation — so
        a single clock advance can flip an event from `OPEN` to `RESTRICTED`."

        Design: Difficulty/transitive_cascade/mentor_expiry_cascades_to_posture
        """
        event = setup_event_registration_open()
        entry = register_and_confirm_team(event["id"], 7001)
        # Mentor was cleared at the default clock (2026-05-01); a MENTOR's
        # clearance expires 180 days later (PRD §2.5).
        assert get_event(event["id"])["posture"] == "OPEN"
        set_clock("2026-10-29T00:00:00Z")  # 181 days past clearance
        person = validate_success(
            api_client.get_person(event["id"], entry["mentor"]["id"], TEST_USERS["screening_officer_headers"])
        )
        assert person["screening_status"] == "EXPIRED"
        assert get_event(event["id"])["posture"] == "RESTRICTED"

    def test_second_cleared_mentor_keeps_posture_open(self):
        """PRD §2.6: posture counts "confirmed teams that have no cleared
        mentor" — expiring one of two cleared mentors leaves the team staffed,
        so posture stays `OPEN`.

        Design: Difficulty/transitive_cascade/mentor_expiry_cascades_to_posture
        """
        event = setup_event_registration_open()
        team = validate_success(
            api_client.create_team(event["id"], {"team_number": 7002, "nickname": "T7002"},
                                   TEST_USERS["registration_officer_headers"]),
            expected_status=201,
        )
        # Mentor A cleared at the default clock (2026-05-01, expires +180d).
        mentor_a = add_cleared_person(event["id"], team["id"], "MENTOR", "m7002a@example.com")
        # Clock only moves forward: B cleared 30 days later (expires +180d).
        set_clock("2026-05-31T00:00:00Z")
        mentor_b = add_cleared_person(event["id"], team["id"], "MENTOR", "m7002b@example.com")
        add_person(event["id"], team["id"], "STUDENT", "s7002@example.com")
        validate_success(
            api_client.mark_payment_cleared(event["id"], team["id"],
                                            TEST_USERS["registration_officer_headers"])
        )
        validate_success(
            api_client.submit_roster(event["id"], team["id"],
                                     make_team_lead_headers(mentor_b["id"]))
        )
        validate_success(
            api_client.confirm_team(event["id"], team["id"],
                                    TEST_USERS["registration_officer_headers"])
        )
        # 2026-10-29 is past A's window (2026-05-01 + 180d = 2026-10-28) but
        # inside B's (2026-05-31 + 180d = 2026-11-27).
        set_clock("2026-10-29T00:00:00Z")
        so = TEST_USERS["screening_officer_headers"]
        a = validate_success(api_client.get_person(event["id"], mentor_a["id"], so))
        b = validate_success(api_client.get_person(event["id"], mentor_b["id"], so))
        assert a["screening_status"] == "EXPIRED"
        assert b["screening_status"] == "CLEARED"
        assert get_event(event["id"])["posture"] == "OPEN"

    def test_clock_advance_expires_cleared_person(self):
        """PRD §2.9: "Advancing the clock triggers the `screening_expiry`
        calculation, which transitions every `Person` whose `screening_status`
        is `CLEARED` and whose `screening_expires_at` has been reached or
        passed into `EXPIRED`."

        Design: Corner/cross_cutting/clock_set_drives_screening_expiry
        """
        event = create_event()
        # Cleared at the default clock (2026-05-01); MENTOR validity is 180
        # days (PRD §2.5), expiring 2026-10-28. Clock only moves forward.
        person = add_cleared_person(event["id"], None, "MENTOR", "expiry@example.com")
        assert person["screening_status"] == "CLEARED"
        set_clock("2026-10-29T00:00:00Z")  # past 2026-05-01 + 180 days
        person = validate_success(
            api_client.get_person(event["id"], person["id"], TEST_USERS["screening_officer_headers"])
        )
        assert person["screening_status"] == "EXPIRED"


class TestInspectionFailCascade:
    def test_fail_creates_open_major_inspection_violation(self):
        """PRD §3.4: "On a fail, the inspection moves `SUBMITTED → FAILED`,
        the team's `robot_inspection_status` flips to `FAILED`, and the server
        creates a `ComplianceViolation` against the team with `source_kind`
        set to `INSPECTION`, `severity` set to `MAJOR`, and `resolution_status`
        set to `OPEN`, recomputing the event's `outstanding_violation_count`."

        Design: Corner/state_machines/inspection_fail_creates_violation_cascade
        """
        from test_helpers import (
            advance_to_inspection,
            advance_to_build_season,
            create_robot_inspection_payload,
            make_inspector_headers,
            make_lead_inspector_headers,
        )

        ctx = setup_confirmed_teams(num_teams=2)
        event_id = ctx["event"]["id"]
        inspector = add_cleared_person(event_id, None, "VOLUNTEER", "insp-fail@example.com")
        advance_to_build_season(ctx)
        advance_to_inspection(ctx)
        team = ctx["teams"][0]["team"]
        insp = validate_success(
            api_client.create_robot_inspection(
                event_id, team["id"],
                create_robot_inspection_payload(inspector_id=inspector["id"]),
                make_inspector_headers(inspector["id"]),
            ),
            expected_status=201,
        )
        validate_success(
            api_client.submit_robot_inspection(
                event_id, team["id"], insp["id"], make_inspector_headers(inspector["id"])
            )
        )
        failed = validate_success(
            api_client.fail_robot_inspection(
                event_id, team["id"], insp["id"], make_lead_inspector_headers(inspector["id"])
            )
        )
        assert failed["status"] == "FAILED"
        reread_team = validate_success(api_client.get_team(event_id, team["id"], ED))
        assert reread_team["robot_inspection_status"] == "FAILED"
        violations = validate_success(
            api_client.list_violations(event_id, team["id"], HEAD_REFEREE, params={"limit": 100})
        )
        assert isinstance(violations, list) and len(violations) == 1
        v = violations[0]
        assert v["source_kind"] == "INSPECTION"
        assert v["severity"] == "MAJOR"
        assert v["resolution_status"] == "OPEN"
        assert get_event(event_id)["outstanding_violation_count"] == 1

    def test_overweight_robot_cannot_pass(self):
        """PRD §2.5: "`MAX_ROBOT_WEIGHT_KG` is 56.7 kilograms — a
        `RobotInspection` whose `weight_kg` is greater than 56.7 cannot be
        passed." PRD §3.4: "`weight_kg` at most 56.7 (else
        `ERR_ROBOT_OVERWEIGHT`)".

        Design: Corner/errors/err_robot_overweight_triggerable
        """
        from test_helpers import (
            advance_to_inspection,
            advance_to_build_season,
            create_robot_inspection_payload,
            make_inspector_headers,
            make_lead_inspector_headers,
        )

        ctx = setup_confirmed_teams(num_teams=2)
        event_id = ctx["event"]["id"]
        inspector = add_cleared_person(event_id, None, "VOLUNTEER", "insp-heavy@example.com")
        advance_to_build_season(ctx)
        advance_to_inspection(ctx)
        team = ctx["teams"][0]["team"]
        insp = validate_success(
            api_client.create_robot_inspection(
                event_id, team["id"],
                create_robot_inspection_payload(inspector_id=inspector["id"], weight_kg=60.0),
                make_inspector_headers(inspector["id"]),
            ),
            expected_status=201,
        )
        validate_success(
            api_client.submit_robot_inspection(
                event_id, team["id"], insp["id"], make_inspector_headers(inspector["id"])
            )
        )
        resp = api_client.pass_robot_inspection(
            event_id, team["id"], insp["id"], make_lead_inspector_headers(inspector["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ROBOT_OVERWEIGHT)
