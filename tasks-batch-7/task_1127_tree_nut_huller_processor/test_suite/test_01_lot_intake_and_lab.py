"""Lot intake, receiving-lab recording, aflatoxin gate, and reject/resample cycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_lot,
    create_aflatoxin_test_payload,
    create_grower,
    create_lot,
    create_lot_payload,
    create_sampled_lot,
    get_lot,
    make_intake_headers,
    make_lab_headers,
    record_aflatoxin,
    record_moisture_kernel,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)


class TestLotIntake:
    def test_lot_create_returns_201_with_initial_state_and_system_fields(self, api):
        """PRD (Field Lot Intake): "The lot is born in RECEIVED status, and at that
        moment every laboratory-derived field on it is null."
        PRD (Common Resource Properties): "version (integer): a system-managed
        integer that increments by one on every mutation."

        Design: Corner/entities/lot_create_returns_201_with_initial_state_and_system_fields
        """
        grower = create_grower()
        resp = api.create_lot(
            create_lot_payload(grower_id=grower["id"], gross_weight_lbs=3000),
            make_intake_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert_lot(data)
        assert data["status"] == "RECEIVED"
        assert data["version"] == 1
        assert data["created_at"].startswith("2026-05-01T00:00:00")

    def test_lot_create_missing_required_gross_weight_rejected(self, api):
        """PRD (Field Lot Intake): "the gross_weight_lbs — the scale weight at
        intake, which must be greater than zero."
        PRD (Validation Order): "Required fields are present, types are correct,
        enum values belong to their declared sets ... otherwise
        ERR_INVALID_REQUEST (400)".

        Design: Corner/entities/lot_create_missing_required_gross_weight_rejected
        """
        grower = create_grower()
        resp = api.create_lot(
            {"grower_id": grower["id"], "variety": "Nonpareil"},
            make_intake_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_lot_create_system_field_status_input_ignored(self, api):
        """PRD (Field Lot Intake): "The lot is born in RECEIVED status, and at
        that moment every laboratory-derived field on it is null". A
        client-supplied status field is not among the POST /lots inputs
        (grower_id, variety, gross_weight_lbs) and cannot change that.

        Design: Corner/entities/lot_create_system_field_status_input_ignored
        """
        grower = create_grower()
        resp = api.create_lot(
            {
                "grower_id": grower["id"],
                "variety": "Nonpareil",
                "gross_weight_lbs": 3000,
                "status": "SETTLED",
            },
            make_intake_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "RECEIVED", (
            f"input status must be ignored; lot born RECEIVED, got {data['status']}"
        )

    def test_lot_create_unknown_grower_fk_rejected(self, api):
        """PRD (Referential Integrity): "body foreign-key fields (grower_id,
        lot_id, dryer_id, bin_id, contract_id, buyer_id) must reference existing
        entities; otherwise the matching per-entity not-found error (404)" —
        ERR_GROWER_NOT_FOUND for grower references.

        Design: Corner/entities/lot_create_unknown_grower_fk_rejected
        """
        resp = api.create_lot(
            {
                "grower_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                "variety": "Nonpareil",
                "gross_weight_lbs": 3000,
            },
            make_intake_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_GROWER_NOT_FOUND)


class TestLabTestConditionalFields:
    def test_lab_test_aflatoxin_missing_ppb_rejected(self, api):
        """PRD (Field Lot Intake): "An AFLATOXIN test requires aflatoxin_ppb (zero
        or greater, parts per billion). Every other measurement field is
        forbidden." and "either violation is rejected with ERR_INVALID_REQUEST".

        Design: Corner/validations/lab_test_aflatoxin_missing_ppb_rejected
        """
        grower = create_grower()
        lot = create_lot(grower["id"], gross_weight_lbs=2000)
        resp = api.create_lab_test(
            {"lot_id": lot["id"], "test_type": "AFLATOXIN"}, make_lab_headers()
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_lab_test_foreign_field_for_type_rejected(self, api):
        """PRD (Field Lot Intake): "supplying a field the type forbids is as much
        an error as omitting one it requires — either violation is rejected with
        ERR_INVALID_REQUEST".

        Design: Corner/validations/lab_test_foreign_field_for_type_rejected
        """
        grower = create_grower()
        lot = create_lot(grower["id"], gross_weight_lbs=2000)
        resp = api.create_lab_test(
            {
                "lot_id": lot["id"],
                "test_type": "AFLATOXIN",
                "aflatoxin_ppb": 3.0,
                "moisture_pct": 5.0,
            },
            make_lab_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_kernel_grade_test_requires_processed_lot(self, api):
        """PRD (Field Lot Intake): "A kernel grade may only be recorded against a
        lot in PROCESSED status; against any other state the recording is
        rejected with ERR_INVALID_STATE."

        Design: Corner/validations/kernel_grade_test_requires_processed_lot
        """
        _, lot = create_sampled_lot()
        resp = api.create_lab_test(
            {
                "lot_id": lot["id"],
                "test_type": "KERNEL_GRADE",
                "edible_kernel_pct": 0.80,
                "size_spec": "SPEC_23_25",
            },
            make_lab_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestAflatoxinThreshold:
    def test_aflatoxin_below_boundary_passes(self, api):
        """PRD (Field Lot Intake): "Every recorded aflatoxin test receives an
        `aflatoxin_verdict`" and "A `PASS` recorded against a `SAMPLED` lot
        advances it to `GRADED` and copies the sample's value onto the lot's
        `aflatoxin_ppb`."

        Design: Difficulty/boundary_precision_check/aflatoxin_threshold_twenty_ppb
        """
        grower = create_grower()
        lot = create_lot(grower["id"], gross_weight_lbs=2000)
        record_moisture_kernel(lot["id"])
        test = record_aflatoxin(lot["id"], aflatoxin_ppb=19.9)
        assert test["aflatoxin_verdict"] == "PASS"
        updated = get_lot(lot["id"])
        assert updated["status"] == "GRADED"
        assert updated["aflatoxin_ppb"] == 19.9

    def test_aflatoxin_boundary_value_twenty_fails(self, api):
        """PRD (Field Lot Intake): "the boundary value 20.0 itself fails. A
        `PASS` recorded against a `SAMPLED` lot advances it to `GRADED`" — and
        a FAIL "drives the lot to `REJECTED`".

        Design: Difficulty/boundary_precision_check/aflatoxin_threshold_twenty_ppb
        """
        grower = create_grower()
        lot = create_lot(grower["id"], gross_weight_lbs=2000)
        record_moisture_kernel(lot["id"])
        test = record_aflatoxin(lot["id"], aflatoxin_ppb=20.0)
        assert test["aflatoxin_verdict"] == "FAIL"
        updated = get_lot(lot["id"])
        assert updated["status"] == "REJECTED"
        assert updated["aflatoxin_ppb"] == 20.0


class TestRejectResampleCycle:
    def test_resample_returns_lot_to_sampled_and_clears_aflatoxin(self, api):
        """PRD (Field Lot Intake): "An IntakeOperator may resample a REJECTED
        lot, cycling it back to SAMPLED and resetting its aflatoxin_ppb to null
        while the lot awaits a new aflatoxin test".

        Design: Difficulty/non_linear_state_machine/lot_reject_resample_cycle
        """
        grower = create_grower()
        lot = create_lot(grower["id"], gross_weight_lbs=3000)
        record_moisture_kernel(lot["id"])
        record_aflatoxin(lot["id"], aflatoxin_ppb=25.0)
        assert get_lot(lot["id"])["status"] == "REJECTED"

        resp = api.resample_lot(lot["id"], make_intake_headers())
        data = validate_success(resp)
        assert data["status"] == "SAMPLED"
        after = get_lot(lot["id"])
        assert after["status"] == "SAMPLED"
        assert after["aflatoxin_ppb"] is None

    def test_resample_then_pass_advances_lot_to_graded(self, api):
        """PRD (Field Lot Intake): "only a subsequent `PASS` — which transitions
        the lot from `SAMPLED` to `GRADED` as usual — releases them back to
        `STORED` and returns any `BLOCKED` shipment whose allocated placements
        are all stored again to `PLANNED`."

        Design: Difficulty/non_linear_state_machine/lot_reject_resample_cycle
        """
        grower = create_grower()
        lot = create_lot(grower["id"], gross_weight_lbs=3000)
        record_moisture_kernel(lot["id"])
        record_aflatoxin(lot["id"], aflatoxin_ppb=25.0)
        api.resample_lot(lot["id"], make_intake_headers())
        record_aflatoxin(lot["id"], aflatoxin_ppb=4.0)
        after = get_lot(lot["id"])
        assert after["status"] == "GRADED"
        assert after["aflatoxin_ppb"] == 4.0

    def test_resample_from_received_returns_invalid_state(self, api):
        """PRD (Field Lot Intake): "Both actions require the lot to be REJECTED;
        from any other state they are rejected with ERR_INVALID_STATE."

        Design: Corner/state_machines/resample_from_received_returns_invalid_state
        """
        grower = create_grower()
        lot = create_lot(grower["id"], gross_weight_lbs=3000)
        resp = api.resample_lot(lot["id"], make_intake_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_lot(lot["id"])["status"] == "RECEIVED"


class TestProvisionalKernelEstimate:
    def test_provisional_estimate_moisture_branch_inactive(self, api):
        """PRD (Field Lot Intake): "provisional_kernel_lbs, computed as the lot's
        gross_weight_lbs multiplied by its intake_kernel_pct, multiplied by one
        minus intake_fm_pct, and then discounted by one percent for every full
        point of intake moisture above the 8.0 percent standard (no discount
        applies when the moisture is at or below standard); the result is
        rounded half-up to 2 decimal places."
        PRD: "requires_drying is true when the intake moisture exceeds the 8.0
        percent standard moisture level, false once the intake moisture is known
        to be at or below it".

        Design: Difficulty/combinatorial_formula/provisional_kernel_multi_input_shrink
        """
        # moisture 7.0 <= 8.0: no shrink. 4000 * 0.50 * (1 - 0.01) * 1.00 = 1980.00
        grower = create_grower()
        lot = create_lot(grower["id"], gross_weight_lbs=4000)
        record_moisture_kernel(
            lot["id"], moisture_pct=7.0, kernel_pct=0.50, foreign_material_pct=0.01
        )
        updated = get_lot(lot["id"])
        assert updated["provisional_kernel_lbs"] == pytest.approx(1980.00, abs=0.01)
        assert updated["requires_drying"] is False

    def test_provisional_estimate_moisture_branch_active(self, api):
        """PRD (Field Lot Intake): "discounted by one percent for every full
        point of intake moisture above the 8.0 percent standard" and
        "requires_drying is true when the intake moisture exceeds the 8.0
        percent standard".

        Design: Difficulty/combinatorial_formula/provisional_kernel_multi_input_shrink
        """
        # moisture 9.5: excess 1.5 -> factor (1 - 0.01*1.5) = 0.985.
        # 4000 * 0.50 * 0.99 * 0.985 = 1950.30
        grower = create_grower()
        lot = create_lot(grower["id"], gross_weight_lbs=4000)
        record_moisture_kernel(
            lot["id"], moisture_pct=9.5, kernel_pct=0.50, foreign_material_pct=0.01
        )
        updated = get_lot(lot["id"])
        assert updated["provisional_kernel_lbs"] == pytest.approx(1950.30, abs=0.01)
        assert updated["requires_drying"] is True
