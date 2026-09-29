"""Contended resources: a team's calendar, a container's reseal buffer, a room's seats."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    factories,
    fixtures,
    make_tally_team_lead_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["elections_director_headers"]


def _setup_three_checked_out_batches():
    """Round one with every drawn batch of the round checked out of storage."""
    scenario = fixtures.setup_canvassed_contest()
    scenario["team"] = fixtures.create_bipartisan_team(scenario["election"]["id"])
    scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
    for drawn in scenario["audit_batches"]:
        physical = fixtures.read_batch(drawn["ballot_batch_id"])
        fixtures.retrieve_batch(
            drawn["id"], physical["id"], physical["current_seal_number"]
        )
    return scenario


def _open_session(audit_batch_id, tally_team_id, start_at, end_at):
    return api_client.create_manual_tally(
        factories.create_manual_tally_payload(
            audit_batch_id,
            tally_team_id,
            start_at,
            end_at,
            counted_votes={"ALVAREZ": 525, "BRENNAN": 475},
        ),
        make_tally_team_lead_headers(tally_team_id),
    )


class TestTeamCalendarIsHalfOpen:
    """A team's own sessions may touch at an instant but never overlap."""

    def test_a_session_starting_exactly_when_the_previous_one_ends_is_accepted(self):
        """PRD §3.5: "No other hand tally of the same team in `DRAFT`, `SUBMITTED` or
        `PENDING_ADJUDICATION` may overlap the requested window, compared as a half-open
        interval that includes its start and excludes its end, so two sessions that merely
        touch at a single instant are allowed and anything more is refused as a team
        session overlap."

        Design: Difficulty/resource_temporal_overlap/overlap_team_session_half_open_adjacent_allowed
        """
        scenario = _setup_three_checked_out_batches()
        team_id = scenario["team"]["id"]
        first, second, _third = scenario["audit_batches"]
        fixtures.open_manual_tally(
            first["id"],
            team_id,
            session_start_at="2026-11-05T09:00:00Z",
            session_end_at="2026-11-05T11:00:00Z",
            counted_votes={"ALVAREZ": 525, "BRENNAN": 475},
        )

        response = _open_session(
            second["id"], team_id, "2026-11-05T11:00:00Z", "2026-11-05T13:00:00Z"
        )

        adjacent = validate_success(response, 201)
        assert adjacent["status"] == "DRAFT"
        assertions.assert_same_instant(
            adjacent["session_start_at"], "2026-11-05T11:00:00Z", "session_start_at"
        )
        assert fixtures.read_audit_batch(second["id"])["tally_status"] == "IN_PROGRESS"

    def test_a_session_overlapping_the_team_s_own_booking_is_refused(self):
        """PRD §2.9: "The tally session does not overlap another live session of the same
        team — otherwise `ERR_TEAM_SESSION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/overlap_team_session_half_open_adjacent_allowed
        """
        scenario = _setup_three_checked_out_batches()
        team_id = scenario["team"]["id"]
        first, second, third = scenario["audit_batches"]
        fixtures.open_manual_tally(
            first["id"],
            team_id,
            session_start_at="2026-11-05T09:00:00Z",
            session_end_at="2026-11-05T11:00:00Z",
            counted_votes={"ALVAREZ": 525, "BRENNAN": 475},
        )
        validate_success(
            _open_session(
                second["id"], team_id, "2026-11-05T11:00:00Z", "2026-11-05T13:00:00Z"
            ),
            201,
        )

        response = _open_session(
            third["id"], team_id, "2026-11-05T12:00:00Z", "2026-11-05T14:00:00Z"
        )

        validate_error(response, ApiErrorId.ERR_TEAM_SESSION_OVERLAP.value, 409)
        _rows, meta = validate_paginated(
            api_client.list_manual_tallies(
                DIRECTOR, params={"tally_team_id": team_id, "limit": 100}
            )
        )
        assert meta["total_count"] == 2
        assert fixtures.read_audit_batch(third["id"])["tally_status"] == "NOT_STARTED"
        team = fixtures.read_tally_team(team_id)
        assert team["status"] == "READY"
        assert team["is_bipartisan"] is True


class TestContainerResealBuffer:
    """Two audits counting the same container are kept thirty minutes apart."""

    def _setup_shared_container_with_live_session(self):
        scenario = fixtures.setup_two_audits_sharing_first_batch()
        scenario["second_team"] = fixtures.create_bipartisan_team(
            scenario["election"]["id"],
            team_label="T-2",
            room_code="ROOM-B",
            dem_user_id="u-dem-2",
            rep_user_id="u-rep-2",
        )
        fixtures.open_manual_tally(
            scenario["rla_target"]["id"],
            scenario["team"]["id"],
            session_start_at="2026-11-05T09:00:00Z",
            session_end_at="2026-11-05T11:00:00Z",
            counted_votes={"ALVAREZ": 525, "BRENNAN": 475},
        )
        return scenario

    def test_a_session_twenty_nine_minutes_after_another_on_the_same_container_is_refused(
        self,
    ):
        """PRD §3.5: "No other live session on the same physical batch may fall inside the
        thirty-minute reseal buffer either: the two windows conflict when the new session
        starts before thirty minutes after the other ends **and** the other starts before
        thirty minutes after the new one ends, so a session may begin exactly thirty
        minutes after another on the same container ends, and anything tighter is refused
        as a batch session overlap."

        Design: Difficulty/resource_temporal_overlap/overlap_batch_session_closed_interval_with_reseal_buffer
        """
        scenario = self._setup_shared_container_with_live_session()

        response = _open_session(
            scenario["comparison_target"]["id"],
            scenario["second_team"]["id"],
            "2026-11-05T11:29:00Z",
            "2026-11-05T13:00:00Z",
        )

        validate_error(response, ApiErrorId.ERR_BATCH_SESSION_OVERLAP.value, 409)

    def test_a_session_exactly_thirty_minutes_later_is_accepted_on_the_same_container(
        self,
    ):
        """PRD §2.9: "The tally session does not fall inside the reseal buffer of another
        live session on the same physical batch — otherwise `ERR_BATCH_SESSION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/overlap_batch_session_closed_interval_with_reseal_buffer
        """
        scenario = self._setup_shared_container_with_live_session()

        response = _open_session(
            scenario["comparison_target"]["id"],
            scenario["second_team"]["id"],
            "2026-11-05T11:30:00Z",
            "2026-11-05T13:00:00Z",
        )

        accepted = validate_success(response, 201)
        assertions.assert_same_instant(
            accepted["session_start_at"], "2026-11-05T11:30:00Z", "session_start_at"
        )
        assert accepted["status"] == "DRAFT"
        drawn = fixtures.read_audit_batch(scenario["comparison_target"]["id"])
        assert drawn["tally_status"] == "IN_PROGRESS"
        assert drawn["retrieval_status"] == "PENDING_RETRIEVAL"
        physical = fixtures.read_batch(scenario["shared_batch"]["id"])
        assert physical["custody_status"] == "CHECKED_OUT"
        assert physical["open_checkout_count"] == 1
        assert fixtures.read_audit(scenario["comparison"]["audit"]["id"])["status"] == (
            "TALLYING"
        )
        assert fixtures.read_audit_round(scenario["comparison"]["round"]["id"])[
            "status"
        ] == "TALLYING"
        _rows, meta = validate_paginated(
            api_client.list_manual_tallies(
                DIRECTOR,
                params={"tally_team_id": scenario["second_team"]["id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 1


class TestSessionOverlapPrecedesDuplicateTally:
    """Both rules fire on a second session of the same batch; the earlier tier wins."""

    def test_overlapping_second_session_reports_the_team_overlap_not_the_duplicate(self):
        """PRD §2.9 lists the tally session overlap check as tier 31 and states "At most
        one live hand tally exists per drawn batch — otherwise `ERR_DUPLICATE_TALLY`" as
        tier 38, and: "The server evaluates the checks below in exactly this order and
        responds to the **first** violation it finds; no later check is evaluated."

        Design: Difficulty/priority_pair_validation_conflict/priority_team_session_overlap_precedes_duplicate_tally
        """
        scenario = fixtures.setup_draft_tally(
            session_start_at="2026-11-05T13:00:00Z",
            session_end_at="2026-11-05T15:00:00Z",
        )

        response = _open_session(
            scenario["target_audit_batch"]["id"],
            scenario["team"]["id"],
            "2026-11-05T14:00:00Z",
            "2026-11-05T16:00:00Z",
        )

        validate_error(response, ApiErrorId.ERR_TEAM_SESSION_OVERLAP.value, 409)

    def test_a_non_overlapping_second_session_reports_the_duplicate_tally(self):
        """PRD §3.5: "Finally at most one live tally may exist per drawn batch: a second
        one is refused as a duplicate tally while a tally in `DRAFT`, `SUBMITTED`,
        `PENDING_ADJUDICATION` or `CERTIFIED` exists for the same `audit_batch_id`."

        Design: Difficulty/priority_pair_validation_conflict/priority_team_session_overlap_precedes_duplicate_tally
        """
        scenario = fixtures.setup_draft_tally(
            session_start_at="2026-11-05T13:00:00Z",
            session_end_at="2026-11-05T15:00:00Z",
        )

        response = _open_session(
            scenario["target_audit_batch"]["id"],
            scenario["team"]["id"],
            "2026-11-05T15:30:00Z",
            "2026-11-05T17:30:00Z",
        )

        validate_error(response, ApiErrorId.ERR_DUPLICATE_TALLY.value, 409)
        _rows, meta = validate_paginated(
            api_client.list_manual_tallies(
                DIRECTOR,
                params={
                    "audit_batch_id": scenario["target_audit_batch"]["id"],
                    "limit": 100,
                },
            )
        )
        assert meta["total_count"] == 1
        surviving = fixtures.read_manual_tally(scenario["manual_tally"]["id"])
        assert surviving["status"] == "DRAFT"
        assertions.assert_same_instant(
            surviving["session_end_at"], "2026-11-05T15:00:00Z", "session_end_at"
        )
        assert fixtures.read_audit_batch(scenario["target_audit_batch"]["id"])[
            "tally_status"
        ] == "IN_PROGRESS"


class TestObserverRoomCapacityIsAggregate:
    """Two active credentials fill a room; the third is refused collectively."""

    def test_a_third_overlapping_credential_exceeds_the_room_capacity(self):
        """PRD §3.9: "Rooms are small: at most two `ACTIVE` credentials may overlap in the
        same `room_code`, counted over half-open windows that include their start and
        exclude their end, and a third overlapping credential is refused because the room
        capacity is exceeded — each of the three being perfectly legal on its own."

        Design: Difficulty/resource_temporal_overlap/overlap_observer_room_capacity_aggregate
        """
        scenario = fixtures.setup_canvassed_contest()
        occupants = fixtures.setup_room_at_observer_capacity(scenario["election"]["id"])
        assert [credential["status"] for credential in occupants] == ["ACTIVE", "ACTIVE"]

        response = api_client.create_observer_credential(
            factories.create_observer_credential_payload(
                scenario["election"]["id"],
                organization_name="State Press Pool",
                party_affiliation="PRESS",
                room_code="ROOM-A",
                access_start_at="2026-11-05T12:00:00Z",
                access_end_at="2026-11-05T16:00:00Z",
            ),
            DIRECTOR,
        )

        validate_error(
            response, ApiErrorId.ERR_OBSERVER_ROOM_CAPACITY_EXCEEDED.value, 409
        )

    def test_revoking_a_credential_releases_its_room_slot(self):
        """PRD §3.9: "Revocation sets `status` to `REVOKED`, which is terminal, records the
        reason, and releases the room-capacity slot the credential held for its window, so
        another credential may then be issued for the same room and overlapping window."

        Design: Difficulty/resource_temporal_overlap/overlap_observer_room_capacity_aggregate
        """
        scenario = fixtures.setup_canvassed_contest()
        first, second = fixtures.setup_room_at_observer_capacity(
            scenario["election"]["id"]
        )

        revoked = validate_success(
            api_client.revoke_observer_credential(
                first["id"],
                {"revoked_reason": "Organization withdrew its observer."},
                DIRECTOR,
            )
        )
        press = validate_success(
            api_client.create_observer_credential(
                factories.create_observer_credential_payload(
                    scenario["election"]["id"],
                    organization_name="State Press Pool",
                    party_affiliation="PRESS",
                    room_code="ROOM-A",
                    access_start_at="2026-11-05T12:00:00Z",
                    access_end_at="2026-11-05T16:00:00Z",
                ),
                DIRECTOR,
            ),
            201,
        )

        assert revoked["status"] == "REVOKED"
        assert revoked["revoked_reason"] == "Organization withdrew its observer."
        assert press["status"] == "ACTIVE"
        assert fixtures.read_observer_credential(second["id"])["status"] == "ACTIVE"

    def test_a_window_starting_at_another_windows_end_does_not_consume_a_slot(self):
        """PRD §3.9: "at most two `ACTIVE` credentials may overlap in the same `room_code`,
        counted over half-open windows that include their start and exclude their end".

        Design: Difficulty/resource_temporal_overlap/overlap_observer_room_capacity_aggregate
        """
        scenario = fixtures.setup_canvassed_contest()
        first, _second = fixtures.setup_room_at_observer_capacity(
            scenario["election"]["id"]
        )
        validate_success(
            api_client.revoke_observer_credential(
                first["id"],
                {"revoked_reason": "Organization withdrew its observer."},
                DIRECTOR,
            )
        )
        fixtures.create_observer_credential(
            scenario["election"]["id"],
            organization_name="State Press Pool",
            party_affiliation="PRESS",
            room_code="ROOM-A",
            access_start_at="2026-11-05T12:00:00Z",
            access_end_at="2026-11-05T16:00:00Z",
        )

        night_shift = validate_success(
            api_client.create_observer_credential(
                factories.create_observer_credential_payload(
                    scenario["election"]["id"],
                    organization_name="Night Shift Monitors",
                    party_affiliation="UNAFFILIATED",
                    room_code="ROOM-A",
                    access_start_at="2026-11-05T17:00:00Z",
                    access_end_at="2026-11-05T19:00:00Z",
                ),
                DIRECTOR,
            ),
            201,
        )

        assert night_shift["status"] == "ACTIVE"
        _active, active_meta = validate_paginated(
            api_client.list_observer_credentials(
                DIRECTOR,
                params={"room_code": "ROOM-A", "status": "ACTIVE", "limit": 100},
            )
        )
        assert active_meta["total_count"] == 3
        _all_rows, all_meta = validate_paginated(
            api_client.list_observer_credentials(
                DIRECTOR, params={"room_code": "ROOM-A", "limit": 100}
            )
        )
        assert all_meta["total_count"] == 4
