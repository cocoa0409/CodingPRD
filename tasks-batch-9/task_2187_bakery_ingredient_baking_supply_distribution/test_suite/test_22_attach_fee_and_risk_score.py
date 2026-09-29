"""The marginally tiered attach fee and the pounds-weighted allergen score (PRD §3.7, §3.9)."""

from test_helpers import (
    add_order_line,
    allocate_order,
    cancel_order,
    create_customer,
    create_product,
    create_zone,
    log_hours,
    open_engagement,
    open_order,
    read_customer,
    read_engagement,
    read_order,
    read_order_line,
    receive_lot,
    set_clock,
    submit_order,
)

EPOCH = "2026-08-01T00:00:00Z"

TECH_FLOUR = {
    "sku": "FLR-TECH-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 180,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}
PEANUT_PASTE_25 = {
    "sku": "NUT-PEA-25",
    "category": "INCLUSION",
    "allergen_class": "PEANUT",
    "shelf_life_days": 200,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}
GLUTEN_FLOUR_30 = {
    "sku": "FLR-GLU-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 180,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}


def _bakery():
    set_clock(EPOCH)
    return create_customer(credit_limit_cents=10000000, min_drop_cents=1000)


def _stocked(product_spec, zone_code, quantity_received_lb=20000, lot_code="LOT-0001"):
    product = create_product(product_spec)
    zone = create_zone(zone_code=zone_code, allergen_class=product_spec["allergen_class"])
    lot = receive_lot(
        product["id"], zone["id"], lot_code=lot_code,
        manufactured_on="2026-07-01T00:00:00Z",
        quantity_received_lb=quantity_received_lb,
    )
    return product, zone, lot


class TestAttachFeeBands:
    """Two free hours, eight at the high rate, the rest at the low one."""

    def test_twelve_logged_hours_bill_eight_high_hours_and_two_low_ones(self):
        """PRD §3.9: "The first four hours are the qualifying threshold — the moment
        `hours_logged` reaches 4.0, the boundary being inclusive, an `OPEN` engagement
        moves itself to `BILLABLE` and the attach fee is computed."

        PRD §3.9: "The first two logged hours are included at no charge, so billable
        hours are `hours_logged` less two, floored at zero. Of those billable hours,
        the first eight bill at one hundred eighty-five dollars per hour — 18500 cents
        — and every billable hour beyond the eighth bills at the lower rate of one
        hundred forty-five dollars per hour, or 14500 cents."

        PRD §3.9: "for `GREEN` and `AMBER` accounts the multiplier is one"

        Design: Corner/calculations/corner_calc_attach_fee_marginal_tiers_after_included_hours
        """
        customer = _bakery()
        flour = create_product(TECH_FLOUR)
        engagement = open_engagement(customer, flour["id"])
        log_hours(engagement["id"], 3.5, work_note="Dough rheology bench trial")
        before = read_engagement(engagement["id"])
        assert before["status"] == "OPEN", (
            f"3.5 hours has not reached the 4.0 threshold, got {before['status']}"
        )
        assert before["attach_fee_cents"] == 0, (
            f"An OPEN engagement carries no fee yet, got {before['attach_fee_cents']}"
        )

        after = log_hours(
            engagement["id"], 8.5,
            work_note="Plant line trial and formulation sign-off",
        )

        assert float(after["hours_logged"]) == 12.0, (
            f"Expected 3.5 + 8.5 hours, got {after['hours_logged']}"
        )
        assert after["status"] == "BILLABLE", (
            f"Expected BILLABLE, got {after['status']}"
        )
        assert after["attach_fee_cents"] == 177000, (
            f"Expected 8 x 18500 plus 2 x 14500, got {after['attach_fee_cents']}"
        )
        assert after["order_id"] is None, (
            f"The fee is computed long before any order is named, got {after['order_id']}"
        )
        assert after["assigned_specialist_user_id"] == "ts-1", (
            f"Expected the opening specialist, got {after['assigned_specialist_user_id']}"
        )


class TestRedTierMultiplier:
    """A `RED` account pays a quarter more, and the multiplier lands after the bands."""

    def test_a_peanut_only_account_pays_the_uplifted_fee_while_the_order_stays_at_zero(self):
        """PRD §3.7: "`PEANUT` weighs the full 1.00" ... "`RED` at 60.00 and above."

        PRD §3.9: "A risk multiplier then applies: when the owning bakery's
        `risk_tier` as persisted at computation time reads `RED`, the gross is
        multiplied by one and a quarter, reflecting the additional oversight a
        high-exposure allergen account demands"

        PRD §3.4: "The attach fee is read from `tech_attach_fee_cents` as it stands at
        the moment of the pricing event, and it is 0 until a support engagement has
        been attached to the order as described in §3.9."

        Design: Corner/calculations/corner_calc_red_tier_multiplier_applied_after_gross_fee
        """
        customer = _bakery()
        peanut, _zone, _lot = _stocked(PEANUT_PASTE_25, "Z-PEA", lot_code="LOT-PN-0001")
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-05T00:00:00Z",
        )
        add_order_line(customer, order["id"], peanut["id"], 1000)
        submit_order(customer, order["id"])
        allocate_order(order["id"])
        engagement = open_engagement(customer, peanut["id"])

        billed = log_hours(
            engagement["id"], 5.0, work_note="Peanut inclusion dispersion study"
        )

        scored = read_customer(customer["id"])
        assert float(scored["allergen_risk_score"]) == 100.00, (
            f"A peanut-only in-flight set scores the ceiling, got {scored['allergen_risk_score']}"
        )
        assert scored["risk_tier"] == "RED", (
            f"Expected RED, got {scored['risk_tier']}"
        )
        assert float(billed["hours_logged"]) == 5.0, (
            f"Expected 5.0 hours, got {billed['hours_logged']}"
        )
        assert billed["status"] == "BILLABLE", (
            f"Expected BILLABLE, got {billed['status']}"
        )
        assert billed["attach_fee_cents"] == 69375, (
            f"Expected 3 x 18500 uplifted by a quarter, not the flat 55500, got "
            f"{billed['attach_fee_cents']}"
        )
        assert read_order(order["id"])["tech_attach_fee_cents"] == 0, (
            "No fee lands on the order until the engagement is attached to it"
        )


class TestCancelledLinesLeaveTheInputSet:
    """A cancelled peanut order stops counting the instant it is cancelled."""

    def test_the_score_reads_gluten_only_even_though_peanut_pounds_were_once_ordered(self):
        """PRD §3.7: "Both variants exclude the same two things: order lines belonging
        to orders whose `fulfillment_status` is `CANCELLED`, and order lines whose
        `allocation_status` is `RELEASED`."

        PRD §3.3: "Cancellation drives both dimensions at once: `fulfillment_status`
        becomes `CANCELLED` and `pricing_status` becomes `VOID` — a transition
        available from either `UNPRICED` or `PROVISIONAL`."

        A combined set of 1000 lb peanut and 1000 lb gluten would average to 77.50 and
        tip the account to `RED`; the exclusion leaves the gluten weight standing alone.

        Design: Corner/calculations/corner_calc_risk_score_excludes_cancelled_order_lines
        """
        customer = _bakery()
        peanut, _pz, _pl = _stocked(PEANUT_PASTE_25, "Z-PEA", lot_code="LOT-PN-0001")
        flour, _gz, gluten_lot = _stocked(
            GLUTEN_FLOUR_30, "Z-GLU", lot_code="LOT-GL-0001"
        )
        peanut_order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-05T00:00:00Z",
        )
        add_order_line(customer, peanut_order["id"], peanut["id"], 1000)
        submit_order(customer, peanut_order["id"])
        cancel_order(
            customer, peanut_order["id"],
            cancellation_reason="Bakery dropped the peanut inclusion line",
        )
        gluten_order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-06T00:00:00Z",
        )
        gluten_line = add_order_line(customer, gluten_order["id"], flour["id"], 1000)
        submit_order(customer, gluten_order["id"])

        allocated = allocate_order(gluten_order["id"])

        scored = read_customer(customer["id"])
        assert float(scored["allergen_risk_score"]) == 55.00, (
            f"Expected the gluten weight of 0.55 alone, got {scored['allergen_risk_score']}"
        )
        assert scored["risk_tier"] == "AMBER", (
            f"Expected AMBER rather than the RED a combined set would give, got "
            f"{scored['risk_tier']}"
        )
        dropped = read_order(peanut_order["id"])
        assert dropped["fulfillment_status"] == "CANCELLED", (
            f"Expected CANCELLED, got {dropped['fulfillment_status']}"
        )
        assert dropped["pricing_status"] == "VOID", (
            f"Expected VOID, got {dropped['pricing_status']}"
        )
        assert allocated["fulfillment_status"] == "ALLOCATED", (
            f"Expected ALLOCATED, got {allocated['fulfillment_status']}"
        )
        assert read_order_line(gluten_line["id"])["lot_id"] == gluten_lot["id"], (
            "The gluten line draws from the only gluten lot"
        )
        assert scored["open_exposure_cents"] == 30750, (
            f"The cancelled order contributes 0, so expected 30750, got "
            f"{scored['open_exposure_cents']}"
        )


class TestWeightedAverageRounding:
    """Pounds do the weighting, and the single rounding is half-up to two places."""

    def test_a_three_allergen_mix_persists_twenty_nine_point_five_three(self):
        """PRD §3.7: "The score is a pounds-weighted average of allergen severity,
        expressed on a nought-to-one-hundred scale. Each allergen class carries a
        weight: `NONE` weighs nothing at all, `SOY` weighs 0.20, `EGG` weighs 0.35,
        `DAIRY` weighs 0.40, `GLUTEN` weighs 0.55, `TREE_NUT` weighs 0.90, and
        `PEANUT` weighs the full 1.00. For the input set of order lines described
        below, the engine totals each line's weight multiplied by its `quantity_lb`,
        divides that by the total of `quantity_lb` across the same lines" ... "and
        multiplies by one hundred."

        PRD §3.7: "The sum is rounded half-up to two decimal places, once, after the
        penalty has been added" ... "`AMBER` from 25.00 up to but not including 60.00"

        1000 lb of dairy, 1500 of soy and 700 of egg weigh 945 pounds-of-severity
        against 3200 pounds, which is 29.53125 — a pounds-agnostic average of the three
        weights would read 31.67 instead.

        Design: Corner/calculations/corner_calc_risk_score_weighted_average_rounds_half_up_to_two_dp
        """
        customer = _bakery()
        dairy, _dz, dairy_lot = _stocked(
            {**GLUTEN_FLOUR_30, "sku": "DRY-MIX-30", "category": "INCLUSION",
             "allergen_class": "DAIRY", "shelf_life_days": 150},
            "Z-DRY", lot_code="LOT-D-0001",
        )
        soy, _sz, soy_lot = _stocked(
            {**GLUTEN_FLOUR_30, "sku": "SOY-MIX-30", "category": "FAT",
             "allergen_class": "SOY", "shelf_life_days": 150},
            "Z-SOY", lot_code="LOT-S-0001",
        )
        egg, _ez, egg_lot = _stocked(
            {**GLUTEN_FLOUR_30, "sku": "EGG-MIX-30", "category": "INCLUSION",
             "allergen_class": "EGG", "shelf_life_days": 150},
            "Z-EGG", lot_code="LOT-E-0001",
        )
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on="2026-09-05T00:00:00Z",
        )
        dairy_line = add_order_line(customer, order["id"], dairy["id"], 1000)
        soy_line = add_order_line(customer, order["id"], soy["id"], 1500)
        egg_line = add_order_line(customer, order["id"], egg["id"], 700)
        submit_order(customer, order["id"])

        allocated = allocate_order(order["id"])

        mixed = read_customer(customer["id"])
        assert float(mixed["allergen_risk_score"]) == 29.53, (
            f"Expected 29.53125 rounded half-up to 29.53, got {mixed['allergen_risk_score']}"
        )
        assert mixed["risk_tier"] == "AMBER", (
            f"Expected AMBER, got {mixed['risk_tier']}"
        )
        assert read_order_line(dairy_line["id"])["lot_id"] == dairy_lot["id"], (
            "Each line must draw from its own allergen-matched zone"
        )
        assert read_order_line(soy_line["id"])["lot_id"] == soy_lot["id"]
        assert read_order_line(egg_line["id"])["lot_id"] == egg_lot["id"]
        assert allocated["fulfillment_status"] == "ALLOCATED", (
            f"Expected ALLOCATED, got {allocated['fulfillment_status']}"
        )
