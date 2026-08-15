"""Shipping gates, rush-lane quote/settlement variants, the turnaround
boundary, and cancellation guards (PRD §3.4, §3.6, §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    assign_order,
    create_approved_recipe,
    create_customer,
    create_load,
    create_work_order,
    get_work_order,
    process_order_to_processed,
    record_inspection,
    release_load,
    set_clock,
    setup_shop,
    start_run,
    validate_error,
    validate_success,
)

CSR = TEST_USERS["customer_service_rep"]


# ---------------------------------------------------------------------------
# Corner: state_machines / ship_from_received_returns_not_shippable
# ---------------------------------------------------------------------------

def test_ship_from_received_returns_not_shippable(api):
    """PRD §3.8: "Shipping is performed by a `CustomerServiceRep` and is
    gated on quality: the order must be `PROCESSED` with `quality_status`
    either `PASSED` or `WAIVED`, failing otherwise with
    `ERR_WORK_ORDER_NOT_SHIPPABLE` (HTTP 409)."

    Design: Corner/state_machines/ship_from_received_returns_not_shippable
    """
    customer = create_customer(name="Ship Co")
    recipe = create_approved_recipe()
    order = create_work_order(customer["id"], recipe["id"])
    assert order["processing_status"] == "RECEIVED"

    res = api.ship_work_order(order["id"], CSR)
    validate_error(res, ApiErrorId.ERR_WORK_ORDER_NOT_SHIPPABLE.value)
    assert get_work_order(order["id"])["processing_status"] == "RECEIVED"


# ---------------------------------------------------------------------------
# Corner: state_machines / cancel_in_process_order_rejected
# ---------------------------------------------------------------------------

def test_cancel_in_process_order_rejected(api):
    """PRD §3.8: "Cancellation, likewise a `CustomerServiceRep` action, is
    possible only while the order is `RECEIVED` or `SCHEDULED`
    (`ERR_WORK_ORDER_NOT_CANCELLABLE`, HTTP 409) and lands in the terminal
    `CANCELLED` status."

    Design: Corner/state_machines/cancel_in_process_order_rejected
    """
    shop = setup_shop()
    order = create_work_order(shop["customer"]["id"], shop["recipe"]["id"])
    load = create_load(shop["furnace"]["id"], shop["recipe"]["id"])
    assign_order(load["id"], order["id"])
    release_load(load["id"])
    start_run(load["id"])
    assert get_work_order(order["id"])["processing_status"] == "IN_PROCESS"

    res = api.cancel_work_order(order["id"], CSR)
    validate_error(res, ApiErrorId.ERR_WORK_ORDER_NOT_CANCELLABLE.value)
    assert get_work_order(order["id"])["processing_status"] == "IN_PROCESS"


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / rush_surcharge_provisional_vs_final_on_breach
# ---------------------------------------------------------------------------

def _setup_shippable_rush_order(charge=100000, hours=48):
    """RUSH order processed and quality-PASSED, ready to ship. Returns the
    order as created (quote already settled at intake)."""
    bundle = process_order_to_processed(
        order_overrides={
            "service_lane": "RUSH",
            "guaranteed_turnaround_hours": hours,
            "processing_charge_cents": charge,
        }
    )
    passing = record_inspection(bundle["order"]["id"], readings=[40, 42, 41])
    assert passing["result"] == "PASS"
    return bundle


def test_rush_surcharge_provisional_vs_final_on_breach(api):
    """PRD §3.4: "The quote starts from a base of 15,000 cents plus 20 percent
    of the lot's `processing_charge_cents`, the percentage portion rounded
    half-up to whole cents before being added to the base. When the promised
    turnaround is 24 hours or less, this combined base is then multiplied by
    1.5 and again rounded half-up to whole cents. The quoted surcharge is that
    figure clamped to a floor of 25,000 cents and a ceiling of 200,000 cents."
    PRD §3.8: "`turnaround_breached` is `true` when `shipped_at` is strictly
    later than `promised_due_at` — shipping exactly at the promised instant
    meets the guarantee and is not a breach. Settlement follows immediately:
    `rush_surcharge_final_cents` becomes the previously quoted surcharge when
    the guarantee was met, and 0 when it was breached."

    Design: Difficulty/dual_variant_calc/rush_surcharge_provisional_vs_final_on_breach
    """
    bundle = _setup_shippable_rush_order(charge=100000, hours=48)
    order = bundle["order"]
    # Provisional variant at intake: 15000 + 0.20 x 100000 = 35000; 48h is
    # beyond the 24-hour expedite threshold, so no multiplier applies.
    assert order["rush_surcharge_quoted_cents"] == 35000
    assert_instant_equals(
        order["promised_due_at"], "2026-08-03T00:00:00Z", "promised_due_at"
    )
    assert order["turnaround_breached"] is False
    assert order["rush_surcharge_final_cents"] is None

    # Ship after the promised instant: the final variant settles to 0.
    set_clock("2026-08-04T00:00:00Z")
    shipped = validate_success(api.ship_work_order(order["id"], CSR), 200)
    assert shipped["processing_status"] == "SHIPPED"
    assert shipped["turnaround_breached"] is True, (
        "shipped 2026-08-04 strictly after promised 2026-08-03"
    )
    assert shipped["rush_surcharge_final_cents"] == 0, (
        "breached guarantee waives the final surcharge; provisional 35000 "
        f"diverges from final, got {shipped['rush_surcharge_final_cents']}"
    )
    assert shipped["rush_surcharge_quoted_cents"] == 35000


def test_rush_final_settles_quote_when_guarantee_met(api):
    """PRD §3.8: "Settlement follows immediately: `rush_surcharge_final_cents`
    becomes the previously quoted surcharge when the guarantee was met, and 0
    when it was breached. `STANDARD` lots always settle with
    `turnaround_breached` false and a final surcharge of 0."

    Design: Difficulty/dual_variant_calc/rush_surcharge_provisional_vs_final_on_breach
    """
    # Ship at the default clock 2026-08-01, ahead of the 2026-08-03 promise.
    bundle = _setup_shippable_rush_order(charge=100000, hours=48)
    shipped = validate_success(
        api.ship_work_order(bundle["order"]["id"], CSR), 200
    )
    assert shipped["turnaround_breached"] is False
    assert shipped["rush_surcharge_final_cents"] == 35000, (
        "met guarantee settles the final surcharge to the quoted 35000, got "
        f"{shipped['rush_surcharge_final_cents']}"
    )

    # STANDARD lane: no promise, no surcharge at intake or settlement. The
    # second shop needs a distinct (alloy_code, spec_code) pair and
    # furnace_code — PRD §3.2 rejects duplicate pairs and furnace codes.
    std = process_order_to_processed(
        recipe_overrides={"alloy_code": "8620"},
        furnace_overrides={"furnace_code": "F-2"},
    )
    record_inspection(std["order"]["id"], readings=[40, 42, 41])
    shipped_std = validate_success(
        api.ship_work_order(std["order"]["id"], CSR), 200
    )
    assert shipped_std["promised_due_at"] is None
    assert shipped_std["turnaround_breached"] is False
    assert shipped_std["rush_surcharge_quoted_cents"] == 0
    assert shipped_std["rush_surcharge_final_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: calculations / turnaround_exactly_at_due_not_breached
# ---------------------------------------------------------------------------

def test_turnaround_exactly_at_due_not_breached(api):
    """PRD §3.8: "`turnaround_breached` is `true` when `shipped_at` is
    strictly later than `promised_due_at` — shipping exactly at the promised
    instant meets the guarantee and is not a breach. Settlement follows
    immediately: `rush_surcharge_final_cents` becomes the previously quoted
    surcharge when the guarantee was met, and 0 when it was breached."

    Design: Corner/calculations/turnaround_exactly_at_due_not_breached
    """
    bundle = _setup_shippable_rush_order(charge=100000, hours=48)
    set_clock("2026-08-03T00:00:00Z")  # exactly promised_due_at
    shipped = validate_success(
        api.ship_work_order(bundle["order"]["id"], CSR), 200
    )
    assert_instant_equals(shipped["shipped_at"], "2026-08-03T00:00:00Z", "shipped_at")
    assert_instant_equals(
        shipped["promised_due_at"], "2026-08-03T00:00:00Z", "promised_due_at"
    )
    assert shipped["turnaround_breached"] is False, (
        "equality with promised_due_at is not a breach"
    )
    assert shipped["rush_surcharge_final_cents"] == 35000


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / rush_quote_nested_clamp_and_expedite_branch
# ---------------------------------------------------------------------------

def test_rush_quote_nested_clamp_and_expedite_branch(api):
    """PRD §3.4: "The quote starts from a base of 15,000 cents plus 20 percent
    of the lot's `processing_charge_cents`, the percentage portion rounded
    half-up to whole cents before being added to the base. When the promised
    turnaround is 24 hours or less, this combined base is then multiplied by
    1.5 and again rounded half-up to whole cents. The quoted surcharge is that
    figure clamped to a floor of 25,000 cents and a ceiling of 200,000 cents."

    Design: Difficulty/combinatorial_formula/rush_quote_nested_clamp_and_expedite_branch
    """
    customer = create_customer(name="Clamp Co")
    recipe = create_approved_recipe()

    plain = create_work_order(
        customer["id"], recipe["id"], service_lane="RUSH",
        guaranteed_turnaround_hours=48, processing_charge_cents=100000,
    )
    assert plain["rush_surcharge_quoted_cents"] == 35000, (
        "15000 + 20000 = 35000, inside [25000, 200000], no expedite; got "
        f"{plain['rush_surcharge_quoted_cents']}"
    )

    expedited = create_work_order(
        customer["id"], recipe["id"], service_lane="RUSH",
        guaranteed_turnaround_hours=24, processing_charge_cents=100000,
    )
    assert expedited["rush_surcharge_quoted_cents"] == 52500, (
        "24h hits the '24 hours or less' expedite branch: "
        "round_half_up(35000 x 1.5) = 52500; got "
        f"{expedited['rush_surcharge_quoted_cents']}"
    )

    floored = create_work_order(
        customer["id"], recipe["id"], service_lane="RUSH",
        guaranteed_turnaround_hours=72, processing_charge_cents=10000,
    )
    assert floored["rush_surcharge_quoted_cents"] == 25000, (
        "15000 + 2000 = 17000 clamps up to the 25000 floor; got "
        f"{floored['rush_surcharge_quoted_cents']}"
    )


def test_rush_quote_ceiling_clamp_and_expedite_boundary(api):
    """PRD §3.4: "The quote starts from a base of 15,000 cents plus 20 percent
    of the lot's `processing_charge_cents`, the percentage portion rounded
    half-up to whole cents before being added to the base. When the promised
    turnaround is 24 hours or less, this combined base is then multiplied by
    1.5 and again rounded half-up to whole cents. The quoted surcharge is that
    figure clamped to a floor of 25,000 cents and a ceiling of 200,000 cents."

    Design: Difficulty/combinatorial_formula/rush_quote_nested_clamp_and_expedite_branch
    """
    customer = create_customer(name="Cap Co")
    recipe = create_approved_recipe()

    capped = create_work_order(
        customer["id"], recipe["id"], service_lane="RUSH",
        guaranteed_turnaround_hours=48, processing_charge_cents=2000000,
    )
    assert capped["rush_surcharge_quoted_cents"] == 200000, (
        "15000 + 400000 = 415000 clamps down to the 200000 ceiling; got "
        f"{capped['rush_surcharge_quoted_cents']}"
    )

    # 25 hours is beyond the "24 hours or less" expedite threshold.
    no_expedite = create_work_order(
        customer["id"], recipe["id"], service_lane="RUSH",
        guaranteed_turnaround_hours=25, processing_charge_cents=100000,
    )
    assert no_expedite["rush_surcharge_quoted_cents"] == 35000, (
        "25h does not trigger the expedite multiplier; got "
        f"{no_expedite['rush_surcharge_quoted_cents']}"
    )
