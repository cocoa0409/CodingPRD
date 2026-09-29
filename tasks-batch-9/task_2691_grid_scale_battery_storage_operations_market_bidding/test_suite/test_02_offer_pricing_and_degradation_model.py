"""Offer floor pricing and the pinned state-of-health degradation model.

Both are multi-term formulas whose terms interact non-linearly: a tier knee in
the cycle-scarcity ladder and a direction branch in the price, an evaluation
order in the degradation model that decides which rated energy a remedy is
sized against.
"""
import pytest

from test_helpers.fixtures import (
    approve_claim,
    completed_test,
    draft_bid,
    file_claim,
    hold_reservation,
    install_remedy,
    lightly_cycled_plant,
    mid_life_plant,
    refresh_asset,
    refresh_claim,
    set_clock,
    submit_claim,
)


class TestOfferFloorPrice:
    """A plant 85 percent through its throughput warranty with 195 cycles left."""

    def _drafting_context(self):
        set_clock("2026-08-01T00:00:00Z")
        asset = mid_life_plant()
        reservation = hold_reservation(asset["id"], reserved_mwh=40.0)
        return asset, reservation

    def test_discharge_floor_stacks_charge_cost_degradation_and_warranty_terms(self):
        """Selling energy prices wear on top of the grossed-up cost of charging: 45.60 dollars.

        PRD: "For a `DISCHARGE` offer the floor is the sum of the charge-cost, degradation and warranty terms, multiplied by the product weighting."

        Design: Difficulty/combinatorial_formula/bid_floor_price_nonlinear_tier_knee_and_direction_branch
        """
        asset, reservation = self._drafting_context()

        bid = draft_bid(
            asset["id"],
            reservation["id"],
            market_type="DAY_AHEAD",
            product="ENERGY",
            direction="DISCHARGE",
            offer_mw=20.0,
        )

        assert asset["equivalent_full_cycles_ytd"] == pytest.approx(170.0, abs=0.01)
        assert bid["offer_price_usd_per_mwh"] == pytest.approx(45.60, abs=0.01)
        assert bid["expected_energy_mwh"] == pytest.approx(80.0, abs=0.01)
        assert bid["cycle_debit_efc"] == pytest.approx(0.4, abs=0.01)
        assert bid["status"] == "DRAFT"

    def test_charge_floor_subtracts_the_wear_terms_from_the_energy_cost(self):
        """Being paid to absorb energy flips the wear terms negative: 4.40 dollars.

        PRD: "For a `CHARGE` offer the operator is paid to absorb energy, so the wear terms subtract instead: the floor is the greater of 0 and the charge-cost term minus the degradation term minus the warranty term, multiplied by the product weighting."

        Design: Difficulty/combinatorial_formula/bid_floor_price_nonlinear_tier_knee_and_direction_branch
        """
        asset, reservation = self._drafting_context()

        bid = draft_bid(
            asset["id"],
            reservation["id"],
            market_type="DAY_AHEAD",
            product="ENERGY",
            direction="CHARGE",
            offer_mw=20.0,
        )

        assert bid["direction"] == "CHARGE"
        assert bid["offer_price_usd_per_mwh"] == pytest.approx(4.40, abs=0.01)

    def test_reserve_product_weighting_applies_before_the_trader_adder(self):
        """A spinning-reserve offer weights the floor to 0.55 and then adds the margin: 28.08.

        PRD: "`offer_price_usd_per_mwh` is then the greater of that floor plus `price_adder_usd_per_mwh` and a minimum offer price of 0.00 dollars, rounded half up to 2 decimal places."

        Design: Difficulty/combinatorial_formula/bid_floor_price_nonlinear_tier_knee_and_direction_branch
        """
        asset, reservation = self._drafting_context()

        bid = draft_bid(
            asset["id"],
            reservation["id"],
            market_type="REAL_TIME",
            product="SPIN",
            direction="DISCHARGE",
            offer_mw=12.0,
            price_adder_usd_per_mwh=3.00,
        )

        assert bid["product"] == "SPIN"
        assert bid["offer_price_usd_per_mwh"] == pytest.approx(28.08, abs=0.01)
        assert bid["status"] == "DRAFT"


class TestDegradationModelEvaluationOrder:
    """A capacity test, the remedy it justifies, and a second test after augmentation."""

    def test_first_test_is_read_against_beginning_of_life_rated_energy(self):
        """90 MWh measured against 100 MWh rated leaves a 2.10 point deficit that triggers the warranty.

        PRD: "**Measured state of health** is `measured_capacity_mwh` divided by the step-1 rated energy, multiplied by 100, rounded half up to 2 decimal places, and it is stored as `measured_soh_pct`."

        Design: Difficulty/combinatorial_formula/soh_model_pinned_order_sizes_remedy_against_pre_remedy_rated_energy
        """
        set_clock("2026-08-01T00:00:00Z")
        asset = lightly_cycled_plant()

        test = completed_test(
            asset["id"],
            scheduled_date="2026-08-01T00:00:00Z",
            measured_capacity_mwh=90.0,
        )

        assert test["status"] == "COMPLETED"
        assert test["expected_soh_pct"] == pytest.approx(92.10, abs=0.01)
        assert test["measured_soh_pct"] == pytest.approx(90.00, abs=0.01)
        assert test["soh_deficit_pct"] == pytest.approx(2.10, abs=0.01)
        assert test["warranty_claim_triggered"] is True
        assert test["test_energy_throughput_mwh"] == pytest.approx(90.0, abs=0.01)

    def test_remedy_is_sized_against_the_rated_energy_that_existed_before_it(self):
        """A 2.10 point shortfall on a 100 MWh plant buys 2.31 MWh of augmentation racks.

        PRD: "**Remedy sizing** happens later, on the approval branch of adjudication: `remedy_energy_add_mwh` is the step-1 rated energy multiplied by the claim's `claimed_shortfall_pct` divided by 100, multiplied by an oversize factor of 1.10, rounded half up to 3 decimal places."

        Design: Difficulty/combinatorial_formula/soh_model_pinned_order_sizes_remedy_against_pre_remedy_rated_energy
        """
        set_clock("2026-08-01T00:00:00Z")
        asset = lightly_cycled_plant()
        test = completed_test(
            asset["id"],
            scheduled_date="2026-08-01T00:00:00Z",
            measured_capacity_mwh=90.0,
        )
        claim = file_claim(asset["id"], test["id"])
        submit_claim(claim["id"])

        approved = approve_claim(
            claim["id"],
            remedy_install_date="2026-09-01T00:00:00Z",
            remedy_outage_days=3,
        )
        asset_while_approved = refresh_asset(asset["id"])

        assert approved["status"] == "APPROVED"
        assert approved["claimed_shortfall_pct"] == pytest.approx(2.10, abs=0.01)
        assert approved["remedy_energy_add_mwh"] == pytest.approx(2.31, abs=0.01)
        assert asset_while_approved["rated_energy_mwh"] == pytest.approx(100.0, abs=0.01)

    def test_installation_grows_rated_available_energy_and_recomputes_the_cycles(self):
        """Installing the racks lifts rated energy to 102.31 MWh and available energy to 92.079 MWh.

        PRD: "The propagation order is pinned and is followed exactly: the asset's `rated_energy_mwh` is recomputed by step 1 with this claim now `REMEDIED`, so it includes this claim's `remedy_energy_add_mwh`; then `available_energy_mwh` becomes `rated_energy_mwh` multiplied by the asset's `soh_pct` divided by 100, rounded half up to 3 decimal places; then `equivalent_full_cycles_ytd` is recomputed as `cumulative_throughput_mwh` divided by twice the new `available_energy_mwh`, rounded half up to 4 decimal places; and `free_dispatchable_mwh` is recomputed last."

        Design: Difficulty/combinatorial_formula/soh_model_pinned_order_sizes_remedy_against_pre_remedy_rated_energy
        """
        set_clock("2026-08-01T00:00:00Z")
        asset = lightly_cycled_plant()
        test = completed_test(
            asset["id"],
            scheduled_date="2026-08-01T00:00:00Z",
            measured_capacity_mwh=90.0,
        )
        claim = file_claim(asset["id"], test["id"])
        submit_claim(claim["id"])
        approve_claim(
            claim["id"],
            remedy_install_date="2026-09-01T00:00:00Z",
            remedy_outage_days=3,
        )
        set_clock("2026-09-01T00:00:00Z")

        remedied = install_remedy(claim["id"])
        augmented = refresh_asset(asset["id"])

        assert remedied["status"] == "REMEDIED"
        assert augmented["rated_energy_mwh"] == pytest.approx(102.31, abs=0.01)
        assert augmented["soh_pct"] == pytest.approx(90.00, abs=0.01)
        assert augmented["available_energy_mwh"] == pytest.approx(92.079, abs=0.01)
        assert augmented["equivalent_full_cycles_ytd"] == pytest.approx(0.5962, abs=0.01)
        assert augmented["cumulative_throughput_mwh"] == pytest.approx(109.8, abs=0.01)

    def test_an_augmented_plant_is_judged_against_the_higher_bar(self):
        """The same 90 MWh measurement now reads 87.97 percent against 102.31 MWh rated.

        PRD: "Because the same measured capacity is judged against whatever rated energy the asset carries, an augmented plant is judged against a higher bar: before any remedy is installed, rated energy equals `nameplate_energy_mwh` and the measurement is read against beginning-of-life energy, whereas once at least one claim is `REMEDIED` the rated energy includes every installed remedy, so an identical `measured_capacity_mwh` yields a lower `measured_soh_pct` and a larger `soh_deficit_pct`."

        Design: Difficulty/combinatorial_formula/soh_model_pinned_order_sizes_remedy_against_pre_remedy_rated_energy
        """
        set_clock("2026-08-01T00:00:00Z")
        asset = lightly_cycled_plant()
        first = completed_test(
            asset["id"],
            scheduled_date="2026-08-01T00:00:00Z",
            measured_capacity_mwh=90.0,
        )
        claim = file_claim(asset["id"], first["id"])
        submit_claim(claim["id"])
        approve_claim(
            claim["id"],
            remedy_install_date="2026-09-01T00:00:00Z",
            remedy_outage_days=3,
        )
        set_clock("2026-09-01T00:00:00Z")
        install_remedy(claim["id"])

        second = completed_test(
            asset["id"],
            scheduled_date="2026-09-10T00:00:00Z",
            measured_capacity_mwh=90.0,
        )

        assert refresh_claim(claim["id"])["status"] == "REMEDIED"
        assert second["measured_soh_pct"] == pytest.approx(87.97, abs=0.01)
        assert second["expected_soh_pct"] == pytest.approx(90.02, abs=0.01)
        assert second["soh_deficit_pct"] == pytest.approx(2.05, abs=0.01)
        assert second["warranty_claim_triggered"] is True
