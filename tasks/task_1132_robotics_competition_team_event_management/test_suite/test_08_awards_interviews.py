"""Judge interview scheduling: half-open overlap rule and award RBAC
(PRD §3.7, §2.1)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_cleared_person,
    add_person,
    create_award_payload,
    create_interview_slot_payload,
    make_team_lead_headers,
    setup_event_registration_open,
    validate_error,
    validate_success,
    api_client,
)

JA = TEST_USERS["judge_advisor_headers"]
RO = TEST_USERS["registration_officer_headers"]
JUDGE_FALLBACK = TEST_USERS["judge_headers"]


def _setup_judge_and_teams():
    """REGISTRATION_OPEN event, one CLEARED judge, two teams with mentors."""
    event = setup_event_registration_open()
    event_id = event["id"]
    judge = add_cleared_person(event_id, None, "JUDGE", "judge-overlap@example.com")
    teams = []
    for i in (1, 2, 3):
        team = validate_success(
            api_client.create_team(event_id, {"team_number": 8000 + i, "nickname": f"T{i}"}, RO),
            expected_status=201,
        )
        mentor = add_person(event_id, team["id"], "MENTOR", f"mentor{i}@example.com")
        teams.append({"team": team, "mentor": mentor})
    award = validate_success(
        api_client.create_award(
            event_id, create_award_payload(award_kind="CHAIRMANS", requires_interview=True), JA,
        ),
        expected_status=201,
    )
    return event, judge, teams, award


class TestJudgeDoubleBooking:
    def test_adjacent_slots_do_not_conflict_but_one_minute_overlap_does(self):
        """PRD §3.7: "no other `CONFIRMED` slot for the same judge may overlap
        in time, where overlap is defined on half-open intervals
        `[starts_at, starts_at + duration_minutes)` — two slots that share
        only an endpoint do not overlap. A conflicting confirm is rejected
        with `ERR_JUDGE_DOUBLE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/judge_interview_overlap_half_open
        """
        event, judge, teams, award = _setup_judge_and_teams()
        event_id, award_id = event["id"], award["id"]
        # Slot 1: [10:00, 10:30) CONFIRMED.
        s1 = validate_success(
            api_client.create_interview_slot(
                event_id, award_id,
                create_interview_slot_payload(
                    team_id=teams[0]["team"]["id"], judge_id=judge["id"],
                    starts_at="2026-04-02T10:00:00Z", duration_minutes=30,
                ),
                JA,
            ),
            expected_status=201,
        )
        validate_success(
            api_client.confirm_interview_slot(
                event_id, award_id, s1["id"],
                make_team_lead_headers(teams[0]["mentor"]["id"]),
            )
        )
        # Slot 2: [10:30, 11:00) — shares only the endpoint 10:30 -> allowed.
        s2 = validate_success(
            api_client.create_interview_slot(
                event_id, award_id,
                create_interview_slot_payload(
                    team_id=teams[1]["team"]["id"], judge_id=judge["id"],
                    starts_at="2026-04-02T10:30:00Z", duration_minutes=30,
                ),
                JA,
            ),
            expected_status=201,
        )
        confirmed2 = validate_success(
            api_client.confirm_interview_slot(
                event_id, award_id, s2["id"],
                make_team_lead_headers(teams[1]["mentor"]["id"]),
            )
        )
        assert confirmed2["status"] == "CONFIRMED"
        # Slot 3: [10:29, 10:59) — overlaps slot 1 by one minute -> rejected.
        s3 = validate_success(
            api_client.create_interview_slot(
                event_id, award_id,
                create_interview_slot_payload(
                    team_id=teams[2]["team"]["id"], judge_id=judge["id"],
                    starts_at="2026-04-02T10:29:00Z", duration_minutes=30,
                ),
                JA,
            ),
            expected_status=201,
        )
        resp = api_client.confirm_interview_slot(
            event_id, award_id, s3["id"],
            make_team_lead_headers(teams[2]["mentor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_JUDGE_DOUBLE_BOOKED)

    def test_overlap_rule_is_per_judge(self):
        """PRD §3.7: "Confirming a slot checks for judge double-booking: no
        other `CONFIRMED` slot for the same judge may overlap in time" — the
        rule is scoped to the same judge, so a different judge may hold an
        overlapping CONFIRMED slot.

        Design: Difficulty/resource_temporal_overlap/judge_interview_overlap_half_open
        """
        event, judge_a, teams, award = _setup_judge_and_teams()
        judge_b = add_cleared_person(event["id"], None, "JUDGE", "judge-b@example.com")
        event_id, award_id = event["id"], award["id"]
        s1 = validate_success(
            api_client.create_interview_slot(
                event_id, award_id,
                create_interview_slot_payload(
                    team_id=teams[0]["team"]["id"], judge_id=judge_a["id"],
                    starts_at="2026-04-02T10:00:00Z", duration_minutes=30,
                ),
                JA,
            ),
            expected_status=201,
        )
        validate_success(
            api_client.confirm_interview_slot(
                event_id, award_id, s1["id"],
                make_team_lead_headers(teams[0]["mentor"]["id"]),
            )
        )
        s2 = validate_success(
            api_client.create_interview_slot(
                event_id, award_id,
                create_interview_slot_payload(
                    team_id=teams[1]["team"]["id"], judge_id=judge_b["id"],
                    starts_at="2026-04-02T10:15:00Z", duration_minutes=30,
                ),
                JA,
            ),
            expected_status=201,
        )
        confirmed = validate_success(
            api_client.confirm_interview_slot(
                event_id, award_id, s2["id"],
                make_team_lead_headers(teams[1]["mentor"]["id"]),
            )
        )
        assert confirmed["status"] == "CONFIRMED"


class TestAwardRbac:
    def test_judge_cannot_decide_award(self):
        """PRD §2.1: "the server checks that the named role is on the
        endpoint's permitted-role list; if not, the request is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." PRD §4: award decide is
        authorized for `JudgeAdvisor` only.

        Design: Corner/rbac/judge_cannot_decide_award
        """
        event = setup_event_registration_open()
        award = validate_success(
            api_client.create_award(
                event["id"], create_award_payload(award_kind="SAFETY", requires_interview=False),
                JA,
            ),
            expected_status=201,
        )
        resp = api_client.decide_award(event["id"], award["id"], JUDGE_FALLBACK)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
