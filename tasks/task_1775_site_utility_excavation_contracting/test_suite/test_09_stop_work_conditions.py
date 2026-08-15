"""Stop-work posture cascade, holds and resumes, and condition/CO gating."""

from test_helpers import (
    FOREMAN,
    PROJECT_MANAGER,
    ApiErrorId,
    change_order_payload,
    complete_segment_install,
    create_approved_plan,
    create_change_order,
    create_project,
    create_segment,
    create_unforeseen_condition,
    create_utility_owner,
    get_condition,
    get_project,
    get_segment,
    mark_segment_ready,
    record_confirmed_inspection,
    setup_installing_segment,
    setup_project_with_active_ticket,
    setup_ready_segment,
    start_segment_backfill,
    start_segment_install,
    submit_change_order,
    validate_error,
    validate_success,
)


def _two_segment_worksite(api):
    """Project with S1 INSTALLING and S2 BACKFILLING behind a confirmed PASS
    inspection. Returns (ctx, s1, s2)."""
    ctx = setup_project_with_active_ticket()
    project, owner = ctx["project"], ctx["owner"]

    s1 = create_segment(project, owner, segment_label="WL-E-01")
    create_approved_plan(project, s1, protective_system="TRENCH_BOX",
                         slope_ratio=None)
    s1 = mark_segment_ready(s1["id"])
    s1 = start_segment_install(s1["id"])

    s2 = create_segment(project, owner, segment_label="WL-E-02", length_ft=180.0)
    create_approved_plan(project, s2, protective_system="TRENCH_BOX",
                         slope_ratio=None)
    s2 = mark_segment_ready(s2["id"])
    s2 = start_segment_install(s2["id"])
    s2 = complete_segment_install(s2["id"])
    record_confirmed_inspection(s2["id"])
    s2 = start_segment_backfill(s2["id"])

    return ctx, s1, s2


def test_stop_work_cascade_holds_active_segments(api):
    """PRD §2.6: "Posture changes cascade into the pipe segments of the
    project in a second hop: when a project stops, every segment in
    `INSTALLING` or `BACKFILLING` moves to `ON_HOLD`, with `hold_reason` set
    to `STOP_WORK` and `resume_status` remembering the status the segment
    left."
    PRD §2.6: "The posture is `STOPPED` exactly when the project has at least
    one unforeseen condition in `OPEN` status whose `stop_work_required` flag
    is true; otherwise it is `CLEAR`."

    Design: Difficulty/transitive_cascade/stop_work_depth2_cascade
    """
    ctx, s1, s2 = _two_segment_worksite(api)
    project = ctx["project"]
    assert s1["status"] == "INSTALLING" and s2["status"] == "BACKFILLING"

    condition = create_unforeseen_condition(
        project, condition_type="ROCK", stop_work_required=True,
        description="rock face across alignment",
    )
    assert condition["status"] == "OPEN"

    project_now = get_project(project["id"])
    assert project_now["work_posture"] == "STOPPED"
    assert project_now["status"] == "ACTIVE"

    held1 = get_segment(s1["id"])
    assert held1["status"] == "ON_HOLD"
    assert held1["hold_reason"] == "STOP_WORK"
    assert held1["resume_status"] == "INSTALLING"

    held2 = get_segment(s2["id"])
    assert held2["status"] == "ON_HOLD"
    assert held2["hold_reason"] == "STOP_WORK"
    assert held2["resume_status"] == "BACKFILLING"


def test_stop_work_cascade_leaves_ready_and_planned_segments(api):
    """PRD §2.6: "Posture changes cascade into the pipe segments of the
    project in a second hop: when a project stops, every segment in
    `INSTALLING` or `BACKFILLING` moves to `ON_HOLD`, with `hold_reason` set
    to `STOP_WORK` and `resume_status` remembering the status the segment
    left."

    Design: Difficulty/transitive_cascade/stop_work_depth2_cascade
    """
    ctx = setup_project_with_active_ticket()
    project, owner = ctx["project"], ctx["owner"]

    s_ready = create_segment(project, owner, segment_label="WL-E-03")
    create_approved_plan(project, s_ready, protective_system="TRENCH_BOX",
                         slope_ratio=None)
    s_ready = mark_segment_ready(s_ready["id"])
    s_planned = create_segment(project, owner, segment_label="WL-E-04")

    create_unforeseen_condition(
        project, condition_type="ROCK", stop_work_required=True,
        description="rock face",
    )
    assert get_project(project["id"])["work_posture"] == "STOPPED"

    # Only INSTALLING/BACKFILLING segments are held.
    assert get_segment(s_ready["id"])["status"] == "READY"
    assert get_segment(s_planned["id"])["status"] == "PLANNED"


def test_stop_then_resume_restores_segments(api):
    """PRD §2.6: "When the last blocking condition leaves `OPEN`, the posture
    recomputes to `CLEAR`, and every segment sitting `ON_HOLD` with
    `hold_reason` `STOP_WORK` returns to its remembered `resume_status`; its
    `hold_reason` resets to `NONE` and `resume_status` clears to null."

    Design: Difficulty/compensating_invariant/on_hold_segments_stop_then_resume
    """
    ctx, s1, s2 = _two_segment_worksite(api)
    project = ctx["project"]

    condition = create_unforeseen_condition(
        project, condition_type="ROCK", stop_work_required=True,
        description="rock face",
    )
    for segment in (get_segment(s1["id"]), get_segment(s2["id"])):
        assert segment["status"] == "ON_HOLD"

    resolved = validate_success(
        api.resolve_unforeseen_condition(
            condition["id"], "RESOLVED", PROJECT_MANAGER
        )
    )
    assert resolved["status"] == "RESOLVED"
    assert get_project(project["id"])["work_posture"] == "CLEAR"

    resumed1 = get_segment(s1["id"])
    resumed2 = get_segment(s2["id"])
    assert resumed1["status"] == "INSTALLING"
    assert resumed2["status"] == "BACKFILLING"
    for segment in (resumed1, resumed2):
        assert segment["hold_reason"] == "NONE"
        assert segment.get("resume_status") is None


def test_posture_stays_stopped_until_last_blocker_leaves_open(api):
    """PRD §3.7: "Whenever a stop-work condition leaves `OPEN`, the project's
    posture recomputes: if no other `OPEN` condition with `stop_work_required`
    remains, the posture clears and every segment held with `hold_reason`
    `STOP_WORK` resumes per §2.6; segments held for `DEWATERING` are not
    resumed by this transition."

    Design: Difficulty/compensating_invariant/on_hold_segments_stop_then_resume
    """
    ctx = setup_installing_segment(
        plan_overrides={"protective_system": "TRENCH_BOX", "slope_ratio": None}
    )
    project, segment = ctx["project"], ctx["segment"]

    first = create_unforeseen_condition(
        project, condition_type="ROCK", stop_work_required=True,
        description="rock face A",
    )
    second = create_unforeseen_condition(
        project, condition_type="VOID", stop_work_required=True,
        description="void B",
    )
    assert get_segment(segment["id"])["status"] == "ON_HOLD"

    # Resolving the first blocker alone leaves the project stopped.
    validate_success(
        api.resolve_unforeseen_condition(first["id"], "RESOLVED", PROJECT_MANAGER)
    )
    assert get_project(project["id"])["work_posture"] == "STOPPED"
    assert get_segment(segment["id"])["status"] == "ON_HOLD"

    # The last blocker clearing resumes the held segment.
    validate_success(
        api.resolve_unforeseen_condition(second["id"], "RESOLVED", PROJECT_MANAGER)
    )
    assert get_project(project["id"])["work_posture"] == "CLEAR"
    resumed = get_segment(segment["id"])
    assert resumed["status"] == "INSTALLING"
    assert resumed["hold_reason"] == "NONE"
    assert resumed.get("resume_status") is None


def test_status_and_posture_are_parallel_dimensions(api):
    """PRD §2.6: "A project carries a computed `work_posture` of `CLEAR` or
    `STOPPED`. The posture is `STOPPED` exactly when the project has at least
    one unforeseen condition in `OPEN` status whose `stop_work_required` flag
    is true; otherwise it is `CLEAR`."
    PRD §3.7: "Resolution is gated on money. A `ProjectManager` resolves a
    condition by passing an `outcome` of `RESOLVED` or `CLOSED_NO_ACTION`."

    Design: Difficulty/non_linear_state_machine/project_status_x_posture_parallel_dims
    """
    project = create_project(name="P-PAR", contract_ref="C-600",
                             soil_class_default="SOIL_A")
    assert project["status"] == "ACTIVE" and project["work_posture"] == "CLEAR"

    condition = create_unforeseen_condition(
        project, condition_type="ROCK", stop_work_required=True,
        description="rock face",
    )
    project_now = get_project(project["id"])
    assert project_now["status"] == "ACTIVE"
    assert project_now["work_posture"] == "STOPPED"

    resolved = validate_success(
        api.resolve_unforeseen_condition(
            condition["id"], "RESOLVED", PROJECT_MANAGER
        )
    )
    assert resolved["status"] == "RESOLVED"
    project_now = get_project(project["id"])
    assert project_now["status"] == "ACTIVE"
    assert project_now["work_posture"] == "CLEAR"


def test_non_stop_condition_never_moves_posture(api):
    """PRD §2.6: "The posture is `STOPPED` exactly when the project has at
    least one unforeseen condition in `OPEN` status whose `stop_work_required`
    flag is true; otherwise it is `CLEAR`."

    Design: Difficulty/non_linear_state_machine/project_status_x_posture_parallel_dims
    """
    project = create_project(name="P-PAR2", contract_ref="C-601",
                             soil_class_default="SOIL_A")

    condition = create_unforeseen_condition(
        project, condition_type="CONTAMINATED_SOIL", stop_work_required=False,
        description="stained soil",
    )
    assert condition["status"] == "OPEN"
    project_now = get_project(project["id"])
    assert project_now["status"] == "ACTIVE"
    assert project_now["work_posture"] == "CLEAR"

    closed = validate_success(
        api.resolve_unforeseen_condition(
            condition["id"], "CLOSED_NO_ACTION", PROJECT_MANAGER
        )
    )
    assert closed["status"] == "CLOSED_NO_ACTION"
    assert get_project(project["id"])["work_posture"] == "CLEAR"


def test_condition_resolve_blocked_by_open_change_order(api):
    """PRD §3.7: "From `OPEN`, either outcome requires that no change order of
    the condition remain in `DRAFT`, `SUBMITTED`, or `APPROVED`
    (`ERR_CO_NOT_COMPLETED`)."

    Design: Corner/validations/condition_resolve_blocked_by_open_co
    """
    project = create_project(name="P-RBC", contract_ref="C-417")
    owner = create_utility_owner()
    condition = create_unforeseen_condition(
        project, condition_type="ROCK", description="rock"
    )
    co = create_change_order(project, owner, condition)
    submit_change_order(co["id"])

    response = api.resolve_unforeseen_condition(
        condition["id"], "RESOLVED", PROJECT_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_CO_NOT_COMPLETED, 409)
    assert get_condition(condition["id"])["status"] == "OPEN"


def test_change_order_on_closed_condition_rejected(api):
    """PRD §3.8: "A `ProjectManager` creates one against a condition that is
    still `OPEN` — anything else is `ERR_CONDITION_NOT_OPEN`"

    Design: Corner/validations/co_create_on_closed_condition_rejected
    """
    project = create_project(name="P-CNC", contract_ref="C-418")
    owner = create_utility_owner()
    condition = create_unforeseen_condition(
        project, condition_type="VOID", description="harmless void"
    )
    closed = validate_success(
        api.resolve_unforeseen_condition(
            condition["id"], "CLOSED_NO_ACTION", PROJECT_MANAGER
        )
    )
    assert closed["status"] == "CLOSED_NO_ACTION"

    response = api.create_change_order(
        change_order_payload(
            project["id"], condition["id"], owner["id"],
            project["version"],
            labor_hours=1.0, labor_rate_cents=15_000,
            equipment_hours=0.0, equipment_rate_cents=1,
            material_cost_cents=0,
        ),
        PROJECT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_CONDITION_NOT_OPEN, 422)


def test_stop_work_blocks_segment_actions_until_resolved(api):
    """PRD §3.4: "Starting installation moves `READY → INSTALLING` and
    re-verifies the active-ticket and clear-posture gates."
    PRD §2.6: "The posture is `STOPPED` exactly when the project has at least
    one unforeseen condition in `OPEN` status whose `stop_work_required` flag
    is true; otherwise it is `CLEAR`."
    PRD §3.7: "Whenever a stop-work condition leaves `OPEN`, the project's
    posture recomputes: if no other `OPEN` condition with `stop_work_required`
    remains, the posture clears and every segment held with `hold_reason`
    `STOP_WORK` resumes per §2.6; segments held for `DEWATERING` are not
    resumed by this transition."

    Design: Corner/complexity_layers/stop_work_blocks_segment_actions
    """
    ctx = setup_ready_segment(
        plan_overrides={"protective_system": "TRENCH_BOX", "slope_ratio": None}
    )
    project, segment = ctx["project"], ctx["segment"]
    assert segment["status"] == "READY"

    condition = create_unforeseen_condition(
        project, condition_type="CONFLICTING_UTILITY", stop_work_required=True,
        description="unmarked lateral",
    )

    response = api.start_install(segment["id"], FOREMAN)
    validate_error(response, ApiErrorId.ERR_PROJECT_STOPPED, 409)
    assert get_segment(segment["id"])["status"] == "READY"

    validate_success(
        api.resolve_unforeseen_condition(
            condition["id"], "RESOLVED", PROJECT_MANAGER
        )
    )
    assert get_project(project["id"])["work_posture"] == "CLEAR"

    installing = validate_success(api.start_install(segment["id"], FOREMAN))
    assert installing["status"] == "INSTALLING"
