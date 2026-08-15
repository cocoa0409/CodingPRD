"""Section lifecycle, meeting rules, and ops-checkpoint window transitions."""
from test_helpers import (
    TEST_USERS, add_meeting, make_building, make_course,
    make_instructor, make_section, make_teacher,
    register_teacher, run_ops, set_clock, setup_catalog_scenario,
    validate_error, validate_success,
)
from test_helpers.constants import CLOCK_AFTER_END


def test_publish_section_without_meetings_rejected(api):
    """PRD §3.2: "Publish requires the parent course to be `ACTIVE`, at least one
    `SectionMeeting` to exist for the section, and the temporal quadruple to be
    coherent". PRD §2.10 step 6: "Lifecycle state — the target's current state
    permits the operation, including terminal-state lockdown
    (`ERR_INVALID_STATE`, ...)".

    Design: Corner/state_machines/publish_section_without_meetings_rejected
    """
    set_clock()
    building = make_building()
    instructor = make_instructor(building["id"])
    course = make_course(course_code="PM-1", clock_hours=5, fee_cents=0)
    section = make_section(course["id"], instructor["id"], building["id"])
    res = api.publish_section(section["id"], TEST_USERS["coordinator_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=400)


def test_publish_canceled_section_rejected(api):
    """PRD §3.2: "Cancellation moves a `DRAFT`, `PUBLISHED`, or
    `REGISTRATION_CLOSED` section to terminal `CANCELED`". PRD §2.10 step 6:
    "Lifecycle state — the target's current state permits the operation,
    including terminal-state lockdown (`ERR_INVALID_STATE`, ...)".

    Design: Corner/state_machines/publish_canceled_section_rejected
    """
    sc = setup_catalog_scenario(course_overrides={"course_code": "SM-1",
                                                  "clock_hours": 5, "fee_cents": 0})
    validate_success(api.cancel_section(sc.section["id"],
                                        TEST_USERS["coordinator_headers"]), 200)
    res = api.publish_section(sc.section["id"], TEST_USERS["coordinator_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=400)


def test_meeting_outside_section_rejected(api):
    """PRD §3.2: "A meeting's interval must be contained in the section's session
    window with its end strictly after its start; a meeting outside that window
    is rejected with `ERR_MEETING_OUTSIDE_SECTION`."

    Design: Corner/validations/meeting_outside_section_rejected
    """
    set_clock()
    building = make_building()
    instructor = make_instructor(building["id"])
    course = make_course(course_code="MO-1", clock_hours=5, fee_cents=0)
    section = make_section(course["id"], instructor["id"], building["id"])
    add_meeting(section["id"])  # one valid meeting inside the window
    res = api.add_meeting(section["id"],
                          {"starts_at": "2026-08-21T10:00:00Z",
                           "ends_at": "2026-08-21T12:00:00Z", "room": "R1"},
                          TEST_USERS["coordinator_headers"])
    validate_error(res, "ERR_MEETING_OUTSIDE_SECTION", expected_status=400)


def test_ops_run_section_window_transitions(api):
    """PRD §3.8 step 1: "Every `PUBLISHED` section whose `registration_closes_at`
    is now in the past moves to `REGISTRATION_CLOSED`; then every
    `REGISTRATION_CLOSED` section whose `starts_at` has been reached moves to
    `IN_SESSION`; then every `IN_SESSION` section whose `ends_at` is now past
    moves to `COMPLETED`. One run may advance a section through multiple steps."
    PRD §2.11: the checkpoint "returns six parallel arrays reporting what moved:
    `transitioned_section_ids`, ...".

    Design: Corner/state_machines/ops_run_section_window_transitions
    """
    sc = setup_catalog_scenario(course_overrides={"course_code": "OP-1",
                                                  "clock_hours": 5, "fee_cents": 0})
    set_clock(CLOCK_AFTER_END)
    report = run_ops()
    assert sc.section["id"] in report["transitioned_section_ids"]
    after = validate_success(api.get_section(sc.section["id"],
                                             TEST_USERS["coordinator_headers"]), 200)
    assert after["status"] == "COMPLETED", (
        "one run walks PUBLISHED -> REGISTRATION_CLOSED -> IN_SESSION -> COMPLETED")


def test_section_cancel_cascade_drops_and_expires(api):
    """PRD §3.2: "Cancellation moves a `DRAFT`, `PUBLISHED`, or
    `REGISTRATION_CLOSED` section to terminal `CANCELED` and cascades: every
    `REGISTERED` registration becomes `DROPPED` with its encumbrance released
    from the registrant's building budget (bumping that budget's `version`),
    every `WAITLISTED` registration becomes `EXPIRED`, and no promotion sweep
    runs because the section is terminal."

    Design: Corner/state_machines/section_cancel_cascade_drops_and_expires
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "CC-1", "clock_hours": 5, "fee_cents": 10000},
        section_overrides={"seat_capacity": 1}, with_budget=500000)
    t1 = make_teacher(sc.building["id"], email="tcc@x.com", full_name="T CC")
    t2 = make_teacher(sc.building["id"], email="tcd@x.com", full_name="T CD")
    r1 = register_teacher(t1["id"], sc.section["id"])
    r2 = register_teacher(t2["id"], sc.section["id"])
    assert r1["status"] == "REGISTERED"
    assert r2["status"] == "WAITLISTED"

    canceled = validate_success(api.cancel_section(
        sc.section["id"], TEST_USERS["coordinator_headers"]), 200)
    assert canceled["status"] == "CANCELED"

    r1_after = validate_success(api.get_registration(r1["id"],
                                                     TEST_USERS["coordinator_headers"]), 200)
    r2_after = validate_success(api.get_registration(r2["id"],
                                                     TEST_USERS["coordinator_headers"]), 200)
    assert r1_after["status"] == "DROPPED"
    assert r2_after["status"] == "EXPIRED", "cancel-driven expiry, not withdrawal"

    budget = validate_success(api.get_budget(sc.budget["id"],
                                             TEST_USERS["coordinator_headers"]), 200)
    assert budget["encumbered_cents"] == 0, "the 10000 encumbrance is released"


class TestRoomTurnoverBuffer:
    """PRD §3.2: "Two meetings sharing the same room must respect a thirty-minute
    turnover gap against every existing meeting in that room — a violation is
    `ERR_ROOM_CONFLICT` (HTTP 409).\""""

    def _section_with_anchor_meeting(self):
        sc = setup_catalog_scenario(
            course_overrides={"course_code": "ROOM-1", "clock_hours": 6,
                              "fee_cents": 0},
            section_overrides={
                "room": "RB", "starts_at": "2026-08-15T08:00:00Z",
                "ends_at": "2026-08-15T18:00:00Z"},
            meeting_times=[("2026-08-15T09:00:00Z", "2026-08-15T10:00:00Z", "RB")])
        return sc

    def test_room_turnover_gap_below_thirty_rejected(self, api):
        """PRD §3.2: "Two meetings sharing the same room must respect a
        thirty-minute turnover gap against every existing meeting in that room —
        a violation is `ERR_ROOM_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_room_turnover_buffer
        """
        sc = self._section_with_anchor_meeting()
        res_zero = api.add_meeting(
            sc.section["id"],
            {"starts_at": "2026-08-15T10:00:00Z", "ends_at": "2026-08-15T10:30:00Z",
             "room": "RB"},
            TEST_USERS["coordinator_headers"])
        validate_error(res_zero, "ERR_ROOM_CONFLICT", expected_status=409)

        res_29 = api.add_meeting(
            sc.section["id"],
            {"starts_at": "2026-08-15T10:29:00Z", "ends_at": "2026-08-15T11:00:00Z",
             "room": "RB"},
            TEST_USERS["coordinator_headers"])
        validate_error(res_29, "ERR_ROOM_CONFLICT", expected_status=409)

    def test_room_turnover_gap_exactly_thirty_accepted(self, api):
        """PRD §3.2: "Two meetings sharing the same room must respect a
        thirty-minute turnover gap against every existing meeting in that room —
        a violation is `ERR_ROOM_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_room_turnover_buffer
        """
        sc = self._section_with_anchor_meeting()
        res_ok = api.add_meeting(
            sc.section["id"],
            {"starts_at": "2026-08-15T10:30:00Z", "ends_at": "2026-08-15T11:00:00Z",
             "room": "RB"},
            TEST_USERS["coordinator_headers"])
        meeting = validate_success(res_ok, 201)
        assert meeting["id"], "a gap of exactly thirty minutes satisfies the buffer"


def test_capacity_shrink_below_registered_rejected(api):
    """PRD §3.2: "A `PUBLISHED` section may still be edited — capacity, room, or
    schedule — but the new `seat_capacity` must be at least the current
    `seats_registered`, or the edit is rejected with
    `ERR_CAPACITY_BELOW_REGISTERED`."

    Design: Corner/validations/capacity_shrink_below_registered_rejected
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "CS-1", "clock_hours": 5, "fee_cents": 0},
        section_overrides={"seat_capacity": 2})
    t1 = make_teacher(sc.building["id"], email="tcs@x.com")
    t2 = make_teacher(sc.building["id"], email="tct@x.com")
    register_teacher(t1["id"], sc.section["id"])
    register_teacher(t2["id"], sc.section["id"])

    res = api.patch_section(sc.section["id"], {"seat_capacity": 1},
                            TEST_USERS["coordinator_headers"])
    validate_error(res, "ERR_CAPACITY_BELOW_REGISTERED", expected_status=400)


def test_immediate_consistency_capacity_patch(api):
    """PRD §3.2: "When a capacity edit increases seats, a synchronous waitlist
    promotion sweep runs for that section immediately (§3.3)." PRD §2.2:
    "operations that create or modify a resource will return the created or
    updated resource object in the data field."

    Design: Corner/consistency_model/immediate_consistency_capacity_patch
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "IM-1", "clock_hours": 5, "fee_cents": 0},
        section_overrides={"seat_capacity": 2})
    t1 = make_teacher(sc.building["id"], email="tim@x.com")
    t2 = make_teacher(sc.building["id"], email="tin@x.com")
    t3 = make_teacher(sc.building["id"], email="tio@x.com")
    register_teacher(t1["id"], sc.section["id"])
    register_teacher(t2["id"], sc.section["id"])
    r3 = register_teacher(t3["id"], sc.section["id"])
    assert r3["status"] == "WAITLISTED"

    patched = validate_success(
        api.patch_section(sc.section["id"], {"seat_capacity": 3},
                          TEST_USERS["coordinator_headers"]), 200)
    assert patched["seat_capacity"] == 3
    assert patched["seats_registered"] == 3, (
        "promotion applied synchronously inside the PATCH response")
    assert patched["seats_open"] == 0

    r3_after = validate_success(api.get_registration(
        r3["id"], TEST_USERS["coordinator_headers"]), 200)
    assert r3_after["status"] == "REGISTERED"
