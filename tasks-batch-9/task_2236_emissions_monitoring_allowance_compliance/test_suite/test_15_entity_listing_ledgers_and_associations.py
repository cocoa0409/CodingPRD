"""Collection paging on the hour list, the two append-only ledger records, and
the three associations one operating hour resolves at once."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_append_only_audit_fields,
    assert_daily_calibration,
    assert_operating_hour,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import appendix_d_hour_payload, single_hour_payload

CLOCK_APRIL = "2026-04-02T00:00:00Z"
OPERATOR_ORG = "op_alpha"


def _hours(params):
    return validate_paginated(api_client.list_operating_hours(fx.REVIEWER, params))


class TestOperatingHourListing:
    """Three hours, two pages, and three rejected pagination arguments."""

    def test_two_pages_cover_three_hours_and_has_more_flips(self):
        """limit 2 gives 2 rows with has_more true, then 1 row with it false.

        PRD: "the `meta` block of a list response carries `limit`, `offset`,
        `total_count` (the number of rows matching the filters before pagination is
        applied) and `has_more`."

        PRD: "`limit` defaults to 10 when absent, and when supplied must be an
        integer of at least 1 and at most 100."

        Design: Corner/entities/entity_operating_hour_listing_paginates_and_rejects_bad_pagination
        """
        station = fx.setup_draft_report_with_cems_hours(hour_count=3, clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]

        first_page, first_meta = _hours({"unit_id": unit_id, "limit": 2, "offset": 0})
        assert len(first_page) == 2, f"expected 2 rows, got {len(first_page)}"
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["total_count"] == 3, (
            "total_count counts every row matching the filter, before paging"
        )
        assert first_meta["has_more"] is True

        second_page, second_meta = _hours({"unit_id": unit_id, "limit": 2, "offset": 2})
        assert len(second_page) == 1
        assert second_meta["offset"] == 2
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

        ids = {row["id"] for row in first_page} | {row["id"] for row in second_page}
        assert len(ids) == 3, "the two pages must not overlap"

    def test_a_zero_limit_an_oversized_limit_and_a_negative_offset_are_refused(self):
        """The floor of 1, the ceiling of 100 and the offset floor of 0.

        PRD: "`offset` defaults to 0 when absent, and when supplied must be an
        integer of at least 0. An explicit value outside those bounds is rejected
        with `ERR_INVALID_PAGINATION` (HTTP 400)."

        Design: Corner/entities/entity_operating_hour_listing_paginates_and_rejects_bad_pagination
        """
        station = fx.setup_draft_report_with_cems_hours(hour_count=3, clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]

        for params in (
            {"unit_id": unit_id, "limit": 0},
            {"unit_id": unit_id, "limit": 101},
            {"unit_id": unit_id, "offset": -1},
        ):
            validate_error(
                api_client.list_operating_hours(fx.REVIEWER, params),
                ApiErrorId.ERR_INVALID_PAGINATION.value,
            )

        _, meta = _hours({"unit_id": unit_id, "limit": 100})
        assert meta["limit"] == 100, "100 is inside the ceiling and is honoured"
        assert meta["total_count"] == 3


class TestAppendOnlyLedgerRecords:
    """An operating hour and a daily calibration carry only id and created_at."""

    def test_neither_ledger_record_exposes_a_version_or_an_updated_at(self):
        """Both carry the parent's post-cascade version instead.

        PRD: "Two record types are append-only ledger entries and are the
        exception: a **daily calibration** and an **operating hour** carry only `id`
        and `created_at`."

        PRD: "a daily calibration exposes `monitoring_system_version_after`, and an
        operating hour exposes `quarterly_report_version_after`. Both are the
        parent's `version` observed *after* the write and after every cascade it
        triggered, and both are therefore always at least 2."

        Design: Corner/entities/entity_operating_hour_and_daily_calibration_carry_no_version_or_update_path
        """
        station = fx.setup_facility_and_unit(clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]
        certified = fx.setup_certified_cem(unit_id)
        report = fx.open_quarterly_report(unit_id)
        appended = fx.append_hour(unit_id, report["version"], fx.cems_hours(1)[0])

        hour = validate_success(
            api_client.get_operating_hour(appended["id"], fx.REVIEWER)
        )
        assert_operating_hour(hour)
        assert_append_only_audit_fields(hour)
        assert "version" not in hour or hour["version"] is None
        assert "updated_at" not in hour or hour["updated_at"] is None
        assert hour["quarterly_report_version_after"] == 2, (
            "the report stood at 1 and the append moved it to 2, got "
            f"{hour['quarterly_report_version_after']}"
        )
        assert hour["created_at"].startswith("2026-04-02T00:00:00")

        calibration = validate_success(
            api_client.get_daily_calibration(certified["calibration"]["id"], fx.REVIEWER)
        )
        assert_daily_calibration(calibration)
        assert_append_only_audit_fields(calibration)
        assert "version" not in calibration or calibration["version"] is None
        assert "updated_at" not in calibration or calibration["updated_at"] is None
        assert calibration["span_error_pct_of_span"] == 2.00
        assert calibration["result"] == "PASSED"
        assert calibration["monitoring_system_version_after"] == 2, (
            "the system stood at 1 when the calibration was recorded"
        )


class TestOperatingHourAssociations:
    """Path unit, timestamp-selected report and body fuel sample, all at once."""

    def _two_unit_station(self):
        station = fx.setup_facility_and_unit(clock=CLOCK_APRIL)
        facility_id = station["facility"]["id"]
        station["second_unit"] = fx.create_unit(facility_id, unit_identifier="U2")
        fx.setup_appendix_d_system(station["unit"]["id"], parameter="CO2", span_value=20.0)
        station["sample_a"] = fx.setup_analyzed_fuel_sample(
            station["unit"]["id"],
            OPERATOR_ORG,
            analysis_overrides={"gcv_btu_per_lb": 12500.0, "sulfur_content_pct": 0.85},
            lot_identifier="LOT-A",
        )
        station["sample_z"] = fx.setup_analyzed_fuel_sample(
            station["second_unit"]["id"],
            OPERATOR_ORG,
            analysis_overrides={"gcv_btu_per_lb": 12500.0, "sulfur_content_pct": 0.85},
            lot_identifier="LOT-Z",
        )
        station["report"] = fx.open_quarterly_report(station["unit"]["id"])
        return station

    def _append(self, unit_id, version, hour_begin_utc, fuel_sample_id):
        return api_client.append_operating_hour(
            unit_id,
            single_hour_payload(
                version,
                appendix_d_hour_payload(hour_begin_utc, fuel_sample_id),
            ),
            fx.PREPARER,
        )

    def test_a_wrong_quarter_a_half_hour_and_a_foreign_sample_are_each_refused(self):
        """Two timestamp faults answer 422 and the cross-unit sample answers 404.

        PRD: "The server resolves the report of that unit whose `year` and `quarter`
        contain `hour_begin_utc` and records it as `quarterly_report_id`; if the
        timestamp is not exactly on the hour, or if no report standing at `DRAFT` or
        `VALIDATED` exists for that unit and quarter, the append is rejected with
        `ERR_HOUR_OUTSIDE_REPORT_PERIOD`."

        PRD: "(10) A referenced child actually belongs to the parent named in the
        path — a `fuel_sample_id` must belong to the unit in the path, a
        `retest_of_rata_test_id` must belong to the monitoring system in the path,
        and a certification named for revocation must belong to its report."

        Design: Corner/entities/entity_operating_hour_associates_across_three_aggregates_at_once
        """
        station = self._two_unit_station()
        unit_id = station["unit"]["id"]
        version = station["report"]["version"]
        sample_a = station["sample_a"]["id"]

        validate_error(
            self._append(unit_id, version, "2026-07-01T00:00:00Z", sample_a),
            ApiErrorId.ERR_HOUR_OUTSIDE_REPORT_PERIOD.value,
        )
        validate_error(
            self._append(unit_id, version, "2026-04-01T00:30:00Z", sample_a),
            ApiErrorId.ERR_HOUR_OUTSIDE_REPORT_PERIOD.value,
        )
        validate_error(
            self._append(
                unit_id, version, "2026-04-01T00:00:00Z", station["sample_z"]["id"]
            ),
            ApiErrorId.ERR_FUEL_SAMPLE_NOT_FOUND.value,
        )

        unchanged = validate_success(
            api_client.get_quarterly_report(station["report"]["id"], fx.PREPARER)
        )
        assert unchanged["version"] == 1, (
            "three refusals must leave the report's version unspent, got "
            f"{unchanged['version']}"
        )
        assert unchanged["operating_hour_count"] == 0

    def test_one_accepted_hour_resolves_all_three_associations_to_one_row(self):
        """562.500 mmBtu and 765.0 lb SO2 from the path unit, report and sample.

        PRD: "`heat_input_mmbtu` is `fuel_flow_lbs` multiplied by the referenced
        sample's `gcv_btu_per_lb`, divided by one million to convert Btu to mmBtu,
        multiplied by `op_time_fraction`, rounded half up to three decimals."

        PRD: "`so2_mass_lbs` is a stoichiometric conversion: `fuel_flow_lbs`
        multiplied by the sulfur-to-SO2 mass ratio of 2.0, multiplied by the
        sample's `sulfur_content_pct` divided by 100, multiplied by
        `op_time_fraction`, rounded half up to one decimal — and **no bias
        adjustment ever applies to this variant**."

        Design: Corner/entities/entity_operating_hour_associates_across_three_aggregates_at_once
        """
        station = self._two_unit_station()
        unit_id = station["unit"]["id"]
        report = station["report"]

        hour = validate_success(
            self._append(
                unit_id,
                report["version"],
                "2026-04-01T00:00:00Z",
                station["sample_a"]["id"],
            ),
            201,
        )
        assert_operating_hour(hour)
        assert hour["unit_id"] == unit_id
        assert hour["quarterly_report_id"] == report["id"], (
            "the hour's own timestamp selected the report; the client never named it"
        )
        assert hour["fuel_sample_id"] == station["sample_a"]["id"]
        assert hour["heat_input_mmbtu"] == 562.500, (
            "45000 * 12500 / 1000000 is 562.5, got "
            f"{hour['heat_input_mmbtu']}"
        )
        assert hour["so2_mass_lbs"] == 765.0, (
            f"45000 * 2.0 * 0.85 / 100 is 765.0, got {hour['so2_mass_lbs']}"
        )
        assert hour["data_quality"] == "MEASURED"

        after = validate_success(
            api_client.get_quarterly_report(report["id"], fx.PREPARER)
        )
        assert after["version"] == 2
        assert after["operating_hour_count"] == 1
