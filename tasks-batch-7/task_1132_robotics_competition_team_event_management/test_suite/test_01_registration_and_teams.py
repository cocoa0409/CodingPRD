"""Registration, screening, and team lifecycle tests (PRD §3.1-§3.2)."""
import pytest

from test_helpers import (
    ED,
    RO,
    SO,
    ApiErrorId,
    add_cleared_person,
    add_person,
    assert_frc_event,
    assert_person,
    assert_team,
    create_event,
    create_person_payload,
    create_screening_record_payload,
    create_team_payload,
    get_event,
    make_team_lead_headers,
    open_registration,
    register_and_confirm_team,
    set_clock,
    setup_confirmed_teams,
    setup_event_registration_open,
    submit_screening,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import NON_EXISTENT_UUID, TEST_USERS, api_client

HEAD_REFEREE = TEST_USERS["head_referee_headers"]


class TestEventCreation:
    def test_event_create_minimal_returns_201(self):
        """PRD §3.1: "The new event is born in `SETUP` status with `posture`
        equal to `OPEN` and all three computed counters (`registered_team_count`,
        `cleared_mentor_count`, `outstanding_violation_count`) at zero. The
        server returns the freshly created event with HTTP 201."
        PRD §2.4: "`version` (integer starting at 1, incremented by exactly 1
        on every write that mutates the entity)".

        Design: Corner/entities/frc_event_create_minimal_returns_201
        """
        resp = api_client.create_event(
            {
                "event_code": "E1",
                "event_name": "E1",
                "season_year": 2026,
                "start_date": "2026-04-01T08:00:00Z",
                "end_date": "2026-04-04T18:00:00Z",
                "team_capacity": 40,
                "match_cycle_minutes": 7,
                "field_count": 1,
                "championship_slots": 2,
            },
            ED,
        )
        event = validate_success(resp, expected_status=201)
        assert_frc_event(event)
        assert event["status"] == "SETUP"
        assert event["posture"] == "OPEN"
        assert event["registered_team_count"] == 0
        assert event["cleared_mentor_count"] == 0
        assert event["outstanding_violation_count"] == 0
        assert event["version"] == 1

    def test_get_event_by_id_returns_404_for_missing(self):
        """PRD §2.7: "Path-parameter existence — every id in the path must
        resolve to a real entity nested under its parent. The specific error
        varies by which segment failed: `ERR_EVENT_NOT_FOUND` ...".

        Design: Corner/entities/get_event_by_id_returns_404_for_missing
        """
        resp = api_client.get_event(NON_EXISTENT_UUID, ED)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND)


class TestTeamRegistration:
    def test_duplicate_team_number_rejected(self):
        """PRD §3.2: "A duplicate `team_number` is rejected with
        `ERR_DUPLICATE_TEAM_NUMBER` (HTTP 409)."

        Design: Corner/entities/team_create_duplicate_team_number_rejected
        """
        event = setup_event_registration_open()
        resp1 = api_client.create_team(event["id"], create_team_payload(team_number=1001), RO)
        validate_success(resp1, expected_status=201)
        resp2 = api_client.create_team(event["id"], create_team_payload(team_number=1001), RO)
        validate_error(resp2, ApiErrorId.ERR_DUPLICATE_TEAM_NUMBER)

    def test_confirm_nonexistent_team_returns_team_not_found(self):
        """PRD §2.7: "Path-parameter existence — every id in the path must
        resolve to a real entity nested under its parent." The team segment
        failure yields `ERR_TEAM_NOT_FOUND` (priority 3, before state checks).

        Design: Difficulty/priority_pair_validation_conflict/existence_vs_state_on_team_confirm
        """
        event = setup_event_registration_open()
        resp = api_client.confirm_team(event["id"], NON_EXISTENT_UUID, RO)
        validate_error(resp, ApiErrorId.ERR_TEAM_NOT_FOUND)

    def test_confirm_nonexistent_team_wins_over_frozen_posture(self):
        """PRD §2.7: "A `TeamLead` calling confirm against a team that does not
        exist gets `ERR_TEAM_NOT_FOUND`, not `ERR_EVENT_FROZEN`, even when the
        event is frozen."

        Design: Difficulty/priority_pair_validation_conflict/existence_vs_state_on_team_confirm
        """
        ctx = setup_confirmed_teams(num_teams=1)
        event = ctx["event"]
        team_id = ctx["teams"][0]["team"]["id"]
        opener = ctx["teams"][0]["mentor"]
        # Three unresolved CRITICAL violations push posture to FROZEN (§2.6).
        for i in range(3):
            resp = api_client.create_violation(
                event["id"], team_id,
                {
                    "source_kind": "FIELD_SAFETY",
                    "severity": "CRITICAL",
                    "description": f"critical {i}",
                    "opened_by_person_id": opener["id"],
                },
                HEAD_REFEREE,
            )
            validate_success(resp, expected_status=201)
        assert get_event(event["id"])["posture"] == "FROZEN"
        resp = api_client.confirm_team(event["id"], NON_EXISTENT_UUID, RO)
        validate_error(resp, ApiErrorId.ERR_TEAM_NOT_FOUND)


class TestCapacityBoundary:
    def test_confirm_at_capacity_returns_event_full(self):
        """PRD §3.2: "Confirmation requires the event's `registered_team_count`
        to be strictly less than `team_capacity` (else `ERR_EVENT_FULL`,
        HTTP 409)".

        Design: Difficulty/boundary_precision_check/registered_team_count_boundary
        """
        event = setup_event_registration_open(team_capacity=2)
        register_and_confirm_team(event["id"], 2001)
        register_and_confirm_team(event["id"], 2002)
        assert get_event(event["id"])["registered_team_count"] == 2
        # Third team reaches ROSTER_SUBMITTED but cannot be confirmed.
        team = validate_success(
            api_client.create_team(event["id"], create_team_payload(team_number=2003), RO),
            expected_status=201,
        )
        mentor = add_cleared_person(event["id"], team["id"], "MENTOR", "m2003@example.com")
        add_person(event["id"], team["id"], "STUDENT", "s2003@example.com")
        validate_success(api_client.mark_payment_cleared(event["id"], team["id"], RO))
        validate_success(
            api_client.submit_roster(event["id"], team["id"], make_team_lead_headers(mentor["id"]))
        )
        resp = api_client.confirm_team(event["id"], team["id"], RO)
        validate_error(resp, ApiErrorId.ERR_EVENT_FULL)

    def test_confirm_below_capacity_succeeds_and_increments(self):
        """PRD §3.2: "Confirmation requires the event's `registered_team_count`
        to be strictly less than `team_capacity`" and "On success,
        `registered_team_count` increments by 1" — the boundary is inclusive
        below capacity.

        Design: Difficulty/boundary_precision_check/registered_team_count_boundary
        """
        event = setup_event_registration_open(team_capacity=2)
        register_and_confirm_team(event["id"], 2001)
        assert get_event(event["id"])["registered_team_count"] == 1
        register_and_confirm_team(event["id"], 2002)
        event = get_event(event["id"])
        assert event["registered_team_count"] == 2


class TestConfirmPostureGate:
    def test_confirm_rejected_when_posture_restricted(self):
        """PRD §3.2: "Confirmation requires the event's `registered_team_count`
        to be strictly less than `team_capacity` (else `ERR_EVENT_FULL`,
        HTTP 409) and requires posture to be `OPEN` — under `RESTRICTED` or
        `FROZEN` the call is rejected with `ERR_EVENT_FROZEN`."

        Design: Difficulty/cross_entity_state_dependency/team_confirm_depends_on_event_posture_open
        """
        event = setup_event_registration_open()
        # Team A drives posture to RESTRICTED via one open CRITICAL violation.
        entry_a = register_and_confirm_team(event["id"], 3001)
        # Team B reaches ROSTER_SUBMITTED while posture is still OPEN.
        team_b = validate_success(
            api_client.create_team(event["id"], create_team_payload(team_number=3002), RO),
            expected_status=201,
        )
        mentor_b = add_cleared_person(event["id"], team_b["id"], "MENTOR", "m3002@example.com")
        add_person(event["id"], team_b["id"], "STUDENT", "s3002@example.com")
        validate_success(api_client.mark_payment_cleared(event["id"], team_b["id"], RO))
        validate_success(
            api_client.submit_roster(event["id"], team_b["id"], make_team_lead_headers(mentor_b["id"]))
        )
        validate_success(
            api_client.create_violation(
                event["id"], entry_a["team"]["id"],
                {
                    "source_kind": "FIELD_SAFETY",
                    "severity": "CRITICAL",
                    "description": "open critical",
                    "opened_by_person_id": entry_a["mentor"]["id"],
                },
                HEAD_REFEREE,
            ),
            expected_status=201,
        )
        assert get_event(event["id"])["posture"] == "RESTRICTED"
        resp = api_client.confirm_team(event["id"], team_b["id"], RO)
        validate_error(resp, ApiErrorId.ERR_EVENT_FROZEN)

    def test_confirm_rejected_when_posture_frozen(self):
        """PRD §3.2: "under `RESTRICTED` or `FROZEN` the call is rejected with
        `ERR_EVENT_FROZEN`."

        Design: Difficulty/cross_entity_state_dependency/team_confirm_depends_on_event_posture_open
        """
        event = setup_event_registration_open()
        entry_a = register_and_confirm_team(event["id"], 3001)
        team_b = validate_success(
            api_client.create_team(event["id"], create_team_payload(team_number=3002), RO),
            expected_status=201,
        )
        mentor_b = add_cleared_person(event["id"], team_b["id"], "MENTOR", "m3002@example.com")
        add_person(event["id"], team_b["id"], "STUDENT", "s3002@example.com")
        validate_success(api_client.mark_payment_cleared(event["id"], team_b["id"], RO))
        validate_success(
            api_client.submit_roster(event["id"], team_b["id"], make_team_lead_headers(mentor_b["id"]))
        )
        for i in range(3):
            validate_success(
                api_client.create_violation(
                    event["id"], entry_a["team"]["id"],
                    {
                        "source_kind": "FIELD_SAFETY",
                        "severity": "CRITICAL",
                        "description": f"critical {i}",
                        "opened_by_person_id": entry_a["mentor"]["id"],
                    },
                    HEAD_REFEREE,
                ),
                expected_status=201,
            )
        assert get_event(event["id"])["posture"] == "FROZEN"
        resp = api_client.confirm_team(event["id"], team_b["id"], RO)
        validate_error(resp, ApiErrorId.ERR_EVENT_FROZEN)


class TestWithdraw:
    def test_confirm_then_withdraw_restores_registered_count(self):
        """PRD §3.2: confirm — "On success, `registered_team_count` increments
        by 1"; withdraw from CONFIRMED — "`registered_team_count` decrements
        by 1". The pair must restore the pre-confirm count.

        Design: Difficulty/compensating_invariant/registered_team_count_invariant_on_withdraw
        """
        event = setup_event_registration_open(team_capacity=10)
        entry = register_and_confirm_team(event["id"], 4001)
        pre_count = get_event(event["id"])["registered_team_count"]
        team_b = validate_success(
            api_client.create_team(event["id"], create_team_payload(team_number=4002), RO),
            expected_status=201,
        )
        mentor_b = add_cleared_person(event["id"], team_b["id"], "MENTOR", "m4002@example.com")
        add_person(event["id"], team_b["id"], "STUDENT", "s4002@example.com")
        validate_success(api_client.mark_payment_cleared(event["id"], team_b["id"], RO))
        validate_success(
            api_client.submit_roster(event["id"], team_b["id"], make_team_lead_headers(mentor_b["id"]))
        )
        validate_success(api_client.confirm_team(event["id"], team_b["id"], RO))
        assert get_event(event["id"])["registered_team_count"] == pre_count + 1
        validate_success(
            api_client.withdraw_team(event["id"], team_b["id"], make_team_lead_headers(mentor_b["id"]))
        )
        assert get_event(event["id"])["registered_team_count"] == pre_count

    def test_withdraw_pending_payment_has_no_side_effects(self):
        """PRD §3.2: "From `PENDING_PAYMENT`, withdrawal has no preconditions
        and no side effects beyond the team's own state change."

        Design: Difficulty/compensating_invariant/registered_team_count_invariant_on_withdraw
        """
        event = setup_event_registration_open()
        team = validate_success(
            api_client.create_team(event["id"], create_team_payload(team_number=4003), RO),
            expected_status=201,
        )
        mentor = add_person(event["id"], team["id"], "MENTOR", "m4003@example.com")
        pre_count = get_event(event["id"])["registered_team_count"]
        withdrawn = validate_success(
            api_client.withdraw_team(event["id"], team["id"], make_team_lead_headers(mentor["id"]))
        )
        assert withdrawn["registration_status"] == "WITHDRAWN"
        assert get_event(event["id"])["registered_team_count"] == pre_count

    def test_withdrawn_team_rejects_further_transitions(self):
        """PRD §3.2: "Withdrawal is the team-initiated exit." PRD §2.7: "the
        target entity must be in the `from` state the transition requires; if
        it is already in a terminal state, the more specific
        `ERR_ALREADY_TERMINAL` is used instead."

        Design: Corner/state_machines/team_withdraw_terminal_lockdown
        """
        event = setup_event_registration_open()
        team = validate_success(
            api_client.create_team(event["id"], create_team_payload(team_number=4004), RO),
            expected_status=201,
        )
        mentor = add_person(event["id"], team["id"], "MENTOR", "m4004@example.com")
        validate_success(
            api_client.withdraw_team(event["id"], team["id"], make_team_lead_headers(mentor["id"]))
        )
        resp = api_client.confirm_team(event["id"], team["id"], RO)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL]
        )


class TestImmediateConsistency:
    def test_confirm_visible_immediately(self):
        """PRD §3.2: confirm "moves it `ROSTER_SUBMITTED → CONFIRMED`" and "On
        success, `registered_team_count` increments by 1 and
        `cleared_mentor_count` is recomputed."

        Design: Corner/consistency_model/immediate_visibility_after_transition
        """
        event = setup_event_registration_open()
        team = validate_success(
            api_client.create_team(event["id"], create_team_payload(team_number=5001), RO),
            expected_status=201,
        )
        mentor = add_cleared_person(event["id"], team["id"], "MENTOR", "m5001@example.com")
        add_person(event["id"], team["id"], "STUDENT", "s5001@example.com")
        validate_success(api_client.mark_payment_cleared(event["id"], team["id"], RO))
        validate_success(
            api_client.submit_roster(event["id"], team["id"], make_team_lead_headers(mentor["id"]))
        )
        confirmed = validate_success(api_client.confirm_team(event["id"], team["id"], RO))
        assert confirmed["registration_status"] == "CONFIRMED"
        reread = validate_success(api_client.get_team(event["id"], team["id"], RO))
        assert reread["registration_status"] == "CONFIRMED"
        assert get_event(event["id"])["registered_team_count"] == 1


class TestDisqualify:
    def test_disqualify_without_grounds_rejected(self):
        """PRD §3.2: "A `CONFIRMED` team may be disqualified only when at least
        one `ComplianceViolation` exists against it with `severity` equal to
        `CRITICAL` and `resolution_status` not equal to `RESOLVED`; otherwise
        the call is rejected with `ERR_NO_GROUNDS` (HTTP 409)."

        Design: Corner/errors/err_no_grounds_disqualify
        """
        ctx = setup_confirmed_teams(num_teams=1)
        team = ctx["teams"][0]["team"]
        resp = api_client.disqualify_team(ctx["event"]["id"], team["id"], ED)
        validate_error(resp, ApiErrorId.ERR_NO_GROUNDS)


class TestScreening:
    def test_screening_expires_at_mentor_180_volunteer_90(self):
        """PRD §2.5: "When a `Person` is cleared, `screening_expires_at` is set
        to the clearance instant plus 180 days for `MENTOR` and `JUDGE`, and
        plus 90 days for `VOLUNTEER`."

        Design: Corner/entities/person_computed_screening_expires_at_mentor
        """
        from datetime import datetime, timedelta

        event = create_event()
        # No clock call: clearance happens at the PRD-stated default logical
        # clock instant (§2.9), so the expiry offsets are absolute.
        mentor = add_cleared_person(event["id"], None, "MENTOR", "exp-mentor@example.com")
        volunteer = add_cleared_person(event["id"], None, "VOLUNTEER", "exp-vol@example.com")
        base = datetime(2026, 5, 1, 0, 0, 0)  # PRD §2.9 default current_utc
        for person, days in ((mentor, 180), (volunteer, 90)):
            expected = base + timedelta(days=days)
            actual = datetime.fromisoformat(person["screening_expires_at"].replace("Z", "+00:00"))
            assert actual.replace(tzinfo=None) == expected, (
                f"{person['role_kind']} expiry must be clearance + {days} days: "
                f"expected {expected.isoformat()}, got {person['screening_expires_at']}"
            )

    def test_approve_with_missing_record_returns_404(self):
        """PRD §2.7: "Path-parameter existence — every id in the path must
        resolve to a real entity nested under its parent. The specific error
        varies by which segment failed: ... `ERR_RECORD_NOT_FOUND` ...".

        Design: Corner/state_machines/pending_person_cannot_be_approved_via_missing_record
        """
        event = create_event()
        person = add_person(event["id"], None, "MENTOR", "norec@example.com")
        person = validate_success(api_client.get_person(event["id"], person["id"], SO))
        resp = api_client.approve_screening(
            event["id"], person["id"], NON_EXISTENT_UUID, person["version"], SO,
        )
        validate_error(resp, ApiErrorId.ERR_RECORD_NOT_FOUND)

    def test_approve_with_stale_person_version_returns_412(self):
        """PRD §2.4: "Approving a screening record requires
        `expected_person_version` matching the current `Person.version`; if the
        person's version has advanced since the caller last observed it, the
        call is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/occ_stale_version_returns_412
        """
        event = create_event()
        person = add_person(event["id"], None, "MENTOR", "stale@example.com")
        record = submit_screening(event["id"], person["id"])
        person = validate_success(api_client.get_person(event["id"], person["id"], SO))
        # The record creation moved the person PENDING -> IN_REVIEW (a write),
        # so the pre-submission version is now stale.
        stale_version = person["version"] - 1
        resp = api_client.approve_screening(
            event["id"], person["id"], record["id"], stale_version, SO,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
