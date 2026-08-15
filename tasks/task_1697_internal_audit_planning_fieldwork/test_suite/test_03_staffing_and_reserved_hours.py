"""Staffing integrity: assignment guards, half-open overlap, cancel cascade,
and the reserved-hours compensating invariant (PRD §3.4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assign_auditor,
    create_auditor,
    create_engagement_assignment_payload,
    create_engagement_payload,
    create_entity,
    create_plan,
    get_plan,
    get_success_data,
    make_manager_headers,
    set_clock,
    setup_approved_plan_with_engagement,
    validate_error,
    validate_success,
)


def _two_engagement_setup(api):
    """Plan with two PLANNED engagements on two different entities (keeps the
    90-day cooling rule out of scope); returns (plan, eng1, eng2, mgr, staff)."""
    set_clock()
    ent1 = create_entity(name="Entity O1")
    ent2 = create_entity(name="Entity O2")
    mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
    staff = create_auditor(full_name="Sam Staff", grade="STAFF")
    mgr_h = make_manager_headers(mgr["id"])
    plan = create_plan()
    eng1 = get_success_data(api.create_engagement(
        create_engagement_payload(plan["id"], ent1["id"], plan["version"], title="Eng O1",
                                  budget_hours=80),
        mgr_h,
    ))
    plan_v2 = get_plan(plan["id"])["version"]
    eng2 = get_success_data(api.create_engagement(
        create_engagement_payload(plan["id"], ent2["id"], plan_v2, title="Eng O2",
                                  budget_hours=80),
        mgr_h,
    ))
    return plan, eng1, eng2, mgr, staff


class TestAssignmentOverlap:
    def test_overlapping_window_rejected(self, api):
        """PRD §3.4: "an auditor's assignment windows may not overlap: because
        ends are exclusive, a collision exists precisely when another `ACTIVE`
        assignment of the same auditor starts before the new window's end and
        the new window starts before that existing assignment's end"
        PRD §3.4: "A colliding create fails with `ERR_ASSIGNMENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/auditor_assignment_half_open_overlap
        """
        _, eng1, eng2, mgr, staff = _two_engagement_setup(api)
        mgr_h = make_manager_headers(mgr["id"])
        # Existing window [2026-02-01, 2026-03-01).
        assign_auditor(eng1["id"], staff, role_in_engagement="STAFF", allocated_hours=40, actor=mgr)

        # [2026-02-15, 2026-03-15) intersects: 02-01 < 03-15 and 02-15 < 03-01.
        overlapping = api.create_engagement_assignment(
            create_engagement_assignment_payload(
                eng2["id"], staff["id"], role_in_engagement="STAFF", allocated_hours=20,
                start_date="2026-02-15T00:00:00Z", end_date="2026-03-15T00:00:00Z",
            ),
            mgr_h,
        )
        validate_error(overlapping, ApiErrorId.ERR_ASSIGNMENT_OVERLAP, expected_status=409)

    def test_touching_window_allowed_and_reserves_hours(self, api):
        """PRD §3.4: "windows that merely touch, one ending exactly when the
        other begins, are permitted."
        PRD §3.4: "Each creation reserves hours on the engagement:
        `reserved_hours` increases by the assignment's `allocated_hours`"

        Design: Difficulty/resource_temporal_overlap/auditor_assignment_half_open_overlap
        """
        _, eng1, eng2, mgr, staff = _two_engagement_setup(api)
        mgr_h = make_manager_headers(mgr["id"])
        assign_auditor(eng1["id"], staff, role_in_engagement="STAFF", allocated_hours=40, actor=mgr)

        # [2026-03-01, 2026-04-01) touches the existing window's exclusive end.
        adjacent = get_success_data(api.create_engagement_assignment(
            create_engagement_assignment_payload(
                eng2["id"], staff["id"], role_in_engagement="STAFF", allocated_hours=30,
                start_date="2026-03-01T00:00:00Z", end_date="2026-04-01T00:00:00Z",
            ),
            mgr_h,
        ))
        assert adjacent["status"] == "ACTIVE"

        eng2_after = get_success_data(api.get_engagement(eng2["id"], mgr_h))
        assert eng2_after["reserved_hours"] == 30, (
            "Only the accepted assignment reserves hours on eng2"
        )


class TestAssignmentGuards:
    def test_assignment_guard_violations(self, api, admin_headers):
        """PRD §3.4: "An auditor may hold only one `ACTIVE` assignment on the
        same engagement; a duplicate fails with `ERR_DUPLICATE_ASSIGNMENT`."
        PRD §3.4: "an `end_date` not strictly after the `start_date` fails with
        `ERR_ASSIGNMENT_WINDOW_INVALID`."
        PRD §3.4: "Assigning an auditor whose record is `INACTIVE` is rejected
        with `ERR_AUDITOR_INACTIVE`"
        PRD §3.4: "deactivating an already-inactive auditor fails with
        `ERR_AUDITOR_INACTIVE`"
        PRD §3.4: "An assignment may be cancelled while it is `ACTIVE` — a
        second cancel fails with `ERR_ASSIGNMENT_INVALID_STATE`"

        Design: Corner/state_machines/assignment_guard_violations
        """
        _, eng1, eng2, mgr, staff = _two_engagement_setup(api)
        mgr_h = make_manager_headers(mgr["id"])
        a2 = create_auditor(full_name="Ada A2", grade="SENIOR")
        asg1 = assign_auditor(eng1["id"], staff, role_in_engagement="STAFF",
                              allocated_hours=40, actor=mgr)

        # Duplicate ACTIVE assignment of the same auditor on the engagement.
        dup = api.create_engagement_assignment(
            create_engagement_assignment_payload(
                eng1["id"], staff["id"], role_in_engagement="REVIEWER", allocated_hours=10,
                start_date="2026-02-10T00:00:00Z", end_date="2026-02-20T00:00:00Z",
            ),
            mgr_h,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_ASSIGNMENT, expected_status=409)

        # Zero-length window: end_date == start_date is not strictly after.
        zero_window = api.create_engagement_assignment(
            create_engagement_assignment_payload(
                eng2["id"], a2["id"], role_in_engagement="STAFF", allocated_hours=10,
                start_date="2026-03-01T00:00:00Z", end_date="2026-03-01T00:00:00Z",
            ),
            mgr_h,
        )
        validate_error(zero_window, ApiErrorId.ERR_ASSIGNMENT_WINDOW_INVALID, expected_status=422)

        # Assigning an INACTIVE auditor is rejected.
        get_success_data(api.deactivate_auditor(a2["id"], admin_headers))
        inactive = api.create_engagement_assignment(
            create_engagement_assignment_payload(
                eng2["id"], a2["id"], role_in_engagement="STAFF", allocated_hours=10,
                start_date="2026-03-01T00:00:00Z", end_date="2026-04-01T00:00:00Z",
            ),
            mgr_h,
        )
        validate_error(inactive, ApiErrorId.ERR_AUDITOR_INACTIVE, expected_status=409)

        # Double deactivation is rejected.
        redeactivate = api.deactivate_auditor(a2["id"], admin_headers)
        validate_error(redeactivate, ApiErrorId.ERR_AUDITOR_INACTIVE, expected_status=409)

        # Double cancel is rejected; the assignment stays CANCELLED.
        cancelled = get_success_data(api.cancel_engagement_assignment(asg1["id"], mgr_h))
        assert cancelled["status"] == "CANCELLED"
        recancel = api.cancel_engagement_assignment(asg1["id"], mgr_h)
        validate_error(recancel, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE, expected_status=409)
        eng1_after = get_success_data(api.get_engagement(eng1["id"], mgr_h))
        assert eng1_after["reserved_hours"] == 0

    def test_assignment_body_fk_integrity(self, api):
        """PRD §2.11: "Requests that address resources through identifying
        fields validate those references in a strict order: path identifiers
        first, left to right, and then foreign keys carried in the request body
        in the order the endpoint declares them."
        PRD §3.4: "unknown auditor or assignment references yield
        `ERR_AUDITOR_NOT_FOUND` and `ERR_ASSIGNMENT_NOT_FOUND` respectively."

        Design: Corner/entities/assignment_body_fk_integrity
        """
        _, eng1, _, mgr, staff = _two_engagement_setup(api)
        mgr_h = make_manager_headers(mgr["id"])

        # Both FKs bogus: engagement_id is declared first, so it surfaces.
        both_bogus = api.create_engagement_assignment(
            create_engagement_assignment_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                role_in_engagement="STAFF", allocated_hours=10,
            ),
            mgr_h,
        )
        validate_error(both_bogus, ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND, expected_status=404)

        # Valid engagement, bogus auditor: the auditor reference surfaces.
        bogus_auditor = api.create_engagement_assignment(
            create_engagement_assignment_payload(
                eng1["id"], NON_EXISTENT_UUID,
                role_in_engagement="STAFF", allocated_hours=10,
            ),
            mgr_h,
        )
        validate_error(bogus_auditor, ApiErrorId.ERR_AUDITOR_NOT_FOUND, expected_status=404)


class TestReservedHoursInvariant:
    def test_reserved_hours_create_accumulates(self, api):
        """PRD §3.4: "Each creation reserves hours on the engagement:
        `reserved_hours` increases by the assignment's `allocated_hours`,
        maintaining the invariant that `reserved_hours` always equals the sum
        of `allocated_hours` over the engagement's `ACTIVE` assignments."

        Design: Difficulty/compensating_invariant/assignment_reserved_hours_create_cancel_neutral
        """
        set_clock()
        ent = create_entity(name="Entity H1")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        a1 = create_auditor(full_name="Ann A1", grade="STAFF")
        a2 = create_auditor(full_name="Bob A2", grade="SENIOR")
        mgr_h = make_manager_headers(mgr["id"])
        plan = create_plan()
        eng = get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent["id"], plan["version"], title="Eng H1",
                                      budget_hours=200),
            mgr_h,
        ))
        assert eng["reserved_hours"] == 0

        assign_auditor(eng["id"], a1, role_in_engagement="LEAD", allocated_hours=40, actor=mgr)
        after_first = get_success_data(api.get_engagement(eng["id"], mgr_h))
        assert after_first["reserved_hours"] == 40

        assign_auditor(eng["id"], a2, role_in_engagement="STAFF", allocated_hours=25, actor=mgr)
        after_second = get_success_data(api.get_engagement(eng["id"], mgr_h))
        assert after_second["reserved_hours"] == 65, (
            "reserved_hours accumulates 0 -> 40 -> 65 over the two creations"
        )

    def test_reserved_hours_cancel_compensates_to_zero(self, api):
        """PRD §3.4: "Cancellation is a compensating action: the engagement's
        `reserved_hours` decreases by the released `allocated_hours`,
        preserving the reservation invariant."

        Design: Difficulty/compensating_invariant/assignment_reserved_hours_create_cancel_neutral
        """
        set_clock()
        ent = create_entity(name="Entity H1")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        a1 = create_auditor(full_name="Ann A1", grade="STAFF")
        a2 = create_auditor(full_name="Bob A2", grade="SENIOR")
        mgr_h = make_manager_headers(mgr["id"])
        plan = create_plan()
        eng = get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent["id"], plan["version"], title="Eng H1",
                                      budget_hours=200),
            mgr_h,
        ))
        asg1 = assign_auditor(eng["id"], a1, role_in_engagement="LEAD", allocated_hours=40, actor=mgr)
        asg2 = assign_auditor(eng["id"], a2, role_in_engagement="STAFF", allocated_hours=25, actor=mgr)

        get_success_data(api.cancel_engagement_assignment(asg1["id"], mgr_h))
        after_first_cancel = get_success_data(api.get_engagement(eng["id"], mgr_h))
        assert after_first_cancel["reserved_hours"] == 25

        get_success_data(api.cancel_engagement_assignment(asg2["id"], mgr_h))
        after_second_cancel = get_success_data(api.get_engagement(eng["id"], mgr_h))
        assert after_second_cancel["reserved_hours"] == 0, (
            "Create(40)+create(25) paired with their cancels returns the "
            "engagement to the initial 0 — no drift"
        )


class TestEngagementCancelCascade:
    def test_engagement_cancel_cascades_and_terminal_lockdown(self, api):
        """PRD §3.4: "Cancellation cascades downward: every `ACTIVE` assignment
        of the engagement transitions to `CANCELLED` and `reserved_hours` is
        recomputed, and the plan ledger is synchronized — the plan's
        `engagement_count` and `high_risk_coverage_pct` are recomputed"
        PRD §3.3: "The `engagement_count` is the number of the plan's
        engagements whose status is anything other than `CANCELLED`."
        PRD §3.4: "Cancelling a whole engagement is possible from `PLANNED` or
        `SCOPED` only, moving it to the terminal `CANCELLED` status; any other
        from-state fails with `ERR_ENGAGEMENT_INVALID_STATE`."

        Design: Corner/state_machines/engagement_cancel_cascades_and_terminal_lockdown
        """
        set_clock()
        ent = create_entity(name="E")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        staff = create_auditor(full_name="Sam Staff", grade="STAFF")
        mgr_h = make_manager_headers(mgr["id"])
        plan = create_plan()
        eng = get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent["id"], plan["version"], title="G",
                                      budget_hours=50),
            mgr_h,
        ))
        asg = assign_auditor(eng["id"], staff, role_in_engagement="STAFF",
                             allocated_hours=40, actor=mgr)

        cancelled = get_success_data(api.cancel_engagement(eng["id"], mgr_h))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["reserved_hours"] == 0

        asg_after = get_success_data(api.get_engagement_assignment(asg["id"], mgr_h))
        assert asg_after["status"] == "CANCELLED", "Cascade down cancels staffing"

        plan_after = get_plan(plan["id"])
        assert plan_after["engagement_count"] == 0, "CANCELLED engagements are excluded"

        # Terminal lockdown: no further transitions from CANCELLED.
        scope = api.scope_engagement(eng["id"], mgr_h)
        validate_error(scope, ApiErrorId.ERR_ENGAGEMENT_INVALID_STATE, expected_status=409)


class TestBeginFieldworkGates:
    def test_engagement_begin_fieldwork_requires_approved_plan(self, api, cae_headers, committee_headers):
        """PRD §3.4: "Beginning fieldwork moves `SCOPED` to `FIELDWORK` and
        carries two cross-entity gates evaluated after the state check: the
        owning plan must be `APPROVED` (else `ERR_PLAN_NOT_APPROVED`), and the
        engagement must have at least one `ACTIVE` assignment whose
        `role_in_engagement` is `LEAD` (else `ERR_NO_LEAD_ASSIGNED`)."

        Design: Corner/state_machines/engagement_begin_fieldwork_requires_approved_plan
        """
        set_clock()
        ent = create_entity(name="E")
        mgr = create_auditor(full_name="Mary Mgr", grade="MANAGER")
        mgr_h = make_manager_headers(mgr["id"])
        plan = create_plan()  # stays DRAFT — never submitted
        eng = get_success_data(api.create_engagement(
            create_engagement_payload(plan["id"], ent["id"], plan["version"], title="G",
                                      budget_hours=50),
            mgr_h,
        ))
        get_success_data(api.scope_engagement(eng["id"], mgr_h))
        assign_auditor(eng["id"], mgr, role_in_engagement="LEAD", allocated_hours=40, actor=mgr)

        resp = api.begin_fieldwork(eng["id"], mgr_h)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_APPROVED, expected_status=409)
        assert get_success_data(api.get_engagement(eng["id"], mgr_h))["status"] == "SCOPED"

    def test_engagement_begin_fieldwork_requires_lead_assignment(self, api):
        """PRD §3.4: "the engagement must have at least one `ACTIVE` assignment
        whose `role_in_engagement` is `LEAD` (else `ERR_NO_LEAD_ASSIGNED`)."

        Design: Corner/state_machines/engagement_begin_fieldwork_requires_lead_assignment
        """
        ctx = setup_approved_plan_with_engagement(entity_name="E", budget_hours=50)
        mgr, staff, eng = ctx["mgr"], ctx["staff"], ctx["engagement"]
        mgr_h = make_manager_headers(mgr["id"])
        get_success_data(api.scope_engagement(eng["id"], mgr_h))
        # Only a STAFF assignment — the LEAD gate is not satisfied.
        assign_auditor(eng["id"], staff, role_in_engagement="STAFF", allocated_hours=40, actor=mgr)

        resp = api.begin_fieldwork(eng["id"], mgr_h)
        validate_error(resp, ApiErrorId.ERR_NO_LEAD_ASSIGNED, expected_status=422)
        assert get_success_data(api.get_engagement(eng["id"], mgr_h))["status"] == "SCOPED"
