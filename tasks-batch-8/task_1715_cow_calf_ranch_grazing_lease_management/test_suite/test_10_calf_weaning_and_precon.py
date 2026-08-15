"""Calf crop: adjusted 205-day weaning weights, the parallel wean/precon axes,
preconditioning certification gates, and vaccine spacing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_date_field,
    assert_pct1,
    create_calf_crop,
    create_sale_lot_payload,
    drive_season_to_gestation,
    enroll_preconditioning,
    get_calf_crop,
    get_success_data,
    record_vaccine,
    record_weaning,
    set_clock,
    setup_enrolled_crop,
    setup_ranch_with_group,
    setup_weaned_crop,
    validate_error,
    validate_success,
)

HERD_MGR = TEST_USERS["herd_manager_headers"]
SALES_AGENT = TEST_USERS["sales_agent_headers"]


def _unweaned_crop(steer_head=100, heifer_head=60):
    ranch, group = setup_ranch_with_group()
    season = drive_season_to_gestation(ranch["id"], group["id"],
                                       exposed_head_count=50)
    crop = create_calf_crop(season["id"], ranch["id"], steer_head=steer_head,
                            heifer_head=heifer_head)
    return ranch, crop


class TestAdjusted205Weights:
    def test_age_only_variant(self, api):
        """PRD §3.6: "The age-only variant, `adj205_age_only_lbs`, takes the
        difference between average weaning weight and average birth weight,
        divides it by the average weaning age in days, multiplies by 205, adds
        the average birth weight back, and rounds half-up to 1 decimal place"

        Design: Difficulty/dual_variant_calc/adj205_age_only_vs_dam_adjusted
        """
        ctx = setup_weaned_crop(avg_dam_age_years=2)
        crop = ctx["crop"]
        assert crop["wean_status"] == "WEANED"
        # (560 - 80) / 200 x 205 + 80 = 572.0
        assert_pct1(crop["adj205_age_only_lbs"], 572.0)

    def test_dam_adjusted_variant_diverges_by_54(self, api):
        """PRD §3.6: "The dam-adjusted variant, `adj205_dam_adjusted_lbs`, adds
        a dam-age adjustment to the age-only figure and is likewise rounded
        half-up to 1 decimal place: 54 pounds when the average dam age is two
        years, 20 pounds when it is three years, no adjustment for dams aged
        four through ten years, and 20 pounds again for dams eleven years or
        older. For a crop whose dams average two years old, the two variants
        therefore diverge by exactly +54.0 pounds."

        Design: Difficulty/dual_variant_calc/adj205_age_only_vs_dam_adjusted
        """
        ctx = setup_weaned_crop(avg_dam_age_years=2)
        crop = ctx["crop"]
        assert_pct1(crop["adj205_age_only_lbs"], 572.0)
        assert_pct1(crop["adj205_dam_adjusted_lbs"], 626.0, "572.0 + 54")
        assert abs(crop["adj205_dam_adjusted_lbs"]
                   - crop["adj205_age_only_lbs"] - 54.0) < 0.05


class TestParallelAxes:
    def test_enroll_moves_precon_axis_only_and_certify_needs_weaned(self, api):
        """PRD §3.6: "Enrolling the crop moves `precon_status` from `NONE` to
        `ENROLLED` and is permitted even while the calves are still `UNWEANED` —
        enrollment is a program signup, not a biological event."
        PRD §3.6: "It must be `WEANED`, failing with `ERR_CROP_NOT_WEANED`
        (HTTP 400) otherwise."

        Design: Difficulty/non_linear_state_machine/calf_crop_parallel_wean_precon_axes
        """
        _ranch, crop = _unweaned_crop()
        assert crop["wean_status"] == "UNWEANED"
        assert crop["precon_status"] == "NONE"

        enrolled = enroll_preconditioning(crop["id"])
        assert enrolled["precon_status"] == "ENROLLED"
        assert enrolled["wean_status"] == "UNWEANED", (
            "the precon axis moved; the wean axis is untouched"
        )
        resp = api.certify_preconditioning(crop["id"], HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_CROP_NOT_WEANED,
                       expected_status=400)

    def test_weaning_moves_wean_axis_only(self, api):
        """PRD §3.6: "Recording weaning moves the crop from `UNWEANED` to
        `WEANED` and computes both variants of the adjusted 205-day weight,
        which sit null until that moment."
        PRD §3.6: "Preconditioning runs on its own axis, independent of
        weaning."

        Design: Difficulty/non_linear_state_machine/calf_crop_parallel_wean_precon_axes
        """
        _ranch, crop = _unweaned_crop()
        enroll_preconditioning(crop["id"])
        set_clock("2026-09-15T00:00:00Z")
        weaned = record_weaning(crop["id"], avg_dam_age_years=6)
        assert weaned["wean_status"] == "WEANED"
        assert weaned["precon_status"] == "ENROLLED", (
            "the wean axis moved; the precon axis is untouched"
        )
        # Dam age 6 is inside the 4-10 band: no adjustment.
        assert_pct1(weaned["adj205_age_only_lbs"], 572.0)
        assert_pct1(weaned["adj205_dam_adjusted_lbs"], 572.0)


class TestCertifyDayBoundary:
    def test_certify_at_day_44_rejected(self, api):
        """PRD §3.6: "And the current date must be at least 45 days past the
        `weaning_date` — exactly 45 days qualifies — failing with
        `ERR_PRECON_DAYS_INSUFFICIENT` (HTTP 422) when fewer have elapsed."

        Design: Difficulty/boundary_precision_check/precon_certify_45_day_boundary
        """
        ctx = setup_enrolled_crop()  # weaned 2026-09-15, vaccines on record
        set_clock("2026-10-29T00:00:00Z")  # day 44
        resp = api.certify_preconditioning(ctx["crop"]["id"], HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_PRECON_DAYS_INSUFFICIENT,
                       expected_status=422)
        assert get_calf_crop(ctx["crop"]["id"])["precon_status"] == "ENROLLED"

    def test_certify_at_exactly_day_45_admitted(self, api):
        """PRD §3.6: "And the current date must be at least 45 days past the
        `weaning_date` — exactly 45 days qualifies — failing with
        `ERR_PRECON_DAYS_INSUFFICIENT` (HTTP 422) when fewer have elapsed. A
        crop that clears all four moves from `ENROLLED` to `CERTIFIED`."

        Design: Difficulty/boundary_precision_check/precon_certify_45_day_boundary
        """
        ctx = setup_enrolled_crop()
        set_clock("2026-10-30T00:00:00Z")  # exactly day 45
        certified = validate_success(api.certify_preconditioning(
            ctx["crop"]["id"], HERD_MGR))
        assert certified["precon_status"] == "CERTIFIED"


class TestPreconGates:
    def test_certify_vaccine_incomplete_rejected(self, api):
        """PRD §3.6: "Both vaccine rounds must be on record, failing with
        `ERR_PRECON_VACCINE_INCOMPLETE` (HTTP 422) when either is missing."

        Design: Corner/validations/certify_vaccine_incomplete_rejected
        """
        ctx = setup_weaned_crop(steer_head=40, heifer_head=60)
        crop = ctx["crop"]
        enroll_preconditioning(crop["id"])
        record_vaccine(crop["id"], 1, "2026-09-20")
        set_clock("2026-11-04T00:00:00Z")  # day 50 — the day count is satisfied
        resp = api.certify_preconditioning(crop["id"], HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_PRECON_VACCINE_INCOMPLETE,
                       expected_status=422)
        assert get_calf_crop(crop["id"])["precon_status"] == "ENROLLED"

    def test_certify_not_enrolled_rejected(self, api):
        """PRD §3.6: "The crop must be `ENROLLED`, or the attempt fails with
        `ERR_PRECON_NOT_ENROLLED` (HTTP 400)."

        Design: Corner/validations/certify_not_enrolled_rejected
        """
        ctx = setup_weaned_crop(steer_head=40, heifer_head=60)
        set_clock("2026-11-04T00:00:00Z")
        resp = api.certify_preconditioning(ctx["crop"]["id"], HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_PRECON_NOT_ENROLLED,
                       expected_status=400)

    def test_vaccine_spacing_rejected(self, api):
        """PRD §3.6: "The second round requires the first to already be on
        record and must fall at least 14 days after it — recording round two
        before round one, or inside that 14-day spacing, is rejected with
        `ERR_VACCINE_SPACING_VIOLATION` (HTTP 422)."

        Design: Corner/validations/vaccine_spacing_rejected
        """
        ctx = setup_weaned_crop(steer_head=40, heifer_head=60)
        crop = ctx["crop"]
        enroll_preconditioning(crop["id"])
        record_vaccine(crop["id"], 1, "2026-09-20")
        # 2026-09-30 is 10 days after round 1 — inside the spacing.
        resp = api.record_vaccine(crop["id"],
                                  {"round_number": 2,
                                   "vaccine_date": "2026-09-30"}, HERD_MGR)
        validate_error(resp, ApiErrorId.ERR_VACCINE_SPACING_VIOLATION,
                       expected_status=422)
        # Exactly 14 days passes.
        ok = record_vaccine(crop["id"], 2, "2026-10-04")
        assert_date_field(ok["vaccine_round_2_date"], "2026-10-04")

    def test_lot_create_unweaned_crop_rejected(self, api):
        """PRD §3.7: "Creation enforces the marketing gates: the crop must be
        `WEANED` (`ERR_CROP_NOT_WEANED`), its lifecycle must still be `ACTIVE` —
        a closed crop yields `ERR_ALREADY_TERMINAL`"

        Design: Corner/validations/lot_create_unweaned_crop_rejected
        """
        ranch, crop = _unweaned_crop(steer_head=40, heifer_head=60)
        resp = api.create_sale_lot(
            create_sale_lot_payload(crop["id"], ranch["id"], lot_class="STEER",
                                    head_count=10), SALES_AGENT)
        validate_error(resp, ApiErrorId.ERR_CROP_NOT_WEANED, expected_status=400)
