"""Acuity snapshots, the required-nurses derivation, and shift gating."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_acuity_snapshot,
    create_full_matrix,
    create_nurse,
    create_unit,
    make_charge_nurse_headers,
    submit_snapshot,
    validate_error,
    validate_success,
)


def _icu_unit_with_matrix(name):
    unit = create_unit(name=name, unit_type="ICU", bed_count=12,
                       incentive_budget_cents=500000)
    create_full_matrix("ICU")
    return unit


class TestSnapshotCreation:

    def test_snapshot_total_census_computed(self):
        """PRD section 3.2: "A snapshot enters directly in `SUBMITTED` status —
        there is no draft phase. From its census counts the system derives
        `total_census`, the plain sum of the four census fields".

        Design: Corner/entities/snapshot_total_census_computed
        """
        unit = _icu_unit_with_matrix("ICU S")
        resp = api_client.create_acuity_snapshot(
            {"unit_id": unit["id"], "shift_date": "2026-08-11",
             "shift_code": "NIGHT", "census_low": 3, "census_moderate": 2,
             "census_high": 1, "census_critical": 2},
            make_charge_nurse_headers("charge-snap-1"),
        )
        data = validate_success(resp, expected_status=201)
        assert_acuity_snapshot(data)
        assert data["total_census"] == 8, \
            f"total_census must be the plain sum 3+2+1+2=8, got {data['total_census']}"
        assert data["status"] == "SUBMITTED"

    def test_snapshot_requires_complete_matrix_rejected(self):
        """PRD section 3.2: "Submission is only possible once all four staffing
        matrix rules exist for the unit's `unit_type`; if any of the four is
        missing, the submission is rejected with `ERR_MATRIX_RULE_MISSING`
        (HTTP 422)."

        Design: Corner/entities/snapshot_requires_complete_matrix_rejected
        """
        unit = create_unit(name="SD V", unit_type="STEP_DOWN", bed_count=16,
                           incentive_budget_cents=500000)
        for level, ratio in (("LOW", 4), ("MODERATE", 3), ("HIGH", 2)):
            validate_success(api_client.create_matrix_rule(
                {"unit_type": "STEP_DOWN", "acuity_level": level,
                 "patients_per_nurse": ratio}, ADMIN), expected_status=201)
        resp = api_client.create_acuity_snapshot(
            {"unit_id": unit["id"], "shift_date": "2026-08-10",
             "shift_code": "DAY", "census_low": 4, "census_moderate": 2,
             "census_high": 1, "census_critical": 0},
            make_charge_nurse_headers("charge-snap-2"),
        )
        validate_error(resp, ApiErrorId.ERR_MATRIX_RULE_MISSING)


class TestRequiredNursesDerivation:
    """Difficulty instance: required_nurses_multi_level_ceil_floor."""

    def test_required_nurses_multi_level_exact_ceils(self):
        """PRD section 3.2: "For each acuity level, the census at that level is
        divided by the `patients_per_nurse` of the matrix rule for this unit's
        type at that level, and the quotient is rounded up to a whole nurse; a
        level with zero patients contributes zero. The four per-level figures
        are then summed, and `required_nurses` is the greater of two and that
        sum — every slot demands at least two nurses no matter how light the
        census. The per-level rounding-up happens before the summation, and
        that order is pinned."

        Design: Difficulty/combinatorial_formula/required_nurses_multi_level_ceil_floor
        """
        unit = _icu_unit_with_matrix("ICU East")
        resp = api_client.create_acuity_snapshot(
            {"unit_id": unit["id"], "shift_date": "2026-08-10",
             "shift_code": "DAY", "census_low": 2, "census_moderate": 3,
             "census_high": 2, "census_critical": 1},
            make_charge_nurse_headers("charge-req-1"),
        )
        data = validate_success(resp, expected_status=201)
        # ceil(2/4) + ceil(3/3) + ceil(2/2) + ceil(1/1) = 1+1+1+1
        assert data["required_nurses"] == 4, \
            f"expected 4 from exact per-level ceils, got {data['required_nurses']}"
        assert data["total_census"] == 8

    def test_required_nurses_floor_engages_over_raw_sum(self):
        """PRD section 3.2: "The four per-level figures are then summed, and
        `required_nurses` is the greater of two and that sum — every slot
        demands at least two nurses no matter how light the census."

        Design: Difficulty/combinatorial_formula/required_nurses_multi_level_ceil_floor
        """
        unit = _icu_unit_with_matrix("ICU East Floor")
        resp = api_client.create_acuity_snapshot(
            {"unit_id": unit["id"], "shift_date": "2026-08-10",
             "shift_code": "NIGHT", "census_low": 1, "census_moderate": 0,
             "census_high": 0, "census_critical": 0},
            make_charge_nurse_headers("charge-req-2"),
        )
        data = validate_success(resp, expected_status=201)
        # raw sum ceil(1/4) = 1 raised to the floor of 2
        assert data["required_nurses"] == 2, \
            f"floor of 2 must engage over raw sum 1, got {data['required_nurses']}"


class TestRatioBoundary:
    """Difficulty instance: exact_ratio_multiple_required_nurses."""

    def test_exact_ratio_multiple_not_overcounted(self):
        """PRD section 3.2: "For each acuity level, the census at that level is
        divided by the `patients_per_nurse` of the matrix rule for this unit's
        type at that level, and the quotient is rounded up to a whole nurse".

        Design: Difficulty/boundary_precision_check/exact_ratio_multiple_required_nurses
        """
        unit = _icu_unit_with_matrix("ICU I")
        resp = api_client.create_acuity_snapshot(
            {"unit_id": unit["id"], "shift_date": "2026-08-10",
             "shift_code": "DAY", "census_low": 8, "census_moderate": 0,
             "census_high": 0, "census_critical": 0},
            make_charge_nurse_headers("charge-rat-1"),
        )
        data = validate_success(resp, expected_status=201)
        # ceil(8/4) == 2 exactly
        assert data["required_nurses"] == 2, \
            f"exact ratio multiple 8 at 1:4 must give 2, got {data['required_nurses']}"

    def test_one_patient_over_ratio_crosses_boundary(self):
        """PRD section 3.2: "the quotient is rounded up to a whole nurse; a
        level with zero patients contributes zero."

        Design: Difficulty/boundary_precision_check/exact_ratio_multiple_required_nurses
        """
        unit = _icu_unit_with_matrix("ICU I Plus")
        resp = api_client.create_acuity_snapshot(
            {"unit_id": unit["id"], "shift_date": "2026-08-10",
             "shift_code": "NIGHT", "census_low": 9, "census_moderate": 0,
             "census_high": 0, "census_critical": 0},
            make_charge_nurse_headers("charge-rat-2"),
        )
        data = validate_success(resp, expected_status=201)
        # ceil(9/4) == 3 — the 9th patient crosses the ratio boundary
        assert data["required_nurses"] == 3, \
            f"9 patients at 1:4 must round up to 3, got {data['required_nurses']}"


class TestShiftCreationGates:

    def test_shift_creation_requires_snapshot_rejected(self):
        """PRD section 3.3: "a `SUBMITTED` acuity snapshot must already exist
        for exactly that slot, and its absence is rejected with
        `ERR_ACUITY_SNAPSHOT_REQUIRED` (HTTP 422)."

        Design: Corner/entities/shift_creation_requires_snapshot_rejected
        """
        unit = _icu_unit_with_matrix("ICU U")
        resp = api_client.create_shift(
            {"unit_id": unit["id"], "shift_date": "2026-08-13",
             "shift_code": "NIGHT"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ACUITY_SNAPSHOT_REQUIRED)

    def test_shift_duplicate_slot_rejected(self):
        """PRD section 3.3: "The slot is unique: a second shift for the same
        (unit, date, code) triple is rejected with `ERR_SHIFT_ALREADY_EXISTS`."

        Design: Corner/entities/shift_duplicate_slot_rejected
        """
        unit = _icu_unit_with_matrix("ICU T")
        cn = create_nurse(full_name="T Charge", employment_type="CORE",
                          competencies=["ICU"], base_hourly_rate_cents=7000,
                          home_unit_id=unit["id"], charge_qualified=True)
        submit_snapshot(unit["id"], "2026-08-12", "DAY", (4, 0, 0, 0),
                        as_headers=make_charge_nurse_headers(cn["id"]))
        first = api_client.create_shift(
            {"unit_id": unit["id"], "shift_date": "2026-08-12",
             "shift_code": "DAY"},
            ADMIN,
        )
        validate_success(first, expected_status=201)
        resp = api_client.create_shift(
            {"unit_id": unit["id"], "shift_date": "2026-08-12",
             "shift_code": "DAY"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SHIFT_ALREADY_EXISTS)
