"""Invoice component math, freight tier boundaries, and price resolution (PRD §3.6)."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_success,
)

from test_helpers import (
    TEST_USERS,
    create_and_deliver_drop,
    create_drop,
    create_posted_price,
    deliver_drop,
    dispatch_drop,
    schedule_drop,
    setup_full_drop_fixture,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
PRICING = TEST_USERS["pricing_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Difficulty / combinatorial_formula / invoice_total_tiered_freight_diesel_branch
# ---------------------------------------------------------------------------


def test_invoice_total_tiered_freight_diesel_branch_estimate(api):
    """PRD §3.6: "The invoice's `fuel_amount_cents` is the delivered gallons
    multiplied by the applied `price_tc_per_gal`, divided by ten, rounded
    half-up; its `freight_amount_cents` is tiered — a flat 15000 cents (that
    is, $150.00) when the delivered gallons are at most 2000, 40
    tenths-of-a-cent per gallon on all gallons when the delivery is between
    2001 and 6000 gallons inclusive, and 32 tenths-of-a-cent per gallon on all
    gallons when the delivery exceeds 6000 gallons, with per-gallon tiers
    rounded half-up; its `tax_amount_cents` is the delivered gallons multiplied
    by the sum of the product's `federal_excise_tc_per_gal`, the station's
    `state_excise_tc_per_gal`, and the station's `local_option_tc_per_gal`,
    divided by ten, rounded half-up. Each component is rounded before they are
    summed into `total_cents`."

    Design: Difficulty/combinatorial_formula/invoice_total_tiered_freight_diesel_branch
    """
    fixture = setup_full_drop_fixture(
        state_code="TX",
        state_excise_tc_per_gal=200,
        price_tc_per_gal=3059,
        tank_capacity=30000,
        opening_physical=0,
        category="DIESEL",
    )
    drop = create_drop(fixture, planned_gallons=5500)
    # Estimated amount uses planned gallons and the current POSTED price
    # (PRD §3.6: "the projected invoice total computed from `planned_gallons`
    # and the current rack price").
    assert drop["estimated_amount_cents"] == 1_948_650


def test_invoice_total_tiered_freight_diesel_branch_invoice(api):
    """PRD §3.6: "The invoice's `fuel_amount_cents` is the delivered gallons
    multiplied by the applied `price_tc_per_gal`, divided by ten, rounded
    half-up; its `freight_amount_cents` is tiered — a flat 15000 cents (that
    is, $150.00) when the delivered gallons are at most 2000, 40
    tenths-of-a-cent per gallon on all gallons when the delivery is between
    2001 and 6000 gallons inclusive, and 32 tenths-of-a-cent per gallon on all
    gallons when the delivery exceeds 6000 gallons, with per-gallon tiers
    rounded half-up; its `tax_amount_cents` is the delivered gallons multiplied
    by the sum of the product's `federal_excise_tc_per_gal`, the station's
    `state_excise_tc_per_gal`, and the station's `local_option_tc_per_gal`,
    divided by ten, rounded half-up. Each component is rounded before they are
    summed into `total_cents`."

    Design: Difficulty/combinatorial_formula/invoice_total_tiered_freight_diesel_branch
    """
    fixture = setup_full_drop_fixture(
        state_code="TX",
        state_excise_tc_per_gal=200,
        price_tc_per_gal=3059,
        tank_capacity=30000,
        opening_physical=0,
        category="DIESEL",
    )
    delivered = create_and_deliver_drop(
        fixture, planned_gallons=5500, delivered_gallons=5500
    )
    invoice = get_success_data(api.get_invoice(delivered["invoice_id"], DISPATCH))
    assert invoice["fuel_amount_cents"] == 1_682_450
    assert invoice["freight_amount_cents"] == 22_000
    assert invoice["tax_amount_cents"] == 244_200
    assert invoice["total_cents"] == 1_948_650


# ---------------------------------------------------------------------------
# Corner / calculations / freight_tier_cliff_at_2000_gallons
# ---------------------------------------------------------------------------


def test_freight_tier_cliff_at_2000_gallons(api):
    """PRD §3.6: "its `freight_amount_cents` is tiered — a flat 15000 cents
    (that is, $150.00) when the delivered gallons are at most 2000, 40
    tenths-of-a-cent per gallon on all gallons when the delivery is between
    2001 and 6000 gallons inclusive, and 32 tenths-of-a-cent per gallon on all
    gallons when the delivery exceeds 6000 gallons, with per-gallon tiers
    rounded half-up"
    PRD §3.6: "its `tax_amount_cents` is the delivered gallons multiplied by
    the sum of the product's `federal_excise_tc_per_gal`, the station's
    `state_excise_tc_per_gal`, and the station's `local_option_tc_per_gal`,
    divided by ten, rounded half-up."

    Design: Corner/calculations/freight_tier_cliff_at_2000_gallons
    """
    fixture = setup_full_drop_fixture(
        state_code="NM",
        state_excise_tc_per_gal=0,
        price_tc_per_gal=1000,
        tank_capacity=20000,
        opening_physical=0,
    )
    d1 = create_and_deliver_drop(
        fixture, planned_gallons=2000,
        window_start="2026-05-02T08:00:00Z", window_end="2026-05-02T12:00:00Z",
    )
    d2 = create_and_deliver_drop(
        fixture, planned_gallons=2001,
        window_start="2026-05-03T08:00:00Z", window_end="2026-05-03T12:00:00Z",
    )
    inv1 = get_success_data(api.get_invoice(d1["invoice_id"], ADMIN))
    inv2 = get_success_data(api.get_invoice(d2["invoice_id"], ADMIN))
    assert inv1["freight_amount_cents"] == 15_000
    assert inv1["total_cents"] == 251_800
    assert inv2["freight_amount_cents"] == 8_004
    assert inv2["total_cents"] == 244_922


# ---------------------------------------------------------------------------
# Corner / calculations / price_selection_latest_effective_then_supersede
# ---------------------------------------------------------------------------


def test_price_selection_latest_effective_then_supersede(api):
    """PRD §2.6: "The current rack price for a product at a station's
    `home_terminal_code` on date D is the posting in `POSTED` status for that
    terminal and product whose `effective_date` is the greatest effective date
    on or before D; when several postings share that greatest effective date,
    the tie is broken in favor of the posting with the latest `created_at`."
    PRD §3.5: "Supersession retires a `POSTED` posting to `SUPERSEDED` and
    atomically creates its replacement: a brand-new posting in `POSTED` status
    for the same terminal, product, and effective date, priced at the
    request's `new_price_tc_per_gal`."

    Design: Corner/calculations/price_selection_latest_effective_then_supersede
    """
    fixture = setup_full_drop_fixture(
        state_code="NM",
        state_excise_tc_per_gal=0,
        price_tc_per_gal=2000,
        price_effective_date="2026-05-01",
        tank_capacity=30000,
        opening_physical=0,
    )
    # Second POSTED posting at effective 2026-05-15.
    posting2 = create_posted_price(
        fixture["product"]["id"],
        terminal_code="TX-NORTH",
        effective_date="2026-05-15",
        price_tc_per_gal=2100,
    )
    set_clock("2026-05-20T00:00:00Z")
    d1 = create_and_deliver_drop(
        fixture, planned_gallons=1000,
        window_start="2026-05-20T08:00:00Z", window_end="2026-05-20T12:00:00Z",
    )
    inv1 = get_success_data(api.get_invoice(d1["invoice_id"], ADMIN))
    assert inv1["price_tc_per_gal"] == 2100
    assert inv1["fuel_amount_cents"] == 210_000
    # Supersede posting2 -> replacement at 2050.
    get_success_data(api.supersede_rack_price_posting(
        posting2["id"],
        {
            "expected_superseded_posting_version": posting2["version"],
            "new_price_tc_per_gal": 2050,
            "effective_date": "2026-05-15",
        },
        PRICING,
    ))
    d2 = create_and_deliver_drop(
        fixture, planned_gallons=1000,
        window_start="2026-05-21T08:00:00Z", window_end="2026-05-21T12:00:00Z",
    )
    inv2 = get_success_data(api.get_invoice(d2["invoice_id"], ADMIN))
    assert inv2["price_tc_per_gal"] == 2050
    assert inv2["fuel_amount_cents"] == 205_000


# ---------------------------------------------------------------------------
# Corner / endpoints / deliver_response_links_invoice_immediately
# ---------------------------------------------------------------------------


def test_deliver_response_links_invoice_immediately(api):
    """PRD §3.6: "Delivery then sets the drop's `invoice_id`, recomputes the
    station's `current_exposure_cents` to include the new invoice, and
    re-evaluates the station's credit band per §2.10."
    PRD §1: "cross-entity consequences (a delivered drop creates an invoice, a
    verified loss shrinks a tank book, a failed brand audit cascades into
    agreement default) are applied immediately and are visible in the same
    request's response and in every subsequent read."

    Design: Corner/endpoints/deliver_response_links_invoice_immediately
    """
    fixture = setup_full_drop_fixture(
        state_code="NM",
        state_excise_tc_per_gal=0,
        price_tc_per_gal=2000,
        tank_capacity=20000,
        opening_physical=0,
    )
    drop = create_drop(fixture, planned_gallons=1000)
    schedule_drop(drop["id"])
    dispatch_drop(drop["id"])
    delivered = validate_success(api.deliver_transport_drop(
        drop["id"], {"delivered_gallons": 1000}, DISPATCH
    ))
    assert delivered["status"] == "DELIVERED"
    assert delivered["invoice_id"] is not None
    invoice = get_success_data(api.get_invoice(delivered["invoice_id"], ADMIN))
    assert invoice["fuel_amount_cents"] == 200_000
    assert invoice["freight_amount_cents"] == 15_000
    assert invoice["tax_amount_cents"] == 18_400
    assert invoice["total_cents"] == 233_400
    assert invoice["status"] == "ISSUED"
