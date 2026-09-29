"""Nothing in the scoring chain waits for a batch: one on-demand pass writes all four
category rows, the carrier roll-up and the screening projection, and the reads issued
immediately afterwards agree with the pass's own response.
"""

from typing import Any, Dict

from test_helpers import (
    AlertStatus,
    BasicCategory,
    CarrierSegment,
    InterventionStatus,
    ReportStatus,
    SelectionBand,
    UnitType,
    assert_measure,
    assert_one_decimal,
    assert_two_decimals,
    contribution_for,
    find_score,
    fixtures as fx,
    validate_success,
)

UD = BasicCategory.UNSAFE_DRIVING
HOS = BasicCategory.HOURS_OF_SERVICE
VM = BasicCategory.VEHICLE_MAINTENANCE
DF = BasicCategory.DRIVER_FITNESS


def _validated_report_awaiting_its_first_score(api) -> Dict[str, Any]:
    """One MEDIUM carrier, one UNSAFE_DRIVING violation, one threshold row, and a report
    that has reached VALIDATED but has never been scored -- so no score row exists yet."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    threshold = fx.create_threshold(
        api, basic_category=UD, carrier_segment=CarrierSegment.MEDIUM
    )
    report, rows = fx.build_validated_report(
        api,
        carrier["id"],
        [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    return {
        "carrier": carrier,
        "code": code,
        "threshold": threshold,
        "report": report,
        "violation": rows[0],
    }


class TestOnDemandScoringIsImmediatelyVisible:
    def test_one_score_call_settles_rows_rollup_and_screening_risk(self, api):
        """PRD 3.4: "Each row records the `snapshot_utc` that is the aging basis of its
        current numbers, the `scoring_run_id` of the run that last wrote it — empty when
        the last write came from an on-demand pass rather than from a run — and the
        `threshold_id` of the reference row used for its percentile mapping."

        Design: Corner/consistency_model/score_response_and_immediate_reads_agree_without_a_scoring_run
        """
        scenario = _validated_report_awaiting_its_first_score(api)
        carrier_id = scenario["carrier"]["id"]

        scored = validate_success(
            api.score_report(scenario["report"]["id"], fx.OFFICER), 200
        )
        assert scored["status"] == ReportStatus.SCORED
        # PRD 3.1/3.2: the carrier was freshly registered when this report was ingested,
        # so its `iss_value` was 0.0 and its `selection_band` was PASS, and ingestion
        # snapshots exactly those two values onto the report.  Scoring the report does
        # not rewrite the selection-time snapshot.
        assert_one_decimal(scored["iss_value_at_selection"], 0.0)
        assert scored["selection_band_at_selection"] == SelectionBand.PASS

        row = fx.read_basic_score(api, carrier_id, UD)
        assert_one_decimal(row["total_time_weighted_severity"], 15.0)
        assert_one_decimal(row["challenged_time_weighted_severity"], 0.0)
        assert row["included_violation_count"] == 1
        assert row["relevant_inspection_count"] == 1
        assert_one_decimal(row["denominator_value"], 30.0)
        assert_measure(row["provisional_measure"], 0.500)
        assert_measure(row["certified_measure"], 0.500)
        assert_one_decimal(row["percentile"], 50.0)
        assert row["alert_status"] == AlertStatus.MONITOR
        assert row["threshold_id"] == scenario["threshold"]["id"]
        assert row["scoring_run_id"] is None
        assert row["snapshot_utc"].startswith("2026-08-01T00:00:00")

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["open_alert_count"] == 0
        assert_one_decimal(carrier["max_percentile"], 50.0)
        assert carrier["intervention_status"] == InterventionStatus.NONE
        assert_one_decimal(carrier["iss_pre_credit_value"], 17.5)
        assert_one_decimal(carrier["iss_value"], 17.5)
        assert carrier["selection_band"] == SelectionBand.PASS

        risk = validate_success(api.get_screening_risk(carrier_id, fx.AUDITOR), 200)
        assert_one_decimal(risk["iss_pre_credit_value"], 17.5)
        assert_one_decimal(risk["data_quality_credit_pct"], 0.0)
        assert_one_decimal(risk["iss_value"], 17.5)
        assert risk["selection_band"] == SelectionBand.PASS
        assert_one_decimal(risk["oos_adder"], 0.0)
        assert risk["oos_violation_count_24mo"] == 0
        assert_two_decimals(contribution_for(risk, UD), 17.50)
        for quiet in (HOS, VM, DF):
            assert_two_decimals(contribution_for(risk, quiet), 0.00)
        assert risk["not_enough_data_categories"] == []

        all_rows = fx.read_basic_scores(api, carrier_id)
        assert len(all_rows) == 4
        assert all(candidate["scoring_run_id"] is None for candidate in all_rows)
        assert_one_decimal(find_score(all_rows, UD)["percentile"], 50.0)
        for quiet in (HOS, VM, DF):
            other = find_score(all_rows, quiet)
            assert other["included_violation_count"] == 0
            assert_one_decimal(other["total_time_weighted_severity"], 0.0)
            assert other["relevant_inspection_count"] == 1
            assert_measure(other["certified_measure"], 0.000)
            assert_one_decimal(other["percentile"], 0.0)
            assert other["alert_status"] == AlertStatus.CLEAR

        assert_one_decimal(
            fx.read_violation(api, scenario["violation"]["id"])["time_weighted_severity"],
            15.0,
        )
