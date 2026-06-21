"""Fleet account credit discipline: reserved vs settled aggregations, the credit-limit
gate, the inactive-account gate, suspend/reactivate re-pricing, close-with-open-balance,
and the reserved-credit compensating invariant under authorize -> void.

Sources: difficulty rules dual_variant_calc, cross_entity_state_dependency,
compensating_invariant; corner sections state_machines + validations.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_fleet_manager_headers,
    # fixtures
    set_clock,
    setup_shop_with_catalog,
    create_technician,
    create_fleet_account,
    create_fleet_vehicle,
    create_retail_vehicle,
    create_direct_work_order,
    claim_start,
    begin_inspection,
    finish_inspection,
    mark_ready,
    add_line,
    create_inspection_item,
    authorize,
    capture,
    void_payment,
    cancel_work_order,
    drive_to_ready,
    setup_fleet_ready_order,
)

SA = TEST_USERS["service_advisor_headers"]
SM = TEST_USERS["shop_manager_headers"]


# ─── dual_variant_calc / fleet_reserved_vs_settled_available_credit ────────

def test_reserved_counts_authorized_plus_paid(api):
    """PRD §2.11: "Its `reserved_credit_cents` is the sum of `total_cents` across all work
    orders of the account's vehicles whose `payment_status` is `AUTHORIZED` or `PAID` — a
    forward-looking figure that includes authorized-but-not-yet-captured orders and
    therefore gates new authorizations conservatively."

    Design: Difficulty/dual_variant_calc/fleet_reserved_vs_settled_available_credit
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    # WO_A and WO_B are concurrent at the fixed logical clock, so each needs its
    # own technician — one technician on two simultaneous live orders would be a
    # buffered double-booking per PRD §3.4.
    tech_b = create_technician(shop["id"], full_name="Tom")
    item = create_inspection_item(shop["id"], code="AIR_FILTER", name="Air Filter",
                                  price_cents=4495, labor_minutes=5)
    fleet = create_fleet_account(shop["id"], company_name="Acme", discount_pct=0.10,
                                 credit_limit_cents=100000)
    bay_b = get_success_data(api.create_bay({"shop_id": shop["id"], "label": "Bay 2"}, SM))
    veh_a = create_fleet_vehicle(shop["id"], fleet["id"], vin="VINFLA001", plate="FLA1",
                                 make="Ford", model="F150", odometer=20000)
    veh_b = create_fleet_vehicle(shop["id"], fleet["id"], vin="VINFLA002", plate="FLA2",
                                 make="Ford", model="F250", odometer=25000)

    # WO_A: package 6995 + AIR_FILTER 4495, fleet 10% -> AUTHORIZED (not captured), total 11194.
    wo_a = create_direct_work_order(shop["id"], veh_a["id"], bay["id"], pkg["id"], 20000)
    claim_start(wo_a["id"], tech["id"])
    in_insp = begin_inspection(wo_a["id"], tech["id"])
    add_line(wo_a["id"], tech["id"], item["id"], in_insp["version"])
    finish_inspection(wo_a["id"], tech["id"])
    mark_ready(wo_a["id"], tech["id"])
    authorize(wo_a["id"], "FLEET_ACCOUNT")

    # WO_B: package 6995 only, fleet 10% -> AUTHORIZED then CAPTURED (PAID), total 6814.
    wo_b = create_direct_work_order(shop["id"], veh_b["id"], bay_b["id"], pkg["id"], 25000)
    claim_start(wo_b["id"], tech_b["id"])
    mark_ready(wo_b["id"], tech_b["id"])
    authorize(wo_b["id"], "FLEET_ACCOUNT")
    capture(wo_b["id"])

    fm = make_fleet_manager_headers(fleet["id"])
    acct = get_success_data(api.get_fleet_account(fleet["id"], fm))
    assert acct["reserved_credit_cents"] == 18008  # 11194 AUTHORIZED + 6814 PAID


def test_settled_counts_paid_only(api):
    """PRD §2.11: "Its `settled_credit_cents` is the sum of `total_cents` across only those
    work orders whose `payment_status` is `PAID` — the money actually captured."

    Design: Difficulty/dual_variant_calc/fleet_reserved_vs_settled_available_credit
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    # Concurrent orders at the fixed logical clock need distinct technicians
    # (one technician on two simultaneous live orders = double-booking, PRD §3.4).
    tech_b = create_technician(shop["id"], full_name="Tom")
    item = create_inspection_item(shop["id"], code="AIR_FILTER", name="Air Filter",
                                  price_cents=4495, labor_minutes=5)
    fleet = create_fleet_account(shop["id"], company_name="Acme", discount_pct=0.10,
                                 credit_limit_cents=100000)
    bay_b = get_success_data(api.create_bay({"shop_id": shop["id"], "label": "Bay 2"}, SM))
    veh_a = create_fleet_vehicle(shop["id"], fleet["id"], vin="VINFLA003", plate="FLA3",
                                 make="Ford", model="F150", odometer=20000)
    veh_b = create_fleet_vehicle(shop["id"], fleet["id"], vin="VINFLA004", plate="FLA4",
                                 make="Ford", model="F250", odometer=25000)
    wo_a = create_direct_work_order(shop["id"], veh_a["id"], bay["id"], pkg["id"], 20000)
    claim_start(wo_a["id"], tech["id"])
    in_insp = begin_inspection(wo_a["id"], tech["id"])
    add_line(wo_a["id"], tech["id"], item["id"], in_insp["version"])
    finish_inspection(wo_a["id"], tech["id"])
    mark_ready(wo_a["id"], tech["id"])
    authorize(wo_a["id"], "FLEET_ACCOUNT")  # stays AUTHORIZED

    wo_b = create_direct_work_order(shop["id"], veh_b["id"], bay_b["id"], pkg["id"], 25000)
    claim_start(wo_b["id"], tech_b["id"])
    mark_ready(wo_b["id"], tech_b["id"])
    authorize(wo_b["id"], "FLEET_ACCOUNT")
    capture(wo_b["id"])  # PAID

    fm = make_fleet_manager_headers(fleet["id"])
    acct = get_success_data(api.get_fleet_account(fleet["id"], fm))
    assert acct["settled_credit_cents"] == 6814  # only WO_B PAID
    assert acct["reserved_credit_cents"] != acct["settled_credit_cents"]


# ─── compensating_invariant / fleet_reserved_credit_conserved ──────────────

def test_reserved_credit_charged_on_fleet_authorize(api):
    """PRD §3.8: "A successful authorization creates a `Payment` whose `method` snapshots
    the order's `payment_method`, whose `amount_cents` snapshots the order's `total_cents`,
    and whose `status` is `AUTHORIZED`; for a fleet payment the account's
    `reserved_credit_cents` is recomputed to include this order."

    Design: Difficulty/compensating_invariant/fleet_reserved_credit_conserved_under_authorize_then_void
    """
    s = setup_fleet_ready_order(credit_limit_cents=100000, discount_pct=0.10)
    fleet, wo = s["fleet_account"], s["work_order"]
    authorize(wo["id"], "FLEET_ACCOUNT")
    acct = get_success_data(api.get_fleet_account(fleet["id"], SM))
    assert acct["reserved_credit_cents"] == 6814


def test_reserved_credit_released_to_zero_on_void(api):
    """PRD §3.8: "Voiding moves the `Payment` from `AUTHORIZED` to `VOIDED` and, because the
    order no longer counts as committed, recomputes the fleet account's
    `reserved_credit_cents` to release the reservation."

    Design: Difficulty/compensating_invariant/fleet_reserved_credit_conserved_under_authorize_then_void
    """
    s = setup_fleet_ready_order(credit_limit_cents=100000, discount_pct=0.10)
    fleet, wo = s["fleet_account"], s["work_order"]
    authorize(wo["id"], "FLEET_ACCOUNT")
    mid = get_success_data(api.get_fleet_account(fleet["id"], SM))
    assert mid["reserved_credit_cents"] == 6814
    void_payment(wo["id"])
    after = get_success_data(api.get_fleet_account(fleet["id"], SM))
    # Conserved: back to the pre-authorize value (0).
    assert after["reserved_credit_cents"] == 0


# ─── cross_entity_state_dependency / fleet_authorize_requires_account_active ─

def test_authorize_fleet_rejected_when_account_suspended(api):
    """PRD §3.8: "When the method is `FLEET_ACCOUNT`, the vehicle must be bound to a fleet
    account — its `fleet_account_id` must be set, else `ERR_VEHICLE_HAS_NO_FLEET_ACCOUNT` —
    and that account must be `ACTIVE`, else `ERR_FLEET_ACCOUNT_INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/fleet_authorize_requires_account_active_workorder_to_fleet
    """
    s = setup_fleet_ready_order(credit_limit_cents=100000, discount_pct=0.10)
    fleet, wo = s["fleet_account"], s["work_order"]
    get_success_data(api.suspend_fleet_account(fleet["id"], SM))
    res = api.authorize_payment(wo["id"], {"payment_method": "FLEET_ACCOUNT"}, SA)
    validate_error(res, "ERR_FLEET_ACCOUNT_INACTIVE", expected_status=409)


def test_authorize_fleet_active_account_succeeds(api):
    """PRD §3.8: "When the method is `FLEET_ACCOUNT`, the vehicle must be bound to a fleet
    account — its `fleet_account_id` must be set, else `ERR_VEHICLE_HAS_NO_FLEET_ACCOUNT` —
    and that account must be `ACTIVE`, else `ERR_FLEET_ACCOUNT_INACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/fleet_authorize_requires_account_active_workorder_to_fleet
    """
    s = setup_fleet_ready_order(credit_limit_cents=100000, discount_pct=0.10)
    wo = s["work_order"]
    res = api.authorize_payment(wo["id"], {"payment_method": "FLEET_ACCOUNT"}, SA)
    updated = validate_success(res, 200)
    assert updated["payment_status"] == "AUTHORIZED"


# ─── corner: validations / error_fleet_credit_exceeded_triggered ───────────

def test_authorize_fleet_credit_exceeded(api):
    """PRD §3.8: "A fleet authorization is also held to the credit limit: the account's
    `reserved_credit_cents` plus this order's `total_cents` must be at most the account's
    `credit_limit_cents`, and an authorization that would exceed it is rejected with
    `ERR_FLEET_CREDIT_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/error_fleet_credit_exceeded_triggered
    """
    # discount_pct 0.0 + limit 5000; READY order total 7572 > 5000.
    s = setup_fleet_ready_order(credit_limit_cents=5000, discount_pct=0.0)
    wo = s["work_order"]
    assert wo["total_cents"] == 7572
    res = api.authorize_payment(wo["id"], {"payment_method": "FLEET_ACCOUNT"}, SA)
    validate_error(res, "ERR_FLEET_CREDIT_EXCEEDED", expected_status=402)


# ─── corner: validations / authorize_fleet_when_vehicle_has_no_account ─────

def test_authorize_fleet_for_retail_vehicle_rejected(api):
    """PRD §3.8: "When the method is `FLEET_ACCOUNT`, the vehicle must be bound to a fleet
    account — its `fleet_account_id` must be set, else `ERR_VEHICLE_HAS_NO_FLEET_ACCOUNT`".

    Design: Corner/validations/authorize_fleet_when_vehicle_has_no_account_rejected
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINVNA001", plate="VNA1",
                                make="Honda", model="Fit", odometer=1000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 1000)
    drive_to_ready(wo["id"], tech["id"])
    res = api.authorize_payment(wo["id"], {"payment_method": "FLEET_ACCOUNT"}, SA)
    validate_error(res, "ERR_VEHICLE_HAS_NO_FLEET_ACCOUNT", expected_status=404)


# ─── corner: state_machines / close_fleet_account_with_open_balance ────────

def test_close_fleet_account_with_open_balance_rejected(api):
    """PRD §3.11: "Closing an account moves it from `ACTIVE` or `SUSPENDED` to `CLOSED`,
    which is terminal; closure is permitted only when the account's `reserved_credit_cents`
    is zero, meaning no authorized or paid order is outstanding, and otherwise is rejected
    with `ERR_FLEET_HAS_OPEN_BALANCE`."

    Design: Corner/state_machines/close_fleet_account_with_open_balance_rejected
    """
    s = setup_fleet_ready_order(credit_limit_cents=100000, discount_pct=0.10)
    fleet, wo = s["fleet_account"], s["work_order"]
    authorize(wo["id"], "FLEET_ACCOUNT")  # reserved_credit now > 0
    res = api.close_fleet_account(fleet["id"], SM)
    validate_error(res, "ERR_FLEET_HAS_OPEN_BALANCE", expected_status=409)
    acct = get_success_data(api.get_fleet_account(fleet["id"], SM))
    assert acct["status"] == "ACTIVE"


# ─── corner: state_machines / fleet_suspend_reactivate_reprices_draft_orders ─

def test_suspend_zeroes_then_reactivate_restores_fleet_discount(api):
    """PRD §3.11: "Because a suspended account no longer grants its discount, every
    still-`DRAFT` work order belonging to a vehicle on that account that currently carries
    a non-zero fleet discount is re-priced with the fleet component now zero, recomputing
    all of that order's discount and total fields."
    PRD §3.11: "Reactivating moves the account from `SUSPENDED` back to `ACTIVE` — requiring
    it to be `SUSPENDED`, else `ERR_INVALID_STATE` — and re-prices those vehicles' draft
    work orders with the fleet discount restored."

    Design: Corner/state_machines/fleet_suspend_reactivate_reprices_draft_orders
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay = base["shop"], base["package"], base["bay"]
    fleet = create_fleet_account(shop["id"], company_name="Acme", discount_pct=0.10,
                                 credit_limit_cents=100000)
    veh = create_fleet_vehicle(shop["id"], fleet["id"], vin="VINSRP001", plate="SRP1",
                               make="Ford", model="F150", odometer=6000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 6000)
    # While ACTIVE: fleet 10% on 6995 -> discount 700, taxable 6295, tax 519, total 6814.
    assert wo["total_cents"] == 6814
    assert wo["fleet_discount_cents"] == 700

    get_success_data(api.suspend_fleet_account(fleet["id"], SM))
    suspended = get_success_data(api.get_work_order(wo["id"], SA))
    assert suspended["fleet_discount_cents"] == 0
    assert suspended["total_cents"] == 7572  # no discount: 6995 + round(6995*0.0825)=577

    get_success_data(api.reactivate_fleet_account(fleet["id"], SM))
    reactivated = get_success_data(api.get_work_order(wo["id"], SA))
    assert reactivated["fleet_discount_cents"] == 700
    assert reactivated["total_cents"] == 6814
