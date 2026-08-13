"""Safety plan lifecycle, safety-hold interlocks, and lockout-tagout window
rules (PRD section 3.3), including the lockout clearance buffer and the
safety-before-temporal priority pair."""
from test_helpers import (
    ApiErrorId,
    create_active_safety_plan,
    create_approved_rigging_plan,
    create_lockout_window,
    create_lockout_window_payload,
    create_project,
    create_safety_plan_payload,
    find_lockout_window,
    get_project,
    set_clock,
    setup_project_installing,
    validate_error,
    validate_success,
)


def test_safety_plan_exists(api, so_headers):
    """PRD section 3.3: "Each project may have at most one safety plan; an
    attempt to create a second is rejected with `ERR_SAFETY_PLAN_EXISTS`."

    Design: Corner/validations/safety_plan_exists
    """
    project = create_project(name="One Plan Job", site_address="42 Plant Rd")
    first = validate_success(
        api.create_safety_plan(create_safety_plan_payload(project_id=project["id"]), so_headers),
        201,
    )
    assert first["status"] == "DRAFT"

    resp = api.create_safety_plan(
        create_safety_plan_payload(
            project_id=project["id"],
            plan_document_ref="DOC-SP-2",
            loto_procedure_ref="DOC-LOTO-2",
        ),
        so_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SAFETY_PLAN_EXISTS)


def test_safety_plan_double_suspend_rejected(api, so_headers):
    """PRD section 3.3: "When the `SafetyOfficer` suspends an `ACTIVE` plan,
    the plan moves to `SUSPENDED` and three things happen in sequence: first
    the project's `hold_status` flips from `CLEAR` to `SAFETY_HOLD`; then, as
    a consequence, every labor entry of the project sitting in `SUBMITTED`
    status — that is, awaiting payroll approval — is automatically rejected
    with `rejection_reason` recorded as `SAFETY_HOLD`; finally the project's
    derived fields are re-evaluated and its `version` increments by one."

    Design: Corner/state_machines/safety_plan_double_suspend_rejected
    """
    project = create_project(name="SM9 Job", site_address="31 Plant Rd")
    plan = create_active_safety_plan(project["id"])

    suspended = validate_success(api.suspend_safety_plan(plan["id"], so_headers))
    assert suspended["status"] == "SUSPENDED"

    resp = api.suspend_safety_plan(plan["id"], so_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    plans = api.list_safety_plans(project["id"], so_headers).json()["data"]
    assert plans[0]["status"] == "SUSPENDED", "Plan must remain SUSPENDED"
    assert get_project(project["id"])["hold_status"] == "SAFETY_HOLD", (
        "The hold must remain in place; a rejected suspend does not re-fire the cascade"
    )


def test_lockout_release_from_scheduled_rejected(api, so_headers):
    """PRD section 3.3: "An `ACTIVE` window never releases itself when its end
    passes — physical locks require manual removal — so the `SafetyOfficer`
    releases it explicitly, moving it to `RELEASED`."

    Design: Corner/state_machines/lockout_release_from_scheduled_rejected
    """
    project = create_project(name="SM8 Job", site_address="30 Plant Rd")
    create_active_safety_plan(project["id"])
    window = create_lockout_window(project["id"])
    assert window["status"] == "SCHEDULED"

    resp = api.release_lockout_window(window["id"], so_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    assert find_lockout_window(project["id"], window["id"])["status"] == "SCHEDULED"


def test_invalid_window(api, so_headers):
    """PRD section 3.3: "The window must be well-formed — the end strictly
    after the start — or creation fails with `ERR_INVALID_WINDOW`."

    Design: Corner/validations/invalid_window
    """
    project = create_project(name="Zero Window Job", site_address="52 Plant Rd")
    create_active_safety_plan(project["id"])

    resp = api.create_lockout_window(
        create_lockout_window_payload(
            project_id=project["id"],
            starts_at="2026-08-10T10:00:00Z",
            ends_at="2026-08-10T10:00:00Z",  # zero-length window
        ),
        so_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


def test_lockout_exact_thirty_minute_clearance_passes(api, so_headers):
    """PRD section 3.3: "Beyond well-formedness, a clearance rule protects each
    feeder: within the same project on the same `feeder_id`, a new window must
    keep at least a thirty-minute clearance from every existing window in
    `SCHEDULED` or `ACTIVE` status, meaning the new window either starts at
    least thirty minutes after the existing window ends or ends at least thirty
    minutes before the existing window starts. Exactly thirty minutes of
    clearance satisfies the rule; anything less is rejected with
    `ERR_LOCKOUT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/lockout_buffer_clearance
    """
    project = create_project(name="LOTO Job", site_address="17 Plant Rd")
    create_active_safety_plan(project["id"])
    first = create_lockout_window(project["id"], feeder_id="F-1")
    assert first["status"] == "SCHEDULED"

    # Exactly thirty minutes after the existing window ends (14:00 -> 14:30).
    resp = api.create_lockout_window(
        create_lockout_window_payload(
            project_id=project["id"],
            feeder_id="F-1",
            starts_at="2026-08-10T14:30:00Z",
            ends_at="2026-08-10T16:00:00Z",
        ),
        so_headers,
    )
    second = validate_success(resp, 201)
    assert second["status"] == "SCHEDULED", (
        "Exactly thirty minutes of clearance must satisfy the buffer rule"
    )


def test_lockout_short_gap_rejected_but_other_feeder_ok(api, so_headers):
    """PRD section 3.3: "Exactly thirty minutes of clearance satisfies the
    rule; anything less is rejected with `ERR_LOCKOUT_CONFLICT`."
    PRD section 2.9: "Electrical feeders, by contrast, are pooled per project:
    lockout clearance rules compare windows on the same feeder within the same
    project only."

    Design: Difficulty/resource_temporal_overlap/lockout_buffer_clearance
    """
    project = create_project(name="LOTO Job", site_address="17 Plant Rd")
    create_active_safety_plan(project["id"])
    create_lockout_window(project["id"], feeder_id="F-1")

    # Fifteen minutes of clearance: violates the buffer.
    resp = api.create_lockout_window(
        create_lockout_window_payload(
            project_id=project["id"],
            feeder_id="F-1",
            starts_at="2026-08-10T14:15:00Z",
            ends_at="2026-08-10T15:00:00Z",
        ),
        so_headers,
    )
    validate_error(resp, ApiErrorId.ERR_LOCKOUT_CONFLICT)

    # The same overlapping hours on a different feeder are pooled separately.
    resp = api.create_lockout_window(
        create_lockout_window_payload(
            project_id=project["id"],
            feeder_id="F-2",
            starts_at="2026-08-10T11:00:00Z",
            ends_at="2026-08-10T12:00:00Z",
        ),
        so_headers,
    )
    other = validate_success(resp, 201)
    assert other["status"] == "SCHEDULED"


def test_lockout_create_with_suspended_plan_fails_safety_not_conflict(api, so_headers):
    """PRD section 3.3: "An active plan is a hard prerequisite for two things:
    scheduling any lockout window, and the very first project advance from
    `AWARDED` to `MOBILIZED` — both fail with `ERR_SAFETY_PLAN_NOT_ACTIVE` when
    no plan of the project stands `ACTIVE`."
    PRD section 2.6: "The safety interlocks run first: the project safety-hold
    check (`ERR_SAFETY_HOLD`) precedes the active-safety-plan check
    (`ERR_SAFETY_PLAN_NOT_ACTIVE`)."
    PRD section 2.6: "Temporal rules are evaluated after those
    (`ERR_INVALID_WINDOW`, `ERR_LOCKOUT_CONFLICT`,
    `ERR_CRANE_WINDOW_CONFLICT`, `ERR_OUTSIDE_LIFT_WINDOW`), then the fiscal
    rules (`ERR_NTE_EXCEEDED`, `ERR_FINAL_INVOICE_EXISTS`,
    `ERR_NO_BILLABLE_WORK`)."

    Design: Difficulty/priority_pair_validation_conflict/lockout_safety_beats_temporal
    """
    project = create_project(name="Lockout Conflict Job", site_address="11 Plant Rd")
    plan = create_active_safety_plan(project["id"])
    create_lockout_window(project["id"], feeder_id="F-1")
    validate_success(api.suspend_safety_plan(plan["id"], so_headers))

    # Fifteen-minute gap would violate the buffer, but the suspended plan
    # interlock is evaluated before any temporal rule.
    resp = api.create_lockout_window(
        create_lockout_window_payload(
            project_id=project["id"],
            feeder_id="F-1",
            starts_at="2026-08-10T14:15:00Z",
            ends_at="2026-08-10T15:00:00Z",
        ),
        so_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SAFETY_PLAN_NOT_ACTIVE)


def test_suspended_plan_lockout_failure_leaves_existing_window(api, so_headers):
    """PRD section 3.3: "When the `SafetyOfficer` suspends an `ACTIVE` plan,
    the plan moves to `SUSPENDED` and three things happen in sequence: first
    the project's `hold_status` flips from `CLEAR` to `SAFETY_HOLD`; then, as
    a consequence, every labor entry of the project sitting in `SUBMITTED`
    status — that is, awaiting payroll approval — is automatically rejected
    with `rejection_reason` recorded as `SAFETY_HOLD`; finally the project's
    derived fields are re-evaluated and its `version` increments by one."

    Design: Difficulty/priority_pair_validation_conflict/lockout_safety_beats_temporal
    """
    project = create_project(name="Lockout Conflict Job", site_address="11 Plant Rd")
    plan = create_active_safety_plan(project["id"])
    window = create_lockout_window(project["id"], feeder_id="F-1")
    validate_success(api.suspend_safety_plan(plan["id"], so_headers))

    resp = api.create_lockout_window(
        create_lockout_window_payload(
            project_id=project["id"],
            feeder_id="F-1",
            starts_at="2026-08-10T14:15:00Z",
            ends_at="2026-08-10T15:00:00Z",
        ),
        so_headers,
    )
    err = resp.json()["data"]["error_id"]
    assert err == "ERR_SAFETY_PLAN_NOT_ACTIVE", (
        f"Safety interlock must win over the temporal buffer check, got {err}"
    )
    assert err != "ERR_LOCKOUT_CONFLICT"
    assert find_lockout_window(project["id"], window["id"])["status"] == "SCHEDULED", (
        "Suspending the plan does not cancel already-scheduled lockout windows"
    )


def test_lockouts_outstanding_on_commissioning(api, pm_headers, sup_headers, so_headers):
    """PRD section 3.3: "Lockouts also gate the
    installation-to-commissioning advance: the project cannot enter
    `COMMISSIONING` while any of its windows remains `SCHEDULED` or `ACTIVE`,
    failing with `ERR_LOCKOUTS_OUTSTANDING`."
    PRD section 3.3: "A new window begins as `SCHEDULED`. From there the
    logical clock takes over: when the clock reaches a point at or after
    `starts_at` but before `ends_at`, the window transitions to `ACTIVE`; if
    the clock reaches or passes `ends_at` while the window is still
    `SCHEDULED`, it transitions to `EXPIRED` instead."

    Design: Corner/validations/lockouts_outstanding_on_commissioning
    """
    ctx = setup_project_installing(name="Outstanding LOTO Job", site_address="50 Plant Rd")
    project = ctx["project"]
    create_approved_rigging_plan(project["id"])
    permit = validate_success(
        api.create_lift_permit(
            {
                "project_id": project["id"],
                "crane_ref": "CR-7",
                "lift_starts_at": "2026-08-10T10:00:00Z",
                "lift_ends_at": "2026-08-10T14:00:00Z",
                "road_permit_required": False,
            },
            sup_headers,
        ),
        201,
    )
    window = create_lockout_window(
        project["id"],
        feeder_id="F-1",
        starts_at="2026-08-10T12:00:00Z",
        ends_at="2026-08-10T16:00:00Z",
    )
    set_clock("2026-08-10T11:00:00Z")
    validate_success(api.execute_lift_permit(permit["id"], sup_headers))
    # Crossing 12:00 auto-activates the scheduled lockout window.
    set_clock("2026-08-10T12:30:00Z")
    assert find_lockout_window(project["id"], window["id"])["status"] == "ACTIVE"

    resp = api.advance_project(project["id"], pm_headers)
    validate_error(resp, ApiErrorId.ERR_LOCKOUTS_OUTSTANDING)
    assert get_project(project["id"])["work_status"] == "INSTALLING"
