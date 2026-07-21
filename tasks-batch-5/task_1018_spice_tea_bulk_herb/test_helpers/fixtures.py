"""Composite setup helpers.

Every helper builds its preconditions from scratch (the server database is empty
before every test) and uses the lenient get_success_data validator so setup
failures surface as clear "Setup failed" errors.

Setup calls act as PlatformAdmin, which the PRD authorizes as a hierarchical
override of every peer role — this keeps composite setup free of ownership
plumbing. Tests that must exercise a specific role or ownership drive the
trigger call themselves with the appropriate headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------
# Low-level create helpers (each returns the created resource's data dict)
# --------------------------------------------------------------------------
def clock_set(api, iso, headers=ADMIN):
    return get_success_data(api.set_clock({"to_iso8601": iso}, headers))


def new_product(api, *, name="Chamomile", category="HERB", kind="SIMPLE",
                unit_price_cents_per_gram=2.5, tare_default_grams=8,
                allergen_tags=None, shelf_life_days=None, headers=ADMIN):
    payload = {
        "name": name,
        "category": category,
        "kind": kind,
        "unit_price_cents_per_gram": unit_price_cents_per_gram,
        "tare_default_grams": tare_default_grams,
        "allergen_tags": [] if allergen_tags is None else allergen_tags,
    }
    if shelf_life_days is not None:
        payload["shelf_life_days"] = shelf_life_days
    return get_success_data(api.create_product(payload, headers))


def new_blend_component(api, blend_id, component_id, weight_ratio_bps, headers=ADMIN):
    payload = {
        "blend_product_id": blend_id,
        "component_product_id": component_id,
        "weight_ratio_bps": weight_ratio_bps,
    }
    return get_success_data(api.create_blend_component(payload, headers))


def new_lot(api, product_id, *, lot_code="LOT-1", grams_received=500,
            received_at="2026-06-01T00:00:00Z", best_by="2026-12-01T00:00:00Z",
            headers=ADMIN):
    payload = {
        "product_id": product_id,
        "lot_code": lot_code,
        "grams_received": grams_received,
        "received_at": received_at,
        "best_by": best_by,
    }
    return get_success_data(api.create_inventory_lot(payload, headers))


def new_production_line(api, *, name="Line 1", headers=ADMIN):
    return get_success_data(api.create_production_line({"name": name}, headers))


def new_batch(api, blend_id, line_id, *, target_output_grams=100,
              scheduled_start="2026-07-10T08:00:00Z",
              scheduled_end="2026-07-10T10:00:00Z", headers=ADMIN):
    payload = {
        "blend_product_id": blend_id,
        "production_line_id": line_id,
        "target_output_grams": target_output_grams,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    return get_success_data(api.create_batch(payload, headers))


def new_labeling_station(api, *, name="Station A", headers=ADMIN):
    return get_success_data(api.create_labeling_station({"name": name}, headers))


def new_tin_run(api, station_id, product_ids, *,
                scheduled_start="2026-07-10T08:00:00Z",
                scheduled_end="2026-07-10T09:00:00Z", headers=ADMIN):
    payload = {
        "labeling_station_id": station_id,
        "product_ids": product_ids,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    return get_success_data(api.create_tin_run(payload, headers))


def new_account(api, *, business_name="Acme Co", credit_limit_cents=100000,
                tier=None, headers=ADMIN):
    payload = {"business_name": business_name, "credit_limit_cents": credit_limit_cents}
    if tier is not None:
        payload["tier"] = tier
    return get_success_data(api.create_wholesale_account(payload, headers))


def new_order(api, account_id, *, allergen_ack=None, headers=ADMIN):
    payload = {"wholesale_account_id": account_id}
    if allergen_ack is not None:
        payload["allergen_ack"] = allergen_ack
    return get_success_data(api.create_order(payload, headers))


def new_line(api, order_id, product_id, requested_grams, headers=ADMIN):
    payload = {"product_id": product_id, "requested_grams": requested_grams}
    return get_success_data(api.add_order_line(order_id, payload, headers))


def account_version(api, account_id, headers=ADMIN):
    return get_success_data(api.get_wholesale_account(account_id, headers))["version"]


def do_price(api, order_id, headers=ADMIN):
    return get_success_data(api.price_order(order_id, headers))


def do_confirm(api, order_id, account_id, expected_version=None, headers=ADMIN):
    if expected_version is None:
        expected_version = account_version(api, account_id, headers)
    payload = {"expected_wholesale_account_version": expected_version}
    return get_success_data(api.confirm_order(order_id, payload, headers))


def do_pack(api, order_id, measurements, headers=ADMIN):
    return get_success_data(api.pack_order(order_id, {"line_measurements": measurements}, headers))


# --------------------------------------------------------------------------
# Composite fixtures
# --------------------------------------------------------------------------
def setup_confirmed_order(api, *, name="Chamomile", category="HERB",
                          unit_price_cents_per_gram=2.5, tare_default_grams=8,
                          allergen_tags=None, requested_grams=100,
                          credit_limit_cents=100000, allergen_ack=False,
                          clock="2026-06-15T00:00:00Z",
                          with_lot=True, lot_grams=500,
                          lot_received_at="2026-06-01T00:00:00Z",
                          lot_best_by="2026-12-01T00:00:00Z"):
    """Product (+optional lot) + account + order with one line, priced and confirmed.

    Returns a context dict: product, lot, account, order (post-confirm), line.
    Tests drive the next transition (pack / cancel) themselves.
    """
    if clock is not None:
        clock_set(api, clock)
    product = new_product(
        api, name=name, category=category, unit_price_cents_per_gram=unit_price_cents_per_gram,
        tare_default_grams=tare_default_grams, allergen_tags=allergen_tags,
    )
    lot = None
    if with_lot:
        lot = new_lot(api, product["id"], grams_received=lot_grams,
                      received_at=lot_received_at, best_by=lot_best_by)
    account = new_account(api, credit_limit_cents=credit_limit_cents)
    order = new_order(api, account["id"], allergen_ack=allergen_ack)
    line = new_line(api, order["id"], product["id"], requested_grams)
    do_price(api, order["id"])
    do_confirm(api, order["id"], account["id"])
    order = get_success_data(api.get_order(order["id"], ADMIN))
    line = get_success_data(api.get_order_line(line["id"], ADMIN))
    return {"product": product, "lot": lot, "account": account, "order": order, "line": line}


def setup_packed_order(api, *, gross_grams=121, tare_grams=10, requested_grams=100,
                       lot_grams=500, allergen_ack=False, allergen_tags=None,
                       unit_price_cents_per_gram=2.5,
                       clock="2026-06-15T00:00:00Z"):
    """A confirmed order that is then packed, drawing (gross-tare) grams from its lot.

    Returns the same context dict as setup_confirmed_order with order in PACKED state.
    """
    ctx = setup_confirmed_order(
        api, with_lot=True, requested_grams=requested_grams, lot_grams=lot_grams,
        allergen_ack=allergen_ack, allergen_tags=allergen_tags,
        unit_price_cents_per_gram=unit_price_cents_per_gram, clock=clock,
    )
    measurements = [{"line_id": ctx["line"]["id"], "gross_grams": gross_grams,
                     "tare_grams": tare_grams}]
    do_pack(api, ctx["order"]["id"], measurements)
    ctx["order"] = get_success_data(api.get_order(ctx["order"]["id"], ADMIN))
    ctx["line"] = get_success_data(api.get_order_line(ctx["line"]["id"], ADMIN))
    if ctx["lot"] is not None:
        ctx["lot"] = get_success_data(api.get_inventory_lot(ctx["lot"]["id"], ADMIN))
    return ctx


def setup_priced_order(api, *, unit_price_cents_per_gram=2.5, requested_grams=100,
                       credit_limit_cents=100000, allergen_ack=None,
                       category="HERB", name="Chamomile"):
    """Account + order with one line, priced (DRAFT -> PRICED), not confirmed.

    Returns: product, account, order (PRICED), line.
    """
    product = new_product(api, name=name, category=category,
                          unit_price_cents_per_gram=unit_price_cents_per_gram)
    account = new_account(api, credit_limit_cents=credit_limit_cents)
    order = new_order(api, account["id"], allergen_ack=allergen_ack)
    line = new_line(api, order["id"], product["id"], requested_grams)
    do_price(api, order["id"])
    order = get_success_data(api.get_order(order["id"], ADMIN))
    return {"product": product, "account": account, "order": order, "line": line}


def setup_two_orders_committed_and_priced(api):
    """One account with order A confirmed (provisional 250) and order B only priced
    (provisional 700). Used to distinguish committed vs projected exposure.

    Returns: account, order_a, order_b.
    """
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    ceylon = new_product(api, name="Ceylon Cinnamon", category="SPICE",
                         unit_price_cents_per_gram=3.5, tare_default_grams=10)
    account = new_account(api, credit_limit_cents=100000)
    order_a = new_order(api, account["id"])
    new_line(api, order_a["id"], cham["id"], 100)
    do_price(api, order_a["id"])
    do_confirm(api, order_a["id"], account["id"])
    order_b = new_order(api, account["id"])
    new_line(api, order_b["id"], ceylon["id"], 200)
    do_price(api, order_b["id"])
    return {"account": account, "order_a": order_a, "order_b": order_b,
            "cham": cham, "ceylon": ceylon}


def setup_blend_ready_to_produce(api, *, bt_ratio=7000, sa_ratio=3000,
                                 bt_lot_grams=200, sa_lot_grams=30,
                                 target_output_grams=100,
                                 clock="2026-06-15T00:00:00Z"):
    """Almond Chai blend = Black Tea + Sweet Almond with the given ratios and lots,
    plus a PLANNED batch targeting target_output_grams. Both components are stocked.

    Returns: bt, sa, chai, bt_lot, sa_lot, line, batch.
    """
    if clock is not None:
        clock_set(api, clock)
    bt = new_product(api, name="Black Tea Base", category="TEA",
                     unit_price_cents_per_gram=4.0, tare_default_grams=5)
    sa = new_product(api, name="Sweet Almond Bits", category="HERB",
                     unit_price_cents_per_gram=5.0, tare_default_grams=5,
                     allergen_tags=["TREE_NUTS"])
    chai = new_product(api, name="Almond Chai Blend", category="TEA", kind="BLEND",
                       unit_price_cents_per_gram=7.2, tare_default_grams=5)
    new_blend_component(api, chai["id"], bt["id"], bt_ratio)
    new_blend_component(api, chai["id"], sa["id"], sa_ratio)
    bt_lot = new_lot(api, bt["id"], lot_code="BT-1", grams_received=bt_lot_grams)
    sa_lot = new_lot(api, sa["id"], lot_code="SA-1", grams_received=sa_lot_grams)
    line = new_production_line(api)
    batch = new_batch(api, chai["id"], line["id"], target_output_grams=target_output_grams)
    return {"bt": bt, "sa": sa, "chai": chai, "bt_lot": bt_lot, "sa_lot": sa_lot,
            "line": line, "batch": batch}


def setup_line_with_two_batches(api):
    """One production line carrying batch1 [08:00,10:00) and adjacent batch3
    [10:00,12:00), both PLANNED. Returns: chai, line, batch1, batch3.
    """
    chai = new_product(api, name="Almond Chai Blend", category="TEA", kind="BLEND",
                       unit_price_cents_per_gram=7.2, tare_default_grams=5)
    line = new_production_line(api)
    batch1 = new_batch(api, chai["id"], line["id"],
                       scheduled_start="2026-07-10T08:00:00Z",
                       scheduled_end="2026-07-10T10:00:00Z")
    batch3 = new_batch(api, chai["id"], line["id"],
                       scheduled_start="2026-07-10T10:00:00Z",
                       scheduled_end="2026-07-10T12:00:00Z")
    return {"chai": chai, "line": line, "batch1": batch1, "batch3": batch3}


def setup_station_with_two_runs(api):
    """One station carrying run1 [08:00,09:00) and run3 [09:30,10:00) (30-min gap).
    Returns: cham, station, run1, run3.
    """
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    station = new_labeling_station(api)
    run1 = new_tin_run(api, station["id"], [cham["id"]],
                       scheduled_start="2026-07-10T08:00:00Z",
                       scheduled_end="2026-07-10T09:00:00Z")
    run3 = new_tin_run(api, station["id"], [cham["id"]],
                       scheduled_start="2026-07-10T09:30:00Z",
                       scheduled_end="2026-07-10T10:00:00Z")
    return {"cham": cham, "station": station, "run1": run1, "run3": run3}
