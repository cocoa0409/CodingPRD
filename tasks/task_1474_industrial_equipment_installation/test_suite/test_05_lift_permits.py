"""Crane lift permits: the approved-rigging-plan gate, half-open fleet-wide
overlap arithmetic, execution window checks, and booking release
(PRD section 3.5)."""
from test_helpers import (
    ApiErrorId,
    create_approved_rigging_plan,
    create_lift_permit_payload,
    find_lift_permit,
    get_project,
    set_clock,
    setup_project_installing,
    setup_project_with_approved_rigging,
    validate_error,
    validate_success,
)


def test_lift_permit_without_approved_plan_rejected(api, sup_headers):
    """PRD section 3.5: "Booking is gated on the project's phase and readiness:
    the project must be in `INSTALLING` (otherwise `ERR_INVALID_STATE`), clear
    of any safety hold, and must have an approved rigging plan currently pinned
    (otherwise `ERR_RIGGING_PLAN_NOT_APPROVED`)."

    Design: Difficulty/cross_entity_state_dependency/lift_permit_requires_approved_rigging_plan
    """
    ctx = setup_project_installing(name="Gate Job", site_address="14 Plant Rd")
    project = ctx["project"]

    resp = api.create_lift_permit(
        create_lift_permit_payload(project_id=project["id"], crane_ref="CR-9"),
        sup_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RIGGING_PLAN_NOT_APPROVED)


def test_lift_permit_after_plan_approval_succeeds(api, sup_headers):
    """PRD section 3.5: "Booking is gated on the project's phase and readiness:
    the project must be in `INSTALLING` (otherwise `ERR_INVALID_STATE`), clear
    of any safety hold, and must have an approved rigging plan currently pinned
    (otherwise `ERR_RIGGING_PLAN_NOT_APPROVED`)."
    PRD section 3.5: "A permit is created in `ISSUED` status with its
    `duration_hours` computed as the length of the booked window in hours; its
    `equipment_charge_cents` remains null until execution."

    Design: Difficulty/cross_entity_state_dependency/lift_permit_requires_approved_rigging_plan
    """
    ctx = setup_project_installing(name="Gate Job", site_address="14 Plant Rd")
    project = ctx["project"]

    blocked = api.create_lift_permit(
        create_lift_permit_payload(project_id=project["id"], crane_ref="CR-9"),
        sup_headers,
    )
    validate_error(blocked, ApiErrorId.ERR_RIGGING_PLAN_NOT_APPROVED)

    create_approved_rigging_plan(project["id"])
    permit = validate_success(
        api.create_lift_permit(
            create_lift_permit_payload(project_id=project["id"], crane_ref="CR-9"),
            sup_headers,
        ),
        201,
    )
    assert permit["status"] == "ISSUED"
    assert permit["duration_hours"] == 4.0
    assert permit["equipment_charge_cents"] is None


def test_adjacent_crane_windows_do_not_conflict(api, sup_headers):
    """PRD section 3.5: "A new window conflicts with an existing `ISSUED`
    window only when the two half-open intervals genuinely overlap — the new
    start falls before the existing end and the existing start falls before
    the new end. Touching endpoints are not a conflict: a new window that
    starts exactly when an existing window ends, or ends exactly when one
    starts, books cleanly."

    Design: Difficulty/resource_temporal_overlap/crane_booking_half_open_adjacency
    """
    ctx = setup_project_with_approved_rigging(name="Crane Pool Job", site_address="16 Plant Rd")
    project = ctx["project"]
    first = validate_success(
        api.create_lift_permit(
            create_lift_permit_payload(project_id=project["id"], crane_ref="CR-9"),
            sup_headers,
        ),
        201,
    )
    assert first["status"] == "ISSUED"

    # Adjacent: starts exactly when the existing window ends (14:00).
    adjacent = validate_success(
        api.create_lift_permit(
            create_lift_permit_payload(
                project_id=project["id"],
                crane_ref="CR-9",
                lift_starts_at="2026-08-10T14:00:00Z",
                lift_ends_at="2026-08-10T18:00:00Z",
            ),
            sup_headers,
        ),
        201,
    )
    assert adjacent["status"] == "ISSUED", "Half-open adjacency is not a conflict"


def test_overlapping_crane_window_rejected(api, sup_headers):
    """PRD section 3.5: "Any genuine overlap is rejected with
    `ERR_CRANE_WINDOW_CONFLICT`."
    PRD section 2.9: "A crane booking made under one project competes with
    bookings of the same crane unit under every other project, so overlap
    validation always runs fleet-wide against the crane unit identifier rather
    than within a single project."

    Design: Difficulty/resource_temporal_overlap/crane_booking_half_open_adjacency
    """
    ctx = setup_project_with_approved_rigging(name="Crane Pool Job", site_address="16 Plant Rd")
    project = ctx["project"]
    validate_success(
        api.create_lift_permit(
            create_lift_permit_payload(project_id=project["id"], crane_ref="CR-9"),
            sup_headers,
        ),
        201,
    )

    # Genuine overlap with the 10:00-14:00 booking on the same crane.
    resp = api.create_lift_permit(
        create_lift_permit_payload(
            project_id=project["id"],
            crane_ref="CR-9",
            lift_starts_at="2026-08-10T13:00:00Z",
            lift_ends_at="2026-08-10T15:00:00Z",
        ),
        sup_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CRANE_WINDOW_CONFLICT)

    # The same hours on a different crane unit book cleanly.
    other = validate_success(
        api.create_lift_permit(
            create_lift_permit_payload(
                project_id=project["id"],
                crane_ref="CR-10",
                lift_starts_at="2026-08-10T13:00:00Z",
                lift_ends_at="2026-08-10T15:00:00Z",
            ),
            sup_headers,
        ),
        201,
    )
    assert other["status"] == "ISSUED"


def test_outside_lift_window(api, sup_headers):
    """PRD section 3.5: "When the `SiteSupervisor` executes the lift, the
    project's `hold_status` must be `CLEAR` (otherwise `ERR_SAFETY_HOLD`) and
    the current logical time must fall within the half-open booking window —
    at or after `lift_starts_at` and strictly before `lift_ends_at` —
    otherwise the attempt is rejected with `ERR_OUTSIDE_LIFT_WINDOW`."

    Design: Corner/validations/outside_lift_window
    """
    ctx = setup_project_with_approved_rigging(name="Window Job", site_address="48 Plant Rd")
    project = ctx["project"]
    permit = validate_success(
        api.create_lift_permit(create_lift_permit_payload(project_id=project["id"]), sup_headers),
        201,
    )
    # Clock stays at the cured position 2026-08-08, two days before the window.
    resp = api.execute_lift_permit(permit["id"], sup_headers)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_LIFT_WINDOW)

    stored = find_lift_permit(project["id"], permit["id"])
    assert stored["status"] == "ISSUED"
    assert stored["equipment_charge_cents"] is None


def test_lift_execute_after_cancel_rejected(api, sup_headers):
    """PRD section 3.5: "`EXECUTED`, `CANCELLED`, and `EXPIRED` are terminal."
    PRD section 3.5: "A permit is created in `ISSUED` status with its
    `duration_hours` computed as the length of the booked window in hours; its
    `equipment_charge_cents` remains null until execution."

    Design: Corner/state_machines/lift_execute_after_cancel_rejected
    """
    ctx = setup_project_with_approved_rigging(name="SM6 Job", site_address="28 Plant Rd")
    project = ctx["project"]
    permit = validate_success(
        api.create_lift_permit(create_lift_permit_payload(project_id=project["id"]), sup_headers),
        201,
    )
    cancelled = validate_success(api.cancel_lift_permit(permit["id"], sup_headers))
    assert cancelled["status"] == "CANCELLED"

    set_clock("2026-08-10T11:00:00Z")  # inside the original booking window
    resp = api.execute_lift_permit(permit["id"], sup_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    stored = find_lift_permit(project["id"], permit["id"])
    assert stored["status"] == "CANCELLED"
    assert stored["equipment_charge_cents"] is None


def test_no_executed_lift_on_advance(api, pm_headers):
    """PRD section 3.5: "The advance from `INSTALLING` to `COMMISSIONING`
    requires at least one lift permit of the project in `EXECUTED` status,
    failing with `ERR_NO_EXECUTED_LIFT` otherwise, in addition to the lockout
    gate of §3.3 and the ever-present hold check."

    Design: Corner/validations/no_executed_lift_on_advance
    """
    ctx = setup_project_installing(name="No Lift Job", site_address="53 Plant Rd")
    project = ctx["project"]
    assert project["work_status"] == "INSTALLING"

    resp = api.advance_project(project["id"], pm_headers)
    validate_error(resp, ApiErrorId.ERR_NO_EXECUTED_LIFT)
    assert get_project(project["id"])["work_status"] == "INSTALLING"


def test_permit_creation_commits_window_hours(api, sup_headers):
    """PRD section 3.5: "A permit is created in `ISSUED` status with its
    `duration_hours` computed as the length of the booked window in hours; its
    `equipment_charge_cents` remains null until execution."

    Design: Difficulty/compensating_invariant/crane_booking_create_cancel_conserves_commitment
    """
    ctx = setup_project_with_approved_rigging(name="Release Job", site_address="19 Plant Rd")
    project = ctx["project"]
    permit = validate_success(
        api.create_lift_permit(
            create_lift_permit_payload(project_id=project["id"], crane_ref="CR-5"),
            sup_headers,
        ),
        201,
    )
    assert permit["status"] == "ISSUED"
    assert permit["duration_hours"] == 4.0, (
        f"A 10:00-14:00 booking commits 4.0 hours, got {permit['duration_hours']}"
    )


def test_cancel_releases_booking_allowing_rebook(api, sup_headers):
    """PRD section 3.5: "Cancellation — whether by the supervisor or by the
    rigging supersede cascade of §3.4 — and expiry both release the booking:
    the window stops counting toward the crane's committed time, whereas an
    `EXECUTED` window is historic and likewise no longer counts."

    Design: Difficulty/compensating_invariant/crane_booking_create_cancel_conserves_commitment
    """
    ctx = setup_project_with_approved_rigging(name="Release Job", site_address="19 Plant Rd")
    project = ctx["project"]
    permit = validate_success(
        api.create_lift_permit(
            create_lift_permit_payload(project_id=project["id"], crane_ref="CR-5"),
            sup_headers,
        ),
        201,
    )
    cancelled = validate_success(api.cancel_lift_permit(permit["id"], sup_headers))
    assert cancelled["status"] == "CANCELLED"

    # The released window no longer counts against the crane's commitment, so
    # an identical window rebooks without conflict.
    rebooked = validate_success(
        api.create_lift_permit(
            create_lift_permit_payload(project_id=project["id"], crane_ref="CR-5"),
            sup_headers,
        ),
        201,
    )
    assert rebooked["status"] == "ISSUED", (
        "Cancelling the first permit must release its crane-time commitment"
    )
    assert rebooked["duration_hours"] == 4.0
