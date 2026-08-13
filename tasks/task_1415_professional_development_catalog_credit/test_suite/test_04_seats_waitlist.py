"""Seat allocation, waitlist waterfall, and promotion cascades."""
from test_helpers import (
    TEST_USERS, assert_seat_conservation, make_building, make_budget,
    make_course, make_instructor, make_section, make_teacher, add_meeting,
    publish_section, register_teacher, run_ops, set_clock,
    setup_catalog_scenario, validate_error, validate_success,
    make_teacher_headers,
)
from test_helpers.factories import create_registration_payload


class TestLastSeatBoundary:
    def _capacity_two_section(self):
        sc = setup_catalog_scenario(
            course_overrides={"course_code": "SEAT-1", "clock_hours": 5,
                              "fee_cents": 0},
            section_overrides={"seat_capacity": 2})
        teachers = [make_teacher(sc.building["id"], email=f"t{c}@x.com",
                                 full_name=f"T {c}") for c in ("H", "I", "J")]
        return sc, teachers

    def test_last_open_seat_registers(self, api):
        """PRD §3.3: "If `seats_open` is at least one, the registration is
        created in `REGISTERED`." PRD §3.2: "its computed `seats_registered`
        counts registrations currently in `REGISTERED`, while `seats_open` is the
        capacity minus that count."

        Design: Difficulty/boundary_precision_check/boundary_seat_last_seat_vs_waitlist
        """
        sc, teachers = self._capacity_two_section()
        r1 = register_teacher(teachers[0]["id"], sc.section["id"])
        assert r1["status"] == "REGISTERED", "seats_open was 2"
        r2 = register_teacher(teachers[1]["id"], sc.section["id"])
        assert r2["status"] == "REGISTERED", "seats_open was exactly 1 — last seat succeeds"
        section = validate_success(api.get_section(
            sc.section["id"], TEST_USERS["coordinator_headers"]), 200)
        assert section["seats_registered"] == 2
        assert section["seats_open"] == 0

    def test_full_section_waitlists_with_seq(self, api):
        """PRD §3.3: "If no seat is open, the registration is created in
        `WAITLISTED` with `waitlist_seq` set to the next per-section monotonic
        integer and `encumbered_cents` zero — a waitlisted seat holds no money."

        Design: Difficulty/boundary_precision_check/boundary_seat_last_seat_vs_waitlist
        """
        sc, teachers = self._capacity_two_section()
        register_teacher(teachers[0]["id"], sc.section["id"])
        register_teacher(teachers[1]["id"], sc.section["id"])
        r3 = register_teacher(teachers[2]["id"], sc.section["id"])
        assert r3["status"] == "WAITLISTED", "seats_open == 0 waitlists — never an error"
        assert r3["waitlist_seq"] == 1
        assert r3["encumbered_cents"] == 0


class TestSeatConservationDropPromote:
    def _capacity_one_pair(self):
        sc = setup_catalog_scenario(
            course_overrides={"course_code": "SEAT-INV", "clock_hours": 4,
                              "fee_cents": 0},
            section_overrides={"seat_capacity": 1})
        t1 = make_teacher(sc.building["id"], email="to@x.com", full_name="T O")
        t2 = make_teacher(sc.building["id"], email="tp@x.com", full_name="T P")
        r1 = register_teacher(t1["id"], sc.section["id"])
        r2 = register_teacher(t2["id"], sc.section["id"])
        assert r1["status"] == "REGISTERED"
        assert r2["status"] == "WAITLISTED"
        return sc, t1, t2, r1, r2

    def test_seat_count_conserved_across_drop_and_promotion(self, api):
        """PRD §3.2: "its computed `seats_registered` counts registrations
        currently in `REGISTERED`, while `seats_open` is the capacity minus that
        count." PRD §3.3: "Seat freeing events — an explicit drop, a capacity
        increase, or an ops-run transition — trigger the promotion sweep."

        Design: Difficulty/compensating_invariant/invariant_seat_conservation_drop_promote
        """
        sc, t1, _t2, r1, _r2 = self._capacity_one_pair()
        pre = validate_success(api.get_section(
            sc.section["id"], TEST_USERS["coordinator_headers"]), 200)
        assert pre["seats_registered"] == 1 and pre["seats_open"] == 0
        assert_seat_conservation(pre)

        dropped = validate_success(api.drop_registration(
            r1["id"], make_teacher_headers(t1["id"])), 200)
        assert dropped["status"] == "DROPPED"

        post = validate_success(api.get_section(
            sc.section["id"], TEST_USERS["coordinator_headers"]), 200)
        assert post["seats_registered"] == 1 and post["seats_open"] == 0, (
            "the seat changed occupants, not count")
        assert_seat_conservation(post)

    def test_promotion_moves_waitlisted_to_registered(self, api):
        """PRD §3.3: "Promotion clears the candidate's `waitlist_seq` to null,
        moves them to `REGISTERED`, encumbers the fee exactly as a fresh
        registration would, bumps the budget's `version`, and advances their
        `ASSIGNED` compliance assignments for the course to `IN_PROGRESS`."

        Design: Difficulty/compensating_invariant/invariant_seat_conservation_drop_promote
        """
        sc, t1, _t2, r1, r2 = self._capacity_one_pair()
        validate_success(api.drop_registration(r1["id"],
                                               make_teacher_headers(t1["id"])), 200)
        r2_after = validate_success(api.get_registration(
            r2["id"], TEST_USERS["coordinator_headers"]), 200)
        assert r2_after["status"] == "REGISTERED"
        assert r2_after["waitlist_seq"] is None


class TestDropReleasePromoteEncumberCascade:
    def _two_building_scenario(self):
        set_clock()
        b1 = make_building(name="B One", building_code="B1")
        b2 = make_building(name="B Two", building_code="B2")
        bud1 = make_budget(b1["id"], allocated_cents=500000)
        bud2 = make_budget(b2["id"], allocated_cents=500000)
        t1 = make_teacher(b1["id"], email="ta@x.com", full_name="T A")
        t2 = make_teacher(b2["id"], email="tb@x.com", full_name="T B")
        instructor = make_instructor(b1["id"], email="ia@x.com")
        course = make_course(course_code="CASC-10", clock_hours=10,
                             fee_cents=20000)
        section = make_section(course["id"], instructor["id"], b1["id"],
                               seat_capacity=1)
        add_meeting(section["id"])
        publish_section(section["id"])
        r1 = register_teacher(t1["id"], section["id"])
        r2 = register_teacher(t2["id"], section["id"])
        assert r1["status"] == "REGISTERED"
        assert r2["status"] == "WAITLISTED" and r2["waitlist_seq"] == 1
        return (b1, b2, bud1, bud2, t1, t2, section, r1, r2)

    def test_drop_releases_seat_and_encumbrance(self, api):
        """PRD §3.3: "the registration becomes `DROPPED`, its `encumbered_cents`
        is subtracted from the budget's `encumbered_cents` and zeroed on the
        registration (budget `version` bumped), and the freed seat triggers the
        promotion sweep."

        Design: Difficulty/transitive_cascade/cascade_drop_release_promote_encumber
        """
        _b1, _b2, bud1, _bud2, t1, _t2, _s, r1, _r2 = self._two_building_scenario()
        dropped = validate_success(api.drop_registration(
            r1["id"], make_teacher_headers(t1["id"])), 200)
        assert dropped["status"] == "DROPPED"  # link 1
        budget1 = validate_success(api.get_budget(
            bud1["id"], TEST_USERS["coordinator_headers"]), 200)
        assert budget1["encumbered_cents"] == 0, "release caused by the drop"

    def test_promotion_encumbers_next_teacher_building(self, api):
        """PRD §3.3: "Note the depth this creates: a drop releases a seat, the
        release triggers promotion, and the promotion creates a fresh encumbrance
        — a three-level cascade inside one request."

        Design: Difficulty/transitive_cascade/cascade_drop_release_promote_encumber
        """
        _b1, _b2, _bud1, bud2, t1, _t2, _s, r1, r2 = self._two_building_scenario()
        validate_success(api.drop_registration(r1["id"],
                                               make_teacher_headers(t1["id"])), 200)
        r2_after = validate_success(api.get_registration(
            r2["id"], TEST_USERS["coordinator_headers"]), 200)
        assert r2_after["status"] == "REGISTERED", (
            "link 2: promotion caused by the seat release, synchronous")
        budget2 = validate_success(api.get_budget(
            bud2["id"], TEST_USERS["coordinator_headers"]), 200)
        assert budget2["encumbered_cents"] == 20000, (
            "link 3: fresh encumbrance caused by the promotion")


def test_promotion_skips_budget_failed_candidate(api):
    """PRD §3.3: "Each candidate is eligible only while the section is still
    `PUBLISHED`, a seat is actually open after the freeing event, and — when the
    fee is greater than zero — the candidate teacher's building budget for the
    section's fiscal year is `OPEN` with `available_cents` covering the fee. A
    candidate whose budget fails is skipped and remains `WAITLISTED`; the sweep
    continues down the list, promoting until no seats remain".

    Design: Corner/calculations/promotion_skips_budget_failed_candidate
    """
    set_clock()
    b1 = make_building(name="Sel B1", building_code="SB1")
    b2 = make_building(name="Sel B2", building_code="SB2")
    b3 = make_building(name="Sel B3", building_code="SB3")
    make_budget(b1["id"], allocated_cents=500000)
    bud2 = make_budget(b2["id"], allocated_cents=5000)
    bud3 = make_budget(b3["id"], allocated_cents=500000)
    t1 = make_teacher(b1["id"], email="ts1@x.com")
    t2 = make_teacher(b2["id"], email="ts2@x.com")
    t3 = make_teacher(b3["id"], email="ts3@x.com")
    instructor = make_instructor(b1["id"], email="ise@x.com")
    course = make_course(course_code="SEL-1", clock_hours=5, fee_cents=10000)
    section = make_section(course["id"], instructor["id"], b1["id"], seat_capacity=1)
    add_meeting(section["id"])
    publish_section(section["id"])
    r1 = register_teacher(t1["id"], section["id"])
    r2 = register_teacher(t2["id"], section["id"])
    r3 = register_teacher(t3["id"], section["id"])
    assert r2["waitlist_seq"] == 1 and r3["waitlist_seq"] == 2

    validate_success(api.drop_registration(r1["id"], make_teacher_headers(t1["id"])), 200)

    r2_after = validate_success(api.get_registration(
        r2["id"], TEST_USERS["coordinator_headers"]), 200)
    r3_after = validate_success(api.get_registration(
        r3["id"], TEST_USERS["coordinator_headers"]), 200)
    assert r2_after["status"] == "WAITLISTED", (
        "B2 available 5000 < fee 10000 — candidate skipped, stays in queue")
    assert r3_after["status"] == "REGISTERED", "next eligible candidate in seq order"

    budget3 = validate_success(api.get_budget(bud3["id"],
                                              TEST_USERS["coordinator_headers"]), 200)
    budget2 = validate_success(api.get_budget(bud2["id"],
                                              TEST_USERS["coordinator_headers"]), 200)
    assert budget3["encumbered_cents"] == 10000
    assert budget2["encumbered_cents"] == 0


def test_employee_separation_cascade(api):
    """PRD §3.3: "when a `PDCoordinator` moves an employee from `ACTIVE` or
    `ON_LEAVE` to `SEPARATED`, every `WAITLISTED` registration of that employee
    becomes `WITHDRAWN`, and every `REGISTERED` registration whose section is
    `PUBLISHED` or `REGISTRATION_CLOSED` becomes `DROPPED` with its encumbrance
    released and a promotion sweep run per freed seat." PRD §3.3: "an
    employee-targeted write against an `ON_LEAVE` or `SEPARATED` employee fails
    with `ERR_EMPLOYEE_NOT_ACTIVE`".

    Design: Corner/state_machines/employee_separation_cascade
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "SP-1", "clock_hours": 5, "fee_cents": 0})
    t1 = make_teacher(sc.building["id"], email="tsp@x.com")
    t2 = make_teacher(sc.building["id"], email="tsq@x.com")
    # Second section of the same course with capacity 1: T2 holds the seat.
    # Its session window is disjoint from S1's so the schedule-overlap gate of
    # PRD §3.3 does not interfere with the waitlist placement under test.
    s2 = make_section(sc.course["id"], sc.instructor["id"], sc.building["id"],
                      room="R2", seat_capacity=1,
                      starts_at="2026-08-22T09:00:00Z",
                      ends_at="2026-08-27T17:00:00Z",
                      registration_opens_at="2026-08-01T00:00:00Z",
                      registration_closes_at="2026-08-18T00:00:00Z")
    add_meeting(s2["id"], "2026-08-22T10:00:00Z", "2026-08-22T12:00:00Z", "R2")
    publish_section(s2["id"])
    r1 = register_teacher(t1["id"], sc.section["id"])      # REGISTERED (capacity 5)
    register_teacher(t2["id"], s2["id"])                   # REGISTERED in s2
    r2 = register_teacher(t1["id"], s2["id"])              # WAITLISTED in s2
    assert r2["status"] == "WAITLISTED"

    emp = validate_success(api.set_employee_status(
        t1["id"], {"status": "SEPARATED"}, TEST_USERS["coordinator_headers"]), 200)
    assert emp["status"] == "SEPARATED"

    r1_after = validate_success(api.get_registration(
        r1["id"], TEST_USERS["coordinator_headers"]), 200)
    r2_after = validate_success(api.get_registration(
        r2["id"], TEST_USERS["coordinator_headers"]), 200)
    assert r1_after["status"] == "DROPPED", "conditional: was REGISTERED"
    assert r2_after["status"] == "WITHDRAWN", "conditional: was WAITLISTED"

    res = api.create_registration(
        create_registration_payload(t1["id"], sc.section["id"]),
        make_teacher_headers(t1["id"]))
    validate_error(res, "ERR_EMPLOYEE_NOT_ACTIVE", expected_status=400)


def test_ops_run_close_before_promote_then_expire(api):
    """PRD §3.8: "1. **Section windows.** ... 2. **Waitlist promotion.** For
    sections still `PUBLISHED`, the promotion waterfall of §3.3 runs.
    3. **Waitlist expiry.** `WAITLISTED` registrations in sections now
    `IN_SESSION`, `COMPLETED`, or `CANCELED` become `EXPIRED`." PRD §3.3: "A
    `REGISTERED` teacher may drop (or be dropped by a coordinator) while the
    section is `PUBLISHED` or `REGISTRATION_CLOSED`".

    Design: Corner/calculations/ops_run_close_before_promote_then_expire
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "OR-1", "clock_hours": 5, "fee_cents": 0},
        section_overrides={"seat_capacity": 1})
    t1 = make_teacher(sc.building["id"], email="tor@x.com")
    t2 = make_teacher(sc.building["id"], email="tos@x.com")
    r1 = register_teacher(t1["id"], sc.section["id"])
    r2 = register_teacher(t2["id"], sc.section["id"])
    assert r2["status"] == "WAITLISTED"

    # Clock past registration_closes_at (2026-08-10): first run closes the window.
    set_clock("2026-08-12T00:00:00Z")
    run_ops()
    # Drop is still legal from REGISTRATION_CLOSED, but the freed seat is NOT
    # promoted because promotion requires PUBLISHED.
    validate_success(api.drop_registration(r1["id"], make_teacher_headers(t1["id"])), 200)
    r2_mid = validate_success(api.get_registration(
        r2["id"], TEST_USERS["coordinator_headers"]), 200)
    assert r2_mid["status"] == "WAITLISTED", "freed seat is not filled off-PUBLISHED"

    # Clock past starts_at (2026-08-15): second run moves IN_SESSION, then
    # expires the waitlisted row.
    set_clock("2026-08-16T00:00:00Z")
    run_ops()
    r2_fin = validate_success(api.get_registration(
        r2["id"], TEST_USERS["coordinator_headers"]), 200)
    section = validate_success(api.get_section(
        sc.section["id"], TEST_USERS["coordinator_headers"]), 200)
    assert section["status"] == "IN_SESSION"
    assert r2_fin["status"] == "EXPIRED"
    assert section["seats_registered"] == 0
