"""Mix suspension cascades, cross-entity gating, duty ordering and role access."""

from test_helpers import (
    CLOCK_START,
    NON_EXISTENT_UUID,
    ApiErrorId,
    QC_TECHNICIAN_USER,
    TEST_USERS,
    assert_piece_dimensions_status,
    assert_project_counters,
    build_user_headers,
    create_cylinder_set,
    create_bed_run_payload,
    create_piece,
    create_project,
    create_qualified_mix,
    cylinder_break_payload,
    make_project_owner_headers,
    make_quality_engineer_headers,
    read_bed_run,
    read_cylinder_set,
    read_mix_design,
    read_piece,
    read_project,
    setup_plant,
    setup_production_line,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]
QC = TEST_USERS["qc_technician_headers"]
ENGINEER = TEST_USERS["quality_engineer_headers"]
FOREMAN = TEST_USERS["yard_foreman_headers"]
PERMITS = TEST_USERS["permit_coordinator_headers"]

SUSPEND_REASON = "Aggregate source change pending re-qualification"


def test_suspension_blocks_scheduled_runs_and_holds_their_pieces(api):
    """PRD §3.1: "Three hops then fire in order. In the first hop, every bed run
    that names this mix and is still in `SCHEDULED` moves `SCHEDULED → BLOCKED`
    and has its `blocked_reason` set to `MIX_SUSPENDED`. In the second hop —
    caused by the first, not by the suspend call itself — every piece assigned to
    one of the runs that just became `BLOCKED` and whose `qc_status` is `PENDING`
    moves `PENDING → HOLD` and has its `qc_hold_reason` set to `MIX_SUSPENDED`.
    In the third hop, caused by the second, every project that owns a piece which
    just moved to `HOLD` recomputes both `held_piece_count` and
    `cleared_piece_count`."

    Design: Difficulty/transitive_cascade/mix_suspension_cascade_run_to_piece_to_project
    """
    ctx = setup_production_line(stage="scheduled", piece_specs=[{}, {}])

    validate_success(
        api.suspend_mix_design(ctx["mix"]["id"], {"reason": SUSPEND_REASON}, ENGINEER)
    )

    run = read_bed_run(ctx["run"]["id"])
    assert run["status"] == "BLOCKED"
    assert run["blocked_reason"] == "MIX_SUSPENDED"

    for piece in ctx["pieces"]:
        assert_piece_dimensions_status(
            read_piece(piece["id"]), "SCHEDULED", "HOLD", "MIX_SUSPENDED"
        )

    assert_project_counters(read_project(ctx["project"]["id"]), held_piece_count=2)


def test_suspension_records_the_reason_and_keeps_qualified_at(api):
    """PRD §3.1: "A `QualityEngineer` suspends a mix by supplying a free-text
    `reason`, which is stored as `suspension_reason`; the mix moves `QUALIFIED →
    SUSPENDED`, and suspension from any other status is refused with
    `ERR_MIX_DESIGN_INVALID_STATE`."
    PRD §3.1: "Qualification stamps `qualified_at` with the current logical clock
    instant and increments the mix's `version` by 1."

    Design: Difficulty/transitive_cascade/mix_suspension_cascade_run_to_piece_to_project
    """
    ctx = setup_production_line(stage="scheduled", piece_specs=[{}, {}])
    qualified_at = read_mix_design(ctx["mix"]["id"])["qualified_at"]

    suspended = validate_success(
        api.suspend_mix_design(ctx["mix"]["id"], {"reason": SUSPEND_REASON}, ENGINEER)
    )

    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == SUSPEND_REASON
    assert suspended["qualified_at"] == qualified_at
    assert qualified_at.startswith("2026-08-03T06:00:00"), (
        f"qualified_at is stamped from the logical clock, got {qualified_at}"
    )


def test_reinstatement_returns_held_piece_count_to_its_baseline(api):
    """PRD §2.11: "reinstating a suspended mix must return every blocked run and
    every held piece to precisely the standing it had before the suspension."
    PRD §3.1: "In the third compensation hop, every affected project recomputes
    `held_piece_count`, which returns it to its pre-suspension value."
    PRD §3.1: "A `QualityEngineer` moves the mix `SUSPENDED → QUALIFIED`, which
    clears `suspension_reason` back to null while deliberately leaving
    `qualified_at` untouched — the first qualification instant is a historical
    fact and is never overwritten."

    Design: Difficulty/compensating_invariant/project_held_piece_count_returns_to_baseline_after_reinstate
    """
    ctx = setup_production_line(stage="scheduled", piece_specs=[{}, {}])
    baseline = read_project(ctx["project"]["id"])["held_piece_count"]
    assert baseline == 0

    validate_success(
        api.suspend_mix_design(ctx["mix"]["id"], {"reason": "Silica fume lot recalled"}, ENGINEER)
    )
    assert read_project(ctx["project"]["id"])["held_piece_count"] == 2
    assert read_bed_run(ctx["run"]["id"])["status"] == "BLOCKED"

    reinstated = validate_success(api.reinstate_mix_design(ctx["mix"]["id"], ENGINEER))

    assert reinstated["status"] == "QUALIFIED"
    assert reinstated["suspension_reason"] is None
    project = read_project(ctx["project"]["id"])
    assert project["held_piece_count"] == baseline, (
        f"held_piece_count must return to exactly {baseline}, got {project['held_piece_count']}"
    )
    assert_project_counters(project, total_piece_count=2, cleared_piece_count=0)


def test_reinstatement_clears_the_block_and_the_mix_suspended_hold(api):
    """PRD §3.1: "In the first compensation hop, every bed run on this mix whose
    status is `BLOCKED` returns `BLOCKED → SCHEDULED` and has `blocked_reason`
    cleared to null."
    PRD §3.1: "In the second compensation hop, caused by the first, every piece on
    one of those runs whose `qc_status` is `HOLD` **and** whose `qc_hold_reason`
    is `MIX_SUSPENDED` returns `HOLD → PENDING` with `qc_hold_reason` cleared to
    null — pieces held for any other reason are left exactly as they are."

    Design: Difficulty/compensating_invariant/project_held_piece_count_returns_to_baseline_after_reinstate
    """
    ctx = setup_production_line(stage="scheduled", piece_specs=[{}, {}])
    validate_success(
        api.suspend_mix_design(ctx["mix"]["id"], {"reason": "Silica fume lot recalled"}, ENGINEER)
    )

    validate_success(api.reinstate_mix_design(ctx["mix"]["id"], ENGINEER))

    run = read_bed_run(ctx["run"]["id"])
    assert run["status"] == "SCHEDULED"
    assert run["blocked_reason"] is None
    for piece in ctx["pieces"]:
        assert_piece_dimensions_status(read_piece(piece["id"]), "SCHEDULED", "PENDING", None)


def test_cast_is_refused_while_the_mix_is_suspended(api):
    """PRD §3.4: "**Casting** the run is the `ProductionSupervisor`'s act of
    placing the concrete, moving the run `TENSIONED → CURING`. The run must be in
    `TENSIONED` (otherwise `ERR_BED_RUN_INVALID_STATE`), its mix must still be
    `QUALIFIED` (otherwise `ERR_MIX_DESIGN_NOT_QUALIFIED`), and its `piece_count`
    must be at least 1 — pouring an empty bed is refused with
    `ERR_NO_PIECES_ASSIGNED`."
    PRD §3.1: "In the first hop, every bed run that names this mix and is still in
    `SCHEDULED` moves `SCHEDULED → BLOCKED` and has its `blocked_reason` set to
    `MIX_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/bed_run_cast_gated_on_mix_design_qualified_state
    """
    ctx = setup_production_line(
        stage="tensioned", with_cylinder_set=False, with_curing_cycle=False
    )
    validate_success(
        api.suspend_mix_design(
            ctx["mix"]["id"], {"reason": "Cement mill certificate under review"}, ENGINEER
        )
    )

    response = api.cast_bed_run(ctx["run"]["id"], SUPERVISOR)
    validate_error(response, ApiErrorId.ERR_MIX_DESIGN_NOT_QUALIFIED.value, 409)

    run = read_bed_run(ctx["run"]["id"])
    assert run["status"] == "TENSIONED", "a TENSIONED run is out of reach of the block cascade"
    assert run["blocked_reason"] is None
    assert run["cast_at"] is None


def test_reinstating_the_mix_lets_the_tensioned_run_cast(api):
    """PRD §3.1: "From that moment the mix may be scheduled onto a bed, tensioned
    and cast; a mix that is not `QUALIFIED` may do none of those things, and an
    attempt is refused with `ERR_MIX_DESIGN_NOT_QUALIFIED`."
    PRD §3.4: "On success the run's `cast_at` is stamped from the logical clock
    and four effects follow. Every piece assigned to the run whose
    `production_status` is `SCHEDULED` moves `SCHEDULED → CAST`. Those same
    pieces move `qc_status` from `PENDING` to `HOLD` with `qc_hold_reason` set to
    `AWAITING_RELEASE_STRENGTH` — green concrete is on hold by default until
    cylinders say otherwise."

    Design: Difficulty/cross_entity_state_dependency/bed_run_cast_gated_on_mix_design_qualified_state
    """
    ctx = setup_production_line(
        stage="tensioned", with_cylinder_set=False, with_curing_cycle=False
    )
    validate_success(
        api.suspend_mix_design(
            ctx["mix"]["id"], {"reason": "Cement mill certificate under review"}, ENGINEER
        )
    )
    validate_error(
        api.cast_bed_run(ctx["run"]["id"], SUPERVISOR),
        ApiErrorId.ERR_MIX_DESIGN_NOT_QUALIFIED.value,
        409,
    )

    reinstated = validate_success(api.reinstate_mix_design(ctx["mix"]["id"], ENGINEER))
    assert reinstated["status"] == "QUALIFIED"
    assert reinstated["suspension_reason"] is None

    cast = validate_success(api.cast_bed_run(ctx["run"]["id"], SUPERVISOR))
    assert cast["status"] == "CURING"
    assert cast["cast_at"].startswith("2026-08-03T06:00:00")
    assert_piece_dimensions_status(
        read_piece(ctx["pieces"][0]["id"]), "CAST", "HOLD", "AWAITING_RELEASE_STRENGTH"
    )


def test_duty_conflict_is_reported_while_the_run_is_release_ready(api):
    """PRD §2.10: "The first governs the detensioning release. The `X-User-ID` of
    the `QualityEngineer` signing a release must not appear anywhere in the
    `recorded_by_user_ids` list of the release cylinder set that justifies it."
    PRD §3.5: "Only after all of those does the duty check of §2.10 run: the
    signing `X-User-ID` must not appear in the release set's
    `recorded_by_user_ids`, or the request fails with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/bed_run_state_beats_segregation_of_duties
    """
    ctx = setup_production_line(stage="release_ready", break_user_id=QC_TECHNICIAN_USER)
    assert read_bed_run(ctx["run"]["id"])["status"] == "RELEASE_READY"

    conflicted = api.request_release(
        ctx["run"]["id"], make_quality_engineer_headers(QC_TECHNICIAN_USER)
    )
    validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    assert read_bed_run(ctx["run"]["id"])["status"] == "RELEASE_READY"
    assert read_cylinder_set(ctx["cylinder_set"]["id"])["recorded_by_user_ids"] == [
        QC_TECHNICIAN_USER
    ]


def test_bed_run_state_outranks_the_duty_conflict(api):
    """PRD §2.10: "Both checks raise `ERR_SEGREGATION_OF_DUTIES` (403 Forbidden),
    and both are evaluated at step 11 of §2.8 — after the state gates and after
    the quality and safety gates. A request that is both in the wrong state and
    in breach of a duty rule therefore returns the state error, not the duty
    error."
    PRD §3.5: "Its state gate deliberately admits a run in either `CURING` or
    `RELEASE_READY`, so that a premature attempt is answered by a specific
    quality error rather than a generic state error; a run in any other status is
    refused with `ERR_BED_RUN_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/bed_run_state_beats_segregation_of_duties
    """
    ctx = setup_production_line(stage="release_ready", break_user_id=QC_TECHNICIAN_USER)
    validate_error(
        api.request_release(ctx["run"]["id"], make_quality_engineer_headers(QC_TECHNICIAN_USER)),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        403,
    )

    released = validate_success(api.request_release(ctx["run"]["id"], ENGINEER))
    assert released["status"] == "RELEASED"
    assert released["released_at"].startswith("2026-08-03T06:00:00")

    again = api.request_release(
        ctx["run"]["id"], make_quality_engineer_headers(QC_TECHNICIAN_USER)
    )
    error = validate_error(again, ApiErrorId.ERR_BED_RUN_INVALID_STATE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, (
        "the duty conflict still stands, but the state gate is checked first"
    )


def test_missing_or_blank_auth_headers_are_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the acting operator, and `X-User-Role`, naming the role that
    operator is acting in. If either header is absent or present but empty, the
    request is rejected with `ERR_UNAUTHENTICATED` (401 Unauthorized) before
    anything else about the request is examined."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    validate_success(api.set_clock({"to_iso8601": CLOCK_START}, ADMIN))
    payload = {
        "name": "Ghost",
        "jobsite_city": "Nashville",
        "erection_start_date": "2026-09-15",
    }

    no_headers = api.create_project(payload, {"Content-Type": "application/json"})
    validate_error(no_headers, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    blank_user = api.create_project(payload, build_user_headers("", "PlantAdmin"))
    validate_error(blank_user, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    blank_role = api.create_project(payload, build_user_headers("admin-1", ""))
    validate_error(blank_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_role_check_runs_before_path_existence(api):
    """PRD §2.8: "**Role.** The supplied role is listed for the endpoint in §4, or
    the request fails with `ERR_UNAUTHORIZED`. This applies to every endpoint."
    PRD §2.8: "**Path existence.** Every identifier in the path resolves, left to
    right, or the request fails with the matching 404 code from §2.6. This
    applies to every endpoint that has a path parameter."

    Design: Corner/validations/role_check_precedes_path_existence
    """
    validate_success(api.set_clock({"to_iso8601": CLOCK_START}, ADMIN))

    response = api.qualify_mix_design(NON_EXISTENT_UUID, PERMITS)
    error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    assert error["error_id"] != ApiErrorId.ERR_MIX_DESIGN_NOT_FOUND.value, (
        "the role check at step 2 pre-empts the path existence check at step 3"
    )


def test_peer_roles_cannot_perform_each_others_writes(api):
    """PRD §2.1: "Read access is uniform: every GET endpoint in §4 is available to
    all seven roles. Write authority is exclusive and never shared between roles
    — no two roles may perform the same write operation."
    PRD §2.1: "If both headers are present but the supplied role is not one of the
    roles listed for that endpoint in §4, the request is rejected with
    `ERR_UNAUTHORIZED` (403 Forbidden)."

    Design: Corner/rbac/peer_roles_cannot_perform_each_others_exclusive_operations
    """
    ctx = setup_production_line(stage="scheduled", piece_specs=[])
    cylinder_set = create_cylinder_set(ctx["run"]["id"])

    validate_error(
        api.suspend_mix_design(
            ctx["mix"]["id"], {"reason": "attempted by the wrong role"}, SUPERVISOR
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api.record_cylinder_break(cylinder_set["id"], cylinder_break_payload(43983), FOREMAN),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )
    validate_error(
        api.request_release(ctx["run"]["id"], QC), ApiErrorId.ERR_UNAUTHORIZED.value, 403
    )
    validate_error(
        api.create_bed_run(
            create_bed_run_payload(
                ctx["bed"]["id"],
                ctx["mix"]["id"],
                scheduled_start="2026-08-06T06:00:00Z",
                scheduled_end="2026-08-07T06:00:00Z",
            ),
            PERMITS,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    assert read_mix_design(ctx["mix"]["id"])["status"] == "QUALIFIED"
    assert read_cylinder_set(cylinder_set["id"])["recorded_break_count"] == 0
    validate_success(api.get_bed_run(ctx["run"]["id"], PERMITS))


def test_project_owner_scope_is_checked_before_piece_state(api):
    """PRD §2.1: "When `X-User-Role` is `ProjectOwner`, `X-User-ID` is the `id` of
    the acting `Project`. Ownership checks on any resource that references a
    `Project` compare the resource's project reference to `X-User-ID`: confirming
    that a piece has been erected is permitted only when the `project_id` of the
    targeted piece equals the acting `X-User-ID`, and a mismatch is rejected with
    `ERR_PROJECT_SCOPE_FORBIDDEN` (403 Forbidden)."
    PRD §2.8: "**Project scope.** When the acting role is `ProjectOwner`,
    `X-User-ID` equals the `project_id` of the targeted piece, or the request
    fails with `ERR_PROJECT_SCOPE_FORBIDDEN`. This applies only to confirming a
    piece erected."
    PRD §3.8: "Confirming a piece erected moves it `production_status` `SHIPPED →
    ERECTED`, and a piece in any other production status is refused with
    `ERR_PIECE_INVALID_STATE`."

    Design: Corner/rbac/project_owner_cannot_confirm_another_projects_piece
    """
    ctx = setup_plant(project_count=2)
    piece = create_piece(ctx["projects"][0]["id"], ctx["mix"]["id"])

    wrong_owner = api.confirm_piece_erected(
        piece["id"], make_project_owner_headers(ctx["projects"][1]["id"])
    )
    validate_error(wrong_owner, ApiErrorId.ERR_PROJECT_SCOPE_FORBIDDEN.value, 403)

    right_owner = api.confirm_piece_erected(
        piece["id"], make_project_owner_headers(ctx["projects"][0]["id"])
    )
    error = validate_error(right_owner, ApiErrorId.ERR_PIECE_INVALID_STATE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_PROJECT_SCOPE_FORBIDDEN.value

    assert read_piece(piece["id"])["production_status"] == "PLANNED"
    assert_project_counters(read_project(ctx["projects"][0]["id"]), erected_piece_count=0)


def test_cascade_effects_are_visible_immediately(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.1: "In the first hop, every bed run that names this mix and is still in
    `SCHEDULED` moves `SCHEDULED → BLOCKED` and has its `blocked_reason` set to
    `MIX_SUSPENDED`."
    PRD §3.1: "In the second hop — caused by the first, not by the suspend call
    itself — every piece assigned to one of the runs that just became `BLOCKED`
    and whose `qc_status` is `PENDING` moves `PENDING → HOLD` and has its
    `qc_hold_reason` set to `MIX_SUSPENDED`."

    Design: Corner/consistency_model/cascade_effects_are_visible_in_the_same_response
    """
    ctx = setup_production_line(stage="scheduled")

    suspended = validate_success(
        api.suspend_mix_design(
            ctx["mix"]["id"], {"reason": "Immediate-consistency probe"}, ENGINEER
        )
    )
    assert suspended["status"] == "SUSPENDED", (
        "the suspend call's own response already carries the new status"
    )

    run = validate_success(api.get_bed_run(ctx["run"]["id"], SUPERVISOR))
    assert run["status"] == "BLOCKED"
    assert run["blocked_reason"] == "MIX_SUSPENDED"

    piece = validate_success(api.get_piece(ctx["pieces"][0]["id"], SUPERVISOR))
    assert_piece_dimensions_status(piece, "SCHEDULED", "HOLD", "MIX_SUSPENDED")

    project = validate_success(api.get_project(ctx["project"]["id"], ADMIN))
    assert project["held_piece_count"] == 1
