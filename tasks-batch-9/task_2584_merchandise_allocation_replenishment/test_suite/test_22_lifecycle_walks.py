"""Lifecycle walks: declared initial states, every declared transition, and the
refusals that guard the transitions the PRD never declares.

Each test builds its own preconditions through the PRD's own endpoints, because
the server is restarted and the database wiped before every test.
"""
from test_helpers import (
    ADMIN,
    ALLOCATOR,
    DEFAULT_CLOCK_UTC,
    FIXTURE_SPECS_FOUR,
    MANAGER,
    POSITION_SPECS_REBALANCE,
    STORE_SPECS_FOUR,
    ApiErrorId,
    api_client,
    assert_allocation_line,
    assert_allocation_run,
    assert_assortment_action,
    assert_item,
    assert_program,
    assert_promo_event,
    assert_receipt,
    assert_store,
    assert_store_position,
    assert_transfer_recommendation,
    create_fixture_plan_payload,
    create_item_payload,
    create_program_payload,
    create_promo_event_payload,
    create_receipt,
    create_receipt_payload,
    create_size_profile_payload,
    create_store_payload,
    create_store_position_payload,
    create_transfer_payload,
    current_position_version,
    current_receipt_version,
    line_for_store,
    lines_for_run,
    make_store_operator_headers,
    set_clock,
    setup_network,
    setup_receipt_network,
    units_by_size,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------- #
# Local network descriptions used by the walks below.
# --------------------------------------------------------------------------- #

# One store whose shelf plan gives capacity 24 and a presentation minimum of 8.
SINGLE_STORE_FIXTURE_SPECS = {
    "0101": {
        "fixture_count": 2,
        "facings_per_fixture": 3,
        "units_per_facing": 4,
        "presentation_min_units": 8,
    },
}

# An empty position: all four CORE sizes are missing, so it opens BROKEN.
EMPTY_POSITION_SPECS = {
    "0101": {
        "on_hand_units": 0,
        "size_on_hand": [],
        "min_units": 6,
        "max_units": 20,
        "weekly_forecast_units": 3,
        "trailing_4wk_sales_units": 10,
    },
}

PROMO_EVENT_SEPTEMBER = {
    "event_code": "BTS-A",
    "scope": "PROGRAM",
    "item_class": "APPAREL_TOP",
    "start_date": "2026-09-01T00:00:00Z",
    "end_date": "2026-09-05T00:00:00Z",
    "lift_factor_bp": 11000,
}


def _single_store_network():
    """Program FA26 ACTIVE, store 0101 with capacity 24 / pmin 8, SKU-1001 and an
    empty position that is therefore BROKEN on all four CORE sizes."""
    return setup_network(
        store_specs=STORE_SPECS_FOUR[:1],
        fixture_specs=SINGLE_STORE_FIXTURE_SPECS,
        position_specs=EMPTY_POSITION_SPECS,
    )


def _two_store_network(**program_overrides):
    """Stores 0101 (capacity 48 / pmin 12, 4 units on hand) and 0102 (capacity 24 /
    pmin 8, 30 units on hand) under one ACTIVE program."""
    return setup_network(
        store_specs=STORE_SPECS_FOUR[:2],
        fixture_specs=FIXTURE_SPECS_FOUR,
        position_specs=POSITION_SPECS_REBALANCE,
        program_overrides=program_overrides or None,
    )


def _assert_sizes(size_array, expected):
    """Compare a size/units array against ``{size_code: units}``, treating a size
    code absent from the array as zero units for that size."""
    actual = units_by_size(size_array)
    for code, units in expected.items():
        assert actual.get(code, 0) == units, (
            f"expected {units} units of size {code}, got {actual.get(code, 0)}"
        )
    for code, units in actual.items():
        assert units == expected.get(code, 0), (
            f"unexpected {units} units of size {code}"
        )


def _sole_action(program_id, item_id, store_id):
    """The one assortment action the detection sweep raised for a pair."""
    data, meta = validate_paginated(
        api_client.list_assortment_actions(
            MANAGER, params={"item_id": item_id, "store_id": store_id, "limit": 100}
        )
    )
    assert meta["total_count"] == 1, f"expected one action, got {meta['total_count']}"
    return data[0]


# --------------------------------------------------------------------------- #
# Initial states
# --------------------------------------------------------------------------- #

def test_every_machine_is_born_in_its_declared_initial_state():
    """Each machine is observed on the very response that created it.

    "A new program opens in `PLANNING` with `total_units_received`, `total_units_committed` and `open_reserve_units` all at 0 and with `locked_at` and `lock_reason` both null."
    "A store is created with `status` of `ACTIVE`."
    "A new SKU opens with `lifecycle_state` of `ACTIVE` and with `broken_store_count` and `size_out_store_count` both at 0."
    "A newly booked receipt opens in `STAGED` with `units_committed` at 0 and `units_unallocated` equal to `units_received`"
    "The run opens in `DRAFT`, records the acting `X-User-ID` as `proposed_by_user_id`, and advances the receipt's `version` by one."
    "`units_proposed` is the sum of the lines' proposed units and is 0 while the run is `DRAFT`"
    "Every line opens with `fulfillment_status` of `PENDING`."
    "An event is created in `DRAFT`."
    "A recommendation created this way opens in `PROPOSED` with `source_reason` of `REBALANCE`"
    "Each action opens with `status` of `PENDING`."
    "a brand-new position is created with `broken_size_count`, `stock_status` and `assortment_status` already populated"

    Design: Corner/state_machines/every_machines_initial_state_on_creation
    """
    set_clock(DEFAULT_CLOCK_UTC)

    program = validate_success(
        api_client.create_program(create_program_payload(), ADMIN), 201
    )
    assert_program(program)
    assert program["status"] == "PLANNING"
    assert program["version"] == 1
    assert program["total_units_received"] == 0
    assert program["total_units_committed"] == 0
    assert program["open_reserve_units"] == 0
    assert program["locked_at"] is None
    assert program["lock_reason"] is None

    store_one = validate_success(
        api_client.create_store(
            create_store_payload(program["id"], "0101"), ADMIN
        ),
        201,
    )
    store_two = validate_success(
        api_client.create_store(
            create_store_payload(
                program["id"],
                "0102",
                grade="B",
                grade_index_bp=10000,
                freight_flat_usd=38.00,
                historical_sell_through_bp=5800,
            ),
            ADMIN,
        ),
        201,
    )
    for store in (store_one, store_two):
        assert_store(store)
        assert store["status"] == "ACTIVE"

    validate_success(
        api_client.create_fixture_plan(
            create_fixture_plan_payload(store_one["id"]), ADMIN
        ),
        201,
    )
    validate_success(
        api_client.create_fixture_plan(
            create_fixture_plan_payload(
                store_two["id"], fixture_count=2, presentation_min_units=8
            ),
            ADMIN,
        ),
        201,
    )
    profile = validate_success(
        api_client.create_size_profile(
            create_size_profile_payload(program["id"]), ADMIN
        ),
        201,
    )
    item = validate_success(
        api_client.create_item(
            create_item_payload(program["id"], profile["id"]), ADMIN
        ),
        201,
    )
    assert_item(item)
    assert item["lifecycle_state"] == "ACTIVE"
    assert item["broken_store_count"] == 0
    assert item["size_out_store_count"] == 0

    program = validate_success(api_client.activate_program(program["id"], ADMIN))
    assert program["status"] == "ACTIVE"
    assert program["version"] == 2

    position_one = validate_success(
        api_client.create_store_position(
            create_store_position_payload(store_one["id"], item["id"]), ALLOCATOR
        ),
        201,
    )
    assert_store_position(position_one)
    assert position_one["available_units"] == 4
    assert position_one["stock_status"] == "LOW"
    assert position_one["broken_size_count"] == 2
    assert position_one["assortment_status"] == "BROKEN"
    assert position_one["consolidated_out"] is False

    position_two = validate_success(
        api_client.create_store_position(
            create_store_position_payload(
                store_two["id"],
                item["id"],
                on_hand_units=30,
                size_on_hand=[
                    {"size_code": "S", "units": 8},
                    {"size_code": "M", "units": 10},
                    {"size_code": "L", "units": 8},
                    {"size_code": "XL", "units": 4},
                ],
                min_units=8,
                max_units=24,
                weekly_forecast_units=5,
                trailing_4wk_sales_units=16,
            ),
            ALLOCATOR,
        ),
        201,
    )
    assert position_two["available_units"] == 30
    assert position_two["stock_status"] == "OVERSTOCK"
    assert position_two["broken_size_count"] == 0
    assert position_two["assortment_status"] == "COMPLETE"

    # The broken opening mix at 0101 is what re-derives the SKU, not its creation.
    item = validate_success(api_client.get_item(item["id"], ADMIN))
    assert item["lifecycle_state"] == "BROKEN"
    assert item["broken_store_count"] == 1

    receipt = validate_success(
        api_client.create_receipt(
            create_receipt_payload(
                program["id"],
                item["id"],
                reference="ASN-8001",
                units_received=20,
                size_received=[
                    {"size_code": "S", "units": 4},
                    {"size_code": "M", "units": 7},
                    {"size_code": "L", "units": 6},
                    {"size_code": "XL", "units": 3},
                ],
            ),
            ALLOCATOR,
        ),
        201,
    )
    assert_receipt(receipt)
    assert receipt["status"] == "STAGED"
    assert receipt["units_committed"] == 0
    assert receipt["units_unallocated"] == 20

    run = validate_success(
        api_client.create_allocation_run(
            receipt["id"],
            {
                "method": "DEMAND_DRIVEN",
                "need_basis": "FORWARD_LOOKING",
                "expected_receipt_version": receipt["version"],
            },
            ALLOCATOR,
        ),
        201,
    )
    assert_allocation_run(run)
    assert run["status"] == "DRAFT"
    assert run["units_proposed"] == 0
    assert run["units_committed"] == 0
    assert run["eligible_store_count"] == 0

    run = validate_success(api_client.propose_run(run["id"], ALLOCATOR))
    assert run["status"] == "PROPOSED"
    assert run["units_proposed"] == 20
    assert run["eligible_store_count"] == 1
    assert run["unallocated_remainder_units"] == 0

    lines = lines_for_run(run["id"])
    assert len(lines) == 1, "only 0101 has need above zero, so only 0101 gets a line"
    line = lines[0]
    assert_allocation_line(line)
    assert line["store_id"] == store_one["id"]
    assert line["fulfillment_status"] == "PENDING"
    assert line["need_units"] == 32
    assert line["units_proposed"] == 20
    assert line["units_allocated"] == 0
    assert line["capacity_capped_units"] == 0
    assert line["presentation_gap_units"] == 0
    _assert_sizes(line["size_breakdown"], {"S": 4, "M": 7, "L": 6, "XL": 3})

    event = validate_success(
        api_client.create_promo_event(
            create_promo_event_payload(
                program["id"],
                event_code="BTS-A",
                item_class="APPAREL_TOP",
                start_date="2026-08-05T00:00:00Z",
                end_date="2026-08-10T00:00:00Z",
                lift_factor_bp=11000,
            ),
            ADMIN,
        ),
        201,
    )
    assert_promo_event(event)
    assert event["status"] == "DRAFT"
    assert event["version"] == 1

    transfer = validate_success(
        api_client.create_transfer_recommendation(
            create_transfer_payload(
                program["id"],
                store_two["id"],
                store_one["id"],
                item["id"],
                6,
                current_position_version(position_two["id"]),
            ),
            ALLOCATOR,
        ),
        201,
    )
    assert_transfer_recommendation(transfer)
    assert transfer["status"] == "PROPOSED"
    assert transfer["source_reason"] == "REBALANCE"
    assert transfer["expires_at"].startswith("2026-08-08T00:00:00")
    # S and XL are the CORE sizes the receiver is out of and the donor still holds.
    _assert_sizes(transfer["size_split"], {"S": 4, "XL": 2})

    raised = validate_success(
        api_client.run_assortment_detection({"program_id": program["id"]}, MANAGER)
    )
    assert len(raised) == 1, "only the BROKEN position at 0101 is degraded"
    action = _sole_action(program["id"], item["id"], store_one["id"])
    assert_assortment_action(action)
    assert action["status"] == "PENDING"
    assert action["trigger_reason"] == "BROKEN_ASSORTMENT"
    assert action["action_type"] == "MARKDOWN"
    assert action["markdown_pct_bp"] == 3000
    assert action["broken_size_count"] == 2
    assert action["units_at_detection"] == 4
    assert action["consolidation_target_store_id"] is None
    assert action["detected_at"].startswith("2026-08-01T00:00:00")


# --------------------------------------------------------------------------- #
# The program walk: PLANNING -> ACTIVE -> LOCKED -> ACTIVE -> LOCKED -> CLOSED
# --------------------------------------------------------------------------- #

def test_program_lock_unlock_and_relock_stamp_and_clear_the_lock_fields():
    """
    "An `AllocationManager` may take the program `ACTIVE → LOCKED`, supplying a `reason` that is stored as `lock_reason` while `locked_at` records the current logical clock; the reverse transition `LOCKED → ACTIVE` clears both fields back to null."
    "Locking is not terminal and may be repeated any number of times."
    "`version` is an integer that begins at 1 when the resource is created and increases by exactly 1 on each mutation."
    "the `locked_at` stamp on a program lock are all evaluated and written against this logical clock and nothing else"

    Design: Corner/state_machines/program_lifecycle_walks_every_declared_transition_and_closes_with_a_cascade
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _single_store_network()
    program_id = scenario["program"]["id"]
    assert scenario["program"]["status"] == "ACTIVE"
    assert scenario["program"]["version"] == 2

    locked = validate_success(
        api_client.lock_program(program_id, MANAGER, {"reason": "month-end freeze"})
    )
    assert locked["status"] == "LOCKED"
    assert locked["version"] == 3
    assert locked["lock_reason"] == "month-end freeze"
    assert locked["locked_at"].startswith("2026-08-01T00:00:00")

    unlocked = validate_success(api_client.unlock_program(program_id, MANAGER))
    assert unlocked["status"] == "ACTIVE"
    assert unlocked["version"] == 4
    assert unlocked["locked_at"] is None
    assert unlocked["lock_reason"] is None

    relocked = validate_success(
        api_client.lock_program(program_id, MANAGER, {"reason": "quarter close"})
    )
    assert relocked["status"] == "LOCKED"
    assert relocked["version"] == 5
    assert relocked["lock_reason"] == "quarter close"
    assert relocked["locked_at"].startswith("2026-08-01T00:00:00")


def test_program_close_from_locked_cascades_the_receipt_and_the_pending_action():
    """
    "A `PlanningAdmin` may take a program `ACTIVE → CLOSED` or `LOCKED → CLOSED`"
    "every receipt of the program whose `status` is `STAGED`, `ALLOCATING` or `ALLOCATED` is driven to `CLOSED`, every assortment action whose `status` is `PENDING` and whose SKU belongs to the program is driven to `CANCELLED`, and the program's `version` advances by one"
    "Both closing paths behave identically"
    "`total_units_received` is the sum of `units_received` over the program's receipts whose `status` is `STAGED`, `ALLOCATING`, `ALLOCATED` or `CLOSED`"
    "It snapshots two figures from the position at detection time and then never changes them"

    Design: Corner/state_machines/program_lifecycle_walks_every_declared_transition_and_closes_with_a_cascade
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _single_store_network()
    program_id = scenario["program"]["id"]
    store = scenario["stores"]["0101"]
    item = scenario["item"]
    position = scenario["positions"]["0101"]

    receipt = create_receipt(
        program_id,
        item["id"],
        reference="ASN-8002",
        units_received=10,
        size_received=[
            {"size_code": "S", "units": 2},
            {"size_code": "M", "units": 4},
            {"size_code": "L", "units": 3},
            {"size_code": "XL", "units": 1},
        ],
    )
    assert receipt["status"] == "STAGED"

    validate_success(
        api_client.run_assortment_detection({"program_id": program_id}, MANAGER)
    )
    action = _sole_action(program_id, item["id"], store["id"])
    assert action["status"] == "PENDING"
    assert action["action_type"] == "MARKDOWN"

    validate_success(
        api_client.lock_program(program_id, MANAGER, {"reason": "month-end freeze"})
    )
    validate_success(api_client.unlock_program(program_id, MANAGER))
    validate_success(
        api_client.lock_program(program_id, MANAGER, {"reason": "quarter close"})
    )

    closed = validate_success(api_client.close_program(program_id, ADMIN))
    assert closed["status"] == "CLOSED"
    assert closed["version"] == 6
    assert closed["total_units_received"] == 10

    cascaded_receipt = validate_success(
        api_client.get_receipt(receipt["id"], ALLOCATOR)
    )
    assert cascaded_receipt["status"] == "CLOSED"
    assert cascaded_receipt["units_received"] == 10
    assert cascaded_receipt["units_committed"] == 0
    assert cascaded_receipt["units_unallocated"] == 10

    cascaded_action = validate_success(
        api_client.get_assortment_action(action["id"], MANAGER)
    )
    assert cascaded_action["status"] == "CANCELLED"
    assert cascaded_action["broken_size_count"] == 4
    assert cascaded_action["markdown_pct_bp"] == 4500
    assert cascaded_action["units_at_detection"] == 0

    # The cascade set is closed: it names receipts and pending actions, nothing else.
    assert validate_success(api_client.get_store(store["id"], ADMIN))["status"] == "ACTIVE"
    still_broken = validate_success(
        api_client.get_store_position(position["id"], ALLOCATOR)
    )
    assert still_broken["assortment_status"] == "BROKEN"
    assert still_broken["broken_size_count"] == 4

# --------------------------------------------------------------------------- #
# Refusals: a trigger that is not declared from the current state
# --------------------------------------------------------------------------- #

def _planning_network():
    """Program FA26 still in PLANNING, stores 0101 and 0102 both ACTIVE, a shelf
    plan for 0101 only, the size curve and SKU-1001. No position exists."""
    return setup_network(
        store_specs=STORE_SPECS_FOUR[:2],
        fixture_specs=SINGLE_STORE_FIXTURE_SPECS,
        activate=False,
        create_positions=False,
    )


def test_program_lock_unlock_and_close_are_all_refused_from_planning():
    """
    "The target resource is in a state that permits the requested transition — `ERR_INVALID_STATE_TRANSITION`, 409."
    "An `AllocationManager` may take the program `ACTIVE → LOCKED`, supplying a `reason` that is stored as `lock_reason` while `locked_at` records the current logical clock; the reverse transition `LOCKED → ACTIVE` clears both fields back to null."
    "A `PlanningAdmin` may take a program `ACTIVE → CLOSED` or `LOCKED → CLOSED`"
    "Moving a program from `PLANNING` to `ACTIVE` requires that at least one store belonging to the program exists with `status` of `ACTIVE`, and that at least one SKU belonging to the program exists; the program's `version` advances by one."

    Design: Corner/state_machines/invalid_from_state_triggers_rejected_on_program_store_and_promo
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _planning_network()
    program_id = scenario["program"]["id"]
    assert scenario["program"]["status"] == "PLANNING"

    validate_error(
        api_client.lock_program(program_id, MANAGER, {"reason": "month-end freeze"}),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    still_planning = validate_success(api_client.get_program(program_id, ADMIN))
    assert still_planning["status"] == "PLANNING"
    assert still_planning["version"] == 1
    assert still_planning["locked_at"] is None
    assert still_planning["lock_reason"] is None

    validate_error(
        api_client.unlock_program(program_id, MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    validate_error(
        api_client.close_program(program_id, ADMIN),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    assert validate_success(api_client.get_program(program_id, ADMIN))["version"] == 1

    # The declared move out of PLANNING still works, so the three refusals were
    # about the from-state and not about the endpoints.
    activated = validate_success(api_client.activate_program(program_id, ADMIN))
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == 2


def test_store_lifecycle_refuses_the_moves_it_never_declares():
    """
    "The store lifecycle is driven by a `PlanningAdmin` supplying a `target_status`, and only four moves are declared."
    "Any `target_status` that is not the destination of one of these four declared moves — an attempt to jump from `ACTIVE` straight to `CLOSED`, for instance, or any move out of `CLOSED` — is refused with `ERR_INVALID_STATE_TRANSITION`."
    "`REMODEL → ACTIVE` returns the store to eligibility and advances `version` by one"

    Design: Corner/state_machines/invalid_from_state_triggers_rejected_on_program_store_and_promo
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _planning_network()
    validate_success(api_client.activate_program(scenario["program"]["id"], ADMIN))
    store_one = scenario["stores"]["0101"]
    store_two = scenario["stores"]["0102"]

    # CLOSED is the destination of CLOSING -> CLOSED only; the step may not be skipped.
    validate_error(
        api_client.set_store_status(store_one["id"], {"target_status": "CLOSED"}, ADMIN),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    unchanged = validate_success(api_client.get_store(store_one["id"], ADMIN))
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["version"] == 1

    remodelling = validate_success(
        api_client.set_store_status(store_two["id"], {"target_status": "REMODEL"}, ADMIN)
    )
    assert remodelling["status"] == "REMODEL"
    assert remodelling["version"] == 2
    # A remodelling store must come back to ACTIVE before it can start closing.
    validate_error(
        api_client.set_store_status(store_two["id"], {"target_status": "CLOSING"}, ADMIN),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    held = validate_success(api_client.get_store(store_two["id"], ADMIN))
    assert held["status"] == "REMODEL"
    assert held["version"] == 2

    closing = validate_success(
        api_client.set_store_status(store_one["id"], {"target_status": "CLOSING"}, ADMIN)
    )
    assert closing["status"] == "CLOSING"
    assert closing["version"] == 2
    # CLOSING is one-way: there is no CLOSING -> REMODEL move.
    validate_error(
        api_client.set_store_status(store_one["id"], {"target_status": "REMODEL"}, ADMIN),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    still_closing = validate_success(api_client.get_store(store_one["id"], ADMIN))
    assert still_closing["status"] == "CLOSING"
    assert still_closing["version"] == 2


def test_promo_event_refuses_activate_and_end_before_it_has_been_scheduled():
    """
    "An event is created in `DRAFT`."
    "The event lifecycle is `PlanningAdmin`-driven throughout, and each transition advances the event's `version` by one. `DRAFT → SCHEDULED` re-runs the buffered conflict test against every `SCHEDULED` or `ACTIVE` peer. `SCHEDULED → ACTIVE` is the moment the lift becomes real"
    "`ACTIVE → ENDED` is terminal and stops the event contributing lift to any subsequent calculation."

    Design: Corner/state_machines/invalid_from_state_triggers_rejected_on_program_store_and_promo
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _planning_network()
    validate_success(api_client.activate_program(scenario["program"]["id"], ADMIN))

    event = validate_success(
        api_client.create_promo_event(
            create_promo_event_payload(
                scenario["program"]["id"], **PROMO_EVENT_SEPTEMBER
            ),
            ADMIN,
        ),
        201,
    )
    assert event["status"] == "DRAFT"

    validate_error(
        api_client.activate_promo_event(event["id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    validate_error(
        api_client.end_promo_event(event["id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    still_draft = validate_success(api_client.get_promo_event(event["id"], ADMIN))
    assert still_draft["status"] == "DRAFT"
    assert still_draft["version"] == 1

    scheduled = validate_success(api_client.schedule_promo_event(event["id"], ADMIN))
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["version"] == 2
    # ENDED is reachable only from ACTIVE.
    validate_error(
        api_client.end_promo_event(event["id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    held = validate_success(api_client.get_promo_event(event["id"], ADMIN))
    assert held["status"] == "SCHEDULED"
    assert held["version"] == 2


def _walk_network():
    """The two-store network with the freight-worthiness gate wide open, so a
    transfer's from-state is the only thing a probe can trip over."""
    return _two_store_network(transfer_min_ratio_bp=0)


def _staged_receipt(program_id, item_id):
    return create_receipt(
        program_id,
        item_id,
        reference="ASN-8003",
        units_received=20,
        size_received=[
            {"size_code": "S", "units": 4},
            {"size_code": "M", "units": 7},
            {"size_code": "L", "units": 6},
            {"size_code": "XL", "units": 3},
        ],
    )


def test_receipt_close_and_run_commit_or_recall_are_refused_from_the_wrong_state():
    """
    "A commit requires a `PROPOSED` run; a recall requires a `COMMITTED` run"
    "An `AllocationManager` may close a receipt from either `ALLOCATING` or `ALLOCATED`, which abandons any open spread"
    "Opening the first allocation run against a `STAGED` receipt drives it `STAGED → ALLOCATING` and advances its `version` by one"
    "`units_proposed` is the sum of the lines' proposed units and is 0 while the run is `DRAFT`"

    Design: Corner/state_machines/invalid_from_state_triggers_rejected_on_receipt_run_line_and_transfer
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _walk_network()
    receipt = _staged_receipt(scenario["program"]["id"], scenario["item"]["id"])
    assert receipt["status"] == "STAGED"

    # CLOSED is reachable only from ALLOCATING or ALLOCATED.
    validate_error(
        api_client.close_receipt(receipt["id"], MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    held = validate_success(api_client.get_receipt(receipt["id"], ALLOCATOR))
    assert held["status"] == "STAGED"
    assert held["version"] == receipt["version"]

    run = validate_success(
        api_client.create_allocation_run(
            receipt["id"],
            {
                "method": "DEMAND_DRIVEN",
                "need_basis": "FORWARD_LOOKING",
                "expected_receipt_version": held["version"],
            },
            ALLOCATOR,
        ),
        201,
    )
    assert run["status"] == "DRAFT"
    assert validate_success(
        api_client.get_receipt(receipt["id"], ALLOCATOR)
    )["status"] == "ALLOCATING"

    validate_error(
        api_client.commit_run(run["id"], MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    validate_error(
        api_client.recall_run(run["id"], MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    still_draft = validate_success(api_client.get_allocation_run(run["id"], ALLOCATOR))
    assert still_draft["status"] == "DRAFT"
    assert still_draft["units_proposed"] == 0
    assert still_draft["version"] == run["version"]

    proposed = validate_success(api_client.propose_run(run["id"], ALLOCATOR))
    assert proposed["status"] == "PROPOSED"
    assert proposed["version"] == run["version"] + 1

    # Recall exists only from COMMITTED, never from PROPOSED.
    validate_error(
        api_client.recall_run(run["id"], MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    after = validate_success(api_client.get_allocation_run(run["id"], ALLOCATOR))
    assert after["status"] == "PROPOSED"
    assert after["version"] == run["version"] + 1


def test_confirm_receipt_is_refused_on_a_line_that_has_not_shipped():
    """
    "a line receipt confirmation requires a `SHIPPED` line"
    "Every line opens with `fulfillment_status` of `PENDING`."
    "the line's `units_allocated` are added to the position's `on_hand_units`"

    Design: Corner/state_machines/invalid_from_state_triggers_rejected_on_receipt_run_line_and_transfer
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _walk_network()
    store_one = scenario["stores"]["0101"]
    position_one = scenario["positions"]["0101"]
    receipt = _staged_receipt(scenario["program"]["id"], scenario["item"]["id"])

    run = validate_success(
        api_client.create_allocation_run(
            receipt["id"],
            {
                "method": "DEMAND_DRIVEN",
                "need_basis": "FORWARD_LOOKING",
                "expected_receipt_version": receipt["version"],
            },
            ALLOCATOR,
        ),
        201,
    )
    validate_success(api_client.propose_run(run["id"], ALLOCATOR))
    line = line_for_store(run["id"], store_one["id"])
    assert line["fulfillment_status"] == "PENDING"

    validate_error(
        api_client.confirm_line_receipt(
            line["id"], make_store_operator_headers(store_one["id"])
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )

    unchanged_line = validate_success(
        api_client.get_allocation_line(line["id"], ALLOCATOR)
    )
    assert unchanged_line["fulfillment_status"] == "PENDING"
    assert unchanged_line["version"] == line["version"]
    unchanged_position = validate_success(
        api_client.get_store_position(position_one["id"], ALLOCATOR)
    )
    assert unchanged_position["on_hand_units"] == 4
    assert unchanged_position["in_transit_units"] == 0


def test_transfer_dispatch_and_receive_are_refused_while_it_is_only_proposed():
    """
    "a dispatch requires an `APPROVED` recommendation; a transfer receive requires a `DISPATCHED` recommendation"
    "**Dispatch** takes the recommendation `APPROVED → DISPATCHED`"
    "the transfer's `units` are added to the donor position's `reserved_out_units`"
    "it adds the `units` to the receiving position's `in_transit_units`"

    Design: Corner/state_machines/invalid_from_state_triggers_rejected_on_receipt_run_line_and_transfer
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _walk_network()
    store_one = scenario["stores"]["0101"]
    store_two = scenario["stores"]["0102"]
    position_one = scenario["positions"]["0101"]
    position_two = scenario["positions"]["0102"]

    transfer = validate_success(
        api_client.create_transfer_recommendation(
            create_transfer_payload(
                scenario["program"]["id"],
                store_two["id"],
                store_one["id"],
                scenario["item"]["id"],
                6,
                current_position_version(position_two["id"]),
            ),
            ALLOCATOR,
        ),
        201,
    )
    assert transfer["status"] == "PROPOSED"

    validate_error(
        api_client.dispatch_transfer(transfer["id"], MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    held = validate_success(
        api_client.get_transfer_recommendation(transfer["id"], MANAGER)
    )
    assert held["status"] == "PROPOSED"
    assert held["version"] == transfer["version"]

    validate_error(
        api_client.receive_transfer(
            transfer["id"], make_store_operator_headers(store_one["id"])
        ),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    after = validate_success(
        api_client.get_transfer_recommendation(transfer["id"], MANAGER)
    )
    assert after["status"] == "PROPOSED"
    assert after["version"] == transfer["version"]

    # Neither reservation nor departure happened: those belong to approve and dispatch.
    donor = validate_success(
        api_client.get_store_position(position_two["id"], ALLOCATOR)
    )
    assert donor["reserved_out_units"] == 0
    assert donor["available_units"] == 30
    receiver = validate_success(
        api_client.get_store_position(position_one["id"], ALLOCATOR)
    )
    assert receiver["in_transit_units"] == 0


# --------------------------------------------------------------------------- #
# Terminal states
# --------------------------------------------------------------------------- #

def test_a_cancelled_promo_event_accepts_nothing_at_all():
    """
    "Cancellation is reachable from `DRAFT`, from `SCHEDULED` and from `ACTIVE`, is terminal, and likewise removes the event from any future lift calculation."
    "and a resource in a terminal state accepts nothing at all."

    Design: Corner/state_machines/terminal_states_freeze_promo_action_item_and_program
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _single_store_network()

    event = validate_success(
        api_client.create_promo_event(
            create_promo_event_payload(
                scenario["program"]["id"], **PROMO_EVENT_SEPTEMBER
            ),
            ADMIN,
        ),
        201,
    )
    cancelled = validate_success(api_client.cancel_promo_event(event["id"], ADMIN))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["version"] == 2

    validate_error(
        api_client.schedule_promo_event(event["id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    validate_error(
        api_client.cancel_promo_event(event["id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    frozen = validate_success(api_client.get_promo_event(event["id"], ADMIN))
    assert frozen["status"] == "CANCELLED"
    assert frozen["version"] == 2


def test_executing_a_markdown_remedy_freezes_both_the_action_and_the_sku():
    """
    "Executing an action belongs to an `AllocationManager` and takes it `PENDING → EXECUTED`."
    "A `MARKDOWN` action instead drives the SKU straight to `MARKDOWN`, which is terminal — reachable from `BROKEN` and equally from `SIZE_OUT_WATCH` — leaves `consolidation_target_store_id` null, advances the SKU's `version` by one"
    "an assortment remedy execution requires a `PENDING` action"
    "An `AllocationManager` may instead waive the remedy, taking the action `PENDING → CANCELLED`, which is terminal and advances `version` by one."
    "And positions of SKUs whose `lifecycle_state` is `MARKDOWN` are skipped, since a marked-down SKU is beyond remedy."

    Design: Corner/state_machines/terminal_states_freeze_promo_action_item_and_program
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _single_store_network()
    program_id = scenario["program"]["id"]
    item_id = scenario["item"]["id"]
    store_id = scenario["stores"]["0101"]["id"]

    validate_success(
        api_client.run_assortment_detection({"program_id": program_id}, MANAGER)
    )
    action = _sole_action(program_id, item_id, store_id)
    assert action["status"] == "PENDING"
    assert action["action_type"] == "MARKDOWN"

    before_item = validate_success(api_client.get_item(item_id, ADMIN))
    assert before_item["lifecycle_state"] == "BROKEN"

    executed = validate_success(
        api_client.execute_assortment_action(action["id"], MANAGER)
    )
    assert executed["status"] == "EXECUTED"
    assert executed["consolidation_target_store_id"] is None
    assert executed["version"] == action["version"] + 1

    marked_down = validate_success(api_client.get_item(item_id, ADMIN))
    assert marked_down["lifecycle_state"] == "MARKDOWN"
    assert marked_down["version"] == before_item["version"] + 1

    validate_error(
        api_client.execute_assortment_action(action["id"], MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    validate_error(
        api_client.cancel_assortment_action(action["id"], MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    frozen = validate_success(api_client.get_assortment_action(action["id"], MANAGER))
    assert frozen["status"] == "EXECUTED"
    assert frozen["version"] == action["version"] + 1

    # The SKU's terminal state is honoured by the sweep itself, not only by the endpoint.
    again = validate_success(
        api_client.run_assortment_detection({"program_id": program_id}, MANAGER)
    )
    assert len(again) == 0
    _, meta = validate_paginated(
        api_client.list_assortment_actions(
            MANAGER, params={"item_id": item_id, "limit": 100}
        )
    )
    assert meta["total_count"] == 1


def test_a_closed_program_separates_its_own_transitions_from_child_decisions():
    """
    "A `PlanningAdmin` may take a program `ACTIVE → CLOSED` or `LOCKED → CLOSED`"
    "and a resource in a terminal state accepts nothing at all."
    "Only an `ACTIVE` program admits **decisions**: booking a receipt, correcting a receipt count, opening an allocation run, proposing, revising or committing a spread, creating, approving or dispatching a transfer, running the assortment detection sweep, executing an assortment remedy, and creating a cluster snapshot. Attempting any of those while the program is `PLANNING`, `LOCKED` or `CLOSED` is rejected with `ERR_PROGRAM_LOCKED` and HTTP 409."

    Design: Corner/state_machines/terminal_states_freeze_promo_action_item_and_program
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _single_store_network()
    program_id = scenario["program"]["id"]
    item_id = scenario["item"]["id"]
    store_id = scenario["stores"]["0101"]["id"]

    validate_success(
        api_client.run_assortment_detection({"program_id": program_id}, MANAGER)
    )
    action = _sole_action(program_id, item_id, store_id)
    validate_success(api_client.execute_assortment_action(action["id"], MANAGER))

    event = validate_success(
        api_client.create_promo_event(
            create_promo_event_payload(program_id, **PROMO_EVENT_SEPTEMBER), ADMIN
        ),
        201,
    )
    validate_success(api_client.cancel_promo_event(event["id"], ADMIN))

    # Terminal children are not preconditions on the close.
    closed = validate_success(api_client.close_program(program_id, ADMIN))
    assert closed["status"] == "CLOSED"
    closed_version = closed["version"]

    for refused in (
        api_client.activate_program(program_id, ADMIN),
        api_client.lock_program(program_id, MANAGER, {"reason": "month-end freeze"}),
        api_client.close_program(program_id, ADMIN),
    ):
        validate_error(refused, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert validate_success(api_client.get_program(program_id, ADMIN))["version"] == (
        closed_version
    )

    # A child decision is stopped one rung later, by the program-status rule.
    validate_error(
        api_client.create_receipt(
            create_receipt_payload(
                program_id,
                item_id,
                reference="ASN-DEAD",
                units_received=4,
                size_received=[{"size_code": "M", "units": 4}],
            ),
            ALLOCATOR,
        ),
        ApiErrorId.ERR_PROGRAM_LOCKED,
    )
    validate_error(
        api_client.create_performance_snapshot(
            {"program_id": program_id, "cluster_code": "URBAN"}, ALLOCATOR
        ),
        ApiErrorId.ERR_PROGRAM_LOCKED,
    )

    _, receipts_meta = validate_paginated(
        api_client.list_receipts(ALLOCATOR, params={"program_id": program_id})
    )
    assert receipts_meta["total_count"] == 0
    _, snapshots_meta = validate_paginated(
        api_client.list_performance_snapshots(
            ALLOCATOR, params={"program_id": program_id}
        )
    )
    assert snapshots_meta["total_count"] == 0


# --------------------------------------------------------------------------- #
# Replays of settled actions
# --------------------------------------------------------------------------- #

RECEIPT_44_SIZES = [
    {"size_code": "S", "units": 8},
    {"size_code": "M", "units": 16},
    {"size_code": "L", "units": 14},
    {"size_code": "XL", "units": 6},
]


def _committed_spread():
    """The four-store receipt network with a 44-unit receipt spread and committed,
    which puts 26 / 10 / 8 units on stores 0101 / 0103 / 0104."""
    scenario = setup_receipt_network(
        program_overrides={"transfer_min_ratio_bp": 0}
    )
    scenario["receipt"] = create_receipt(
        scenario["program"]["id"],
        scenario["item"]["id"],
        reference="ASN-8005",
        units_received=44,
        size_received=RECEIPT_44_SIZES,
    )
    run = validate_success(
        api_client.create_allocation_run(
            scenario["receipt"]["id"],
            {
                "method": "DEMAND_DRIVEN",
                "need_basis": "FORWARD_LOOKING",
                "expected_receipt_version": scenario["receipt"]["version"],
            },
            ALLOCATOR,
        ),
        201,
    )
    validate_success(api_client.propose_run(run["id"], ALLOCATOR))
    scenario["run"] = validate_success(api_client.commit_run(run["id"], MANAGER))
    assert scenario["run"]["status"] == "COMMITTED"
    return scenario


def test_a_second_commit_and_a_second_activate_are_conflicts_not_no_ops():
    """
    "A commit requires a `PROPOSED` run"
    "For any receipt, `units_committed` is the sum of `units_allocated` over every allocation line whose owning run has reached `COMMITTED` and whose own `fulfillment_status` is `PENDING`, `SHIPPED` or `RECEIVED`; `units_unallocated` is `units_received` minus that committed total."
    "The receipt's `units_committed` and `units_unallocated` are recomputed, and if `units_unallocated` reaches 0 the receipt is driven `ALLOCATING → ALLOCATED`."
    "Moving a program from `PLANNING` to `ACTIVE` requires that at least one store belonging to the program exists with `status` of `ACTIVE`, and that at least one SKU belonging to the program exists; the program's `version` advances by one."

    Design: Corner/state_machines/a_repeated_settled_action_is_a_conflict_not_a_no_op
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _committed_spread()
    program_id = scenario["program"]["id"]
    receipt_id = scenario["receipt"]["id"]
    run = scenario["run"]

    settled = validate_success(api_client.get_receipt(receipt_id, ALLOCATOR))
    assert settled["status"] == "ALLOCATED"
    assert settled["units_committed"] == 44
    assert settled["units_unallocated"] == 0

    validate_error(
        api_client.commit_run(run["id"], MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    unmoved = validate_success(api_client.get_receipt(receipt_id, ALLOCATOR))
    assert unmoved["units_committed"] == 44
    assert unmoved["units_unallocated"] == 0
    assert unmoved["version"] == settled["version"]

    before = validate_success(api_client.get_program(program_id, ADMIN))
    assert before["status"] == "ACTIVE"
    validate_error(
        api_client.activate_program(program_id, ADMIN),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    after = validate_success(api_client.get_program(program_id, ADMIN))
    assert after["status"] == "ACTIVE"
    assert after["version"] == before["version"]
    assert after["total_units_committed"] == 44
    assert after["total_units_received"] == 44
    assert after["open_reserve_units"] == 0


def test_replaying_ship_and_confirm_receipt_never_doubles_the_position_ledger():
    """
    "The release adds the line's `units_allocated` to the destination position's `in_transit_units` and re-derives that position's `stock_status`; the line's `version` advances by one."
    "the line's `units_allocated` are added to the position's `on_hand_units`"
    "a line receipt confirmation requires a `SHIPPED` line"
    "The target resource is in a state that permits the requested transition — `ERR_INVALID_STATE_TRANSITION`, 409."

    Design: Corner/state_machines/a_repeated_settled_action_is_a_conflict_not_a_no_op
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _committed_spread()
    store_one = scenario["stores"]["0101"]
    position_one = scenario["positions"]["0101"]
    line = line_for_store(scenario["run"]["id"], store_one["id"])
    assert line["units_allocated"] == 26
    assert line["fulfillment_status"] == "PENDING"

    shipped = validate_success(api_client.ship_line(line["id"], MANAGER))
    assert shipped["fulfillment_status"] == "SHIPPED"
    in_transit = validate_success(
        api_client.get_store_position(position_one["id"], ALLOCATOR)
    )
    assert in_transit["in_transit_units"] == 26
    assert in_transit["on_hand_units"] == 6

    validate_error(
        api_client.ship_line(line["id"], MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    still_in_transit = validate_success(
        api_client.get_store_position(position_one["id"], ALLOCATOR)
    )
    assert still_in_transit["in_transit_units"] == 26
    assert still_in_transit["version"] == in_transit["version"]

    operator = make_store_operator_headers(store_one["id"])
    received = validate_success(api_client.confirm_line_receipt(line["id"], operator))
    assert received["fulfillment_status"] == "RECEIVED"
    landed = validate_success(
        api_client.get_store_position(position_one["id"], ALLOCATOR)
    )
    assert landed["on_hand_units"] == 32
    assert landed["in_transit_units"] == 0

    validate_error(
        api_client.confirm_line_receipt(line["id"], operator),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    final = validate_success(
        api_client.get_store_position(position_one["id"], ALLOCATOR)
    )
    assert final["on_hand_units"] == 32
    assert final["in_transit_units"] == 0
    assert final["version"] == landed["version"]
    assert validate_success(
        api_client.get_allocation_line(line["id"], ALLOCATOR)
    )["fulfillment_status"] == "RECEIVED"


def test_replaying_a_transfer_approval_never_doubles_the_donor_reservation():
    """
    "On success the recommendation moves `PROPOSED → APPROVED`, `approved_by_user_id` is set to the acting `X-User-ID`, the transfer's `units` are added to the donor position's `reserved_out_units` — which lowers that position's `available_units` and re-derives its `stock_status` — and the recommendation's `version` advances by one."
    "`available_units` is `on_hand_units` minus `reserved_out_units`"
    "The target resource is in a state that permits the requested transition — `ERR_INVALID_STATE_TRANSITION`, 409."
    "`total_units_committed` is the sum of `units_allocated` over lines of `COMMITTED` runs whose `fulfillment_status` is `PENDING`, `SHIPPED` or `RECEIVED`"

    Design: Corner/state_machines/a_repeated_settled_action_is_a_conflict_not_a_no_op
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _committed_spread()
    donor_position = scenario["positions"]["0102"]

    transfer = validate_success(
        api_client.create_transfer_recommendation(
            create_transfer_payload(
                scenario["program"]["id"],
                scenario["stores"]["0102"]["id"],
                scenario["stores"]["0104"]["id"],
                scenario["item"]["id"],
                6,
                current_position_version(donor_position["id"]),
            ),
            ALLOCATOR,
        ),
        201,
    )
    assert transfer["status"] == "PROPOSED"

    approved = validate_success(api_client.approve_transfer(transfer["id"], MANAGER))
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] is not None
    reserved = validate_success(
        api_client.get_store_position(donor_position["id"], ALLOCATOR)
    )
    assert reserved["reserved_out_units"] == 6
    assert reserved["available_units"] == 14

    validate_error(
        api_client.approve_transfer(transfer["id"], MANAGER),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION,
    )
    unchanged = validate_success(
        api_client.get_store_position(donor_position["id"], ALLOCATOR)
    )
    assert unchanged["reserved_out_units"] == 6
    assert unchanged["available_units"] == 14
    assert unchanged["version"] == reserved["version"]
    settled = validate_success(
        api_client.get_transfer_recommendation(transfer["id"], MANAGER)
    )
    assert settled["status"] == "APPROVED"
    assert settled["version"] == approved["version"]
    assert settled["approved_by_user_id"] == approved["approved_by_user_id"]

    # None of the replays moved the program ledger.
    program = validate_success(
        api_client.get_program(scenario["program"]["id"], ADMIN)
    )
    assert program["total_units_committed"] == 44


# --------------------------------------------------------------------------- #
# The PROPOSED -> DRAFT -> PROPOSED cycle
# --------------------------------------------------------------------------- #

def _proposed_44_spread():
    """The four-store receipt network with a 44-unit receipt spread once, whose
    needs of 26 / 0 / 10 / 8 exactly consume the pool."""
    scenario = setup_receipt_network()
    scenario["receipt"] = create_receipt(
        scenario["program"]["id"],
        scenario["item"]["id"],
        reference="ASN-8006",
        units_received=44,
        size_received=RECEIPT_44_SIZES,
    )
    run = validate_success(
        api_client.create_allocation_run(
            scenario["receipt"]["id"],
            {
                "method": "DEMAND_DRIVEN",
                "need_basis": "FORWARD_LOOKING",
                "expected_receipt_version": scenario["receipt"]["version"],
            },
            ALLOCATOR,
        ),
        201,
    )
    scenario["run"] = validate_success(api_client.propose_run(run["id"], ALLOCATOR))
    return scenario


def test_revise_demolishes_the_spread_and_leaves_the_receipt_ledger_alone():
    """
    "An `Allocator` may take a `PROPOSED` run back to `DRAFT` to change its inputs and try again"
    "Revising **deletes every allocation line of the run** and resets `units_proposed`, `unallocated_remainder_units` and `eligible_store_count` to 0, then advances the run's `version` by one."
    "The propose-and-revise cycle may loop any number of times while the receipt remains in `ALLOCATING`."
    "`units_unallocated` is `units_received` minus that committed total"

    Design: Corner/state_machines/revise_cycles_proposed_back_to_draft_and_reproposes_a_different_spread
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _proposed_44_spread()
    run = scenario["run"]
    assert run["status"] == "PROPOSED"
    assert run["version"] == 2
    assert run["units_proposed"] == 44
    assert run["eligible_store_count"] == 3
    assert run["unallocated_remainder_units"] == 0
    assert len(lines_for_run(run["id"])) == 3

    revised = validate_success(api_client.revise_run(run["id"], ALLOCATOR))
    assert revised["status"] == "DRAFT"
    assert revised["version"] == 3
    assert revised["units_proposed"] == 0
    assert revised["unallocated_remainder_units"] == 0
    assert revised["eligible_store_count"] == 0

    # The lines are deleted, not left behind as zeroed rows.
    _, meta = validate_paginated(
        api_client.list_allocation_lines(
            ALLOCATOR, params={"run_id": run["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0

    ledger = validate_success(
        api_client.get_receipt(scenario["receipt"]["id"], ALLOCATOR)
    )
    assert ledger["status"] == "ALLOCATING"
    assert ledger["units_received"] == 44
    assert ledger["units_committed"] == 0
    assert ledger["units_unallocated"] == 44


def test_the_second_propose_recomputes_need_and_prorates_the_short_pool():
    """
    "The pipeline under this basis is the position's `available_units` plus its `in_transit_units` plus its `on_order_units`"
    "such a patch re-derives the position's stock dimension, leaves its assortment dimension entirely alone because the two are independent, and advances `version` by one"
    "Revising **deletes every allocation line of the run** and resets `units_proposed`, `unallocated_remainder_units` and `eligible_store_count` to 0, then advances the run's `version` by one."
    "a store allocated zero units gets no line at all"

    Design: Corner/state_machines/revise_cycles_proposed_back_to_draft_and_reproposes_a_different_spread
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = _proposed_44_spread()
    run = scenario["run"]
    first_pass_ids = {line["id"] for line in lines_for_run(run["id"])}
    assert len(first_pass_ids) == 3

    validate_success(api_client.revise_run(run["id"], ALLOCATOR))
    patched = validate_success(
        api_client.patch_store_position(
            scenario["positions"]["0101"]["id"],
            {"weekly_forecast_units": 12},
            ALLOCATOR,
        )
    )
    assert patched["weekly_forecast_units"] == 12

    reproposed = validate_success(api_client.propose_run(run["id"], ALLOCATOR))
    assert reproposed["status"] == "PROPOSED"
    assert reproposed["version"] == 4
    assert reproposed["eligible_store_count"] == 3
    assert reproposed["units_proposed"] == 44
    assert reproposed["unallocated_remainder_units"] == 0

    line_one = line_for_store(run["id"], scenario["stores"]["0101"]["id"])
    line_three = line_for_store(run["id"], scenario["stores"]["0103"]["id"])
    line_four = line_for_store(run["id"], scenario["stores"]["0104"]["id"])

    # Need is now 38 / 10 / 8 = 56 against a pool of 44, so the pool is prorated.
    assert line_one["need_units"] == 38
    assert line_three["need_units"] == 10
    assert line_four["need_units"] == 8
    assert line_one["units_proposed"] == 31
    assert line_three["units_proposed"] == 7
    assert line_four["units_proposed"] == 6

    _assert_sizes(line_one["size_breakdown"], {"S": 6, "M": 11, "L": 10, "XL": 4})
    _assert_sizes(line_three["size_breakdown"], {"S": 1, "M": 3, "L": 2, "XL": 1})
    _assert_sizes(line_four["size_breakdown"], {"S": 1, "M": 3, "L": 2})

    second_pass_ids = {line["id"] for line in lines_for_run(run["id"])}
    assert len(second_pass_ids) == 3
    assert second_pass_ids.isdisjoint(first_pass_ids)

    # Store 0102 has need 0 and never earns a line in either pass.
    _, meta = validate_paginated(
        api_client.list_allocation_lines(
            ALLOCATOR,
            params={
                "run_id": run["id"],
                "store_id": scenario["stores"]["0102"]["id"],
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------- #
# The receipt close cascade
# --------------------------------------------------------------------------- #

def test_receipt_close_cancels_the_open_run_and_spares_the_committed_one():
    """
    "An `AllocationManager` may close a receipt from either `ALLOCATING` or `ALLOCATED`, which abandons any open spread: every allocation run of the receipt whose `status` is `DRAFT` or `PROPOSED` is driven to `CANCELLED`, every allocation line of those runs is driven to `RECALLED`, and the receipt's `version` advances by one."
    "Every line's `units_allocated` is set equal to its `units_proposed` and its `fulfillment_status` is set to `PENDING`."
    "`total_units_received` is the sum of `units_received` over the program's receipts whose `status` is `STAGED`, `ALLOCATING`, `ALLOCATED` or `CLOSED`"
    "`open_reserve_units` is `total_units_received` minus `total_units_committed`, representing the DC-side units not yet committed to any store"

    Design: Corner/state_machines/receipt_close_cascades_open_runs_and_spares_the_committed_one
    """
    set_clock(DEFAULT_CLOCK_UTC)
    scenario = setup_receipt_network()
    program_id = scenario["program"]["id"]
    receipt = create_receipt(
        program_id,
        scenario["item"]["id"],
        reference="ASN-8007",
        units_received=60,
        size_received=[
            {"size_code": "S", "units": 12},
            {"size_code": "M", "units": 21},
            {"size_code": "L", "units": 18},
            {"size_code": "XL", "units": 9},
        ],
    )

    run_one = validate_success(
        api_client.create_allocation_run(
            receipt["id"],
            {
                "method": "DEMAND_DRIVEN",
                "need_basis": "FORWARD_LOOKING",
                "expected_receipt_version": receipt["version"],
            },
            ALLOCATOR,
        ),
        201,
    )
    validate_success(api_client.propose_run(run_one["id"], ALLOCATOR))
    validate_success(api_client.commit_run(run_one["id"], MANAGER))
    committed_lines = lines_for_run(run_one["id"])
    assert sorted(line["units_allocated"] for line in committed_lines) == [8, 10, 26]
    line_one = line_for_store(run_one["id"], scenario["stores"]["0101"]["id"])
    assert line_one["units_allocated"] == 26

    run_two = validate_success(
        api_client.create_allocation_run(
            receipt["id"],
            {
                "method": "DEMAND_DRIVEN",
                "need_basis": "FORWARD_LOOKING",
                "expected_receipt_version": current_receipt_version(receipt["id"]),
            },
            ALLOCATOR,
        ),
        201,
    )
    validate_success(api_client.propose_run(run_two["id"], ALLOCATOR))
    open_lines = lines_for_run(run_two["id"])
    assert sorted(line["units_proposed"] for line in open_lines) == [2, 3, 11]

    closed = validate_success(api_client.close_receipt(receipt["id"], MANAGER))
    assert closed["status"] == "CLOSED"
    assert closed["units_received"] == 60
    assert closed["units_committed"] == 44
    assert closed["units_unallocated"] == 16

    cancelled_run = validate_success(
        api_client.get_allocation_run(run_two["id"], ALLOCATOR)
    )
    assert cancelled_run["status"] == "CANCELLED"
    for line in lines_for_run(run_two["id"]):
        fresh = validate_success(api_client.get_allocation_line(line["id"], ALLOCATOR))
        assert fresh["fulfillment_status"] == "RECALLED"
        assert fresh["units_allocated"] == 0

    spared_run = validate_success(
        api_client.get_allocation_run(run_one["id"], ALLOCATOR)
    )
    assert spared_run["status"] == "COMMITTED"
    for line in lines_for_run(run_one["id"]):
        fresh = validate_success(api_client.get_allocation_line(line["id"], ALLOCATOR))
        assert fresh["fulfillment_status"] == "PENDING"
        assert fresh["units_allocated"] > 0
    assert validate_success(
        api_client.get_allocation_line(line_one["id"], ALLOCATOR)
    )["units_allocated"] == 26

    program = validate_success(api_client.get_program(program_id, ADMIN))
    assert program["total_units_received"] == 60
    assert program["total_units_committed"] == 44
    assert program["open_reserve_units"] == 16

    # Closing forfeits the 16 units without moving any stock.
    position_one = validate_success(
        api_client.get_store_position(scenario["positions"]["0101"]["id"], ALLOCATOR)
    )
    assert position_one["on_hand_units"] == 6
    assert position_one["in_transit_units"] == 0
