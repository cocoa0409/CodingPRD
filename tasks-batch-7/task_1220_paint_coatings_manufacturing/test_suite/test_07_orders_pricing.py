"""Order capture and pricing: the rush fork/join, pinned pricing order,
custom minimums, rush daily capacity, and fulfillment bubble-up."""

import test_helpers as fx
from test_helpers import ApiErrorId, validate_error, validate_success


def _setup_two_formula_catalog():
    """TB1/C1/F1 (stock) + TB2/C2/F2 (custom hazmat), all ACTIVE; CU1."""
    tb1 = fx.create_tb1()
    tb2 = fx.create_tb2()
    c1 = fx.create_c1()
    c2 = fx.create_c2()
    f1 = fx.create_f1(tb1["id"], c1["id"])
    fx.activate_formula(f1["id"])
    f2 = fx.create_f2(tb2["id"], c2["id"])
    fx.activate_formula(f2["id"])
    cu1 = fx.create_customer(name="Sunbelt Paints AZ")
    return tb1, tb2, c1, c2, f1, f2, cu1


def test_rush_fee_tier_keyed_on_prefee_subtotal(api):
    """PRD §3.3: "Fourth, the rush fee: at order creation `rush_fee_cents` is
    0; on rush approval it becomes 12 percent of the pre-fee subtotal, rounded
    half up to whole cents, when that subtotal is at least 200000 cents, and a
    flat 15000 cents otherwise. The tier is keyed on `subtotal_cents` alone
    and must never be keyed on `total_cents`, which contains the fee itself."
    PRD §3.3: "Third, `setup_fee_cents` is 7500 cents — seventy-five dollars —
    for each line whose formula is custom."

    Design: Difficulty/combinatorial_formula/order_pricing_pinned_eval_order
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _tb2, _c1, _c2, f1, f2, cu1 = _setup_two_formula_catalog()

    o_rush = validate_success(
        api.create_order(
            fx.create_order_payload(
                cu1["id"], f1["id"], rush_flag=True,
                lines=[
                    {"formula_id": f1["id"], "gallons": 30, "size_code": "GALLON"},
                    {"formula_id": f2["id"], "gallons": 100,
                     "size_code": "FIVE_GALLON"},
                ],
            ),
            fx.make_dealer_headers(cu1["id"]),
        ),
        expected_status=201,
    )
    assert o_rush["status"] == "RUSH_REVIEW"
    assert o_rush["rush_fee_cents"] == 0
    assert o_rush["subtotal_cents"] == 30 * 3200 + 100 * 4100
    assert o_rush["setup_fee_cents"] == 7500

    approved = validate_success(
        api.rush_approve_order(o_rush["id"], fx.PLANT_MANAGER)
    )
    assert approved["status"] == "PLACED"
    # 12% of the PRE-FEE subtotal 506000 = 60720.
    assert approved["rush_fee_cents"] == 60720
    assert approved["total_cents"] == 506000 + 7500 + 60720
    fx.assert_order_invariants(approved)


def test_rush_flat_fee_branch_on_small_subtotal(api):
    """PRD §3.3: "on rush approval it becomes 12 percent of the pre-fee
    subtotal, rounded half up to whole cents, when that subtotal is at least
    200000 cents, and a flat 15000 cents otherwise."
    PRD §3.3: "First, each line's amount is computed as its `gallons`
    multiplied by the unit price per gallon of the base its formula tints,
    rounded half up to whole cents. Second, `subtotal_cents` is the sum of
    those line amounts."

    Design: Difficulty/combinatorial_formula/order_pricing_pinned_eval_order
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _tb2, _c1, _c2, f1, _f2, cu1 = _setup_two_formula_catalog()

    o_small = validate_success(
        api.create_order(
            fx.create_order_payload(cu1["id"], f1["id"], rush_flag=True,
                                    lines=[{"formula_id": f1["id"],
                                            "gallons": 10,
                                            "size_code": "GALLON"}]),
            fx.make_dealer_headers(cu1["id"]),
        ),
        expected_status=201,
    )
    assert o_small["subtotal_cents"] == 32000

    approved = validate_success(
        api.rush_approve_order(o_small["id"], fx.PLANT_MANAGER)
    )
    # 32000 < 200000 -> flat branch, not 12%.
    assert approved["rush_fee_cents"] == 15000
    assert approved["total_cents"] == 32000 + 0 + 15000
    assert approved["status"] == "PLACED"


def test_custom_minimum_exact_gallons(api):
    """PRD §3.3: "custom work carries minimums: each custom-formula line must
    order at least 50 gallons, raised to at least 100 gallons when the order
    is rushed; a shortfall is `ERR_CUSTOM_MINIMUM_NOT_MET`."

    Design: Difficulty/boundary_precision_check/custom_minimum_exact_gallons
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _tb2, _c1, _c2, _f1, f2, cu1 = _setup_two_formula_catalog()
    dealer = fx.make_dealer_headers(cu1["id"])

    # Exactly 50 gal on a custom formula passes (at least 50).
    o50 = validate_success(
        api.create_order(
            fx.create_order_payload(
                cu1["id"], f2["id"],
                lines=[{"formula_id": f2["id"], "gallons": 50,
                        "size_code": "FIVE_GALLON"}],
            ),
            dealer,
        ),
        expected_status=201,
    )
    assert o50["total_cents"] == 50 * 4100 + 7500

    # 49 gal misses the standard floor.
    err49 = api.create_order(
        fx.create_order_payload(
            cu1["id"], f2["id"],
            lines=[{"formula_id": f2["id"], "gallons": 49,
                    "size_code": "FIVE_GALLON"}],
        ),
        dealer,
    )
    validate_error(err49, ApiErrorId.ERR_CUSTOM_MINIMUM_NOT_MET.value, 422)

    # Rush raises the floor to 100: 99 fails, exactly 100 forks to review.
    err99 = api.create_order(
        fx.create_order_payload(
            cu1["id"], f2["id"], rush_flag=True,
            lines=[{"formula_id": f2["id"], "gallons": 99,
                    "size_code": "FIVE_GALLON"}],
        ),
        dealer,
    )
    validate_error(err99, ApiErrorId.ERR_CUSTOM_MINIMUM_NOT_MET.value, 422)

    o100 = validate_success(
        api.create_order(
            fx.create_order_payload(
                cu1["id"], f2["id"], rush_flag=True,
                lines=[{"formula_id": f2["id"], "gallons": 100,
                        "size_code": "FIVE_GALLON"}],
            ),
            dealer,
        ),
        expected_status=201,
    )
    assert o100["status"] == "RUSH_REVIEW"


def test_custom_minimum_rush_floor_compared_to_standard(api):
    """PRD §3.3: "custom work carries minimums: each custom-formula line must
    order at least 50 gallons, raised to at least 100 gallons when the order
    is rushed; a shortfall is `ERR_CUSTOM_MINIMUM_NOT_MET`."
    PRD §3.3: "The order is marked `is_custom_order` when any line's formula
    is a custom one"

    Design: Difficulty/boundary_precision_check/custom_minimum_exact_gallons
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _tb2, _c1, _c2, _f1, f2, cu1 = _setup_two_formula_catalog()
    dealer = fx.make_dealer_headers(cu1["id"])

    # 75 gal: fine standard, short under rush.
    standard = validate_success(
        api.create_order(
            fx.create_order_payload(
                cu1["id"], f2["id"],
                lines=[{"formula_id": f2["id"], "gallons": 75,
                        "size_code": "FIVE_GALLON"}],
            ),
            dealer,
        ),
        expected_status=201,
    )
    assert standard["status"] == "PLACED"
    assert standard["is_custom_order"] is True

    rushed = api.create_order(
        fx.create_order_payload(
            cu1["id"], f2["id"], rush_flag=True,
            lines=[{"formula_id": f2["id"], "gallons": 75,
                    "size_code": "FIVE_GALLON"}],
        ),
        dealer,
    )
    validate_error(rushed, ApiErrorId.ERR_CUSTOM_MINIMUM_NOT_MET.value, 422)


def _create_rush_order(api, cu1, f1):
    return validate_success(
        api.create_order(
            fx.create_order_payload(cu1["id"], f1["id"], rush_flag=True,
                                    lines=[{"formula_id": f1["id"],
                                            "gallons": 10,
                                            "size_code": "GALLON"}]),
            fx.make_dealer_headers(cu1["id"]),
        ),
        expected_status=201,
    )


def test_rush_capacity_third_ok_fourth_fails(api):
    """PRD §3.3: "Rush approval is capacity-limited: the plant grants at most
    3 rush approvals per UTC calendar date, counted over all orders by their
    `rush_approved_date` regardless of those orders' current status, so the
    day's third approval succeeds and its fourth is rejected with
    `ERR_RUSH_CAPACITY_EXCEEDED`; the counter resets implicitly at each date
    rollover."

    Design: Difficulty/boundary_precision_check/rush_capacity_third_ok_fourth_fails
    """
    fx.set_clock("2026-06-01T08:00:00Z")
    _tb1, _c1, f1 = fx.setup_lab_catalog_active()
    cu1 = fx.create_customer(name="Sunbelt Paints AZ")
    orders = [_create_rush_order(api, cu1, f1) for _ in range(4)]

    for order in orders[:3]:
        approved = validate_success(
            api.rush_approve_order(order["id"], fx.PLANT_MANAGER)
        )
        assert approved["status"] == "PLACED"
        assert approved["rush_fee_cents"] == 15000

    fourth = api.rush_approve_order(orders[3]["id"], fx.PLANT_MANAGER)
    validate_error(fourth, ApiErrorId.ERR_RUSH_CAPACITY_EXCEEDED.value, 422)

    untouched = fx.read_order(orders[3]["id"])
    assert untouched["status"] == "RUSH_REVIEW"
    assert untouched["rush_fee_cents"] == 0, (
        "a failed approval leaves no fee behind"
    )


def test_rush_capacity_boundary_is_exactly_three(api):
    """PRD §3.3: "the plant grants at most 3 rush approvals per UTC calendar
    date, counted over all orders by their `rush_approved_date` regardless of
    those orders' current status, so the day's third approval succeeds and
    its fourth is rejected with `ERR_RUSH_CAPACITY_EXCEEDED`"

    Design: Difficulty/boundary_precision_check/rush_capacity_third_ok_fourth_fails
    """
    fx.set_clock("2026-06-01T08:00:00Z")
    _tb1, _c1, f1 = fx.setup_lab_catalog_active()
    cu1 = fx.create_customer(name="Sunbelt Paints AZ")
    orders = [_create_rush_order(api, cu1, f1) for _ in range(4)]

    validate_success(api.rush_approve_order(orders[0]["id"], fx.PLANT_MANAGER))
    validate_success(api.rush_approve_order(orders[1]["id"], fx.PLANT_MANAGER))

    # The third approval is the boundary success.
    third = validate_success(api.rush_approve_order(orders[2]["id"],
                                                    fx.PLANT_MANAGER))
    assert third["status"] == "PLACED"
    assert third["rush_approved_date"] is not None
    assert str(third["rush_approved_date"]).startswith("2026-06-01")

    fourth = api.rush_approve_order(orders[3]["id"], fx.PLANT_MANAGER)
    validate_error(fourth, ApiErrorId.ERR_RUSH_CAPACITY_EXCEEDED.value, 422)


def test_rush_capacity_resets_next_utc_day(api):
    """PRD §3.3: "the counter resets implicitly at each date rollover."
    PRD §3.3: "Approval computes the rush fee, recomputes the total, stamps
    `rush_approved_date` with the current UTC date, and returns the order to
    `PLACED`."

    Design: Corner/cross_cutting_layers/rush_capacity_resets_next_utc_day
    """
    fx.set_clock("2026-06-01T08:00:00Z")
    _tb1, _c1, f1 = fx.setup_lab_catalog_active()
    cu1 = fx.create_customer(name="Sunbelt Paints AZ")
    orders = [_create_rush_order(api, cu1, f1) for _ in range(4)]
    for order in orders[:3]:
        validate_success(api.rush_approve_order(order["id"], fx.PLANT_MANAGER))
    blocked = api.rush_approve_order(orders[3]["id"], fx.PLANT_MANAGER)
    validate_error(blocked, ApiErrorId.ERR_RUSH_CAPACITY_EXCEEDED.value, 422)

    # The next UTC date has its own quota; no manual reset exists.
    fx.set_clock("2026-06-02T08:00:00Z")
    approved = validate_success(
        api.rush_approve_order(orders[3]["id"], fx.PLANT_MANAGER)
    )
    assert approved["status"] == "PLACED"
    assert approved["rush_fee_cents"] == 15000
    assert str(approved["rush_approved_date"]).startswith("2026-06-02")


def test_order_rush_reject_branch_clears_flag_and_fee(api):
    """PRD §3.3: "Rush rejection also returns the order to `PLACED`, but by
    clearing `rush_flag` to false — no fee is applied, `rush_fee_cents` stays
    0, and `total_cents` is unchanged."
    PRD §3.3: "A `ProductionOperator` schedules a `PLACED` order by presenting
    a `batch_id`; the batch must belong to this order — its `order_id` must
    equal the order's id, else `ERR_ORDER_BATCH_MISMATCH` — and must still be
    `PLANNED`, else `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/order_rush_fork_join_branches
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    tb1, c1, f1, m1 = fx.setup_plant()
    cu1 = fx.create_customer(name="Sunbelt Paints AZ")
    o_rej = _create_rush_order(api, cu1, f1)
    assert o_rej["status"] == "RUSH_REVIEW"

    rejected = validate_success(
        api.rush_reject_order(o_rej["id"], fx.PLANT_MANAGER)
    )
    assert rejected["status"] == "PLACED"
    assert rejected["rush_flag"] is False
    assert rejected["rush_fee_cents"] == 0
    assert rejected["total_cents"] == 32000
    assert rejected.get("rush_approved_date") is None

    # The join point: the reverted order schedules like any standard order.
    b_rej = fx.plan_batch(f1["id"], m1["id"], planned_gallons=10,
                          order_id=o_rej["id"])
    scheduled = validate_success(
        api.schedule_order(o_rej["id"], {"batch_id": b_rej["id"]},
                           fx.PRODUCTION_OPERATOR)
    )
    assert scheduled["status"] == "SCHEDULED"


def test_order_rush_approve_branch_then_schedule_join(api):
    """PRD §3.3: "A standard order is born in `PLACED`; an order with
    `rush_flag` set is born directly in `RUSH_REVIEW`, awaiting a
    `PlantManager` decision."
    PRD §3.3: "Approval computes the rush fee, recomputes the total, stamps
    `rush_approved_date` with the current UTC date, and returns the order to
    `PLACED`."

    Design: Difficulty/non_linear_state_machine/order_rush_fork_join_branches
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    tb1, c1, f1, m1 = fx.setup_plant()
    cu1 = fx.create_customer(name="Sunbelt Paints AZ")
    o_app = _create_rush_order(api, cu1, f1)
    assert o_app["status"] == "RUSH_REVIEW"

    approved = validate_success(
        api.rush_approve_order(o_app["id"], fx.PLANT_MANAGER)
    )
    assert approved["status"] == "PLACED"
    assert approved["rush_flag"] is True
    assert approved["rush_fee_cents"] == 15000
    assert approved["total_cents"] == 47000
    assert str(approved["rush_approved_date"]).startswith("2026-05-01")

    # Same join point as the reject branch: schedule against its own batch.
    b_app = fx.plan_batch(f1["id"], m1["id"], planned_gallons=10,
                          order_id=o_app["id"],
                          window=("2026-06-11T08:00:00Z",
                                  "2026-06-11T10:00:00Z"))
    scheduled = validate_success(
        api.schedule_order(o_app["id"], {"batch_id": b_app["id"]},
                           fx.PRODUCTION_OPERATOR)
    )
    assert scheduled["status"] == "SCHEDULED"


def test_order_batch_mismatch_on_schedule_returns_error(api):
    """PRD §3.3: "the batch must belong to this order — its `order_id` must
    equal the order's id, else `ERR_ORDER_BATCH_MISMATCH`"

    Design: Corner/validations/order_batch_mismatch_on_schedule_returns_error
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    cu1 = fx.create_customer(name="Sunbelt Paints AZ")
    dealer = fx.make_dealer_headers(cu1["id"])
    o1 = validate_success(
        api.create_order(fx.create_order_payload(cu1["id"], f1["id"]), dealer),
        expected_status=201,
    )
    o2 = validate_success(
        api.create_order(
            fx.create_order_payload(
                cu1["id"], f1["id"],
                lines=[{"formula_id": f1["id"], "gallons": 5,
                        "size_code": "GALLON"}],
            ),
            dealer,
        ),
        expected_status=201,
    )
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3,
                       order_id=o1["id"])

    mismatch = api.schedule_order(o2["id"], {"batch_id": b1["id"]},
                                  fx.PRODUCTION_OPERATOR)
    validate_error(mismatch, ApiErrorId.ERR_ORDER_BATCH_MISMATCH.value, 422)
    assert fx.read_order(o2["id"])["status"] == "PLACED"


def test_order_fulfilled_bubble_up_on_last_ship(api):
    """PRD §3.3: "On every shipment, the volumes of that order's shipped
    containers are summed and compared against the sum of its line gallons;
    once shipped volume covers the lines, the order moves to `FULFILLED`.
    This bubble-up can fire from `IN_PRODUCTION`, and for stock-only
    fulfillment — shipping from existing inventory with no batch ever
    scheduled — directly from `PLACED`."

    Design: Corner/state_machines/order_fulfilled_bubble_up_on_last_ship
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    fx.create_active_voc_rule(category="NONFLAT", state_code="*",
                              max_voc_gpl=250, effective_from="2026-01-01")
    cu1 = fx.create_customer(name="Sunbelt Paints AZ")

    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=2)
    _batch, cans = fx.drive_batch_to_filled(
        b1["id"], actual_gallons=2,
        fills=[("GALLON", 4600), ("GALLON", 4600)], waste_gallons=0,
    )
    o1 = validate_success(
        api.create_order(
            fx.create_order_payload(
                cu1["id"], f1["id"],
                lines=[{"formula_id": f1["id"], "gallons": 2,
                        "size_code": "GALLON"}],
            ),
            fx.make_dealer_headers(cu1["id"]),
        ),
        expected_status=201,
    )
    fx.set_clock("2026-06-15T09:00:00Z")

    # Partial coverage: 1.0 of 2 gallons shipped — still PLACED.
    first = validate_success(
        api.ship_container(cans[0]["id"], {"order_id": o1["id"]},
                           fx.PRODUCTION_OPERATOR)
    )
    assert first["status"] == "SHIPPED"
    assert fx.read_order(o1["id"])["status"] == "PLACED"

    # The completing ship bubbles the order straight from PLACED.
    second = validate_success(
        api.ship_container(cans[1]["id"], {"order_id": o1["id"]},
                           fx.PRODUCTION_OPERATOR)
    )
    assert second["status"] == "SHIPPED"
    assert fx.read_order(o1["id"])["status"] == "FULFILLED"
