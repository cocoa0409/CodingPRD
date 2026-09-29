"""The billing threshold, the unsplittable line and the five-hop approval (PRD §3.5, §3.7, §3.8, §3.11)."""

from test_helpers import (
    ApiErrorId,
    add_order_line,
    allocate_order,
    api_client,
    approve_substitution_request,
    claim_substitution_request,
    create_customer,
    create_product,
    create_zone,
    log_hours,
    open_engagement,
    open_order,
    raise_substitution_request,
    read_customer,
    read_engagement,
    read_lot,
    read_order,
    read_order_line,
    read_substitution_request,
    receive_lot,
    set_clock,
    submit_order,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import QM, WO

EPOCH = "2026-08-01T00:00:00Z"
SERVICE_ON = "2026-09-10T00:00:00Z"

FLOUR_30 = {
    "sku": "FLR-THR-30",
    "category": "FLOUR",
    "allergen_class": "GLUTEN",
    "shelf_life_days": 365,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}


class TestTheBillingThresholdIsOnTheAccumulatedTotal:
    """Three postings of 3.9 hours bill nothing; the 0.1 that lands on 4.0 does."""

    def test_the_posting_that_reaches_four_hours_flips_the_engagement_and_prices_it(self):
        """PRD §3.11: "Bench time is posted incrementally: each posting carries an `hours`
        figure strictly greater than zero and an optional `work_note`, and it adds to the
        running `hours_logged`, which is carried at one decimal place. The first four hours
        are the qualifying threshold — the moment `hours_logged` reaches 4.0, the boundary
        being inclusive, an `OPEN` engagement moves itself to `BILLABLE` and the attach fee
        is computed. Every subsequent posting while the engagement is `BILLABLE` recomputes
        the fee."

        PRD §3.11: "The first two logged hours are included at no charge, so billable hours
        are `hours_logged` less two, floored at zero. Of those billable hours, the first
        eight bill at one hundred eighty-five dollars per hour — 18500 cents — and every
        billable hour beyond the eighth bills at the lower rate of one hundred forty-five
        dollars per hour, or 14500 cents."

        PRD §3.11: "The engagement begins with `status` at `OPEN`, `hours_logged` at 0,
        `attach_fee_cents` at 0, `order_id` null, and `assigned_specialist_user_id` set to
        the acting specialist's `X-User-ID`."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_hours_threshold_flips_engagement_exactly_at_four_hours
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(dict(FLOUR_30, sku="FLR-THR-30"))
        engagement = open_engagement(customer, flour["id"])
        log_hours(engagement["id"], 1.5, work_note="Dough rheology bench work")
        log_hours(engagement["id"], 1.5, work_note="Proof box trials")
        just_below = log_hours(engagement["id"], 0.9, work_note="Crumb scoring")
        assert float(just_below["hours_logged"]) == 3.9, (
            f"Expected 3.9 hours logged, got {just_below['hours_logged']}"
        )
        assert just_below["status"] == "OPEN", (
            f"One tenth short of the threshold, so expected OPEN, got "
            f"{just_below['status']}"
        )
        assert just_below["attach_fee_cents"] == 0, (
            f"Nothing is billed below the threshold, got "
            f"{just_below['attach_fee_cents']}"
        )

        billable = log_hours(
            engagement["id"], 0.1,
            work_note="Final write-up crossing the billing threshold",
        )

        assert float(billable["hours_logged"]) == 4.0, (
            f"Expected 4.0 hours logged, got {billable['hours_logged']}"
        )
        assert billable["status"] == "BILLABLE", (
            f"The boundary is inclusive, so expected BILLABLE, got "
            f"{billable['status']}"
        )
        assert billable["attach_fee_cents"] == 37000, (
            f"Expected 2.0 billable hours at 18500, got {billable['attach_fee_cents']}"
        )
        assert billable["order_id"] is None, (
            f"The fee only lands on an order at attach time, got {billable['order_id']}"
        )
        assert read_customer(customer["id"])["risk_tier"] == "GREEN", (
            "No allergen pounds are in flight, so no RED multiplier applies"
        )

        recomputed = log_hours(
            engagement["id"], 0.5, work_note="Follow-up scaling run"
        )

        assert recomputed["attach_fee_cents"] == 46250, (
            f"Expected 2.5 billable hours at 18500, got "
            f"{recomputed['attach_fee_cents']}"
        )
        assert read_engagement(engagement["id"])["status"] == "BILLABLE", (
            "A further posting does not move the engagement on again"
        )


class TestALineIsNeverSplitAcrossTwoLots:
    """Ten thousand pounds on hand across two lots will not fill a nine-thousand line."""

    def test_the_pair_is_refused_and_a_single_larger_lot_wins_over_the_fefo_earliest(self):
        """PRD §3.5: "Splitting a line across two lots is not permitted — one lot must
        cover the whole line by itself — which is precisely why the on-hand test above is
        stated against the full line quantity. If the candidate set is empty for any line,
        the operation is rejected with `ERR_NO_ELIGIBLE_LOT` (HTTP 409)."

        PRD §3.5: "Among the candidates, ranking is First-Expired-First-Out: the earliest
        `expires_on` wins."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_selector_refuses_to_split_a_line_across_two_lots
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=10000000, min_drop_cents=1000)
        flour = create_product(
            dict(FLOUR_30, sku="FLR-NSP-30", shelf_life_days=180)
        )
        zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        early = receive_lot(
            flour["id"], zone["id"], lot_code="LOT-NSP-EARLY",
            manufactured_on="2026-06-01T00:00:00Z", quantity_received_lb=5000,
        )
        late = receive_lot(
            flour["id"], zone["id"], lot_code="LOT-NSP-LATE",
            manufactured_on="2026-07-01T00:00:00Z", quantity_received_lb=5000,
        )
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        line = add_order_line(customer, order["id"], flour["id"], 9000)
        submit_order(customer, order["id"])

        response = api_client.allocate_order(order["id"], {}, WO)

        validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_LOT)
        assert response.status_code == 409, (
            f"Expected HTTP 409, got {response.status_code}"
        )
        assert read_order(order["id"])["fulfillment_status"] == "NEW", (
            "A refused allocation leaves the order at NEW"
        )
        assert read_order_line(line["id"])["allocation_status"] == "UNALLOCATED", (
            "No lot was picked, so the line stays unallocated"
        )
        assert read_lot(early["id"])["quantity_reserved_lb"] == 0, (
            "The earlier-expiring lot reserves nothing"
        )
        assert read_lot(late["id"])["quantity_reserved_lb"] == 0, (
            "Neither does the later-expiring lot"
        )

        big = receive_lot(
            flour["id"], zone["id"], lot_code="LOT-NSP-BIG",
            manufactured_on="2026-07-20T00:00:00Z", quantity_received_lb=12000,
        )
        allocated = allocate_order(order["id"])

        assert allocated["fulfillment_status"] == "ALLOCATED", (
            f"One lot now covers the line, got {allocated['fulfillment_status']}"
        )
        filled = read_order_line(line["id"])
        assert filled["lot_id"] == big["id"], (
            f"The only lot able to cover the line wins over the FEFO-earliest, got "
            f"{filled['lot_id']}"
        )
        assert read_lot(early["id"])["quantity_reserved_lb"] == 0, (
            "The FEFO-earliest lot is skipped entirely"
        )
        assert read_lot(big["id"])["quantity_reserved_lb"] == 9000, (
            "The whole line is reserved from the single larger lot"
        )


class TestOneApprovalFiresBothConditionalTails:
    """The reprice trips the credit limit by a cent and the swap trips the tier to RED."""

    def test_all_five_hops_land_including_the_credit_hold_and_the_red_tier(self):
        """PRD §3.8: "**Hop one:** the order line's current `product_id` is copied into
        `substituted_from_product_id`, and `product_id` becomes the request's
        `proposed_product_id`. **Hop two:** because the line's product changed, any
        existing `RESERVED` allocation is released — the line's `allocation_status` becomes
        `RELEASED` and the old lot returns the line's pounds from `quantity_reserved_lb` to
        `quantity_on_hand_lb` — and the rotation selector of §3.5 re-picks a lot of the new
        product and re-reserves it" ... "**Hop three:** because the line's product and unit
        price changed, the order is repriced through the `PROVISIONAL` self-loop, changing
        `subtotal_cents`, `volume_rebate_cents` and `total_cents`. **Hop four:** because
        `total_cents` changed, the bakery's `open_exposure_cents` is recomputed, and if it
        now exceeds `credit_limit_cents` the bakery moves `ACTIVE → CREDIT_HOLD`. **Hop
        five:** because the line's allergen class changed, the bakery's
        `allergen_risk_score` is recomputed on the in-flight basis and `risk_tier` is
        re-derived."

        PRD §3.7: "`GLUTEN` weighs 0.55, `TREE_NUT` weighs 0.90, and `PEANUT` weighs the
        full 1.00."

        PRD §3.7: "`risk_tier` is then re-derived: `GREEN` below 25.00, `AMBER` from 25.00
        up to but not including 60.00, and `RED` at 60.00 and above."

        4000 lb at 32 cents extends to 126080 after the 1.5% tier, and the 2.5% fuel
        surcharge of 3152 carries the total to 129232 — one cent past the 129231 limit.

        Design: Corner/cross_cutting_complexity_layers/corner_layer_approval_cascade_five_hops_credit_hold_and_red_tier
        """
        set_clock(EPOCH)
        customer = create_customer(credit_limit_cents=129231, min_drop_cents=1000)
        gluten_flour = create_product(dict(FLOUR_30, sku="FLR-5HA-30"))
        nut_inclusion = create_product(
            dict(
                FLOUR_30,
                sku="INC-5HB-32",
                category="INCLUSION",
                allergen_class="TREE_NUT",
                list_price_cents_per_lb=32,
            )
        )
        gluten_zone = create_zone(zone_code="Z-GLU", allergen_class="GLUTEN")
        nut_zone = create_zone(zone_code="Z-NUT", allergen_class="TREE_NUT")
        gluten_lot = receive_lot(
            gluten_flour["id"], gluten_zone["id"], lot_code="LOT-5HA-0001",
            manufactured_on="2026-07-15T00:00:00Z", quantity_received_lb=20000,
        )
        nut_lot = receive_lot(
            nut_inclusion["id"], nut_zone["id"], lot_code="LOT-5HB-0001",
            manufactured_on="2026-07-15T00:00:00Z", quantity_received_lb=20000,
        )
        order = open_order(
            customer,
            delivery_mode="BAGGED",
            requested_delivery_on=SERVICE_ON,
        )
        line = add_order_line(customer, order["id"], gluten_flour["id"], 4000)
        submit_order(customer, order["id"])
        allocated = allocate_order(order["id"])
        request = raise_substitution_request(
            line["id"], nut_inclusion["id"], allocated["version"],
            rationale="Mill outage; nut inclusion offered as the closest substitute",
        )
        claim_substitution_request(request["id"])
        before = read_customer(customer["id"])
        assert float(before["allergen_risk_score"]) == 55.00, (
            f"4000 GLUTEN pounds in flight score 55.00, got "
            f"{before['allergen_risk_score']}"
        )
        assert before["risk_tier"] == "AMBER", (
            f"Expected AMBER, got {before['risk_tier']}"
        )
        assert before["open_exposure_cents"] == 121155, (
            f"Expected 121155 booked, got {before['open_exposure_cents']}"
        )
        assert before["status"] == "ACTIVE", (
            f"121155 is inside the 129231 limit, got {before['status']}"
        )

        approved = approve_substitution_request(request["id"])

        assert approved["status"] == "APPROVED", (
            f"Expected APPROVED, got {approved['status']}"
        )
        swapped = read_order_line(line["id"])
        assert swapped["product_id"] == nut_inclusion["id"], (
            f"Hop one: expected the proposed SKU on the line, got "
            f"{swapped['product_id']}"
        )
        assert swapped["substituted_from_product_id"] == gluten_flour["id"], (
            f"Hop one: expected the original SKU recorded, got "
            f"{swapped['substituted_from_product_id']}"
        )
        released = read_lot(gluten_lot["id"])
        assert released["quantity_reserved_lb"] == 0, (
            f"Hop two: expected the old lot released, got "
            f"{released['quantity_reserved_lb']}"
        )
        assert released["quantity_on_hand_lb"] == 20000, (
            f"Hop two: expected the pounds back on hand, got "
            f"{released['quantity_on_hand_lb']}"
        )
        repicked = read_lot(nut_lot["id"])
        assert repicked["quantity_reserved_lb"] == 4000, (
            f"Hop two: expected the new lot reserved, got "
            f"{repicked['quantity_reserved_lb']}"
        )
        assert swapped["lot_id"] == nut_lot["id"], (
            f"Hop two: expected the line bound to the nut lot, got {swapped['lot_id']}"
        )
        assert swapped["allocation_status"] == "RESERVED", (
            f"Hop two: expected RESERVED after the re-pick, got "
            f"{swapped['allocation_status']}"
        )
        assert swapped["unit_price_cents"] == 32, (
            f"Hop three: expected the new list price, got {swapped['unit_price_cents']}"
        )
        assert swapped["extended_cents"] == 126080, (
            f"Hop three: expected 128000 less the 1.5% tier, got "
            f"{swapped['extended_cents']}"
        )
        repriced = read_order(order["id"])
        assert repriced["fuel_surcharge_cents"] == 3152, (
            f"Hop three: expected 2.5% of 126080, got "
            f"{repriced['fuel_surcharge_cents']}"
        )
        assert repriced["volume_rebate_cents"] == 0, (
            f"Hop three: expected no rebate below 500000, got "
            f"{repriced['volume_rebate_cents']}"
        )
        assert repriced["total_cents"] == 129232, (
            f"Hop three: expected total 129232, got {repriced['total_cents']}"
        )
        assert repriced["pricing_status"] == "PROVISIONAL", (
            f"Hop three: the self-loop keeps the order PROVISIONAL, got "
            f"{repriced['pricing_status']}"
        )
        assert repriced["fulfillment_status"] == "ALLOCATED", (
            f"The approval cascade never rewinds fulfilment, got "
            f"{repriced['fulfillment_status']}"
        )
        after = read_customer(customer["id"])
        assert after["open_exposure_cents"] == 129232, (
            f"Hop four: expected 129232, got {after['open_exposure_cents']}"
        )
        assert after["status"] == "CREDIT_HOLD", (
            f"Hop four: one cent past the limit puts the account on hold, got "
            f"{after['status']}"
        )
        assert float(after["allergen_risk_score"]) == 90.00, (
            f"Hop five: 4000 TREE_NUT pounds score 90.00, got "
            f"{after['allergen_risk_score']}"
        )
        assert after["risk_tier"] == "RED", (
            f"Hop five: expected RED, got {after['risk_tier']}"
        )
        assert read_substitution_request(request["id"])["status"] == "APPROVED", (
            "The request itself is terminal at APPROVED"
        )
