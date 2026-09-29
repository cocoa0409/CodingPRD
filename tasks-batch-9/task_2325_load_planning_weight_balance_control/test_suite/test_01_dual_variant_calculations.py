"""Two configurations of the same operation that must diverge numerically."""

from __future__ import annotations

from typing import Tuple

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import (
    AUDIT_INSPECTOR,
    CAPTAIN_1,
    LOAD_CONTROLLER_1,
    api_client,
)
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import captain_headers, load_controller_headers

# ---------------------------------------------------------------------------
# Weight programme kind: published masses against weighed masses
# ---------------------------------------------------------------------------

#: The same passenger mix seated in the same three cabin zones on both flights.
_PAX_MIX = (
    ("OA", {"male_count": 10, "female_count": 8, "child_count": 2, "infant_count": 1}),
    ("OB", {"male_count": 25, "female_count": 20, "child_count": 5, "infant_count": 2}),
    ("OC", {"male_count": 20, "female_count": 18, "child_count": 3, "infant_count": 0}),
)
#: The weighed cabin-zone totals declared under the ACTUAL programme.
_ACTUAL_ZONE_WEIGHTS = {"OA": 1480, "OB": 3700, "OC": 3060}
_BAGS = (("H1", 112, 1450), ("H4", 92, 1200), ("H5", 23, 300))


def _programme_pair() -> Tuple[fx.Scenario, fx.Scenario]:
    """Two airframes flying the same distribution under the two programme kinds."""
    standard = fx.reference_world(band_specs=[F.CANONICAL_BANDS[1]])
    actual = fx.sibling_airframe_world(standard)
    actual.program = fx.create_actual_weight_program()

    fx.flight_world(standard, flight_number="LX1602")
    fx.flight_world(
        actual,
        flight_number="LX1604",
        scheduled_off_block_utc="2026-08-15T10:20:00Z",
        scheduled_on_block_utc="2026-08-15T12:50:00Z",
    )

    standard.plan = fx.open_plan(standard.flight_id)
    actual.plan = fx.open_plan(actual.flight_id)

    for code, counts in _PAX_MIX:
        fx.seat(standard, code, **counts)
        fx.seat(actual, code, actual_weight_kg=_ACTUAL_ZONE_WEIGHTS[code], **counts)
    for code, bag_count, bag_weight_kg in _BAGS:
        fx.stow_bags(standard, code, bag_count, bag_weight_kg)
        fx.stow_bags(actual, code, bag_count, bag_weight_kg)
    fx.book_and_stow_cargo(
        standard, "724-11110001", "H4", item_kind="GENERAL", weight_kg=900, length_m=1.2
    )
    fx.book_and_stow_cargo(
        actual, "724-11110002", "H4", item_kind="GENERAL", weight_kg=900, length_m=1.2
    )

    fx.compute_plan(standard)
    fx.compute_plan(actual)
    return standard, actual


class TestWeightProgrammeKindDivergence:
    def test_standard_programme_prices_the_mix_from_published_masses(self):
        """A STANDARD programme prices every zone from the published per-head masses.

        PRD: "Under `STANDARD`, the mass is the male count multiplied by the
        programme's `male_kg`, plus the female count multiplied by `female_kg`,
        plus the child count multiplied by `child_kg`, plus the infant count
        multiplied by `infant_kg` — so lap infants contribute mass even though
        they consume no seat."

        Design: Difficulty/dual_variant_calc/pax_weight_program_standard_vs_actual_diverges
        """
        standard, _ = _programme_pair()

        A.assert_plan_figures(
            standard.plan,
            status="COMPUTED",
            base_payload_kg=12290.00,
            index_zfw=85.24,
            mac_zfw_pct=15.30,
            takeoff_weight_kg=64390.00,
            mac_tow_pct=16.21,
            underload_kg=7890.00,
        )
        A.assert_kg(standard.pax_line("OA")["line_weight_kg"], 1520.00, "OA line_weight_kg")
        A.assert_kg(standard.pax_line("OB")["line_weight_kg"], 3795.00, "OB line_weight_kg")
        A.assert_kg(standard.pax_line("OC")["line_weight_kg"], 3125.00, "OC line_weight_kg")

    def test_actual_programme_takes_the_weighed_zone_totals_verbatim(self):
        """An ACTUAL programme takes the weighed total and ignores the head counts.

        PRD: "Under `ACTUAL`, the mass is the weighed `actual_weight_kg` taken
        verbatim, and the four counts contribute no mass at all; they exist only
        for the seat-capacity check."

        Design: Difficulty/dual_variant_calc/pax_weight_program_standard_vs_actual_diverges
        """
        _, actual = _programme_pair()

        A.assert_plan_figures(
            actual.plan,
            status="COMPUTED",
            base_payload_kg=12090.00,
            index_zfw=84.95,
            mac_zfw_pct=15.23,
            takeoff_weight_kg=64190.00,
            mac_tow_pct=16.15,
            underload_kg=8090.00,
        )
        for code, weighed in _ACTUAL_ZONE_WEIGHTS.items():
            A.assert_kg(
                actual.pax_line(code)["line_weight_kg"], float(weighed), f"{code} line_weight_kg"
            )

    def test_identical_mix_under_two_programmes_diverges_by_two_hundred_kilograms(self):
        """The same seated mix lands 200 kg apart under the two programme kinds.

        PRD: "For an identical passenger mix the two programme kinds therefore
        yield a different `line_weight_kg`, a different `index_zfw` and a
        different `mac_zfw_pct`, which is exactly why the programme's
        `documentation_ref` is part of the audit trail."

        Design: Difficulty/dual_variant_calc/pax_weight_program_standard_vs_actual_diverges
        """
        standard, actual = _programme_pair()

        A.assert_kg(
            float(standard.plan["base_payload_kg"]) - float(actual.plan["base_payload_kg"]),
            200.00,
            "base payload difference between the two programme kinds",
        )
        assert float(standard.plan["index_zfw"]) != float(actual.plan["index_zfw"]), (
            "the two programme kinds should not agree on index_zfw"
        )
        assert float(standard.plan["mac_zfw_pct"]) != float(actual.plan["mac_zfw_pct"]), (
            "the two programme kinds should not agree on mac_zfw_pct"
        )
        A.assert_kg(
            float(actual.plan["underload_kg"]) - float(standard.plan["underload_kg"]),
            200.00,
            "underload difference between the two programme kinds",
        )


# ---------------------------------------------------------------------------
# Audit basis: documented plan against final load sheet
# ---------------------------------------------------------------------------

_S1_CARGO = (
    ("724-11110001", "GENERAL", 900, 1.2, "H4"),
    ("724-11110002", "COMPANY", 400, 0.8, "H1"),
    ("724-11110003", "MAIL", 250, 0.6, "H5"),
)
#: The weighed totals handed to both audits.
_ACTUAL_PAX = 8990
_ACTUAL_BAGS = 3050
_ACTUAL_CARGO = 1550


def _departed_world_with_one_applied_change() -> fx.Scenario:
    """The S1 distribution flown out with a single +176.00 kg passenger addition."""
    world = fx.reference_world(band_specs=[F.CANONICAL_BANDS[1]])
    fx.flight_world(world, flight_number="LX1602")
    world.plan = fx.open_plan(world.flight_id)

    for code, counts in _PAX_MIX:
        fx.seat(world, code, **counts)
    for code, bag_count, bag_weight_kg in _BAGS:
        fx.stow_bags(world, code, bag_count, bag_weight_kg)
    for awb, item_kind, weight_kg, length_m, code in _S1_CARGO:
        fx.book_and_stow_cargo(
            world, awb, code, item_kind=item_kind, weight_kg=weight_kg, length_m=length_m
        )
    fx.compute_plan(world)

    controller = load_controller_headers(LOAD_CONTROLLER_1)
    fx.issue_sheet(world, controller)
    validate_success(
        api_client.create_last_minute_change(
            F.last_minute_change_payload(
                world.sheet_id, "PAX_ADD", world.compartment_id("OB"), male_count=2
            ),
            controller,
        ),
        201,
    )
    fx.accept_sheet(world, captain_headers(CAPTAIN_1))
    fx.depart(world, controller)
    return world


def _open_audit(world: fx.Scenario, basis: str) -> dict:
    return get_success_data(
        api_client.create_load_audit(
            F.load_audit_payload(
                world.flight_id, basis, _ACTUAL_PAX, _ACTUAL_BAGS, _ACTUAL_CARGO
            ),
            AUDIT_INSPECTOR,
        ),
        201,
    )


class TestAuditBasisDivergence:
    def test_documented_basis_ignores_the_applied_last_minute_change(self):
        """A DOCUMENTED_BASIS audit scores against the plan as it was computed.

        PRD: "Under `DOCUMENTED_BASIS` the three basis figures are exactly the
        documented figures above, ignoring every applied last-minute change —
        this asks "how good was the plan?"."

        Design: Difficulty/dual_variant_calc/audit_discrepancy_documented_vs_final_basis_severity_flip
        """
        world = _departed_world_with_one_applied_change()

        audit = _open_audit(world, "DOCUMENTED_BASIS")

        A.assert_audit_figures(
            audit,
            basis="DOCUMENTED_BASIS",
            pax_delta_kg=550.00,
            bag_delta_kg=100.00,
            cargo_delta_kg=0.00,
            total_absolute_discrepancy_kg=650.00,
            severity="MAJOR",
            status="OPEN",
        )

    def test_final_basis_absorbs_the_applied_passenger_addition(self):
        """A FINAL_BASIS audit shifts the passenger basis by the applied change.

        PRD: "Under `FINAL_BASIS` each documented figure is adjusted by the
        last-minute changes of the matching class recorded on the accepted sheet:
        the passenger basis is the documented passenger figure plus the sum of
        `weight_delta_kg` over `APPLIED` changes whose `change_kind` is
        `PAX_ADD` or `PAX_REMOVE`; the bag basis is the documented bag figure
        plus the same sum restricted to `BAG_ADD` and `BAG_REMOVE`; the cargo
        basis is the documented cargo figure plus the same sum restricted to
        `CARGO_OFFLOAD`."

        Design: Difficulty/dual_variant_calc/audit_discrepancy_documented_vs_final_basis_severity_flip
        """
        world = _departed_world_with_one_applied_change()
        A.assert_sheet_figures(fx.refresh_sheet(world), lmc_net_weight_delta_kg=176.00)

        audit = _open_audit(world, "FINAL_BASIS")

        A.assert_audit_figures(
            audit,
            basis="FINAL_BASIS",
            pax_delta_kg=374.00,
            bag_delta_kg=100.00,
            cargo_delta_kg=0.00,
            total_absolute_discrepancy_kg=474.00,
            severity="MINOR",
        )

    def test_the_two_bases_land_the_same_actuals_in_different_severity_bands(self):
        """One set of weighed actuals reads MAJOR on one basis and MINOR on the other.

        PRD: "For identical weighed actuals the two bases produce different
        deltas and can land in different severity bands."

        Design: Difficulty/dual_variant_calc/audit_discrepancy_documented_vs_final_basis_severity_flip
        """
        world = _departed_world_with_one_applied_change()

        documented = _open_audit(world, "DOCUMENTED_BASIS")
        final = _open_audit(world, "FINAL_BASIS")

        A.assert_kg(
            float(documented["total_absolute_discrepancy_kg"])
            - float(final["total_absolute_discrepancy_kg"]),
            176.00,
            "the gap between the two bases",
        )
        assert documented["severity"] == "MAJOR", "the plan-based audit should read MAJOR"
        assert final["severity"] == "MINOR", "the sheet-based audit should read MINOR"


# ---------------------------------------------------------------------------
# Offload strategy: cheapest traffic first against fewest pieces
# ---------------------------------------------------------------------------


def _offloaded_strategy_pair() -> Tuple[fx.Scenario, fx.Scenario]:
    """The same weight-restricted distribution relieved under both strategies."""
    priority = fx.reference_world(band_specs=[F.CANONICAL_BANDS[1]])
    fewest = fx.sibling_airframe_world(priority)

    fx.s2_restricted_world(
        "PRIORITY_FIRST", scenario=priority, awb_prefix="724-2222", flight_number="LX1606"
    )
    fx.s2_restricted_world(
        "FEWEST_PIECES",
        scenario=fewest,
        awb_prefix="724-3333",
        flight_number="LX1608",
        scheduled_off_block_utc="2026-08-15T10:20:00Z",
        scheduled_on_block_utc="2026-08-15T12:50:00Z",
    )

    fx.apply_offload(priority)
    fx.apply_offload(fewest)
    return priority, fewest


class TestOffloadStrategyDivergence:
    def test_priority_first_sheds_the_two_cheapest_consignments(self):
        """PRIORITY_FIRST walks the priority ranks and lets the mail travel.

        PRD: "Under `PRIORITY_FIRST` the ordering is `offload_priority_rank`
        ascending — so `COMPANY` traffic at rank 1 leaves first, then `GENERAL`
        at rank 2, then `MAIL` at rank 3, then any gate bag at rank 4 — then
        `weight_kg` descending, then `created_at` ascending; the lowest-value
        traffic leaves first even when that means handling several pieces."

        Design: Difficulty/dual_variant_calc/offload_strategy_priority_first_vs_fewest_pieces
        """
        priority, _ = _offloaded_strategy_pair()

        A.assert_plan_figures(
            priority.plan,
            frozen_underload_kg=-700.00,
            planned_payload_kg=18280.00,
            underload_kg=1900.00,
            index_zfw=92.30,
            mac_zfw_pct=16.56,
            mac_tow_pct=17.22,
        )
        A.assert_cargo_state(fx.refresh_cargo(priority, "724-22220001"), status="OFFLOADED")
        A.assert_cargo_state(fx.refresh_cargo(priority, "724-22220002"), status="OFFLOADED")
        A.assert_cargo_state(fx.refresh_cargo(priority, "724-22220003"), status="ACCEPTED")

    def test_fewest_pieces_sheds_the_single_heaviest_consignment(self):
        """FEWEST_PIECES relieves the excess by touching one piece only.

        PRD: "Under `FEWEST_PIECES` the ordering is `weight_kg` descending, then
        `offload_priority_rank` ascending, then `created_at` ascending; the
        heaviest single piece leaves first so that as few pieces as possible are
        handled."

        Design: Difficulty/dual_variant_calc/offload_strategy_priority_first_vs_fewest_pieces
        """
        _, fewest = _offloaded_strategy_pair()

        A.assert_plan_figures(
            fewest.plan,
            planned_payload_kg=18680.00,
            underload_kg=1500.00,
            index_zfw=89.18,
            mac_zfw_pct=15.24,
        )
        A.assert_cargo_state(fx.refresh_cargo(fewest, "724-33330001"), status="ACCEPTED")
        A.assert_cargo_state(fx.refresh_cargo(fewest, "724-33330002"), status="OFFLOADED")
        A.assert_cargo_state(fx.refresh_cargo(fewest, "724-33330003"), status="ACCEPTED")

    def test_the_two_strategies_leave_different_payloads_behind(self):
        """One excess, two orderings, two surviving distributions.

        PRD: "For the same excess the two strategies can select different
        consignments, relieve a different total weight and leave a different
        `planned_payload_kg` behind."

        Design: Difficulty/dual_variant_calc/offload_strategy_priority_first_vs_fewest_pieces
        """
        priority, fewest = _offloaded_strategy_pair()

        A.assert_kg(
            float(fewest.plan["planned_payload_kg"])
            - float(priority.plan["planned_payload_kg"]),
            400.00,
            "the payload the two strategies leave behind",
        )
        assert float(priority.plan["index_zfw"]) != float(fewest.plan["index_zfw"]), (
            "two different surviving distributions should not share one zero-fuel index"
        )
        for plan in (priority.plan, fewest.plan):
            A.assert_plan_figures(plan, status="COMPUTED", frozen_underload_kg=-700.00)
