"""Acceptance charge arithmetic at the receiving dock.

Three charge behaviours are exercised here: the provisional charge frozen when
the truck is weighed in, the final charge frozen when the manifest is certified,
and the money conservation that follows when a whole shipment is handed back to
the transporter. Every precondition is built through the documented endpoints
against the logical clock, which reads 2026-08-01T00:00:00Z at the start of
each test.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_cents,
    assert_mass,
    assert_mass_ledger_balances,
)
from test_helpers.factories import (
    discrepancy_resolution_payload,
    manifest_line_payload,
    receipt_line,
    receive_payload,
)
from test_helpers.test_users import TEST_USERS

# ─── A short-weighed bulk shipment ────────────────────────────────────────────
# A BULK_LIQUID / ORGANIC_SOLVENT profile with no land disposal restriction
# family prices at 40 x 1.20 = 48 cents per kilogram.
DECLARED_KG = 1500.0
RECEIVED_KG = 1250.5
ACCEPTED_KG = 1180.0
RECEIVED_CONTAINERS = 5
# 1250.5 kg x 48 cents = 60024 cents, plus five handling fees of 750 cents.
PROVISIONAL_CHARGE_CENTS = 63_774
# 1180.0 kg x 48 cents = 56640 cents, plus the same five handling fees.
FINAL_CHARGE_CENTS = 60_390
CHARGE_ADJUSTMENT_CENTS = FINAL_CHARGE_CENTS - PROVISIONAL_CHARGE_CENTS  # -3384


def _bulk_shipment_awaiting_receipt(tracking_number: str = "MTN0000001"):
    """A funded facility, an ACTIVE generator, an APPROVED bulk liquid profile
    and a single-line manifest of 1500.0 kg still EN_ROUTE."""
    fixtures.set_clock()
    facility, instrument = fixtures.create_funded_facility()
    generator = fixtures.create_generator()
    profile = fixtures.create_approved_profile(
        generator["id"],
        facility["id"],
        profile_overrides={"physical_form": "BULK_LIQUID"},
    )
    manifest = fixtures.create_manifest(
        generator["id"],
        facility["id"],
        lines=[manifest_line_payload(profile["id"], DECLARED_KG, RECEIVED_CONTAINERS, True)],
        manifest_tracking_number=tracking_number,
    )
    return fixtures.Scenario(
        facility=facility,
        instrument=instrument,
        generator=generator,
        profile=profile,
        manifest=manifest,
    )


def _short_receipt_resolved_by_adjustment():
    """The same shipment weighed in short at 1250.5 kg and then resolved by
    adjusting the accepted quantity down to 1180.0 kg."""
    scenario = _bulk_shipment_awaiting_receipt()
    fixtures.receive_manifest(
        scenario.manifest["id"],
        [receipt_line(1, RECEIVED_KG, RECEIVED_CONTAINERS)],
    )
    fixtures.resolve_discrepancy(
        scenario.manifest["id"],
        "ACCEPT_ADJUSTED",
        adjusted_lines=[{"line_number": 1, "accepted_quantity_kg": ACCEPTED_KG}],
    )
    return scenario


class TestProvisionalAndFinalAcceptanceCharge:
    def test_receipt_freezes_the_provisional_charge_on_the_weighed_quantity(self):
        """Weighing in 1250.5 kg against 1500.0 kg declared makes the shipment
        discrepant and prices the provisional charge off what was weighed.

        Otherwise, a line whose absolute variance reaches or exceeds its tolerance takes a `significance` of `QUANTITY_SIGNIFICANT`; the tolerance is 10 percent expressed as the fraction 0.10 for a bulk line and 2 percent expressed as the fraction 0.02 for a containerised one, and the comparison is inclusive, so a bulk line declared at 1000.0 kg and weighed at 900.0 kg reaches exactly 0.1000 and is significant, while the same line weighed at 905.0 kg yields 0.0950 and is not.
        Both use the same per-line arithmetic and differ only in which lines they include and which quantity they price.
        The **provisional** variant runs at receipt, includes every line whose `line_status` is `RECEIVED`, and prices each line's `received_quantity_kg`.
        Its per-line results are stored as each line's `provisional_line_charge_cents` and its total as the manifest's `provisional_charge_cents`, and that total is added to the offering generator's `open_charge_cents`.

        Design: Difficulty/dual_variant_calc/manifest_charge_provisional_vs_final_diverges
        """
        scenario = _bulk_shipment_awaiting_receipt()

        received = validate_success(
            api_client.receive_manifest(
                scenario.manifest["id"],
                receive_payload([receipt_line(1, RECEIVED_KG, RECEIVED_CONTAINERS)]),
                TEST_USERS["clerk"],
            )
        )

        assert received["status"] == "DISCREPANT"
        assert received["discrepancy_type"] == "QUANTITY_SIGNIFICANT"
        assert_cents(
            received["provisional_charge_cents"],
            PROVISIONAL_CHARGE_CENTS,
            "provisional_charge_cents",
        )

        line = fixtures.read_line(scenario.manifest["id"], 1)
        assert line["line_status"] == "RECEIVED"
        assert_cents(
            line["provisional_line_charge_cents"],
            PROVISIONAL_CHARGE_CENTS,
            "provisional_line_charge_cents",
        )

        generator = fixtures.read_generator(scenario.generator["id"])
        assert_cents(
            generator["open_charge_cents"], PROVISIONAL_CHARGE_CENTS, "open_charge_cents"
        )

    def test_certification_freezes_the_final_charge_on_the_accepted_quantity(self):
        """After the adjustment, the final variant of the same arithmetic prices
        1180.0 kg while the provisional figure stays frozen at what was weighed.

        **Acceptance charges** are frozen twice: provisionally at receipt and finally at certification.
        Under `ACCEPT_ADJUSTED`, every line currently `RECEIVED` moves to `ACCEPTED`, with `accepted_quantity_kg` taken from the matching `adjusted_lines` entry when one was supplied for that `line_number` and left at `received_quantity_kg` otherwise, and `returned_quantity_kg` set to the received quantity less the accepted quantity.
        The **final** variant runs at certification, includes every line whose `line_status` is `RECEIVED`, `ACCEPTED` or `ADJUSTED` — lines that ended up `RETURNED` are excluded entirely — and prices each line's `accepted_quantity_kg`.
        Its per-line results are stored as each line's `final_line_charge_cents` and its total as the manifest's `final_charge_cents`.
        It moves the manifest from `VERIFIED` to the terminal `CERTIFIED` and requires either that `discrepancy_type` be `NONE` or that `discrepancy_report_filed` already be true; otherwise it is refused with `ERR_DISCREPANCY_REPORT_OVERDUE`.

        Design: Difficulty/dual_variant_calc/manifest_charge_provisional_vs_final_diverges
        """
        scenario = _short_receipt_resolved_by_adjustment()

        certified = validate_success(
            api_client.certify_manifest(scenario.manifest["id"], {}, TEST_USERS["clerk"])
        )

        assert certified["status"] == "CERTIFIED"
        assert_cents(
            certified["provisional_charge_cents"],
            PROVISIONAL_CHARGE_CENTS,
            "provisional_charge_cents",
        )
        assert_cents(
            certified["final_charge_cents"], FINAL_CHARGE_CENTS, "final_charge_cents"
        )

        line = fixtures.read_line(scenario.manifest["id"], 1)
        assert line["line_status"] == "ACCEPTED"
        assert_mass(line["accepted_quantity_kg"], ACCEPTED_KG, "accepted_quantity_kg")
        assert_mass(line["returned_quantity_kg"], 70.5, "returned_quantity_kg")
        assert_cents(
            line["provisional_line_charge_cents"],
            PROVISIONAL_CHARGE_CENTS,
            "provisional_line_charge_cents",
        )
        assert_cents(
            line["final_line_charge_cents"], FINAL_CHARGE_CENTS, "final_line_charge_cents"
        )

    def test_certification_reconciles_the_generator_balances_across_both_variants(self):
        """The gap between the two variants of the same charge is exactly what
        the generator's adjustment balance records.

        Certification freezes the final charge as described above, moves every line whose `line_status` is `RECEIVED` or `ADJUSTED` to `ACCEPTED`, and reconciles the generator's balances in three moves: `open_charge_cents` falls by the manifest's `provisional_charge_cents`, `settled_charge_cents` rises by its `final_charge_cents`, and `charge_adjustment_cents` accumulates the final charge less the provisional charge — a figure that is negative whenever the facility accepted less than it weighed in.

        Design: Difficulty/dual_variant_calc/manifest_charge_provisional_vs_final_diverges
        """
        scenario = _short_receipt_resolved_by_adjustment()

        fixtures.certify_manifest(scenario.manifest["id"])

        generator = fixtures.read_generator(scenario.generator["id"])
        assert_cents(generator["open_charge_cents"], 0, "open_charge_cents")
        assert_cents(
            generator["settled_charge_cents"], FINAL_CHARGE_CENTS, "settled_charge_cents"
        )
        assert_cents(
            generator["charge_adjustment_cents"],
            CHARGE_ADJUSTMENT_CENTS,
            "charge_adjustment_cents",
        )
        assert_cents(generator["voided_charge_cents"], 0, "voided_charge_cents")


# ─── A two-line shipment that lands on half cents ─────────────────────────────
# Line 1: SOLID 30 x WATER_REACTIVE 1.45 = 43.50 cents per kilogram.
# Line 2: SLUDGE 55 x ACID 1.10 = 60.50 cents per kilogram.
LINE_1_KG = 23.0
LINE_2_KG = 33.0
# 23.0 x 43.50 = 1000.5 raw cents, rounded to 1001, plus one handling fee.
LINE_1_CHARGE_CENTS = 1_751
# 33.0 x 60.50 = 1996.5 raw cents, rounded to 1997, plus one handling fee.
LINE_2_CHARGE_CENTS = 2_747
MANIFEST_CHARGE_CENTS = LINE_1_CHARGE_CENTS + LINE_2_CHARGE_CENTS  # 4498
CHARGE_IF_ROUNDED_ONCE_CENTS = 4_497


def _two_line_shipment_awaiting_receipt():
    """A funded facility, an ACTIVE generator, two APPROVED profiles whose rates
    each land on a half cent, and a two-line manifest still EN_ROUTE."""
    fixtures.set_clock()
    facility, instrument = fixtures.create_funded_facility()
    generator = fixtures.create_generator()
    water_reactive_solid = fixtures.create_approved_profile(
        generator["id"],
        facility["id"],
        profile_overrides={
            "waste_codes": ["D003"],
            "physical_form": "SOLID",
            "compatibility_class": "WATER_REACTIVE",
            "ldr_subcategory": "NONE",
            "declared_constituent_ppm": 8000.0,
            "declared_flash_point_c": 90.0,
            "declared_ph": 9.0,
            "requested_treatment_method": "STABILIZATION",
        },
        sample_overrides={
            "measured_constituent_ppm": 8200.0,
            "measured_flash_point_c": 91.0,
            "measured_ph": 9.2,
        },
        approved_treatment_method="STABILIZATION",
    )
    acid_sludge = fixtures.create_approved_profile(
        generator["id"],
        facility["id"],
        profile_overrides={
            "waste_codes": ["D002"],
            "physical_form": "SLUDGE",
            "compatibility_class": "ACID",
            "ldr_subcategory": "NONE",
            "declared_constituent_ppm": 5000.0,
            "declared_flash_point_c": 95.0,
            "declared_ph": 2.0,
            "requested_treatment_method": "NEUTRALIZATION",
        },
        sample_overrides={
            "measured_constituent_ppm": 5100.0,
            "measured_flash_point_c": 95.0,
            "measured_ph": 2.1,
        },
        approved_treatment_method="NEUTRALIZATION",
    )
    manifest = fixtures.create_manifest(
        generator["id"],
        facility["id"],
        lines=[
            manifest_line_payload(water_reactive_solid["id"], LINE_1_KG, 1, False),
            manifest_line_payload(acid_sludge["id"], LINE_2_KG, 1, False),
        ],
        manifest_tracking_number="MTN0000010",
    )
    return fixtures.Scenario(
        facility=facility,
        instrument=instrument,
        generator=generator,
        manifest=manifest,
    )


class TestPerLineChargeRounding:
    def test_each_line_is_rounded_to_whole_cents_before_the_manifest_total(self):
        """Two lines that each price to a half cent settle at 4498 cents in
        total, one cent above what a single closing rounding would report.

        The line's charge is the priced quantity multiplied by that rate, rounded half up to whole cents, plus a container handling fee of 750 cents for each container in the line's `received_container_count`.
        The manifest total is the sum of those already-rounded per-line charges.
        **Per-line rounding happens before summation**: summing raw per-line values and rounding once at the end produces a different, incorrect total.
        A two-line manifest whose first line prices to 1000.5 raw cents and whose second prices to 1996.5 raw cents totals 4498 cents once each line is rounded and the two handling fees of 750 cents are added, whereas summing raw and rounding once would report 4497 — off by a cent.

        Design: Difficulty/combinatorial_formula/line_charge_rounds_per_line_then_sums
        """
        scenario = _two_line_shipment_awaiting_receipt()

        received = validate_success(
            api_client.receive_manifest(
                scenario.manifest["id"],
                receive_payload(
                    [receipt_line(1, LINE_1_KG, 1), receipt_line(2, LINE_2_KG, 1)]
                ),
                TEST_USERS["clerk"],
            )
        )

        assert_cents(
            received["provisional_charge_cents"],
            MANIFEST_CHARGE_CENTS,
            "provisional_charge_cents",
        )
        assert received["provisional_charge_cents"] != CHARGE_IF_ROUNDED_ONCE_CENTS

        lines = fixtures.read_lines(scenario.manifest["id"])
        assert [line["line_number"] for line in lines] == [1, 2]
        assert_cents(
            lines[0]["provisional_line_charge_cents"],
            LINE_1_CHARGE_CENTS,
            "line 1 provisional_line_charge_cents",
        )
        assert_cents(
            lines[1]["provisional_line_charge_cents"],
            LINE_2_CHARGE_CENTS,
            "line 2 provisional_line_charge_cents",
        )

    def test_the_rounded_line_total_is_what_reaches_the_generator_balance(self):
        """A shipment weighed exactly as declared verifies without discrepancy,
        and the already-rounded line total is what the generator now owes.

        When `discrepancy_type` computes to `NONE`, the manifest moves from `EN_ROUTE` to `VERIFIED`.
        The manifest total is the sum of those already-rounded per-line charges.
        Its per-line results are stored as each line's `provisional_line_charge_cents` and its total as the manifest's `provisional_charge_cents`, and that total is added to the offering generator's `open_charge_cents`.

        Design: Difficulty/combinatorial_formula/line_charge_rounds_per_line_then_sums
        """
        scenario = _two_line_shipment_awaiting_receipt()

        received = fixtures.receive_manifest(
            scenario.manifest["id"],
            [receipt_line(1, LINE_1_KG, 1), receipt_line(2, LINE_2_KG, 1)],
        )

        assert received["status"] == "VERIFIED"
        assert received["discrepancy_type"] == "NONE"

        generator = fixtures.read_generator(scenario.generator["id"])
        assert_cents(
            generator["open_charge_cents"], MANIFEST_CHARGE_CENTS, "open_charge_cents"
        )
        assert_cents(generator["settled_charge_cents"], 0, "settled_charge_cents")


def _discrepant_shipment_with_one_container():
    """The short-weighed bulk shipment with one 200.0 kg drum already filled
    from its receipt line and standing in an open container area."""
    return fixtures.setup_container_in_storage(
        profile_overrides={"physical_form": "BULK_LIQUID"},
        unit_overrides={
            "aisle_free_container_capacity": 20,
            "allowed_compatibility_classes": ["ORGANIC_SOLVENT"],
        },
        declared_quantity_kg=DECLARED_KG,
        declared_container_count=RECEIVED_CONTAINERS,
        is_bulk=True,
        received_quantity_kg=RECEIVED_KG,
        received_container_count=RECEIVED_CONTAINERS,
        net_weight_kg=200.0,
    )


class TestShipmentRejectionConservesTheGeneratorCharge:
    def test_reject_return_moves_the_provisional_charge_into_the_voided_balance(self):
        """Handing the whole shipment back neither forgives nor settles the
        provisional charge: it moves intact from the open to the voided balance.

        Choosing `REJECT_RETURN` sends the whole shipment back and is defined from two source statuses.
        From `DISCREPANT`, the clock must still be at or before `discrepancy_report_due_at`.
        Both source statuses move the manifest to the terminal `REJECTED_RETURNED` and fire the identical shipment rejection cascade of §2.10: every line moves to `RETURNED` with `accepted_quantity_kg` of zero and `returned_quantity_kg` equal to its received quantity; every container whose receipt line is one of those and whose custody is `FILLING` or `SEALED` becomes `VOIDED`; each storage unit that held a voided container recomputes its `container_count`, `stored_kg`, `effective_aisle_width_cm` and `posture`; and the generator's `open_charge_cents` falls by the manifest's `provisional_charge_cents` while its `voided_charge_cents` rises by the same amount.

        Design: Difficulty/compensating_invariant/manifest_reject_return_conserves_generator_charge_ledger
        """
        scenario = _discrepant_shipment_with_one_container()
        assert scenario.manifest["status"] == "DISCREPANT"

        returned = validate_success(
            api_client.resolve_manifest_discrepancy(
                scenario.manifest["id"],
                discrepancy_resolution_payload("REJECT_RETURN"),
                TEST_USERS["compliance_manager"],
            )
        )

        assert returned["status"] == "REJECTED_RETURNED"
        assert_cents(
            returned["provisional_charge_cents"],
            PROVISIONAL_CHARGE_CENTS,
            "provisional_charge_cents",
        )

        generator = fixtures.read_generator(scenario.generator["id"])
        assert_cents(generator["open_charge_cents"], 0, "open_charge_cents")
        assert_cents(
            generator["voided_charge_cents"],
            PROVISIONAL_CHARGE_CENTS,
            "voided_charge_cents",
        )
        assert_cents(generator["settled_charge_cents"], 0, "settled_charge_cents")
        assert_cents(generator["charge_adjustment_cents"], 0, "charge_adjustment_cents")

    def test_reject_return_returns_every_line_and_voids_the_drums_it_filled(self):
        """The mass side of the same hand-back: the line is returned in full,
        the drum drawn from it is voided, and the mass ledger still balances.

        Every line on the manifest is returned, every container drawn from those lines that is still in early custody is voided, and each storage unit that held a voided container recomputes its container count, stored mass, effective aisle width and posture.
        Voiding from either source has identical effects: the container's mass leaves its unit's `stored_kg` and leaves its line's `allocated_container_mass_kg`, so the mass returns to the facility's `unallocated_receipt_kg` and `mass_ledger_kg` does not move, while the facility's `closure_cost_estimate_cents` and `required_assurance_cents` are recomputed downward.
        Against that intake stand five destinations: `held_mass_kg`, the sum of `stored_kg` across the facility's storage units; `unallocated_receipt_kg`, the sum over those same lines of each line's `accepted_quantity_kg` less its `allocated_container_mass_kg`; `returned_mass_kg`, the sum of `returned_quantity_kg` over those lines; `treated_residue_kg`, the sum of `residue_mass_kg` over the facility's batches whose `status` is `TREATED`, `LDR_FAILED` or `VERIFIED`; and `destroyed_mass_kg`, the sum over those same batches of each batch's `input_mass_kg` less its `residue_mass_kg`.
        Sending a shipment back moves accepted mass into `returned_mass_kg` while voiding the containers, so `held_mass_kg` and `unallocated_receipt_kg` both fall by exactly what `returned_mass_kg` gains.
        `mass_ledger_kg` is the sum of those five destinations, and it must equal `received_mass_kg` after every operation, with no rounding drift.

        Design: Difficulty/compensating_invariant/manifest_reject_return_conserves_generator_charge_ledger
        """
        scenario = _discrepant_shipment_with_one_container()

        fixtures.resolve_discrepancy(scenario.manifest["id"], "REJECT_RETURN")

        line = fixtures.read_line(scenario.manifest["id"], 1)
        assert line["line_status"] == "RETURNED"
        assert_mass(line["accepted_quantity_kg"], 0.0, "accepted_quantity_kg")
        assert_mass(line["returned_quantity_kg"], RECEIVED_KG, "returned_quantity_kg")

        container = fixtures.read_container(scenario.container["id"])
        assert container["custody_state"] == "VOIDED"

        unit = fixtures.read_unit(scenario.unit["id"])
        assert unit["container_count"] == 0
        assert_mass(unit["stored_kg"], 0.0, "stored_kg")

        facility = fixtures.read_facility(scenario.facility["id"])
        assert_mass(facility["returned_mass_kg"], RECEIVED_KG, "returned_mass_kg")
        assert_mass(facility["held_mass_kg"], 0.0, "held_mass_kg")
        assert_mass(facility["unallocated_receipt_kg"], 0.0, "unallocated_receipt_kg")
        assert_mass(facility["received_mass_kg"], RECEIVED_KG, "received_mass_kg")
        assert_mass(facility["mass_ledger_kg"], RECEIVED_KG, "mass_ledger_kg")
        assert_mass_ledger_balances(facility)
