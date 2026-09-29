"""Read-after-write, on the deepest cascade the system performs.

One confirmation touches an assignment, a post, a plan and an event. This case
checks that every one of those levels is readable at its new value the instant the
request returns, and that the plan's computed read agrees with what the write
already reported.
"""

from test_helpers import (
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ApiClient,
    GatePosture,
    PostStatus,
    PostType,
    ReadinessPosture,
    assert_coverage,
    assert_ledger,
    assert_post_fill,
    build_published_plan_with_posts_world,
    confirm,
    create_assignment,
    create_verified_guard,
    validate_success,
)


def test_every_hop_of_a_confirmation_is_readable_the_instant_the_request_returns():
    """No deferral anywhere on the four-level chain.

    The confirmation's own response already carries the priced shift, and the
    follow-up reads of the post, the plan and the event agree with it — including
    the event's gate, which the same request re-derived and which the pre-plan
    variant of the posture ladder resolves to OPEN while the event is still
    RISK_ASSESSED. The second confirmation's second-order effects are visible the
    same way, and the computed read afterwards matches the write-time figures to
    the cent.

    PRD: "In the same request the ledger is synchronised: the row's `line_cost_cents` is added to the plan's `committed_cost_cents`, the row's `scheduled_hours` is added to the plan's `committed_guard_hours`, and `budget_remaining_cents` is set to `budget_cents` minus `committed_cost_cents`."
    Design: Corner/consistency_model/all_cascade_effects_are_visible_in_the_same_request_response
    """
    api = ApiClient()
    world = build_published_plan_with_posts_world(
        api,
        [
            {
                "code": "S1",
                "post_type": PostType.SUPERVISOR,
                "required_guard_count": 1,
                "min_credential_level": 3,
            },
            {"code": "P1", "post_type": PostType.PERIMETER, "required_guard_count": 4},
        ],
    )
    supervisor_guard = create_verified_guard(
        api, "GC-7401", credential_level=3, full_name="Sam Sentinel"
    )
    line_guard = create_verified_guard(api, "GC-7402", full_name="Gale One")
    a_s1 = create_assignment(api, world.s1_id, supervisor_guard)
    a_p1 = create_assignment(api, world.p1_id, line_guard)

    first = confirm(api, a_s1)
    assert first["scheduled_hours"] == 7.50
    assert first["line_cost_cents"] == 16500

    assert_post_fill(
        validate_success(api.get_post(world.s1_id, COORDINATOR_HEADERS)), 1, PostStatus.FILLED
    )
    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 16500, 7.50, budget_remaining_cents=483500)
    assert_coverage(plan, 5, 1, 0.20, ReadinessPosture.BLOCKED)
    assert plan["understaffed_post_count"] == 0
    assert (
        validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))["gate_posture"]
        == GatePosture.OPEN
    )

    confirm(api, a_p1)
    assert_post_fill(
        validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS)),
        1,
        PostStatus.PARTIALLY_STAFFED,
    )
    plan_after = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(plan_after, 5, 2, 0.40, ReadinessPosture.BLOCKED)
    assert_ledger(plan_after, 33000, 15.00, budget_remaining_cents=467000)

    summary = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(summary, 5, 2, 0.40, ReadinessPosture.BLOCKED)
    assert_ledger(summary, 33000, 15.00, budget_remaining_cents=467000)
