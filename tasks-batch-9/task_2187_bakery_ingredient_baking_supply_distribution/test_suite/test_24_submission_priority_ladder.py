"""Which of two simultaneous breaches a submission reports (PRD §2.7, §2.8, §3.3)."""

from test_helpers import (
    ApiErrorId,
    add_order_line,
    allocate_order,
    api_client,
    create_customer,
    create_product,
    create_zone,
    open_order,
    read_customer,
    read_order,
    receive_lot,
    set_clock,
    submit_order,
    validate_error,
)
from test_helpers.fixtures import buyer_headers

EPOCH = "2026-08-01T00:00:00Z"

PEANUT_PASTE = {
    "sku": "NUT-PEA-25",
    "category": "INCLUSION",
    "allergen_class": "PEANUT",
    "shelf_life_days": 200,
    "index_code": "NONE",
    "list_price_cents_per_lb": 30,
    "min_rotation_days": 0,
}


def _two_peanut_orders(credit_limit_cents=10000000, submit_the_held_order=False):
    """One peanut order held back, one submitted and allocated so the tier reads RED.

    Both peanut lines are written while the account is still `GREEN`, which is the
    only window in which the §2.8 gate lets them through.
    """
    set_clock(EPOCH)
    customer = create_customer(
        credit_limit_cents=credit_limit_cents, min_drop_cents=1000
    )
    peanut = create_product(PEANUT_PASTE)
    zone = create_zone(zone_code="Z-PEA", allergen_class="PEANUT")
    receive_lot(
        peanut["id"], zone["id"], lot_code="LOT-PN-0001",
        manufactured_on="2026-07-01T00:00:00Z", quantity_received_lb=20000,
    )
    held = open_order(
        customer,
        delivery_mode="BAGGED",
        requested_delivery_on="2026-09-12T00:00:00Z",
    )
    held_line = add_order_line(customer, held["id"], peanut["id"], 1000)
    if submit_the_held_order:
        submit_order(customer, held["id"])
    driver = open_order(
        customer,
        delivery_mode="BAGGED",
        requested_delivery_on="2026-09-05T00:00:00Z",
    )
    add_order_line(customer, driver["id"], peanut["id"], 1000)
    submit_order(customer, driver["id"])
    allocate_order(driver["id"])
    return {
        "customer": customer,
        "peanut": peanut,
        "held_order": held,
        "held_line": held_line,
        "driver_order": driver,
    }


class TestRedTierBlocksPeanutAtSubmission:
    """A line legal when written becomes illegal once the tier is re-derived."""

    def test_submitting_an_untouched_peanut_order_is_refused_once_the_account_reads_red(self):
        """PRD §2.8: "Independently of the declared program, a customer whose
        `risk_tier` has been derived as `RED` may not receive a product whose
        `allergen_class` is `TREE_NUT` or `PEANUT`. All three of those bakery-level
        breaches return `ERR_ALLERGEN_PROGRAM_CONFLICT` (HTTP 422), and the check is
        enforced at exactly three moments: when a line is added to an order, when an
        order is submitted, and when a substitution is approved."

        PRD §3.4: "A bakery's `open_exposure_cents` is the total of `total_cents` over
        every one of its orders whose `pricing_status` is either `PROVISIONAL` or
        `FINAL`; orders that are `UNPRICED`, `INVOICED` or `VOID` contribute nothing."

        Design: Corner/validations/corner_val_red_tier_peanut_order_rejected_at_submit
        """
        scenario = _two_peanut_orders()

        response = api_client.submit_order(
            scenario["held_order"]["id"], {}, buyer_headers(scenario["customer"])
        )

        validate_error(response, ApiErrorId.ERR_ALLERGEN_PROGRAM_CONFLICT)
        assert response.status_code == 422, (
            f"Expected HTTP 422, got {response.status_code}"
        )
        customer = read_customer(scenario["customer"]["id"])
        assert customer["risk_tier"] == "RED", (
            f"Expected RED, got {customer['risk_tier']}"
        )
        assert float(customer["allergen_risk_score"]) == 100.00, (
            f"Expected 100.00, got {customer['allergen_risk_score']}"
        )
        held = read_order(scenario["held_order"]["id"])
        assert held["fulfillment_status"] == "NEW", (
            f"Expected NEW, got {held['fulfillment_status']}"
        )
        assert held["pricing_status"] == "UNPRICED", (
            f"Expected UNPRICED, got {held['pricing_status']}"
        )
        assert held["subtotal_cents"] == 0, (
            f"Expected nothing priced, got subtotal {held['subtotal_cents']}"
        )
        assert held["total_cents"] == 0, (
            f"Expected nothing priced, got total {held['total_cents']}"
        )
        assert customer["open_exposure_cents"] == 30750, (
            f"Only the allocated order contributes, so expected 30750, got "
            f"{customer['open_exposure_cents']}"
        )


class TestStateLegalityOutranksAllergenCompatibility:
    """Both breaches at once, and the 409 wins over the 422."""

    def test_a_double_submit_reports_the_state_transition_not_the_allergen_breach(self):
        """PRD §2.7: "A submit request against an order that is already `PROVISIONAL`
        *and* whose lines breach the customer's allergen program returns
        `ERR_INVALID_STATE_TRANSITION`, not `ERR_ALLERGEN_PROGRAM_CONFLICT`, because
        state legality outranks allergen compatibility."

        PRD §2.7: "Only after all of that do state and business checks run, in this
        order: the target resource's own state-transition legality; the cross-dimension
        gate on an order; the state of related entities; segregation of duties;
        allergen-program compatibility"

        Design: Corner/validations/corner_val_state_check_outranks_allergen_conflict_on_double_submit
        """
        scenario = _two_peanut_orders(submit_the_held_order=True)

        response = api_client.submit_order(
            scenario["held_order"]["id"], {}, buyer_headers(scenario["customer"])
        )

        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert response.status_code == 409, (
            f"Expected HTTP 409 rather than the allergen gate's 422, got "
            f"{response.status_code}"
        )
        customer = read_customer(scenario["customer"]["id"])
        assert customer["risk_tier"] == "RED", (
            f"The allergen breach is genuinely present, so expected RED, got "
            f"{customer['risk_tier']}"
        )
        held = read_order(scenario["held_order"]["id"])
        assert held["pricing_status"] == "PROVISIONAL", (
            f"Expected PROVISIONAL, got {held['pricing_status']}"
        )
        assert held["total_cents"] == 30750, (
            f"Expected the first submission's total intact, got {held['total_cents']}"
        )
        assert customer["open_exposure_cents"] == 61500, (
            f"Both submitted orders stay priced, so expected 61500, got "
            f"{customer['open_exposure_cents']}"
        )


class TestAllergenCompatibilityOutranksTheFiscalGates:
    """Both breaches at once, and the 422 wins over the 402."""

    def test_an_order_over_the_limit_and_over_the_tier_reports_the_allergen_breach(self):
        """PRD §2.7: "An order that both breaches the allergen program *and* would
        exceed the customer's credit limit returns `ERR_ALLERGEN_PROGRAM_CONFLICT`,
        because allergen compatibility outranks the fiscal checks."

        PRD §3.3: "Then the bakery's existing `open_exposure_cents` plus this order's
        computed `total_cents` must be no greater than its `credit_limit_cents`; a sum
        that strictly exceeds the limit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`
        (HTTP 402)."

        30750 already booked plus 30750 more would breach the 40000 limit, so both
        gates are armed and only the higher-priority one may speak.

        Design: Corner/validations/corner_val_allergen_conflict_outranks_credit_limit_breach
        """
        scenario = _two_peanut_orders(credit_limit_cents=40000)

        response = api_client.submit_order(
            scenario["held_order"]["id"], {}, buyer_headers(scenario["customer"])
        )

        validate_error(response, ApiErrorId.ERR_ALLERGEN_PROGRAM_CONFLICT)
        assert response.status_code == 422, (
            f"Expected HTTP 422 rather than the credit gate's 402, got "
            f"{response.status_code}"
        )
        held = read_order(scenario["held_order"]["id"])
        assert held["pricing_status"] == "UNPRICED", (
            f"Expected UNPRICED, got {held['pricing_status']}"
        )
        assert held["total_cents"] == 0, (
            f"Expected nothing priced, got {held['total_cents']}"
        )
        customer = read_customer(scenario["customer"]["id"])
        assert customer["open_exposure_cents"] == 30750, (
            f"Expected only the allocated order booked, got "
            f"{customer['open_exposure_cents']}"
        )
        assert customer["status"] == "ACTIVE", (
            f"30750 is inside the 40000 limit, so expected ACTIVE, got {customer['status']}"
        )
        assert customer["risk_tier"] == "RED", (
            f"Expected RED, got {customer['risk_tier']}"
        )
