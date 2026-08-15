"""Intake and order-composition rules: defaults, computed intake fields,
body-FK existence, request shape, composition minimums, uniqueness, lead time."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_customer,
    assert_press_order,
    create_customer,
    create_press_line,
    create_press_order_payload,
    create_release,
    create_release_payload,
    is_valid_uuid,
    set_clock,
    setup_world,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import CSR, PLANNER


class TestCustomerDefaults:
    def test_customer_create_applies_defaults(self, api):
        """PRD §3.1: "the `discount_tier` (one of `STANDARD`, `SILVER`, `GOLD`,
        `PLATINUM`) and the `overrun_policy` (one of `EXACT_ONLY`,
        `ACCEPT_AND_BILL_10`, `ACCEPT_ALL_AND_BILL`) may be supplied at creation
        and default to `STANDARD` and `ACCEPT_AND_BILL_10` respectively. New
        customers begin with `status` `ACTIVE` and a `trailing_billed_cents` of
        zero."

        Design: Corner/entities/customer_create_applies_defaults
        """
        set_clock()
        resp = api.create_customer(
            {"name": "Defaults Co", "contact_email": "d@x.com",
             "credit_limit_cents": 5000000},
            CSR,
        )
        data = validate_success(resp, 201)
        assert_customer(data)
        assert data["discount_tier"] == "STANDARD", (
            f"Omitted discount_tier must default to STANDARD, got {data['discount_tier']}"
        )
        assert data["overrun_policy"] == "ACCEPT_AND_BILL_10", (
            f"Omitted overrun_policy must default to ACCEPT_AND_BILL_10, got {data['overrun_policy']}"
        )
        assert data["status"] == "ACTIVE"
        assert data["trailing_billed_cents"] == 0
        assert is_valid_uuid(str(data["id"])), "id must be a typeless UUID"


class TestOrderIntakeComputedFields:
    def test_order_intake_computed_fields(self, api):
        """PRD §3.2: "The `tolerance_pct` is the strictest quality tolerance
        across the order's variants: `BLACK` tolerates 5.0 percent rejects,
        `SOLID_COLOR` 6.0, `SPLATTER` 8.0, `MARBLED` 8.0, and `PICTURE_DISC`
        12.0, and the smallest applicable value wins. The `color_family` is the
        family of the largest-quantity variant, ties broken by the variant that
        appears first in the array"
        PRD §3.2: "Creation stamps the order with a plant-wide monotonic
        `intake_seq` beginning at 1"
        PRD §3.2: "A fresh order holds `production_status` `DRAFT` and
        `billing_status` `UNBILLED`"

        Design: Corner/entities/order_intake_computed_fields
        """
        world = setup_world(with_line=False, with_bath=False)
        resp = api.create_press_order(
            {
                "release_id": world["release"]["id"],
                "quantity_ordered": 1000,
                "sides": 2,
                "plating_route": "TWO_STEP",
                "variants": [
                    {"color_config": "BLACK", "quantity": 500},
                    {"color_config": "SPLATTER", "quantity": 500},
                ],
            },
            CSR,
        )
        data = validate_success(resp, 201)
        assert_press_order(data)
        assert data["tolerance_pct"] == pytest.approx(5.0), (
            f"strictest of BLACK 5.0 / SPLATTER 8.0 must win, got {data['tolerance_pct']}"
        )
        assert data["color_family"] == "STANDARD", (
            "500/500 tie must be broken by the first variant in the array (BLACK)"
        )
        assert data["production_status"] == "DRAFT"
        assert data["billing_status"] == "UNBILLED"
        assert data["intake_seq"] == 1, (
            f"first order created must carry intake_seq 1, got {data['intake_seq']}"
        )


class TestBodyFkExistence:
    def test_body_fk_existence_enforced(self, api):
        """PRD §2.8: "Identifiers referenced in a request body — a `release_id`,
        a `customer_id`, a `distributor_customer_id`, or a `plating_bath_id` —
        must likewise exist and fail with the corresponding not-found error."

        Design: Corner/entities/body_fk_existence_enforced
        """
        world = setup_world(with_line=False, with_bath=False)
        cust = world["customer"]
        rel = world["release"]

        r1 = api.create_release(
            create_release_payload(NON_EXISTENT_UUID, catalog_number="FK-002"),
            CSR,
        )
        validate_error(r1, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)

        r2 = api.create_press_order(
            create_press_order_payload(NON_EXISTENT_UUID, quantity_ordered=100),
            CSR,
        )
        validate_error(r2, ApiErrorId.ERR_RELEASE_NOT_FOUND)

        r3 = api.create_shipment(
            {
                "release_id": rel["id"],
                "distributor_customer_id": NON_EXISTENT_UUID,
                "quantity": 10,
                "requested_ship_date": "2026-08-15",
            },
            CSR,
        )
        validate_error(r3, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)
        assert cust["id"] and rel["id"]  # setup sanity


class TestRequestShape:
    def test_missing_required_field_rejected(self, api):
        """PRD §2.9: "Request shape — missing required fields, wrong types,
        invalid enum members, non-positive quantities, slot hours outside the
        owning line's bookable range, a `weight_gram` other than 140 or 180, or
        `sides` other than 1 or 2, rejected with `ERR_INVALID_REQUEST` on every
        write endpoint."

        Design: Corner/validations/missing_required_field_rejected
        """
        world = setup_world(with_line=False, with_bath=False)
        payload = {
            "release_id": world["release"]["id"],
            "sides": 2,
            "plating_route": "TWO_STEP",
            "variants": [{"color_config": "BLACK", "quantity": 100}],
        }
        resp = api.create_press_order(payload, CSR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_invalid_enum_value_rejected(self, api):
        """PRD §2.9: "Request shape — missing required fields, wrong types,
        invalid enum members, non-positive quantities, slot hours outside the
        owning line's bookable range, a `weight_gram` other than 140 or 180, or
        `sides` other than 1 or 2, rejected with `ERR_INVALID_REQUEST` on every
        write endpoint."

        Design: Corner/validations/invalid_enum_value_rejected
        """
        world = setup_world(with_line=False, with_bath=False)
        cust = world["customer"]

        bad_variant = create_press_order_payload(
            world["release"]["id"], quantity_ordered=100,
            variants=[{"color_config": "HOLOGRAPHIC", "quantity": 100}],
        )
        r1 = api.create_press_order(bad_variant, CSR)
        validate_error(r1, ApiErrorId.ERR_INVALID_REQUEST)

        bad_weight = create_release_payload(
            cust["id"], catalog_number="V3-002", weight_gram=200
        )
        r2 = api.create_release(bad_weight, CSR)
        validate_error(r2, ApiErrorId.ERR_INVALID_REQUEST)


class TestLeadTime:
    def test_lead_time_boundary_inclusive(self, api):
        """PRD §3.2: "An optional `requested_completion_date`, when present, must
        fall at least twenty-one days — three full weeks — after the current
        logical date, or intake is rejected with `ERR_LEAD_TIME_VIOLATION`."

        Design: Corner/validations/lead_time_boundary_inclusive
        """
        world = setup_world(with_line=False, with_bath=False, clock="2026-08-01T00:00:00Z")
        rel = world["release"]

        too_soon = create_press_order_payload(
            rel["id"], quantity_ordered=100,
            requested_completion_date="2026-08-10",
        )
        r1 = api.create_press_order(too_soon, CSR)
        validate_error(r1, ApiErrorId.ERR_LEAD_TIME_VIOLATION)

        exactly_21 = create_press_order_payload(
            rel["id"], quantity_ordered=100,
            requested_completion_date="2026-08-22",
        )
        r2 = api.create_press_order(exactly_21, CSR)
        data = validate_success(r2, 201)
        assert data["requested_completion_date"] == "2026-08-22"


class TestCompositionRules:
    def test_variant_sum_mismatch_rejected(self, api):
        """PRD §3.2: "the variant quantities must sum exactly to
        `quantity_ordered` (`ERR_VARIANT_SUM_MISMATCH`)"

        Design: Corner/validations/variant_sum_mismatch_rejected
        """
        world = setup_world(with_line=False, with_bath=False)
        payload = create_press_order_payload(
            world["release"]["id"], quantity_ordered=1000,
            variants=[{"color_config": "BLACK", "quantity": 900}],
        )
        resp = api.create_press_order(payload, CSR)
        validate_error(resp, ApiErrorId.ERR_VARIANT_SUM_MISMATCH)

    def test_order_below_minimum_rejected(self, api):
        """PRD §3.2: "the order must be for at least 100 units
        (`ERR_ORDER_BELOW_MINIMUM`)"

        Design: Corner/validations/order_below_minimum_rejected
        """
        world = setup_world(with_line=False, with_bath=False)
        rel = world["release"]

        low = create_press_order_payload(
            rel["id"], quantity_ordered=99,
            variants=[{"color_config": "BLACK", "quantity": 99}],
        )
        r1 = api.create_press_order(low, CSR)
        validate_error(r1, ApiErrorId.ERR_ORDER_BELOW_MINIMUM)

        exact = create_press_order_payload(
            rel["id"], quantity_ordered=100,
            variants=[{"color_config": "BLACK", "quantity": 100}],
        )
        r2 = api.create_press_order(exact, CSR)
        validate_success(r2, 201)

    def test_duplicate_codes_rejected(self, api):
        """PRD §3.2: "a `catalog_number` unique within that customer's catalog
        (a duplicate is rejected with `ERR_DUPLICATE_CODE`)"
        PRD §3.6: "A `ProductionPlanner` registers each PressLine with a unique
        `line_code` (duplicates rejected with `ERR_DUPLICATE_CODE`)"

        Design: Corner/validations/duplicate_codes_rejected
        """
        set_clock()
        create_press_line(line_code="L1")
        cust_a = create_customer(name="V7a", contact_email="v7a@x.com",
                                 credit_limit_cents=1000000)
        cust_b = create_customer(name="V7b", contact_email="v7b@x.com",
                                 credit_limit_cents=1000000)
        create_release(cust_a["id"], catalog_number="DUP-1", format="LP",
                       weight_gram=140)

        r1 = api.create_press_line(
            {"line_code": "L1", "tonnage_class": "HEAVY", "hours_per_day": 8,
             "daily_unit_capacity": 2000},
            PLANNER,
        )
        validate_error(r1, ApiErrorId.ERR_DUPLICATE_CODE)

        r2 = api.create_release(
            create_release_payload(cust_a["id"], catalog_number="DUP-1",
                                   format="EP", weight_gram=140, title="T2"),
            CSR,
        )
        validate_error(r2, ApiErrorId.ERR_DUPLICATE_CODE)

        r3 = api.create_release(
            create_release_payload(cust_b["id"], catalog_number="DUP-1",
                                   format="EP", weight_gram=140, title="T3"),
            CSR,
        )
        validate_success(r3, 201)


class TestVariantMinimumBoundary:
    def test_variant_minimum_exact_boundary_accepted(self, api):
        """PRD §3.2: "each variant must meet its configuration minimum — a
        single unit suffices for `BLACK`, while `SOLID_COLOR`, `SPLATTER`, and
        `MARBLED` each require at least 100 and `PICTURE_DISC` at least 200
        (`ERR_VARIANT_BELOW_MINIMUM`)"

        Design: Difficulty/boundary_precision_check/variant_minimum_exact_boundary
        """
        world = setup_world(with_line=False, with_bath=False)
        payload = create_press_order_payload(
            world["release"]["id"], quantity_ordered=100,
            variants=[{"color_config": "SPLATTER", "quantity": 100}],
        )
        resp = api.create_press_order(payload, CSR)
        data = validate_success(resp, 201)
        assert data["quantity_ordered"] == 100, (
            "SPLATTER quantity exactly at its 100 minimum must be accepted"
        )

    def test_variant_minimum_one_below_rejected(self, api):
        """PRD §3.2: "each variant must meet its configuration minimum — a
        single unit suffices for `BLACK`, while `SOLID_COLOR`, `SPLATTER`, and
        `MARBLED` each require at least 100 and `PICTURE_DISC` at least 200
        (`ERR_VARIANT_BELOW_MINIMUM`)"

        Design: Difficulty/boundary_precision_check/variant_minimum_exact_boundary
        """
        world = setup_world(with_line=False, with_bath=False)
        payload = create_press_order_payload(
            world["release"]["id"], quantity_ordered=100,
            variants=[
                {"color_config": "SPLATTER", "quantity": 99},
                {"color_config": "BLACK", "quantity": 1},
            ],
        )
        resp = api.create_press_order(payload, CSR)
        validate_error(resp, ApiErrorId.ERR_VARIANT_BELOW_MINIMUM)
