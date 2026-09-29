"""Two overlap rules with deliberately opposite interval semantics.

A guard's shifts are compared half-open, so two shifts that merely touch at an
instant are two legal shifts. A zone's posts are compared closed, so two windows
that touch at an instant are both counted at that instant and their guard slots
are summed. The same pair of touching timestamps is therefore fine in one rule
and load-bearing in the other, and both directions are pinned here.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    ApiClient,
    ApiErrorId,
    AssignmentStatus,
    PayBasis,
    PlanStatus,
    PostType,
    ReadinessPosture,
    World,
    action,
    assert_assignment_cost,
    assert_coverage,
    assert_ledger,
    build_plan_world,
    build_published_plan_with_posts_world,
    confirm,
    create_assignment,
    create_verified_guard,
    post_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

EARLY_SHIFT_END = "2026-09-12T18:00:00Z"
LATE_SHIFT_START = "2026-09-12T18:00:00Z"
OVERLAP_START = "2026-09-12T17:59:00Z"
OVERLAP_END = "2026-09-12T18:30:00Z"

MORNING_START = "2026-09-12T10:00:00Z"
MIDDAY_HANDOVER = "2026-09-12T18:00:00Z"
OVERNIGHT_HANDOVER = "2026-09-13T02:00:00Z"
DAWN_END = "2026-09-13T04:00:00Z"


def _split_shift_world(api: ApiClient) -> World:
    """One guard on a confirmed early shift, with a touching row pencilled in."""
    world = build_published_plan_with_posts_world(
        api,
        [
            {"code": "P1", "post_type": PostType.PERIMETER, "required_guard_count": 1},
            {"code": "P2", "post_type": PostType.PERIMETER, "required_guard_count": 1},
            {"code": "P3", "post_type": PostType.PERIMETER, "required_guard_count": 1},
            {"code": "PF", "post_type": PostType.PERIMETER, "required_guard_count": 2},
        ],
    )
    world.g1_id = create_verified_guard(api, "GC-7001", full_name="Gale One")

    world.a1 = create_assignment(
        api, world.p1_id, world.g1_id, window_end=EARLY_SHIFT_END
    )
    world.early = confirm(api, world.a1)
    world.a2 = create_assignment(
        api, world.p2_id, world.g1_id, window_start=LATE_SHIFT_START
    )
    return world


def test_a_second_shift_starting_the_instant_the_first_ends_is_accepted():
    """The same guard works 15:00 to 18:00 and then 18:00 to 22:30 on two posts.

    The early shift is three hours at 2200 cents with no night differential. The
    late shift begins at the very instant the early one ends, and because the
    comparison is half-open that is not an overlap, so the 4.50 hour row confirms
    at 9900 cents.

    PRD: "Two back-to-back shifts that merely touch, where the other shift's `window_end` equals this shift's `window_start`, are accepted."
    Design: Difficulty/resource_temporal_overlap/guard_shift_half_open_touching_allowed_overlap_rejected
    """
    api = ApiClient()
    world = _split_shift_world(api)

    assert_assignment_cost(world.early, 3.00, 6600, PayBasis.EMPLOYEE_STRAIGHT)
    assert world.early["night_differential_applies"] is False

    touching = validate_success(
        api.post_assignment_duty_event(world.a2, action("CONFIRM"), COORDINATOR_HEADERS)
    )
    assert touching["assignment_status"] == AssignmentStatus.CONFIRMED
    assert_assignment_cost(touching, 4.50, 9900, PayBasis.EMPLOYEE_STRAIGHT)


def test_a_shift_starting_one_minute_before_the_first_ends_is_refused():
    """A single minute of genuine overlap is enough to refuse the third booking.

    The overlapping row starts at 17:59 and ends at 18:30, so it straddles the end
    of the early shift and the start of the late one. It is allowed to be pencilled
    in even so; the conflict is only resolved when someone tries to commit it, and
    the refused row stays TENTATIVE with the ledger unmoved.

    PRD: "The **double-booking rule** uses half-open interval semantics and is enforced only at confirmation, never at creation — overlapping pencilled-in rows are allowed to exist and are resolved when someone tries to commit one of them."
    Design: Difficulty/resource_temporal_overlap/guard_shift_half_open_touching_allowed_overlap_rejected
    """
    api = ApiClient()
    world = _split_shift_world(api)
    confirm(api, world.a2)
    world.a3 = create_assignment(
        api, world.p3_id, world.g1_id, window_start=OVERLAP_START, window_end=OVERLAP_END
    )

    validate_error(
        api.post_assignment_duty_event(world.a3, action("CONFIRM"), COORDINATOR_HEADERS),
        ApiErrorId.GUARD_WINDOW_CONFLICT,
    )

    refused = validate_success(api.get_post_assignment(world.a3, COORDINATOR_HEADERS))
    assert refused["assignment_status"] == AssignmentStatus.TENTATIVE

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 16500, 7.50)
    assert_coverage(plan, 5, 2, 0.40, ReadinessPosture.BLOCKED)


def _chained_quadrant_world(api: ApiClient) -> World:
    """Draft plan whose floor zone is filled to its 12-slot capacity by two touching posts."""
    world = build_plan_world(api)
    for code, guards, start, end in (
        ("Q1", 6, MORNING_START, MIDDAY_HANDOVER),
        ("Q2", 6, MIDDAY_HANDOVER, OVERNIGHT_HANDOVER),
    ):
        created = validate_success(
            api.create_post(
                world.plan_id,
                post_payload(
                    world.zf_id,
                    code,
                    PostType.PERIMETER,
                    required_guard_count=guards,
                    window_start=start,
                    window_end=end,
                ),
                COORDINATOR_HEADERS,
            ),
            expected_status=201,
        )
        setattr(world, code.lower() + "_id", created["id"])
    return world


def test_touching_post_windows_may_sum_to_exactly_the_zone_slot_capacity():
    """Two six-guard posts handing over at 18:00 put 12 slots in a 12-slot zone.

    Both posts contain the shared 18:00 instant under closed-interval semantics,
    so the aggregate there is 12 — equal to the zone's capacity, and only a sum
    strictly above it is refused. A third six-guard post handing over at 02:00
    from the second is accepted on the same reasoning.

    PRD: "If any of those sums exceeds the zone's `post_slot_capacity`, the request is refused with `ERR_ZONE_POST_CAPACITY_EXCEEDED`."
    Design: Difficulty/resource_temporal_overlap/zone_post_slot_closed_interval_aggregate_capacity
    """
    api = ApiClient()
    world = _chained_quadrant_world(api)

    dawn = validate_success(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zf_id,
                "Q4",
                PostType.PERIMETER,
                required_guard_count=6,
                window_start=OVERNIGHT_HANDOVER,
                window_end=DAWN_END,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    assert dawn["required_guard_count"] == 6

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert plan["status"] == PlanStatus.DRAFT
    assert_coverage(plan, 18, 0, 0.00, ReadinessPosture.BLOCKED)


def test_one_extra_guard_at_the_shared_handover_instant_breaches_the_zone():
    """A single one-guard post spanning 18:00 pushes the aggregate to 13 and is refused.

    Both existing posts count at 18:00, so the zone is already at 12 there. The
    new post asks for one more slot at that same instant, which is one above
    capacity, and the refusal leaves only the two original posts on the plan.

    PRD: "Note that under closed-interval semantics two windows that merely touch at an endpoint **do** overlap, and both posts count at that shared instant."
    Design: Difficulty/resource_temporal_overlap/zone_post_slot_closed_interval_aggregate_capacity
    """
    api = ApiClient()
    world = _chained_quadrant_world(api)

    validate_error(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zf_id,
                "Q3",
                PostType.PERIMETER,
                required_guard_count=1,
                window_start=MIDDAY_HANDOVER,
                window_end="2026-09-12T19:00:00Z",
            ),
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.ZONE_POST_CAPACITY_EXCEEDED,
    )

    posts, meta = validate_paginated(
        api.list_posts(COORDINATOR_HEADERS, params={"staffing_plan_id": world.plan_id})
    )
    assert meta["total_count"] == 2
    assert sorted(post["post_code"] for post in posts) == ["Q1", "Q2"]

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert plan["required_total_staff"] == 12
