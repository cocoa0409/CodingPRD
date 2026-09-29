"""Confirmations that fail two rules at once, and which failure the caller sees.

Confirmation is the most heavily guarded operation in the system, so it is the
natural place to pin the judging order. Each pair below is set up so that two
checks are simultaneously violated, and a control confirmation proves the
lower-ranked check really was reachable rather than simply absent.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    ApiClient,
    ApiErrorId,
    AssignmentStatus,
    AUDITOR_HEADERS,
    PostStatus,
    PostType,
    SubcontractorStatus,
    VerificationStatus,
    action,
    assert_ledger,
    assert_post_fill,
    build_published_plan_with_posts_world,
    cancel_action,
    confirm,
    create_assignment,
    create_verified_guard,
    subcontracted_guard_payload,
    subcontractor_payload,
    validate_error,
    validate_success,
)


def _budget_pair_world(api: ApiClient):
    """Tight 40000 cent budget, one shift already committed and two rows on P2."""
    world = build_published_plan_with_posts_world(
        api,
        [
            {"code": "P1", "post_type": PostType.PERIMETER, "required_guard_count": 1},
            {"code": "P2", "post_type": PostType.PERIMETER, "required_guard_count": 1},
            {"code": "PF", "post_type": PostType.PERIMETER, "required_guard_count": 3},
        ],
        budget_cents=40000,
    )
    world.g1_id = create_verified_guard(api, "GC-2001", full_name="Gale One")
    world.g2_id = create_verified_guard(
        api, "GC-2002", full_name="Gale Two", base_hourly_rate_cents=4000
    )

    world.a1 = create_assignment(api, world.p1_id, world.g1_id)
    confirm(api, world.a1)

    world.a2 = create_assignment(api, world.p2_id, world.g2_id)
    validate_success(
        api.post_assignment_duty_event(
            world.a2, cancel_action("pencilled in by mistake"), COORDINATOR_HEADERS
        )
    )
    world.a3 = create_assignment(api, world.p2_id, world.g2_id)
    return world


def test_transition_legality_outranks_the_budget_check_on_confirm():
    """Confirming an already-cancelled row reports the state error, never the money error.

    The 30000 cent shift would blow the 23500 cents left in the budget, but the
    row is CANCELLED and rank 12 fires long before rank 38 is reached.

    PRD: "**Transition legality** — the target resource's current state has an outgoing transition for the requested action, else `ERR_INVALID_STATE` (409)."
    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_budget_exceeded_on_confirm
    """
    api = ApiClient()
    world = _budget_pair_world(api)

    response = api.post_assignment_duty_event(world.a2, action("CONFIRM"), COORDINATOR_HEADERS)
    validate_error(response, ApiErrorId.INVALID_STATE)

    row = validate_success(api.get_post_assignment(world.a2, COORDINATOR_HEADERS))
    assert row["assignment_status"] == AssignmentStatus.CANCELLED


def test_the_budget_check_is_reachable_once_the_row_is_in_a_confirmable_state():
    """The live twin of the cancelled row is refused for the money instead.

    Identical guard, identical post, identical window — the only difference is
    that this row is still TENTATIVE, so the request travels all the way to the
    budget headroom check and is refused there with the payment status.

    PRD: "**Budget headroom** — a confirmation requires the assignment's `line_cost_cents` to be at most the plan's `budget_remaining_cents`, else `ERR_PLAN_BUDGET_EXCEEDED` (402)."
    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_budget_exceeded_on_confirm
    """
    api = ApiClient()
    world = _budget_pair_world(api)

    response = api.post_assignment_duty_event(world.a3, action("CONFIRM"), COORDINATOR_HEADERS)
    validate_error(response, ApiErrorId.PLAN_BUDGET_EXCEEDED)

    row = validate_success(api.get_post_assignment(world.a3, COORDINATOR_HEADERS))
    assert row["assignment_status"] == AssignmentStatus.TENTATIVE
    assert row["line_cost_cents"] == 30000

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 16500, 7.50, budget_remaining_cents=23500)


def _double_booking_pair_world(api: ApiClient):
    """P1 already full, with a second row for the same guard and one for another."""
    world = build_published_plan_with_posts_world(
        api,
        [
            {"code": "P1", "post_type": PostType.PERIMETER, "required_guard_count": 1},
            {"code": "PF", "post_type": PostType.PERIMETER, "required_guard_count": 4},
        ],
    )
    world.g1_id = create_verified_guard(api, "GC-3001", full_name="Gale One")
    world.g2_id = create_verified_guard(api, "GC-3002", full_name="Gale Two")

    world.a1 = create_assignment(api, world.p1_id, world.g1_id)
    confirm(api, world.a1)
    world.a2 = create_assignment(api, world.p1_id, world.g2_id)
    world.a3 = create_assignment(api, world.p1_id, world.g1_id)
    return world


def test_double_booking_outranks_post_headroom_on_confirm():
    """The same guard's second row on a full post is refused as a double booking.

    Both rules are broken: the guard already holds a CONFIRMED shift over the
    identical window and the post has no headroom left. Rank 23 is checked
    first, so the window conflict is what the caller sees.

    PRD: "Confirmation is refused with `ERR_GUARD_WINDOW_CONFLICT` when some other assignment for the same `guard_id` whose `assignment_status` is `TENTATIVE` or `CONFIRMED` starts strictly before this shift ends and also ends strictly after this shift starts."
    Design: Difficulty/priority_pair_validation_conflict/guard_window_conflict_outranks_post_fully_staffed
    """
    api = ApiClient()
    world = _double_booking_pair_world(api)

    response = api.post_assignment_duty_event(world.a3, action("CONFIRM"), COORDINATOR_HEADERS)
    validate_error(response, ApiErrorId.GUARD_WINDOW_CONFLICT)

    row = validate_success(api.get_post_assignment(world.a3, COORDINATOR_HEADERS))
    assert row["assignment_status"] == AssignmentStatus.TENTATIVE


def test_post_headroom_is_reachable_for_a_guard_who_is_not_double_booked():
    """A second guard on the same full post is refused for the headroom instead.

    This guard holds no other row at all, so the double-booking check passes and
    the request reaches rank 25, where the post's single slot is already taken.

    PRD: "**Post headroom** — the number of assignments on the post whose `assignment_status` is `CONFIRMED` or `COMPLETED` and whose `duty_status` is anything other than `NO_SHOW` is strictly below the post's `required_guard_count`, else `ERR_POST_FULLY_STAFFED` (409)."
    Design: Difficulty/priority_pair_validation_conflict/guard_window_conflict_outranks_post_fully_staffed
    """
    api = ApiClient()
    world = _double_booking_pair_world(api)

    response = api.post_assignment_duty_event(world.a2, action("CONFIRM"), COORDINATOR_HEADERS)
    validate_error(response, ApiErrorId.POST_FULLY_STAFFED)

    row = validate_success(api.get_post_assignment(world.a2, COORDINATOR_HEADERS))
    assert row["assignment_status"] == AssignmentStatus.TENTATIVE

    post = validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS))
    assert_post_fill(post, 1, PostStatus.FILLED)

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 16500, 7.50)


def _vendor_pair_world(api: ApiClient):
    """P1 full, plus a vendor whose certificate lapses before the shift ends."""
    world = build_published_plan_with_posts_world(
        api,
        [
            {"code": "P1", "post_type": PostType.PERIMETER, "required_guard_count": 1},
            {"code": "PF", "post_type": PostType.PERIMETER, "required_guard_count": 4},
        ],
    )
    world.g1_id = create_verified_guard(api, "GC-4001", full_name="Gale One")
    world.a1 = create_assignment(api, world.p1_id, world.g1_id)
    confirm(api, world.a1)

    world.g2_id = create_verified_guard(api, "GC-4002", full_name="Gale Two")
    world.a2 = create_assignment(api, world.p1_id, world.g2_id)

    vendor = validate_success(
        api.create_subcontractor(
            subcontractor_payload(
                company_name="Shortdated Security",
                license_number="SC-4001",
                insurance_expires_on="2026-09-05T00:00:00Z",
                markup_pct=0.20,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.vendor_id = vendor["id"]
    validate_success(
        api.subcontractor_decision(world.vendor_id, action("APPROVE"), AUDITOR_HEADERS)
    )
    guard = validate_success(
        api.create_guard(
            subcontracted_guard_payload("GC-4003", world.vendor_id, full_name="Vendor Hand"),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.g3_id = guard["id"]
    validate_success(
        api.guard_credential_verification(world.g3_id, action("VERIFY"), AUDITOR_HEADERS)
    )
    world.a3 = create_assignment(api, world.p1_id, world.g3_id)
    return world


def test_vendor_eligibility_outranks_post_headroom_on_confirm():
    """A lapsing insurance certificate is reported before the post's missing headroom.

    The vendor was legitimately approved while its certificate still ran, but
    that certificate expires on 5 September and the shift runs to 12 September,
    so rank 20 fires ahead of the full post at rank 25. Neither the guard's own
    verification nor the vendor's approval is disturbed by the refusal.

    PRD: "**Vendor eligibility** — for a guard whose `employment_type` is `SUBCONTRACTED`, the vendor's `status` is `APPROVED` and its `insurance_expires_on` is strictly after the assignment's `window_end`, else `ERR_SUBCONTRACTOR_NOT_ELIGIBLE` (422)."
    Design: Difficulty/priority_pair_validation_conflict/subcontractor_not_eligible_outranks_post_fully_staffed
    """
    api = ApiClient()
    world = _vendor_pair_world(api)

    response = api.post_assignment_duty_event(world.a3, action("CONFIRM"), COORDINATOR_HEADERS)
    validate_error(response, ApiErrorId.SUBCONTRACTOR_NOT_ELIGIBLE)

    guard = validate_success(api.get_guard(world.g3_id, COORDINATOR_HEADERS))
    assert guard["verification_status"] == VerificationStatus.VERIFIED
    vendor = validate_success(api.get_subcontractor(world.vendor_id, COORDINATOR_HEADERS))
    assert vendor["status"] == SubcontractorStatus.APPROVED

    row = validate_success(api.get_post_assignment(world.a3, COORDINATOR_HEADERS))
    assert row["assignment_status"] == AssignmentStatus.TENTATIVE


def test_post_headroom_is_reachable_for_an_employee_on_the_same_full_post():
    """The employee twin of the vendor row is refused for the headroom instead.

    An EMPLOYEE row skips the vendor branch entirely, so the request reaches
    rank 25 and is refused there, which is what proves the vendor rule sits
    above it rather than replacing it.

    PRD: "Later checks are never reached once an earlier one has fired."
    Design: Difficulty/priority_pair_validation_conflict/subcontractor_not_eligible_outranks_post_fully_staffed
    """
    api = ApiClient()
    world = _vendor_pair_world(api)

    response = api.post_assignment_duty_event(world.a2, action("CONFIRM"), COORDINATOR_HEADERS)
    validate_error(response, ApiErrorId.POST_FULLY_STAFFED)

    post = validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS))
    assert_post_fill(post, 1, PostStatus.FILLED)

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert plan["committed_cost_cents"] == 16500
