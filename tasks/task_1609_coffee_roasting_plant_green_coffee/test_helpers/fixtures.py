"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

All roles are opaque in this PRD — X-User-ID is never compared against any
entity id — so fixtures use the shared TEST_USERS constants, except where a
test needs to thread a specific user id (e.g., segregation-of-duties).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK_ISO,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)
from .factories import (
    add_recipe_component_payload,
    approve_recipe_payload,
    create_contract_payload,
    create_counterparty_payload,
    create_cupping_session_payload,
    create_financing_line_payload,
    create_financing_reserve_payload,
    create_fulfillment_order_payload,
    add_fulfillment_line_payload,
    create_futures_hedge_payload,
    create_price_fix_payload,
    create_product_payload,
    create_roast_batch_payload,
    create_roast_profile_payload,
    create_shipment_payload,
    finish_roast_batch_payload,
    pack_roast_batch_payload,
    receive_shipment_payload,
    resolve_dispute_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
TRADER = TEST_USERS["trader_headers"]
RISK = TEST_USERS["risk_manager_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]
HEAD_ROASTER = TEST_USERS["head_roaster_headers"]
ROAST_OP = TEST_USERS["roast_operator_headers"]
QA = TEST_USERS["qa_grader_headers"]
PLANNER = TEST_USERS["fulfillment_planner_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK_ISO):
    """Drive the server logical clock. Default startup is 2026-08-01T00:00:00Z."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_counterparty(ref="SUP-TEST", legal_name="Test Supplier Co",
                         kind="SUPPLIER", credit_limit_usd=1000000):
    """Create a counterparty. Returns the counterparty."""
    payload = create_counterparty_payload(
        counterparty_ref=ref, legal_name=legal_name, counterparty_kind=kind,
        credit_limit_usd=credit_limit_usd,
    )
    return get_success_data(api_client.create_counterparty(payload, TRADER))


def create_customer(ref="CUST-TEST", legal_name="Test Customer Co",
                     credit_limit_usd=100000):
    """Create a CUSTOMER counterparty."""
    return create_counterparty(ref=ref, legal_name=legal_name,
                                kind="CUSTOMER", credit_limit_usd=credit_limit_usd)


def create_ptbf_contract(counterparty_id, contract_ref="C-PTBF",
                          total_lbs=10000, differential=0.25,
                          coffee_grade="SHB",
                          window_start=DEFAULT_WINDOW_START,
                          window_end=DEFAULT_WINDOW_END):
    """Create a DIFFERENTIAL_PTBF contract."""
    payload = create_contract_payload(
        contract_ref=contract_ref, pricing_mode="DIFFERENTIAL_PTBF",
        coffee_grade=coffee_grade, total_lbs=total_lbs,
        differential_usd_per_lb=differential,
        delivery_window_start=window_start, delivery_window_end=window_end,
    )
    # Explicitly drop the outright-only field so a fresh PTBF payload is clean.
    payload.pop("fixed_price_usd_per_lb", None)
    return get_success_data(
        api_client.create_contract(counterparty_id, payload, TRADER))


def create_fixed_contract(counterparty_id, contract_ref="C-FO",
                           total_lbs=5000, fixed_price=2.00,
                           coffee_grade="SHB",
                           window_start=DEFAULT_WINDOW_START,
                           window_end=DEFAULT_WINDOW_END):
    """Create a FIXED_OUTRIGHT contract."""
    payload = create_contract_payload(
        contract_ref=contract_ref, pricing_mode="FIXED_OUTRIGHT",
        coffee_grade=coffee_grade, total_lbs=total_lbs,
        fixed_price_usd_per_lb=fixed_price,
        delivery_window_start=window_start, delivery_window_end=window_end,
    )
    payload.pop("differential_usd_per_lb", None)
    return get_success_data(
        api_client.create_contract(counterparty_id, payload, TRADER))


def get_contract(contract_id):
    return get_success_data(api_client.get_contract(contract_id, TRADER))


def record_price_fix(contract_id, fix_lbs, futures_price, expected_version):
    """POST a price-fix and return the recorded PriceFixEvent."""
    payload = create_price_fix_payload(fix_lbs, futures_price, expected_version)
    return get_success_data(
        api_client.create_price_fix(contract_id, payload, TRADER))


# ---------------------------------------------------------------------------
# Tier 2: shipments (book -> depart -> arrive -> receive)
# ---------------------------------------------------------------------------

def book_shipment(contract_id, shipment_ref="SH-1", planned_lbs=1000,
                   scheduled_arrival="2026-09-01T00:00:00Z"):
    payload = create_shipment_payload(
        shipment_ref=shipment_ref, planned_lbs=planned_lbs,
        scheduled_arrival=scheduled_arrival,
    )
    return get_success_data(
        api_client.create_shipment(contract_id, payload, LOGISTICS))


def mark_in_transit(shipment_id):
    return get_success_data(api_client.depart_shipment(shipment_id, LOGISTICS))


def mark_arrived(shipment_id):
    return get_success_data(api_client.arrive_shipment(shipment_id, LOGISTICS))


def receive_shipment(shipment_id, received_lbs, lot_code="L-1",
                      moisture_pct=11.0, warehouse_location="WH-A"):
    payload = receive_shipment_payload(
        received_lbs=received_lbs, lot_code=lot_code,
        moisture_pct=moisture_pct, warehouse_location=warehouse_location,
    )
    return get_success_data(
        api_client.receive_shipment(shipment_id, payload, WAREHOUSE))


def walk_shipment_to_arrived(shipment_id):
    mark_in_transit(shipment_id)
    return mark_arrived(shipment_id)


def receive_shipment_full(shipment_id, received_lbs, lot_code="L-1"):
    """ARRIVED -> RECEIVED; returns the updated shipment dict."""
    return receive_shipment(shipment_id, received_lbs, lot_code=lot_code)


def list_green_lots_by_shipment(shipment_id):
    data, _meta = validate_paginated(
        api_client.list_green_lots(WAREHOUSE, params={"shipment_id": shipment_id}))
    return data


def get_lot_for_shipment(shipment_id):
    """Each shipment produces exactly one GreenLot at receive."""
    lots = list_green_lots_by_shipment(shipment_id)
    assert len(lots) == 1, f"expected exactly one lot for shipment, got {len(lots)}"
    return lots[0]


# ---------------------------------------------------------------------------
# Tier 3: cupping
# ---------------------------------------------------------------------------

def open_cupping_session(subject_kind, subject_id, panelist_count=3,
                          score_aroma=8.5, score_flavor=8.5,
                          score_aftertaste=8.5, score_acidity=8.5,
                          score_body=8.5, score_balance=8.5,
                          score_uniformity=10.0, score_clean_cup=10.0,
                          score_sweetness=10.0, score_overall=8.5,
                          defects_subtracted=0, qa_headers=QA):
    payload = create_cupping_session_payload(
        subject_kind, subject_id, panelist_count,
        score_aroma=score_aroma, score_flavor=score_flavor,
        score_aftertaste=score_aftertaste, score_acidity=score_acidity,
        score_body=score_body, score_balance=score_balance,
        score_uniformity=score_uniformity, score_clean_cup=score_clean_cup,
        score_sweetness=score_sweetness, score_overall=score_overall,
        defects_subtracted=defects_subtracted,
    )
    return get_success_data(api_client.create_cupping_session(payload, qa_headers))


def finalize_cupping_session(session_id, qa_headers=QA):
    return get_success_data(
        api_client.finalize_cupping_session(session_id, qa_headers))


def open_and_finalize_cupping(subject_kind, subject_id, qa_headers=QA,
                               **session_kwargs):
    """Create + finalize in one shot; returns the finalized session."""
    sess = open_cupping_session(subject_kind, subject_id,
                                 qa_headers=qa_headers, **session_kwargs)
    return finalize_cupping_session(sess["id"], qa_headers=qa_headers)


def cup_lot_pass(shipment_id, qa_headers=QA):
    """Run a passing cupping on a green-lot shipment. Returns finalized session."""
    return open_and_finalize_cupping("GREEN_LOT", shipment_id,
                                      qa_headers=qa_headers)


def cup_lot_fail(shipment_id, qa_headers=QA):
    """Run a failing cupping on a green-lot shipment."""
    return open_and_finalize_cupping(
        "GREEN_LOT", shipment_id, qa_headers=qa_headers,
        score_aroma=6.0, score_flavor=6.0, score_aftertaste=6.0,
        score_acidity=6.0, score_body=6.0, score_balance=6.0,
        score_uniformity=10.0, score_clean_cup=10.0, score_sweetness=10.0,
        score_overall=6.0, defects_subtracted=6,
    )


def cup_batch_pass(batch_id, qa_headers=QA):
    """Run a passing cupping on a roast batch (78.00 threshold)."""
    return open_and_finalize_cupping(
        "ROAST_BATCH", batch_id, qa_headers=qa_headers,
        score_aroma=8.0, score_flavor=8.0, score_aftertaste=8.0,
        score_acidity=8.0, score_body=8.0, score_balance=8.0,
        score_uniformity=10.0, score_clean_cup=10.0, score_sweetness=10.0,
        score_overall=8.0, defects_subtracted=0,
    )


# ---------------------------------------------------------------------------
# Tier 4: production (profile -> product -> recipe -> components -> approve)
# ---------------------------------------------------------------------------

def create_roast_profile(profile_code="RP-STD", charge_temp_c=200,
                          target_drop_temp_c=210, expected_yield_loss_pct=0.16,
                          shrinkage_alert_band_pct=0.02):
    payload = create_roast_profile_payload(
        profile_code=profile_code, charge_temp_c=charge_temp_c,
        target_drop_temp_c=target_drop_temp_c,
        expected_yield_loss_pct=expected_yield_loss_pct,
        shrinkage_alert_band_pct=shrinkage_alert_band_pct,
    )
    return get_success_data(api_client.create_roast_profile(payload, HEAD_ROASTER))


def create_product(profile_id, sku="P-TEST", display_name="Test Product",
                    channel="WHOLESALE", freshness_days=30):
    payload = create_product_payload(
        profile_id, sku=sku, display_name=display_name, channel=channel,
        freshness_days=freshness_days,
    )
    return get_success_data(api_client.create_product(payload, HEAD_ROASTER))


def create_draft_recipe(product_id):
    return get_success_data(api_client.create_recipe(product_id, HEAD_ROASTER))


def add_component(recipe_id, required_grade="SHB", component_pct=1.0,
                   substitution_grade=None, substitution_max_pct=None):
    payload = add_recipe_component_payload(
        required_grade=required_grade, component_pct=component_pct,
    )
    if substitution_grade is not None:
        payload["substitution_grade"] = substitution_grade
    if substitution_max_pct is not None:
        payload["substitution_max_pct"] = substitution_max_pct
    return get_success_data(
        api_client.add_recipe_component(recipe_id, payload, HEAD_ROASTER))


def approve_recipe(recipe_id, expected_product_version):
    payload = approve_recipe_payload(expected_product_version)
    return get_success_data(
        api_client.approve_recipe(recipe_id, payload, HEAD_ROASTER))


def create_product_with_recipe(profile_id=None, sku="P-TEST",
                                freshness_days=30,
                                components=None):
    """Product + one APPROVED recipe.

    components: list of dicts with required_grade / component_pct /
    optional substitution_grade / substitution_max_pct. If None, a single
    1.0 SHB component is used.

    Returns (product, recipe).
    """
    if profile_id is None:
        profile = create_roast_profile(profile_code=f"RP-{sku}")
        profile_id = profile["id"]
    product = create_product(profile_id, sku=sku, freshness_days=freshness_days)
    recipe = create_draft_recipe(product["id"])
    if components is None:
        components = [{"required_grade": "SHB", "component_pct": 1.0}]
    for comp in components:
        add_component(recipe["id"], **comp)
    recipe = approve_recipe(recipe["id"], product["version"])
    return product, recipe


# ---------------------------------------------------------------------------
# Tier 5: roast batches
# ---------------------------------------------------------------------------

def create_batch(product_id, recipe_id, scheduled_green_lbs, headers=ROAST_OP):
    payload = create_roast_batch_payload(product_id, recipe_id,
                                          scheduled_green_lbs)
    return get_success_data(api_client.create_roast_batch(payload, headers))


def start_batch(batch_id, headers=ROAST_OP):
    return get_success_data(api_client.start_roast_batch(batch_id, headers))


def finish_batch(batch_id, actual_roasted_lbs, headers=ROAST_OP):
    payload = finish_roast_batch_payload(actual_roasted_lbs)
    return get_success_data(api_client.finish_roast_batch(batch_id, payload,
                                                           headers))


def pack_batch(batch_id, packed_lbs, headers=ROAST_OP):
    payload = pack_roast_batch_payload(packed_lbs)
    return get_success_data(api_client.pack_roast_batch(batch_id, payload,
                                                         headers))


def void_batch(batch_id, headers=ROAST_OP):
    return get_success_data(api_client.void_roast_batch(batch_id, headers))


# ---------------------------------------------------------------------------
# Tier 6: financing lines and reserves
# ---------------------------------------------------------------------------

def create_financing_line(lender_name="Bank", facility_limit_usd=100000,
                           advance_rate_pct=0.50):
    payload = create_financing_line_payload(
        lender_name=lender_name, facility_limit_usd=facility_limit_usd,
        advance_rate_pct=advance_rate_pct,
    )
    return get_success_data(api_client.create_financing_line(payload, RISK))


def pledge_reserve(line_id, green_lot_id, reserved_lbs):
    payload = create_financing_reserve_payload(green_lot_id, reserved_lbs)
    return get_success_data(
        api_client.create_financing_reserve(line_id, payload, RISK))


def release_reserve(reserve_id):
    return get_success_data(api_client.release_financing_reserve(reserve_id, RISK))


# ---------------------------------------------------------------------------
# Tier 7: futures hedges
# ---------------------------------------------------------------------------

def create_hedge(contract_id, hedge_side="BUY_FUTURES", hedge_lbs=1000,
                  entry_price=1.80, trader_headers=TRADER):
    payload = create_futures_hedge_payload(
        hedge_side=hedge_side, hedge_lbs=hedge_lbs,
        entry_price_usd_per_lb=entry_price,
    )
    return get_success_data(
        api_client.create_futures_hedge(contract_id, payload, trader_headers))


def approve_hedge(hedge_id, risk_headers=RISK):
    return get_success_data(api_client.approve_futures_hedge(hedge_id,
                                                              risk_headers))


def lift_hedge(hedge_id, exit_price, trader_headers=TRADER):
    payload = {"exit_price_usd_per_lb": exit_price}
    return get_success_data(api_client.lift_futures_hedge(hedge_id, payload,
                                                           trader_headers))


# ---------------------------------------------------------------------------
# Tier 8: composite — full "received + cupped + released" green lot
# ---------------------------------------------------------------------------

def setup_released_lot(supplier_ref="SUP-RL", contract_ref="C-RL",
                        shipment_ref="SH-RL", lot_code="L-RL",
                        received_lbs=5000, fixed_price=2.00,
                        coffee_grade="SHB"):
    """Create a FIXED_OUTRIGHT contract, ship + receive + cup PASS.

    Returns dict with supplier, contract, shipment, green_lot.
    The green lot is in RELEASED status with cup_score set.
    """
    supplier = create_counterparty(ref=supplier_ref)
    contract = create_fixed_contract(
        supplier["id"], contract_ref=contract_ref, total_lbs=received_lbs,
        fixed_price=fixed_price, coffee_grade=coffee_grade,
    )
    shipment = book_shipment(contract["id"], shipment_ref=shipment_ref,
                              planned_lbs=received_lbs)
    walk_shipment_to_arrived(shipment["id"])
    receive_shipment(shipment["id"], received_lbs, lot_code=lot_code)
    cup_lot_pass(shipment["id"])
    green_lot = get_lot_for_shipment(shipment["id"])
    return {
        "supplier": supplier,
        "contract": contract,
        "shipment": shipment,
        "green_lot": green_lot,
    }


def setup_released_lot_with_grade(coffee_grade, ref_suffix, received_lbs=5000,
                                   fixed_price=2.00):
    """Variant of setup_released_lot keyed by coffee grade."""
    return setup_released_lot(
        supplier_ref=f"SUP-{ref_suffix}", contract_ref=f"C-{ref_suffix}",
        shipment_ref=f"SH-{ref_suffix}", lot_code=f"L-{ref_suffix}",
        received_lbs=received_lbs, fixed_price=fixed_price,
        coffee_grade=coffee_grade,
    )


# ---------------------------------------------------------------------------
# Tier 9: composite — roasted batch ready to pack (or already packed)
# ---------------------------------------------------------------------------

def setup_roasted_batch(supplier_ref="SUP-RB", product_sku="P-RB",
                         scheduled_green_lbs=100, actual_roasted_lbs=84,
                         freshness_days=30,
                         lot_received_lbs=5000):
    """Full pipeline: supplier -> contract -> shipment -> receive -> cup PASS
    -> profile/product/recipe APPROVED -> batch created/started/finished.

    Returns dict with keys: supplier, contract, shipment, green_lot, profile,
    product, recipe, batch.
    """
    ctx = setup_released_lot(
        supplier_ref=supplier_ref, contract_ref=f"C-{supplier_ref}",
        shipment_ref=f"SH-{supplier_ref}", lot_code=f"L-{supplier_ref}",
        received_lbs=lot_received_lbs,
    )
    profile = create_roast_profile(profile_code=f"RP-{product_sku}")
    product = create_product(profile["id"], sku=product_sku,
                              freshness_days=freshness_days)
    recipe = create_draft_recipe(product["id"])
    add_component(recipe["id"], required_grade="SHB", component_pct=1.0)
    recipe = approve_recipe(recipe["id"], product["version"])
    batch = create_batch(product["id"], recipe["id"], scheduled_green_lbs)
    batch = start_batch(batch["id"])
    batch = finish_batch(batch["id"], actual_roasted_lbs)
    ctx.update({
        "profile": profile,
        "product": product,
        "recipe": recipe,
        "batch": batch,
    })
    return ctx


def setup_packed_batch(supplier_ref="SUP-PB", product_sku="P-PB",
                        scheduled_green_lbs=100, actual_roasted_lbs=84,
                        packed_lbs=84, freshness_days=30,
                        lot_received_lbs=5000):
    """Same as setup_roasted_batch plus QC PASS on batch and pack.

    Returns dict including the finished goods lot as "fg_lot".
    """
    ctx = setup_roasted_batch(
        supplier_ref=supplier_ref, product_sku=product_sku,
        scheduled_green_lbs=scheduled_green_lbs,
        actual_roasted_lbs=actual_roasted_lbs,
        freshness_days=freshness_days, lot_received_lbs=lot_received_lbs,
    )
    cup_batch_pass(ctx["batch"]["id"])
    fg = pack_batch(ctx["batch"]["id"], packed_lbs)
    ctx["fg_lot"] = fg
    return ctx


# ---------------------------------------------------------------------------
# Tier 10: fulfillment orders
# ---------------------------------------------------------------------------

def create_fulfillment_order(customer_id, channel="WHOLESALE",
                              requested_ship_date="2026-08-15T00:00:00Z"):
    payload = create_fulfillment_order_payload(
        customer_id, channel=channel,
        requested_ship_date=requested_ship_date,
    )
    return get_success_data(api_client.create_fulfillment_order(payload, PLANNER))


def add_order_line(order_id, finished_goods_lot_id, allocated_lbs):
    payload = add_fulfillment_line_payload(finished_goods_lot_id, allocated_lbs)
    return get_success_data(
        api_client.add_fulfillment_line(order_id, payload, PLANNER))


def reserve_order(order_id):
    return get_success_data(api_client.reserve_fulfillment_order(order_id,
                                                                  PLANNER))
