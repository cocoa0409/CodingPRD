"""Transitive contagion in the fastener plant: one write that walks several records.

This module covers the two chains the PRD describes where each link is caused by the
mutation the previous link performed rather than by the original request. The first is
the counterfeit chain of PRD §3.2, which runs from a suspected mill certificate through
the heat's wire lots, their production lots and those lots' certificates all the way to a
pack unit that already left the dock. The second is the heading-completion chain of PRD
§3.4, where advancing the die set's piece counter wears the set out and thereby freezes a
sibling lot still in setup on that same set — a lot the request never names.
"""

import pytest

from test_helpers import (
    assert_lot_piece_ledger,
    assert_versions_incremented,
    assert_wire_mass_ledger,
    fixtures,
    validate_success,
)


# ---------------------------------------------------------------------------
# Link-by-link propagation of a suspected counterfeit mill certificate
# ---------------------------------------------------------------------------
class TestCounterfeitHeatCascade:
    """One flag-counterfeit call, four chained links, a recalled shipped pack."""

    def test_flagging_the_heat_recalls_the_pack_four_links_downstream(
        self, api, manager_alt_headers
    ):
        """A shipped pack the request never names ends RECALLED with reason HEAT_COUNTERFEIT.

        PRD: "Flagging a heat whose `cert_status` is `PENDING` or `VERIFIED` moves it to `SUSPECTED_COUNTERFEIT`, records the supplied `reason` as `counterfeit_reason`, and fires the plant's longest chain — four links, each caused by the write the previous link performed rather than by the original request."

        PRD: "Link one: every wire lot of the heat in `status` `DRAWN` or `RELEASED` becomes `QUARANTINED` with `quarantine_source` of `HEAT_COUNTERFEIT`, in ascending `created_at` order."

        PRD: "Link two, caused by link one: every production lot whose wire lot was quarantined by link one and whose `process_state` is not `ABORTED` becomes `disposition` `QUARANTINED` with `hold_source` `HEAT_COUNTERFEIT`, in ascending `created_at` order."

        PRD: "Link three, caused by link two: every certificate of a lot quarantined by link two whose `status` is `DRAFT`, `ISSUED` or `REISSUE_PENDING` becomes `REVOKED` with `revoked_reason` recorded as `HEAT_COUNTERFEIT`, in ascending `created_at` order."

        PRD: "Link four, caused by link three: every pack unit printed with a certificate revoked by link three whose `status` is `SEALED` or `SHIPPED` becomes `RECALLED` with `recall_reason` recorded as `HEAT_COUNTERFEIT`, in ascending `created_at` order."

        Design: Difficulty/transitive_cascade/counterfeit_heat_cascades_four_links_to_recalled_pack_unit
        """
        env = fixtures.setup_shipped_pack(
            spec_overrides={"blank_mass_g": 20.0, "scrap_allowance_pct": 0.05},
        )
        heat_id = env["heat"]["id"]
        wire_id = env["wire"]["id"]
        lot_id = env["lot"]["id"]
        cert_id = env["certificate"]["id"]
        pack_id = env["pack"]["id"]

        # The whole chain is intact before the trigger.
        assert fixtures.read_heat(heat_id)["cert_status"] == "VERIFIED"
        assert fixtures.read_wire_lot(wire_id)["status"] == "RELEASED"
        assert fixtures.read_lot(lot_id)["disposition"] == "IN_PROCESS"
        assert fixtures.read_certificate(cert_id)["status"] == "ISSUED"
        assert fixtures.read_pack_unit(pack_id)["status"] == "SHIPPED"

        fixtures.set_clock("2026-09-02T12:00:00Z", manager_alt_headers)
        flagged = validate_success(
            api.flag_counterfeit(
                heat_id,
                {"reason": "MILL_CERT_SERIAL_NOT_ON_MILL_REGISTER"},
                manager_alt_headers,
            )
        )

        assert flagged["cert_status"] == "SUSPECTED_COUNTERFEIT", (
            f"Expected SUSPECTED_COUNTERFEIT, got {flagged['cert_status']} after flagging"
        )
        assert flagged["counterfeit_reason"] == "MILL_CERT_SERIAL_NOT_ON_MILL_REGISTER", (
            "The supplied reason must be recorded as counterfeit_reason, got "
            f"{flagged['counterfeit_reason']}"
        )

        wire = fixtures.read_wire_lot(wire_id)
        assert wire["status"] == "QUARANTINED", (
            f"Link one must quarantine the RELEASED wire lot, got {wire['status']}"
        )
        assert wire["quarantine_source"] == "HEAT_COUNTERFEIT", (
            f"Expected quarantine_source HEAT_COUNTERFEIT, got {wire['quarantine_source']}"
        )

        lot = fixtures.read_lot(lot_id)
        assert lot["disposition"] == "QUARANTINED", (
            f"Link two must quarantine the production lot, got {lot['disposition']}"
        )
        assert lot["hold_source"] == "HEAT_COUNTERFEIT", (
            f"Expected hold_source HEAT_COUNTERFEIT, got {lot['hold_source']}"
        )

        cert = fixtures.read_certificate(cert_id)
        assert cert["status"] == "REVOKED", (
            f"Link three must revoke the ISSUED certificate, got {cert['status']}"
        )
        assert cert["revoked_reason"] == "HEAT_COUNTERFEIT", (
            f"Expected revoked_reason HEAT_COUNTERFEIT, got {cert['revoked_reason']}"
        )

        pack = fixtures.read_pack_unit(pack_id)
        assert pack["status"] == "RECALLED", (
            f"Link four must recall the SHIPPED pack unit, got {pack['status']}"
        )
        assert pack["recall_reason"] == "HEAT_COUNTERFEIT", (
            f"Expected recall_reason HEAT_COUNTERFEIT, got {pack['recall_reason']}"
        )

    def test_counterfeit_cascade_increments_the_version_of_every_record_it_touches(
        self, api, manager_alt_headers
    ):
        """Heat, wire lot, production lot, certificate and pack unit each advance by one.

        PRD: "The heat's `version` increments by 1, as does that of every wire lot, production lot, certificate and pack unit the chain touched."

        PRD: "Third, **every record a cascade mutates has its own `version` incremented and its `updated_at` refreshed**, exactly as if it had been written directly."

        Design: Difficulty/transitive_cascade/counterfeit_heat_cascades_four_links_to_recalled_pack_unit
        """
        env = fixtures.setup_shipped_pack(
            spec_overrides={"blank_mass_g": 20.0, "scrap_allowance_pct": 0.05},
        )
        heat_id = env["heat"]["id"]
        wire_id = env["wire"]["id"]
        lot_id = env["lot"]["id"]
        cert_id = env["certificate"]["id"]
        pack_id = env["pack"]["id"]

        heat_before = fixtures.read_heat(heat_id)
        wire_before = fixtures.read_wire_lot(wire_id)
        lot_before = fixtures.read_lot(lot_id)
        cert_before = fixtures.read_certificate(cert_id)
        pack_before = fixtures.read_pack_unit(pack_id)

        fixtures.set_clock("2026-09-02T12:00:00Z", manager_alt_headers)
        validate_success(
            api.flag_counterfeit(
                heat_id,
                {"reason": "MILL_CERT_SERIAL_NOT_ON_MILL_REGISTER"},
                manager_alt_headers,
            )
        )

        assert_versions_incremented(heat_before, fixtures.read_heat(heat_id))
        assert_versions_incremented(wire_before, fixtures.read_wire_lot(wire_id))
        assert_versions_incremented(lot_before, fixtures.read_lot(lot_id))
        assert_versions_incremented(cert_before, fixtures.read_certificate(cert_id))
        assert_versions_incremented(pack_before, fixtures.read_pack_unit(pack_id))

        pack_after = fixtures.read_pack_unit(pack_id)
        assert pack_after["updated_at"] != pack_before["updated_at"], (
            "A cascaded recall must refresh updated_at on the pack unit, got "
            f"{pack_after['updated_at']} unchanged"
        )

    def test_link_two_freezes_a_sibling_lot_while_the_shipped_lot_keeps_its_route(
        self, api, manager_alt_headers
    ):
        """Both lots drawing the quarantined wire freeze; the shipped one keeps its packed pieces.

        PRD: "Link two, caused by link one: every production lot whose wire lot was quarantined by link one and whose `process_state` is not `ABORTED` becomes `disposition` `QUARANTINED` with `hold_source` `HEAT_COUNTERFEIT`, in ascending `created_at` order."

        PRD: "Recalled pieces do not come back into inventory: the lot's `packed_count` is left exactly as it was, because those pieces have left the lot for good."

        PRD: "For every wire lot, the mass received from the mill equals the mass still free, plus the mass reserved by lots in setup, plus the mass already burned into blanks: `gross_mass_kg` equals `available_mass_kg` plus `reserved_mass_kg` plus `consumed_mass_kg`."

        Design: Difficulty/transitive_cascade/counterfeit_heat_cascades_four_links_to_recalled_pack_unit
        """
        env = fixtures.setup_shipped_pack(
            spec_overrides={"blank_mass_g": 20.0, "scrap_allowance_pct": 0.05},
        )
        heat_id = env["heat"]["id"]
        wire_id = env["wire"]["id"]
        shipped_lot_id = env["lot"]["id"]
        pack_id = env["pack"]["id"]

        # A second lot drawing the very same wire lot, still in SETUP and holding
        # nothing but a wire reservation. It is never named in the trigger payload.
        sibling = fixtures.open_production_lot(
            env["spec"]["id"],
            env["wire"]["id"],
            env["tool"]["id"],
            press_code=env["press_code"],
            lot_code="L-2602",
            planned_pieces=1000,
            press_window_start_at="2026-09-01T11:00:00Z",
            press_window_end_at="2026-09-01T15:00:00Z",
        )
        assert sibling["process_state"] == "SETUP", (
            f"The sibling lot must start in SETUP, got {sibling['process_state']}"
        )

        packed_before = fixtures.read_lot(shipped_lot_id)["packed_count"]
        declared_count = fixtures.read_pack_unit(pack_id)["declared_count"]
        assert packed_before == declared_count, (
            f"Expected packed_count {declared_count}, got {packed_before} after shipment"
        )

        fixtures.set_clock("2026-09-02T12:00:00Z", manager_alt_headers)
        validate_success(
            api.flag_counterfeit(
                heat_id,
                {"reason": "MILL_CERT_SERIAL_NOT_ON_MILL_REGISTER"},
                manager_alt_headers,
            )
        )

        sibling_after = fixtures.read_lot(sibling["id"])
        assert sibling_after["disposition"] == "QUARANTINED", (
            "Link two must reach the sibling lot on the same wire, got "
            f"{sibling_after['disposition']}"
        )
        assert sibling_after["hold_source"] == "HEAT_COUNTERFEIT", (
            f"Expected hold_source HEAT_COUNTERFEIT, got {sibling_after['hold_source']}"
        )
        assert sibling_after["process_state"] == "SETUP", (
            "The cascade moves only the disposition dimension, got process_state "
            f"{sibling_after['process_state']}"
        )

        shipped_after = fixtures.read_lot(shipped_lot_id)
        assert shipped_after["disposition"] == "QUARANTINED", (
            f"Expected QUARANTINED, got {shipped_after['disposition']} on the shipped lot"
        )
        assert shipped_after["process_state"] == "SHIPPED", (
            "The counterfeit chain leaves the process dimension alone, got "
            f"{shipped_after['process_state']}"
        )
        assert shipped_after["packed_count"] == packed_before, (
            f"Expected packed_count {packed_before}, got {shipped_after['packed_count']} "
            "after the pack was recalled"
        )
        assert_lot_piece_ledger(shipped_after)
        assert_wire_mass_ledger(fixtures.read_wire_lot(wire_id))


# ---------------------------------------------------------------------------
# Heading completion: piece counter -> worn die set -> held sibling lot
# ---------------------------------------------------------------------------
class TestHeadingCompletionToolWearCascade:
    """Reporting heading on one lot walks the counter, the die set and a sibling lot."""

    @staticmethod
    def _two_lots_on_one_nearly_spent_die_set():
        """Die set rated 5985 pieces on PRESS-5 with L-2620 (5700) and L-2621 (3000).

        Both lots sit in ``SETUP`` / ``IN_PROCESS`` and L-2620 is created first, so
        L-2620's report is exactly the write that exhausts the set under L-2621.
        """
        env = fixtures.setup_master_data(
            clock="2026-09-01T06:00:00Z",
            spec_overrides={"blank_mass_g": 20.0, "scrap_allowance_pct": 0.05},
            wire_overrides={"gross_mass_kg": 500.0},
            tool_overrides={"tool_code": "DIE-1S-777", "rated_life_pieces": 5985},
            press_code="PRESS-5",
        )
        env["lot_a"] = fixtures.open_production_lot(
            env["spec"]["id"],
            env["wire"]["id"],
            env["tool"]["id"],
            press_code="PRESS-5",
            lot_code="L-2620",
            planned_pieces=5700,
            press_window_start_at="2026-09-01T06:00:00Z",
            press_window_end_at="2026-09-01T10:00:00Z",
        )
        env["lot_b"] = fixtures.open_production_lot(
            env["spec"]["id"],
            env["wire"]["id"],
            env["tool"]["id"],
            press_code="PRESS-5",
            lot_code="L-2621",
            planned_pieces=3000,
            press_window_start_at="2026-09-01T11:00:00Z",
            press_window_end_at="2026-09-01T15:00:00Z",
        )
        return env

    def test_heading_completion_wears_the_set_and_holds_the_sibling_setup_lot(
        self, api, engineer_headers
    ):
        """5985 pieces exhaust the derated nameplate, so L-2621 lands on TOOL_WEAR hold.

        PRD: "The first cascade link advances the die set: `cumulative_pieces_current_cycle` grows by the sum of the two reported counts and `lifetime_pieces` is recomputed."

        PRD: "The second cascade link is caused by the first: if `cumulative_pieces_current_cycle` has reached or passed `rated_derated_life_pieces`, the set transitions `MOUNTED → WORN`."

        PRD: "The third link is caused by the second: every other production lot on that set still in `process_state` `SETUP` moves to `disposition` `HOLD` with `hold_source` `TOOL_WEAR`, in ascending `created_at` order."

        PRD: "The counter-driven route fires automatically when heading completion pushes `cumulative_pieces_current_cycle` to or past `rated_derated_life_pieces`: `status` becomes `WORN`, `mounted_press_code` is cleared, `condemn_reason` stays empty because no operator gave a reason, and every *other* production lot queued on that set whose `process_state` is `SETUP` moves, in ascending `created_at` order, to `disposition` of `HOLD` with `hold_source` of `TOOL_WEAR`."

        Design: Difficulty/transitive_cascade/heading_completion_wears_tool_and_holds_sibling_setup_lot
        """
        env = self._two_lots_on_one_nearly_spent_die_set()
        tool_before = fixtures.read_tool(env["tool"]["id"])
        assert tool_before["rated_derated_life_pieces"] == 5985, (
            "A fresh set with no regrinds offers its full nameplate, expected 5985, got "
            f"{tool_before['rated_derated_life_pieces']}"
        )
        assert tool_before["status"] == "MOUNTED", (
            f"Expected MOUNTED before the report, got {tool_before['status']}"
        )

        lot_a_after = validate_success(
            api.complete_heading(
                env["lot_a"]["id"],
                {"headed_count": 5900, "heading_scrap_count": 85},
                engineer_headers,
            )
        )

        # Link one: the piece counter.
        tool_after = fixtures.read_tool(env["tool"]["id"])
        assert tool_after["cumulative_pieces_current_cycle"] == 5985, (
            "Expected 5985 pieces in the open cycle, got "
            f"{tool_after['cumulative_pieces_current_cycle']}"
        )
        assert tool_after["lifetime_pieces"] == 5985, (
            f"Expected lifetime_pieces 5985, got {tool_after['lifetime_pieces']}"
        )

        # Link two: the die set wears out.
        assert tool_after["status"] == "WORN", (
            f"Expected WORN once the derated budget is reached, got {tool_after['status']}"
        )
        assert tool_after["mounted_press_code"] in (None, ""), (
            f"mounted_press_code must be cleared, got {tool_after['mounted_press_code']!r}"
        )
        assert tool_after["condemn_reason"] in (None, ""), (
            "condemn_reason stays empty on the counter-driven route, got "
            f"{tool_after['condemn_reason']!r}"
        )

        # Link three: the sibling lot nobody named.
        lot_b_after = fixtures.read_lot(env["lot_b"]["id"])
        assert lot_b_after["disposition"] == "HOLD", (
            f"Expected the sibling lot on HOLD, got {lot_b_after['disposition']}"
        )
        assert lot_b_after["hold_source"] == "TOOL_WEAR", (
            f"Expected hold_source TOOL_WEAR, got {lot_b_after['hold_source']}"
        )
        assert lot_b_after["process_state"] == "SETUP", (
            "The hold does not move the sibling along its process route, got "
            f"{lot_b_after['process_state']}"
        )

        # The reporting lot itself is not the "other" lot, so it stays in process.
        assert lot_a_after["process_state"] == "HEADED", (
            f"Expected HEADED, got {lot_a_after['process_state']} on the reporting lot"
        )
        assert lot_a_after["disposition"] == "IN_PROCESS", (
            f"Expected IN_PROCESS, got {lot_a_after['disposition']} on the reporting lot"
        )
        assert lot_a_after["available_count"] == 5900, (
            f"Expected available_count 5900, got {lot_a_after['available_count']}"
        )
        assert lot_a_after["headed_count"] == 5900, (
            f"Expected headed_count 5900, got {lot_a_after['headed_count']}"
        )
        assert lot_a_after["heading_scrap_count"] == 85, (
            f"Expected heading_scrap_count 85, got {lot_a_after['heading_scrap_count']}"
        )
        assert_lot_piece_ledger(lot_a_after)

    def test_utilisation_snapshot_and_wire_ledger_settle_around_the_worn_set(
        self, api, engineer_headers
    ):
        """The reporting lot snapshots 100.00 percent wear; the sibling keeps its reservation.

        PRD: "The lot then snapshots its own wear picture as `tool_utilization_pct`, which is 100 multiplied by the set's new `cumulative_pieces_current_cycle`, divided by its `rated_derated_life_pieces`, rounded half up to two decimal places — note that wear is always measured against the *rated derated* budget, never against the conservative one, whatever the part's qualification programme."

        PRD: "The wire ledger settles: the actually consumed mass is the sum of the two reported counts multiplied by `blank_mass_g`, divided by 1000, rounded half up to three decimal places; the lot's original `wire_reserved_kg` is subtracted from the wire lot's `reserved_mass_kg`, the consumed mass is added to `consumed_mass_kg`, and the difference between the reservation and the consumption is added back to `available_mass_kg` — which will be negative when the lot over-consumed."

        PRD: "The consumed mass is stored as `wire_consumed_kg` and `wire_reserved_kg` drops to zero."

        Design: Difficulty/transitive_cascade/heading_completion_wears_tool_and_holds_sibling_setup_lot
        """
        env = self._two_lots_on_one_nearly_spent_die_set()

        lot_a_after = validate_success(
            api.complete_heading(
                env["lot_a"]["id"],
                {"headed_count": 5900, "heading_scrap_count": 85},
                engineer_headers,
            )
        )

        assert lot_a_after["tool_utilization_pct"] == pytest.approx(100.00, abs=0.001), (
            "Expected tool_utilization_pct 100.00 at 5985 of 5985 derated pieces, got "
            f"{lot_a_after['tool_utilization_pct']}"
        )
        assert lot_a_after["wire_consumed_kg"] == pytest.approx(119.700, abs=0.001), (
            f"Expected wire_consumed_kg 119.700, got {lot_a_after['wire_consumed_kg']}"
        )
        assert lot_a_after["wire_reserved_kg"] == pytest.approx(0.0, abs=0.001), (
            f"wire_reserved_kg must drop to zero, got {lot_a_after['wire_reserved_kg']}"
        )

        wire = fixtures.read_wire_lot(env["wire"]["id"])
        assert wire["consumed_mass_kg"] == pytest.approx(119.700, abs=0.001), (
            f"Expected consumed_mass_kg 119.700, got {wire['consumed_mass_kg']}"
        )
        assert wire["reserved_mass_kg"] == pytest.approx(63.000, abs=0.001), (
            "The held sibling lot keeps its 63.000 kg reservation, got "
            f"{wire['reserved_mass_kg']}"
        )
        assert wire["available_mass_kg"] == pytest.approx(317.300, abs=0.001), (
            f"Expected available_mass_kg 317.300, got {wire['available_mass_kg']}"
        )
        assert_wire_mass_ledger(wire)

    def test_the_wear_chain_versions_the_reporting_lot_wire_set_and_held_sibling(
        self, api, engineer_headers
    ):
        """Four records advance by one version: the lot, its wire, the set, the held sibling.

        PRD: "The lot's `version`, the wire lot's `version` and the die set's `version` each increment by 1, plus the `version` of every lot put on hold."

        PRD: "A derived-field refresh counts as a mutation: when a heading completion snapshots `tool_utilization_pct` onto a lot and advances the die set's life counter, both the lot and the die set have their `version` incremented and their `updated_at` refreshed."

        Design: Difficulty/transitive_cascade/heading_completion_wears_tool_and_holds_sibling_setup_lot
        """
        env = self._two_lots_on_one_nearly_spent_die_set()

        lot_a_before = fixtures.read_lot(env["lot_a"]["id"])
        lot_b_before = fixtures.read_lot(env["lot_b"]["id"])
        wire_before = fixtures.read_wire_lot(env["wire"]["id"])
        tool_before = fixtures.read_tool(env["tool"]["id"])

        # `updated_at` is refreshed *from the logical clock*, so the refresh is only
        # observable once the clock has moved on from the setup instant.
        fixtures.set_clock("2026-09-01T07:30:00Z", engineer_headers)

        validate_success(
            api.complete_heading(
                env["lot_a"]["id"],
                {"headed_count": 5900, "heading_scrap_count": 85},
                engineer_headers,
            )
        )

        assert_versions_incremented(lot_a_before, fixtures.read_lot(env["lot_a"]["id"]))
        assert_versions_incremented(wire_before, fixtures.read_wire_lot(env["wire"]["id"]))
        assert_versions_incremented(tool_before, fixtures.read_tool(env["tool"]["id"]))
        assert_versions_incremented(lot_b_before, fixtures.read_lot(env["lot_b"]["id"]))

        tool_after = fixtures.read_tool(env["tool"]["id"])
        assert tool_after["updated_at"].startswith("2026-09-01T07:30:00"), (
            "Advancing the die set's life counter must refresh its updated_at from the "
            f"logical clock, expected 2026-09-01T07:30:00, got {tool_after['updated_at']}"
        )
