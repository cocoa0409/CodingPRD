"""Inventory programs: reorder-threshold cycle, ship cascade with
replenishment auto-creation, release gating, and stock conservation."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_inventory_program,
    assert_msf,
    assert_program_stock_invariant,
    assert_release_order,
    create_approved_release,
    create_customer,
    create_grade,
    create_inventory_program,
    create_release,
    create_stocked_program,
    get_program,
    make_customer_headers,
    post_receipt,
    setup_customer_and_grade,
    setup_program_with_shipped_release,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

SALES = TEST_USERS["sales_rep_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


def test_ship_crossing_reorder_point_flips_program_to_replenishment_needed(
    api, production_planner_headers
):
    """PRD 3.7: "The ship decrements both `on_hand_qty` and `committed_qty` by
    the release's `qty`, flips the release to `SHIPPED`, and then runs the
    reorder threshold check on the program. That check is boundary-sensitive:
    if the program is `ACTIVE` and the post-decrement `on_hand_qty` is at or
    below `reorder_point`, the program flips to `REPLENISHMENT_NEEDED`".

    Design: Difficulty/non_linear_state_machine/inventory_program_replenishment_cycle_active_need_active
    """
    customer, grade = setup_customer_and_grade()
    program, release = setup_program_with_shipped_release(
        customer["id"], grade["id"], stock_qty=400, release_qty=350,
        reorder_point=100, replenishment_qty=500,
    )
    assert release["status"] == "SHIPPED"
    assert program["status"] == "REPLENISHMENT_NEEDED"  # 50 <= 100
    assert program["on_hand_qty"] == 50
    assert_inventory_program(program)


def test_receipt_above_reorder_point_flips_program_back_to_active(
    api, production_planner_headers
):
    """PRD 3.7: "Conversely, after a receipt, if the program is
    `REPLENISHMENT_NEEDED` and the post-increment `on_hand_qty` is strictly
    greater than `reorder_point`, it flips back to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/inventory_program_replenishment_cycle_active_need_active
    """
    customer, grade = setup_customer_and_grade()
    program, _release = setup_program_with_shipped_release(
        customer["id"], grade["id"], stock_qty=400, release_qty=350,
        reorder_point=100, replenishment_qty=500,
    )
    assert program["status"] == "REPLENISHMENT_NEEDED"

    after = post_receipt(program["id"], 60)  # 50 + 60 = 110 > 100 strictly
    assert after["on_hand_qty"] == 110
    assert after["status"] == "ACTIVE"
    assert_inventory_program(after)


def test_ship_decrements_program_balances_and_flips_replenishment_needed(
    api, production_planner_headers
):
    """PRD 3.7: "The ship decrements both `on_hand_qty` and `committed_qty` by
    the release's `qty`, flips the release to `SHIPPED`, and then runs the
    reorder threshold check on the program. That check is boundary-sensitive:
    if the program is `ACTIVE` and the post-decrement `on_hand_qty` is at or
    below `reorder_point`, the program flips to `REPLENISHMENT_NEEDED`".

    Design: Difficulty/transitive_cascade/release_ship_to_replenishment_order_three_link_cascade
    """
    customer, grade = setup_customer_and_grade()
    program = create_stocked_program(
        customer["id"], grade["id"], 400, reorder_point=100, replenishment_qty=500
    )
    release = create_approved_release(program["id"], 350, customer["id"])
    mid = get_program(program["id"])
    assert mid["on_hand_qty"] == 400
    assert mid["committed_qty"] == 350

    shipped = validate_success(
        api.ship_release_order(release["id"], production_planner_headers)
    )
    assert shipped["status"] == "SHIPPED"

    after = get_program(program["id"])
    assert after["on_hand_qty"] == 50  # link 1: stock decremented
    assert after["committed_qty"] == 0  # link 1: commitment cleared
    assert after["status"] == "REPLENISHMENT_NEEDED"  # link 2: threshold flip
    assert_program_stock_invariant(after)


def test_replenishment_flip_auto_creates_draft_box_order(api, plant_admin_headers):
    """PRD 3.7: "if the program is `ACTIVE` and the post-decrement
    `on_hand_qty` is at or below `reorder_point`, the program flips to
    `REPLENISHMENT_NEEDED` and the system auto-creates a replenishment box
    order in `DRAFT` — `customer_id`, `board_grade_id`, `routing_type`,
    `blank_width_in`, and `blank_length_in` copied from the program, `quantity`
    set to `replenishment_qty`, `board_source` set to `INTERNAL`, `ink_colors`
    empty, and `min_ect_required` 0."

    Design: Difficulty/transitive_cascade/release_ship_to_replenishment_order_three_link_cascade
    """
    customer, grade = setup_customer_and_grade()
    program, _release = setup_program_with_shipped_release(
        customer["id"], grade["id"], stock_qty=400, release_qty=350,
        reorder_point=100, replenishment_qty=500,
    )
    orders, meta = validate_paginated(
        api.list_box_orders(plant_admin_headers, params={"customer_id": customer["id"]})
    )
    assert meta["total_count"] == 1  # link 3: exactly one auto-created order
    replenishment = orders[0]
    assert replenishment["status"] == "DRAFT"
    assert replenishment["quantity"] == 500
    assert replenishment["board_source"] == "INTERNAL"
    assert replenishment["routing_type"] == "SLOTTED"
    assert replenishment["min_ect_required"] == 0
    assert replenishment["ink_colors"] == []
    assert replenishment["board_grade_id"] == grade["id"]
    assert_msf(replenishment["blank_width_in"], 24.0)
    assert_msf(replenishment["blank_length_in"], 20.0)


def test_release_on_suspended_program_returns_program_not_releasable(api):
    """PRD 2.7: "When a request trips multiple rules, the first applicable rule
    by the following priority order determines the error."; program
    releasability is a priority-4 state check while "Fiscal gates are ninth and
    last: the customer credit limit (`ERR_CREDIT_LIMIT_EXCEEDED`) and program
    balance sufficiency (`ERR_INSUFFICIENT_PROGRAM_BALANCE`)."
    PRD 3.7: "Suspending a program in `ACTIVE` or `REPLENISHMENT_NEEDED`
    (otherwise `ERR_INVALID_STATE`) moves it to `SUSPENDED`, which blocks all
    release create, approve, and ship operations with
    `ERR_PROGRAM_NOT_RELEASABLE`."

    Design: Difficulty/priority_pair_validation_conflict/release_create_state_error_beats_fiscal_error
    """
    customer, grade = setup_customer_and_grade()
    program = create_stocked_program(
        customer["id"], grade["id"], 100, reorder_point=10, replenishment_qty=500
    )
    validate_success(api.suspend_inventory_program(program["id"], ADMIN))

    # qty 150 > available 100 would also trip the fiscal ceiling; the
    # priority-4 state error must win
    res = api.create_release_order(
        program["id"],
        {"qty": 150, "requested_ship_date": "2026-08-12"},
        make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_RELEASABLE, expected_status=409)


def test_release_state_error_leaves_program_untouched(api):
    """PRD 3.7: "Suspending a program in `ACTIVE` or `REPLENISHMENT_NEEDED`
    (otherwise `ERR_INVALID_STATE`) moves it to `SUSPENDED`, which blocks all
    release create, approve, and ship operations with
    `ERR_PROGRAM_NOT_RELEASABLE`." A blocked creation mutates no balance:
    "`committed_qty` is the sum of `qty` over the program's release orders in
    `PENDING` or `APPROVED` status".

    Design: Difficulty/priority_pair_validation_conflict/release_create_state_error_beats_fiscal_error
    """
    customer, grade = setup_customer_and_grade()
    program = create_stocked_program(
        customer["id"], grade["id"], 100, reorder_point=10, replenishment_qty=500
    )
    validate_success(api.suspend_inventory_program(program["id"], ADMIN))

    res = api.create_release_order(
        program["id"],
        {"qty": 150, "requested_ship_date": "2026-08-12"},
        make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_RELEASABLE, expected_status=409)

    after = get_program(program["id"])
    assert after["committed_qty"] == 0
    assert after["on_hand_qty"] == 100


def test_release_qty_equal_to_available_qty_accepted(api):
    """PRD 3.7: "Creation is gated twice: the program must be `ACTIVE`
    (creation is not permitted from `REPLENISHMENT_NEEDED` or `SUSPENDED` —
    otherwise `ERR_PROGRAM_NOT_RELEASABLE`), and `qty` must be strictly
    positive and no greater than the program's `available_qty`, with equality
    allowed (otherwise `ERR_INVALID_QUANTITY` for the positivity floor and
    `ERR_INSUFFICIENT_PROGRAM_BALANCE` for the balance ceiling)."

    Design: Difficulty/boundary_precision_check/release_qty_equal_to_available_boundary
    """
    customer, grade = setup_customer_and_grade()
    program = create_stocked_program(
        customer["id"], grade["id"], 400, reorder_point=10, replenishment_qty=500
    )
    release = create_release(program["id"], 400, customer["id"])
    assert_release_order(release)
    assert release["status"] == "PENDING"

    after = get_program(program["id"])
    assert after["available_qty"] == 0
    assert after["committed_qty"] == 400
    assert_program_stock_invariant(after)


def test_release_one_unit_above_available_rejected(api):
    """PRD 3.7: "`qty` must be strictly positive and no greater than the
    program's `available_qty`, with equality allowed (otherwise
    `ERR_INVALID_QUANTITY` for the positivity floor and
    `ERR_INSUFFICIENT_PROGRAM_BALANCE` for the balance ceiling)."

    Design: Difficulty/boundary_precision_check/release_qty_equal_to_available_boundary
    """
    customer, grade = setup_customer_and_grade()
    program = create_stocked_program(
        customer["id"], grade["id"], 400, reorder_point=10, replenishment_qty=500
    )
    create_release(program["id"], 400, customer["id"])  # available now 0
    res = api.create_release_order(
        program["id"],
        {"qty": 1, "requested_ship_date": "2026-08-12"},
        make_customer_headers(customer["id"]),
    )
    validate_error(
        res, ApiErrorId.ERR_INSUFFICIENT_PROGRAM_BALANCE, expected_status=422
    )


def test_approve_release_on_suspended_program_rejected(api):
    """PRD 3.7: "A `PlantAdmin` approves a `PENDING` release (otherwise
    `ERR_INVALID_STATE`), moving it to `APPROVED`; approval additionally
    requires the program to be `ACTIVE` or `REPLENISHMENT_NEEDED` (otherwise
    `ERR_PROGRAM_NOT_RELEASABLE`)".
    PRD 3.7: "Suspending a program in `ACTIVE` or `REPLENISHMENT_NEEDED`
    (otherwise `ERR_INVALID_STATE`) moves it to `SUSPENDED`, which blocks all
    release create, approve, and ship operations with
    `ERR_PROGRAM_NOT_RELEASABLE`."

    Design: Difficulty/cross_entity_state_dependency/release_approve_blocked_while_program_suspended
    """
    customer, grade = setup_customer_and_grade()
    program = create_stocked_program(
        customer["id"], grade["id"], 100, reorder_point=10, replenishment_qty=500
    )
    release = create_release(program["id"], 10, customer["id"])
    validate_success(api.suspend_inventory_program(program["id"], ADMIN))

    res = api.approve_release_order(release["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_RELEASABLE, expected_status=409)

    releases, _ = validate_paginated(
        api.list_release_orders(program["id"], PLANNER)
    )
    assert releases[0]["status"] == "PENDING"


def test_approve_release_succeeds_after_program_reactivation(api):
    """PRD 3.7: "Reactivating a `SUSPENDED` program returns it to `ACTIVE`
    unconditionally — the reorder threshold is not re-evaluated at
    reactivation, only on the next ship or receipt."
    PRD 3.7: "A `PlantAdmin` approves a `PENDING` release (otherwise
    `ERR_INVALID_STATE`), moving it to `APPROVED`; approval additionally
    requires the program to be `ACTIVE` or `REPLENISHMENT_NEEDED` (otherwise
    `ERR_PROGRAM_NOT_RELEASABLE`)".

    Design: Difficulty/cross_entity_state_dependency/release_approve_blocked_while_program_suspended
    """
    customer, grade = setup_customer_and_grade()
    program = create_stocked_program(
        customer["id"], grade["id"], 100, reorder_point=10, replenishment_qty=500
    )
    release = create_release(program["id"], 10, customer["id"])
    validate_success(api.suspend_inventory_program(program["id"], ADMIN))
    validate_error(
        api.approve_release_order(release["id"], ADMIN),
        ApiErrorId.ERR_PROGRAM_NOT_RELEASABLE,
        expected_status=409,
    )

    validate_success(api.reactivate_inventory_program(program["id"], ADMIN))
    approved = validate_success(api.approve_release_order(release["id"], ADMIN))
    assert approved["status"] == "APPROVED"


def test_program_stock_invariant_holds_across_release_create(api):
    """PRD 3.7: "`committed_qty` is the sum of `qty` over the program's release
    orders in `PENDING` or `APPROVED` status (shipped and cancelled releases
    are excluded), and `available_qty` is `on_hand_qty` minus `committed_qty`."
    PRD 3.7: "The release lands in `PENDING` and immediately counts toward
    `committed_qty`".

    Design: Difficulty/compensating_invariant/program_stock_conserved_across_release_create_and_cancel
    """
    customer, grade = setup_customer_and_grade()
    program = create_stocked_program(
        customer["id"], grade["id"], 400, reorder_point=10, replenishment_qty=500
    )
    # 400 == 400 + 0
    assert program["on_hand_qty"] == 400
    assert program["available_qty"] == 400
    assert program["committed_qty"] == 0
    assert_program_stock_invariant(program)

    create_release(program["id"], 150, customer["id"])
    after = get_program(program["id"])
    # 400 == 250 + 150; on_hand untouched by a release create
    assert after["on_hand_qty"] == 400
    assert after["available_qty"] == 250
    assert after["committed_qty"] == 150
    assert_program_stock_invariant(after)


def test_program_stock_invariant_restored_after_release_cancel(api):
    """PRD 3.7: "Cancellation restores the commitment — `committed_qty`
    decreases by `qty`, `on_hand_qty` is untouched, the release becomes
    `CANCELLED`, and both `version`s increment."

    Design: Difficulty/compensating_invariant/program_stock_conserved_across_release_create_and_cancel
    """
    customer, grade = setup_customer_and_grade()
    program = create_stocked_program(
        customer["id"], grade["id"], 400, reorder_point=10, replenishment_qty=500
    )
    release = create_release(program["id"], 150, customer["id"])

    cancelled = validate_success(
        api.cancel_release_order(
            release["id"], make_customer_headers(customer["id"])
        )
    )
    assert cancelled["status"] == "CANCELLED"

    after = get_program(program["id"])
    assert after["on_hand_qty"] == 400  # never moved across create + cancel
    assert after["available_qty"] == 400
    assert after["committed_qty"] == 0
    assert_program_stock_invariant(after)


def test_ship_to_exactly_reorder_point_flips_into_need(
    api, production_planner_headers
):
    """PRD 3.7: "if the program is `ACTIVE` and the post-decrement
    `on_hand_qty` is at or below `reorder_point`, the program flips to
    `REPLENISHMENT_NEEDED`". "The boundary is deliberately asymmetric:
    `on_hand_qty` exactly equal to `reorder_point` flips the program into
    `REPLENISHMENT_NEEDED` but does not flip it back."

    Design: Corner/calculations/reorder_threshold_equality_flips_into_need
    """
    customer, grade = setup_customer_and_grade()
    program, _release = setup_program_with_shipped_release(
        customer["id"], grade["id"], stock_qty=400, release_qty=300,
        reorder_point=100, replenishment_qty=500,
    )
    assert program["on_hand_qty"] == 100
    assert program["status"] == "REPLENISHMENT_NEEDED"  # 100 <= 100 triggers


def test_receipt_to_exactly_reorder_point_stays_in_need(
    api, production_planner_headers
):
    """PRD 3.7: "Conversely, after a receipt, if the program is
    `REPLENISHMENT_NEEDED` and the post-increment `on_hand_qty` is strictly
    greater than `reorder_point`, it flips back to `ACTIVE`. The boundary is
    deliberately asymmetric: `on_hand_qty` exactly equal to `reorder_point`
    flips the program into `REPLENISHMENT_NEEDED` but does not flip it back."

    Design: Corner/calculations/receipt_to_exactly_reorder_point_stays_in_need
    """
    customer, grade = setup_customer_and_grade()
    program, _release = setup_program_with_shipped_release(
        customer["id"], grade["id"], stock_qty=400, release_qty=350,
        reorder_point=100, replenishment_qty=500,
    )
    assert program["on_hand_qty"] == 50
    assert program["status"] == "REPLENISHMENT_NEEDED"

    after = post_receipt(program["id"], 50)  # 50 + 50 = 100 == reorder_point
    assert after["on_hand_qty"] == 100
    assert after["status"] == "REPLENISHMENT_NEEDED"  # strict > required


def test_release_qty_zero_rejected(api):
    """PRD 3.7: "`qty` must be strictly positive and no greater than the
    program's `available_qty`, with equality allowed (otherwise
    `ERR_INVALID_QUANTITY` for the positivity floor and
    `ERR_INSUFFICIENT_PROGRAM_BALANCE` for the balance ceiling)."

    Design: Corner/validations/release_qty_zero_invalid
    """
    customer, grade = setup_customer_and_grade()
    program = create_stocked_program(
        customer["id"], grade["id"], 400, reorder_point=10, replenishment_qty=500
    )
    res = api.create_release_order(
        program["id"],
        {"qty": 0, "requested_ship_date": "2026-08-12"},
        make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_QUANTITY, expected_status=400)
    after = get_program(program["id"])
    assert after["committed_qty"] == 0
