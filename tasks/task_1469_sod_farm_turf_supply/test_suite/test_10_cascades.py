"""Maturity-scan OVERAGED cascade (depth 3): field -> pending batches ->
under-allocated confirmed orders (PRD §2.11, §3.2)."""
from test_helpers import (
    TEST_USERS,
    accept_quote,
    assert_money_eq,
    create_batch,
    create_config,
    create_customer,
    create_field,
    create_quote,
    create_variety,
    factories,
    get_order,
    get_success_data,
    set_clock,
    validate_success,
)

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
HARVEST = TEST_USERS["harvest_supervisor_headers"]


def _confirmed_order_on_maturing_field(api):
    """Field 'East 7' planted 2026-02-20 (MATURE at the default clock); one
    PENDING 10-pallet PREMIUM batch scheduled 2026-08-10; a CONFIRMED order
    (line 10 PREMIUM) allocated to it with window 2026-08-10 08:00-10:00."""
    bundle = {}
    bundle["pc"] = create_config(api)
    bundle["v"] = create_variety(api)
    bundle["f"] = create_field(
        api, bundle["v"]["id"], name="East 7",
        last_planted_at="2026-02-20T00:00:00Z", health_score=80,
    )
    bundle["b"] = create_batch(api, bundle["f"]["id"], pallet_count=10,
                               scheduled_date="2026-08-10")
    bundle["c"] = create_customer(
        api, full_name="Cy Rao", email="cy@example.com", phone="555-0103",
        freight_zone=3, address="9 Elm Rd",
    )
    set_clock(api, "2026-08-08T09:00:00Z")  # before the 2026-08-09T14:00 cutoff
    bundle["q"] = create_quote(
        api, bundle["c"]["id"],
        [factories.quote_line(bundle["v"]["id"], "PREMIUM", 10)],
        0, 0, 10,
        delivery_date="2026-08-10",
    )
    bundle["o"] = accept_quote(api, bundle["q"]["id"])
    bundle["o"] = validate_success(api.confirm_order(
        bundle["o"]["id"],
        factories.confirm_order_payload(
            delivery_window_start="2026-08-10T08:00:00Z"
        ),
        SALES,
    ), 200)
    assert bundle["o"]["status"] == "CONFIRMED"
    assert_money_eq(bundle["o"]["allocated_sqft"], 1000, "allocated_sqft")
    # Age 242 days at 2026-10-20 -> beyond mature_max_days 240.
    set_clock(api, "2026-10-20T08:00:00Z")
    return bundle


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / maturity_scan_overaged_cascade_depth3
# ---------------------------------------------------------------------------

def test_maturity_scan_overaged_cancels_pending_batches(api):
    """PRD §3.2: "The scan has teeth. When the persisted `maturity_state` actually changes into `OVERAGED` — and only then — the field is no longer harvestable, so every `PENDING` harvest batch of that field becomes `CANCELLED`."
    PRD §3.2: "Comparing `age_days` with the variety's windows yields `maturity_state`: `SEEDED` while age is at most `germination_max_days`, `GROWING` while at most `growing_max_days`, `READY` while at most `ready_max_days`, `MATURE` while at most `mature_max_days`, and `OVERAGED` beyond that."

    Design: Difficulty/transitive_cascade/maturity_scan_overaged_cascade_depth3
    """
    bundle = _confirmed_order_on_maturing_field(api)
    scanned = get_success_data(api.maturity_scan(bundle["f"]["id"], FARM))
    assert scanned["maturity_state"] == "OVERAGED", "hop 0: age 242 > 240"

    batch = get_success_data(api.get_harvest_batch(bundle["b"]["id"], HARVEST))
    assert batch["status"] == "CANCELLED", "hop 2: pending batch cancelled"


def test_maturity_scan_overaged_reverts_under_allocated_order(api):
    """PRD §3.2: "Any order in `CONFIRMED` whose `allocated_sqft` after those cancellations falls below its promised `turf_sqft` reverts to `PLACED`: its delivery window is cleared (releasing the booked truck capacity), all of its remaining batch links are removed, and its `allocated_sqft` recomputes to zero."
    PRD §2.11: "Several writes propagate beyond their primary target, and every cascade commits atomically within the request — there is no eventual-consistency window."

    Design: Difficulty/transitive_cascade/maturity_scan_overaged_cascade_depth3
    """
    bundle = _confirmed_order_on_maturing_field(api)
    get_success_data(api.maturity_scan(bundle["f"]["id"], FARM))

    order = get_order(api, bundle["o"]["id"])
    assert order["status"] == "PLACED", "hop 3: CONFIRMED -> PLACED reversion"
    assert order["delivery_window_start"] is None, "delivery window cleared"
    assert_money_eq(order["allocated_sqft"], 0, "allocated_sqft recomputes to zero")

    batch = get_success_data(api.get_harvest_batch(bundle["b"]["id"], HARVEST))
    assert batch["status"] == "CANCELLED"
