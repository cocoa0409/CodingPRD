"""Reversals that must land back on the original numbers exactly: a withdrawn challenge,
a report moved between carriers, and a driver attribution released then re-applied.
"""

from typing import Any, Dict

from test_helpers import (
    AlertStatus,
    AmendmentType,
    ApiErrorId,
    BasicCategory,
    ChallengeStatus,
    ChallengeType,
    CoachingStatus,
    CurriculumCode,
    EmploymentStatus,
    EvidenceType,
    ReportStatus,
    UnitType,
    WaivedReason,
    assert_measure,
    assert_one_decimal,
    assert_two_decimals,
    factories as fac,
    fixtures as fx,
    get_success_data,
    make_carrier_analyst_headers,
    make_carrier_safety_manager_headers,
    validate_error,
    validate_success,
)


def _one_challenge_submitted_and_one_waiting(api) -> Dict[str, Any]:
    """A SMALL carrier at its single-challenge quota: challenge A submitted against the
    first violation, challenge B complete but still DRAFT against the second."""
    fx.set_clock(api)
    carrier = fx.create_carrier(
        api,
        dot_number="1000003",
        legal_name="Ridge Runner Trucking",
        average_power_units=10,
        annual_vmt=800000,
    )
    code = fx.create_violation_code(
        api,
        code="392.2S",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=5,
    )
    fx.create_threshold(
        api,
        basic_category=BasicCategory.UNSAFE_DRIVING,
        carrier_segment="SMALL",
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
        report_number="OH2026070118",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    first = fx.build_submitted_challenge(
        api,
        carrier["id"],
        report["id"],
        challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
        narrative="First entry unsupported.",
        target_violation_id=rows[0]["id"],
    )
    second = fx.create_draft_challenge(
        api,
        carrier["id"],
        report["id"],
        challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
        narrative="Second entry unsupported.",
        target_violation_id=rows[1]["id"],
    )
    fx.add_evidence(
        api, carrier["id"], second["id"], evidence_type=EvidenceType.ELD_RECORD
    )
    return {
        "carrier": carrier,
        "report": report,
        "violations": rows,
        "first": first,
        "second": second,
        "analyst": make_carrier_analyst_headers(carrier["id"]),
    }


class TestWithdrawRestoresQuotaAndMeasure:
    def test_withdrawing_gives_back_the_quota_and_the_original_measure(self, api):
        """PRD 3.6: "Withdrawing from `SUBMITTED` decrements the carrier's
        `challenge_quota_used` by 1 as compensation for the submit increment, and clears
        `under_challenge` on the covered violations with the full downstream cascade
        through `certified_measure`, `alert_status`, intervention posture and screening
        risk."

        Design: Difficulty/compensating_invariant/challenge_quota_and_certified_measure_restored_by_withdraw
        """
        scenario = _one_challenge_submitted_and_one_waiting(api)
        carrier_id = scenario["carrier"]["id"]

        blocked = api.submit_challenge(scenario["second"]["id"], scenario["analyst"])
        validate_error(blocked, ApiErrorId.CHALLENGE_QUOTA_EXCEEDED, 409)
        assert fx.read_carrier(api, carrier_id)["challenge_quota_used"] == 1

        get_success_data(
            api.withdraw_challenge(
                scenario["first"]["id"],
                scenario["analyst"],
                {"withdraw_note": "Re-prioritising: challenging the second entry instead."},
            )
        )

        withdrawn = get_success_data(
            api.get_data_challenge(scenario["first"]["id"], fx.REVIEWER)
        )
        assert withdrawn["status"] == ChallengeStatus.WITHDRAWN
        assert fx.read_violation(api, scenario["violations"][0]["id"])["under_challenge"] is False

        row = fx.read_basic_score(api, carrier_id, BasicCategory.UNSAFE_DRIVING)
        assert_one_decimal(row["challenged_time_weighted_severity"], 0.0)
        assert_measure(row["provisional_measure"], 2.000)
        assert_measure(row["certified_measure"], 2.000)
        assert_one_decimal(row["percentile"], 80.0)
        assert row["alert_status"] == AlertStatus.ALERT

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["challenge_quota_used"] == 0
        assert_one_decimal(carrier["iss_pre_credit_value"], 28.0)
        assert_one_decimal(carrier["iss_value"], 28.0)
        assert carrier["accepted_challenge_count_24mo"] == 0
        assert carrier["resolved_challenge_count_24mo"] == 0

    def test_the_freed_quota_is_immediately_spendable(self, api):
        """PRD 3.6: "Between scoring runs it is maintained incrementally: a submit adds 1
        to `challenge_quota_used` and a withdrawal subtracts 1, floored at 0 so the
        counter can never go negative."

        Design: Difficulty/compensating_invariant/challenge_quota_and_certified_measure_restored_by_withdraw
        """
        scenario = _one_challenge_submitted_and_one_waiting(api)
        carrier_id = scenario["carrier"]["id"]
        api.submit_challenge(scenario["second"]["id"], scenario["analyst"])
        get_success_data(
            api.withdraw_challenge(
                scenario["first"]["id"],
                scenario["analyst"],
                {"withdraw_note": "Re-prioritising: challenging the second entry instead."},
            )
        )

        validate_success(
            api.submit_challenge(scenario["second"]["id"], scenario["analyst"]), 200
        )

        second = get_success_data(
            api.get_data_challenge(scenario["second"]["id"], fx.REVIEWER)
        )
        assert second["status"] == ChallengeStatus.SUBMITTED
        assert fx.read_carrier(api, carrier_id)["challenge_quota_used"] == 1
        assert fx.read_violation(api, scenario["violations"][1]["id"])["under_challenge"] is True

        row = fx.read_basic_score(api, carrier_id, BasicCategory.UNSAFE_DRIVING)
        assert_measure(row["certified_measure"], 1.000)
        assert_one_decimal(row["percentile"], 65.0)


def _report_reattributed_by_amendment(api) -> Dict[str, Any]:
    """A 30.0-point scored report moved from the losing to the gaining carrier by a
    CARRIER_REATTRIBUTION amendment, left in AMENDED status."""
    fx.set_clock(api)
    losing = fx.create_carrier(api)
    gaining = fx.create_carrier(
        api,
        dot_number="1000002",
        legal_name="Maple Leaf Transport",
        average_power_units=25,
        annual_vmt=2000000,
    )
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
        losing["id"],
        [
            {"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE},
            {"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE},
        ],
        report_number="OH2026070119",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    amendment = get_success_data(
        api.create_amendment(
            report["id"],
            fac.create_amendment_payload(
                expected_report_version=fx.current_version(api, "report", report["id"]),
                amendment_type=AmendmentType.CARRIER_REATTRIBUTION,
                rationale="Tractor was under lease to Maple Leaf Transport on the inspection date.",
                corrected_carrier_id=gaining["id"],
            ),
            fx.OFFICER,
        )
    )
    return {
        "losing": losing,
        "gaining": gaining,
        "report": report,
        "violations": rows,
        "amendment": amendment,
    }


class TestSeverityConservedAcrossReattribution:
    def test_the_amendment_parks_the_weight_without_destroying_it(self, api):
        """PRD 3.7: "`CARRIER_REATTRIBUTION` stores the report's old
        `attributed_carrier_id` as `original_carrier_id`, writes `corrected_carrier_id`
        into `attributed_carrier_id`, sets `reattributed` to true, and rewrites
        `attributed_carrier_id` on every violation of the report."

        Design: Difficulty/compensating_invariant/time_weighted_severity_conserved_across_carrier_reattribution
        """
        scenario = _report_reattributed_by_amendment(api)

        report = fx.read_report(api, scenario["report"]["id"])
        assert report["status"] == ReportStatus.AMENDED
        assert report["attributed_carrier_id"] == scenario["gaining"]["id"]
        assert report["original_carrier_id"] == scenario["losing"]["id"]
        assert report["reattributed"] is True
        assert_one_decimal(report["total_time_weighted_severity"], 30.0)

        for row in scenario["violations"]:
            violation = fx.read_violation(api, row["id"])
            assert_one_decimal(violation["time_weighted_severity"], 15.0)
            assert violation["attributed_carrier_id"] == scenario["gaining"]["id"]

        amendment = scenario["amendment"]
        assert amendment["amendment_type"] == AmendmentType.CARRIER_REATTRIBUTION
        assert (
            amendment["report_version_after"] == amendment["report_version_before"] + 1
        )

        for carrier_id in (scenario["losing"]["id"], scenario["gaining"]["id"]):
            score = fx.read_basic_score(api, carrier_id, BasicCategory.UNSAFE_DRIVING)
            assert_one_decimal(score["total_time_weighted_severity"], 0.0)
            assert score["relevant_inspection_count"] == 0
            assert score["alert_status"] == AlertStatus.NOT_ENOUGH_DATA

    def test_rescoring_moves_exactly_thirty_points_and_no_more(self, api):
        """PRD 3.7: "Bringing the corrected report back into the measures requires a
        fresh scoring pass, which re-pins the weights so the correction actually takes
        effect."

        Design: Difficulty/compensating_invariant/time_weighted_severity_conserved_across_carrier_reattribution
        """
        scenario = _report_reattributed_by_amendment(api)
        fx.score_report(api, scenario["report"]["id"])
        assert fx.read_report(api, scenario["report"]["id"])["status"] == ReportStatus.SCORED

        gained = fx.read_basic_score(
            api, scenario["gaining"]["id"], BasicCategory.UNSAFE_DRIVING
        )
        assert_one_decimal(gained["total_time_weighted_severity"], 30.0)
        assert gained["relevant_inspection_count"] == 1
        assert_one_decimal(gained["denominator_value"], 37.5)
        assert_measure(gained["certified_measure"], 0.800)
        assert_one_decimal(gained["percentile"], 59.0)
        assert gained["alert_status"] == AlertStatus.MONITOR

        emptied = fx.read_basic_score(
            api, scenario["losing"]["id"], BasicCategory.UNSAFE_DRIVING
        )
        assert_one_decimal(emptied["total_time_weighted_severity"], 0.0)
        assert_one_decimal(
            emptied["total_time_weighted_severity"]
            + gained["total_time_weighted_severity"],
            30.0,
        )

        loser = fx.read_carrier(api, scenario["losing"]["id"])
        assert loser["open_alert_count"] == 0
        assert_one_decimal(loser["iss_value"], 0.0)
        assert_one_decimal(
            fx.read_carrier(api, scenario["gaining"]["id"])["iss_value"], 20.7
        )


def _attributed_violation_with_coaching(api) -> Dict[str, Any]:
    """Two scored weight-5 violations on one report — the first attributed to the driver,
    the second left on the vehicle — with one ASSIGNED coaching session on the first."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    driver = fx.create_driver(
        api,
        carrier["id"],
        cdl_number="OH-D-99001",
        full_name="Dana Reyes",
        employment_status=EmploymentStatus.ACTIVE,
    )
    code = fx.create_violation_code(
        api,
        code="392.2S",
        basic_category=BasicCategory.UNSAFE_DRIVING,
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
    _, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [
            {
                "violation_code_id": code["id"],
                "unit_type": UnitType.DRIVER,
                "driver_id": driver["id"],
            },
            {"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE},
        ],
        report_number="OH2026070120",
        driver_id=driver["id"],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    coaching = fx.create_coaching_assignment(
        api,
        carrier["id"],
        driver["id"],
        rows[0]["id"],
        curriculum_code=CurriculumCode.UNSAFE_DRIVING_101,
        session_start="2026-08-05T14:00:00Z",
        session_end="2026-08-05T16:00:00Z",
    )
    return {
        "carrier": carrier,
        "driver": driver,
        "violations": rows,
        "coaching": coaching,
        "manager": make_carrier_safety_manager_headers(carrier["id"]),
    }


class TestAttributionReleaseAndReapply:
    def test_releasing_the_attribution_empties_the_driver_and_waives_the_session(self, api):
        """PRD 3.5: "Clearing an attribution is the compensating action: it empties the
        violation's `driver_id`, increments the violation's `version` by 1, recomputes the
        released driver's aggregates, waives that driver's `ASSIGNED` and `IN_PROGRESS`
        assignments for this violation with `waived_reason` `ATTRIBUTION_CLEARED`, and
        recomputes the carrier's `unattributed_violation_count` so that the identity
        between attributed and unattributed counts continues to hold."

        Design: Difficulty/compensating_invariant/driver_attribution_counts_conserved_on_attribution_release
        """
        scenario = _attributed_violation_with_coaching(api)
        carrier_id = scenario["carrier"]["id"]
        get_success_data(
            api.clear_driver_attribution(
                scenario["violations"][0]["id"], scenario["manager"]
            )
        )

        assert fx.read_violation(api, scenario["violations"][0]["id"])["driver_id"] is None

        driver = fx.read_driver(api, scenario["driver"]["id"])
        assert driver["attributed_violation_count"] == 0
        assert_two_decimals(driver["strict_attribution_score"], 0.00)
        assert_two_decimals(driver["adjudicated_attribution_score"], 0.00)
        assert driver["coaching_required"] is False
        assert driver["open_coaching_count"] == 0

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["scored_violation_count"] == 2
        assert carrier["unattributed_violation_count"] == 2
        assert carrier["open_coaching_count"] == 0

        coaching = get_success_data(
            api.get_coaching_assignment(scenario["coaching"]["id"], fx.AUDITOR)
        )
        assert coaching["status"] == CoachingStatus.WAIVED
        assert coaching["waived_reason"] == WaivedReason.ATTRIBUTION_CLEARED

        row = fx.read_basic_score(api, carrier_id, BasicCategory.UNSAFE_DRIVING)
        assert_one_decimal(row["total_time_weighted_severity"], 30.0)
        assert_measure(row["certified_measure"], 1.000)
        assert_one_decimal(row["percentile"], 65.0)

    def test_reapplying_restores_every_count_but_not_the_waived_session(self, api):
        """PRD 3.5: "Setting an attribution increments the violation's `version` by 1,
        recomputes the aggregates and `coaching_required` of both the previous driver and
        the new one, and recomputes the carrier's `unattributed_violation_count` and
        `scored_violation_count`."

        Design: Difficulty/compensating_invariant/driver_attribution_counts_conserved_on_attribution_release
        """
        scenario = _attributed_violation_with_coaching(api)
        carrier_id = scenario["carrier"]["id"]
        driver_id = scenario["driver"]["id"]
        get_success_data(
            api.clear_driver_attribution(
                scenario["violations"][0]["id"], scenario["manager"]
            )
        )
        fx.attribute_driver(api, carrier_id, scenario["violations"][0]["id"], driver_id)

        assert fx.read_violation(api, scenario["violations"][0]["id"])["driver_id"] == driver_id

        driver = fx.read_driver(api, driver_id)
        assert driver["attributed_violation_count"] == 1
        assert_two_decimals(driver["strict_attribution_score"], 15.00)
        assert_two_decimals(driver["adjudicated_attribution_score"], 15.00)
        assert driver["coaching_required"] is True

        summary = get_success_data(api.get_attribution_summary(driver_id, fx.AUDITOR))
        assert summary["attributed_violation_count"] == 1
        assert_two_decimals(summary["strict_attribution_score"], 15.00)

        carrier = fx.read_carrier(api, carrier_id)
        assert carrier["scored_violation_count"] == 2
        assert carrier["unattributed_violation_count"] == 1
        assert carrier["open_coaching_count"] == 0

        coaching = get_success_data(
            api.get_coaching_assignment(scenario["coaching"]["id"], fx.AUDITOR)
        )
        assert coaching["status"] == CoachingStatus.WAIVED

        row = fx.read_basic_score(api, carrier_id, BasicCategory.UNSAFE_DRIVING)
        assert_measure(row["certified_measure"], 1.000)
