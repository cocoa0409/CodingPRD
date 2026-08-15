"""Inbound batches, screening, and cook runs (PRD §2.11, §3.5, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_run_to_pressing,
    assert_batch,
    assert_batch_mass_conserved,
    assert_cook_run,
    complete_cook_run,
    create_accepted_batch,
    create_plant,
    create_staged_cook_run,
    create_supplier,
    create_active_agreement,
    create_walkin_batch,
    get_lot_for_run,
    get_settlement,
    setup_completed_cook_run,
    setup_plant_with_agreement,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PS = TEST_USERS["production_supervisor_headers"]
SH = TEST_USERS["scalehouse_operator_headers"]
SH2 = TEST_USERS["scalehouse_operator_2_headers"]
ANY = TEST_USERS["any_headers"]


class TestBatchCreationAndScreening:
    def test_batch_create_computed_fields_input_ignored(self, api):
        """PRD §3.5: "Every new batch starts `RECEIVED` with `screening_result` `PENDING`,
        `reserved_lbs` zero, `consumed_lbs` zero, `remaining_lbs` equal to its `weight_lbs`,
        and `screened_by` null until screening."

        Design: Corner/entities/batch_create_computed_fields_input_ignored
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        # Client-supplied values for server-computed fields must be ignored.
        res = api.create_inbound_batch(
            {
                "plant_id": plant["id"],
                "supplier_id": supplier["id"],
                "agreement_id": agreement["id"],
                "species": "BOVINE",
                "weight_lbs": 8000,
                "temperature_f": 60.0,
                "received_at": "2026-08-02T08:00:00Z",
                "remaining_lbs": 5,
                "reserved_lbs": 99,
            },
            SH,
        )
        batch = validate_success(res, 201)
        assert_batch(batch)
        assert batch["remaining_lbs"] == 8000
        assert batch["reserved_lbs"] == 0
        assert batch["consumed_lbs"] == 0
        assert batch["screening_result"] == "PENDING"
        assert batch["status"] == "RECEIVED"

    def test_batch_screen_quarantine_adjudicate_accept_path(self, api):
        """PRD §3.5: "a `FAIL_TEMPERATURE` moves it to `QUARANTINED`"
        PRD §3.5: "The batch must be `QUARANTINED` (`ERR_BATCH_INVALID_STATE`), and when a
        `screened_by` screener is recorded the adjudicator must be someone else
        (`ERR_SOD_VIOLATION`). `ACCEPT` moves the batch to `ACCEPTED`; `REJECT` moves it to
        `REJECTED`, which is terminal."

        Design: Corner/state_machines/batch_screen_quarantine_adjudicate_accept_path
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        batch = create_walkin_batch(plant["id"], supplier["id"], agreement["id"],
                                    temperature_f=104.0)

        screened = validate_success(
            api.screen_batch(batch["id"], {"screening_result": "FAIL_TEMPERATURE"}, SH),
            200,
        )
        assert screened["status"] == "QUARANTINED"
        assert screened["screening_result"] == "FAIL_TEMPERATURE"
        assert screened["screened_by"] == "sh-1"

        adjudicated = validate_success(
            api.adjudicate_batch(batch["id"], {"decision": "ACCEPT"}, CO), 200
        )
        assert adjudicated["status"] == "ACCEPTED"
        assert adjudicated["screened_by"] == "sh-1"

    def test_screen_fail_prohibited_policy_branch(self, api):
        """PRD §3.5: "a `FAIL_PROHIBITED` moves it to `REJECTED` under a `ZERO_TOLERANCE`
        policy but only to `QUARANTINED` under `SORT_AND_RETURN`, giving the material a
        chance at adjudicated return."

        Design: Corner/state_machines/screen_fail_prohibited_policy_branch
        """
        plant = create_plant()
        supplier1 = create_supplier(plant["id"], supplier_name="S1")
        agreement1 = create_active_agreement(
            plant["id"], supplier1["id"], agreement_ref="AGR-ZT",
            prohibited_material_policy="ZERO_TOLERANCE",
        )
        supplier2 = create_supplier(plant["id"], supplier_name="S2", supplier_type="GROCERY")
        agreement2 = create_active_agreement(
            plant["id"], supplier2["id"], agreement_ref="AGR-SR",
            prohibited_material_policy="SORT_AND_RETURN",
        )
        batch1 = create_walkin_batch(plant["id"], supplier1["id"], agreement1["id"],
                                     weight_lbs=8000)
        batch2 = create_walkin_batch(plant["id"], supplier2["id"], agreement2["id"],
                                     weight_lbs=6000, received_at="2026-08-02T09:00:00Z")

        rejected = validate_success(
            api.screen_batch(batch1["id"], {"screening_result": "FAIL_PROHIBITED"}, SH), 200
        )
        assert rejected["status"] == "REJECTED"

        quarantined = validate_success(
            api.screen_batch(batch2["id"], {"screening_result": "FAIL_PROHIBITED"}, SH2), 200
        )
        assert quarantined["status"] == "QUARANTINED"


class TestCookRunCreationRules:
    def test_cook_input_exceeds_batch_remaining_rejected(self, api):
        """PRD §3.6: "Each input's planned weight must not exceed its batch's current
        `remaining_lbs` (`ERR_WEIGHT_EXCEEDS_REMAINING`)."

        Design: Corner/validations/cook_input_exceeds_batch_remaining_rejected
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        batch = create_accepted_batch(plant["id"], supplier["id"], agreement["id"],
                                      weight_lbs=5000)
        res = api.create_cook_run(
            {
                "plant_id": plant["id"],
                "cooker_line": 1,
                "recipe": "RUMINANT_RENDER",
                "planned_inputs": [{"batch_id": batch["id"], "weight_lbs": 5001}],
                "cook_start": "2026-08-05T06:00:00Z",
                "cook_end": "2026-08-05T10:00:00Z",
            },
            PS,
        )
        validate_error(res, ApiErrorId.ERR_WEIGHT_EXCEEDS_REMAINING, expected_status=422)

        batch_after = validate_success(api.get_inbound_batch(batch["id"], ANY), 200)
        assert batch_after["reserved_lbs"] == 0
        assert_batch_mass_conserved(batch_after)

    def test_species_mixing_matrix_enforced(self, api):
        """PRD §3.6: "Species segregation is absolute. `RUMINANT_RENDER` accepts only
        `BOVINE` and `OVINE` inputs — and uniquely, those two may be mixed in one run;
        `PORCINE_RENDER` accepts only `PORCINE`; `POULTRY_RENDER` accepts only `POULTRY`;
        `MIXED_RENDER` accepts `BOVINE`, `OVINE`, and `PORCINE` — poultry is never permitted
        in a mixed render. Any input batch outside the recipe's allowed set is rejected with
        `ERR_SPECIES_MIXING_VIOLATION`."

        Design: Corner/calculations/species_mixing_matrix_enforced
        """
        plant = create_plant()
        supplier = create_supplier(plant["id"], supplier_type="SLAUGHTERHOUSE")
        agreement = create_active_agreement(
            plant["id"], supplier["id"], species_scope=["BOVINE", "OVINE", "POULTRY"]
        )
        b_bov = create_accepted_batch(plant["id"], supplier["id"], agreement["id"],
                                      species="BOVINE", weight_lbs=5000)
        b_ovi = create_accepted_batch(plant["id"], supplier["id"], agreement["id"],
                                      species="OVINE", weight_lbs=3000,
                                      received_at="2026-08-03T09:00:00Z")
        b_pou = create_accepted_batch(plant["id"], supplier["id"], agreement["id"],
                                      species="POULTRY", weight_lbs=4000,
                                      received_at="2026-08-03T10:00:00Z")

        # BOVINE + OVINE is the one legal mix under RUMINANT_RENDER.
        ok = validate_success(
            api.create_cook_run(
                {
                    "plant_id": plant["id"],
                    "cooker_line": 1,
                    "recipe": "RUMINANT_RENDER",
                    "planned_inputs": [
                        {"batch_id": b_bov["id"], "weight_lbs": 1000},
                        {"batch_id": b_ovi["id"], "weight_lbs": 1000},
                    ],
                    "cook_start": "2026-08-05T06:00:00Z",
                    "cook_end": "2026-08-05T10:00:00Z",
                },
                PS,
            ),
            201,
        )
        assert_cook_run(ok)
        assert ok["status"] == "STAGED"

        # BOVINE + POULTRY under RUMINANT_RENDER violates the matrix.
        res1 = api.create_cook_run(
            {
                "plant_id": plant["id"],
                "cooker_line": 2,
                "recipe": "RUMINANT_RENDER",
                "planned_inputs": [
                    {"batch_id": b_bov["id"], "weight_lbs": 1000},
                    {"batch_id": b_pou["id"], "weight_lbs": 1000},
                ],
                "cook_start": "2026-08-06T06:00:00Z",
                "cook_end": "2026-08-06T10:00:00Z",
            },
            PS,
        )
        validate_error(res1, ApiErrorId.ERR_SPECIES_MIXING_VIOLATION, expected_status=422)

        # POULTRY is excluded even from MIXED_RENDER.
        res2 = api.create_cook_run(
            {
                "plant_id": plant["id"],
                "cooker_line": 2,
                "recipe": "MIXED_RENDER",
                "planned_inputs": [{"batch_id": b_pou["id"], "weight_lbs": 1000}],
                "cook_start": "2026-08-06T06:00:00Z",
                "cook_end": "2026-08-06T10:00:00Z",
            },
            PS,
        )
        validate_error(res2, ApiErrorId.ERR_SPECIES_MIXING_VIOLATION, expected_status=422)


class TestCookYieldDualVariant:
    def _setup_pressing_run_10000(self, api):
        """ACCEPTED 10000-lb BOVINE batch; RUMINANT_RENDER run consuming all of it,
        advanced to PRESSING. Window 2026-08-03 08:00-12:00 (4h)."""
        plant, supplier, agreement = setup_plant_with_agreement()
        batch = create_accepted_batch(plant["id"], supplier["id"], agreement["id"],
                                      weight_lbs=10000, received_at="2026-08-02T08:00:00Z")
        run = create_staged_cook_run(
            plant["id"], [{"batch_id": batch["id"], "weight_lbs": 10000}],
            cook_start="2026-08-03T08:00:00Z", cook_end="2026-08-03T12:00:00Z",
        )
        return plant, batch, run

    def test_cook_yield_theoretical_computed_at_staging(self, api):
        """PRD §3.6: "For each planned input line, the line's weight is multiplied by the
        fat coefficient of that batch's species — 0.16 for `BOVINE`, 0.14 for `PORCINE`,
        0.10 for `POULTRY`, 0.15 for `OVINE`, 0.12 for `MIXED` — and the product rounded
        half-up to a whole pound; `theoretical_fat_lbs` is the sum of those per-line rounded
        values. `theoretical_meal_lbs` is computed identically with the meal coefficients —
        0.24 for `BOVINE`, 0.22 for `PORCINE`, 0.30 for `POULTRY`, 0.23 for `OVINE`, 0.25
        for `MIXED`."

        Design: Difficulty/dual_variant_calc/cook_yield_theoretical_vs_actual
        """
        plant, batch, run = self._setup_pressing_run_10000(api)
        # THEORETICAL variant at staging: 10000 * 0.16 fat, 10000 * 0.24 meal.
        assert run["theoretical_fat_lbs"] == 1600
        assert run["theoretical_meal_lbs"] == 2400
        assert run["total_input_lbs"] == 10000
        assert run["status"] == "STAGED"

        # Staging reserves the batch's mass.
        batch_mid = validate_success(api.get_inbound_batch(batch["id"], ANY), 200)
        assert batch_mid["reserved_lbs"] == 10000
        assert batch_mid["remaining_lbs"] == 0
        assert_batch_mass_conserved(batch_mid)

    def test_cook_completion_variance_energy_and_lots(self, api):
        """PRD §3.6: "The server finalizes `yield_variance_pct`: the sum of the two actual
        outputs minus the sum of the two theoretical yields, divided by that theoretical
        total, multiplied by one hundred, and rounded half-up to two decimal places."
        PRD §3.6: "The first tier costs 4200 cents per hour and the second 3800 cents per
        hour, so `energy_cost_cents` is the first-tier hours times 4200 plus the second-tier
        hours times 3800."
        PRD §3.6: "a `RUMINANT_RENDER`, `PORCINE_RENDER`, or `MIXED_RENDER` run produces a
        `TALLOW` lot with `quantity_lbs` equal to `actual_fat_output_lbs` and a
        `PROTEIN_MEAL` lot with `quantity_lbs` equal to `actual_meal_output_lbs`; ..."
        PRD §3.6: "For each input batch, `reserved_lbs` decreases by the planned weight and
        `consumed_lbs` increases by the same amount; a batch whose `remaining_lbs` reaches 0
        with positive consumption becomes `DEPLETED`."

        Design: Difficulty/dual_variant_calc/cook_yield_theoretical_vs_actual
        """
        plant, batch, run = self._setup_pressing_run_10000(api)
        advance_run_to_pressing(run["id"])

        # ACTUAL variant: 1500 + 2450 = 3950 vs theoretical 4000 -> variance -1.25.
        completed = complete_cook_run(run["id"], 1500, 2450)
        assert_cook_run(completed)
        assert completed["status"] == "COMPLETED"
        assert completed["yield_variance_pct"] == pytest.approx(-1.25, abs=1e-9)
        # 4-hour window, no prior completions: all hours bill at the first tier.
        assert completed["energy_cost_cents"] == 16800  # 4 * 4200

        fat_lot = get_lot_for_run(run["id"], "TALLOW")
        meal_lot = get_lot_for_run(run["id"], "PROTEIN_MEAL")
        assert fat_lot["quantity_lbs"] == 1500
        assert fat_lot["status"] == "LAB_PENDING"
        assert fat_lot["grade"] == "UNGRADED"
        assert meal_lot["quantity_lbs"] == 2450

        batch_after = validate_success(api.get_inbound_batch(batch["id"], ANY), 200)
        assert batch_after["consumed_lbs"] == 10000
        assert batch_after["reserved_lbs"] == 0
        assert batch_after["status"] == "DEPLETED"
        assert_batch_mass_conserved(batch_after)

        settlement = get_settlement(plant["id"], period_index=1)
        assert settlement["energy_costs_cents"] == 16800


class TestCookRunRecookCycle:
    def _setup_ovine_run(self, api):
        plant = create_plant()
        supplier = create_supplier(plant["id"], supplier_type="SLAUGHTERHOUSE")
        agreement = create_active_agreement(plant["id"], supplier["id"],
                                            species_scope=["OVINE"])
        batch = create_accepted_batch(plant["id"], supplier["id"], agreement["id"],
                                      species="OVINE", weight_lbs=5000)
        run = create_staged_cook_run(
            plant["id"], [{"batch_id": batch["id"], "weight_lbs": 5000}],
        )
        return plant, batch, run

    def test_cook_run_recook_cycle_retains_reservations(self, api):
        """PRD §3.6: "A run in `COOKING` or `SETTLING` may be failed (from any other state:
        `ERR_COOK_RUN_INVALID_STATE`), recording the supplied `failure_reason`; batch
        reservations are retained so the material can be cooked again. A `FAILED` run may be
        restaged to `STAGED`, which increments `recook_count` by one, clears
        `failure_reason`, and again retains the reservations."

        Design: Difficulty/non_linear_state_machine/cook_run_recook_cycle
        """
        plant, batch, run = self._setup_ovine_run(api)

        # First cycle: COOKING -> FAILED -> STAGED.
        validate_success(api.start_cook_run(run["id"], PS), 200)
        failed = validate_success(
            api.fail_cook_run(run["id"], {"failure_reason": "temp fault"}, PS), 200
        )
        assert failed["status"] == "FAILED"
        assert failed["failure_reason"] == "temp fault"
        restaged = validate_success(api.restage_cook_run(run["id"], PS), 200)
        assert restaged["status"] == "STAGED"
        assert restaged["recook_count"] == 1
        assert restaged["failure_reason"] is None

        # Second cycle: STAGED -> COOKING -> SETTLING -> FAILED -> STAGED.
        validate_success(api.start_cook_run(run["id"], PS), 200)
        validate_success(api.advance_cook_run(run["id"], PS), 200)  # SETTLING
        failed2 = validate_success(
            api.fail_cook_run(run["id"], {"failure_reason": "agitator jam"}, PS), 200
        )
        assert failed2["status"] == "FAILED"
        restaged2 = validate_success(api.restage_cook_run(run["id"], PS), 200)
        assert restaged2["recook_count"] == 2

        # The batch reservation survived both FAILED states.
        batch_mid = validate_success(api.get_inbound_batch(batch["id"], ANY), 200)
        assert batch_mid["reserved_lbs"] == 5000
        assert batch_mid["remaining_lbs"] == 0
        assert batch_mid["consumed_lbs"] == 0
        assert_batch_mass_conserved(batch_mid)

    def test_cook_run_recook_cycle_completes_with_zero_variance(self, api):
        """PRD §3.6: "A `FAILED` run may be restaged to `STAGED`, which increments
        `recook_count` by one, clears `failure_reason`, and again retains the reservations."
        PRD §3.6: "For each input batch, `reserved_lbs` decreases by the planned weight and
        `consumed_lbs` increases by the same amount; a batch whose `remaining_lbs` reaches 0
        with positive consumption becomes `DEPLETED`."

        Design: Difficulty/non_linear_state_machine/cook_run_recook_cycle
        """
        plant, batch, run = self._setup_ovine_run(api)
        # Two full FAILED -> STAGED cycles.
        for reason in ["temp fault", "agitator jam"]:
            validate_success(api.start_cook_run(run["id"], PS), 200)
            if reason == "agitator jam":
                validate_success(api.advance_cook_run(run["id"], PS), 200)
            validate_success(api.fail_cook_run(run["id"], {"failure_reason": reason}, PS), 200)
            validate_success(api.restage_cook_run(run["id"], PS), 200)

        # Third attempt: drive to PRESSING and complete with outputs equal to the
        # theoretical yields (5000 * 0.15 = 750 fat, 5000 * 0.23 = 1150 meal).
        advance_run_to_pressing(run["id"])
        completed = complete_cook_run(run["id"], 750, 1150)
        assert completed["status"] == "COMPLETED"
        assert completed["recook_count"] == 2
        assert completed["theoretical_fat_lbs"] == 750
        assert completed["theoretical_meal_lbs"] == 1150
        assert completed["yield_variance_pct"] == pytest.approx(0.0, abs=1e-9)
        # 3-hour window at the first tier rate.
        assert completed["energy_cost_cents"] == 12600  # 3 * 4200

        batch_after = validate_success(api.get_inbound_batch(batch["id"], ANY), 200)
        assert batch_after["consumed_lbs"] == 5000
        assert batch_after["status"] == "DEPLETED"
        assert_batch_mass_conserved(batch_after)


class TestCookerAggregateCapacity:
    def _setup_two_overlapping_runs(self, api):
        """Plant with cooker_capacity 2 and one 100000-lb ACCEPTED BOVINE batch.
        R1 [09:00,13:00) 30000 lbs and R2 [10:00,14:00) 30000 lbs, both STAGED."""
        plant = create_plant(cooker_capacity=2)
        supplier = create_supplier(plant["id"], supplier_type="SLAUGHTERHOUSE")
        agreement = create_active_agreement(plant["id"], supplier["id"])
        batch = create_accepted_batch(plant["id"], supplier["id"], agreement["id"],
                                      weight_lbs=100000)
        r1 = create_staged_cook_run(
            plant["id"], [{"batch_id": batch["id"], "weight_lbs": 30000}],
            cooker_line=1, cook_start="2026-08-05T09:00:00Z", cook_end="2026-08-05T13:00:00Z",
        )
        r2 = create_staged_cook_run(
            plant["id"], [{"batch_id": batch["id"], "weight_lbs": 30000}],
            cooker_line=2, cook_start="2026-08-05T10:00:00Z", cook_end="2026-08-05T14:00:00Z",
        )
        return plant, batch, r1, r2

    def test_cooker_aggregate_capacity_rejects_third_overlap(self, api):
        """PRD §3.6: "Cooker capacity is enforced in aggregate, not per line: `cooker_line`
        is informational and does not partition capacity. The server counts the plant's cook
        runs in `STAGED`, `COOKING`, `SETTLING`, or `PRESSING` whose half-open cook windows
        overlap the new run's window — two windows overlap exactly when each one's start is
        earlier than the other's end; windows merely touching at an endpoint do not overlap —
        and that count must be strictly less than the plant's `cooker_capacity`, else staging
        is rejected with `ERR_COOKER_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/cooker_aggregate_capacity
        """
        plant, batch, r1, r2 = self._setup_two_overlapping_runs(api)
        # R3 [11:00,12:00) overlaps both active runs: count 2 == cooker_capacity 2.
        res = api.create_cook_run(
            {
                "plant_id": plant["id"],
                "cooker_line": 3,
                "recipe": "RUMINANT_RENDER",
                "planned_inputs": [{"batch_id": batch["id"], "weight_lbs": 10000}],
                "cook_start": "2026-08-05T11:00:00Z",
                "cook_end": "2026-08-05T12:00:00Z",
            },
            PS,
        )
        validate_error(res, ApiErrorId.ERR_COOKER_CAPACITY_EXCEEDED, expected_status=409)

    def test_cooker_touching_windows_do_not_overlap(self, api):
        """PRD §3.6: "The server counts the plant's cook runs in `STAGED`, `COOKING`,
        `SETTLING`, or `PRESSING` whose half-open cook windows overlap the new run's window
        — two windows overlap exactly when each one's start is earlier than the other's end;
        windows merely touching at an endpoint do not overlap — and that count must be
        strictly less than the plant's `cooker_capacity`, else staging is rejected with
        `ERR_COOKER_CAPACITY_EXCEEDED`."
        PRD §3.6: "At the same moment, each input batch's `reserved_lbs` increases by its
        planned weight and its `remaining_lbs` decreases by the same amount."

        Design: Difficulty/resource_temporal_overlap/cooker_aggregate_capacity
        """
        plant, batch, r1, r2 = self._setup_two_overlapping_runs(api)
        # R4 [14:00,16:00): R1 ends 13:00, R2 ends exactly 14:00 — touching endpoints do
        # not overlap, so zero overlaps and staging succeeds.
        r4 = validate_success(
            api.create_cook_run(
                {
                    "plant_id": plant["id"],
                    "cooker_line": 3,
                    "recipe": "RUMINANT_RENDER",
                    "planned_inputs": [{"batch_id": batch["id"], "weight_lbs": 5000}],
                    "cook_start": "2026-08-05T14:00:00Z",
                    "cook_end": "2026-08-05T16:00:00Z",
                },
                PS,
            ),
            201,
        )
        assert r4["status"] == "STAGED"

        batch_after = validate_success(api.get_inbound_batch(batch["id"], ANY), 200)
        assert batch_after["reserved_lbs"] == 65000  # 30000 + 30000 + 5000
        assert_batch_mass_conserved(batch_after)


class TestCookStageCancelConservation:
    def test_stage_reserves_batch_mass(self, api):
        """PRD §2.11: "For every inbound batch, its `weight_lbs` always equals the sum of
        its `remaining_lbs`, `reserved_lbs`, and `consumed_lbs`. Staging a cook run moves
        pounds from `remaining_lbs` into `reserved_lbs`; ..."

        Design: Difficulty/compensating_invariant/cook_stage_cancel_mass_conservation
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        batch = create_accepted_batch(plant["id"], supplier["id"], agreement["id"],
                                      weight_lbs=10000)
        run = create_staged_cook_run(
            plant["id"], [{"batch_id": batch["id"], "weight_lbs": 4000}],
            cook_start="2026-08-05T06:00:00Z", cook_end="2026-08-05T10:00:00Z",
        )
        assert run["status"] == "STAGED"

        batch_mid = validate_success(api.get_inbound_batch(batch["id"], ANY), 200)
        assert batch_mid["remaining_lbs"] == 6000
        assert batch_mid["reserved_lbs"] == 4000
        assert batch_mid["consumed_lbs"] == 0
        assert_batch_mass_conserved(batch_mid)

    def test_cancel_releases_reservation_exactly(self, api):
        """PRD §3.6: "Cancellation is permitted from `STAGED` or `FAILED` (else
        `ERR_COOK_RUN_INVALID_STATE`) and releases each input batch's reservation exactly —
        `reserved_lbs` down, `remaining_lbs` up by the planned weight — so that a stage
        followed by a cancel returns every batch's `remaining_lbs` to its pre-stage value."
        PRD §2.11: "A stage followed by a cancel of the same run must restore
        `remaining_lbs` to exactly its prior value."

        Design: Difficulty/compensating_invariant/cook_stage_cancel_mass_conservation
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        batch = create_accepted_batch(plant["id"], supplier["id"], agreement["id"],
                                      weight_lbs=10000)
        run = create_staged_cook_run(
            plant["id"], [{"batch_id": batch["id"], "weight_lbs": 4000}],
            cook_start="2026-08-05T06:00:00Z", cook_end="2026-08-05T10:00:00Z",
        )
        cancelled = validate_success(api.cancel_cook_run(run["id"], PS), 200)
        assert cancelled["status"] == "CANCELLED"

        batch_after = validate_success(api.get_inbound_batch(batch["id"], ANY), 200)
        assert batch_after["remaining_lbs"] == 10000
        assert batch_after["reserved_lbs"] == 0
        assert batch_after["consumed_lbs"] == 0
        assert_batch_mass_conserved(batch_after)


class TestCookRunCompletionRules:
    def test_cook_run_complete_from_staged_rejected(self, api):
        """PRD §3.6: "Completion, from `PRESSING` only (`ERR_COOK_RUN_INVALID_STATE`), is
        where theory meets the scale."

        Design: Corner/state_machines/cook_run_complete_from_staged_rejected
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        batch = create_accepted_batch(plant["id"], supplier["id"], agreement["id"],
                                      weight_lbs=5000)
        run = create_staged_cook_run(
            plant["id"], [{"batch_id": batch["id"], "weight_lbs": 5000}],
        )
        assert run["status"] == "STAGED"

        res = api.complete_cook_run(
            run["id"], {"actual_fat_output_lbs": 800, "actual_meal_output_lbs": 1200}, PS
        )
        validate_error(res, ApiErrorId.ERR_COOK_RUN_INVALID_STATE, expected_status=409)

        fetched = validate_success(api.get_cook_run(run["id"], ANY), 200)
        assert fetched["status"] == "STAGED"

    def test_yield_tolerance_override_enforced(self, api):
        """PRD §3.6: "When the absolute variance exceeds 25 percent, completion is refused
        with `ERR_YIELD_OUT_OF_TOLERANCE` unless the supervisor supplies an `override_note`,
        which is the deliberate human-override channel for unusual but legitimate cooks."

        Design: Corner/calculations/yield_tolerance_override_enforced
        """
        plant, supplier, agreement = setup_plant_with_agreement()
        batch = create_accepted_batch(plant["id"], supplier["id"], agreement["id"],
                                      weight_lbs=10000)
        run = create_staged_cook_run(
            plant["id"], [{"batch_id": batch["id"], "weight_lbs": 10000}],
        )
        advance_run_to_pressing(run["id"])

        # Theoretical total 1600 + 2400 = 4000; actual 2800 -> variance -30.0% (> 25).
        res = api.complete_cook_run(
            run["id"], {"actual_fat_output_lbs": 1500, "actual_meal_output_lbs": 1300}, PS
        )
        validate_error(res, ApiErrorId.ERR_YIELD_OUT_OF_TOLERANCE, expected_status=422)
        mid = validate_success(api.get_cook_run(run["id"], ANY), 200)
        assert mid["status"] == "PRESSING"

        # The override note is the deliberate human channel past the tolerance gate.
        completed = validate_success(
            api.complete_cook_run(
                run["id"],
                {"actual_fat_output_lbs": 1500, "actual_meal_output_lbs": 1300,
                 "override_note": "freeze event degraded yield"},
                PS,
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"
        assert completed["yield_variance_pct"] == pytest.approx(-30.0, abs=1e-9)


class TestEnergyTieredPricing:
    def test_energy_cost_tier_straddle_marginal_hours(self, api):
        """PRD §3.6: "Completion prices the run's energy with a marginal two-tier tariff.
        The run's duration is its whole-hour window length. The plant's banked hours are the
        sum of durations of this plant's cook runs that completed earlier in the current
        period, with completions at the same instant ordered by `updated_at` ascending. Of
        this run's hours, the portion billed at the first-tier rate is the larger of zero
        and the smaller of the run's duration and the gap remaining between the banked hours
        and the 500-hour tier boundary; the remainder bills at the second-tier rate."

        Design: Corner/calculations/energy_cost_tier_straddle_marginal_hours
        """
        plant = create_plant()
        supplier = create_supplier(plant["id"], supplier_type="SLAUGHTERHOUSE")
        agreement = create_active_agreement(plant["id"], supplier["id"])
        batch = create_accepted_batch(plant["id"], supplier["id"], agreement["id"],
                                      weight_lbs=100000)

        # Run 1: 360h window, 20000 lbs; Run 2: 240h window, 15000 lbs.
        r1 = create_staged_cook_run(
            plant["id"], [{"batch_id": batch["id"], "weight_lbs": 20000}],
            cooker_line=1, cook_start="2026-08-05T00:00:00Z", cook_end="2026-08-20T00:00:00Z",
        )
        r2 = create_staged_cook_run(
            plant["id"], [{"batch_id": batch["id"], "weight_lbs": 15000}],
            cooker_line=2, cook_start="2026-08-05T00:00:00Z", cook_end="2026-08-15T00:00:00Z",
        )
        advance_run_to_pressing(r1["id"])
        advance_run_to_pressing(r2["id"])

        # Run 1 completes with zero variance (20000*0.16 = 3200 fat, 20000*0.24 = 4800).
        c1 = complete_cook_run(r1["id"], 3200, 4800)
        assert c1["status"] == "COMPLETED"
        assert c1["yield_variance_pct"] == pytest.approx(0.0, abs=1e-9)
        # Banked hours 0: all 360h at tier 1.
        assert c1["energy_cost_cents"] == 1512000  # 360 * 4200

        # Run 2 completes with zero variance (15000*0.16 = 2400, 15000*0.24 = 3600).
        # Banked 360h: 140h remain below the 500h boundary at tier 1, 100h at tier 2.
        c2 = complete_cook_run(r2["id"], 2400, 3600)
        assert c2["status"] == "COMPLETED"
        assert c2["yield_variance_pct"] == pytest.approx(0.0, abs=1e-9)
        assert c2["energy_cost_cents"] == 968000  # 140 * 4200 + 100 * 3800

        settlement = get_settlement(plant["id"], period_index=1)
        assert settlement["energy_costs_cents"] == 2480000  # 1512000 + 968000
