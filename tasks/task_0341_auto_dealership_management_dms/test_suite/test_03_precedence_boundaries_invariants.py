"""Validation precedence, numeric boundaries, resource temporal overlaps, and
compensating invariants.

Difficulty queue (A) instances: priority_pair_validation_conflict (state vs
fiscal only), boundary_precision_check, resource_temporal_overlap,
compensating_invariant.

Note: the priority_pair instance conflict_safety_vs_temporal_on_testdrive is
SKIPPED — PRD §3.2 states the license check is performed FIRST ("First, the
customer must hold a verified license ... Second, the requested interval must
not collide"), so a PRD-only implementer would return ERR_LICENSE_INVALID, the
opposite of that instance's asserted ERR_TESTDRIVE_OVERLAP. The outcome is not
uniquely derivable from PRD prose, so no test is emitted for it.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    ApiErrorId, TEST_USERS, fixtures,
)
from test_helpers import factories as f

INV = TEST_USERS["inventory_clerk_headers"]
SALES = TEST_USERS["sales_manager_headers"]
FIN = TEST_USERS["finance_manager_headers"]
SVC = TEST_USERS["service_advisor_headers"]
TITLE = TEST_USERS["title_clerk_headers"]


# ===========================================================================
# priority_pair_validation_conflict / conflict_state_vs_fiscal_on_fund
# ===========================================================================
class TestStateVsFiscalPrecedence:
    def test_fund_on_approved_deal_reports_state_not_fiscal(self, api):
        """PRD §2.8: "After these universal gates, resource-specific constraints
        apply (for example, VIN uniqueness on vehicle creation yields
        `ERR_VIN_DUPLICATE`), followed by state-transition legality
        (`ERR_INVALID_STATE` when the target is not in a state from which the
        requested transition is defined), then optimistic-concurrency checks
        (`ERR_STALE_VERSION`), and finally the domain-specific business rules
        described throughout §3."

        Design: Difficulty/priority_pair_validation_conflict/conflict_state_vs_fiscal_on_fund
        """
        # APPROVED (not CONTRACTED) deal whose amount_financed (2282846) also
        # exceeds the LTV cap (list_price 1500000 -> cap 1875000).
        veh = fixtures.create_vehicle(condition="USED", model="CPE", model_year=2024,
                                      msrp_cents=1700000, list_price_cents=1500000)
        cust = fixtures.create_customer(credit_tier="TIER_A", monthly_income_cents=2500000)
        lp = fixtures.create_lender_program(tier="TIER_A", buy_rate_bps=549, max_markup_bps=200,
                                            max_ltv_bps=12500, max_pti_bps=1800, max_term_months=72)
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=1899500, accessories_cents=129500,
                                    doc_fee_cents=59900, title_fee_cents=7500,
                                    registration_fee_cents=35000, tax_rate_bps=725)
        deal_id = deal["id"]
        get_success_data(api.desk_deal(deal_id, SALES))
        fixtures.upload_document(deal_id, "CREDIT_APP")
        get_success_data(api.submit_to_lender(deal_id, SALES))
        get_success_data(api.lender_decision(deal_id, {"decision": "APPROVE", "lender_program_id": lp["id"]}, FIN))
        veh_now = get_success_data(api.get_vehicle(veh["id"], FIN))
        # Deal is APPROVED, not CONTRACTED: the fund transition is undefined here.
        resp = api.fund_deal(deal_id, {"expected_vehicle_version": veh_now["version"]}, FIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_fiscal_ltv_check_fires_once_state_passes(self, api):
        """PRD §2.8: "After these universal gates, resource-specific constraints
        apply (for example, VIN uniqueness on vehicle creation yields
        `ERR_VIN_DUPLICATE`), followed by state-transition legality
        (`ERR_INVALID_STATE` when the target is not in a state from which the
        requested transition is defined), then optimistic-concurrency checks
        (`ERR_STALE_VERSION`), and finally the domain-specific business rules
        described throughout §3."

        Design: Difficulty/priority_pair_validation_conflict/conflict_state_vs_fiscal_on_fund
        """
        # Same LTV-busting pricing, but now driven all the way to CONTRACTED so
        # the state gate passes; the next gate (the §3.6 fiscal LTV rule) is then
        # the one that fires -> ERR_LTV_EXCEEDED, confirming state precedes fiscal.
        ctx = fixtures.create_contracted_deal(
            vehicle_overrides=dict(condition="USED", model="CPE", model_year=2024,
                                   msrp_cents=1700000, list_price_cents=1500000),
            customer_overrides=dict(monthly_income_cents=5000000),
            deal_overrides=dict(sale_price_cents=1899500, accessories_cents=129500,
                                doc_fee_cents=59900, title_fee_cents=7500,
                                registration_fee_cents=35000, tax_rate_bps=725),
            with_floor_plan=True, floor_overrides=dict(principal_cents=1400000),
            markup_bps=100, term_months=72)
        assert ctx["deal"]["status"] == "CONTRACTED"
        veh = get_success_data(api.get_vehicle(ctx["vehicle_id"], FIN))
        resp = api.fund_deal(ctx["deal_id"], {"expected_vehicle_version": veh["version"]}, FIN)
        validate_error(resp, ApiErrorId.ERR_LTV_EXCEEDED.value)


# ===========================================================================
# boundary_precision_check / boundary_ltv_at_cap_vs_over_cap_on_fund
# ===========================================================================
class TestLtvBoundary:
    def _contracted_with_af(self, accessories_cents):
        """Build a CONTRACTED deal on a list_price-2000000 vehicle with a chosen
        accessories amount (which moves amount_financed). Returns (deal_id, vehicle_id)."""
        veh = fixtures.create_vehicle(condition="USED", model="CPE", model_year=2024,
                                      msrp_cents=2200000, list_price_cents=2000000)
        line = fixtures.floor_vehicle(veh["id"], veh["version"], principal_cents=1800000,
                                      annual_rate_bps=825, floored_on="2026-05-01T00:00:00.000Z")
        cust = fixtures.create_customer(credit_tier="TIER_A", monthly_income_cents=5000000)
        lp = fixtures.create_lender_program(tier="TIER_A", buy_rate_bps=549, max_markup_bps=200,
                                            max_ltv_bps=12500, max_pti_bps=1800, max_term_months=72)
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, accessories_cents=accessories_cents,
                                    tax_rate_bps=725)
        deal_id = deal["id"]
        get_success_data(api_client.desk_deal(deal_id, SALES))
        fixtures.upload_document(deal_id, "CREDIT_APP")
        fixtures.upload_document(deal_id, "INSURANCE")
        get_success_data(api_client.submit_to_lender(deal_id, SALES))
        approved = get_success_data(api_client.lender_decision(
            deal_id, {"decision": "APPROVE", "lender_program_id": lp["id"]}, FIN))
        fixtures.add_finance_contract(deal_id, lp["id"], approved["version"], markup_bps=100, term_months=72)
        get_success_data(api_client.contract_deal(deal_id, FIN))
        return deal_id, veh["id"]

    def test_amount_financed_one_cent_over_cap_rejected(self, api):
        """PRD §3.6: "The loan-to-value cap must hold: the deal's
        `amount_financed_cents` must not exceed the lender program's
        `max_ltv_bps` divided by ten thousand, multiplied by the vehicle's
        `list_price_cents` — at most, never beyond — or funding is rejected with
        `ERR_LTV_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/boundary_ltv_at_cap_vs_over_cap_on_fund
        """
        # accessories 331003 -> amount_financed 2500001 = cap(2500000) + 1.
        deal_id, vehicle_id = self._contracted_with_af(331003)
        deal = get_success_data(api.get_deal(deal_id, FIN))
        assert deal["amount_financed_cents"] == 2500001, deal["amount_financed_cents"]
        veh = get_success_data(api.get_vehicle(vehicle_id, FIN))
        resp = api.fund_deal(deal_id, {"expected_vehicle_version": veh["version"]}, FIN)
        validate_error(resp, ApiErrorId.ERR_LTV_EXCEEDED.value)

    def test_amount_financed_exactly_at_cap_funds(self, api):
        """PRD §3.6: "The loan-to-value cap must hold: the deal's
        `amount_financed_cents` must not exceed the lender program's
        `max_ltv_bps` divided by ten thousand, multiplied by the vehicle's
        `list_price_cents` — at most, never beyond — or funding is rejected with
        `ERR_LTV_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/boundary_ltv_at_cap_vs_over_cap_on_fund
        """
        # accessories 331002 -> amount_financed exactly 2500000 == cap.
        deal_id, vehicle_id = self._contracted_with_af(331002)
        deal = get_success_data(api.get_deal(deal_id, FIN))
        assert deal["amount_financed_cents"] == 2500000, deal["amount_financed_cents"]
        veh = get_success_data(api.get_vehicle(vehicle_id, FIN))
        funded = validate_success(api.fund_deal(deal_id, {"expected_vehicle_version": veh["version"]}, FIN))
        assert funded["status"] == "FUNDED"


# ===========================================================================
# boundary_precision_check / boundary_empty_incentive_eligible_set_on_apply
# ===========================================================================
class TestIncentiveEmptyEligibleSet:
    def _deal_and_make_restricted_incentive(self):
        veh = fixtures.create_vehicle(make="ACME", condition="NEW", model_year=2026,
                                      msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_A", monthly_income_cents=2500000)
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        inc = fixtures.create_oem_incentive(program_code=f.unique_code("OTHERONLY"),
                                            rebate_cents=100000, eligible_condition="ANY",
                                            eligible_make="OTHER", min_model_year=None,
                                            stackable_with_finance=True, active=True)
        return deal["id"], inc["id"]

    def test_apply_make_mismatched_incentive_rejected(self, api):
        """PRD §3.4: "An OEM incentive is eligible for a deal only when all of the
        following hold: the incentive's `active` flag is true; the incentive's
        `eligible_condition` equals the vehicle's `condition` or the incentive's
        `eligible_condition` is `ANY`; the incentive's `eligible_make` is null or
        equals the vehicle's `make`; the incentive's `min_model_year` is null or
        the vehicle's `model_year` is at least that value; and either the deal's
        `deal_type` is not `FINANCE` or the incentive's `stackable_with_finance`
        flag is true. If the requested incentive fails any of these, it is not
        eligible and the apply is rejected with `ERR_INCENTIVE_NOT_ELIGIBLE`."

        Design: Difficulty/boundary_precision_check/boundary_empty_incentive_eligible_set_on_apply
        """
        deal_id, inc_id = self._deal_and_make_restricted_incentive()
        resp = api.apply_incentive(deal_id, {"oem_incentive_id": inc_id}, SALES)
        validate_error(resp, ApiErrorId.ERR_INCENTIVE_NOT_ELIGIBLE.value)

    def test_rejected_incentive_leaves_rebate_zero(self, api):
        """PRD §3.4: "When it passes, the deal's `applied_incentive_id` is set to
        the incentive's id and the deal's `rebate_cents` is set to the incentive's
        `rebate_cents`."

        Design: Difficulty/boundary_precision_check/boundary_empty_incentive_eligible_set_on_apply
        """
        deal_id, inc_id = self._deal_and_make_restricted_incentive()
        api.apply_incentive(deal_id, {"oem_incentive_id": inc_id}, SALES)
        deal = validate_success(api.get_deal(deal_id, FIN))
        assert deal["rebate_cents"] == 0
        assert deal["applied_incentive_id"] is None


# ===========================================================================
# resource_temporal_overlap / overlap_testdrive_halfopen_with_buffer
# ===========================================================================
class TestTestDriveOverlap:
    def test_back_to_back_drive_within_buffer_rejected(self, api):
        """PRD §3.2: "Second, the requested interval must not collide with another
        SCHEDULED test drive on the same vehicle, where the collision check
        includes a turnaround buffer applied after each drive so that
        back-to-back drives are spaced apart; an overlap (buffer included) is
        rejected with `ERR_TESTDRIVE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/overlap_testdrive_halfopen_with_buffer
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        c1 = fixtures.create_customer(credit_tier="TIER_C", drivers_license_valid=True,
                                      monthly_income_cents=1000000)
        c2 = fixtures.create_customer(credit_tier="TIER_C", drivers_license_valid=True,
                                      monthly_income_cents=1000000)
        get_success_data(api.book_test_drive(
            {"vehicle_id": veh["id"], "customer_id": c1["id"],
             "start_at": "2026-06-11T10:00:00.000Z", "end_at": "2026-06-11T10:30:00.000Z"}, SALES))
        # A drive starting exactly when the prior one ended is back-to-back and
        # falls inside the prior drive's turnaround buffer.
        resp = api.book_test_drive(
            {"vehicle_id": veh["id"], "customer_id": c2["id"],
             "start_at": "2026-06-11T10:30:00.000Z", "end_at": "2026-06-11T11:00:00.000Z"}, SALES)
        validate_error(resp, ApiErrorId.ERR_TESTDRIVE_OVERLAP.value)

    def test_overlap_check_scoped_to_same_vehicle(self, api):
        """PRD §3.2: "Second, the requested interval must not collide with another
        SCHEDULED test drive on the same vehicle, where the collision check
        includes a turnaround buffer applied after each drive so that
        back-to-back drives are spaced apart; an overlap (buffer included) is
        rejected with `ERR_TESTDRIVE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/overlap_testdrive_halfopen_with_buffer
        """
        veh_a = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        veh_b = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        c1 = fixtures.create_customer(credit_tier="TIER_C", drivers_license_valid=True)
        c2 = fixtures.create_customer(credit_tier="TIER_C", drivers_license_valid=True)
        get_success_data(api.book_test_drive(
            {"vehicle_id": veh_a["id"], "customer_id": c1["id"],
             "start_at": "2026-06-11T10:00:00.000Z", "end_at": "2026-06-11T10:30:00.000Z"}, SALES))
        # Identical interval but a DIFFERENT vehicle: no collision.
        booked = validate_success(api.book_test_drive(
            {"vehicle_id": veh_b["id"], "customer_id": c2["id"],
             "start_at": "2026-06-11T10:00:00.000Z", "end_at": "2026-06-11T10:30:00.000Z"}, SALES),
            expected_status=201)
        assert booked["status"] == "SCHEDULED"


# ===========================================================================
# resource_temporal_overlap / overlap_repair_bay_closed_interval_no_buffer
# ===========================================================================
class TestRepairBayOverlap:
    def test_closed_interval_touch_collides(self, api):
        """PRD §3.8: "The bay slot must not overlap another OPEN repair order in
        the same bay; the overlap test treats the slot as a closed interval with
        no buffer, and a collision is rejected with `ERR_BAY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/overlap_repair_bay_closed_interval_no_buffer
        """
        veh = fixtures.create_vehicle(condition="USED", model="CPE", model_year=2023,
                                      msrp_cents=1800000, list_price_cents=1600000)
        get_success_data(api.create_repair_order(
            {"vehicle_id": veh["id"], "deal_id": None, "ro_type": "RETAIL", "bay": "BAY_1",
             "scheduled_start_at": "2026-06-12T10:00:00.000Z",
             "scheduled_end_at": "2026-06-12T11:00:00.000Z", "parts_cents": 5000, "labor_cents": 12000}, SVC))
        # New order 09:00-10:00 touches the existing 10:00-11:00 at 10:00; closed
        # intervals include the shared endpoint, so it collides.
        resp = api.create_repair_order(
            {"vehicle_id": veh["id"], "deal_id": None, "ro_type": "RETAIL", "bay": "BAY_1",
             "scheduled_start_at": "2026-06-12T09:00:00.000Z",
             "scheduled_end_at": "2026-06-12T10:00:00.000Z", "parts_cents": 0, "labor_cents": 8000}, SVC)
        validate_error(resp, ApiErrorId.ERR_BAY_OVERLAP.value)

    def test_overlap_check_scoped_to_same_bay(self, api):
        """PRD §3.8: "The bay slot must not overlap another OPEN repair order in
        the same bay; the overlap test treats the slot as a closed interval with
        no buffer, and a collision is rejected with `ERR_BAY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/overlap_repair_bay_closed_interval_no_buffer
        """
        veh = fixtures.create_vehicle(condition="USED", model="CPE", model_year=2023,
                                      msrp_cents=1800000, list_price_cents=1600000)
        get_success_data(api.create_repair_order(
            {"vehicle_id": veh["id"], "deal_id": None, "ro_type": "RETAIL", "bay": "BAY_1",
             "scheduled_start_at": "2026-06-12T10:00:00.000Z",
             "scheduled_end_at": "2026-06-12T11:00:00.000Z", "parts_cents": 0, "labor_cents": 0}, SVC))
        # Same overlapping interval but BAY_2: no collision.
        booked = validate_success(api.create_repair_order(
            {"vehicle_id": veh["id"], "deal_id": None, "ro_type": "RETAIL", "bay": "BAY_2",
             "scheduled_start_at": "2026-06-12T10:00:00.000Z",
             "scheduled_end_at": "2026-06-12T11:00:00.000Z", "parts_cents": 0, "labor_cents": 0}, SVC),
            expected_status=201)
        assert booked["status"] == "OPEN"


# ===========================================================================
# compensating_invariant / invariant_fund_unwind_preserves_floorplan_principal
# ===========================================================================
class TestFundUnwindPrincipalConserved:
    def test_unwind_reinstates_paid_off_floor_plan_principal(self, api):
        """PRD §3.6: "As a consequence, the floor-plan line that this funding paid
        off is reinstated: it transitions `PAID_OFF → REINSTATED` and its
        `principal_outstanding_cents` is restored to the original `principal_cents`
        less the sum of any curtailment reductions previously recorded against it."

        Design: Difficulty/compensating_invariant/invariant_fund_unwind_preserves_floorplan_principal
        """
        ctx = fixtures.create_funded_deal(
            deal_overrides=dict(sale_price_cents=2000000, tax_rate_bps=725),
            floor_overrides=dict(principal_cents=1800000), with_odometer=False)
        line_before = get_success_data(api.get_floor_plan_line(ctx["floor_plan_line_id"], FIN))
        assert line_before["principal_outstanding_cents"] == 0
        unwound = validate_success(api.unwind_deal(ctx["deal_id"], FIN))
        assert unwound["status"] == "UNWOUND"
        line_after = get_success_data(api.get_floor_plan_line(ctx["floor_plan_line_id"], FIN))
        assert line_after["status"] == "REINSTATED"
        assert line_after["principal_outstanding_cents"] == 1800000

    def test_unwind_restores_vehicle_to_available(self, api):
        """PRD §3.6: "When unwind is permitted, it runs the compensation chain
        that reverses the fund cascade so the dealership's global floor-plan
        principal outstanding returns to its pre-fund total. The vehicle is
        restored `SOLD → AVAILABLE`."

        Design: Difficulty/compensating_invariant/invariant_fund_unwind_preserves_floorplan_principal
        """
        ctx = fixtures.create_funded_deal(
            deal_overrides=dict(sale_price_cents=2000000, tax_rate_bps=725),
            floor_overrides=dict(principal_cents=1800000), with_odometer=False)
        get_success_data(api.unwind_deal(ctx["deal_id"], FIN))
        veh = get_success_data(api.get_vehicle(ctx["vehicle_id"], FIN))
        assert veh["status"] == "AVAILABLE"


# ===========================================================================
# compensating_invariant / invariant_product_add_void_preserves_amount_financed
# ===========================================================================
class TestProductAddVoidConservesAmountFinanced:
    def _desked_deal_with_product(self):
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_A", monthly_income_cents=2500000)
        fp = fixtures.create_finance_product(cost_cents=120000, max_retail_cents=250000)
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        deal_id = deal["id"]
        desked = get_success_data(api_client.desk_deal(deal_id, SALES))
        dp = get_success_data(api_client.attach_product(
            deal_id, {"finance_product_id": fp["id"], "sold_price_cents": 200000}, FIN))
        return deal_id, dp["id"]

    def test_adding_product_raises_amount_financed(self, api):
        """PRD §3.3: "A successful attach creates a product line in status
        `ACTIVE`, snapshots the catalog's cost into `product_cost_cents`,
        recomputes the deal's amount financed and back-end gross, and increments
        the deal's `version`."

        Design: Difficulty/compensating_invariant/invariant_product_add_void_preserves_amount_financed
        """
        deal_id, dp_id = self._desked_deal_with_product()
        deal = get_success_data(api.get_deal(deal_id, FIN))
        assert deal["amount_financed_cents"] == 2345000, deal["amount_financed_cents"]
        assert deal["fi_products_total_cents"] == 200000, deal["fi_products_total_cents"]

    def test_voiding_product_restores_amount_financed(self, api):
        """PRD §3.3: "During a rehash a `FinanceManager` may void a product line,
        transitioning it `ACTIVE → VOID`; voiding likewise recomputes the deal's
        amount financed and back-end gross and bumps the deal's `version`."

        Design: Difficulty/compensating_invariant/invariant_product_add_void_preserves_amount_financed
        """
        deal_id, dp_id = self._desked_deal_with_product()
        voided = validate_success(api.void_product(deal_id, dp_id, FIN))
        assert voided["status"] == "VOID"
        deal = get_success_data(api.get_deal(deal_id, FIN))
        assert deal["amount_financed_cents"] == 2145000, deal["amount_financed_cents"]
        assert deal["fi_products_total_cents"] == 0, deal["fi_products_total_cents"]
