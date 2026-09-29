"""Invoice variants, supplier trust windows, warranty waterfall order and the
credit-utilisation / chassis-margin boundaries of the RV assembly plant contract.
"""
from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_cents,
    assert_hours,
    assert_two_decimals,
    build_canon_kit,
    canon_option_ids,
    create_chassis_receipt,
    create_component_lot,
    create_dealer,
    create_floor_plan,
    create_option_item,
    create_order,
    create_supplier,
    decide_funding,
    draft_campaign,
    file_claim,
    inject_delivered_unit,
    install_pieces,
    make_dealer_principal_headers,
    make_quality_inspector_headers,
    make_warranty_admin_headers,
    match_chassis,
    open_campaign,
    release_to_line,
    request_funding,
    reserve_slot,
    submit_order,
    validate_error,
    validate_success,
    advance_build,
    complete_inspection,
    replace_configuration,
    schedule_booth_inspection,
    schedule_pdi,
)

# ─── Master data of PRD §3.1 used by the money and boundary tests ──────────

FLOOR_PLAN_3410 = {
    "model_code": "FP-3410",
    "chassis_class": "CLASS_A",
    "length_ft": 34,
    "base_msrp_cents": 18500000,
    "base_station_hours": 46.00,
    "base_dry_weight_lbs": 22400,
    "gvwr_lbs": 26000,
    "required_wheelbase_in": 242,
    "electrical_service_amps": 50,
    "fresh_water_capacity_gal": 90,
}

OPTION_SPECS = [
    {
        "option_code": "OPT-AC2",
        "category": "ELECTRICAL",
        "install_station": "ROOF_SET",
        "price_cents": 385000,
        "weight_lbs": 95,
        "added_station_hours": 2.50,
        "amp_draw": 16,
        "water_demand_gal": 0,
    },
    {
        "option_code": "OPT-WASH",
        "category": "APPLIANCE",
        "install_station": "APPLIANCE_INSTALL",
        "price_cents": 245500,
        "weight_lbs": 180,
        "added_station_hours": 3.00,
        "amp_draw": 12,
        "water_demand_gal": 0,
    },
    {
        "option_code": "OPT-BATT",
        "category": "ELECTRICAL",
        "install_station": "ROUGH_IN",
        "price_cents": 415000,
        "weight_lbs": 130,
        "added_station_hours": 2.00,
        "amp_draw": 0,
        "water_demand_gal": 0,
    },
    {
        "option_code": "OPT-INV",
        "category": "ELECTRICAL",
        "install_station": "ROUGH_IN",
        "price_cents": 165000,
        "weight_lbs": 45,
        "added_station_hours": 1.50,
        "amp_draw": 0,
        "water_demand_gal": 0,
        "requires_option_codes": ["OPT-BATT"],
    },
    {
        "option_code": "OPT-SOLAR",
        "category": "ELECTRICAL",
        "install_station": "ROOF_SET",
        "price_cents": 325000,
        "weight_lbs": 70,
        "added_station_hours": 4.00,
        "amp_draw": 0,
        "water_demand_gal": 0,
        "requires_option_codes": ["OPT-INV"],
    },
]

SELECTION_ORDER = ("OPT-AC2", "OPT-WASH", "OPT-SOLAR", "OPT-INV", "OPT-BATT")

DEALER_WEST = {
    "dealer_code": "D-WEST",
    "region": "WEST",
    "allocation_share_bp": 1500,
    "floor_plan_credit_limit_cents": 15274000,
    "goodwill_budget_cents": 500000,
}

INSPECTOR_ALICE = make_quality_inspector_headers("qi-alice")
INSPECTOR_BOB = make_quality_inspector_headers("qi-bob")
WARRANTY_CAROL = make_warranty_admin_headers("wa-carol")


def publish_class_a_catalogue():
    """Publish floor plan FP-3410 and its five options. Returns (plan, options)."""
    floor_plan = create_floor_plan(**FLOOR_PLAN_3410)
    options = {spec["option_code"]: create_option_item(**spec) for spec in OPTION_SPECS}
    return floor_plan, options


def five_option_ids(options):
    """The five option identifiers in the order the dealer selects them."""
    return [options[code]["id"] for code in SELECTION_ORDER]


def five_option_order(dealer_id, floor_plan_id, option_ids):
    """A STOCK order on the five options, left in DRAFT."""
    return create_order(
        dealer_id,
        floor_plan_id,
        order_type="STOCK",
        selected_option_ids=option_ids,
        requested_delivery_date="2026-09-15T00:00:00Z",
    )


def five_option_submitted_order(dealer_id, floor_plan_id, option_ids):
    order = five_option_order(dealer_id, floor_plan_id, option_ids)
    return submit_order(order["id"], dealer_id)


def canon_build_ready_to_ship():
    """One Class A coach walked to READY_TO_SHIP through a failed water test.

    The walk books 75.00 station hours in total, fails the first water test on
    a leak, takes the retest at 6 defect points and the pre-delivery inspection
    at 3, so the build carries rework_count 1 and defect_points_total 9.
    Returns (kit, order, build).
    """
    kit = build_canon_kit()
    dealer_id = kit["dealer"]["id"]
    order = five_option_submitted_order(
        dealer_id, kit["floor_plan"]["id"], canon_option_ids(kit)
    )
    request_funding(order["id"], dealer_id)
    funded = decide_funding(order["id"], "APPROVED")
    reserve_slot(order["id"], kit["line"]["id"], "2026-08-05T00:00:00Z", funded["version"])
    match_chassis(order["id"])
    build = release_to_line(order["id"])

    advance_build(build["id"], "SIDEWALL_LAM", 8.00)
    advance_build(build["id"], "ROOF_SET", 10.00)
    advance_build(build["id"], "ROUGH_IN", 14.00)
    install_pieces(build["id"], kit["lot"]["id"], "APPLIANCE_INSTALL", 2)
    advance_build(build["id"], "APPLIANCE_INSTALL", 12.00)
    advance_build(build["id"], "FINISH", 9.00)
    advance_build(build["id"], "WATER_TEST", 2.00)

    leaking = schedule_booth_inspection(
        build["id"],
        kit["booth"]["id"],
        "2026-08-05T09:00:00Z",
        "2026-08-05T10:00:00Z",
        headers=INSPECTOR_ALICE,
    )
    complete_inspection(leaking["id"], 0, True, headers=INSPECTOR_ALICE)

    advance_build(build["id"], "APPLIANCE_INSTALL", 6.00)
    advance_build(build["id"], "FINISH", 4.00)
    advance_build(build["id"], "WATER_TEST", 2.00)

    retest = schedule_booth_inspection(
        build["id"],
        kit["booth"]["id"],
        "2026-08-05T11:00:00Z",
        "2026-08-05T12:00:00Z",
        headers=INSPECTOR_ALICE,
    )
    complete_inspection(retest["id"], 6, False, headers=INSPECTOR_ALICE)

    advance_build(build["id"], "PDI", 3.00)
    pdi = schedule_pdi(build["id"], headers=INSPECTOR_BOB)
    complete_inspection(pdi["id"], 3, False, headers=INSPECTOR_BOB)
    advance_build(build["id"], "READY_TO_SHIP", 5.00)
    return kit, order, build


def supplier_with_two_open_safety_campaigns():
    """One appliance supplier carrying two SAFETY campaigns opened at the clock start."""
    supplier = create_supplier(
        supplier_code="SUP-APP",
        name="Northline Appliance",
        component_categories=["APPLIANCE"],
    )
    for lot_code in ("L-1", "L-2"):
        create_component_lot(
            supplier["id"],
            part_number="WH-6G-2026",
            lot_code=lot_code,
            category="APPLIANCE",
            quantity_received=10,
        )
    for campaign_code, lot_code in (("RC-2026-01", "L-1"), ("RC-2026-02", "L-2")):
        campaign = draft_campaign(
            supplier["id"],
            campaign_code=campaign_code,
            part_number="WH-6G-2026",
            lot_codes=[lot_code],
            severity="SAFETY",
        )
        open_campaign(campaign["id"])
    return supplier


def delivered_unit_for_appliance_claim():
    """Supplier, dealer, appliance lot and one delivered coach. Returns a dict."""
    supplier = create_supplier(
        supplier_code="SUP-APP",
        name="Northline Appliance",
        component_categories=["APPLIANCE"],
    )
    floor_plan = create_floor_plan(**FLOOR_PLAN_3410)
    dealer = create_dealer(**DEALER_WEST)
    lot = create_component_lot(
        supplier["id"],
        part_number="WH-6G-2026",
        lot_code="L-2211",
        category="APPLIANCE",
        quantity_received=20,
    )
    build = inject_delivered_unit(
        dealer["id"], floor_plan["id"], shipped_at="2026-08-01T00:00:00Z"
    )
    return {
        "supplier": supplier,
        "floor_plan": floor_plan,
        "dealer": dealer,
        "lot": lot,
        "build": build,
    }


APPLIANCE_CLAIM = {
    "claim_type": "APPLIANCE",
    "labor_hours": 3.50,
    "parts_cost_cents": 68000,
    "narrative": "Water heater failed on delivery inspection",
    "goodwill_requested_cents": 60000,
}


# ─── PRD §3.7 the two invoice variants of one coach ────────────────────────


class TestInvoiceVariants:
    def test_shipping_writes_a_final_invoice_63460_cents_above_the_provisional(
        self, api, plant_admin_headers, scheduler_headers
    ):
        """PRD §3.7: "Under the **final variant**, computed at shipment from the finished build, three adjustments apply."
        PRD §3.7: "Overtime is the excess of the build's `actual_station_hours` over the order's `required_station_hours`, or zero when the coach came in on or under plan; that excess in hours is multiplied by 8500 cents per hour and rounded half up to whole cents."
        PRD §3.7: "Rework is a flat 45000 cents for each unit of the build's `rework_count`."
        PRD §3.7: "The quality credit is 1500 cents for each point of the build's `defect_points_total`, capped at 90000 cents."
        PRD §3.7: "`final_invoice_cents` is then the discounted subtotal plus freight plus the overtime surcharge plus the rework surcharge, minus the quality credit."
        PRD §3.7: "Notably, `financed_principal_cents` is *not* recomputed at shipment, so the gap between the provisional and final invoices is exactly the dealer's cash settlement."
        PRD §3.7: "On success `shipped_at` is stamped from the logical clock, `final_invoice_cents` is written from the final variant, and the build moves `READY_TO_SHIP → SHIPPED`."

        Design: Difficulty/dual_variant_calc/invoice_provisional_at_submit_versus_final_at_ship_diverge_on_one_unit
        """
        _kit, order, build = canon_build_ready_to_ship()

        shipped = validate_success(api.ship_order(order["id"], scheduler_headers))

        assert_cents(shipped["provisional_invoice_cents"], 16122725)
        assert_cents(shipped["final_invoice_cents"], 16186185)
        assert shipped["final_invoice_cents"] - shipped["provisional_invoice_cents"] == 63460
        assert_hours(shipped["required_station_hours"], "71.24")

        built = validate_success(api.get_unit_build(build["id"], plant_admin_headers))
        assert_hours(built["actual_station_hours"], "75.00")
        assert built["rework_count"] == 1
        assert built["defect_points_total"] == 9

        assert shipped["status"] == "SHIPPED"
        assert built["current_station"] == "SHIPPED"
        assert_cents(shipped["financed_principal_cents"], 14510453)

    def test_provisional_invoice_stands_alone_while_the_coach_is_only_built(
        self, api, plant_admin_headers
    ):
        """PRD §3.2: "The seventh figure is money, and §3.7 develops it fully; at submit the order's `provisional_invoice_cents` is written from the provisional variant of the invoice calculation, and `final_invoice_cents` stays null until the coach ships."
        PRD §3.7: "Under the **provisional variant**, computed at submit, no build exists yet, so the three build-derived adjustments are all zero and `provisional_invoice_cents` is simply the discounted subtotal plus freight."
        PRD §3.5: "On success the reported `station_hours_used` is added to the build's `actual_station_hours`, which accumulates across the whole build including every rework loop, and which later becomes the overtime term of the final invoice."
        PRD §3.5: "Reaching `READY_TO_SHIP` is also the moment the paperwork catches up: the owning order moves `IN_PRODUCTION → BUILT` in the same operation."
        PRD §3.7: "An approval requires a positive `provisional_invoice_cents` and advances `financing_status` `FUNDING_REQUESTED → FLOOR_PLAN_FUNDED`: the plant advances 9000 basis points of the provisional invoice, so `financed_principal_cents` is the provisional invoice multiplied by 9000, divided by 10000, and rounded half up to whole cents, and `funded_at` is stamped from the logical clock."

        Design: Difficulty/dual_variant_calc/invoice_provisional_at_submit_versus_final_at_ship_diverge_on_one_unit
        """
        _kit, order, build = canon_build_ready_to_ship()

        built_order = validate_success(api.get_unit_order(order["id"], plant_admin_headers))

        assert built_order["status"] == "BUILT"
        assert_cents(built_order["provisional_invoice_cents"], 16122725)
        assert built_order["final_invoice_cents"] is None
        assert_hours(built_order["required_station_hours"], "71.24")
        assert_cents(built_order["financed_principal_cents"], 14510453)

        built = validate_success(api.get_unit_build(build["id"], plant_admin_headers))
        assert built["current_station"] == "READY_TO_SHIP"
        assert_hours(built["actual_station_hours"], "75.00")
        assert built["rework_count"] == 1
        assert built["defect_points_total"] == 9


# ─── PRD §3.9 the two windowing variants of the trust score ────────────────


class TestSupplierScoreWindowVariants:
    def test_two_safety_events_aged_ninety_days_leave_rolling_at_100_and_lifetime_at_85(
        self, api, plant_admin_headers
    ):
        """PRD §3.9: "Under the **rolling** variant there is a hard 90-day cutoff and no decay: the penalty is the sum of the weights of events whose age is strictly less than 90 days. An event whose age is exactly 90 days is outside the window and contributes nothing at all."
        PRD §3.9: "Under the **lifetime** variant nothing is ever dropped: events younger than 90 days count at full weight, and events at or past 90 days keep half their weight, so the lifetime figure is at or below the rolling figure whenever any event has aged out."
        PRD §3.9: "The event set is the same for both: every campaign of that supplier whose `status` is `OPEN` or `CLOSED` and whose `opened_at` is not null, weighted by severity at 15.0 for `SAFETY`, 10.0 for `COMPLIANCE`, and 4.0 for `ADVISORY`, timestamped at `opened_at`; plus every `APPROVED` or `PAID` warranty claim whose component lot belongs to that supplier and whose `supplier_chargeback_cents` is positive, weighted at 2.0 and timestamped at the claim's `created_at`."
        PRD §3.9: "`Supplier.quality_score` always holds the **rolling** figure, and `supplier_status` is derived from it alone: a score of 70.00 or more is `ACTIVE`, a score from 50.00 up to but not including 70.00 is `PROBATION`, and anything below 50.00 is `SUSPENDED`."
        PRD §3.9: "It returns the `supplier_id`, the `rolling_quality_score`, the `lifetime_quality_score`, the current `supplier_status`, the `open_recall_count`, the `penalty_event_count`, and the `evaluated_at` instant at which the figures were computed."

        Design: Difficulty/dual_variant_calc/supplier_score_rolling_window_and_lifetime_decay_diverge_at_day_ninety
        """
        supplier = supplier_with_two_open_safety_campaigns()
        advance_clock("2026-10-30T00:00:00Z")

        scorecard = validate_success(
            api.get_supplier_scorecard(supplier["id"], plant_admin_headers)
        )

        assert_two_decimals(scorecard["rolling_quality_score"], "100.00")
        assert_two_decimals(scorecard["lifetime_quality_score"], "85.00")
        assert scorecard["supplier_status"] == "ACTIVE"
        assert scorecard["penalty_event_count"] == 2
        assert scorecard["open_recall_count"] == 2

        persisted = validate_success(api.get_supplier(supplier["id"], plant_admin_headers))
        assert_two_decimals(persisted["quality_score"], "100.00")

    def test_two_safety_events_aged_eighty_nine_days_are_still_inside_the_window(
        self, api, plant_admin_headers
    ):
        """PRD §3.9: "Under the **rolling** variant there is a hard 90-day cutoff and no decay: the penalty is the sum of the weights of events whose age is strictly less than 90 days. An event whose age is exactly 90 days is outside the window and contributes nothing at all."
        PRD §3.9: "Under the **lifetime** variant nothing is ever dropped: events younger than 90 days count at full weight, and events at or past 90 days keep half their weight, so the lifetime figure is at or below the rolling figure whenever any event has aged out."
        PRD §3.9: "Each event's age is the whole days between its timestamp and the logical clock, discarding any fractional remainder."
        PRD §3.9: "`Supplier.quality_score` always holds the **rolling** figure, and `supplier_status` is derived from it alone: a score of 70.00 or more is `ACTIVE`, a score from 50.00 up to but not including 70.00 is `PROBATION`, and anything below 50.00 is `SUSPENDED`."

        Design: Difficulty/dual_variant_calc/supplier_score_rolling_window_and_lifetime_decay_diverge_at_day_ninety
        """
        supplier = supplier_with_two_open_safety_campaigns()
        advance_clock("2026-10-29T00:00:00Z")

        scorecard = validate_success(
            api.get_supplier_scorecard(supplier["id"], plant_admin_headers)
        )

        assert_two_decimals(scorecard["rolling_quality_score"], "70.00")
        assert_two_decimals(scorecard["lifetime_quality_score"], "70.00")
        assert scorecard["supplier_status"] == "ACTIVE"
        assert scorecard["penalty_event_count"] == 2
        assert scorecard["open_recall_count"] == 2

        persisted = validate_success(api.get_supplier(supplier["id"], plant_admin_headers))
        assert_two_decimals(persisted["quality_score"], "70.00")

    def test_both_variants_read_seventy_on_the_day_the_two_campaigns_open(
        self, api, plant_admin_headers
    ):
        """PRD §3.9: "Under the **rolling** variant there is a hard 90-day cutoff and no decay: the penalty is the sum of the weights of events whose age is strictly less than 90 days."
        PRD §3.9: "Under the **lifetime** variant nothing is ever dropped: events younger than 90 days count at full weight, and events at or past 90 days keep half their weight, so the lifetime figure is at or below the rolling figure whenever any event has aged out."
        PRD §3.9: "Its `open_recall_count` increases by one, its `penalty_event_count` increases by one, and its `quality_score` and `supplier_status` are recomputed — which can drop it to `PROBATION` or `SUSPENDED` and thereby, in one stroke, remove its chassis from the matching pool of §3.4 and raise the chargeback rate applied to its warranty claims in §3.8."
        PRD §3.9: "`Supplier.quality_score` always holds the **rolling** figure, and `supplier_status` is derived from it alone: a score of 70.00 or more is `ACTIVE`, a score from 50.00 up to but not including 70.00 is `PROBATION`, and anything below 50.00 is `SUSPENDED`."

        Design: Difficulty/dual_variant_calc/supplier_score_rolling_window_and_lifetime_decay_diverge_at_day_ninety
        """
        supplier = supplier_with_two_open_safety_campaigns()

        scorecard = validate_success(
            api.get_supplier_scorecard(supplier["id"], plant_admin_headers)
        )

        assert_two_decimals(scorecard["rolling_quality_score"], "70.00")
        assert_two_decimals(scorecard["lifetime_quality_score"], "70.00")
        assert scorecard["supplier_status"] == "ACTIVE"
        assert scorecard["penalty_event_count"] == 2
        assert scorecard["open_recall_count"] == 2


# ─── PRD §3.7 per-line discount rounding ───────────────────────────────────


class TestPerLineDiscountRounding:
    def test_provisional_invoice_rounds_each_discount_line_before_summing(self, api):
        """PRD §2.6: "First, invoice discounts are computed and rounded **per line** before the lines are summed; totalling the raw discounted products and rounding once at the end produces a different figure and is incorrect."
        PRD §3.7: "Now discount each line **independently**: multiply the line's gross amount by 10000 minus its rate, divide by 10000, and round that line half up to whole cents."
        PRD §3.7: "Sum the rounded line amounts to obtain the discounted subtotal. Do not sum the raw products and round once — the per-line rounding boundary is part of the contract and the two approaches disagree by a few cents on a real configuration."
        PRD §3.7: "The base unit's rate comes from the order's `order_type`: a `STOCK` order discounts 2200 basis points, a `SOLD` order 2050, and a `DEMO` order 2600."
        PRD §3.7: "Each option's rate comes from its `category`: `APPLIANCE` discounts 1550 basis points, `PLUMBING` 1450, `ELECTRICAL` 1725, `EXTERIOR` 1600, `INTERIOR` 1350, and `CHASSIS_UPGRADE` 1250."
        PRD §3.7: "It is a base of 180000 cents, plus 4200 cents for each foot of the floor plan's `length_ft`, plus a regional surcharge drawn from the dealer's `region`: 95000 cents for `WEST`, nothing for `CENTRAL`, 60000 cents for `EAST`, and 35000 cents for `SOUTH`."
        PRD §3.2: "`option_price_total_cents` is the sum of `price_cents` across the selected options at list price."
        PRD §3.2: "An order that clears all of it is stamped: the roll-up is recomputed, `provisional_invoice_cents` is written, `locked_floor_plan_version` is pinned to the floor plan's current `version`, and `locked_option_versions` is pinned as one entry per selected option carrying that option's identifier, its `version`, and its `price_cents` at the moment of submit."

        Design: Difficulty/combinatorial_formula/invoice_rounds_each_discount_line_before_summing_costing_two_cents
        """
        floor_plan, options = publish_class_a_catalogue()
        dealer = create_dealer(**DEALER_WEST)
        order = five_option_order(dealer["id"], floor_plan["id"], five_option_ids(options))

        submitted = validate_success(
            api.submit_order(order["id"], make_dealer_principal_headers(dealer["id"]))
        )

        assert_cents(submitted["provisional_invoice_cents"], 16122725)
        assert submitted["provisional_invoice_cents"] != 16122723
        assert_cents(submitted["option_price_total_cents"], 1535500)
        assert submitted["status"] == "CONFIG_VALIDATED"
        assert submitted["locked_floor_plan_version"] == 1

    def test_resubmitted_configuration_reprices_to_the_same_per_line_rounded_invoice(
        self, api
    ):
        """PRD §3.2: "Replacement overwrites those two fields with the supplied values, re-runs the roll-up, and — when the order was `CONFIG_VALIDATED` — walks it back to `DRAFT`, clearing `locked_floor_plan_version`, emptying `locked_option_versions`, and resetting `provisional_invoice_cents` to 0."
        PRD §3.2: "This is the revision cycle: `CONFIG_VALIDATED → DRAFT → CONFIG_VALIDATED`, traversable as many times as the dealer needs."
        PRD §2.6: "First, invoice discounts are computed and rounded **per line** before the lines are summed; totalling the raw discounted products and rounding once at the end produces a different figure and is incorrect."
        PRD §3.7: "Now discount each line **independently**: multiply the line's gross amount by 10000 minus its rate, divide by 10000, and round that line half up to whole cents."
        PRD §3.2: "`option_price_total_cents` is the sum of `price_cents` across the selected options at list price."

        Design: Difficulty/combinatorial_formula/invoice_rounds_each_discount_line_before_summing_costing_two_cents
        """
        floor_plan, options = publish_class_a_catalogue()
        dealer = create_dealer(**DEALER_WEST)
        option_ids = five_option_ids(options)
        order = five_option_submitted_order(dealer["id"], floor_plan["id"], option_ids)
        assert_cents(order["provisional_invoice_cents"], 16122725)

        walked_back = replace_configuration(order["id"], dealer["id"], option_ids)
        assert walked_back["status"] == "DRAFT"
        assert_cents(walked_back["provisional_invoice_cents"], 0)

        resubmitted = validate_success(
            api.submit_order(order["id"], make_dealer_principal_headers(dealer["id"]))
        )

        assert_cents(resubmitted["provisional_invoice_cents"], 16122725)
        assert resubmitted["provisional_invoice_cents"] != 16122723
        assert_cents(resubmitted["option_price_total_cents"], 1535500)
        assert resubmitted["status"] == "CONFIG_VALIDATED"
        assert resubmitted["locked_floor_plan_version"] == 1


# ─── PRD §3.8 the seven-step reimbursement waterfall ───────────────────────


class TestWarrantyWaterfallOrder:
    def test_approval_derives_tier_from_the_subtotal_and_chargeback_from_the_total(
        self, api, plant_admin_headers
    ):
        """PRD §3.8: "The **reimbursement waterfall** is seven steps that must execute in the written order, because two of its ceilings read values produced by earlier steps."
        PRD §3.8: "The billable hours are the lesser of the claimed `labor_hours` and 8.0 hours."
        PRD §3.8: "Multiply the billable hours by the flat rate for the claim's `claim_type` — 7800 cents per hour for `APPLIANCE`, 8600 for `PLUMBING`, 9200 for `ELECTRICAL`, 10400 for `STRUCTURAL`, and 11000 for `WATER_INTRUSION` — and round half up to whole cents."
        PRD §3.8: "Multiply `parts_cost_cents` by 11500, divide by 10000, and round half up to whole cents."
        PRD §3.8: "The `authority_tier` is chosen **from** that subtotal, so it can never be settled before labour and parts are known: a subtotal at or below 150000 cents is `TIER_A`, a subtotal above that but at or below 750000 cents is `TIER_B`, and anything above 750000 cents is `TIER_C`."
        PRD §3.8: "The candidates are the dealer's `goodwill_requested_cents`; the tier ceiling, which is 75000 cents for `TIER_A`, 150000 cents for `TIER_B`, and zero for `TIER_C` — the largest claims carry no goodwill authority at all; the percentage ceiling, which is 2000 basis points of the step-3 subtotal, computed by multiplying the subtotal by 2000, dividing by 10000, and rounding half up to whole cents; and the dealer's remaining budget, which is its `goodwill_budget_cents` minus its `goodwill_used_cents`."
        PRD §3.8: "The total paid to the dealer is the schedule subtotal plus `goodwill_authorized_cents` — under the in-warranty variant."
        PRD §3.8: "The supplier chargeback is a percentage **of** the step-6 total, scaled by how much the plant currently trusts the supplier."
        PRD §3.8: "Otherwise take the `supplier_status` of the lot's supplier and apply its rate to the total: 6000 basis points for `ACTIVE`, 8000 for `PROBATION`, and 10000 for `SUSPENDED`."
        PRD §3.8: "When the resulting `supplier_chargeback_cents` is positive, the claim itself becomes a penalty event against the lot's supplier: that supplier's `penalty_event_count` increases by one and its `quality_score` and `supplier_status` are recomputed."

        Design: Difficulty/combinatorial_formula/warranty_reimbursement_tier_and_goodwill_and_chargeback_pin_evaluation_order
        """
        world = delivered_unit_for_appliance_claim()
        claim = file_claim(
            world["dealer"]["id"],
            world["build"]["id"],
            component_lot_id=world["lot"]["id"],
            **APPLIANCE_CLAIM,
        )

        decided = validate_success(
            api.decide_claim(claim["id"], {"decision": "APPROVED"}, WARRANTY_CAROL)
        )

        assert_cents(decided["labor_reimbursement_cents"], 27300)
        assert_cents(decided["parts_reimbursement_cents"], 78200)
        assert decided["authority_tier"] == "TIER_A"
        assert_cents(decided["goodwill_authorized_cents"], 21100)
        assert_cents(decided["total_reimbursement_cents"], 126600)
        assert_cents(decided["supplier_chargeback_cents"], 75960)
        assert decided["status"] == "APPROVED"
        assert decided["in_warranty"] is True

        dealer = validate_success(
            api.get_dealer(world["dealer"]["id"], plant_admin_headers)
        )
        assert_cents(dealer["goodwill_used_cents"], 21100)

        supplier = validate_success(
            api.get_supplier(world["supplier"]["id"], plant_admin_headers)
        )
        assert supplier["penalty_event_count"] == 1
        assert_two_decimals(supplier["quality_score"], "98.00")

    def test_filing_previews_labor_parts_and_tier_but_holds_goodwill_and_chargeback_at_zero(
        self, api, plant_admin_headers
    ):
        """PRD §3.8: "Filing a claim previews steps 1 through 4 and step 7's structure, writing `labor_reimbursement_cents` and `parts_reimbursement_cents`; `goodwill_authorized_cents`, `total_reimbursement_cents`, and `supplier_chargeback_cents` all stay at zero until a decision is made."
        PRD §3.8: "The billable hours are the lesser of the claimed `labor_hours` and 8.0 hours."
        PRD §3.8: "Multiply `parts_cost_cents` by 11500, divide by 10000, and round half up to whole cents."
        PRD §3.8: "The `authority_tier` is chosen **from** that subtotal, so it can never be settled before labour and parts are known: a subtotal at or below 150000 cents is `TIER_A`, a subtotal above that but at or below 750000 cents is `TIER_B`, and anything above 750000 cents is `TIER_C`."
        PRD §3.8: "The claim starts at `status` `SUBMITTED` with `denial_reason` null, `info_request_count` 0, `resubmission_count` 0, and both `approved_by_user_id` and `paid_by_user_id` null."
        PRD §3.8: "At filing, `in_warranty` is set true when the logical clock is within that period of `shipped_at` and false otherwise, and that single boolean selects which of the two reimbursement variants governs the payout."
        PRD §3.8: "When the resulting `supplier_chargeback_cents` is positive, the claim itself becomes a penalty event against the lot's supplier: that supplier's `penalty_event_count` increases by one and its `quality_score` and `supplier_status` are recomputed."

        Design: Difficulty/combinatorial_formula/warranty_reimbursement_tier_and_goodwill_and_chargeback_pin_evaluation_order
        """
        world = delivered_unit_for_appliance_claim()
        payload = {
            "unit_build_id": world["build"]["id"],
            "component_lot_id": world["lot"]["id"],
            **APPLIANCE_CLAIM,
        }

        filed = validate_success(
            api.create_warranty_claim(
                payload, make_dealer_principal_headers(world["dealer"]["id"])
            ),
            201,
        )

        assert_cents(filed["labor_reimbursement_cents"], 27300)
        assert_cents(filed["parts_reimbursement_cents"], 78200)
        assert filed["authority_tier"] == "TIER_A"
        assert_cents(filed["goodwill_authorized_cents"], 0)
        assert_cents(filed["total_reimbursement_cents"], 0)
        assert_cents(filed["supplier_chargeback_cents"], 0)
        assert filed["status"] == "SUBMITTED"
        assert filed["in_warranty"] is True

        dealer = validate_success(
            api.get_dealer(world["dealer"]["id"], plant_admin_headers)
        )
        assert_cents(dealer["goodwill_used_cents"], 0)

        supplier = validate_success(
            api.get_supplier(world["supplier"]["id"], plant_admin_headers)
        )
        assert supplier["penalty_event_count"] == 0
        assert_two_decimals(supplier["quality_score"], "100.00")


# ─── PRD §3.7 the credit-utilisation boundary ──────────────────────────────


class TestCreditUtilizationBoundary:
    def test_utilization_9500_is_watch_while_9501_is_credit_hold(
        self, api, plant_admin_headers
    ):
        """PRD §3.7: "A dealer's `financed_exposure_cents` is the sum, across every one of its orders whose `financing_status` is `FLOOR_PLAN_FUNDED` or `CURTAILED`, of that order's `financed_principal_cents` minus its `curtailment_paid_cents`."
        PRD §3.7: "Its `credit_utilization_bp` is that exposure multiplied by 10000 and divided by its `floor_plan_credit_limit_cents`, truncated toward zero to a whole number of basis points — and zero when the credit limit is zero."
        PRD §3.7: "Its `credit_status` follows from two strictly-greater-than comparisons: utilisation above 9500 basis points is `CREDIT_HOLD`, utilisation above 8000 basis points (but not above 9500) is `WATCH`, and anything at or below 8000 is `GOOD_STANDING`. Because both comparisons are strict, exactly 9500 basis points is `WATCH` and 9501 is `CREDIT_HOLD`."
        PRD §3.7: "An approval requires a positive `provisional_invoice_cents` and advances `financing_status` `FUNDING_REQUESTED → FLOOR_PLAN_FUNDED`: the plant advances 9000 basis points of the provisional invoice, so `financed_principal_cents` is the provisional invoice multiplied by 9000, divided by 10000, and rounded half up to whole cents, and `funded_at` is stamped from the logical clock."

        Design: Difficulty/boundary_precision_check/credit_utilization_boundary_9500_is_watch_and_9501_is_credit_hold
        """
        floor_plan, options = publish_class_a_catalogue()
        option_ids = five_option_ids(options)
        dealer_a = create_dealer(
            dealer_code="D-EDGE-A",
            region="WEST",
            allocation_share_bp=1500,
            floor_plan_credit_limit_cents=15274000,
            goodwill_budget_cents=500000,
        )
        dealer_b = create_dealer(
            dealer_code="D-EDGE-B",
            region="WEST",
            allocation_share_bp=1500,
            floor_plan_credit_limit_cents=15272000,
            goodwill_budget_cents=500000,
        )
        order_a = five_option_submitted_order(dealer_a["id"], floor_plan["id"], option_ids)
        request_funding(order_a["id"], dealer_a["id"])
        order_b = five_option_submitted_order(dealer_b["id"], floor_plan["id"], option_ids)
        request_funding(order_b["id"], dealer_b["id"])

        funded_a = validate_success(
            api.funding_decision(order_a["id"], {"decision": "APPROVED"}, plant_admin_headers)
        )
        funded_b = validate_success(
            api.funding_decision(order_b["id"], {"decision": "APPROVED"}, plant_admin_headers)
        )

        assert_cents(funded_a["financed_principal_cents"], 14510453)
        assert_cents(funded_b["financed_principal_cents"], 14510453)

        read_a = validate_success(api.get_dealer(dealer_a["id"], plant_admin_headers))
        assert_cents(read_a["financed_exposure_cents"], 14510453)
        assert read_a["credit_utilization_bp"] == 9500
        assert read_a["credit_status"] == "WATCH"

        read_b = validate_success(api.get_dealer(dealer_b["id"], plant_admin_headers))
        assert_cents(read_b["financed_exposure_cents"], 14510453)
        assert read_b["credit_utilization_bp"] == 9501
        assert read_b["credit_status"] == "CREDIT_HOLD"

        assert funded_a["financing_status"] == "FLOOR_PLAN_FUNDED"
        assert funded_b["financing_status"] == "FLOOR_PLAN_FUNDED"
        assert funded_a["funded_at"].startswith("2026-08-01T00:00:00")

    def test_only_funded_principal_counts_so_the_unfunded_twin_stays_good_standing(
        self, api, plant_admin_headers
    ):
        """PRD §3.7: "A dealer's `financed_exposure_cents` is the sum, across every one of its orders whose `financing_status` is `FLOOR_PLAN_FUNDED` or `CURTAILED`, of that order's `financed_principal_cents` minus its `curtailment_paid_cents`."
        PRD §3.7: "Its `credit_utilization_bp` is that exposure multiplied by 10000 and divided by its `floor_plan_credit_limit_cents`, truncated toward zero to a whole number of basis points — and zero when the credit limit is zero."
        PRD §3.7: "Its `credit_status` follows from two strictly-greater-than comparisons: utilisation above 9500 basis points is `CREDIT_HOLD`, utilisation above 8000 basis points (but not above 9500) is `WATCH`, and anything at or below 8000 is `GOOD_STANDING`. Because both comparisons are strict, exactly 9500 basis points is `WATCH` and 9501 is `CREDIT_HOLD`."
        PRD §3.1: "A dealer's derived position — `financed_exposure_cents`, `credit_utilization_bp`, `credit_status` (initialised to `GOOD_STANDING`), `goodwill_used_cents`, `entitlement_hours`, `allocation_hours_consumed`, and `allocation_slots_reserved` — is recomputed whenever the dealer record is read, so a read is always current."

        Design: Difficulty/boundary_precision_check/credit_utilization_boundary_9500_is_watch_and_9501_is_credit_hold
        """
        floor_plan, options = publish_class_a_catalogue()
        option_ids = five_option_ids(options)
        dealer_a = create_dealer(
            dealer_code="D-EDGE-A",
            region="WEST",
            allocation_share_bp=1500,
            floor_plan_credit_limit_cents=15274000,
            goodwill_budget_cents=500000,
        )
        dealer_b = create_dealer(
            dealer_code="D-EDGE-B",
            region="WEST",
            allocation_share_bp=1500,
            floor_plan_credit_limit_cents=15272000,
            goodwill_budget_cents=500000,
        )
        order_a = five_option_submitted_order(dealer_a["id"], floor_plan["id"], option_ids)
        request_funding(order_a["id"], dealer_a["id"])
        order_b = five_option_submitted_order(dealer_b["id"], floor_plan["id"], option_ids)
        request_funding(order_b["id"], dealer_b["id"])

        funded_a = validate_success(
            api.funding_decision(order_a["id"], {"decision": "APPROVED"}, plant_admin_headers)
        )

        assert_cents(funded_a["financed_principal_cents"], 14510453)
        assert funded_a["financing_status"] == "FLOOR_PLAN_FUNDED"

        read_a = validate_success(api.get_dealer(dealer_a["id"], plant_admin_headers))
        assert_cents(read_a["financed_exposure_cents"], 14510453)
        assert read_a["credit_utilization_bp"] == 9500
        assert read_a["credit_status"] == "WATCH"

        pending_b = validate_success(api.get_unit_order(order_b["id"], plant_admin_headers))
        assert pending_b["financing_status"] == "FUNDING_REQUESTED"
        read_b = validate_success(api.get_dealer(dealer_b["id"], plant_admin_headers))
        assert_cents(read_b["financed_exposure_cents"], 0)
        assert read_b["credit_utilization_bp"] == 0
        assert read_b["credit_status"] == "GOOD_STANDING"


# ─── PRD §3.4 the chassis GVWR margin boundary ─────────────────────────────


class TestChassisGvwrMarginBoundary:
    def test_matching_admits_the_23420_chassis_and_skips_the_23419_candidate(
        self, api, plant_admin_headers, scheduler_headers
    ):
        """PRD §3.4: "Its `gvwr_lbs` must be at least the order's `config_weight_lbs` plus a 500-pound safety margin."
        PRD §3.4: "Among the eligible candidates the winner is chosen by three ordered keys."
        PRD §3.4: "The winning chassis moves `RECEIVED → MATCHED` with `matched_unit_order_id` set to the order."
        PRD §3.4: "Matching is available while the order's `status` is `CONFIG_VALIDATED` or `SLOTTED`, and only when no other chassis already names this order in its `matched_unit_order_id`; an order that already holds a matched or installed chassis is rejected with `ERR_ORDER_ALREADY_MATCHED`."
        PRD §3.2: "`config_weight_lbs` is the floor plan's `base_dry_weight_lbs` plus the sum of `weight_lbs` across the selected options."

        Design: Difficulty/boundary_precision_check/chassis_gvwr_margin_boundary_admits_23420_and_skips_23419
        """
        supplier = create_supplier(
            supplier_code="SUP-CH",
            name="Cascade Chassis Works",
            component_categories=["CHASSIS"],
        )
        floor_plan, options = publish_class_a_catalogue()
        dealer = create_dealer(
            dealer_code="D-BIG",
            region="WEST",
            allocation_share_bp=1500,
            floor_plan_credit_limit_cents=100000000,
            goodwill_budget_cents=500000,
        )
        chassis_low = create_chassis_receipt(
            supplier["id"],
            chassis_serial="CH-LOW",
            chassis_class="CLASS_A",
            gvwr_lbs=23419,
            wheelbase_in=242,
        )
        chassis_exact = create_chassis_receipt(
            supplier["id"],
            chassis_serial="CH-EXACT",
            chassis_class="CLASS_A",
            gvwr_lbs=23420,
            wheelbase_in=242,
        )
        order = five_option_submitted_order(
            dealer["id"], floor_plan["id"], five_option_ids(options)
        )

        matched = validate_success(api.match_chassis(order["id"], scheduler_headers))

        assert matched["id"] == chassis_exact["id"]
        assert matched["chassis_serial"] == "CH-EXACT"

        winner = validate_success(
            api.get_chassis_receipt(chassis_exact["id"], plant_admin_headers)
        )
        assert winner["status"] == "MATCHED"
        assert winner["matched_unit_order_id"] == order["id"]

        skipped = validate_success(
            api.get_chassis_receipt(chassis_low["id"], plant_admin_headers)
        )
        assert skipped["status"] == "RECEIVED"
        assert skipped["matched_unit_order_id"] is None

        read_order = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
        assert read_order["config_weight_lbs"] == 22920
        assert read_order["status"] == "CONFIG_VALIDATED"

    def test_a_lone_candidate_one_pound_short_of_the_margin_matches_nothing(
        self, api, plant_admin_headers, scheduler_headers
    ):
        """PRD §3.4: "Its `gvwr_lbs` must be at least the order's `config_weight_lbs` plus a 500-pound safety margin."
        PRD §3.4: "When the eligible set is empty the request is rejected with `ERR_NO_MATCHING_CHASSIS`."
        PRD §3.2: "`config_weight_lbs` is the floor plan's `base_dry_weight_lbs` plus the sum of `weight_lbs` across the selected options."

        Design: Difficulty/boundary_precision_check/chassis_gvwr_margin_boundary_admits_23420_and_skips_23419
        """
        supplier = create_supplier(
            supplier_code="SUP-CH",
            name="Cascade Chassis Works",
            component_categories=["CHASSIS"],
        )
        floor_plan, options = publish_class_a_catalogue()
        dealer = create_dealer(
            dealer_code="D-BIG",
            region="WEST",
            allocation_share_bp=1500,
            floor_plan_credit_limit_cents=100000000,
            goodwill_budget_cents=500000,
        )
        chassis_low = create_chassis_receipt(
            supplier["id"],
            chassis_serial="CH-LOW",
            chassis_class="CLASS_A",
            gvwr_lbs=23419,
            wheelbase_in=242,
        )
        order = five_option_submitted_order(
            dealer["id"], floor_plan["id"], five_option_ids(options)
        )

        validate_error(
            api.match_chassis(order["id"], scheduler_headers),
            ApiErrorId.ERR_NO_MATCHING_CHASSIS,
        )

        skipped = validate_success(
            api.get_chassis_receipt(chassis_low["id"], plant_admin_headers)
        )
        assert skipped["status"] == "RECEIVED"
        assert skipped["matched_unit_order_id"] is None

        read_order = validate_success(api.get_unit_order(order["id"], plant_admin_headers))
        assert read_order["config_weight_lbs"] == 22920
        assert read_order["status"] == "CONFIG_VALIDATED"
