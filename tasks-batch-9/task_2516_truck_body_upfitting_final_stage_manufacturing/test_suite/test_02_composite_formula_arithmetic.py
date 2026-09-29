"""Formulas whose result depends on the order in which their terms are combined.

Payload capacity is a minimum over candidate ceilings, one of which vanishes
entirely; the warranty cents split rounds twice and hands the remainder to
goodwill; and the invoice discounts before it decides which certification fee
band applies.
"""

from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_axle_numbers,
    assert_claim_split,
    assert_installation_hydraulics,
    assert_order_commitments,
    assert_order_dimensions,
    assert_order_ledger,
)
from test_helpers.constants import (
    BODY_VAN_BOX_14FT,
    DISCOUNT_PCT_BY_TIER,
    FEE_TIER_LOW_BOUND_CENTS,
    FEE_TIER_LOW_CENTS,
    FEE_TIER_MID_CENTS,
    LABOR_HOURS_BY_BODY_TYPE,
    SHOP_RATE_CENTS_PER_HOUR,
)
from test_helpers.fixtures import (
    allocate,
    catalog_dump,
    catalog_service,
    delivered_service_order,
    draft_certification,
    new_body_spec,
    new_configuration,
    new_customer,
    new_order,
    open_claim,
    plan_equipment,
    read_installation,
    read_order,
    received_and_inspected_chassis,
    release,
    submit_engineering,
)


def _rear_heavy_dump_world(api):
    """A twelve-foot dump body mounted so far back that its cargo clears the rear axle.

    On the 176-inch F450 wheelbase a 96-inch mount offset puts the body centroid
    at 174 inches and the cargo centroid at 180 inches — four inches behind the
    rear axle — and the ten-ton hoist is planned at 130 inches.
    """
    ns = catalog_dump(api)
    ns.customer = new_customer(api)
    ns.config = new_configuration(api, ns.cm["id"], ns.body["id"], config_code="CFG-DUMP-B")
    ns.chassis = received_and_inspected_chassis(
        api,
        ns.cm["id"],
        availability_date="2026-08-10",
        ownership="CUSTOMER_ASSIGNED",
        measured=(4180, 2320),
    )
    ns.order = new_order(
        api,
        ns.config["id"],
        order_number="UO-1101",
        order_type="CUSTOMER_SPECIFIC",
        customer_id=ns.customer["id"],
        body_mount_offset_from_front_axle_in=96,
        required_payload_lb=2000,
        requested_in_service_date="2026-09-15",
    )
    allocate(api, ns.order["id"], ns.chassis["id"])
    ns.hoist_install = plan_equipment(
        api, ns.order["id"], ns.hoist["id"], 130, "PRIMARY", headers=users.TECHNICIAN
    )
    ns.order = submit_engineering(api, ns.order["id"])
    return ns


class TestPayloadCapacityNestedMinimum:
    """Payload capacity is the smallest of several ceilings, and one may drop out."""

    def test_the_front_axle_ceiling_is_omitted_when_its_load_fraction_is_not_positive(self, api):
        """Cargo behind the rear axle unloads the front axle, so that ceiling cannot bind.

        The cargo centroid sits four inches behind the rear axle, which makes the
        front-axle load fraction negative; the front term therefore leaves the
        minimum entirely and the rear-axle ceiling wins at 2999 pounds instead of
        collapsing to zero.

        Design: Difficulty/combinatorial_formula/payload_capacity_nested_min_with_front_term_skipped
        """
        ns = _rear_heavy_dump_world(api)

        certification = draft_certification(
            api, ns.order["id"], "AS_DESIGNED", expected_version=ns.order["version"]
        )

        assert certification["payload_capacity_lb"] == 2999
        assert certification["payload_capacity_lb"] != 0

    def test_the_axle_split_and_component_count_behind_that_capacity(self, api):
        """The same reading pins the two axle loads, the gross weight and the tally.

        The body and the hoist are the two components counted under the design
        basis, and the gross weight is the sum of the two separately rounded axle
        integers.

        Design: Difficulty/combinatorial_formula/payload_capacity_nested_min_with_front_term_skipped
        """
        ns = _rear_heavy_dump_world(api)

        certification = draft_certification(
            api, ns.order["id"], "AS_DESIGNED", expected_version=ns.order["version"]
        )

        assert_axle_numbers(certification, 4467, 6383, 10850, 2999, component_count=2)

    def test_the_hoist_holds_the_whole_flow_pool_of_the_bound_unit(self, api):
        """The single hydraulic item is fully granted, so nothing is in deficit.

        Twelve gallons per minute of demand against the bound model's fourteen
        leaves the hoist satisfied and the order committed to twelve.

        Design: Difficulty/combinatorial_formula/payload_capacity_nested_min_with_front_term_skipped
        """
        ns = _rear_heavy_dump_world(api)

        installation = read_installation(api, ns.hoist_install["id"])
        assert_installation_hydraulics(installation, 12, "OK")
        assert_order_commitments(read_order(api, ns.order["id"]), flow_gpm=12)


class TestWarrantyCentsRoundingAndRemainder:
    """Two shares are rounded and the third absorbs whatever is left over."""

    def test_each_share_rounds_half_up_and_goodwill_takes_the_remainder(self, api):
        """A claim of 73333 cents cannot be split three ways without a remainder.

        Sixty percent rounds up to 44000 and thirty-five percent rounds up to
        25667, which leaves goodwill with 3666 cents — one cent less than a
        rounded five percent would have given.

        Design: Difficulty/combinatorial_formula/warranty_cents_split_pinned_rounding_and_remainder
        """
        ns = delivered_service_order(api)

        claim = open_claim(
            api, ns.order["id"], "CHASSIS_ELECTRICAL", 73333, claim_number="WC-3101"
        )

        assert_claim_split(claim, 60, 35, 5, 44000, 25667, 3666, split_basis="PROVISIONAL")
        assert claim["customer_goodwill_cents"] != 3667

    def test_a_submitted_claim_does_not_yet_move_the_order_ledger(self, api):
        """The order totals count adjudicated and paid claims only.

        The claim carries a full provisional split of its own while the order it
        belongs to still shows three zeroes, because a SUBMITTED claim has not
        been adjudicated.

        Design: Difficulty/combinatorial_formula/warranty_cents_split_pinned_rounding_and_remainder
        """
        ns = delivered_service_order(api)
        claim = open_claim(
            api, ns.order["id"], "CHASSIS_ELECTRICAL", 73333, claim_number="WC-3101"
        )

        assert claim["status"] == "SUBMITTED"
        assert_order_ledger(read_order(api, ns.order["id"]), 0, 0, 0)


class TestInvoiceTierEvaluationOrder:
    """The discount is applied first and only then does a fee band get chosen."""

    def _van_pool_order(self, api):
        ns = catalog_service(api, with_equipment=False)
        ns.van = new_body_spec(api, BODY_VAN_BOX_14FT)
        ns.config = new_configuration(
            api,
            ns.cm["id"],
            ns.van["id"],
            config_code="STD-VAN-A",
            standardization_tier="TIER_A",
            standard_equipment_spec_ids=[],
        )
        ns.chassis = received_and_inspected_chassis(api, ns.cm["id"], measured=(4820, 2680))
        ns.order = new_order(
            api,
            ns.config["id"],
            order_number="UO-1201",
            order_type="POOL_STOCK",
            body_mount_offset_from_front_axle_in=120,
            required_payload_lb=5000,
        )
        allocate(api, ns.order["id"], ns.chassis["id"])
        ns.order = submit_engineering(api, ns.order["id"])
        return ns

    def test_the_fee_band_is_chosen_from_the_discounted_subtotal(self, api):
        """An eight percent discount drops the build under the two-million line.

        The gross subtotal of 2153000 cents would have earned the middle
        certification fee, but the tier discount is taken first and the
        discounted subtotal of 1980760 falls in the lowest band, so the invoice
        settles at 2025760 rather than 2053260.

        Design: Difficulty/combinatorial_formula/build_invoice_total_pinned_tier_evaluation_order
        """
        ns = self._van_pool_order(api)

        released = release(api, ns.order["id"])

        assert_order_dimensions(released, build_status="RELEASED")
        assert_order_commitments(released, invoice_cents=2025760)
        assert released["invoice_total_cents"] != 2053260

    def test_the_subtotal_is_the_body_list_price_plus_the_van_labour_allowance(self, api):
        """Every term of the invoice can be rebuilt from the published tables.

        Twenty-two van labour hours at 11500 cents an hour on top of a 1900000
        cent body give the gross subtotal, the eight percent tier discount comes
        off it, and the low fee applies because the discounted figure is strictly
        below two million.

        Design: Difficulty/combinatorial_formula/build_invoice_total_pinned_tier_evaluation_order
        """
        ns = self._van_pool_order(api)

        released = release(api, ns.order["id"])

        labour = LABOR_HOURS_BY_BODY_TYPE["VAN"] * SHOP_RATE_CENTS_PER_HOUR
        gross = BODY_VAN_BOX_14FT["list_price_cents"] + labour
        discount = gross * DISCOUNT_PCT_BY_TIER["TIER_A"] // 100
        discounted = gross - discount
        assert gross == 2153000
        assert discount == 172240
        assert discounted == 1980760
        assert discounted < FEE_TIER_LOW_BOUND_CENTS
        assert released["invoice_total_cents"] == discounted + FEE_TIER_LOW_CENTS
        assert released["invoice_total_cents"] != discounted + FEE_TIER_MID_CENTS

    def test_releasing_the_pool_order_prices_it_without_touching_compliance(self, api):
        """Pricing happens at release; certification has not started yet.

        The only aux draw the order carries is the van body's fourteen amps,
        because no equipment and no interfaces were ever planned, and the
        compliance dimension is still untouched.

        Design: Difficulty/combinatorial_formula/build_invoice_total_pinned_tier_evaluation_order
        """
        ns = self._van_pool_order(api)

        released = release(api, ns.order["id"])

        assert_order_dimensions(
            released, build_status="RELEASED", compliance_status="NOT_STARTED"
        )
        assert_order_commitments(released, aux_amps=14)
