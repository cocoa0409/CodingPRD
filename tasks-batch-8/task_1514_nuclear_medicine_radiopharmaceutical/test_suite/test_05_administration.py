"""Calibration and dose administration: dual assay variants, the sixty-minute
window, decay floor, idempotency, and the calibrate/administer duty split."""
import pytest

from test_helpers import (
    TEST_USERS,
    make_radiopharmacist_headers,
    make_technologist_headers,
    report_spill,
    set_clock,
    setup_f18_administered,
    setup_f18_calibrated_vial,
    setup_f18_prepared_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestDualVariantAssay:
    """Same vial, same instants, same isotope: the exact and tabular variants
    legitimately diverge because the tabular method rounds at every minute step."""

    def test_exact_variant_assay_value(self, api):
        """PRD §2.5: "As a concrete illustration, 220.000 MBq of an isotope with
        a 110-minute half-life decayed over 110 minutes yields 110.000 MBq under
        the exact variant and 109.993 MBq under the tabular variant." and
        PRD §3.5: "both assay variants — `assayed_activity_exact_mbq` under the
        exact variant and `assayed_activity_tabular_mbq` under the tabular
        minute-step variant, each evaluated at the administration instant".

        Calibrated 220.000 at 08:30; administered at 10:20 (110 min, HL 110).

        Design: Difficulty/dual_variant_calc/vial_assay_exact_vs_tabular_diverge
        """
        ctx = setup_f18_administered(with_appointment=True)
        adm = ctx["administration"]
        assert adm["assayed_activity_exact_mbq"] == pytest.approx(110.000, abs=1e-9)

    def test_tabular_variant_diverges_and_window_flag_set(self, api):
        """PRD §2.5: "The variants diverge because the tabular method rounds at
        every minute step while the exact method rounds only once. As a concrete
        illustration, 220.000 MBq of an isotope with a 110-minute half-life
        decayed over 110 minutes yields 110.000 MBq under the exact variant and
        109.993 MBq under the tabular variant." and PRD §3.5: "a
        `within_admin_window` boolean that is true exactly when the
        administration instant falls inside the sixty-minute window."

        Design: Difficulty/dual_variant_calc/vial_assay_exact_vs_tabular_diverge
        """
        ctx = setup_f18_administered(with_appointment=True)
        adm = ctx["administration"]
        assert adm["assayed_activity_tabular_mbq"] == pytest.approx(109.993, abs=1e-9)
        assert adm["assayed_activity_exact_mbq"] != adm["assayed_activity_tabular_mbq"]
        assert adm["within_admin_window"] is True


class TestAdministrationWindow:
    def test_administer_61_minutes_late_rejected(self, api):
        """PRD §3.5: "The administration instant — the current clock value — must
        fall within sixty minutes of the order's `administration_scheduled_at` on
        either side: no earlier than sixty minutes before it and no later than
        sixty minutes after it, with both boundaries inclusive; outside that
        window the call is rejected with `ERR_OUTSIDE_ADMIN_WINDOW` (HTTP 409)."

        Scheduled 10:20; the clock is 11:21 (61 minutes late). The assay would
        still be well above the 10 MBq floor, so the window is the only failure
        and the vial stays CALIBRATED.

        Design: Corner/validations/administer_outside_window_rejected
        """
        ctx = setup_f18_calibrated_vial(measured_activity_mbq=220)
        set_clock("2026-08-01T11:21:00Z")
        res = api.administer_dose_vial(ctx["vial"]["id"], make_technologist_headers("tech-2"))
        validate_error(res, "ERR_OUTSIDE_ADMIN_WINDOW", expected_status=409)

        vial = validate_success(api.get_dose_vial(ctx["vial"]["id"], ADMIN), 200)
        assert vial["status"] == "CALIBRATED"


class TestCalibrationFloor:
    def test_calibrate_below_min_usable_rejected(self, api):
        """PRD §3.4: "the vial must be `PREPARED`, otherwise `ERR_INVALID_STATE`;
        and the assayed activity must be at least the isotope's
        `min_usable_activity_mbq`, otherwise the call is rejected with
        `ERR_DOSE_DECAYED_BELOW_MIN` (HTTP 409)."

        Assay 5.0 MBq against the 10 MBq floor.

        Design: Corner/validations/calibrate_below_min_usable_rejected
        """
        ctx = setup_f18_prepared_order(prescribed_activity_mbq=4)
        res = api.calibrate_dose_vial(
            ctx["vial"]["id"],
            {"measured_activity_mbq": 5},
            make_radiopharmacist_headers("rp-1"),
        )
        validate_error(res, "ERR_DOSE_DECAYED_BELOW_MIN", expected_status=409)

        vial = validate_success(api.get_dose_vial(ctx["vial"]["id"], ADMIN), 200)
        assert vial["status"] == "PREPARED"


class TestAdministrationIdempotency:
    def test_double_administer_rejected(self, api):
        """PRD §3.5: "The vial must be `CALIBRATED`, otherwise
        `ERR_INVALID_STATE`." An ADMINISTERED vial fails that precondition, and
        the rejected retry creates no second administration record.

        Design: Corner/state_machines/double_administer_rejected_invalid_state
        """
        ctx = setup_f18_administered()
        res = api.administer_dose_vial(ctx["vial"]["id"], make_technologist_headers("tech-3"))
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

        records, meta = validate_paginated(
            api.list_dose_administrations(ADMIN, params={"vial_id": ctx["vial"]["id"]})
        )
        assert meta["total_count"] == 1 and len(records) == 1
        assert records[0]["id"] == ctx["administration"]["id"]


class TestAdministerStateBeatsLicenseSafety:
    """Precedence pair: the vial is QUARANTINED (state-machine legality) while
    the license is SUSPENDED (safety family). The PRD §2.9 pipeline ranks
    state-machine legality ahead of the safety family."""

    def _quarantined_and_suspended(self, api):
        """Calibrated vial; spill quarantines the vial and holds the order;
        the license is then suspended (its hop-two cascade only touches
        ORDERED/DOSE_PREPARED orders, so this ON_HOLD order is untouched)."""
        ctx = setup_f18_calibrated_vial(measured_activity_mbq=220, with_appointment=True)
        set_clock("2026-08-01T08:45:00Z")
        report_spill(
            ctx["room"]["id"], ctx["isotope"]["id"],
            reporter_headers=make_technologist_headers("tech-1"),
            occurred_at="2026-08-01T08:45:00Z",
        )
        validate_success(api.suspend_license(ctx["license"]["id"], ADMIN), 200)
        return ctx

    def test_quarantined_vial_suspended_license_reports_invalid_state(self, api):
        """PRD §2.9: "Every request is checked against an ordered validation
        pipeline, and only the first failure encountered is reported. When
        several rules guard the same call, evaluation proceeds in this global
        precedence order: ... then state-machine legality — the generic
        invalid-transition rejection (`ERR_INVALID_STATE`) ... then the safety
        family in rank order — license suspension (`ERR_LICENSE_SUSPENDED`),
        ..."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_license_safety_on_administer
        """
        ctx = self._quarantined_and_suspended(api)
        res = api.administer_dose_vial(ctx["vial"]["id"], make_technologist_headers("tech-2"))
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_rejected_administration_leaves_no_trace(self, api):
        """PRD §3.5: "On success, an append-only administration record is
        created..." — a rejected administration creates nothing, and neither
        the QUARANTINED vial nor the ON_HOLD order changes state.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_license_safety_on_administer
        """
        ctx = self._quarantined_and_suspended(api)
        res = api.administer_dose_vial(ctx["vial"]["id"], make_technologist_headers("tech-2"))
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

        vial = validate_success(api.get_dose_vial(ctx["vial"]["id"], ADMIN), 200)
        assert vial["status"] == "QUARANTINED"
        order = validate_success(api.get_dose_order(ctx["order"]["id"], ADMIN), 200)
        assert order["status"] == "ON_HOLD"
        rows, meta = validate_paginated(
            api.list_dose_administrations(ADMIN, params={"vial_id": ctx["vial"]["id"]})
        )
        assert meta["total_count"] == 0 and rows == []


class TestAdministrationSegregationOfDuties:
    def test_calibrator_cannot_administer_same_vial(self, api):
        """PRD §2.7: "The technologist who administers a vial must not be the
        radiopharmacist who calibrated it: the administering `X-User-ID` must
        differ from the vial's `calibrated_by_user_id`. ... Violating any of the
        three pairings is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        The vial was calibrated by operator shared-1; the administration attempt
        carries the same operator id under the technologist role.

        Design: Corner/rbac/calibrator_cannot_administer_same_vial
        """
        ctx = setup_f18_calibrated_vial(measured_activity_mbq=220, calibrator_id="shared-1")
        set_clock("2026-08-01T10:20:00Z")
        res = api.administer_dose_vial(ctx["vial"]["id"], make_technologist_headers("shared-1"))
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

        vial = validate_success(api.get_dose_vial(ctx["vial"]["id"], ADMIN), 200)
        assert vial["status"] == "CALIBRATED"
