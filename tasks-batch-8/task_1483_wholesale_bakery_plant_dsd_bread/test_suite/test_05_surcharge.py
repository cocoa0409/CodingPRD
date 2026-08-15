"""Surcharge pass-through: provisional vs final variants, publish cascade,
clamp at the 0.15 cap, and missing-index rejection (PRD §3.9, §2.8)."""
from test_helpers import (
    TEST_USERS,
    create_ingredient_index,
    create_plant,
    create_product,
    create_surcharge_schedule,
    setup_surcharge_scenario,
    validate_error,
    validate_success,
)


class TestSurchargeProvisionalVsFinal:
    def test_provisional_uses_forecast_values(self, api):
        """PRD §3.9: "The provisional variant reads `forecast_value`." And:
        "The surcharge in cents is the product's `base_price_cents` multiplied
        by that clamped percentage, rounded half-up to a whole cent."

        Design: Difficulty/dual_variant_calc/surcharge_provisional_vs_final
        """
        ctx = setup_surcharge_scenario(plant_name="Plant Beta")
        schedule = ctx["schedule"]
        # delta_flour = (440-400)/400 = 0.10; delta_butter = (600-600)/600 = 0
        # pct = 0.30*0.10 + 0.10*0.00 = 0.03; cents = round_half_up(249*0.03) = 7
        assert schedule["provisional_surcharge_cents"] == 7, (
            f"provisional must be round_half_up(249*0.03)=7, got {schedule['provisional_surcharge_cents']}"
        )
        assert schedule["status"] == "PROVISIONAL"

    def test_final_uses_published_values_after_both_publish(self, api):
        """PRD §3.9: "The provisional variant reads `forecast_value`; the
        final variant reads `published_value`." PRD §3.9: "Publishing is the
        `PricingAnalyst`'s second act: supplying the `published_value` moves
        the index from `FORECAST` to `PUBLISHED` and fires a two-hop
        cascade. First, every `PROVISIONAL` surcharge schedule for that
        plant and period whose required `FLOUR` and `BUTTER` indices are now
        all `PUBLISHED` finalizes."

        Design: Difficulty/dual_variant_calc/surcharge_provisional_vs_final
        """
        ctx = setup_surcharge_scenario(plant_name="Plant Beta 2")
        schedule = ctx["schedule"]
        idx_flour = ctx["index_flour"]
        idx_butter = ctx["index_butter"]
        product_c = ctx["product_c"]

        # Publish FLOUR first — schedule must remain PROVISIONAL until both
        # required indices are PUBLISHED.
        validate_success(
            api.publish_ingredient_index(
                idx_flour["id"], {"published_value": 500}, TEST_USERS["pricing_headers"]
            )
        )
        mid = validate_success(
            api.get_surcharge_schedule(schedule["id"], TEST_USERS["pricing_headers"])
        )
        assert mid["status"] == "PROVISIONAL", (
            f"with BUTTER still FORECAST the schedule must not finalize, got {mid['status']}"
        )

        validate_success(
            api.publish_ingredient_index(
                idx_butter["id"], {"published_value": 606}, TEST_USERS["pricing_headers"]
            )
        )
        fin = validate_success(
            api.get_surcharge_schedule(schedule["id"], TEST_USERS["pricing_headers"])
        )
        # final: delta_flour = (500-400)/400 = 0.25; delta_butter = (606-600)/600 = 0.01
        # pct = 0.30*0.25 + 0.10*0.01 = 0.076; cents = round_half_up(249*0.076) = 19
        assert fin["status"] == "FINALIZED"
        assert fin["final_surcharge_cents"] == 19, (
            f"final must be round_half_up(249*0.076)=19, got {fin['final_surcharge_cents']}"
        )

        product = validate_success(
            api.get_product(product_c["id"], TEST_USERS["pricing_headers"])
        )
        assert product["current_surcharge_cents"] == 19, (
            f"hop 2 must write Product.current_surcharge_cents=19, got {product['current_surcharge_cents']}"
        )


class TestIndexPublishCascadeScheduleProduct:
    def test_publish_cascade_finalizes_schedule(self, api):
        """PRD §3.9: "First, every `PROVISIONAL` surcharge schedule for that
        plant and period whose required `FLOUR` and `BUTTER` indices are now
        all `PUBLISHED` finalizes: its `final_surcharge_cents` is computed
        with the final variant and its status moves to the terminal
        `FINALIZED`."

        Design: Difficulty/transitive_cascade/index_publish_cascade_schedule_product
        """
        ctx = setup_surcharge_scenario(plant_name="Plant Kappa")
        schedule = ctx["schedule"]
        idx_flour = ctx["index_flour"]
        idx_butter = ctx["index_butter"]

        validate_success(
            api.publish_ingredient_index(
                idx_flour["id"], {"published_value": 500}, TEST_USERS["pricing_headers"]
            )
        )
        validate_success(
            api.publish_ingredient_index(
                idx_butter["id"], {"published_value": 606}, TEST_USERS["pricing_headers"]
            )
        )
        fin = validate_success(
            api.get_surcharge_schedule(schedule["id"], TEST_USERS["pricing_headers"])
        )
        assert fin["status"] == "FINALIZED"
        assert fin["final_surcharge_cents"] == 19

    def test_publish_cascade_updates_product_surcharge(self, api):
        """PRD §3.9: "Second, each affected product's `current_surcharge_cents`
        is set to that final amount, with the product's `version`
        incrementing."

        Design: Difficulty/transitive_cascade/index_publish_cascade_schedule_product
        """
        ctx = setup_surcharge_scenario(plant_name="Plant Kappa 2")
        schedule = ctx["schedule"]
        idx_flour = ctx["index_flour"]
        idx_butter = ctx["index_butter"]
        product_c = ctx["product_c"]

        before = validate_success(
            api.get_product(product_c["id"], TEST_USERS["pricing_headers"])
        )
        assert before["current_surcharge_cents"] == 0

        validate_success(
            api.publish_ingredient_index(
                idx_flour["id"], {"published_value": 500}, TEST_USERS["pricing_headers"]
            )
        )
        validate_success(
            api.publish_ingredient_index(
                idx_butter["id"], {"published_value": 606}, TEST_USERS["pricing_headers"]
            )
        )

        after = validate_success(
            api.get_product(product_c["id"], TEST_USERS["pricing_headers"])
        )
        assert after["current_surcharge_cents"] == 19, (
            f"publish cascade must write Product.current_surcharge_cents=19, got {after['current_surcharge_cents']}"
        )


class TestSurchargeClampedAtMax:
    def test_surcharge_clamped_at_max_pct(self, api):
        """PRD §3.9: "The surcharge percentage is the product's
        `flour_share_pct` multiplied by the flour delta plus its
        `butter_share_pct` multiplied by the butter delta, then clamped so it
        is never below 0 and never above 0.15 — fifteen percent."

        Design: Corner/calculations/surcharge_clamped_at_max_pct
        """
        ctx = setup_surcharge_scenario(plant_name="Plant P Clamp")
        schedule = ctx["schedule"]
        idx_flour = ctx["index_flour"]
        idx_butter = ctx["index_butter"]

        # Publish FLOUR at 800 (delta 1.0): unclamped pct = 0.30*1.0 + 0.10*0 = 0.30
        # Clamp at 0.15 -> round_half_up(249*0.15) = round_half_up(37.35) = 37.
        validate_success(
            api.publish_ingredient_index(
                idx_flour["id"], {"published_value": 800}, TEST_USERS["pricing_headers"]
            )
        )
        validate_success(
            api.publish_ingredient_index(
                idx_butter["id"], {"published_value": 600}, TEST_USERS["pricing_headers"]
            )
        )
        fin = validate_success(
            api.get_surcharge_schedule(schedule["id"], TEST_USERS["pricing_headers"])
        )
        assert fin["status"] == "FINALIZED"
        assert fin["final_surcharge_cents"] == 37, (
            f"clamped at 0.15: round_half_up(249*0.15)=37, got {fin['final_surcharge_cents']}"
        )


class TestSurchargeScheduleWithoutIndices:
    def test_surcharge_schedule_without_indices_rejected(self, api):
        """PRD §3.9: "Creation requires the plant's `FLOUR` and `BUTTER`
        indices for that period to exist in the status the operation needs —
        forecasts at schedule creation, published values at finalization —
        and a missing or wrong-status index is rejected with
        `ERR_INDEX_NOT_PUBLISHED`."

        Design: Corner/validations/surcharge_schedule_without_indices_rejected
        """
        plant = create_plant()
        product_c = create_product(
            plant["id"],
            sku="SKU-C",
            name="Brioche 250",
            unit_weight_g=250,
            base_price_cents=249,
            batch_capacity_units=200,
        )
        resp = api.create_surcharge_schedule(
            {"product_id": product_c["id"], "period": "2026-08"},
            TEST_USERS["pricing_headers"],
        )
        validate_error(resp, "ERR_INDEX_NOT_PUBLISHED", expected_status=409)
