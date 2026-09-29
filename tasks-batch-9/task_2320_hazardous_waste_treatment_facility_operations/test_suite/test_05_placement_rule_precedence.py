"""Which rule reports a refused container placement when several would refuse it.

Two competing pairs are exercised at the receiving dock: a suspended storage unit
against an incompatible resident drum, and a lapsed recertification against an
underfunded closure obligation.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import TEST_USERS, api_client, assert_cents, assert_mass, fixtures
from test_helpers.factories import container_payload, manifest_line_payload, receipt_line


def _unit_suspended_by_a_condemned_acid_drum() -> fixtures.Scenario:
    """A container area permitted for acid and water-reactive waste that holds one
    condemned acid drum, plus a received line of water-reactive waste waiting to
    be drummed into that same unit."""
    fixtures.set_clock()
    facility, instrument = fixtures.create_funded_facility()
    generator = fixtures.create_generator()
    unit = fixtures.create_storage_unit(
        facility["id"],
        allowed_compatibility_classes=["ACID", "WATER_REACTIVE"],
        aisle_free_container_capacity=20,
    )
    acid_profile = fixtures.create_approved_profile(
        generator["id"],
        facility["id"],
        profile_overrides={
            "waste_codes": ["D002"],
            "physical_form": "SLUDGE",
            "compatibility_class": "ACID",
        },
    )
    reactive_profile = fixtures.create_approved_profile(
        generator["id"],
        facility["id"],
        profile_overrides={
            "waste_codes": ["D003"],
            "physical_form": "SOLID",
            "compatibility_class": "WATER_REACTIVE",
        },
    )
    manifest = fixtures.create_manifest(
        generator["id"],
        facility["id"],
        lines=[
            manifest_line_payload(acid_profile["id"], 400.0, 1, False),
            manifest_line_payload(reactive_profile["id"], 400.0, 1, False),
        ],
    )
    fixtures.receive_manifest(
        manifest["id"], [receipt_line(1, 400.0, 1), receipt_line(2, 400.0, 1)]
    )
    lines = fixtures.read_lines(manifest["id"])
    acid_drum = fixtures.place_container(
        lines[0]["id"],
        unit["id"],
        net_weight_kg=200.0,
        label_waste_codes=["D002"],
        label_hazard_class="8",
    )
    fixtures.set_container_compliance(acid_drum["id"], "CONDEMNED", "CONTAINER_LEAK")
    return fixtures.Scenario(
        facility=fixtures.read_facility(facility["id"]),
        instrument=instrument,
        generator=generator,
        unit=fixtures.read_unit(unit["id"]),
        acid_profile=acid_profile,
        reactive_profile=reactive_profile,
        acid_drum=fixtures.read_container(acid_drum["id"]),
        reactive_line=lines[1],
    )


def _place_water_reactive_drum(scenario: fixtures.Scenario):
    """Attempt the water-reactive placement into the suspended unit."""
    return api_client.create_container(
        container_payload(
            scenario.reactive_line["id"],
            scenario.unit["id"],
            net_weight_kg=200.0,
            label_waste_codes=["D003"],
            label_hazard_class="4.3",
        ),
        TEST_USERS["clerk"],
    )


def _expired_profile_over_an_underfunded_facility() -> fixtures.Scenario:
    """A shipment received while assurance was ample, then stripped back to a
    1,000,000-cent instrument, with the clock carried past the profile's
    recertification date."""
    scenario = fixtures.setup_received_manifest(
        profile_overrides={"recertification_months": 1},
        declared_quantity_kg=1250.5,
        declared_container_count=5,
        unit_overrides={"aisle_free_container_capacity": 20},
    )
    fixtures.post_instrument(
        scenario.facility["id"],
        face_amount_cents=1_000_000,
        instrument_type="LETTER_OF_CREDIT",
        effective_on="2026-08-15",
    )
    fixtures.set_clock("2026-09-02T00:00:00Z")
    return scenario


def _place_drum_under_lapsed_profile(scenario: fixtures.Scenario):
    return api_client.create_container(
        container_payload(
            scenario.line["id"],
            scenario.unit["id"],
            net_weight_kg=200.0,
            accumulation_start_date="2026-09-02T00:00:00Z",
        ),
        TEST_USERS["clerk"],
    )


class TestSuspendedUnitOutranksIncompatibleContents:
    def test_suspended_posture_reports_itself_before_the_segregation_table(self):
        """A water-reactive drum offered to a unit that is suspended by a condemned
        acid resident is refused for posture, not for segregation.

        PRD: "All validations are evaluated in ascending priority order and **the first violated rule wins**; no later rule may mask an earlier one, and no earlier rule may be skipped because a later one would also fail."
        PRD: "**Unit posture.** The target storage unit's `posture` permits the operation: container placement requires `OPEN` or `RESTRICTED`, while treatment batch creation and treatment start require `OPEN` — `ERR_UNIT_POSTURE_BLOCKED` (409)."
        PRD: "Second, for every resident container in the unit whose custody is neither `VOIDED` nor `EMPTIED`, the pair formed by the candidate's class and the resident's class must not be one of the six incompatible pairs: acid with alkaline, acid with cyanide-bearing, acid with water-reactive, oxidizer with organic solvent, oxidizer with water-reactive, and water-reactive with alkaline."
        PRD: "Violation of either clause is `ERR_INCOMPATIBLE_SEGREGATION`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_container_placement
        """
        scenario = _unit_suspended_by_a_condemned_acid_drum()
        assert scenario.unit["posture"] == "SUSPENDED"
        assert scenario.acid_drum["compliance_state"] == "CONDEMNED"

        refusal = validate_error(_place_water_reactive_drum(scenario), "ERR_UNIT_POSTURE_BLOCKED")
        assert refusal["error_id"] != "ERR_INCOMPATIBLE_SEGREGATION"

    def test_refused_water_reactive_drum_leaves_the_unit_untouched(self):
        """The refused placement adds no drum and no kilogram to the suspended unit.

        PRD: "Container placement requires the unit's posture to be `OPEN` or `RESTRICTED` and is refused when it is `SUSPENDED` or `CLOSED`."
        PRD: "Otherwise it is `SUSPENDED` when any container in the unit is `CONDEMNED`, or when any emission repair order on the unit is overdue."
        PRD: "`container_count` is the number of containers in the unit whose custody is `FILLING`, `SEALED` or `STAGED`."
        PRD: "`stored_kg` is the sum of `net_weight_kg` over those same containers, to 3 decimals."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_container_placement
        """
        scenario = _unit_suspended_by_a_condemned_acid_drum()
        validate_error(_place_water_reactive_drum(scenario), "ERR_UNIT_POSTURE_BLOCKED")

        unit = fixtures.read_unit(scenario.unit["id"])
        assert unit["posture"] == "SUSPENDED"
        assert unit["container_count"] == 1
        assert_mass(unit["stored_kg"], 200.0, "stored_kg")


class TestLapsedRecertificationOutranksAssuranceShortfall:
    def test_lapsed_profile_reports_itself_before_the_assurance_shortfall(self):
        """A placement under a profile whose recertification has passed is refused
        for the lapse even though the facility is also short of assurance.

        PRD: "All validations are evaluated in ascending priority order and **the first violated rule wins**; no later rule may mask an earlier one, and no earlier rule may be skipped because a later one would also fail."
        PRD: "**Recertification currency.** The waste profile's `recertification_due_at` has not been passed by the logical clock — `ERR_PROFILE_EXPIRED` (409)."
        PRD: "**Financial assurance.** The facility's `assurance_shortfall_cents` is zero before waste acceptance, container placement, permit renewal filing or instrument cancellation — `ERR_FINANCIAL_ASSURANCE_SHORTFALL` (402)."
        PRD: "The lapse cascades to nothing: containers already placed under the profile are unaffected, but a new container placement under it is refused with `ERR_PROFILE_EXPIRED`."
        PRD: "Whenever the profile is read or touched and the clock has passed `recertification_due_at`, an `APPROVED` profile is observed as `EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_container_placement
        """
        scenario = _expired_profile_over_an_underfunded_facility()
        assert fixtures.read_profile(scenario.profile["id"])["status"] == "EXPIRED"

        refusal = validate_error(_place_drum_under_lapsed_profile(scenario), "ERR_PROFILE_EXPIRED")
        assert refusal["error_id"] != "ERR_FINANCIAL_ASSURANCE_SHORTFALL"

    def test_shortfall_survives_the_refusal_and_no_drum_is_placed(self):
        """The 33,250,000-cent shortfall stands and the storage unit stays empty.

        PRD: "**Step one** prices closure from inventory."
        PRD: "`closure_base_cost_cents` is 25,000,000 cents of fixed closure overhead plus 1,800 cents for every kilogram of `held_mass_kg`, that per-kilogram product being rounded half up to whole cents before it is added to the fixed component."
        PRD: "`assurance_tier` is `TIER_1` when `closure_base_cost_cents` is below 30,000,000 cents, `TIER_2` when it is below 60,000,000 cents but not below 30,000,000, and `TIER_3` otherwise."
        PRD: "**Step three** applies the tier's surcharge rate: `closure_cost_estimate_cents` is `closure_base_cost_cents` multiplied by one plus the tier's rate, rounded half up to whole cents."
        PRD: "`required_assurance_cents` is the sum of `closure_cost_estimate_cents`, the facility's input `post_closure_cost_cents`, `corrective_action_reserve_cents`, and `active_treatment_liability_cents` — the last being the sum of `estimated_treatment_liability_cents` across the facility's batches that are `PLANNED` or `IN_TREATMENT`."
        PRD: "`posted_assurance_cents` is the sum of `face_amount_cents` over the facility's instruments whose `status` is `ACTIVE`, and `assurance_shortfall_cents` is the amount by which the required total exceeds the posted total, or zero when the posted total is at least the required total."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_container_placement
        """
        scenario = _expired_profile_over_an_underfunded_facility()
        validate_error(_place_drum_under_lapsed_profile(scenario), "ERR_PROFILE_EXPIRED")

        facility = fixtures.read_facility(scenario.facility["id"])
        assert_cents(facility["posted_assurance_cents"], 1_000_000, "posted_assurance_cents")
        assert_cents(facility["required_assurance_cents"], 34_250_000, "required_assurance_cents")
        assert_cents(
            facility["assurance_shortfall_cents"], 33_250_000, "assurance_shortfall_cents"
        )
        unit = fixtures.read_unit(scenario.unit["id"])
        assert unit["container_count"] == 0
        assert_mass(unit["stored_kg"], 0.0, "stored_kg")
