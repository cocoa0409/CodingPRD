"""Composite setup helpers (multi-step scenario builders).

The harness restarts the server before every test, so every helper builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use
the lenient get_success_data() validator so failures surface as clear
"Setup failed" errors. Ownership-gated Customer calls thread the real
Customer.id through make_customer_headers().
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories
from .api_client import api_client as _default_api
from .test_users import TEST_USERS, make_customer_headers

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
HARVEST = TEST_USERS["harvest_supervisor_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------

def create_config(api=_default_api, name="Std 2026") -> dict:
    resp = api.create_price_config(factories.create_price_config_payload(name=name), FARM)
    return get_success_data(resp)


def create_variety(api=_default_api, name="Tifway 419 Bermuda") -> dict:
    resp = api.create_variety_config(
        factories.create_variety_config_payload(name=name), FARM
    )
    return get_success_data(resp)


def create_field(api=_default_api, variety_id=None, **overrides) -> dict:
    payload = factories.create_field_payload(**overrides)
    if variety_id is not None:
        payload["variety_id"] = variety_id
    resp = api.create_field(payload, FARM)
    return get_success_data(resp)


def get_field(api, field_id) -> dict:
    return get_success_data(api.get_field(field_id, FARM))


def create_batch(api, field_id, *, grade="PREMIUM", pallet_count=5,
                 scheduled_date="2026-08-03", shortfall_slabs=0,
                 shortfall_rolls=0) -> dict:
    """Schedule a harvest batch, threading the field's current version into
    the OCC token expected_field_version (PRD §2.8)."""
    version = get_field(api, field_id)["version"]
    payload = factories.create_harvest_batch_payload(
        field_id,
        version,
        grade=grade,
        pallet_count=pallet_count,
        scheduled_date=scheduled_date,
        shortfall_slabs=shortfall_slabs,
        shortfall_rolls=shortfall_rolls,
    )
    return get_success_data(api.create_harvest_batch(payload, HARVEST))


def complete_batch(api, batch_id, start="2026-08-03T06:00:00Z",
                   end="2026-08-03T06:45:00Z") -> dict:
    payload = factories.complete_harvest_batch_payload(
        actual_harvest_start=start, actual_harvest_end=end
    )
    return get_success_data(api.complete_harvest_batch(batch_id, payload, HARVEST))


def create_customer(api=_default_api, **overrides) -> dict:
    return get_success_data(api.create_customer(
        factories.create_customer_payload(**overrides), SALES
    ))


def set_clock(api, iso: str) -> None:
    get_success_data(api.set_clock(iso, FARM))


def create_quote(api, customer_id, lines, z1, z2, z3, **overrides) -> dict:
    payload = factories.create_quote_payload(customer_id, lines, z1, z2, z3, **overrides)
    return get_success_data(api.create_quote(payload, SALES))


def accept_quote(api, quote_id) -> dict:
    return get_success_data(api.accept_quote(quote_id, SALES))


def confirm_order(api, order_id, window_start="2026-08-03T08:00:00Z") -> dict:
    payload = factories.confirm_order_payload(delivery_window_start=window_start)
    return get_success_data(api.confirm_order(order_id, payload, SALES))


def deliver(api, order_id, accepted_sqft) -> dict:
    return get_success_data(
        api.mark_delivered(order_id, {"accepted_sqft": accepted_sqft}, FLEET)
    )


def record_check(api, order_id) -> dict:
    return get_success_data(api.create_delivery_check(order_id, SALES))


def pay(api, order_id, amount, method="CARD") -> dict:
    return get_success_data(
        api.create_payment(order_id, factories.create_payment_payload(amount, method), SALES)
    )


def get_order(api, order_id, headers=None) -> dict:
    return get_success_data(api.get_order(order_id, headers or SALES))


def linked_batches(api, order_id) -> list:
    data, _meta = validate_paginated(
        api.list_harvest_batches(FARM, params={"order_id": order_id})
    )
    return data


def complete_linked_batches(api, order_id, start="2026-08-03T06:00:00Z",
                            end="2026-08-03T06:45:00Z") -> list:
    completed = []
    for batch in linked_batches(api, order_id):
        completed.append(complete_batch(api, batch["id"], start, end))
    return completed


def create_crew(api=_default_api, **overrides) -> dict:
    return get_success_data(api.create_crew(factories.create_crew_payload(**overrides), FARM))


# ---------------------------------------------------------------------------
# Composite scenario: the "mini" 2-pallet PREMIUM order
# Quote: 2 PREMIUM pallets full -> turf 171.00, freight 1.03 (zones 1/1/0),
# pre 172.03, T0, card_fee 3.44, total_price 175.47.
# ---------------------------------------------------------------------------

MINI_ORDER_TOTAL = 175.47
MINI_ORDER_TURF = 171.00


def mini_chain(api=_default_api, stage="claim", *, accepted_sqft=200,
               weather_case="W1", customer_kwargs=None):
    """Build the mini order chain up to `stage`:
    placed -> confirmed -> out_for_delivery -> delivered -> installed ->
    closed -> claim. Returns a dict of every entity created.

    - confirmed: READY field with one 3-pallet PREMIUM batch (sellable 300)
      scheduled 2026-08-03; order line needs 200 so the whole batch links.
    - delivered: batch completed 06:00-06:45 on 2026-08-03, dispatched 06:50,
      `accepted_sqft` delivered at 09:30.
    - installed: install-start 09:30, install-complete 11:00 (same day).
    - closed: payment of the full 175.47 amount_due while INSTALLED, which
      auto-joins the order to CLOSED.
    - claim: warranty claim filed by the owning customer at 2026-08-20.
    """
    stages = ["placed", "confirmed", "out_for_delivery", "delivered",
              "installed", "closed", "claim"]
    assert stage in stages, f"unknown stage {stage!r}"
    bundle = {}
    bundle["pc"] = create_config(api)
    bundle["v"] = create_variety(api)
    c_kwargs = dict(customer_kwargs or {})
    bundle["c"] = create_customer(api, **c_kwargs)
    bundle["customer_headers"] = make_customer_headers(bundle["c"]["id"])

    if stage != "placed":
        bundle["f"] = create_field(api, bundle["v"]["id"])
        bundle["b"] = create_batch(api, bundle["f"]["id"], pallet_count=3)

    set_clock(api, "2026-08-01T09:00:00Z")
    bundle["q"] = create_quote(
        api,
        bundle["c"]["id"],
        [factories.quote_line(bundle["v"]["id"], "PREMIUM", 2)],
        1, 1, 0,
    )
    bundle["o"] = accept_quote(api, bundle["q"]["id"])
    if stage == "placed":
        return bundle

    bundle["o"] = confirm_order(api, bundle["o"]["id"])
    if stage == "confirmed":
        return bundle

    set_clock(api, "2026-08-03T06:50:00Z")
    complete_linked_batches(api, bundle["o"]["id"])
    bundle["o"] = get_success_data(api.dispatch_order(bundle["o"]["id"], FLEET))
    if stage == "out_for_delivery":
        return bundle

    set_clock(api, "2026-08-03T09:30:00Z")
    bundle["o"] = deliver(api, bundle["o"]["id"], accepted_sqft)
    if stage == "delivered":
        return bundle

    bundle["o"] = get_success_data(
        api.install_start(bundle["o"]["id"], bundle["customer_headers"])
    )
    set_clock(api, "2026-08-03T11:00:00Z")
    bundle["o"] = get_success_data(
        api.install_complete(bundle["o"]["id"], bundle["customer_headers"])
    )
    if stage == "installed":
        return bundle

    pay(api, bundle["o"]["id"], MINI_ORDER_TOTAL)
    bundle["o"] = get_order(api, bundle["o"]["id"])
    if stage == "closed":
        return bundle

    set_clock(api, "2026-08-20T09:00:00Z")
    bundle["w"] = get_success_data(api.create_warranty_claim(
        bundle["o"]["id"],
        factories.create_warranty_claim_payload(weather_case),
        bundle["customer_headers"],
    ))
    return bundle


# ---------------------------------------------------------------------------
# Composite scenario: the 1500-sqft order used by delivery-check tests
# Quote lines: PREMIUM x6 full (600 sqft) + STANDARD x29 short 4 rolls
# (1410 sqft) -> turf 1500.00; zones 18/17/0 -> freight 156.60; pre 1656.60;
# T0; card_fee 33.13; total_price 1689.73; blended_rate 1.1265.
# Batches on one READY field: PREMIUM x10, PREMIUM x8, STANDARD x20,
# STANDARD x12 (all scheduled 2026-08-03). Allocation links PREMIUM x8
# (sellable 800), STANDARD x12 (600) and STANDARD x20 (1000).
# ---------------------------------------------------------------------------

W1500_TURF = 1500.00
W1500_TOTAL = 1689.73
W1500_BASELINE = 1425.00


def w1500_chain(api=_default_api):
    """Config, variety, READY field, four batches, customer, quote, accept,
    confirm (window 2026-08-03 08:00-10:00), complete the three linked
    batches (06:00-06:45), dispatch at 06:50; leaves the clock at
    2026-08-03T09:00:00Z. Returns a dict of every entity created."""
    bundle = {}
    bundle["pc"] = create_config(api)
    bundle["v"] = create_variety(api)
    bundle["f"] = create_field(api, bundle["v"]["id"])
    bundle["b_pre10"] = create_batch(api, bundle["f"]["id"], pallet_count=10)
    bundle["b_pre8"] = create_batch(api, bundle["f"]["id"], pallet_count=8)
    bundle["b_st20"] = create_batch(api, bundle["f"]["id"], grade="STANDARD",
                                    pallet_count=20)
    bundle["b_st12"] = create_batch(api, bundle["f"]["id"], grade="STANDARD",
                                    pallet_count=12)
    bundle["c"] = create_customer(api)
    bundle["customer_headers"] = make_customer_headers(bundle["c"]["id"])
    set_clock(api, "2026-08-01T09:00:00Z")
    bundle["q"] = create_quote(
        api,
        bundle["c"]["id"],
        [
            factories.quote_line(bundle["v"]["id"], "PREMIUM", 6),
            factories.quote_line(bundle["v"]["id"], "STANDARD", 29,
                                 shortfall_rolls=4),
        ],
        18, 17, 0,
    )
    bundle["o"] = accept_quote(api, bundle["q"]["id"])
    bundle["o"] = confirm_order(api, bundle["o"]["id"])
    set_clock(api, "2026-08-03T06:50:00Z")
    complete_linked_batches(api, bundle["o"]["id"])
    bundle["o"] = get_success_data(api.dispatch_order(bundle["o"]["id"], FLEET))
    set_clock(api, "2026-08-03T09:00:00Z")
    return bundle
