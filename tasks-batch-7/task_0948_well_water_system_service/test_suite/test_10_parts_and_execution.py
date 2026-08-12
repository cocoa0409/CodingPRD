"""Posting parts: the money gates, the stock gates and the conservation identity."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_close,
    assert_instant_equals,
    assert_money,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def _conservation_world():
    """Twenty units on hand and three of them posted against an IN_PROGRESS job."""
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Conserve Creek",
        email="ap@conserve.example",
        membership_tier="NONE",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="20 Conserve Creek",
        drawdown=8.0,
        technician_name="Nils Grant",
    )
    part = fixtures.new_part("CTL-3000-C", "CONTROL", 3000, on_hand_qty=20)
    stage = fixtures.emergency_work_order_in_progress(world)
    entry = fixtures.post_parts(
        stage["work_order_id"], world["technician_id"], part["id"], 3
    )
    world.update(
        {
            "part_id": part["id"],
            "work_order_id": stage["work_order_id"],
            "entry_id": entry["id"],
        }
    )
    return world


def test_posting_decrements_stock_and_cancelling_restores_it_exactly(api):
    """PRD 2.12: "For every catalog part, the sum of its `on_hand_qty` and the quantities
    of all consumption rows for that part whose status is `POSTED` is invariant across
    posting and reversal."
    PRD 3.9: "From `IN_PROGRESS` it runs the inventory compensating action: every
    `POSTED` consumption entry on the work order moves to `REVERSED` and each catalog
    part's `on_hand_qty` is restored by exactly that entry's quantity, leaving the
    conservation identity of Section 2.12 exactly where it was before the postings."

    Design: Difficulty/compensating_invariant/parts_inventory_units_conserved_across_posting_and_work_order_cancel
    """
    world = _conservation_world()
    mid = fixtures.get_part(world["part_id"])
    assert mid["on_hand_qty"] == 17, "Posting must decrement stock at the instant of posting"
    posted, _ = validate_paginated(
        api.list_parts_consumption_entries(
            DISPATCHER, params={"part_catalog_item_id": world["part_id"], "status": "POSTED"}
        )
    )
    assert mid["on_hand_qty"] + sum(row["quantity"] for row in posted) == 20

    validate_success(api.cancel_work_order(world["work_order_id"], DISPATCHER))

    after = fixtures.get_part(world["part_id"])
    assert after["on_hand_qty"] == 20
    still_posted, _ = validate_paginated(
        api.list_parts_consumption_entries(
            DISPATCHER, params={"part_catalog_item_id": world["part_id"], "status": "POSTED"}
        )
    )
    assert after["on_hand_qty"] + sum(row["quantity"] for row in still_posted) == 20


def test_cancelling_an_in_progress_job_reverses_its_consumption_rows(api):
    """PRD 2.12: "Cancelling an in-progress work order is the compensating action: every
    `POSTED` row on it moves to `REVERSED` and `on_hand_qty` is restored by exactly that
    quantity. Work-order completion moves no stock at all — it only freezes prices — so
    the identity holds across it too. Rows in `REVERSED` never participate in the sum."
    PRD 3.9: "**Cancellation** is a dispatcher's or admin's act and is available from
    `DRAFT`, `SCHEDULED` or `IN_PROGRESS`."

    Design: Difficulty/compensating_invariant/parts_inventory_units_conserved_across_posting_and_work_order_cancel
    """
    world = _conservation_world()
    cancelled = validate_success(
        api.cancel_work_order(world["work_order_id"], DISPATCHER)
    )
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["billing_status"] == "NOT_BILLABLE"
    assert fixtures.get_consumption_entry(world["entry_id"])["status"] == "REVERSED"


def test_stock_moves_at_posting_while_the_parts_charge_waits_for_completion(api):
    """PRD 3.9: "Posting **immediately** decrements `on_hand_qty` by the quantity and
    raises the catalog part's `version` by 1."
    PRD 3.9: "A posted entry stores `unit_cost_cents_snapshot`, `markup_pct_applied`,
    `unit_price_cents` and `extended_price_cents`, stamps `posted_at` from the logical
    clock and opens at `status` `POSTED`, the other member being `REVERSED`."
    PRD 3.9: "The row opens at `fulfillment_status` `DRAFT` and `billing_status`
    `NOT_BILLABLE`, with `origin_callback_claim_id`, `hold_reason`, the scheduled and
    actual instants, `actual_labor_minutes`, `billable_minutes` and
    `labor_rate_cents_per_hour` all null, `labor_charge_cents` and `parts_charge_cents`
    0, `callback_eligibility` `NONE` and `callback_attempt_count` 0."

    Design: Corner/consistency_model/corner_consistency_stock_moves_at_posting_not_at_completion
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Stock Immediate Co",
        email="sm@corner.example",
        address_line="10 Stock",
        technician_tier="MASTER",
        technician_name="Stock Immediate Tech",
    )
    part = fixtures.new_part("CTL-5000-M", "CONTROL", 5000, on_hand_qty=10)
    stage = fixtures.emergency_work_order_in_progress(world)

    first = validate_success(
        api.post_parts_consumption(
            stage["work_order_id"],
            {"part_catalog_item_id": part["id"], "quantity": 3},
            world["technician_headers"],
        ),
        201,
    )
    assert_money(first["extended_price_cents"], 24000, "PartsConsumptionEntry.extended_price_cents")
    assert fixtures.get_part(part["id"])["on_hand_qty"] == 7

    second = validate_success(
        api.post_parts_consumption(
            stage["work_order_id"],
            {"part_catalog_item_id": part["id"], "quantity": 2},
            world["technician_headers"],
        ),
        201,
    )
    assert_money(second["extended_price_cents"], 16000, "PartsConsumptionEntry.extended_price_cents")
    assert fixtures.get_part(part["id"])["on_hand_qty"] == 5

    assert_money(first["unit_price_cents"], 8000, "PartsConsumptionEntry.unit_price_cents")
    assert first["status"] == "POSTED"
    assert_money(
        second["unit_cost_cents_snapshot"], 5000, "PartsConsumptionEntry.unit_cost_cents_snapshot"
    )
    assert_close(
        second["markup_pct_applied"], 0.60, "PartsConsumptionEntry.markup_pct_applied"
    )
    assert_instant_equals(
        first["posted_at"], "2026-06-01T12:00:00Z", "PartsConsumptionEntry.posted_at"
    )

    work_order = fixtures.get_work_order(stage["work_order_id"])
    assert work_order["fulfillment_status"] == "IN_PROGRESS"
    assert_money(work_order["parts_charge_cents"], 0, "WorkOrder.parts_charge_cents")
    rows, _ = validate_paginated(
        api.list_work_order_parts_consumption(stage["work_order_id"], DISPATCHER)
    )
    assert len(rows) == 2


def test_the_three_parts_business_gates_each_own_their_error(api):
    """PRD 3.9: "The part must exist and be `ACTIVE`, or the answers are
    `ERR_PART_CATALOG_ITEM_NOT_FOUND` and `ERR_PART_DISCONTINUED` respectively. The
    quantity must not exceed 50, or the answer is `ERR_QUANTITY_EXCEEDS_LIMIT`, and the
    part's `on_hand_qty` must be at least the requested quantity, or the answer is
    `ERR_PART_OUT_OF_STOCK`."

    Design: Corner/validations/corner_parts_business_gate_family_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Parts Gate Co",
        email="pg@corner.example",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="2 Parts",
        technician_name="Parts Tech",
    )
    part_ok = fixtures.new_part("CTL-LOW-STOCK", "CONTROL", 3000, on_hand_qty=2)
    part_dead = fixtures.new_part(
        "CTL-DEAD", "CONTROL", 3000, on_hand_qty=50, status="DISCONTINUED"
    )
    stage = fixtures.emergency_work_order_in_progress(world)

    validate_error(
        api.post_parts_consumption(
            stage["work_order_id"],
            {"part_catalog_item_id": part_ok["id"], "quantity": 51},
            world["technician_headers"],
        ),
        ApiErrorId.ERR_QUANTITY_EXCEEDS_LIMIT.value,
        422,
    )
    validate_error(
        api.post_parts_consumption(
            stage["work_order_id"],
            {"part_catalog_item_id": part_dead["id"], "quantity": 1},
            world["technician_headers"],
        ),
        ApiErrorId.ERR_PART_DISCONTINUED.value,
        422,
    )
    validate_error(
        api.post_parts_consumption(
            stage["work_order_id"],
            {"part_catalog_item_id": part_ok["id"], "quantity": 3},
            world["technician_headers"],
        ),
        ApiErrorId.ERR_PART_OUT_OF_STOCK.value,
        409,
    )
    assert fixtures.get_part(part_ok["id"])["on_hand_qty"] == 2
    rows, _ = validate_paginated(
        api.list_work_order_parts_consumption(stage["work_order_id"], DISPATCHER)
    )
    assert rows == []


def test_a_discontinued_part_is_refused_before_its_empty_shelf_is_consulted(api):
    """PRD 3.9: "The part must exist and be `ACTIVE`, or the answers are
    `ERR_PART_CATALOG_ITEM_NOT_FOUND` and `ERR_PART_DISCONTINUED` respectively. The
    quantity must not exceed 50, or the answer is `ERR_QUANTITY_EXCEEDS_LIMIT`, and the
    part's `on_hand_qty` must be at least the requested quantity, or the answer is
    `ERR_PART_OUT_OF_STOCK`."
    PRD 2.6: "Sub-gate **G9B** then runs cross-entity business rules in this fixed
    internal order: safety and potability first, then capacity and temporal overlap, then
    quantity and stock, then fiscal rules (credit hold, payment, caps)."

    Design: Corner/errors/corner_error_part_discontinued_outranks_part_out_of_stock
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Stock Order Co",
        email="so@corner.example",
        address_line="0 Stock",
        technician_tier="MASTER",
        technician_name="Stock Tech",
    )
    part_disc = fixtures.new_part(
        "CTL-DISC-0", "CONTROL", 5000, on_hand_qty=0, status="DISCONTINUED"
    )
    part_act = fixtures.new_part("CTL-ACT-0", "CONTROL", 5000, on_hand_qty=0)
    stage = fixtures.emergency_work_order_in_progress(world)

    validate_error(
        api.post_parts_consumption(
            stage["work_order_id"],
            {"part_catalog_item_id": part_disc["id"], "quantity": 1},
            world["technician_headers"],
        ),
        ApiErrorId.ERR_PART_DISCONTINUED.value,
        422,
    )
    validate_error(
        api.post_parts_consumption(
            stage["work_order_id"],
            {"part_catalog_item_id": part_act["id"], "quantity": 1},
            world["technician_headers"],
        ),
        ApiErrorId.ERR_PART_OUT_OF_STOCK.value,
        409,
    )
    rows, _ = validate_paginated(
        api.list_work_order_parts_consumption(stage["work_order_id"], DISPATCHER)
    )
    assert rows == []
    assert fixtures.get_part(part_disc["id"])["on_hand_qty"] == 0
    assert fixtures.get_part(part_act["id"])["on_hand_qty"] == 0
    assert_money(
        fixtures.get_work_order(stage["work_order_id"])["parts_charge_cents"],
        0,
        "WorkOrder.parts_charge_cents",
    )


def test_the_three_emergency_money_gates_each_own_their_error(api):
    """PRD 3.9: "On the emergency pipeline two further rules apply: a ticket diagnosed
    `NON_WELL_CAUSE` forbids parts entirely, refused with
    `ERR_NON_WELL_CAUSE_BLOCKS_PARTS`, and a ticket whose authorisation axis is `PENDING`
    refuses the posting with `ERR_AUTHORIZATION_REQUIRED`."
    PRD 3.9: "On a `PRE_AUTHORIZED` emergency work order, the cumulative posted parts plus
    the work order's labour charge — the sum of the extended prices of every `POSTED`
    entry including the one being posted, plus the work order's current
    `labor_charge_cents`, which is 0 until completion — must not exceed the ticket's
    `preauth_cap_cents`, failing which is `ERR_PREAUTH_CAP_EXCEEDED`."

    Design: Corner/validations/corner_emergency_money_gates_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Money Gate Co", "JUR_BRAVO", "mg@corner.example")
    prop = fixtures.new_property(account["id"], "3 Money", "JUR_BRAVO", 20.0, 3)
    wells = [
        fixtures.new_well(prop["id"], "JUR_BRAVO", "DRILLED", depth)
        for depth in (200.0, 205.0, 210.0)
    ]
    technician = fixtures.new_technician("Money Tech", "JOURNEYMAN", "JUR_BRAVO")
    part = fixtures.new_part("CTL-60000", "CONTROL", 60000, on_hand_qty=20)

    plan = [
        ("NON_WELL_CAUSE", 10000, "2026-06-01T12:00:00Z", "2026-06-01T13:00:00Z"),
        ("PUMP_FAILURE", 200000, "2026-06-01T15:00:00Z", "2026-06-01T16:00:00Z"),
        ("CONTROL_FAILURE", 20000, "2026-06-01T18:00:00Z", "2026-06-01T19:00:00Z"),
    ]
    tickets = []
    work_orders = []
    for well, (cause, estimate, start_at, end_at) in zip(wells, plan):
        ticket = fixtures.diagnosed_ticket(
            prop["id"], well["id"], account["id"], technician["id"], cause, estimate
        )
        work_order = fixtures.new_work_order(
            prop["id"], well["id"], technician["id"], "REPAIR",
            emergency_ticket_id=ticket["id"],
        )
        fixtures.schedule_work_order(work_order["id"], start_at, end_at)
        tickets.append(ticket)
        work_orders.append(work_order)

    fixtures.set_clock("2026-06-01T12:00:00Z")
    for work_order in work_orders:
        fixtures.start_work_order(work_order["id"], technician["id"])

    expected = [
        ApiErrorId.ERR_NON_WELL_CAUSE_BLOCKS_PARTS.value,
        ApiErrorId.ERR_AUTHORIZATION_REQUIRED.value,
        ApiErrorId.ERR_PREAUTH_CAP_EXCEEDED.value,
    ]
    statuses = [422, 402, 402]
    for work_order, error_id, status in zip(work_orders, expected, statuses):
        validate_error(
            api.post_parts_consumption(
                work_order["id"],
                {"part_catalog_item_id": part["id"], "quantity": 1},
                fixtures.make_technician_headers(technician["id"]),
            ),
            error_id,
            status,
        )

    assert fixtures.get_ticket(tickets[1]["id"])["authorization_status"] == "PENDING"
    third = fixtures.get_ticket(tickets[2]["id"])
    assert third["authorization_status"] == "PRE_AUTHORIZED"
    assert_money(third["preauth_cap_cents"], 75000, "EmergencyTicket.preauth_cap_cents")
    assert fixtures.get_part(part["id"])["on_hand_qty"] == 20


def test_each_payload_gate_row_owns_a_distinct_error(api):
    """PRD 2.7: "`ERR_INVALID_TIMESTAMP` (HTTP 400) is raised when a datetime **body**
    field on a mutating endpoint does not parse as an ISO 8601 UTC instant."
    PRD 2.7: "`ERR_NEGATIVE_QUANTITY` (HTTP 400) is raised when a quantity, amount or
    pounds body field is **strictly** negative."
    PRD 2.4: "a `to_iso8601` strictly before the current clock is rejected with
    `ERR_CLOCK_BACKWARD` (HTTP 400)"
    PRD 2.3: "A `limit` of 0, a `limit` above 100, a negative `offset`, or a value of
    either that is not an integer is rejected with `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/validations/corner_payload_gate_family_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Payload Co",
        email="pl@corner.example",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="1 Payload",
        technician_name="Payload Tech",
    )
    part = fixtures.new_part("CTL-3000-H", "CONTROL", 3000, on_hand_qty=20)
    stage = fixtures.emergency_work_order_in_progress(world)

    validate_error(
        api.create_water_test(
            {
                "well_profile_id": world["well_id"],
                "collected_by_technician_id": world["technician_id"],
                "panel_type": "BACTERIOLOGICAL",
                "sample_datetime": "01/06/2026 08:00",
            },
            world["technician_headers"],
        ),
        ApiErrorId.ERR_INVALID_TIMESTAMP.value,
        400,
    )
    validate_error(
        api.post_parts_consumption(
            stage["work_order_id"],
            {"part_catalog_item_id": part["id"], "quantity": -2},
            world["technician_headers"],
        ),
        ApiErrorId.ERR_NEGATIVE_QUANTITY.value,
        400,
    )
    validate_error(
        api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, ADMIN),
        ApiErrorId.ERR_CLOCK_BACKWARD.value,
        400,
    )
    validate_error(
        api.list_technicians(ADMIN, params={"limit": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        400,
    )

    assert fixtures.get_part(part["id"])["on_hand_qty"] == 20
    assert_instant_equals(
        fixtures.read_clock()["current_utc"],
        "2026-06-01T12:00:00Z",
        "clock.current_utc",
    )


def test_the_logical_clock_may_stand_still_but_never_move_backward(api):
    """PRD 2.4: "The clock may move forward or stay where it is, but never backwards: a
    `to_iso8601` strictly before the current clock is rejected with `ERR_CLOCK_BACKWARD`
    (HTTP 400), and a `to_iso8601` that is not a parseable ISO 8601 UTC instant is
    rejected with `ERR_INVALID_TIMESTAMP` (HTTP 400)."
    PRD 2.4: "A `PlatformAdmin` advances it by supplying a `to_iso8601` instant to the
    clock-advance capability; the response reports `current_utc` and `previous_utc`."

    Design: Corner/validations/corner_validation_clock_may_stand_still_but_never_move_backward
    """
    first = validate_success(
        api.set_clock({"to_iso8601": "2026-06-01T09:00:00Z"}, ADMIN)
    )
    assert_instant_equals(
        first["previous_utc"], "2026-05-01T00:00:00Z", "clock.previous_utc"
    )

    same = validate_success(api.set_clock({"to_iso8601": "2026-06-01T09:00:00Z"}, ADMIN))
    assert_instant_equals(same["current_utc"], "2026-06-01T09:00:00Z", "clock.current_utc")
    assert_instant_equals(
        same["previous_utc"], "2026-06-01T09:00:00Z", "clock.previous_utc"
    )

    validate_error(
        api.set_clock({"to_iso8601": "2026-06-01T08:59:59Z"}, ADMIN),
        ApiErrorId.ERR_CLOCK_BACKWARD.value,
        400,
    )
    assert_instant_equals(
        validate_success(api.get_clock(ADMIN))["current_utc"],
        "2026-06-01T09:00:00Z",
        "clock.current_utc",
    )
