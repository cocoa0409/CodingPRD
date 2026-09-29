"""Cascades that run from a single request down to the facility's assurance figures.

Both chains start on one drum: a leak citation condemns it and suspends its unit,
while a suspended waste profile only makes it deficient and merely restricts the
unit. In each case the treatment batch scheduled into that unit is held, its mass
leaves the unit's reservation, and the facility's required assurance falls by the
liability the batch was carrying.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_assurance,
    assert_cents,
    assert_unit_state,
    factories,
    fixtures,
)

# A 200.0 kg drum priced through the closure and treatment formulas:
# 25,000,000 + 1,800 x 200 = 25,360,000 base, surcharged at the TIER_1 rate of
# 5 percent to 26,628,000, plus 8,000,000 of post-closure care, plus a treatment
# liability of 220 x 200 = 44,000 cents while the batch is still PLANNED.
STAGED_MASS_KG = 200.0
TREATMENT_LIABILITY_CENTS = 44_000
REQUIRED_WITH_PLANNED_BATCH_CENTS = 34_672_000
REQUIRED_AFTER_HOLD_CENTS = 34_628_000


def _planned_batch_over_one_staged_drum() -> fixtures.Scenario:
    """A funded facility whose OPEN container area holds one 200.0 kg drum,
    staged into a PLANNED treatment batch under an APPROVED waste profile."""
    return fixtures.setup_planned_batch(net_weight_kg=STAGED_MASS_KG)


class TestContainerLeakCondemnationCascade:
    def test_leak_citation_condemns_the_named_drum_and_opens_a_repair_order(self):
        """`leak_detected` is true when `measured_organic_vapor_ppm` reaches or exceeds the leak definition of the unit's `air_emission_control_level`, or when `finding_code` is `CONTAINER_LEAK` or `TANK_SHELL_CORROSION`.

        The container records the finding that condemned it, the holding storage unit recomputes its operating posture and arrives at `SUSPENDED` because it now holds at least one condemned container, every treatment batch on that unit that was still `PLANNED` moves to `HELD`, and each held batch drops out of the unit's reserved mass and out of the facility's active treatment liability — so the facility's required assurance falls by exactly the liability those batches were carrying.
        A container can be `SEALED` and `CONDEMNED` at the same time, and a custody move never touches condition while a condition change never touches custody.
        The order copies `storage_unit_id` and `container_id` from the inspection, records the triggering inspection as its `source_inspection_event_id`, copies `inspected_at` into `detected_at`, records the triggering reading as `detected_ppm` and the applied threshold as `leak_definition_ppm`, and sets `leak_type` to `CONTAINER_LEAK` when a `container_id` was named and to `TANK_LEAK` otherwise.
        A new order opens with `status` of `OPEN`, `attempt_count` zero, `justification_code` of `NONE`, and `delayed_due_at` and `last_monitored_ppm` null.

        Design: Difficulty/transitive_cascade/inspection_leak_condemn_unit_suspend_batch_hold_reserved_release
        """
        scenario = _planned_batch_over_one_staged_drum()

        inspection = validate_success(
            api_client.create_inspection_event(
                factories.inspection_payload(
                    scenario.unit["id"],
                    inspection_type="WEEKLY_CONTAINER_AREA",
                    finding_code="CONTAINER_LEAK",
                    container_id=scenario.container["id"],
                ),
                TEST_USERS["compliance_manager"],
            ),
            expected_status=201,
        )
        assert inspection["leak_detected"] is True

        container = fixtures.read_container(scenario.container["id"])
        assert container["compliance_state"] == "CONDEMNED"
        assert container["last_finding_code"] == "CONTAINER_LEAK"
        assert container["custody_state"] == "STAGED"

        orders, meta = validate_paginated(
            api_client.list_repair_orders(
                TEST_USERS["compliance_manager"],
                params={"source_inspection_event_id": inspection["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert orders[0]["status"] == "OPEN"
        assert orders[0]["leak_type"] == "CONTAINER_LEAK"
        assert orders[0]["storage_unit_id"] == scenario.unit["id"]
        assert orders[0]["container_id"] == scenario.container["id"]

    def test_condemned_drum_suspends_the_unit_holds_the_batch_and_frees_the_liability(self):
        """The container records the finding that condemned it, the holding storage unit recomputes its operating posture and arrives at `SUSPENDED` because it now holds at least one condemned container, every treatment batch on that unit that was still `PLANNED` moves to `HELD`, and each held batch drops out of the unit's reserved mass and out of the facility's active treatment liability — so the facility's required assurance falls by exactly the liability those batches were carrying.

        Otherwise it is `SUSPENDED` when any container in the unit is `CONDEMNED`, or when any emission repair order on the unit is overdue.
        From `COMPLIANT` to `DEFICIENT` — reachable by direct request, by an inspection whose `finding_code` is `LABEL_DEFICIENT` or `OVERFILL`, or by the profile suspension cascade — the container stores `last_finding_code`, its custody is untouched, the holding unit recomputes posture from `OPEN` to `RESTRICTED`, and, caused by that posture change, `PLANNED` batches on the unit move to `HELD` with `held_reason_code` of `UNIT_POSTURE`.
        A batch moves from `PLANNED` to `HELD` with `held_reason_code` set when its unit's posture leaves `OPEN` — through the condemnation cascade or the profile suspension cascade — and each such move drops the batch out of the unit's `reserved_kg` and out of the facility's `active_treatment_liability_cents`.
        `reserved_kg` is the sum of `input_mass_kg` over the batches on the unit whose `status` is `PLANNED` or `IN_TREATMENT`, to 3 decimals.
        `required_assurance_cents` is the sum of `closure_cost_estimate_cents`, the facility's input `post_closure_cost_cents`, `corrective_action_reserve_cents`, and `active_treatment_liability_cents` — the last being the sum of `estimated_treatment_liability_cents` across the facility's batches that are `PLANNED` or `IN_TREATMENT`.

        Design: Difficulty/transitive_cascade/inspection_leak_condemn_unit_suspend_batch_hold_reserved_release
        """
        scenario = _planned_batch_over_one_staged_drum()
        assert_cents(
            scenario.batch["estimated_treatment_liability_cents"],
            TREATMENT_LIABILITY_CENTS,
            "estimated_treatment_liability_cents",
        )
        assert_unit_state(scenario.unit, posture="OPEN", reserved_kg=STAGED_MASS_KG)
        assert_assurance(
            scenario.facility,
            liability_cents=TREATMENT_LIABILITY_CENTS,
            required_cents=REQUIRED_WITH_PLANNED_BATCH_CENTS,
        )

        fixtures.condemn_container_by_inspection(
            scenario.unit["id"], scenario.container["id"]
        )

        assert_unit_state(
            fixtures.read_unit(scenario.unit["id"]), posture="SUSPENDED", reserved_kg=0.0
        )
        batch = fixtures.read_batch(scenario.batch["id"])
        assert batch["status"] == "HELD"
        assert batch["held_reason_code"] == "UNIT_POSTURE"
        assert_assurance(
            fixtures.read_facility(scenario.facility["id"]),
            liability_cents=0,
            required_cents=REQUIRED_AFTER_HOLD_CENTS,
            shortfall_cents=0,
        )


class TestProfileSuspensionCascade:
    def test_suspending_the_profile_makes_its_drum_deficient_without_moving_custody(self):
        """The **profile suspension cascade** starts when an approved waste profile is suspended.

        Every container filled under that profile that is still in physical custody and was in good condition becomes deficient with a finding code of `PROFILE_SUSPENDED`; each unit holding one of those containers recomputes posture and moves from `OPEN` to `RESTRICTED`; and every `PLANNED` batch on a unit that just became restricted moves to `HELD`, again dropping out of reserved mass and out of the facility's active treatment liability.
        A container can be `SEALED` and `CONDEMNED` at the same time, and a custody move never touches condition while a condition change never touches custody.

        Design: Difficulty/transitive_cascade/profile_suspension_deficient_unit_restricted_batch_hold
        """
        scenario = _planned_batch_over_one_staged_drum()

        suspended = validate_success(
            api_client.set_waste_profile_status(
                scenario.profile["id"],
                factories.profile_status_payload("SUSPENDED", "CHARACTERIZATION_DOUBT"),
                TEST_USERS["compliance_manager"],
            )
        )

        assert suspended["status"] == "SUSPENDED"
        container = fixtures.read_container(scenario.container["id"])
        assert container["compliance_state"] == "DEFICIENT"
        assert container["last_finding_code"] == "PROFILE_SUSPENDED"
        assert container["custody_state"] == "STAGED"

    def test_profile_suspension_restricts_the_unit_and_holds_its_planned_batch(self):
        """Every container filled under that profile that is still in physical custody and was in good condition becomes deficient with a finding code of `PROFILE_SUSPENDED`; each unit holding one of those containers recomputes posture and moves from `OPEN` to `RESTRICTED`; and every `PLANNED` batch on a unit that just became restricted moves to `HELD`, again dropping out of reserved mass and out of the facility's active treatment liability.

        Naming a `to_status` of `APPROVED` reverses the chain exactly: every container under that profile that is `DEFICIENT` with `last_finding_code` equal to `PROFILE_SUSPENDED` returns to `COMPLIANT`; the affected units recompute posture and return from `RESTRICTED` to `OPEN` when no other restriction holds; and every batch on those units that is `HELD` with `held_reason_code` of `PROFILE_SUSPENDED` returns to `PLANNED`, re-entering reserved mass and active treatment liability.
        `reserved_kg` is the sum of `input_mass_kg` over the batches on the unit whose `status` is `PLANNED` or `IN_TREATMENT`, to 3 decimals.
        `required_assurance_cents` is the sum of `closure_cost_estimate_cents`, the facility's input `post_closure_cost_cents`, `corrective_action_reserve_cents`, and `active_treatment_liability_cents` — the last being the sum of `estimated_treatment_liability_cents` across the facility's batches that are `PLANNED` or `IN_TREATMENT`.

        Design: Difficulty/transitive_cascade/profile_suspension_deficient_unit_restricted_batch_hold
        """
        scenario = _planned_batch_over_one_staged_drum()
        assert_assurance(
            scenario.facility,
            liability_cents=TREATMENT_LIABILITY_CENTS,
            required_cents=REQUIRED_WITH_PLANNED_BATCH_CENTS,
        )

        fixtures.set_profile_status(
            scenario.profile["id"], "SUSPENDED", "CHARACTERIZATION_DOUBT"
        )

        assert_unit_state(
            fixtures.read_unit(scenario.unit["id"]), posture="RESTRICTED", reserved_kg=0.0
        )
        batch = fixtures.read_batch(scenario.batch["id"])
        assert batch["status"] == "HELD"
        assert batch["held_reason_code"] == "PROFILE_SUSPENDED"
        assert_assurance(
            fixtures.read_facility(scenario.facility["id"]),
            liability_cents=0,
            required_cents=REQUIRED_AFTER_HOLD_CENTS,
        )
