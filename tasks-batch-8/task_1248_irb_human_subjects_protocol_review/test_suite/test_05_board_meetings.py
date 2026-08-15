"""Board meetings: quorum count and composition, room occupation geometry,
failed-quorum recovery, agenda capacity and uniqueness, and meeting-level OCC
(PRD §2.4, §2.8, §3.6).
"""
from test_helpers import (
    ApiErrorId,
    add_agenda_item_ok,
    convene_meeting_ok,
    create_draft_protocol,
    drive_to_awaiting_full_board,
    get_agenda_item,
    get_meeting,
    get_success_data,
    make_chair_headers,
    register_chair,
    register_investigator,
    register_member,
    register_quorum_members,
    schedule_meeting,
    set_clock,
    setup_awaiting_full_board_scenario,
    submit_protocol_ok,
    unique_email,
    upload_consent,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

COORDINATOR = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _five_member_quorum():
    """Five ACTIVE members (all categories); quorum threshold floor(5/2)+1=3."""
    return register_quorum_members()


class TestQuorumThresholdBoundary:
    def test_quorum_threshold_exact_count_convenes(self, api):
        """PRD §3.6: "the roster size must reach the quorum threshold — one
        more than half the number of `ACTIVE` members, the half rounded down to
        a whole number — else `ERR_QUORUM_NOT_MET`". With five ACTIVE members
        the threshold is exactly 3 and a roster of exactly 3 convenes.

        Design: Difficulty/boundary_precision_check/quorum_threshold_exact_count_boundary
        """
        members = _five_member_quorum()
        meeting = schedule_meeting(room_id="R-QA", scheduled_at="2026-06-01T10:00:00Z")

        data = convene_meeting_ok(
            meeting["id"], members["chair"]["id"],
            [members["chair"]["id"], members["nonsci"]["id"], members["unaff"]["id"]],
        )
        assert data["status"] == "CONVENED"
        assert data["quorum_threshold"] == 3, (
            f"floor(5/2)+1 == 3, got {data['quorum_threshold']}"
        )

    def test_quorum_threshold_below_count_rejected(self, api):
        """PRD §3.6: "the roster size must reach the quorum threshold — one
        more than half the number of `ACTIVE` members, the half rounded down to
        a whole number — else `ERR_QUORUM_NOT_MET`". One below the threshold
        (2 of 3) is rejected and the meeting stays SCHEDULED.

        Design: Difficulty/boundary_precision_check/quorum_threshold_exact_count_boundary
        """
        members = _five_member_quorum()
        meeting = schedule_meeting(room_id="R-QB", scheduled_at="2026-06-02T10:00:00Z")

        resp = api.convene_meeting(
            meeting["id"],
            {"attendee_member_ids": [members["chair"]["id"], members["nonsci"]["id"]]},
            make_chair_headers(members["chair"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET)
        assert get_meeting(meeting["id"])["status"] == "SCHEDULED"


class TestQuorumComposition:
    def test_prisoner_branch_rejects_roster_without_representative(self, api):
        """PRD §3.6: "the composition must include at least one attendee of
        category `NON_SCIENTIST` and at least one of category `UNAFFILIATED`,
        with an additional requirement of at least one
        `PRISONER_REPRESENTATIVE` attendee whenever any `LISTED` item's
        protocol has `involves_prisoners` true, composition failures drawing
        `ERR_QUORUM_COMPOSITION_MISSING`."

        Design: Difficulty/combinatorial_formula/quorum_composition_prisoner_representative_branch
        """
        members = _five_member_quorum()
        scenario = setup_awaiting_full_board_scenario(
            involves_prisoners=True, chair=members["chair"])
        proto = scenario["protocol"]
        meeting = schedule_meeting(room_id="R-PRIS", scheduled_at="2026-06-01T10:00:00Z",
                                   duration_minutes=120)
        add_agenda_item_ok(meeting["id"], proto["id"], meeting["version"])

        # Count (4 >= 3) and base composition pass, but the prisoner-research
        # agenda item forces the PRISONER_REPRESENTATIVE branch.
        resp = api.convene_meeting(
            meeting["id"],
            {"attendee_member_ids": [
                members["chair"]["id"], members["sci"]["id"],
                members["nonsci"]["id"], members["unaff"]["id"],
            ]},
            make_chair_headers(members["chair"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QUORUM_COMPOSITION_MISSING)
        assert get_meeting(meeting["id"])["status"] == "SCHEDULED"

    def test_prisoner_branch_convenes_with_representative(self, api):
        """PRD §3.6: "with an additional requirement of at least one
        `PRISONER_REPRESENTATIVE` attendee whenever any `LISTED` item's
        protocol has `involves_prisoners` true". PRD §3.6: "On success the
        roster and the computed `quorum_threshold` are snapshotted onto the
        meeting and its status becomes `CONVENED`."

        Design: Difficulty/combinatorial_formula/quorum_composition_prisoner_representative_branch
        """
        members = _five_member_quorum()
        scenario = setup_awaiting_full_board_scenario(
            involves_prisoners=True, chair=members["chair"])
        proto = scenario["protocol"]
        meeting = schedule_meeting(room_id="R-PRIS", scheduled_at="2026-06-01T10:00:00Z",
                                   duration_minutes=120)
        add_agenda_item_ok(meeting["id"], proto["id"], meeting["version"])

        data = convene_meeting_ok(
            meeting["id"], members["chair"]["id"],
            [members["chair"]["id"], members["nonsci"]["id"],
             members["unaff"]["id"], members["pris"]["id"]],
        )
        assert data["status"] == "CONVENED"
        assert data["quorum_threshold"] == 3

    def test_convene_inactive_attendee_rejected(self, api):
        """PRD §3.6: "The checks run in a deliberate order: every listed id
        must resolve to an `ACTIVE` member, else `ERR_ATTENDEE_NOT_ELIGIBLE`".

        Design: Corner/validations/convene_inactive_attendee_rejected
        """
        chair = register_chair(email=unique_email("chair"))
        nonsci = register_member("NON_SCIENTIST", email=unique_email("nsia"))
        unaff = register_member("UNAFFILIATED", email=unique_email("unia"))
        get_success_data(api.deactivate_member(unaff["id"], ADMIN))

        meeting = schedule_meeting(room_id="R-IA")
        resp = api.convene_meeting(
            meeting["id"],
            {"attendee_member_ids": [chair["id"], nonsci["id"], unaff["id"]]},
            make_chair_headers(chair["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ATTENDEE_NOT_ELIGIBLE)
        assert get_meeting(meeting["id"])["status"] == "SCHEDULED"

    def test_convene_missing_non_scientist_rejected(self, api):
        """PRD §3.6: "the composition must include at least one attendee of
        category `NON_SCIENTIST` and at least one of category `UNAFFILIATED`,
        with an additional requirement of at least one `PRISONER_REPRESENTATIVE`
        attendee whenever any `LISTED` item's protocol has `involves_prisoners`
        true, composition failures drawing `ERR_QUORUM_COMPOSITION_MISSING`."

        Design: Corner/validations/convene_missing_non_scientist_rejected
        """
        chair = register_chair(email=unique_email("chair"))
        sci2 = register_member("SCIENTIST", email=unique_email("scins"))
        register_member("NON_SCIENTIST", email=unique_email("nsm2"))

        # 3 ACTIVE members -> threshold floor(3/2)+1 == 2; a 2-member roster of
        # scientists meets the count but fails the composition rule.
        meeting = schedule_meeting(room_id="R-NS")
        resp = api.convene_meeting(
            meeting["id"],
            {"attendee_member_ids": [chair["id"], sci2["id"]]},
            make_chair_headers(chair["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QUORUM_COMPOSITION_MISSING)


class TestRoomOccupationGeometry:
    def test_meeting_room_overlap_rejected(self, api):
        """PRD §3.6: "A meeting occupies its room over a half-open interval —
        from `scheduled_at` up to but not including `scheduled_at` plus
        `duration_minutes` — so a meeting beginning at the exact instant
        another ends does not collide with it. Any true overlap with another
        `SCHEDULED` or `CONVENED` meeting in the same room is rejected with
        `ERR_MEETING_ROOM_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/meeting_room_half_open_adjacency
        """
        m1 = schedule_meeting(room_id="R-HO", scheduled_at="2026-06-01T09:00:00Z",
                              duration_minutes=60)
        # 09:30 lies strictly inside [09:00, 10:00): a true overlap.
        resp = api.create_board_meeting(
            {"room_id": "R-HO", "scheduled_at": "2026-06-01T09:30:00Z",
             "duration_minutes": 60},
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_MEETING_ROOM_CONFLICT)
        assert get_meeting(m1["id"])["status"] == "SCHEDULED"

    def test_meeting_room_adjacent_start_allowed(self, api):
        """PRD §3.6: "a meeting beginning at the exact instant another ends
        does not collide with it" — under the half-open occupation
        [scheduled_at, scheduled_at + duration_minutes) the 10:00 meeting is
        free of the [09:00, 10:00) occupation.

        Design: Difficulty/resource_temporal_overlap/meeting_room_half_open_adjacency
        """
        schedule_meeting(room_id="R-HO", scheduled_at="2026-06-01T09:00:00Z",
                         duration_minutes=60)
        data = validate_success(
            api.create_board_meeting(
                {"room_id": "R-HO", "scheduled_at": "2026-06-01T10:00:00Z",
                 "duration_minutes": 60},
                COORDINATOR,
            ),
            201,  # PRD §4: creates return 201 Created
        )
        assert data["status"] == "SCHEDULED"


class TestFailedQuorumRecoveryCycle:
    def _setup(self):
        """Three ACTIVE members (chair SCIENTIST, NON_SCIENTIST, UNAFFILIATED)
        so the quorum threshold is floor(3/2)+1 == 2, and a SCHEDULED meeting."""
        chair = register_chair(email=unique_email("chair"))
        nonsci = register_member("NON_SCIENTIST", email=unique_email("nsm"))
        unaff = register_member("UNAFFILIATED", email=unique_email("unm"))
        meeting = schedule_meeting(room_id="R-CYC", scheduled_at="2026-06-01T10:00:00Z",
                                   duration_minutes=60)
        return chair, nonsci, unaff, meeting

    def test_failed_quorum_then_reschedule_returns_to_scheduled(self, api):
        """PRD §2.4: "Any board meeting still `SCHEDULED` once the clock has
        passed thirty minutes beyond its scheduled start transitions to
        `FAILED_QUORUM`." PRD §3.6: "the coordinator may then reschedule it —
        a new `scheduled_at` strictly after the current logical time (else
        `ERR_SCHEDULE_IN_PAST`), optionally a new `room_id` or
        `duration_minutes`, the room-occupation overlap check applied anew
        (else `ERR_MEETING_ROOM_CONFLICT`) — returning it to `SCHEDULED` with
        its `LISTED` items carried over."

        Design: Difficulty/non_linear_state_machine/board_meeting_failed_quorum_reschedule_cycle
        """
        _chair, _nonsci, _unaff, meeting = self._setup()

        # 10:31 is more than thirty minutes past the 10:00 start.
        set_clock("2026-06-01T10:31:00Z")
        assert get_meeting(meeting["id"])["status"] == "FAILED_QUORUM"

        data = validate_success(
            api.reschedule_meeting(
                meeting["id"], {"scheduled_at": "2026-06-08T10:00:00Z"}, COORDINATOR
            )
        )
        assert data["status"] == "SCHEDULED", (
            "Reschedule closes the FAILED_QUORUM loop back to SCHEDULED"
        )

    def test_convene_and_adjourn_after_reschedule(self, api):
        """PRD §3.6: "On success the roster and the computed `quorum_threshold`
        are snapshotted onto the meeting and its status becomes `CONVENED`."
        PRD §3.6: "Adjournment by the chair moves the meeting `CONVENED` →
        `ADJOURNED`".

        Design: Difficulty/non_linear_state_machine/board_meeting_failed_quorum_reschedule_cycle
        """
        chair, nonsci, unaff, meeting = self._setup()

        set_clock("2026-06-01T10:31:00Z")
        assert get_meeting(meeting["id"])["status"] == "FAILED_QUORUM"
        validate_success(
            api.reschedule_meeting(
                meeting["id"], {"scheduled_at": "2026-06-08T10:00:00Z"}, COORDINATOR
            )
        )

        set_clock("2026-06-08T10:00:00Z")
        convened = convene_meeting_ok(
            meeting["id"], chair["id"], [chair["id"], nonsci["id"], unaff["id"]]
        )
        assert convened["status"] == "CONVENED"
        assert convened["quorum_threshold"] == 2

        adjourned = validate_success(
            api.adjourn_meeting(meeting["id"], make_chair_headers(chair["id"]))
        )
        assert adjourned["status"] == "ADJOURNED"


class TestAgendaConstraints:
    def test_adjourn_defers_listed_items(self, api):
        """PRD §3.6: "Adjournment by the chair moves the meeting `CONVENED` →
        `ADJOURNED` and converts every still-`LISTED` item to `DEFERRED`,
        recomputing `item_count`."

        Design: Corner/state_machines/adjourn_defers_listed_items
        """
        members = _five_member_quorum()
        scenario = setup_awaiting_full_board_scenario(chair=members["chair"])
        proto = scenario["protocol"]
        meeting = schedule_meeting(room_id="R-ADJ")
        item = add_agenda_item_ok(meeting["id"], proto["id"], meeting["version"])
        convene_meeting_ok(
            meeting["id"], members["chair"]["id"],
            [members["chair"]["id"], members["nonsci"]["id"], members["unaff"]["id"]],
        )

        data = validate_success(
            api.adjourn_meeting(meeting["id"], make_chair_headers(members["chair"]["id"]))
        )
        assert data["status"] == "ADJOURNED"
        item_after = get_agenda_item(item["id"])
        assert item_after["status"] == "DEFERRED"
        assert get_protocol_status(api, proto["id"]) == "AWAITING_FULL_BOARD"

    def test_duplicate_agenda_listing_rejected(self, api):
        """PRD §3.6: "a protocol may hold at most one `LISTED` item across all
        `SCHEDULED` or `CONVENED` meetings at a time, a second listing drawing
        `ERR_DUPLICATE_AGENDA_LISTING` (HTTP 409)."

        Design: Corner/validations/duplicate_agenda_listing_rejected
        """
        scenario = setup_awaiting_full_board_scenario(approve_consent=False)
        proto = scenario["protocol"]
        m1 = schedule_meeting(room_id="R-D1", scheduled_at="2026-06-01T10:00:00Z")
        m2 = schedule_meeting(room_id="R-D2", scheduled_at="2026-06-02T10:00:00Z")
        add_agenda_item_ok(m1["id"], proto["id"], m1["version"])

        resp = api.add_agenda_item(
            m2["id"],
            {"protocol_id": proto["id"], "expected_meeting_version": m2["version"]},
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_AGENDA_LISTING)

        rows, _meta = validate_paginated(
            api.list_meeting_agenda_items(m2["id"], COORDINATOR)
        )
        assert rows == [], f"Rejected listing must not persist, got {rows}"

    def test_agenda_capacity_ninth_item_rejected(self, api):
        """PRD §3.6: "Capacity is capped at eight `LISTED` items per meeting —
        a ninth is rejected with `ERR_AGENDA_CAPACITY_EXCEEDED`". PRD §3.6:
        "Each successful addition increments the meeting's `version` and
        recomputes its `item_count`."

        Design: Corner/validations/agenda_capacity_ninth_item_rejected
        """
        inv = register_investigator()
        protocols = []
        for i in range(1, 10):
            proto = create_draft_protocol(
                inv["id"], title=f"Cap {i}", claimed_review_level="FULL_BOARD",
                risk_level="GREATER_THAN_MINIMAL",
            )
            upload_consent(proto["id"], inv["id"], file_ref=f"s3://consent/c{i}.pdf")
            drive_to_awaiting_full_board(proto["id"], inv["id"])
            protocols.append(proto)

        meeting = schedule_meeting(room_id="R-CAP", scheduled_at="2026-06-01T10:00:00Z",
                                   duration_minutes=240)
        base_version = meeting["version"]
        for i, proto in enumerate(protocols[:8]):
            added = add_agenda_item_ok(
                meeting["id"], proto["id"], base_version + i
            )
            assert added["status"] == "LISTED"

        assert get_meeting(meeting["id"])["item_count"] == 8

        resp = api.add_agenda_item(
            meeting["id"],
            {"protocol_id": protocols[8]["id"],
             "expected_meeting_version": base_version + 8},
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_AGENDA_CAPACITY_EXCEEDED)

    def test_meeting_scheduled_in_past_rejected(self, api):
        """PRD §3.6: "a `scheduled_at` start that must be strictly after the
        current logical time (otherwise `ERR_SCHEDULE_IN_PAST`)". PRD §2.4:
        "At startup, before any adjustment, the logical clock reads exactly
        `2026-05-01T00:00:00Z`".

        Design: Corner/validations/meeting_scheduled_in_past_rejected
        """
        register_investigator()  # anchor row
        resp = api.create_board_meeting(
            {"room_id": "R-PAST", "scheduled_at": "2026-04-30T23:59:59Z",
             "duration_minutes": 60},
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_IN_PAST)


class TestMeetingOptimisticConcurrency:
    def test_occ_stale_meeting_version_rejected(self, api):
        """PRD §2.8: "Each agenda-item addition bumps the meeting's `version`,
        so a writer holding an older value is composing against a stale agenda
        — its capacity headroom and duplicate-listing set may no longer be
        accurate. When `expected_meeting_version` does not match the meeting's
        current `version`, the listing is rejected with
        `ERR_STALE_MEETING_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_meeting_version_rejected
        """
        inv = register_investigator()
        protocols = []
        for title in ("M1 Study", "M2 Study"):
            proto = create_draft_protocol(
                inv["id"], title=title, claimed_review_level="FULL_BOARD",
                risk_level="GREATER_THAN_MINIMAL",
            )
            upload_consent(proto["id"], inv["id"])
            drive_to_awaiting_full_board(proto["id"], inv["id"])
            protocols.append(proto)

        meeting = schedule_meeting(room_id="R-OCC")
        observed_version = meeting["version"]

        item1 = add_agenda_item_ok(meeting["id"], protocols[0]["id"], observed_version)
        assert item1["status"] == "LISTED"

        # The first add bumped the meeting version; the stale value is rejected.
        resp = api.add_agenda_item(
            meeting["id"],
            {"protocol_id": protocols[1]["id"],
             "expected_meeting_version": observed_version},
            COORDINATOR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_MEETING_VERSION)

        fresh_version = get_meeting(meeting["id"])["version"]
        item2 = add_agenda_item_ok(meeting["id"], protocols[1]["id"], fresh_version)
        assert item2["status"] == "LISTED"


def get_protocol_status(api, protocol_id):
    return get_success_data(api.get_protocol(protocol_id, COORDINATOR))["status"]
