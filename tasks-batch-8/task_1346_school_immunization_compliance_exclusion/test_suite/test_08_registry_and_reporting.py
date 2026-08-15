"""State-registry reconciliation, dual-variant evaluation, and annual reporting."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_compliance_snapshot,
    assert_registry_sync_run,
    district_rollup,
    generate_snapshot,
    get_compliance,
    get_student,
    run_registry_sync,
    seed_registry_dose,
    setup_census_variant_school,
    setup_manual_plus_registry_student,
    setup_rollup_scenario,
    validate_error,
    validate_success,
)


class TestDualVariantEvaluation:

    def test_registry_import_invisible_to_local_records(self):
        """PRD section 3.8: "Because LOCAL_RECORDS counts only `MANUAL` and `CLINIC`
        sources, a registry import never moves a student's official status by
        itself; it is the REGISTRY_RECONCILED lens — the per-student compliance
        view's reconciled fields and the annual snapshot's `compliant_count` — that
        absorbs imported doses."
        PRD section 3.8: "`imported_count` counts seeded doses with no local record
        for the same student, vaccine, and dose number: each is imported as an
        ImmunizationRecord with `source` set to `REGISTRY_IMPORT` and `status` born
        `VERIFIED`."

        Design: Difficulty/dual_variant_calc/local_vs_reconciled_requirement_evaluation
        """
        student, run = setup_manual_plus_registry_student("SCH-A")
        assert_registry_sync_run(run)
        assert run["status"] == "COMPLETED"
        assert run["imported_count"] == 1

        # LOCAL_RECORDS still sees only the one MANUAL dose against a 2-dose
        # requirement, so the official status and deficiency list do not move.
        assert student["status"] == "ENROLLED_PROVISIONAL"
        assert student["deficiency_vaccine_codes"] == ["MMR"]

        compliance = get_compliance(student["id"])
        assert compliance["student_status"] == "ENROLLED_PROVISIONAL"
        assert len(compliance["requirements"]) == 1, (
            "one row per applicable requirement"
        )

    def test_registry_import_counts_in_reconciled_reporting(self):
        """PRD section 2.9: "A student can therefore be fully satisfied under
        REGISTRY_RECONCILED while still deficient under LOCAL_RECORDS — the
        registry knows about doses the district has not yet verified locally — and
        such a student is never excluded on the strength of that discrepancy, but
        is reported as compliant in the annual filing."
        PRD section 3.9: "`compliant_count` counts members whose
        REGISTRY_RECONCILED evaluation is fully satisfied at that moment — this is
        where registry reconciliation pays off (§3.8)."

        Design: Difficulty/dual_variant_calc/local_vs_reconciled_requirement_evaluation
        """
        student, run = setup_manual_plus_registry_student("SCH-A")
        assert run["imported_count"] == 1

        snapshot = generate_snapshot("SCH-A", rate_variant="CENSUS_DATE")
        assert_compliance_snapshot(snapshot)
        assert snapshot["enrolled_count"] == 1
        assert snapshot["compliant_count"] == 1, (
            "the reconciled lens counts the imported dose toward the annual filing"
        )
        assert snapshot["compliance_rate"] == pytest.approx(100.0, abs=1e-6)

        assert get_student(student["id"])["status"] == "ENROLLED_PROVISIONAL", (
            "the LOCAL_RECORDS-driven official status must not move on an import"
        )


class TestSnapshotRateVariants:

    def test_census_date_variant_excludes_withdrawn(self):
        """PRD section 3.9: "Membership in the cell is decided by the variant:
        under `CENSUS_DATE` — the official report — the denominator counts students
        of that school and grade whose `enrollment_date` is on or before the
        `census_date` and whose status is not `WITHDRAWN`; under `EVER_ENROLLED` —
        the auxiliary accountability view — withdrawn students remain in the
        denominator, so identical data yields an equal or lower rate."
        PRD section 3.9: "`compliance_rate` is one hundred times `compliant_count`
        divided by `enrolled_count`, rounded half-up to 1 decimal place; when
        `enrolled_count` is zero the rate is null rather than zero."

        Design: Difficulty/dual_variant_calc/census_vs_ever_enrolled_rate
        """
        setup_census_variant_school("SCH-R")
        snapshot = generate_snapshot("SCH-R", rate_variant="CENSUS_DATE")
        assert_compliance_snapshot(snapshot)
        assert snapshot["enrolled_count"] == 2, (
            "the WITHDRAWN student is excluded from the CENSUS_DATE denominator"
        )
        assert snapshot["compliant_count"] == 1
        assert snapshot["exempt_count"] == 0
        assert snapshot["compliance_rate"] == pytest.approx(50.0, abs=1e-6)

    def test_ever_enrolled_variant_includes_withdrawn(self):
        """PRD section 3.9: "Membership in the cell is decided by the variant:
        under `CENSUS_DATE` — the official report — the denominator counts students
        of that school and grade whose `enrollment_date` is on or before the
        `census_date` and whose status is not `WITHDRAWN`; under `EVER_ENROLLED` —
        the auxiliary accountability view — withdrawn students remain in the
        denominator, so identical data yields an equal or lower rate."

        Design: Difficulty/dual_variant_calc/census_vs_ever_enrolled_rate
        """
        setup_census_variant_school("SCH-R")
        snapshot = generate_snapshot("SCH-R", rate_variant="EVER_ENROLLED")
        assert_compliance_snapshot(snapshot)
        assert snapshot["enrolled_count"] == 3, (
            "the WITHDRAWN student remains in the EVER_ENROLLED denominator"
        )
        assert snapshot["compliant_count"] == 1
        # round(100.0 * 1 / 3, 1) half-up == 33.3
        assert snapshot["compliance_rate"] == pytest.approx(33.3, abs=1e-6)


class TestDistrictRollup:

    def test_district_rollup_nested_rounding_order(self):
        """PRD section 3.9: "The rounding order is pinned and non-negotiable: first,
        each school's rate is computed and rounded half-up to 1 decimal place on
        its own; second, the district rate is the enrollment-weighted average of
        those already-rounded school rates — the sum over schools of each rounded
        rate multiplied by that school's enrolled count, divided by the sum of
        enrolled counts — itself rounded half-up to 1 decimal place. Aggregating
        the raw counts first and rounding once is explicitly not the rule; the
        per-school rounded rate is the weighted term."

        Design: Difficulty/combinatorial_formula/district_rollup_nested_rounding_order
        """
        setup_rollup_scenario()
        rollup = district_rollup()
        # Per-school rates round first: SCH-A round(200/3, 1) == 66.7,
        # SCH-B round(100/6, 1) == 16.7. The pinned order then yields
        # round((66.7*3 + 16.7*6) / 9, 1) == 33.4. Aggregating raw counts first
        # (3/9 = 33.333...) would report 33.3 and is explicitly not the rule.
        assert rollup["district_rate"] == pytest.approx(33.4, abs=1e-6)

    def test_district_rollup_response_composition(self):
        """PRD section 3.9: "The response carries the `district_rate`, the
        `schools_included` count, and the `enrolled_total`; when no school has any
        members, `district_rate` is null."
        PRD section 3.9: "A `DistrictHealthOfficer` requests the district-wide rate
        for a `school_year` and `grade`; the rollup is computed live, using the
        current logical clock as the census date and CENSUS_DATE membership, over
        every school that has at least one member."

        Design: Difficulty/combinatorial_formula/district_rollup_nested_rounding_order
        """
        setup_rollup_scenario()
        rollup = district_rollup()
        assert rollup["schools_included"] == 2, (
            "exactly the two schools with at least one grade-K member participate"
        )
        assert rollup["enrolled_total"] == 9


class TestSnapshotGeneration:

    def test_snapshot_uses_reconciled_variant(self):
        """PRD section 3.9: "`compliant_count` counts members whose
        REGISTRY_RECONCILED evaluation is fully satisfied at that moment — this is
        where registry reconciliation pays off (§3.8)."
        PRD section 3.8: "Because LOCAL_RECORDS counts only `MANUAL` and `CLINIC`
        sources, a registry import never moves a student's official status by
        itself; it is the REGISTRY_RECONCILED lens — the per-student compliance
        view's reconciled fields and the annual snapshot's `compliant_count` — that
        absorbs imported doses."

        Design: Corner/calculations/snapshot_uses_reconciled_variant
        """
        student, run = setup_manual_plus_registry_student(
            "SCH-REG", registry_administered_date="2026-09-05T00:00:00Z"
        )
        assert run["imported_count"] == 1

        snapshot = generate_snapshot("SCH-REG", rate_variant="CENSUS_DATE")
        assert snapshot["enrolled_count"] == 1
        assert snapshot["compliant_count"] == 1
        assert snapshot["compliance_rate"] == pytest.approx(100.0, abs=1e-6)

        assert get_student(student["id"])["status"] == "ENROLLED_PROVISIONAL", (
            "LOCAL_RECORDS sees only 1 of 2 required doses, so the official "
            "status stays provisional"
        )

    def test_snapshot_zero_enrollment_rate_null(self):
        """PRD section 3.9: "`compliance_rate` is one hundred times
        `compliant_count` divided by `enrolled_count`, rounded half-up to 1 decimal
        place; when `enrolled_count` is zero the rate is null rather than zero."

        Design: Corner/calculations/snapshot_zero_enrollment_rate_null
        """
        snapshot = generate_snapshot("SCH-EMPTY", rate_variant="CENSUS_DATE")
        assert_compliance_snapshot(snapshot)
        assert snapshot["enrolled_count"] == 0
        assert snapshot["compliant_count"] == 0
        assert snapshot["compliance_rate"] is None, (
            "a zero-denominator cell must report a null rate, not 0.0"
        )
        assert snapshot["status"] == "DRAFT"

    def test_finalize_snapshot_twice_rejected(self, officer_headers):
        """PRD section 3.9: "A snapshot is born `DRAFT`. Regenerating the same cell
        — the same `school_year`, `school_code`, `grade`, and `rate_variant` —
        supersedes an existing draft, but once a `DistrictHealthOfficer` finalizes
        the snapshot (`DRAFT` → `FINALIZED`) its numbers are locked: further
        mutation of the snapshot is rejected with `ERR_SNAPSHOT_FINALIZED`, and
        regeneration of that cell is rejected with `ERR_SNAPSHOT_EXISTS`."

        Design: Corner/state_machines/finalize_snapshot_twice_rejected
        """
        snapshot = generate_snapshot("SCH-F", rate_variant="CENSUS_DATE")
        assert snapshot["status"] == "DRAFT"

        finalized = validate_success(
            api_client.finalize_compliance_snapshot(snapshot["id"], officer_headers),
            200,
        )
        assert finalized["status"] == "FINALIZED"

        resp = api_client.finalize_compliance_snapshot(snapshot["id"], officer_headers)
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_FINALIZED)
