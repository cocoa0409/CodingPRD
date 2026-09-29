"""The arithmetic itself: which violations reach the numerator, which denominator each
category uses, where the roundings fall, and when a pinned number is allowed to move.
"""

from typing import Any, Dict

from test_helpers import (
    AlertStatus,
    BasicCategory,
    CourtStatus,
    InterventionStatus,
    RecordUpdateStatus,
    RemovalReason,
    ReportStatus,
    SelectionBand,
    UnitType,
    ViolationStatus,
    assert_credit_pct,
    assert_measure,
    assert_one_decimal,
    assert_two_decimals,
    contribution_for,
    fixtures as fx,
    get_success_data,
)

UD = BasicCategory.UNSAFE_DRIVING
HOS = BasicCategory.HOURS_OF_SERVICE
VM = BasicCategory.VEHICLE_MAINTENANCE
DF = BasicCategory.DRIVER_FITNESS


def _scored_pair_plus_a_validated_report(api) -> Dict[str, Any]:
    """A SCORED report holding two weight-5 vehicle violations, a second report left in
    VALIDATED, and a DISMISSED citation on the second violation not yet pushed."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    fx.create_threshold(
        api,
        basic_category=UD,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    scored, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [
            {"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE},
            {"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE},
        ],
        report_number="OH2026070301",
        vehicle_vin="1FUJA6CK21LK00301",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    unscored, unscored_rows = fx.build_validated_report(
        api,
        carrier["id"],
        [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
        report_number="OH2026070302",
        vehicle_vin="1FUJA6CK21LK00302",
        inspection_start="2026-07-02T14:00:00Z",
        inspection_end="2026-07-02T15:00:00Z",
    )
    adjudication = fx.create_adjudication(
        api, rows[1]["id"], citation_number="OH-CIT-7790"
    )
    fx.record_court_result(
        api,
        adjudication["id"],
        CourtStatus.DISMISSED,
        court_note="Dismissed for lack of evidence.",
    )
    return {
        "carrier": carrier,
        "scored": scored,
        "violations": rows,
        "unscored": unscored,
        "unscored_violation": unscored_rows[0],
        "adjudication": adjudication,
    }


class TestExclusionsFromTheNumerator:
    def test_only_active_rows_on_scored_reports_reach_the_measure(self, api):
        """PRD 3.4: "A violation is *included* in a category row when its `status` is
        `ACTIVE` or `RECODED`, its owning report's `status` is `SCORED`, that report's
        `attributed_carrier_id` is this carrier, its `time_weight` is greater than 0, and
        its `basic_category` matches the row's category."

        Design: Corner/calculations/unscored_report_and_removed_violation_excluded_from_measure
        """
        scenario = _scored_pair_plus_a_validated_report(api)
        carrier_id = scenario["carrier"]["id"]

        before = fx.read_basic_score(api, carrier_id, UD)
        assert before["included_violation_count"] == 2
        assert before["relevant_inspection_count"] == 1
        assert_one_decimal(before["total_time_weighted_severity"], 30.0)
        assert_measure(before["certified_measure"], 1.000)
        assert_one_decimal(before["percentile"], 65.0)
        assert before["alert_status"] == AlertStatus.ALERT

        assert (
            fx.read_report(api, scenario["unscored"]["id"])["status"]
            == ReportStatus.VALIDATED
        )
        waiting = fx.read_violation(api, scenario["unscored_violation"]["id"])
        assert_one_decimal(waiting["time_weighted_severity"], 0.0)

        pushed = fx.apply_adjudication(api, scenario["adjudication"]["id"])
        assert pushed["record_update_status"] == RecordUpdateStatus.APPLIED

        removed = fx.read_violation(api, scenario["violations"][1]["id"])
        assert removed["status"] == ViolationStatus.REMOVED
        assert removed["removal_reason"] == RemovalReason.ADJUDICATION_DISMISSED
        assert_one_decimal(removed["time_weighted_severity"], 0.0)

        report = fx.read_report(api, scenario["scored"]["id"])
        assert report["active_violation_count"] == 1
        assert_one_decimal(report["total_time_weighted_severity"], 15.0)

        after = fx.read_basic_score(api, carrier_id, UD)
        assert after["included_violation_count"] == 1
        assert after["relevant_inspection_count"] == 1
        assert_one_decimal(after["total_time_weighted_severity"], 15.0)
        assert_measure(after["certified_measure"], 0.500)
        assert_one_decimal(after["percentile"], 50.0)
        assert after["alert_status"] == AlertStatus.MONITOR

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["open_alert_count"] == 0
        assert_one_decimal(carrier["iss_value"], 17.5)


def _one_pinned_violation(api) -> Dict[str, Any]:
    """A single weight-5 violation pinned at time weight 3 on a SCORED report."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    fx.create_threshold(
        api,
        basic_category=UD,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    report, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
        report_number="OH2026070303",
        vehicle_vin="1FUJA6CK21LK00303",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    return {
        "carrier": carrier,
        "code": code,
        "report": report,
        "violation": rows[0],
    }


class TestPinnedWeightSurvivesACodeRevision:
    def test_the_republished_weight_only_lands_at_the_next_run(self, api):
        """PRD 3.3: "If an auditor revises a code's `severity_weight` after a violation
        has been pinned, the violation keeps scoring at the old weight; the divergence is
        visible because `has_stale_code_pin` becomes true whenever the effective code's
        current `version` differs from the violation's `pinned_violation_code_version`,
        and the score only moves at the next pass."

        Design: Corner/calculations/severity_weight_change_holds_the_pin_until_the_next_scoring_run
        """
        scenario = _one_pinned_violation(api)
        carrier_id = scenario["carrier"]["id"]

        revised = get_success_data(
            api.patch_violation_code(
                scenario["code"]["id"],
                {
                    "severity_weight": 8,
                    "description": "Speeding 15 or more over the limit (reweighted)",
                },
                fx.AUDITOR,
            )
        )
        assert revised["severity_weight"] == 8

        pinned = fx.read_violation(api, scenario["violation"]["id"])
        assert pinned["code_weight_snapshot"] == 5
        assert_one_decimal(pinned["time_weighted_severity"], 15.0)
        assert pinned["has_stale_code_pin"] is True

        held = fx.read_basic_score(api, carrier_id, UD)
        assert_measure(held["certified_measure"], 0.500)
        assert_one_decimal(held["percentile"], 50.0)
        assert_one_decimal(fx.read_carrier(api, carrier_id)["iss_value"], 17.5)

        run = fx.run_scoring(api, note="Weekly re-pin after the severity table update.")
        assert run["snapshot_utc"].startswith("2026-08-01T00:00:00")
        assert run["carriers_scored"] == 1

        repinned = fx.read_violation(api, scenario["violation"]["id"])
        assert repinned["code_weight_snapshot"] == 8
        assert repinned["time_weight"] == 3
        assert_one_decimal(repinned["time_weighted_severity"], 24.0)
        assert repinned["has_stale_code_pin"] is False

        moved = fx.read_basic_score(api, carrier_id, UD)
        assert_one_decimal(moved["total_time_weighted_severity"], 24.0)
        assert_measure(moved["certified_measure"], 0.800)
        assert_one_decimal(moved["percentile"], 59.0)
        assert moved["alert_status"] == AlertStatus.MONITOR

        carrier = fx.read_carrier(api, carrier_id)
        assert_one_decimal(carrier["iss_pre_credit_value"], 20.7)
        assert_one_decimal(carrier["iss_value"], 20.7)


def _small_carrier_with_two_categories(api) -> Dict[str, Any]:
    """A seven-truck carrier whose single inspection carries one UNSAFE_DRIVING and one
    HOURS_OF_SERVICE violation, so the two denominators differ."""
    fx.set_clock(api)
    carrier = fx.create_carrier(
        api,
        dot_number="1000005",
        legal_name="Hocking Valley Cartage",
        average_power_units=7,
        annual_vmt=70000,
    )
    unsafe = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    hours = fx.create_violation_code(
        api,
        code="395.3A1",
        description="11 hour driving limit exceeded",
        basic_category=HOS,
        severity_weight=5,
    )
    fx.create_thresholds_for_all_categories(
        api, carrier_segment="SMALL", measures=(2.0, 4.0, 6.0)
    )
    report, rows = fx.build_validated_report(
        api,
        carrier["id"],
        [
            {"violation_code_id": unsafe["id"], "unit_type": UnitType.VEHICLE},
            {"violation_code_id": hours["id"], "unit_type": UnitType.VEHICLE},
        ],
        report_number="OH2026070304",
        vehicle_vin="1FUJA6CK21LK00304",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    return {
        "carrier": carrier,
        "report": report,
        "unsafe_violation": rows[0],
        "hours_violation": rows[1],
    }


class TestDenominatorFloorsAndRounding:
    def test_the_percentile_is_read_off_the_already_rounded_measure(self, api):
        """PRD 3.4: "for `HOURS_OF_SERVICE` it is the smaller of power-unit exposure and
        twice `relevant_inspection_count`, again with a floor of 1.0" — and the mapping
        input is fixed: "Let the certified measure be the already-rounded
        `certified_measure` and let the reference row be the selected threshold."

        Design: Corner/calculations/denominator_floors_and_three_decimal_half_up_precision
        """
        scenario = _small_carrier_with_two_categories(api)
        carrier_id = scenario["carrier"]["id"]
        fx.score_report(api, scenario["report"]["id"])

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["carrier_segment"] == "SMALL"
        assert_one_decimal(carrier["utilization_factor"], 1.0)

        assert_one_decimal(
            fx.read_violation(api, scenario["unsafe_violation"]["id"])[
                "time_weighted_severity"
            ],
            15.0,
        )
        assert_one_decimal(
            fx.read_violation(api, scenario["hours_violation"]["id"])[
                "time_weighted_severity"
            ],
            15.0,
        )
        assert_one_decimal(
            fx.read_report(api, scenario["report"]["id"])[
                "total_time_weighted_severity"
            ],
            30.0,
        )

        unsafe_row = fx.read_basic_score(api, carrier_id, UD)
        assert_one_decimal(unsafe_row["denominator_value"], 7.0)
        assert_measure(unsafe_row["certified_measure"], 2.143)
        assert_one_decimal(unsafe_row["percentile"], 51.1)
        assert unsafe_row["alert_status"] == AlertStatus.MONITOR

        hours_row = fx.read_basic_score(api, carrier_id, HOS)
        assert_one_decimal(hours_row["denominator_value"], 2.0)
        assert_measure(hours_row["certified_measure"], 7.500)
        assert_one_decimal(hours_row["percentile"], 85.0)
        assert hours_row["alert_status"] == AlertStatus.ALERT

        risk = fx.read_screening_risk(api, carrier_id)
        assert_two_decimals(contribution_for(risk, UD), 17.89)
        assert_two_decimals(contribution_for(risk, HOS), 25.50)
        assert_one_decimal(risk["iss_pre_credit_value"], 43.4)
        assert_credit_pct(risk["data_quality_credit_pct"], 0.0)
        assert_one_decimal(risk["iss_value"], 43.4)
        assert risk["selection_band"] == SelectionBand.PASS

        posture = fx.read_carrier(api, carrier_id)
        assert posture["open_alert_count"] == 1
        assert_one_decimal(posture["max_percentile"], 85.0)
        assert posture["intervention_status"] == InterventionStatus.INVESTIGATION


def _two_categories_summing_to_fifty(api) -> Dict[str, Any]:
    """One inspection carrying an hours violation that saturates its percentile and a
    maintenance violation that lands exactly on the p80 reference measure."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    hours = fx.create_violation_code(
        api,
        code="395.3A1",
        description="11 hour driving limit exceeded",
        basic_category=HOS,
        severity_weight=5,
    )
    maintenance = fx.create_violation_code(
        api,
        code="393.9TS",
        description="Inoperative tail lamp",
        basic_category=VM,
        severity_weight=2,
    )
    fx.create_threshold(
        api,
        basic_category=HOS,
        carrier_segment="MEDIUM",
        measure_at_p50=0.1,
        measure_at_p65=0.2,
        measure_at_p80=0.4,
    )
    fx.create_threshold(
        api,
        basic_category=VM,
        carrier_segment="MEDIUM",
        measure_at_p50=2.0,
        measure_at_p65=4.0,
        measure_at_p80=6.0,
    )
    for category in (UD, DF):
        fx.create_threshold(
            api,
            basic_category=category,
            carrier_segment="MEDIUM",
            measure_at_p50=0.5,
            measure_at_p65=1.0,
            measure_at_p80=2.0,
        )
    report, rows = fx.build_validated_report(
        api,
        carrier["id"],
        [
            {"violation_code_id": hours["id"], "unit_type": UnitType.VEHICLE},
            {"violation_code_id": maintenance["id"], "unit_type": UnitType.VEHICLE},
        ],
        report_number="OH2026070305",
        vehicle_vin="1FUJA6CK21LK00305",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    return {
        "carrier": carrier,
        "report": report,
        "hours_violation": rows[0],
        "maintenance_violation": rows[1],
    }


class TestBandBoundary:
    def test_a_screening_value_of_exactly_fifty_reads_optional(self, api):
        """PRD 3.5: "The `selection_band` then follows directly: `INSPECT` when
        `iss_value` is 75.0 or above, `OPTIONAL` when it is 50.0 or above but below 75.0,
        and `PASS` below 50.0."

        Design: Corner/calculations/iss_exactly_fifty_selects_optional_band
        """
        scenario = _two_categories_summing_to_fifty(api)
        carrier_id = scenario["carrier"]["id"]

        scored = get_success_data(
            api.score_report(scenario["report"]["id"], fx.OFFICER)
        )
        assert_one_decimal(scored["total_time_weighted_severity"], 21.0)
        assert_one_decimal(
            fx.read_violation(api, scenario["hours_violation"]["id"])[
                "time_weighted_severity"
            ],
            15.0,
        )
        assert_one_decimal(
            fx.read_violation(api, scenario["maintenance_violation"]["id"])[
                "time_weighted_severity"
            ],
            6.0,
        )

        hours_row = fx.read_basic_score(api, carrier_id, HOS)
        assert_one_decimal(hours_row["denominator_value"], 2.0)
        assert_measure(hours_row["certified_measure"], 7.500)
        assert_one_decimal(hours_row["percentile"], 100.0)

        maintenance_row = fx.read_basic_score(api, carrier_id, VM)
        assert_one_decimal(maintenance_row["denominator_value"], 1.0)
        assert_measure(maintenance_row["certified_measure"], 6.000)
        assert_one_decimal(maintenance_row["percentile"], 80.0)

        risk = fx.read_screening_risk(api, carrier_id)
        assert_two_decimals(contribution_for(risk, HOS), 30.00)
        assert_two_decimals(contribution_for(risk, VM), 20.00)
        assert_two_decimals(contribution_for(risk, UD), 0.00)
        assert risk["oos_violation_count_24mo"] == 0
        assert_one_decimal(risk["oos_adder"], 0.0)
        assert risk["not_enough_data_categories"] == []

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["oos_violation_count_24mo"] == 0
        assert_one_decimal(carrier["iss_pre_credit_value"], 50.0)
        assert_credit_pct(carrier["data_quality_credit_pct"], 0.0)
        assert_one_decimal(carrier["iss_value"], 50.0)
        assert carrier["selection_band"] == SelectionBand.OPTIONAL
        assert carrier["open_alert_count"] == 2
        assert_one_decimal(carrier["max_percentile"], 100.0)
        assert carrier["intervention_status"] == InterventionStatus.INVESTIGATION


def _carrier_awaiting_two_inspections(api) -> Dict[str, Any]:
    """A MEDIUM carrier and one weight-5 code, with no reports filed yet."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    fx.create_threshold(
        api,
        basic_category=UD,
        carrier_segment="MEDIUM",
        effective_from="2025-01-01T00:00:00Z",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    return {"carrier": carrier, "code": code}


def _score_one_inspection(
    api, carrier_id: str, code_id: str, report_number: str, vin: str, start: str, end: str
) -> Dict[str, Any]:
    """Ingest, populate, validate and score one single-violation inspection."""
    _, rows = fx.build_scored_report(
        api,
        carrier_id,
        [{"violation_code_id": code_id, "unit_type": UnitType.VEHICLE}],
        report_number=report_number,
        vehicle_vin=vin,
        inspection_start=start,
        inspection_end=end,
    )
    return rows[0]


class TestOutOfOrderIngestion:
    def test_each_inspection_ages_from_its_own_date_whatever_the_arrival_order(self, api):
        """PRD 3.3: "computes the violation's age as the number of whole days from the
        report's `inspection_start` to that basis, discarding any fractional day. The age
        then selects an integer `time_weight`: 3 for the first 26 weeks, meaning an age of
        182 days or fewer; 2 for an age from 183 through 365 days inclusive"

        Design: Corner/calculations/out_of_order_ingestion_yields_the_same_chronological_scores
        """
        scenario = _carrier_awaiting_two_inspections(api)
        carrier_id = scenario["carrier"]["id"]
        code_id = scenario["code"]["id"]

        recent = _score_one_inspection(
            api,
            carrier_id,
            code_id,
            "OH2026070306",
            "1FUJA6CK21LK00306",
            "2026-07-01T14:00:00Z",
            "2026-07-01T15:00:00Z",
        )
        assert recent["time_weight"] == 3
        assert_one_decimal(recent["time_weighted_severity"], 15.0)
        assert_measure(fx.read_basic_score(api, carrier_id, UD)["certified_measure"], 0.500)

        backfilled = _score_one_inspection(
            api,
            carrier_id,
            code_id,
            "OH2025080101",
            "1FUJA6CK21LK00307",
            "2025-08-01T14:00:00Z",
            "2025-08-01T15:00:00Z",
        )
        assert backfilled["time_weight"] == 2
        assert_one_decimal(backfilled["time_weighted_severity"], 10.0)

        unchanged = fx.read_violation(api, recent["id"])
        assert unchanged["time_weight"] == 3
        assert_one_decimal(unchanged["time_weighted_severity"], 15.0)

        row = fx.read_basic_score(api, carrier_id, UD)
        assert_one_decimal(row["total_time_weighted_severity"], 25.0)
        assert row["relevant_inspection_count"] == 2
        assert_one_decimal(row["denominator_value"], 30.0)
        assert_measure(row["certified_measure"], 0.833)
        assert_one_decimal(row["percentile"], 60.0)
        assert row["alert_status"] == AlertStatus.MONITOR
        assert_one_decimal(fx.read_carrier(api, carrier_id)["iss_value"], 21.0)

        fx.run_scoring(api, note="Re-derive after backfilling the 2025 inspection.")

        assert fx.read_violation(api, backfilled["id"])["time_weight"] == 2
        settled = fx.read_basic_score(api, carrier_id, UD)
        assert_measure(settled["certified_measure"], 0.833)
        assert_one_decimal(settled["percentile"], 60.0)
        assert_one_decimal(fx.read_carrier(api, carrier_id)["iss_value"], 21.0)


def _violation_at_the_edge_of_its_age_band(api) -> Dict[str, Any]:
    """A violation pinned at time weight 3 with an age of exactly 182 days."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    fx.create_threshold(
        api,
        basic_category=UD,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    report, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
        report_number="OH2026013101",
        vehicle_vin="1FUJA6CK21LK00308",
        inspection_start="2026-01-31T00:00:00Z",
        inspection_end="2026-01-31T01:00:00Z",
    )
    return {"carrier": carrier, "report": report, "violation": rows[0]}


class TestDecayWaitsForTheRun:
    def test_crossing_the_age_band_only_bites_at_the_next_run(self, api):
        """PRD 3.11: "First it re-pins every violation on every report in `VALIDATED`,
        `SCORED` or `AMENDED` status, using the run's `snapshot_utc` as the aging basis,
        which is where age-decayed violations lose their `time_weight` and where stale
        code pins are refreshed."

        Design: Corner/calculations/scoring_run_repins_time_weight_after_the_clock_crosses_the_age_band
        """
        scenario = _violation_at_the_edge_of_its_age_band(api)
        carrier_id = scenario["carrier"]["id"]
        moved = fx.set_clock(api, "2026-08-02T00:00:00Z")
        assert moved["current_utc"].startswith("2026-08-02T00:00:00")

        held = fx.read_violation(api, scenario["violation"]["id"])
        assert held["time_weight"] == 3
        assert_one_decimal(held["time_weighted_severity"], 15.0)

        stale_row = fx.read_basic_score(api, carrier_id, UD)
        assert stale_row["snapshot_utc"].startswith("2026-08-01T00:00:00")
        assert stale_row["scoring_run_id"] is None
        assert_measure(stale_row["certified_measure"], 0.500)
        assert_one_decimal(stale_row["percentile"], 50.0)
        assert_one_decimal(fx.read_carrier(api, carrier_id)["iss_value"], 17.5)

        run = fx.run_scoring(api, note="Nightly decay re-pin.")
        assert run["snapshot_utc"].startswith("2026-08-02T00:00:00")
        assert run["carriers_scored"] == 1

        decayed = fx.read_violation(api, scenario["violation"]["id"])
        assert decayed["time_weight"] == 2
        assert_one_decimal(decayed["time_weighted_severity"], 10.0)

        fresh_row = fx.read_basic_score(api, carrier_id, UD)
        assert fresh_row["snapshot_utc"].startswith("2026-08-02T00:00:00")
        assert fresh_row["scoring_run_id"] == run["id"]
        assert_one_decimal(fresh_row["total_time_weighted_severity"], 10.0)
        assert_measure(fresh_row["certified_measure"], 0.333)
        assert_one_decimal(fresh_row["percentile"], 33.3)
        assert fresh_row["alert_status"] == AlertStatus.CLEAR

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["open_alert_count"] == 0
        assert_one_decimal(carrier["iss_pre_credit_value"], 11.7)
        assert_one_decimal(carrier["iss_value"], 11.7)
