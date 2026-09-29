"""Missing-data substitution under the pinned evaluation order, the quantities
that survive a flip, and the availability floor at report validation."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_report_hour_partition,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def _hour(hour_id):
    return validate_success(api_client.get_operating_hour(hour_id, fx.PREPARER))


def _report(report_id):
    return validate_success(api_client.get_quarterly_report(report_id, fx.PREPARER))


def _hours_of(unit_id):
    hours, _ = validate_paginated(
        api_client.list_operating_hours(fx.PREPARER, {"unit_id": unit_id})
    )
    return hours


def _substitute(unit_id, from_hour_utc, to_hour_utc):
    return api_client.run_missing_data_substitution(
        unit_id,
        {"from_hour_utc": from_hour_utc, "to_hour_utc": to_hour_utc},
        fx.PREPARER,
    )


class TestPinnedSubstitutionOrder:
    """The tier reads an availability figure that excludes the target hour."""

    def _flipped_station(self, recertify=True):
        station = fx.setup_draft_report_with_cems_hours(hour_count=3)
        fx.drive_qa_status(
            station["system"]["id"],
            "DECLARE_OUT_OF_CONTROL",
            effective_utc="2026-04-01T01:00:00Z",
            reason="quarterly linearity check aborted",
        )
        if recertify:
            fx.drive_qa_status(station["system"]["id"], "CERTIFY")
        return station

    def test_two_hours_flipped_by_one_call_land_in_different_tiers(self):
        """01:00 substitutes at 100.0 availability, 02:00 at 50.0.

        PRD: "First, availability for a target hour is computed **excluding that
        hour itself and every hour whose `hour_begin_utc` is at or after it**;
        this is what breaks the circularity."

        Design: Difficulty/combinatorial_formula/combinatorial_substitution_tier_uses_pinned_availability_evaluation_order
        """
        station = self._flipped_station()
        first, second, third = station["hours"]

        validate_success(
            _substitute(
                station["unit"]["id"],
                "2026-04-01T01:00:00Z",
                "2026-04-01T03:00:00Z",
            )
        )

        untouched = _hour(first["id"])
        assert untouched["data_quality"] == "MEASURED"
        assert untouched["so2_mass_lbs"] == 292.2

        earlier = _hour(second["id"])
        assert earlier["data_quality"] == "SUBSTITUTED"
        assert earlier["monitor_data_availability_pct_at_substitution"] == 100.0, (
            "only the 00:00 hour is in scope for the 01:00 hour's availability"
        )
        assert earlier["substitution_method"] == "T1_90TH_PERCENTILE"

        later = _hour(third["id"])
        assert later["data_quality"] == "SUBSTITUTED"
        assert later["monitor_data_availability_pct_at_substitution"] == 50.0, (
            "the freshly substituted 01:00 hour joins the 02:00 hour's "
            "denominator but not its numerator"
        )
        assert later["substitution_method"] == "T4_MAX_POTENTIAL_CONCENTRATION", (
            "50.0 availability falls through every percentile tier"
        )
        assert earlier["substitution_method"] != later["substitution_method"], (
            "a whole-quarter availability figure would have put both hours in "
            "the same tier"
        )

    def test_each_tier_writes_its_own_substitute_concentration_and_mass(self):
        """The 90th percentile of a one-value lookback is 220, the fallback is 400.

        PRD: "The tier's value is written to `substituted_so2_conc_ppm` as a
        whole number, taken verbatim from the lookback set rather than
        interpolated, `data_quality` becomes `SUBSTITUTED`, and `so2_mass_lbs` is
        recomputed as the SO2 mass conversion constant 0.000000166 multiplied by
        the substitute concentration, by `flow_scfh` and by `op_time_fraction`,
        rounded half up to one decimal."

        Design: Difficulty/combinatorial_formula/combinatorial_substitution_tier_uses_pinned_availability_evaluation_order
        """
        station = self._flipped_station()
        _, second, third = station["hours"]

        validate_success(
            _substitute(
                station["unit"]["id"],
                "2026-04-01T01:00:00Z",
                "2026-04-01T03:00:00Z",
            )
        )

        earlier = _hour(second["id"])
        assert earlier["substituted_so2_conc_ppm"] == 220.0
        assert earlier["so2_mass_lbs"] == 292.2

        later = _hour(third["id"])
        assert later["substituted_so2_conc_ppm"] == 400.0, (
            "the lookback set holds only measured hours, so the fallback writes "
            "the maximum potential concentration"
        )
        assert later["so2_mass_lbs"] == 531.2

        report = _report(station["report"]["id"])
        assert report["total_so2_lbs"] == 1115.6
        assert report["substituted_hour_count"] == 2
        assert report["measured_hour_count"] == 1
        assert report["monitor_data_availability_pct"] == 33.3, (
            "substitution restores emissions, never availability"
        )
        assert report["total_heat_input_mmbtu"] == 1666.668


class TestConservedHourQuantities:
    """Two identities hold across the flip and the substitution."""

    def _validated_then_flipped(self):
        station = fx.setup_draft_report_with_cems_hours(hour_count=3)
        station["report"] = fx.validate_report(station["report"]["id"])
        fx.drive_qa_status(
            station["system"]["id"],
            "DECLARE_OUT_OF_CONTROL",
            effective_utc="2026-04-01T01:00:00Z",
            reason="quarterly linearity check outside specification",
        )
        return station

    def test_the_hour_partition_closes_at_every_checkpoint(self):
        """Measured plus substituted plus unavailable is always three.

        PRD: "`measured_hour_count` is the number of hours whose `data_quality`
        is `MEASURED` and `substituted_hour_count` the number whose
        `data_quality` is `SUBSTITUTED`; both counts are taken over **all** of
        the report's hours without any operating-time filter, so they are not
        necessarily subsets of `operating_hour_count`."

        Design: Difficulty/compensating_invariant/invariant_hour_classification_partition_and_heat_input_survive_flip_and_substitution
        """
        station = fx.setup_draft_report_with_cems_hours(hour_count=3)
        report_id = station["report"]["id"]
        unit_id = station["unit"]["id"]

        checkpoint_a = fx.validate_report(report_id)
        assert checkpoint_a["status"] == "VALIDATED"
        assert checkpoint_a["operating_hour_count"] == 3
        assert checkpoint_a["measured_hour_count"] == 3
        assert checkpoint_a["substituted_hour_count"] == 0
        assert_report_hour_partition(checkpoint_a, _hours_of(unit_id))

        fx.drive_qa_status(
            station["system"]["id"],
            "DECLARE_OUT_OF_CONTROL",
            effective_utc="2026-04-01T01:00:00Z",
            reason="quarterly linearity check outside specification",
        )
        checkpoint_b = _report(report_id)
        assert checkpoint_b["status"] == "DRAFT"
        assert checkpoint_b["operating_hour_count"] == 3
        assert checkpoint_b["measured_hour_count"] == 1
        assert checkpoint_b["substituted_hour_count"] == 0
        assert_report_hour_partition(checkpoint_b, _hours_of(unit_id))

        validate_success(
            _substitute(unit_id, "2026-04-01T01:00:00Z", "2026-04-01T03:00:00Z")
        )
        checkpoint_c = _report(report_id)
        assert checkpoint_c["status"] == "DRAFT"
        assert checkpoint_c["operating_hour_count"] == 3
        assert checkpoint_c["measured_hour_count"] == 1
        assert checkpoint_c["substituted_hour_count"] == 2
        assert_report_hour_partition(checkpoint_c, _hours_of(unit_id))

    def test_the_heat_input_total_holds_while_the_so2_total_swings(self):
        """876.6 to 292.2 to 1115.6 pounds, all at 1666.668 mmBtu.

        PRD: "`total_heat_input_mmbtu` is the sum of the hours'
        `heat_input_mmbtu`, rounded half up to three decimals."

        Design: Difficulty/compensating_invariant/invariant_hour_classification_partition_and_heat_input_survive_flip_and_substitution
        """
        station = fx.setup_draft_report_with_cems_hours(hour_count=3)
        report_id = station["report"]["id"]
        unit_id = station["unit"]["id"]
        _, second, third = station["hours"]

        checkpoint_a = fx.validate_report(report_id)
        assert checkpoint_a["total_heat_input_mmbtu"] == 1666.668
        assert checkpoint_a["total_so2_lbs"] == 876.6
        assert checkpoint_a["total_so2_tons"] == 0.438
        assert checkpoint_a["monitor_data_availability_pct"] == 100.0

        fx.drive_qa_status(
            station["system"]["id"],
            "DECLARE_OUT_OF_CONTROL",
            effective_utc="2026-04-01T01:00:00Z",
            reason="quarterly linearity check outside specification",
        )
        assert _hour(second["id"])["heat_input_mmbtu"] == 555.556
        assert _hour(third["id"])["heat_input_mmbtu"] == 555.556

        checkpoint_b = _report(report_id)
        assert checkpoint_b["total_heat_input_mmbtu"] == 1666.668, (
            "nulling a concentration never touches the heat-input determination"
        )
        assert checkpoint_b["total_so2_lbs"] == 292.2
        assert checkpoint_b["total_so2_tons"] == 0.146
        assert checkpoint_b["monitor_data_availability_pct"] == 33.3

        validate_success(
            _substitute(unit_id, "2026-04-01T01:00:00Z", "2026-04-01T03:00:00Z")
        )
        checkpoint_c = _report(report_id)
        assert checkpoint_c["total_heat_input_mmbtu"] == 1666.668
        assert checkpoint_c["total_so2_lbs"] == 1115.6
        assert checkpoint_c["monitor_data_availability_pct"] == 33.3

        unit = validate_success(api_client.get_unit(unit_id, fx.REVIEWER))
        assert unit["data_availability_pct"] == 33.3


class TestAvailabilityFloorBoundary:
    """The floor is crossed in one direction only."""

    def _twenty_hours(self):
        return fx.setup_draft_report_with_cems_hours(hour_count=20)

    def test_sixteen_measured_hours_of_twenty_is_exactly_the_floor(self):
        """80.0 percent clears the floor and the report validates.

        PRD: "When the denominator is zero the availability is 100.0 by
        definition; otherwise it is the numerator divided by the denominator,
        multiplied by 100, rounded half up to one decimal place."

        Design: Difficulty/boundary_precision_check/boundary_data_availability_exactly_at_floor_validates
        """
        station = self._twenty_hours()
        before = _report(station["report"]["id"])
        assert before["monitor_data_availability_pct"] == 100.0
        assert before["total_so2_lbs"] == 5844.0

        fx.drive_qa_status(
            station["system"]["id"],
            "DECLARE_OUT_OF_CONTROL",
            effective_utc="2026-04-01T16:00:00Z",
            reason="flow monitor leak check failed",
        )
        at_floor = _report(station["report"]["id"])
        assert at_floor["measured_hour_count"] == 16
        assert at_floor["monitor_data_availability_pct"] == 80.0
        assert at_floor["total_so2_lbs"] == 4675.2
        assert at_floor["total_heat_input_mmbtu"] == 11111.120

        fx.drive_qa_status(station["system"]["id"], "CERTIFY")
        validated = validate_success(
            api_client.validate_quarterly_report(
                station["report"]["id"], {}, fx.PREPARER
            )
        )
        assert validated["status"] == "VALIDATED", (
            "exactly 80.0 is at the floor and therefore passes"
        )
        assert validated["monitor_data_availability_pct"] == 80.0

    def test_fifteen_measured_hours_of_twenty_falls_below_the_floor(self):
        """75.0 percent is refused, and the heat input total never moves.

        PRD: "the recomputed `monitor_data_availability_pct` must be **at or
        above** the data availability floor of 80.0 percent, so exactly 80.0
        passes and 79.9 does not (`ERR_DATA_AVAILABILITY_BELOW_FLOOR`)."

        Design: Difficulty/boundary_precision_check/boundary_data_availability_exactly_at_floor_validates
        """
        station = self._twenty_hours()
        system_id = station["system"]["id"]

        fx.drive_qa_status(
            system_id,
            "DECLARE_OUT_OF_CONTROL",
            effective_utc="2026-04-01T16:00:00Z",
            reason="flow monitor leak check failed",
        )
        fx.drive_qa_status(system_id, "CERTIFY")
        fx.validate_report(station["report"]["id"])

        fx.drive_qa_status(
            system_id,
            "DECLARE_OUT_OF_CONTROL",
            effective_utc="2026-04-01T15:00:00Z",
            reason="retroactive invalidation after the audit review",
        )
        below_floor = _report(station["report"]["id"])
        assert below_floor["measured_hour_count"] == 15
        assert below_floor["monitor_data_availability_pct"] == 75.0
        assert below_floor["status"] == "DRAFT"
        assert below_floor["total_so2_lbs"] == 4383.0
        assert below_floor["total_heat_input_mmbtu"] == 11111.120

        fx.drive_qa_status(system_id, "CERTIFY")
        response = api_client.validate_quarterly_report(
            station["report"]["id"], {}, fx.PREPARER
        )
        validate_error(response, ApiErrorId.ERR_DATA_AVAILABILITY_BELOW_FLOOR.value)

        unit = validate_success(
            api_client.get_unit(station["unit"]["id"], fx.REVIEWER)
        )
        assert unit["data_availability_pct"] == 75.0
