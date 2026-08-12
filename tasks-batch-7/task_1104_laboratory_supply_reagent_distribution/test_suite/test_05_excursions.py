"""Cold-chain telemetry and excursions: provisional vs final credit variants,
severity classification, the DESTROYED refund cascade, balance restoration,
and excursion state/role guards."""
from test_helpers import (
    ApiErrorId,
    get_customer,
    get_excursion,
    get_order,
    get_shipment,
    get_success_data,
    setup_in_transit_shipment,
    setup_open_excursion,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
QUALITY = TEST_USERS["quality_manager_headers"]


class TestExcursionCreditVariants:
    def test_excursion_provisional_credit_at_open(self, api):
        """PRD §3.6: "The new excursion records its `shipment_id`, the breaching `peak_temp_celsius`, the reported `duration_minutes`, and the computed `deviation_degrees`, classifies its `severity` — `CRITICAL` when the deviation exceeds 5.0 degrees or the duration reaches at least 240 minutes, otherwise `MAJOR` when the deviation exceeds 2.0 degrees or the duration reaches at least 60 minutes, otherwise `MINOR` — and stores a `provisional_credit_cents` estimate: half of the affected value, rounded half up, where the affected value is the sum of `line_total_cents` over the order's lines whose product `requires_cold_chain`."

        Design: Difficulty/dual_variant_calc/excursion_credit_provisional_vs_final_destroyed
        """
        ctx = setup_open_excursion(api, temp_celsius=12.5, duration_minutes=90,
                                   actual_weight_grams=3000)
        reading = ctx["reading"]
        assert reading["excursion_created"] is True
        # 12.5C against band [2, 8]: deviation 4.5 (> 2.0) and 90 min (>= 60) -> MAJOR.
        assert reading["severity"] == "MAJOR"
        assert reading["shipment_status"] == "EXCURSION_HOLD"

        excursion = get_excursion(api, ctx["excursion_id"])
        assert excursion["status"] == "OPEN"
        # affected value = 2 x 20000 = 40000 (the only line requires cold chain).
        assert excursion["provisional_credit_cents"] == 20000, (
            f"round_half_up(40000 * 0.5): {excursion}"
        )
        assert excursion["final_credit_cents"] is None, (
            "final credit stays null until disposition"
        )

    def test_excursion_final_credit_destroyed_diverges(self, api):
        """PRD §3.6: "A `DESTROYED` disposition sets the final credit to the full affected cold-chain product value and fires the refund cascade:"
        PRD §3.6: "The final credit is the credit-memo record of the refund basis; the actual balance movement is always the full invoice reversal."

        Design: Difficulty/dual_variant_calc/excursion_credit_provisional_vs_final_destroyed
        """
        ctx = setup_open_excursion(api, temp_celsius=12.5, duration_minutes=90,
                                   actual_weight_grams=3000)
        provisional = get_excursion(api, ctx["excursion_id"])["provisional_credit_cents"]

        resp = api.disposition_excursion(ctx["excursion_id"], {"decision": "DESTROYED"}, QUALITY)
        excursion = validate_success(resp, 200)
        assert excursion["status"] == "DESTROYED"
        assert excursion["severity"] == "MAJOR"
        assert excursion["final_credit_cents"] == 40000, (
            "DESTROYED credits 100% of the affected cold-chain value"
        )
        assert provisional != excursion["final_credit_cents"], (
            "the two variants disagree on identical order data: 20000 vs 40000"
        )


class TestExcursionDestroyCascade:
    def test_excursion_destroy_cascade_statuses(self, api):
        """PRD §3.6: "A `DESTROYED` disposition sets the final credit to the full affected cold-chain product value and fires the refund cascade: the shipment moves from `EXCURSION_HOLD` to `RETURNED`, the order moves from `SHIPPED` to `REFUNDED`, and the customer's `outstanding_balance_cents` is reduced by the order's `product_total_cents` plus the shipment's `final_freight_cents` — a full invoice reversal with freight waived."

        Design: Difficulty/transitive_cascade/excursion_destroy_cascade_depth3
        """
        ctx = setup_open_excursion(api, temp_celsius=12.5, duration_minutes=90,
                                   actual_weight_grams=3000)
        resp = api.disposition_excursion(ctx["excursion_id"], {"decision": "DESTROYED"}, QUALITY)
        excursion = validate_success(resp, 200)
        assert excursion["status"] == "DESTROYED"
        assert excursion["final_credit_cents"] == 40000
        assert get_shipment(api, ctx["shipment"]["id"])["status"] == "RETURNED", "hop 1"
        assert get_order(api, ctx["order"]["id"])["status"] == "REFUNDED", "hop 2"

    def test_excursion_destroy_cascade_reverses_invoice(self, api):
        """PRD §3.6: "the customer's `outstanding_balance_cents` is reduced by the order's `product_total_cents` plus the shipment's `final_freight_cents` — a full invoice reversal with freight waived."
        PRD §3.3: "`REFUNDED` orders contribute nothing — the reversal removes them from the set."

        Design: Difficulty/transitive_cascade/excursion_destroy_cascade_depth3
        """
        ctx = setup_open_excursion(api, temp_celsius=12.5, duration_minutes=90,
                                   actual_weight_grams=3000)
        # Invoice posted at dispatch: 40000 product + 2300 final freight.
        assert get_customer(api, ctx["customer"]["id"])["outstanding_balance_cents"] == 42300

        get_success_data(
            api.disposition_excursion(ctx["excursion_id"], {"decision": "DESTROYED"}, QUALITY)
        )
        customer = get_customer(api, ctx["customer"]["id"])
        assert customer["outstanding_balance_cents"] == 0, (
            f"hop 3: the 42300 invoice is fully reversed: {customer}"
        )


class TestDispatchThenDestroyBalanceInvariant:
    def test_dispatch_then_destroy_restores_customer_balance(self, api):
        """PRD §3.5: "the invoice posts by adding `product_total_cents` plus `final_freight_cents` to the customer's `outstanding_balance_cents`"
        PRD §3.6: "the customer's `outstanding_balance_cents` is reduced by the order's `product_total_cents` plus the shipment's `final_freight_cents` — a full invoice reversal with freight waived."

        Design: Difficulty/compensating_invariant/dispatch_then_destroy_restores_customer_balance
        """
        ctx = setup_in_transit_shipment(api, actual_weight_grams=3000)
        after_dispatch = get_customer(api, ctx["customer"]["id"])
        assert after_dispatch["outstanding_balance_cents"] == 42300, (
            "invoice 40000 + 2300 posted at dispatch"
        )
        reading = get_success_data(
            api.record_temperature(
                ctx["shipment"]["id"],
                {"temp_celsius": 12.5, "duration_minutes": 90},
                CLERK,
            )
        )
        get_success_data(
            api.disposition_excursion(reading["excursion_id"], {"decision": "DESTROYED"}, QUALITY)
        )
        after_destroy = get_customer(api, ctx["customer"]["id"])
        assert after_destroy["outstanding_balance_cents"] == 0, (
            "money conservation: 42300 invoiced then exactly 42300 reversed"
        )

    def test_dispatch_then_destroy_terminal_states(self, api):
        """PRD §3.6: "the shipment moves from `EXCURSION_HOLD` to `RETURNED`, the order moves from `SHIPPED` to `REFUNDED`, and the customer's `outstanding_balance_cents` is reduced by the order's `product_total_cents` plus the shipment's `final_freight_cents` — a full invoice reversal with freight waived."
        PRD §3.4: "`DELIVERED`, `CANCELLED`, and `REFUNDED` are the order's terminal states."

        Design: Difficulty/compensating_invariant/dispatch_then_destroy_restores_customer_balance
        """
        ctx = setup_open_excursion(api, temp_celsius=12.5, duration_minutes=90,
                                   actual_weight_grams=3000)
        get_success_data(
            api.disposition_excursion(ctx["excursion_id"], {"decision": "DESTROYED"}, QUALITY)
        )
        assert get_order(api, ctx["order"]["id"])["status"] == "REFUNDED"
        assert get_shipment(api, ctx["shipment"]["id"])["status"] == "RETURNED"
        assert get_customer(api, ctx["customer"]["id"])["outstanding_balance_cents"] == 0


class TestSeverityBoundaries:
    def test_severity_boundary_59_vs_60_minutes(self, api):
        """PRD §3.6: "classifies its `severity` — `CRITICAL` when the deviation exceeds 5.0 degrees or the duration reaches at least 240 minutes, otherwise `MAJOR` when the deviation exceeds 2.0 degrees or the duration reaches at least 60 minutes, otherwise `MINOR`"
        PRD §3.6: "A reading is tested against the shipment's band: the `deviation_degrees` is the amount by which the temperature exceeds `temp_max_celsius` or falls below `temp_min_celsius`, and an in-band reading — deviation exactly zero — is accepted without creating anything."

        Design: Corner/calculations/severity_boundary_59_vs_60_minutes
        """
        ctx_a = setup_in_transit_shipment(api, quantity=1, coolant_type="GEL_PACK",
                                          coolant_units=1)
        reading_a = get_success_data(
            api.record_temperature(
                ctx_a["shipment"]["id"],
                {"temp_celsius": 9.0, "duration_minutes": 59},
                CLERK,
            )
        )
        # deviation 1.0 (9.0 vs band max 8): below the >2.0 gate; 59 < 60 -> MINOR.
        assert reading_a["excursion_created"] is True
        assert reading_a["severity"] == "MINOR"

        ctx_b = setup_in_transit_shipment(api, quantity=1, coolant_type="GEL_PACK",
                                          coolant_units=1, product_overrides={"sku": "RG-101"})
        reading_b = get_success_data(
            api.record_temperature(
                ctx_b["shipment"]["id"],
                {"temp_celsius": 9.0, "duration_minutes": 60},
                CLERK,
            )
        )
        # duration 60 reaches the >= 60 MAJOR gate.
        assert reading_b["excursion_created"] is True
        assert reading_b["severity"] == "MAJOR"


class TestExcursionGuards:
    def test_second_breach_reading_while_excursion_open_rejected(self, api):
        """PRD §3.6: "An out-of-band reading opens a temperature excursion, provided none of this shipment's excursions is still `OPEN` (a second breach while one is open is rejected with `ERR_EXCURSION_ALREADY_OPEN`)."

        Design: Corner/state_machines/second_breach_reading_while_excursion_open_rejected
        """
        ctx = setup_open_excursion(api, temp_celsius=12.5, duration_minutes=90,
                                   actual_weight_grams=3000)
        resp = api.record_temperature(
            ctx["shipment"]["id"],
            {"temp_celsius": 13.0, "duration_minutes": 10},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_EXCURSION_ALREADY_OPEN)
        assert get_shipment(api, ctx["shipment"]["id"])["status"] == "EXCURSION_HOLD"

    def test_excursion_second_disposition_rejected(self, api):
        """PRD §3.6: "Disposition belongs to the `QualityManager`, who supplies a `decision` on an excursion that must still be `OPEN` (`ERR_EXCURSION_NOT_OPEN`)."

        Design: Corner/state_machines/excursion_second_disposition_rejected
        """
        ctx = setup_open_excursion(api, temp_celsius=12.5, duration_minutes=90,
                                   actual_weight_grams=3000)
        get_success_data(
            api.disposition_excursion(ctx["excursion_id"], {"decision": "DESTROYED"}, QUALITY)
        )
        resp = api.disposition_excursion(ctx["excursion_id"], {"decision": "ACCEPTED"}, QUALITY)
        validate_error(resp, ApiErrorId.ERR_EXCURSION_NOT_OPEN)

        excursion = get_excursion(api, ctx["excursion_id"])
        assert excursion["status"] == "DESTROYED", "the terminal disposition stands"
        assert excursion["final_credit_cents"] == 40000
        assert get_shipment(api, ctx["shipment"]["id"])["status"] == "RETURNED"
        assert get_order(api, ctx["order"]["id"])["status"] == "REFUNDED"

    def test_inventory_clerk_cannot_disposition_excursion(self, api):
        """PRD §3.6: "Disposition belongs to the `QualityManager`, who supplies a `decision` on an excursion that must still be `OPEN` (`ERR_EXCURSION_NOT_OPEN`)."
        PRD §2.1: "Once the context is accepted, each operation is restricted to a designated role list; an authenticated caller whose role is not on that list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/roles/inventory_clerk_cannot_disposition_excursion
        """
        ctx = setup_open_excursion(api, temp_celsius=12.5, duration_minutes=90,
                                   actual_weight_grams=3000)
        resp = api.disposition_excursion(ctx["excursion_id"], {"decision": "ACCEPTED"}, CLERK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_excursion(api, ctx["excursion_id"])["status"] == "OPEN"
