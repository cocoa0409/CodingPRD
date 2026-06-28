"""Pricing and routing calculations (depth queue A — rules 1, 2, 6).

Covers the dual-variant renewal/crew calculations, the three combinatorial-formula modes
(contract total, route minutes, damage settlement), and the bundle/storage-fee boundaries.
"""
import pytest
from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    create_client_payload,
    create_contract_payload,
    create_inventory_item_payload,
    create_design_proposal_payload,
    create_line_item_payload,
    create_crew_payload,
    create_work_order_payload,
    create_visit_payload,
    create_schedule_payload,
    create_storage_bay_payload,
    create_storage_lot_payload,
    create_damage_report_payload,
    create_renewal_offer_payload,
    setup_active_contract,
    create_work_order_with_visits,
    schedule_work_order,
    create_completed_takedown,
    setup_sent_renewal_offer,
    create_stored_lot,
    make_client_contact_headers,
    TEST_USERS,
)

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]
PA = TEST_USERS["platform_admin_headers"]


# =====================================================================
# Rule 1 — dual_variant_calc
# =====================================================================
class TestRenewalProvisionalVsFinalDiverge:
    """Difficulty/dual_variant_calc/renewal_price_provisional_vs_final_diverge_on_contract."""

    def _build(self):
        # COMMERCIAL contract: single ACCEPTED line 50 @ 10000, install 475000, storage
        # 15000, surcharge 0, total 490000. Clock left at the 2026-04-01 default; deadline
        # 2026-03-01 is in the past so no early-bird discount. Provisional = 490000*1.05 = 514500.
        ctx = setup_active_contract(
            account_type="COMMERCIAL",
            contract_type="COMMERCIAL",
            sku="LIGHT-A-DV",
            sku_overrides={"category": "LIGHTING", "unit_replacement_cents": 6000, "on_hand_qty": 20},
            contract_overrides={"custom_design_surcharge_cents": 0},
            line_quantity=50,
            unit_install_cents=10000,
        )
        crew = get_success_data(api_client.create_crew(
            create_crew_payload(crew_name="DV Crew"), FS))
        # A COMPLETED TAKEDOWN work order with one DamageReport ASSESSED as REPAIR
        # (replacement 5*6000=30000, base 0.20, labor 6000, total 36000), not yet settled.
        completed_wo = create_completed_takedown(ctx, crew["id"], scheduled_date="2026-11-10T00:00:00Z")
        dr = get_success_data(api_client.create_damage_report(
            completed_wo["id"], create_damage_report_payload(ctx["sku_id"], damaged_qty=5), FS))
        get_success_data(api_client.assess_damage_report(dr["id"], {"resolution_path": "REPAIR"}, FS))
        renewal = setup_sent_renewal_offer(ctx)
        return ctx, renewal

    def test_provisional_price_excludes_damage_carry(self):
        """PRD §3.9: "The provisional quote computed at offer creation is exactly this
        escalated base and excludes any damage carry-forward, populating
        `provisional_price_cents`."

        Design: Difficulty/dual_variant_calc/renewal_price_provisional_vs_final_diverge_on_contract
        """
        _ctx, renewal = self._build()
        assert renewal["provisional_price_cents"] == 514500, (
            f"expected provisional 514500, got {renewal['provisional_price_cents']}")

    def test_final_price_adds_assessed_damage_carry(self):
        """PRD §3.9: "The final price, computed at acceptance, takes the same escalated base
        and adds the carry-forward of unsettled damage: the sum of `settlement_total_cents`
        over the contract's work orders' damage reports that are in `ASSESSED` — that is,
        assessed but not yet settled."

        Design: Difficulty/dual_variant_calc/renewal_price_provisional_vs_final_diverge_on_contract
        """
        ctx, renewal = self._build()
        cc = make_client_contact_headers(ctx["client_id"])
        accepted = validate_success(api_client.accept_renewal_offer(renewal["offer"]["id"], cc), 200)
        assert accepted["final_price_cents"] == 550500, (
            f"expected final 550500, got {accepted['final_price_cents']}")
        assert accepted["final_price_cents"] - renewal["provisional_price_cents"] == 36000


class TestCrewPlannedVsActualUtilizationDiverge:
    """Difficulty/dual_variant_calc/crew_planned_vs_actual_utilization_diverge_on_crew."""

    def _build(self):
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="TREE-A-DV", sku_overrides={"unit_replacement_cents": 9000, "on_hand_qty": 50},
            line_quantity=10, unit_install_cents=5000)
        crew = get_success_data(api_client.create_crew(
            create_crew_payload(crew_name="Alpha DV", daily_capacity_minutes=480), FS))
        wo, visits = create_work_order_with_visits(
            ctx["contract_id"], job_type="INSTALL",
            visits=[
                {"stop_sequence": 1, "leg_distance_km": 12.4, "on_site_minutes": 90},
                {"stop_sequence": 2, "leg_distance_km": 7.8, "on_site_minutes": 120},
                {"stop_sequence": 3, "leg_distance_km": 21.1, "on_site_minutes": 60},
            ])
        scheduled = schedule_work_order(wo["id"], crew["id"], "2026-11-15T00:00:00Z")
        get_success_data(api_client.dispatch_work_order(wo["id"], FS))
        get_success_data(api_client.complete_visit(visits[0]["id"], {"actual_minutes": 150}, FS))
        get_success_data(api_client.complete_visit(visits[1]["id"], {"actual_minutes": 180}, FS))
        get_success_data(api_client.complete_visit(visits[2]["id"], {"actual_minutes": 120}, FS))
        return crew, wo, scheduled

    def test_planned_utilization_from_scheduled_route_minutes(self):
        """PRD §3.4: "The planned figure looks at the crew's work orders in `schedule_status`
        `SCHEDULED` or `DISPATCHED`, finds the crew's busiest date — the `scheduled_date`
        carrying the greatest summed `route_total_minutes`, with ties broken by the earliest
        date — sums `route_total_minutes` for the work orders on that date, divides by the
        crew's `daily_capacity_minutes`, multiplies by 100, and rounds half-up to populate
        `planned_utilization_pct`."

        Design: Difficulty/dual_variant_calc/crew_planned_vs_actual_utilization_diverge_on_crew
        """
        crew, wo, scheduled = self._build()
        assert scheduled["route_total_minutes"] == 333
        crew_after = validate_success(api_client.get_crew(crew["id"], FS), 200)
        assert crew_after["planned_utilization_pct"] == 69, (
            f"expected planned 69, got {crew_after['planned_utilization_pct']}")

    def test_actual_utilization_from_completed_visit_minutes(self):
        """PRD §3.4: "The actual figure looks only at completed work, summing the
        `actual_minutes` of visits in `COMPLETED` on the crew's `COMPLETED` work orders'
        busiest date, dividing by `daily_capacity_minutes`, multiplying by 100, and rounding
        half-up to populate `actual_utilization_pct`; it is recomputed on work-order completion."

        Design: Difficulty/dual_variant_calc/crew_planned_vs_actual_utilization_diverge_on_crew
        """
        crew, wo, _scheduled = self._build()
        validate_success(api_client.complete_work_order(wo["id"], FS), 200)
        crew_after = validate_success(api_client.get_crew(crew["id"], FS), 200)
        assert crew_after["actual_utilization_pct"] == 94, (
            f"expected actual 94, got {crew_after['actual_utilization_pct']}")


# =====================================================================
# Rule 2 — combinatorial_formula
# =====================================================================
class TestContractTotalNonlinearBranchingModeA:
    """Difficulty/combinatorial_formula/contract_total_nonlinear_branching_mode_a."""

    def _sign(self):
        validate_success(api_client.set_clock({"to_iso8601": "2026-02-15T00:00:00Z"}, PA), 200)
        client = get_success_data(api_client.create_client(
            create_client_payload(legal_name="Maple HOA", account_type="HOA",
                                  contact_email="board@maple.test", site_address="Maple Ln"), AM))
        light = get_success_data(api_client.create_inventory_item(
            create_inventory_item_payload(sku="LIGHT-RUN-A", category="LIGHTING",
                                          unit_replacement_cents=3000, on_hand_qty=100), PA))
        wreath = get_success_data(api_client.create_inventory_item(
            create_inventory_item_payload(sku="WREATH-XL-A", category="WREATH",
                                          unit_replacement_cents=8000, on_hand_qty=100), PA))
        contract = get_success_data(api_client.create_contract(
            client["id"], create_contract_payload(contract_type="HOA",
                                                   early_bird_deadline="2026-03-01T00:00:00Z",
                                                   custom_design_surcharge_cents=50000), AM))
        proposal = get_success_data(api_client.create_design_proposal(
            contract["id"], create_design_proposal_payload(theme="Winter Gold", is_custom=True), AM))
        get_success_data(api_client.create_line_item(
            proposal["id"], create_line_item_payload(light["id"], quantity=30, unit_install_cents=4999), AM))
        get_success_data(api_client.create_line_item(
            proposal["id"], create_line_item_payload(wreath["id"], quantity=25, unit_install_cents=12500), AM))
        get_success_data(api_client.submit_proposal(proposal["id"], AM))
        proposed = get_success_data(api_client.propose_contract(client["id"], contract["id"], AM))
        cc = make_client_contact_headers(client["id"])
        get_success_data(api_client.accept_proposal(
            proposal["id"], {"expected_contract_version": proposed["version"]}, cc))
        signed = validate_success(api_client.sign_contract(client["id"], contract["id"], cc), 200)
        return signed

    def test_hoa_install_and_storage_components(self):
        """PRD §3.3: "for each line item, multiply its `unit_install_cents` by its `quantity`,
        apply the bundle discount by multiplying by one minus the chosen rate, and round that
        line's result half-up to whole cents; the install fee is the sum of those per-line
        rounded amounts."

        Design: Difficulty/combinatorial_formula/contract_total_nonlinear_branching_mode_a
        """
        signed = self._sign()
        assert signed["install_fee_cents"] == 439347, (
            f"expected install 439347, got {signed['install_fee_cents']}")
        assert signed["storage_fee_cents"] == 15000, (
            f"expected storage 15000, got {signed['storage_fee_cents']}")

    def test_hoa_early_bird_and_total(self):
        """PRD §3.3: "The contract total is then the install fee plus the storage fee plus the
        surcharge, minus the early-bird discount, and populates `total_amount_cents`."

        Design: Difficulty/combinatorial_formula/contract_total_nonlinear_branching_mode_a
        """
        signed = self._sign()
        assert signed["early_bird_discount_cents"] == 54522, (
            f"expected discount 54522, got {signed['early_bird_discount_cents']}")
        assert signed["total_amount_cents"] == 449825, (
            f"expected total 449825, got {signed['total_amount_cents']}")


class TestRouteMinutesRoundPerLegThenSumModeB:
    """Difficulty/combinatorial_formula/route_minutes_round_per_leg_then_sum_mode_b."""

    def _schedule(self, scheduled_date):
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="GARLAND-A-RB", sku_overrides={"category": "GARLAND", "unit_replacement_cents": 4000, "on_hand_qty": 60},
            line_quantity=10, unit_install_cents=5000)
        crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="Bravo RB"), FS))
        wo, _visits = create_work_order_with_visits(
            ctx["contract_id"], job_type="INSTALL",
            visits=[
                {"stop_sequence": 1, "leg_distance_km": 12.4, "on_site_minutes": 90},
                {"stop_sequence": 2, "leg_distance_km": 7.8, "on_site_minutes": 120},
                {"stop_sequence": 3, "leg_distance_km": 21.1, "on_site_minutes": 60},
            ])
        return schedule_work_order(wo["id"], crew["id"], scheduled_date)

    def test_route_total_rounds_each_leg_before_summing(self):
        """PRD §3.4: "for each visit, divide its `leg_distance_km` by an average speed of 40
        kilometers per hour and multiply by 60 to get drive minutes, then round that leg
        half-up to a whole minute; the drive total is the sum of those per-leg rounded minutes."

        Design: Difficulty/combinatorial_formula/route_minutes_round_per_leg_then_sum_mode_b
        """
        scheduled = self._schedule("2026-11-20T00:00:00Z")
        assert scheduled["route_total_minutes"] == 333, (
            f"expected route 333 (per-leg round 19+12+32=63 + on-site 270), "
            f"got {scheduled['route_total_minutes']}")

    def test_route_total_not_sum_then_round(self):
        """PRD §3.4: "Each leg is rounded before summing — summing raw minutes and rounding
        once at the end is the wrong order and is not used."

        Design: Difficulty/combinatorial_formula/route_minutes_round_per_leg_then_sum_mode_b
        """
        scheduled = self._schedule("2026-11-22T00:00:00Z")
        # sum-raw-then-round would give 332; the per-leg order gives 333.
        assert scheduled["route_total_minutes"] == 333
        assert scheduled["route_total_minutes"] != 332


class TestDamageSettlementOrderPinnedModeC:
    """Difficulty/combinatorial_formula/damage_settlement_order_pinned_mode_c."""

    def _assess(self):
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="STRAND-5900-MC", sku_overrides={"category": "LIGHTING", "unit_replacement_cents": 5900, "on_hand_qty": 40},
            line_quantity=5, unit_install_cents=5000)
        crew = get_success_data(api_client.create_crew(create_crew_payload(crew_name="Charlie MC"), FS))
        completed_wo = create_completed_takedown(ctx, crew["id"], scheduled_date="2027-01-05T00:00:00Z")
        dr = get_success_data(api_client.create_damage_report(
            completed_wo["id"], create_damage_report_payload(ctx["sku_id"], damaged_qty=5), FS))
        return validate_success(api_client.assess_damage_report(dr["id"], {"resolution_path": "REPAIR"}, FS), 200)

    def test_replacement_cost_computed_first(self):
        """PRD §3.7: "The system first computes the replacement cost as `damaged_qty`
        multiplied by the inventory item's `unit_replacement_cents`, populating
        `replacement_cost_cents`."

        Design: Difficulty/combinatorial_formula/damage_settlement_order_pinned_mode_c
        """
        assessed = self._assess()
        assert assessed["replacement_cost_cents"] == 29500, (
            f"expected replacement 29500 (5*5900), got {assessed['replacement_cost_cents']}")

    def test_settlement_total_is_replacement_plus_labor(self):
        """PRD §3.7: "The labor fee is the replacement cost multiplied by the effective
        percentage, rounded half-up to whole cents. The settlement total is the replacement
        cost plus the labor fee, populating `settlement_total_cents`."

        Design: Difficulty/combinatorial_formula/damage_settlement_order_pinned_mode_c
        """
        assessed = self._assess()
        # base_pct 0.20 (29500 < 50000), no waiver → labor 5900, total 35400.
        assert assessed["settlement_total_cents"] == 35400, (
            f"expected total 35400, got {assessed['settlement_total_cents']}")


# =====================================================================
# Rule 6 — boundary_precision_check
# =====================================================================
class TestBundleTierBoundaryAt50Units:
    """Difficulty/boundary_precision_check/bundle_tier_boundary_at_50_units_on_sign."""

    def test_total_unit_count_at_boundary(self):
        """PRD §3.2: "submission requires the proposal to be `DRAFT` and to carry at least one
        line item, and it recomputes `total_unit_count` as the sum of `quantity` across the
        proposal's line items."

        Design: Difficulty/boundary_precision_check/bundle_tier_boundary_at_50_units_on_sign
        """
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="TREE-K-BND", sku_overrides={"unit_replacement_cents": 9000, "on_hand_qty": 60},
            line_quantity=50, unit_install_cents=10000)
        proposal = validate_success(api_client.get_design_proposal(ctx["proposal_id"], AM), 200)
        assert proposal["total_unit_count"] == 50

    def test_install_fee_selects_five_percent_tier_at_50(self):
        """PRD §3.3: "no discount when the total is below 50 units; 5 percent when the total is
        at least 50 but below 100; 10 percent when the total is at least 100 but below 200; and
        15 percent when the total is 200 or more."

        Design: Difficulty/boundary_precision_check/bundle_tier_boundary_at_50_units_on_sign
        """
        ctx = setup_active_contract(
            account_type="COMMERCIAL", contract_type="COMMERCIAL",
            sku="TREE-K2-BND", sku_overrides={"unit_replacement_cents": 9000, "on_hand_qty": 60},
            line_quantity=50, unit_install_cents=10000)
        signed = validate_success(api_client.get_contract(ctx["contract_id"], AM), 200)
        # 50 units selects tier 0.05 → 50*10000*0.95 = 475000 (vs 490000 at 49 units / 0%).
        assert signed["install_fee_cents"] == 475000, (
            f"expected install 475000 at the 50-unit boundary, got {signed['install_fee_cents']}")
