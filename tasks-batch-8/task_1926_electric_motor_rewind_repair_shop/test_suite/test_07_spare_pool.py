"""Spare-motor pool claims (PRD §3.6): checkout availability gates, slot
cardinality, contract lifecycle guards, prorated first-month fee, and the
delivery -> loan-overdue -> standing cascade."""
from test_helpers import (
    TEST_USERS,
    checkout_loan,
    create_loan_payload,
    create_motor,
    create_pool_contract,
    create_pool_spare,
    create_shop,
    create_customer,
    deliver_work_order,
    get_customer,
    get_single_invoice,
    get_work_order_version,
    intake_work_order,
    record_incoming_test,
    record_coil_data,
    record_final_test,
    diagnose_work_order,
    issue_quote,
    send_quote,
    accept_quote,
    start_rewind,
    release_work_order,
    return_loan,
    set_clock,
    setup_released_work_order,
    setup_work_order_intake,
    setup_shop_customer_motor,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["service_manager_headers"]


def _pool_setup(api, slot_count=2, spare_kw=75, unit_kw=75):
    """Shop + customer + unit motor on a fresh work order + pool spare +
    ACTIVE contract."""
    shop = create_shop()
    customer = create_customer(shop["id"])
    motor = create_motor(shop["id"], customer["id"], serial_number="M-P", rated_kw=unit_kw)
    spare = create_pool_spare(shop["id"], serial_number="P-P", rated_kw=spare_kw)
    contract = create_pool_contract(shop["id"], customer["id"], slot_count=slot_count)
    wo = intake_work_order(shop["id"], customer["id"], motor["id"], "STANDARD")
    return shop, customer, motor, spare, contract, wo


# ─── Contract state dependency (Difficulty/cross_entity_state_dependency) ───

def test_checkout_rejected_when_contract_suspended(api):
    """PRD §3.6: "Four availability gates then apply, all rejected with
    `ERR_POOL_UNAVAILABLE` (HTTP 409): the contract must be `ACTIVE`; the
    number of loans under the contract currently `OUT` or `OVERDUE` must be
    fewer than the contract's `slot_count`; the spare motor must be a pool
    spare sitting `IN_POOL`; and the spare's `rated_kw` must fall within
    twenty percent of the unit under repair's rating, inclusive".

    Design: Difficulty/cross_entity_state_dependency/pool_checkout_depends_on_contract_active_and_spare_in_pool
    """
    shop, customer, motor, spare, contract, wo = _pool_setup(api, slot_count=1)
    validate_success(api.suspend_pool_contract(shop["id"], contract["id"], MANAGER), 200)

    res = api.checkout_loan(
        shop["id"], contract["id"], create_loan_payload(wo["id"], spare["id"]), MANAGER
    )
    validate_error(res, "ERR_POOL_UNAVAILABLE", expected_status=409)


def test_checkout_succeeds_after_resume_and_flips_custody(api):
    """PRD §3.6: "resume a `SUSPENDED` contract back to `ACTIVE`".
    PRD §3.6: "A successful checkout stamps `checked_out_at`, leaves `due_at`
    null until the linked repair is delivered, flips the spare's custody from
    `IN_POOL` to `ON_LOAN`".

    Design: Difficulty/cross_entity_state_dependency/pool_checkout_depends_on_contract_active_and_spare_in_pool
    """
    shop, customer, motor, spare, contract, wo = _pool_setup(api, slot_count=1)
    validate_success(api.suspend_pool_contract(shop["id"], contract["id"], MANAGER), 200)
    validate_success(api.resume_pool_contract(shop["id"], contract["id"], MANAGER), 200)

    loan = checkout_loan(shop["id"], contract["id"], wo["id"], spare["id"])
    assert loan["status"] == "OUT"
    assert loan["due_at"] is None
    spare_after = validate_success(api.get_motor(shop["id"], spare["id"], MANAGER), 200)
    assert spare_after["custody"] == "ON_LOAN"


# ─── Slot cardinality (Difficulty/resource_temporal_overlap) ───

def _slot_capacity_setup(api):
    shop = create_shop()
    customer = create_customer(shop["id"])
    m1 = create_motor(shop["id"], customer["id"], serial_number="M-13", rated_kw=75)
    m2 = create_motor(shop["id"], customer["id"], serial_number="M-14", rated_kw=75)
    p1 = create_pool_spare(shop["id"], serial_number="P-3", rated_kw=75)
    p2 = create_pool_spare(shop["id"], serial_number="P-4", rated_kw=75)
    contract = create_pool_contract(shop["id"], customer["id"], slot_count=1)
    wo1 = intake_work_order(shop["id"], customer["id"], m1["id"], "STANDARD")
    wo2 = intake_work_order(shop["id"], customer["id"], m2["id"], "STANDARD")
    loan1 = checkout_loan(shop["id"], contract["id"], wo1["id"], p1["id"])
    return shop, customer, contract, wo2, p2, loan1


def test_second_concurrent_loan_rejected_at_slot_capacity(api):
    """PRD §3.6: "the number of loans under the contract currently `OUT` or
    `OVERDUE` must be fewer than the contract's `slot_count`".

    Design: Difficulty/resource_temporal_overlap/pool_slot_capacity_is_count_not_interval
    """
    shop, customer, contract, wo2, p2, loan1 = _slot_capacity_setup(api)
    res = api.checkout_loan(
        shop["id"], contract["id"], create_loan_payload(wo2["id"], p2["id"]), MANAGER
    )
    validate_error(res, "ERR_POOL_UNAVAILABLE", expected_status=409)


def test_checkout_succeeds_after_return_frees_slot(api):
    """PRD §3.6: "A `ServiceManager` records the return: `returned_at` is
    stamped, the spare's custody moves back to `IN_POOL`, and the loan's
    status becomes the terminal `RETURNED`."

    Design: Difficulty/resource_temporal_overlap/pool_slot_capacity_is_count_not_interval
    """
    shop, customer, contract, wo2, p2, loan1 = _slot_capacity_setup(api)
    returned = return_loan(shop["id"], contract["id"], loan1["id"])
    assert returned["status"] == "RETURNED"

    loan2 = checkout_loan(shop["id"], contract["id"], wo2["id"], p2["id"])
    assert loan2["status"] == "OUT"


# ─── Delivery -> loan overdue -> standing (Difficulty/transitive_cascade) ───

def _delivered_with_open_loan(api):
    """Repair work order released and delivered 2026-08-01 with a pool loan
    checked out against it; clock then advanced to 2026-08-06."""
    bundle = setup_released_work_order(
        rewind_hours=5, materials_cents=10000, replacement_cost_cents=999999,
        motor_overrides={"rated_kw": 75, "frame_mm": 200, "manufacture_year": 2020},
    )
    shop, customer = bundle["shop"], bundle["customer"]
    spare = create_pool_spare(shop["id"], serial_number="P-1", rated_kw=75)
    contract = create_pool_contract(shop["id"], customer["id"], slot_count=2)
    loan = checkout_loan(shop["id"], contract["id"], bundle["work_order"]["id"], spare["id"])
    set_clock("2026-08-01T00:00:00Z")
    bundle["work_order"] = deliver_work_order(shop["id"], bundle["work_order"]["id"])
    set_clock("2026-08-06T00:00:00Z")
    return shop, customer, contract, loan


def test_deliver_sets_loan_due_at_and_lazy_overdue_flip(api):
    """PRD §3.5: "every pool loan still `OUT` against the order has its
    `due_at` recomputed as `delivered_at` plus the shop's
    `pool_loan_grace_days`".
    PRD §2.4: "A pool loan whose `due_at` is set and has passed flips from
    `OUT` to `OVERDUE` on read."
    PRD §3.6: "`overdue_days` is the number of whole days between `due_at` and
    the return time — or the current time for a loan still out — floored to
    whole days and never below zero, and it is zero whenever `due_at` is null;
    `overdue_charge_cents` is `overdue_days` multiplied by the shop's
    `pool_loan_daily_cents`."

    Design: Difficulty/transitive_cascade/deliver_cascades_to_loan_overdue_to_standing_hold
    """
    shop, customer, contract, loan = _delivered_with_open_loan(api)
    data, _meta = validate_paginated(api.list_loans(shop["id"], contract["id"], MANAGER))
    current = [l for l in data if l["id"] == loan["id"]]
    assert len(current) == 1
    loan_now = current[0]
    assert loan_now["due_at"] == "2026-08-04T00:00:00.000Z"  # delivered + 3 grace days
    assert loan_now["status"] == "OVERDUE"
    assert loan_now["overdue_days"] == 2
    assert loan_now["overdue_charge_cents"] == 3600


def test_overdue_loan_feeds_customer_standing_watch(api):
    """PRD §3.5: "Short of that, it is `WATCH` when any invoice is past due,
    or when any pool loan attached to the customer through their spare-pool
    contracts is `OVERDUE`; overdue loans can only ever contribute `WATCH`,
    never `HOLD`."

    Design: Difficulty/transitive_cascade/deliver_cascades_to_loan_overdue_to_standing_hold
    """
    shop, customer, contract, loan = _delivered_with_open_loan(api)
    # Force the lazy flip via a loan read, then re-read the customer.
    validate_paginated(api.list_loans(shop["id"], contract["id"], MANAGER))
    standing = get_customer(shop["id"], customer["id"])
    assert standing["standing"] == "WATCH"


# ─── kW band gate (Corner/validations) ───

def test_pool_checkout_spare_kw_outside_band_rejected(api):
    """PRD §3.6: "the spare's `rated_kw` must fall within twenty percent of
    the unit under repair's rating, inclusive — no less than 80 percent and no
    more than 120 percent of it".

    Design: Corner/validations/pool_checkout_spare_kw_outside_band_rejected
    """
    shop, customer, motor, spare, contract, wo = _pool_setup(
        api, slot_count=2, spare_kw=50, unit_kw=75
    )
    res = api.checkout_loan(
        shop["id"], contract["id"], create_loan_payload(wo["id"], spare["id"]), MANAGER
    )
    validate_error(res, "ERR_POOL_UNAVAILABLE", expected_status=409)  # 50 < 75*0.8 == 60

    # Inclusive lower bound: a 60 kW spare is exactly 80% of 75 kW.
    spare_ok = create_pool_spare(shop["id"], serial_number="P-K2", rated_kw=60)
    loan = checkout_loan(shop["id"], contract["id"], wo["id"], spare_ok["id"])
    assert loan["status"] == "OUT"


# ─── Contract suspend guard (Corner/state_machines) ───

def test_contract_suspend_blocked_while_loan_out(api):
    """PRD §3.6: "A `ServiceManager` may suspend an `ACTIVE` contract —
    blocked while any loan under it is `OUT` or `OVERDUE`, rejected as
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/contract_suspend_blocked_while_loan_out
    """
    shop, customer, motor, spare, contract, wo = _pool_setup(api, slot_count=2)
    loan = checkout_loan(shop["id"], contract["id"], wo["id"], spare["id"])

    res = api.suspend_pool_contract(shop["id"], contract["id"], MANAGER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    return_loan(shop["id"], contract["id"], loan["id"])
    suspended = validate_success(api.suspend_pool_contract(shop["id"], contract["id"], MANAGER), 200)
    assert suspended["status"] == "SUSPENDED"


# ─── Prorated first-month fee (Corner/calculations) ───

def test_pool_first_month_fee_prorated_by_activation_day(api):
    """PRD §3.6: "the first month charges the fraction of the calendar month
    remaining — counting the activation day itself, so the remaining days are
    the days in the month of `activated_on` minus the day of the month of
    `activated_on` plus one, over the days in that month — rounded half-up to
    whole cents".

    Design: Corner/calculations/pool_first_month_fee_prorated_by_activation_day
    """
    shop = create_shop()
    customer = create_customer(shop["id"])
    set_clock("2026-08-15T00:00:00Z")

    contract = validate_success(
        api.create_pool_contract(
            shop["id"], {"customer_id": customer["id"], "slot_count": 4}, MANAGER
        ),
        201,
    )
    # 4 * 4500 = 18000; August has 31 days; 31 - 15 + 1 = 17 remaining;
    # round_half_up(18000 * 17 / 31) = 9871.
    assert contract["first_month_fee_cents"] == 9871
    assert contract["activated_on"] == "2026-08-15T00:00:00.000Z"
    assert contract["status"] == "ACTIVE"
