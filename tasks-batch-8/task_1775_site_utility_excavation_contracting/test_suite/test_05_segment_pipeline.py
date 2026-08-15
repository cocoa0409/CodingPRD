"""Pipe segment readiness gates and the installation pipeline."""

from test_helpers import (
    FOREMAN,
    FOREMAN_USER,
    PROJECT_MANAGER,
    SAFETY_USER,
    ApiErrorId,
    create_approved_plan,
    create_locate_ticket,
    create_project,
    create_segment,
    create_utility_owner,
    get_pothole,
    get_segment,
    get_ticket,
    make_foreman_headers,
    make_safety_officer_headers,
    pothole_payload,
    record_confirmed_inspection,
    setup_complete_segment,
    setup_installed_segment,
    setup_project_with_active_ticket,
    trench_plan_payload,
    validate_error,
    validate_success,
)


def test_lifts_required_ceiling_variants(api):
    """PRD §3.4: "Creation also computes `lifts_required`, the number of
    one-foot backfill lifts the trench will demand: the trench depth is the
    design invert depth plus the pipe diameter converted from inches to feet
    plus a bedding allowance of 0.5 feet for `CLASS_B`, 0.5 feet for
    `CLASS_C`, or 0.25 feet for `CLASS_D`; that depth, divided by the one-foot
    lift thickness and rounded up to a whole number, is the lift count."

    Design: Corner/calculations/lifts_required_ceiling_variants
    """
    ctx = setup_project_with_active_ticket(with_verified_pothole=False)

    deep = create_segment(
        ctx["project"], ctx["owner"], segment_label="WL-D-01",
        pipe_material="PVC_C900", diameter_in=12, length_ft=200.0,
        bedding_class="CLASS_B", design_invert_depth_ft=8.0,
    )
    # ceil((8.0 + 12/12 + 0.5) / 1.0) == ceil(9.5) == 10
    assert deep["lifts_required"] == 10

    shallow = create_segment(
        ctx["project"], ctx["owner"], segment_label="WL-D-02",
        pipe_material="HDPE", diameter_in=6, length_ft=100.0,
        bedding_class="CLASS_D", design_invert_depth_ft=1.0,
        design_slope_pct=0.5,
    )
    # ceil((1.0 + 6/12 + 0.25) / 1.0) == ceil(1.75) == 2
    assert shallow["lifts_required"] == 2


def test_mark_ready_blocked_while_plan_in_draft(api):
    """PRD §3.4: "Marking a segment ready moves it `PLANNED → READY` only when
    the segment has a trench safety plan in `APPROVED` status (else
    `ERR_PLAN_NOT_APPROVED`), the project holds an `ACTIVE` locate ticket
    (`ERR_LOCATE_NOT_ACTIVE`), no pothole verification of the project remains
    in `PLANNED`, `PERFORMED`, or `CONFLICT` (`ERR_POTHOLES_OUTSTANDING`), and
    the project's posture is `CLEAR` (`ERR_PROJECT_STOPPED`)."

    Design: Difficulty/cross_entity_state_dependency/mark_ready_gated_by_plan_approval
    """
    ctx = setup_project_with_active_ticket()
    segment = create_segment(ctx["project"], ctx["owner"], segment_label="WL-G-01")
    draft_plan = validate_success(
        api.create_trench_safety_plan(
            trench_plan_payload(ctx["project"]["id"], segment["id"]),
            make_foreman_headers(FOREMAN_USER),
        ),
        201,
    )
    assert draft_plan["status"] == "DRAFT"

    response = api.mark_segment_ready(segment["id"], FOREMAN)
    validate_error(response, ApiErrorId.ERR_PLAN_NOT_APPROVED, 409)
    assert get_segment(segment["id"])["status"] == "PLANNED"

    # Approve the plan and the same transition now succeeds.
    validate_success(
        api.submit_trench_safety_plan(
            draft_plan["id"], make_foreman_headers(FOREMAN_USER)
        )
    )
    validate_success(
        api.review_trench_safety_plan(
            draft_plan["id"], "APPROVE", make_safety_officer_headers(SAFETY_USER)
        )
    )
    ready = validate_success(api.mark_segment_ready(segment["id"], FOREMAN))
    assert ready["status"] == "READY"


def test_mark_ready_blocked_while_plan_only_submitted(api):
    """PRD §3.4: "Marking a segment ready moves it `PLANNED → READY` only when
    the segment has a trench safety plan in `APPROVED` status (else
    `ERR_PLAN_NOT_APPROVED`), the project holds an `ACTIVE` locate ticket
    (`ERR_LOCATE_NOT_ACTIVE`), no pothole verification of the project remains
    in `PLANNED`, `PERFORMED`, or `CONFLICT` (`ERR_POTHOLES_OUTSTANDING`), and
    the project's posture is `CLEAR` (`ERR_PROJECT_STOPPED`)."

    Design: Difficulty/cross_entity_state_dependency/mark_ready_gated_by_plan_approval
    """
    ctx = setup_project_with_active_ticket()
    segment = create_segment(ctx["project"], ctx["owner"], segment_label="WL-G-02")
    plan = validate_success(
        api.create_trench_safety_plan(
            trench_plan_payload(ctx["project"]["id"], segment["id"]),
            make_foreman_headers(FOREMAN_USER),
        ),
        201,
    )
    submitted = validate_success(
        api.submit_trench_safety_plan(plan["id"], make_foreman_headers(FOREMAN_USER))
    )
    assert submitted["status"] == "SUBMITTED"

    response = api.mark_segment_ready(segment["id"], FOREMAN)
    validate_error(response, ApiErrorId.ERR_PLAN_NOT_APPROVED, 409)
    assert get_segment(segment["id"])["status"] == "PLANNED"


def test_mark_ready_blocked_by_unperformed_pothole(api):
    """PRD §3.4: "Marking a segment ready moves it `PLANNED → READY` only when
    the segment has a trench safety plan in `APPROVED` status (else
    `ERR_PLAN_NOT_APPROVED`), the project holds an `ACTIVE` locate ticket
    (`ERR_LOCATE_NOT_ACTIVE`), no pothole verification of the project remains
    in `PLANNED`, `PERFORMED`, or `CONFLICT` (`ERR_POTHOLES_OUTSTANDING`), and
    the project's posture is `CLEAR` (`ERR_PROJECT_STOPPED`)."

    Design: Corner/validations/mark_ready_blocked_by_outstanding_potholes
    """
    ctx = setup_project_with_active_ticket(with_verified_pothole=False)
    pothole = validate_success(
        api.create_pothole_verification(
            pothole_payload(
                ctx["project"]["id"], ctx["ticket"]["id"],
                station_label="STA 2+00",
            ),
            PROJECT_MANAGER,
        ),
        201,
    )
    segment = create_segment(ctx["project"], ctx["owner"], segment_label="WL-V-06")
    create_approved_plan(ctx["project"], segment)

    response = api.mark_segment_ready(segment["id"], FOREMAN)
    validate_error(response, ApiErrorId.ERR_POTHOLES_OUTSTANDING, 409)
    assert get_segment(segment["id"])["status"] == "PLANNED"
    assert get_pothole(pothole["id"])["status"] == "PLANNED"


def test_mark_ready_blocked_without_active_ticket(api):
    """PRD §3.4: "Marking a segment ready moves it `PLANNED → READY` only when
    the segment has a trench safety plan in `APPROVED` status (else
    `ERR_PLAN_NOT_APPROVED`), the project holds an `ACTIVE` locate ticket
    (`ERR_LOCATE_NOT_ACTIVE`), no pothole verification of the project remains
    in `PLANNED`, `PERFORMED`, or `CONFLICT` (`ERR_POTHOLES_OUTSTANDING`), and
    the project's posture is `CLEAR` (`ERR_PROJECT_STOPPED`)."
    PRD §3.2: "The `ACTIVE` status is a hard gate on the work itself:
    performing a pothole, marking a segment ready, starting installation, and
    starting backfill are each rejected with `ERR_LOCATE_NOT_ACTIVE` when no
    active ticket covers the project."

    Design: Corner/validations/start_install_without_active_ticket
    """
    project = create_project(name="P-LNA", contract_ref="C-421")
    owner = create_utility_owner()
    ticket = create_locate_ticket(
        project["id"], ticket_number="T-1",
        legal_start_at="2026-08-03T00:00:00Z",
    )
    validate_success(api.submit_locate_ticket(ticket["id"], PROJECT_MANAGER))
    # Clock is still at 2026-08-01T00:00:00Z: the ticket waits out its
    # waiting period in SUBMITTED.
    assert get_ticket(ticket["id"])["status"] == "SUBMITTED"

    segment = create_segment(project, owner, segment_label="WL-V-14")
    create_approved_plan(project, segment)

    response = api.mark_segment_ready(segment["id"], FOREMAN)
    validate_error(response, ApiErrorId.ERR_LOCATE_NOT_ACTIVE, 409)
    assert get_segment(segment["id"])["status"] == "PLANNED"


def test_start_backfill_without_inspection_rejected(api):
    """PRD §3.4: "Starting backfill moves `INSTALLED → BACKFILLING` and
    demands that the segment's most recently created `CONFIRMED` inspection
    has `result` `PASS` — when none exists, or the latest is a failure, the
    rejection is `ERR_INSPECTION_NOT_PASSED` — alongside the standing
    active-ticket and clear-posture gates."

    Design: Corner/validations/start_backfill_without_inspection_rejected
    """
    ctx = setup_installed_segment(shallow=False)
    segment_id = ctx["segment"]["id"]
    assert ctx["segment"]["status"] == "INSTALLED"

    response = api.start_backfill(segment_id, FOREMAN)
    validate_error(response, ApiErrorId.ERR_INSPECTION_NOT_PASSED, 409)
    assert get_segment(segment_id)["status"] == "INSTALLED"


def test_inspection_fail_rework_loop(api):
    """PRD §3.4: "Starting backfill moves `INSTALLED → BACKFILLING` and
    demands that the segment's most recently created `CONFIRMED` inspection
    has `result` `PASS` — when none exists, or the latest is a failure, the
    rejection is `ERR_INSPECTION_NOT_PASSED` — alongside the standing
    active-ticket and clear-posture gates. When the latest confirmed
    inspection is a `FAIL`, the `Foreman` may instead reopen installation,
    moving `INSTALLED → INSTALLING` (the attempt draws `ERR_INVALID_STATE`
    when the latest confirmed result is not `FAIL`), and the segment cycles
    `INSTALLING → INSTALLED` again once reworked."

    Design: Corner/state_machines/inspection_fail_rework_loop
    """
    ctx = setup_installed_segment(shallow=False)
    segment_id = ctx["segment"]["id"]

    failing = record_confirmed_inspection(segment_id, bedding_ok=False)
    assert failing["result"] == "FAIL"
    assert failing["status"] == "CONFIRMED"

    response = api.start_backfill(segment_id, FOREMAN)
    validate_error(response, ApiErrorId.ERR_INSPECTION_NOT_PASSED, 409)

    reopened = validate_success(api.reopen_install(segment_id, FOREMAN))
    assert reopened["status"] == "INSTALLING"

    validate_success(api.complete_install(segment_id, FOREMAN))
    passing = record_confirmed_inspection(segment_id)
    assert passing["result"] == "PASS"

    backfilling = validate_success(api.start_backfill(segment_id, FOREMAN))
    assert backfilling["status"] == "BACKFILLING"


def test_complete_segment_rejects_further_actions(api):
    """PRD §2.10: "Sixth, the target resource must be in a valid from-state
    for the requested transition, and a resource in a terminal state rejects
    every action, else `ERR_INVALID_STATE`."
    PRD §3.4: "Starting installation moves `READY → INSTALLING` and
    re-verifies the active-ticket and clear-posture gates."

    Design: Corner/state_machines/complete_segment_rejects_further_actions
    """
    ctx = setup_complete_segment()
    segment = ctx["segment"]
    assert segment["status"] == "COMPLETE"
    assert segment["lifts_satisfied"] == segment["lifts_required"] == 2

    response = api.start_install(segment["id"], FOREMAN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_segment(segment["id"])["status"] == "COMPLETE"
