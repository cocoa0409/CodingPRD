"""Hourly emissions determination under the two heat-input methods, and the
report totals rolled up from those hours."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_operating_hour,
    assert_quarterly_report,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    appendix_d_hour_payload,
    cems_hour_payload,
    single_hour_payload,
)


class TestDualDeterminationMethods:
    """The same physical hour priced through each method."""

    def test_cems_hour_derives_heat_input_and_mass_from_stack_gas(self):
        """A CEMS_FLOW_CO2 hour computes all four derived quantities from flow.

        PRD: "`heat_input_mmbtu` is `flow_scfh` multiplied by `co2_conc_pct`
        divided by 100, divided by the carbon-based F-factor of 1800.0 dry
        standard cubic feet of CO2 per mmBtu, multiplied by `op_time_fraction`,
        rounded half up to three decimals."

        Design: Difficulty/dual_variant_calc/dual_variant_heat_input_cems_vs_appendix_d_same_hour_diverges
        """
        station = fx.setup_dual_method_station()

        response = api_client.append_operating_hour(
            station["unit"]["id"],
            single_hour_payload(
                station["report"]["version"],
                cems_hour_payload("2026-04-01T00:00:00Z", gross_load_mw=600.0),
            ),
            fx.PREPARER,
        )
        hour = validate_success(response, 201)

        assert_operating_hour(hour)
        assert hour["heat_input_method"] == "CEMS_FLOW_CO2"
        assert hour["heat_input_mmbtu"] == 555.556, (
            f"expected 555.556 mmBtu from 8000000 scfh at 12.5% CO2, "
            f"got {hour['heat_input_mmbtu']}"
        )
        assert hour["so2_mass_lbs"] == 292.2, (
            f"expected 292.2 lb SO2 at 220 ppm, got {hour['so2_mass_lbs']}"
        )
        assert hour["nox_mass_lbs"] == 100.0, (
            f"expected 100.0 lb NOx from 0.180 lb/mmBtu, got {hour['nox_mass_lbs']}"
        )
        assert hour["co2_mass_tons"] == 59.700, (
            f"expected 59.700 tons CO2, got {hour['co2_mass_tons']}"
        )
        assert hour["data_quality"] == "MEASURED"
        assert hour["fuel_flow_lbs"] is None, (
            "a CEMS hour forbids fuel_flow_lbs, so the stored value must be null"
        )
        assert hour["fuel_sample_id"] is None, (
            "a CEMS hour forbids fuel_sample_id, so the stored value must be null"
        )

    def test_appendix_d_hour_derives_heat_input_and_mass_from_the_fuel_burned(self):
        """An APPENDIX_D_FUEL hour computes the same four quantities from fuel.

        PRD: "`heat_input_mmbtu` is `fuel_flow_lbs` multiplied by the referenced
        sample's `gcv_btu_per_lb`, divided by one million to convert Btu to
        mmBtu, multiplied by `op_time_fraction`, rounded half up to three
        decimals."

        Design: Difficulty/dual_variant_calc/dual_variant_heat_input_cems_vs_appendix_d_same_hour_diverges
        """
        station = fx.setup_dual_method_station()

        response = api_client.append_operating_hour(
            station["unit"]["id"],
            single_hour_payload(
                station["report"]["version"],
                appendix_d_hour_payload(
                    "2026-04-01T01:00:00Z",
                    station["fuel_sample"]["id"],
                    gross_load_mw=600.0,
                ),
            ),
            fx.PREPARER,
        )
        hour = validate_success(response, 201)

        assert_operating_hour(hour)
        assert hour["heat_input_method"] == "APPENDIX_D_FUEL"
        assert hour["heat_input_mmbtu"] == 562.500, (
            f"expected 562.500 mmBtu from 45000 lb at 12500 Btu/lb, "
            f"got {hour['heat_input_mmbtu']}"
        )
        assert hour["so2_mass_lbs"] == 765.0, (
            f"expected 765.0 lb SO2 from 0.85% sulfur, got {hour['so2_mass_lbs']}"
        )
        assert hour["nox_mass_lbs"] == 101.3, (
            f"expected 101.3 lb NOx, got {hour['nox_mass_lbs']}"
        )
        assert hour["co2_mass_tons"] == 57.741, (
            f"expected 57.741 tons CO2 at 205.3 lb/mmBtu, got {hour['co2_mass_tons']}"
        )
        assert hour["data_quality"] == "MEASURED"
        assert hour["flow_scfh"] is None, (
            "an Appendix D hour forbids flow_scfh, so the stored value must be null"
        )
        assert hour["so2_conc_ppm"] is None, (
            "an Appendix D hour forbids so2_conc_ppm, so the stored value must be null"
        )

    def test_the_two_methods_diverge_on_identical_operating_conditions(self):
        """Identical conditions priced both ways differ by 6.944 mmBtu / 472.8 lb.

        PRD: "It also carries `heat_input_method`, which selects one of two
        mutually exclusive families of measurement fields and produces
        materially different numbers from the same physical hour."

        Design: Difficulty/dual_variant_calc/dual_variant_heat_input_cems_vs_appendix_d_same_hour_diverges
        """
        station = fx.setup_dual_method_station()
        unit_id = station["unit"]["id"]

        cems_hour = fx.append_hour(
            unit_id,
            station["report"]["version"],
            cems_hour_payload("2026-04-01T00:00:00Z", gross_load_mw=600.0),
        )
        appendix_d_hour = fx.append_hour(
            unit_id,
            cems_hour["quarterly_report_version_after"],
            appendix_d_hour_payload(
                "2026-04-01T01:00:00Z",
                station["fuel_sample"]["id"],
                gross_load_mw=600.0,
            ),
        )

        assert (
            appendix_d_hour["heat_input_mmbtu"] - cems_hour["heat_input_mmbtu"]
            == pytest.approx(6.944, abs=0.0005)
        ), (
            "the fuel-based determination should exceed the stack-gas one by "
            f"6.944 mmBtu, got {appendix_d_hour['heat_input_mmbtu']} vs "
            f"{cems_hour['heat_input_mmbtu']}"
        )
        assert (
            appendix_d_hour["so2_mass_lbs"] - cems_hour["so2_mass_lbs"]
            == pytest.approx(472.8, abs=0.05)
        ), (
            "the stoichiometric SO2 mass should exceed the concentration-based "
            f"one by 472.8 lb, got {appendix_d_hour['so2_mass_lbs']} vs "
            f"{cems_hour['so2_mass_lbs']}"
        )


class TestMethodFieldFamilies:
    """`heat_input_method` alone decides which measurement fields are legal."""

    def test_appendix_d_hour_carrying_flow_scfh_is_a_method_field_mismatch(self):
        """A forbidden CEMS member on a fuel-method hour is refused.

        PRD: "Any deviation from those two field families — a missing required
        member, a forbidden member supplied, or a unit that owns no monitoring
        system whose `system_type` matches the chosen method — is rejected with
        `ERR_METHOD_FIELD_MISMATCH`."

        Design: Difficulty/dual_variant_calc/dual_variant_appendix_d_hour_rejects_cems_measurement_fields
        """
        station = fx.setup_appendix_d_only_station()

        payload = single_hour_payload(
            station["report"]["version"],
            appendix_d_hour_payload(
                "2026-04-01T00:00:00Z",
                station["fuel_sample"]["id"],
                flow_scfh=8000000.0,
            ),
        )
        response = api_client.append_operating_hour(
            station["unit"]["id"], payload, fx.PREPARER
        )

        validate_error(response, ApiErrorId.ERR_METHOD_FIELD_MISMATCH.value)

    def test_cems_hour_carrying_a_fuel_sample_is_a_method_field_mismatch(self):
        """A forbidden fuel member on a stack-gas hour is refused, not a shape error.

        PRD: "Note that this is *not* a shape error: a request that mixes the
        families is syntactically well formed, passes the request-shape check,
        and is caught only here."

        Design: Difficulty/dual_variant_calc/dual_variant_appendix_d_hour_rejects_cems_measurement_fields
        """
        station = fx.setup_appendix_d_only_station()

        payload = single_hour_payload(
            station["report"]["version"],
            cems_hour_payload(
                "2026-04-01T00:00:00Z",
                fuel_sample_id=station["fuel_sample"]["id"],
            ),
        )
        response = api_client.append_operating_hour(
            station["unit"]["id"], payload, fx.PREPARER
        )

        validate_error(response, ApiErrorId.ERR_METHOD_FIELD_MISMATCH.value)

    def test_a_refused_hour_persists_nothing_and_spends_no_report_version(self):
        """After two refusals the same version still admits a well-formed hour.

        PRD: "Appending an hour recomputes its owning report's counts and
        totals, reverts that report from `VALIDATED` back to `DRAFT` with its
        `version` incremented, recomputes the unit's `data_availability_pct`,
        and records `quarterly_report_version_after` on the hour so the client
        can chain the next guarded append without re-reading the report."

        Design: Difficulty/dual_variant_calc/dual_variant_appendix_d_hour_rejects_cems_measurement_fields
        """
        station = fx.setup_appendix_d_only_station()
        unit_id = station["unit"]["id"]
        report_version = station["report"]["version"]

        validate_error(
            api_client.append_operating_hour(
                unit_id,
                single_hour_payload(
                    report_version,
                    appendix_d_hour_payload(
                        "2026-04-01T00:00:00Z",
                        station["fuel_sample"]["id"],
                        flow_scfh=8000000.0,
                    ),
                ),
                fx.PREPARER,
            ),
            ApiErrorId.ERR_METHOD_FIELD_MISMATCH.value,
        )
        validate_error(
            api_client.append_operating_hour(
                unit_id,
                single_hour_payload(
                    report_version,
                    cems_hour_payload(
                        "2026-04-01T00:00:00Z",
                        fuel_sample_id=station["fuel_sample"]["id"],
                    ),
                ),
                fx.PREPARER,
            ),
            ApiErrorId.ERR_METHOD_FIELD_MISMATCH.value,
        )

        hours, meta = validate_paginated(
            api_client.list_operating_hours(fx.PREPARER, {"unit_id": unit_id})
        )
        assert meta["total_count"] == 0, (
            f"a refused append must persist nothing, found {meta['total_count']} hours"
        )

        report = validate_success(
            api_client.get_quarterly_report(station["report"]["id"], fx.PREPARER)
        )
        assert report["version"] == report_version, (
            f"a refused append must not spend a version: expected "
            f"{report_version}, got {report['version']}"
        )

        accepted = validate_success(
            api_client.append_operating_hour(
                unit_id,
                single_hour_payload(
                    report_version,
                    appendix_d_hour_payload(
                        "2026-04-01T00:00:00Z", station["fuel_sample"]["id"]
                    ),
                ),
                fx.PREPARER,
            ),
            201,
        )
        assert accepted["heat_input_mmbtu"] == 562.500
        assert accepted["so2_mass_lbs"] == 765.0
        assert accepted["co2_mass_tons"] == 57.741


class TestReportTotalsAggregation:
    """Totals sum the stored per-hour values; the raw products are never re-summed."""

    def _three_mixed_hours(self):
        station = fx.setup_dual_method_station()
        unit_id = station["unit"]["id"]
        first = fx.append_hour(
            unit_id,
            station["report"]["version"],
            cems_hour_payload("2026-04-01T00:00:00Z"),
        )
        second = fx.append_hour(
            unit_id,
            first["quarterly_report_version_after"],
            appendix_d_hour_payload(
                "2026-04-01T01:00:00Z", station["fuel_sample"]["id"]
            ),
        )
        third = fx.append_hour(
            unit_id,
            second["quarterly_report_version_after"],
            cems_hour_payload(
                "2026-04-01T02:00:00Z", flow_scfh=1000000.0, so2_conc_ppm=80.0
            ),
        )
        station["hours"] = [first, second, third]
        return station

    def test_report_total_so2_sums_the_already_rounded_hourly_pounds(self):
        """292.2 + 765.0 + 13.3 rolls up to 1070.5, never to 1070.4.

        PRD: "The aggregation order for the emission totals is **mandatory**:
        each hour's already-stored, already-rounded value is summed, and the raw
        unrounded products are never re-summed."

        Design: Difficulty/combinatorial_formula/combinatorial_report_total_so2_rounds_per_hour_before_summing
        """
        station = self._three_mixed_hours()
        first, second, third = station["hours"]

        assert first["so2_mass_lbs"] == 292.2
        assert second["so2_mass_lbs"] == 765.0
        assert third["so2_mass_lbs"] == 13.3

        report = validate_success(
            api_client.validate_quarterly_report(
                station["report"]["id"], {}, fx.PREPARER
            )
        )
        assert_quarterly_report(report)
        assert report["total_so2_lbs"] == 1070.5, (
            "summing the stored per-hour pounds gives 1070.5; 1070.4 is the "
            f"forbidden sum-then-round result, got {report['total_so2_lbs']}"
        )
        assert report["total_heat_input_mmbtu"] == 1187.500
        assert report["total_nox_lbs"] == 213.8
        assert report["total_co2_tons"] == 124.904
        assert report["operating_hour_count"] == 3
        assert report["measured_hour_count"] == 3
        assert report["substituted_hour_count"] == 0
        assert report["monitor_data_availability_pct"] == 100.0
        assert report["status"] == "VALIDATED"

    def test_report_total_so2_tons_derives_from_the_rounded_pound_total(self):
        """0.535 tons comes from 1070.5 lb / 2000, not from a re-sum of tons.

        PRD: "`total_so2_tons` is then derived from the **already-rounded**
        `total_so2_lbs`, divided by 2000 pounds per ton and rounded half up to
        three decimals — never from a re-sum of per-hour tons."

        Design: Difficulty/combinatorial_formula/combinatorial_report_total_so2_rounds_per_hour_before_summing
        """
        station = self._three_mixed_hours()

        report = validate_success(
            api_client.validate_quarterly_report(
                station["report"]["id"], {}, fx.PREPARER
            )
        )
        assert report["total_so2_lbs"] == 1070.5
        assert report["total_so2_tons"] == 0.535, (
            "1070.5 lb / 2000 rounds half up to 0.535 tons, got "
            f"{report['total_so2_tons']}"
        )
