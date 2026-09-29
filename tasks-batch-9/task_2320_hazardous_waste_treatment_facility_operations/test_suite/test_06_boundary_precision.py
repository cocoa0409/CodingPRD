"""Values landing exactly on a regulatory boundary.

A lead residue measured exactly at its universal treatment standard, and a
storage unit crowded to exactly its free container capacity.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_cents,
    assert_mass,
    assert_one_decimal,
    fixtures,
)
from test_helpers.factories import container_payload, ldr_verification_payload
from test_helpers.test_users import COMPLIANCE_MANAGER_2_USER_ID


def _treated_lead_batch_awaiting_verification() -> fixtures.Scenario:
    """A 200.0 kg alkaline lead drum stabilised into 120.0 kg of residue, the
    batch sitting TREATED and awaiting its land-disposal-restriction signature."""
    return fixtures.setup_treated_batch(
        unit_overrides={"allowed_compatibility_classes": ["ALKALINE"]},
        profile_overrides={
            "waste_codes": ["D008"],
            "physical_form": "SOLID",
            "compatibility_class": "ALKALINE",
            "ldr_subcategory": "D008_LEAD",
            "requested_treatment_method": "STABILIZATION",
        },
        approved_treatment_method="STABILIZATION",
        treatment_method="STABILIZATION",
        container_overrides={"label_waste_codes": ["D008"], "label_hazard_class": "8"},
        net_weight_kg=200.0,
        declared_quantity_kg=500.0,
        declared_container_count=1,
        residue_mass_kg=120.0,
        residue_constituent_ppm=740.0,
    )


def _sign_verification_at_the_standard(scenario: fixtures.Scenario):
    """Sign the verification with a split sample reading exactly 750.0 ppm."""
    return api_client.verify_batch_ldr(
        scenario.batch["id"],
        ldr_verification_payload(750.0, verification_note="split sample at the standard"),
        TEST_USERS["compliance_manager_2"],
    )


def _unit_with_three_drums_below_its_free_capacity() -> fixtures.Scenario:
    """A container area surveyed at 78.0 cm with a free capacity of four drums,
    holding three drums drawn from a single 1250.5 kg receipt line. The unit read
    before any placement is kept as `empty_unit`."""
    scenario = fixtures.setup_received_manifest(
        unit_overrides={"aisle_width_cm": 78.0, "aisle_free_container_capacity": 4},
        declared_quantity_kg=1250.5,
        declared_container_count=5,
    )
    scenario.empty_unit = scenario.unit
    for _ in range(3):
        fixtures.place_container(scenario.line["id"], scenario.unit["id"], net_weight_kg=200.0)
    scenario.unit = fixtures.read_unit(scenario.unit["id"])
    return scenario


def _place_another_drum(scenario: fixtures.Scenario):
    return api_client.create_container(
        container_payload(scenario.line["id"], scenario.unit["id"], net_weight_kg=200.0),
        TEST_USERS["clerk"],
    )


class TestLeadResidueAtTheUniversalTreatmentStandard:
    def test_residue_exactly_at_seven_hundred_fifty_ppm_passes_verification(self):
        """A verification sample of exactly 750.0 ppm meets the lead standard and
        carries the batch to VERIFIED.

        PRD: "For the two concentration families, `ldr_standard_ppm` is set to the universal treatment standard — 750 ppm for `D008_LEAD` and 560 ppm for `F001_SOLVENTS` — and the result is a pass when `verification_sample_ppm` is at or below that standard and a failure otherwise, so a lead residue at exactly 750.0 ppm passes while one at 750.1 ppm fails."
        PRD: "A pass sets `ldr_result` to `PASS`, records `verified_by_user_id`, and advances the batch from `TREATED` to the terminal `VERIFIED`; the batch leaves the unit's `reserved_kg` and the facility's `active_treatment_liability_cents`."

        Design: Difficulty/boundary_precision_check/ldr_residue_exactly_at_uts_standard_passes
        """
        scenario = _treated_lead_batch_awaiting_verification()
        assert scenario.batch["status"] == "TREATED"

        verified = validate_success(_sign_verification_at_the_standard(scenario))
        assert_one_decimal(verified["ldr_standard_ppm"], 750.0, "ldr_standard_ppm")
        assert verified["ldr_result"] == "PASS"
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == COMPLIANCE_MANAGER_2_USER_ID

    def test_passing_verification_releases_reserve_and_splits_the_input_mass(self):
        """The verified batch leaves reserved mass and treatment liability behind,
        with the input mass already split into residue and destruction.

        PRD: "A pass sets `ldr_result` to `PASS`, records `verified_by_user_id`, and advances the batch from `TREATED` to the terminal `VERIFIED`; the batch leaves the unit's `reserved_kg` and the facility's `active_treatment_liability_cents`."
        PRD: "On the facility ledger, `treated_residue_kg` gains the reported `residue_mass_kg` and `destroyed_mass_kg` gains the input mass less the residue mass, so `mass_ledger_kg` is unchanged."
        PRD: "`reserved_kg` is the sum of `input_mass_kg` over the batches on the unit whose `status` is `PLANNED` or `IN_TREATMENT`, to 3 decimals."

        Design: Difficulty/boundary_precision_check/ldr_residue_exactly_at_uts_standard_passes
        """
        scenario = _treated_lead_batch_awaiting_verification()
        validate_success(_sign_verification_at_the_standard(scenario))

        unit = fixtures.read_unit(scenario.unit["id"])
        assert_mass(unit["reserved_kg"], 0.0, "reserved_kg")
        facility = fixtures.read_facility(scenario.facility["id"])
        assert_cents(
            facility["active_treatment_liability_cents"], 0, "active_treatment_liability_cents"
        )
        assert_mass(facility["treated_residue_kg"], 120.0, "treated_residue_kg")
        assert_mass(facility["destroyed_mass_kg"], 80.0, "destroyed_mass_kg")


class TestAisleClearanceAtTheFreeContainerCapacity:
    def test_empty_unit_and_fourth_drum_both_read_the_surveyed_width(self):
        """An empty unit reads its surveyed 78.0 cm with no extra credit, and the
        fourth drum is accepted while the width still reads 78.0 cm.

        PRD: "`effective_aisle_width_cm` is the surveyed `aisle_width_cm` reduced by 6 centimetres for each container beyond `aisle_free_container_capacity`, where that excess is taken as zero when the unit holds no more containers than its free capacity — so an empty unit reads its full surveyed width rather than being credited extra width."
        PRD: "A unit surveyed at 78 centimetres with a free capacity of four containers therefore reads 78 while empty and still reads 78 at four containers, but a fifth container would bring it to 72, so that fifth placement is refused."
        PRD: "A new container opens with `custody_state` of `FILLING`, `compliance_state` of `COMPLIANT`, `last_finding_code` null, and `treatment_batch_id` null."

        Design: Difficulty/boundary_precision_check/aisle_clearance_on_empty_unit_passes_with_zero_containers
        """
        scenario = _unit_with_three_drums_below_its_free_capacity()
        assert scenario.empty_unit["container_count"] == 0
        assert_one_decimal(
            scenario.empty_unit["effective_aisle_width_cm"], 78.0, "effective_aisle_width_cm"
        )

        fourth = validate_success(_place_another_drum(scenario), expected_status=201)
        assert fourth["custody_state"] == "FILLING"

        unit = fixtures.read_unit(scenario.unit["id"])
        assert unit["container_count"] == 4
        assert_one_decimal(unit["effective_aisle_width_cm"], 78.0, "effective_aisle_width_cm")

    def test_fifth_drum_is_refused_and_the_unit_stays_at_four_drums(self):
        """The fifth drum would drive the aisle to 72.0 cm, so it is refused and the
        unit keeps four drums and 800.0 kg.

        PRD: "A placement is refused when the effective width computed **with the candidate container included** would fall below 76 centimetres, which is the regulatory minimum; the rejection is `ERR_AISLE_CLEARANCE_VIOLATION`."
        PRD: "A unit surveyed at 78 centimetres with a free capacity of four containers therefore reads 78 while empty and still reads 78 at four containers, but a fifth container would bring it to 72, so that fifth placement is refused."
        PRD: "`stored_kg` is the sum of `net_weight_kg` over those same containers, to 3 decimals."

        Design: Difficulty/boundary_precision_check/aisle_clearance_on_empty_unit_passes_with_zero_containers
        """
        scenario = _unit_with_three_drums_below_its_free_capacity()
        validate_success(_place_another_drum(scenario), expected_status=201)

        validate_error(_place_another_drum(scenario), "ERR_AISLE_CLEARANCE_VIOLATION")

        unit = fixtures.read_unit(scenario.unit["id"])
        assert unit["container_count"] == 4
        assert_mass(unit["stored_kg"], 800.0, "stored_kg")
        assert_one_decimal(unit["effective_aisle_width_cm"], 78.0, "effective_aisle_width_cm")
