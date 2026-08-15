"""Reel length accounting, cut-waste policy, and confirm-time reel gating
(PRD §2.7, §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_reel_length_invariant,
    cancel_assembly_order,
    create_assembly_order,
    create_customer,
    create_reel,
    confirm_assembly_order,
    get_reel,
    validate_error,
    validate_success,
)


class TestCutLengthBoundary:
    def test_cut_exactly_equal_to_remaining_is_clean_cut(self, api):
        """PRD §3.3: "Fifth, the `cut_length_mm` must not exceed the reel's `remaining_length_mm` — a cut exactly equal to what remains is permitted — with shortfalls rejected as `ERR_INSUFFICIENT_REEL_LENGTH`."
        PRD §3.3: "A remnant of exactly zero is a clean cut — nothing is scrapped and the reel drops to `DEPLETED`."

        reel 5000mm (LOW, usable), cut 5000mm -> confirm succeeds, remaining 0,
        scrap 0 (the 0 < MIN_REMNANT_MM remnant is NOT scrapped), reel DEPLETED, waste 0.

        Design: Difficulty/boundary_precision_check/cut_length_exactly_equals_remaining
        """
        cust = create_customer(name="EdgeCo")
        reel = create_reel(hose_sku="PARK-387-8E", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=5000)
        order = create_assembly_order(
            cust["id"], reel["id"],
            cut_length_mm=5000, required_working_pressure_psi=2000,
            crimp_diameter_spec_mm=25.0, estimated_labor_minutes=10)

        res = api.confirm_assembly_order(order["id"], {},
                                         TEST_USERS["counter_sales_headers"])
        confirmed = validate_success(res, 200)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["scrap_charged_mm"] == 0
        assert confirmed["waste_surcharge_cents"] == 0

        reel_after = validate_success(
            api.get_reel(reel["id"], TEST_USERS["shop_manager_headers"]), 200)
        assert reel_after["remaining_length_mm"] == 0
        assert reel_after["scrap_length_mm"] == 0, (
            "remaining_after == 0 is the clean-cut branch, not a scrap")
        assert reel_after["status"] == "DEPLETED"

    def test_cut_one_millimeter_over_remaining_rejected(self, api):
        """PRD §3.3: "Fifth, the `cut_length_mm` must not exceed the reel's `remaining_length_mm` — a cut exactly equal to what remains is permitted — with shortfalls rejected as `ERR_INSUFFICIENT_REEL_LENGTH`."

        cut 5001mm on a 5000mm reel exceeds what remains -> ERR_INSUFFICIENT_REEL_LENGTH.

        Design: Difficulty/boundary_precision_check/cut_length_exactly_equals_remaining
        """
        cust = create_customer(name="EdgeCo")
        reel = create_reel(hose_sku="PARK-387-8E", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=5000)
        order = create_assembly_order(
            cust["id"], reel["id"],
            cut_length_mm=5001, required_working_pressure_psi=2000,
            crimp_diameter_spec_mm=25.0, estimated_labor_minutes=10)

        res = api.confirm_assembly_order(order["id"], {},
                                         TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_REEL_LENGTH,
                       expected_status=422)

        order_after = validate_success(
            api.get_assembly_order(order["id"],
                                   TEST_USERS["counter_sales_headers"]), 200)
        assert order_after["status"] == "DRAFT"
        reel_after = validate_success(
            api.get_reel(reel["id"], TEST_USERS["shop_manager_headers"]), 200)
        assert reel_after["remaining_length_mm"] == 5000

    def test_remnant_exactly_one_meter_is_kept(self, api):
        """PRD §2.7: "A remnant shorter than 1,000 millimeters — one meter — is too short to sell again and must be scrapped."
        PRD §3.3: "A remnant of at least one meter simply stays on the reel."

        reel 6000mm, cut 5000mm -> remnant exactly 1000mm is KEPT (strict < rule):
        no scrap, no waste surcharge, reel drops to LOW not DEPLETED.

        Design: Corner/calculations/remnant_exactly_min_is_kept
        """
        cust = create_customer(name="RemnantCo")
        reel = create_reel(hose_sku="PARK-387-8M", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=6000)
        order = create_assembly_order(
            cust["id"], reel["id"],
            cut_length_mm=5000, required_working_pressure_psi=2000,
            crimp_diameter_spec_mm=25.0, estimated_labor_minutes=10)

        confirmed = confirm_assembly_order(order["id"])
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["scrap_charged_mm"] == 0
        assert confirmed["waste_surcharge_cents"] == 0

        reel_after = validate_success(
            api.get_reel(reel["id"], TEST_USERS["shop_manager_headers"]), 200)
        assert reel_after["remaining_length_mm"] == 1000
        assert reel_after["scrap_length_mm"] == 0
        assert reel_after["status"] == "LOW", (
            "1000mm reaches at least one meter but is below twenty meters -> LOW")


class TestCancelRestoresReel:
    def _setup_depleted_reel_order(self):
        cust = create_customer(name="RestoreCo")
        reel = create_reel(hose_sku="PARK-387-8X", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        order = create_assembly_order(
            cust["id"], reel["id"],
            cut_length_mm=49500, required_working_pressure_psi=2000,
            crimp_diameter_spec_mm=25.0, estimated_labor_minutes=10)
        confirm_assembly_order(order["id"])
        return cust, reel, order

    def test_cancel_from_confirmed_restores_length_and_scrap(self, api):
        """PRD §3.5: "From `CONFIRMED`, the reel is made whole: its `remaining_length_mm` is credited back the cut length plus the order's `scrap_charged_mm`, its `scrap_length_mm` is reduced by that same scrapped amount, its status is recomputed — so even a `DEPLETED` reel can climb back to `LOW` or `AVAILABLE` — and every coupling reservation is released."

        cut 49500 off 50000 scraps the 500mm remnant (remaining 0, scrap 500, DEPLETED);
        cancel restores remaining 0 + 49500 + 500 = 50000 and scrap 0.

        Design: Difficulty/transitive_cascade/cancel_restores_reel_depth2
        """
        cust, reel, order = self._setup_depleted_reel_order()
        reel_pre = validate_success(
            api.get_reel(reel["id"], TEST_USERS["shop_manager_headers"]), 200)
        assert reel_pre["status"] == "DEPLETED"
        assert reel_pre["remaining_length_mm"] == 0
        assert reel_pre["scrap_length_mm"] == 500

        cancelled = cancel_assembly_order(order["id"])
        assert cancelled["status"] == "CANCELLED"

        reel_post = validate_success(
            api.get_reel(reel["id"], TEST_USERS["shop_manager_headers"]), 200)
        assert reel_post["remaining_length_mm"] == 50000
        assert reel_post["scrap_length_mm"] == 0

    def test_cancel_from_confirmed_flips_reel_status_back_up(self, api):
        """PRD §2.7: "Status moves are automatic in both directions: confirming an order can push a reel down the ladder, and cancelling a confirmed order can bring a `DEPLETED` reel back to `LOW` or even `AVAILABLE`."
        PRD §3.5: "From `CONFIRMED`, the reel is made whole: its `remaining_length_mm` is credited back the cut length plus the order's `scrap_charged_mm`, its `scrap_length_mm` is reduced by that same scrapped amount, its status is recomputed — so even a `DEPLETED` reel can climb back to `LOW` or `AVAILABLE` — and every coupling reservation is released."

        Reel is DEPLETED after the confirm; the cancel restores 50000mm >= 20000mm -> AVAILABLE.

        Design: Difficulty/transitive_cascade/cancel_restores_reel_depth2
        """
        cust, reel, order = self._setup_depleted_reel_order()
        reel_pre = validate_success(
            api.get_reel(reel["id"], TEST_USERS["shop_manager_headers"]), 200)
        assert reel_pre["status"] == "DEPLETED"

        cancel_assembly_order(order["id"])

        reel_post = validate_success(
            api.get_reel(reel["id"], TEST_USERS["shop_manager_headers"]), 200)
        assert reel_post["status"] == "AVAILABLE", (
            "50000mm is at least twenty meters -> AVAILABLE after restoration")


class TestReelLengthConservation:
    def _setup_two_confirmed_orders(self):
        cust = create_customer(name="InvCo")
        reel = create_reel(hose_sku="PARK-387-8I", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        o1 = create_assembly_order(cust["id"], reel["id"], cut_length_mm=12000,
                                   required_working_pressure_psi=2000,
                                   crimp_diameter_spec_mm=25.0,
                                   estimated_labor_minutes=10)
        confirm_assembly_order(o1["id"])
        o2 = create_assembly_order(cust["id"], reel["id"], cut_length_mm=8000,
                                   required_working_pressure_psi=2000,
                                   crimp_diameter_spec_mm=25.0,
                                   estimated_labor_minutes=10)
        confirm_assembly_order(o2["id"])
        return cust, reel, o1, o2

    def test_cancel_releases_only_the_cancelled_order_cut(self, api):
        """PRD §3.3: "The reel's `remaining_length_mm` is debited by the cut length plus whatever was scrapped, and its status is recomputed against the ladder — `DEPLETED` below one meter, `LOW` below twenty meters, otherwise `AVAILABLE`."
        PRD §3.5: "From `CONFIRMED`, the reel is made whole: its `remaining_length_mm` is credited back the cut length plus the order's `scrap_charged_mm`, its `scrap_length_mm` is reduced by that same scrapped amount, its status is recomputed — so even a `DEPLETED` reel can climb back to `LOW` or `AVAILABLE` — and every coupling reservation is released."

        O1 cut 12000 + O2 cut 8000 confirmed; cancel O1 -> remaining 30000 + 12000 = 42000,
        scrap 0, status AVAILABLE.

        Design: Difficulty/compensating_invariant/reel_length_conservation
        """
        cust, reel, o1, o2 = self._setup_two_confirmed_orders()
        reel_mid = validate_success(
            api.get_reel(reel["id"], TEST_USERS["shop_manager_headers"]), 200)
        assert reel_mid["remaining_length_mm"] == 30000

        cancel_assembly_order(o1["id"])

        reel_post = validate_success(
            api.get_reel(reel["id"], TEST_USERS["shop_manager_headers"]), 200)
        assert reel_post["remaining_length_mm"] == 42000
        assert reel_post["scrap_length_mm"] == 0
        assert reel_post["status"] == "AVAILABLE"

    def test_reel_length_ledger_invariant_holds(self, api):
        """PRD §3.3: "The reel's `remaining_length_mm` is debited by the cut length plus whatever was scrapped, and its status is recomputed against the ladder — `DEPLETED` below one meter, `LOW` below twenty meters, otherwise `AVAILABLE`."
        PRD §3.5: "From `CONFIRMED`, the reel is made whole: its `remaining_length_mm` is credited back the cut length plus the order's `scrap_charged_mm`, its `scrap_length_mm` is reduced by that same scrapped amount, its status is recomputed — so even a `DEPLETED` reel can climb back to `LOW` or `AVAILABLE` — and every coupling reservation is released."

        Invariant: initial 50000 == remaining 42000 + scrap 0 + O2's committed cut 8000.

        Design: Difficulty/compensating_invariant/reel_length_conservation
        """
        cust, reel, o1, o2 = self._setup_two_confirmed_orders()
        cancel_assembly_order(o1["id"])

        reel_post = validate_success(
            api.get_reel(reel["id"], TEST_USERS["shop_manager_headers"]), 200)
        o2_after = validate_success(
            api.get_assembly_order(o2["id"], TEST_USERS["counter_sales_headers"]),
            200)
        assert o2_after["status"] == "CONFIRMED", (
            "Cancelling O1 must not disturb the still-committed O2")
        assert_reel_length_invariant(reel_post, committed_cut_mm=8000)


class TestConfirmReelGating:
    def test_confirm_blocked_once_reel_is_depleted(self, api):
        """PRD §3.3: "Third, the reel must be usable — `AVAILABLE` or `LOW`, never `DEPLETED` or `RETIRED` — or the confirm is rejected with `ERR_REEL_NOT_USABLE`."
        PRD §2.7: "Below one meter it is `DEPLETED`, and no further order can be confirmed against it."

        O1 cut 5000 drains the 5000mm reel to DEPLETED; O2's confirm is rejected
        and O2 remains DRAFT.

        Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_depleted_reel
        """
        cust = create_customer(name="GateCo")
        reel = create_reel(hose_sku="PARK-387-8G", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=5000)
        o1 = create_assembly_order(cust["id"], reel["id"], cut_length_mm=5000,
                                   required_working_pressure_psi=2000,
                                   crimp_diameter_spec_mm=25.0,
                                   estimated_labor_minutes=10)
        confirm_assembly_order(o1["id"])
        assert get_reel(reel["id"])["status"] == "DEPLETED"

        o2 = create_assembly_order(cust["id"], reel["id"], cut_length_mm=1000,
                                   required_working_pressure_psi=2000,
                                   crimp_diameter_spec_mm=25.0,
                                   estimated_labor_minutes=10)
        res = api.confirm_assembly_order(o2["id"], {},
                                         TEST_USERS["counter_sales_headers"])
        validate_error(res, ApiErrorId.ERR_REEL_NOT_USABLE, expected_status=422)

        o2_after = validate_success(
            api.get_assembly_order(o2["id"], TEST_USERS["counter_sales_headers"]),
            200)
        assert o2_after["status"] == "DRAFT"

    def test_confirm_on_low_reel_is_allowed(self, api):
        """PRD §3.3: "Third, the reel must be usable — `AVAILABLE` or `LOW`, never `DEPLETED` or `RETIRED` — or the confirm is rejected with `ERR_REEL_NOT_USABLE`."
        PRD §2.7: "It becomes `LOW` once the remainder drops below twenty meters but still reaches at least one meter."

        A 6000mm reel sits at LOW (below twenty meters, at least one meter) and
        still accepts a confirm.

        Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_depleted_reel
        """
        cust = create_customer(name="GateCo")
        reel = create_reel(hose_sku="PARK-387-8G", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=6000)
        assert get_reel(reel["id"])["status"] == "LOW"

        order = create_assembly_order(cust["id"], reel["id"], cut_length_mm=1000,
                                      required_working_pressure_psi=2000,
                                      crimp_diameter_spec_mm=25.0,
                                      estimated_labor_minutes=10)
        confirmed = confirm_assembly_order(order["id"])
        assert confirmed["status"] == "CONFIRMED"


class TestReelCreation:
    def test_reel_create_ignores_client_supplied_system_fields(self, api):
        """PRD §3.2: "The reel's `remaining_length_mm` initializes to the full received length, `scrap_length_mm` starts at zero, and the status ladder from §2.7 puts the fresh reel at `AVAILABLE`."

        Client-supplied remaining_length_mm 999 / scrap_length_mm 50 are ignored;
        the server initializes remaining = initial (50000) and scrap = 0.

        Design: Corner/entities/reel_create_system_fields_input_ignored
        """
        res = api.create_reel({
            "hose_sku": "PARK-387-8S", "hose_diameter_in": 0.5,
            "working_pressure_psi": 3000, "price_per_meter_cents": 800,
            "initial_length_mm": 50000,
            "remaining_length_mm": 999, "scrap_length_mm": 50,
        }, TEST_USERS["shop_manager_headers"])
        reel = validate_success(res, 201)
        assert reel["remaining_length_mm"] == 50000
        assert reel["scrap_length_mm"] == 0
        assert reel["status"] == "AVAILABLE"


class TestConfirmResponseConsistency:
    def test_confirm_response_immediately_reflects_mutation(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.3: "A remnant greater than zero but shorter than one meter is written off in full: it is added to the reel's `scrap_length_mm`, recorded on the order as `scrap_charged_mm`, and billed through the waste surcharge, which is recomputed from the freshly recorded scrap."
        PRD §3.3: "The waste surcharge, `waste_surcharge_cents`, converts `scrap_charged_mm` to meters and multiplies by the reel's per-meter price, again rounding half up; it is zero at draft because nothing has been scrapped yet."

        cut 49850mm off a 50000mm reel at 800c/m leaves a 150mm remnant: the confirm
        response itself carries status CONFIRMED, scrap_charged_mm 150,
        waste_surcharge_cents round_half_up(150/1000 x 800) = 120.

        Design: Corner/cross_cutting_layers/confirm_response_immediately_reflects_mutation
        """
        cust = create_customer(name="ImmCo")
        reel = create_reel(hose_sku="PARK-387-8IM", hose_diameter_in=0.5,
                           working_pressure_psi=3000, price_per_meter_cents=800,
                           initial_length_mm=50000)
        order = create_assembly_order(cust["id"], reel["id"], cut_length_mm=49850,
                                      required_working_pressure_psi=2000,
                                      crimp_diameter_spec_mm=25.0,
                                      estimated_labor_minutes=10)

        res = api.confirm_assembly_order(order["id"], {},
                                         TEST_USERS["counter_sales_headers"])
        confirmed = validate_success(res, 200)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["scrap_charged_mm"] == 150
        assert confirmed["waste_surcharge_cents"] == 120
