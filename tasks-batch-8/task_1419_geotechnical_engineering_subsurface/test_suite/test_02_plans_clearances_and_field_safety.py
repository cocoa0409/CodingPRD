"""Boring-plan lifecycle, utility-clearance tickets, expiry boundaries, and
the state-vs-safety evaluation-order interaction on the drill endpoint."""
import pytest

from test_helpers import (
    FA,
    PM,
    SE,
    ApiErrorId,
    api_client,
    assert_boring,
    assert_boring_plan,
    assert_utility_clearance,
    create_approved_plan,
    create_boring_plan_payload,
    create_client_and_project,
    create_subcontractor,
    add_boring,
    drill_boring,
    file_clearance,
    get_success_data,
    make_drilling_sub_headers,
    parse_instant,
    schedule_rig,
    set_logical_clock,
    setup_boring_cleared,
    setup_drilled_boring,
    setup_fieldwork_project,
    setup_scoped_project,
    transition_boring,
    transition_clearance,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# BoringPlan approval exclusivity and lockdown
# ---------------------------------------------------------------------------

def test_plan_approve_rejected_when_plan_already_active(api):
    """PRD section 3.1: "A `ProjectManager` then either returns the plan to
    `DRAFT` for rework (`SUBMITTED` → `DRAFT`, the revise loop) or approves it
    (`SUBMITTED` → `APPROVED`). Approval is guarded twice: the project must
    still be in `DRAFT` or `SCOPED` — otherwise `ERR_PROJECT_STATE_FORBIDS` —
    and no other boring plan of the same project may stand in `APPROVED` or
    `LOCKED`, otherwise the approval is rejected with
    `ERR_PLAN_ALREADY_ACTIVE` (HTTP 409)".

    Design: Corner/state_machines/plan_approve_rejected_when_plan_already_active
    """
    _client, project = create_client_and_project()
    plan1 = create_approved_plan(project)
    assert_boring_plan(plan1)

    fresh = get_success_data(api.get_project(project["id"], PM))
    plan2 = get_success_data(api.create_boring_plan(
        project["id"],
        create_boring_plan_payload(fresh["version"], planned_boring_count=2,
                                   planned_total_footage_ft=60),
        SE))
    plan2 = get_success_data(api.transition_boring_plan(
        plan2["id"], {"to": "SUBMITTED"}, SE))

    resp = api.transition_boring_plan(plan2["id"], {"to": "APPROVED"}, PM)
    validate_error(resp, ApiErrorId.ERR_PLAN_ALREADY_ACTIVE)

    plan1_after = get_success_data(api.get_boring_plan(plan1["id"], PM))
    assert plan1_after["status"] == "APPROVED"


def test_locked_plan_rejects_direct_boring_create(api):
    """PRD section 3.1: "Once field work begins, the plan freezes: the first
    boring of a plan to reach `DRILLED` flips the plan from `APPROVED` to
    `LOCKED` automatically, bumps the plan's `version`, and freezes plan
    scope" and "A `StaffEngineer` adds borings directly only to an `APPROVED`
    plan; attempting to add one to a `LOCKED` or `SUPERSEDED` plan is rejected
    with `ERR_PLAN_NOT_EDITABLE` (HTTP 409)."

    Design: Corner/state_machines/locked_plan_rejects_direct_boring_create
    """
    ctx = setup_drilled_boring()
    plan = get_success_data(api.get_boring_plan(ctx["plan"]["id"], SE))
    assert plan["status"] == "LOCKED"

    resp = api.create_boring(
        plan["id"], {"boring_no": "B-2", "planned_depth_ft": 25}, SE)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_EDITABLE)


# ---------------------------------------------------------------------------
# Clearance defaults and ticket uniqueness
# ---------------------------------------------------------------------------

def test_clearance_defaults_valid_days_14(api):
    """PRD section 3.2: "A `StaffEngineer` files a one-call UtilityClearance
    ticket against a boring with its `ticket_number` — unique per boring,
    duplicates rejected as `ERR_DUPLICATE_TICKET` — the `issued_on` timestamp,
    and an optional `valid_days` defaulting to 14. The system computes
    `expires_on` as `issued_on` plus `valid_days` times twenty-four hours."
    and "A ticket starts `FILED`".

    Design: Corner/entities/clearance_defaults_valid_days_14
    """
    ctx = setup_scoped_project(schedule_first_rig=False, clear_tickets=False)
    boring = ctx["boring"]

    # File without valid_days so the default applies.
    resp = api.create_clearance(
        boring["id"],
        {"ticket_number": "T-99", "issued_on": "2026-08-01T00:00:00Z"}, SE)
    clearance = validate_success(resp, 201)
    assert_utility_clearance(clearance)
    assert clearance["valid_days"] == 14
    assert clearance["status"] == "FILED"
    expected = parse_instant("2026-08-01T00:00:00Z")
    from datetime import timedelta
    expected = expected + timedelta(days=14)
    assert parse_instant(clearance["expires_on"]) == expected, (
        f"expires_on must be issued_on + 14 days "
        f"(2026-08-15T00:00:00Z), got {clearance['expires_on']}"
    )


def test_clearance_duplicate_ticket_rejected(api):
    """PRD section 3.2: "A `StaffEngineer` files a one-call UtilityClearance
    ticket against a boring with its `ticket_number` — unique per boring,
    duplicates rejected as `ERR_DUPLICATE_TICKET`".

    Design: Corner/validations/clearance_duplicate_ticket_rejected
    """
    ctx = setup_scoped_project(schedule_first_rig=False, clear_tickets=False)
    boring = ctx["boring"]
    # The setup already filed T-1 on this boring.
    assert ctx["clearance"]["ticket_number"] == "T-1"

    dup = api.create_clearance(
        boring["id"],
        {"ticket_number": "T-1", "issued_on": "2026-08-02T00:00:00Z",
         "valid_days": 14}, SE)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_TICKET)

    ok = api.create_clearance(
        boring["id"],
        {"ticket_number": "T-2", "issued_on": "2026-08-02T00:00:00Z",
         "valid_days": 14}, SE)
    validate_success(ok, 201)


# ---------------------------------------------------------------------------
# Clearance expiry — inclusive boundary (difficulty instance, two tests)
# ---------------------------------------------------------------------------

class TestClearanceExpiryInclusiveBoundary:
    """The validity boundary is inclusive: drilling at exactly expires_on
    succeeds, and the expiry sweep only fires strictly past expires_on."""

    def test_drilling_at_exact_expiry_succeeds(self, api):
        """PRD section 3.2: "The ticket is valid while the current logical
        time is less than or equal to `expires_on`: the boundary is inclusive,
        so clearing or drilling at exactly `expires_on` succeeds, while one
        second later fails with `ERR_CLEARANCE_EXPIRED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/clearance_expiry_inclusive_boundary
        """
        ctx = setup_boring_cleared()
        clearance = get_success_data(api.get_clearance(ctx["clearance"]["id"], SE))
        # issued 2026-08-01T00:00:00Z with the 14-day default.
        assert parse_instant(clearance["expires_on"]) == parse_instant(
            "2026-08-15T00:00:00Z")

        set_logical_clock("2026-08-15T00:00:00Z")
        bored = drill_boring(ctx["boring"]["id"], ctx["subcontractor"]["id"])
        assert_boring(bored)
        assert bored["status"] == "DRILLED", (
            "Drilling at exactly expires_on must succeed (inclusive boundary)"
        )

    def test_no_expiry_sweep_at_exact_expiry(self, api):
        """PRD section 2.6: "Advancing the clock performs a sweep: every
        utility clearance ticket in `FILED` or `CLEARED` whose `expires_on`
        now lies strictly in the past transitions to `EXPIRED`."
        PRD section 3.2: "The ticket is valid while the current logical time
        is less than or equal to `expires_on`: the boundary is inclusive, so
        clearing or drilling at exactly `expires_on` succeeds, while one
        second later fails with `ERR_CLEARANCE_EXPIRED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/clearance_expiry_inclusive_boundary
        """
        ctx = setup_fieldwork_project()
        # A second ticket still FILED at the boundary instant.
        second = file_clearance(ctx["boring"]["id"], ticket_number="T-2",
                                clear=False)
        set_logical_clock("2026-08-15T00:00:00Z")  # exactly expires_on

        cleared = transition_clearance(second["id"], "CLEARED")
        assert cleared["status"] == "CLEARED", (
            "Clearing at exactly expires_on must succeed (inclusive boundary)"
        )
        first = get_success_data(api.get_clearance(ctx["clearance"]["id"], SE))
        assert first["status"] == "CLEARED", (
            "A ticket whose expires_on equals the logical time is not swept; "
            "the sweep only fires strictly past expires_on"
        )


def test_clearance_expiry_plus_one_second_rejected(api):
    """PRD section 3.2: "The ticket is valid while the current logical time
    is less than or equal to `expires_on`: the boundary is inclusive, so
    clearing or drilling at exactly `expires_on` succeeds, while one second
    later fails with `ERR_CLEARANCE_EXPIRED` (HTTP 409)."
    PRD section 2.6: "Advancing the clock performs a sweep: every utility
    clearance ticket in `FILED` or `CLEARED` whose `expires_on` now lies
    strictly in the past transitions to `EXPIRED`."

    Design: Corner/calculations/clearance_expiry_plus_one_second_rejected
    """
    ctx = setup_boring_cleared()
    set_logical_clock("2026-08-15T00:00:01Z")  # one second past expires_on

    resp = api.transition_boring(
        ctx["boring"]["id"],
        {"to": "DRILLED", "actual_depth_ft": 30, "rock_depth_ft": 0,
         "groundwater_depth_ft": 12, "avg_n60": 12},
        make_drilling_sub_headers(ctx["subcontractor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_EXPIRED)

    clearance = get_success_data(api.get_clearance(ctx["clearance"]["id"], SE))
    assert clearance["status"] == "EXPIRED", (
        "The clock sweep flips a ticket strictly past expires_on to EXPIRED"
    )


# ---------------------------------------------------------------------------
# Evaluation order: state (category 5) masks field-safety (category 6)
# ---------------------------------------------------------------------------

class TestDrillStateErrorBeatsClearanceExpired:
    """When the drill request violates both a state rule and the clearance
    safety gate, the earlier category's error is surfaced."""

    def test_state_error_reported_when_boring_not_cleared_and_ticket_expired(self, api):
        """PRD section 2.9: "Every request is evaluated against an ordered
        pipeline of check categories. A failure in an earlier category aborts
        evaluation, so a request never surfaces a later category's error when
        an earlier one applies", with "5. **State legality** — the target
        resource's current state permits the requested transition per its
        state machine, parent states permit the child operation, and the OCC
        checks of §2.7 pass." preceding "6. **Field-safety gates** —
        clearance presence and validity, and the frozen-posture freeze
        (`ERR_CLEARANCE_MISSING`, `ERR_CLEARANCE_EXPIRED`, `ERR_POSTURE_FROZEN`,
        all 409)."
        PRD section 3: "where a transition has no guard listed, only the
        from-state itself constrains it, and requesting any transition from a
        state that does not offer it is rejected with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/drill_state_error_beats_clearance_expired_safety
        """
        # Boring stays SCHEDULED (never CLEARED) and its ticket is swept to
        # EXPIRED: the drill violates category 5 (SCHEDULED does not offer
        # DRILLED) and category 6 (expired clearance) simultaneously.
        ctx = setup_fieldwork_project()
        from test_helpers import mobilize_assignment
        mobilize_assignment(ctx["assignment"]["id"], ctx["subcontractor"]["id"])
        set_logical_clock("2026-08-16T00:00:00Z")  # strictly past expires_on

        resp = api.transition_boring(
            ctx["boring"]["id"],
            {"to": "DRILLED", "actual_depth_ft": 30, "rock_depth_ft": 0,
             "groundwater_depth_ft": 12, "avg_n60": 12},
            make_drilling_sub_headers(ctx["subcontractor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409

    def test_safety_error_surfaces_once_state_is_legal(self, api):
        """PRD section 2.9: "A failure in an earlier category aborts
        evaluation, so a request never surfaces a later category's error when
        an earlier one applies" — with the state gate satisfied (CLEARED ->
        DRILLED is a legal transition), evaluation reaches "6.
        **Field-safety gates** — clearance presence and validity, and the
        frozen-posture freeze (`ERR_CLEARANCE_MISSING`, `ERR_CLEARANCE_EXPIRED`,
        `ERR_POSTURE_FROZEN`, all 409)."
        PRD section 3.3: "a `CLEARED` ticket of the boring must still be
        valid (`ERR_CLEARANCE_EXPIRED`)".

        Design: Difficulty/priority_pair_validation_conflict/drill_state_error_beats_clearance_expired_safety
        """
        ctx = setup_boring_cleared()  # boring CLEARED, ticket CLEARED, rig MOBILIZED
        set_logical_clock("2026-08-16T00:00:00Z")  # strictly past expires_on

        resp = api.transition_boring(
            ctx["boring"]["id"],
            {"to": "DRILLED", "actual_depth_ft": 30, "rock_depth_ft": 0,
             "groundwater_depth_ft": 12, "avg_n60": 12},
            make_drilling_sub_headers(ctx["subcontractor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CLEARANCE_EXPIRED)
        assert resp.status_code == 409
