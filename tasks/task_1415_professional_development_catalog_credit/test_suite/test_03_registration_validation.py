"""Registration validation ladder: alignment, temporal, constraint, and fiscal gates."""
from test_helpers import (
    TEST_USERS, api_client, make_admin, make_building, make_building_admin_headers,
    make_course, make_growth_plan, make_instructor, make_section, make_teacher,
    publish_section, add_meeting, register_teacher, set_clock,
    setup_catalog_scenario, validate_error, validate_success,
    make_teacher_headers,
)
from test_helpers.factories import create_registration_payload


class TestRegistrationRequiresApprovedPlan:
    def _scenario_with_draft_plan(self):
        sc = setup_catalog_scenario(
            course_overrides={"course_code": "XENT-1", "clock_hours": 15,
                              "fee_cents": 0})
        teacher = make_teacher(sc.building["id"], email="tk@x.com")
        admin = make_admin(sc.building["id"], email="ah@x.com")
        plan = make_growth_plan(teacher, school_year="2026-2027",
                                target_credits=2.0, focus_areas=("math",))
        return sc, teacher, admin, plan

    def test_draft_plan_alignment_rejected(self, api):
        """PRD §3.6: "Any `growth_plan_id` carried by a registration or a
        workshop request must belong to the same teacher, must stand in
        `APPROVED` or `FULFILLED` (else `ERR_PLAN_NOT_APPROVED`)".

        Design: Difficulty/cross_entity_state_dependency/cross_entity_registration_requires_approved_plan
        """
        sc, teacher, _admin, plan = self._scenario_with_draft_plan()
        assert plan["status"] == "DRAFT"
        res = api.create_registration(
            create_registration_payload(teacher["id"], sc.section["id"],
                                        growth_plan_id=plan["id"],
                                        aligned_focus_area="math"),
            make_teacher_headers(teacher["id"]))
        validate_error(res, "ERR_PLAN_NOT_APPROVED", expected_status=400)

    def test_approved_plan_alignment_accepted(self, api):
        """PRD §3.6: "Any `growth_plan_id` carried by a registration or a
        workshop request must belong to the same teacher, must stand in
        `APPROVED` or `FULFILLED` (else `ERR_PLAN_NOT_APPROVED`)" — the same
        request succeeds once the plan stands in `APPROVED`.

        Design: Difficulty/cross_entity_state_dependency/cross_entity_registration_requires_approved_plan
        """
        sc, teacher, admin, plan = self._scenario_with_draft_plan()
        validate_success(api.submit_plan(plan["id"],
                                         make_teacher_headers(teacher["id"])), 200)
        approved = validate_success(
            api.approve_plan(plan["id"], make_building_admin_headers(admin["id"])), 200)
        assert approved["status"] == "APPROVED"
        reg = register_teacher(teacher["id"], sc.section["id"],
                               growth_plan_id=approved["id"],
                               aligned_focus_area="math")
        assert reg["status"] == "REGISTERED"
        assert reg["growth_plan_id"] == approved["id"]


class TestStateVsFiscalPriority:
    def _canceled_section_no_budget(self):
        """Building with NO budget at all; fee-bearing course; section PUBLISHED
        then CANCELED — state failure and fiscal failure both armed."""
        sc = setup_catalog_scenario(
            course_overrides={"course_code": "PRIO-1", "clock_hours": 10,
                              "fee_cents": 10000})
        validate_success(api_client.cancel_section(
            sc.section["id"], TEST_USERS["coordinator_headers"]), 200)
        teacher = make_teacher(sc.building["id"], email="td@x.com")
        return sc, teacher

    def test_canceled_section_state_error_outranks_fiscal(self, api):
        """PRD §2.10: "6. **Lifecycle state** — the target's current state
        permits the operation, including terminal-state lockdown
        (`ERR_INVALID_STATE`, `ERR_SECTION_NOT_OPEN`, ...)" precedes
        "11. **Fiscal checks last** — budget exists and is `OPEN` for the charge
        (`ERR_BUDGET_NOT_OPEN`)". PRD §2.10: "A registration attempt against a
        section that is not `PUBLISHED` fails at step 6 as
        `ERR_SECTION_NOT_OPEN`".

        Design: Difficulty/priority_pair_validation_conflict/priority_state_vs_fiscal_section_canceled
        """
        sc, teacher = self._canceled_section_no_budget()
        res = api.create_registration(
            create_registration_payload(teacher["id"], sc.section["id"]),
            make_teacher_headers(teacher["id"]))
        validate_error(res, "ERR_SECTION_NOT_OPEN", expected_status=400)

    def test_fiscal_error_fires_when_state_is_clean(self, api):
        """PRD §3.3: "that budget must exist and be `OPEN`
        (`ERR_BUDGET_NOT_OPEN`) and its `available_cents` must cover the fee
        (`ERR_BUDGET_INSUFFICIENT`)". With the section PUBLISHED (state gate
        passing) and no budget row at all, the fiscal error surfaces.

        Design: Difficulty/priority_pair_validation_conflict/priority_state_vs_fiscal_section_canceled
        """
        sc = setup_catalog_scenario(
            course_overrides={"course_code": "PRIO-2", "clock_hours": 10,
                              "fee_cents": 10000})
        teacher = make_teacher(sc.building["id"], email="td2@x.com")
        res = api.create_registration(
            create_registration_payload(teacher["id"], sc.section["id"]),
            make_teacher_headers(teacher["id"]))
        validate_error(res, "ERR_BUDGET_NOT_OPEN", expected_status=400)


class TestTemporalVsConstraintPriority:
    def _overlap_scenario(self):
        """T1 REGISTERED in S_A (session 09-10 09:00-12:00). S_B overlaps S_A
        (same session window) but its registration window opens 2026-09-01."""
        set_clock()
        building = make_building()
        teacher = make_teacher(building["id"], email="te@x.com")
        instructor = make_instructor(building["id"], email="ie@x.com")
        course_a = make_course(course_code="PA-1", clock_hours=3, fee_cents=0)
        course_b = make_course(course_code="PB-1", clock_hours=3, fee_cents=0)
        sa = make_section(course_a["id"], instructor["id"], building["id"],
                          room="R1", starts_at="2026-09-10T09:00:00Z",
                          ends_at="2026-09-10T12:00:00Z",
                          registration_opens_at="2026-08-01T00:00:00Z",
                          registration_closes_at="2026-09-01T00:00:00Z")
        add_meeting(sa["id"], "2026-09-10T09:30:00Z", "2026-09-10T10:30:00Z", "R1")
        publish_section(sa["id"])
        sb = make_section(course_b["id"], instructor["id"], building["id"],
                          room="R2", starts_at="2026-09-10T09:00:00Z",
                          ends_at="2026-09-10T12:00:00Z",
                          registration_opens_at="2026-09-01T00:00:00Z",
                          registration_closes_at="2026-09-05T00:00:00Z")
        add_meeting(sb["id"], "2026-09-10T09:30:00Z", "2026-09-10T10:30:00Z", "R2")
        publish_section(sb["id"])
        ra = register_teacher(teacher["id"], sa["id"])
        assert ra["status"] == "REGISTERED"
        set_clock("2026-08-15T00:00:00Z")
        return teacher, sa, sb

    def test_not_yet_open_outranks_schedule_conflict(self, api):
        """PRD §2.10: step "9. **Temporal windows** — registration window
        boundaries (`ERR_REGISTRATION_NOT_YET_OPEN`,
        `ERR_REGISTRATION_WINDOW_CLOSED`)" precedes step "10. **Domain
        constraints** — duplicate registration (`ERR_DUPLICATE_REGISTRATION`),
        teacher schedule overlap (`ERR_SCHEDULE_CONFLICT`)".
        PRD §3.3: "the logical clock must sit inside the registration window —
        at or after `registration_opens_at`, else `ERR_REGISTRATION_NOT_YET_OPEN`".

        Design: Difficulty/priority_pair_validation_conflict/priority_temporal_vs_constraint_window_vs_overlap
        """
        teacher, _sa, sb = self._overlap_scenario()
        res = api.create_registration(
            create_registration_payload(teacher["id"], sb["id"]),
            make_teacher_headers(teacher["id"]))
        validate_error(res, "ERR_REGISTRATION_NOT_YET_OPEN", expected_status=400)

    def test_schedule_conflict_fires_when_window_is_open(self, api):
        """PRD §3.3: "the new section's window must not overlap, in half-open
        fashion, the window of any section the teacher is currently `REGISTERED`
        in — adjacency is allowed, and a true overlap is `ERR_SCHEDULE_CONFLICT`
        (HTTP 409)." With the window gate satisfied, the overlap surfaces.

        Design: Difficulty/priority_pair_validation_conflict/priority_temporal_vs_constraint_window_vs_overlap
        """
        set_clock()
        building = make_building()
        teacher = make_teacher(building["id"], email="te2@x.com")
        instructor = make_instructor(building["id"], email="ie2@x.com")
        course_a = make_course(course_code="PA-2", clock_hours=3, fee_cents=0)
        course_c = make_course(course_code="PC-2", clock_hours=3, fee_cents=0)
        sa = make_section(course_a["id"], instructor["id"], building["id"],
                          room="R1", starts_at="2026-09-10T09:00:00Z",
                          ends_at="2026-09-10T12:00:00Z",
                          registration_opens_at="2026-08-01T00:00:00Z",
                          registration_closes_at="2026-09-01T00:00:00Z")
        add_meeting(sa["id"], "2026-09-10T09:30:00Z", "2026-09-10T10:30:00Z", "R1")
        publish_section(sa["id"])
        # Same overlapping session, but this window is already open.
        sc2 = make_section(course_c["id"], instructor["id"], building["id"],
                           room="R3", starts_at="2026-09-10T10:00:00Z",
                           ends_at="2026-09-10T13:00:00Z",
                           registration_opens_at="2026-08-01T00:00:00Z",
                           registration_closes_at="2026-09-01T00:00:00Z")
        add_meeting(sc2["id"], "2026-09-10T10:30:00Z", "2026-09-10T11:30:00Z", "R3")
        publish_section(sc2["id"])
        register_teacher(teacher["id"], sa["id"])
        res = api.create_registration(
            create_registration_payload(teacher["id"], sc2["id"]),
            make_teacher_headers(teacher["id"]))
        validate_error(res, "ERR_SCHEDULE_CONFLICT", expected_status=409)


class TestTeacherScheduleHalfOpen:
    def _three_sections(self):
        set_clock()
        building = make_building()
        teacher = make_teacher(building["id"], email="tm@x.com")
        instructor = make_instructor(building["id"], email="ij@x.com")
        courses = [make_course(course_code=f"OVL-{c}", clock_hours=3, fee_cents=0)
                   for c in "ABC"]
        s1 = make_section(courses[0]["id"], instructor["id"], building["id"],
                          room="R1", starts_at="2026-09-10T09:00:00Z",
                          ends_at="2026-09-10T12:00:00Z",
                          registration_opens_at="2026-08-01T00:00:00Z",
                          registration_closes_at="2026-09-01T00:00:00Z")
        add_meeting(s1["id"], "2026-09-10T09:30:00Z", "2026-09-10T10:30:00Z", "R1")
        publish_section(s1["id"])
        s2 = make_section(courses[1]["id"], instructor["id"], building["id"],
                          room="R2", starts_at="2026-09-10T12:00:00Z",
                          ends_at="2026-09-10T15:00:00Z",
                          registration_opens_at="2026-08-01T00:00:00Z",
                          registration_closes_at="2026-09-01T00:00:00Z")
        add_meeting(s2["id"], "2026-09-10T12:30:00Z", "2026-09-10T13:30:00Z", "R2")
        publish_section(s2["id"])
        s3 = make_section(courses[2]["id"], instructor["id"], building["id"],
                          room="R3", starts_at="2026-09-10T11:00:00Z",
                          ends_at="2026-09-10T13:00:00Z",
                          registration_opens_at="2026-08-01T00:00:00Z",
                          registration_closes_at="2026-09-01T00:00:00Z")
        add_meeting(s3["id"], "2026-09-10T11:30:00Z", "2026-09-10T12:00:00Z", "R3")
        publish_section(s3["id"])
        return teacher, s1, s2, s3

    def test_adjacent_sections_do_not_conflict(self, api):
        """PRD §3.3: "the new section's window must not overlap, in half-open
        fashion, the window of any section the teacher is currently `REGISTERED`
        in — adjacency is allowed, and a true overlap is `ERR_SCHEDULE_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_teacher_schedule_half_open
        """
        teacher, s1, s2, _s3 = self._three_sections()
        r1 = register_teacher(teacher["id"], s1["id"])
        assert r1["status"] == "REGISTERED"
        r2 = register_teacher(teacher["id"], s2["id"])
        assert r2["status"] == "REGISTERED", (
            "S2.starts_at == S1.ends_at is adjacency under half-open semantics")

    def test_interior_overlap_rejected(self, api):
        """PRD §3.3: "the new section's window must not overlap, in half-open
        fashion, the window of any section the teacher is currently `REGISTERED`
        in — adjacency is allowed, and a true overlap is `ERR_SCHEDULE_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_teacher_schedule_half_open
        """
        teacher, s1, s2, s3 = self._three_sections()
        register_teacher(teacher["id"], s1["id"])
        register_teacher(teacher["id"], s2["id"])
        res = api.create_registration(
            create_registration_payload(teacher["id"], s3["id"]),
            make_teacher_headers(teacher["id"]))
        validate_error(res, "ERR_SCHEDULE_CONFLICT", expected_status=409)


def test_duplicate_registration_rejected(api):
    """PRD §3.3: "The teacher must not already hold a `REGISTERED` or
    `WAITLISTED` registration in the same section — a second live registration
    for the same (`teacher_id`, `section_id`) pair is `ERR_DUPLICATE_REGISTRATION`
    (HTTP 409)."

    Design: Corner/validations/duplicate_registration_rejected
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "DP-1", "clock_hours": 5, "fee_cents": 0})
    teacher = make_teacher(sc.building["id"], email="tdp@x.com")
    register_teacher(teacher["id"], sc.section["id"])
    res = api.create_registration(
        create_registration_payload(teacher["id"], sc.section["id"]),
        make_teacher_headers(teacher["id"]))
    validate_error(res, "ERR_DUPLICATE_REGISTRATION", expected_status=409)


def test_prerequisite_unmet_rejected(api):
    """PRD §3.3: "If the course names a prerequisite, the teacher must hold an
    `AWARDED` transcript entry of `source_type` `COURSE_COMPLETION` for that
    prerequisite course, else `ERR_PREREQUISITE_NOT_COMPLETED`."

    Design: Corner/validations/prerequisite_unmet_rejected
    """
    set_clock()
    building = make_building()
    teacher = make_teacher(building["id"], email="tpq@x.com")
    instructor = make_instructor(building["id"], email="ipq@x.com")
    course_a = make_course(course_code="PQ-A", clock_hours=3, fee_cents=0)
    course_b = make_course(course_code="PQ-B", clock_hours=3, fee_cents=0,
                           prerequisite_course_id=course_a["id"])
    sb = make_section(course_b["id"], instructor["id"], building["id"])
    add_meeting(sb["id"])
    publish_section(sb["id"])
    res = api.create_registration(
        create_registration_payload(teacher["id"], sb["id"]),
        make_teacher_headers(teacher["id"]))
    validate_error(res, "ERR_PREREQUISITE_NOT_COMPLETED", expected_status=400)


def test_registration_after_window_close_rejected(api):
    """PRD §3.3: "the logical clock must sit inside the registration window —
    at or after `registration_opens_at`, else `ERR_REGISTRATION_NOT_YET_OPEN`,
    and at or before `registration_closes_at`, else
    `ERR_REGISTRATION_WINDOW_CLOSED`."

    Design: Corner/validations/registration_after_window_close_rejected
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "WC-1", "clock_hours": 5, "fee_cents": 0})
    teacher = make_teacher(sc.building["id"], email="twc@x.com")
    set_clock("2026-08-12T00:00:00Z")  # past closes 2026-08-10; no ops-run ran
    res = api.create_registration(
        create_registration_payload(teacher["id"], sc.section["id"]),
        make_teacher_headers(teacher["id"]))
    validate_error(res, "ERR_REGISTRATION_WINDOW_CLOSED", expected_status=400)


def test_plan_year_mismatch_rejected(api):
    """PRD §3.6: "its school year must contain the activity's date — the
    section's `starts_at` for a registration, the workshop's window for a
    request — else `ERR_PLAN_YEAR_MISMATCH`."

    Design: Corner/validations/plan_year_mismatch_rejected
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "YM-1", "clock_hours": 15, "fee_cents": 0})
    teacher = make_teacher(sc.building["id"], email="tym@x.com")
    admin = make_admin(sc.building["id"], email="aym@x.com")
    plan = make_growth_plan(teacher, school_year="2027-2028", target_credits=2.0,
                            focus_areas=("literacy",))
    validate_success(api.submit_plan(plan["id"], make_teacher_headers(teacher["id"])), 200)
    approved = validate_success(
        api.approve_plan(plan["id"], make_building_admin_headers(admin["id"])), 200)
    assert approved["status"] == "APPROVED"
    res = api.create_registration(
        create_registration_payload(teacher["id"], sc.section["id"],
                                    growth_plan_id=plan["id"],
                                    aligned_focus_area="literacy"),
        make_teacher_headers(teacher["id"]))
    validate_error(res, "ERR_PLAN_YEAR_MISMATCH", expected_status=400)


def test_teacher_cannot_drop_others_registration(api):
    """PRD §2.1: "ownership checks on any resource that references an `Employee`
    (a registration's `teacher_id`, a workshop request's `teacher_id`, a growth
    plan's `teacher_id`) compare that foreign-key field to `X-User-ID`, and a
    mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/teacher_cannot_drop_others_registration
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "RO-1", "clock_hours": 5, "fee_cents": 0})
    t1 = make_teacher(sc.building["id"], email="tro@x.com")
    t2 = make_teacher(sc.building["id"], email="trp@x.com")
    r1 = register_teacher(t1["id"], sc.section["id"])
    res = api.drop_registration(r1["id"], make_teacher_headers(t2["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)
    r1_after = validate_success(api.get_registration(
        r1["id"], TEST_USERS["coordinator_headers"]), 200)
    assert r1_after["status"] == "REGISTERED", "no mutation leaks through the denial"
