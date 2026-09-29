"""Grading an inbound load at the scale: shrink, the per-factor quality
discounts, the service fee tier and the settlement value — all computed once
and frozen on the ticket."""

import pytest

from test_helpers import (
    CLEAN_LOAD,
    FULL_TIERS,
    TEST_WEIGHT_TIERS,
    TEST_WEIGHT_TIERS_DEAR,
    ApiErrorId,
    apply_ticket,
    assert_delivery_ticket,
    create_delivery_ticket_payload,
    new_contract,
    new_location,
    new_schedule,
    new_ticket,
    read_contract,
    read_schedule,
    setup_contract_scenario,
    setup_trading_floor,
    validate_error,
    validate_paginated,
)
from test_helpers.test_users import TEST_USERS


INSPECTOR = TEST_USERS["grain_inspector_headers"]
MERCH = TEST_USERS["merchandiser_headers"]


# The probe readings that drive the dual-variant instance: 16.2 moisture,
# 52.4 lb test weight, 3.7 per cent foreign material, 6.5 per cent damage.
DIRTY_LOAD = {
    "moisture_pct": 16.2,
    "test_weight_lbs": 52.4,
    "foreign_material_pct": 3.7,
    "damage_pct": 6.5,
}


def _dual_variant_scenario():
    """One desk carrying two byte-identical 50,000-bushel CASH contracts that
    differ only in settlement_basis."""
    floor = setup_trading_floor(
        desk_code="GD1", desk_name="Illinois River Desk", lots_open=20,
        avg_entry_price_cents=448, schedule_tiers=FULL_TIERS,
    )
    shrink_first = new_contract(
        floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
        bushels=50000, seller_name="Bell Farms", futures_price_cents=448,
        settlement_basis="SHRINK_FIRST",
    )
    gross_grade = new_contract(
        floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
        bushels=50000, seller_name="Halberd Farms", futures_price_cents=448,
        settlement_basis="GROSS_GRADE",
    )
    floor["shrink_first"] = shrink_first
    floor["gross_grade"] = gross_grade
    return floor


class TestSettlementBasisVariants:
    """SHRINK_FIRST removes moisture as bushels; GROSS_GRADE removes it as a
    cents-per-bushel drying charge."""

    def test_shrink_first_removes_moisture_as_bushels(self, api):
        """PRD §3.7: "Under `SHRINK_FIRST`, the excess moisture is the measured
        `moisture_pct` less the schedule's `moisture_standard_pct`, floored at zero
        so a dry load has no excess; `shrink_pct` is that excess multiplied by the
        schedule's `shrink_factor_pct_per_point`; and `net_bushels` is
        `gross_bushels` multiplied by one minus one-hundredth of `shrink_pct`,
        rounded half-up to 2 decimal places."
        PRD §3.7: "Under `SHRINK_FIRST` the `MOISTURE` factor's rate is forced to
        zero, because the shrink taken in step one has already extracted the
        moisture penalty and charging the tier as well would be charging twice."

        Design: Difficulty/dual_variant_calc/delivery_settlement_shrink_first_vs_gross_grade
        """
        scenario = _dual_variant_scenario()

        ticket = new_ticket(
            scenario["shrink_first"]["id"], scenario["location"]["id"],
            gross_bushels=10000, **DIRTY_LOAD,
        )
        assert_delivery_ticket(ticket)

        assert ticket["shrink_pct"] == pytest.approx(1.416, abs=0.0001), (
            f"(16.2 - 15.0) x 1.18 = 1.416, got {ticket['shrink_pct']}"
        )
        assert ticket["net_bushels"] == pytest.approx(9858.40, abs=0.01), (
            f"10000 x (1 - 0.01416) = 9,858.40, got {ticket['net_bushels']}"
        )
        assert ticket["discount_total_usd"] == pytest.approx(1774.51, abs=0.01), (
            f"690.09 + 295.75 + 788.67 with moisture forced to zero = 1,774.51, "
            f"got {ticket['discount_total_usd']}"
        )
        assert ticket["gross_contract_value_usd"] == pytest.approx(41010.94, abs=0.01)
        assert ticket["service_fee_cents_per_bushel"] == pytest.approx(3.0, abs=0.01)
        assert ticket["settlement_value_usd"] == pytest.approx(38940.68, abs=0.01)

    def test_gross_grade_keeps_the_bushels_and_charges_moisture_as_a_rate(self, api):
        """PRD §3.7: "Under `GROSS_GRADE`, no bushels are removed at all:
        `shrink_pct` is zero and `net_bushels` is simply `gross_bushels` rounded
        half-up to 2 decimal places."
        PRD §3.7: "Under `GROSS_GRADE` no shrink was taken, so the `MOISTURE` tier
        is evaluated normally and becomes a cents-per-bushel drying charge."

        Design: Difficulty/dual_variant_calc/delivery_settlement_shrink_first_vs_gross_grade
        """
        scenario = _dual_variant_scenario()

        ticket = new_ticket(
            scenario["gross_grade"]["id"], scenario["location"]["id"],
            gross_bushels=10000, **DIRTY_LOAD,
        )

        assert ticket["shrink_pct"] == pytest.approx(0, abs=0.0001)
        assert ticket["net_bushels"] == pytest.approx(10000.00, abs=0.01)
        assert ticket["discount_total_usd"] == pytest.approx(2550.00, abs=0.01), (
            f"750.00 moisture + 700.00 test weight + 300.00 foreign material + "
            f"800.00 damage = 2,550.00, got {ticket['discount_total_usd']}"
        )
        assert ticket["gross_contract_value_usd"] == pytest.approx(41600.00, abs=0.01)
        assert ticket["settlement_value_usd"] == pytest.approx(38750.00, abs=0.01)

    def test_the_two_variants_diverge_on_identical_probe_readings(self, api):
        """PRD §3.7: "The contract's `settlement_basis` selects between two
        settlement variants that differ in how moisture is charged for, and the
        choice is made once, on the contract, and applies to every load delivered
        against it."
        PRD §3.7: "The other three factors are evaluated identically under both
        variants; what differs is only that under `SHRINK_FIRST` they extend on the
        shrunken bushels while under `GROSS_GRADE` they extend on the full gross
        bushels, since in that variant the two quantities are the same number."

        Design: Difficulty/dual_variant_calc/delivery_settlement_shrink_first_vs_gross_grade
        """
        scenario = _dual_variant_scenario()

        shrink_ticket = new_ticket(
            scenario["shrink_first"]["id"], scenario["location"]["id"],
            gross_bushels=10000, **DIRTY_LOAD,
        )
        gross_ticket = new_ticket(
            scenario["gross_grade"]["id"], scenario["location"]["id"],
            gross_bushels=10000, **DIRTY_LOAD,
        )

        assert shrink_ticket["net_bushels"] != gross_ticket["net_bushels"], (
            "identical readings must yield different net bushels under the two "
            "settlement variants"
        )
        assert shrink_ticket["net_bushels"] == pytest.approx(9858.40, abs=0.01)
        assert gross_ticket["net_bushels"] == pytest.approx(10000.00, abs=0.01)
        assert shrink_ticket["discount_total_usd"] == pytest.approx(1774.51, abs=0.01)
        assert gross_ticket["discount_total_usd"] == pytest.approx(2550.00, abs=0.01)


class TestPerFactorRoundingOrder:
    """Each factor is extended and rounded on its own before the four amounts
    are summed."""

    def _rounding_scenario(self):
        floor = setup_trading_floor(
            desk_code="GD3", desk_name="Rounding Desk", lots_open=20,
            avg_entry_price_cents=448, schedule_tiers=FULL_TIERS,
        )
        floor["contract"] = new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=50000, seller_name="Bell Farms", futures_price_cents=448,
            settlement_basis="SHRINK_FIRST",
        )
        return floor

    def test_rounding_each_factor_before_summing_gives_the_extra_cent(self, api):
        """PRD §3.7: "The rounding order is pinned and it matters. Each factor's
        dollar amount is computed on its own — `net_bushels` multiplied by that
        factor's rate, divided by 100 to turn cents into dollars, rounded half-up to
        2 decimal places — and only then are the four rounded per-factor amounts
        added together to give `discount_total_usd`."
        PRD §3.7: "Summing the four rates first and rounding the product once at the
        end is explicitly **not** the rule, and on real numbers the two orders can
        differ by a cent."

        Design: Difficulty/combinatorial_formula/quality_discount_per_factor_rounding_order
        """
        scenario = self._rounding_scenario()

        ticket = new_ticket(
            scenario["contract"]["id"], scenario["location"]["id"],
            gross_bushels=4000.24, moisture_pct=15.0, test_weight_lbs=52.4,
            foreign_material_pct=3.7, damage_pct=5.0,
        )

        assert ticket["net_bushels"] == pytest.approx(4000.24, abs=0.01)
        assert ticket["discount_total_usd"] == pytest.approx(400.03, abs=0.005), (
            f"280.02 test weight + 120.01 foreign material = 400.03, got "
            f"{ticket['discount_total_usd']}"
        )
        assert ticket["discount_total_usd"] != pytest.approx(400.02, abs=0.001), (
            "400.02 is the answer produced by summing the rates first and rounding "
            "once at the end, which is explicitly not the rule"
        )

    def test_the_pinned_rounding_order_carries_into_the_settlement_value(self, api):
        """PRD §3.7: "For each evaluated factor, the number of penalty steps depends
        on the tier's `direction`. When `direction` is `ABOVE`, the shortfall is the
        measured value less the tier's `threshold_value`, floored at zero; when
        `direction` is `BELOW`, it is the tier's `threshold_value` less the measured
        value, floored at zero. That shortfall is divided by the tier's `unit_step`
        and **rounded up to the next whole step**, so any part of a step counts as a
        whole one. The factor's rate is the step count multiplied by
        `rate_cents_per_bushel_per_step`."
        PRD §3.7: "Fourth, `settlement_value_usd` is `net_bushels` multiplied by
        `net_unit_price_cents`, divided by 100, rounded half-up to 2 decimal places,
        and then reduced by the whole of `discount_total_usd` — the discount total,
        already rounded per factor, is subtracted from the rounded net extension
        rather than folded into it before rounding."

        Design: Difficulty/combinatorial_formula/quality_discount_per_factor_rounding_order
        """
        scenario = self._rounding_scenario()

        ticket = new_ticket(
            scenario["contract"]["id"], scenario["location"]["id"],
            gross_bushels=4000.24, moisture_pct=15.0, test_weight_lbs=52.4,
            foreign_material_pct=3.7, damage_pct=5.0,
        )

        assert ticket["gross_contract_value_usd"] == pytest.approx(16641.00, abs=0.01), (
            f"4000.24 x 416 / 100 = 16,641.00, got "
            f"{ticket['gross_contract_value_usd']}"
        )
        assert ticket["settlement_value_usd"] == pytest.approx(16120.96, abs=0.01), (
            f"16,520.99 net extension less 400.03 of discounts = 16,120.96, got "
            f"{ticket['settlement_value_usd']}"
        )


class TestServiceFeeTierSelection:
    """The fee tier is keyed on the pre-fee gross value and is never re-derived
    from the post-fee value."""

    def _fee_scenario(self):
        floor = setup_trading_floor(
            desk_code="GD4", desk_name="Fee Tier Desk", lots_open=20,
            avg_entry_price_cents=449, schedule_tiers=FULL_TIERS,
        )
        floor["contract"] = new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=50000, seller_name="Bell Farms", futures_price_cents=449,
            settlement_basis="SHRINK_FIRST",
        )
        return floor

    def test_the_tier_comes_from_the_gross_value_above_the_breakpoint(self, api):
        """PRD §3.7: "Second, the merchandising service fee tier is selected **from
        that gross figure**: a gross value below 50,000.00 dollars draws a fee of
        3.0 cents per bushel, a gross value below 250,000.00 dollars draws 2.0 cents
        per bushel, and anything at or above 250,000.00 dollars draws 1.0 cent per
        bushel — both breakpoints being exclusive upper bounds, so a value landing
        exactly on 50,000.00 falls into the second band and one landing exactly on
        250,000.00 falls into the third."
        PRD §3.7: "First, `gross_contract_value_usd` is `net_bushels` multiplied by
        the contract's `gross_unit_price_cents`, divided by 100, rounded half-up to
        2 decimal places."

        Design: Difficulty/combinatorial_formula/service_fee_tier_keyed_on_pre_fee_gross_value
        """
        scenario = self._fee_scenario()

        ticket = new_ticket(
            scenario["contract"]["id"], scenario["location"]["id"],
            gross_bushels=12000, **CLEAN_LOAD,
        )

        assert ticket["net_bushels"] == pytest.approx(12000.00, abs=0.01)
        assert ticket["discount_total_usd"] == pytest.approx(0.00, abs=0.01)
        assert ticket["gross_contract_value_usd"] == pytest.approx(50040.00, abs=0.01), (
            f"12000 x 417 / 100 = 50,040.00, got "
            f"{ticket['gross_contract_value_usd']}"
        )
        assert ticket["service_fee_cents_per_bushel"] == pytest.approx(2.0, abs=0.01), (
            f"50,040.00 clears the 50,000.00 breakpoint, so the fee is 2.0 cents, "
            f"got {ticket['service_fee_cents_per_bushel']}"
        )

    def test_the_tier_is_not_re_derived_from_the_post_fee_value(self, api):
        """PRD §3.7: "Crucially, the tier is never re-derived from the post-fee
        value: a load whose gross value clears a breakpoint but whose net value
        would fall back below it keeps the tier the gross value selected."
        PRD §3.7: "Third, `net_unit_price_cents` is the contract's
        `gross_unit_price_cents` less `service_fee_cents_per_bushel`."

        Design: Difficulty/combinatorial_formula/service_fee_tier_keyed_on_pre_fee_gross_value
        """
        scenario = self._fee_scenario()

        ticket = new_ticket(
            scenario["contract"]["id"], scenario["location"]["id"],
            gross_bushels=12000, **CLEAN_LOAD,
        )

        assert ticket["net_unit_price_cents"] == pytest.approx(415, abs=0.0001), (
            f"417 less the 2.0 cent fee = 415, got {ticket['net_unit_price_cents']}"
        )
        assert ticket["settlement_value_usd"] == pytest.approx(49800.00, abs=0.01), (
            f"12000 x 415 / 100 = 49,800.00, which falls back below the 50,000.00 "
            f"breakpoint yet leaves the 2.0 cent tier untouched, got "
            f"{ticket['settlement_value_usd']}"
        )
        assert ticket["service_fee_cents_per_bushel"] == pytest.approx(2.0, abs=0.01)


class TestMoistureStandardBoundary:

    def _moisture_scenario(self):
        floor = setup_trading_floor(
            desk_code="GD14", desk_name="Moisture Desk", lots_open=20,
            avg_entry_price_cents=448, schedule_tiers=FULL_TIERS,
            moisture_standard_pct=15.0, shrink_factor_pct_per_point=1.18,
        )
        floor["contract"] = new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=50000, seller_name="Bell Farms", futures_price_cents=448,
            settlement_basis="SHRINK_FIRST",
        )
        return floor

    def test_a_load_reading_exactly_the_standard_takes_no_shrink(self, api):
        """PRD §3.7: "Note that the moisture standard is a ceiling that is itself
        penalty-free — a load reading exactly the standard has zero excess points
        and therefore zero shrink; only a reading strictly above it shrinks."
        PRD §3.7: "A factor with no tier row on the schedule contributes a rate of
        zero, and therefore an amount of exactly 0.00."

        Design: Difficulty/boundary_precision_check/moisture_exactly_at_standard_yields_no_shrink
        """
        scenario = self._moisture_scenario()

        ticket = new_ticket(
            scenario["contract"]["id"], scenario["location"]["id"],
            gross_bushels=10000, moisture_pct=15.0, test_weight_lbs=56.0,
            foreign_material_pct=2.0, damage_pct=0.0,
        )

        assert ticket["shrink_pct"] == pytest.approx(0, abs=0.0001)
        assert ticket["net_bushels"] == pytest.approx(10000.00, abs=0.01), (
            f"at exactly the standard net bushels equal gross bushels, got "
            f"{ticket['net_bushels']}"
        )
        assert ticket["discount_total_usd"] == pytest.approx(0.00, abs=0.01)

    def test_one_tenth_of_a_point_above_the_standard_shrinks_the_load(self, api):
        """PRD §3.7: "Under `SHRINK_FIRST`, the excess moisture is the measured
        `moisture_pct` less the schedule's `moisture_standard_pct`, floored at zero
        so a dry load has no excess; `shrink_pct` is that excess multiplied by the
        schedule's `shrink_factor_pct_per_point`; and `net_bushels` is
        `gross_bushels` multiplied by one minus one-hundredth of `shrink_pct`,
        rounded half-up to 2 decimal places."
        PRD §3.1: "and `shrink_factor_pct_per_point`, the shrink percentage taken
        per whole point of moisture above that standard, which defaults to 1.18."

        Design: Difficulty/boundary_precision_check/moisture_exactly_at_standard_yields_no_shrink
        """
        scenario = self._moisture_scenario()

        ticket = new_ticket(
            scenario["contract"]["id"], scenario["location"]["id"],
            gross_bushels=10000, moisture_pct=15.1, test_weight_lbs=56.0,
            foreign_material_pct=2.0, damage_pct=0.0,
        )

        assert ticket["shrink_pct"] == pytest.approx(0.118, abs=0.0001), (
            f"(15.1 - 15.0) x 1.18 = 0.118, got {ticket['shrink_pct']}"
        )
        assert ticket["net_bushels"] == pytest.approx(9988.20, abs=0.01), (
            f"10000 x (1 - 0.00118) = 9,988.20, got {ticket['net_bushels']}"
        )
        assert ticket["discount_total_usd"] == pytest.approx(0.00, abs=0.01), (
            "under SHRINK_FIRST the moisture tier rate is forced to zero"
        )


class TestScheduleSelectionAndAbsence:

    def test_grading_pins_the_active_schedule_and_ignores_the_superseded_one(self, api):
        """PRD §3.7: "That single `ACTIVE` schedule is the only one ever consulted —
        a `DRAFT` schedule and a `SUPERSEDED` schedule are both invisible here — and
        its id is written onto the ticket as `discount_schedule_id`, pinning the
        grading rules for the life of the ticket even after a newer schedule
        supersedes it."

        Design: Corner/calculations/grading_consults_only_the_active_discount_schedule
        """
        floor = setup_trading_floor(
            desk_code="CD22", desk_name="Corner Desk 22", lots_open=10,
            schedule_tiers=TEST_WEIGHT_TIERS,
        )
        superseded = floor["schedule"]
        current = new_schedule(
            activate=True, commodity_code="CORN",
            effective_from="2026-07-15T00:00:00Z",
            tiers=[dict(t) for t in TEST_WEIGHT_TIERS_DEAR],
        )
        contract = new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=20000, seller_name="Bell Farms", futures_price_cents=448,
            settlement_basis="SHRINK_FIRST",
        )

        ticket = new_ticket(
            contract["id"], floor["location"]["id"], gross_bushels=10000,
            moisture_pct=15.0, test_weight_lbs=52.4, foreign_material_pct=2.0,
            damage_pct=0.0,
        )

        assert ticket["discount_schedule_id"] == current["id"], (
            "the ticket pins the ACTIVE schedule, never the superseded one"
        )
        assert ticket["net_bushels"] == pytest.approx(10000.00, abs=0.01)
        assert ticket["discount_total_usd"] == pytest.approx(2000.00, abs=0.01), (
            f"2 steps at the 10.0 cent rate over 10,000 bushels = 2,000.00, got "
            f"{ticket['discount_total_usd']}"
        )
        assert ticket["settlement_value_usd"] == pytest.approx(39300.00, abs=0.01)
        assert read_schedule(superseded["id"])["status"] == "SUPERSEDED"

    def test_grading_without_an_active_schedule_is_refused(self, api):
        """PRD §3.7: "And there must be a discount schedule in `ACTIVE` status for
        the contract's commodity; when none exists, grading is refused with
        `ERR_NO_ACTIVE_DISCOUNT_SCHEDULE`."

        Design: Corner/validations/grading_without_an_active_schedule_returns_no_active_discount_schedule
        """
        scenario = setup_contract_scenario(
            desk_code="CD37", desk_name="Corner Desk 37", lots_open=10,
            schedule_activate=False, schedule_tiers=TEST_WEIGHT_TIERS,
            contract_overrides={"contract_type": "CASH", "bushels": 20000},
        )

        payload = create_delivery_ticket_payload(
            scenario["contract"]["id"], scenario["location"]["id"],
            gross_bushels=5000, **CLEAN_LOAD,
        )
        validate_error(api.create_delivery_ticket(payload, INSPECTOR),
                       ApiErrorId.ERR_NO_ACTIVE_DISCOUNT_SCHEDULE.value, 422)

        assert read_schedule(scenario["schedule"]["id"])["status"] == "DRAFT"
        _, meta = validate_paginated(api.list_delivery_tickets(
            INSPECTOR, params={"contract_id": scenario["contract"]["id"]}
        ))
        assert meta["total_count"] == 0

    def test_a_load_on_an_unpriced_contract_carries_no_money(self, api):
        """PRD §3.7: "When the contract's `gross_unit_price_cents` is null — because
        at least one leg is still floating — then `gross_contract_value_usd`,
        `service_fee_cents_per_bushel`, `net_unit_price_cents` and
        `settlement_value_usd` are all null on the ticket, and the load is still
        perfectly gradeable and appliable; it simply carries no money with it."
        PRD §3.8: "On success the contract's `delivered_bushels` grows by the
        ticket's `net_bushels` and its `settled_value_usd` grows by the ticket's
        `settlement_value_usd`, where a null settlement value is treated as zero."

        Design: Corner/calculations/ticket_on_unpriced_contract_leaves_settlement_fields_null
        """
        scenario = setup_contract_scenario(
            desk_code="CD23", desk_name="Corner Desk 23", lots_open=10,
            schedule_tiers=TEST_WEIGHT_TIERS,
            contract_overrides={"contract_type": "DEFERRED", "bushels": 20000},
        )

        ticket = new_ticket(
            scenario["contract"]["id"], scenario["location"]["id"],
            gross_bushels=10000, moisture_pct=15.0, test_weight_lbs=52.4,
            foreign_material_pct=2.0, damage_pct=0.0,
        )
        assert ticket["net_bushels"] == pytest.approx(10000.00, abs=0.01)
        assert ticket["discount_total_usd"] == pytest.approx(700.00, abs=0.01), (
            f"2 steps at the 3.5 cent rate over 10,000 bushels = 700.00, got "
            f"{ticket['discount_total_usd']}"
        )
        assert ticket["gross_contract_value_usd"] is None
        assert ticket["service_fee_cents_per_bushel"] is None
        assert ticket["net_unit_price_cents"] is None
        assert ticket["settlement_value_usd"] is None

        apply_ticket(ticket["id"])
        contract = read_contract(scenario["contract"]["id"])
        assert contract["delivered_bushels"] == pytest.approx(10000.00, abs=0.01)
        assert contract["settled_value_usd"] == pytest.approx(0.00, abs=0.01)
        assert contract["status"] == "ACTIVE"
        assert contract["pricing_status"] == "UNPRICED"


class TestLocationMismatchPrecedesScheduleAbsence:
    """A grading request that is both at the wrong elevator and unbacked by any
    ACTIVE schedule reports the earlier ladder row (rank 15)."""

    def _mismatch_scenario(self):
        floor = setup_trading_floor(
            desk_code="GD12", desk_name="Ladder B Desk", with_schedule=False,
            lots_open=10,
        )
        floor["other_location"] = new_location(
            floor["desk"]["id"], location_code="ELV2", name="Seneca Elevator",
            intake_capacity_bushels=5000000, rail_served=False,
        )
        floor["contract"] = new_contract(
            floor["bid"]["id"], floor["position"]["id"], contract_type="CASH",
            bushels=10000, seller_name="Bell Farms", futures_price_cents=448,
        )
        return floor

    def test_the_wrong_elevator_is_reported_over_the_missing_schedule(self, api):
        """PRD §3.7: "The ticket's `location_id` must equal the contract's own
        `location_id` — grain delivered to the wrong elevator is not this contract's
        grain — with a mismatch reported as `ERR_LOCATION_MISMATCH`."
        PRD §2.8: "This ordering is normative, not a description of a convenient
        implementation: when two conditions are simultaneously violated, the
        response must name the earlier one."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_ticket_location_mismatch
        """
        scenario = self._mismatch_scenario()

        payload = create_delivery_ticket_payload(
            scenario["contract"]["id"], scenario["other_location"]["id"],
            gross_bushels=5000, **CLEAN_LOAD,
        )
        resp = api.create_delivery_ticket(payload, INSPECTOR)
        error = validate_error(resp, ApiErrorId.ERR_LOCATION_MISMATCH.value, 422)

        assert resp.status_code == 422
        assert error["error_id"] != ApiErrorId.ERR_NO_ACTIVE_DISCOUNT_SCHEDULE.value, (
            "the priority-15 referential rule decides, not the priority-29 rule"
        )

    def test_the_refused_grading_leaves_no_ticket_behind(self, api):
        """PRD §3.7: "Grading computes everything at once and freezes the result.
        The acting `X-User-ID` is stored as `graded_by_user_id`, the ticket lands in
        `GRADED` status, and **nothing else in the system moves**: no contract
        field, no hedge position, no desk aggregate and no freight booking changes
        at grading time."
        PRD §3.7: "The ticket's `location_id` must equal the contract's own
        `location_id` — grain delivered to the wrong elevator is not this contract's
        grain — with a mismatch reported as `ERR_LOCATION_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_constraint_on_ticket_location_mismatch
        """
        scenario = self._mismatch_scenario()

        payload = create_delivery_ticket_payload(
            scenario["contract"]["id"], scenario["other_location"]["id"],
            gross_bushels=5000, **CLEAN_LOAD,
        )
        validate_error(api.create_delivery_ticket(payload, INSPECTOR),
                       ApiErrorId.ERR_LOCATION_MISMATCH.value, 422)

        _, meta = validate_paginated(api.list_delivery_tickets(
            INSPECTOR, params={"contract_id": scenario["contract"]["id"]}
        ))
        assert meta["total_count"] == 0, (
            "no delivery ticket row may exist for the contract after the refusal"
        )
