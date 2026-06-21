"""Pricing & material-quantity calculation tests.

Covers the dual-variant and combinatorial-formula difficulty instances: the
estimate-vs-final contract-total divergence, the provisional-vs-actual material
consumption divergence, the tiered-margin non-linear contract total, and the
ceil-per-spec-then-sum cut list.
"""
from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    TEST_USERS,
    make_customer_headers,
    setup_quoted_project,
    setup_committed_reservation,
    create_shop,
    create_material,
    create_customer,
    create_project,
    add_spec,
    setup_base_shop,
    assert_project,
)

MANAGER = TEST_USERS["shop_manager_headers"]
DESIGNER = TEST_USERS["designer_headers"]


# ===========================================================================
# Difficulty / dual_variant_calc
# ===========================================================================
def test_contract_total_estimate_vs_final_diverge(api):
    """PRD §3.3: "A project's forward-looking estimate is held in
    `estimate_total_cents` and recomputed whenever a spec is added or removed and
    at the measure and quote milestones."
    PRD §3.4: "The estimate variant prices all specs regardless of `lock_state`,
    treats a missing finish as `RAW` at zero basis points, and never applies the
    rush surcharge."
    PRD §3.4: "for an identical set of specs and finish, the final total is
    therefore at least the estimate and is strictly greater whenever the project
    is rush or a finish was chosen after the estimate was last taken."

    Design: Difficulty/dual_variant_calc/contract_total_estimate_vs_final_diverge_on_project
    """
    # Shop tax_rate_bps=800, rush_surcharge_bps=1500; project is_rush, STANDARD,
    # one spec base 100000 qty4 (MED tier). Finish PAINT chosen after measure.
    shop = create_shop(tax_rate_bps=800, rush_surcharge_bps=1500, deposit_pct_bps=3000)
    material = create_material(shop["id"])
    customer = create_customer(shop["id"])
    project = create_project(shop["id"], customer["id"], is_rush=True, margin_policy="STANDARD")
    add_spec(shop["id"], project["id"], material["id"], label="Base", quantity=4, base_unit_price_cents=100000)

    # Measure BEFORE selecting a finish: estimate uses RAW (0 bps), no rush.
    measured = get_success_data(api.measure_project(shop["id"], project["id"], DESIGNER))
    assert measured["estimate_total_cents"] == 561600, (
        f"estimate at measure (RAW, no rush) expected 561600, got {measured['estimate_total_cents']}"
    )

    # Now choose PAINT and quote.
    get_success_data(api.create_finish_selection(shop["id"], project["id"], {"finish_code": "PAINT", "sheen": "SATIN"}, DESIGNER))
    quoted = get_success_data(api.quote_project(shop["id"], project["id"], DESIGNER))

    cust_headers = make_customer_headers(customer["id"])
    contracted = validate_success(
        api.contract_project(shop["id"], project["id"], {"expected_project_version": quoted["version"]}, cust_headers)
    )
    assert contracted["contract_total_cents"] == 723341, (
        f"final contract_total (PAINT + rush + tax) expected 723341, got {contracted['contract_total_cents']}"
    )
    assert contracted["contract_total_cents"] != measured["estimate_total_cents"], (
        "final contract total must diverge from the estimate variant"
    )


def test_contract_total_estimate_vs_final_strictly_greater(api):
    """PRD §3.4: "for an identical set of specs and finish, the final total is
    therefore at least the estimate and is strictly greater whenever the project
    is rush or a finish was chosen after the estimate was last taken."

    Design: Difficulty/dual_variant_calc/contract_total_estimate_vs_final_diverge_on_project
    """
    shop = create_shop(tax_rate_bps=800, rush_surcharge_bps=1500, deposit_pct_bps=3000)
    material = create_material(shop["id"])
    customer = create_customer(shop["id"])
    project = create_project(shop["id"], customer["id"], is_rush=True, margin_policy="STANDARD")
    add_spec(shop["id"], project["id"], material["id"], label="Base", quantity=4, base_unit_price_cents=100000)
    measured = get_success_data(api.measure_project(shop["id"], project["id"], DESIGNER))
    get_success_data(api.create_finish_selection(shop["id"], project["id"], {"finish_code": "PAINT"}, DESIGNER))
    quoted = get_success_data(api.quote_project(shop["id"], project["id"], DESIGNER))
    cust_headers = make_customer_headers(customer["id"])
    contracted = validate_success(
        api.contract_project(shop["id"], project["id"], {"expected_project_version": quoted["version"]}, cust_headers)
    )
    # is_rush AND finish chosen after the measure-time estimate -> strictly greater.
    assert contracted["contract_total_cents"] > measured["estimate_total_cents"], (
        f"final {contracted['contract_total_cents']} must be strictly greater than "
        f"estimate {measured['estimate_total_cents']} (rush + later finish)"
    )


def test_material_consumption_provisional_vs_actual_diverge(api):
    """PRD §3.6: "Reservation is forward-looking and provisional: the requested
    `sheets` are added to the material's `reserved_sheets` up front, which lowers
    `available_sheets`, even though the eventual build may consume fewer sheets."
    PRD §3.6: "so only committed reservations are consumed, while any reservation
    that is still merely `HELD` is not consumed even though it held quota."

    Design: Difficulty/dual_variant_calc/material_consumption_provisional_vs_actual_diverge_on_material
    """
    # Material on_hand=10; R1=4 committed, R2=3 held; complete build -> only R1's 4 consumed.
    shop, material, customer = setup_base_shop()
    material = get_success_data(api.restock_material(shop["id"], material["id"], {"sheets": 10}, MANAGER))
    machine = get_success_data(api.create_machine(shop["id"], {"name": "CNC", "changeover_buffer_min": 0}, MANAGER))
    project = create_project(shop["id"], customer["id"], margin_policy="STANDARD")
    add_spec(shop["id"], project["id"], material["id"], quantity=2, base_unit_price_cents=100000)
    get_success_data(api.create_finish_selection(shop["id"], project["id"], {"finish_code": "STAIN"}, DESIGNER))
    get_success_data(api.measure_project(shop["id"], project["id"], DESIGNER))
    quoted = get_success_data(api.quote_project(shop["id"], project["id"], DESIGNER))
    cust = make_customer_headers(customer["id"])
    get_success_data(api.contract_project(shop["id"], project["id"], {"expected_project_version": quoted["version"]}, cust))
    draws = api.list_draws(shop["id"], project["id"], MANAGER).json()["data"]
    dep = next(d for d in draws if d["draw_type"] == "DEPOSIT")
    get_success_data(api.issue_draw(shop["id"], project["id"], dep["id"], MANAGER))
    get_success_data(api.pay_draw(shop["id"], project["id"], dep["id"], cust))

    r1 = get_success_data(api.create_reservation(shop["id"], project["id"], {"material_id": material["id"], "sheets": 4}, MANAGER))
    r2 = get_success_data(api.create_reservation(shop["id"], project["id"], {"material_id": material["id"], "sheets": 3}, MANAGER))
    # Scheduling the first build job drives the project CONTRACTED -> IN_PRODUCTION,
    # which is the state in which a HELD reservation may be committed (PRD §3.6).
    bj = get_success_data(api.create_build_job(shop["id"], project["id"], {"machine_id": machine["id"], "start_utc": "2026-07-01T09:00:00Z", "end_utc": "2026-07-01T12:00:00Z"}, MANAGER))
    get_success_data(api.commit_reservation(shop["id"], project["id"], r1["id"], MANAGER))

    # provisional over-counts: reserved == 4 (committed) + 3 (held) == 7 before the build.
    mat_before = get_success_data(api.get_material(shop["id"], material["id"], MANAGER))
    assert mat_before["reserved_sheets"] == 7, f"provisional reserved expected 7, got {mat_before['reserved_sheets']}"

    get_success_data(api.start_build_job(shop["id"], project["id"], bj["id"], MANAGER))
    get_success_data(api.complete_build_job(shop["id"], project["id"], bj["id"], MANAGER))

    mat_after = get_success_data(api.get_material(shop["id"], material["id"], MANAGER))
    assert mat_after["on_hand_sheets"] == 6, f"on_hand after actual consume expected 6 (10-4), got {mat_after['on_hand_sheets']}"
    assert mat_after["reserved_sheets"] == 3, f"reserved after consume expected 3 (R2 still HELD), got {mat_after['reserved_sheets']}"
    r1_after = get_success_data(api.get_reservation(shop["id"], project["id"], r1["id"], MANAGER))
    r2_after = get_success_data(api.get_reservation(shop["id"], project["id"], r2["id"], MANAGER))
    assert r1_after["status"] == "CONSUMED", "committed reservation must be CONSUMED"
    assert r2_after["status"] == "HELD", "held reservation must remain HELD (not consumed)"


def test_held_reservation_not_consumed_by_build_complete(api):
    """PRD §3.6: "so only committed reservations are consumed, while any
    reservation that is still merely `HELD` is not consumed even though it held
    quota."

    Design: Difficulty/dual_variant_calc/material_consumption_provisional_vs_actual_diverge_on_material
    """
    shop, material, customer = setup_base_shop()
    material = get_success_data(api.restock_material(shop["id"], material["id"], {"sheets": 10}, MANAGER))
    machine = get_success_data(api.create_machine(shop["id"], {"name": "CNC", "changeover_buffer_min": 0}, MANAGER))
    project = create_project(shop["id"], customer["id"], margin_policy="STANDARD")
    add_spec(shop["id"], project["id"], material["id"], quantity=2, base_unit_price_cents=100000)
    get_success_data(api.create_finish_selection(shop["id"], project["id"], {"finish_code": "STAIN"}, DESIGNER))
    get_success_data(api.measure_project(shop["id"], project["id"], DESIGNER))
    quoted = get_success_data(api.quote_project(shop["id"], project["id"], DESIGNER))
    cust = make_customer_headers(customer["id"])
    get_success_data(api.contract_project(shop["id"], project["id"], {"expected_project_version": quoted["version"]}, cust))
    draws = api.list_draws(shop["id"], project["id"], MANAGER).json()["data"]
    dep = next(d for d in draws if d["draw_type"] == "DEPOSIT")
    get_success_data(api.issue_draw(shop["id"], project["id"], dep["id"], MANAGER))
    get_success_data(api.pay_draw(shop["id"], project["id"], dep["id"], cust))

    r1 = get_success_data(api.create_reservation(shop["id"], project["id"], {"material_id": material["id"], "sheets": 4}, MANAGER))
    r2 = get_success_data(api.create_reservation(shop["id"], project["id"], {"material_id": material["id"], "sheets": 3}, MANAGER))
    # Scheduling the first build job drives the project CONTRACTED -> IN_PRODUCTION,
    # which is the state in which a HELD reservation may be committed (PRD §3.6).
    bj = get_success_data(api.create_build_job(shop["id"], project["id"], {"machine_id": machine["id"], "start_utc": "2026-07-01T09:00:00Z", "end_utc": "2026-07-01T12:00:00Z"}, MANAGER))
    get_success_data(api.commit_reservation(shop["id"], project["id"], r1["id"], MANAGER))
    get_success_data(api.start_build_job(shop["id"], project["id"], bj["id"], MANAGER))
    get_success_data(api.complete_build_job(shop["id"], project["id"], bj["id"], MANAGER))

    r2_after = get_success_data(api.get_reservation(shop["id"], project["id"], r2["id"], MANAGER))
    assert r2_after["status"] == "HELD", "a never-committed HELD reservation is not consumed by build complete"


# ===========================================================================
# Difficulty / combinatorial_formula
# ===========================================================================
def test_contract_total_tiered_margin_nonlinear(api):
    """PRD §3.4: "The quantity tier is `SMALL` when `quantity` is at most 2, `MED`
    when `quantity` is 3 through 6, and `BULK` when `quantity` is 7 or more. Under
    the `STANDARD` policy the multipliers are 13500 basis points for `SMALL`,
    13000 for `MED`, and 12500 for `BULK`; under the `PREMIUM` policy they are
    16000 for `SMALL`, 15500 for `MED`, and 15000 for `BULK`."

    Design: Difficulty/combinatorial_formula/contract_total_tiered_margin_nonlinear_mode_a
    """
    # tax0, STANDARD, finish RAW; spec1 qty2 (SMALL 13500), spec2 qty7 (BULK 12500),
    # same base 100000 -> estimate 270000 + 875000 == 1145000.
    shop = create_shop(tax_rate_bps=0)
    material = create_material(shop["id"])
    customer = create_customer(shop["id"])
    project = create_project(shop["id"], customer["id"], margin_policy="STANDARD")
    add_spec(shop["id"], project["id"], material["id"], label="S1", quantity=2, base_unit_price_cents=100000)
    add_spec(shop["id"], project["id"], material["id"], label="S2", quantity=7, base_unit_price_cents=100000)

    measured = validate_success(api.measure_project(shop["id"], project["id"], DESIGNER))
    assert measured["estimate_total_cents"] == 1145000, (
        f"tiered-margin estimate expected 1145000 (SMALL 270000 + BULK 875000), "
        f"got {measured['estimate_total_cents']}"
    )


def test_contract_total_premium_tier_diverges_from_standard(api):
    """PRD §3.4: "Under the `STANDARD` policy the multipliers are 13500 basis
    points for `SMALL`, 13000 for `MED`, and 12500 for `BULK`; under the
    `PREMIUM` policy they are 16000 for `SMALL`, 15500 for `MED`, and 15000 for
    `BULK`."

    Design: Difficulty/combinatorial_formula/contract_total_tiered_margin_nonlinear_mode_a
    """
    # Same two specs but PREMIUM policy: SMALL=16000 -> 320000, BULK=15000 -> 1050000 == 1370000.
    shop = create_shop(tax_rate_bps=0)
    material = create_material(shop["id"])
    customer = create_customer(shop["id"])
    project = create_project(shop["id"], customer["id"], margin_policy="PREMIUM")
    add_spec(shop["id"], project["id"], material["id"], label="S1", quantity=2, base_unit_price_cents=100000)
    add_spec(shop["id"], project["id"], material["id"], label="S2", quantity=7, base_unit_price_cents=100000)
    measured = validate_success(api.measure_project(shop["id"], project["id"], DESIGNER))
    assert measured["estimate_total_cents"] == 1370000, (
        f"PREMIUM tiered-margin estimate expected 1370000 (320000 + 1050000), "
        f"got {measured['estimate_total_cents']}"
    )


def test_cut_list_round_per_spec_then_sum(api):
    """PRD §3.3: "The ceiling is applied to each spec individually before summing;
    the system does not pool fractional sheets across specs, so summing the
    ceilings of two specs can exceed the ceiling of their combined area."

    Design: Difficulty/combinatorial_formula/cut_list_sheets_round_per_spec_then_sum_mode_b
    """
    # sheet_area 5796000; spec1 600x720x560 qty3 -> 2 sheets; spec2 900x720x600 qty2 -> 2 sheets;
    # ceil-per-spec-then-sum == 4 (pooled would be 3).
    shop = create_shop(tax_rate_bps=0)
    material = create_material(shop["id"], sheet_area_mm2=5796000, sheet_price_cents=4000)
    customer = create_customer(shop["id"])
    project = create_project(shop["id"], customer["id"], margin_policy="STANDARD")
    add_spec(shop["id"], project["id"], material["id"], label="S1", width_mm=600, height_mm=720, depth_mm=560, quantity=3, base_unit_price_cents=100000)
    add_spec(shop["id"], project["id"], material["id"], label="S2", width_mm=900, height_mm=720, depth_mm=600, quantity=2, base_unit_price_cents=100000)

    cut = validate_success(api.get_cut_list(shop["id"], project["id"], DESIGNER))
    assert cut["total_sheets"] == 4, (
        f"cut-list total_sheets expected 4 (ceil-per-spec-then-sum, not pooled), got {cut['total_sheets']}"
    )


def test_cut_list_per_spec_ceiling_single_spec(api):
    """PRD §3.3: "it then inflates that area by a 12% saw-kerf and offcut waste
    uplift (that is, it multiplies the total panel area by 11200 and divides by
    10000), divides the inflated area by the spec's material's `sheet_area_mm2`,
    and rounds that quotient up to the next whole sheet."

    Design: Difficulty/combinatorial_formula/cut_list_sheets_round_per_spec_then_sum_mode_b
    """
    # Single spec 600x720x560 qty3: panel 2006400, *3 = 6019200, *11200/10000 = 6741504,
    # /5796000 = 1.16 -> ceil == 2 sheets.
    shop = create_shop(tax_rate_bps=0)
    material = create_material(shop["id"], sheet_area_mm2=5796000, sheet_price_cents=4000)
    customer = create_customer(shop["id"])
    project = create_project(shop["id"], customer["id"], margin_policy="STANDARD")
    add_spec(shop["id"], project["id"], material["id"], label="S1", width_mm=600, height_mm=720, depth_mm=560, quantity=3, base_unit_price_cents=100000)
    cut = validate_success(api.get_cut_list(shop["id"], project["id"], DESIGNER))
    assert cut["total_sheets"] == 2, f"single-spec cut-list expected 2 sheets, got {cut['total_sheets']}"
