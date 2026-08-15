"""Chip-tracked garments: the full custody round trip driven by cascades, and
the deterministic return-to-customer selection order."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    create_plant, create_linen_category, create_customer,
    create_route, create_stop, dispatch_route, arrive_stop,
    create_batch_posted, stage_wash_load,
    register_garment, set_par_level, get_garment,
    get_customer_version,
)

OPERATOR = TEST_USERS["plant_operator_headers"]
DRIVER = TEST_USERS["route_driver_headers"]


class TestGarmentRoundTrip:
    def _setup(self, api, chip_codes=("CHIP-001",)):
        """Chip-tracking customer + registered garments + stop ARRIVED."""
        plant = create_plant()
        category = create_linen_category(plant["id"])
        customer = create_customer(
            plant["id"], billing_mode="RENTAL", chip_tracking_enabled=True
        )
        set_par_level(customer["id"], category["id"], 10)
        garments = [
            register_garment(customer["id"], category["id"], code)
            for code in chip_codes
        ]
        route = create_route(plant["id"])
        stop = create_stop(
            route["id"], customer["id"], declared_soiled_weight_lb=0.5
        )
        dispatch_route(route["id"])
        arrive_stop(stop["id"])
        return {
            "plant": plant, "category": category, "customer": customer,
            "garments": garments, "route": route, "stop": stop,
        }

    def test_garment_full_round_trip(self, api):
        """PRD §3.6: "From there the garment rides the physical flows described in earlier sections through automatic cascades: pickup of the customer's stop moves `AT_CUSTOMER` garments to `IN_TRANSIT_SOILED`; cart receiving moves `IN_TRANSIT_SOILED` to `SOILED_RECEIVED`; a wash load of the garment's category and customer starting its run moves `SOILED_RECEIVED` to `WASHING`; unloading moves `WASHING` to `CLEAN_STOCK`."
        PRD §3.6: "Finally, when a delivery of the garment's category and customer is marked delivered, `LOADED_OUT` garments return to `AT_CUSTOMER` — up to the delivered piece count, chosen by earliest garment `created_at` first, with ties broken by `chip_code` in ascending order; the chip code serves as a deterministic business key for this selection rather than any random identifier."

        Design: Difficulty/non_linear_state_machine/garment_round_trip_cycle
        """
        ctx = self._setup(api)
        garment = ctx["garments"][0]
        assert garment["state"] == "AT_CUSTOMER"

        # pickup: AT_CUSTOMER -> IN_TRANSIT_SOILED
        validate_success(api.pickup_stop(
            ctx["stop"]["id"],
            {"carts": [{"cart_tag": "CART-1", "scale_weight_lb": 0.5}]},
            DRIVER,
        ), 200)
        assert get_garment(garment["id"])["state"] == "IN_TRANSIT_SOILED"

        # cart receive: IN_TRANSIT_SOILED -> SOILED_RECEIVED
        carts = get_success_data(api.list_carts(ctx["stop"]["id"], OPERATOR))
        validate_success(api.receive_cart(carts[0]["id"], OPERATOR), 200)
        assert get_garment(garment["id"])["state"] == "SOILED_RECEIVED"

        # wash start: SOILED_RECEIVED -> WASHING
        batch = create_batch_posted(ctx["stop"]["id"], [
            {"category_id": ctx["category"]["id"], "pieces": 1},
        ])
        load = stage_wash_load(batch["id"], ctx["category"]["id"])
        validate_success(api.start_wash_load(load["id"], OPERATOR), 200)
        assert get_garment(garment["id"])["state"] == "WASHING"

        # unload: WASHING -> CLEAN_STOCK
        validate_success(api.finish_cycle_wash_load(load["id"], OPERATOR), 200)
        validate_success(api.bypass_test_wash_load(load["id"], OPERATOR), 200)
        validate_success(api.unload_wash_load(load["id"], OPERATOR), 200)
        assert get_garment(garment["id"])["state"] == "CLEAN_STOCK"

        # load-out: CLEAN_STOCK -> LOADED_OUT
        validate_success(api.load_out_garment(garment["id"], OPERATOR), 200)
        assert get_garment(garment["id"])["state"] == "LOADED_OUT"

        # delivery: LOADED_OUT -> AT_CUSTOMER (round trip complete)
        version = get_customer_version(ctx["customer"]["id"], DRIVER)
        delivery = get_success_data(api.create_delivery(
            ctx["stop"]["id"],
            {"category_id": ctx["category"]["id"], "pieces_promised": 1},
            DRIVER,
        ))
        validate_success(api.mark_delivered(
            delivery["id"],
            {"pieces_delivered": 1, "expected_customer_version": version},
            DRIVER,
        ), 200)
        final = get_garment(garment["id"])
        assert final["state"] == "AT_CUSTOMER", (
            f"the round trip must return the garment home, got {final['state']}"
        )

    def test_return_selection_prefers_lowest_chip_code_on_timestamp_tie(self, api):
        """PRD §3.6: "Finally, when a delivery of the garment's category and customer is marked delivered, `LOADED_OUT` garments return to `AT_CUSTOMER` — up to the delivered piece count, chosen by earliest garment `created_at` first, with ties broken by `chip_code` in ascending order; the chip code serves as a deterministic business key for this selection rather than any random identifier."

        Design: Difficulty/non_linear_state_machine/garment_round_trip_cycle
        """
        # Both garments are registered under the unchanged logical clock
        # (PRD §2.5: the clock reads exactly 2026-05-01T00:00:00Z before any
        # clock-setting call), so created_at ties and chip_code decides.
        ctx = self._setup(api, chip_codes=("CHIP-002", "CHIP-001"))
        g_by_chip = {g["chip_code"]: g for g in ctx["garments"]}

        validate_success(api.pickup_stop(
            ctx["stop"]["id"],
            {"carts": [{"cart_tag": "CART-1", "scale_weight_lb": 1.0}]},
            DRIVER,
        ), 200)
        carts = get_success_data(api.list_carts(ctx["stop"]["id"], OPERATOR))
        validate_success(api.receive_cart(carts[0]["id"], OPERATOR), 200)
        batch = create_batch_posted(ctx["stop"]["id"], [
            {"category_id": ctx["category"]["id"], "pieces": 2},
        ])
        load = stage_wash_load(batch["id"], ctx["category"]["id"])
        validate_success(api.start_wash_load(load["id"], OPERATOR), 200)
        validate_success(api.finish_cycle_wash_load(load["id"], OPERATOR), 200)
        validate_success(api.bypass_test_wash_load(load["id"], OPERATOR), 200)
        validate_success(api.unload_wash_load(load["id"], OPERATOR), 200)
        for g in ctx["garments"]:
            validate_success(api.load_out_garment(g["id"], OPERATOR), 200)

        version = get_customer_version(ctx["customer"]["id"], DRIVER)
        delivery = get_success_data(api.create_delivery(
            ctx["stop"]["id"],
            {"category_id": ctx["category"]["id"], "pieces_promised": 2},
            DRIVER,
        ))
        validate_success(api.mark_delivered(
            delivery["id"],
            {"pieces_delivered": 1, "expected_customer_version": version},
            DRIVER,
        ), 200)

        assert get_garment(g_by_chip["CHIP-001"]["id"])["state"] == "AT_CUSTOMER", (
            "on a created_at tie the lower chip_code must return first"
        )
        assert get_garment(g_by_chip["CHIP-002"]["id"])["state"] == "LOADED_OUT", (
            "only one garment returns for one delivered piece"
        )
