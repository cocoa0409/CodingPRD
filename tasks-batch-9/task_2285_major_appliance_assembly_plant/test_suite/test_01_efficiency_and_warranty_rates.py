"""Two calculations that each publish a second, different figure from one data set.

The efficiency index is read twice — provisionally from the latest measurement of
each type and bindingly from every measurement of each type — and a part's field
failure intensity is reported both per shipped cohort unit and per service hour.
"""

from test_helpers import (
    QUALITY_INSPECTOR_HEADERS,
    WARRANTY_ANALYST_HEADERS,
    AssemblyStatus,
    CertificationTier,
    Disposition,
    QualityStatus,
    WarrantyReturnStatus,
    approx2,
    base_plant_with_shift,
    design_defect_return,
    gated_unit,
    read_part,
    read_unit,
    set_clock,
    shipped_unit,
    validate_success,
)


class TestProvisionalVersusCertificationIndex:
    """One unit, three measurements, two indices."""

    def test_provisional_index_uses_only_the_latest_test_of_each_type(self, api):
        """Two energy tests and one water test read provisionally as 0.94.

        "The **provisional** variant, published as `provisional_efficiency_index`
        on every unit read while `quality_status` is anything other than
        `CERTIFIED`, uses for each of `ENERGY` and `WATER` only the single most
        recent `RECORDED` test of that type, ordered by `created_at` descending
        with `id` descending as the tie-break; averaging a single rounded ratio is
        of course the identity, so the provisional index moves with the latest
        measurement."

        Design: Difficulty/dual_variant_calc/efficiency_provisional_as_tested_vs_certification_average
        """
        plant = base_plant_with_shift(api)
        unit = gated_unit(api, plant, 1, energy=[420.00, 380.00], water=[184.00])

        before = validate_success(
            api.get_production_unit(unit["id"], QUALITY_INSPECTOR_HEADERS)
        )

        assert before["quality_status"] == QualityStatus.GATED.value
        # Latest ENERGY 380.00/400.00 = 0.95 and WATER 184.00/200.00 = 0.92, so
        # 0.6 * 0.9500 + 0.4 * 0.9200 = 0.938, which rounds to 0.94.
        assert float(before["provisional_efficiency_index"]) == approx2(0.94)
        assert before["efficiency_index"] is None
        assert before["certification_tier"] is None

    def test_certification_averages_every_recorded_test_and_moves_the_tier(self, api):
        """The same three measurements certify at 0.97, one tier band lower.

        "The **certification** variant uses **all** `RECORDED` tests of each type
        and genuinely averages them; it is computed only by certification and
        written into `efficiency_index` and `certification_tier`."

        Design: Difficulty/dual_variant_calc/efficiency_provisional_as_tested_vs_certification_average
        """
        plant = base_plant_with_shift(api)
        unit = gated_unit(api, plant, 1, energy=[420.00, 380.00], water=[184.00])
        provisional = float(read_unit(api, unit["id"])["provisional_efficiency_index"])

        certified = validate_success(
            api.certify_unit(unit["id"], QUALITY_INSPECTOR_HEADERS)
        )

        # Energy mean of 1.05 and 0.95 is 1.0000 against a water mean of 0.9200,
        # so 0.6 * 1.0000 + 0.4 * 0.9200 = 0.968, which rounds to 0.97.
        assert float(certified["efficiency_index"]) == approx2(0.97)
        assert certified["certification_tier"] == CertificationTier.B.value
        assert certified["quality_status"] == QualityStatus.CERTIFIED.value
        assert certified["assembly_status"] == AssemblyStatus.IN_STATION.value
        assert float(certified["efficiency_index"]) - provisional == approx2(0.03)


class TestWarrantyRateVariants:
    """One design-defect return against a two-unit shipped cohort."""

    def test_cohort_and_shipped_exposure_rates_diverge_on_one_return(self, api):
        """500.00 per thousand cohort units against 4000.00 per thousand hours.

        "Two shipped cohort units carrying a part with one design-defect return of
        500 field hours illustrate the divergence: the production-cohort rate is
        500.00 while the shipped-exposure rate is 4000.00."

        Design: Difficulty/dual_variant_calc/warranty_rate_production_cohort_vs_shipped_exposure
        """
        plant = base_plant_with_shift(api)
        shipped_unit(api, plant, 1)
        shipped_unit(api, plant, 2, planned_start="2026-08-03T08:00:00Z",
                     safety=0.31, leak=1.20)
        set_clock(api, "2026-08-03T12:00:00Z")
        design_defect_return(api, plant, plant.unit_id(1), field_hours=500,
                             returned_at="2026-08-03T11:00:00Z")

        metrics = validate_success(
            api.get_warranty_metrics(plant.part_id, WARRANTY_ANALYST_HEADERS)
        )

        assert metrics["part_id"] == plant.part_id
        assert metrics["failure_count"] == 1
        assert metrics["cohort_units"] == 2
        assert float(metrics["total_field_hours"]) == approx2(500)
        assert float(metrics["cohort_failure_rate_per_1000"]) == approx2(500.00)
        assert float(metrics["shipped_exposure_rate_per_1000"]) == approx2(4000.00)

    def test_only_the_cohort_variant_is_stored_and_drives_the_trigger(self, api):
        """The stored rate and the breach flag both mirror the cohort figure.

        "This is the variant stored on the part's `cohort_failure_rate_per_1000`
        and the only one compared against the 8.00 auto-change trigger."

        Design: Difficulty/dual_variant_calc/warranty_rate_production_cohort_vs_shipped_exposure
        """
        plant = base_plant_with_shift(api)
        shipped_unit(api, plant, 1)
        shipped_unit(api, plant, 2, planned_start="2026-08-03T08:00:00Z",
                     safety=0.31, leak=1.20)
        set_clock(api, "2026-08-03T12:00:00Z")
        wr = design_defect_return(api, plant, plant.unit_id(1), field_hours=500,
                                  returned_at="2026-08-03T11:00:00Z")
        assert wr["status"] == WarrantyReturnStatus.ANALYZED_DESIGN.value
        assert wr["disposition"] == Disposition.DESIGN_DEFECT.value

        metrics = validate_success(
            api.get_warranty_metrics(plant.part_id, WARRANTY_ANALYST_HEADERS)
        )
        part = read_part(api, plant.part_id)

        assert float(metrics["trigger_threshold"]) == approx2(8.00)
        assert metrics["trigger_breached"] is True
        assert float(part["cohort_failure_rate_per_1000"]) == approx2(500.00)
        assert float(part["cohort_failure_rate_per_1000"]) != approx2(4000.00)
        assert part["field_failure_count"] == 1
