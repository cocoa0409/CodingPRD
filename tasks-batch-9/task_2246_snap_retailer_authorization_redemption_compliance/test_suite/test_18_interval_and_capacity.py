"""Three interval families with three different conventions.

Inspector windows are half-open with a travel buffer, terminal deployments are
closed on both ends, and the store's terminal slots are an aggregate ceiling that
allows exact equality.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    INV_PASS,
    ApiErrorId,
    api_client,
    application_payload,
    assert_depot_conservation,
    assert_inspector_minutes,
    assert_row_count,
    authorized_store,
    create_depot,
    create_inspector,
    create_owner,
    create_store,
    create_terminal,
    created,
    deployment_payload,
    ok,
    owner_headers,
    refresh_application,
    refresh_depot,
    refresh_inspector,
    refresh_store,
    refresh_terminal,
    schedule_visit,
    store_visit_payload,
    validate_error,
)

CORNER_STORE = {
    "store_name": "Rio Corner Market",
    "checkout_lane_count": 1,
    "staple_shelf_linear_feet": 30,
    "annual_gross_sales_cents": 24000000,
    "annual_staple_sales_cents": 14000000,
    "max_terminal_slots": 1,
    "tax_rate_bps": None,
    "hardship_designated": None,
}


def _two_submitted_applications():
    """One owner, two stores, two submitted CRITERION_A applications, one
    inspector with a 480-minute daily ceiling."""
    owner = create_owner()
    store_a = create_store(owner)
    store_b = create_store(owner, **CORNER_STORE)
    applications = []
    for store in (store_a, store_b):
        application = created(
            api_client.create_application(
                application_payload(
                    store["id"], store["version"], reported_inventory_lines=INV_PASS
                ),
                owner_headers(owner),
            )
        )
        ok(api_client.submit_application(application["id"], owner_headers(owner)))
        applications.append(application)
    return owner, applications, create_inspector()


def _book(application, inspector, start, end):
    return api_client.create_store_visit(
        store_visit_payload(
            application["id"], inspector["id"], window_start=start, window_end=end
        ),
        ANALYST,
    )


def test_inspector_window_one_minute_inside_the_travel_buffer_is_refused():
    """Against an existing 09:00-11:00 visit, a second window starting at 11:59 is
    refused for the same inspector, even at a different store.

    The specification pins the boundary exactly: "against an existing window from
    09:00 to 11:00, a new window from 12:00 to 13:00 is accepted, because 12:00 is
    not earlier than 12:00; a new window from 11:59 to 12:59 is refused." The
    sixty-minute travel buffer is what pushes the refusal boundary out to 12:00.

    Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_with_travel_buffer_boundary_one_minute_apart
    """
    _owner, applications, inspector = _two_submitted_applications()
    morning = schedule_visit(
        applications[0],
        inspector,
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T11:00:00Z",
    )
    assert morning["window_minutes"] == 120

    response = _book(
        applications[1], inspector, "2026-08-01T11:59:00Z", "2026-08-01T12:59:00Z"
    )

    validate_error(response, ApiErrorId.ERR_INSPECTOR_WINDOW_CONFLICT.value, 409)
    assert_row_count(
        api_client.list_store_visits(ADMIN, {"inspector_id": inspector["id"]}), 1
    )


def test_inspector_window_exactly_at_the_buffer_edge_is_accepted():
    """One minute later -- 12:00 -- the same booking is accepted, and the
    inspector's committed minutes are the plain sum of the two windows.

    The specification warns against conflating the two figures: "Note that the
    travel buffer widens the *conflict* test but is never added to the *minute*
    total." So 120 plus 60 is 180, comfortably inside the 480-minute ceiling, and
    the second application advances to PENDING_VISIT.

    Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_with_travel_buffer_boundary_one_minute_apart
    """
    _owner, applications, inspector = _two_submitted_applications()
    schedule_visit(
        applications[0],
        inspector,
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T11:00:00Z",
    )
    _book(applications[1], inspector, "2026-08-01T11:59:00Z", "2026-08-01T12:59:00Z")

    afternoon = created(
        _book(applications[1], inspector, "2026-08-01T12:00:00Z", "2026-08-01T13:00:00Z")
    )

    assert afternoon["window_minutes"] == 60
    assert_inspector_minutes(refresh_inspector(inspector["id"]), 180)
    assert refresh_application(applications[1]["id"])["status"] == "PENDING_VISIT"
    assert_row_count(
        api_client.list_store_visits(ADMIN, {"inspector_id": inspector["id"]}), 2
    )


def _store_with_terminal():
    context = authorized_store()
    depot = create_depot(total_units_owned=5)
    terminal = create_terminal(depot)
    return context, depot, terminal


def test_deployment_starting_on_the_previous_end_date_collides():
    """Deployment intervals are closed at both ends, so a booking that starts on
    the day the previous one ends is refused.

    The specification gives the boundary in the opposite convention to the
    inspector windows: "against an existing commitment ending 2026-09-30, a new
    commitment starting 2026-09-30 is refused and one starting 2026-10-01 is
    accepted."

    Design: Difficulty/resource_temporal_overlap/terminal_deployment_closed_interval_touching_endpoint_collides
    """
    context, _depot, terminal = _store_with_terminal()
    created(
        api_client.create_terminal_deployment(
            deployment_payload(
                context.store_id,
                terminal["id"],
                deploy_start="2026-08-01T00:00:00Z",
                deploy_end="2026-09-30T00:00:00Z",
            ),
            ADMIN,
        )
    )

    response = api_client.create_terminal_deployment(
        deployment_payload(
            context.store_id,
            terminal["id"],
            deploy_start="2026-09-30T00:00:00Z",
            deploy_end="2026-10-31T00:00:00Z",
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_TERMINAL_ALREADY_COMMITTED.value, 409)


def test_deployment_starting_the_next_day_is_accepted_without_double_reserving():
    """A booking starting 2026-10-01 is accepted, and the one physical unit is
    still counted as reserved exactly once.

    Two non-overlapping commitments on the same terminal do not consume two units:
    the depot identity requires the five counters to sum to `total_units_owned`,
    so `units_reserved` stays at 1 with 4 still in stock.

    Design: Difficulty/resource_temporal_overlap/terminal_deployment_closed_interval_touching_endpoint_collides
    """
    context, depot, terminal = _store_with_terminal()
    created(
        api_client.create_terminal_deployment(
            deployment_payload(
                context.store_id,
                terminal["id"],
                deploy_start="2026-08-01T00:00:00Z",
                deploy_end="2026-09-30T00:00:00Z",
            ),
            ADMIN,
        )
    )

    second = created(
        api_client.create_terminal_deployment(
            deployment_payload(
                context.store_id,
                terminal["id"],
                deploy_start="2026-10-01T00:00:00Z",
                deploy_end="2026-10-31T00:00:00Z",
            ),
            ADMIN,
        )
    )

    assert second["status"] == "RESERVED"
    assert refresh_terminal(terminal["id"])["status"] == "RESERVED"
    assert_depot_conservation(
        refresh_depot(depot["id"]), {"units_reserved": 1, "units_in_stock": 4}
    )
    assert_row_count(
        api_client.list_terminal_deployments(ADMIN, {"terminal_id": terminal["id"]}), 2
    )


def _three_terminals_at_one_store():
    context, depot, terminal1 = _store_with_terminal()
    terminal2 = create_terminal(depot, serial_number="EBT-0002", model="EBT_ONLY_DIAL")
    terminal3 = create_terminal(
        depot, serial_number="EBT-0003", model="EBT_ONLY_WIRELESS"
    )
    created(
        api_client.create_terminal_deployment(
            deployment_payload(
                context.store_id,
                terminal1["id"],
                deploy_start="2026-08-01T00:00:00Z",
                deploy_end="2026-12-31T00:00:00Z",
            ),
            ADMIN,
        )
    )
    return context, depot, terminal2, terminal3


def test_second_concurrent_deployment_is_accepted_at_exact_slot_equality():
    """A second overlapping deployment brings peak concurrency to exactly the
    store's two slots, and equality is allowed.

    The specification permits the boundary explicitly: "that maximum plus one must
    be at or below the store's `max_terminal_slots`, with equality allowed", so
    the second booking is a normal RESERVED commitment.

    Design: Difficulty/resource_temporal_overlap/store_terminal_slot_aggregate_capacity_allows_equality_refuses_third
    """
    context, depot, terminal2, _terminal3 = _three_terminals_at_one_store()

    second = created(
        api_client.create_terminal_deployment(
            deployment_payload(
                context.store_id,
                terminal2["id"],
                deploy_start="2026-09-01T00:00:00Z",
                deploy_end="2027-01-31T00:00:00Z",
            ),
            ADMIN,
        )
    )

    assert second["status"] == "RESERVED"
    assert_depot_conservation(
        refresh_depot(depot["id"]), {"units_reserved": 2, "units_in_stock": 3}
    )


def test_third_overlapping_deployment_exceeds_the_aggregate_slot_ceiling():
    """A third deployment whose window sits inside the overlap of the first two
    pushes peak concurrency to three and is refused, reserving nothing.

    The ceiling is aggregate rather than pairwise: each interval is individually
    conflict-free on its own unit, so only the store-level peak concurrency count
    can refuse it. The refused booking leaves the third terminal in stock and the
    store with nothing activated.

    Design: Difficulty/resource_temporal_overlap/store_terminal_slot_aggregate_capacity_allows_equality_refuses_third
    """
    context, depot, terminal2, terminal3 = _three_terminals_at_one_store()
    created(
        api_client.create_terminal_deployment(
            deployment_payload(
                context.store_id,
                terminal2["id"],
                deploy_start="2026-09-01T00:00:00Z",
                deploy_end="2027-01-31T00:00:00Z",
            ),
            ADMIN,
        )
    )

    response = api_client.create_terminal_deployment(
        deployment_payload(
            context.store_id,
            terminal3["id"],
            deploy_start="2026-10-01T00:00:00Z",
            deploy_end="2026-11-01T00:00:00Z",
        ),
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_STORE_TERMINAL_SLOTS_EXCEEDED.value, 409)
    assert refresh_terminal(terminal3["id"])["status"] == "IN_STOCK"
    assert_depot_conservation(
        refresh_depot(depot["id"]), {"units_reserved": 2, "units_in_stock": 3}
    )
    assert_row_count(
        api_client.list_terminal_deployments(ADMIN, {"store_id": context.store_id}), 2
    )
    assert refresh_store(context.store_id)["active_terminal_count"] == 0
