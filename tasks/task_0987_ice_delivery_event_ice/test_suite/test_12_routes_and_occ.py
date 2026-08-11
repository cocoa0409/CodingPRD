"""Recurring routes, standing-order generation, and optimistic concurrency
(PRD §2.5, §2.7, §3.3, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    agent,
    get_success_data,
    make_customer,
    make_depot,
    make_route,
    make_active_book,
    mini_book_payload,
    order_line,
    make_order,
    quoted_order,
    run_ops,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _setup(customer_name, depot_name, limit=200000):
    depot = make_depot(10, depot_name)
    set_logical_clock()
    cust = make_customer(
        account_name=customer_name, kind="BAR_RESTAURANT", tier="STANDARD",
        credit_terms="NET_30", credit_limit_cents=limit,
    )
    return depot, cust


def test_route_weekday_uniqueness_conflict(api):
    """PRD §3.3: "One customer may hold at most one live route per weekday:
    creating a route, or resuming a paused one, while another route for the
    same customer and weekday is `ACTIVE` or `PAUSED` fails with
    `ERR_ROUTE_SCHEDULE_CONFLICT`."
    PRD §3.3: "terminating from either state lands on `TERMINATED`, excluding
    the route from all future order generation."

    Design: Corner/state_machines/route_weekday_uniqueness_conflict
    """
    depot, cust = _setup("S18", "Depot S18")
    r1 = make_route(cust["id"], depot["id"], weekday="MON",
                    window_start="08:00", window_end="10:00")

    from test_helpers import route_payload

    resp = api.create_route(
        route_payload(
            cust["id"], depot["id"], "MON", "11:00", "12:00",
            [{"product_form": "BLOCK", "packaging": "PALLET", "quantity_units": 2}],
        ),
        agent(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_SCHEDULE_CONFLICT)

    terminated = validate_success(api.terminate_route(r1["id"], agent(cust["id"])))
    assert terminated["status"] == "TERMINATED"

    r3 = make_route(cust["id"], depot["id"], weekday="MON",
                    window_start="11:00", window_end="12:00",
                    standing_lines=[{"product_form": "BLOCK", "packaging": "PALLET",
                                     "quantity_units": 2}])
    assert r3["status"] == "ACTIVE", "conflict cleared once R1 terminated"


def test_occ_route_patch_stale_version(api):
    """PRD §3.3: "The patch is one of the platform's two OCC-guarded writes: it
    must carry `expected_route_version` equal to the route's current `version`,
    and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a
    pause/resume cycle or an earlier patch will have advanced the version
    beyond what the client observed (§2.7)."

    Design: Corner/cross_cutting_complexity_layers/occ_route_patch_stale_version
    """
    depot, cust = _setup("X53", "Depot X53", limit=100000)
    route = make_route(cust["id"], depot["id"], weekday="MON",
                       window_start="08:00", window_end="10:00")
    r_ver = route["version"]

    patched = validate_success(
        api.patch_standing_order(
            route["id"],
            {
                "expected_route_version": r_ver,
                "standing_lines": [
                    {"product_form": "BLOCK", "packaging": "PALLET", "quantity_units": 3}
                ],
            },
            agent(cust["id"]),
        )
    )
    assert patched["version"] == r_ver + 1, "fresh patch succeeds and bumps"

    resp = api.patch_standing_order(
        route["id"],
        {
            "expected_route_version": r_ver,
            "standing_lines": [
                {"product_form": "BLOCK", "packaging": "PALLET", "quantity_units": 5}
            ],
        },
        agent(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_occ_reprice_stale_version(api):
    """PRD §2.7: "A request to reprice an order must carry
    `expected_order_version` holding the order's `version` as the client last
    observed it."
    PRD §2.7: "if the supplied value does not match the entity's current
    `version` — meaning another write, such as a prior reprice or a
    pause/resume cycle, has advanced the entity since the client last read it —
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412)".
    PRD §2.5: "`version` (integer): a system-managed integer incremented by one
    on every mutation".

    Design: Corner/cross_cutting_complexity_layers/occ_reprice_stale_version
    """
    depot, cust = _setup("X52", "Depot X52")
    make_active_book(mini_book_payload())
    order = make_order(
        cust["id"], depot["id"], [order_line("BLOCK", "PALLET", 1)],
        channel="WILL_CALL", event_date="2026-05-10",
        window_start="10:00", window_end="12:00",
    )
    v_create = order["version"]
    quoted = validate_success(api.quote_order(order["id"], agent(cust["id"])))
    q_ver = quoted["version"]
    assert q_ver == v_create + 1, "quoting mutates the order once"

    repriced = validate_success(
        api.reprice_order(order["id"], {"expected_order_version": q_ver}, agent(cust["id"]))
    )
    assert repriced["version"] == q_ver + 1, (
        "reprice with the last observed version succeeds and increments"
    )

    resp = api.reprice_order(order["id"], {"expected_order_version": q_ver}, agent(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    # replaying the stale observed version is rejected with 412


# ----------------- difficulty: route pause/resume generation cycle ---------------

def test_route_pause_resume_generation_cycle(api):
    """PRD §3.3: "For each `ACTIVE` route the sweep finds the next occurrence:
    the first date bearing the route's `weekday` that falls strictly after
    `last_generated_date` — or, while that field is still null, on or after the
    current logical date — and no more than three days beyond the current
    logical date."
    PRD §3.3: "Pausing flips `ACTIVE` to `PAUSED`; resuming flips back,
    re-running the weekday-uniqueness check".
    PRD §3.9: "Seventh, route generation: each `ACTIVE` route spawns its next
    occurrence as described in §3.3, within a lead horizon of three days beyond
    the current logical date, idempotent per date through
    `last_generated_date`."

    Design: Difficulty/non_linear_state_machine/recurring_route_pause_resume_cycle
    """
    # Clock starts on Friday 2026-05-01; the route's weekday is Monday.
    depot, cust = _setup("SM2 Bar", "Depot SM2", limit=100000)
    route = make_route(cust["id"], depot["id"], weekday="MON",
                       window_start="08:00", window_end="10:00",
                       standing_lines=[{"product_form": "BLOCK", "packaging": "PALLET",
                                        "quantity_units": 1}])
    assert route["status"] == "ACTIVE", "a new route is immediately ACTIVE"

    validate_success(api.pause_route(route["id"], agent(cust["id"])))
    ops_paused = run_ops(depot["id"])
    assert ops_paused["generated_order_ids"] == [], (
        "PAUSED routes are skipped by route generation"
    )

    resumed = validate_success(api.resume_route(route["id"], agent(cust["id"])))
    assert resumed["status"] == "ACTIVE", "cycle PAUSED -> ACTIVE completed"

    ops_resumed = run_ops(depot["id"])
    assert len(ops_resumed["generated_order_ids"]) == 1
    spawned, meta = validate_paginated(
        api.list_orders(ADMIN, params={"recurring_route_id": route["id"]})
    )
    assert meta["total_count"] == 1
    assert spawned[0]["fulfillment_status"] == "DRAFT"
    assert spawned[0]["event_date"] == "2026-05-04", (
        "first Monday within the lead horizon"
    )

    route_after = get_success_data(api.get_route(route["id"], agent(cust["id"])))
    assert route_after["last_generated_date"] == "2026-05-04"

    ops_again = run_ops(depot["id"])
    assert ops_again["generated_order_ids"] == [], (
        "idempotent per date; the next Monday is beyond clock + 3 days"
    )


def test_route_spawned_order_copies_window_and_lines(api):
    """PRD §3.3: "Each occurrence spawns a new order in `DRAFT` with channel
    `DELIVERY`, its `recurring_route_id` pointing back to the route,
    `event_date` set to the occurrence date, and the window and lines copied
    from the route's window and `standing_lines`".

    Design: Difficulty/non_linear_state_machine/recurring_route_pause_resume_cycle
    """
    depot, cust = _setup("SM2b Bar", "Depot SM2b", limit=100000)
    route = make_route(cust["id"], depot["id"], weekday="MON",
                       window_start="08:00", window_end="10:00",
                       standing_lines=[{"product_form": "BLOCK", "packaging": "PALLET",
                                        "quantity_units": 2}])
    ops = run_ops(depot["id"])
    assert len(ops["generated_order_ids"]) == 1

    spawned, _meta = validate_paginated(
        api.list_orders(ADMIN, params={"recurring_route_id": route["id"]})
    )
    order = spawned[0]
    assert order["recurring_route_id"] == route["id"]
    assert order["channel"] == "DELIVERY"
    assert order["event_date"] == "2026-05-04"
    assert order["window_start"] == "08:00" and order["window_end"] == "10:00", (
        "window copied from the route"
    )
    assert order["fulfillment_status"] == "DRAFT"
    assert order["billing_status"] == "UNBILLED"

    lines, _meta = validate_paginated(
        api.list_order_lines(order["id"], ADMIN)
    )
    assert len(lines) == 1
    assert lines[0]["product_form"] == "BLOCK"
    assert lines[0]["packaging"] == "PALLET"
    assert lines[0]["quantity_units"] == 2, "lines copied from standing_lines"
