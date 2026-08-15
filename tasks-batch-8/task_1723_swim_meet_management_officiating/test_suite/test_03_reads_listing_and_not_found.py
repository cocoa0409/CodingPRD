"""Existence validation (dedicated 404 per resource type), list pagination with
filters, and the heat-sheet computed read."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    add_entry,
    add_event,
    add_swimmer,
    add_team,
    create_open_meet,
    lanes_for_event,
    seed_meet,
    validate_error,
    validate_paginated,
    validate_success,
    verify_entry,
)

DIRECTOR = TEST_USERS["meet_director_headers"]


class TestNotFoundSweep:
    """PRD §2.9: "Each resource type carries a dedicated not-found error:
    `ERR_MEET_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_SWIMMER_NOT_FOUND`,
    `ERR_EVENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_RELAY_TEAM_NOT_FOUND`,
    `ERR_LANE_ASSIGNMENT_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`,
    `ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND`, `ERR_DISQUALIFICATION_NOT_FOUND`, and
    `ERR_RECORD_NOT_FOUND` (all HTTP 404).\""""

    def test_meet_not_found(self, api):
        """PRD §2.9: "Each resource type carries a dedicated not-found error: `ERR_MEET_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_SWIMMER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_RELAY_TEAM_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND`, `ERR_DISQUALIFICATION_NOT_FOUND`, and `ERR_RECORD_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/meet_not_found_returns_404
        """
        resp = api.get_meet(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_MEET_NOT_FOUND)

    def test_team_not_found(self, api):
        """PRD §2.9: "Each resource type carries a dedicated not-found error: `ERR_MEET_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_SWIMMER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_RELAY_TEAM_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND`, `ERR_DISQUALIFICATION_NOT_FOUND`, and `ERR_RECORD_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/team_not_found_returns_404
        """
        resp = api.get_team(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_TEAM_NOT_FOUND)

    def test_swimmer_not_found(self, api):
        """PRD §2.9: "Each resource type carries a dedicated not-found error: `ERR_MEET_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_SWIMMER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_RELAY_TEAM_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND`, `ERR_DISQUALIFICATION_NOT_FOUND`, and `ERR_RECORD_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/swimmer_not_found_returns_404
        """
        resp = api.get_swimmer(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_SWIMMER_NOT_FOUND)

    def test_event_not_found(self, api):
        """PRD §2.9: "Each resource type carries a dedicated not-found error: `ERR_MEET_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_SWIMMER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_RELAY_TEAM_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND`, `ERR_DISQUALIFICATION_NOT_FOUND`, and `ERR_RECORD_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/event_not_found_returns_404
        """
        resp = api.get_event(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND)

    def test_entry_not_found(self, api):
        """PRD §2.9: "Each resource type carries a dedicated not-found error: `ERR_MEET_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_SWIMMER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_RELAY_TEAM_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND`, `ERR_DISQUALIFICATION_NOT_FOUND`, and `ERR_RECORD_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/entry_not_found_returns_404
        """
        resp = api.get_entry(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_ENTRY_NOT_FOUND)

    def test_relay_team_not_found(self, api):
        """PRD §2.9: "Each resource type carries a dedicated not-found error: `ERR_MEET_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_SWIMMER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_RELAY_TEAM_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND`, `ERR_DISQUALIFICATION_NOT_FOUND`, and `ERR_RECORD_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/relay_team_not_found_returns_404
        """
        resp = api.get_relay_team(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_RELAY_TEAM_NOT_FOUND)

    def test_lane_assignment_not_found(self, api):
        """PRD §2.9: "Each resource type carries a dedicated not-found error: `ERR_MEET_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_SWIMMER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_RELAY_TEAM_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND`, `ERR_DISQUALIFICATION_NOT_FOUND`, and `ERR_RECORD_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/lane_assignment_not_found_returns_404
        """
        resp = api.get_lane_assignment(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_LANE_ASSIGNMENT_NOT_FOUND)

    def test_official_not_found(self, api):
        """PRD §2.9: "Each resource type carries a dedicated not-found error: `ERR_MEET_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_SWIMMER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_RELAY_TEAM_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND`, `ERR_DISQUALIFICATION_NOT_FOUND`, and `ERR_RECORD_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/official_not_found_returns_404
        """
        resp = api.get_official(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_OFFICIAL_NOT_FOUND)

    def test_official_assignment_not_found(self, api):
        """PRD §2.9: "Each resource type carries a dedicated not-found error: `ERR_MEET_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_SWIMMER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_RELAY_TEAM_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND`, `ERR_DISQUALIFICATION_NOT_FOUND`, and `ERR_RECORD_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/official_assignment_not_found_returns_404
        """
        resp = api.get_official_assignment(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND)

    def test_disqualification_not_found(self, api):
        """PRD §2.9: "Each resource type carries a dedicated not-found error: `ERR_MEET_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_SWIMMER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_RELAY_TEAM_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND`, `ERR_DISQUALIFICATION_NOT_FOUND`, and `ERR_RECORD_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/disqualification_not_found_returns_404
        """
        resp = api.get_disqualification(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_DISQUALIFICATION_NOT_FOUND)

    def test_record_not_found(self, api):
        """PRD §2.9: "Each resource type carries a dedicated not-found error: `ERR_MEET_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_SWIMMER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_RELAY_TEAM_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_OFFICIAL_ASSIGNMENT_NOT_FOUND`, `ERR_DISQUALIFICATION_NOT_FOUND`, and `ERR_RECORD_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/record_not_found_returns_404
        """
        resp = api.get_record(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_RECORD_NOT_FOUND)


class TestEntriesPagination:
    def test_entries_pagination_with_event_filter(self, api):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD §2.3: "entries by `event_id`, `swimmer_id`, `relay_team_id`, or
        `team_id`"

        Design: Corner/endpoints/entries_pagination_filtering
        """
        meet = create_open_meet(meet_name="PG1")
        team = add_team(meet["id"])
        swimmers = [add_swimmer(team["id"], full_name=f"Sw {c}",
                                birth_date=f"2014-03-1{c}")
                    for c in "123"]
        event = add_event(meet["id"], qualifying_time_cs=3000)
        for i, swimmer in enumerate(swimmers):
            add_entry(event["id"], swimmer["id"], team["id"],
                      seed_time_cs=2900 + i * 10)

        page1_resp = api.list_entries(
            DIRECTOR, params={"event_id": event["id"], "limit": 2, "offset": 0})
        page1, meta1 = validate_paginated(page1_resp)
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2

        page2_resp = api.list_entries(
            DIRECTOR, params={"event_id": event["id"], "limit": 2, "offset": 2})
        page2, meta2 = validate_paginated(page2_resp)
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert len(page2) == 1


class TestHeatSheet:
    def test_heat_sheet_groups_seeded_lanes_by_heat(self, api):
        """PRD §3.6: "The heat sheet itself is a computed read over this state,
        returning the `event_id` and a `heats` array grouping the event's
        seeded lane assignments by heat."
        PRD §3.6: "Within a heat, lanes are dealt middle-out: the fastest
        candidate receives the most preferred lane, and preference orders
        lanes by absolute distance from the pool's midpoint — the midpoint
        lying at half of one more than `lane_count` — with equidistant pairs
        resolved in favor of the lower-numbered lane. Under the default
        six-lane pool the preference order is lane 3, then 4, then 2, then 5,
        then 1, then 6; in an eight-lane pool it runs 4, 5, 3, 6, 2, 7, 1, 8."

        Design: Corner/endpoints/heat_sheet_computed_read
        """
        meet = create_open_meet(meet_name="HS1")
        team = add_team(meet["id"])
        swimmers = [add_swimmer(team["id"], full_name=f"Sw {c}",
                                birth_date=f"2014-03-1{c}")
                    for c in "123"]
        event = add_event(meet["id"], qualifying_time_cs=3000)
        entries = []
        for i, swimmer in enumerate(swimmers):
            entry = add_entry(event["id"], swimmer["id"], team["id"],
                              seed_time_cs=2900 + i * 10)
            verify_entry(entry["id"])
            entries.append(entry)
        seed_meet(meet["id"])

        sheet_resp = api.get_heat_sheet(event["id"], DIRECTOR)
        sheet = validate_success(sheet_resp)
        assert sheet["event_id"] == event["id"]
        # Three seeded entries in a six-lane pool form exactly one heat.
        assert isinstance(sheet["heats"], list)
        assert len(sheet["heats"]) == 1

        # Lane placement (middle-out, fastest first) is pinned by §3.6 and is
        # independently observable on the lane-assignment rows.
        placement = {lane["entry_id"]: (lane["heat_number"], lane["lane_number"])
                     for lane in lanes_for_event(event["id"])}
        assert placement[entries[0]["id"]] == (1, 3)  # fastest -> lane 3
        assert placement[entries[1]["id"]] == (1, 4)  # next -> lane 4
        assert placement[entries[2]["id"]] == (1, 2)  # next -> lane 2
