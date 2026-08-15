"""Coordination meetings: half-open room-window arithmetic, state gates,
commitment trade matching, and list pagination defaults."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adjourn_meeting,
    create_in_session_meeting,
    create_meeting,
    create_meeting_payload,
    create_partner,
    create_project,
    set_clock,
    setup_assigned_clash,
    start_meeting,
    validate_error,
    validate_paginated,
    validate_success,
)

VDC = TEST_USERS["vdc_manager_headers"]
COORD = TEST_USERS["bim_coordinator_headers"]


class TestRoomWindowArithmetic:
    def test_meeting_room_half_open_adjacency_rules(self, api):
        """PRD §3.5: "Meeting intervals are half-open: the room is occupied
        from the start instant up to but not including the end instant. A new
        booking conflicts with an existing `SCHEDULED` or `IN_SESSION` meeting
        on the same `project_id` and `room_id` when the new meeting starts
        before the existing one ends and the existing one starts before the
        new one ends; the conflict is rejected with
        `ERR_ROOM_WINDOW_CONFLICT`. Adjacency is explicitly not a conflict —
        a meeting may begin at the exact instant another ends"

        Design: Difficulty/resource_temporal_overlap/meeting_room_half_open_adjacency_rules
        """
        project = create_project("TO1")
        mta = create_meeting(project["id"], room_id="RM-1",
                             starts_at="2026-08-10T09:00:00Z",
                             ends_at="2026-08-10T10:00:00Z")
        assert mta["status"] == "SCHEDULED"

        # Adjacent booking (starts exactly when the existing one ends):
        # allowed with zero gap.
        mtb = validate_success(api.create_coordination_meeting(
            project["id"],
            create_meeting_payload(room_id="RM-1",
                                   starts_at="2026-08-10T10:00:00Z",
                                   ends_at="2026-08-10T11:00:00Z"),
            COORD), 201)
        assert mtb["status"] == "SCHEDULED"
        assert mtb["room_id"] == "RM-1"

        # Strict overlap: rejected.
        overlap = api.create_coordination_meeting(
            project["id"],
            create_meeting_payload(room_id="RM-1",
                                   starts_at="2026-08-10T09:30:00Z",
                                   ends_at="2026-08-10T10:30:00Z"),
            COORD)
        validate_error(overlap, ApiErrorId.ERR_ROOM_WINDOW_CONFLICT)

        # The same clock window in a different room is a different resource.
        mtd = validate_success(api.create_coordination_meeting(
            project["id"],
            create_meeting_payload(room_id="RM-2",
                                   starts_at="2026-08-10T09:30:00Z",
                                   ends_at="2026-08-10T10:30:00Z"),
            COORD), 201)
        assert mtd["room_id"] == "RM-2"

    def test_adjourned_meeting_frees_its_room(self, api):
        """PRD §3.5: "Adjacency is explicitly not a conflict — a meeting may
        begin at the exact instant another ends — and an `ADJOURNED` meeting
        frees its room."

        Design: Difficulty/resource_temporal_overlap/meeting_room_half_open_adjacency_rules
        """
        project = create_project("TO1B")
        # Window covers the default logical clock so the meeting can start.
        meeting = create_meeting(project["id"], room_id="RM-1")
        start_meeting(meeting["id"])
        adjourned = adjourn_meeting(meeting["id"])
        assert adjourned["status"] == "ADJOURNED"

        # The identical window in the same room is bookable again.
        rebooked = validate_success(api.create_coordination_meeting(
            project["id"], create_meeting_payload(room_id="RM-1"), COORD), 201)
        assert rebooked["status"] == "SCHEDULED"


class TestMeetingStateGates:
    def test_meeting_window_and_state_gates(self, api):
        """PRD §3.5: "A `BIMCoordinator` schedules a **CoordinationMeeting**
        with a `room_id`, a `starts_at`, and an `ends_at` strictly after the
        start (otherwise `ERR_INVALID_TIME_RANGE`)."
        PRD §3.5: "Starting a meeting requires `SCHEDULED`
        (`ERR_MEETING_NOT_SCHEDULED`) and a logical clock inside the booked
        window — on or after `starts_at` and strictly before `ends_at`, else
        `ERR_MEETING_WINDOW_NOT_ACTIVE`; the meeting becomes `IN_SESSION`.
        Adjourning requires `IN_SESSION` (`ERR_MEETING_NOT_IN_SESSION`)"
        PRD §3.5: "commitments recorded at any other time fail with
        `ERR_MEETING_NOT_IN_SESSION`"

        Design: Corner/state_machines/meeting_window_and_state_gates
        """
        # An ASSIGNED clash exists for the post-adjourn commitment probe.
        ws = setup_assigned_clash("SM8", overlap_mm=10.0)
        pid = ws["project"]["id"]

        # Reversed window at creation: ends_at must be strictly after
        # starts_at.
        e0 = api.create_coordination_meeting(
            pid, create_meeting_payload(room_id="RM-9",
                                        starts_at="2026-08-10T10:00:00Z",
                                        ends_at="2026-08-10T09:00:00Z"),
            COORD)
        validate_error(e0, ApiErrorId.ERR_INVALID_TIME_RANGE)

        meeting = create_meeting(pid, room_id="RM-1",
                                 starts_at="2026-08-10T09:00:00Z",
                                 ends_at="2026-08-10T10:00:00Z")

        # The default clock (2026-08-01) is outside the booked window.
        e1 = api.start_meeting(meeting["id"], COORD)
        validate_error(e1, ApiErrorId.ERR_MEETING_WINDOW_NOT_ACTIVE)

        # Adjourn from SCHEDULED.
        e2 = api.adjourn_meeting(meeting["id"], COORD)
        validate_error(e2, ApiErrorId.ERR_MEETING_NOT_IN_SESSION)

        # Inside the window, the start succeeds.
        set_clock("2026-08-10T09:30:00Z")
        started = validate_success(api.start_meeting(meeting["id"], COORD))
        assert started["status"] == "IN_SESSION"

        # Second start: no longer SCHEDULED.
        e3 = api.start_meeting(meeting["id"], COORD)
        validate_error(e3, ApiErrorId.ERR_MEETING_NOT_SCHEDULED)

        adjourned = validate_success(api.adjourn_meeting(meeting["id"], COORD))
        assert adjourned["status"] == "ADJOURNED"

        # Commitments require IN_SESSION.
        e4 = api.create_commitment(
            meeting["id"],
            {"clash_issue_id": ws["clash"]["id"],
             "committed_by_partner_id": ws["partner"]["id"],
             "due_at": "2026-08-11T00:00:00Z"},
            COORD)
        validate_error(e4, ApiErrorId.ERR_MEETING_NOT_IN_SESSION)


class TestCommitmentRules:
    def test_commitment_trade_mismatch_rejected(self, api):
        """PRD §3.5: "the `committed_by_partner_id`, which must equal that
        clash's `assigned_trade_partner_id` or the record is rejected with
        `ERR_COMMITMENT_TRADE_MISMATCH`"

        Design: Corner/validations/commitment_trade_mismatch_rejected
        """
        ws = setup_assigned_clash("V7", overlap_mm=10.0)
        p2 = create_partner(ws["project"]["id"], company_name="MechCo",
                            discipline="MECHANICAL", hourly_rate_cents=10000,
                            coordination_budget_hours=50.0,
                            software_platform="TEKLA")
        meeting = create_in_session_meeting(ws["project"]["id"])

        # Both partners exist in the project; only the assigned one matches.
        resp = api.create_commitment(
            meeting["id"],
            {"clash_issue_id": ws["clash"]["id"],
             "committed_by_partner_id": p2["id"],
             "due_at": "2026-08-11T00:00:00Z"},
            COORD)
        validate_error(resp, ApiErrorId.ERR_COMMITMENT_TRADE_MISMATCH)

        _, meta = validate_paginated(api.list_commitments(
            COORD, params={"meeting_id": meeting["id"]}))
        assert meta["total_count"] == 0, "no commitment persisted"


class TestMeetingListing:
    def test_meeting_list_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned: it defaults to 10 when omitted, accepts a minimum of 1, and
        is capped at a maximum of 100. The `offset` parameter sets the number
        of items skipped and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/meeting_list_pagination_defaults
        """
        project = create_project("E7")
        for i in range(1, 12):
            create_meeting(project["id"], room_id=f"R{i:02d}",
                           starts_at="2026-08-10T09:00:00Z",
                           ends_at="2026-08-10T10:00:00Z")

        data, meta = validate_paginated(api.list_coordination_meetings(
            VDC, params={"project_id": project["id"]}))
        assert len(data) == 10, "default limit is 10"
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 11
        assert meta["has_more"] is True

        data2, meta2 = validate_paginated(api.list_coordination_meetings(
            VDC, params={"project_id": project["id"], "offset": 10}))
        assert len(data2) == 1
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 11
