"""Generator reliability variants, closure costing tiers and the mass ledger.

Each scenario is assembled through the documented endpoints, and the logical
clock is moved only where a deadline or an arrival order depends on it. The
clock reads 2026-08-01T00:00:00Z at the start of every test.
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
    custody_payload,
    manifest_line_payload,
    receipt_line,
)
from test_helpers.test_users import TEST_USERS

# ─── Four closed manifests, only the oldest of them discrepant ────────────────
# A bulk line declared at 1000.0 kg and weighed at 900.0 kg reaches exactly the
# 0.10 bulk tolerance, so the oldest arrival is the only discrepant shipment.
OLDEST_DECLARED_KG = 1000.0
OLDEST_RECEIVED_KG = 900.0
LATER_SHIPMENT_KG = 100.0
ARRIVAL_DAYS = (
    "2026-08-02T00:00:00Z",
    "2026-08-03T00:00:00Z",
    "2026-08-04T00:00:00Z",
    "2026-08-05T00:00:00Z",
)


def _generator_with_four_closed_manifests():
    """One generator whose four manifests all reach CERTIFIED, arriving on four
    consecutive days, with only the first arrival resolved as discrepant."""
    fixtures.set_clock()
    facility, instrument = fixtures.create_funded_facility()
    generator = fixtures.create_generator()
    profile = fixtures.create_approved_profile(
        generator["id"],
        facility["id"],
        profile_overrides={"physical_form": "BULK_LIQUID"},
    )
    quantities = (OLDEST_DECLARED_KG, LATER_SHIPMENT_KG, LATER_SHIPMENT_KG, LATER_SHIPMENT_KG)
    manifests = [
        fixtures.create_manifest(
            generator["id"],
            facility["id"],
            lines=[manifest_line_payload(profile["id"], declared, 1, True)],
            manifest_tracking_number=f"MTN000000{index}",
        )
        for index, declared in enumerate(quantities, start=1)
    ]

    # The oldest arrival is weighed short by exactly the bulk tolerance, so it
    # has to be resolved before it can be certified.
    fixtures.set_clock(ARRIVAL_DAYS[0])
    fixtures.receive_manifest(
        manifests[0]["id"], [receipt_line(1, OLDEST_RECEIVED_KG, 1)]
    )
    fixtures.resolve_discrepancy(
        manifests[0]["id"],
        "ACCEPT_ADJUSTED",
        adjusted_lines=[{"line_number": 1, "accepted_quantity_kg": OLDEST_RECEIVED_KG}],
    )
    fixtures.certify_manifest(manifests[0]["id"])

    # The three later arrivals are weighed exactly as declared.
    for arrival, manifest in zip(ARRIVAL_DAYS[1:], manifests[1:]):
        fixtures.set_clock(arrival)
        fixtures.receive_manifest(manifest["id"], [receipt_line(1, LATER_SHIPMENT_KG, 1)])
        fixtures.certify_manifest(manifest["id"])

    return fixtures.Scenario(
        facility=facility,
        instrument=instrument,
        generator=generator,
        profile=profile,
        manifests=manifests,
    )


class TestGeneratorReliabilityVariants:
    def test_rolling_score_ignores_the_discrepant_shipment_outside_its_window(self):
        """The three-manifest window covers only the three most recent arrivals,
        all of them clean, so the rolling score stays at 100.

        Both use the same weighted formula and differ only in which closed manifests they consider; a manifest is closed when its `status` is `CERTIFIED` or `REJECTED_RETURNED`.
        `reliability_score_rolling` applies the formula to the three most recent closed manifests, ordered by `arrived_at` descending with `created_at` descending as the tie-break, and it is the variant that gates laboratory work.
        A generator with four closed manifests of which only the oldest was resolved as discrepant therefore reads 100 on the rolling variant, because the three-manifest window excludes that manifest entirely, while the lifetime variant reads the rounded result of subtracting 45 times one quarter from 100.

        Design: Difficulty/dual_variant_calc/generator_reliability_rolling_vs_lifetime_diverges
        """
        scenario = _generator_with_four_closed_manifests()

        scores = validate_success(
            api_client.get_reliability_score(
                scenario.generator["id"], TEST_USERS["compliance_manager"]
            )
        )

        assert scores["reliability_score_rolling"] == 100

        oldest = fixtures.read_manifest(scenario.manifests[0]["id"])
        newest = fixtures.read_manifest(scenario.manifests[3]["id"])
        assert oldest["status"] == "CERTIFIED"
        assert oldest["discrepancy_type"] == "QUANTITY_SIGNIFICANT"
        assert newest["status"] == "CERTIFIED"
        assert newest["discrepancy_type"] == "NONE"

    def test_lifetime_score_counts_the_discrepant_shipment_and_diverges(self):
        """The lifetime variant weighs the same discrepancy against all four
        closed manifests, so it lands at 89 where the rolling variant reads 100.

        `reliability_score_lifetime` applies the formula to every closed manifest of the generator and is reported but never used as a gate.
        The discrepancy rate is the count of manifests in the set whose `discrepancy_type` is anything other than `NONE`, divided by the number of manifests in the set.
        The score is then 100, less 45 times the discrepancy rate, less 35 times the return rate, less 20 times the profile failure rate; the result is rounded half up to a whole number and then clamped into the inclusive range from 0 to 100.
        A generator with four closed manifests of which only the oldest was resolved as discrepant therefore reads 100 on the rolling variant, because the three-manifest window excludes that manifest entirely, while the lifetime variant reads the rounded result of subtracting 45 times one quarter from 100.

        Design: Difficulty/dual_variant_calc/generator_reliability_rolling_vs_lifetime_diverges
        """
        scenario = _generator_with_four_closed_manifests()

        scores = validate_success(
            api_client.get_reliability_score(
                scenario.generator["id"], TEST_USERS["compliance_manager"]
            )
        )

        assert scores["reliability_score_lifetime"] == 89
        assert scores["reliability_score_lifetime"] != scores["reliability_score_rolling"]

        generator = fixtures.read_generator(scenario.generator["id"])
        assert generator["reliability_score_lifetime"] == 89
        assert generator["reliability_score_rolling"] == 100


# ─── A facility whose closure base sits just under the first tier boundary ─────
HELD_KG = 2700.0
# 25,000,000 cents of overhead plus 2700.0 kg x 1,800 cents.
CLOSURE_BASE_CENTS = 29_860_000
# TIER_1 carries a 5 percent surcharge on that base.
CLOSURE_ESTIMATE_CENTS = 31_353_000
POST_CLOSURE_COST_CENTS = 8_000_000
REQUIRED_ASSURANCE_CENTS = CLOSURE_ESTIMATE_CENTS + POST_CLOSURE_COST_CENTS  # 39,353,000
# Re-deriving the tier from the surcharged figure would apply 10 percent instead.
REQUIRED_IF_TIER_RE_DERIVED_CENTS = 40_846_000
POSTED_ASSURANCE_CENTS = 90_000_000


def _facility_holding_2700_kg():
    """A funded facility holding a single 2700.0 kg box in an open container
    area, so its closure cost is priced off exactly that held mass."""
    return fixtures.setup_container_in_storage(
        profile_overrides={"physical_form": "BULK_LIQUID"},
        unit_overrides={"aisle_free_container_capacity": 20},
        declared_quantity_kg=HELD_KG,
        declared_container_count=1,
        is_bulk=True,
        net_weight_kg=HELD_KG,
        container_overrides={"container_type": "CUBIC_YARD_BOX", "capacity_kg": 3000.0},
    )


class TestFinancialAssuranceTierSelection:
    def test_tier_is_keyed_on_the_pre_surcharge_closure_base_cost(self):
        """A closure base of 29,860,000 cents stays in the first tier even though
        the 5 percent surcharge carries the surcharged figure past 30,000,000.

        `closure_base_cost_cents` is 25,000,000 cents of fixed closure overhead plus 1,800 cents for every kilogram of `held_mass_kg`, that per-kilogram product being rounded half up to whole cents before it is added to the fixed component.
        `assurance_tier` is `TIER_1` when `closure_base_cost_cents` is below 30,000,000 cents, `TIER_2` when it is below 60,000,000 cents but not below 30,000,000, and `TIER_3` otherwise.
        The tier is keyed on the pre-surcharge base cost from step one and on nothing else.
        It is never re-derived from the surcharged result of step three, and never from the required total: a facility whose base cost is just under the first tier boundary stays in `TIER_1` even though applying the surcharge pushes the surcharged figure past that boundary.
        The rate is 5 percent for `TIER_1`, 10 percent for `TIER_2` and 18 percent for `TIER_3`.

        Design: Difficulty/combinatorial_formula/financial_assurance_tier_keyed_on_closure_cost_not_total
        """
        scenario = _facility_holding_2700_kg()

        facility = fixtures.read_facility(scenario.facility["id"])
        assert_mass(facility["held_mass_kg"], HELD_KG, "held_mass_kg")

        summary = validate_success(
            api_client.get_financial_assurance_summary(
                scenario.facility["id"], TEST_USERS["compliance_manager"]
            )
        )

        assert_cents(
            summary["closure_base_cost_cents"], CLOSURE_BASE_CENTS, "closure_base_cost_cents"
        )
        assert summary["assurance_tier"] == "TIER_1"
        assert_cents(
            summary["closure_cost_estimate_cents"],
            CLOSURE_ESTIMATE_CENTS,
            "closure_cost_estimate_cents",
        )

    def test_required_assurance_totals_the_first_tier_estimate_with_post_closure_cost(self):
        """With no findings and no scheduled treatment, the requirement is the
        first-tier estimate plus the approved post-closure care cost.

        `required_assurance_cents` is the sum of `closure_cost_estimate_cents`, the facility's input `post_closure_cost_cents`, `corrective_action_reserve_cents`, and `active_treatment_liability_cents` — the last being the sum of `estimated_treatment_liability_cents` across the facility's batches that are `PLANNED` or `IN_TREATMENT`.
        `posted_assurance_cents` is the sum of `face_amount_cents` over the facility's instruments whose `status` is `ACTIVE`, and `assurance_shortfall_cents` is the amount by which the required total exceeds the posted total, or zero when the posted total is at least the required total.
        It is never re-derived from the surcharged result of step three, and never from the required total: a facility whose base cost is just under the first tier boundary stays in `TIER_1` even though applying the surcharge pushes the surcharged figure past that boundary.

        Design: Difficulty/combinatorial_formula/financial_assurance_tier_keyed_on_closure_cost_not_total
        """
        scenario = _facility_holding_2700_kg()

        summary = validate_success(
            api_client.get_financial_assurance_summary(
                scenario.facility["id"], TEST_USERS["compliance_manager"]
            )
        )

        assert_cents(
            summary["corrective_action_reserve_cents"], 0, "corrective_action_reserve_cents"
        )
        assert_cents(
            summary["active_treatment_liability_cents"], 0, "active_treatment_liability_cents"
        )
        assert_cents(
            summary["required_assurance_cents"],
            REQUIRED_ASSURANCE_CENTS,
            "required_assurance_cents",
        )
        assert summary["required_assurance_cents"] != REQUIRED_IF_TIER_RE_DERIVED_CENTS
        assert_cents(
            summary["posted_assurance_cents"], POSTED_ASSURANCE_CENTS, "posted_assurance_cents"
        )
        assert_cents(summary["assurance_shortfall_cents"], 0, "assurance_shortfall_cents")


# ─── A drum voided out of storage ─────────────────────────────────────────────
RECEIPT_KG = 1250.5
DRUM_KG = 200.0
# With nothing held, the closure base is the fixed overhead alone.
EMPTY_CLOSURE_BASE_CENTS = 25_000_000
EMPTY_CLOSURE_ESTIMATE_CENTS = 26_250_000
EMPTY_REQUIRED_ASSURANCE_CENTS = EMPTY_CLOSURE_ESTIMATE_CENTS + POST_CLOSURE_COST_CENTS


def _drum_placed_from_a_full_receipt():
    """A verified receipt of 1250.5 kg in five containers with one 200.0 kg drum
    filled from it and standing in an open container area."""
    return fixtures.setup_container_in_storage(
        profile_overrides={"physical_form": "BULK_LIQUID"},
        unit_overrides={
            "aisle_free_container_capacity": 20,
            "allowed_compatibility_classes": ["ORGANIC_SOLVENT"],
        },
        declared_quantity_kg=RECEIPT_KG,
        declared_container_count=5,
        is_bulk=False,
        net_weight_kg=DRUM_KG,
    )


class TestContainerVoidRestoresTheMassLedger:
    def test_voiding_a_drum_empties_its_unit_and_frees_its_receipt_line(self):
        """A voided drum stops counting towards its unit's occupancy and stops
        being allocated against the receipt line it drew from.

        Voiding a container moves it from either `FILLING` or `SEALED` to the terminal `VOIDED`, whether requested directly by a `ReceivingClerk` with a `to_custody_state` of `VOIDED` and an optional `reason_code`, or driven by the shipment rejection cascade.
        Voiding from either source has identical effects: the container's mass leaves its unit's `stored_kg` and leaves its line's `allocated_container_mass_kg`, so the mass returns to the facility's `unallocated_receipt_kg` and `mass_ledger_kg` does not move, while the facility's `closure_cost_estimate_cents` and `required_assurance_cents` are recomputed downward.
        `container_count` is the number of containers in the unit whose custody is `FILLING`, `SEALED` or `STAGED`.

        Design: Difficulty/compensating_invariant/container_void_restores_facility_mass_ledger
        """
        scenario = _drum_placed_from_a_full_receipt()
        assert scenario.container["custody_state"] == "FILLING"

        voided = validate_success(
            api_client.set_container_custody_state(
                scenario.container["id"],
                custody_payload("VOIDED", "REPACK_ERROR"),
                TEST_USERS["clerk"],
            )
        )

        assert voided["custody_state"] == "VOIDED"

        unit = fixtures.read_unit(scenario.unit["id"])
        assert unit["container_count"] == 0
        assert_mass(unit["stored_kg"], 0.0, "stored_kg")

        line = fixtures.read_line(scenario.manifest["id"], 1)
        assert_mass(line["allocated_container_mass_kg"], 0.0, "allocated_container_mass_kg")

    def test_voiding_returns_the_mass_to_the_unallocated_pool_and_lowers_closure_cost(self):
        """The voided kilograms go back where they came from, so the ledger still
        equals what was received and the closure figures fall back exactly.

        Creating a container moves mass out of `unallocated_receipt_kg` and into `held_mass_kg`; voiding that container moves the identical figure back, leaving `mass_ledger_kg` untouched.
        `mass_ledger_kg` is the sum of those five destinations, and it must equal `received_mass_kg` after every operation, with no rounding drift.
        `closure_base_cost_cents` is 25,000,000 cents of fixed closure overhead plus 1,800 cents for every kilogram of `held_mass_kg`, that per-kilogram product being rounded half up to whole cents before it is added to the fixed component.
        Voiding from either source has identical effects: the container's mass leaves its unit's `stored_kg` and leaves its line's `allocated_container_mass_kg`, so the mass returns to the facility's `unallocated_receipt_kg` and `mass_ledger_kg` does not move, while the facility's `closure_cost_estimate_cents` and `required_assurance_cents` are recomputed downward.

        Design: Difficulty/compensating_invariant/container_void_restores_facility_mass_ledger
        """
        scenario = _drum_placed_from_a_full_receipt()
        before = fixtures.read_facility(scenario.facility["id"])
        assert_mass(before["held_mass_kg"], DRUM_KG, "held_mass_kg before the void")
        assert_mass(
            before["unallocated_receipt_kg"],
            RECEIPT_KG - DRUM_KG,
            "unallocated_receipt_kg before the void",
        )

        fixtures.void_container(scenario.container["id"])

        facility = fixtures.read_facility(scenario.facility["id"])
        assert_mass(facility["held_mass_kg"], 0.0, "held_mass_kg")
        assert_mass(facility["unallocated_receipt_kg"], RECEIPT_KG, "unallocated_receipt_kg")
        assert_mass(facility["received_mass_kg"], RECEIPT_KG, "received_mass_kg")
        assert_mass(facility["mass_ledger_kg"], RECEIPT_KG, "mass_ledger_kg")
        assert_mass_ledger_balances(facility)

        assert_cents(
            facility["closure_base_cost_cents"],
            EMPTY_CLOSURE_BASE_CENTS,
            "closure_base_cost_cents",
        )
        assert_cents(
            facility["closure_cost_estimate_cents"],
            EMPTY_CLOSURE_ESTIMATE_CENTS,
            "closure_cost_estimate_cents",
        )
        assert_cents(
            facility["required_assurance_cents"],
            EMPTY_REQUIRED_ASSURANCE_CENTS,
            "required_assurance_cents",
        )
