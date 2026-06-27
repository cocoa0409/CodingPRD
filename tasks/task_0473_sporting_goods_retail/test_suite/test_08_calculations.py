"""Pricing calculations: effective markdown unit price, final-total markdown
drift, service fee, price-match floor clamp, embroidery surcharge.

Corner queue: calculations section.
"""
import pytest
from test_helpers import (
    api_client,
    get_success_data,
    create_store,
    create_sku,
    create_customer,
    stock_sku,
    create_markdown,
    set_clock,
    setup_placed_order,
    setup_ready_order,
    fulfill_order,
    build_order_with_lines,
    place_order,
    setup_started_service_ticket,
    submit_price_match_claim,
    approve_price_match_claim,
    get_order,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
TECH = TEST_USERS["service_tech_headers"]
PRICE_ADMIN = TEST_USERS["price_admin_headers"]


def test_active_markdown_applied_to_unit_price_on_read(api):
    """PRD §3.2: "When a markdown is active for that SKU at the supplied instant,
    the effective unit price is the base price multiplied by the quantity (100 minus
    `percent_off`), divided by 100, rounded half up to whole cents."
    PRD §3.2: "When a markdown is active for a SKU, that SKU's `lifecycle` reflects
    the markdown kind (`SEASONAL` or `CLEARANCE`)".

    With the clock inside a SEASONAL 25%-off window on a base-6000 SKU, the SKU
    reads SEASONAL and the placed order line prices at 4500 (6000 * 0.75).

    Design: Corner/calculations/effective_unit_price_active_markdown_applied_on_read
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="APPAREL", name="Tee", base_price_cents=6000, size_label="M")
    customer = create_customer(home_state_code="CA")
    create_markdown(sku["id"], "SEASONAL", 25, "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z")
    set_clock("2026-03-10T00:00:00Z")
    stock_sku(store["id"], sku["id"], 5)

    placed, _ = setup_placed_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    sku_read = get_success_data(api.get_sku(sku["id"], ADMIN))
    assert sku_read["lifecycle"] == "SEASONAL"
    assert placed["provisional_total_cents"] == 4500


def test_final_total_reflects_markdown_drift_at_fulfillment(api):
    """PRD §3.6: "For every other line, the effective unit price is re-snapshotted
    at the fulfillment-time clock, so a markdown that became `ACTIVE` or `EXPIRED`
    between placement and fulfillment changes the line price."

    Placed with no active markdown (provisional 10000); a CLEARANCE 40% markdown
    becomes ACTIVE before fulfillment (clock advanced into its window); final
    re-snapshots to 6000.

    Design: Corner/calculations/order_final_markdown_drift_between_place_and_fulfill
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="APPAREL", name="Jacket", base_price_cents=10000, size_label="L")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    ready, _ = setup_ready_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    assert ready["provisional_total_cents"] == 10000

    create_markdown(sku["id"], "CLEARANCE", 40, "2026-02-01T00:00:00Z", "2026-05-01T00:00:00Z")
    set_clock("2026-02-15T00:00:00Z")

    fulfilled = fulfill_order(ready["id"])
    assert fulfilled["provisional_total_cents"] == 10000
    assert fulfilled["final_total_cents"] == 6000


def test_service_fee_skate_sharpen_bronze(api):
    """PRD §3.9: "The base fee is 1000 cents for `SKATE_SHARPEN` and 2500 cents for
    `RACKET_STRING`. The tier discount percent is the same loyalty mapping used in
    pricing — 0 for `BRONZE`".

    A BRONZE customer's completed SKATE_SHARPEN ticket charges the base 1000 (0%
    discount).

    Design: Corner/calculations/service_fee_skate_sharpen_bronze_correct
    """
    store = create_store(state_code="CA")
    customer = create_customer(home_state_code="CA")
    ticket = setup_started_service_ticket(customer["id"], store["id"], "SKATE_SHARPEN")

    completed = get_success_data(api.complete_service_ticket(ticket["id"], TECH))
    assert completed["status"] == "COMPLETED"
    assert completed["service_fee_cents"] == 1000


def test_price_match_floor_clamps_low_competitor_price(api):
    """PRD §3.7: "On approval, the server sets `approved_unit_price_cents` to the
    larger of the submitted `competitor_price_cents` and a price-match floor. The
    floor is the line's `unit_price_cents` multiplied by 50, divided by 100, rounded
    up to the next whole cent".

    A competitor 1000 against a line whose unit_price_cents is 5000 clamps to the
    floor ceil(5000*50/100) = 2500, not 1000.

    Design: Corner/calculations/price_match_floor_clamps_below_50pct
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Bat3", base_price_cents=5000, size_label="31in")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    placed, lines = setup_placed_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    claim = submit_price_match_claim(placed["id"], lines[0]["id"], customer["id"], 1000)
    approved = approve_price_match_claim(claim["id"])
    assert approved["status"] == "APPROVED"
    assert approved["approved_unit_price_cents"] == 2500


def test_embroidery_surcharge_added_per_unit(api):
    """PRD §3.6: "If the line carries `embroidery_text`, an embroidery surcharge of
    500 cents per unit is added — 500 multiplied by the line's `quantity`".

    An embroiderable line base 6000 qty 2 with embroidery_text: provisional =
    6000*2 + 500*2 = 13000 (BRONZE customer, no loyalty discount).

    Design: Corner/calculations/embroidery_surcharge_added_per_unit
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="TEAMWEAR", name="Hat", base_price_cents=6000,
                     size_label="OS", embroiderable=True)
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    placed, _ = setup_placed_order(
        customer["id"], store["id"],
        [{"sku_id": sku["id"], "quantity": 2, "embroidery_text": "GO TEAM"}],
    )
    assert placed["provisional_total_cents"] == 13000
