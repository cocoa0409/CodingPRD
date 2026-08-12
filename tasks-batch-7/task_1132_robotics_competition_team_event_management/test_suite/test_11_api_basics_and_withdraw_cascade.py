"""API-wide basics (pagination envelope, role gating) and the team-withdraw
cascade (PRD §2.1, §2.3, §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_cleared_person,
    create_award_payload,
    create_event_payload,
    create_interview_slot_payload,
    create_manual_match,
    create_queue_slot_payload,
    get_event,
    make_team_lead_headers,
    setup_event_registration_open,
    setup_matches_running,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)

ED = TEST_USERS["event_director_headers"]
JA = TEST_USERS["judge_advisor_headers"]
QM = TEST_USERS["queue_manager_headers"]
TL_FALLBACK = TEST_USERS["team_lead_headers"]


class TestListPagination:
    def test_list_events_default_pagination_envelope(self):
        """PRD §2.3: "`limit` defaults to 10, must be at least 1, and must be
        at most 100. `offset` defaults to 0 ... The response `meta` for list
        endpoints includes `limit`, `offset`, `total_count`, and `has_more`;
        `has_more` is true if and only if `offset + limit` is less than
        `total_count`."

        Design: Corner/endpoints/list_events_default_pagination
        """
        for i in range(3):
            validate_success(
                api_client.create_event(create_event_payload(), ED), expected_status=201,
            )
        resp = api_client.list_events(ED)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestRoleGating:
    def test_teamlead_cannot_create_event(self):
        """PRD §2.1: "the server checks that the named role is on the
        endpoint's permitted-role list; if not, the request is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." PRD §4: `POST /frc-events` is
        authorized for `EventDirector` only.

        Design: Corner/validations/unauthorized_role_returns_403
        """
        resp = api_client.create_event(create_event_payload(), TL_FALLBACK)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestWithdrawCascade:
    def test_confirmed_withdraw_cascades_to_slots_and_interviews(self):
        """PRD §3.2: "The side effects are layered: `registered_team_count`
        decrements by 1, every `QueueSlot` belonging to this team that is
        currently `STAGED` or `AT_FIELD` flips to `NO_SHOW`, and every
        `InterviewSlot` belonging to this team that is currently `PROPOSED` or
        `CONFIRMED` flips to `CANCELLED`."

        Design: Difficulty/transitive_cascade/team_withdraw_cascades_3_levels
        """
        ctx = setup_matches_running(num_teams=6, field_count=2, with_judge=True)
        event_id = ctx["event"]["id"]
        target = ctx["teams"][0]
        team_id = target["team"]["id"]
        # A queue slot for the team (born STAGED, PRD §3.5).
        match = create_manual_match(
            ctx, team_id, ctx["teams"][3]["team"]["id"], match_number=9601,
        )
        slot = validate_success(
            api_client.create_queue_slot(
                event_id, match["id"],
                create_queue_slot_payload(team_id=team_id, position="RED_1"),
                QM,
            ),
            expected_status=201,
        )
        # An interview slot for the team (born PROPOSED, PRD §3.7).
        award = validate_success(
            api_client.create_award(
                event_id, create_award_payload(award_kind="DEANS_LIST", requires_interview=True),
                JA,
            ),
            expected_status=201,
        )
        interview = validate_success(
            api_client.create_interview_slot(
                event_id, award["id"],
                create_interview_slot_payload(
                    team_id=team_id, judge_id=ctx["judge"]["id"],
                    starts_at="2026-04-03T09:00:00Z", duration_minutes=30,
                ),
                JA,
            ),
            expected_status=201,
        )
        pre = get_event(event_id)["registered_team_count"]
        withdrawn = validate_success(
            api_client.withdraw_team(
                event_id, team_id, make_team_lead_headers(target["mentor"]["id"])
            )
        )
        assert withdrawn["registration_status"] == "WITHDRAWN"
        assert get_event(event_id)["registered_team_count"] == pre - 1
        slot_after = validate_success(
            api_client.get_queue_slot(event_id, match["id"], slot["id"], QM)
        )
        assert slot_after["status"] == "NO_SHOW"
        interview_after = validate_success(
            api_client.get_interview_slot(event_id, award["id"], interview["id"], JA)
        )
        assert interview_after["status"] == "CANCELLED"

    def test_withdraw_does_not_touch_other_teams_slots(self):
        """PRD §3.2 scopes the cascade to "this team": "every `QueueSlot`
        belonging to this team that is currently `STAGED` or `AT_FIELD` flips
        to `NO_SHOW`" — other teams' slots are unaffected.

        Design: Difficulty/transitive_cascade/team_withdraw_cascades_3_levels
        """
        ctx = setup_matches_running(num_teams=6, field_count=2, with_judge=True)
        event_id = ctx["event"]["id"]
        target = ctx["teams"][0]
        other = ctx["teams"][1]
        match = create_manual_match(
            ctx, target["team"]["id"], ctx["teams"][3]["team"]["id"], match_number=9602,
        )
        own_slot = validate_success(
            api_client.create_queue_slot(
                event_id, match["id"],
                create_queue_slot_payload(team_id=target["team"]["id"], position="RED_1"),
                QM,
            ),
            expected_status=201,
        )
        other_slot = validate_success(
            api_client.create_queue_slot(
                event_id, match["id"],
                create_queue_slot_payload(team_id=other["team"]["id"], position="RED_2"),
                QM,
            ),
            expected_status=201,
        )
        validate_success(
            api_client.withdraw_team(
                event_id, target["team"]["id"], make_team_lead_headers(target["mentor"]["id"])
            )
        )
        own_after = validate_success(
            api_client.get_queue_slot(event_id, match["id"], own_slot["id"], QM)
        )
        other_after = validate_success(
            api_client.get_queue_slot(event_id, match["id"], other_slot["id"], QM)
        )
        assert own_after["status"] == "NO_SHOW"
        assert other_after["status"] == "STAGED"
