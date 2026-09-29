"""Reads, listings and action dispatch, exercised on their own terms.

These cases treat the surface of the API as the thing under test: which query
parameters a listing honours, what a computed read projects, that a read writes
nothing, and that an action verb is checked for shape before any state machine is
consulted.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ApiClient,
    ApiErrorId,
    AssignmentStatus,
    DutyStatus,
    EventStatus,
    GatePosture,
    LaneStatus,
    PostStatus,
    PostType,
    ReadinessPosture,
    action,
    assert_coverage,
    assert_coverage_summary_shape,
    assert_ledger,
    brief,
    build_approved_assessment_world,
    build_briefed_event_world,
    build_five_post_activated_world,
    check_in,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PRE_DOORS_INSTANT = "2026-09-12T16:30:00Z"


def test_the_coverage_summary_projects_nine_derived_figures_and_writes_nothing():
    """A fully covered plan, read twice around a plan read.

    The projection carries exactly the nine declared keys and no others, with the
    money conserved against the authorised budget. Reading it twice with a plan
    read in between returns identical figures and leaves the plan's version where
    it was — a computed read is not a mutation.

    PRD: "These figures, together with `committed_cost_cents`, `budget_remaining_cents` and `committed_guard_hours`, are also exposed as a dedicated computed read on the plan."
    Design: Corner/endpoints/coverage_summary_returns_derived_plan_metrics
    """
    api = ApiClient()
    world = build_briefed_event_world(api)

    first = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage_summary_shape(first)
    assert_coverage(first, 5, 5, 1.00, ReadinessPosture.READY)
    assert first["understaffed_post_count"] == 0
    assert first["supervisor_coverage_ok"] is True
    assert_ledger(first, 82500, 37.50, budget_remaining_cents=417500)

    plan = validate_success(api.get_staffing_plan(world.plan_id, DIRECTOR_HEADERS))
    assert_coverage(plan, 5, 5, 1.00, ReadinessPosture.READY)
    assert_ledger(plan, 82500, 37.50, budget_remaining_cents=417500)
    version_between_reads = plan["version"]

    second = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert second == first
    assert (
        validate_success(api.get_staffing_plan(world.plan_id, DIRECTOR_HEADERS))["version"]
        == version_between_reads
    )


def test_the_post_listing_honours_each_declared_filter_and_paginates():
    """Six filters over four posts, then a two-page walk.

    Each filter is an exact match on one column, so the supervisor's three
    subordinates exclude the supervisor itself and the lane filter picks out only
    the ingress post that operates it. A filter that matches nothing is a 200 with
    an empty page, not a 404.

    PRD: "The post list accepts `staffing_plan_id`, `zone_id`, `reports_to_post_id`, `lane_id`, `post_type` and `status`."
    Design: Corner/endpoints/posts_list_filters_by_plan_type_supervisor_and_lane_and_paginates
    """
    api = ApiClient()
    world = build_briefed_event_world(api)
    plan_filter = {"staffing_plan_id": world.plan_id}

    rows, meta = validate_paginated(api.list_posts(COORDINATOR_HEADERS, params=plan_filter))
    assert meta["total_count"] == 4
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert len(rows) == 4

    rows, meta = validate_paginated(
        api.list_posts(
            COORDINATOR_HEADERS,
            params=dict(plan_filter, post_type=PostType.INGRESS_SCREENING),
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == world.i1_id
    assert rows[0]["required_guard_count"] == 2

    rows, meta = validate_paginated(
        api.list_posts(COORDINATOR_HEADERS, params={"reports_to_post_id": world.s1_id})
    )
    assert meta["total_count"] == 3
    assert sorted(row["id"] for row in rows) == sorted([world.i1_id, world.f1_id, world.e1_id])

    rows, meta = validate_paginated(
        api.list_posts(COORDINATOR_HEADERS, params={"lane_id": world.lane1_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == world.i1_id

    _, meta = validate_paginated(
        api.list_posts(COORDINATOR_HEADERS, params=dict(plan_filter, status=PostStatus.FILLED))
    )
    assert meta["total_count"] == 4

    rows, meta = validate_paginated(
        api.list_posts(COORDINATOR_HEADERS, params=dict(plan_filter, limit=2, offset=0))
    )
    assert len(rows) == 2
    assert meta["total_count"] == 4
    assert meta["has_more"] is True

    rows, meta = validate_paginated(
        api.list_posts(COORDINATOR_HEADERS, params=dict(plan_filter, limit=2, offset=2))
    )
    assert len(rows) == 2
    assert meta["total_count"] == 4
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api.list_posts(COORDINATOR_HEADERS, params=dict(plan_filter, post_type=PostType.PERIMETER))
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert meta["has_more"] is False


def test_a_lifecycle_verb_is_checked_for_shape_before_any_transition_is_attempted():
    """Four malformed verbs, four identical 400s.

    A plausible-but-wrong verb, the right verb in the wrong case, a missing key
    and an empty string all fail on shape rather than on state — none of them
    produces the 409 that a well-formed but out-of-order verb would. The event is
    untouched, version included.

    PRD: "**Body schema** — required fields present, enum values drawn from the declared member sets, integers and numbers inside their declared ranges, `window_end` strictly after `window_start`, `event_start_at` strictly after `doors_open_at`, `event_end_at` strictly after `event_start_at`, and a guard whose `employment_type` is `SUBCONTRACTED` carrying a `subcontractor_id` while a guard whose `employment_type` is `EMPLOYEE` carries none."
    Design: Corner/endpoints/event_lifecycle_rejects_unknown_action_and_missing_action
    """
    api = ApiClient()
    world = build_approved_assessment_world(api)
    before = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert before["status"] == EventStatus.RISK_ASSESSED

    for body in ({"action": "OPEN_DOORS"}, {"action": "brief"}, {}, {"action": ""}):
        validate_error(
            api.event_lifecycle(world.event_id, body, DIRECTOR_HEADERS),
            ApiErrorId.INVALID_REQUEST,
        )

    after = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert after["status"] == EventStatus.RISK_ASSESSED
    assert after["version"] == before["version"]
    assert after["gate_posture"] == before["gate_posture"]


def test_an_assignment_is_reachable_from_its_post_and_from_its_guard_alike():
    """The junction carries both foreign keys, and both are filterable.

    The two-guard ingress post yields two rows; either guard alone yields one; the
    two filters together intersect to a single row whose direct read shows both
    keys explicitly. The roster and duty columns filter independently over the
    same five rows.

    PRD: "The assignment list accepts `post_id`, `guard_id`, `assignment_status` and `duty_status`."
    Design: Corner/endpoints/assignment_is_reachable_from_both_its_post_and_its_guard
    """
    api = ApiClient()
    world = build_briefed_event_world(api)

    _, meta = validate_paginated(
        api.list_post_assignments(COORDINATOR_HEADERS, params={"post_id": world.i1_id})
    )
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api.list_post_assignments(COORDINATOR_HEADERS, params={"guard_id": world.g1_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["post_id"] == world.i1_id

    rows, meta = validate_paginated(
        api.list_post_assignments(
            COORDINATOR_HEADERS, params={"post_id": world.i1_id, "guard_id": world.g2_id}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == world.a_i2

    direct = validate_success(api.get_post_assignment(world.a_i2, COORDINATOR_HEADERS))
    assert direct["post_id"] == world.i1_id
    assert direct["guard_id"] == world.g2_id

    _, meta = validate_paginated(
        api.list_post_assignments(
            COORDINATOR_HEADERS,
            params={
                "assignment_status": AssignmentStatus.CONFIRMED,
                "duty_status": DutyStatus.BRIEFED,
            },
        )
    )
    assert meta["total_count"] == 5

    _, meta = validate_paginated(
        api.list_post_assignments(
            COORDINATOR_HEADERS, params={"assignment_status": AssignmentStatus.TENTATIVE}
        )
    )
    assert meta["total_count"] == 0


def test_opening_a_lane_checks_the_event_state_before_it_counts_operators():
    """Two conditions, surfaced strictly in order by the same request.

    While the event is only STAFFED the lane is both wrongly-timed and unstaffed,
    and it is the state condition that answers. Once the night is briefed the same
    call reveals the second condition instead. One operator opens the lane at half
    rate, and the second operator's check-in alone lifts the throughput to full
    without any further status call.

    PRD: "Opening a lane from `PLANNED` requires the event's `status` to be `BRIEFED`, `DOORS_OPEN` or `IN_PROGRESS` (else `ERR_INVALID_STATE`), requires `assigned_operator_count` of at least 1 (else `ERR_LANE_UNSTAFFED`), and respects the gate interlock; it sets `status` to `OPEN` and re-derives `effective_throughput_pph`."
    Design: Corner/endpoints/lane_open_is_gated_by_event_state_then_by_operator_presence
    """
    api = ApiClient()
    world = build_five_post_activated_world(api)
    assert (
        validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))["status"]
        == EventStatus.STAFFED
    )

    validate_error(
        api.screening_lane_status(world.lane1_id, action("OPEN"), COORDINATOR_HEADERS),
        ApiErrorId.INVALID_STATE,
    )

    channels = {
        world.a_s1: "CH1",
        world.a_i1: "CH2",
        world.a_i2: "CH2",
        world.a_f1: "CH3",
        world.a_e1: "CH4",
    }
    for assignment_id, channel in channels.items():
        brief(api, assignment_id, world.gs_id, radio_channel=channel)
    briefed = validate_success(
        api.event_lifecycle(world.event_id, action("BRIEF"), DIRECTOR_HEADERS)
    )
    assert briefed["status"] == EventStatus.BRIEFED
    assert briefed["gate_posture"] == GatePosture.OPEN
    set_clock(api, PRE_DOORS_INSTANT)

    validate_error(
        api.screening_lane_status(world.lane1_id, action("OPEN"), COORDINATOR_HEADERS),
        ApiErrorId.LANE_UNSTAFFED,
    )

    check_in(api, world.a_i1, world.gs_id)
    opened = validate_success(
        api.screening_lane_status(world.lane1_id, action("OPEN"), COORDINATOR_HEADERS)
    )
    assert opened["status"] == LaneStatus.OPEN
    assert opened["effective_throughput_pph"] == 87
    # Created at 1; the first operator's check-in re-derived assigned_operator_count
    # 0 -> 1 (a derived-field-only mutation, PRD 2.4) for 2; the OPEN transition is 3.
    assert opened["version"] == 3

    check_in(api, world.a_i2, world.gs_id)
    full = validate_success(api.get_screening_lane(world.lane1_id, COORDINATOR_HEADERS))
    assert full["assigned_operator_count"] == 2
    assert full["effective_throughput_pph"] == 175
    assert full["status"] == LaneStatus.OPEN
