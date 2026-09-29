"""One write, several hops: each scenario follows a single mutation through the score
rows, the posture, the screening band and, in two cases, into a second entity type.
"""

from typing import Any, Dict

from test_helpers import (
    AlertStatus,
    BasicCategory,
    ChallengeStatus,
    ChallengeType,
    CoachingStatus,
    CourtStatus,
    CurriculumCode,
    EmploymentStatus,
    EvidenceType,
    InterventionStatus,
    RecordUpdateStatus,
    RemovalReason,
    ResolutionDisposition,
    ReviewAction,
    STATE_OFFICER_WA_ID,
    SelectionBand,
    UnitType,
    ViolationStatus,
    WaivedReason,
    assert_credit_pct,
    assert_measure,
    assert_one_decimal,
    assert_two_decimals,
    contribution_for,
    fixtures as fx,
    get_success_data,
    make_state_officer_headers,
)


def _four_categories_with_a_draft_challenge(api) -> Dict[str, Any]:
    """A SMALL carrier alerting in two categories, holding a DRAFT
    VIOLATION_NOT_SUPPORTED challenge on its HOURS_OF_SERVICE violation."""
    officer = make_state_officer_headers(STATE_OFFICER_WA_ID)
    fx.set_clock(api)
    carrier = fx.create_carrier(
        api,
        legal_name="Cascade Hauling Inc",
        average_power_units=10,
        annual_vmt=1200000,
    )
    driver = fx.create_driver(
        api, carrier["id"], cdl_number="WA-D-40001", full_name="Kai Osborne"
    )
    code_ud = fx.create_violation_code(
        api,
        code="392.2S",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=5,
        driver_attributable=True,
    )
    code_hos = fx.create_violation_code(
        api,
        code="395.3A1",
        description="Driving beyond 11 hour limit",
        basic_category=BasicCategory.HOURS_OF_SERVICE,
        severity_weight=5,
        driver_attributable=True,
    )
    code_vm = fx.create_violation_code(
        api,
        code="393.9TS",
        description="Inoperative tail lamp",
        basic_category=BasicCategory.VEHICLE_MAINTENANCE,
        severity_weight=2,
    )
    code_df = fx.create_violation_code(
        api,
        code="391.11B5",
        description="Driver lacking valid medical certificate",
        basic_category=BasicCategory.DRIVER_FITNESS,
        severity_weight=4,
        driver_attributable=True,
    )
    fx.create_thresholds_for_all_categories(
        api, carrier_segment="SMALL", measures=(1.0, 2.0, 4.0)
    )
    report_a, rows_a = fx.build_scored_report(
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
        officer,
        report_number="WA20260701A",
        inspection_state="WA",
        driver_id=driver["id"],
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    fx.build_scored_report(
        api,
        carrier["id"],
        [
            {"violation_code_id": code_vm["id"], "unit_type": UnitType.VEHICLE},
            {
                "violation_code_id": code_df["id"],
                "unit_type": UnitType.DRIVER,
                "driver_id": driver["id"],
            },
        ],
        officer,
        report_number="WA20260701B",
        inspection_state="WA",
        inspection_level=1,
        selection_source="WEIGH_STATION",
        driver_id=driver["id"],
        inspection_start="2026-07-01T18:00:00Z",
        inspection_end="2026-07-01T19:00:00Z",
    )
    challenge = fx.create_draft_challenge(
        api,
        carrier["id"],
        report_a["id"],
        challenge_type=ChallengeType.VIOLATION_NOT_SUPPORTED,
        narrative="The ELD shows the driver was within the 11-hour limit.",
        target_violation_id=rows_a[1]["id"],
    )
    fx.add_evidence(
        api, carrier["id"], challenge["id"], evidence_type=EvidenceType.ELD_RECORD
    )
    return {
        "carrier": carrier,
        "driver": driver,
        "report": report_a,
        "unsafe_violation": rows_a[0],
        "hos_violation": rows_a[1],
        "challenge": challenge,
    }


class TestChallengeSubmitCascade:
    def test_submit_reaches_the_score_row_of_only_its_own_category(self, api):
        """PRD 2.10: "The chain runs: pinned violation weights, then the owning
        report's rolled-up totals, then the affected carrier's behaviour-category score
        rows, then that carrier's intervention posture, then that carrier's screening
        risk and selection band."

        Design: Difficulty/transitive_cascade/challenge_submit_cascades_to_selection_band
        """
        scenario = _four_categories_with_a_draft_challenge(api)
        carrier_id = scenario["carrier"]["id"]
        fx.submit_challenge(api, carrier_id, scenario["challenge"]["id"])

        assert fx.read_violation(api, scenario["hos_violation"]["id"])["under_challenge"] is True
        assert (
            fx.read_violation(api, scenario["unsafe_violation"]["id"])["under_challenge"]
            is False
        )

        hos = fx.read_basic_score(api, carrier_id, BasicCategory.HOURS_OF_SERVICE)
        assert_one_decimal(hos["total_time_weighted_severity"], 15.0)
        assert_one_decimal(hos["challenged_time_weighted_severity"], 15.0)
        assert_measure(hos["provisional_measure"], 3.750)
        assert_measure(hos["certified_measure"], 0.000)
        assert_one_decimal(hos["percentile"], 0.0)
        assert hos["alert_status"] == AlertStatus.CLEAR

        vehicle = fx.read_basic_score(api, carrier_id, BasicCategory.VEHICLE_MAINTENANCE)
        assert_one_decimal(vehicle["percentile"], 72.5)
        assert vehicle["alert_status"] == AlertStatus.ALERT

    def test_submit_moves_the_posture_and_the_selection_band(self, api):
        """PRD 3.6: "Because `under_challenge` changed, the affected score rows'
        `challenged_time_weighted_severity` and `certified_measure` are recomputed, which
        moves `percentile` and `alert_status`, which moves the carrier's
        `open_alert_count`, `max_percentile` and `intervention_status`, which moves the
        carrier's screening risk and `selection_band`."

        Design: Difficulty/transitive_cascade/challenge_submit_cascades_to_selection_band
        """
        scenario = _four_categories_with_a_draft_challenge(api)
        carrier_id = scenario["carrier"]["id"]

        before = fx.read_carrier(api, carrier_id)
        assert before["open_alert_count"] == 2
        assert before["intervention_status"] == InterventionStatus.INVESTIGATION
        assert_one_decimal(before["iss_value"], 59.5)
        assert before["selection_band"] == SelectionBand.OPTIONAL

        fx.submit_challenge(api, carrier_id, scenario["challenge"]["id"])

        after = fx.read_carrier(api, carrier_id)
        assert after["open_alert_count"] == 1
        assert_one_decimal(after["max_percentile"], 72.5)
        assert after["intervention_status"] == InterventionStatus.WARNING_LETTER
        assert_one_decimal(after["iss_pre_credit_value"], 36.1)
        assert_one_decimal(after["iss_value"], 36.1)
        assert after["selection_band"] == SelectionBand.PASS
        assert after["challenge_quota_used"] == 1

        risk = fx.read_screening_risk(api, carrier_id)
        assert_two_decimals(contribution_for(risk, BasicCategory.UNSAFE_DRIVING), 14.60)
        assert_two_decimals(contribution_for(risk, BasicCategory.HOURS_OF_SERVICE), 0.00)
        assert_two_decimals(
            contribution_for(risk, BasicCategory.VEHICLE_MAINTENANCE), 18.13
        )
        assert_two_decimals(contribution_for(risk, BasicCategory.DRIVER_FITNESS), 3.34)


def _wrong_carrier_challenge_under_review(api) -> Dict[str, Any]:
    """A scored report attributed to the losing carrier, with an UNDER_REVIEW
    WRONG_CARRIER challenge naming the gaining carrier."""
    fx.set_clock(api)
    losing = fx.create_carrier(api)
    gaining = fx.create_carrier(
        api,
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
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    challenge = fx.build_challenge_under_review(
        api,
        losing["id"],
        report["id"],
        evidence_type=EvidenceType.BILL_OF_LADING,
        challenge_type=ChallengeType.WRONG_CARRIER,
        narrative="The tractor was under lease to Maple Leaf Transport on that date.",
        asserted_correct_carrier_id=gaining["id"],
    )
    return {
        "losing": losing,
        "gaining": gaining,
        "report": report,
        "violations": rows,
        "challenge": challenge,
    }


class TestReattributionCascadeAcrossTwoCarriers:
    def test_acceptance_moves_the_report_and_every_violation(self, api):
        """PRD 3.6: "It rewrites the report's `attributed_carrier_id` to the
        `asserted_correct_carrier_id`, stores the previous value as
        `original_carrier_id`, and sets `reattributed` to true."

        Design: Difficulty/transitive_cascade/wrong_carrier_acceptance_cascades_across_two_carriers
        """
        scenario = _wrong_carrier_challenge_under_review(api)
        fx.review_challenge(
            api,
            scenario["challenge"]["id"],
            ReviewAction.RESOLVE_ACCEPT,
        )

        challenge = get_success_data(
            api.get_data_challenge(scenario["challenge"]["id"], fx.REVIEWER)
        )
        assert challenge["status"] == ChallengeStatus.RESOLVED_ACCEPTED
        assert challenge["resolution_disposition"] == ResolutionDisposition.REATTRIBUTED

        report = fx.read_report(api, scenario["report"]["id"])
        assert report["attributed_carrier_id"] == scenario["gaining"]["id"]
        assert report["original_carrier_id"] == scenario["losing"]["id"]
        assert report["reattributed"] is True

        for row in scenario["violations"]:
            violation = fx.read_violation(api, row["id"])
            assert violation["attributed_carrier_id"] == scenario["gaining"]["id"]
            assert violation["under_challenge"] is False

    def test_the_full_chain_runs_once_for_each_carrier(self, api):
        """PRD 2.10: "When a single request touches two carriers — the only case being a
        reattribution, which moves a report from a losing carrier to a gaining one — the
        full chain runs independently for each carrier."

        Design: Difficulty/transitive_cascade/wrong_carrier_acceptance_cascades_across_two_carriers
        """
        scenario = _wrong_carrier_challenge_under_review(api)
        fx.review_challenge(
            api,
            scenario["challenge"]["id"],
            ReviewAction.RESOLVE_ACCEPT,
        )

        emptied = fx.read_basic_score(
            api, scenario["losing"]["id"], BasicCategory.UNSAFE_DRIVING
        )
        assert_one_decimal(emptied["total_time_weighted_severity"], 0.0)
        assert emptied["relevant_inspection_count"] == 0
        assert_measure(emptied["certified_measure"], 0.000)
        assert emptied["percentile"] is None
        assert emptied["alert_status"] == AlertStatus.NOT_ENOUGH_DATA

        loser = fx.read_carrier(api, scenario["losing"]["id"])
        assert loser["open_alert_count"] == 0
        assert loser["max_percentile"] is None
        assert loser["intervention_status"] == InterventionStatus.NONE
        assert loser["accepted_challenge_count_24mo"] == 1
        assert loser["resolved_challenge_count_24mo"] == 1
        assert_one_decimal(loser["iss_pre_credit_value"], 0.0)
        assert_credit_pct(loser["data_quality_credit_pct"], 0.0200)
        assert_one_decimal(loser["iss_value"], 0.0)
        assert loser["selection_band"] == SelectionBand.PASS

        gained = fx.read_basic_score(
            api, scenario["gaining"]["id"], BasicCategory.UNSAFE_DRIVING
        )
        assert_one_decimal(gained["total_time_weighted_severity"], 30.0)
        assert gained["relevant_inspection_count"] == 1
        assert_one_decimal(gained["denominator_value"], 37.5)
        assert_measure(gained["certified_measure"], 0.800)
        assert_one_decimal(gained["percentile"], 59.0)
        assert gained["alert_status"] == AlertStatus.MONITOR

        winner = fx.read_carrier(api, scenario["gaining"]["id"])
        assert_one_decimal(winner["iss_pre_credit_value"], 20.7)
        assert_credit_pct(winner["data_quality_credit_pct"], 0.0)
        assert_one_decimal(winner["iss_value"], 20.7)
        assert winner["selection_band"] == SelectionBand.PASS


def _dismissed_citation_with_open_coaching(api) -> Dict[str, Any]:
    """A driver carrying one 24.0 violation, an ASSIGNED coaching session for it, and a
    DISMISSED court result waiting to be pushed to the record."""
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
        code="392.2R",
        description="Reckless driving",
        basic_category=BasicCategory.UNSAFE_DRIVING,
        severity_weight=8,
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
    report, rows = fx.build_scored_report(
        api,
        carrier["id"],
        [
            {
                "violation_code_id": code["id"],
                "unit_type": UnitType.DRIVER,
                "driver_id": driver["id"],
            }
        ],
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
        session_end="2026-08-10T16:00:00Z",
    )
    adjudication = fx.create_adjudication(
        api,
        rows[0]["id"],
        citation_number="OH-CIT-77003",
        court_date="2026-07-24T00:00:00Z",
    )
    fx.record_court_result(
        api,
        adjudication["id"],
        CourtStatus.DISMISSED,
        court_note="Citation dismissed at arraignment.",
    )
    return {
        "carrier": carrier,
        "driver": driver,
        "report": report,
        "violation": rows[0],
        "coaching": coaching,
        "adjudication": adjudication,
    }


class TestApplyToRecordCascadeIntoCoaching:
    def test_push_removes_the_violation_and_empties_the_category(self, api):
        """PRD 3.8: "For `DISMISSED` or `NOT_GUILTY`, `record_update_status` moves from
        `NOT_APPLIED` to `APPLIED` and the violation's `status` becomes `REMOVED` with a
        `removal_reason` of `ADJUDICATION_DISMISSED` and a `time_weighted_severity`
        forced to 0.0."

        Design: Difficulty/transitive_cascade/adjudication_apply_cascades_to_coaching_waiver
        """
        scenario = _dismissed_citation_with_open_coaching(api)
        fx.apply_adjudication(api, scenario["adjudication"]["id"])

        adjudication = get_success_data(
            api.get_citation_adjudication(scenario["adjudication"]["id"], fx.OFFICER)
        )
        assert adjudication["record_update_status"] == RecordUpdateStatus.APPLIED

        violation = fx.read_violation(api, scenario["violation"]["id"])
        assert violation["status"] == ViolationStatus.REMOVED
        assert violation["removal_reason"] == RemovalReason.ADJUDICATION_DISMISSED
        assert_one_decimal(violation["time_weighted_severity"], 0.0)

        report = fx.read_report(api, scenario["report"]["id"])
        assert report["active_violation_count"] == 0

        row = fx.read_basic_score(
            api, scenario["carrier"]["id"], BasicCategory.UNSAFE_DRIVING
        )
        assert_one_decimal(row["total_time_weighted_severity"], 0.0)
        assert row["included_violation_count"] == 0
        assert row["relevant_inspection_count"] == 1
        assert_measure(row["certified_measure"], 0.000)
        assert_one_decimal(row["percentile"], 0.0)
        assert row["alert_status"] == AlertStatus.CLEAR

        carrier = fx.read_carrier(api, scenario["carrier"]["id"])
        assert_one_decimal(carrier["iss_value"], 0.0)
        assert carrier["selection_band"] == SelectionBand.PASS

    def test_push_waives_the_now_pointless_coaching_session(self, api):
        """PRD 3.8: "Because the violation has either left the driver's attributed set
        or changed weight within it, the driver's aggregates recompute, and every
        `ASSIGNED` or `IN_PROGRESS` coaching assignment whose `violation_id` points at a
        now-`REMOVED` violation moves to `WAIVED` with a `waived_reason` of
        `VIOLATION_REMOVED`, decrementing the carrier's `open_coaching_count`."

        Design: Difficulty/transitive_cascade/adjudication_apply_cascades_to_coaching_waiver
        """
        scenario = _dismissed_citation_with_open_coaching(api)
        fx.apply_adjudication(api, scenario["adjudication"]["id"])

        driver = fx.read_driver(api, scenario["driver"]["id"])
        assert driver["attributed_violation_count"] == 0
        assert_two_decimals(driver["strict_attribution_score"], 0.00)
        assert_two_decimals(driver["adjudicated_attribution_score"], 0.00)
        assert driver["coaching_required"] is False
        assert driver["open_coaching_count"] == 0

        coaching = get_success_data(
            api.get_coaching_assignment(scenario["coaching"]["id"], fx.AUDITOR)
        )
        assert coaching["status"] == CoachingStatus.WAIVED
        assert coaching["waived_reason"] == WaivedReason.VIOLATION_REMOVED
        assert coaching["due_at"].startswith("2026-08-24T16:00:00")

        carrier = fx.read_carrier(api, scenario["carrier"]["id"])
        assert carrier["open_coaching_count"] == 0
