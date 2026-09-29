"""Derived figures of the plant contract: the configuration roll-up, the chassis
selector, the line-day occupancy sum, the warranty variant switch and the dealer's
credit position.
"""
from decimal import Decimal

from test_helpers import (
    advance_clock,
    assert_cents,
    assert_hours,
    build_canon_kit,
    build_tow_kit,
    create_chassis_receipt,
    create_dealer,
    create_floor_plan,
    create_option_item,
    create_order,
    create_production_line,
    create_supplier,
    fund_order,
    inject_delivered_unit,
    make_dealer_principal_headers,
    read_dealer,
    read_order,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)

FIVE_CANONICAL_OPTION_CODES = ("OPT-AC2", "OPT-BATT", "OPT-INV", "OPT-SOLAR", "OPT-WASH")

DELIVERY_DATE = "2026-10-01T00:00:00Z"


def _weightless_option(option_code, category="INTERIOR", **overrides):
    """Publish a 1.00 h, 100000 cent option that adds no weight, amps or water."""
    payload = {
        "option_code": option_code,
        "category": category,
        "install_station": "FINISH",
        "price_cents": 100000,
        "weight_lbs": 0,
        "added_station_hours": 1.00,
        "amp_draw": 0,
        "water_demand_gal": 0,
    }
    payload.update(overrides)
    return create_option_item(**payload)


def test_canonical_class_a_configuration_totals_are_computed_at_submit(api):
    """PRD §3.2: "The **configuration roll-up** derives seven figures from the floor plan
    baseline plus the selected option set, and it re-runs on creation, on configuration
    replacement, and again at submit." and "`config_weight_lbs` is the floor plan's
    `base_dry_weight_lbs` plus the sum of `weight_lbs` across the selected options.
    `payload_remaining_lbs` is the floor plan's `gvwr_lbs` minus `config_weight_lbs`."
    and "Multiply raw hours by the complexity factor and by the class factor, add the
    surcharge, and round that single final result half up to two decimal places."

    Design: Corner/calculations/canonical_class_a_configuration_totals_are_computed_at_submit
    """
    kit = build_canon_kit(
        with_chassis=False,
        with_booth=False,
        with_lot=False,
        dealer={"floor_plan_credit_limit_cents": 100000000},
    )
    dealer_id = kit["dealer"]["id"]
    option_ids = [kit["options"][code]["id"] for code in FIVE_CANONICAL_OPTION_CODES]

    order = create_order(
        dealer_id,
        kit["floor_plan"]["id"],
        order_type="STOCK",
        selected_option_ids=option_ids,
        requested_delivery_date=DELIVERY_DATE,
    )
    # The roll-up already ran at creation, before any submit-time gate.
    assert_hours(order["required_station_hours"], "71.24")

    submitted = validate_success(
        api.submit_order(order["id"], make_dealer_principal_headers(dealer_id))
    )

    # Raw 59.00 hours * 1.05 complexity * 1.15 CLASS_A = 71.2425, rounded once.
    assert_hours(submitted["required_station_hours"], "71.24")
    assert submitted["config_weight_lbs"] == 22920
    assert submitted["payload_remaining_lbs"] == 3080
    assert_cents(submitted["option_price_total_cents"], 1535500)
    assert submitted["total_amp_draw"] == 28
    assert submitted["total_water_demand_gal"] == 0
    assert_cents(submitted["provisional_invoice_cents"], 16122725)
    assert submitted["status"] == "CONFIG_VALIDATED"
    assert len(submitted["locked_option_versions"]) == 5


def test_amp_surcharge_applies_only_above_forty_amps(api):
    """PRD §3.2: "Then determine the electrical surcharge: a configuration whose
    `total_amp_draw` is more than 40 amps adds a flat four hours of extra rough-in
    labour, and one at 40 amps or below adds nothing."

    Design: Corner/calculations/amp_surcharge_constant_applies_only_above_forty_amps
    """
    floor_plan = create_floor_plan()
    option_a = create_option_item(
        option_code="OPT-A20",
        category="ELECTRICAL",
        install_station="ROUGH_IN",
        price_cents=100000,
        weight_lbs=0,
        added_station_hours=1.00,
        amp_draw=20,
        water_demand_gal=0,
    )
    option_b = create_option_item(
        option_code="OPT-B20",
        category="ELECTRICAL",
        install_station="ROUGH_IN",
        price_cents=100000,
        weight_lbs=0,
        added_station_hours=1.00,
        amp_draw=20,
        water_demand_gal=0,
    )
    option_c = create_option_item(
        option_code="OPT-C1",
        category="ELECTRICAL",
        install_station="ROUGH_IN",
        price_cents=100000,
        weight_lbs=0,
        added_station_hours=1.00,
        amp_draw=1,
        water_demand_gal=0,
    )
    dealer = create_dealer()
    dealer_headers = make_dealer_principal_headers(dealer["id"])

    order_at_forty = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option_a["id"], option_b["id"]],
        requested_delivery_date=DELIVERY_DATE,
    )
    order_at_forty_one = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option_a["id"], option_b["id"], option_c["id"]],
        requested_delivery_date=DELIVERY_DATE,
    )

    at_forty = validate_success(api.submit_order(order_at_forty["id"], dealer_headers))
    at_forty_one = validate_success(api.submit_order(order_at_forty_one["id"], dealer_headers))

    # 40 amps is not more than 40 amps, so no surcharge.
    assert at_forty["total_amp_draw"] == 40
    assert_hours(at_forty["required_station_hours"], "42.00")
    assert_cents(at_forty["provisional_invoice_cents"], 6703100)
    # One extra ampere buys the flat four hours on top of the raw 43.00.
    assert at_forty_one["total_amp_draw"] == 41
    assert_hours(at_forty_one["required_station_hours"], "47.00")
    # The surcharge is labour only and never reaches the invoice.
    assert_cents(at_forty_one["provisional_invoice_cents"], 6785850)
    assert at_forty["status"] == "CONFIG_VALIDATED"
    assert at_forty_one["status"] == "CONFIG_VALIDATED"


def test_station_hours_round_once_at_the_end_not_per_factor(api):
    """PRD §2.6: "Wherever a station-hour figure is produced by a calculation, it is
    rounded half up to exactly two decimal places, and — critically — the rounding is
    applied once, to the final result of the expression, never to intermediate factors."
    PRD §3.2: "The rounding happens once, at the end; rounding the intermediate product
    first is incorrect."

    Design: Corner/calculations/station_hours_round_once_at_the_end_not_per_factor
    """
    floor_plan = create_floor_plan(
        model_code="FP-2900",
        chassis_class="CLASS_C",
        length_ft=29,
        base_msrp_cents=8000000,
        base_station_hours=36.10,
        base_dry_weight_lbs=6000,
        gvwr_lbs=9000,
        required_wheelbase_in=180,
        electrical_service_amps=50,
        fresh_water_capacity_gal=60,
    )
    options = [_weightless_option(f"OPT-N{index}") for index in range(1, 6)]
    dealer = create_dealer()

    order = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"] for option in options],
        requested_delivery_date=DELIVERY_DATE,
    )

    # Raw 41.10 * 1.05 * 1.10 = 47.4705, one rounding at the end.
    assert_hours(order["required_station_hours"], "47.47")
    # Rounding 43.155 to 43.16 first and then multiplying by 1.10 would give 47.48.
    assert Decimal(str(order["required_station_hours"])) != Decimal("47.48")
    assert order["config_weight_lbs"] == 6000
    assert order["total_amp_draw"] == 0
    assert_cents(order["option_price_total_cents"], 500000)


def test_complexity_factor_tier_boundary_between_four_and_five_options(api):
    """PRD §3.2: "Next choose a complexity factor from the *count* of selected options:
    four or fewer options (including none at all) gives 1.00; five through nine gives
    1.05; ten through fourteen gives 1.12; fifteen or more gives 1.20." and "Then choose
    a class factor from the floor plan's `chassis_class`: a towable is 1.00, a Class C is
    1.10, and a Class A is 1.15."

    Design: Corner/calculations/complexity_factor_tier_boundary_between_four_and_five_options
    """
    floor_plan = create_floor_plan()
    options = [_weightless_option(f"OPT-T{index}") for index in range(1, 6)]
    dealer = create_dealer()

    order_of_four = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"] for option in options[:4]],
        requested_delivery_date=DELIVERY_DATE,
    )
    order_of_five = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"] for option in options],
        requested_delivery_date=DELIVERY_DATE,
    )

    # Four options stay in the 1.00 tier, so the hours are the plain sum.
    assert_hours(order_of_four["required_station_hours"], "44.00")
    # The fifth option flips the factor to 1.05: 45.00 * 1.05.
    assert_hours(order_of_five["required_station_hours"], "47.25")
    jump = Decimal(str(order_of_five["required_station_hours"])) - Decimal(
        str(order_of_four["required_station_hours"])
    )
    assert jump == Decimal("3.25"), f"expected a 3.25 hour jump, got {jump}"
    assert_cents(order_of_four["option_price_total_cents"], 400000)
    assert_cents(order_of_five["option_price_total_cents"], 500000)


def test_chassis_selection_ranks_by_receipt_date_then_by_gvwr(api, plant_admin_headers, scheduler_headers):
    """PRD §3.4: "Among the eligible candidates the winner is chosen by three ordered
    keys. Oldest inventory goes first, so the earliest `received_at` wins. Where two
    candidates share the same `received_at`, the smaller `gvwr_lbs` wins — the plant does
    not waste a heavy chassis on a light coach. Where they still tie, the earlier
    `created_at` wins. The row identifier is never used as a tiebreak." and "Its
    `wheelbase_in` must equal the floor plan's `required_wheelbase_in` exactly — a floor
    plan mounts on one wheelbase and no other, so near misses are not near."

    Design: Corner/calculations/chassis_selection_ranks_by_receipt_date_then_by_gvwr
    """
    supplier = create_supplier()
    floor_plan = create_floor_plan()
    option = create_option_item()
    dealer = create_dealer()

    advance_clock("2026-08-02T00:00:00Z")
    chassis_old = create_chassis_receipt(
        supplier["id"],
        chassis_serial="CH-OLD",
        chassis_class="TOWABLE",
        gvwr_lbs=12000,
        wheelbase_in=180,
    )
    advance_clock("2026-08-03T00:00:00Z")
    chassis_big = create_chassis_receipt(
        supplier["id"],
        chassis_serial="CH-BIG",
        chassis_class="TOWABLE",
        gvwr_lbs=9600,
        wheelbase_in=180,
    )
    chassis_small = create_chassis_receipt(
        supplier["id"],
        chassis_serial="CH-SMALL",
        chassis_class="TOWABLE",
        gvwr_lbs=9500,
        wheelbase_in=180,
    )
    chassis_wrong_wheelbase = create_chassis_receipt(
        supplier["id"],
        chassis_serial="CH-WB",
        chassis_class="TOWABLE",
        gvwr_lbs=14000,
        wheelbase_in=200,
    )

    order_a = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date=DELIVERY_DATE,
    )
    submit_order(order_a["id"], dealer["id"])
    order_b = create_order(
        dealer["id"],
        floor_plan["id"],
        order_type="STOCK",
        selected_option_ids=[option["id"]],
        requested_delivery_date=DELIVERY_DATE,
    )
    submit_order(order_b["id"], dealer["id"])

    winner_a = validate_success(api.match_chassis(order_a["id"], scheduler_headers))
    winner_b = validate_success(api.match_chassis(order_b["id"], scheduler_headers))

    # Received 2026-08-02, so it beats both 2026-08-03 arrivals despite being heaviest.
    assert winner_a["id"] == chassis_old["id"]
    assert winner_a["chassis_serial"] == "CH-OLD"
    matched_old = validate_success(api.get_chassis_receipt(chassis_old["id"], plant_admin_headers))
    assert matched_old["status"] == "MATCHED"
    assert matched_old["matched_unit_order_id"] == order_a["id"]
    # The two 2026-08-03 arrivals tie on receipt date, so the lighter rating wins even
    # though CH-BIG was created first.
    assert winner_b["id"] == chassis_small["id"]
    assert winner_b["gvwr_lbs"] == 9500
    assert winner_b["id"] != chassis_big["id"]
    still_big = validate_success(api.get_chassis_receipt(chassis_big["id"], plant_admin_headers))
    assert still_big["status"] == "RECEIVED"
    assert still_big["matched_unit_order_id"] is None
    # Wheelbase 200 never enters the eligible set, whatever its rating.
    still_wrong = validate_success(
        api.get_chassis_receipt(chassis_wrong_wheelbase["id"], plant_admin_headers)
    )
    assert still_wrong["status"] == "RECEIVED"
    assert still_wrong["matched_unit_order_id"] is None


def test_line_day_occupancy_counts_only_the_same_line_and_the_same_day(
    api, plant_admin_headers, scheduler_headers
):
    """PRD §3.3: "The **line-day ceiling** looks at one calendar-day bucket on one line.
    Day buckets never overlap; a slot occupies a whole day keyed by `slot_date`, not an
    instant range. Gather every slot on that line and that date whose `status` is
    `RESERVED` or `CONSUMED`, excluding the slot this same request just released, and
    take two numbers from them: the count of such slots, and the sum of their
    `station_hours_committed`." and "Only then is the hours ceiling checked — if the
    summed committed hours plus this order's `required_station_hours` would exceed the
    line's `daily_station_hour_capacity`, the request fails with
    `ERR_LINE_DAY_HOURS_EXCEEDED`."

    Design: Corner/calculations/line_day_occupancy_counts_only_the_same_line_and_the_same_day
    """
    kit = build_tow_kit(
        with_supplier=False,
        with_chassis=False,
        with_booth=False,
        line={"daily_station_hour_capacity": 45.00, "max_units_per_day": 4},
    )
    line_one = kit["line"]
    line_two = create_production_line(
        line_code="LINE-T2",
        chassis_class_supported="TOWABLE",
        daily_station_hour_capacity=45.00,
        max_units_per_day=4,
    )
    dealer_id = kit["dealer"]["id"]

    orders = []
    for _ in range(4):
        order = create_order(
            dealer_id,
            kit["floor_plan"]["id"],
            order_type="STOCK",
            selected_option_ids=[kit["option"]["id"]],
            requested_delivery_date=DELIVERY_DATE,
        )
        orders.append(submit_order(order["id"], dealer_id))
    order_a, order_b, order_c, order_d = orders

    slot_a = validate_success(
        api.reserve_production_slot(
            order_a["id"],
            {
                "line_id": line_one["id"],
                "slot_date": "2026-08-05T00:00:00Z",
                "expected_unit_order_version": order_a["version"],
            },
            scheduler_headers,
        ),
        201,
    )
    slot_b = validate_success(
        api.reserve_production_slot(
            order_b["id"],
            {
                "line_id": line_one["id"],
                "slot_date": "2026-08-06T00:00:00Z",
                "expected_unit_order_version": order_b["version"],
            },
            scheduler_headers,
        ),
        201,
    )
    slot_c = validate_success(
        api.reserve_production_slot(
            order_c["id"],
            {
                "line_id": line_two["id"],
                "slot_date": "2026-08-05T00:00:00Z",
                "expected_unit_order_version": order_c["version"],
            },
            scheduler_headers,
        ),
        201,
    )
    refused = api.reserve_production_slot(
        order_d["id"],
        {
            "line_id": line_one["id"],
            "slot_date": "2026-08-05T00:00:00Z",
            "expected_unit_order_version": order_d["version"],
        },
        scheduler_headers,
    )

    assert slot_a["sequence_position"] == 1
    assert_hours(slot_a["station_hours_committed"], "41.00")
    # A different slot_date is a different bucket, so LINE-T's 2026-08-06 started empty.
    assert slot_b["sequence_position"] == 1
    # A different line is a different bucket too, even on the same calendar day.
    assert slot_c["sequence_position"] == 1
    # 41.00 + 41.00 = 82.00 against LINE-T's 45.00 hours for 2026-08-05.
    validate_error(refused, ApiErrorId.ERR_LINE_DAY_HOURS_EXCEEDED)

    assert read_order(order_d["id"])["status"] == "CONFIG_VALIDATED"
    _rows, meta = validate_paginated(
        api.list_production_slots(plant_admin_headers, {"unit_order_id": order_d["id"]})
    )
    assert meta["total_count"] == 0
    _rows, meta = validate_paginated(
        api.list_production_slots(
            plant_admin_headers,
            {"line_id": line_one["id"], "slot_date": "2026-08-05T00:00:00Z"},
        )
    )
    assert meta["total_count"] == 1

    dealer = read_dealer(dealer_id)
    assert_hours(dealer["allocation_hours_consumed"], "123.00")
    assert_hours(dealer["entitlement_hours"], "270.00")


def test_warranty_variant_is_selected_by_the_365_day_boundary(api, warranty_admin_headers):
    """PRD §3.8: "Warranty coverage runs 365 days from the `shipped_at` of the order that
    owns the claimed build. At filing, `in_warranty` is set true when the logical clock is
    within that period of `shipped_at` and false otherwise, and that single boolean selects
    which of the two reimbursement variants governs the payout." and "The total paid to the
    dealer is the schedule subtotal plus `goodwill_authorized_cents` — under the in-warranty
    variant. Under the out-of-warranty variant the subtotal is computed and recorded for the
    record but is **not** paid, so `total_reimbursement_cents` is `goodwill_authorized_cents`
    alone. The tier is still derived from the unpaid subtotal, so tier selection is identical
    across the two variants even though the payout differs."

    Design: Corner/calculations/warranty_variant_is_selected_by_the_365_day_boundary
    """
    floor_plan = create_floor_plan()
    dealer = create_dealer()
    dealer_headers = make_dealer_principal_headers(dealer["id"])
    build_one = inject_delivered_unit(
        dealer["id"], floor_plan["id"], shipped_at="2026-08-01T00:00:00Z"
    )
    build_two = inject_delivered_unit(
        dealer["id"], floor_plan["id"], shipped_at="2026-08-01T00:00:00Z"
    )

    # Exactly 365 days after shipment.
    advance_clock("2027-08-01T00:00:00Z")
    claim_one = validate_success(
        api.create_warranty_claim(
            {
                "unit_build_id": build_one["id"],
                "claim_type": "APPLIANCE",
                "labor_hours": 3.50,
                "parts_cost_cents": 68000,
                "narrative": "water heater ignition board failed",
                "goodwill_requested_cents": 60000,
            },
            dealer_headers,
        ),
        201,
    )
    decided_one = validate_success(
        api.decide_claim(claim_one["id"], {"decision": "APPROVED"}, warranty_admin_headers)
    )

    # One day later the same coach is out of warranty.
    advance_clock("2027-08-02T00:00:00Z")
    claim_two = validate_success(
        api.create_warranty_claim(
            {
                "unit_build_id": build_two["id"],
                "claim_type": "APPLIANCE",
                "labor_hours": 3.50,
                "parts_cost_cents": 68000,
                "narrative": "identical water heater ignition board failure",
                "goodwill_requested_cents": 60000,
            },
            dealer_headers,
        ),
        201,
    )
    decided_two = validate_success(
        api.decide_claim(claim_two["id"], {"decision": "APPROVED"}, warranty_admin_headers)
    )

    assert claim_one["in_warranty"] is True
    assert decided_one["authority_tier"] == "TIER_A"
    for decided in (decided_one, decided_two):
        assert_cents(decided["labor_reimbursement_cents"], 27300)
        assert_cents(decided["parts_reimbursement_cents"], 78200)
    # The 2000 bp ceiling on the 105500 subtotal beats the 60000 request and the 75000
    # TIER_A ceiling.
    assert_cents(decided_one["goodwill_authorized_cents"], 21100)
    assert_cents(decided_one["total_reimbursement_cents"], 126600)

    assert claim_two["in_warranty"] is False
    # The tier is derived from the unpaid subtotal, so it does not move with the variant.
    assert decided_two["authority_tier"] == "TIER_A"
    assert_cents(decided_two["goodwill_authorized_cents"], 21100)
    # The schedule is recorded but not paid.
    assert_cents(decided_two["total_reimbursement_cents"], 21100)

    assert_cents(decided_one["supplier_chargeback_cents"], 0)
    assert_cents(decided_two["supplier_chargeback_cents"], 0)
    assert_cents(read_dealer(dealer["id"])["goodwill_used_cents"], 42200)


def test_dealer_exposure_reconciles_with_the_sum_of_its_funded_orders(api, plant_admin_headers):
    """PRD §3.7: "A dealer's `financed_exposure_cents` is the sum, across every one of its
    orders whose `financing_status` is `FLOOR_PLAN_FUNDED` or `CURTAILED`, of that order's
    `financed_principal_cents` minus its `curtailment_paid_cents`. Its
    `credit_utilization_bp` is that exposure multiplied by 10000 and divided by its
    `floor_plan_credit_limit_cents`, truncated toward zero to a whole number of basis
    points — and zero when the credit limit is zero." and "A payment that leaves the paid
    total short of the full principal adds `amount_cents` to `curtailment_paid_cents` and
    recomputes `curtailment_due_cents`".

    Design: Corner/calculations/dealer_exposure_reconciles_with_the_sum_of_its_funded_orders
    """
    kit = build_tow_kit(with_supplier=False, with_chassis=False, with_booth=False)
    dealer_id = kit["dealer"]["id"]
    dealer_headers = make_dealer_principal_headers(dealer_id)

    funded = []
    for _ in range(2):
        order = create_order(
            dealer_id,
            kit["floor_plan"]["id"],
            order_type="STOCK",
            selected_option_ids=[kit["option"]["id"]],
            requested_delivery_date=DELIVERY_DATE,
        )
        submit_order(order["id"], dealer_id)
        funded.append(fund_order(order["id"], dealer_id))
    order_one, order_two = funded

    before = validate_success(api.get_dealer(dealer_id, plant_admin_headers))
    paid = validate_success(
        api.floor_plan_payment(order_one["id"], {"amount_cents": 1000000}, dealer_headers)
    )
    after = validate_success(api.get_dealer(dealer_id, plant_admin_headers))

    assert_cents(order_one["financed_principal_cents"], 5958315)
    assert_cents(order_two["financed_principal_cents"], 5958315)
    assert_cents(before["financed_exposure_cents"], 11916630)
    assert (
        before["financed_exposure_cents"]
        == order_one["financed_principal_cents"] + order_two["financed_principal_cents"]
    )
    assert before["credit_utilization_bp"] == 1191
    # A partial payment is not a payoff.
    assert_cents(paid["curtailment_paid_cents"], 1000000)
    assert paid["financing_status"] == "FLOOR_PLAN_FUNDED"
    assert_cents(after["financed_exposure_cents"], 10916630)
    assert after["financed_exposure_cents"] == (
        order_one["financed_principal_cents"] - 1000000
    ) + order_two["financed_principal_cents"]
    assert after["credit_utilization_bp"] == 1091
    assert after["credit_status"] == "GOOD_STANDING"
    # The payment touched only the order it addressed.
    assert_cents(read_order(order_two["id"])["curtailment_paid_cents"], 0)
