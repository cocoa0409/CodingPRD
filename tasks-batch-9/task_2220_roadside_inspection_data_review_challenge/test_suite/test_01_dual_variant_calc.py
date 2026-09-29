"""Paired calculations where an all-data variant and an operative variant are both
published on the same record and must diverge.
"""

from typing import Any, Dict

from test_helpers import (
    AlertStatus,
    BasicCategory,
    ChallengeStatus,
    ChallengeType,
    CourtStatus,
    EmploymentStatus,
    EvidenceType,
    InterventionStatus,
    RecordUpdateStatus,
    SelectionBand,
    UnitType,
    ViolationStatus,
    assert_credit_pct,
    assert_measure,
    assert_one_decimal,
    assert_two_decimals,
    fixtures as fx,
    get_success_data,
)


def _challenged_report(api) -> Dict[str, Any]:
    """A MEDIUM carrier with two 15.0-severity UNSAFE_DRIVING violations on one
    SCORED report, the second of them carrying a submitted challenge."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    code = fx.create_violation_code(
        api,
        code="392.2S",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=5,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    report, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [
            {"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE},
            {"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE},
        ],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    challenge = fx.create_draft_challenge(
        api,
        carrier["id"],
        report["id"],
        challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
        narrative="Second speeding entry is not supported by the officer narrative.",
        target_violation_id=rows[1]["id"],
    )
    fx.add_evidence(
        api, carrier["id"], challenge["id"], evidence_type=EvidenceType.ELD_RECORD
    )
    fx.submit_challenge(api, carrier["id"], challenge["id"])
    return {
        "carrier": carrier,
        "report": report,
        "violations": rows,
        "challenge": challenge,
    }


class TestProvisionalVersusCertifiedMeasure:
    def test_certified_measure_subtracts_the_challenged_severity(self, api):
        """PRD 3.4: "`certified_measure` is `total_time_weighted_severity` less
        `challenged_time_weighted_severity`, divided by `denominator_value`, rounded
        half up to 3 decimal places; it is the operative variant, and it alone drives
        `percentile`, `alert_status`, intervention posture and screening risk."

        Design: Difficulty/dual_variant_calc/basic_score_provisional_vs_certified_diverge_while_challenge_open
        """
        scenario = _challenged_report(api)
        v1, v2 = scenario["violations"]

        challenge = get_success_data(
            api.get_data_challenge(scenario["challenge"]["id"], fx.REVIEWER)
        )
        assert challenge["status"] == ChallengeStatus.SUBMITTED
        assert fx.read_violation(api, v2["id"])["under_challenge"] is True
        assert fx.read_violation(api, v1["id"])["under_challenge"] is False
        assert_one_decimal(fx.read_violation(api, v2["id"])["time_weighted_severity"], 15.0)

        row = fx.read_basic_score(
            api, scenario["carrier"]["id"], BasicCategory.UNSAFE_DRIVING
        )
        assert_one_decimal(row["total_time_weighted_severity"], 30.0)
        assert_one_decimal(row["challenged_time_weighted_severity"], 15.0)
        assert row["included_violation_count"] == 2
        assert_one_decimal(row["denominator_value"], 30.0)
        assert_measure(row["provisional_measure"], 1.000)
        assert_measure(row["certified_measure"], 0.500)
        assert_one_decimal(row["percentile"], 50.0)
        assert row["alert_status"] == AlertStatus.MONITOR

    def test_posture_and_screening_risk_follow_the_operative_variant(self, api):
        """PRD 3.4: "The consequence is intentional: filing a challenge immediately
        lowers the operative measure even though the underlying report data has not
        been touched."

        Design: Difficulty/dual_variant_calc/basic_score_provisional_vs_certified_diverge_while_challenge_open
        """
        scenario = _challenged_report(api)
        carrier = fx.read_carrier(api, scenario["carrier"]["id"])

        assert carrier["open_alert_count"] == 0
        assert carrier["intervention_status"] == InterventionStatus.NONE
        assert_one_decimal(carrier["iss_pre_credit_value"], 17.5)
        assert_credit_pct(carrier["data_quality_credit_pct"], 0.0)
        assert_one_decimal(carrier["iss_value"], 17.5)
        assert carrier["selection_band"] == SelectionBand.PASS
        assert carrier["challenge_quota_used"] == 1


def _dismissed_citation(api) -> Dict[str, Any]:
    """One driver holding a 24.0 UNSAFE_DRIVING violation and a 15.0
    HOURS_OF_SERVICE violation, the latter with a DISMISSED court result recorded
    but never pushed to the record."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    driver = fx.create_driver(
        api,
        carrier["id"],
        cdl_number="OH-D-99001",
        full_name="Dana Reyes",
        employment_status=EmploymentStatus.ACTIVE,
    )
    code_ud = fx.create_violation_code(
        api,
        code="392.2R",
        description="Reckless driving",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=8,
        driver_attributable=True,
    )
    code_hos = fx.create_violation_code(
        api,
        code="395.8E",
        description="False record of duty status",
        basic_category=BasicCategory.HOURS_OF_SERVICE,
        severity_weight=5,
        driver_attributable=True,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.HOURS_OF_SERVICE,
        carrier_segment="MEDIUM",
        measure_at_p50=7.0,
        measure_at_p65=10.75,
        measure_at_p80=21.5,
    )
    report, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [
            {
                "violation_code_id": code_ud["id"],
                "unit_type": UnitType.DRIVER,
                "driver_id": driver["id"],
            },
            {
                "violation_code_id": code_hos["id"],
                "unit_type": UnitType.DRIVER,
                "driver_id": driver["id"],
            },
        ],
        driver_id=driver["id"],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    adjudication = fx.create_adjudication(
        api, rows[1]["id"], citation_number="OH-CIT-77001"
    )
    fx.record_court_result(api, adjudication["id"], CourtStatus.DISMISSED)
    return {
        "carrier": carrier,
        "driver": driver,
        "report": report,
        "violations": rows,
        "adjudication": adjudication,
    }


class TestStrictVersusAdjudicatedAttributionScore:
    def test_dismissal_moves_only_the_adjudicated_score(self, api):
        """PRD 3.9: "`strict_attribution_score` is the sum of
        `time_weighted_severity` over that included set, rounded half up to 2 decimal
        places; it ignores court outcomes entirely, so a citation that was dismissed
        but not yet pushed to the record still counts against the driver."

        Design: Difficulty/dual_variant_calc/driver_strict_vs_adjudicated_diverge_on_dismissal
        """
        scenario = _dismissed_citation(api)
        summary = get_success_data(
            api.get_attribution_summary(scenario["driver"]["id"], fx.AUDITOR)
        )

        assert summary["attributed_violation_count"] == 2
        assert_two_decimals(summary["strict_attribution_score"], 39.00)
        assert_two_decimals(summary["adjudicated_attribution_score"], 24.00)
        assert summary["coaching_required"] is True

        driver = fx.read_driver(api, scenario["driver"]["id"])
        assert driver["attributed_violation_count"] == 2
        assert_two_decimals(driver["strict_attribution_score"], 39.00)
        assert_two_decimals(driver["adjudicated_attribution_score"], 24.00)
        assert driver["coaching_required"] is True

    def test_court_result_leaves_the_violation_and_category_measures_untouched(self, api):
        """PRD 3.8: "Critically, `record_update_status` stays at `NOT_APPLIED` — the
        record dimension does not move just because the court one did, and the
        violation record itself is untouched."

        Design: Difficulty/dual_variant_calc/driver_strict_vs_adjudicated_diverge_on_dismissal
        """
        scenario = _dismissed_citation(api)
        adjudication = get_success_data(
            api.get_citation_adjudication(scenario["adjudication"]["id"], fx.OFFICER)
        )
        assert adjudication["court_status"] == CourtStatus.DISMISSED
        assert_one_decimal(adjudication["severity_factor"], 0.0)
        assert adjudication["record_update_status"] == RecordUpdateStatus.NOT_APPLIED

        hos_violation = fx.read_violation(api, scenario["violations"][1]["id"])
        assert hos_violation["status"] == ViolationStatus.ACTIVE
        assert_one_decimal(hos_violation["time_weighted_severity"], 15.0)

        carrier_id = scenario["carrier"]["id"]
        unsafe = fx.read_basic_score(api, carrier_id, BasicCategory.UNSAFE_DRIVING)
        assert_measure(unsafe["certified_measure"], 0.800)
        assert_one_decimal(unsafe["percentile"], 59.0)

        hos = fx.read_basic_score(api, carrier_id, BasicCategory.HOURS_OF_SERVICE)
        assert_one_decimal(hos["denominator_value"], 2.0)
        assert_measure(hos["certified_measure"], 7.500)
        assert_one_decimal(hos["percentile"], 52.0)
