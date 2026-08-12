"""Registration, catalog reads, request-shape validation, and read-after-write.

Covers customer/component/lot registration rules, the append-only quality-record
shape, request-shape validation, the pagination envelope, not-found handling,
and the immediate-consistency read path.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_component,
    assert_lot,
    create_active_formula,
    create_component,
    create_component_payload,
    create_customer,
    create_formula_payload,
    create_lot_payload,
    create_order,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCustomerRegistration:
    def test_create_customer_missing_credit_limit_rejected(self, api, plant_director_headers):
        """PRD §2.8: "then request-shape validation (`ERR_VALIDATION`, HTTP 400 —
        missing or invalid required fields, invalid enum members, or an ingredient
        list whose percentages fail to sum to 100 within one-hundredth of a point
        in either direction)".
        PRD §3.1: "A `PlantDirector` registers each brand owner as a customer,
        supplying a display `name`, a commercial `tier` of `STANDARD` or
        `PRESTIGE` — prestige brands earn a per-unit filling-fee discount at
        quotation time (§3.4) — a negotiated `minimum_run_units` of at least one
        unit, and a `credit_limit_cents` of zero or more."

        Design: Corner/entities/create_customer_missing_required_field_returns_validation
        """
        resp = api.create_customer(
            {"name": "No Credit Corp", "tier": "STANDARD", "minimum_run_units": 1000},
            plant_director_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestComponentRegistration:
    def test_component_invalid_kind_rejected(self, api, production_planner_headers):
        """PRD §2.8: "then request-shape validation (`ERR_VALIDATION`, HTTP 400 —
        missing or invalid required fields, invalid enum members, or an ingredient
        list whose percentages fail to sum to 100 within one-hundredth of a point
        in either direction)".
        PRD §3.1: "a `kind` drawn from `RAW_MATERIAL`, `BULK_FRAGRANCE`,
        `COLORANT`, `PRIMARY_PACK`, or `SECONDARY_PACK`".

        Design: Corner/validations/invalid_enum_rejected
        """
        resp = api.create_component(
            create_component_payload(name="Mystery", kind="LIQUID"),
            production_planner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestFormulaRegistration:
    def test_ingredient_sum_not_100_rejected(self, api, formulation_chemist_headers):
        """PRD §3.2: "the percentages must sum to exactly 100 within a tolerance
        of one-hundredth of a point in either direction, failing which the request
        is rejected with `ERR_VALIDATION`."

        Design: Corner/validations/ingredient_sum_not_100_rejected
        """
        customer = create_customer()
        component = create_component()
        payload = create_formula_payload(
            customer["id"],
            ingredients=[
                {"inci_name": "AQUA", "component_id": component["id"], "percentage": 60},
                {"inci_name": "OIL", "percentage": 30},
            ],
            name="Bad",
        )
        resp = api.create_formula(payload, formulation_chemist_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestLotReceipt:
    def test_lot_sensorial_defaults_applied(self, api, production_planner_headers):
        """PRD §3.1: "optionally the receipt also records the lot's actual
        `unit_cost_per_kg_cents` and a `sensorial_profile` flag, which defaults to
        `WITHIN_SPEC` and may instead be declared `MINOR_VARIANT` when a fragrance
        or color lot drifts from standard."
        PRD §3.1: "At receipt, `quantity_available` initializes to
        `quantity_received` while `quantity_reserved` and `quantity_consumed` start
        at zero; `variant_waiver` initializes to `PENDING` for a `MINOR_VARIANT`
        lot and to `NOT_REQUIRED` otherwise; and the lot begins life `AVAILABLE`."

        Design: Corner/entities/lot_sensorial_defaults_applied
        """
        component = create_component()
        resp = api.create_lot(
            component["id"],
            create_lot_payload(lot_code="A1", quantity_received=100),
            production_planner_headers,
        )
        lot = validate_success(resp, 201)
        assert_lot(lot)
        assert lot["sensorial_profile"] == "WITHIN_SPEC", "sensorial_profile must default to WITHIN_SPEC"
        assert lot["variant_waiver"] == "NOT_REQUIRED"
        assert lot["status"] == "AVAILABLE"

    def test_lot_available_equals_received_on_create(self, api, production_planner_headers):
        """PRD §3.1: "At receipt, `quantity_available` initializes to
        `quantity_received` while `quantity_reserved` and `quantity_consumed` start
        at zero; `variant_waiver` initializes to `PENDING` for a `MINOR_VARIANT`
        lot and to `NOT_REQUIRED` otherwise; and the lot begins life `AVAILABLE`."

        Design: Corner/entities/lot_available_equals_received_on_create
        """
        component = create_component()
        resp = api.create_lot(
            component["id"],
            create_lot_payload(lot_code="A1", quantity_received=250),
            production_planner_headers,
        )
        lot = validate_success(resp, 201)
        assert_lot(lot)
        assert lot["quantity_available"] == 250
        assert lot["quantity_reserved"] == 0
        assert lot["quantity_consumed"] == 0


class TestOrderListingAndLookup:
    def test_get_order_not_found_returns_404(self, api, production_planner_headers):
        """PRD §2.8: "then existence of every identifier in the path and every
        referenced foreign identifier in the body (`formula_id`, `lot_id`,
        `line_id`, `batch_id`, `chamber_id`, `component_id`, and the like — any
        missing one yields `ERR_NOT_FOUND`, HTTP 404)".

        Design: Corner/entities/get_order_not_found_returns_404
        """
        resp = api.get_order(NON_EXISTENT_UUID, production_planner_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_list_orders_pagination_envelope(self, api, production_planner_headers):
        """PRD §2.3: "`limit` sets the maximum number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
        the number of items to skip and defaults to 0."
        PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
        `total_count`, `has_more`) are included for list endpoints."

        Design: Corner/entities/list_orders_pagination_envelope
        """
        customer = create_customer()
        component = create_component()
        formula = create_active_formula(customer["id"], component_id=component["id"])
        create_order(customer["id"], formula["id"], 1000)
        create_order(customer["id"], formula["id"], 1500)

        resp = api.list_orders(production_planner_headers, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert len(data) == 1


class TestImmediateConsistency:
    def test_immediate_consistency_read_after_write(self, api, production_planner_headers):
        """PRD §2.9: "the platform follows an immediate-consistency model with no
        deferred reconciliation."
        PRD §2.4: "`version` (integer): starts at 1 and increments by one on every
        mutation — including system-driven cascade transitions, counter updates,
        and computed-field recomputation — providing the basis for optimistic
        concurrency control (§2.7)."

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        created = create_component(name="Water", kind="RAW_MATERIAL",
                                   supply_mode="MANUFACTURER_SUPPLIED",
                                   standard_cost_per_kg_cents=1000)
        resp = api.get_component(created["id"], production_planner_headers)
        fetched = validate_success(resp, 200)
        assert_component(fetched)
        assert fetched["name"] == "Water"
        assert fetched["kind"] == "RAW_MATERIAL"
        assert fetched["version"] == 1
        assert is_valid_uuid(fetched["id"])
        assert is_iso8601_timestamp(fetched["created_at"])
        assert is_iso8601_timestamp(fetched["updated_at"])
