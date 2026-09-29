"""Two overlap resources with two different interval algebras.

Shelf plans reserve a (store, item_class) shelf over half-open intervals with no
buffer, so adjacency is free. Promotional windows reserve a (scope, target,
item_class) triple over closed intervals expanded by a buffer day on each end, so
two clear calendar days are needed between neighbours.
"""
from test_helpers import (
    ApiErrorId,
    STORE_SPECS_FOUR,
    create_fixture_plan_payload,
    create_promo_event_payload,
    create_scheduled_promo_event,
    run_detection,
    set_clock,
    setup_network,
    setup_rebalance_network,
    validate_error,
    validate_success,
)

INCUMBENT_PLAN = {
    "fixture_count": 4,
    "facings_per_fixture": 3,
    "units_per_facing": 4,
    "presentation_min_units": 12,
    "effective_to": "2026-09-01T00:00:00Z",
}

TWO_POSITIONS = {
    # S and XL out of 4 CORE sizes: 6 units on a shelf whose minimum is 12.
    "0101": {
        "on_hand_units": 6,
        "size_on_hand": [
            {"size_code": "S", "units": 0},
            {"size_code": "M", "units": 4},
            {"size_code": "L", "units": 2},
            {"size_code": "XL", "units": 0},
        ],
        "min_units": 12,
        "max_units": 48,
        "weekly_forecast_units": 9,
        "trailing_4wk_sales_units": 30,
    },
    # Every CORE size out, and no shelf plan anywhere in this store.
    "0102": {
        "on_hand_units": 0,
        "size_on_hand": [],
        "min_units": 8,
        "max_units": 24,
        "weekly_forecast_units": 5,
        "trailing_4wk_sales_units": 16,
    },
}


def _one_incumbent_plan_over_july_and_august():
    """Store 0101 carries a single APPAREL_TOP plan over [2026-07-01, 2026-09-01) with
    capacity 48; store 0102 has no shelf plan at all. The clock sits at 2026-08-01,
    inside the incumbent."""
    set_clock("2026-08-01T00:00:00Z")
    return setup_network(
        store_specs=STORE_SPECS_FOUR[:2],
        fixture_specs={"0101": dict(INCUMBENT_PLAN)},
        position_specs=TWO_POSITIONS,
    )


def _publish(api, headers, store_id, **overrides):
    return api.create_fixture_plan(
        create_fixture_plan_payload(store_id, **overrides), headers
    )


def test_a_plan_that_starts_exactly_where_the_incumbent_ends_is_adjacent_not_overlapping(
    api, planning_admin_headers
):
    """PRD §3.1: "The plan's effective interval runs from `effective_from` inclusive to
    `effective_to` exclusive, and an omitted or null `effective_to` means the plan runs
    forever." And: "Two plans for the same store and the same merchandise class conflict
    only when their half-open intervals actually intersect; a new plan whose
    `effective_from` falls exactly on an existing plan's `effective_to` is adjacent, not
    overlapping, and is accepted with zero gap between them."

    Both adjacency directions are legal: a successor pinned to the incumbent's exclusive
    end instant, and a predecessor ending on the incumbent's inclusive start instant.

    Design: Difficulty/resource_temporal_overlap/fixture_plan_half_open_intervals_adjacency_versus_intersection
    """
    scenario = _one_incumbent_plan_over_july_and_august()
    store_id = scenario["stores"]["0101"]["id"]

    successor = validate_success(
        _publish(
            api,
            planning_admin_headers,
            store_id,
            effective_from="2026-09-01T00:00:00Z",
            fixture_count=2,
            facings_per_fixture=3,
            units_per_facing=4,
            presentation_min_units=8,
        ),
        201,
    )
    assert successor["effective_from"][:19] == "2026-09-01T00:00:00"
    assert successor["effective_to"] is None
    assert successor["capacity_units"] == 24

    predecessor = validate_success(
        _publish(
            api,
            planning_admin_headers,
            store_id,
            effective_from="2026-06-01T00:00:00Z",
            effective_to="2026-07-01T00:00:00Z",
            fixture_count=1,
            facings_per_fixture=3,
            units_per_facing=4,
            presentation_min_units=6,
        ),
        201,
    )
    assert predecessor["capacity_units"] == 12


def test_a_window_strictly_inside_the_incumbent_is_refused_as_an_overlap(
    api, planning_admin_headers
):
    """PRD §3.1: "Plan intervals are **half-open with no buffer**. Two plans for the same
    store and the same merchandise class conflict only when their half-open intervals
    actually intersect; a new plan whose `effective_from` falls exactly on an existing
    plan's `effective_to` is adjacent, not overlapping, and is accepted with zero gap
    between them. An overlap is refused with `ERR_FIXTURE_PLAN_OVERLAP`."

    A window wholly contained by the incumbent intersects it at every instant, and the
    refusal persists nothing.

    Design: Difficulty/resource_temporal_overlap/fixture_plan_half_open_intervals_adjacency_versus_intersection
    """
    scenario = _one_incumbent_plan_over_july_and_august()
    store_id = scenario["stores"]["0101"]["id"]

    validate_error(
        _publish(
            api,
            planning_admin_headers,
            store_id,
            effective_from="2026-08-15T00:00:00Z",
            effective_to="2026-08-20T00:00:00Z",
            fixture_count=1,
            facings_per_fixture=2,
            units_per_facing=3,
            presentation_min_units=4,
        ),
        ApiErrorId.ERR_FIXTURE_PLAN_OVERLAP.value,
        409,
    )

    surviving = validate_success(
        api.list_fixture_plans(
            planning_admin_headers,
            params={"store_id": store_id, "item_class": "APPAREL_TOP", "limit": 100},
        )
    )
    assert len(surviving) == 1
    assert surviving[0]["id"] == scenario["fixture_plans"]["0101"]["id"]


def test_a_null_effective_to_reserves_the_whole_tail_of_the_calendar(
    api, planning_admin_headers
):
    """PRD §3.1: "The plan's effective interval runs from `effective_from` inclusive to
    `effective_to` exclusive, and an omitted or null `effective_to` means the plan runs
    forever." And: "Two plans for the same store and the same merchandise class conflict
    only when their half-open intervals actually intersect; a new plan whose
    `effective_from` falls exactly on an existing plan's `effective_to` is adjacent, not
    overlapping, and is accepted with zero gap between them. An overlap is refused with
    `ERR_FIXTURE_PLAN_OVERLAP`."

    Once the open-ended successor exists, a bounded window that begins after it does
    intersects it, because an unbounded tail has no end instant to be adjacent to.

    Design: Difficulty/resource_temporal_overlap/fixture_plan_half_open_intervals_adjacency_versus_intersection
    """
    scenario = _one_incumbent_plan_over_july_and_august()
    store_id = scenario["stores"]["0101"]["id"]
    validate_success(
        _publish(
            api,
            planning_admin_headers,
            store_id,
            effective_from="2026-09-01T00:00:00Z",
            fixture_count=2,
            facings_per_fixture=3,
            units_per_facing=4,
            presentation_min_units=8,
        ),
        201,
    )

    validate_error(
        _publish(
            api,
            planning_admin_headers,
            store_id,
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-09-15T00:00:00Z",
            fixture_count=1,
            facings_per_fixture=1,
            units_per_facing=4,
            presentation_min_units=2,
        ),
        ApiErrorId.ERR_FIXTURE_PLAN_OVERLAP.value,
        409,
    )


def test_the_reserved_resource_is_the_store_and_class_pair_not_the_store_alone(
    api, planning_admin_headers
):
    """PRD §3.1: "Shelf capacity is expressed as a **shelf plan** published by
    `PlanningAdmin` for exactly one merchandise class in exactly one store over a bounded
    interval." And: "Two plans for the same store and the same merchandise class conflict
    only when their half-open intervals actually intersect; a new plan whose
    `effective_from` falls exactly on an existing plan's `effective_to` is adjacent, not
    overlapping, and is accepted with zero gap between them."

    An APPAREL_BOTTOM plan running forever from 2026-07-01 fully covers both APPAREL_TOP
    windows and is still accepted, and exactly one of the three APPAREL_TOP plans contains
    the clock.

    Design: Difficulty/resource_temporal_overlap/fixture_plan_half_open_intervals_adjacency_versus_intersection
    """
    scenario = _one_incumbent_plan_over_july_and_august()
    store_id = scenario["stores"]["0101"]["id"]
    for extra in (
        {"effective_from": "2026-09-01T00:00:00Z", "fixture_count": 2,
         "facings_per_fixture": 3, "units_per_facing": 4, "presentation_min_units": 8},
        {"effective_from": "2026-06-01T00:00:00Z", "effective_to": "2026-07-01T00:00:00Z",
         "fixture_count": 1, "facings_per_fixture": 3, "units_per_facing": 4,
         "presentation_min_units": 6},
    ):
        validate_success(_publish(api, planning_admin_headers, store_id, **extra), 201)

    bottoms = validate_success(
        _publish(
            api,
            planning_admin_headers,
            store_id,
            item_class="APPAREL_BOTTOM",
            effective_from="2026-07-01T00:00:00Z",
            fixture_count=2,
            facings_per_fixture=2,
            units_per_facing=5,
            presentation_min_units=5,
        ),
        201,
    )
    assert bottoms["capacity_units"] == 20

    tops = validate_success(
        api.list_fixture_plans(
            planning_admin_headers,
            params={"store_id": store_id, "item_class": "APPAREL_TOP", "limit": 100},
        )
    )
    assert len(tops) == 3
    covering_the_clock = [
        plan
        for plan in tops
        if plan["effective_from"][:19] <= "2026-08-01T00:00:00"
        and (plan["effective_to"] is None or plan["effective_to"][:19] > "2026-08-01T00:00:00")
    ]
    assert len(covering_the_clock) == 1
    assert covering_the_clock[0]["id"] == scenario["fixture_plans"]["0101"]["id"]


def test_the_sweep_is_all_or_nothing_when_one_position_has_no_plan_in_effect(
    api, allocation_manager_headers
):
    """PRD §3.1: "Downstream, four operations need a plan to be in effect for the SKU's
    class at the store, meaning the plan whose half-open interval contains the current
    logical clock: proposing a spread, committing a spread, approving a transfer, and
    running the assortment detection sweep." PRD §3.9: "The sweep needs a shelf plan in
    effect for the SKU's class at the store, and its absence is reported as
    `ERR_NO_FIXTURE_PLAN_IN_EFFECT`."

    Store 0102 has no shelf plan at all, and that one gap takes the whole sweep down:
    store 0101 is degraded and covered, yet no action is left behind for it.

    Design: Difficulty/resource_temporal_overlap/fixture_plan_half_open_intervals_adjacency_versus_intersection
    """
    scenario = _one_incumbent_plan_over_july_and_august()

    validate_error(
        api.run_assortment_detection(
            {"program_id": scenario["program"]["id"]}, allocation_manager_headers
        ),
        ApiErrorId.ERR_NO_FIXTURE_PLAN_IN_EFFECT.value,
        422,
    )

    assert (
        validate_success(
            api.list_assortment_actions(
                allocation_manager_headers,
                params={"item_id": scenario["item"]["id"], "limit": 100},
            )
        )
        == []
    )


def test_covering_the_gap_lets_the_identical_sweep_raise_both_actions(
    api, planning_admin_headers, allocation_manager_headers
):
    """PRD §3.9: "The actions the sweep returns are ordered by the store's `store_code`
    ascending and then by the SKU's `sku_code` ascending — this is one of the few places a
    list is not ordered by `created_at`." And: "The resulting `markdown_pct_bp` is then
    read off four tiers, each lower-inclusive and upper-exclusive: a broken ratio below
    2500 gives 0, a ratio from 2500 up to but not including 5000 gives 1500, a ratio from
    5000 up to but not including 7500 gives 3000, and a ratio of 7500 or above gives 4500."

    Publishing the missing [2026-07-01, 2026-09-01) plan for 0102 turns the refusal into a
    two-action sweep: 0101 is 2 of 4 CORE sizes down (5000bp, tier 3000) and 0102 is 4 of
    4 down (10000bp, tier 4500). Neither gets a consolidation target because no position of
    the SKU is COMPLETE, and 0101's snapshot of 6 available units proves the in-effect
    plan was the one that framed it.

    Design: Difficulty/resource_temporal_overlap/fixture_plan_half_open_intervals_adjacency_versus_intersection
    """
    scenario = _one_incumbent_plan_over_july_and_august()
    validate_success(
        _publish(
            api,
            planning_admin_headers,
            scenario["stores"]["0102"]["id"],
            effective_from="2026-07-01T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
            fixture_count=2,
            facings_per_fixture=3,
            units_per_facing=4,
            presentation_min_units=8,
        ),
        201,
    )

    raised = run_detection(scenario["program"]["id"], allocation_manager_headers)
    assert len(raised) == 2
    assert [action["store_id"] for action in raised] == [
        scenario["stores"]["0101"]["id"],
        scenario["stores"]["0102"]["id"],
    ]

    thin, empty = raised
    assert thin["action_type"] == "MARKDOWN"
    assert thin["markdown_pct_bp"] == 3000
    assert thin["consolidation_target_store_id"] is None
    assert thin["units_at_detection"] == 6

    assert empty["action_type"] == "MARKDOWN"
    assert empty["markdown_pct_bp"] == 4500
    assert empty["consolidation_target_store_id"] is None
    assert empty["units_at_detection"] == 0


BTS_A = {
    "event_code": "BTS-A",
    "scope": "STORE",
    "item_class": "APPAREL_TOP",
    "start_date": "2026-08-05T00:00:00Z",
    "end_date": "2026-08-10T00:00:00Z",
    "lift_factor_bp": 11000,
}


def _calendar_with_one_scheduled_incumbent():
    """Three stores and one SCHEDULED STORE-scope APPAREL_TOP event on 0101 over the
    closed window [2026-08-05, 2026-08-10], whose buffered footprint is therefore
    [2026-08-04, 2026-08-11]."""
    scenario = setup_rebalance_network()
    scenario["incumbent"] = create_scheduled_promo_event(
        scenario["program"]["id"],
        store_id=scenario["stores"]["0101"]["id"],
        **BTS_A,
    )
    return scenario


def _propose_event(api, headers, scenario, **overrides):
    return api.create_promo_event(
        create_promo_event_payload(scenario["program"]["id"], **overrides), headers
    )


def test_a_follower_needs_two_clear_days_after_a_buffered_window(
    api, planning_admin_headers
):
    """PRD §3.5: "Two events may not fight over the same ground. Promotional windows are
    treated as **closed intervals** — both `start_date` and `end_date` are inside the
    window — and before any overlap test each window is **expanded by one buffer day on
    each end**." And: "The check runs at creation **and** runs again when the event is
    scheduled, because peers may have been scheduled in between. A conflict is refused with
    `ERR_PROMO_WINDOW_CONFLICT`."

    The incumbent ends 08-10, so it reserves through 08-11. A follower starting 08-11 is
    buffered back to 08-10 and collides outright; one starting 08-12 is buffered back to
    08-11 and still touches, because closed intervals that share an endpoint do intersect;
    08-13 is the first legal start.

    Design: Difficulty/resource_temporal_overlap/promo_event_buffered_closed_windows_per_scope_target_and_class
    """
    scenario = _calendar_with_one_scheduled_incumbent()
    on_the_same_store = {
        "scope": "STORE",
        "store_id": scenario["stores"]["0101"]["id"],
        "item_class": "APPAREL_TOP",
        "lift_factor_bp": 10500,
    }

    for code, start, end in (
        ("BTS-B", "2026-08-11T00:00:00Z", "2026-08-15T00:00:00Z"),
        ("BTS-C", "2026-08-12T00:00:00Z", "2026-08-15T00:00:00Z"),
    ):
        validate_error(
            _propose_event(
                api,
                planning_admin_headers,
                scenario,
                event_code=code,
                start_date=start,
                end_date=end,
                **on_the_same_store,
            ),
            ApiErrorId.ERR_PROMO_WINDOW_CONFLICT.value,
            409,
        )

    cleared = validate_success(
        _propose_event(
            api,
            planning_admin_headers,
            scenario,
            event_code="BTS-D",
            start_date="2026-08-13T00:00:00Z",
            end_date="2026-08-18T00:00:00Z",
            **on_the_same_store,
        ),
        201,
    )
    assert cleared["status"] == "DRAFT"
    assert cleared["start_date"][:19] == "2026-08-13T00:00:00"


def test_the_same_window_is_free_on_another_target_and_in_another_scope(
    api, planning_admin_headers
):
    """PRD §3.5: "Two events conflict only when all three of the following hold: they share
    the same `scope` and the same target, meaning the same `store_id` for `STORE` scope, the
    same `cluster_code` for `CLUSTER` scope, and program-wide for `PROGRAM` scope; their
    merchandise classes overlap, meaning their `item_class` values are equal or at least one
    of them is null; and their buffered windows intersect."

    The identical window is accepted twice over: once on a different store, and once at
    CLUSTER scope on URBAN — the cluster that contains the incumbent's own store — because
    scope must match before the target is even compared.

    Design: Difficulty/resource_temporal_overlap/promo_event_buffered_closed_windows_per_scope_target_and_class
    """
    scenario = _calendar_with_one_scheduled_incumbent()
    assert scenario["stores"]["0101"]["cluster_code"] == "URBAN"

    neighbour = validate_success(
        _propose_event(
            api,
            planning_admin_headers,
            scenario,
            event_code="BTS-E",
            scope="STORE",
            store_id=scenario["stores"]["0102"]["id"],
            item_class="APPAREL_TOP",
            start_date="2026-08-05T00:00:00Z",
            end_date="2026-08-10T00:00:00Z",
            lift_factor_bp=11000,
        ),
        201,
    )
    assert neighbour["scope"] == "STORE"
    assert neighbour["cluster_code"] is None

    wider = validate_success(
        _propose_event(
            api,
            planning_admin_headers,
            scenario,
            event_code="BTS-F",
            scope="CLUSTER",
            cluster_code="URBAN",
            item_class="APPAREL_TOP",
            start_date="2026-08-05T00:00:00Z",
            end_date="2026-08-10T00:00:00Z",
            lift_factor_bp=12500,
        ),
        201,
    )
    assert wider["scope"] == "CLUSTER"
    assert wider["store_id"] is None


def test_an_event_with_no_item_class_collides_with_every_class(
    api, planning_admin_headers
):
    """PRD §3.5: "Independently of scope, an optional `item_class` restricts the event to a
    single merchandise class; leaving it null applies the event to every class." And: "their
    merchandise classes overlap, meaning their `item_class` values are equal or at least one
    of them is null; and their buffered windows intersect."

    Same store, same window, class omitted: the class test passes on the null side, so the
    creation is refused.

    Design: Difficulty/resource_temporal_overlap/promo_event_buffered_closed_windows_per_scope_target_and_class
    """
    scenario = _calendar_with_one_scheduled_incumbent()

    validate_error(
        _propose_event(
            api,
            planning_admin_headers,
            scenario,
            event_code="BTS-G",
            scope="STORE",
            store_id=scenario["stores"]["0101"]["id"],
            start_date="2026-08-05T00:00:00Z",
            end_date="2026-08-10T00:00:00Z",
            lift_factor_bp=10800,
        ),
        ApiErrorId.ERR_PROMO_WINDOW_CONFLICT.value,
        409,
    )


def test_two_draft_events_may_be_stacked_and_the_loser_only_learns_at_schedule_time(
    api, planning_admin_headers
):
    """PRD §3.5: "Only an incumbent whose `status` is `SCHEDULED` or `ACTIVE` can be
    conflicted with — `DRAFT`, `ENDED` and `CANCELLED` events are invisible to the test. The
    check runs at creation **and** runs again when the event is scheduled, because peers may
    have been scheduled in between." And: "`DRAFT → SCHEDULED` re-runs the buffered conflict
    test against every `SCHEDULED` or `ACTIVE` peer."

    Two events on store 0103, the second strictly inside the first, are both created without
    complaint. Scheduling the inner one succeeds; the outer one then loses the same test it
    passed at creation and stays DRAFT.

    Design: Difficulty/resource_temporal_overlap/promo_event_buffered_closed_windows_per_scope_target_and_class
    """
    scenario = _calendar_with_one_scheduled_incumbent()
    on_the_quiet_store = {
        "scope": "STORE",
        "store_id": scenario["stores"]["0103"]["id"],
        "item_class": "APPAREL_TOP",
    }

    outer = validate_success(
        _propose_event(
            api,
            planning_admin_headers,
            scenario,
            event_code="BTS-H",
            start_date="2026-08-05T00:00:00Z",
            end_date="2026-08-10T00:00:00Z",
            lift_factor_bp=11000,
            **on_the_quiet_store,
        ),
        201,
    )
    inner = validate_success(
        _propose_event(
            api,
            planning_admin_headers,
            scenario,
            event_code="BTS-I",
            start_date="2026-08-06T00:00:00Z",
            end_date="2026-08-09T00:00:00Z",
            lift_factor_bp=11500,
            **on_the_quiet_store,
        ),
        201,
    )
    assert outer["status"] == "DRAFT"
    assert inner["status"] == "DRAFT"

    scheduled = validate_success(
        api.schedule_promo_event(inner["id"], planning_admin_headers)
    )
    assert scheduled["status"] == "SCHEDULED"

    validate_error(
        api.schedule_promo_event(outer["id"], planning_admin_headers),
        ApiErrorId.ERR_PROMO_WINDOW_CONFLICT.value,
        409,
    )
    assert (
        validate_success(api.get_promo_event(outer["id"], planning_admin_headers))["status"]
        == "DRAFT"
    )


def test_the_refused_creations_leave_the_calendar_exactly_as_they_found_it(
    api, planning_admin_headers
):
    """PRD §3.5: "A `PlanningAdmin` creates one against a `program_id` with an `event_code`
    unique within that program — a duplicate is refused with `ERR_DUPLICATE_EVENT_CODE` — a
    `scope`, a window running from `start_date` to `end_date` where the end must not precede
    the start, and a `lift_factor_bp` multiplier in basis points that must be at least 10000,
    so an event can amplify a forecast but never suppress it. An event is created in `DRAFT`."

    Walking the whole calendar — three refused creations among nine attempts, then two
    schedule attempts of which one is refused — leaves six events: the incumbent and BTS-I
    SCHEDULED, and BTS-D, BTS-E, BTS-F and the schedule-refused BTS-H still DRAFT. None of
    the three rejected codes exists.

    Design: Difficulty/resource_temporal_overlap/promo_event_buffered_closed_windows_per_scope_target_and_class
    """
    scenario = _calendar_with_one_scheduled_incumbent()
    store_0101 = scenario["stores"]["0101"]["id"]
    store_0103 = scenario["stores"]["0103"]["id"]

    refused = (
        {"event_code": "BTS-B", "scope": "STORE", "store_id": store_0101,
         "item_class": "APPAREL_TOP", "start_date": "2026-08-11T00:00:00Z",
         "end_date": "2026-08-15T00:00:00Z", "lift_factor_bp": 10500},
        {"event_code": "BTS-C", "scope": "STORE", "store_id": store_0101,
         "item_class": "APPAREL_TOP", "start_date": "2026-08-12T00:00:00Z",
         "end_date": "2026-08-15T00:00:00Z", "lift_factor_bp": 10500},
        {"event_code": "BTS-G", "scope": "STORE", "store_id": store_0101,
         "start_date": "2026-08-05T00:00:00Z", "end_date": "2026-08-10T00:00:00Z",
         "lift_factor_bp": 10800},
    )
    accepted = (
        {"event_code": "BTS-D", "scope": "STORE", "store_id": store_0101,
         "item_class": "APPAREL_TOP", "start_date": "2026-08-13T00:00:00Z",
         "end_date": "2026-08-18T00:00:00Z", "lift_factor_bp": 10500},
        {"event_code": "BTS-E", "scope": "STORE", "store_id": scenario["stores"]["0102"]["id"],
         "item_class": "APPAREL_TOP", "start_date": "2026-08-05T00:00:00Z",
         "end_date": "2026-08-10T00:00:00Z", "lift_factor_bp": 11000},
        {"event_code": "BTS-F", "scope": "CLUSTER", "cluster_code": "URBAN",
         "item_class": "APPAREL_TOP", "start_date": "2026-08-05T00:00:00Z",
         "end_date": "2026-08-10T00:00:00Z", "lift_factor_bp": 12500},
        {"event_code": "BTS-H", "scope": "STORE", "store_id": store_0103,
         "item_class": "APPAREL_TOP", "start_date": "2026-08-05T00:00:00Z",
         "end_date": "2026-08-10T00:00:00Z", "lift_factor_bp": 11000},
        {"event_code": "BTS-I", "scope": "STORE", "store_id": store_0103,
         "item_class": "APPAREL_TOP", "start_date": "2026-08-06T00:00:00Z",
         "end_date": "2026-08-09T00:00:00Z", "lift_factor_bp": 11500},
    )

    created = {}
    for payload in refused:
        validate_error(
            _propose_event(api, planning_admin_headers, scenario, **payload),
            ApiErrorId.ERR_PROMO_WINDOW_CONFLICT.value,
            409,
        )
    for payload in accepted:
        event = validate_success(
            _propose_event(api, planning_admin_headers, scenario, **payload), 201
        )
        created[payload["event_code"]] = event

    validate_success(api.schedule_promo_event(created["BTS-I"]["id"], planning_admin_headers))
    validate_error(
        api.schedule_promo_event(created["BTS-H"]["id"], planning_admin_headers),
        ApiErrorId.ERR_PROMO_WINDOW_CONFLICT.value,
        409,
    )

    calendar = validate_success(
        api.list_promo_events(
            planning_admin_headers,
            params={"program_id": scenario["program"]["id"], "limit": 100},
        )
    )
    by_code = {event["event_code"]: event["status"] for event in calendar}
    assert by_code == {
        "BTS-A": "SCHEDULED",
        "BTS-D": "DRAFT",
        "BTS-E": "DRAFT",
        "BTS-F": "DRAFT",
        "BTS-H": "DRAFT",
        "BTS-I": "SCHEDULED",
    }
