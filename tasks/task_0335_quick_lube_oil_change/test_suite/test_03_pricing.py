"""Work-order pricing: provisional vs final totals, discount stacking, per-line coupon
rounding, plain totals, throughput timing, and the next-service projection.

Sources: difficulty rules dual_variant_calc + combinatorial_formula; corner section
calculations.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_technician_headers,
    assert_work_order_pricing_consistent,
    assert_service_sticker,
    # fixtures
    set_clock,
    setup_shop_with_catalog,
    create_inspection_item,
    create_coupon,
    create_retail_vehicle,
    create_direct_work_order,
    claim_start,
    begin_inspection,
    finish_inspection,
    mark_ready,
    add_line,
    get_work_order,
    authorize,
    capture,
    complete,
)

SA = TEST_USERS["service_advisor_headers"]
SM = TEST_USERS["shop_manager_headers"]


# ─── dual_variant_calc / work_order_provisional_vs_final_total ──────────────

def test_provisional_then_final_total_diverge_after_upsell(api):
    """PRD §3.6: "While the order is `DRAFT`, `IN_SERVICE`, or `INSPECTION`, the result
    is provisional — a customer-facing quote that reflects only the lines present so far
    and is recomputed on every line add or remove and on finishing an inspection."
    PRD §3.6: "The final variant is computed once, when the order is marked ready, over
    the complete set of upsells accepted during inspection; it is frozen at that point
    and may exceed the earlier provisional quote because it reflects more lines, but it
    uses the identical formula."

    Design: Difficulty/dual_variant_calc/work_order_provisional_vs_final_total
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    item = create_inspection_item(shop["id"], code="AIR_FILTER", name="Air Filter",
                                  price_cents=4495, labor_minutes=5)
    create_coupon(shop["id"], code="SAVE10", discount_type="PERCENT",
                  percent_value=0.10, min_subtotal_cents=0, usage_limit=5)
    veh = create_retail_vehicle(shop["id"], vin="VINPROV001", plate="PRV1",
                                make="Honda", model="Civic", odometer=30000)

    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 30000,
                                  coupon_code="SAVE10")
    # Provisional at DRAFT: package 6995, coupon -700, taxable 6295, tax 519 -> 6814.
    assert wo["total_cents"] == 6814, f"provisional total expected 6814, got {wo['total_cents']}"

    claim_start(wo["id"], tech["id"])
    in_insp = begin_inspection(wo["id"], tech["id"])
    add_line(wo["id"], tech["id"], item["id"], in_insp["version"])
    finish_inspection(wo["id"], tech["id"])
    ready = mark_ready(wo["id"], tech["id"])

    # Final at READY: subtotal 11490, coupon -1150, taxable 10340, tax 853 -> 11193.
    assert ready["subtotal_cents"] == 11490
    assert ready["total_cents"] == 11193, f"final total expected 11193, got {ready['total_cents']}"
    assert_work_order_pricing_consistent(ready)


def test_final_total_uses_complete_upsell_set(api):
    """PRD §3.6: "The final variant is computed once, when the order is marked ready, over
    the complete set of upsells accepted during inspection; it is frozen at that point
    and may exceed the earlier provisional quote because it reflects more lines, but it
    uses the identical formula."

    Design: Difficulty/dual_variant_calc/work_order_provisional_vs_final_total
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    item = create_inspection_item(shop["id"], code="AIR_FILTER", name="Air Filter",
                                  price_cents=4495, labor_minutes=5)
    create_coupon(shop["id"], code="SAVE10", discount_type="PERCENT",
                  percent_value=0.10, min_subtotal_cents=0, usage_limit=5)
    veh = create_retail_vehicle(shop["id"], vin="VINPROV002", plate="PRV2",
                                make="Honda", model="Civic", odometer=30000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 30000,
                                  coupon_code="SAVE10")
    prov = wo["total_cents"]
    claim_start(wo["id"], tech["id"])
    in_insp = begin_inspection(wo["id"], tech["id"])
    add_line(wo["id"], tech["id"], item["id"], in_insp["version"])
    finish_inspection(wo["id"], tech["id"])
    ready = mark_ready(wo["id"], tech["id"])
    assert ready["subtotal_cents"] == 11490
    assert ready["total_cents"] == 11193
    assert ready["total_cents"] > prov, "final total should exceed the earlier provisional quote"


# ─── combinatorial_formula / discount_stacking_max_vs_sum_with_cap ─────────

def test_non_stackable_coupon_takes_larger_of_two_discounts(api):
    """PRD §3.6: "If a coupon is present and its `stackable_with_fleet` flag is true, the
    raw discount is the coupon component plus the fleet component. Otherwise the raw
    discount is the larger of the two components."

    Design: Difficulty/combinatorial_formula/discount_stacking_max_vs_sum_with_cap
    """
    set_clock()
    shop = get_success_data(api.create_shop(
        {"name": "Main", "tax_rate": 0.0825, "target_throughput_seconds": 1800}, SM))
    pkg = get_success_data(api.create_service_package(
        {"shop_id": shop["id"], "oil_grade": "CONVENTIONAL", "name": "Basic",
         "base_price_cents": 6995, "included_quarts": 5, "labor_minutes": 20,
         "interval_miles": 5000, "interval_days": 180}, SM))
    item = get_success_data(api.create_inspection_item(
        {"shop_id": shop["id"], "code": "AIR_FILTER", "name": "Air Filter",
         "price_cents": 4495, "labor_minutes": 5}, SM))
    get_success_data(api.create_coupon(
        {"shop_id": shop["id"], "code": "FLAT15", "discount_type": "FLAT", "flat_cents": 1500,
         "min_subtotal_cents": 0, "stackable_with_fleet": False, "usage_limit": 5}, SM))
    fleet = get_success_data(api.create_fleet_account(
        {"shop_id": shop["id"], "company_name": "Acme", "discount_pct": 0.10,
         "credit_limit_cents": 100000}, SM))
    bay = get_success_data(api.create_bay({"shop_id": shop["id"], "label": "Bay 1"}, SM))
    tech = get_success_data(api.create_technician({"shop_id": shop["id"], "full_name": "Tess"}, SM))
    veh = get_success_data(api.create_vehicle(
        {"shop_id": shop["id"], "fleet_account_id": fleet["id"], "vin": "VINSTK001",
         "plate": "STK1", "make": "Ford", "model": "F150", "odometer": 20000},
        {"X-User-ID": fleet["id"], "X-User-Role": "FleetManager", "Content-Type": "application/json"}))
    wo = get_success_data(api.create_work_order(
        {"shop_id": shop["id"], "vehicle_id": veh["id"], "bay_id": bay["id"],
         "package_id": pkg["id"], "odometer_in": 20000, "coupon_code": "FLAT15"}, SA))
    claim_start(wo["id"], tech["id"])
    in_insp = begin_inspection(wo["id"], tech["id"])
    add_line(wo["id"], tech["id"], item["id"], in_insp["version"])
    finished = finish_inspection(wo["id"], tech["id"])

    assert finished["subtotal_cents"] == 11490
    assert finished["coupon_discount_cents"] == 1500
    assert finished["fleet_discount_cents"] == 1149
    # max(1500, 1149) = 1500, NOT the sum 2649.
    assert finished["total_discount_cents"] == 1500
    assert finished["total_cents"] == 10814
    assert_work_order_pricing_consistent(finished)


def test_discount_cap_floors_subtotal_times_max_discount_pct(api):
    """PRD §3.6: "A cap is computed as the floor of `subtotal_cents` multiplied by the
    shop's `max_discount_pct`. The `total_discount_cents` recorded on the order is the
    smaller of the raw discount and that cap."

    Design: Difficulty/combinatorial_formula/discount_stacking_max_vs_sum_with_cap
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    # FLAT coupon for 100000 cents off vs a 6995 subtotal: raw discount would be the
    # smaller of flat_cents and subtotal (6995), but the 50% cap = floor(6995*0.5)=3497.
    create_coupon(shop["id"], code="HUGE", discount_type="FLAT", flat_cents=100000,
                  min_subtotal_cents=0, usage_limit=5)
    veh = create_retail_vehicle(shop["id"], vin="VINCAP001", plate="CAP1",
                                make="Honda", model="Fit", odometer=1000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 1000,
                                  coupon_code="HUGE")
    assert wo["subtotal_cents"] == 6995
    # FLAT component = min(100000, 6995) = 6995; cap = floor(6995*0.50) = 3497.
    assert wo["total_discount_cents"] == 3497, (
        f"discount should be capped at floor(6995*0.5)=3497, got {wo['total_discount_cents']}"
    )
    assert_work_order_pricing_consistent(wo)


# ─── combinatorial_formula / percent_coupon_per_line_rounding_order ────────

def test_percent_coupon_rounds_per_line_then_sums(api):
    """PRD §3.6: "for a percentage coupon the discount is computed per line and then
    summed — treating the package itself as one line — so that the component equals the
    package price multiplied by the coupon's `percent_value` and rounded half-up, plus,
    for each non-voided line, that line's `price_cents` multiplied by `percent_value` and
    rounded half-up, all those per-line rounded figures added together."
    PRD §3.6: "This per-line-then-sum order is deliberate and is not the same as rounding
    one product of subtotal times percent."

    Design: Difficulty/combinatorial_formula/percent_coupon_per_line_rounding_order
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    item_a = create_inspection_item(shop["id"], code="AIR_FILTER", name="Air Filter",
                                    price_cents=4495, labor_minutes=5)
    item_b = create_inspection_item(shop["id"], code="CABIN_FILTER", name="Cabin Filter",
                                    price_cents=2895, labor_minutes=5)
    create_coupon(shop["id"], code="SAVE10", discount_type="PERCENT",
                  percent_value=0.10, min_subtotal_cents=0, usage_limit=5)
    veh = create_retail_vehicle(shop["id"], vin="VINRND001", plate="RND1",
                                make="Toyota", model="Camry", odometer=40000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 40000,
                                  coupon_code="SAVE10")
    claim_start(wo["id"], tech["id"])
    in_insp = begin_inspection(wo["id"], tech["id"])
    add_line(wo["id"], tech["id"], item_a["id"], in_insp["version"])
    mid = get_work_order(wo["id"])
    add_line(wo["id"], tech["id"], item_b["id"], mid["version"])
    finished = finish_inspection(wo["id"], tech["id"])

    assert finished["subtotal_cents"] == 14385
    # per-line: round(6995*.1)=700 + round(4495*.1)=450 + round(2895*.1)=290 = 1440
    # (NOT round(14385*.1)=1439).
    assert finished["coupon_discount_cents"] == 1440, (
        f"per-line rounding expected 1440, got {finished['coupon_discount_cents']}"
    )
    assert finished["total_cents"] == 14013
    assert_work_order_pricing_consistent(finished)


def test_percent_coupon_per_line_diverges_from_subtotal_rounding(api):
    """PRD §3.6: "for a percentage coupon the discount is computed per line and then
    summed — treating the package itself as one line — so that the component equals the
    package price multiplied by the coupon's `percent_value` and rounded half-up, plus,
    for each non-voided line, that line's `price_cents` multiplied by `percent_value` and
    rounded half-up, all those per-line rounded figures added together."
    PRD §3.6: "This per-line-then-sum order is deliberate and is not the same as rounding
    one product of subtotal times percent."

    Design: Difficulty/combinatorial_formula/percent_coupon_per_line_rounding_order
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    item_a = create_inspection_item(shop["id"], code="AIR_FILTER", name="Air Filter",
                                    price_cents=4495, labor_minutes=5)
    item_b = create_inspection_item(shop["id"], code="CABIN_FILTER", name="Cabin Filter",
                                    price_cents=2895, labor_minutes=5)
    create_coupon(shop["id"], code="SAVE10", discount_type="PERCENT",
                  percent_value=0.10, min_subtotal_cents=0, usage_limit=5)
    veh = create_retail_vehicle(shop["id"], vin="VINRND002", plate="RND2",
                                make="Toyota", model="Camry", odometer=40000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 40000,
                                  coupon_code="SAVE10")
    claim_start(wo["id"], tech["id"])
    in_insp = begin_inspection(wo["id"], tech["id"])
    add_line(wo["id"], tech["id"], item_a["id"], in_insp["version"])
    mid = get_work_order(wo["id"])
    add_line(wo["id"], tech["id"], item_b["id"], mid["version"])
    finished = finish_inspection(wo["id"], tech["id"])

    # The deliberate per-line-then-sum result (1440) must NOT equal the naive
    # round-half-up(subtotal * percent_value). Per PRD §2.7 round-half-up is
    # floor(x + 0.5), so floor(14385 * 0.10 + 0.5) = floor(1439.0) = 1439.
    # (Python's builtin round() uses banker's rounding and is NOT the PRD rule.)
    import math
    naive_round = math.floor(finished["subtotal_cents"] * 0.10 + 0.5)
    assert naive_round == 1439
    assert finished["coupon_discount_cents"] == 1440
    assert finished["coupon_discount_cents"] != naive_round


# ─── corner: calculations / plain_total_no_coupon_no_fleet ─────────────────

def test_plain_total_no_coupon_no_fleet(api):
    """PRD §3.6: "The `tax_cents` is that taxable base multiplied by the shop's `tax_rate`,
    rounded half-up. The `total_cents` is the taxable base plus `tax_cents`."

    Design: Corner/calculations/plain_total_no_coupon_no_fleet
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay = base["shop"], base["package"], base["bay"]
    veh = create_retail_vehicle(shop["id"], vin="VINPLN001", plate="PLN1",
                                make="Honda", model="Fit", odometer=1000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 1000)
    assert wo["subtotal_cents"] == 6995
    assert wo["total_discount_cents"] == 0
    assert wo["tax_cents"] == 577  # round(6995 * 0.0825)
    assert wo["total_cents"] == 7572
    assert_work_order_pricing_consistent(wo)


# ─── corner: calculations / throughput_breach_strict_boundary ──────────────

def test_throughput_breach_when_seconds_exceed_target(api):
    """PRD §3.7: "The `throughput_seconds` is the whole-second difference obtained by
    taking the floor of the elapsed time from `service_start_at` to `service_ready_at`."
    PRD §3.7: "The `throughput_breach` flag is true exactly when `throughput_seconds` is
    strictly greater than the shop's `target_throughput_seconds`; equalling the target is
    not a breach."

    Design: Corner/calculations/throughput_breach_strict_boundary
    """
    base = setup_shop_with_catalog(clock="2026-06-14T09:00:00Z")
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINTHR001", plate="THR1",
                                make="Honda", model="Fit", odometer=1000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 1000)
    claim_start(wo["id"], tech["id"])
    # Advance the clock 40 minutes = 2400s before mark-ready.
    set_clock("2026-06-14T09:40:00Z")
    ready = mark_ready(wo["id"], tech["id"])
    assert ready["throughput_seconds"] == 2400
    assert ready["throughput_breach"] is True


# ─── corner: calculations / sticker_next_service_projection_basis ──────────

def test_next_service_projection_sticker_and_vehicle_fields(api):
    """PRD §3.10: "The sticker's `next_service_odometer` is that service odometer plus the
    package's `interval_miles`."
    PRD §3.10: "If that projected number of days to hit the mileage limit is at most the
    package's `interval_days`, the basis is `MILEAGE`; otherwise the basis is `TIME`."
    PRD §3.2: "`next_service_odometer` is the last-service odometer plus the completed
    order's package `interval_miles`".

    Design: Corner/calculations/sticker_next_service_projection_basis
    """
    base = setup_shop_with_catalog(clock="2026-06-14T10:00:00Z")
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINNSP001", plate="NSP1",
                                make="Honda", model="Fit", odometer=30000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 30000)
    claim_start(wo["id"], tech["id"])
    mark_ready(wo["id"], tech["id"])
    authorize(wo["id"], "CASH")
    capture(wo["id"])
    complete(wo["id"])

    vehicle_after = get_success_data(api.get_vehicle(veh["id"], SA))
    assert vehicle_after["last_service_odometer"] == 30000
    assert vehicle_after["next_service_odometer"] == 35000  # 30000 + 5000

    stickers = validate_success(api.get_sticker(wo["id"], SA))
    sticker = stickers[0]
    assert_service_sticker(sticker)
    assert sticker["next_service_odometer"] == 35000
    # ceil(5000/40)=125 <= 180 -> MILEAGE.
    assert sticker["basis"] == "MILEAGE"
