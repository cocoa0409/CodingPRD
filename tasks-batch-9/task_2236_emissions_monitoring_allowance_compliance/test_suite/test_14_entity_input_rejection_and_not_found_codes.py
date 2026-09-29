"""Rejected input: missing required fields, unknown enum values, out-of-range
numbers, and the per-resource not-found code each path identifier owns."""
from test_helpers import (
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import cems_hour_payload, single_hour_payload

CLOCK_AUGUST = "2026-08-01T00:00:00Z"
CLOCK_APRIL = "2026-04-02T00:00:00Z"
TRUE_UP_DEADLINE = "2027-03-01T00:00:00Z"
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def _total(response):
    _, meta = validate_paginated(response)
    return meta["total_count"]


class TestRequiredFieldsAndValueBounds:
    """Shape first, then the numeric range rule far later in the order."""

    def test_three_creates_missing_one_required_field_each_are_refused(self):
        """Omitting a required field is 400; omitting an optional one is 201.

        PRD: "(6) The request body and query shape are well formed — no unknown
        enum values, no wrong JSON types, every required field present — else
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/entity_create_with_a_missing_required_field_is_rejected
        """
        fx.set_clock(CLOCK_AUGUST)

        without_orispl = api_client.create_facility(
            {
                "name": "Kestrel Generating Station",
                "state_code": "OH",
                "operator_org": "op_alpha",
                "programs": ["ARP_SO2"],
                "true_up_deadline_utc": TRUE_UP_DEADLINE,
            },
            fx.REVIEWER,
        )
        validate_error(without_orispl, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert _total(api_client.list_facilities(fx.REVIEWER)) == 0, (
            "the refused create must not have persisted a partial facility"
        )

        facility = validate_success(
            api_client.create_facility(
                {
                    "name": "Kestrel Generating Station",
                    "orispl_code": "7101",
                    "state_code": "OH",
                    "operator_org": "op_alpha",
                    "programs": ["ARP_SO2"],
                    "true_up_deadline_utc": TRUE_UP_DEADLINE,
                },
                fx.REVIEWER,
            ),
            201,
        )

        without_heat_input = api_client.create_unit(
            facility["id"],
            {
                "unit_identifier": "U1",
                "primary_fuel": "COAL",
                "nameplate_capacity_mw": 600,
            },
            fx.REVIEWER,
        )
        validate_error(without_heat_input, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert _total(api_client.list_units(fx.REVIEWER)) == 0

        unit = validate_success(
            api_client.create_unit(
                facility["id"],
                {
                    "unit_identifier": "U1",
                    "primary_fuel": "COAL",
                    "nameplate_capacity_mw": 600,
                    "max_rated_heat_input_mmbtu_hr": 6000,
                },
                fx.REVIEWER,
            ),
            201,
        )
        assert unit["control_device"] == "NONE", (
            "control_device is optional, so its absence is a default and not a "
            "shape violation"
        )

        without_basis = api_client.create_permit_limit(
            unit["id"],
            {
                "pollutant": "SO2",
                "limit_value": 250.0,
                "limit_units": "LB_PER_HR",
                "effective_from_utc": "2026-01-01T00:00:00Z",
            },
            fx.REVIEWER,
        )
        validate_error(without_basis, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert (
            _total(api_client.list_permit_limits(fx.REVIEWER, {"unit_id": unit["id"]}))
            == 0
        )

    def test_an_unknown_enum_is_400_while_four_bad_numbers_are_422(self):
        """`MERCURY` never reaches the range rule; 1.4, 25.0, 0.0 and 0.0 do.

        PRD: "The numeric range rule at step 36 applies to every creating or
        modifying request that accepts a numeric input, and enforces these bounds:
        `op_time_fraction` from 0.0 through 1.0 inclusive; `co2_conc_pct` greater
        than 0.0 and at most 20.0; `so2_conc_ppm` from 0 through 2000 inclusive;
        `nox_rate_lb_mmbtu` from 0.0 through 2.0 inclusive; `flow_scfh` strictly
        greater than 0; `gross_load_mw` at least 0; `sulfur_content_pct` from 0.0
        through 10.0 inclusive; `gcv_btu_per_lb` from 1000 through 20000 inclusive;
        `span_value` strictly greater than 0; `calibration_error_spec_pct` greater
        than 0.0 and at most 20.0; `limit_value` strictly greater than 0;
        `max_concurrent_control_outages` from 0 through 10 inclusive; and `quarter`
        from 1 through 4 inclusive."

        PRD: "Violations of any of these report `ERR_VALUE_OUT_OF_RANGE` (HTTP
        422)."

        Design: Corner/entities/entity_enum_and_numeric_constraints_are_enforced_on_input
        """
        station = fx.setup_facility_and_unit(clock=CLOCK_APRIL)
        unit_id = station["unit"]["id"]
        fx.setup_certified_cem(unit_id)
        report = fx.open_quarterly_report(unit_id)
        assert report["version"] == 1

        unknown_parameter = api_client.install_monitoring_system(
            unit_id,
            {"parameter": "MERCURY", "system_type": "CEM", "span_value": 400.0},
            fx.QA,
        )
        validate_error(unknown_parameter, ApiErrorId.ERR_INVALID_REQUEST.value)

        for field, value in (
            ("op_time_fraction", 1.4),
            ("co2_conc_pct", 25.0),
            ("flow_scfh", 0.0),
        ):
            out_of_range = api_client.append_operating_hour(
                unit_id,
                single_hour_payload(
                    report["version"],
                    cems_hour_payload("2026-04-01T00:00:00Z", **{field: value}),
                ),
                fx.PREPARER,
            )
            validate_error(out_of_range, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value)

        bad_limit = api_client.create_permit_limit(
            unit_id,
            {
                "pollutant": "SO2",
                "limit_value": 0.0,
                "limit_units": "LB_PER_HR",
                "averaging_basis": "ROLLING_3_HOUR",
                "effective_from_utc": "2026-01-01T00:00:00Z",
            },
            fx.REVIEWER,
        )
        validate_error(bad_limit, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value)

        assert (
            _total(api_client.list_operating_hours(fx.PREPARER, {"unit_id": unit_id}))
            == 0
        ), "not one of the refused hours was persisted"
        assert (
            validate_success(
                api_client.get_quarterly_report(report["id"], fx.PREPARER)
            )["version"]
            == 1
        ), "a refused append never spends the report's version"


class TestNotFoundDiscipline:
    """Each resource answers with its own code, and the path outranks the body."""

    def test_thirteen_unknown_path_ids_each_answer_with_their_own_code(self):
        """One shared unknown id, thirteen distinct not-found error ids.

        PRD: "The remaining not-found codes — `ERR_DAILY_CALIBRATION_NOT_FOUND`,
        `ERR_OPERATING_HOUR_NOT_FOUND`, `ERR_QUARTERLY_REPORT_NOT_FOUND`,
        `ERR_CERTIFICATION_NOT_FOUND`, `ERR_PERMIT_LIMIT_NOT_FOUND`,
        `ERR_EXCESS_EVENT_NOT_FOUND`, `ERR_ALLOWANCE_TRANSACTION_NOT_FOUND` and
        `ERR_CONTROL_OUTAGE_NOT_FOUND` — follow the same discipline for their own
        resources."

        Design: Corner/entities/entity_every_path_id_has_its_own_not_found_code
        """
        fx.set_clock(CLOCK_AUGUST)

        probes = (
            (api_client.get_unit, ApiErrorId.ERR_UNIT_NOT_FOUND),
            (
                api_client.get_monitoring_system,
                ApiErrorId.ERR_MONITORING_SYSTEM_NOT_FOUND,
            ),
            (
                api_client.get_daily_calibration,
                ApiErrorId.ERR_DAILY_CALIBRATION_NOT_FOUND,
            ),
            (api_client.get_rata_test, ApiErrorId.ERR_RATA_TEST_NOT_FOUND),
            (api_client.get_operating_hour, ApiErrorId.ERR_OPERATING_HOUR_NOT_FOUND),
            (api_client.get_fuel_sample, ApiErrorId.ERR_FUEL_SAMPLE_NOT_FOUND),
            (
                api_client.get_quarterly_report,
                ApiErrorId.ERR_QUARTERLY_REPORT_NOT_FOUND,
            ),
            (api_client.get_certification, ApiErrorId.ERR_CERTIFICATION_NOT_FOUND),
            (api_client.get_permit_limit, ApiErrorId.ERR_PERMIT_LIMIT_NOT_FOUND),
            (
                api_client.get_excess_emission_event,
                ApiErrorId.ERR_EXCESS_EVENT_NOT_FOUND,
            ),
            (
                api_client.get_allowance_account,
                ApiErrorId.ERR_ALLOWANCE_ACCOUNT_NOT_FOUND,
            ),
            (
                api_client.get_allowance_transaction,
                ApiErrorId.ERR_ALLOWANCE_TRANSACTION_NOT_FOUND,
            ),
            (api_client.get_control_outage, ApiErrorId.ERR_CONTROL_OUTAGE_NOT_FOUND),
        )
        assert len(probes) == 13

        seen = set()
        for getter, error_id in probes:
            validate_error(getter(UNKNOWN_ID, fx.REVIEWER), error_id.value)
            seen.add(error_id.value)
        assert len(seen) == 13, (
            "no two resources may share a not-found code, saw "
            f"{len(seen)} distinct ids"
        )

    def test_a_nested_create_reports_its_parents_code_before_the_body(self):
        """Unknown facility, unit and system parents each answer 404 first.

        PRD: "(8) Every identifier in the request **path** resolves, checked
        outermost-first, so a unit create under a non-existent facility reports
        `ERR_FACILITY_NOT_FOUND` before the body is considered."

        PRD: "A daily-calibration append against a non-existent monitoring system
        reports `ERR_MONITORING_SYSTEM_NOT_FOUND`; an allowance account opened under
        a non-existent facility reports `ERR_FACILITY_NOT_FOUND`; every
        sub-resource operation beneath a unit reports `ERR_UNIT_NOT_FOUND` when the
        unit does not exist."

        PRD: "Shape validation precedes every 404, so a request that both carries
        an unknown enum value and references a non-existent parent returns
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/entity_child_create_under_an_unknown_parent_returns_the_parent_code
        """
        fx.set_clock(CLOCK_AUGUST)

        validate_error(
            api_client.create_unit(
                UNKNOWN_ID,
                {
                    "unit_identifier": "U1",
                    "primary_fuel": "COAL",
                    "nameplate_capacity_mw": 600,
                    "max_rated_heat_input_mmbtu_hr": 6000,
                },
                fx.REVIEWER,
            ),
            ApiErrorId.ERR_FACILITY_NOT_FOUND.value,
        )
        validate_error(
            api_client.open_quarterly_report(
                UNKNOWN_ID, {"year": 2026, "quarter": 2}, fx.PREPARER
            ),
            ApiErrorId.ERR_UNIT_NOT_FOUND.value,
        )
        validate_error(
            api_client.drive_qa_status(UNKNOWN_ID, {"action": "CERTIFY"}, fx.QA),
            ApiErrorId.ERR_MONITORING_SYSTEM_NOT_FOUND.value,
        )
        validate_error(
            api_client.open_allowance_account(
                UNKNOWN_ID,
                {
                    "program": "ARP_SO2",
                    "compliance_year": 2026,
                    "holdings_current_vintage_tons": 5.0,
                    "holdings_prior_vintage_tons": 5.0,
                    "holdings_next_vintage_tons": 5.0,
                },
                fx.REVIEWER,
            ),
            ApiErrorId.ERR_FACILITY_NOT_FOUND.value,
        )
        validate_error(
            api_client.install_monitoring_system(
                UNKNOWN_ID,
                {"parameter": "MERCURY", "system_type": "CEM", "span_value": 400.0},
                fx.QA,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )

        assert _total(api_client.list_units(fx.REVIEWER)) == 0, (
            "none of the refused creates left a row behind"
        )
        assert _total(api_client.list_facilities(fx.REVIEWER)) == 0
