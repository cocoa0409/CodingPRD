"""Single operations whose effects propagate across three or more entities."""

from __future__ import annotations

import pytest

from test_helpers import CAPTAIN_1, DG_OFFICER_1, LOAD_CONTROLLER_1
from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import captain_headers, dg_officer_headers, load_controller_headers

_SPECS = {spec["code"]: spec for spec in F.CANONICAL_COMPARTMENTS}


def _layout(*codes: str):
    return [_SPECS[code] for code in codes]


# ---------------------------------------------------------------------------
# Captain acceptance: release, load and notify in one call
# ---------------------------------------------------------------------------

_STOWED_DG = "724-66660001"
_STOWED_PLAIN = "724-66660002"
_UNSTOWED_DG = "724-66660003"


def _issued_cascade_world() -> fx.Scenario:
    """An issued sheet over two stowed consignments and one accepted but unstowed."""
    world = fx.reference_world(
        compartment_specs=_layout("OC", "H1", "H4"), band_specs=[F.CANONICAL_BANDS[1]]
    )
    fx.plan_world(world, flight_overrides={"flight_number": "LX1630"})
    fx.seat(world, "OC", male_count=50, child_count=6, infant_count=4)
    fx.stow_bags(world, "H1", 112, 1450)

    fx.book_and_stow_cargo(
        world, _STOWED_DG, "H4", item_kind="GENERAL", weight_kg=400, length_m=1.0,
        is_dangerous_goods=True,
    )
    fx.book_and_stow_cargo(
        world, _STOWED_PLAIN, "H4", item_kind="GENERAL", weight_kg=300, length_m=0.8
    )
    fx.book_cargo(
        world, _UNSTOWED_DG, item_kind="GENERAL", weight_kg=150, length_m=0.5,
        is_dangerous_goods=True,
    )

    fx.submit_declaration(world, _STOWED_DG, 400)
    fx.submit_declaration(
        world,
        _UNSTOWED_DG,
        150,
        un_number="UN1789",
        imo_class="CLASS_8",
        segregation_group="CORROSIVE",
    )
    officer = dg_officer_headers(DG_OFFICER_1)
    fx.accept_declaration(world.declaration_id(_STOWED_DG), officer)
    fx.accept_declaration(world.declaration_id(_UNSTOWED_DG), officer)
    fx.accept_cargo_item(world.cargo_id(_STOWED_DG))
    fx.accept_cargo_item(world.cargo_id(_UNSTOWED_DG))

    fx.compute_plan(world)
    fx.issue_sheet(world, load_controller_headers(LOAD_CONTROLLER_1))
    return world


class TestSheetAcceptanceCascade:
    def test_acceptance_releases_the_load_and_loads_every_stowed_consignment(self):
        """One signature moves the sheet, the flight and both stowed consignments.

        PRD: "Acceptance cascades in three hops. The sheet moves `ISSUED` →
        `ACCEPTED` with `accepted_by_user_id` set to the acting `X-User-ID` and
        its `version` incremented by 1."

        Design: Difficulty/transitive_cascade/sheet_accept_cascade_release_load_notoc
        """
        world = _issued_cascade_world()

        fx.accept_sheet(world, captain_headers(CAPTAIN_1))

        A.assert_sheet_figures(world.sheet, status="ACCEPTED", accepted_by_user_id=CAPTAIN_1)
        A.assert_flight_state(
            fx.refresh_flight(world),
            status="LOAD_CONTROLLED",
            load_release_state="RELEASED",
            dg_hold_count=0,
        )
        A.assert_cargo_state(fx.refresh_cargo(world, _STOWED_DG), status="LOADED")
        A.assert_cargo_state(fx.refresh_cargo(world, _STOWED_PLAIN), status="LOADED")

    def test_the_notoc_flag_follows_the_loaded_consignments_only(self):
        """Only declarations on consignments that were loaded get stamped notified.

        PRD: "Consignments left unstowed are untouched by acceptance and remain
        `ACCEPTED`."

        Design: Difficulty/transitive_cascade/sheet_accept_cascade_release_load_notoc
        """
        world = _issued_cascade_world()

        fx.accept_sheet(world, captain_headers(CAPTAIN_1))

        A.assert_declaration_state(
            fx.refresh_declaration(world, _STOWED_DG), status="ACCEPTED", notoc_issued=True
        )
        A.assert_cargo_state(fx.refresh_cargo(world, _UNSTOWED_DG), status="ACCEPTED")
        A.assert_declaration_state(
            fx.refresh_declaration(world, _UNSTOWED_DG), status="ACCEPTED", notoc_issued=False
        )

    def test_the_plan_figures_the_cascade_rests_on_are_the_issued_snapshot(self):
        """The cascade fires over the plan the sheet snapshotted, unaltered.

        PRD: "The **base payload** is then assembled from three collections and
        nothing else: every passenger line on the plan, contributing its
        `line_weight_kg`; every bag allocation on the plan, contributing its
        `effective_weight_kg`; and every consignment on the plan's flight whose
        `status` is `ACCEPTED` or `LOADED`, whose `assigned_compartment_id` is
        set, and whose `item_kind` is not `GATE_BAG`, contributing its
        `weight_kg`."

        Design: Difficulty/transitive_cascade/sheet_accept_cascade_release_load_notoc
        """
        world = _issued_cascade_world()
        A.assert_sheet_figures(world.sheet, issued_payload_kg=6800.00)

        fx.accept_sheet(world, captain_headers(CAPTAIN_1))

        A.assert_plan_figures(
            fx.refresh_plan(world),
            base_payload_kg=6800.00,
            index_zfw=83.98,
            mac_zfw_pct=16.39,
            takeoff_weight_kg=58900.00,
            mac_tow_pct=17.21,
        )


# ---------------------------------------------------------------------------
# Applying an offload: offload, recompute and advance in one call
# ---------------------------------------------------------------------------

_OFFLOAD_COMPANY = "724-77770001"
_OFFLOAD_GENERAL = "724-77770002"
_OFFLOAD_MAIL = "724-77770003"


def _restricted_world() -> fx.Scenario:
    return fx.s2_restricted_world(
        "PRIORITY_FIRST",
        scenario=fx.reference_world(band_specs=[F.CANONICAL_BANDS[1]]),
        awb_prefix="724-7777",
        flight_number="LX1632",
    )


class TestApplyOffloadCascade:
    def test_the_first_hop_offloads_the_selected_consignments_and_clears_their_hold(self):
        """Every selected consignment leaves the aircraft and loses its compartment.

        PRD: "First, each selected consignment transitions `ACCEPTED` →
        `OFFLOADED` with its `assigned_compartment_id` cleared and its own
        `version` incremented by 1."

        Design: Difficulty/transitive_cascade/apply_offload_cascade_plan_recompute_flight_load_controlled
        """
        world = _restricted_world()
        A.assert_plan_figures(
            world.plan,
            status="RESTRICTED",
            restriction_status="WEIGHT_RESTRICTED",
            base_payload_kg=20880.00,
            frozen_underload_kg=-700.00,
        )
        A.assert_flight_state(fx.refresh_flight(world), status="PLANNING")

        fx.apply_offload(world)

        A.assert_cargo_state(
            fx.refresh_cargo(world, _OFFLOAD_COMPANY),
            status="OFFLOADED",
            assigned_compartment_id=None,
        )
        A.assert_cargo_state(
            fx.refresh_cargo(world, _OFFLOAD_GENERAL),
            status="OFFLOADED",
            assigned_compartment_id=None,
        )
        A.assert_cargo_state(fx.refresh_cargo(world, _OFFLOAD_MAIL), status="ACCEPTED")

    def test_the_second_hop_recomputes_the_live_figures_and_leaves_the_frozen_ones(self):
        """The whole balance chain is re-run while the frozen posture stands.

        PRD: "Second, the plan's `planned_payload_kg` and `underload_kg` are
        refreshed from the surviving distribution and the entire index and
        percent-MAC chain is recomputed against it — with `frozen_underload_kg`
        and `restriction_status` left untouched, since those are frozen."

        Design: Difficulty/transitive_cascade/apply_offload_cascade_plan_recompute_flight_load_controlled
        """
        world = _restricted_world()

        fx.apply_offload(world)

        A.assert_plan_figures(
            world.plan,
            planned_payload_kg=18280.00,
            underload_kg=1900.00,
            index_zfw=92.30,
            mac_zfw_pct=16.56,
            zero_fuel_weight_kg=60830.00,
            takeoff_weight_kg=70380.00,
            index_tow=100.90,
            mac_tow_pct=17.22,
            envelope_ok=True,
            base_payload_kg=20880.00,
            frozen_underload_kg=-700.00,
            restriction_status="WEIGHT_RESTRICTED",
        )

    def test_the_third_hop_advances_the_plan_and_the_flight_together(self):
        """The restriction resolves: the plan computes and the flight takes control.

        PRD: "Third, the plan moves `RESTRICTED` → `COMPUTED` and the flight
        moves `PLANNING` → `LOAD_CONTROLLED`."

        Design: Difficulty/transitive_cascade/apply_offload_cascade_plan_recompute_flight_load_controlled
        """
        world = _restricted_world()

        fx.apply_offload(world)

        A.assert_plan_figures(world.plan, status="COMPUTED")
        A.assert_flight_state(fx.refresh_flight(world), status="LOAD_CONTROLLED")
