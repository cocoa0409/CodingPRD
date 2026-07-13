"""Quote pricing, deposit split, and optimistic-concurrency of quote generation.

Translated from SCAFFOLD_DIFFICULTY_DESIGN.yaml §1.8 (combinatorial_formula) and
SCAFFOLD_CORNER_DESIGN.yaml §1.9 (calculations, cross_cutting_complexity_layers,
consistency_model).

NOTE — Difficulty/combinatorial_formula/quote_tiered_band_selection_mode_a is
SKIPPED: its setup uses route_miles=1000 but asserts base_cents==100000, whereas
PRD §3.3 uniquely derives 500*95 + 500*75 = 85000 for a 1000-mile route (a value
independently confirmed by Corner/calculations/inoperable_surcharge_applied_per_vehicle,
which asserts base_cents==85000 for 1000 miles). The asserted 100000 is the
1200-mile base, so the instance is not PRD-uniquely-derivable — gap left as a gap.
"""
from test_helpers import (
    attach_vehicle,
    create_order,
    create_quote_payload,
    generate_quote,
    make_shipper_headers,
    register_shipper,
    setup_order_with_offered_quote,
    validate_error,
    validate_success,
)


# ─── combinatorial_formula (mode_b) — 2 tests ──────────────────────────────

def test_quote_base_and_transport_surcharge_403mi_enclosed_expedited(api):
    """PRD §3.3: "The first 500 miles — miles 1 through 500 — are billed at 95
    cents per mile."
    PRD §3.3: "If transport_type is ENCLOSED, an enclosed surcharge of 40% of
    base_cents, rounded half-up, is added; otherwise the enclosed surcharge is
    zero. If service_level is EXPEDITED, an expedited surcharge of 25% of
    base_cents, rounded half-up, is added; otherwise the expedited surcharge is
    zero. transport_surcharge_cents is the sum of the enclosed and expedited
    surcharges."

    Design: Difficulty/combinatorial_formula/quote_multi_car_rounding_order_mode_b
    """
    ctx = setup_order_with_offered_quote(
        route_miles=403, transport_type="ENCLOSED", service_level="EXPEDITED",
        num_vehicles=3, declared_value_cents=500_000,
    )
    quote = ctx["quote"]
    assert quote["base_cents"] == 38285, f"base_cents was {quote['base_cents']}"
    assert quote["transport_surcharge_cents"] == 24885, (
        f"transport_surcharge_cents was {quote['transport_surcharge_cents']}"
    )


def test_quote_multi_car_discount_rounds_once_403mi_three_vehicles(api):
    """PRD §3.3: "The raw discount is 5% of that sum for each vehicle beyond the
    first — that is, 5% multiplied by (the vehicle count minus 1), applied to
    (base_cents plus transport_surcharge_cents), rounded half-up."
    PRD §3.3: "The quote total is base_cents plus transport_surcharge_cents plus
    inoperable_surcharge_cents minus multi_car_discount_cents."

    Design: Difficulty/combinatorial_formula/quote_multi_car_rounding_order_mode_b
    """
    ctx = setup_order_with_offered_quote(
        route_miles=403, transport_type="ENCLOSED", service_level="EXPEDITED",
        num_vehicles=3, declared_value_cents=500_000,
    )
    quote = ctx["quote"]
    assert quote["multi_car_discount_cents"] == 6317, (
        f"multi_car_discount_cents was {quote['multi_car_discount_cents']}"
    )
    assert quote["total_cents"] == 56853, f"total_cents was {quote['total_cents']}"


# ─── Deposit split boundaries (calculations) ───────────────────────────────

def test_deposit_clamped_up_to_floor(api):
    """PRD §3.3: "The raw deposit is 20% of quoted_total_cents, rounded half-up.
    deposit_cents is that raw figure clamped to a floor of 10000 cents ($100) and
    a ceiling of 40000 cents ($400): if the raw figure is below the floor it
    becomes 10000, if above the ceiling it becomes 40000, otherwise it stands."
    PRD §3.3: "cod_balance_cents is quoted_total_cents minus deposit_cents".

    Design: Corner/calculations/deposit_floor_boundary_total_38000
    """
    ctx = setup_order_with_offered_quote(route_miles=400, declared_value_cents=500_000)
    resp = api.accept_quote(ctx["order"]["id"], ctx["quote"]["id"],
                            make_shipper_headers(ctx["shipper"]["id"]))
    order = validate_success(resp, expected_status=200)
    assert order["quoted_total_cents"] == 38000
    assert order["deposit_cents"] == 10000
    assert order["cod_balance_cents"] == 28000


def test_deposit_clamped_down_to_cap(api):
    """PRD §3.3: "The raw deposit is 20% of quoted_total_cents, rounded half-up.
    deposit_cents is that raw figure clamped to a floor of 10000 cents ($100) and
    a ceiling of 40000 cents ($400): if the raw figure is below the floor it
    becomes 10000, if above the ceiling it becomes 40000, otherwise it stands."
    PRD §3.3: "cod_balance_cents is quoted_total_cents minus deposit_cents".

    Design: Corner/calculations/deposit_cap_boundary_total_212500
    """
    ctx = setup_order_with_offered_quote(route_miles=3000, declared_value_cents=500_000)
    resp = api.accept_quote(ctx["order"]["id"], ctx["quote"]["id"],
                            make_shipper_headers(ctx["shipper"]["id"]))
    order = validate_success(resp, expected_status=200)
    assert order["quoted_total_cents"] == 212500
    assert order["deposit_cents"] == 40000
    assert order["cod_balance_cents"] == 172500


def test_inoperable_surcharge_added_per_inoperable_vehicle(api):
    """PRD §3.3: "Each vehicle whose is_inoperable flag is true adds a flat 15000
    cents ($150). The surcharge is 15000 multiplied by the count of inoperable
    vehicles on the order."
    PRD §3.3: "The quote total is base_cents plus transport_surcharge_cents plus
    inoperable_surcharge_cents minus multi_car_discount_cents."

    Design: Corner/calculations/inoperable_surcharge_applied_per_vehicle
    """
    ctx = setup_order_with_offered_quote(
        route_miles=1000,
        vehicles=[{"make": "Jeep", "model": "Wrangler", "year": 2015,
                   "is_inoperable": True, "declared_value_cents": 800_000}],
    )
    quote = ctx["quote"]
    assert quote["base_cents"] == 85000
    assert quote["inoperable_surcharge_cents"] == 15000
    assert quote["total_cents"] == 100000


# ─── Optimistic concurrency of quote generation (§2.7) ─────────────────────

def test_quote_generation_with_stale_order_version_rejected(api):
    """PRD §2.7: "If expected_order_version does not equal the order's current
    version — for example because another writer attached a vehicle after the
    client last read the order — the request is rejected with ERR_STALE_VERSION
    (HTTP 412), and no quote is created."

    Design: Corner/cross_cutting_complexity_layers/quote_create_stale_order_version_returns_stale_version
    """
    shipper = register_shipper()
    order = create_order(shipper["id"], route_miles=1200, transport_type="OPEN")
    stale_version = order["version"]  # version 1, before any vehicle attach
    attach_vehicle(order["id"], shipper["id"], declared_value_cents=1_000_000)  # bumps to 2

    resp = api.create_quote(order["id"], create_quote_payload(stale_version),
                            make_shipper_headers(shipper["id"]))
    validate_error(resp, "ERR_STALE_VERSION", expected_status=412)


def test_quote_generation_with_current_version_succeeds(api):
    """PRD §2.7: "The quote-generation request must carry an expected_order_version
    field holding the client's last observed ShipmentOrder.version."
    PRD §3.3: "Generation runs the pricing algorithm over all vehicles currently
    attached to the order and produces a Quote in OFFERED status."

    Design: Corner/cross_cutting_complexity_layers/quote_create_correct_order_version_succeeds
    """
    shipper = register_shipper()
    order = create_order(shipper["id"], route_miles=1200, transport_type="OPEN")
    attach_vehicle(order["id"], shipper["id"], declared_value_cents=1_000_000)
    current = api.get_order(order["id"], make_shipper_headers(shipper["id"]))
    current_version = validate_success(current, expected_status=200)["version"]

    resp = api.create_quote(order["id"], create_quote_payload(current_version),
                            make_shipper_headers(shipper["id"]))
    quote = validate_success(resp, expected_status=201)
    assert quote["status"] == "OFFERED"
    assert quote["total_cents"] == 100000


def test_deposit_and_cod_visible_immediately_on_accept(api):
    """PRD §3.3: "cod_balance_cents is quoted_total_cents minus deposit_cents, so
    that deposit_cents and cod_balance_cents always sum exactly to
    quoted_total_cents. At this point amount_paid_cents is still 0, so
    outstanding_balance_cents equals quoted_total_cents."
    PRD §2.8: "the system performs the cascade immediately and in full — there is
    no eventual reconciliation and no partial application."

    Design: Corner/consistency_model/computed_deposit_and_cod_visible_immediately_on_accept
    """
    ctx = setup_order_with_offered_quote(route_miles=1200, declared_value_cents=1_000_000)
    resp = api.accept_quote(ctx["order"]["id"], ctx["quote"]["id"],
                            make_shipper_headers(ctx["shipper"]["id"]))
    order = validate_success(resp, expected_status=200)
    assert order["deposit_cents"] == 20000
    assert order["cod_balance_cents"] == 80000
    assert order["outstanding_balance_cents"] == 100000
