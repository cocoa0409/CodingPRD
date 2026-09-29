"""Calculations that answer twice on the same record, and the multi-step
formulas whose rounding and tier positions are pinned by the contract.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    BASIS_REPAIR_ACTUAL,
    BASIS_SURVEY_BASED,
    CLAIM_FILED,
    DAMAGE_SURVEY_DAMAGE_OPEN,
    DAMAGE_ZONE_BODY_PANEL,
    DAMAGE_ZONE_GLASS,
    DAMAGE_ZONE_INTERIOR,
    DAMAGE_ZONE_UNDERBODY,
    MODEL_LINE_EV900,
    MODEL_LINE_LX500,
    MODEL_LINE_TX300,
    PROC_ACCESSORY_IN_PROGRESS,
    PROC_SURVEYED,
    RO_RELEASED,
    ROUTE_ZONE_B,
    Vpc,
    assert_center_ledgers,
    assert_freight_breakdown,
    assert_kit_ledger,
    assert_storage_charges,
    assert_subset,
    assert_vehicle_dimensions,
    factories as f,
    open_port,
)

MAJOR_LINES = [
    f.damage_line(DAMAGE_ZONE_BODY_PANEL, 40, 40_000),
    f.damage_line(DAMAGE_ZONE_GLASS, 30, 20_000),
]
CLAIMABLE_LINES = [
    f.damage_line(DAMAGE_ZONE_UNDERBODY, 34, 95_000),
    f.damage_line(DAMAGE_ZONE_GLASS, 30, 32_000),
]
CLEAN_LINE = f.damage_line(DAMAGE_ZONE_INTERIOR, 20, 0)


# ==========================================================================
# storage: the provisional accrual and the final bill
# ==========================================================================
def _allocated_after_repair(flow: Vpc) -> Dict[str, Any]:
    """A repaired unit allocated on 2026-08-14 off a 2026-08-02 arrival."""
    port = open_port(flow)
    unit = port.discharge("000001", model_line=MODEL_LINE_LX500)
    port.complete_voyage()

    port.set_clock("2026-08-03T00:00:00Z")
    survey = port.survey(unit["id"], MAJOR_LINES)
    port.submit_survey(survey["id"])
    repair = port.repair_order(unit["id"], 60_000)

    port.set_clock("2026-08-06T00:00:00Z")
    port.complete_repair(repair["id"], 58_000)
    port.pass_inspection(unit["id"])
    port.prep_complete(unit["id"])

    dealer = port.create_dealer(
        dealer_code="D-ATL",
        name="Atlanta Import Motors",
        route_zone=ROUTE_ZONE_B,
        distance_miles=285,
        allocation_quota=2,
    )
    port.create_carrier(
        carrier_code="TC-ROAD",
        name="Roadway Auto Transport",
        served_route_zones=["B"],
        linehaul_rate_cents_per_mile=412,
        slot_capacity=3,
        concurrent_load_capacity=2,
    )

    port.set_clock("2026-08-14T00:00:00Z")
    current = port.get_vehicle(unit["id"])
    order = port.allocate(
        current["id"],
        dealer["id"],
        current["version"],
        pickup_window_start="2026-08-16T08:00:00Z",
        pickup_window_end="2026-08-16T12:00:00Z",
    )
    return {"port": port, "vehicle_id": unit["id"], "order": order}


class TestStorageChargeVariants:
    def test_provisional_accrual_projects_two_days_past_allocation_with_no_credit(self, flow: Vpc):
        """The provisional evaluation ends two days after allocation and credits nothing.

        PRD: "The **provisional** evaluation is stamped at allocation into the
        unit's `storage_charge_provisional_cents`. Its end instant is the
        allocation instant advanced forward by two days — a forward-looking
        projection of when the unit will actually leave — and its credit days
        are zero, because at allocation time nobody knows yet whether the
        carrier will concede the damage-open period."

        Design: Difficulty/dual_variant_calc/storage_charge_provisional_vs_final_diverge_on_same_unit
        """
        scenario = _allocated_after_repair(flow)
        port = scenario["port"]

        unit = port.get_vehicle(scenario["vehicle_id"])
        assert_storage_charges(unit, provisional_cents=13_050, blocked_credit_days=3)
        assert_center_ledgers(port.get_center(), provisional_storage_accrued_cents=13_050)

    def test_final_bill_credits_the_blocked_days_and_clears_the_provisional(self, flow: Vpc):
        """Gate-out bills the shorter, credited figure and zeroes the accrual.

        PRD: "The **final** evaluation is stamped at gate-out into the unit's
        `storage_charge_final_cents`, and `storage_charge_provisional_cents` is
        reset to 0 in the same request. Its end instant is the actual gate-out
        instant, and its credit days are the unit's `blocked_credit_days` — the
        whole days between `damage_opened_at` and `damage_cleared_at`, or zero
        when either is null."

        Design: Difficulty/dual_variant_calc/storage_charge_provisional_vs_final_diverge_on_same_unit
        """
        scenario = _allocated_after_repair(flow)
        port = scenario["port"]

        port.dispatch(scenario["order"]["id"])
        port.set_clock("2026-08-16T00:00:00Z")
        port.gate_out(scenario["order"]["id"])

        unit = port.get_vehicle(scenario["vehicle_id"])
        assert_storage_charges(unit, provisional_cents=0, final_cents=8_700, blocked_credit_days=3)
        assert 13_050 - unit["storage_charge_final_cents"] == 4_350
        assert_center_ledgers(
            port.get_center(),
            realized_storage_revenue_cents=8_700,
            provisional_storage_accrued_cents=0,
        )


# ==========================================================================
# claim recovery: the survey basis and the actual-cost basis
# ==========================================================================
def _claim_with_linked_repair(flow: Vpc) -> Dict[str, Any]:
    """A filed claim on a 112,000-cent survey with a repair order attached."""
    port = open_port(flow)
    unit = port.discharge("000002", model_line=MODEL_LINE_TX300)
    survey = port.surveyed(unit["id"], CLAIMABLE_LINES)
    claim = port.file_claim(survey["id"], survey["version"])
    repair = port.repair_order(unit["id"], 120_000, carrier_claim_id=claim["id"])
    return {"port": port, "vehicle_id": unit["id"], "claim": claim, "repair": repair}


class TestClaimRecoverableBasis:
    def test_filing_recovers_the_capped_survey_projection_less_the_deductible(self, flow: Vpc):
        """At filing the basis amount is the claimed amount itself.

        PRD: "At filing, and on every resubmission while the basis has not
        changed, the basis is `SURVEY_BASED`: the basis amount is
        `claimed_amount_cents` itself, so the claim recovers the surveyor's
        capped projection of what repair will cost."

        Design: Difficulty/dual_variant_calc/claim_recoverable_survey_based_vs_repair_actual_basis_switch
        """
        scenario = _claim_with_linked_repair(flow)
        claim = scenario["port"].get_claim(scenario["claim"]["id"])

        assert_subset(
            claim,
            {
                "status": CLAIM_FILED,
                "claimed_amount_cents": 112_000,
                "recoverable_basis": BASIS_SURVEY_BASED,
                "recoverable_amount_cents": 87_000,
            },
        )

    def test_completed_linked_repair_latches_the_basis_onto_actual_cost(self, flow: Vpc):
        """Completion switches the basis and shrinks the recoverable figure.

        PRD: "The basis latches to `REPAIR_ACTUAL` the moment a repair order
        carrying this claim's identifier reaches completion while the claim is
        still non-terminal, and once latched it never reverts. Under
        `REPAIR_ACTUAL` the basis amount is the *lesser* of
        `claimed_amount_cents` and the sum of `actual_cost_cents` over every
        completed repair order pointing at this claim."

        Design: Difficulty/dual_variant_calc/claim_recoverable_survey_based_vs_repair_actual_basis_switch
        """
        scenario = _claim_with_linked_repair(flow)
        port = scenario["port"]

        port.complete_repair(scenario["repair"]["id"], 61_500)

        claim = port.get_claim(scenario["claim"]["id"])
        assert_subset(
            claim,
            {
                "recoverable_basis": BASIS_REPAIR_ACTUAL,
                "recoverable_amount_cents": 36_500,
                "claimed_amount_cents": 112_000,
            },
        )
        assert 87_000 - claim["recoverable_amount_cents"] == 50_500


# ==========================================================================
# accessory billing: per-unit rounding then multiplication
# ==========================================================================
def _kitted_work_order(flow: Vpc) -> Dict[str, Any]:
    """A three-unit accessory work order reserved against 12,340-cent kit stock."""
    port = open_port(flow)
    kit = port.create_kit(
        kit_code="KIT-ALLOY-19",
        program_code="PIO-ALLOY",
        received_qty_total=10,
        unit_cost_cents=12_340,
        install_minutes_per_unit=24,
    )
    unit = port.discharge("000003", model_line=MODEL_LINE_LX500, pio_program_code="PIO-ALLOY")
    port.surveyed(unit["id"], [CLEAN_LINE])
    order = port.plan_work_order(unit["id"], kit["id"], 3)
    port.kit_work_order(order["id"])
    return {"port": port, "vehicle_id": unit["id"], "kit_id": kit["id"], "order": order}


class TestAccessoryBillingRounding:
    def test_each_per_unit_component_rounds_before_the_quantity_multiplies_out(self, flow: Vpc):
        """Rounding happens twice per unit and never after the multiplication.

        PRD: "Add the two rounded per-unit components together and multiply the
        sum by the work order's `qty`; that product is `billed_cents`, and it is
        not rounded again. Rounding happens exactly twice, once per per-unit
        component, and never after the multiplication — summing unrounded
        components, or multiplying by quantity before rounding, yields a
        different cent total and is incorrect."

        Design: Difficulty/combinatorial_formula/accessory_billing_rounds_per_unit_then_multiplies_by_qty
        """
        scenario = _kitted_work_order(flow)
        port = scenario["port"]

        installed = port.install_work_order(scenario["order"]["id"])

        assert installed["billed_cents"] == 52_449
        assert port.get_vehicle(scenario["vehicle_id"])["accessory_billed_cents"] == 52_449

    def test_installation_consumes_the_reserved_units_from_on_hand_stock(self, flow: Vpc):
        """The installed quantity moves out of on-hand and into consumed.

        PRD: "The kit's `on_hand_qty` is reduced by the work order's `qty`, and
        `consumed_qty`, `reserved_qty` and `available_qty` are recomputed so
        that the conservation invariant of §2.9 still holds."

        Design: Difficulty/combinatorial_formula/accessory_billing_rounds_per_unit_then_multiplies_by_qty
        """
        scenario = _kitted_work_order(flow)
        port = scenario["port"]

        port.install_work_order(scenario["order"]["id"])

        assert_kit_ledger(
            port.get_kit(scenario["kit_id"]),
            on_hand_qty=7,
            reserved_qty=0,
            available_qty=7,
            consumed_qty=3,
            received_qty_total=10,
        )
        assert_vehicle_dimensions(
            port.get_vehicle(scenario["vehicle_id"]),
            processing_status=PROC_ACCESSORY_IN_PROGRESS,
        )


# ==========================================================================
# freight settlement: the discount tier keyed on gross
# ==========================================================================
def _allocated_zone_b_unit(flow: Vpc) -> Dict[str, Any]:
    """A zone-B allocation at 268 billable miles and 412 cents per mile."""
    port = open_port(flow)
    unit = port.discharge("000004", model_line=MODEL_LINE_EV900)
    port.complete_voyage()
    port.surveyed(unit["id"], [CLEAN_LINE])
    port.pass_inspection(unit["id"])
    ready = port.prep_complete(unit["id"])

    dealer = port.create_dealer(
        dealer_code="D-COL",
        name="Columbus Auto Group",
        route_zone=ROUTE_ZONE_B,
        distance_miles=268,
        allocation_quota=2,
    )
    port.create_carrier(
        carrier_code="TC-ROAD",
        name="Roadway Auto Transport",
        served_route_zones=["B"],
        linehaul_rate_cents_per_mile=412,
        slot_capacity=3,
        concurrent_load_capacity=2,
    )
    order = port.allocate(
        ready["id"],
        dealer["id"],
        ready["version"],
        pickup_window_start="2026-08-05T08:00:00Z",
        pickup_window_end="2026-08-05T12:00:00Z",
    )
    return {"port": port, "order": order}


class TestFreightDiscountTier:
    def test_gross_freight_is_the_exact_sum_of_base_surcharge_and_accessorial(self, flow: Vpc):
        """The fuel surcharge applies to base linehaul only, and gross is exact.

        PRD: "Step two: multiply that base by the center's `fuel_surcharge_pct`
        as read at dispatch time and round half up to whole cents, giving
        `fuel_surcharge_cents` — the surcharge applies to the base linehaul
        only, never to the accessorial."

        Design: Difficulty/combinatorial_formula/freight_discount_tier_keyed_on_gross_not_on_post_discount_total
        """
        scenario = _allocated_zone_b_unit(flow)

        order = scenario["port"].dispatch(scenario["order"]["id"])

        assert_subset(
            order,
            {
                "base_linehaul_cents": 110_416,
                "fuel_surcharge_cents": 10_213,
                "zone_accessorial_cents": 4_500,
                "gross_freight_cents": 125_129,
            },
        )

    def test_discount_rate_is_read_off_gross_not_off_the_post_discount_total(self, flow: Vpc):
        """A gross above the six-percent threshold discounts at six percent.

        PRD: "The discount tier is keyed on `gross_freight_cents` from step four
        and never on the post-discount `freight_total_cents`; rounding occurs at
        steps one, two and six and nowhere else."

        Design: Difficulty/combinatorial_formula/freight_discount_tier_keyed_on_gross_not_on_post_discount_total
        """
        scenario = _allocated_zone_b_unit(flow)

        order = scenario["port"].dispatch(scenario["order"]["id"])

        assert order["status"] == RO_RELEASED
        assert_freight_breakdown(
            order,
            base_linehaul_cents=110_416,
            fuel_surcharge_cents=10_213,
            zone_accessorial_cents=4_500,
            gross_freight_cents=125_129,
            freight_discount_cents=7_508,
            freight_total_cents=117_621,
        )


# ==========================================================================
# severity scoring: rounded maximum plus line spread
# ==========================================================================
def _draft_survey(flow: Vpc) -> Dict[str, Any]:
    """A two-line draft survey whose zones weight differently."""
    port = open_port(flow)
    unit = port.discharge("000005", model_line=MODEL_LINE_LX500)
    survey = port.survey(unit["id"], CLAIMABLE_LINES)
    return {"port": port, "vehicle_id": unit["id"], "survey": survey}


class TestSeverityIndexScoring:
    def test_peak_is_the_maximum_weighted_line_rounded_after_the_maximum(self, flow: Vpc):
        """Only the largest weighted line contributes, plus five per extra line.

        PRD: "Take the **largest** weighted score across all lines, and only
        then round that single figure half up to a whole number — this is the
        *peak*, and the rounding happens after the maximum is taken, never to
        each line beforehand."

        Design: Difficulty/combinatorial_formula/damage_severity_index_nested_max_zone_weight_and_line_spread
        """
        scenario = _draft_survey(flow)

        survey = scenario["port"].submit_survey(scenario["survey"]["id"])

        assert survey["severity_index"] == 66
        assert survey["line_count"] == 2

    def test_the_scored_index_opens_the_damage_dimension_and_mandates_a_claim(self, flow: Vpc):
        """The unit takes the survey's index and the two dimensions both move.

        PRD: "The unit's own `severity_index` is set to the survey's, and
        `claim_mandatory` is set to true exactly when that index is 60 or more."

        Design: Difficulty/combinatorial_formula/damage_severity_index_nested_max_zone_weight_and_line_spread
        """
        scenario = _draft_survey(flow)
        port = scenario["port"]

        port.submit_survey(scenario["survey"]["id"])

        unit = port.get_vehicle(scenario["vehicle_id"])
        assert unit["severity_index"] == 66
        assert unit["claim_mandatory"] is True
        assert_vehicle_dimensions(
            unit,
            processing_status=PROC_SURVEYED,
            damage_status=DAMAGE_SURVEY_DAMAGE_OPEN,
        )
