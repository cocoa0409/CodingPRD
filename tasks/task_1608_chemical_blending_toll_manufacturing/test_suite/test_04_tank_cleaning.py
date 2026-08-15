"""Tank cleaning and QA validation: maker-checker protocol, segregation of
duties, the residue limit, and the cyclic cleaning axis (PRD §3.5, §2.6)."""
from test_helpers import (
    ApiErrorId,
    assert_cleaning_record,
    assert_tank,
    create_tank,
    get_tank,
    make_operator_headers,
    make_validator_headers,
    open_cleaning_record,
    setup_completed_batch,
    submit_cleaning_record,
    validate_cleaning_record,
    validate_error,
    validate_success,
)


class TestSegregationOfDuties:
    def test_validator_same_as_creator_rejected(self, api):
        """PRD §3.5: "Two people must be involved: the validator's `X-User-ID`
        must differ from the `X-User-ID` that created the record, or the
        validation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) —
        this applies to both PASS and FAIL decisions."

        Design: Corner/state_machines/cleaning_validator_same_as_creator_returns_segregation_of_duties
        """
        tank = create_tank()
        operator_headers = make_operator_headers("user-op-1")
        record = open_cleaning_record(tank["id"],
                                      operator_headers=operator_headers)
        submit_cleaning_record(tank["id"], record["id"],
                               operator_headers=operator_headers)

        # Same human, now wearing the QAValidator hat, attempts the check.
        resp = api.validate_cleaning_record(
            tank["id"], record["id"], "PASS",
            make_validator_headers("user-op-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


class TestCleaningCycleRevalidation:
    def test_failed_validation_returns_tank_to_dirty(self, api):
        """PRD §3.5: "On FAIL the record becomes `FAILED` and the tank returns
        to `DIRTY`, ready for another attempt."

        Design: Difficulty/non_linear_state_machine/tank_cleaning_state_machine_cyclic_revalidation
        """
        tank = create_tank(capacity_l=500, working_capacity_l=500)
        record = open_cleaning_record(tank["id"], method="CAUSTIC_CIP",
                                      residue_ppm=200)
        submit_cleaning_record(tank["id"], record["id"])
        validated = validate_cleaning_record(tank["id"], record["id"],
                                             decision="FAIL")
        assert_cleaning_record(validated)
        assert validated["validation_outcome"] == "FAILED"

        tank_after = get_tank(tank["id"])
        assert_tank(tank_after)
        assert tank_after["cleaning_state"] == "DIRTY", (
            f"FAIL must loop the cleaning axis back to DIRTY, got "
            f"{tank_after['cleaning_state']}")

    def test_reclean_after_failure_reaches_clean_validated(self, api):
        """PRD §3.5: "On PASS the record's `validation_outcome` becomes
        `PASSED`, `validated_by` records the validator's `X-User-ID`, the tank
        moves to `CLEAN_VALIDATED`, and its `last_product_ghs` is cleared to
        null."

        Design: Difficulty/non_linear_state_machine/tank_cleaning_state_machine_cyclic_revalidation
        """
        tank = create_tank(capacity_l=500, working_capacity_l=500)
        first = open_cleaning_record(tank["id"], method="CAUSTIC_CIP",
                                     residue_ppm=200)
        submit_cleaning_record(tank["id"], first["id"])
        validate_cleaning_record(tank["id"], first["id"], decision="FAIL")
        assert get_tank(tank["id"])["cleaning_state"] == "DIRTY"

        # Second attempt on the cycled-back tank.
        second = open_cleaning_record(
            tank["id"], method="STEAM", started_at="2026-08-06T08:00:00Z",
            completed_at="2026-08-06T09:30:00Z", residue_ppm=30)
        submit_cleaning_record(tank["id"], second["id"])
        passed = validate_cleaning_record(tank["id"], second["id"],
                                          decision="PASS")
        assert passed["validation_outcome"] == "PASSED"
        assert passed["validated_by"] is not None

        tank_after = get_tank(tank["id"])
        assert tank_after["cleaning_state"] == "CLEAN_VALIDATED"
        assert tank_after["last_product_ghs"] is None


class TestResidueLimitBoundary:
    def test_residue_at_limit_passes_validation(self, api):
        """PRD §2.6: "The acceptance limit is 50 parts per million: a cleaning
        record reporting `residue_ppm` at or below that limit may pass
        validation, while anything above it may not." PRD §3.5: "when the tank
        has a non-null `last_product_ghs`, the measured `residue_ppm` to be at
        most the 50-parts-per-million limit".

        Design: Difficulty/boundary_precision_check/residue_ppm_at_50_threshold_boundary
        """
        # Run a FLAMMABLE batch to completion so the tank holds a non-null
        # last_product_ghs and returns to DIRTY.
        ctx = setup_completed_batch(ghs_class="FLAMMABLE", density=0.75,
                                    yield_pct=98, batch_size_l=100,
                                    charge_qty_kg=80, actual_output_kg=75,
                                    heel_returned_kg=5)
        tank = get_tank(ctx["tank"]["id"])
        assert tank["cleaning_state"] == "DIRTY"
        assert tank["last_product_ghs"] == "FLAMMABLE"

        # Exactly at the 50 ppm limit: PASS must be accepted.
        record = open_cleaning_record(
            tank["id"], method="SOLVENT_FLUSH",
            started_at="2026-10-21T08:00:00Z",
            completed_at="2026-10-21T09:00:00Z", residue_ppm=50)
        submit_cleaning_record(tank["id"], record["id"])
        validated = validate_cleaning_record(tank["id"], record["id"],
                                             decision="PASS")
        assert validated["validation_outcome"] == "PASSED", (
            "residue_ppm=50 satisfies the at-or-below-50 limit")

        tank_after = get_tank(tank["id"])
        assert tank_after["cleaning_state"] == "CLEAN_VALIDATED"
        assert tank_after["last_product_ghs"] is None, (
            "Validated cleaning clears last_product_ghs to null")

    def test_never_used_tank_passes_residue_regardless(self, api):
        """PRD §3.5: "a tank that has never held product always passes the
        residue test."

        Design: Difficulty/boundary_precision_check/residue_ppm_at_50_threshold_boundary
        """
        tank = create_tank(capacity_l=500, working_capacity_l=500)
        assert tank["last_product_ghs"] is None

        record = open_cleaning_record(tank["id"], residue_ppm=9999)
        submit_cleaning_record(tank["id"], record["id"])
        validated = validate_cleaning_record(tank["id"], record["id"],
                                             decision="PASS")
        assert validated["validation_outcome"] == "PASSED", (
            "A never-used tank always passes the residue test")
        assert get_tank(tank["id"])["cleaning_state"] == "CLEAN_VALIDATED"
