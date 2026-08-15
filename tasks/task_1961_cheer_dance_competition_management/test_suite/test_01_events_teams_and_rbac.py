"""Event creation envelope, division defaults, team system fields, RBAC."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_division,
    assert_team,
    create_division_payload,
    create_event,
    create_event_payload,
    create_panel,
    create_team_payload,
    get_success_data,
    make_team_coach_headers,
    setup_event_with_division,
    setup_registered_team,
    validate_error,
    validate_paginated,
    validate_success,
)

DIRECTOR = TEST_USERS["event_director_headers"]
MUSIC = TEST_USERS["music_compliance_headers"]


class TestEventBasics:
    def test_event_create_missing_name_returns_invalid_request(self, api):
        """PRD §2.6: "**Request-body shape** — all required fields present,
        types correct, enum members valid, and payload-local ranges hold:
        `quantity` at least 1 and integral, `ends_at` strictly after
        `starts_at`, `min_age` not greater than `max_age`, `max_athletes` not
        less than `min_athletes`, `judge_ids` containing 3 to 9 elements, all
        score fields within 0 to 10, ticket `quantity` within 1 to 40
        (`ERR_INVALID_INPUT`)."

        Design: Corner/entities/event_create_missing_name_returns_invalid_request
        """
        payload = create_event_payload()
        del payload["name"]
        resp = api.create_event(payload, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT)

    def test_get_missing_event_returns_not_found(self, api):
        """PRD §2.6: "**Existence** — path identifiers resolve left-to-right,
        then request-body foreign keys (`event_id`, `division_id`, `team_id`,
        `athlete_id`, `session_id`, and so on) resolve (`ERR_NOT_FOUND`)."

        Design: Corner/entities/get_missing_event_returns_not_found
        """
        resp = api.get_event(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_event(create_event_payload(), {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestDivisionDefaults:
    def test_division_creation_applies_defaults(self, api):
        """PRD §3.1: "Deduction pricing is per division:
        `time_deduction_per_second` (default 0.5 points per full second over
        the time limit), `safety_deduction_points` (default 2.0 per safety
        occurrence), and `boundary_deduction_points` (default 0.25 per
        boundary occurrence)."
        PRD §3.1: "`warmup_duration_seconds`, which defaults to 900 — fifteen
        minutes per warm-up slot."
        PRD §2.8: "Each division is created with a championship bid pool whose
        size is `paid_bid_count` plus `at_large_bid_count`; that sum is the
        initial value of the division's `bid_pool_available`."

        Design: Corner/entities/division_creation_applies_defaults
        """
        event = create_event()
        panel, _, _ = create_panel(count=3)
        resp = api.create_division(
            create_division_payload(event["id"], [j["id"] for j in panel],
                                    paid_bid_count=2, at_large_bid_count=1),
            DIRECTOR,
        )
        division = validate_success(resp, 201)
        assert_division(division)
        assert division["time_deduction_per_second"] == 0.5
        assert division["safety_deduction_points"] == 2.0
        assert division["boundary_deduction_points"] == 0.25
        assert division["warmup_duration_seconds"] == 900
        assert division["bid_pool_available"] == 3
        assert division["scheduled"] is False
        assert division["version"] == 1


class TestTeamSystemFields:
    def test_team_system_fields_input_ignored(self, api):
        """PRD §2.8: "Request payloads follow a silent-ignore convention:
        fields not declared for an endpoint are never persisted and never
        echoed, and fields that are system- or computed-sourced are ignored
        when supplied by a client."
        PRD §3.2: "A team is born with `reg_status` of `REGISTERED` and a
        parallel `music_status` of `PENDING`"

        Design: Corner/entities/team_system_fields_input_ignored
        """
        event, division, panel, head, safety = setup_event_with_division()
        payload = create_team_payload(event["id"], division["id"], "coach-1")
        payload["reg_status"] = "CHECKED_IN"
        payload["music_status"] = "VERIFIED"
        resp = api.create_team(payload, make_team_coach_headers("coach-1"))
        team = validate_success(resp, 201)
        assert_team(team)
        assert team["reg_status"] == "REGISTERED"
        assert team["music_status"] == "PENDING"


class TestImmediateConsistency:
    def test_immediate_read_after_write_visibility(self, api):
        """PRD §2.3: "Unless otherwise specified, every list endpoint returns
        its resources sorted by `created_at` ascending (oldest first)"
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the
        data field."

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        event, division, panel, head, safety = setup_event_with_division()
        team, athlete, entry = setup_registered_team(division)

        created = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert created["name"] == "T1"
        assert created["reg_status"] == "REGISTERED"

        teams, meta = validate_paginated(api.list_event_teams(event["id"], DIRECTOR))
        assert meta["total_count"] == 1
        assert len(teams) == 1
        assert teams[0]["id"] == team["id"]


class TestRbac:
    def test_coach_cannot_perform_director_operations_returns_forbidden(self, api):
        """PRD §2.1: "A request whose role is not listed among the endpoint's
        authorized roles — or that fails the endpoint's ownership check — is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/coach_cannot_perform_director_operations_returns_forbidden
        """
        payload = create_division_payload(NON_EXISTENT_UUID, ["x", "y", "z"])
        resp = api.create_division(payload, make_team_coach_headers("coach-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_coach_cannot_operate_other_coachs_team(self, api):
        """PRD §2.1: "every coach-scoped operation (roster management,
        check-in, withdrawal, music submission, appeals, bid responses,
        warm-up booking) compares the team's `coach_user_id` to `X-User-ID`."
        PRD §2.1: "A request whose role is not listed among the endpoint's
        authorized roles — or that fails the endpoint's ownership check — is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/coach_cannot_operate_other_coachs_team
        """
        event, division, panel, head, safety = setup_event_with_division()
        team, athlete, entry = setup_registered_team(division, coach_id="coach-1")

        resp = api.lock_roster(team["id"], make_team_coach_headers("coach-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        team_after = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert team_after["reg_status"] == "REGISTERED"

    def test_judge_role_cannot_confirm_official(self, api):
        """PRD §2.1: "A request whose role is not listed among the endpoint's
        authorized roles — or that fails the endpoint's ownership check — is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.6: "**Authorization and ownership** — role appears in the
        endpoint's authorized list; `TeamCoach` operations compare `X-User-ID`
        to the team's `coach_user_id`, spectator pay/cancel compares to the
        order's `purchaser_user_id`, and score-sheet edit or submit compares
        to the sheet's `judge_id` (`ERR_FORBIDDEN`)."

        Design: Corner/rbac/judge_role_cannot_confirm_official
        """
        resp = api.confirm_official(NON_EXISTENT_UUID,
                                    TEST_USERS["judge_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_spectator_cannot_pay_anothers_order(self, api):
        """PRD §2.1: "When `X-User-Role` is `Spectator`, `X-User-ID` is
        likewise opaque; it is captured as `purchaser_user_id` on each
        `TicketOrder` at creation, and the pay/cancel ownership checks compare
        that stored field to `X-User-ID`."
        PRD §3.8: "From `HELD`, the owning spectator pays: the logical now
        must be no later than `hold_expires_at`, inclusive
        (`ERR_ORDER_HOLD_EXPIRED`), and the actor must match
        `purchaser_user_id` (`ERR_FORBIDDEN`)."

        Design: Corner/rbac/spectator_cannot_pay_anothers_order
        """
        from test_helpers import create_ticket_order, setup_session
        event, session = setup_session(capacity=50)
        order = create_ticket_order(session["id"], "spec-1", quantity=2)

        from test_helpers import make_spectator_headers
        resp = api.pay_ticket_order(order["id"], make_spectator_headers("spec-2"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_ticket_order(order["id"], DIRECTOR))
        assert after["status"] == "HELD"


class TestEmptyListing:
    def test_empty_list_pagination_envelope(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.3: "`limit` defaults to 10 when omitted, accepts a minimum of 1
        and a maximum of 100, and `offset` defaults to 0."
        PRD §2.3: "The `meta` envelope of a list response carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/empty_list_pagination_envelope
        """
        event = create_event()
        resp = api.list_event_teams(event["id"], DIRECTOR)
        data, meta = validate_paginated(resp)
        assert data == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
