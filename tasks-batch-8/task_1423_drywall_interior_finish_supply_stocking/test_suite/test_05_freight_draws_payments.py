"""Freight tier math, dispatch-day fuel surcharge, automatic draw issuance,
credit-limit cascade, payment application, and draw listing (PRD §3.6–§3.8)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    assert_payment, assert_draw_balance_invariants,
    create_product, create_project, create_boom_truck,
    create_takeoff_with_lines, submit_takeoff, lock_takeoff, open_stocking,
    create_stocking_order_with_drops, schedule_order, dispatch_order,
    mark_order_stocked, set_logical_clock, get_account, get_draws_for_project,
    setup_scheduled_order_scenario, setup_stocked_order_scenario,
)
from test_helpers import api_client

CM = TEST_USERS["credit_manager_headers"]
EST = TEST_USERS["estimator_headers"]
DISP = TEST_USERS["dispatcher_headers"]
FORE = TEST_USERS["foreman_headers"]
AR = TEST_USERS["accounts_receivable_headers"]
WH = TEST_USERS["warehouse_manager_headers"]


# ─── Freight: provisional vs dispatch-day final variants ─────────────

def test_schedule_computes_provisional_freight_without_surcharge(api):
    """PRD §3.6: "Freight is tiered on the project's `distance_miles`: a
    distance of at most 25 miles is charged a flat 9,500 cents; beyond 25 miles
    and up to 75 miles the charge is a flat 19,500 cents plus 320 cents for
    each mile beyond the 25th; beyond 75 miles the charge is that same
    19,500-cent base plus 320 cents for each of the 50 miles from the 25th to
    the 75th, plus 480 cents for each mile beyond the 75th. The provisional
    figure applies no fuel surcharge."

    Distance 10 miles sits in the flat tier: 9500 cents.

    Design: Difficulty/dual_variant_calc/freight_provisional_vs_dispatch_final_differ
    """
    ctx = setup_scheduled_order_scenario(
        account_overrides={"company_name": "Bravo Builders"},
        project_overrides={"jobsite_name": "Tower B", "distance_miles": 10},
        bundle_count=3, sheet_count=50)
    assert ctx["order"]["status"] == "SCHEDULED"
    assert ctx["order"]["freight_charge_cents"] == 9500, (
        f"Provisional freight at 10 miles must be the flat 9500, "
        f"got {ctx['order']['freight_charge_cents']}")


def test_dispatch_requotes_freight_with_fuel_surcharge(api):
    """PRD §3.7: "Dispatch re-quotes the freight: the tiered charge from
    Section 3.6 is recomputed from the current `distance_miles`, and a fuel
    surcharge of 750 basis points — seven and a half percent — is applied on
    top, with the result rounded half up to whole cents."

    9500 * 1.075 = 10212.5 → round half up → 10213. The final figure differs
    from the provisional 9500.

    Design: Difficulty/dual_variant_calc/freight_provisional_vs_dispatch_final_differ
    """
    ctx = setup_scheduled_order_scenario(
        account_overrides={"company_name": "Bravo Builders 2"},
        project_overrides={"jobsite_name": "Tower B", "distance_miles": 10},
        bundle_count=3, sheet_count=50)
    provisional = ctx["order"]["freight_charge_cents"]

    set_logical_clock("2026-08-02T08:00:00Z")
    dispatched = dispatch_order(ctx["order"]["id"])
    assert dispatched["status"] == "DISPATCHED"
    final = dispatched["freight_charge_cents"]
    assert final == 10213, f"Dispatch-day freight must be 10213, got {final}"
    assert final != provisional


# ─── Freight tier boundary straddle ──────────────────────────────────

def _freight_for_distance(distance_miles):
    ctx = setup_scheduled_order_scenario(
        account_overrides={"company_name": "Tier Acct", "credit_limit_cents": 9000000},
        project_overrides={"distance_miles": distance_miles},
        truck_overrides={"truck_code": f"BT-{distance_miles}"})
    return ctx["order"]["freight_charge_cents"]


def test_freight_tier1_flat_and_tier2_per_mile(api):
    """PRD §3.6: "Freight is tiered on the project's `distance_miles`: a
    distance of at most 25 miles is charged a flat 9,500 cents; beyond 25 miles
    and up to 75 miles the charge is a flat 19,500 cents plus 320 cents for
    each mile beyond the 25th; beyond 75 miles the charge is that same
    19,500-cent base plus 320 cents for each of the 50 miles from the 25th to
    the 75th, plus 480 cents for each mile beyond the 75th. The provisional
    figure applies no fuel surcharge."

    25 miles → 9500 (top of tier 1); 50 miles → 19500 + 25*320 = 27500.

    Design: Difficulty/combinatorial_formula/freight_tier_straddles_tier2_boundary
    """
    f25 = _freight_for_distance(25)
    f50 = _freight_for_distance(50)
    assert f25 == 9500, f"25 miles must price at the flat tier-1 9500, got {f25}"
    assert f50 == 27500, f"50 miles must price at 19500 + 25*320 = 27500, got {f50}"
    assert f25 != f50


def test_freight_tier3_per_mile_beyond_75(api):
    """PRD §3.6: "Freight is tiered on the project's `distance_miles`: a
    distance of at most 25 miles is charged a flat 9,500 cents; beyond 25 miles
    and up to 75 miles the charge is a flat 19,500 cents plus 320 cents for
    each mile beyond the 25th; beyond 75 miles the charge is that same
    19,500-cent base plus 320 cents for each of the 50 miles from the 25th to
    the 75th, plus 480 cents for each mile beyond the 75th. The provisional
    figure applies no fuel surcharge."

    100 miles → 19500 + 50*320 + 25*480 = 47500 — distinct from both lower
    tiers.

    Design: Difficulty/combinatorial_formula/freight_tier_straddles_tier2_boundary
    """
    f25 = _freight_for_distance(25)
    f100 = _freight_for_distance(100)
    assert f100 == 47500, (
        f"100 miles must price at 19500 + 50*320 + 25*480 = 47500, got {f100}")
    assert f25 != f100


# ─── Mark-stocked cascade: draw issuance → AR → suspension ───────────

def _setup_tight_credit_stocked():
    """50-sheet line, 10% waste, price moved to 1700 pre-lock; 3-bundle drop;
    distance 10. Draw = 3*20*1700 material + 10213 freight = 112213 against a
    100000-cent credit limit."""
    return setup_stocked_order_scenario(
        account_overrides={"company_name": "Tight Credit Co",
                           "credit_limit_cents": 100000,
                           "default_waste_pct_bp": 1000},
        project_overrides={"distance_miles": 10},
        sheet_count=50, pre_lock_price=1700, bundle_count=3)


def test_mark_stocked_issues_draw_and_moves_ar(api):
    """PRD §3.7: "That confirmation automatically issues a draw request against
    the project for this order."
    PRD §3.7: "The draw's `requested_cents` is the sum of two parts: the
    material component, computed by taking the locked takeoff's lines that are
    still `ACTIVE`, keeping only those whose `product_id` actually appears
    among the distinct products in this order's drops, and summing their
    `final_line_cents`; plus the order's (final) `freight_charge_cents`."
    PRD §3.7: "The new draw starts in `ISSUED` with `paid_cents` at zero, and
    the account's `ar_outstanding_cents` increases by `requested_cents` at
    once."

    Design: Difficulty/transitive_cascade/mark_stocked_cascades_to_account_suspension
    """
    ctx = _setup_tight_credit_stocked()
    assert ctx["order"]["status"] == "STOCKED"

    draws = get_draws_for_project(ctx["project"]["id"])
    assert len(draws) == 1
    draw = draws[0]
    assert draw["status"] == "ISSUED"
    assert draw["paid_cents"] == 0
    assert draw["requested_cents"] == 112213, (
        f"Draw must be 102000 material + 10213 final freight = 112213, "
        f"got {draw['requested_cents']}")

    account = get_account(ctx["account"]["id"])
    assert account["ar_outstanding_cents"] == 112213


def test_mark_stocked_over_credit_limit_suspends_account(api):
    """PRD §3.7: "If `ar_outstanding_cents` exceeds `credit_limit_cents` after
    the draw lands, the account cascades into `SUSPENDED` immediately —
    blocking new takeoff submissions and new draws until the credit desk
    collects or raises the limit and reinstates it."

    Draw of 112213 against a 100000 limit pushes the account over.

    Design: Difficulty/transitive_cascade/mark_stocked_cascades_to_account_suspension
    """
    ctx = _setup_tight_credit_stocked()
    account = get_account(ctx["account"]["id"])
    assert account["status"] == "SUSPENDED", (
        f"Account must cascade to SUSPENDED when AR exceeds the credit limit, "
        f"got {account['status']}")
    assert account["ar_outstanding_cents"] == 112213


# ─── Payment application conserves the draw balance (PRD §3.8) ───────

def _setup_paid_scenario():
    """Same money as the cascade scenario but with ample credit: draw 112213."""
    return setup_stocked_order_scenario(
        account_overrides={"company_name": "Inv Co", "credit_limit_cents": 5000000,
                           "default_waste_pct_bp": 1000},
        project_overrides={"distance_miles": 10},
        sheet_count=50, pre_lock_price=1700, bundle_count=3)


def test_partial_payment_moves_draw_to_partially_paid_and_reduces_ar(api):
    """PRD §3.8: "A payment below the remaining balance moves an `ISSUED` draw
    to `PARTIALLY_PAID` (or leaves a `PARTIALLY_PAID` draw there) and adds to
    `paid_cents`; a payment exactly equal to the remaining balance moves the
    draw to terminal `PAID` and brings `paid_cents` up to `requested_cents`."
    PRD §3.8: "Either way the account's `ar_outstanding_cents` decreases by
    `amount_cents`."

    Design: Difficulty/compensating_invariant/payment_application_conserves_draw_balance
    """
    ctx = _setup_paid_scenario()
    draw = get_draws_for_project(ctx["project"]["id"])[0]
    assert draw["requested_cents"] == 112213

    res = api_client.apply_payment(
        draw["id"], {"amount_cents": 50000, "method": "ACH",
                     "received_at": "2026-08-03T00:00:00Z"}, AR)
    validate_success(res, 201)

    draw_after = get_success_data(api_client.get_draw_request(draw["id"], CM))
    assert draw_after["status"] == "PARTIALLY_PAID"
    assert draw_after["paid_cents"] == 50000
    assert_draw_balance_invariants(draw_after)
    assert get_account(ctx["account"]["id"])["ar_outstanding_cents"] == 62213


def test_final_payment_settles_draw_and_zeroes_ar(api):
    """PRD §3.8: "A payment below the remaining balance moves an `ISSUED` draw
    to `PARTIALLY_PAID` (or leaves a `PARTIALLY_PAID` draw there) and adds to
    `paid_cents`; a payment exactly equal to the remaining balance moves the
    draw to terminal `PAID` and brings `paid_cents` up to `requested_cents`."
    PRD §3.8: "Either way the account's `ar_outstanding_cents` decreases by
    `amount_cents`."

    Payments of 50000 then the exact remainder 62213 conserve the draw balance
    and drain AR to zero.

    Design: Difficulty/compensating_invariant/payment_application_conserves_draw_balance
    """
    ctx = _setup_paid_scenario()
    draw = get_draws_for_project(ctx["project"]["id"])[0]

    validate_success(api_client.apply_payment(
        draw["id"], {"amount_cents": 50000, "method": "ACH",
                     "received_at": "2026-08-03T00:00:00Z"}, AR), 201)
    validate_success(api_client.apply_payment(
        draw["id"], {"amount_cents": 62213, "method": "ACH",
                     "received_at": "2026-08-04T00:00:00Z"}, AR), 201)

    draw_after = get_success_data(api_client.get_draw_request(draw["id"], CM))
    assert draw_after["requested_cents"] == 112213
    assert draw_after["paid_cents"] == 112213
    assert draw_after["status"] == "PAID"
    assert_draw_balance_invariants(draw_after)
    assert get_account(ctx["account"]["id"])["ar_outstanding_cents"] == 0


def test_overpayment_rejected(api):
    """PRD §3.8: "The amount may never exceed the draw's remaining balance —
    `requested_cents` minus `paid_cents` — or the payment is rejected with
    `ERR_OVERPAYMENT`."

    The draw stands at 40213 (30000 material + 10213 final freight); 99999
    exceeds the remaining balance.

    Design: Corner/state_machines/precondition_enforcement_overpayment_rejected
    """
    ctx = setup_stocked_order_scenario(
        account_overrides={"company_name": "OP Co", "credit_limit_cents": 5000000},
        project_overrides={"distance_miles": 10})
    draw = get_draws_for_project(ctx["project"]["id"])[0]

    res = api_client.apply_payment(
        draw["id"], {"amount_cents": 99999, "method": "ACH",
                     "received_at": "2026-08-03T00:00:00Z"}, AR)
    validate_error(res, ApiErrorId.ERR_OVERPAYMENT)


# ─── Draw amount SKU filtering (PRD §3.7) ────────────────────────────

def test_draw_excludes_lines_not_stocked_in_order(api):
    """PRD §3.7: "The draw's `requested_cents` is the sum of two parts: the
    material component, computed by taking the locked takeoff's lines that are
    still `ACTIVE`, keeping only those whose `product_id` actually appears
    among the distinct products in this order's drops, and summing their
    `final_line_cents`; plus the order's (final) `freight_charge_cents`."

    The locked takeoff carries two 30000-cent lines (products A and B); the
    order drops only A, so the draw is 30000 + 10213 freight = 40213.

    Design: Corner/calculations/draw_amount_excludes_skus_not_stocked_in_order
    """
    set_logical_clock()
    account = get_success_data(api_client.create_contractor_account(
        {"company_name": "Filter Co", "credit_limit_cents": 5000000,
         "default_waste_pct_bp": 0}, CM))
    prod_a = create_product(sku="REG-A")
    prod_b = create_product(sku="REG-B", length_ft=10)
    project = create_project(account["id"], distance_miles=10)
    takeoff, _ = create_takeoff_with_lines(
        project["id"], [(prod_a["id"], 20), (prod_b["id"], 20)])
    submit_takeoff(takeoff["id"])
    lock_takeoff(takeoff["id"])
    open_stocking(project["id"])
    truck = create_boom_truck(truck_code="BT-01")
    order, _ = create_stocking_order_with_drops(
        project["id"], takeoff["id"], truck["id"], [(prod_a["id"], 1)])
    schedule_order(order["id"])
    set_logical_clock("2026-08-02T08:00:00Z")
    dispatch_order(order["id"])
    mark_order_stocked(order["id"])

    draws = get_draws_for_project(project["id"])
    assert len(draws) == 1
    assert draws[0]["requested_cents"] == 40213, (
        f"Draw must bill only the stocked SKU's 30000 plus 10213 freight, "
        f"got {draws[0]['requested_cents']}")


# ─── Draw list filtering by project (PRD §3.8) ───────────────────────

def _stock_one_order(account_id, product_id, jobsite, truck_code):
    project = create_project(account_id, jobsite_name=jobsite, distance_miles=10)
    takeoff, _ = create_takeoff_with_lines(project["id"], [(product_id, 20)])
    submit_takeoff(takeoff["id"])
    lock_takeoff(takeoff["id"])
    open_stocking(project["id"])
    truck = create_boom_truck(truck_code=truck_code)
    order, _ = create_stocking_order_with_drops(
        project["id"], takeoff["id"], truck["id"], [(product_id, 1)])
    schedule_order(order["id"])
    set_logical_clock("2026-08-02T08:00:00Z")
    dispatch_order(order["id"])
    mark_order_stocked(order["id"])
    return project


def test_draw_list_filtered_by_project(api):
    """PRD §3.8: "Payments on a draw can be listed for audit; the draw list
    itself is filterable by `project_id`, `status`, and `stocking_order_id`."

    Two projects each stock one order; the project_id filter must return only
    the matching draw.

    Design: Corner/endpoints/filtered_list_draw_requests_by_project
    """
    set_logical_clock()
    account = get_success_data(api_client.create_contractor_account(
        {"company_name": "FL Co", "credit_limit_cents": 9000000,
         "default_waste_pct_bp": 0}, CM))
    product = create_product()
    proj_a = _stock_one_order(account["id"], product["id"], "P-A", "BT-A")
    proj_b = _stock_one_order(account["id"], product["id"], "P-B", "BT-B")

    res = api_client.list_draw_requests(CM, params={"project_id": proj_a["id"]})
    data, _meta = validate_paginated(res)
    assert len(data) == 1, f"Expected exactly one draw for project A, got {len(data)}"
    assert all(d["project_id"] == proj_a["id"] for d in data)
    assert data[0]["project_id"] != proj_b["id"]


# ─── Payment immutability (PRD §2.4) ─────────────────────────────────

def test_payment_is_append_only_without_version(api):
    """PRD §2.4: "The exception is the `Payment` resource: payments are
    append-only ledger entries and carry only `id` and `created_at`; they have
    neither `updated_at` nor `version`, and no operation ever mutates a
    recorded payment."

    Design: Corner/entities/payment_immutable_no_version_field
    """
    ctx = setup_stocked_order_scenario(
        account_overrides={"company_name": "Imm Co", "credit_limit_cents": 5000000})
    draw = get_draws_for_project(ctx["project"]["id"])[0]

    res = api_client.apply_payment(
        draw["id"], {"amount_cents": 5000, "method": "ACH",
                     "received_at": "2026-08-03T00:00:00Z"}, AR)
    payment = validate_success(res, 201)
    assert_payment(payment)
