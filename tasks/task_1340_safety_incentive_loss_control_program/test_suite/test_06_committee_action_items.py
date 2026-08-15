"""Committee meetings and action items: quorum boundary, half-open interval
overlap, cancellation lockdown, completion ownership, and the carry-over
open-count invariant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_program,
    create_action_item_record,
    create_meeting_record,
    create_program,
    get_meeting,
    hold_meeting,
    list_events,
    make_committee_chair_headers,
    make_supervisor_headers,
    publish_meeting_minutes,
    set_clock,
    setup_roster,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["ehs_admin_headers"]


class TestQuorumBoundary:
    def test_quorum_exactly_min_holds(self, api):
        """PRD §3.5: "Every attendee identifier must resolve to an existing
        employee (`ERR_NOT_FOUND`), and the count of distinct attendees whose
        `committee_member` flag is true must reach the program's `quorum_min` —
        exactly the quorum passes, one short fails with `ERR_QUORUM_NOT_MET`."
        PRD §3.5: "A meeting that reaches `HELD` pays its committee: each
        distinct committee-member attendee earns a `MEETING_ATTENDED` incentive
        event."

        Design: Difficulty/boundary_precision_check/quorum_exactly_min_holds
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program(quorum_min=2)
        _role, employees = setup_roster(member_names=("C One", "C Two"))
        c1, c2 = employees["C One"], employees["C Two"]
        manager = employees["Marta M"]
        mt1 = create_meeting_record(program["id"], manager["id"],
                                    scheduled_start="2026-06-10T09:00:00Z",
                                    scheduled_end="2026-06-10T10:00:00Z")
        mt2 = create_meeting_record(program["id"], manager["id"],
                                    scheduled_start="2026-06-10T11:00:00Z",
                                    scheduled_end="2026-06-10T12:00:00Z")

        held = hold_meeting(mt1["id"], manager["id"], [c1["id"], c2["id"]])
        assert held["status"] == "HELD", \
            "exactly quorum_min distinct committee members passes"
        attended = list_events(program_id=program["id"],
                               source_type="MEETING_ATTENDED")
        assert len(attended) == 2, \
            "one MEETING_ATTENDED event per distinct committee-member attendee"
        assert {e["employee_id"] for e in attended} == {c1["id"], c2["id"]}

        resp = api.hold_meeting(mt2["id"], {"attendee_ids": [c1["id"]]},
                                make_committee_chair_headers(manager["id"]))
        validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET)
        assert get_meeting(mt2["id"])["status"] == "SCHEDULED", \
            "one short of quorum leaves the meeting SCHEDULED"


class TestMeetingOverlap:
    def test_meeting_half_open_overlap(self, api):
        """PRD §3.5: "Meetings occupy a half-open interval — the start
        inclusive, the end exclusive — and must not overlap another meeting of
        the same program in `SCHEDULED` or `HELD`"
        PRD §3.5: "Back-to-back scheduling is explicitly allowed; a new meeting
        whose `scheduled_start` coincides exactly with an existing meeting's
        `scheduled_end` does not conflict. Violations are rejected with
        `ERR_MEETING_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/meeting_half_open_overlap
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_program()  # DRAFT: meeting scheduling has no phase gate
        _role, employees = setup_roster()
        manager = employees["Marta M"]
        first = create_meeting_record(program["id"], manager["id"],
                                      scheduled_start="2026-06-10T09:00:00Z",
                                      scheduled_end="2026-06-10T10:00:00Z")
        assert first["status"] == "SCHEDULED"

        adjacent = validate_success(api.create_committee_meeting(
            {"program_id": program["id"],
             "scheduled_start": "2026-06-10T10:00:00Z",
             "scheduled_end": "2026-06-10T11:00:00Z", "location": "Room 1"},
            make_committee_chair_headers(manager["id"])), expected_status=201)
        assert adjacent["status"] == "SCHEDULED", \
            "new.start == existing.end does not conflict under half-open semantics"

        resp = api.create_committee_meeting(
            {"program_id": program["id"],
             "scheduled_start": "2026-06-10T09:30:00Z",
             "scheduled_end": "2026-06-10T10:30:00Z", "location": "Room 2"},
            make_committee_chair_headers(manager["id"]))
        validate_error(resp, ApiErrorId.ERR_MEETING_OVERLAP)

        rows, meta = validate_paginated(api.list_committee_meetings(
            ADMIN, params={"program_id": program["id"]}))
        assert meta["total_count"] == 2, "the overlapping meeting was not persisted"


class TestMeetingCancellation:
    def test_cancelled_meeting_cannot_be_held(self, api):
        """PRD §3.5: "A meeting still `SCHEDULED` may instead be cancelled,
        moving to `CANCELLED`; both `MINUTES_PUBLISHED` and `CANCELLED` are
        terminal."
        PRD §2.6: "`ERR_INVALID_STATE` as the generic fallback for any other
        impermissible transition."

        Design: Corner/state_machines/cancelled_meeting_cannot_be_held
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program(quorum_min=1)
        _role, employees = setup_roster(member_names=("Ann A",))
        ann, manager = employees["Ann A"], employees["Marta M"]
        meeting = create_meeting_record(program["id"], manager["id"])

        cancelled = validate_success(api.cancel_meeting(
            meeting["id"], make_committee_chair_headers(manager["id"])))
        assert cancelled["status"] == "CANCELLED"

        resp = api.hold_meeting(meeting["id"], {"attendee_ids": [ann["id"]]},
                                make_committee_chair_headers(manager["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_meeting(meeting["id"])["status"] == "CANCELLED", \
            "CANCELLED is terminal and records no attendance"


class TestActionItemCompletionOwnership:
    def test_non_assignee_cannot_complete_action_item_returns_unauthorized(self, api):
        """PRD §3.5: "Completion is open to the assignee or to the chair: an
        actor whose identity is neither the item's `assignee_id` nor a
        `CommitteeChair` is rejected with `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/non_assignee_cannot_complete_action_item_returns_unauthorized
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program(quorum_min=1)
        _role, employees = setup_roster(member_names=("Ann A",),
                                        plain_names=("Marta M", "Bob B"))
        ann, manager, bob = (employees["Ann A"], employees["Marta M"],
                             employees["Bob B"])
        meeting = create_meeting_record(program["id"], manager["id"])
        hold_meeting(meeting["id"], manager["id"], [ann["id"]])
        item = create_action_item_record(meeting["id"], manager["id"], ann["id"],
                                         description="Inspect eyewash",
                                         due_date="2026-06-20T00:00:00Z")

        resp = api.complete_action_item(item["id"], {},
                                        make_supervisor_headers(bob["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        unchanged = validate_success(api.get_action_item(item["id"], ADMIN))
        assert unchanged["status"] == "ASSIGNED", \
            "Bob is neither the assignee nor a CommitteeChair"


class TestActionItemCarryOver:
    def test_action_item_carryover_count_conservation(self, api):
        """PRD §3.7: "Every `ASSIGNED` action item past its `due_date`
        escalates to `ESCALATED`."
        PRD §3.5: "From `ESCALATED`, the chair may reassign the item back to
        `ASSIGNED`, which requires a new `due_date` (`ERR_INVALID_REQUEST` if
        absent) and optionally accepts a different `assignee_id` or a different
        `meeting_id` — the latter must name a meeting of the same program in
        `HELD` or `MINUTES_PUBLISHED` (otherwise `ERR_INVALID_STATE`). When the
        meeting changes, the counts stay conserved: the old meeting's
        `open_action_count` decrements and the new meeting's increments, so the
        global open count is unchanged by the carry-over."

        Design: Difficulty/compensating_invariant/action_item_carryover_count_conservation
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program(quorum_min=1)
        _role, employees = setup_roster(member_names=("Ann A",))
        ann, manager = employees["Ann A"], employees["Marta M"]
        mt1 = create_meeting_record(program["id"], manager["id"],
                                    scheduled_start="2026-06-08T09:00:00Z",
                                    scheduled_end="2026-06-08T10:00:00Z")
        mt2 = create_meeting_record(program["id"], manager["id"],
                                    scheduled_start="2026-06-09T09:00:00Z",
                                    scheduled_end="2026-06-09T10:00:00Z")
        hold_meeting(mt1["id"], manager["id"], [ann["id"]])
        publish_meeting_minutes(mt1["id"], manager["id"], "Week 1")
        hold_meeting(mt2["id"], manager["id"], [ann["id"]])
        publish_meeting_minutes(mt2["id"], manager["id"], "Week 2")
        item = create_action_item_record(
            mt1["id"], manager["id"], ann["id"],
            description="Inspect eyewash station",
            due_date="2026-06-10T00:00:00Z")
        assert get_meeting(mt1["id"])["open_action_count"] == 1

        set_clock("2026-06-15T00:00:00Z")
        sweep = validate_success(api.sweep_program(program["id"], {}, ADMIN))
        assert sweep["escalated_actions"] == 1, \
            "ASSIGNED past due escalates but remains open"
        escalated = validate_success(api.get_action_item(item["id"], ADMIN))
        assert escalated["status"] == "ESCALATED"
        assert get_meeting(mt1["id"])["open_action_count"] == 1, \
            "ESCALATED still counts as open"

        moved = validate_success(api.reassign_action_item(
            item["id"],
            {"due_date": "2026-06-25T00:00:00Z", "meeting_id": mt2["id"]},
            make_committee_chair_headers(manager["id"])))
        assert moved["status"] == "ASSIGNED"
        assert moved["meeting_id"] == mt2["id"]

        assert get_meeting(mt1["id"])["open_action_count"] == 0, \
            "the source meeting decrements"
        assert get_meeting(mt2["id"])["open_action_count"] == 1, \
            "the target meeting increments; the global open count is conserved"
