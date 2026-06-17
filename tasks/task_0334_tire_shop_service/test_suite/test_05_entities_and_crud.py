"""Entity creation, defaults, computed-field initial values, type constraints, immutability,
reference integrity, listing, and catalog CRUD actions (PRD §2.4, §3.1, §3.2, §2.10).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
    create_customer, create_vehicle, create_tire_model, create_fitment_rule,
    create_work_order, add_tire_line, approve_order,
    setup_customer_vehicle_tire, setup_approved_order_with_tire_line,
)
import test_helpers.factories as F

ADVISOR = TEST_USERS["service_advisor_headers"]
INV = TEST_USERS["inventory_manager_headers"]


# ---------------------------------------------------------------------------
# Corner — entities
# ---------------------------------------------------------------------------
class TestEntityCreation:
    def test_create_tire_model_returns_201_with_fields(self, api):
        """PRD §3.1: "A `TireModel` is created with a `brand`, a `model_name`, a `size_token`
        such as a standard tire-size string, a `load_index` between 70 and 130 inclusive, and
        a `speed_rating`".
        PRD §2.10: "On-hand inventory is tracked by `stock_qty`, which is set from the optional
        creation input (defaulting to zero when omitted)".

        Design: Corner/entities/create_tire_model_returns_201_with_fields
        """
        data = validate_success(api.create_tire_model(
            F.create_tire_model_payload(brand="MICHELIN", size_token="235/45R18",
                                        unit_price_cents=14999, stock_qty=12), INV),
            expected_status=201)
        assert data["brand"] == "MICHELIN"
        assert data["size_token"] == "235/45R18"
        assert data["unit_price_cents"] == 14999
        assert data["stock_qty"] == 12
        assert data["status"] == "ACTIVE"

    def test_get_work_order_not_found_returns_404(self, api):
        """PRD §2.6: "When an endpoint path contains a resource identifier, that resource must
        exist; if it does not, the request fails with `ERR_NOT_FOUND`."

        Design: Corner/entities/get_work_order_not_found_returns_404
        """
        validate_error(api.get_work_order(NON_EXISTENT_UUID, ADVISOR), ApiErrorId.ERR_NOT_FOUND)

    def test_tire_model_default_mileage_warranty_zero(self, api):
        """PRD §3.1: "`mileage_warranty_miles` is the treadwear mileage warranty, defaulting
        to zero, where zero means the model carries no mileage warranty at all".
        PRD §2.10: "On-hand inventory is tracked by `stock_qty`, which is set from the optional
        creation input (defaulting to zero when omitted)".

        Design: Corner/entities/tire_model_default_mileage_warranty_zero_when_omitted
        """
        payload = {"brand": "GENERIC", "model_name": "BASIC", "size_token": "195/65R15",
                   "load_index": 88, "speed_rating": "T", "unit_price_cents": 6000,
                   "original_tread_32nds": 9}
        data = validate_success(api.create_tire_model(payload, INV), expected_status=201)
        assert data["mileage_warranty_miles"] == 0
        assert data["stock_qty"] == 0

    def test_work_order_computed_money_fields_default_zero(self, api):
        """PRD §3.2: "At creation the order is born in `DRAFT` fulfillment and `UNPAID`
        payment."
        PRD §3.2: "the `extended_cents` it will eventually carry is computed at approval."
        (Before approval runs pricing, the computed money fields are zero.)

        Design: Corner/entities/work_order_computed_money_fields_default_zero_on_create
        """
        customer = create_customer()
        vehicle = create_vehicle(customer["id"])
        data = validate_success(api.create_work_order(
            F.create_work_order_payload(customer["id"], vehicle["id"]), ADVISOR),
            expected_status=201)
        assert data["fulfillment_status"] == "DRAFT"
        assert data["payment_status"] == "UNPAID"
        assert data["total_due_cents"] == 0

    def test_system_fields_generated_on_customer_create(self, api):
        """PRD §2.4: "Every resource carries a server-minted `id`, formatted as a UUID with no
        type prefix. Most resources also carry the standard audit triad: a `created_at`
        timestamp set once at creation, an `updated_at` timestamp refreshed on every mutation,
        and an integer `version` that begins at its initial value and increases by one with
        each mutation."
        PRD §3.1: "Each customer carries a running `store_credit_cents` balance that begins at
        zero".

        Design: Corner/entities/system_fields_generated_on_customer_create
        """
        data = validate_success(api.create_customer(F.create_customer_payload(), ADVISOR),
                                expected_status=201)
        assert data["version"] == 1
        assert data["store_credit_cents"] == 0

    def test_invalid_speed_rating_enum_rejected(self, api):
        """PRD §3.1: "a `speed_rating` drawn from `S`, `T`, `H`, `V`, `W`, or `Y`."
        PRD §2.6: "Field-level input validity — that every enum value is within its declared
        domain ... is enforced across all endpoints and, when it fails, raises
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/tire_model_invalid_speed_rating_enum_rejected
        """
        payload = {"brand": "X", "model_name": "Y", "size_token": "235/45R18",
                   "load_index": 94, "speed_rating": "Z", "unit_price_cents": 10000,
                   "original_tread_32nds": 10}
        validate_error(api.create_tire_model(payload, INV), ApiErrorId.ERR_INVALID_REQUEST)

    def test_fitment_rule_immutable_no_version(self, api):
        """PRD §2.4: "A `FitmentRule` is an immutable junction record once written; it carries
        only `id` and `created_at`, and has neither an `updated_at` field nor a `version`
        field."

        Design: Corner/entities/fitment_immutable_entity_only_id_created_at
        """
        customer, vehicle, tire = setup_customer_vehicle_tire()
        # Fitment was already created in the helper; create a fresh one to read the create body.
        data = validate_success(api.create_fitment_rule(
            F.create_fitment_rule_payload(vehicle["id"], tire["id"], fitment_grade="OE_EXACT"),
            INV), expected_status=201)
        assert data["fitment_grade"] == "OE_EXACT"
        assert "id" in data and "created_at" in data
        assert "updated_at" not in data, "FitmentRule must not carry updated_at"
        assert "version" not in data, "FitmentRule must not carry version"

    def test_work_order_reference_vehicle_not_found(self, api):
        """PRD §2.6: "request bodies that reference other resources by their foreign keys —
        among them `customer_id`, `vehicle_id` ... A body that names a resource that does not
        exist is rejected with `ERR_REFERENCE_NOT_FOUND`."

        Design: Corner/entities/work_order_reference_vehicle_not_found_returns_404
        """
        customer = create_customer()
        validate_error(api.create_work_order(
            {"customer_id": customer["id"], "vehicle_id": NON_EXISTENT_UUID}, ADVISOR),
            ApiErrorId.ERR_REFERENCE_NOT_FOUND)

    def test_list_work_orders_pagination_envelope(self, api):
        """PRD §2.3: "List responses include `limit`, `offset`, `total_count`, and `has_more`
        in the `meta` object of the envelope."
        PRD §3.2: "Orders may be fetched with all their computed money fields and listed,
        filterable by `customer_id`, `vehicle_id`, `fulfillment_status`, and `payment_status`."

        Design: Corner/entities/list_work_orders_pagination_envelope
        """
        customer = create_customer()
        vehicle = create_vehicle(customer["id"], make="FORD", model="FOCUS",
                                 model_year=2019, oe_tire_size="215/55R16",
                                 rim_diameter_in=16, tpms_type="INDIRECT")
        create_work_order(customer["id"], vehicle["id"])
        data, meta = validate_paginated(
            api.list_work_orders(ADVISOR, params={"customer_id": customer["id"], "limit": 10, "offset": 0}))
        assert meta["total_count"] == 1
        assert len(data) == 1


# ---------------------------------------------------------------------------
# Corner — endpoints (catalog CRUD)
# ---------------------------------------------------------------------------
class TestCatalogActions:
    def test_restock_increments_stock_qty(self, api):
        """PRD §2.10: "Stock is debited ... and adjusted manually by a restock operation that
        applies a `delta_qty` to the current `stock_qty`."

        stock 3, delta +5 -> 8.

        Design: Corner/endpoints/restock_increments_stock_qty
        """
        tire = create_tire_model(unit_price_cents=10000, original_tread_32nds=10, stock_qty=3)
        data = validate_success(api.restock_tire_model(tire["id"], {"delta_qty": 5}, INV))
        assert data["stock_qty"] == 8

    def test_discontinue_sets_status(self, api):
        """PRD §2.10: "Each `TireModel` carries a `status` that is `ACTIVE` when created and
        may be moved to `DISCONTINUED`; discontinuation is a one-way status change."

        Design: Corner/endpoints/discontinue_sets_status
        """
        tire = create_tire_model(unit_price_cents=10000, original_tread_32nds=10, stock_qty=3)
        data = validate_success(api.discontinue_tire_model(tire["id"], INV))
        assert data["status"] == "DISCONTINUED"

    def test_get_work_order_summary_reflects_pricing(self, api):
        """PRD §3.2: "Orders may be fetched with all their computed money fields".
        PRD §3.2: "`parts_subtotal_cents` is the sum of `extended_cents` over `TIRE` lines".
        PRD §3.2: "`tax_cents` is that taxable base multiplied by the tax rate of 8.25 percent,
        rounded half up to a whole cent in this single rounding step."

        unit 10000 qty 2 -> parts 20000; disposal at 2 tires = 2*350 = 700;
        taxable 20000, tax round_half_up(1650.0)=1650; total = 20000+700+1650 = 22350.

        Design: Corner/endpoints/get_work_order_summary_reflects_pricing
        """
        customer, vehicle, tire, wo, line, approved = setup_approved_order_with_tire_line(
            quantity=2, tire_overrides={"unit_price_cents": 10000, "mileage_warranty_miles": 60000,
                                        "original_tread_32nds": 10, "stock_qty": 8})
        fetched = validate_success(api.get_work_order(wo["id"], ADVISOR))
        assert fetched["parts_subtotal_cents"] == 20000
        assert fetched["disposal_fee_cents"] == 700
        assert fetched["tax_cents"] == 1650
        assert fetched["total_due_cents"] == 22350
