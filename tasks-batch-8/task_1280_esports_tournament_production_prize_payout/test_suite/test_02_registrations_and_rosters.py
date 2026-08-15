"""Registration lifecycle, roster construction rules, appeal cycle, listing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_tournament,
    api_client,
    appeal_registration,
    create_player,
    create_registration,
    create_tournament,
    get_registration,
    get_roster_slot,
    make_team_manager_headers,
    review_registration,
    set_clock,
    set_eligibility,
    setup_locked_tournament,
    setup_registration_open_tournament,
    submit_registration,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["organizer_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]


class TestAppealCycle:

    def test_registration_appeal_cycle_completes_once(self):
        """PRD §3.2: "A rejected registration may be appealed exactly once by
        its owning `TeamManager` while the tournament is still in
        `REGISTRATION_OPEN`: the appeal transitions `REJECTED → APPEALED` and
        flips `appeal_used` to true."
        PRD §2.4: "The `version` starts at 1 at creation and increments by
        exactly 1 on every mutation, regardless of how many fields change;
        `updated_at` refreshes on every mutation."

        Design: Corner/state_machines/registration_appeal_cycle_completes_once
        """
        ctx = setup_registration_open_tournament(
            "Appeal Cup",
            team_specs=[{"handle": "p1", "dob": "2000-01-01",
                         "team_name": "Alpha", "rank": 100,
                         "review": None}])
        reg = ctx["registrations"][0]
        assert reg["status"] == "SUBMITTED" and reg["version"] == 2

        rejected = review_registration(reg["id"], "REJECT",
                                       reason="incomplete eligibility paperwork")
        assert rejected["status"] == "REJECTED" and rejected["version"] == 3

        appealed = appeal_registration(reg["id"])
        assert appealed["status"] == "APPEALED"
        assert appealed["appeal_used"] is True
        assert appealed["version"] == 4

        approved = review_registration(reg["id"], "APPROVE")
        assert approved["status"] == "APPROVED" and approved["version"] == 5

    def test_registration_second_appeal_rejected(self):
        """PRD §3.2: "Review of an `APPEALED` registration may end at
        `APPROVED` or `REJECTED`; after a re-rejection the cycle is closed
        because `appeal_used` is already true."
        PRD §3.2: "A second appeal is rejected with `ERR_APPEAL_EXHAUSTED`."

        Design: Corner/state_machines/registration_second_appeal_rejected
        """
        ctx = setup_registration_open_tournament(
            "Appeal2 Cup",
            team_specs=[{"handle": "p1", "dob": "2000-01-01",
                         "team_name": "Alpha", "rank": 100,
                         "review": None}])
        reg = ctx["registrations"][0]
        review_registration(reg["id"], "REJECT")
        appeal_registration(reg["id"])
        review_registration(reg["id"], "REJECT")

        resp = api_client.appeal_registration(
            reg["id"], make_team_manager_headers(reg["id"]))
        validate_error(resp, ApiErrorId.ERR_APPEAL_EXHAUSTED)
        assert get_registration(reg["id"])["status"] == "REJECTED"

    def test_registration_unreviewed_at_lock_auto_rejected(self):
        """PRD §3.3: "The advance cascades: every registration in `APPROVED`
        moves to `LOCKED`, and every registration still in `SUBMITTED` or
        `APPEALED` moves to `REJECTED` as unreviewed at lock."

        Design: Corner/state_machines/registration_unreviewed_at_lock_auto_rejected
        """
        specs = [
            {"handle": "p1", "dob": "2000-01-01", "team_name": "Alpha",
             "rank": 100},
            {"handle": "p2", "dob": "2000-02-02", "team_name": "Beta",
             "rank": 80, "review": None},
        ]
        ctx = setup_locked_tournament("Lock Cup", team_specs=specs)
        r1, r2 = ctx["registrations"]
        assert r1["status"] == "LOCKED"
        assert r2["status"] == "REJECTED", \
            "unreviewed-at-lock registration must be auto-REJECTED"


class TestRosterLockAge:

    def test_roster_slot_lock_computes_age_and_minor_flag(self):
        """PRD §3.2: "A slot starts in `ACTIVE` with `age_at_lock_years` and
        `is_minor` null until roster lock."
        PRD §3.3: "the slot's age is the whole years between the player's
        `date_of_birth` and the lock instant, using calendar-year rollover so
        a player is exactly N years old on their Nth birthday; `is_minor` is
        true when `age_at_lock_years` is strictly less than 18, and an 18th
        birthday falling exactly on the lock day yields `is_minor` false."

        Design: Corner/entities/roster_slot_lock_computes_age_and_minor_flag
        """
        specs = [
            {"handle": "p1", "dob": "2010-06-15", "team_name": "Alpha",
             "rank": 100},
            {"handle": "p2", "dob": "2000-02-02", "team_name": "Beta",
             "rank": 80},
        ]
        ctx = setup_registration_open_tournament("Age Cup", team_specs=specs)
        slot1 = ctx["slots"][0]
        assert slot1["age_at_lock_years"] is None
        assert slot1["is_minor"] is None

        set_clock("2026-08-10T00:00:00Z")
        advance_tournament(ctx["tournament"]["id"], "REGISTRATION_LOCKED")

        locked_slot = get_roster_slot(slot1["id"])
        assert locked_slot["age_at_lock_years"] == 16
        assert locked_slot["is_minor"] is True
        assert get_registration(ctx["registrations"][0]["id"])[
            "status"] == "LOCKED"

    def test_minor_age_exactly_eighteen_at_lock(self):
        """PRD §3.3: "the slot's age is the whole years between the player's
        `date_of_birth` and the lock instant, using calendar-year rollover so
        a player is exactly N years old on their Nth birthday; `is_minor` is
        true when `age_at_lock_years` is strictly less than 18, and an 18th
        birthday falling exactly on the lock day yields `is_minor` false."

        Design: Corner/calculations/minor_age_exactly_eighteen_at_lock
        """
        specs = [
            {"handle": "p1", "dob": "2008-08-10", "team_name": "Alpha",
             "rank": 100},
            {"handle": "p2", "dob": "2008-08-11", "team_name": "Beta",
             "rank": 80},
        ]
        ctx = setup_locked_tournament("AgeEdge Cup", team_specs=specs)
        slot1 = get_roster_slot(ctx["slots"][0]["id"])
        slot2 = get_roster_slot(ctx["slots"][1]["id"])
        assert slot1["age_at_lock_years"] == 18
        assert slot1["is_minor"] is False, \
            "an 18th birthday exactly on lock day yields is_minor false"
        assert slot2["age_at_lock_years"] == 17
        assert slot2["is_minor"] is True


class TestSubmitGates:

    def test_submit_before_window_opens_returns_window_closed(self):
        """PRD §3.2: "the tournament must be in `REGISTRATION_OPEN`, and the
        logical clock must lie within the registration window (at or after
        `registration_opens_at`, at or before `registration_closes_at`) —
        outside that window the request is rejected with
        `ERR_REGISTRATION_WINDOW_CLOSED`."

        Design: Corner/validations/submit_before_window_opens_returns_window_closed
        """
        set_clock("2026-07-15T00:00:00Z")
        ctx = setup_registration_open_tournament(
            "Window Cup", team_count=1,
            team_specs=[{"handle": "p1", "dob": "2000-01-01",
                         "team_name": "Alpha", "rank": 100,
                         "submit": False}])
        reg = ctx["registrations"][0]
        resp = api_client.submit_registration(
            reg["id"], make_team_manager_headers(reg["id"]))
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_WINDOW_CLOSED)
        assert get_registration(reg["id"])["status"] == "DRAFT"

    def test_roster_size_violation_on_submit(self):
        """PRD §3.2: "The roster shape check requires exactly `roster_size`
        `ACTIVE` slots with `slot_role` `STARTER` and a total `ACTIVE` count
        not exceeding `max_roster_size`; violations are rejected with
        `ERR_ROSTER_SIZE_VIOLATION`."

        Design: Corner/validations/roster_size_violation_on_submit
        """
        ctx = setup_registration_open_tournament(
            "Roster Cup", team_count=1, roster_size=2, max_roster_size=3,
            team_specs=[{"handle": "p1", "dob": "2000-01-01",
                         "team_name": "Alpha", "rank": 100,
                         "submit": False}])
        reg = ctx["registrations"][0]
        resp = api_client.submit_registration(
            reg["id"], make_team_manager_headers(reg["id"]))
        validate_error(resp, ApiErrorId.ERR_ROSTER_SIZE_VIOLATION)
        assert get_registration(reg["id"])["status"] == "DRAFT"

    def test_submit_with_suspended_player_returns_ineligible(self):
        """PRD §3.2: "Every `ACTIVE` slot's player must currently be
        `ELIGIBLE`, and the `captain_player_id` must be the `player_id` of an
        `ACTIVE` `STARTER` slot; violations are rejected with
        `ERR_PLAYER_INELIGIBLE`."
        PRD §3.9: "an `OrganizerAdmin` may adjust a player's eligibility via
        an action of `SUSPEND` (moving `ELIGIBLE → SUSPENDED`) or `REINSTATE`
        (moving `SUSPENDED → ELIGIBLE`)."

        Design: Corner/validations/submit_with_suspended_player_returns_ineligible
        """
        ctx = setup_registration_open_tournament(
            "Suspend Cup", team_count=1,
            team_specs=[{"handle": "p1", "dob": "2000-01-01",
                         "team_name": "Alpha", "rank": 100,
                         "submit": False}])
        reg = ctx["registrations"][0]
        player = ctx["players"][0]

        set_eligibility(player["id"], "SUSPEND")
        resp = api_client.submit_registration(
            reg["id"], make_team_manager_headers(reg["id"]))
        validate_error(resp, ApiErrorId.ERR_PLAYER_INELIGIBLE)
        assert get_registration(reg["id"])["status"] == "DRAFT"

        set_eligibility(player["id"], "REINSTATE")
        ok = submit_registration(reg["id"])
        assert ok["status"] == "SUBMITTED"

    def test_double_submit_returns_invalid_registration_status(self):
        """PRD §3.2: "A `TeamManager` submits a registration whose status is
        `DRAFT`; the tournament must be in `REGISTRATION_OPEN`"
        PRD §2.7: "requesting a transition from a state that does not permit
        it is rejected with the machine's specific invalid-status error
        (HTTP 409)."

        Design: Corner/errors/double_submit_returns_invalid_registration_status
        """
        ctx = setup_registration_open_tournament(
            "Twice Cup",
            team_specs=[{"handle": "p1", "dob": "2000-01-01",
                         "team_name": "Alpha", "rank": 100,
                         "review": None}])
        reg = ctx["registrations"][0]
        assert reg["status"] == "SUBMITTED"
        resp = api_client.submit_registration(
            reg["id"], make_team_manager_headers(reg["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REGISTRATION_STATUS)
        assert get_registration(reg["id"])["status"] == "SUBMITTED"


class TestRosterUniqueness:

    def test_double_roster_add_returns_player_double_rostered(self):
        """PRD §3.2: "A player may appear on at most one registration's
        `ACTIVE` roster per tournament; attempting to add a player already
        `ACTIVE` on another registration is rejected with
        `ERR_PLAYER_DOUBLE_ROSTERED`."

        Design: Corner/errors/double_roster_add_returns_player_double_rostered
        """
        ctx = setup_registration_open_tournament(
            "Dup Cup", team_count=2,
            team_specs=[
                {"handle": "p1", "dob": "2000-01-01", "team_name": "Alpha",
                 "rank": 100, "submit": False},
                {"handle": "p2", "dob": "2000-02-02", "team_name": "Beta",
                 "rank": 80, "submit": False},
            ])
        r1, r2 = ctx["registrations"]
        p1 = ctx["players"][0]
        resp = api_client.create_roster_slot(
            {"registration_id": r2["id"], "player_id": p1["id"],
             "slot_role": "SUBSTITUTE"},
            make_team_manager_headers(r2["id"]))
        validate_error(resp, ApiErrorId.ERR_PLAYER_DOUBLE_ROSTERED)
        data = validate_paginated(api_client.list_roster_slots(
            TD, params={"registration_id": r2["id"]}))[0]
        assert [s for s in data if s["player_id"] == p1["id"]] == [], \
            "no second slot may exist for p1 on r2"


class TestRegistrationRbac:

    def test_team_manager_cannot_review_own_registration(self):
        """PRD §2.1: "A request whose role is recognized but not permitted
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)
        per the endpoint's authorized role list in §4."
        PRD §4: "| POST | /api/registrations/{id}/review | Eligibility
        decision on a SUBMITTED or APPEALED registration |
        TournamentDirector |"

        Design: Corner/rbac/team_manager_cannot_review_own_registration
        """
        ctx = setup_registration_open_tournament(
            "RBAC2 Cup",
            team_specs=[{"handle": "p1", "dob": "2000-01-01",
                         "team_name": "Alpha", "rank": 100,
                         "review": None}])
        reg = ctx["registrations"][0]
        resp = api_client.review_registration(
            reg["id"], {"action": "APPROVE"},
            make_team_manager_headers(reg["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_registration(reg["id"])["status"] == "SUBMITTED"

    def test_team_manager_foreign_roster_op_returns_ownership_mismatch(self):
        """PRD §2.1: "A manager submitting, appealing, or editing roster
        slots operates on the registration whose `id` equals `X-User-ID`"
        PRD §2.1: "A request whose role is permitted but whose identity does
        not own the target resource, where the resource is one for which
        ownership is meaningful, is rejected with `ERR_OWNERSHIP_MISMATCH`
        (HTTP 403)."

        Design: Corner/rbac/team_manager_foreign_roster_op_returns_ownership_mismatch
        """
        ctx = setup_registration_open_tournament(
            "Own Cup", team_count=2,
            team_specs=[
                {"handle": "p1", "dob": "2000-01-01", "team_name": "Alpha",
                 "rank": 100, "submit": False},
                {"handle": "p2", "dob": "2000-02-02", "team_name": "Beta",
                 "rank": 80, "submit": False},
            ])
        r1, r2 = ctx["registrations"]
        p2 = ctx["players"][1]
        resp = api_client.create_roster_slot(
            {"registration_id": r1["id"], "player_id": p2["id"],
             "slot_role": "STARTER"},
            make_team_manager_headers(r2["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        data = validate_paginated(api_client.list_roster_slots(
            TD, params={"registration_id": r1["id"]}))[0]
        assert len(data) == 1, "no slot may be added to another manager's registration"


class TestRegistrationListing:

    def test_registrations_list_pagination_and_filter(self):
        """PRD §2.3: "List endpoints accept two query parameters: `limit` and
        `offset`. `limit` defaults to 10, must be at least 1, and may not
        exceed 100. `offset` defaults to 0."
        PRD §2.3: "Responses for list endpoints carry `limit`, `offset`,
        `total_count`, and `has_more` inside `meta`, where `total_count` is
        the number of matching records before pagination and `has_more`
        indicates whether additional records exist beyond the current page."
        PRD §2.3: "Most list endpoints sort deterministically by `created_at`
        ascending."

        Design: Corner/endpoints/registrations_list_pagination_and_filter
        """
        tournament = create_tournament("Page Cup")
        players = [create_player(f"pg{i}", f"2000-01-0{i}", "NA")
                   for i in (1, 2, 3)]
        reg_ids = []
        # Distinct created_at instants pin the deterministic created_at order.
        for i, (name, player) in enumerate(
                zip(["Alpha", "Beta", "Gamma"], players)):
            set_clock(f"2026-08-01T00:00:0{i}Z")
            reg = create_registration(tournament["id"], name, player["id"],
                                      rank=100 - i * 10)
            reg_ids.append(reg["id"])

        resp = api_client.list_registrations(
            TD, params={"tournament_id": tournament["id"]})
        body = resp.json()
        assert body["response_type"] == "array"
        data, meta = validate_paginated(resp)
        assert [r["id"] for r in data] == reg_ids
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0

        data2, meta2 = validate_paginated(api_client.list_registrations(
            TD, params={"tournament_id": tournament["id"], "limit": 2}))
        assert [r["id"] for r in data2] == reg_ids[:2]
        assert meta2["total_count"] == 3 and meta2["has_more"] is True

        data3, meta3 = validate_paginated(api_client.list_registrations(
            TD, params={"tournament_id": tournament["id"], "limit": 2,
                        "offset": 2}))
        assert [r["id"] for r in data3] == reg_ids[2:]
        assert meta3["has_more"] is False
