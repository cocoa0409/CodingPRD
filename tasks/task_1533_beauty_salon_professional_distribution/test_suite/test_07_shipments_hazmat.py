"""Shipments: hazmat method pairing and surcharges, diversion holds, quantity
guards, label lifecycle (PRD §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_order,
    assert_shipment,
    create_active_salon,
    create_draft_order,
    file_diversion_case,
    get_order,
    list_order_line_items,
    make_brand,
    make_compliance_officer_headers,
    make_product,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_operator_headers"]


def _approved_order(api, product, quantity, salon=None):
    """ACTIVE salon (created when absent) + submitted + approved order."""
    if salon is None:
        salon, _ = create_active_salon()
    order = create_draft_order(
        salon["id"], [{"product_id": product["id"], "quantity": quantity}])
    submit_order(order["id"], salon["id"])
    approve_order(order["id"])
    return salon, order


def _sole_item_id(order_id):
    items = list_order_line_items(order_id)
    assert len(items) == 1
    return items[0]["id"]


class TestHazmatChargesAndGuards:
    def test_hazmat_surcharge_computation(self, api):
        """PRD §3.7: "When that sum is zero, `hazmat_surcharge_cents` is 0 and
        `hazmat_declaration_required` is false; otherwise
        `hazmat_declaration_required` is true and `hazmat_surcharge_cents` is
        2500 cents flat plus 2 cents per hazmat gram. The shipment's
        `shipping_charge_cents` is the method base — 1200 cents for `GROUND`,
        3000 cents for `AIR` — plus the surcharge."
        PRD §3.7: "Creating the first shipment for an order moves it
        `APPROVED` → `FULFILLING`; the order's `shipping_total_cents` and
        `grand_total_cents` recompute."

        Design: Corner/calculations/hazmat_surcharge_computation
        """
        brand = make_brand()
        aerosol = make_product(brand["id"], hazmat_class="AEROSOL",
                               base_price_cents=5000, weight_grams=400)
        salon, order = _approved_order(api, aerosol, 3)
        item_id = _sole_item_id(order["id"])

        shipment = validate_success(api.create_shipment(
            order["id"],
            {"method": "GROUND",
             "items": [{"order_item_id": item_id, "quantity": 3}]},
            WAREHOUSE), 201)
        assert_shipment(shipment)
        assert shipment["hazmat_declaration_required"] is True
        assert shipment["hazmat_surcharge_cents"] == 4900, (
            "2500 + 2 * (3 x 400g) == 4900")
        assert shipment["shipping_charge_cents"] == 6100, (
            "GROUND base 1200 + surcharge 4900 == 6100")

        refreshed = get_order(order["id"])
        assert refreshed["fulfillment_status"] == "FULFILLING"
        assert refreshed["grand_total_cents"] == 21100, (
            "net 15000 + shipping 6100 == 21100")

    def test_hazmat_air_violation_masks_quantity_overrun(self, api):
        """PRD §3.7: "Three guards apply at creation, in the validation
        pipeline's order. The hazmat rule: if any shipped item's product has a
        `hazmat_class` other than `NONE`, the shipment must use `GROUND`;
        pairing hazmat with `AIR` is rejected with `ERR_HAZMAT_AIR_FORBIDDEN`
        (HTTP 422)."
        PRD §3.7: "The quantity rule: every referenced line must belong to
        this order, and per-line shipped quantities across the order's
        non-voided shipments must not exceed the ordered quantity —
        `ERR_SHIPMENT_QUANTITY_EXCEEDS_ORDER` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/shipment_hazmat_air_beats_quantity_overrun
        """
        brand = make_brand()
        aerosol = make_product(brand["id"], hazmat_class="AEROSOL",
                               base_price_cents=5000, weight_grams=400)
        salon, order = _approved_order(api, aerosol, 2)
        item_id = _sole_item_id(order["id"])

        resp = api.create_shipment(
            order["id"],
            {"method": "AIR",
             "items": [{"order_item_id": item_id, "quantity": 5}]},
            WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_HAZMAT_AIR_FORBIDDEN)

        shipments, meta = validate_paginated(
            api.list_shipments(order["id"], ADMIN))
        assert meta["total_count"] == 0, (
            "a rejected shipment create persists no shipment row")

    def test_hazmat_air_rejected_even_at_valid_quantity(self, api):
        """PRD §3.7: "The hazmat rule: if any shipped item's product has a
        `hazmat_class` other than `NONE`, the shipment must use `GROUND`;
        pairing hazmat with `AIR` is rejected with `ERR_HAZMAT_AIR_FORBIDDEN`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/shipment_hazmat_air_beats_quantity_overrun
        """
        brand = make_brand()
        aerosol = make_product(brand["id"], hazmat_class="AEROSOL",
                               base_price_cents=5000, weight_grams=400)
        salon, order = _approved_order(api, aerosol, 2)
        item_id = _sole_item_id(order["id"])

        resp = api.create_shipment(
            order["id"],
            {"method": "AIR",
             "items": [{"order_item_id": item_id, "quantity": 2}]},
            WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_HAZMAT_AIR_FORBIDDEN)

    def test_shipment_quantity_overrun_returns_409(self, api):
        """PRD §3.7: "The quantity rule: every referenced line must belong to
        this order, and per-line shipped quantities across the order's
        non-voided shipments must not exceed the ordered quantity —
        `ERR_SHIPMENT_QUANTITY_EXCEEDS_ORDER` (HTTP 409)."

        Design: Corner/validations/shipment_quantity_overrun_returns_409
        """
        brand = make_brand()
        lotion = make_product(brand["id"], base_price_cents=4000)
        salon, order = _approved_order(api, lotion, 2)
        item_id = _sole_item_id(order["id"])

        resp = api.create_shipment(
            order["id"],
            {"method": "GROUND",
             "items": [{"order_item_id": item_id, "quantity": 5}]},
            WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_QUANTITY_EXCEEDS_ORDER)


class TestDiversionHoldGate:
    def _approved_order_with_open_hold(self, api):
        salon, consultant = create_active_salon()
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=6000,
                               weight_grams=200)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 2}])
        submit_order(order["id"], salon["id"])
        approve_order(order["id"])
        case = file_diversion_case(
            salon["id"], product["id"], severity="MINOR",
            evidence_note="online listing", hold_shipments=True,
            filer_consultant_id=consultant["id"])
        return salon, order, case

    def test_shipment_blocked_while_diversion_hold_open(self, api):
        """PRD §3.7: "The diversion hold rule: if the order's salon has any
        diversion case in `OPEN` or `UNDER_REVIEW` with `hold_shipments` true,
        shipment creation is rejected with `ERR_SHIPMENT_HELD_DIVERSION`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/shipment_blocked_by_open_diversion_hold
        """
        salon, order, case = self._approved_order_with_open_hold(api)
        item_id = _sole_item_id(order["id"])
        resp = api.create_shipment(
            order["id"],
            {"method": "GROUND",
             "items": [{"order_item_id": item_id, "quantity": 2}]},
            WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_HELD_DIVERSION)

    def test_shipment_allowed_after_hold_case_dismissed(self, api):
        """PRD §3.11: "Dismissal is available from either `OPEN` or
        `UNDER_REVIEW`, carries the same segregation-of-duties check, stamps
        `adjudicated_by_user_id`, and ends the `hold_shipments` effect."
        PRD §3.7: "When that sum is zero, `hazmat_surcharge_cents` is 0 and
        `hazmat_declaration_required` is false"

        Design: Difficulty/cross_entity_state_dependency/shipment_blocked_by_open_diversion_hold
        """
        salon, order, case = self._approved_order_with_open_hold(api)
        item_id = _sole_item_id(order["id"])

        # A different officer than the filer dismisses the case.
        dismissed = validate_success(api.dismiss_diversion_case(
            case["id"], make_compliance_officer_headers("officer-9")), 200)
        assert dismissed["status"] == "DISMISSED"

        shipment = validate_success(api.create_shipment(
            order["id"],
            {"method": "GROUND",
             "items": [{"order_item_id": item_id, "quantity": 2}]},
            WAREHOUSE), 201)
        assert shipment["status"] == "PLANNED"
        assert shipment["hazmat_declaration_required"] is False
        assert shipment["shipping_charge_cents"] == 1200


class TestShipmentLabelLifecycle:
    def test_shipment_void_label_cycle_restores_planned(self, api):
        """PRD §3.7: "Creating its label moves it to `LABEL_CREATED`; voiding
        the label returns it to `PLANNED` and withdraws that shipment's
        `shipping_charge_cents` from the order's `shipping_total_cents`,
        recomputing `grand_total_cents`."

        Design: Corner/state_machines/shipment_void_label_cycle_restores_planned
        """
        brand = make_brand()
        paste = make_product(brand["id"], base_price_cents=6000)
        salon, order = _approved_order(api, paste, 1)
        item_id = _sole_item_id(order["id"])

        shipment = validate_success(api.create_shipment(
            order["id"],
            {"method": "GROUND",
             "items": [{"order_item_id": item_id, "quantity": 1}]},
            WAREHOUSE), 201)
        validate_success(api.create_shipment_label(shipment["id"], WAREHOUSE), 200)

        voided = validate_success(
            api.void_shipment_label(shipment["id"], WAREHOUSE), 200)
        assert voided["status"] == "PLANNED", "void cycles back to PLANNED"

        refreshed = get_order(order["id"])
        assert refreshed["shipping_total_cents"] == 0, (
            "the voided shipment's charge is withdrawn from the order totals")
        assert refreshed["grand_total_cents"] == 6000

    def test_ship_before_label_rejected(self, api):
        """PRD §3.7: "Every shipment transition attempted from a non-matching
        status is rejected with `ERR_INVALID_SHIPMENT_STATE` (HTTP 409)."

        Design: Corner/state_machines/ship_before_label_rejected
        """
        brand = make_brand()
        balm = make_product(brand["id"], base_price_cents=6000)
        salon, order = _approved_order(api, balm, 1)
        item_id = _sole_item_id(order["id"])
        shipment = validate_success(api.create_shipment(
            order["id"],
            {"method": "GROUND",
             "items": [{"order_item_id": item_id, "quantity": 1}]},
            WAREHOUSE), 201)

        resp = api.ship_shipment(shipment["id"], WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_INVALID_SHIPMENT_STATE)
        after = validate_success(api.get_shipment(shipment["id"], ADMIN), 200)
        assert after["status"] == "PLANNED"

