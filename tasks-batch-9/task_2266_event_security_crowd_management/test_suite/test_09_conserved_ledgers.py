"""Round trips that must land back on the number they started from.

The plan ledger is an aggregation over the committed set, not a running total
that drifts, so every release has to be exactly compensated by the booking that
replaces it. Two different routes out of the committed set are exercised — a
coordinator's cancellation and a clock-driven void — and in both cases the money,
the hours, the coverage and the gate come back to their opening values.
"""

from test_helpers import (
    AUDITOR_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ApiClient,
    AssignmentStatus,
    GatePosture,
    PostStatus,
    ReadinessPosture,
    VerificationStatus,
    World,
    action,
    assert_coverage,
    assert_gate,
    assert_ledger,
    assert_post_fill,
    build_canonical_five_post_activated_world,
    cancel_action,
    create_assignment,
    set_clock,
    validate_success,
)

BUDGET_CENTS = 500000
EXPIRY_INSTANT = "2026-09-13T00:00:00Z"
RENEWED_EXPIRY = "2026-12-31T00:00:00Z"


def _assert_budget_identity(plan: dict) -> None:
    """The two money columns of a plan always account for the whole authorised budget."""
    assert plan["committed_cost_cents"] + plan["budget_remaining_cents"] == BUDGET_CENTS


def _cancelled_world(api: ApiClient) -> World:
    """Five-post activated plan with the perimeter shift released again."""
    world = build_canonical_five_post_activated_world(api)
    world.before = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    world.after_cancel = validate_success(
        api.post_assignment_duty_event(
            world.a_p1, cancel_action("roster churn"), COORDINATOR_HEADERS
        )
    )
    return world


def test_a_cancelled_shift_leaves_the_budget_identity_intact_on_the_way_down():
    """Releasing one 16500 cent shift moves both money columns by the same amount.

    The plan opens fully staffed at 82500 committed cents against 417500
    remaining. The cancellation takes the row out of the committed set, so the
    ledger falls to 66000 and 434000 and the hours to 30.00, and the two money
    columns still account for the whole 500000 cent authorisation.

    PRD: "The plan-level ledger is a straight aggregation over the plan's committed set — the assignments on the plan's posts whose `assignment_status` is `CONFIRMED` or `COMPLETED`."
    Design: Difficulty/compensating_invariant/budget_ledger_restored_after_confirm_then_cancel
    """
    api = ApiClient()
    world = _cancelled_world(api)

    assert_ledger(world.before, 82500, 37.50, budget_remaining_cents=417500)
    _assert_budget_identity(world.before)

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 66000, 30.00, budget_remaining_cents=434000)
    assert_coverage(plan, 5, 4, 0.80, ReadinessPosture.BLOCKED)
    _assert_budget_identity(plan)

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert_gate(event, GatePosture.RESTRICTED)


def test_re_booking_the_same_guard_restores_every_figure_to_its_opening_value():
    """A replacement shift returns the plan to 82500 cents, 37.50 hours and READY.

    Pencilling the replacement in moves nothing: the plan is still at 66000
    committed cents while the new row carries its own 16500 cent line. Confirming
    it re-enters the committed set and every figure — money, hours, coverage,
    posture and the event's gate — lands back exactly where it started.

    PRD: "In the same request the ledger is synchronised: the row's `line_cost_cents` is added to the plan's `committed_cost_cents`, the row's `scheduled_hours` is added to the plan's `committed_guard_hours`, and `budget_remaining_cents` is set to `budget_cents` minus `committed_cost_cents`."
    Design: Difficulty/compensating_invariant/budget_ledger_restored_after_confirm_then_cancel
    """
    api = ApiClient()
    world = _cancelled_world(api)

    replacement = create_assignment(api, world.p1_id, world.g1_id)
    pencilled = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert pencilled["committed_cost_cents"] == 66000
    _assert_budget_identity(pencilled)
    row = validate_success(api.get_post_assignment(replacement, COORDINATOR_HEADERS))
    assert row["line_cost_cents"] == 16500

    validate_success(
        api.post_assignment_duty_event(replacement, action("CONFIRM"), COORDINATOR_HEADERS)
    )

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 82500, 37.50, budget_remaining_cents=417500)
    assert_coverage(plan, 5, 5, 1.00, ReadinessPosture.READY)
    _assert_budget_identity(plan)

    post = validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS))
    assert_post_fill(post, 1, PostStatus.FILLED)

    event = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert_gate(event, GatePosture.OPEN)


def _voided_world(api: ApiClient) -> World:
    """Same plan, but the exit guard's card lapses the moment the clock is advanced."""
    world = build_canonical_five_post_activated_world(
        api, exit_guard_credential_expires_on=EXPIRY_INSTANT
    )
    world.sweep = set_clock(api, EXPIRY_INSTANT)
    return world


def test_the_hours_ledger_drops_by_exactly_the_voided_shift():
    """One swept card takes 7.50 hours and 16500 cents straight out of the plan.

    The sweep is not something the client asked for, yet it recomputes the ledger
    the same way a cancellation does: 37.50 hours become 30.00 and 82500 cents
    become 66000. The voided row keeps the system's own reason and the guard is
    left EXPIRED with no clearance stamp.

    PRD: "`committed_guard_hours` is the sum of those rows' `scheduled_hours`, rounded half-up to two decimal places once, after summing."
    Design: Difficulty/compensating_invariant/guard_hours_ledger_restored_after_void_cascade
    """
    api = ApiClient()
    world = _voided_world(api)

    assert world.sweep["expired_guard_count"] == 1
    assert world.sweep["voided_assignment_count"] == 1

    guard = validate_success(api.get_guard(world.g4_id, COORDINATOR_HEADERS))
    assert guard["verification_status"] == VerificationStatus.EXPIRED
    assert guard["verified_at"] is None

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 66000, 30.00, budget_remaining_cents=434000)
    assert_coverage(plan, 5, 4, 0.80, ReadinessPosture.BLOCKED)
    _assert_budget_identity(plan)


def test_re_certifying_the_guard_and_re_booking_restores_the_hours_exactly():
    """A renewed card and a fresh shift bring the plan back to 37.50 hours and READY.

    Re-certification from EXPIRED must carry a new expiry later than the clock,
    which is stored on the guard and cleared by the auditor at the new clock
    value. The replacement shift then commits 7.50 hours and 16500 cents, the
    voided row stays voided, and the plan is whole again.

    PRD: "From `EXPIRED`, the request requires a `credential_expires_on` in the body that is strictly later than the logical clock, and stores it."
    Design: Difficulty/compensating_invariant/guard_hours_ledger_restored_after_void_cascade
    """
    api = ApiClient()
    world = _voided_world(api)

    under_review = validate_success(
        api.guard_credential_verification(
            world.g4_id,
            action("SUBMIT_FOR_REVIEW", credential_expires_on=RENEWED_EXPIRY),
            COORDINATOR_HEADERS,
        )
    )
    assert under_review["verification_status"] == VerificationStatus.PENDING_REVIEW
    assert under_review["credential_expires_on"] == RENEWED_EXPIRY

    recleared = validate_success(
        api.guard_credential_verification(world.g4_id, action("VERIFY"), AUDITOR_HEADERS)
    )
    assert recleared["verification_status"] == VerificationStatus.VERIFIED
    assert recleared["verified_at"] == EXPIRY_INSTANT

    replacement = create_assignment(api, world.e1_id, world.g4_id)
    row = validate_success(api.get_post_assignment(replacement, COORDINATOR_HEADERS))
    assert row["line_cost_cents"] == 16500
    validate_success(
        api.post_assignment_duty_event(replacement, action("CONFIRM"), COORDINATOR_HEADERS)
    )

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 82500, 37.50, budget_remaining_cents=417500)
    assert_coverage(plan, 5, 5, 1.00, ReadinessPosture.READY)
    _assert_budget_identity(plan)

    voided = validate_success(api.get_post_assignment(world.a_e1, COORDINATOR_HEADERS))
    assert voided["assignment_status"] == AssignmentStatus.VOIDED

    post = validate_success(api.get_post(world.e1_id, COORDINATOR_HEADERS))
    assert_post_fill(post, 1, PostStatus.FILLED)
