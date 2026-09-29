"""Two multi-step money formulas whose step order is normative: the bond
obligation of a filing, and the processing fee of a mitigation petition."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories
from test_helpers.assertions import (
    assert_bond_amounts,
    assert_field,
    assert_ledger_entry,
    assert_money,
    assert_petition_offer,
)
from test_helpers.fixtures import (
    M1_OBLIGATION,
    build_registered_world,
)

HEAVY_CONSIGNMENT = {
    "cargo_value": 3900.00,
    "gross_weight_kg": 100.00,
    "package_count": 4,
}


class TestObligationComponentRounding:
    """Each of the three obligation components is rounded to cents before the
    sum, and the subtotal is never rounded again."""

    def test_obligation_rounds_each_component_before_adding_them(self, client):
        """1,234.60 of cargo, 100.28 kg and 3 packages produce 40.12 + 1.25 + 0.38
        = 41.75; rounding a deferred total of 41.755 would give 41.76 instead.

        PRD: "Those three already-rounded figures are summed, and the subtotal is **not** rounded again."

        Design: Difficulty/combinatorial_formula/obligation_rounds_each_component_before_summing
        """
        world = build_registered_world(client)

        response = client.file_movement(
            factories.movement_payload(
                world.carrier_id,
                world.ports["ny"],
                world.ports["chicago"],
                "MAN-0001",
                bond_id=world.bond_id,
            ),
            world.carrier,
        )
        movement = validate_success(response, 201)

        assert_money(
            movement["obligation_amount"], M1_OBLIGATION, "movement obligation_amount"
        )
        assert movement["obligation_amount"] != 41.76, (
            "41.76 is the figure produced by rounding the total once instead of "
            "rounding each component first"
        )

    def test_the_computed_obligation_is_what_charges_the_bond(self, client):
        """The same 41.75 is what the OBLIGATE ledger entry carries and what the
        bond's obligated and available amounts are replayed from.

        PRD: "It appends a ledger entry of type `OBLIGATE` for the full positive `obligation_amount` with `reason_code` `MOVEMENT_FILED`, and that entry recomputes the bond's `obligated_amount`, `available_amount`, and `open_movement_count` and re-derives the bond's `status`, which becomes `SATURATED` when the headroom has fallen to 0.00 or below."

        Design: Difficulty/combinatorial_formula/obligation_rounds_each_component_before_summing
        """
        world = build_registered_world(client)
        world.file_movement("MAN-0001")

        bond = world.read_bond()
        assert_bond_amounts(
            bond,
            obligated=M1_OBLIGATION,
            available=49958.25,
            status="ACTIVE",
            open_movement_count=1,
        )

        entries = world.ledger_entries(bond_id=world.bond_id)
        assert len(entries) == 1, (
            f"a single filing should write exactly one ledger entry but the audit "
            f"trail holds {len(entries)}"
        )
        assert_ledger_entry(
            entries[0],
            entry_type="OBLIGATE",
            amount=M1_OBLIGATION,
            balance_after=M1_OBLIGATION,
            reason_code="MOVEMENT_FILED",
        )


class TestProcessingFeeTierSelection:
    """The processing-fee tier is chosen on the pre-fee net and never
    re-selected once the fee has moved the number."""

    def test_heavier_consignment_obligation_and_capped_assessment(self, client):
        """3,900.00 of cargo, 100.00 kg and 4 packages obligate 128.51, and a
        twenty-day late arrival assesses 3,900.00 because the cargo value caps the
        5,000.00 raw figure.

        PRD: "A cap is then taken as the lesser of the movement's `cargo_value` and the underwriting bond's `limit_amount`, and `assessed_amount` is the lesser of the raw assessment and that cap, rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/mitigation_fee_tier_selected_on_pre_fee_net_only
        """
        world = build_registered_world(client)
        movement_id = world.file_movement("MAN-0002", **HEAVY_CONSIGNMENT)
        assert_money(
            world.read_movement(movement_id)["obligation_amount"],
            128.51,
            "movement obligation_amount",
        )

        world.depart(movement_id, "SEAL-200")
        world.set_clock("2026-09-25T00:00:00Z")
        world.report_arrival(movement_id, packages_reported=4)

        claim = world.issue_claim(movement_id, "LATE_ARRIVAL", "OVERDUE_ARRIVAL")
        assert_field(claim, "overdue_days_at_issue", 20, "claim")
        assert_money(claim["assessed_amount"], 3900.00, "claim assessed_amount")

    def test_fee_tier_is_read_off_the_net_before_the_fee_is_added(self, client):
        """A net of 1,950.00 sits below 2,000.00 and draws the flat 100.00 fee, so
        the offer is 2,050.00; re-reading the tier off 2,050.00 would draw 250.00
        and yield 2,200.00.

        PRD: "The tier is never re-selected after the fee has changed the number."

        Design: Difficulty/combinatorial_formula/mitigation_fee_tier_selected_on_pre_fee_net_only
        """
        world = build_registered_world(client)
        movement_id = world.file_movement("MAN-0002", **HEAVY_CONSIGNMENT)
        world.depart(movement_id, "SEAL-200")
        world.set_clock("2026-09-25T00:00:00Z")
        world.report_arrival(movement_id, packages_reported=4)
        claim = world.issue_claim(movement_id, "LATE_ARRIVAL", "OVERDUE_ARRIVAL")

        petition = validate_success(
            client.file_petition(
                factories.petition_payload(
                    claim["id"],
                    claim["version"],
                    factories.FOUR_FACTOR_MITIGATION,
                    "PET-0002",
                ),
                world.carrier,
            ),
            201,
        )

        assert_petition_offer(
            petition,
            mitigation_pct=0.50,
            net_before_fee=1950.00,
            processing_fee=100.00,
            offer_amount=2050.00,
            prior_violation_count=0,
            petition_round=1,
        )
        assert petition["offer_amount"] != 2200.00, (
            "2,200.00 is the offer produced by re-selecting the fee tier after the "
            "fee has been added to the net"
        )
